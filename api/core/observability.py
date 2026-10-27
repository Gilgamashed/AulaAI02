"""Observabilidade — métricas de requisições (Aula 20).

O middleware grava uma linha em `core_requisicao_metrica` por requisição
atendida sob `/api/`. Ficam de fora `/health` (o healthcheck do Compose bate
a cada 10 s e dominaria a amostra), `/admin`, `/static`, docs e qualquer
outra rota que não seja tráfego da API.

Além da latência, a linha carrega os contadores de cache da **própria**
requisição. O coletor `core.cache_metrics` ganhou uma janela por thread para
isso: abrir antes da view e fechar depois dá o delta exato, sem chamada HTTP
ao endpoint administrativo de cache.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from .cache_metrics import cache_metrics

logger = logging.getLogger("core.observability")

_PREFIXO_API = "/api/"
_ID_RE = re.compile(r"/\d+(?=/|$)")
_UUID_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


def _deve_instrumentar(path: str) -> bool:
    """Somente rotas da API entram nas métricas (ver docstring do módulo)."""
    return bool(path) and path.startswith(_PREFIXO_API)


def _normalizar_endpoint(path: str) -> str:
    """Troca IDs por `{id}` para não explodir a cardinalidade de endpoints."""
    if not path:
        return path
    normalizado = _UUID_RE.sub("/{id}", path)
    return _ID_RE.sub("/{id}", normalizado)


class RegistrarMetricasMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or ""
        if not getattr(settings, "API_METRICS_ENABLED", True):
            return self.get_response(request)
        if not _deve_instrumentar(path):
            return self.get_response(request)

        inicio = time.perf_counter()
        cache_metrics.iniciar_requisicao()
        try:
            response = self.get_response(request)
        except Exception:
            latencia_ms = (time.perf_counter() - inicio) * 1000.0
            self._registrar(
                request.method,
                _normalizar_endpoint(path),
                500,
                latencia_ms,
                cache_metrics.finalizar_requisicao(),
            )
            raise

        latencia_ms = (time.perf_counter() - inicio) * 1000.0
        self._registrar(
            request.method,
            _normalizar_endpoint(path),
            getattr(response, "status_code", 0),
            latencia_ms,
            cache_metrics.finalizar_requisicao(),
        )
        return response

    @staticmethod
    def _registrar(
        metodo: str,
        endpoint: str,
        status_code: int,
        latencia_ms: float,
        cache: dict[str, int],
    ) -> None:
        # A métrica é acessória: uma falha ao gravá-la (banco fora, tabela
        # ainda não migrada) não pode derrubar a requisição do cliente.
        try:
            from .models import RequisicaoMetrica

            RequisicaoMetrica.objects.create(
                metodo=(metodo or "")[:10],
                endpoint=(endpoint or "")[:200],
                status_code=int(status_code) or 0,
                latencia_ms=float(latencia_ms),
                cache_hits=cache.get("hits", 0),
                cache_misses=cache.get("misses", 0),
                cache_bypasses=cache.get("bypasses", 0),
            )
        except Exception:
            logger.debug("Falha ao registrar métrica de requisição", exc_info=True)
