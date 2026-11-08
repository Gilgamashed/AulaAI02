"""Consultas parametrizadas do painel de pedidos (Aula 19).

As consultas usam SQLAlchemy Core: filtros e valores viram *bind parameters*,
e a ordenação só aceita colunas da allow-list. Não há interpolação de valores
em SQL.

Aula 25: além da listagem, o módulo agrega os indicadores de vendas do painel
(receita total, ticket médio, receita por dia e produtos mais vendidos). A
coluna JSON `itens` é lida para os produtos, mas a consulta continua limitada
(`LIMITE_MAXIMO`) e parametrizada — a agregação acontece em Python, sobre as
linhas já filtradas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    JSON,
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
    # `nullable=True` apenas na projeção: a coluna real é NOT NULL, mas a
    # tabela é usada para leitura e os testes antigos inserem linhas sem
    # `itens` no SQLite. Isso não altera o schema de produção.
    Column("itens", JSON, nullable=True),
)

# Projeção mínima do catálogo para traduzir o SKU do snapshot no nome exibido.
catalogo_itens = Table(
    "core_item",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("sku", String(100), nullable=False),
    Column("name", String(200), nullable=False),
)

_COLUNAS_ORDENACAO = {
    "id": pedidos.c.id,
    "created_at": pedidos.c.created_at,
    "total": pedidos.c.total,
    "status": pedidos.c.status,
}

STATUS_RECEITA = ("processado",)


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
    incluir_itens: bool = False,
) -> Select:
    """Monta a consulta com filtros parametrizados e ordenação validada."""
    if data_inicio and data_fim and data_inicio > data_fim:
        raise ValueError("A data inicial não pode ser posterior à data final")
    if pedido_id is not None and pedido_id < 1:
        raise ValueError("O ID do pedido deve ser positivo")

    status_validos = validar_status(status_list)
    coluna, direcao = resolver_ordenacao(ordem_coluna, ordem_direcao)
    limite_final = normalizar_limite(limite)

    colunas = [
        pedidos.c.id,
        pedidos.c.usuario_id,
        pedidos.c.status,
        pedidos.c.total,
        pedidos.c.tentativas,
        pedidos.c.created_at,
    ]
    if incluir_itens:
        colunas.append(pedidos.c.itens)
    consulta = select(*colunas)

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
    incluir_itens: bool = False,
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
        incluir_itens=incluir_itens,
    )
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).mappings().all()
    return [dict(linha) for linha in linhas]


def carregar_nomes_produtos(
    skus: Sequence[str],
    *,
    engine: Engine | None = None,
) -> dict[str, str]:
    """Traduz SKUs do snapshot no nome do catálogo (consulta parametrizada)."""
    alvos = sorted({sku for sku in skus if sku})
    if not alvos:
        return {}
    consulta = select(catalogo_itens.c.sku, catalogo_itens.c.name).where(
        catalogo_itens.c.sku.in_(alvos)
    )
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).all()
    return {str(sku): str(nome) for sku, nome in linhas}


def carregar_vendas(
    *,
    engine: Engine | None = None,
    status_list: Sequence[str] | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limite: int = 500,
) -> dict[str, Any]:
    """Executa as consultas do painel e devolve os indicadores agregados."""
    registros = carregar_pedidos(
        engine=engine,
        status_list=status_list,
        data_inicio=data_inicio,
        data_fim=data_fim,
        ordem_coluna="created_at",
        ordem_direcao="desc",
        limite=limite,
        incluir_itens=True,
    )
    skus = [
        str(item.get("sku"))
        for registro in registros
        for item in (registro.get("itens") or [])
        if isinstance(item, Mapping) and item.get("sku")
    ]
    nomes = carregar_nomes_produtos(skus, engine=engine)
    return agregar_vendas(registros, nomes)


def agregar_vendas(
    registros: Sequence[Mapping[str, Any]],
    nomes_por_sku: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Agrega os indicadores de vendas a partir das linhas já filtradas.

    Considera receita apenas pedidos com status `processado`: `pendente` e
    `falha` ainda não concluíram o pipeline e não devem inflar o faturamento.
    """
    nomes = nomes_por_sku or {}
    processados = [
        registro
        for registro in registros
        if registro.get("status") in STATUS_RECEITA
    ]

    receita_total = Decimal("0.00")
    receita_por_dia: dict[str, Decimal] = {}
    produtos: dict[str, dict[str, Any]] = {}

    for registro in processados:
        total = _decimal(registro.get("total"))
        receita_total += total

        dia = _dia_iso(registro.get("created_at"))
        if dia is not None:
            receita_por_dia[dia] = receita_por_dia.get(dia, Decimal("0.00")) + total

        for item in registro.get("itens") or []:
            if not isinstance(item, Mapping):
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            quantidade = _inteiro(item.get("quantidade"))
            preco = _decimal(item.get("preco_unitario"))
            linha = produtos.setdefault(
                sku,
                {
                    "sku": sku,
                    "nome": nomes.get(sku, sku),
                    "quantidade": 0,
                    "receita": Decimal("0.00"),
                },
            )
            linha["quantidade"] += quantidade
            linha["receita"] += preco * quantidade

    lista_produtos = sorted(
        produtos.values(),
        key=lambda produto: (-produto["quantidade"], -produto["receita"], produto["sku"]),
    )
    for produto in lista_produtos:
        produto["receita"] = produto["receita"].quantize(Decimal("0.01"))

    total_pedidos = len(processados)
    ticket_medio = (
        (receita_total / total_pedidos).quantize(Decimal("0.01"))
        if total_pedidos
        else Decimal("0.00")
    )
    return {
        "receita_total": receita_total.quantize(Decimal("0.01")),
        "ticket_medio": ticket_medio,
        "pedidos_processados": total_pedidos,
        "receita_por_dia": [
            {"data": dia, "receita": valor.quantize(Decimal("0.01"))}
            for dia, valor in sorted(receita_por_dia.items())
        ],
        "produtos": lista_produtos,
    }


def contar_pedidos(engine: Engine | None = None) -> int:
    """Contagem total usada pela simulação de SQL Injection."""
    consulta = select(func.count()).select_from(pedidos)
    with (engine or get_engine()).connect() as conexao:
        return int(conexao.execute(consulta).scalar_one())


def _decimal(valor: Any) -> Decimal:
    if valor is None or isinstance(valor, bool):
        return Decimal("0.00")
    try:
        return Decimal(str(valor))
    except (ArithmeticError, ValueError):
        return Decimal("0.00")


def _inteiro(valor: Any) -> int:
    if valor is None or isinstance(valor, bool):
        return 0
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _dia_iso(valor: Any) -> str | None:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, str) and valor:
        return valor[:10]
    return None
