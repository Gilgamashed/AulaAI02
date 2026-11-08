"""Testes dos indicadores de vendas do dashboard (Aula 25)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from dashboard import queries
from dashboard.queries import (
    agregar_vendas,
    carregar_vendas,
    montar_consulta_pedidos,
)

pytestmark = pytest.mark.unit


def _registro(
    *,
    status: str = "processado",
    total: str = "100.00",
    criado_em: datetime | None = None,
    itens: list[dict] | None = None,
) -> dict:
    return {
        "id": 1,
        "usuario_id": 1,
        "status": status,
        "total": Decimal(total),
        "tentativas": 0,
        "created_at": criado_em or datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
        "itens": itens or [],
    }


def test_agregar_vendas_com_periodo_vazio():
    resultado = agregar_vendas([])

    assert resultado["receita_total"] == Decimal("0.00")
    assert resultado["ticket_medio"] == Decimal("0.00")
    assert resultado["pedidos_processados"] == 0
    assert resultado["receita_por_dia"] == []
    assert resultado["produtos"] == []


def test_agregar_vendas_considera_somente_pedidos_processados():
    registros = [
        _registro(total="100.00"),
        _registro(total="50.00", criado_em=datetime(2026, 11, 2, 9, tzinfo=timezone.utc)),
        _registro(status="pendente", total="999.00"),
        _registro(status="falha", total="888.00"),
    ]

    resultado = agregar_vendas(registros)

    assert resultado["receita_total"] == Decimal("150.00")
    assert resultado["ticket_medio"] == Decimal("75.00")
    assert resultado["pedidos_processados"] == 2
    assert resultado["receita_por_dia"] == [
        {"data": "2026-11-01", "receita": Decimal("100.00")},
        {"data": "2026-11-02", "receita": Decimal("50.00")},
    ]


def test_agregar_vendas_calcula_produtos_por_quantidade_e_receita():
    registros = [
        _registro(
            total="100.00",
            itens=[
                {"sku": "AAA-1", "quantidade": 2, "preco_unitario": "10.00"},
                {"sku": "BBB-2", "quantidade": 1, "preco_unitario": "80.00"},
            ],
        ),
        _registro(
            total="50.00",
            criado_em=datetime(2026, 11, 2, 9, tzinfo=timezone.utc),
            itens=[{"sku": "AAA-1", "quantidade": 3, "preco_unitario": "10.00"}],
        ),
    ]

    resultado = agregar_vendas(
        registros,
        {"AAA-1": "Produto A", "BBB-2": "Produto B"},
    )

    produtos = {produto["sku"]: produto for produto in resultado["produtos"]}
    assert produtos["AAA-1"] == {
        "sku": "AAA-1",
        "nome": "Produto A",
        "quantidade": 5,
        "receita": Decimal("50.00"),
    }
    assert produtos["BBB-2"]["nome"] == "Produto B"
    assert produtos["BBB-2"]["receita"] == Decimal("80.00")
    # Ordenação padrão: quantidade desc.
    assert [produto["sku"] for produto in resultado["produtos"]] == ["AAA-1", "BBB-2"]


def test_agregar_vendas_ignora_itens_malformados_sem_quebrar():
    registros = [
        _registro(
            itens=[
                {"sku": "AAA-1", "quantidade": "2", "preco_unitario": "10.00"},
                {"quantidade": 9, "preco_unitario": "10.00"},
                "item-invalido",
                {"sku": "", "quantidade": 1, "preco_unitario": "10.00"},
            ],
        )
    ]

    resultado = agregar_vendas(registros)

    assert resultado["produtos"] == [
        {
            "sku": "AAA-1",
            "nome": "AAA-1",
            "quantidade": 2,
            "receita": Decimal("20.00"),
        }
    ]


def test_consulta_de_vendas_inclui_itens_e_mantem_bind_params():
    consulta = montar_consulta_pedidos(
        status_list=["processado"],
        data_inicio=date(2026, 11, 1),
        data_fim=date(2026, 11, 30),
        incluir_itens=True,
    )
    sql = str(consulta.compile(compile_kwargs={"render_postcompile": True}))

    assert "itens" in sql
    assert "core_pedido" in sql
    assert "processado" not in sql


def test_carregar_vendas_agrega_no_sqlite_com_nomes_do_catalogo():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    queries.metadata.create_all(engine)
    agora = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    with engine.begin() as conexao:
        conexao.execute(
            queries.catalogo_itens.insert(),
            [
                {"id": 1, "sku": "AAA-1", "name": "Produto A"},
                {"id": 2, "sku": "BBB-2", "name": "Produto B"},
            ],
        )
        conexao.execute(
            queries.pedidos.insert(),
            [
                {
                    "id": 1,
                    "usuario_id": 1,
                    "status": "processado",
                    "total": 100.00,
                    "tentativas": 0,
                    "created_at": agora,
                    "itens": [
                        {"sku": "AAA-1", "quantidade": 2, "preco_unitario": "10.00"},
                        {"sku": "BBB-2", "quantidade": 1, "preco_unitario": "80.00"},
                    ],
                },
                {
                    "id": 2,
                    "usuario_id": 1,
                    "status": "pendente",
                    "total": 999.00,
                    "tentativas": 0,
                    "created_at": agora,
                    "itens": [
                        {"sku": "AAA-1", "quantidade": 99, "preco_unitario": "10.00"}
                    ],
                },
            ],
        )

    resultado = carregar_vendas(
        engine=engine,
        data_inicio=date(2026, 11, 1),
        data_fim=date(2026, 11, 30),
    )

    assert resultado["receita_total"] == Decimal("100.00")
    assert resultado["pedidos_processados"] == 1
    assert {produto["sku"]: produto["nome"] for produto in resultado["produtos"]} == {
        "AAA-1": "Produto A",
        "BBB-2": "Produto B",
    }
    # A consulta auxiliar também é parametrizada.
    with engine.connect() as conexao:
        linhas = conexao.execute(select(queries.catalogo_itens)).all()
    assert len(linhas) == 2
