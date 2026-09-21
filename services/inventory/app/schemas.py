from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Mesmo formato de SKU validado na Aula 4 (api/core/models.py: validate_sku),
# para manter consistência entre a API principal e o microsserviço de estoque.
SKU_PATTERN = r"^[A-Z]{2,4}-[A-Z0-9-]+$"


class HealthResponse(BaseModel):
    """Resposta padrão do healthcheck do serviço."""

    status: str = Field(default="ok", examples=["ok"])
    service: str = Field(examples=["synapseshop-inventory"])


class InventoryItemCreate(BaseModel):
    """Payload de criação de um item de inventário (domínio real).

    Aula 6 — o domínio continua o mesmo da Aula 5 (sku, name, quantity,
    reserved, reorder_level), agora persistido na tabela `inventory_items`.
    """

    sku: str = Field(
        pattern=SKU_PATTERN,
        examples=["APL-IP15-128"],
        description="SKU do produto, no formato da Aula 4 (ex.: XXXX-AAAA-BBBB).",
    )
    name: str = Field(min_length=1, examples=["iPhone 15 128GB"])
    quantity: int = Field(ge=0, examples=[10], description="Quantidade disponível em estoque.")
    reserved: int = Field(ge=0, default=0, examples=[0], description="Quantidade reservada.")
    reorder_level: int = Field(ge=0, default=0, examples=[5], description="Nível de reposição.")


class InventoryItemUpdate(BaseModel):
    """Payload parcial para atualizar um item de inventário (PATCH)."""

    name: str | None = Field(default=None, min_length=1)
    quantity: int | None = Field(default=None, ge=0)
    reserved: int | None = Field(default=None, ge=0)
    reorder_level: int | None = Field(default=None, ge=0)


class InventoryItem(InventoryItemCreate):
    """Representação de leitura de um item de inventário persistido.

    Aula 6 — além dos campos de negócio, expõe o id e os timestamps gerados
    pelo banco. `from_attributes` permite validar diretamente o objeto SQLAlchemy
    retornado pela camada de serviço.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(examples=[1])
    created_at: datetime
    updated_at: datetime
