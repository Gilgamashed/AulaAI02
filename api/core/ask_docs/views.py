"""View do `POST /api/v1/ask_docs/` (Aula 24).

A view é fina: valida o payload, delega ao serviço e traduz os desfechos em
HTTP. Restrita ao papel `admin` (`IsAdminRole`), como `/ask_sql/` e
`/llm/metrics/`: a chamada consome cota de IA e o assistente é operacional.

Mapa de erros:

- 400 — payload inválido (serializer);
- 401/403 — sem JWT ou sem papel admin;
- 500 — camada de IA mal configurada;
- 502 — provedor devolveu resposta inválida;
- 503 — provedor ou índice de documentação indisponível.
"""

from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.llm import (
    CircuitoAberto,
    LlmConfiguracaoInvalida,
    LlmIndisponivel,
    LlmTerminal,
)
from core.permissions import IsAdminRole

from .erros import IndiceIndisponivel, IndiceVazio, ParametroInvalido
from .serializers import AskDocsSerializer
from .servico import responder

logger = logging.getLogger("core.ask_docs")


class AskDocsView(APIView):
    """Responde perguntas técnicas com base no índice de documentação."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request) -> Response:
        serializer = AskDocsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            resposta = responder(
                serializer.validated_data["question"],
                top_k=serializer.validated_data.get("top_k"),
                min_score=serializer.validated_data.get("min_score"),
            )
        except LlmConfiguracaoInvalida as falha:
            return self._erro(
                "AskDocsConfiguracaoInvalida",
                "A camada de IA está mal configurada no servidor.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                falha,
            )
        except (CircuitoAberto, LlmIndisponivel) as falha:
            return self._erro(
                "AskDocsIndisponivel",
                (
                    "O provedor de IA está indisponível no momento. "
                    "Tente novamente mais tarde."
                ),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                falha,
            )
        except LlmTerminal as falha:
            return self._erro(
                "AskDocsTerminal",
                "O provedor de IA devolveu uma resposta inválida.",
                status.HTTP_502_BAD_GATEWAY,
                falha,
            )
        except (IndiceVazio, IndiceIndisponivel) as falha:
            return self._erro(
                "AskDocsIndiceIndisponivel",
                str(falha),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                falha,
            )
        except ParametroInvalido as falha:
            return self._erro(
                "AskDocsParametroInvalido",
                str(falha),
                status.HTTP_400_BAD_REQUEST,
                falha,
            )

        return Response(
            {
                "answer": resposta.answer,
                "sources": [
                    {
                        "path": fonte.path,
                        "title": fonte.title,
                        "range": fonte.range,
                        "score": fonte.score,
                    }
                    for fonte in resposta.sources
                ],
            }
        )

    @staticmethod
    def _erro(
        evento: str,
        mensagem: str,
        codigo: int,
        falha: Exception,
    ) -> Response:
        logger.warning(
            "falha no assistente de documentação",
            extra={
                "evento": evento,
                "resultado": "erro",
                "erro": str(falha),
            },
        )
        return Response({"detail": mensagem}, status=codigo)
