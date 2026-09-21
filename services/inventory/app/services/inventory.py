"""Serviço de negócio do inventory — consome o repositório transacional.

Regras de domínio (matriz de status da Aula 5, mantida):
- SKU duplicado na criação -> 409 Conflict.
- PATCH sem campos -> 400 Bad Request.
- Recurso inexistente -> 404 Not Found.

Fronteira transacional: cada operação de escrita confirma o commit ao final e,
na falha, executa rollback para não deixar estado parcial.
"""

from fastapi import HTTPException

from ..models import InventoryItem
from ..repositories.inventory import InventoryRepository
from ..schemas import InventoryItemCreate, InventoryItemUpdate


class InventoryService:
    """Orquestra o repositório e controla as transações do domínio."""

    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def list_items(self) -> list[InventoryItem]:
        return self._repository.list()

    def get_item(self, sku: str) -> InventoryItem:
        item = self._repository.get_by_sku(sku)
        if item is None:
            detail = f"Item de inventário '{sku}' não encontrado"
            raise HTTPException(status_code=404, detail=detail)
        return item

    def create_item(self, payload: InventoryItemCreate) -> InventoryItem:
        if self._repository.get_by_sku(payload.sku) is not None:
            raise HTTPException(status_code=409, detail=f"SKU '{payload.sku}' já registrado")
        item = InventoryItem(**payload.model_dump())
        self._repository.create(item)
        self._commit()
        return item

    def update_item(self, sku: str, payload: InventoryItemUpdate) -> InventoryItem:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="Nenhum campo fornecido para atualização")
        item = self.get_item(sku)
        self._repository.update(item, updates)
        self._commit()
        return item

    def delete_item(self, sku: str) -> None:
        item = self.get_item(sku)
        self._repository.delete(item)
        self._commit()

    def _commit(self) -> None:
        """Confirma a transação; em caso de erro, desfaz e propaga a exceção."""
        try:
            self._repository.session.commit()
        except Exception:
            self._repository.session.rollback()
            raise
