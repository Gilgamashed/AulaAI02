"""Validação do SQL do `/ask_sql/` (Aula 21)."""

from __future__ import annotations

import pytest

from core.ask_sql.erros import SqlInvalido, SqlProibido
from core.ask_sql.validacao import validar_sql

pytestmark = pytest.mark.unit

MAX = 200

CONSULTAS_VALIDAS = [
    "SELECT id, username FROM auth_user ORDER BY date_joined DESC LIMIT 5",
    "SELECT COUNT(*) AS total FROM core_pedido",
    "SELECT status, COUNT(*) AS total FROM core_pedido GROUP BY status",
    (
        "SELECT u.username, COUNT(p.id) AS total "
        "FROM auth_user AS u JOIN core_pedido AS p ON p.usuario_id = u.id "
        "GROUP BY u.username ORDER BY total DESC"
    ),
    (
        "WITH recentes AS (SELECT id, total FROM core_pedido ORDER BY created_at DESC LIMIT 3) "
        "SELECT SUM(total) AS soma FROM recentes"
    ),
    (
        "SELECT SUM(total) AS soma FROM ("
        "SELECT total FROM core_pedido ORDER BY created_at DESC LIMIT 3"
        ") AS ultimos"
    ),
    "SELECT id FROM core_pedido WHERE status = 'processado' LIMIT 10",
    "SELECT id FROM core_pedido WHERE status = 'from core_pedido; drop' LIMIT 10",
    "SELECT id FROM public.core_pedido LIMIT 1",
]


@pytest.mark.parametrize("sql", CONSULTAS_VALIDAS)
def test_aceita_consultas_de_leitura(sql):
    validado = validar_sql(sql, max_linhas=MAX)

    assert validado.sql
    assert validado.limite == MAX


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO core_pedido (total) VALUES (1)",
        "UPDATE core_pedido SET total = 0",
        "DELETE FROM core_pedido",
        "DROP TABLE core_pedido",
        "ALTER TABLE core_pedido ADD COLUMN x integer",
        "CREATE TABLE x (id integer)",
        "TRUNCATE core_pedido",
        "COPY core_pedido TO '/tmp/x'",
        "CALL proc()",
        "SET statement_timeout = 0",
        "SELECT id FROM core_pedido; DELETE FROM core_pedido",
        "SELECT id FROM core_pedido -- comentario",
        "SELECT id FROM core_pedido /* comentario */",
        "SELECT password FROM auth_user",
        "SELECT idempotency_key FROM core_pedido",
        "SELECT * FROM core_pedido",
        "SELECT p.* FROM core_pedido AS p",
        "SELECT id, * FROM core_pedido",
        "SELECT id FROM enderecos_entrega",
        "SELECT id FROM pg_catalog.pg_tables",
        "SELECT id FROM information_schema.tables",
        "SELECT id FROM core_requisicao_metrica",
        "SELECT id FROM auth_user, core_pedido",
        "SELECT id FROM core_pedido FOR UPDATE",
        "SELECT pg_sleep(10)",
        "SELECT nextval('seq')",
        "SELECT set_config('statement_timeout', '0', false)",
        'SELECT "id" FROM core_pedido',
        "SELECT id FROM core_pedido WHERE nome = 'sem fechar",
        "WITH x AS (DELETE FROM core_pedido RETURNING id) SELECT * FROM x",
    ],
)
def test_rejeita_comandos_e_referencias_proibidas(sql):
    with pytest.raises((SqlInvalido, SqlProibido)):
        validar_sql(sql, max_linhas=MAX)


def test_aceita_ponto_e_virgula_final_unico():
    validado = validar_sql("SELECT id FROM core_pedido LIMIT 1;", max_linhas=MAX)

    assert not validado.sql.endswith(";")


def test_aplica_limit_quando_ausente():
    validado = validar_sql("SELECT id FROM core_pedido", max_linhas=50)

    assert validado.sql.endswith("LIMIT 50")


def test_preserva_limit_dentro_do_teto():
    validado = validar_sql("SELECT id FROM core_pedido LIMIT 3", max_linhas=50)

    assert validado.sql == "SELECT id FROM core_pedido LIMIT 3"


def test_reduz_limit_acima_do_teto():
    validado = validar_sql("SELECT id FROM core_pedido LIMIT 500", max_linhas=200)

    assert validado.sql.endswith("LIMIT 200")


def test_substitui_limit_all():
    validado = validar_sql("SELECT id FROM core_pedido LIMIT ALL", max_linhas=20)

    assert validado.sql.endswith("LIMIT 20")


@pytest.mark.parametrize("sql", ["SELECT id FROM core_pedido LIMIT 0", "SELECT id FROM core_pedido LIMIT x"])
def test_rejeita_limit_invalido(sql):
    with pytest.raises(SqlInvalido):
        validar_sql(sql, max_linhas=10)


def test_rejeita_limite_de_linhas_invalido():
    with pytest.raises(ValueError):
        validar_sql("SELECT id FROM core_pedido", max_linhas=0)


def test_rejeita_consulta_vazia_e_longa():
    with pytest.raises(SqlInvalido):
        validar_sql("   ", max_linhas=10)
    with pytest.raises(SqlInvalido):
        validar_sql("SELECT " + "id, " * 3000 + "id FROM core_pedido", max_linhas=10)
