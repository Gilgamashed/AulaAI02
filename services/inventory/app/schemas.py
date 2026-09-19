from pydantic import BaseModel, Field

# Mesmo formato de SKU validado na Aula 4 (api/core/models.py: validate_sku),
# para manter consistência entre a API principal e o microsserviço de estoque.
SKU_PATTERN = r"^[A-Z]{2,4}-[A-Z0-9-]+$"


class HealthResponse(BaseModel):
    """Resposta padrão do healthcheck do serviço."""

    status: str = Field(default="ok", examples=["ok"])
    service: str = Field(examples=["synapseshop-inventory"])


class InventoryItemCreate(BaseModel):
    """Payload de criação de um item de inventário (domínio real).

    Sem banco de dados nesta fase (modelagem relacional é a Aula 6); os campos
    descrevem o estoque em si: quantidade disponível, reservada e nível de
    reposição.
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
    """Representação de um item de inventário residente em memória.

    O uso de dicionário em memória apenas exercita o fluxo das rotas no
    scaffold; a persistência real fica para a Aula 6.
    """
