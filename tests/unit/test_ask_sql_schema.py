"""Allow-list e contexto de schema do texto-para-SQL (Aula 21)."""

from __future__ import annotations

import pytest

from core.ask_sql import schema
from core.ask_sql.constantes import TABELAS, TABELAS_PERMITIDAS

pytestmark = pytest.mark.unit


def test_contexto_descreve_tabelas_relacionamentos_e_glossario():
    texto = schema.contexto()

    assert "CREATE TABLE auth_user" in texto
    assert "CREATE TABLE core_pedido" in texto
    assert "core_pedido.usuario_id -> auth_user.id" in texto
    assert "usuários/clientes = auth_user" in texto
    assert "enderecos_entrega" in texto
    assert "pg_catalog" in texto


def test_allow_list_nao_expoe_colunas_sensiveis():
    for tabela in TABELAS.values():
        assert "password" not in tabela["colunas"]
        assert "idempotency_key" not in tabela["colunas"]
        assert "transacao_id" not in tabela["colunas"]


def test_allow_list_nao_inclui_tabelas_internas():
    assert "core_requisicao_metrica" not in TABELAS_PERMITIDAS
    assert "django_session" not in TABELAS_PERMITIDAS
    assert "auth_group" not in TABELAS_PERMITIDAS


def test_colunas_da_allow_list_existem_nos_models():
    from django.contrib.auth import get_user_model

    from core.models import Category, Item, Notificacao, Pagamento, Pedido

    models = {
        "auth_user": get_user_model(),
        "core_pedido": Pedido,
        "core_pagamento": Pagamento,
        "core_notificacao": Notificacao,
        "core_item": Item,
        "core_category": Category,
    }
    for tabela, model in models.items():
        assert model._meta.db_table == tabela
        colunas_do_model = {campo.column for campo in model._meta.concrete_fields}
        assert set(TABELAS[tabela]["colunas"]) <= colunas_do_model


def test_validar_consistencia_nao_levanta_para_a_allow_list_atual():
    schema.validar_consistencia()
