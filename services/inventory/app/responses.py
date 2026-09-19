from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse[T](BaseModel):
    """Envelope padrão de resposta do microsserviço inventory.

    status: "ok" ou "error"; data: objeto ou lista do recurso; message:
    observação opcional (para erros ou trocas de informação).
    """

    status: str
    data: T | None = None
    message: str | None = None


def ok[T](data: T) -> ApiResponse[T]:
    """Factory de resposta de sucesso usando o envelope padrão."""
    return ApiResponse(status="ok", data=data)


def error(message: str) -> ApiResponse[None]:
    """Factory de resposta de erro usando o envelope padrão."""
    return ApiResponse(status="error", data=None, message=message)
