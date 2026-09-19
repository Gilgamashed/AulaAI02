from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .responses import error


def register_exception_handlers(app: FastAPI) -> None:
    """Registra os handlers de erro do serviço usando o envelope padrão."""

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Payload/path inválido: o FastAPI devolveria 422; a squad padronizou 400.
        content = error("Payload ou parâmetro inválido").model_dump()
        return JSONResponse(status_code=400, content=content)

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # 404/409 etc. retornam no mesmo envelope das respostas de sucesso.
        content = error(str(exc.detail)).model_dump()
        return JSONResponse(status_code=exc.status_code, content=content)
