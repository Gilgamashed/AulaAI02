"""Testes unitários das consultas seguras do dashboard (Aula 19)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from dashboard import queries, security
from dashboard.queries import montar_consulta_pedidos, pedidos
from dashboard.security import PAYLOAD_SQLI


def test_resolver_ordenacao_valida_e_rejeita():
    assert security.resolver_ordenacao("created_at", "desc") == ("created_at", "desc")
    assert security.resolver_ordenacao("ID", "ASC") == ("id", "asc")
    with pytest.raises(ValueError):
        security.resolver_ordenacao("senha", "asc")
    with pytest.raises(ValueError):
        security.resolver_ordenacao("id", "sideways")


def test_validar_status():
    assert security.validar_status(["processado", "falha"]) == ["processado", "falha"]
    assert security.validar_status(["processado", "processado"]) == ["processado"]
    with pytest.raises(ValueError):
        security.validar_status(["inexistente"])


def test_montar_consulta_com_bind_params_e_allowlist():
    consulta = montar_consulta_pedidos(
        status_list=["processado"],
        data_inicio=date(2026, 10, 1),
        data_fim=date(2026, 10, 31),
        pedido_id=42,
        ordem_coluna="total",
        ordem_direcao="desc",
    )
    compilada = consulta.compile(compile_kwargs={"render_postcompile": True})
    sql = str(compilada)
    assert "core_pedido" in sql
    assert "ORDER BY" in sql and "total" in sql
    assert "FROM core_pedido" in sql
    assert ":" in str(compilada.params)
    assert PAYLOAD_SQLI not in sql


def test_montar_consulta_rejeita_data_invalida():
    with pytest.raises(ValueError):
        montar_consulta_pedidos(data_inicio=date(2026, 10, 31), data_fim=date(2026, 10, 1))


def test_payload_sqli_nao_faz_bypass_em_sqlite():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    queries.metadata.create_all(engine)
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            pedidos.insert(),
            [
                {"id": 1, "usuario_id": 1, "status": "processado", "total": 10.00, "tentativas": 0, "created_at": agora},
                {"id": 2, "usuario_id": 2, "status": "falha", "total": 5.00, "tentativas": 1, "created_at": agora},
            ],
        )

    # Tentativa com payload malicioso como valor literal
    consulta = select(func.count()).select_from(pedidos).where(pedidos.c.status == PAYLOAD_SQLI)
    with engine.connect() as conn:
        resultado = conn.execute(consulta).scalar_one()
    assert resultado == 0

    # Consulta normal continua funcionando
    consulta_normal = select(func.count()).select_from(pedidos).where(pedidos.c.status == "processado")
    with engine.connect() as conn:
        assert conn.execute(consulta_normal).scalar_one() == 1
