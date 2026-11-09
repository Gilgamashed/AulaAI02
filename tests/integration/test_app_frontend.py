"""Testes do mock de front-end servido em `/app/` (Aula 25)."""

from __future__ import annotations

import pytest
from django.test import Client

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_app_responde_html_sem_autenticacao(settings):
    settings.GEMINI_API_KEY = "chave-secreta-que-nao-pode-vazar"

    resposta = Client().get("/app/")

    assert resposta.status_code == 200
    assert resposta["Content-Type"].startswith("text/html")
    html = resposta.content.decode("utf-8")
    for ponto_de_montagem in (
        'id="login"',
        'id="catalogo"',
        'id="pedido"',
        'id="pagamento"',
        'id="ia"',
        'id="operacao"',
        'id="llm-resumo"',
    ):
        assert ponto_de_montagem in html
    for campo_llm in (
        "provedor_configurado",
        "provedor_efetivo",
        "ultimo_motivo_fallback",
        "fallback_ativo",
    ):
        assert campo_llm in html
    assert "chave-secreta-que-nao-pode-vazar" not in html
    assert "GEMINI_API_KEY" not in html
    assert "localStorage" not in html
    assert "innerHTML" not in html


@pytest.mark.django_db
def test_app_frontend_health_usa_rota_raiz():
    html = Client().get("/app/").content.decode("utf-8")

    assert "semApi: true" in html
    assert "montarUrl(caminho, opcoes.semApi)" in html
    assert "requisitar('/health'" in html

    resposta = Client().get("/health")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


@pytest.mark.django_db
def test_app_frontend_tem_filtro_status_timeout_refresh_e_aviso_dlq():
    html = Client().get("/app/").content.decode("utf-8")

    assert 'id="catalogo-ativo"' in html
    assert "params.set('is_active'" in html
    assert 'id="pagamento-aviso"' in html
    assert "Pagamento marcado para falha" in html
    assert html.count("AbortController") >= 2


@pytest.mark.django_db
def test_app_frontend_sql_renderiza_linhas_como_objetos():
    html = Client().get("/app/").content.decode("utf-8")

    assert "Array.isArray(linha)" in html
    assert "colunas.map((coluna) => linha[coluna])" in html


@pytest.mark.django_db
def test_app_frontend_pagamento_idempotente_exibe_aviso():
    html = Client().get("/app/").content.decode("utf-8")

    assert 'id="pagamento-idempotencia"' in html
    assert "Idempotência: nenhum novo pagamento" in html
    assert "HTTP 200 — idempotência" in html
    assert "Este pedido já tem outro pagamento" in html


@pytest.mark.django_db
def test_app_redireciona_sem_barra_final():
    resposta = Client().get("/app")

    assert resposta.status_code == 301
    assert resposta["Location"].endswith("/app/")


@pytest.mark.django_db
def test_app_frontend_recarrega_catalogo_apos_login_e_logout():
    html = Client().get("/app/").content.decode("utf-8")

    trecho_entrar = html.split("async function entrar", 1)[1].split("function sair", 1)[0]
    assert "recarregarDadosAutenticados" in trecho_entrar

    trecho_sair = html.split("function sair", 1)[1].split(
        "function configurarEventos", 1
    )[0]
    assert "carregarCatalogo()" in trecho_sair

    trecho_recarga = html.split(
        "async function recarregarDadosAutenticados", 1
    )[1].split("async function entrar", 1)[0]
    assert "carregarCategorias()" in trecho_recarga
    assert "carregarCatalogo()" in trecho_recarga
    assert "carregarPedidos()" in trecho_recarga
    assert "carregarMetricasCache()" in trecho_recarga
    assert "carregarMetricasLlm()" in trecho_recarga


@pytest.mark.django_db
def test_app_frontend_link_inventario_so_para_admin_e_na_mesma_aba():
    html = Client().get("/app/").content.decode("utf-8")

    assert 'id="link-inventario"' in html
    assert "linkInventario.hidden = estado.papel !== 'admin'" in html
    linha = next(
        linha for linha in html.splitlines() if 'id="link-inventario"' in linha
    )
    assert 'href="/app/inventario/"' in linha
    assert "target=" not in linha


@pytest.mark.django_db
def test_app_inventario_responde_html_e_nao_expoe_segredo(settings):
    settings.GEMINI_API_KEY = "chave-secreta-que-nao-pode-vazar"

    resposta = Client().get("/app/inventario/")

    assert resposta.status_code == 200
    assert resposta["Content-Type"].startswith("text/html")
    html = resposta.content.decode("utf-8")
    for ponto_de_montagem in (
        'id="inventario-restrito"',
        'id="inventario-conteudo"',
        'id="inventario-lista"',
        'id="inventario-form"',
        'id="inventario-sku"',
        'id="btn-criar"',
        'id="btn-atualizar-item"',
        'id="btn-excluir-item"',
    ):
        assert ponto_de_montagem in html
    assert "/auth/token/refresh/" in html
    assert "Authorization" in html
    assert "chave-secreta-que-nao-pode-vazar" not in html
    assert "GEMINI_API_KEY" not in html
    assert "localStorage" not in html
    assert "innerHTML" not in html


@pytest.mark.django_db
def test_app_tem_secoes_de_ia_e_checkbox_dlq_apenas_em_debug(settings):
    settings.DEBUG = True
    html_debug = Client().get("/app/").content.decode("utf-8")
    assert 'id="pedido-simular-falha"' in html_debug
    assert 'id="pagamento-simular-falha"' in html_debug

    settings.DEBUG = False
    html_producao = Client().get("/app/").content.decode("utf-8")
    assert 'id="pedido-simular-falha"' not in html_producao
    assert 'id="pagamento-simular-falha"' not in html_producao
