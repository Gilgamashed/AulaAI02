"""Extração do SQL da resposta do provedor (Aula 21)."""

from __future__ import annotations

import pytest

from core.ask_sql.erros import PerguntaNaoSuportada, SqlNaoGerado
from core.ask_sql.extracao import extrair_sql

pytestmark = pytest.mark.unit


def test_extrai_sql_puro():
    assert extrair_sql("SELECT id FROM core_pedido") == "SELECT id FROM core_pedido"


def test_extrai_de_cerca_markdown_com_texto_antes():
    resposta = (
        "Claro! Aqui está a consulta:\n"
        "```sql\nSELECT id, username FROM auth_user LIMIT 5\n```\n"
        "Ela lista os usuários."
    )

    assert (
        extrair_sql(resposta)
        == "SELECT id, username FROM auth_user LIMIT 5"
    )


def test_corta_explicacao_apos_o_ponto_e_virgula():
    resposta = (
        "SELECT id FROM core_pedido LIMIT 3; essa consulta lista três pedidos."
    )

    assert extrair_sql(resposta) == "SELECT id FROM core_pedido LIMIT 3"


def test_preserva_ponto_e_virgula_dentro_de_literal():
    consulta = "SELECT id FROM core_pedido WHERE status = 'a;b' LIMIT 1"

    assert extrair_sql(consulta) == consulta


def test_reconhece_nao_suportado():
    with pytest.raises(PerguntaNaoSuportada):
        extrair_sql("NAO_SUPORTADO")


def test_rejeita_resposta_vazia():
    with pytest.raises(SqlNaoGerado):
        extrair_sql("   ")


def test_rejeita_resposta_sem_select():
    with pytest.raises(SqlNaoGerado):
        extrair_sql("Não consigo responder essa pergunta.")
