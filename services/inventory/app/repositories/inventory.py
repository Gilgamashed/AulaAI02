"""Repositório transacional do domínio inventory.

Responsabilidade única: acesso a dados. O repositório recebe uma `Session` do
SQLAlchemy e expõe operações atômicas (CRUD). A fronteira de transação
(commit/rollback) pertence ao serviço de negócio, que orquestra o repositório.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import InventoryItem


class InventoryRepository:
    """Operações de persistência de `InventoryItem` em `inventory_items`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, item: InventoryItem) -> InventoryItem:
        """Persiste um novo item (insert pendente até o commit do serviço)."""
        self.session.add(item)
        self.session.flush()
        return item

    def get_by_sku(self, sku: str) -> InventoryItem | None:
        """Busca pontual por SKU — usa o índice único `ix_inventory_items_sku`."""
        return self.session.scalar(select(InventoryItem).where(InventoryItem.sku == sku))

    def list(self) -> list[InventoryItem]:
        """Lista todos os itens, ordenados por inserção (id)."""
        return list(self.session.scalars(select(InventoryItem).order_by(InventoryItem.id)))

    def update(self, item: InventoryItem, updates: dict[str, object]) -> InventoryItem:
        """Aplica atualização parcial em um item já carregado da sessão."""
        for field, value in updates.items():
            setattr(item, field, value)
        self.session.flush()
        return item

    def delete(self, item: InventoryItem) -> None:
        """Marca um item para exclusão (delete pendente até o commit)."""
        self.session.delete(item)
        self.session.flush()
