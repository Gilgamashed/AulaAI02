"""Dependências reutilizáveis do microsserviço inventory.

`ServiceInfo` (Aula 5) e a composição da camada de dados: sessão do SQLAlchemy
(uma por requisição) e o serviço de negócio construído sobre o repositório.
"""

from collections.abc import Iterator

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import SessionLocal
from .repositories.inventory import InventoryRepository
from .services.inventory import InventoryService


class ServiceInfo(BaseModel):
    """Metadados do serviço injetados via dependência reutilizável."""

    name: str = Field(default="synapseshop-inventory", examples=["synapseshop-inventory"])
    version: str = Field(default="0.1.0", examples=["0.1.0"])


def get_service_info() -> ServiceInfo:
    """Dependência padrão: fornece os metadados do serviço aos endpoints."""
    return ServiceInfo()


def get_session() -> Iterator[Session]:
    """Dependência: fornece uma sessão do SQLAlchemy por requisição.

    O `with` garante que a sessão seja sempre fechada ao final da requisição
    (devolvendo a conexão ao pool do engine).
    """
    with SessionLocal() as session:
        yield session


def get_inventory_service(session: Session = Depends(get_session)) -> InventoryService:
    """Compõe a camada de negócio do inventory (Service sobre Repository)."""
    return InventoryService(InventoryRepository(session))
