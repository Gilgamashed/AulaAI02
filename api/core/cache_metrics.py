"""Métricas de eficácia do cache (Aula 8).

A spec pede a métrica de **hit rate** (`total_hits / total_lookups`) exposta
por endpoint. Aqui mantemos contadores em memória, por *namespace* de cache
(que corresponde 1:1 aos endpoints instrumentados), com três estados
distintos — a distinção é o que dá utilidade operacional à métrica:

| Estado    | Significado                                                  |
| --------- | ------------------------------------------------------------ |
| `hit`     | a chave existia e foi servida sem tocar no PostgreSQL        |
| `miss`    | a chave não existia; o dado veio do banco e preencheu o cache |
| `bypass`  | o cache foi deliberadamente ignorado (CACHE_ENABLED off, ou   |
|           | detalhe com filtros — o payload varyiria)                     |
| `erro`    | o Redis falhou; a API degradou para o banco (fail-open)      |

**Limite conhecido (documentado no README):** os contadores são *por
processo*. Com o gunicorn padrão (1 worker) a leitura é exata; se a API for
escalada para vários workers, cada processo conta a sua parte e o agregado é
a soma — aceitável para uma taxa de acerto agregada.

**Aula 20:** além do agregado por processo, o coletor mantém uma janela
*por thread* (`iniciar_requisicao`/`finalizar_requisicao`). O middleware de
métricas abre a janela antes da view e recolhe os deltas no fim, gravando
`cache_hits`/`cache_misses`/`cache_bypasses` na linha da requisição. É isso
que permite ao dashboard exibir a hit rate real sem chamar o endpoint
administrativo `/api/v1/cache/metrics/`.
"""

import threading
from dataclasses import asdict, dataclass

# Estados possíveis de uma consulta ao cache (usados como rótulos).
HIT = "hit"
MISS = "miss"
BYPASS = "bypass"
ERRO = "erro"
INVALIDACAO = "invalidação"


@dataclass
class NamespaceMetrics:
    """Contadores acumulados para um namespace (endpoint/recurso)."""

    lookups: int = 0
    hits: int = 0
    misses: int = 0
    bypasses: int = 0
    erros: int = 0
    invalidacoes: int = 0

    @property
    def hit_rate(self) -> float:
        """`total_hits / total_lookups` — 0.0 enquanto não houver lookup.

        Quando o cache está desligado (`bypass`), não há lookup no Redis;
        a taxa fica 0.0 em vez de dividir por zero.
        """
        if self.lookups == 0:
            return 0.0
        return round(self.hits / self.lookups, 4)

    def as_dict(self) -> dict:
        dados = asdict(self)
        dados["hit_rate"] = self.hit_rate
        return dados


class CacheMetrics:
    """Coletor thread-safe de métricas por namespace.

    A API Django roda sob gunicorn (workers em processos, mas o acesso pode
    ocorrer de threads) — o `Lock` garante que o `dict` interno não seja
    alterado enquanto outro request o lê.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._namespaces: dict[str, NamespaceMetrics] = {}
        # Contadores da requisição em curso nesta thread. O middleware da
        # Aula 20 abre e fecha a janela; a atribuição é por thread porque o
        # gunicorn atende requisições concorrentes em threads.
        self._local = threading.local()

    def _namespace(self, namespace: str) -> NamespaceMetrics:
        # Chamado já sob o lock.
        return self._namespaces.setdefault(namespace, NamespaceMetrics())

    def iniciar_requisicao(self) -> None:
        """Zera a janela da thread antes de a view executar."""
        self._local.ativo = True
        self._local.hits = 0
        self._local.misses = 0
        self._local.bypasses = 0

    def finalizar_requisicao(self) -> dict[str, int]:
        """Fecha a janela e devolve os contadores acumulados na requisição.

        Chamar sem uma janela aberta devolve zeros em vez de falhar: o
        middleware pode ser desligado por `API_METRICS_ENABLED`, e nesse caso
        ninguém abre a janela.
        """
        if not getattr(self._local, "ativo", False):
            return {"hits": 0, "misses": 0, "bypasses": 0}
        resultado = {
            "hits": self._local.hits,
            "misses": self._local.misses,
            "bypasses": self._local.bypasses,
        }
        self._local.ativo = False
        return resultado

    def _contar_na_requisicao(self, resultado: str) -> None:
        # Sem janela aberta (CLI, testes unitários, worker) não há a quem
        # atribuir o evento; o contador global continua sendo atualizado.
        if not getattr(self._local, "ativo", False):
            return
        if resultado == HIT:
            self._local.hits += 1
        elif resultado == MISS:
            self._local.misses += 1
        elif resultado == BYPASS:
            self._local.bypasses += 1

    def record(self, namespace: str, resultado: str) -> None:
        """Registra o desfecho de uma consulta ao cache em um namespace."""
        with self._lock:
            contadores = self._namespace(namespace)
            self._contar_na_requisicao(resultado)
            if resultado == BYPASS:
                contadores.bypasses += 1
                return
            # bypass não é um lookup: não entra no denominador da hit rate.
            contadores.lookups += 1
            if resultado == HIT:
                contadores.hits += 1
            elif resultado == MISS:
                contadores.misses += 1
            elif resultado == ERRO:
                contadores.erros += 1

    def record_invalidation(self, namespace: str) -> None:
        """Registra uma invalidação disparada por evento de domínio."""
        with self._lock:
            self._namespace(namespace).invalidacoes += 1

    def snapshot(self) -> dict[str, NamespaceMetrics]:
        """Cópia dos contadores (não expõe referências internas)."""
        with self._lock:
            return dict(self._namespaces)

    def total(self) -> NamespaceMetrics:
        """Soma dos contadores de todos os namespaces (visão global)."""
        with self._lock:
            agregado = NamespaceMetrics()
            for contadores in self._namespaces.values():
                agregado.lookups += contadores.lookups
                agregado.hits += contadores.hits
                agregado.misses += contadores.misses
                agregado.bypasses += contadores.bypasses
                agregado.erros += contadores.erros
                agregado.invalidacoes += contadores.invalidacoes
            return agregado

    def reset(self) -> None:
        """Zera todos os contadores (usado em demonstrações de aula)."""
        with self._lock:
            self._namespaces.clear()
            self._local.ativo = False
            self._local.hits = 0
            self._local.misses = 0
            self._local.bypasses = 0


# Instância única do processo: é ela que `core/cache.py` alimenta e que a
# view de métricas (`/api/v1/cache/metrics/`) lê.
cache_metrics = CacheMetrics()
