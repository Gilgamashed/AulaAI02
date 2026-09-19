from pydantic import BaseModel, Field


class ServiceInfo(BaseModel):
    """Metadados do serviço injetados via dependência reutilizável."""

    name: str = Field(default="synapseshop-inventory", examples=["synapseshop-inventory"])
    version: str = Field(default="0.1.0", examples=["0.1.0"])


def get_service_info() -> ServiceInfo:
    """Dependência padrão: fornece os metadados do serviço aos endpoints."""
    return ServiceInfo()
