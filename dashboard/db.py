"""Conexão segura com o PostgreSQL via SQLAlchemy (Aula 19).

A URL é montada exclusivamente a partir de variáveis de ambiente. O engine
habilita *pooling*, tempos limite e exige TLS/SSL (`DB_SSLMODE=require` por
padrão). Nenhum valor sensível fica hardcoded no código.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

SSL_MODES_PERMITIDOS = frozenset({"require", "verify-ca", "verify-full"})
VARIAVEIS_OBRIGATORIAS = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")


def _env(nome: str, padrao: str | None = None) -> str:
    valor = os.environ.get(nome, padrao)
    if valor is None or valor.strip() == "":
        raise ValueError(f"Variável de ambiente obrigatória ausente: {nome}")
    return valor.strip()


def _env_int(nome: str, padrao: int) -> int:
    valor = os.environ.get(nome, str(padrao)).strip()
    try:
        return int(valor)
    except ValueError as exc:
        raise ValueError(f"Variável de ambiente {nome} deve ser inteira: {valor!r}") from exc


def _validar_sslmode() -> str:
    sslmode = os.environ.get("DB_SSLMODE", "require").strip().lower() or "require"
    if sslmode not in SSL_MODES_PERMITIDOS:
        permitidos = ", ".join(sorted(SSL_MODES_PERMITIDOS))
        raise ValueError(
            f"DB_SSLMODE inseguro ou desconhecido: {sslmode!r}. Use um de: {permitidos}."
        )
    return sslmode


def _validar_porta() -> int:
    porta = _env_int("DB_PORT", 5432)
    if not 1 <= porta <= 65535:
        raise ValueError(f"DB_PORT fora do intervalo válido: {porta}")
    return porta


def get_database_url() -> str:
    """Monta a URL do PostgreSQL com credenciais seguras e SSL/TLS."""
    ausentes = [nome for nome in VARIAVEIS_OBRIGATORIAS if not os.environ.get(nome)]
    if ausentes:
        raise ValueError(
            "Variáveis de ambiente obrigatórias ausentes: " + ", ".join(ausentes)
        )

    url = URL.create(
        drivername="postgresql+psycopg",
        username=_env("DB_USER"),
        password=_env("DB_PASSWORD"),
        host=_env("DB_HOST"),
        port=_validar_porta(),
        database=_env("DB_NAME"),
        query={"sslmode": _validar_sslmode()},
    )
    return url.render_as_string(hide_password=False)


def create_secure_engine(database_url: str | None = None) -> Engine:
    """Cria um engine com pool, timeouts e criptografia obrigatória."""
    timeout_ms = _env_int("DB_STATEMENT_TIMEOUT_MS", 30000)
    if timeout_ms <= 0:
        raise ValueError("DB_STATEMENT_TIMEOUT_MS deve ser positivo")

    return create_engine(
        database_url or get_database_url(),
        pool_size=_env_int("DB_POOL_SIZE", 10),
        max_overflow=_env_int("DB_MAX_OVERFLOW", 20),
        pool_timeout=_env_int("DB_POOL_TIMEOUT", 30),
        pool_recycle=_env_int("DB_POOL_RECYCLE", 1800),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "connect_timeout": _env_int("DB_CONNECT_TIMEOUT", 10),
            "options": f"-c statement_timeout={timeout_ms}",
        },
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine compartilhado do processo (o pool é a fonte de reuso)."""
    return create_secure_engine()
