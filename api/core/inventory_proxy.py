"""Proxy admin-only do inventário FastAPI.

O navegador fala apenas com o Django, na mesma origem. Este módulo valida o
JWT/papel ``admin`` (via ``IsAdminRole``), encaminha a operação para o
microsserviço pela rede interna do Compose e devolve o envelope original do
FastAPI. Assim a página ``/app/inventario/`` não precisa de CORS nem recebe o
endereço interno do inventory.

Limite deliberado: o FastAPI direto continua sem autenticação. No Compose, a
porta 8001 fica publicada somente em ``127.0.0.1``; o caminho suportado no MVP
é este proxy.
"""

from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsAdminRole

_CAMINHO_INVENTARIO = "/api/v1/inventory"


def chamar_inventario(
    metodo: str,
    caminho: str,
    payload: Any | None = None,
) -> tuple[int, Any | None]:
    """Executa uma chamada HTTP ao FastAPI e devolve ``(status, corpo)``.

    A função é separada das views para que os testes possam substituí-la sem
    abrir uma conexão real. Nenhum cabeçalho do navegador é repassado — em
    especial o ``Authorization`` — porque o microsserviço não o consome e o
    proxy não deve ampliar a superfície de exposição do token.
    """
    url = f"{settings.INVENTORY_URL}{caminho}"
    timeout = float(getattr(settings, "INVENTORY_TIMEOUT_SEGUNDOS", 5.0))
    with httpx.Client(timeout=timeout) as cliente:
        if payload is None:
            resposta = cliente.request(metodo, url)
        else:
            resposta = cliente.request(metodo, url, json=payload)
    corpo = resposta.json() if resposta.content else None
    return resposta.status_code, corpo


def _encaminhar(metodo: str, caminho: str, payload: Any | None = None) -> Response:
    """Traduz a chamada ao inventory preservando o contrato do FastAPI."""
    try:
        status_code, corpo = chamar_inventario(metodo, caminho, payload)
    except httpx.TimeoutException:
        return Response(
            {
                "status": "error",
                "message": "Tempo esgotado ao consultar o microsserviço de inventário.",
            },
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except httpx.RequestError:
        return Response(
            {
                "status": "error",
                "message": "Microsserviço de inventário indisponível.",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ValueError:
        return Response(
            {
                "status": "error",
                "message": "O microsserviço de inventário devolveu uma resposta inválida.",
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if status_code == status.HTTP_204_NO_CONTENT:
        return Response(status=status_code)
    return Response(corpo, status=status_code)


class InventarioListaView(APIView):
    """Lista e cria itens de inventário (admin-only)."""

    permission_classes = [IsAdminRole]
    parser_classes = [JSONParser]

    def get(self, request: Request) -> Response:
        return _encaminhar("GET", _CAMINHO_INVENTARIO)

    def post(self, request: Request) -> Response:
        return _encaminhar("POST", _CAMINHO_INVENTARIO, request.data)


class InventarioDetalheView(APIView):
    """Consulta, atualiza e remove um item de inventário pelo SKU (admin-only)."""

    permission_classes = [IsAdminRole]
    parser_classes = [JSONParser]

    def get(self, request: Request, sku: str) -> Response:
        return _encaminhar("GET", f"{_CAMINHO_INVENTARIO}/{sku}")

    def patch(self, request: Request, sku: str) -> Response:
        return _encaminhar("PATCH", f"{_CAMINHO_INVENTARIO}/{sku}", request.data)

    def delete(self, request: Request, sku: str) -> Response:
        return _encaminhar("DELETE", f"{_CAMINHO_INVENTARIO}/{sku}")
