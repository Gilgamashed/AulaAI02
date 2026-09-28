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

    def _namespace(self, namespace: str) -> NamespaceMetrics:
        # Chamado já sob o lock.
        return self._namespaces.setdefault(namespace, NamespaceMetrics())

    def record(self, namespace: str, resultado: str) -> None:
        """Registra o desfecho de uma consulta ao cache em um namespace."""
        with self._lock:
            contadores = self._namespace(namespace)
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


# Instância única do processo: é ela que `core/cache.py` alimenta e que a
# view de métricas (`/api/v1/cache/metrics/`) lê.
cache_metrics = CacheMetrics()
