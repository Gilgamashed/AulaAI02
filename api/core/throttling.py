"""Throttling do DRF desacoplado do Redis (Aula 8).

O `SimpleRateThrottle` do DRF usa SEMPRE o cache `default`
(`SimpleRateThrottle.cache = default_cache`); não existe uma setting
`THROTTLE_CACHE` para trocá-lo. Como a Aula 8 transformou o cache `default`
em Redis, as cotas passariam a depender da disponibilidade do Redis: qualquer
falha dele viraria HTTP 500 em TODA requisição (o `cache.get` do throttler
explodiria antes de a view ser executada) — exatamente o oposto do fail-open do
cache-aside.

Estas classes mantêm o comportamento de cotas da Aula 7 (estado por processo,
via LocMemCache) e continuam funcionando com o Redis fora do ar.
"""

from django.core.cache import caches
from rest_framework.throttling import (
    AnonRateThrottle,
    ScopedRateThrottle,
    UserRateThrottle,
)

# Alias definido em `config.settings.CACHES`; os fingerprints das cotas ficam
# assim isolados das chaves de domínio (`item:*`, `categoria:*`).
CACHE_THROTTLE = caches["throttle"]


class ThrottleMemoriaAnon(AnonRateThrottle):
    """Cota de anônimos (`anon`, padrão 20/min) em memória."""

    cache = CACHE_THROTTLE


class ThrottleMemoriaUser(UserRateThrottle):
    """Cota de autenticados (`user`, padrão 100/min) em memória."""

    cache = CACHE_THROTTLE


class ThrottleMemoriaScope(ScopedRateThrottle):
    """Cota por escopo (`login`, padrão 5/min) em memória."""

    cache = CACHE_THROTTLE
