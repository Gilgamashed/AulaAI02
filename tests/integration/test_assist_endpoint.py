"""Integração do `POST /api/v1/assist` e do `GET /api/v1/llm/metrics/` (Aula 14).

O item 4 do DoD pede o caminho HTTP de ponta a ponta. Aqui a view é exercitada
como o cliente a vê — autenticação JWT, validação do serializer, tradução do
desfecho do `llm_service` para o status correto e o contrato de resposta
(`answer` + `meta`), além da política de redação e da telemetria.

O caminho de falha **não** usa o singleton do `llm_service`: patchar
`core.views.criar_llm_service` com um serviço fresco evita que uma falha
forçada por um teste abra o circuit breaker do processo e contamine os demais
(mesmo motivo pelo qual a suíte isola o broker em `broker_capturado`).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core import views as core_views
from core.llm.circuit_breaker import CircuitBreaker
from core.llm.erros import (
    LlmConfiguracaoInvalida,
    LlmErroServidor,
    RespostaInvalida,
)
from core.llm.metricas import llm_metrics
from core.llm.mock import ProvedorMock
from core.llm.retry import RetryPolicy
from core.llm.servico import LlmService

pytestmark = pytest.mark.integration

CORPO_VALIDO = {"mode": "summarize", "logs": ["pedido 42 falhou no pagamento"]}


def _servico_com_falha(excecao):
    """`LlmService` fresco com um provedor que sempre falha (para o patch)."""
    executor = ThreadPoolExecutor(max_workers=2)
    servico = LlmService(
        ProvedorMock(falhar_com=excecao),
        retry=RetryPolicy(max_tentativas=2, base_segundos=0.0, fator=1.0, jitter=False),
        breaker=CircuitBreaker(limite_falhas=5, cooldown_segundos=30.0),
        timeout_segundos=1.0,
        executor=executor,
    )
    return servico, executor


# =====================================================================
# Autenticação
# =====================================================================
def test_assist_sem_token_devolve_401(api_client):
    resposta = api_client.post("/api/v1/assist/", CORPO_VALIDO, format="json")

    assert resposta.status_code == 401


# =====================================================================
# Caminho feliz
# =====================================================================
def test_assist_feliz_respeita_o_contrato(client_autenticado):
    resposta = client_autenticado.post("/api/v1/assist/", CORPO_VALIDO, format="json")

    assert resposta.status_code == 200
    corpo = resposta.data
    assert set(corpo) == {"answer", "meta"}
    assert isinstance(corpo["answer"], str) and corpo["answer"]
    assert isinstance(corpo["meta"]["tokens_prompt"], int)
    assert isinstance(corpo["meta"]["tokens_output"], int)
    assert corpo["meta"]["tokens_prompt"] > 0
    assert corpo["meta"]["tokens_output"] > 0


def test_assist_alimenta_a_telemetria(client_autenticado):
    client_autenticado.post("/api/v1/assist/", CORPO_VALIDO, format="json")

    dados = llm_metrics.snapshot()
    assert dados["sucessos"] == 1
    assert dados["chamadas"] == 1


# =====================================================================
# Payload inválido (400)
# =====================================================================
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"mode": "traduzir", "logs": ["x"]}, id="mode-invalido"),
        pytest.param({"mode": "summarize", "logs": []}, id="logs-vazio"),
        pytest.param({"mode": "summarize", "logs": 42}, id="logs-tipo-errado"),
        pytest.param(
            {"mode": "summarize", "logs": ["x"], "max_tokens": 9999},
            id="max-tokens-fora-da-faixa",
        ),
        pytest.param(
            {"mode": "summarize", "logs": ["x"], "temperature": 2.0},
            id="temperature-fora-da-faixa",
        ),
    ],
)
def test_assist_payload_invalido_devolve_400(client_autenticado, payload):
    resposta = client_autenticado.post("/api/v1/assist/", payload, format="json")

    assert resposta.status_code == 400


# =====================================================================
# Redação de PII ponta a ponta
# =====================================================================
def test_assist_nao_devolve_pii_crua_na_resposta(client_autenticado):
    """O mock ecoa o prompt: se a redação falhasse, a PII apareceria no `answer`."""
    payload = {
        "mode": "explain",
        "logs": [
            "cliente fulano@gmail.com abriu chamado",
            "cpf 123.456.789-01 consta no cadastro",
        ],
    }

    resposta = client_autenticado.post("/api/v1/assist/", payload, format="json")

    assert resposta.status_code == 200
    answer = resposta.data["answer"]
    assert "fulano@gmail.com" not in answer
    assert "123.456.789-01" not in answer
    assert "[EMAIL]" in answer
    assert "[CPF_CNPJ]" in answer


# =====================================================================
# Tradução de falhas do provedor
# =====================================================================
def test_assist_provedor_indisponivel_devolve_503(client_autenticado, monkeypatch):
    servico, executor = _servico_com_falha(LlmErroServidor("500 do provedor"))
    monkeypatch.setattr(core_views, "criar_llm_service", lambda: servico)
    try:
        resposta = client_autenticado.post("/api/v1/assist/", CORPO_VALIDO, format="json")
    finally:
        executor.shutdown(wait=True)

    assert resposta.status_code == 503


def test_assist_resposta_invalida_do_provedor_devolve_502(client_autenticado, monkeypatch):
    servico, executor = _servico_com_falha(RespostaInvalida("corpo fora do contrato"))
    monkeypatch.setattr(core_views, "criar_llm_service", lambda: servico)
    try:
        resposta = client_autenticado.post("/api/v1/assist/", CORPO_VALIDO, format="json")
    finally:
        executor.shutdown(wait=True)

    assert resposta.status_code == 502


def test_assist_configuracao_invalida_devolve_500(client_autenticado, monkeypatch):
    def _explodir():
        raise LlmConfiguracaoInvalida("LLM_PROVIDER desconhecido")

    monkeypatch.setattr(core_views, "criar_llm_service", _explodir)
    resposta = client_autenticado.post("/api/v1/assist/", CORPO_VALIDO, format="json")

    assert resposta.status_code == 500


# =====================================================================
# Telemetria (GET /api/v1/llm/metrics/)
# =====================================================================
def test_metrics_admin_recebe_o_snapshot(client_admin):
    resposta = client_admin.get("/api/v1/llm/metrics/")

    assert resposta.status_code == 200
    corpo = resposta.data
    assert corpo["provedor"] == "mock"
    assert corpo["modelo"] == "mock"
    assert "timeout_segundos" in corpo
    assert set(corpo["custo_por_1m_tokens"]) == {"input_usd", "output_usd"}
    assert "chamadas" in corpo["total"]
    assert "taxa_erro" in corpo["total"]
    assert "latencia_media_ms" in corpo["total"]


def test_metrics_sem_token_e_barrado(api_client):
    resposta = api_client.get("/api/v1/llm/metrics/")

    assert resposta.status_code in (401, 403)


def test_metrics_usuario_comum_e_barrado(client_autenticado):
    resposta = client_autenticado.get("/api/v1/llm/metrics/")

    assert resposta.status_code == 403