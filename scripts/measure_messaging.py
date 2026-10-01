r"""Medição da **latência e da vazão** assíncronas do fluxo de pedidos (RabbitMQ).

Aula 9 entregou latência: do POST que cria o pedido até o instante em que o
worker marcou `processado`. A Aula 10 acrescenta o que faltava para o DoD —
**vazão**, **paralelismo entre consumidores** e **análise dos logs
transacionais**:

1. **Latência ponta a ponta do pedido**: do POST que cria o pedido até o
   instante em que o worker marcou `processado`. É a latência que o cliente
   não sente no POST (que responde 201 assim que o broker confirma) e sim no
   `GET /pedidos/{id}`.
2. **Efeito da idempotência**: reenviar o mesmo POST com a mesma
   `Idempotency-Key` precisa devolver o MESMO pedido (200), sem criar outro e
   sem gerar um segundo evento na fila.
3. **Vazão** (`--carga`): N pedidos disparados em paralelo, medindo
   pedidos/segundo na publicação e no processamento. Sem carga, a fila nunca
   tem mais de uma mensagem em trânsito e "vazão" não existe para medir.
4. **Fila parada na DLQ**: um pedido com `X-Simular-Falha: 1` percorre a escada
   de reentrega (5 s / 15 s / 45 s) e termina na `pedidos.criados.dlq`. Com
   `--inspecionar-dlq` a mensagem retida é **lida sem ser consumida**, e o
   relatório mostra o payload, o `x-tentativa` (nosso contador) e o `x-death`
   (contador do próprio RabbitMQ).
5. **Logs transacionais** (`--analisar-logs`): agrega o JSONL do worker em
   contagem de eventos, latências e distribuição de trabalho por instância.

O script fala HTTP com a API e lê as filas na management API do RabbitMQ
(`:15672`), usando **somente a biblioteca padrão** — nenhuma dependência nova
(dentro do container da API ele roda com o Python da imagem).

```powershell
# Ciclo completo (o ciclo da escada de reentrega leva ~70 s)
.venv\Scripts\python.exe scripts\measure_messaging.py --pedidos 20 --duplicatas 3 `
    --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# Só a análise de um log já salvo (não precisa da API no ar)
docker compose logs --no-color --no-log-prefix worker > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl
```

Notas metodológicas (importam para não ler número errado):

* **Latência por polling, não por push.** O worker não notifica o cliente; o
  script faz `GET /pedidos/{id}` até ver `processado`. Cada leitura é um ciclo
  de `--intervalo` (padrão 0,2 s), então a latência medida tem erro de até
  `intervalo`. Com 0,2 s sobre latências de ~50 ms, o número honesto é "dezenas
  de milissegundos", não o valor exato — e é isso que interessa aqui: a fila
  assíncrona entrega em **milissegundos**, não nos segundos do backoff.
* **Throttling.** O padrão da Aula 7 corta requisições de usuário, e o polling
  da carga gera muito mais GET do que o de uma medição sequencial. O script
  espera `Retry-After` em caso de 429 (e conta), mas para uma amostra limpa
  suba `DRF_USER_RATE` na execução (ver README).
* **O tempo do backoff não entra na amostra.** As ordens com
  `X-Simular-Falha` são medições separadas: elas levam ~65 s até a DLQ por
  desenho, e misturá-las na média "contaminaria" a latência do fluxo feliz com
  o tempo de espera que a política de reentrega impõe de propósito.
* **Profundidade de fila no fim.** A management API é lida depois do fluxo, e
  o resultado é a evidência da DLQ (`messages_ready` na fila de dead letter).
  Antes de fotografar, o script **espera a mensagem aparecer de fato** na DLQ:
  o `status = falha` no banco é gravado *antes* da publicação, então perguntar
  ao banco nada prova sobre a fila. Ver `aguardar_mensagem_na_dlq`.
* **Inspecionar a DLQ não consome.** A leitura usa `ack_requeue_true`, e o
  requeue de uma mensagem já dead-letterada foi verificado como estável: a fila
  segue com a mesma mensagem 90 s depois.
* **A vazão depende do número de consumidores.** Com um worker, cada pedido é
  processado um de cada vez (`prefetch_count=1`). Repetir a carga com
  `--scale worker=3` mede o ganho de ter mais consumidores na mesma fila, e a
  distribuição de trabalho por instância aparece em `--analisar-logs`.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor

ITENS_PATH = "/api/v1/items/"
PEDIDOS_PATH = "/api/v1/pedidos/"
TOKEN_PATH = "/api/v1/auth/token/"
# nomes de fila da Aula 9 (ver core/messaging/topologia.py)
FILA_PRINCIPAL = "pedidos.criados"
FILA_DLQ = "pedidos.criados.dlq"
FILAS_RETRY = ("pedidos.criados.retry.1", "pedidos.criados.retry.2", "pedidos.criados.retry.3")


# =====================================================================
# Cliente HTTP mínimo (stdlib)
# =====================================================================
# Throttling absorvido. Um 429 é resuelto esperando o `Retry-After` e
# repetindo, para que a medição não aborte — mas a latência dessa espera
# entra na amostra. Numa execução real o `docker compose up --scale worker=3`
# recriou a API com `DRF_USER_RATE` no padrão (100/min) e 11 throttles
# empurraram a latência média da carga de ~3,3 s para ~53 s: um relatório
# bonito e completamente falso. Por isso o 429 é contado globalmente e a
# execução é considerada inválida se passar de `--tolerar-429`.
#
# Indisponibilidade (conexão recusada/derrubada) tem contador próprio: ela é
# esperada no experimento de at-least-once, onde derrubar containers é o
# teste, e não invalida a medição de latência.
_TRAVA_CONTAGENS = threading.Lock()
_ABSORVIDOS = {
    "429": 0,
    "espera_429_s": 0.0,
    "conexao_indisponivel": 0,
    "espera_conexao_s": 0.0,
}


def _registrar_429(espera: float) -> None:
    with _TRAVA_CONTAGENS:
        _ABSORVIDOS["429"] += 1
        _ABSORVIDOS["espera_429_s"] += espera


def _registrar_indisponivel(espera: float) -> None:
    with _TRAVA_CONTAGENS:
        _ABSORVIDOS["conexao_indisponivel"] += 1
        _ABSORVIDOS["espera_conexao_s"] += espera


def _headers(token: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """JSON puro (nada de HTML da browsable API) + JWT + extras."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return headers


def request(
    url: str,
    token: str | None = None,
    metodo: str = "GET",
    corpo: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    esperar_429: bool = True,
) -> tuple[int, dict | None, float]:
    """Executa uma requisição e devolve `(status, json, latência_ms)`.

    Dois incidentes são tratados como "aguenta e repete", porque abortar a
    medição no meio seria perder evidência:

    * **429** — o limite de throttling da Aula 7. A espera do `Retry-After`
      entra na amostra e é contada em `_ABSORVIDOS`, o que invalida a execução
      se passar de `--tolerar-429`.
    * **Conexão recusada/derrubada** — quem derruba containers é justamente o
      experimento de at-least-once. Numa execução real, `docker compose up
      --force-recreate` derrubou a API no meio da carga e o harness morreu com
      `http.client.RemoteDisconnected`, que **não** é `URLError` e escapava do
      `except`. Aqui entra na mesma fila de retentativas, e também é contado.
    """
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = _headers(token, extra_headers)
    if dados is not None:
        cabecalhos["Content-Type"] = "application/json"

    inicio = time.perf_counter()
    tentativas = 0
    while True:
        requisicao = urllib.request.Request(
            url, data=dados, headers=cabecalhos, method=metodo
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
                bruto = resposta.read()
                status = resposta.status
                espera = 0.0
        except urllib.error.HTTPError as erro:
            bruto = erro.read()
            status = erro.code
            espera = float(erro.headers.get("Retry-After") or 0) if status == 429 else 0.0
        except (urllib.error.URLError, OSError, http.client.HTTPException) as erro:
            # Conexão recusada, resetada ou resposta incompleta: o serviço
            # reiniciou. Conta como espera e repete, igual ao 429.
            if tentativas < 5:
                tentativas += 1
                pausa = 1.0
                _registrar_indisponivel(pausa)
                print(f"    conexão indisponível ({type(erro).__name__}): {pausa:.1f}s e repetindo")
                time.sleep(pausa)
                continue
            latencia_ms = (time.perf_counter() - inicio) * 1000
            return 0, {"detail": f"{type(erro).__name__}: {erro}"}, latencia_ms
        latencia_ms = (time.perf_counter() - inicio) * 1000

        if status == 429 and esperar_429 and tentativas < 5:
            tentativas += 1
            pausa = max(espera, 1.0)
            _registrar_429(pausa)
            print(f"    429 (throttling): esperando {pausa:.1f}s e repetindo")
            time.sleep(pausa)
            continue
        try:
            payload = json.loads(bruto) if bruto else None
        except json.JSONDecodeError:
            payload = {"raw": bruto[:200].decode("utf-8", "replace")}
        return status, payload, latencia_ms


def percentil(amostras: list[float], p: float) -> float:
    """Percentil pelo rank mais próximo (p95 = 95% abaixo dele)."""
    if not amostras:
        return 0.0
    ordenadas = sorted(amostras)
    posicao = max(1, math.ceil(p / 100 * len(ordenadas)))
    return ordenadas[posicao - 1]


def resumir(nome: str, amostras: list[float]) -> dict:
    """Média/p50/p95/máx de uma amostra de latência, em ms."""
    return {
        "cenario": nome,
        "n": len(amostras),
        "media_ms": round(statistics.fmean(amostras), 2) if amostras else 0.0,
        "p50_ms": round(percentil(amostras, 50), 2),
        "p95_ms": round(percentil(amostras, 95), 2),
        "max_ms": round(max(amostras), 2) if amostras else 0.0,
    }


# =====================================================================
# Etapas da medição
# =====================================================================
class Sessao:
    """Token JWT com renovação automática.

    O `access` do SimpleJWT vive 5 minutos e a medição completa (escada de
    reentrega inclusa) leva mais que isso. Em vez de falhar no meio do
    relatório, a sessão renova o token no primeiro 401 — o refresh é de graça e
    o erro ficaria silencioso, "amostrando" pedidos que nunca foram criados.
    """

    def __init__(self, base_url: str, usuario: str, senha: str) -> None:
        self.base_url = base_url
        self.usuario = usuario
        self.senha = senha
        self.access = ""
        self.refresh = ""
        self.renovacoes = 0
        # Aula 10: a etapa de carga dispara POSTs em paralelo, e várias
        # threads podem tomar 401 ao mesmo tempo. Sem a trava, cada uma renova
        # o token e a contador `renovacoes` perde medidas (é `x += 1`).
        self._trava = threading.Lock()
        self._renovar()

    def _renovar(self) -> None:
        status, corpo, _ = request(
            self.base_url + TOKEN_PATH,
            metodo="POST",
            corpo={"username": self.usuario, "password": self.senha},
        )
        if status != 200 or not isinstance(corpo, dict) or "access" not in corpo:
            sys.exit(
                f"login falhou ({status}): {corpo}\n"
                f"Confira --usuario/--senha e o throttle de 5/min do endpoint de login."
            )
        self.access = corpo["access"]
        self.refresh = corpo.get("refresh", "")

    def renovar_se_preciso(self) -> None:
        """Troca o refresh por um novo access (uma tentativa, sem recursão).

        Sob a trava porque a etapa de carga é multithread: sem ela, N threads
        que tomam 401 juntas renovam N tokens e `renovacoes` (que vai no
        relatório) fica subcontado.
        """
        with self._trava:
            if not self.refresh:
                self._renovar()
                return
            status, corpo, _ = request(
                self.base_url + f"{TOKEN_PATH}refresh/",
                metodo="POST",
                corpo={"refresh": self.refresh},
            )
            if status == 200 and isinstance(corpo, dict) and "access" in corpo:
                self.access = corpo["access"]
                self.renovacoes += 1
            else:
                # Refresh inválido (expirou/executado): refaz o login.
                self._renovar()

    def pedir(
        self,
        metodo: str = "GET",
        caminho: str = "",
        corpo: dict | None = None,
        cabecalhos: dict[str, str] | None = None,
        *,
        renovar: bool = True,
    ) -> tuple[int, dict | None, float]:
        """Requisição autenticada que se renova sozinha em caso de 401."""
        status, resposta, latencia = request(
            self.base_url + caminho,
            token=self.access,
            metodo=metodo,
            corpo=corpo,
            extra_headers=cabecalhos,
        )
        if status == 401 and renovar:
            self.renovar_se_preciso()
            return self.pedir(metodo, caminho, corpo, cabecalhos, renovar=False)
        return status, resposta, latencia


def login(base_url: str, usuario: str, senha: str) -> Sessao:
    return Sessao(base_url, usuario, senha)


def descobrir_skus(sessao: Sessao, quantidade: int) -> list[tuple[str, str]]:
    """Lê SKUs reais do catálogo (o POST resolve preço por SKU).

    Usa a listagem de itens ativos: um SKU inexistente dá 404 no POST, e um SKU
    inativo também — os dois fariam a medição estourar num erro de domínio em
    vez de medir a fila.
    """
    status, corpo, _ = sessao.pedir(caminho=f"{ITENS_PATH}?is_active=true&ordering=price")
    if status != 200 or not isinstance(corpo, dict):
        sys.exit(f"não foi possível ler o catálogo ({status}): {corpo}")
    resultados = corpo.get("results") or []
    if not resultados:
        sys.exit("catálogo vazio: rode as migrations/fixtures antes de medir.")
    return [(item["sku"], str(item["price"])) for item in resultados[:quantidade]]


def criar_pedido(
    sessao: Sessao,
    chave: str,
    itens: list[dict],
    simular_falha: bool = False,
) -> tuple[int, dict | None, float]:
    """POST de pedido com `Idempotency-Key` explícita.

    A chave é sempre enviada: sem ela a API cairia no SHA-256 do próprio
    pedido, que também é idempotente, mas aí o teste de reenvio estaria
    medindo um caminho diferente do que um cliente real usa.
    """
    cabecalhos = {"Idempotency-Key": chave}
    if simular_falha:
        cabecalhos["X-Simular-Falha"] = "1"
    return sessao.pedir(
        metodo="POST", caminho=PEDIDOS_PATH, corpo={"itens": itens}, cabecalhos=cabecalhos
    )


def aguardar_processado(
    sessao: Sessao, pedido_id: int, timeout: float, intervalo: float
) -> tuple[str, float]:
    """Faz `GET /pedidos/{id}` até o estado final. Devolve `(estado, espera_ms)`.

    A espera é medida a partir do `publicado_em` do evento devolvido no POST —
    que é o relógio do produtor dentro do worker — e não do relógio do script:
    o instante da leitura depende de quando o script perguntou, o do produtor
    não.

    O intervalo é adaptativo (rápido nos primeiros segundos, depois mais
    lento) por dois motivos: o caso feliz resolve em dezenas de milissegundos,
    e o throttling de 100/min do usuário não pode ser a razão de o script
    desistir de um pedido que já foi processado.
    """
    inicio = time.perf_counter()
    espera = intervalo
    while True:
        status, corpo, _ = sessao.pedir(caminho=f"{PEDIDOS_PATH}{pedido_id}/")
        waited_ms = (time.perf_counter() - inicio) * 1000
        if status == 200 and isinstance(corpo, dict):
            estado = corpo.get("status", "?")
            if estado in {"processado", "falha"}:
                return estado, waited_ms
        if waited_ms / 1000 >= timeout:
            return "timeout", waited_ms
        time.sleep(espera)
        # Cresce até 2 s: mantém a precisão no caso rápido sem estourar a
        # cota de throttling no caso lento (ou inexistente).
        espera = min(espera * 1.6, 2.0)


def medir_fluxo_feliz(
    sessao: Sessao, skus: list[tuple[str, str]], pedidos: int, intervalo: float
) -> tuple[list[float], dict]:
    """Cria N pedidos e mede a latência até `processado`. Também mede o POST.

    O POST é medido à parte porque é a métrica síncrona (o que o cliente
    sente): ele responde depois do publisher confirm, sem esperar o worker.
    """
    latencias_evento: list[float] = []
    latencias_post: list[float] = []
    # Chaveado por rótulo em texto: mistura o status HTTP ("429", "500") com os
    # casos sem status mas relevantes ("sem_publicado_em") na mesma tabela.
    nao_201: dict[str, int] = {}
    timeouts = 0

    for indice in range(pedidos):
        itens = [{"sku": skus[indice % len(skus)][0], "quantidade": 1 + indice % 3}]
        chave = f"aula9-medida-{int(time.time())}-{indice}"
        status, corpo, post_ms = criar_pedido(sessao, chave, itens)
        if status != 201 or not isinstance(corpo, dict) or "id" not in corpo:
            rotulo = str(status)
            nao_201[rotulo] = nao_201.get(rotulo, 0) + 1
            print(f"  [{indice + 1}/{pedidos}] POST {status}: {str(corpo)[:120]}")
            continue
        latencias_post.append(post_ms)
        evento = corpo.get("evento") or {}
        publicado_em = evento.get("publicado_em")
        if publicado_em is None:
            # Sem o relógio do produtor na resposta, a latência da fila não é
            # mensurável de forma reprodutível (o instante da leitura depende
            # de quando o script perguntou, não de quando o evento saiu).
            nao_201["sem_publicado_em"] = nao_201.get("sem_publicado_em", 0) + 1
            print("  resposta sem `evento.publicado_em`: latência não mensurável")
            continue
        estado, waited_ms = aguardar_processado(
            sessao, corpo["id"], timeout=20.0, intervalo=intervalo
        )
        if estado == "processado":
            # do relógio do produtor até a observação do script
            agora_ms = int(time.time() * 1000)
            latencias_evento.append(max(0, agora_ms - publicado_em))
            print(
                f"  [{indice + 1}/{pedidos}] pedido {corpo['id']}: POST {post_ms:.0f}ms, "
                f"processado em {agora_ms - publicado_em}ms (visto em {waited_ms:.0f}ms)"
            )
        else:
            timeouts += 1
            print(
                f"  [{indice + 1}/{pedidos}] pedido {corpo['id']}: estado '{estado}' "
                f"após {waited_ms / 1000:.1f}s"
            )

    return latencias_evento, {
        "post_media_ms": round(statistics.fmean(latencias_post), 2) if latencias_post else 0.0,
        "post_p95_ms": round(percentil(latencias_post, 95), 2),
        "post_max_ms": round(max(latencias_post), 2) if latencias_post else 0.0,
        "post_n": len(latencias_post),
        "nao_201": dict(nao_201),
        "timeouts": timeouts,
    }


def _dispara_pedido(
    sessao: Sessao, skus: list[tuple[str, str]], indice: int, marca: str
) -> tuple[int, dict | None, float]:
    """POST de um pedido da carga. Devolve `(status, corpo, latência_ms)`.

    Nome próprio (e não `criar_pedido`) porque a carga precisa de uma chave
    distinta por pedido dentro da mesma execução e do mesmo segundo.
    """
    itens = [{"sku": skus[indice % len(skus)][0], "quantidade": 1 + indice % 3}]
    return criar_pedido(sessao, f"aula10-carga-{marca}-{indice}", itens)


def medir_carga(
    sessao: Sessao,
    skus: list[tuple[str, str]],
    total: int,
    concorrencia: int,
    intervalo: float,
    espera_s: float,
) -> dict:
    """Mede **vazão** do pipeline: dispara N pedidos em paralelo e conta.

    A etapa do fluxo feliz é estritamente sequencial (POST → espera
    `processado` → próximo POST), e por isso mede só *latência*: nunca chega a
    haver mais de uma mensagem em trânsito, que é exatamente a situação em que
    a vazão existe. Aqui os N POSTs saem juntos e o gargalo passa a ser o
    broker + o worker, não o script.

    São reportadas **duas** vazões porque elas respondem perguntas diferentes:

    * `publicacao_por_s` — do primeiro ao último POST. Limita pela API e pelo
      publisher confirm (é a vazão de *aceitação* do broker);
    * `processamento_por_s` — do primeiro POST até o último pedido marcado
      `processado`. Inclui a fila, e é a vazão que o negócio sente.

    E a latência sob carga (`publicado_em → processado`), que é o preço da
    concorrência: quanto mais pedido em voo, mais tempo cada um espera.
    """
    marca = f"{int(time.time())}-{os.getpid()}"
    pendentes: dict[int, int] = {}
    latencias_post: list[float] = []
    nao_201: dict[str, int] = {}

    def um(indice: int) -> None:
        status, corpo, post_ms = _dispara_pedido(sessao, skus, indice, marca)
        if status != 201 or not isinstance(corpo, dict) or "id" not in corpo:
            nao_201[str(status)] = nao_201.get(str(status), 0) + 1
            return
        latencias_post.append(post_ms)
        publicado_em = (corpo.get("evento") or {}).get("publicado_em")
        if publicado_em is not None:
            pendentes[corpo["id"]] = publicado_em

    print(f"  disparando {total} pedidos com {concorrencia} POST(s) em paralelo...")
    inicio_publicacao = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concorrencia) as executor:
        list(executor.map(um, range(total)))
    fim_publicacao = time.perf_counter()

    publicados = len(pendentes)
    latencias_evento: list[float] = []
    falhas = 0
    inicio = time.perf_counter()
    passes = 0
    while pendentes and (time.perf_counter() - inicio) < espera_s:
        passes += 1
        for pedido_id, publicado_em in list(pendentes.items()):
            status, leitura, _ = sessao.pedir(caminho=f"{PEDIDOS_PATH}{pedido_id}/")
            if status != 200 or not isinstance(leitura, dict):
                continue
            if leitura.get("status") not in {"processado", "falha"}:
                continue
            del pendentes[pedido_id]
            agora_ms = int(time.time() * 1000)
            if leitura["status"] == "processado":
                latencias_evento.append(max(0, agora_ms - publicado_em))
            else:
                falhas += 1
        if pendentes:
            print(
                f"    t+{time.perf_counter() - inicio:5.1f}s "
                f"aguardando {len(pendentes)}/{publicados} pedidos"
            )
            time.sleep(intervalo)
    fim = time.perf_counter()

    tempo_publicacao = max(fim_publicacao - inicio_publicacao, 1e-6)
    tempo_total = max(fim - inicio_publicacao, 1e-6)
    return {
        "cenario": "carga concorrente",
        "pedidos_pedidos": total,
        "publicados": publicados,
        "concorrencia": concorrencia,
        "processados": len(latencias_evento),
        "nao_processados": len(pendentes),
        "falha": falhas,
        "nao_201": nao_201,
        "publicacao_por_s": round(publicados / tempo_publicacao, 2),
        "processamento_por_s": round(len(latencias_evento) / tempo_total, 2),
        "tempo_publicacao_s": round(tempo_publicacao, 3),
        "tempo_total_s": round(tempo_total, 3),
        "passes_de_poll": passes,
        "post_media_ms": round(statistics.fmean(latencias_post), 2) if latencias_post else 0.0,
        "post_p95_ms": round(percentil(latencias_post, 95), 2),
        **resumir("publicado -> processado (sob carga)", latencias_evento),
    }


def medir_idempotencia(sessao: Sessao, skus: list[tuple[str, str]], repeticoes: int) -> dict:
    """Reenvia o MESMO POST (mesma chave) e confere que o pedido não muda.

    Esperado em toda repetição: HTTP 200, o mesmo `id` e
    `evento.duplicado == true`. Um 201 aqui indicaria que a barreira de
    idempotência não segurou — o defeito mais caro dessa aula, porque o
    cliente pagaria duas vezes.
    """
    itens = [{"sku": skus[0][0], "quantidade": 2}]
    chave = f"aula9-idem-{int(time.time())}"

    status, corpo, _ = criar_pedido(sessao, chave, itens)
    if status != 201 or not isinstance(corpo, dict):
        return {"erro": f"POST inicial falhou ({status}): {corpo}"}
    pedido_id = corpo["id"]

    respostas = []
    for indice in range(repeticoes):
        status, repetido, latencia_ms = criar_pedido(sessao, chave, itens)
        mesmo_id = isinstance(repetido, dict) and repetido.get("id") == pedido_id
        duplicado = bool((repetido or {}).get("evento", {}).get("duplicado"))
        respostas.append(
            {"status": status, "mesmo_pedido": mesmo_id, "marcado_duplicado": duplicado}
        )
        print(
            f"  reenvio {indice + 1}/{repeticoes}: HTTP {status} "
            f"(mesmo id: {mesmo_id}, duplicado: {duplicado}, {latencia_ms:.0f}ms)"
        )
        time.sleep(0.3)

    ok = all(r["status"] == 200 and r["mesmo_pedido"] and r["marcado_duplicado"] for r in respostas)
    return {
        "pedido_id": pedido_id,
        "reenvios": respostas,
        "idempotente": ok,
    }


def medir_dlq(sessao: Sessao, skus: list[tuple[str, str]], espera_s: float) -> dict:
    """Cria um pedido com falha injetada e acompanha a escada até a DLQ.

    Acompanhar é o ponto: mostra os tempos de cada tentativa no log do worker
    (`PedidoFalha` com `tentativa` e o atraso do degrau) e termina com o pedido
    em `falha` e a mensagem na `pedidos.criados.dlq`.
    """
    itens = [{"sku": skus[0][0], "quantidade": 1}]
    chave = f"aula9-dlq-{int(time.time())}"
    status, corpo, _ = criar_pedido(sessao, chave, itens, simular_falha=True)
    if status != 201 or not isinstance(corpo, dict):
        return {"erro": f"POST com X-Simular-Falha falhou ({status}): {corpo}"}
    pedido_id = corpo["id"]
    print(f"  pedido {pedido_id} marcado para falhar; aguardando até {espera_s:.0f}s")

    inicio = time.perf_counter()
    estado = "?"
    degraus: list[float] = []
    anterior = 0.0
    while (time.perf_counter() - inicio) < espera_s:
        _, leitura, _ = sessao.pedir(caminho=f"{PEDIDOS_PATH}{pedido_id}/")
        agora = time.perf_counter() - inicio
        estado = (leitura or {}).get("status", "?")
        tentativas = (leitura or {}).get("tentativas", 0)
        if tentativas != anterior:
            degraus.append(round(agora, 1))
            anterior = tentativas
        print(
            f"    t+{agora:5.1f}s  status={estado} tentativas={tentativas}"
        )
        if estado in {"processado", "falha"}:
            break
        time.sleep(3.0)

    return {
        "pedido_id": pedido_id,
        "estado_final": estado,
        "dlq": estado == "falha",
        # Instante de cada tentativa observada: deve repetir 5 s / 15 s / 45 s
        # (a última linha é a chegada à DLQ, cerca de 65 s após o POST).
        "tentativas_em_s": degraus,
    }


def _credencial(usuario: str, senha: str) -> str:
    return f"Basic {b64encode(f'{usuario}:{senha}'.encode()).decode()}"


def inspecionar_dlq(api_url: str, usuario: str, senha: str) -> dict:
    """Lê a mensagem retida na DLQ, **sem consumi-la**.

    A evidência "a fila `pedidos.criados.dlq` tem 1 mensagem" prova que sobrou
    algo, mas não diz *o que* chegou lá nem *como* chegou. A management API
    resolve isso com `POST /api/queues/{vhost}/{fila}/get` no modo
    `ack_requeue_true`: a mensagem é lida e **devolvida** à fila, então a
    profundidade medida na etapa seguinte continua igual.

    O que se extrai:

    * o payload do evento (`evento_id`, `pedido.id`, `idempotency_key`);
    * `x-tentativa` — o **nosso** contador, que prova quantas reentregas
      ocorreram;
    * `x-death` — o contador do **próprio RabbitMQ**, que registra cada
      passagem por uma fila com TTL (a escada de retry) e o motivo
      (`expired`);
    * `x-motivo` — o resumo da falha que o worker gravou ao reentregar.
    """
    caminho = f"/api/queues/{urllib.parse.quote('/', safe='')}/{urllib.parse.quote(FILA_DLQ, safe='')}/get"
    corpo = {
        # `ack_requeue_true` = devolve a mensagem à fila. É o que permite
        # inspecionar sem destruir a evidência.
        "count": 5,
        "ackmode": "ack_requeue_true",
        "encoding": "auto",
    }
    requisicao = urllib.request.Request(
        f"{api_url}{caminho}",
        data=json.dumps(corpo).encode("utf-8"),
        headers={
            "Authorization": _credencial(usuario, senha),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=10.0) as resposta:
            mensagens = json.loads(resposta.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as erro:
        return {"erro": f"não foi possível ler a DLQ: {erro}"}

    if not isinstance(mensagens, list) or not mensagens:
        return {"mensagens": 0, "observacao": "DLQ vazia"}

    resumos = []
    for mensagem in mensagens[:1]:
        propriedades = mensagem.get("properties") or {}
        cabecalhos = _achatar_headers(propriedades.get("headers"))
        try:
            evento = json.loads(mensagem.get("payload") or "{}")
            pedido = evento.get("pedido") or {}
        except json.JSONDecodeError:
            evento, pedido = {}, {}
        resumos.append(
            {
                "fila": FILA_DLQ,
                "payload": {
                    "evento": evento.get("evento"),
                    "versao": evento.get("versao"),
                    "evento_id": evento.get("evento_id"),
                    "pedido_id": pedido.get("id"),
                    "idempotency_key": (evento.get("idempotency_key") or "")[:16] + "...",
                },
                "message_id": propriedades.get("message_id"),
                "x_tentativa": cabecalhos.get("x-tentativa"),
                "x_motivo": cabecalhos.get("x-motivo"),
                "x_death": _resumir_x_death(cabecalhos.get("x-death")),
            }
        )
    return {"mensagens": len(mensagens), "consumidas": False, "detalhe": resumos}


def _achatar_headers(cabecalhos: object) -> dict:
    """Normaliza os headers AMQP, que podem vir como dict ou lista de pares."""
    if isinstance(cabecalhos, dict):
        return cabecalhos
    if isinstance(cabecalhos, list):
        achatado: dict = {}
        for par in cabecalhos:
            if isinstance(par, (list, tuple)) and len(par) == 2:
                achatado[str(par[0])] = par[1]
        return achatado
    return {}


def _resumir_x_death(x_death: object) -> list[dict]:
    """Reduz o `x-death` (lista de listas de dicionários) a motivo/contagem.

    Cada passagem pela escada de retry soma uma entrada; o que interessa para
    a evidência é "quantas vezes e por quê".
    """
    resumo: list[dict] = []
    if not isinstance(x_death, list):
        return resumo
    for entrada in x_death:
        itens = entrada if isinstance(entrada, list) else [entrada]
        for item in itens:
            if not isinstance(item, dict):
                continue
            resumo.append(
                {
                    "fila": item.get("queue"),
                    "motivo": item.get("reason"),
                    "contagem": item.get("count"),
                    "trocada_por": item.get("exchange"),
                }
            )
    return resumo


def contar_consumidores(api_url: str, usuario: str, senha: str) -> dict:
    """Conta os consumidores de cada fila da Aula 9.

    Este é o indicador de paralelismo no AMQP: como todas as instâncias do
    worker consomem a **mesma** fila, o broker as atende em round-robin e
    `consumers` cresce 1 → 2 → 3 conforme `--scale worker=N`.

    Observação registrada de propósito: o detalhe por consumidor
    (`ack_rate`, `prefetch_count`) **não** é confiável na management API do
    RabbitMQ 3.13 deste ambiente — `GET /api/queues/{vhost}/{fila}/consumers`
    devolve 400, `GET /api/consumers/vhost/{vhost}` devolve 400 e
    `consumer_details` vem vazio em `/api/connections`. Por isso a distribuição
    do trabalho entre os workers é medida pelo log (ver `analisar_logs`), que
    é onde o fato realmente aconteceu.
    """
    filas = _listar_filas(api_url, usuario, senha)
    if isinstance(filas, dict):
        return filas
    conhecidas = {FILA_PRINCIPAL, FILA_DLQ, *FILAS_RETRY}
    return {
        fila["name"]: fila.get("consumers", 0)
        for fila in filas
        if fila.get("name") in conhecidas
    }


def _listar_filas(api_url: str, usuario: str, senha: str) -> list[dict] | dict:
    """`GET /api/queues` cru, ou um dict de erro.

    Filtrar em Python (em vez de pedir as filas pelo nome no caminho) evita as
    duas arestas de codificação do vhost `/` e as versões do RabbitMQ que não
    aceitam a lista de nomes separada por vírgula.
    """
    credencial = b64encode(f"{usuario}:{senha}".encode()).decode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{api_url}/api/queues", headers={"Authorization": f"Basic {credencial}"}
            ),
            timeout=10.0,
        ) as resposta:
            return json.loads(resposta.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as erro:
        return {"erro": f"management API indisponível: {erro}"}


def purgar_filas(api_url: str, usuario: str, senha: str) -> dict:
    """Esvazia as filas da Aula 9 antes de medir (não toca nas outras).

    Sem isso, uma DLQ com resíduo de uma execução anterior (ou de um teste com
    falha injetada) faria o número final parecer errado: a mensagem da medição
    se somaria a mensagens que já estavam lá. O caminho da fila é remontado a
    partir do `vhost` que a management API devolve, com `quote` para que o `/`
    do vhost padrão não vire separador de caminho.
    """
    filas = _listar_filas(api_url, usuario, senha)
    if isinstance(filas, dict):
        return filas
    conhecidas = {FILA_PRINCIPAL, FILA_DLQ, *FILAS_RETRY}
    credencial = b64encode(f"{usuario}:{senha}".encode()).decode()
    resultado = {}
    for fila in filas:
        if fila.get("name") not in conhecidas:
            continue
        caminho = urllib.parse.quote(fila.get("vhost", "/"), safe="")
        requisicao = urllib.request.Request(
            f"{api_url}/api/queues/{caminho}/{urllib.parse.quote(fila['name'], safe='')}"
            "/contents",
            headers={"Authorization": f"Basic {credencial}"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=10.0):
                resultado[fila["name"]] = "purificada"
        except (urllib.error.HTTPError, urllib.error.URLError) as erro:
            resultado[fila["name"]] = f"erro: {erro}"
    return resultado


def ler_profundidade_filas(api_url: str, usuario: str, senha: str) -> dict:
    """Profundidade (`messages_ready`) de cada fila da Aula 9."""
    filas = _listar_filas(api_url, usuario, senha)
    if isinstance(filas, dict):
        return filas

    conhecidas = {FILA_PRINCIPAL, FILA_DLQ, *FILAS_RETRY}
    return {
        fila["name"]: {
            "prontas": fila.get("messages_ready", 0),
            "nao_confirmadas": fila.get("messages_unacknowledged", 0),
            "total": fila.get("messages", 0),
        }
        for fila in filas
        if fila.get("name") in conhecidas
    }


def aguardar_mensagem_na_dlq(
    api_url: str, usuario: str, senha: str, timeout_s: float = 30.0
) -> dict:
    """Espera a mensagem **aparecer** na DLQ, em vez deAssume um tempo fixo.

    Existe por causa de uma corrida medida nesta aula. O worker grava
    `status = falha` no banco numa transação e **depois** publica na DLQ com
    publisher confirm. O `GET /pedidos/{id}` que o script faz percebe o
    `falha` no banco imediatamente — e pode perceber até alguns segundos antes
    de a publicação acontecer. Numa execução real medida aqui:

        t+68,1s  API já responde `falha`; DLQ=0, retry.3=1
        t+74s    DLQ=1, retry.3=0

    Com um `sleep(2.0)` fixo entre os dois, o relatório_final ora mostrava
    `dlq = 0` (a evidência ainda estava em trânsito na última fila de retry),
    ora `dlq = 1`, dependendo do jitter. Aqui o script **pergunta ao broker**:
    a profundidade real é a evidência, e o tempo de espera sai no relatório.

    Devolve `{prontas, aguardou_s, ok}`. `ok = False` significa que a mensagem
    não apareceu dentro de `timeout_s` — o número de DLQ então não deve ser
    lido como "não sobrou nada", e sim "a medição não conseguiu confirmar".
    """
    inicio = time.perf_counter()
    credencial = _credencial(usuario, senha)
    caminho = f"/api/queues/{urllib.parse.quote('/', safe='')}/{urllib.parse.quote(FILA_DLQ, safe='')}"
    while True:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{api_url}{caminho}", headers={"Authorization": credencial}),
                timeout=10.0,
            ) as resposta:
                fila = json.loads(resposta.read())
        except (urllib.error.HTTPError, urllib.error.URLError):
            fila = {}
        prontas = fila.get("messages_ready", 0) or 0
        aguardou = time.perf_counter() - inicio
        if prontas > 0 or aguardou >= timeout_s:
            return {"prontas": prontas, "aguardou_s": round(aguardou, 2), "ok": prontas > 0}
        time.sleep(0.5)


def _separar_prefixo(linha: str) -> tuple[str | None, str]:
    """Separa o nome do container da linha JSON.

    `docker compose logs worker` prefixa cada linha com o serviço
    (`aula02-worker-1  | {...}`) ou com o container (`synapseshop_worker-1 |`).
    Sem esse prefixo — `docker compose logs --no-log-prefix` — a linha começa
    em `{` e não há container a atribuir. Separar por `|` (o separador que o
    Compose usa) é o que sobrevive tanto a `aula02-worker-1  | {...}` quanto a
    `aula02-worker-1  | 2026-10-01T...Z {...}`.
    """
    inicio = linha.find("{")
    if inicio <= 0:
        return None, linha
    prefixo = linha[:inicio]
    if "|" not in prefixo:
        return None, linha
    container = prefixo.split("|")[0].strip()
    return (container or None), linha[inicio:]


def analisar_logs(caminho: str) -> dict:
    r"""Resume o JSONL do worker: contagem de eventos, latências e distribuição.

    É a análise do item "logs transacionais" do DoD. O logger `core.messaging`
    emite uma linha JSON por evento (`JsonLogFormatter`), então a agregação é
    feita direto sobre os campos estruturados:

    * `eventos` — quantas vezes cada tipo aconteceu (o pacote emite 20 tipos,
      dos quais 8 estavam documentados antes da Aula 10);
    * `duracao_ms` — o trabalho **dentro** do consumidor, por pedido;
    * `atraso_fila_ms` — quanto a mensagem esperou entre ser publicada e ser
      recebida; é onde aparecem os degraus do backoff;
    * `por_worker` — quantos pedidos cada instância do worker processou, que é
      a medida real do round-robin entre os consumidores concorrentes.

    ```powershell
    docker compose logs --no-color --no-log-prefix worker > logs_worker.jsonl
    .venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl
    ```
    """
    contagem: dict[str, int] = {}
    por_worker: dict[str, int] = {}
    duracoes: list[float] = []
    atrasos: list[float] = []
    nao_json = 0
    total = 0

    with open(caminho, encoding="utf-8", errors="replace") as arquivo:
        for bruta in arquivo:
            linha = bruta.strip()
            if not linha:
                continue
            total += 1
            container, trecho = _separar_prefixo(linha)
            try:
                registro = json.loads(trecho)
            except json.JSONDecodeError:
                # Linha de stdout do management command ("worker consumindo a
                # fila ..."), que não passa pelo formatter.
                nao_json += 1
                continue
            evento = registro.get("evento")
            if evento:
                contagem[str(evento)] = contagem.get(str(evento), 0) + 1
            if registro.get("evento") == "PedidoProcessado":
                chave = container or "(sem prefixo)"
                por_worker[chave] = por_worker.get(chave, 0) + 1
            for campo, destino in (("duracao_ms", duracoes), ("atraso_fila_ms", atrasos)):
                valor = registro.get(campo)
                if isinstance(valor, (int, float)):
                    destino.append(float(valor))

    return {
        "arquivo": caminho,
        "linhas": total,
        "linhas_sem_json": nao_json,
        "eventos": dict(sorted(contagem.items(), key=lambda par: -par[1])),
        "processados_por_worker": dict(sorted(por_worker.items(), key=lambda par: -par[1])),
        "duracao_ms": resumir("trabalho no consumidor", duracoes),
        "atraso_fila_ms": resumir("espera na fila (publicado -> recebido)", atrasos),
    }


# =====================================================================
# CLI
# =====================================================================
def main() -> int:
    ambiente = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    parser = argparse.ArgumentParser(
        description="Mede a latência assíncrona do fluxo de pedidos (Aula 9).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--usuario", default="demo_user", help="usuário com papel 'user'")
    parser.add_argument("--senha", default="demo-user@Synapse2026")
    parser.add_argument("--pedidos", type=int, default=20, help="pedidos do fluxo feliz")
    parser.add_argument("--duplicatas", type=int, default=3, help="reenvios com a mesma chave")
    parser.add_argument(
        "--forcar-falha",
        type=int,
        default=1,
        help="pedidos com X-Simular-Falha (0 = não medir a DLQ)",
    )
    parser.add_argument(
        "--espera-dlq",
        type=float,
        default=90.0,
        help="segundos de espera pela escada de reentrega (5+15+45 = 65s)",
    )
    parser.add_argument("--intervalo", type=float, default=0.2, help="s entre GETs de status")
    parser.add_argument("--rotulo", default="Aula 10", help="rótulo do relatório")
    parser.add_argument(
        "--carga",
        type=int,
        default=0,
        help="pedidos disparados em paralelo para medir vazão (0 = não medir)",
    )
    parser.add_argument(
        "--concorrencia",
        type=int,
        default=8,
        help="POSTs simultâneos na etapa de carga",
    )
    parser.add_argument(
        "--carga-espera",
        type=float,
        default=60.0,
        help="segundos de espera pelo `processado` de todos os pedidos da carga",
    )
    parser.add_argument(
        "--analisar-logs",
        metavar="ARQUIVO",
        default="",
        help="JSONL do `docker compose logs worker` para resumir; com esta flag "
        "o script só analisa o arquivo e sai (não mede nada)",
    )
    parser.add_argument(
        "--inspecionar-dlq",
        action="store_true",
        help="lê a mensagem retida na DLQ (sem consumi-la) e mostra x-death/x-tentativa",
    )
    parser.add_argument(
        "--rabbitmq-api",
        default="http://localhost:15672",
        help="management API do RabbitMQ (profundidade das filas)",
    )
    parser.add_argument(
        "--rabbitmq-usuario",
        default=os.environ.get("RABBITMQ_USER", "synapse"),
        help="mesma credencial de RABBITMQ_USER no docker-compose",
    )
    parser.add_argument(
        "--rabbitmq-senha",
        default=os.environ.get("RABBITMQ_PASSWORD", "synapse"),
        help="mesma credencial de RABBITMQ_PASSWORD no docker-compose",
    )
    parser.add_argument("--json", action="store_true", help="saída só em JSON")
    parser.add_argument(
        "--tolerar-429",
        type=int,
        default=0,
        help="quantos 429 absorvidos a execução aceita antes de ser declarada "
        "inválida (padrão 0: nenhum). A espera do Retry-After entra na amostra "
        "de latência, então um relatório com throttling mede o throttle",
    )
    parser.add_argument(
        "--purgar",
        action="store_true",
        help="esvazia as filas da Aula 9 antes de medir (recomendado: DLQ "
        "com resíduo de outra execução falsearia a contagem final)",
    )
    args = parser.parse_args()

    def dizer(mensagem: str) -> None:
        if not args.json:
            print(mensagem)

    # Modo "só análise de logs": não autentica, não mexe na API nem no broker.
    # Existe para o arquivo de logs poder ser analisado depois do experimento,
    # quando a API já está fora do ar.
    if args.analisar_logs:
        print(
            json.dumps(
                {"rotulo": args.rotulo, "logs": analisar_logs(args.analisar_logs)},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    base_url = args.base_url.rstrip("/")
    relatorio: dict = {"rotulo": args.rotulo, "ambiente": ambiente or "local"}

    if args.purgar:
        dizer("\n-- 0. limpando as filas da Aula 9 --")
        relatorio["purgar"] = purgar_filas(
            args.rabbitmq_api, args.rabbitmq_usuario, args.rabbitmq_senha
        )
        dizer(f"   {relatorio['purgar']}")

    dizer(f"\n== {args.rotulo}: mensageria (RabbitMQ) ==")
    sessao = login(base_url, args.usuario, args.senha)
    skus = descobrir_skus(sessao, 3)
    dizer(f"   SKUs do catálogo: {', '.join(s[0] for s in skus)}")

    # 1) fluxo feliz -----------------------------------------------------
    dizer(f"\n-- 1. fluxo feliz ({args.pedidos} pedidos) --")
    latencias, post = medir_fluxo_feliz(sessao, skus, args.pedidos, args.intervalo)
    relatorio["fluxo_feliz"] = {**resumir("pedido publicado -> processado", latencias), **post}
    dizer(f"   latência publicação->processado: {relatorio['fluxo_feliz']}")

    # 2) idempotência ----------------------------------------------------
    dizer(f"\n-- 2. idempotência ({args.duplicatas} reenvios da mesma chave) --")
    if args.duplicatas > 0:
        relatorio["idempotencia"] = medir_idempotencia(sessao, skus, args.duplicatas)
        dizer(f"   {relatorio['idempotencia']}")

    # 3) carga concorrente -> vazão ---------------------------------------
    # Fica antes da falha injetada de propósito: a carga deixa a fila
    # zerada (todos os pedidos terminam em `processado`), então a escada de
    # reentrega a seguir começa com o broker em repouso.
    dizer(f"\n-- 3. carga concorrente ({args.carga} pedidos, {args.concorrencia} em paralelo) --")
    if args.carga > 0:
        relatorio["carga"] = medir_carga(
            sessao, skus, args.carga, args.concorrencia, args.intervalo, args.carga_espera
        )
        dizer(f"   vazão: {relatorio['carga']}")

    # 4) falha injetada -> escada de reentrega -> DLQ ---------------------
    dizer(f"\n-- 4. falha injetada e escada de reentrega ({args.forcar_falha} pedido(s)) --")
    if args.forcar_falha > 0:
        relatorio["dlq"] = medir_dlq(sessao, skus, args.espera_dlq)
        dizer(f"   {relatorio['dlq']}")

    # A API grava `status = falha` **antes** de o worker publicar na DLQ, então
    # o `falha` observado não prova que a mensagem já chegou lá. Sem esta
    # espera, o relatório_final diria `dlq = 0` com a evidência ainda a bordo
    # da última fila de retry. Ver `aguardar_mensagem_na_dlq`.
    if args.forcar_falha > 0:
        dizer("\n-- 5. aguardando a mensagem chegar de fato na DLQ --")
        relatorio["dlq_chegada"] = aguardar_mensagem_na_dlq(
            args.rabbitmq_api, args.rabbitmq_usuario, args.rabbitmq_senha
        )
        dizer(f"   {relatorio['dlq_chegada']}")

    # 6) a mensagem que ficou na DLQ -------------------------------------
    # A leitura não consome (`ack_requeue_true`) e, verificado nesta aula, o
    # requeue de uma mensagem já dead-letterada é estável (a fila continua com
    # a mesma mensagem depois de 90 s) — então inspecionar não destrói a
    # evidência nem contamina a profundidade medida na etapa 7.
    if args.inspecionar_dlq:
        dizer("\n-- 6. mensagem retida na DLQ (leitura, não consome) --")
        relatorio["dlq_inspecao"] = inspecionar_dlq(
            args.rabbitmq_api, args.rabbitmq_usuario, args.rabbitmq_senha
        )
        dizer(f"   {relatorio['dlq_inspecao']}")

    # 7) filas e consumidores -------------------------------------------
    dizer("\n-- 7. profundidade das filas e consumidores (management API) --")
    relatorio["filas"] = ler_profundidade_filas(
        args.rabbitmq_api, args.rabbitmq_usuario, args.rabbitmq_senha
    )
    relatorio["consumidores"] = contar_consumidores(
        args.rabbitmq_api, args.rabbitmq_usuario, args.rabbitmq_senha
    )
    dizer(f"   filas: {relatorio['filas']}")
    dizer(f"   consumidores por fila: {relatorio['consumidores']}")

    relatorio["renovacoes_de_token"] = sessao.renovacoes
    absorvidos = dict(_ABSORVIDOS)
    relatorio["throttling_absorvido"] = {
        "respostas_429": absorvidos["429"],
        "espera_total_s": round(absorvidos["espera_429_s"], 2),
        "tolerado": args.tolerar_429,
        "invalido": absorvidos["429"] > args.tolerar_429,
    }
    relatorio["indisponibilidade_absorvida"] = {
        "tentativas": absorvidos["conexao_indisponivel"],
        "espera_total_s": round(absorvidos["espera_conexao_s"], 2),
    }

    invalido = relatorio["throttling_absorvido"]["invalido"]
    if invalido:
        # Sai com erro **depois** de imprimir o relatório: o número existe e
        # está contaminado, e escondê-lo só faria o jogador copiar para o
        # README um número que na verdade mede o throttle da API.
        print(
            f"\n!! ATENÇÃO: {absorvidos['429']} resposta(s) 429 foram absorvidas "
            f"({relatorio['throttling_absorvido']['espera_total_s']}s de espera).\n"
            "!! As latências acima incluem essa espera e NÃO medem a "
            "mensageria.\n"
            "!! Suba o limite antes de medir, por exemplo:\n"
            "!!     $env:DRF_USER_RATE='2000/min'; docker compose up -d "
            "--force-recreate api\n"
            "!! (a variável precisa existir no MESMO comando do compose: sem "
            "ela o container volta ao padrão de 100/min)."
        )
    print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    return 1 if invalido else 0


if __name__ == "__main__":
    raise SystemExit(main())
