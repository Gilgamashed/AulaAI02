"""Testes unitários das regras de negócio do inventory (Aula 12).

O `InventoryService` concentra a matriz de status da Aula 5 — SKU duplicado →
409, PATCH sem campos → 400, recurso inexistente → 404 — e a fronteira
transacional (commit/rollback). A spec da Aula 12 pede os serviços cobertos
nos caminhos felizes e de erro, e é o que esta suíte faz sobre o duplo em
memória do conftest: nenhuma sessão do SQLAlchemy é criada, e a contagem de
commit/rollback do `_SessaoFake` prova a fronteira da transação sem banco.
"""

import pytest
from fastapi import HTTPException

from app.schemas import InventoryItemCreate, InventoryItemUpdate

pytestmark = pytest.mark.unit


def _payload(**campos) -> InventoryItemCreate:
    return InventoryItemCreate(
        sku=campos.get("sku", "APL-IP15-128"),
        name=campos.get("name", "iPhone 15 128GB"),
        quantity=campos.get("quantity", 10),
        reserved=campos.get("reserved", 2),
        reorder_level=campos.get("reorder_level", 5),
    )


def test_listar_vazio(inventory_repository_fake, inventory_service_fake):
    assert inventory_service_fake.list_items() == []
    assert inventory_repository_fake.list() == []


def test_criar_item_caminho_feliz(inventory_repository_fake, inventory_service_fake):
    item = inventory_service_fake.create_item(_payload())

    assert item.id is not None
    assert item.sku == "APL-IP15-128"
    assert item.quantity == 10
    assert item.reserved == 2
    assert item.created_at is not None
    assert item.updated_at is not None
    assert inventory_repository_fake.get_by_sku("APL-IP15-128") is item
    assert inventory_repository_fake.session.commits == 1
    assert inventory_repository_fake.session.rollbacks == 0


def test_sku_duplicado_retorna_409(inventory_service_fake):
    inventory_service_fake.create_item(_payload())

    with pytest.raises(HTTPException) as erro:
        inventory_service_fake.create_item(_payload(quantity=12))

    assert erro.value.status_code == 409
    assert "APL-IP15-128" in erro.value.detail


@pytest.mark.parametrize(
    "existe",
    [pytest.param(True, id="sku-existente"), pytest.param(False, id="sku-inexistente")],
)
def test_buscar_por_sku(inventory_service_fake, existe):
    sku = "APL-IP15-128"
    if existe:
        inventory_service_fake.create_item(_payload())
        item = inventory_service_fake.get_item(sku)
        assert item.sku == sku
        return

    with pytest.raises(HTTPException) as erro:
        inventory_service_fake.get_item(sku)
    assert erro.value.status_code == 404
    assert sku in erro.value.detail


def test_patch_vazio_retorna_400(inventory_service_fake):
    inventory_service_fake.create_item(_payload())

    with pytest.raises(HTTPException) as erro:
        inventory_service_fake.update_item("APL-IP15-128", InventoryItemUpdate())

    assert erro.value.status_code == 400
    assert "Nenhum campo" in erro.value.detail


def test_patch_parcial_atualiza_so_campos_enviados(
    inventory_repository_fake, inventory_service_fake
):
    inventory_service_fake.create_item(_payload())

    atualizado = inventory_service_fake.update_item(
        "APL-IP15-128", InventoryItemUpdate(quantity=7, reorder_level=3)
    )

    assert atualizado.quantity == 7
    assert atualizado.reorder_level == 3
    # Campo não enviado permanece intacto.
    assert atualizado.name == "iPhone 15 128GB"
    assert inventory_repository_fake.session.commits == 2


def test_patch_em_sku_inexistente_retorna_404(inventory_service_fake):
    with pytest.raises(HTTPException) as erro:
        inventory_service_fake.update_item("NAO-EXISTE", InventoryItemUpdate(quantity=1))

    assert erro.value.status_code == 404


def test_delete_caminho_feliz(inventory_repository_fake, inventory_service_fake):
    inventory_service_fake.create_item(_payload())

    inventory_service_fake.delete_item("APL-IP15-128")

    assert inventory_repository_fake.get_by_sku("APL-IP15-128") is None
    assert inventory_repository_fake.session.commits == 2


def test_delete_inexistente_retorna_404(inventory_service_fake):
    with pytest.raises(HTTPException) as erro:
        inventory_service_fake.delete_item("NAO-EXISTE")

    assert erro.value.status_code == 404


def test_falha_no_commit_faz_rollback_e_propaga(
    inventory_repository_fake, inventory_service_fake
):
    inventory_repository_fake.session.falhar_commit = RuntimeError("banco fora do ar")

    with pytest.raises(RuntimeError):
        inventory_service_fake.create_item(_payload())

    assert inventory_repository_fake.session.commits == 1
    assert inventory_repository_fake.session.rollbacks == 1