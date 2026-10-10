"""Testes do coletor de métricas do `llm_service` (Aula 14, item 4 do DoD).

O item 3 pede latência, taxa de erro e consumo de tokens/custo estimado. Este
coletor é a única fonte dos números que o `/api/v1/llm/metrics/` expõe — os
testes aqui garantem que os agregados (taxa, média, total) batem com o que os
desfechos registram, e que o `reset()` entre testes realmente zera.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core.llm.circuit_breaker import CircuitBreaker
from core.llm.erros import CircuitoAberto, LlmErroServidor, LlmIndisponivel
from core.llm.metricas import FALHA, SUCESSO, TERMINAL, llm_metrics
from core.llm.mock import ProvedorMock
from core.llm.portas import LlmResposta
from core.llm.retry import RetryPolicy
from core.llm.servico import LlmService

pytestmark = pytest.mark.unit

MENSAGENS = [{"role": "user", "content": "checkout travou"}]


def _servico(provedor, *, redacao=True, custo_in=5.0, custo_out=15.0):
    executor = ThreadPoolExecutor(max_workers=2)
    servico = LlmService(
        provedor,
        retry=RetryPolicy(max_tentativas=1, base_segundos=0.0, fator=1.0, jitter=False),
        breaker=CircuitBreaker(limite_falhas=5, cooldown_segundos=30.0),
        executor=executor,
        redacao_ativa=redacao,
        custo_input_por_1m=custo_in,
        custo_output_por_1m=custo_out,
    )
    return servico, executor


def test_snapshot_do_coletor_vazio():
    """Nenhum desfecho registrado: agregados neutros (zero, não erro)."""
    dados = llm_metrics.snapshot()

    assert dados["chamadas"] == 0
    assert dados["sucessos"] == 0
    assert dados["falhas"] == 0
    assert dados["taxa_erro"] == 0.0
    assert dados["latencia_media_ms"] == 0.0
    assert dados["custo_usd"] == 0.0


def test_coletor_acumula_desfechos_e_totalizadores():
    llm_metrics.record(SUCESSO, tokens_prompt=100, tokens_output=50, custo_usd=0.021, latencia_ms=40.0)
    llm_metrics.record(FALHA, latencia_ms=10.0)
    llm_metrics.record(TERMINAL, latencia_ms=5.0)
    llm_metrics.record_bloqueada()

    dados = llm_metrics.snapshot()

    assert dados["chamadas"] == 3
    assert dados["sucessos"] == 1
    assert dados["falhas"] == 1
    assert dados["terminais"] == 1
    assert dados["bloqueadas"] == 1
    assert dados["tokens_prompt"] == 100
    assert dados["tokens_output"] == 50
    assert dados["custo_usd"] == pytest.approx(0.021)
    # (40 + 10 + 5) por 3 chamadas, arredondado a 2 casas (como no snapshot).
    assert dados["latencia_media_ms"] == 18.33
    assert dados["taxa_erro"] == 0.3333


def test_reset_zera_o_coletor():
    llm_metrics.record(SUCESSO)
    llm_metrics.reset()

    assert llm_metrics.snapshot()["chamadas"] == 0


def test_sucesso_registra_tokens_e_custo_estimado():
    servico, executor = _servico(ProvedorMock())
    try:
        resposta = servico.completar(MENSAGENS, temperature=0.2, max_tokens=100)
    finally:
        executor.shutdown(wait=True)

    dados = llm_metrics.snapshot()
    # Custo = (prompt / 1M * 5) + (output / 1M * 15) — positivo com tokens > 0.
    esperado = (
        resposta.tokens_prompt / 1_000_000 * 5.0
        + resposta.tokens_output / 1_000_000 * 15.0
    )
    assert dados["sucessos"] == 1
    assert dados["tokens_prompt"] == resposta.tokens_prompt
    assert dados["tokens_output"] == resposta.tokens_output
    assert dados["custo_usd"] == pytest.approx(esperado)


def test_falha_recuperavel_registra_falha_sem_tokens():
    servico, executor = _servico(ProvedorMock(falhar_com=LlmErroServidor("500")))
    try:
        with pytest.raises(LlmIndisponivel):
            servico.completar(MENSAGENS, temperature=0.2, max_tokens=100)
    finally:
        executor.shutdown(wait=True)

    dados = llm_metrics.snapshot()
    assert dados["falhas"] == 1
    assert dados["sucessos"] == 0
    assert dados["tokens_prompt"] == 0
    assert dados["tokens_output"] == 0
    # Falha recuperável com a política esgotada e limite alto: circuito fechado,
    # nada bloqueado.
    assert dados["bloqueadas"] == 0


def test_circuito_aberto_registra_bloqueada_sem_somar_chamadas():
    executor = ThreadPoolExecutor(max_workers=1)
    breaker_proibido = CircuitBreaker(limite_falhas=1)
    breaker_proibido.registrar_falha()
    servico = LlmService(
        ProvedorMock(),
        retry=RetryPolicy(max_tentativas=3, base_segundos=0.0, fator=1.0, jitter=False),
        breaker=breaker_proibido,
        executor=executor,
    )
    try:
        with pytest.raises(CircuitoAberto):
            servico.completar(MENSAGENS, temperature=0.2, max_tokens=100)
    finally:
        executor.shutdown(wait=True)

    dados = llm_metrics.snapshot()
    assert dados["bloqueadas"] == 1
    assert dados["chamadas"] == 0
    assert dados["sucessos"] == 0