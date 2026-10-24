"""Testes unitários do módulo de conexão do inventory (Aula 19)."""

from __future__ import annotations

from services.inventory.app import config


def test_inventory_get_sqlalchemy_url_com_db_vars(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "synapse")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "pass")
    monkeypatch.setenv("DB_SSLMODE", "require")

    # Recarregar para aplicar novas env vars
    url = config.get_sqlalchemy_url()
    assert url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in url
