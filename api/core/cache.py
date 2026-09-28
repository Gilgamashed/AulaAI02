"""Cache-aside com Redis (Aula 8) — módulo central do padrão.

O padrão **cache-aside** delega à aplicação a responsabilidade de popular o
cache; o cache nunca é escrito "por conta própria" na leitura nem notificado
de alterações pelo banco. O fluxo de uma leitura é sempre o mesmo:

    requisição
        │
        ├─ 1) GET <chave> no Redis
        │      ├─ HIT  → devolve o payload serializado (sem tocar no PostgreSQL)
        │      └─ MISS → 2) consulta ao PostgreSQL
        │                    └─ 3) SET <chave> <payload> EX <ttl>
        │                    └─ 4) devolve o payload ao cliente
        ▼
    resposta

Por que "aside" (à parte) e não write-through/write-back?

* O cache **nunca é a fonte da verdade**: se ele for apagado (deploy, restart,
  `FLUSHDB`), a aplicação simplesmente repopula — a correção fica no banco.
* Uma falha no Redis não pode derrubar a API: todo acesso é protegido e, em
  caso de erro, a requisição segue para o PostgreSQL (**fail-open**).
* Escritas ficam em um único caminho (o sinal de domínio em `signals.py`),
  em vez de duplicadas em cada ponto de escrita.

Convenção de chaves (o cabeçalho do README repete esta tabela):

| Chave                        | Onde                              | TTL  |
| ---------------------------- | --------------------------------- | ---- |
| `item:list:g<geracao>:<fp>`  | `GET /api/v1/items/`             | 60 s |
| `item:<id>`                  | `GET /api/v1/items/{id}/`        | 300 s|
| `item:<id>:detalhes`         | `GET /api/v1/items/{id}/detalhes/`| 300 s|
| `categoria:list:g<geracao>:<fp>` | `GET /api/v1/categories/`     | 60 s |
| `categoria:<id>`             | `GET /api/v1/categories/{id}/`   | 300 s|
| `item:list:geracao`          | contador de geração (chave-meta) | —    |

Sobre a **geração** (`g<geracao>`): a listagem tem muitas variantes (página,
filtros, busca, ordenação), então invalidar "a listagem" exigiria apagar
várias chaves. Em vez disso, cada chave carrega o valor atual de um contador e
a invalidação é um único `INCR` (O(1)). As chaves da geração antiga ficam
órfãs e morrem sozinhas pelo TTL de 60 s — o TTL é a rede de segurança.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from redis.exceptions import RedisError

from .cache_metrics import BYPASS, ERRO, HIT, MISS, cache_metrics

# Logger dedicado: uma linha JSON por evento de cache (ver settings.LOGGING).
logger = logging.getLogger("core.cache")

# Namespaces = nomes lógicos dos recursos, usados como rótulo nas métricas
# (o README mapeia namespace -> endpoint).
NS_ITEM_LIST = "item:list"
NS_ITEM_DETALHE = "item:detalhe"
NS_ITEM_DETALHES = "item:detalhes"
NS_CATEGORY_LIST = "categoria:list"
NS_CATEGORY_DETAIL = "categoria:detalhe"

# Prefixo de chave por entidade (usado nas chaves de registro específico).
PREFIXO_ITEM = "item"
PREFIXO_CATEGORY = "categoria"

# Sufixo da chave-meta que guarda o contador de geração de uma listagem.
SUFIXO_GERACAO = "geracao"

# Parâmetros de query que alteram o PAYLOAD de uma listagem. Só eles entram
# no fingerprint da chave: qualquer outro parâmetro irrelevante não deve
# multiplicar as variantes de cache.
PARAMETROS_LISTAGEM = frozenset(
    {"page", "page_size", "search", "ordering"}
)
PARAMETROS_LISTAGEM_ITEM = PARAMETROS_LISTAGEM | {
    "category",
    "is_active",
    "min_price",
    "max_price",
}

# Parâmetros de filtro/busca/ordenação que o `get_object()` do DRF também
# aplica na rota de **detalhe**: mandá-los faz a consulta ao banco devolver
# 404 quando o registro não satisfaz o filtro (ex.: `/items/1/?min_price=999999`).
# Como a chave `item:<id>` não carrega esses parâmetros, uma resposta 200
# cacheada passaria a servir um caso que hoje é 404 — por isso a rota de
# detalhe ignora o cache quando algum deles vem na querystring.
PARAMETROS_FILTRO_ITEM = frozenset(
    {"category", "is_active", "min_price", "max_price", "search", "ordering"}
)
PARAMETROS_FILTRO_CATEGORY = frozenset({"search", "ordering"})


# =====================================================================
# Configuração lida do settings.py
# =====================================================================
def cache_habilitado() -> bool:
    """`CACHE_ENABLED` do ambiente — o switch do baseline de desempenho."""
    return bool(getattr(settings, "CACHE_ENABLED", True))


def ttl_listagem() -> int:
    return int(getattr(settings, "CACHE_TTL_LIST", 60))


def ttl_detalhe() -> int:
    return int(getattr(settings, "CACHE_TTL_DETAIL", 300))


def redis_url_publicavel() -> str:
    """URL do Redis com a **credencial redigida**, para exibir nas métricas.

    A URL pode conter usuário/senha (`redis://:senha@host:6379/1`); como o
    endpoint de métricas é administrativo, mesmo assim nada de segredo é
    exposto.
    """
    url = getattr(settings, "REDIS_URL", "")
    partes = urlsplit(url)
    if not partes.netloc:
        return url
    host = partes.hostname or ""
    if partes.port:
        host = f"{host}:{partes.port}"
    return urlunsplit((partes.scheme, f"***@{host}", partes.path, "", ""))


# =====================================================================
# Construção das chaves
# =====================================================================
def query_fingerprint(parametros: dict[str, Any]) -> str:
    """Assinatura curta e determinística dos parâmetros de uma requisição.

    Duas requisições com os mesmos parâmetros **precisam** gerar a mesma
    chave; ordens diferentes de query string não podem gerar chaves
    diferentes. Por isso o JSON é montado com `sort_keys=True` antes do hash.
    O hash (sha256, 12 hex) serve para não estourar o limite de 250
    caracteres por chave do Redis e para não vazar os valores dos parâmetros.
    """
    bruto = json.dumps(parametros, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]


def fingerprint_de_lista(
    request, parametros_permitidos: frozenset[str] = PARAMETROS_LISTAGEM_ITEM
) -> str:
    """Fingerprint da listagem a partir da querystring da requisição.

    Só os parâmetros de `parametros_permitidos` entram na chave. O usuário
    **não** entra: as listagens do catálogo são públicas (Aula 7) e o payload
    não varia por sessão.
    """
    selecionados = {
        chave: request.query_params.get(chave, "")
        for chave in sorted(parametros_permitidos)
        if request.query_params.get(chave, "") != ""
    }
    return query_fingerprint(selecionados)


def tem_parametros_de_filtro(
    request, parametros: frozenset[str] = PARAMETROS_FILTRO_ITEM
) -> bool:
    """A rota de detalhe deve ignorar o cache? (ver PARAMETROS_FILTRO_ITEM)."""
    return any(
        request.query_params.get(parametro, "") != "" for parametro in parametros
    )


def list_generation(namespace: str) -> int | None:
    """Lê (criando se preciso) o contador de geração de uma listagem.

    A chave-meta é gravada sem TTL (`timeout=None`): é infraestrutura do
    cache, não dado de negócio, e perder o valor apenas reiniciaria a
    numeração das chaves — o que é seguro, pois o valor antigo ainda está
    no Redis. `None` significa "Redis indisponível": quem chamou deve
    seguir sem cache (fail-open).
    """
    chave_meta = f"{namespace}:{SUFIXO_GERACAO}"
    try:
        # `add` só grava se a chave ainda não existir (nx=True) — evita
        # sobrescrever a geração atual com 0 em uma corrida.
        cache.add(chave_meta, 1, timeout=None)
        return int(cache.get(chave_meta) or 1)
    except (RedisError, ValueError) as exc:
        _log_erro(
            namespace,
            f"{chave_meta}",
            "falha ao ler o contador de geração",
            detalhe=repr(exc),
        )
        return None


def list_key(namespace: str, fingerprint: str) -> str | None:
    """Monta `<namespace>:g<geracao>:<fingerprint>`; `None` se o Redis falhar."""
    geracao = list_generation(namespace)
    if geracao is None:
        return None
    return f"{namespace}:g{geracao}:{fingerprint}"


def detail_key(prefixo: str, entity_id: Any) -> str:
    """Chave de acesso a um registro específico: `item:12`, `categoria:7`."""
    return f"{prefixo}:{entity_id}"


def details_key(prefixo: str, entity_id: Any) -> str:
    """Chave da consulta pesada de um registro: `item:12:detalhes`."""
    return f"{detail_key(prefixo, entity_id)}:detalhes"


# =====================================================================
# O padrão cache-aside
# =====================================================================
def to_json_safe(payload: Any) -> Any:
    """Normaliza o payload para tipos JSON nativos antes de ir para o Redis.

    O serializador padrão do backend (`pickle`) gravaria a estrutura como ela
    veio do DRF — e `ReturnList`/`ReturnDict` carregam referência ao
    `Serializer` que os produziu. Isso tornaria a chave um pickle frágil e
    gigante (ligado à versão do DRF). A ida-e-volta por JSON converte para
    `dict`/`list`/`str`/`float`, que é exatamente o que o `JSONRenderer`
    entregaria ao cliente, e mantém `Decimal` como string (mesma
    representação do renderer).
    """
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


def cache_aside(
    chave: str | None,
    ttl: int,
    namespace: str,
    producer: Callable[[], Any],
) -> Any:
    """Executa o padrão cache-aside e devolve o payload (do cache ou do banco).

    `chave=None` significa "não há cache possível" (Redis fora do ar ou
    cache desabilitado) — nesse caso o produtor roda direto. `producer` só é
    chamado no MISS; se ele levantar exceção (ex.: 404 do `get_object`), a
    exceção sobe e **nada é cacheado** — erros não viram dado cacheado.
    """
    if chave is None or not cache_habilitado():
        motivo = "redis indisponivel" if chave is None else "cache desabilitado"
        cache_metrics.record(namespace, BYPASS)
        _log(
            BYPASS,
            namespace,
            chave or "-",
            motivo=motivo,
        )
        return producer()

    inicio = time.perf_counter()
    try:
        cacheado = cache.get(chave)
    except RedisError as exc:
        # Fail-open: o Redis não derruba a leitura da API.
        _log_erro(namespace, chave, "falha na leitura do cache", detalhe=repr(exc))
        cache_metrics.record(namespace, ERRO)
        return producer()

    latencia_ms = _ms(inicio)
    if cacheado is not None:
        # HIT: o payload é devolvido sem consultar o PostgreSQL.
        cache_metrics.record(namespace, HIT)
        _log(HIT, namespace, chave, latencia_ms=latencia_ms)
        return cacheado

    # MISS: o dado vem da fonte de verdade e preenche o cache.
    cache_metrics.record(namespace, MISS)
    inicio_preenchimento = time.perf_counter()
    payload = producer()
    preenchimento_ms = _ms(inicio_preenchimento)
    try:
        cache.set(chave, to_json_safe(payload), ttl)
    except RedisError as exc:
        _log_erro(namespace, chave, "falha ao gravar no cache", detalhe=repr(exc))
    _log(
        MISS,
        namespace,
        chave,
        ttl_s=ttl,
        latencia_ms=latencia_ms,
        preenchimento_ms=preenchimento_ms,
    )
    return payload


# =====================================================================
# Invalidação orientada a eventos de domínio
# =====================================================================
def invalidate_detail(chave: str, namespace: str, evento: str) -> None:
    """Invalida a chave de um registro específico (`DEL`).

    O conjunto de chaves de detalhe é conhecido (uma por registro), então o
    `delete` é determinístico e dispensa varrer o keyspace por padrão
    (wildcard).
    """
    try:
        removida = cache.delete(chave)
    except RedisError as exc:
        _log_erro(namespace, chave, "falha ao invalidar detalhe", detalhe=repr(exc))
        return
    cache_metrics.record_invalidation(namespace)
    _log(
        "invalidacao",
        namespace,
        chave,
        evento=evento,
        motivo=(
            f"registro alterado: chave {chave} removida"
            if removida
            else "chave já expirada (TTL) ou nunca preenchida"
        ),
    )


def invalidate_list(namespace: str, evento: str) -> None:
    """Invalida **todas** as variantes de uma listagem com um único `INCR`.

    O contador `namespace:geracao` é incrementado: as próximas leituras já
    montam chaves com a geração nova (MISS) e as chaves antigas ficam
    órfãs, morrendo pelo TTL. Custo O(1), sem `SCAN`/`KEYS`.
    """
    chave_meta = f"{namespace}:{SUFIXO_GERACAO}"
    try:
        # Sem `add` aqui: se a chave-meta não existir (Redis reiniciado), o
        # `incr` falha e a criação com valor 1 já inicia a geração nova.
        nova_geracao = cache.incr(chave_meta)
    except (RedisError, ValueError):
        try:
            cache.add(chave_meta, 1, timeout=None)
            nova_geracao = 1
        except RedisError as exc:
            _log_erro(
                namespace, chave_meta, "falha ao invalidar listagem", detalhe=repr(exc)
            )
            return
    cache_metrics.record_invalidation(namespace)
    _log(
        "invalidacao",
        namespace,
        chave_meta,
        evento=evento,
        motivo=f"listagem invalidada: nova geração g{nova_geracao}",
    )


def bypass(namespace: str, motivo: str) -> None:
    """Registra uma consulta que **não** usa cache (com a justificativa)."""
    cache_metrics.record(namespace, BYPASS)
    _log(BYPASS, namespace, "-", motivo=motivo)


# =====================================================================
# Logs estruturados (uma linha JSON por evento)
# =====================================================================
def _ms(inicio: float) -> float:
    return round((time.perf_counter() - inicio) * 1000, 3)


def _log(
    resultado: str,
    namespace: str,
    chave: str,
    evento: str | None = None,
    motivo: str | None = None,
    ttl_s: int | None = None,
    latencia_ms: float | None = None,
    preenchimento_ms: float | None = None,
) -> None:
    """Emite o evento de cache no logger estruturado `core.cache`."""
    logger.info(
        "cache %s",
        resultado,
        extra={
            "evento": evento or "CacheLookup",
            "namespace": namespace,
            "chave": chave,
            "resultado": resultado,
            "ttl_s": ttl_s,
            "latencia_ms": latencia_ms,
            "preenchimento_ms": preenchimento_ms,
            "motivo": motivo,
        },
    )


def _log_erro(namespace: str, chave: str, motivo: str, detalhe: str) -> None:
    """Falha do Redis é `warning` (a API degradou, não caiu)."""
    logger.warning(
        motivo,
        extra={
            "evento": "CacheDegradado",
            "namespace": namespace,
            "chave": chave,
            "resultado": ERRO,
            "motivo": motivo,
            "detalhe": detalhe,
        },
    )
