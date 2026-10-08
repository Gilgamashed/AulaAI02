"""Smoke test das rotas de documentação interativa (Aula 13, DoD 4).

Define o DoD 4 em termos verificáveis: o contrato `docs/openapi.yaml` é
servido pela aplicação e o Swagger UI e o ReDoc respondem com HTML a carregar
esse contrato. Nenhum destes casos toca banco nem broker — são views puras.
"""

import pytest

pytestmark = pytest.mark.unit

_CONTRATO = "application/yaml; charset=utf-8"


def test_contrato_openapi_e_servido(api_client):
    resposta = api_client.get("/docs/openapi.yaml")

    assert resposta.status_code == 200
    assert resposta["Content-Type"] == _CONTRATO
    assert b"openapi: 3.1.0" in resposta.content


def test_swagger_ui_aponta_para_o_contrato(api_client):
    resposta = api_client.get("/docs/")

    assert resposta.status_code == 200
    assert b"/docs/openapi.yaml" in resposta.content
    assert b"swagger" in resposta.content.lower()


def test_redoc_aponta_para_o_contrato(api_client):
    resposta = api_client.get("/redoc/")

    assert resposta.status_code == 200
    assert b"/docs/openapi.yaml" in resposta.content
    assert b"redoc" in resposta.content.lower()