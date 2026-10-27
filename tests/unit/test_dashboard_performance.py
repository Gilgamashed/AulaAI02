"""Testes unitários do dashboard de desempenho (Aula 20)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from dashboard import performance

DDL_METRICAS = """
    CREATE TABLE core_requisicao_metrica (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metodo VARCHAR(10) NOT NULL,
        endpoint VARCHAR(200) NOT NULL,
        status_code INTEGER NOT NULL,
        latencia_ms FLOAT NOT NULL,
        cache_hits INTEGER NOT NULL DEFAULT 0,
        cache_misses INTEGER NOT NULL DEFAULT 0,
        cache_bypasses INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL
    )
"""


def _engine_sqlite():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL_METRICAS)
    return engine


def test_percentil_e_resumir_metricas():
    registros = [
        {"latencia_ms": 10, "status_code": 200, "endpoint": "/api/v1/items/", "created_at": datetime(2026, 10, 1, 10, tzinfo=timezone.utc)},
        {"latencia_ms": 20, "status_code": 200, "endpoint": "/api/v1/items/", "created_at": datetime(2026, 10, 1, 10, tzinfo=timezone.utc)},
        {"latencia_ms": 30, "status_code": 500, "endpoint": "/api/v1/pedidos/", "created_at": datetime(2026, 10, 1, 11, tzinfo=timezone.utc)},
        {"latencia_ms": 40, "status_code": 404, "endpoint": "/api/v1/pedidos/", "created_at": datetime(2026, 10, 1, 11, tzinfo=timezone.utc)},
        {"latencia_ms": 100, "status_code": 200, "endpoint": "/api/v1/items/", "created_at": datetime(2026, 10, 1, 12, tzinfo=timezone.utc)},
    ]
    resumo = performance.resumir_metricas(registros)
    assert resumo["total"] == 5
    assert resumo["erros"] == 2
    assert round(resumo["taxa_erro"], 2) == 40.0
    assert resumo["p95_ms"] >= 40
    assert "por_hora" in resumo
    assert resumo["por_status"]["200"] == 3
    assert resumo["por_classe"] == {"2xx": 3, "4xx": 1, "5xx": 1}


def test_resumo_vazio_tem_todas_as_chaves():
    resumo = performance.resumir_metricas([])
    assert resumo["total"] == 0
    assert resumo["por_classe"] == {}
    assert resumo["cache_hit_rate"] == 0.0
    assert resumo["cache_hits"] == 0


def test_hit_rate_de_cache_e_real_e_ignora_bypass():
    registros = [
        {"latencia_ms": 10, "status_code": 200, "endpoint": "/x", "cache_hits": 3, "cache_misses": 1, "cache_bypasses": 2},
        {"latencia_ms": 20, "status_code": 200, "endpoint": "/x", "cache_hits": 0, "cache_misses": 0, "cache_bypasses": 5},
    ]
    resumo = performance.resumir_metricas(registros)
    assert resumo["cache_hits"] == 3
    assert resumo["cache_misses"] == 1
    assert resumo["cache_bypasses"] == 7
    # 3 hits / (3 hits + 1 miss) = 75%; bypass não entra no denominador.
    assert resumo["cache_hit_rate"] == 75.0


def test_carregar_metricas_com_bind_params_sqlite():
    engine = _engine_sqlite()
    agora = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            performance.requisicao_metrica.insert(),
            [
                {"metodo": "GET", "endpoint": "/api/v1/items/", "status_code": 200, "latencia_ms": 15.0, "created_at": agora},
                {"metodo": "POST", "endpoint": "/api/v1/pedidos/", "status_code": 500, "latencia_ms": 50.0, "created_at": agora},
            ],
        )
    registros = performance.carregar_metricas(engine, endpoints=["/api/v1/items/"])
    assert len(registros) == 1
    assert registros[0]["endpoint"] == "/api/v1/items/"
    assert registros[0]["cache_hits"] == 0


def test_listar_endpoints_e_filtro_classe():
    engine = _engine_sqlite()
    agora = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            performance.requisicao_metrica.insert(),
            [
                {"metodo": "GET", "endpoint": "/api/v1/items/", "status_code": 200, "latencia_ms": 10.0, "created_at": agora},
                {"metodo": "GET", "endpoint": "/api/v1/pedidos/", "status_code": 404, "latencia_ms": 20.0, "created_at": agora},
            ],
        )
    endpoints = performance.listar_endpoints(engine)
    assert "/api/v1/items/" in endpoints
    registros_4xx = performance.carregar_metricas(engine, classes_status=["4xx"])
    assert len(registros_4xx) == 1
    assert registros_4xx[0]["status_code"] == 404


def test_periodo_invertido_falha_cedo():
    engine = _engine_sqlite()
    with pytest.raises(ValueError, match="data inicial"):
        performance.carregar_metricas(
            engine,
            data_inicio=datetime(2026, 10, 2).date(),
            data_fim=datetime(2026, 10, 1).date(),
        )


def test_pedidos_por_status():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from dashboard import queries

    queries.metadata.create_all(engine)
    agora = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            queries.pedidos.insert(),
            [
                {"id": 1, "usuario_id": 1, "status": "pendente_publicacao", "total": 10, "tentativas": 0, "created_at": agora},
                {"id": 2, "usuario_id": 1, "status": "processado", "total": 20, "tentativas": 0, "created_at": agora},
            ],
        )
    status = performance.pedidos_por_status(engine)
    assert status["pendente_publicacao"] == 1
    assert status["processado"] == 1
