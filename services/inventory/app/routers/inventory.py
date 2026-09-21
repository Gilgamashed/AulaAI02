from fastapi import APIRouter, Depends, Path

from ..dependencies import get_inventory_service
from ..responses import ApiResponse, ok
from ..schemas import SKU_PATTERN, InventoryItem, InventoryItemCreate, InventoryItemUpdate
from ..services.inventory import InventoryService

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

_SKU_DESCRIPTION = "SKU do produto, no formato da Aula 4 (ex.: XXXX-AAAA-BBBB)."


@router.get(
    "",
    response_model=ApiResponse[list[InventoryItem]],
    summary="Lista os itens de inventário",
)
async def list_items(
    service: InventoryService = Depends(get_inventory_service),
) -> ApiResponse[list[InventoryItem]]:
    items = [InventoryItem.model_validate(item) for item in service.list_items()]
    return ok(items)


@router.post(
    "",
    response_model=ApiResponse[InventoryItem],
    status_code=201,
    summary="Registra um item de inventário",
)
async def create_item(
    payload: InventoryItemCreate,
    service: InventoryService = Depends(get_inventory_service),
) -> ApiResponse[InventoryItem]:
    item = InventoryItem.model_validate(service.create_item(payload))
    return ok(item)


@router.get(
    "/{sku}",
    response_model=ApiResponse[InventoryItem],
    summary="Obtém um item de inventário pelo SKU",
)
async def get_item(
    sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION),
    service: InventoryService = Depends(get_inventory_service),
) -> ApiResponse[InventoryItem]:
    item = InventoryItem.model_validate(service.get_item(sku))
    return ok(item)


@router.patch(
    "/{sku}",
    response_model=ApiResponse[InventoryItem],
    summary="Atualiza parcialmente um item de inventário",
)
async def update_item(
    payload: InventoryItemUpdate,
    sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION),
    service: InventoryService = Depends(get_inventory_service),
) -> ApiResponse[InventoryItem]:
    item = InventoryItem.model_validate(service.update_item(sku, payload))
    return ok(item)


@router.delete(
    "/{sku}",
    status_code=204,
    summary="Remove um item de inventário",
)
async def delete_item(
    sku: str = Path(pattern=SKU_PATTERN, description=_SKU_DESCRIPTION),
    service: InventoryService = Depends(get_inventory_service),
) -> None:
    service.delete_item(sku)
