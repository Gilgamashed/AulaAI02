"""Testes unitários da simulação de SQL Injection (Aula 19)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from dashboard import queries, simular_sqli


def test_executar_simulacao_mitigada():
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
            queries.pedidos.insert(),
            [
                {"id": 1, "usuario_id": 1, "status": "pendente", "total": 10.00, "tentativas": 0, "created_at": agora},
                {"id": 2, "usuario_id": 2, "status": "processado", "total": 20.00, "tentativas": 0, "created_at": agora},
            ],
        )

    resultado = simular_sqli.executar_simulacao(engine)
    assert resultado["total_pedidos"] == 2
    assert resultado["linhas_com_payload"] == 0
    assert resultado["mitigado"] is True
