"""Integração HTTP do microsserviço inventory (Aula 12).

As rotas rodam de verdade (FastAPI + TestClient), mas a dependência
`get_inventory_service` é substituída pelo serviço sobre o repositório falso
do conftest — exatamente o que o `settings_test` documenta: nenhum teste deste
repositório depende de o Alembic ter rodado.

O envelope `{status, data, message}` e o handler de validação (422 → 400) são
parte da superfície pública do serviço, então também são exercitados aqui.
"""

import pytest

pytestmark = pytest.mark.integration

_SKU = "APL-IP15-128"


def _criar(client, sku=_SKU, quantity=5, name=None):
    return client.post(
        "/api/v1/inventory",
        json={"sku": sku, "name": name or f"Item {sku}", "quantity": quantity},
    )


def test_health(inventory_client):
    resposta = inventory_client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok", "service": "synapseshop-inventory"}


def test_lista_inicial_vazia(inventory_client):
    resposta = inventory_client.get("/api/v1/inventory")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["data"] == []


def test_criar_e_consultar_por_sku(inventory_client):
    criacao = _criar(inventory_client)

    assert criacao.status_code == 201
    dados = criacao.json()["data"]
    assert dados["sku"] == _SKU
    assert dados["id"] is not None
    assert dados["reserved"] == 0  # default do schema

    consulta = inventory_client.get(f"/api/v1/inventory/{_SKU}")
    assert consulta.status_code == 200
    assert consulta.json()["data"]["sku"] == _SKU


def test_sku_duplicado_retorna_409(inventory_client):
    _criar(inventory_client)

    resposta = _criar(inventory_client)

    assert resposta.status_code == 409
    corpo = resposta.json()
    assert corpo["status"] == "error"
    assert _SKU in corpo["message"]


def test_sku_inexistente_retorna_404(inventory_client):
    resposta = inventory_client.get("/api/v1/inventory/NAO-EXISTE")

    assert resposta.status_code == 404
    assert resposta.json()["status"] == "error"


def test_patch_vazio_retorna_400(inventory_client):
    _criar(inventory_client)

    resposta = inventory_client.patch(f"/api/v1/inventory/{_SKU}", json={})

    assert resposta.status_code == 400
    assert "Nenhum campo" in resposta.json()["message"]


def test_patch_parcial_atualiza_so_campos_enviados(inventory_client):
    _criar(inventory_client)

    resposta = inventory_client.patch(f"/api/v1/inventory/{_SKU}", json={"quantity": 3})

    assert resposta.status_code == 200
    dados = resposta.json()["data"]
    assert dados["quantity"] == 3
    assert dados["name"] == f"Item {_SKU}"  # campo não enviado permaneceu


def test_patch_em_sku_inexistente_retorna_404(inventory_client):
    resposta = inventory_client.patch(
        "/api/v1/inventory/NAO-EXISTE", json={"quantity": 1}
    )

    assert resposta.status_code == 404


def test_delete_e_consulta_posterior_404(inventory_client):
    _criar(inventory_client)

    remocao = inventory_client.delete(f"/api/v1/inventory/{_SKU}")
    assert remocao.status_code == 204

    consulta = inventory_client.get(f"/api/v1/inventory/{_SKU}")
    assert consulta.status_code == 404


def test_sku_em_formato_invalido_retorna_400(inventory_client):
    resposta = inventory_client.post(
        "/api/v1/inventory",
        json={"sku": "invalido", "name": "Item", "quantity": 1},
    )

    assert resposta.status_code == 400
    corpo = resposta.json()
    assert corpo["status"] == "error"
    assert "Payload ou parâmetro inválido" == corpo["message"]


def test_path_com_sku_invalido_retorna_400(inventory_client):
    resposta = inventory_client.get("/api/v1/inventory/formato-errado")

    assert resposta.status_code == 400
    assert resposta.json()["status"] == "error"


def test_quantidade_negativa_retorna_400(inventory_client):
    resposta = inventory_client.post(
        "/api/v1/inventory",
        json={"sku": _SKU, "name": "Item", "quantity": -1},
    )

    assert resposta.status_code == 400
    assert resposta.json()["status"] == "error"