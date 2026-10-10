"""Testes de resiliência do `llm_service` (Aula 14, item 4 do DoD).

A spec do item 1 define as margens de timeout, retry e circuit breaker; o item 4
manda **prová-las**. Estes testes exercitam cada margem pelas classes reais —
não por duplos da própria política — porque o que precisa ser garantido é o
comportamento que roda em produção:

* **timeout**: o provedor que não responde vira `LlmTimeout` (recuperável) e,
  esgotada a política, `LlmIndisponivel` — o chamador nunca fica pendurado;
* **retry**: backoff exponencial determinístico (jitter injetável), respeito ao
  `retry_after` do rate limit e não-retentar falha terminal;
* **circuit breaker**: `closed → open → half-open → closed`, fail-fast (uma
  chamada bloqueada não chega ao provedor) e o 4xx que não conta falha;
* **métricas**: cada desfecho alimenta `llm_metrics` — a evidência do item 3.
"""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.llm.circuit_breaker import CircuitBreaker, CircuitState
from core.llm.erros import (
    CircuitoAberto,
    LlmErroCliente,
    LlmErroServidor,
    LlmIndisponivel,
    LlmRateLimit,
    LlmTimeout,
    RespostaInvalida,
)
from core.llm.metricas import llm_metrics
from core.llm.mock import ProvedorMock
from core.llm.portas import LlmResposta
from core.llm.retry import RetryPolicy
from core.llm.servico import LlmService

pytestmark = pytest.mark.unit

MENSAGENS = [{"role": "user", "content": "erro de conexão no checkout"}]


def _retry(max_tentativas: int = 1) -> RetryPolicy:
    """Política sem espera: os atrasos ficam nos testes do próprio retry."""
    return RetryPolicy(
        max_tentativas=max_tentativas, base_segundos=0.0, fator=1.0, jitter=False
    )


@pytest.fixture
def fabricar_servico():
    """Constrói `LlmService` com executor fechado no teardown.

    O executor é passado explicitamente e encerrado no fim do teste: deixar as
    threads de guarda de timeout acumularem entre casos é a forma mais discreta
    de a suíte ficar lenta (ou pendurada) sem nenhum teste falhar.
    """
    executores: list[ThreadPoolExecutor] = []

    def _fabricar(
        provedor,
        *,
        retry=None,
        breaker=None,
        timeout=1.0,
        redacao=True,
        custo_in=0.0,
        custo_out=0.0,
    ) -> LlmService:
        executor = ThreadPoolExecutor(max_workers=2)
        executores.append(executor)
        return LlmService(
            provedor,
            retry=retry or _retry(),
            breaker=breaker
            or CircuitBreaker(
                limite_falhas=5, cooldown_segundos=30.0, max_tentativas_half_open=2
            ),
            timeout_segundos=timeout,
            executor=executor,
            redacao_ativa=redacao,
            custo_input_por_1m=custo_in,
            custo_output_por_1m=custo_out,
        )

    yield _fabricar
    for executor in executores:
        executor.shutdown(wait=True)


# =====================================================================
# Timeout
# =====================================================================
def test_timeout_vira_llm_indisponivel_com_causa_timeout(fabricar_servico):
    """O estouro do deadline tem de ser rastreável até `LlmTimeout`.

    A distinção importa para o adaptador HTTP do futuro: timeout é recuperável
    (vale retry), ao contrário de um 4xx. A causa (`__cause__`) preserva de onde
    veio a indisponibilidade.
    """
    servico = fabricar_servico(ProvedorMock(latencia_s=0.2), timeout=0.01)

    with pytest.raises(LlmIndisponivel) as erro:
        servico.completar(MENSAGENS, temperature=0.2, max_tokens=64)

    assert isinstance(erro.value.__cause__, LlmTimeout)


def test_timeout_e_recuperavel_e_respeita_o_texto_do_deadline(fabricar_servico):
    servico = fabricar_servico(ProvedorMock(latencia_s=0.2), timeout=0.01)

    with pytest.raises(LlmIndisponivel):
        servico.completar(MENSAGENS, temperature=0.2, max_tokens=64)

    assert llm_metrics.snapshot()["falhas"] == 1


# =====================================================================
# Retry (backoff + jitter)
# =====================================================================
def test_atraso_exponencial_sem_jitter():
    """1s, 2s, 4s — `base * fator ** (tentativa - 1)`; sem aleatoriedade aqui."""
    policy = RetryPolicy(
        max_tentativas=3, base_segundos=1.0, fator=2.0, jitter=False
    )

    assert policy.atraso(1) == 1.0
    assert policy.atraso(2) == 2.0
    assert policy.atraso(3) == 4.0


def test_jitter_full_e_uniforme_em_zero_e_base():
    """Com jitter, o atraso cai em `[0, base)` — o *full jitter* da spec.

    O `rng` injetável é o que torna a asserção possível: com uma semente fixa,
    o valor é determinístico, e ainda assim comprovamos o teto (nunca chega a
    `base`, evitando o pico de N clientes acordando juntos).
    """
    policy = RetryPolicy(
        max_tentativas=3,
        base_segundos=1.0,
        fator=2.0,
        jitter=True,
        rng=random.Random(2026),
    )
    atrasos = [policy.atraso(2) for _ in range(50)]

    assert all(0.0 <= valor <= 2.0 for valor in atrasos)
    assert len({round(valor, 2) for valor in atrasos}) > 1


def test_esgota_tentativas_e_levanta_llm_indisponivel():
    """Falha recuperável persistente: tenta `max_tentativas` e desiste."""
    tentativas = []
    dormidas: list[float] = []

    def falhar():
        tentativas.append(1)
        raise LlmErroServidor("500 do provedor")

    policy = RetryPolicy(max_tentativas=3, base_segundos=1.0, fator=2.0, jitter=False)

    with pytest.raises(LlmIndisponivel):
        policy.executar(falhar, sleep=dormidas.append)

    assert len(tentativas) == 3
    # Dorme entre as tentativas, mas não depois da última (não há retry a fazer).
    assert dormidas == [1.0, 2.0]


def test_respeita_retry_after_do_rate_limit():
    """429 com `retry_after=5` espera os 5s do provedor, não o backoff de 1s."""
    dormidas: list[float] = []
    policy = RetryPolicy(max_tentativas=2, base_segundos=1.0, fator=2.0, jitter=False)

    def rate_limit():
        raise LlmRateLimit("429", retry_after=5.0)

    with pytest.raises(LlmIndisponivel):
        policy.executar(rate_limit, sleep=dormidas.append)

    assert dormidas == [5.0]


def test_backoff_maior_que_retry_after_e_usado():
    """Quando o backoff da política excede o sugerido, o backoff prevalece."""
    dormidas: list[float] = []
    policy = RetryPolicy(max_tentativas=3, base_segundos=1.0, fator=2.0, jitter=False)

    def rate_limit():
        raise LlmRateLimit("429", retry_after=0.5)

    with pytest.raises(LlmIndisponivel):
        policy.executar(rate_limit, sleep=dormidas.append)

    assert dormidas == [1.0, 2.0]


def test_terminal_nao_e_retentado():
    """4xx do cliente não melhora com retry: propaga de imediato."""
    tentativas = []

    def rejeitar():
        tentativas.append(1)
        raise LlmErroCliente("400 do provedor")

    policy = RetryPolicy(max_tentativas=5, base_segundos=0.0, fator=1.0, jitter=False)

    with pytest.raises(LlmErroCliente):
        policy.executar(rejeitar, sleep=lambda _: None)

    assert len(tentativas) == 1


def test_sucesso_na_segunda_tentativa_interrompe_o_retry():
    tentativas = []

    def instavel():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise LlmErroServidor("500 transitório")
        return "ok"

    policy = RetryPolicy(max_tentativas=3, base_segundos=0.0, fator=1.0, jitter=False)

    assert policy.executar(instavel, sleep=lambda _: None) == "ok"
    assert len(tentativas) == 2


# =====================================================================
# Circuit breaker
# =====================================================================
def test_circuito_abre_ao_atingir_o_limite_de_falhas():
    breaker = CircuitBreaker(limite_falhas=3)

    for _ in range(3):
        breaker.registrar_falha()

    assert breaker.estado is CircuitState.ABERTO
    assert breaker.permitir_chamada() is False


def test_circuito_meio_aberto_apos_cooldown():
    """Passado o cooldown, a próxima chamada é a sonda (half-open)."""
    tempo = {"t": 0.0}
    breaker = CircuitBreaker(
        limite_falhas=1, cooldown_segundos=30.0, relogio=lambda: tempo["t"]
    )
    breaker.registrar_falha()
    assert breaker.estado is CircuitState.ABERTO

    tempo["t"] = 31.0

    assert breaker.permitir_chamada() is True
    assert breaker.estado is CircuitState.MEIO_ABERTO


def test_sucesso_na_sonda_fecha_o_circuito_e_zera_falhas():
    tempo = {"t": 0.0}
    breaker = CircuitBreaker(
        limite_falhas=1, cooldown_segundos=10.0, relogio=lambda: tempo["t"]
    )
    breaker.registrar_falha()
    tempo["t"] = 11.0
    breaker.permitir_chamada()

    breaker.registrar_sucesso()

    assert breaker.estado is CircuitState.FECHADO
    assert breaker.falhas == 0


def test_falha_na_sonda_reabre_imediatamente():
    tempo = {"t": 0.0}
    breaker = CircuitBreaker(
        limite_falhas=5, cooldown_segundos=10.0, relogio=lambda: tempo["t"]
    )
    for _ in range(5):
        breaker.registrar_falha()
    tempo["t"] = 11.0
    breaker.permitir_chamada()

    breaker.registrar_falha()

    assert breaker.estado is CircuitState.ABERTO


def test_meio_aberto_limita_as_sondas():
    """Half-open deixa passar só `max_tentativas_half_open` chamadas de sonda."""
    tempo = {"t": 0.0}
    breaker = CircuitBreaker(
        limite_falhas=1,
        cooldown_segundos=10.0,
        max_tentativas_half_open=2,
        relogio=lambda: tempo["t"],
    )
    breaker.registrar_falha()
    tempo["t"] = 11.0

    assert breaker.permitir_chamada() is True
    assert breaker.permitir_chamada() is True
    assert breaker.permitir_chamada() is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limite_falhas": 0},
        {"cooldown_segundos": -1.0},
        {"max_tentativas_half_open": 0},
    ],
)
def test_configuracao_invalida_do_breaker_e_recusada(kwargs):
    with pytest.raises(ValueError):
        CircuitBreaker(**kwargs)


# =====================================================================
# Integração do serviço (breaker + retry + timeout + métricas)
# =====================================================================
def test_esgotar_retry_conta_uma_falha_no_breaker_e_bloqueia_a_proxima(fabricar_servico):
    """Uma chamada indisponível abre o circuito (limite 1) e a seguinte é fail-fast."""
    breaker = CircuitBreaker(limite_falhas=1, cooldown_segundos=30.0)
    servico = fabricar_servico(
        ProvedorMock(falhar_com=LlmErroServidor("500")),
        retry=_retry(max_tentativas=3),
        breaker=breaker,
    )

    with pytest.raises(LlmIndisponivel) as primeira:
        servico.completar(MENSAGENS, temperature=0.2, max_tokens=64)
    assert not isinstance(primeira.value, CircuitoAberto)
    assert breaker.estado is CircuitState.ABERTO

    with pytest.raises(CircuitoAberto):
        servico.completar(MENSAGENS, temperature=0.2, max_tokens=64)

    metricas = llm_metrics.snapshot()
    assert metricas["falhas"] == 1
    assert metricas["bloqueadas"] == 1


def test_terminal_nao_conta_falha_no_breaker_nem_no_retry(fabricar_servico):
    breaker = CircuitBreaker(limite_falhas=1, cooldown_segundos=30.0)
    servico = fabricar_servico(
        ProvedorMock(falhar_com=RespostaInvalida("corpo fora do contrato")),
        retry=_retry(max_tentativas=5),
        breaker=breaker,
    )

    with pytest.raises(RespostaInvalida):
        servico.completar(MENSAGENS, temperature=0.2, max_tokens=64)

    assert breaker.estado is CircuitState.FECHADO
    assert breaker.falhas == 0
    assert llm_metrics.snapshot()["terminais"] == 1


def test_sucesso_registra_tokens_custo_e_latencia(fabricar_servico):
    servico = fabricar_servico(
        ProvedorMock(), redacao=False, custo_in=5.0, custo_out=15.0
    )

    resposta = servico.completar(MENSAGENS, temperature=0.2, max_tokens=200)

    assert isinstance(resposta, LlmResposta)
    metricas = llm_metrics.snapshot()
    assert metricas["chamadas"] == 1
    assert metricas["sucessos"] == 1
    assert metricas["tokens_prompt"] == resposta.tokens_prompt
    assert metricas["tokens_output"] == resposta.tokens_output
    assert metricas["taxa_erro"] == 0.0
    # Custo estimado a partir do preço configurado — maior que zero porque os
    # tokens também são (o preço de exemplo não é zero).
    assert metricas["custo_usd"] > 0
    assert metricas["latencia_media_ms"] >= 0
