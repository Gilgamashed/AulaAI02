"""View do `POST /api/v1/ask_sql/` (Aula 21).

A view é fina: valida o payload, delega ao serviço e traduz os desfechos em
HTTP. Restrita ao papel `admin` (`IsAdminRole`): uma consulta em linguagem
natural pode ler pedidos, pagamentos e usuários de toda a base — o mesmo
critério de `/cache/metrics/` e `/llm/metrics/`.

Mapa de erros:

- 400 — payload inválido (serializer);
- 401/403 — sem JWT ou sem papel admin;
- 422 — pergunta não suportada, SQL ausente/proibido ou falha de execução;
- 500 — camada de IA mal configurada;
- 502 — provedor devolveu resposta inválida;
- 503 — provedor ou banco indisponível.
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

from .constantes import EXEMPLOS_PERGUNTAS
from .erros import (
    BancoIndisponivel,
    ExecucaoSqlFalhou,
    PerguntaNaoSuportada,
    SqlInvalido,
    SqlNaoGerado,
)
from .serializers import AskSqlSerializer
from .servico import responder

logger = logging.getLogger("core.ask_sql")


class AskSqlView(APIView):
    """Converte uma pergunta de negócio em SQL somente leitura + resultado."""

    permission_classes = [permissions.IsAuthenticated, IsAdminRole]

    def post(self, request) -> Response:
        serializer = AskSqlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            consulta = responder(serializer.validated_data["question"])
        except LlmConfiguracaoInvalida as falha:
            return self._erro(
                "AskSqlConfiguracaoInvalida",
                "A camada de IA está mal configurada no servidor.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                falha,
            )
        except (CircuitoAberto, LlmIndisponivel) as falha:
            return self._erro(
                "AskSqlIndisponivel",
                (
                    "O provedor de IA está indisponível no momento. "
                    "Tente novamente mais tarde."
                ),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                falha,
            )
        except LlmTerminal as falha:
            return self._erro(
                "AskSqlTerminal",
                "O provedor de IA devolveu uma resposta inválida.",
                status.HTTP_502_BAD_GATEWAY,
                falha,
            )
        except PerguntaNaoSuportada as falha:
            return self._nao_suportada(falha)
        except SqlNaoGerado as falha:
            return self._nao_suportada(falha, evento="AskSqlSemConsulta")
        except SqlInvalido as falha:
            return self._erro(
                "AskSqlInvalido",
                str(falha),
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                falha,
            )
        except ExecucaoSqlFalhou as falha:
            return self._erro(
                "AskSqlExecucaoFalhou",
                f"A consulta gerada não pôde ser executada: {falha}",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                falha,
            )
        except BancoIndisponivel as falha:
            return self._erro(
                "AskSqlBancoIndisponivel",
                "O banco de dados está indisponível no momento.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                falha,
            )

        return Response(
            {
                "question": consulta.pergunta,
                "sql": consulta.sql,
                "columns": consulta.resultado.colunas,
                "rows": consulta.resultado.linhas,
                "row_count": consulta.resultado.total_linhas,
                "truncated": consulta.resultado.truncado,
                "meta": consulta.meta,
            }
        )

    def _nao_suportada(
        self,
        falha: Exception,
        *,
        evento: str = "AskSqlNaoSuportada",
    ) -> Response:
        resposta = self._erro(
            evento,
            str(falha),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            falha,
        )
        resposta.data["examples"] = list(EXEMPLOS_PERGUNTAS)
        return resposta

    @staticmethod
    def _erro(
        evento: str,
        mensagem: str,
        codigo: int,
        falha: Exception,
    ) -> Response:
        logger.warning(
            "falha no texto-para-SQL",
            extra={
                "evento": evento,
                "resultado": "erro",
                "erro": str(falha),
            },
        )
        return Response({"detail": mensagem}, status=codigo)
