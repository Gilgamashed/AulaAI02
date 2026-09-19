from fastapi import APIRouter, HTTPException, Path

from ..responses import ApiResponse, ok
from ..schemas import SKU_PATTERN, InventoryItem, InventoryItemCreate, InventoryItemUpdate

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

# Acervo em memória apenas para exercitar o fluxo das rotas no scaffold.
# A persistência real fica para a Aula 6 (modelagem relacional).
_ITEMS: dict[str, InventoryItem] = {}

_SKU_DESCRIPTION = "SKU do produto, no formato da Aula 4 (ex.: XXXX-AAAA-BBBB)."


def _get_or_404(sku: str) -> InventoryItem:
    item = _ITEMS.get(sku)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item de inventário '{sku}' não encontrado")
    return item


@router.get(
    "",
    response_model=ApiResponse[list[InventoryItem]],
    summary="Lista os itens de inventário",
)
async def list_items() -> ApiResponse[list[InventoryItem]]:
    return ok(list(_ITEMS.values()))


@router.post(
    "",
    response_model=ApiResponse[InventoryItem],
    status_code=201,
    summary="Registra um item de inventário",
)
async def create_item(payload: InventoryItemCreate) -> ApiResponse[InventoryItem]:
    if payload.sku in _ITEMS:
        raise HTTPException(status_code=409, detail=f"SKU '{payload.sku}' já registrado")
    item = InventoryItem(**payload.model_dump())
    _ITEMS[item.sku] = item
    return ok(item)


@router.get(
    "/{sku}",
    response_model=ApiResponse[InventoryItem],
    summary="Obtém um item de inventário pelo SKU",
)
async def get_item(
    sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION),
) -> ApiResponse[InventoryItem]:
    return ok(_get_or_404(sku))


@router.patch(
    "/{sku}",
    response_model=ApiResponse[InventoryItem],
    summary="Atualiza parcialmente um item de inventário",
)
async def update_item(
    payload: InventoryItemUpdate,
    sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION),
) -> ApiResponse[InventoryItem]:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido para atualização")
    item = _get_or_404(sku)
    _ITEMS[sku] = item.model_copy(update=updates)
    return ok(_ITEMS[sku])


@router.delete(
    "/{sku}",
    status_code=204,
    summary="Remove um item de inventário",
)
async def delete_item(sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION)) -> None:
    _get_or_404(sku)
    del _ITEMS[sku]
