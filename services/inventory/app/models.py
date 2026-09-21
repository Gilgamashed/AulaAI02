"""Modelo relacional do domínio inventory (tabela `inventory_items`).

Aula 6 — o estoque deixa de ser um dicionário em memória e passa a ser
persistido no PostgreSQL, compartilhando o banco com o Django. Esta tabela é
governada exclusivamente pelo Alembic.

Modelagem:
- PK `id` (BigInteger, autoincrement) — integridade entidade.
- UNIQUE INDEX em `sku` — índice essencial: única chave de consulta das rotas
  (get/patch/delete por SKU) e garantia de unicidade (integridade).
- NOT NULL em todos os campos de negócio.
- CHECK `>= 0` em quantity/reserved/reorder_level — espelha no banco o `ge=0`
  validado pelo Pydantic (integridade consistente entre API e dados).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class InventoryItem(Base):
    """Item de estoque persistido em `inventory_items`."""

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="SKU no formato XXXX-AAAA-BBBB (padrão da Aula 4).",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reorder_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Índice essencial: único (garante unicidade) e usado em todos os lookups por SKU.
        Index("ix_inventory_items_sku", "sku", unique=True),
        CheckConstraint("quantity >= 0", name="ck_inventory_items_quantity_non_negative"),
        CheckConstraint("reserved >= 0", name="ck_inventory_items_reserved_non_negative"),
        CheckConstraint("reorder_level >= 0", name="ck_inventory_items_reorder_level_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<InventoryItem sku={self.sku!r} quantity={self.quantity}>"
