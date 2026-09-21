"""inventory_items — tabela de estoque do microserviço inventory

Revision ID: a7f9e2c1b4d8
Revises:
Create Date: 2026-09-21 00:00:00.000000

Espelha fielmente o modelo `InventoryItem` (models.py): PK BigInteger, índice
único em SKU (índice essencial + integridade) e CHECKs de quantidades
não-negativas. O downgrade remove o índice e a tabela de forma reversível.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7f9e2c1b4d8"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria a tabela `inventory_items` com integridade e índices."""
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "sku",
            sa.String(length=100),
            nullable=False,
            comment="SKU no formato XXXX-AAAA-BBBB (padrão da Aula 4).",
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reorder_level", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_items_quantity_non_negative"),
        sa.CheckConstraint("reserved >= 0", name="ck_inventory_items_reserved_non_negative"),
        sa.CheckConstraint("reorder_level >= 0", name="ck_inventory_items_reorder_level_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Índice essencial: único (integridade) e usado nos lookups por SKU.
    op.create_index("ix_inventory_items_sku", "inventory_items", ["sku"], unique=True)


def downgrade() -> None:
    """Rollback seguro: remove índice e tabela."""
    op.drop_index("ix_inventory_items_sku", table_name="inventory_items")
    op.drop_table("inventory_items")