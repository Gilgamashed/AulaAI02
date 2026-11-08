"""Fallback automático do `auto` para o mock (Aula 25).

A política é restrita a indisponibilidade técnica: timeout, conexão, 5xx,
rate limit, circuito aberto, credencial/modelo inválidos e resposta
vazia/malformada. Erro de requisição (400) e bloqueio de segurança são
terminais e nunca caem para o mock.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core.llm.circuit_breaker import CircuitBreaker
from core.llm.erros import (
    LlmConfiguracaoInvalida,
    LlmErroCliente,
    LlmErroServidor,
    LlmIndisponivel,
    LlmModeloIndisponivel,
    LlmTimeout,
    RespostaBloqueada,
    RespostaInvalida,
)
from core.llm.metricas import llm_metrics
from core.llm.portas import LlmResposta
from core.llm.retry import RetryPolicy
from core.llm.servico import LlmService

pytestmark = pytest.mark.unit

MENSAGENS = [{"role": "user", "content": "erro de conexão no checkout"}]


class _ProvedorFake:
    def __init__(self, *, erro: Exception | None = None, texto: str = "fallback"):
        self.erro = erro
        self.texto = texto
        self.chamadas = 0

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return LlmResposta(
            texto=self.texto,
            tokens_prompt=3,
            tokens_output=5,
        )


@pytest.fixture
def fabricar_servico():
    executores: list[ThreadPoolExecutor] = []

    def _fabricar(
        primario: _ProvedorFake,
        fallback: _ProvedorFake,
        *,
        max_tentativas: int = 3,
        breaker: CircuitBreaker | None = None,
    ) -> LlmService:
        executor = ThreadPoolExecutor(max_workers=2)
        executores.append(executor)
        return LlmService(
            primario,
            retry=RetryPolicy(
                max_tentativas=max_tentativas,
                base_segundos=0.0,
                fator=1.0,
                jitter=False,
            ),
            breaker=breaker
            or CircuitBreaker(
                limite_falhas=5,
                cooldown_segundos=30.0,
                max_tentativas_half_open=2,
            ),
            timeout_segundos=1.0,
            executor=executor,
            fallback_provedor=fallback,
            provedor_nome="gemini",
            fallback_nome="mock",
            fallback_modelo="mock",
        )

    yield _fabricar
    for executor in executores:
        executor.shutdown(wait=True)


def _chamar(servico: LlmService) -> LlmResposta:
    return servico.completar(MENSAGENS, temperature=0.0, max_tokens=32)


def test_timeout_apos_retry_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(erro=LlmTimeout("timeout"))
    fallback = _ProvedorFake(texto="resposta do mock")
    servico = fabricar_servico(primario, fallback, max_tentativas=3)

    resposta = _chamar(servico)

    assert resposta.texto == "resposta do mock"
    assert primario.chamadas == 3
    assert fallback.chamadas == 1

    dados = llm_metrics.snapshot()
    assert dados["fallbacks"] == 1
    assert dados["fallback_sucessos"] == 1
    assert dados["fallback_tokens_prompt"] == 3
    assert dados["fallback_tokens_output"] == 5
    assert dados["provedor_efetivo"] == "mock"
    assert dados["fallback_ativo"] is True
    assert dados["falhas"] == 1


def test_400_nao_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(erro=LlmErroCliente("400"))
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback)

    with pytest.raises(LlmErroCliente):
        _chamar(servico)

    assert primario.chamadas == 1
    assert fallback.chamadas == 0
    assert llm_metrics.snapshot()["fallbacks"] == 0


def test_bloqueio_de_seguranca_nao_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(
        erro=RespostaBloqueada("bloqueado", motivo="SAFETY")
    )
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback)

    with pytest.raises(RespostaBloqueada):
        _chamar(servico)

    assert primario.chamadas == 1
    assert fallback.chamadas == 0
    assert llm_metrics.snapshot()["fallbacks"] == 0


def test_resposta_invalida_vazia_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(erro=RespostaInvalida("sem texto"))
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback)

    resposta = _chamar(servico)

    assert resposta.texto == "fallback"
    assert primario.chamadas == 1
    assert fallback.chamadas == 1


def test_modelo_indisponivel_usa_fallback_apos_primeira_falha(fabricar_servico):
    primario = _ProvedorFake(erro=LlmModeloIndisponivel("modelo 404"))
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback, max_tentativas=5)

    _chamar(servico)

    assert primario.chamadas == 1
    assert fallback.chamadas == 1


def test_credencial_invalida_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(
        erro=LlmConfiguracaoInvalida("credencial inválida")
    )
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback)

    _chamar(servico)

    assert primario.chamadas == 1
    assert fallback.chamadas == 1


def test_circuito_aberto_usa_fallback_sem_chamar_primario(fabricar_servico):
    breaker = CircuitBreaker(limite_falhas=1, cooldown_segundos=30.0)
    primario = _ProvedorFake(erro=LlmErroServidor("500"))
    fallback = _ProvedorFake()
    servico = fabricar_servico(
        primario, fallback, max_tentativas=1, breaker=breaker
    )

    _chamar(servico)
    _chamar(servico)

    assert primario.chamadas == 1
    assert fallback.chamadas == 2
    assert llm_metrics.snapshot()["bloqueadas"] == 1


def test_fallback_que_tambem_falha_vira_indisponivel(fabricar_servico):
    primario = _ProvedorFake(erro=LlmTimeout("timeout"))
    fallback = _ProvedorFake(erro=LlmErroServidor("500"))
    servico = fabricar_servico(primario, fallback)

    with pytest.raises(LlmIndisponivel):
        _chamar(servico)

    assert llm_metrics.snapshot()["fallback_falhas"] == 1


def test_sucesso_primario_nao_usa_fallback(fabricar_servico):
    primario = _ProvedorFake(texto="primário")
    fallback = _ProvedorFake()
    servico = fabricar_servico(primario, fallback)

    resposta = _chamar(servico)

    assert resposta.texto == "primário"
    assert primario.chamadas == 1
    assert fallback.chamadas == 0
    assert llm_metrics.snapshot()["provedor_efetivo"] == "gemini"
    assert llm_metrics.snapshot()["fallback_ativo"] is False
