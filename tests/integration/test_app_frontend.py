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
    ):
        assert ponto_de_montagem in html
    assert "chave-secreta-que-nao-pode-vazar" not in html
    assert "GEMINI_API_KEY" not in html
    assert "localStorage" not in html
    assert "innerHTML" not in html


@pytest.mark.django_db
def test_app_redireciona_sem_barra_final():
    resposta = Client().get("/app")

    assert resposta.status_code == 301
    assert resposta["Location"].endswith("/app/")


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
