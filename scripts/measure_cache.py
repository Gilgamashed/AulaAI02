r"""Medição de desempenho da API **antes e depois** do cache (Aula 8).

A spec pede a comparação de latência média, p95 e RPS antes da introdução do
cache e depois dela. O script mede por HTTP, de ponta a ponta (Django +
DRF + serializer + renderer + PostgreSQL), usando **somente a biblioteca
padrão** — nenhuma dependência nova no projeto (dentro do container da API
ele roda com o Python da própria imagem).

Como obter os dois cenários (o servidor é quem decide):

```powershell
# 1) Baseline: cache DESLIGADO (bypass total — equivale ao código pré-Aula 8)
$env:CACHE_ENABLED = "false"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --label "sem cache"

# 2) Com cache: cache LIGADO
$env:CACHE_ENABLED = "true"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --label "com cache"
```

Opcionalmente, para a medição ser significativa, gere volume de dados
(alguns endpoints só fazem sentido com várias páginas de catálogo):

```powershell
docker compose run --rm api python scripts/measure_cache.py --seed 500 `
  --base-url http://api:8000 --label "com cache"
```

Notas metodológicas (importam para não ler número errado):

* **Carga sequencial de 1 cliente.** O RPS medido é o que um cliente
  sequencial extrai do serviço; serve para comparar os dois cenários sob as
  mesmas condições, não como limite de capacidade.
* **Throttling.** O padrão da Aula 7 corta requisições (20/min anônimo). Para
  a medição, suba `DRF_ANON_RATE`/`DRF_USER_RATE` (ver README); o script
  conta e exibe qualquer resposta não-200, para que um 429 nunca passe
  despercebido como "resposta rápida".
* **A coluna `1ª fria`.** É a PRIMEIRA requisição do endpoint, feita antes do
  aquecimento. Com o cache ligado e o Redis limpo, é ela que paga o MISS
  (banco + escrita) — o preço de entrada do cache. Sem cache, é só a 1ª
  requisição, normalmente a mais lenta da série (pool de conexões ainda frio).
  Rode com o Redis limpo (`redis-cli -n 1 FLUSHDB`) para que ela seja um MISS
  de verdade; com chaves já aquecidas, ela será um HIT e a coluna perde o
  sentido.
* **Aquecimento.** As requisições seguintes (`--warmup`, padrão 3) são
  descartadas para que TCP, DNS e o pool do PostgreSQL não entrem na amostra.
* **`média ss` / `p95 ss`.** Regime permanente: com o cache ligado, quase só
  HITs. É aí que o ganho aparece.
"""

import argparse
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Endpoints instrumentados com cache-aside na Aula 8. `{item}` é substituído
# pelo id informado em --item-id.
ENDPOINTS = (
    ("listagem de itens", "/api/v1/items/"),
    ("detalhe de item", "/api/v1/items/{item}/"),
    ("detalhes (consulta pesada)", "/api/v1/items/{item}/detalhes/"),
    ("listagem de categorias", "/api/v1/categories/"),
)

METRICS_PATH = "/api/v1/cache/metrics/"


# =====================================================================
# Cliente HTTP mínimo (stdlib)
# =====================================================================
def _headers(token: str | None) -> dict[str, str]:
    """Cabeçalhos comuns: JSON puro (nada de HTML da browsable API) + JWT."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_once(url: str, token: str | None, timeout: float = 10.0):
    """Executa um GET e devolve `(status, latência_ms, tamanho_bytes)`.

    `Accept: application/json` força o renderer JSON (evita o HTML da
    browsable API, que mediria o template em vez do cache). Respostas 4xx/5xx
    também são medidas: escondê-las falsearia a média.
    """
    requisicao = urllib.request.Request(url, headers=_headers(token), method="GET")
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            corpo = resposta.read()
            status = resposta.status
    except urllib.error.HTTPError as erro:
        # 4xx/5xx também têm latência relevante para a medição.
        corpo = erro.read()
        status = erro.code
    latencia_ms = (time.perf_counter() - inicio) * 1000
    return status, latencia_ms, len(corpo)


def percentil(amostras: list[float], p: float) -> float:
    """Percentil pelo método do rank mais próximo (p95 = 95% abaixo dele).

    Não usamos `statistics.quantiles` porque ela interpola e exige n>=2;
    com poucas amostras o rank mais próximo é mais honesto.
    """
    if not amostras:
        return 0.0
    ordenadas = sorted(amostras)
    posicao = max(1, math.ceil(p / 100 * len(ordenadas)))
    return ordenadas[posicao - 1]


def medir_endpoint(url: str, requisicoes: int, token: str | None, aquecimento: int):
    """Roda uma requisição fria, o warmup (descartado) e as medições."""
    # Requisição FRIA: a primeira de todas, antes do aquecimento. Com o cache
    # ligado e o Redis limpo, é a única que paga MISS (banco + escrita no
    # Redis) — o preço de entrada do cache. Sem cache, é só a 1ª requisição
    # (normalmente a mais lenta da série, por_pool de conexões ainda frio).
    _, frio_ms, _ = request_once(url, token)

    # Aquecimento: a conexão TCP, a resolução DNS e o pool de conexões do
    # PostgreSQL não devem entrar na amostra de regime permanente.
    for _ in range(aquecimento):
        request_once(url, token)

    latencias: list[float] = []
    nao_200: dict[int, int] = {}
    bytes_total = 0
    inicio_total = time.perf_counter()
    for _ in range(requisicoes):
        status, latencia_ms, tamanho = request_once(url, token)
        latencias.append(latencia_ms)
        bytes_total += tamanho
        if status != 200:
            nao_200[status] = nao_200.get(status, 0) + 1
    duracao_s = time.perf_counter() - inicio_total

    # "ss" (steady state) = regime permanente, sem a 1ª requisição da amostra.
    permanentes = latencias[1:] if len(latencias) > 1 else latencias
    return {
        "n": len(latencias),
        "fria_ms": round(frio_ms, 2),
        "media_ms": round(statistics.fmean(latencias), 2) if latencias else 0.0,
        "p50_ms": round(percentil(latencias, 50), 2),
        "p95_ms": round(percentil(latencias, 95), 2),
        "max_ms": round(max(latencias), 2) if latencias else 0.0,
        "media_ss_ms": round(statistics.fmean(permanentes), 2) if permanentes else 0.0,
        "p95_ss_ms": round(percentil(permanentes, 95), 2) if permanentes else 0.0,
        "rps": round(len(latencias) / duracao_s, 1) if duracao_s else 0.0,
        "bytes": bytes_total,
        "nao_200": nao_200,
    }


def ler_metricas(base_url: str, token: str | None) -> dict | None:
    """Lê `/api/v1/cache/metrics/` (exige token admin) ou devolve None."""
    if not token:
        return None
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                base_url + METRICS_PATH,
                headers=_headers(token),
            ),
            timeout=10.0,
        ) as resposta:
            return json.loads(resposta.read())
    except (urllib.error.HTTPError, urllib.error.URLError):
        # 401/403 (token sem papel admin) ou API fora: as métricas são
        # opcionais para a medição, então não derrubamos o script.
        return None


def descobrir_item_id(base_url: str, token: str | None) -> str:
    """Descobre um id de item que existe, para os endpoints de detalhe.

    Medir `/items/{id}/` com um id inexistente daria 404 (o `404` do DRF é
    mais rápido que o `200` com cache e falsearia a comparação), então o
    script lê a primeira página da listagem e usa o primeiro id. Se a
    listagem falhar, cai no id 1 — e o alerta de respostas não-200 denuncia.
    """
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                base_url + "/api/v1/items/",
                headers=_headers(token),
            ),
            timeout=10.0,
        ) as resposta:
            pagina = json.loads(resposta.read())
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError):
        return "1"
    for item in pagina.get("results", []):
        if "id" in item:
            return str(item["id"])
    return "1"


# =====================================================================
# Volume de dados (opcional) — requer Django
# =====================================================================
def semear(itens: int) -> int:
    """Cria `itens` produtos via ORM (para a medição ter páginas e volume).

    Só funciona dentro do ambiente Django (container da API ou venv com
    `DJANGO_SETTINGS_MODULE`). Os SKUs usam o prefixo `MED-` e seguem o
    formato validado pelo modelo: `^[A-Z]{2,4}-[A-Z0-9-]+$`.
    """
    import django

    # O script vive em `<repo>/scripts`, mas o pacote `config` (settings) fica
    # em `<repo>/api`. Sem esta linha, `import config.settings` só funcionaria
    # se o diretório `api/` estivesse no PYTHONPATH.
    raiz_api = Path(__file__).resolve().parents[1] / "api"
    if raiz_api.is_dir() and str(raiz_api) not in sys.path:
        sys.path.insert(0, str(raiz_api))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from core.models import Category, Item

    categorias, _ = Category.objects.get_or_create(
        name="Benchmark",
        defaults={"description": "Categoria criada pelo script de medição (Aula 8)."},
    )
    # Preços e estados variados: filtros, ordenações e paginação passam a
    # produzir payloads diferentes (como em um catálogo real).
    marcas = ("Synapse", "Orion", "Vertex", "Nimbus")
    criados = 0
    for indice in range(1, itens + 1):
        _, criado = Item.objects.get_or_create(
            sku=f"MED-{indice:04d}",
            defaults={
                "name": f"Produto Benchmark {indice:04d}",
                "brand": marcas[indice % len(marcas)],
                "model": f"BM-{indice:04d}",
                "price": 99.90 * (1 + indice % 40),
                "category": categorias,
                "is_active": indice % 5 != 0,
                "description": "Item criado para a medição de desempenho (Aula 8).",
                "specifications": {"origem": "measure_cache.py", "n": indice},
            },
        )
        criados += int(criado)
    return criados


# =====================================================================
# Apresentação
# =====================================================================
def imprimir_tabela(rotulo: str, resultados: list[tuple[str, dict]]) -> None:
    cabecalho = (
        f"{'endpoint':<34}{'n':>5}{'1ª fria':>10}{'média':>9}{'p95':>9}"
        f"{'média ss':>10}{'p95 ss':>9}{'RPS':>9}"
    )
    print(f"\n=== {rotulo} ===")
    print(cabecalho)
    print("-" * len(cabecalho))
    for nome, stats in resultados:
        print(
            f"{nome:<34}{stats['n']:>5}{stats['fria_ms']:>10.2f}"
            f"{stats['media_ms']:>9.2f}{stats['p95_ms']:>9.2f}"
            f"{stats['media_ss_ms']:>10.2f}{stats['p95_ss_ms']:>9.2f}"
            f"{stats['rps']:>9.1f}"
        )


def imprimir_alertas(resultados: list[tuple[str, dict]]) -> None:
    """Respostas não-200 (429 de throttle, 404 de id inexistente) invalidam
    a comparação — por isso saem em destaque, nunca em silêncio."""
    for nome, stats in resultados:
        if stats["nao_200"]:
            detalhe = ", ".join(f"{qtd}x {status}" for status, qtd in stats["nao_200"].items())
            print(f"[AVISO] {nome}: respostas não-200 — {detalhe}")


def imprimir_metricas(antes: dict | None, depois: dict | None) -> None:
    if not antes or not depois:
        print(
            "\n(métricas de cache indisponíveis — informe --token com JWT de admin "
            "para ver o hit rate)"
        )
        return
    print("\n=== cache (hit rate por namespace) ===")
    print(
        f"{'namespace':<20}{'lookups':>9}{'hits':>8}{'misses':>8}"
        f"{'bypass':>8}{'hit rate':>11}"
    )
    print("-" * 64)
    for namespace, contadores in depois.get("namespaces", {}).items():
        print(
            f"{namespace:<20}{contadores['lookups']:>9}{contadores['hits']:>8}"
            f"{contadores['misses']:>8}{contadores['bypasses']:>8}"
            f"{contadores['hit_rate'] * 100:>10.1f}%"
        )
    total = depois.get("total", {})
    print(
        f"{'TOTAL':<20}{total.get('lookups', 0):>9}{total.get('hits', 0):>8}"
        f"{total.get('misses', 0):>8}{total.get('bypasses', 0):>8}"
        f"{total.get('hit_rate', 0) * 100:>10.1f}%"
    )
    print(
        f"(hit rate antes da rodada: {antes.get('total', {}).get('hit_rate', 0) * 100:.1f}%)"
    )


# =====================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mede latência (média/p50/p95) e RPS dos endpoints com cache-aside."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=100, help="requisições por endpoint")
    parser.add_argument("--warmup", type=int, default=3, help="requisições descartadas")
    parser.add_argument(
        "--item-id",
        default="auto",
        help="id usado nos endpoints de item (padrão: 'auto', o 1º da listagem)",
    )
    parser.add_argument("--label", default="medicao", help="rótulo exibido no relatório")
    parser.add_argument(
        "--token", default=None, help="JWT de admin: habilita a leitura de /cache/metrics/"
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="cria N itens via ORM antes de medir"
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    if args.seed > 0:
        criados = semear(args.seed)
        print(f"[seed] {criados} itens criados (solicitados: {args.seed})")

    item_id = (
        descobrir_item_id(base, args.token)
        if args.item_id == "auto"
        else str(args.item_id)
    )
    print(f"[alvo] endpoints de item usam o id {item_id}")

    metricas_antes = ler_metricas(base, args.token)
    resultados: list[tuple[str, dict]] = []
    for nome, caminho in ENDPOINTS:
        url = base + caminho.format(item=item_id)
        resultados.append(
            (nome, medir_endpoint(url, args.requests, args.token, args.warmup))
        )
    metricas_depois = ler_metricas(base, args.token)

    imprimir_tabela(args.label, resultados)
    imprimir_alertas(resultados)
    imprimir_metricas(metricas_antes, metricas_depois)
    return 0


if __name__ == "__main__":
    sys.exit(main())
