"""Consultas parametrizadas do painel de pedidos (Aula 19).

As consultas usam SQLAlchemy Core: filtros e valores viram *bind parameters*,
e a ordenação só aceita colunas da allow-list. Não há interpolação de valores
em SQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    Select,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.engine import Engine

from .db import get_engine
from .security import normalizar_limite, resolver_ordenacao, validar_status

metadata = MetaData()

pedidos = Table(
    "core_pedido",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("usuario_id", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("total", Numeric(10, 2), nullable=False),
    Column("tentativas", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

_COLUNAS_ORDENACAO = {
    "id": pedidos.c.id,
    "created_at": pedidos.c.created_at,
    "total": pedidos.c.total,
    "status": pedidos.c.status,
}


def _inicio_do_dia(valor: date) -> datetime:
    return datetime.combine(valor, time.min, tzinfo=timezone.utc)


def montar_consulta_pedidos(
    *,
    status_list: Sequence[str] | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    pedido_id: int | None = None,
    ordem_coluna: str | None = "created_at",
    ordem_direcao: str | None = "desc",
    limite: int = 500,
) -> Select:
    """Monta a consulta com filtros parametrizados e ordenação validada."""
    if data_inicio and data_fim and data_inicio > data_fim:
        raise ValueError("A data inicial não pode ser posterior à data final")
    if pedido_id is not None and pedido_id < 1:
        raise ValueError("O ID do pedido deve ser positivo")

    status_validos = validar_status(status_list)
    coluna, direcao = resolver_ordenacao(ordem_coluna, ordem_direcao)
    limite_final = normalizar_limite(limite)

    consulta = select(
        pedidos.c.id,
        pedidos.c.usuario_id,
        pedidos.c.status,
        pedidos.c.total,
        pedidos.c.tentativas,
        pedidos.c.created_at,
    )

    if status_validos:
        consulta = consulta.where(pedidos.c.status.in_(status_validos))
    if data_inicio:
        consulta = consulta.where(pedidos.c.created_at >= _inicio_do_dia(data_inicio))
    if data_fim:
        consulta = consulta.where(
            pedidos.c.created_at < _inicio_do_dia(data_fim) + timedelta(days=1)
        )
    if pedido_id is not None:
        consulta = consulta.where(pedidos.c.id == pedido_id)

    coluna_sql = _COLUNAS_ORDENACAO[coluna]
    ordenacao = coluna_sql.desc() if direcao == "desc" else coluna_sql.asc()
    return consulta.order_by(ordenacao).limit(limite_final)


def carregar_pedidos(
    *,
    engine: Engine | None = None,
    status_list: Sequence[str] | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    pedido_id: int | None = None,
    ordem_coluna: str | None = "created_at",
    ordem_direcao: str | None = "desc",
    limite: int = 500,
) -> list[dict[str, Any]]:
    """Executa a consulta segura e devolve registros prontos para a interface."""
    consulta = montar_consulta_pedidos(
        status_list=status_list,
        data_inicio=data_inicio,
        data_fim=data_fim,
        pedido_id=pedido_id,
        ordem_coluna=ordem_coluna,
        ordem_direcao=ordem_direcao,
        limite=limite,
    )
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).mappings().all()
    return [dict(linha) for linha in linhas]


def contar_pedidos(engine: Engine | None = None) -> int:
    """Contagem total usada pela simulação de SQL Injection."""
    consulta = select(func.count()).select_from(pedidos)
    with (engine or get_engine()).connect() as conexao:
        return int(conexao.execute(consulta).scalar_one())
