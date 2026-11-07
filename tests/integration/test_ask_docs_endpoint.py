"""Integração do `POST /api/v1/ask_docs/` (Aula 24).

Exercita o caminho HTTP completo: autenticação/papel, validação do payload,
índice SQLite real, recuperação por cosseno, guardrail e contrato de resposta.
"""

from __future__ import annotations

import re

import pytest

from core.ask_docs.constantes import FRASE_GUARDRAIL
from core.ask_docs.indice import IndiceRag
from core.ask_docs.ingestao import indexar
from core.ask_docs import servico as ask_docs_servico
from core.llm import (
    LlmConfiguracaoInvalida,
    LlmIndisponivel,
    LlmTerminal,
)

pytestmark = pytest.mark.integration

README = """\
# README de Teste

O cache usa Redis com TTL de sessenta segundos.

## Migrações

As migrações do banco rodam no startup da API com `python api/manage.py migrate`.

## Endpoints

O endpoint `/api/v1/pedidos/` cria pedidos autenticados.
"""

OPENAPI = """\
openapi: 3.1.0
info:
  title: API de Teste
  version: 1.0.0
paths:
  /api/v1/pedidos/:
    post:
      summary: Cria um pedido
"""

CORPO = {"question": "Como rodar as migrações do banco?", "top_k": 2, "min_score": 0.0}


def _construir_indice(tmp_path, settings) -> None:
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    indexar(
        raiz=tmp_path,
        fontes=["README.md", "docs/openapi.yaml"],
        indice=IndiceRag(settings.ASK_DOCS_INDEX_PATH),
    )


def test_sem_token_devolve_401(api_client):
    resposta = api_client.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == 401


def test_usuario_comum_devolve_403(client_autenticado):
    resposta = client_autenticado.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="sem-question"),
        pytest.param({"question": ""}, id="vazio"),
        pytest.param({"question": "   "}, id="so-espacos"),
        pytest.param({"question": 42}, id="question-nao-texto"),
        pytest.param({"question": "x" * 501}, id="acima-do-limite"),
        pytest.param({"question": "x", "top_k": 0}, id="top-k-zero"),
        pytest.param({"question": "x", "top_k": 11}, id="top-k-acima"),
        pytest.param({"question": "x", "top_k": "3"}, id="top-k-texto"),
        pytest.param({"question": "x", "top_k": True}, id="top-k-bool"),
        pytest.param({"question": "x", "min_score": -0.1}, id="score-negativo"),
        pytest.param({"question": "x", "min_score": 1.1}, id="score-acima"),
        pytest.param({"question": "x", "min_score": "0.5"}, id="score-texto"),
        pytest.param({"question": "x", "min_score": True}, id="score-bool"),
    ],
)
def test_payload_invalido_devolve_400(client_admin, payload):
    resposta = client_admin.post("/api/v1/ask_docs/", payload, format="json")

    assert resposta.status_code == 400


def test_caminho_feliz_devolve_resposta_e_fontes(tmp_path, settings, client_admin):
    _construir_indice(tmp_path, settings)

    resposta = client_admin.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == 200
    corpo = resposta.data
    assert set(corpo) == {"answer", "sources"}
    assert isinstance(corpo["answer"], str) and corpo["answer"]
    assert 1 <= len(corpo["sources"]) <= 2
    fonte = corpo["sources"][0]
    assert set(fonte) == {"path", "title", "range", "score"}
    assert fonte["path"] in {"README.md", "docs/openapi.yaml"}
    assert re.fullmatch(r"\d+-\d+", fonte["range"])
    assert isinstance(fonte["score"], float)
    assert 0.0 <= fonte["score"] <= 1.0


def test_gabarito_de_fontes_vem_da_recuperacao(tmp_path, settings, client_admin):
    _construir_indice(tmp_path, settings)

    resposta = client_admin.post(
        "/api/v1/ask_docs/",
        {"question": "Como rodar as migrações do banco?", "min_score": 0.0},
        format="json",
    )

    assert resposta.status_code == 200
    assert resposta.data["sources"][0]["path"] == "README.md"
    assert "migra" in resposta.data["answer"].lower()
    assert "[1]" in resposta.data["answer"] or "Fontes:" in resposta.data["answer"]


def test_guardrail_devolve_200_com_sources_vazio(tmp_path, settings, client_admin):
    _construir_indice(tmp_path, settings)

    resposta = client_admin.post(
        "/api/v1/ask_docs/",
        {"question": "Qual a capital da França?", "min_score": 0.25},
        format="json",
    )

    assert resposta.status_code == 200
    assert resposta.data["answer"] == FRASE_GUARDRAIL
    assert resposta.data["sources"] == []


def test_indice_vazio_devolve_503(client_admin):
    resposta = client_admin.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == 503
    assert "indexar_docs" in resposta.data["detail"]


def test_indice_indisponivel_devolve_503(tmp_path, settings, client_admin):
    caminho = tmp_path / "diretorio"
    caminho.mkdir()
    settings.ASK_DOCS_INDEX_PATH = str(caminho)

    resposta = client_admin.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == 503


@pytest.mark.parametrize(
    "erro,codigo",
    [
        pytest.param(LlmConfiguracaoInvalida("config"), 500, id="config"),
        pytest.param(LlmIndisponivel("fora"), 503, id="indisponivel"),
        pytest.param(LlmTerminal("invalida"), 502, id="terminal"),
    ],
)
def test_erros_do_provedor_mapeiam_http(
    tmp_path,
    settings,
    client_admin,
    monkeypatch,
    erro,
    codigo,
):
    _construir_indice(tmp_path, settings)

    def _falhar(*args, **kwargs):
        raise erro

    monkeypatch.setattr(ask_docs_servico, "criar_llm_service", _falhar)

    resposta = client_admin.post("/api/v1/ask_docs/", CORPO, format="json")

    assert resposta.status_code == codigo


def test_top_k_limita_a_lista_de_fontes(tmp_path, settings, client_admin):
    _construir_indice(tmp_path, settings)

    resposta = client_admin.post(
        "/api/v1/ask_docs/",
        {"question": "Como rodar as migrações do banco?", "top_k": 1, "min_score": 0.0},
        format="json",
    )

    assert resposta.status_code == 200
    assert len(resposta.data["sources"]) == 1
