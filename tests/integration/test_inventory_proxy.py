"""Integração do proxy admin-only do inventário (Aula 25 — complemento).

O proxy é a fronteira de segurança entre o navegador e o FastAPI: o Django
valida o JWT/papel ``admin`` e só então encaminha a operação. A chamada HTTP
ao microsserviço é substituída por um duplo para que a suíte não dependa de
rede nem do container ``inventory``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

_SKU = "INV-DEMO-001"


def _substituir_chamada(
    monkeypatch: pytest.MonkeyPatch,
    *,
    retorno: tuple[int, Any] | None = None,
    erro: Exception | None = None,
) -> list[tuple[str, str, Any]]:
    """Instala o duplo de ``chamar_inventario`` e devolve as chamadas feitas."""
    chamadas: list[tuple[str, str, Any]] = []

    def fake(metodo: str, caminho: str, payload: Any | None = None):
        chamadas.append((metodo, caminho, payload))
        if erro is not None:
            raise erro
        return retorno

    monkeypatch.setattr("core.inventory_proxy.chamar_inventario", fake)
    return chamadas


def test_proxy_sem_token_devolve_401(api_client):
    resposta = api_client.get("/api/v1/inventario/")

    assert resposta.status_code == 401


def test_proxy_usuario_comum_devolve_403(client_autenticado):
    resposta = client_autenticado.get("/api/v1/inventario/")

    assert resposta.status_code == 403


def test_proxy_admin_lista_e_preserva_envelope(client_admin, monkeypatch):
    corpo = {
        "status": "ok",
        "data": [{"id": 1, "sku": _SKU, "name": "Item", "quantity": 10}],
        "message": None,
    }
    chamadas = _substituir_chamada(monkeypatch, retorno=(200, corpo))

    resposta = client_admin.get("/api/v1/inventario/")

    assert resposta.status_code == 200
    assert resposta.json() == corpo
    assert chamadas == [("GET", "/api/v1/inventory", None)]


def test_proxy_admin_cria_e_encaminha_payload(client_admin, monkeypatch):
    payload = {"sku": _SKU, "name": "Item de demonstração", "quantity": 10}
    corpo = {**payload, "id": 1, "reserved": 0, "reorder_level": 0}
    chamadas = _substituir_chamada(
        monkeypatch,
        retorno=(201, {"status": "ok", "data": corpo, "message": None}),
    )

    resposta = client_admin.post("/api/v1/inventario/", payload, format="json")

    assert resposta.status_code == 201
    assert resposta.json()["data"]["sku"] == _SKU
    assert chamadas == [("POST", "/api/v1/inventory", payload)]


def test_proxy_admin_consulta_atualiza_e_remove_por_sku(client_admin, monkeypatch):
    chamadas = _substituir_chamada(
        monkeypatch,
        retorno=(200, {"status": "ok", "data": {"sku": _SKU}}),
    )

    assert client_admin.get(f"/api/v1/inventario/{_SKU}/").status_code == 200
    assert (
        client_admin.patch(
            f"/api/v1/inventario/{_SKU}/", {"quantity": 7}, format="json"
        ).status_code
        == 200
    )

    _substituir_chamada(monkeypatch, retorno=(204, None))
    remocao = client_admin.delete(f"/api/v1/inventario/{_SKU}/")

    assert remocao.status_code == 204
    assert remocao.content == b""
    assert chamadas == [
        ("GET", f"/api/v1/inventory/{_SKU}", None),
        ("PATCH", f"/api/v1/inventory/{_SKU}", {"quantity": 7}),
    ]


@pytest.mark.parametrize(
    ("status_code", "corpo"),
    [
        (400, {"status": "error", "message": "Payload inválido"}),
        (404, {"status": "error", "message": "SKU não encontrado"}),
        (409, {"status": "error", "message": "SKU já existe"}),
    ],
)
def test_proxy_preserva_erros_do_inventory(
    client_admin, monkeypatch, status_code, corpo
):
    _substituir_chamada(monkeypatch, retorno=(status_code, corpo))

    resposta = client_admin.get(f"/api/v1/inventario/{_SKU}/")

    assert resposta.status_code == status_code
    assert resposta.json() == corpo


def test_proxy_timeout_devolve_504(client_admin, monkeypatch):
    _substituir_chamada(monkeypatch, erro=httpx.TimeoutException("timeout"))

    resposta = client_admin.get("/api/v1/inventario/")

    assert resposta.status_code == 504
    assert "Tempo esgotado" in resposta.json()["message"]


def test_proxy_inventory_indisponivel_devolve_503(client_admin, monkeypatch):
    _substituir_chamada(monkeypatch, erro=httpx.ConnectError("fora do ar"))

    resposta = client_admin.get("/api/v1/inventario/")

    assert resposta.status_code == 503
    assert resposta.json()["status"] == "error"


def test_proxy_resposta_invalida_devolve_502(client_admin, monkeypatch):
    _substituir_chamada(monkeypatch, erro=ValueError("json inválido"))

    resposta = client_admin.get("/api/v1/inventario/")

    assert resposta.status_code == 502
    assert "resposta inválida" in resposta.json()["message"]


def test_proxy_rejeita_payload_nao_json(client_admin, monkeypatch):
    chamadas = _substituir_chamada(monkeypatch, retorno=(201, {"status": "ok"}))

    resposta = client_admin.post(
        "/api/v1/inventario/",
        data={"sku": _SKU, "name": "Item", "quantity": "1"},
    )

    assert resposta.status_code == 415
    assert chamadas == []
