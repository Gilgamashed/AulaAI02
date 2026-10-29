"""Cliente HTTP do painel de consulta em linguagem natural (Aula 21).

O dashboard **não** executa SQL por conta própria: ele autentica na API,
envia a pergunta e exibe o SQL/resultado que o `/api/v1/ask_sql/` devolveu.
Assim a validação e a transação read-only ficam num único lugar.

Só a biblioteca padrão é usada aqui (`urllib`) — a página Streamlit pode
importar este módulo sem arrastar `pandas`/`streamlit` para os testes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

URL_PADRAO = "http://localhost:8000"
TIMEOUT_PADRAO = 15.0

# Espelha `core.ask_sql.constantes.EXEMPLOS_PERGUNTAS`: o dashboard é uma
# imagem separada e não importa código da API.
EXEMPLOS_PERGUNTAS = (
    "Quais os 5 últimos usuários cadastrados?",
    "Qual a soma do valor dos últimos 3 pedidos?",
    "Quais usuários fizeram mais pedidos?",
    "Quantos pedidos existem por status?",
    "Quais os produtos mais caros?",
)


class AskSqlErro(Exception):
    """Falha de comunicação ou erro devolvido pela API."""

    def __init__(
        self,
        mensagem: str,
        *,
        status: int | None = None,
        examples: tuple[str, ...] = (),
    ) -> None:
        super().__init__(mensagem)
        self.status: int | None = status
        self.examples: tuple[str, ...] = tuple(examples)


@dataclass(frozen=True)
class RespostaAskSql:
    """Resposta do endpoint já normalizada para a UI."""

    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    meta: dict[str, Any]


def api_base_url() -> str:
    """URL da API: `DASHBOARD_API_URL`, `API_BASE_URL` ou localhost."""
    valor = (
        os.environ.get("DASHBOARD_API_URL")
        or os.environ.get("API_BASE_URL")
        or URL_PADRAO
    )
    return valor.rstrip("/")


def login(usuario: str, senha: str, *, timeout: float = TIMEOUT_PADRAO) -> str:
    """Autentica via `/api/v1/auth/token/` e devolve o access token."""
    dados = _requisitar(
        "POST",
        "/api/v1/auth/token/",
        payload={"username": usuario, "password": senha},
        timeout=timeout,
    )
    token = dados.get("access")
    if not isinstance(token, str) or not token:
        raise AskSqlErro("A API não devolveu um token de acesso válido.")
    return token


def perguntar(
    pergunta: str,
    token: str,
    *,
    timeout: float = TIMEOUT_PADRAO,
) -> RespostaAskSql:
    """Envia a pergunta ao `/api/v1/ask_sql/` e normaliza a resposta."""
    dados = _requisitar(
        "POST",
        "/api/v1/ask_sql/",
        payload={"question": pergunta},
        token=token,
        timeout=timeout,
    )

    sql = dados.get("sql")
    if not isinstance(sql, str) or not sql:
        raise AskSqlErro("A API devolveu uma resposta sem consulta SQL.")

    return RespostaAskSql(
        question=str(dados.get("question", pergunta)),
        sql=sql,
        columns=[str(coluna) for coluna in dados.get("columns", [])],
        rows=list(dados.get("rows", [])),
        row_count=int(dados.get("row_count", 0)),
        truncated=bool(dados.get("truncated", False)),
        meta=dict(dados.get("meta", {})),
    )


def _requisitar(
    metodo: str,
    caminho: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float,
) -> dict[str, Any]:
    corpo = json.dumps(payload).encode("utf-8") if payload is not None else None
    cabecalhos = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"

    requisicao = request.Request(
        f"{api_base_url()}{caminho}",
        data=corpo,
        headers=cabecalhos,
        method=metodo,
    )

    try:
        with request.urlopen(requisicao, timeout=timeout) as resposta:
            return _json(resposta.read().decode("utf-8"))
    except error.HTTPError as falha:
        corpo_erro = falha.read().decode("utf-8", errors="replace")
        raise _erro_da_api(falha.code, corpo_erro) from falha
    except TimeoutError as falha:
        raise AskSqlErro(
            "A API demorou demais para responder. Tente novamente."
        ) from falha
    except error.URLError as falha:
        motivo = getattr(falha, "reason", falha)
        raise AskSqlErro(
            f"Não foi possível conectar à API ({api_base_url()}): {motivo}"
        ) from falha


def _json(texto: str) -> dict[str, Any]:
    if not texto.strip():
        return {}
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as falha:
        raise AskSqlErro("A API devolveu uma resposta que não é JSON.") from falha
    if not isinstance(dados, dict):
        raise AskSqlErro("A API devolveu um JSON fora do contrato esperado.")
    return dados


def _erro_da_api(status: int, corpo: str) -> AskSqlErro:
    dados = _json_seguro(corpo)
    detalhe = dados.get("detail")
    exemplos = dados.get("examples", [])
    mensagem = {
        400: "Pergunta inválida. Ela deve ser um texto de até 500 caracteres.",
        401: "Sessão expirada ou credenciais inválidas. Faça login novamente.",
        403: "A consulta em linguagem natural é restrita ao papel admin.",
        500: "A camada de IA está mal configurada no servidor.",
        502: "O provedor de IA devolveu uma resposta inválida.",
        503: "Serviço indisponível no momento. Tente novamente mais tarde.",
    }.get(status)
    if isinstance(detalhe, str) and detalhe:
        mensagem = detalhe
    if mensagem is None:
        mensagem = f"A API respondeu com HTTP {status}."
    return AskSqlErro(
        mensagem,
        status=status,
        examples=tuple(str(item) for item in exemplos) if isinstance(exemplos, list) else (),
    )


def _json_seguro(texto: str) -> dict[str, Any]:
    try:
        dados = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return {}
    return dados if isinstance(dados, dict) else {}
