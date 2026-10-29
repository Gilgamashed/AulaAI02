"""Provedor mock de texto-para-SQL (Aula 21)."""

from __future__ import annotations

import pytest

from core.ask_sql.validacao import validar_sql
from core.llm.erros import LlmErroServidor
from core.llm.mock_sql import ProvedorMockSql

pytestmark = pytest.mark.unit


def _gerar(pergunta: str) -> str:
    resposta = ProvedorMockSql().completar(
        [{"role": "user", "content": f"PERGUNTA: {pergunta}"}],
        temperature=0.0,
        max_tokens=500,
    )
    return resposta.texto


def test_ultimos_usuarios_gera_select_valido():
    sql = _gerar("Quais os 5 últimos usuários cadastrados?")

    assert "FROM auth_user" in sql
    assert "ORDER BY date_joined DESC" in sql
    assert sql.endswith("LIMIT 5")
    validar_sql(sql, max_linhas=200)


def test_soma_dos_ultimos_pedidos_gera_select_valido():
    sql = _gerar("Qual a soma do valor dos últimos 3 pedidos?")

    assert "SUM(total) AS soma_total" in sql
    assert "LIMIT 3" in sql
    validar_sql(sql, max_linhas=200)


def test_usuarios_com_mais_pedidos_gera_join_explicito():
    sql = _gerar("Quais usuários fizeram mais pedidos?")

    assert "JOIN core_pedido AS p ON p.usuario_id = u.id" in sql
    assert "COUNT(p.id) AS total_pedidos" in sql
    assert "ORDER BY total_pedidos DESC" in sql
    validar_sql(sql, max_linhas=200)


@pytest.mark.parametrize(
    ("pergunta", "fragmento"),
    [
        ("Quantos pedidos existem por status?", "GROUP BY status"),
        ("Quais os produtos mais caros?", "FROM core_item"),
        ("Quantos usuários existem?", "COUNT(*) AS total_usuarios"),
        ("Qual o ticket médio dos pedidos?", "AVG(total) AS ticket_medio"),
        ("Qual o faturamento aprovado?", "WHERE aprovado = TRUE"),
        ("Quais pagamentos por método?", "FROM core_pagamento"),
        ("Notificações por canal", "FROM core_notificacao"),
        ("Quais os últimos pedidos?", "FROM core_pedido"),
    ],
)
def test_perguntas_de_negocio_geram_sql_valido(pergunta, fragmento):
    sql = _gerar(pergunta)

    assert fragmento in sql
    validar_sql(sql, max_linhas=200)


@pytest.mark.parametrize(
    "pergunta",
    [
        "Qual o endereço de entrega do pedido 42?",
        "Qual a senha do usuário admin?",
        "Qual a cor do céu?",
    ],
)
def test_pergunta_fora_do_dominio_devolve_nao_suportado(pergunta):
    assert _gerar(pergunta) == "NAO_SUPORTADO"


def test_limite_e_limitado_ao_teto():
    sql = _gerar("Quais os 999 últimos usuários cadastrados?")

    assert sql.endswith("LIMIT 200")


def test_resposta_inclui_consumo_de_tokens():
    resposta = ProvedorMockSql().completar(
        [
            {"role": "system", "content": "regras"},
            {"role": "user", "content": "PERGUNTA: quantos pedidos existem?"},
        ],
        temperature=0.0,
        max_tokens=100,
    )

    assert resposta.tokens_prompt > 0
    assert resposta.tokens_output > 0


def test_provedor_pode_simular_falha():
    provedor = ProvedorMockSql(falhar_com=LlmErroServidor("indisponível"))

    with pytest.raises(LlmErroServidor):
        provedor.completar(
            [{"role": "user", "content": "PERGUNTA: quantos pedidos existem?"}],
            temperature=0.0,
            max_tokens=100,
        )
