"""Orquestração do texto-para-SQL (Aula 21).

O caminho é sempre o mesmo, independentemente de o provedor ser o mock desta
aula ou um LLM real no futuro:

    pergunta → prompt (schema) → LlmService → extração → validação → execução

Nenhuma etapa opcional: mesmo que o provedor devolva SQL perfeito, ele passa
pela validação e roda em transação read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from core.llm import criar_llm_service

from .execucao import ResultadoSql, executar_sql
from .extracao import extrair_sql
from .prompt import montar_mensagens
from .validacao import validar_sql

PADRAO_MAX_LINHAS = 200
PADRAO_TIMEOUT_MS = 3000
PADRAO_MAX_TOKENS = 500


@dataclass(frozen=True)
class ConsultaRespondida:
    """Resultado completo de uma pergunta de negócio."""

    pergunta: str
    sql: str
    resultado: ResultadoSql
    meta: dict[str, Any]


def responder(
    pergunta: str,
    *,
    llm: Any | None = None,
    max_linhas: int | None = None,
    timeout_ms: int | None = None,
    max_tokens: int | None = None,
) -> ConsultaRespondida:
    """Executa o pipeline completo para uma pergunta em linguagem natural."""
    limite = _inteiro(max_linhas, "ASK_SQL_MAX_LINHAS", PADRAO_MAX_LINHAS)
    tempo_limite = _inteiro(timeout_ms, "ASK_SQL_TIMEOUT_MS", PADRAO_TIMEOUT_MS)
    tokens = _inteiro(max_tokens, "ASK_SQL_MAX_TOKENS", PADRAO_MAX_TOKENS)

    servico = llm if llm is not None else criar_llm_service(tarefa="sql")
    resposta = servico.completar(
        montar_mensagens(pergunta),
        temperature=0.0,
        max_tokens=tokens,
    )

    sql = extrair_sql(resposta.texto)
    validado = validar_sql(sql, max_linhas=limite)
    resultado = executar_sql(
        validado.sql,
        max_linhas=validado.limite,
        timeout_ms=tempo_limite,
    )

    return ConsultaRespondida(
        pergunta=pergunta.strip(),
        sql=validado.sql,
        resultado=resultado,
        meta={
            "tokens_prompt": resposta.tokens_prompt,
            "tokens_output": resposta.tokens_output,
            "modelo": getattr(servico, "modelo", getattr(settings, "LLM_MODEL", "mock")),
        },
    )


def _inteiro(valor: int | None, nome_setting: str, padrao: int) -> int:
    """Resolve o limite: argumento explícito ou setting, sempre >= 1."""
    if valor is None:
        valor = int(getattr(settings, nome_setting, padrao))
    if valor < 1:
        raise ValueError(f"{nome_setting} deve ser >= 1")
    return valor
