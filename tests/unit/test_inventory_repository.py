"""Testes unitários do repositório do inventory (Aula 12).

O `InventoryRepository` é a fronteira de dados do microsserviço. Aqui o
repositório REAL roda contra um SQLite em memória (uma conexão só, via
`StaticPool`), exercitando o mesmo modelo e o mesmo código que o PostgreSQL
de produção usa — sem depender de o Alembic ter criado a tabela (a promessa
do `settings_test`: nenhum teste deste repositório exige o Alembic).

Os testes HTTP, por outro lado, usam o duplo do conftest; é este arquivo
quem cobre o módulo `app/repositories/inventory.py` de verdade.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import InventoryItem
from app.repositories.inventory import InventoryRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sessao = Sessao()
    yield sessao
    sessao.close()
    engine.dispose()


@pytest.fixture
def repositorio(session) -> InventoryRepository:
    return InventoryRepository(session)


_PROXIMO_ID = 0


def _item(sku: str = "APL-IP15-128", **campos) -> InventoryItem:
    global _PROXIMO_ID
    _PROXIMO_ID += 1
    return InventoryItem(
        id=_PROXIMO_ID,
        sku=sku,
        name=campos.get("name", "iPhone 15 128GB"),
        quantity=campos.get("quantity", 10),
        reserved=campos.get("reserved", 0),
        reorder_level=campos.get("reorder_level", 5),
    )


def test_criar_e_recuperar_por_sku(repositorio):
    item = _item()
    repositorio.create(item)

    assert item.id is not None
    assert repositorio.get_by_sku("APL-IP15-128") is item


def test_buscar_por_sku_inexistente_retorna_none(repositorio):
    assert repositorio.get_by_sku("NAO-EXISTE") is None


def test_lista_ordenada_por_insercao(repositorio):
    primeiro = _item(sku="APL-IP15-128")
    segundo = _item(sku="APL-IP15-256", name="iPhone 15 256GB")
    repositorio.create(primeiro)
    repositorio.create(segundo)

    itens = repositorio.list()

    assert [item.id for item in itens] == [primeiro.id, segundo.id]
    assert len(itens) == 2


def test_update_parcial_aplica_so_campos_enviados(repositorio):
    item = _item()
    repositorio.create(item)

    repositorio.update(item, {"quantity": 4})

    assert item.quantity == 4
    assert item.name == "iPhone 15 128GB"


def test_delete_remove_o_item(repositorio):
    item = _item()
    repositorio.create(item)

    repositorio.delete(item)

    assert repositorio.get_by_sku("APL-IP15-128") is None


def test_sku_unico_e_garantido_pelo_banco(repositorio, session):
    repositorio.create(_item())
    session.flush()

    with pytest.raises(IntegrityError):
        repositorio.create(_item(name="Outro item"))