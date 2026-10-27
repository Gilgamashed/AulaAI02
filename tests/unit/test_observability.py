"""Testes unitários da normalização de métricas (Aula 20)."""

from __future__ import annotations

import pytest

from core.observability import _deve_instrumentar, _normalizar_endpoint

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "esperado"),
    [
        ("/api/v1/items/", "/api/v1/items/"),
        ("/api/v1/items/42/", "/api/v1/items/{id}/"),
        ("/api/v1/items/42", "/api/v1/items/{id}"),
        ("/api/v1/items/42/detalhes/", "/api/v1/items/{id}/detalhes/"),
        (
            "/api/v1/pedidos/0f8fad5b-d9cb-469f-a165-70867728950e/",
            "/api/v1/pedidos/{id}/",
        ),
        ("/api/v1/items/abc-123/", "/api/v1/items/abc-123/"),
        ("", ""),
    ],
)
def test_normalizar_endpoint(path, esperado):
    assert _normalizar_endpoint(path) == esperado


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/items/",
        "/api/v1/pedidos/1/",
        "/api/v1/cache/metrics/",
    ],
)
def test_instrumenta_rotas_da_api(path):
    assert _deve_instrumentar(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/admin/login/",
        "/admin/core/item/",
        "/static/admin/css/base.css",
        "/docs",
        "/redoc",
        "/",
        "",
    ],
)
def test_ignora_rotas_fora_da_api(path):
    assert _deve_instrumentar(path) is False


def test_middleware_registra_500_quando_a_view_levanta(monkeypatch):
    """A exceção sobe, mas a tentativa fica registrada como 500."""
    from django.test import RequestFactory

    from core.models import RequisicaoMetrica
    from core.observability import RegistrarMetricasMiddleware

    criadas: list[dict] = []

    def _get_response(request):
        raise RuntimeError("falha proposital")

    monkeypatch.setattr(
        RequisicaoMetrica.objects,
        "create",
        lambda **kwargs: criadas.append(kwargs),
    )

    middleware = RegistrarMetricasMiddleware(_get_response)
    request = RequestFactory().get("/api/v1/items/42/")

    with pytest.raises(RuntimeError, match="falha proposital"):
        middleware(request)

    assert len(criadas) == 1
    assert criadas[0]["status_code"] == 500
    assert criadas[0]["endpoint"] == "/api/v1/items/{id}/"
