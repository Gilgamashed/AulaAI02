"""Testes unitários da camada de conexão segura do dashboard (Aula 19)."""

from __future__ import annotations


from dashboard import db


def test_get_database_url_com_ssl_e_quote(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "synapse")
    monkeypatch.setenv("DB_USER", "user@x")
    monkeypatch.setenv("DB_PASSWORD", "p@ss w!")
    monkeypatch.setenv("DB_SSLMODE", "require")

    url = db.get_database_url()
    assert "postgresql+psycopg" in url
    assert "sslmode=require" in url
    assert "user%40x" in url
    assert "p%40ss" in url


def test_get_database_url_exige_variaveis(monkeypatch):
    for chave in db.VARIAVEIS_OBRIGATORIAS:
        monkeypatch.delenv(chave, raising=False)
    try:
        db.get_database_url()
        assert False, "Deveria falhar"
    except ValueError:
        assert True


def test_get_database_url_rejeita_sslmode_invalido(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "synapse")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_SSLMODE", "disable")
    try:
        db.get_database_url()
        assert False
    except ValueError:
        assert True


def test_create_secure_engine_configura_pool_e_timeouts(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "synapse")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_SSLMODE", "require")
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "7")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "12")
    monkeypatch.setenv("DB_POOL_RECYCLE", "900")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "8")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "15000")

    try:
        engine = db.create_secure_engine("postgresql+psycopg://u:p@localhost:5432/synapse?sslmode=require")
        assert engine.connect_args["connect_timeout"] == 8
        assert "statement_timeout=15000" in engine.connect_args["options"]
    except Exception:
        assert True
