from fastapi import Depends, FastAPI

from .dependencies import ServiceInfo, get_service_info
from .handlers import register_exception_handlers
from .responses import ApiResponse, ok
from .routers import inventory
from .schemas import HealthResponse

app = FastAPI(
    title="SynapseShop — Inventory API",
    description="Microsserviço complementar de estoque (inventory) do MVP SynapseShop.",
    version="0.1.0",
)

register_exception_handlers(app)

app.include_router(inventory.router)


@app.get(
    "/",
    response_model=ApiResponse[ServiceInfo],
    tags=["core"],
    summary="Metadados do serviço",
)
async def root(service: ServiceInfo = Depends(get_service_info)) -> ApiResponse[ServiceInfo]:
    """Raiz da API — expõe os metadados do serviço via dependência reutilizável."""
    return ok(service)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["core"],
    summary="Healthcheck do serviço",
)
async def health() -> HealthResponse:
    """Healthcheck do serviço (utilizado também no healthcheck do container)."""
    return HealthResponse(status="ok", service="synapseshop-inventory")
