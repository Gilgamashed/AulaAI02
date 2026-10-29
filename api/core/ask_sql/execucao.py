"""Execução read-only da consulta validada (Aula 21).

A validação já recusou DML/DDL, mas a garantia final é do banco: a consulta roda
dentro de uma transação `READ ONLY` e com `statement_timeout` local. Mesmo que
uma escrita passasse pela validação, o PostgreSQL a recusaria.

Quando o chamador já está numa transação (o pytest-django envolve os testes numa
transação externa), `SET TRANSACTION READ ONLY` não pode mais ser aplicado; a
transação de teste é preservada e a barreira de banco é provada à parte em um
teste com `transaction=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import DatabaseError, OperationalError, connection, transaction

from .erros import BancoIndisponivel, ExecucaoSqlFalhou


@dataclass(frozen=True)
class ResultadoSql:
    """Resultado serializável de uma consulta aprovada."""

    colunas: list[str]
    linhas: list[dict[str, Any]]
    truncado: bool

    @property
    def total_linhas(self) -> int:
        return len(self.linhas)


def executar_sql(
    sql: str,
    *,
    max_linhas: int,
    timeout_ms: int,
) -> ResultadoSql:
    """Executa a consulta e devolve no máximo `max_linhas` linhas."""
    if max_linhas < 1:
        raise ValueError("max_linhas deve ser >= 1")
    if timeout_ms < 1:
        raise ValueError("timeout_ms deve ser >= 1")

    transacao_externa = connection.in_atomic_block

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if not transacao_externa:
                    cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    [str(timeout_ms)],
                )
                cursor.execute(sql)
                if cursor.description is None:
                    raise ExecucaoSqlFalhou(
                        "a consulta não devolveu um conjunto de resultados"
                    )
                colunas = [descricao[0] for descricao in cursor.description]
                brutas = cursor.fetchmany(max_linhas + 1)
    except OperationalError as falha:
        raise BancoIndisponivel(_resumir(falha)) from falha
    except DatabaseError as falha:
        raise ExecucaoSqlFalhou(_resumir(falha)) from falha

    truncado = len(brutas) > max_linhas
    linhas = [
        _linha_para_dict(colunas, linha)
        for linha in brutas[:max_linhas]
    ]
    return ResultadoSql(colunas=colunas, linhas=linhas, truncado=truncado)


def _linha_para_dict(colunas: list[str], linha: tuple[Any, ...]) -> dict[str, Any]:
    return {
        coluna: _json_safe(valor)
        for coluna, valor in zip(colunas, linha, strict=False)
    }


def _json_safe(valor: Any) -> Any:
    """Converte tipos do PostgreSQL em valores aceitos por `JsonResponse`."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    if isinstance(valor, dict):
        return {str(chave): _json_safe(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json_safe(item) for item in valor]
    return valor


def _resumir(falha: Exception) -> str:
    mensagem = str(falha).strip().splitlines()[0] if str(falha).strip() else ""
    return mensagem[:300] or falha.__class__.__name__
