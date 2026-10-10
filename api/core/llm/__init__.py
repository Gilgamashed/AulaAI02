"""Camada de IA do SynapseShop (Aula 14) — llm_service.

O item 1 da spec constrói a **resiliência** da comunicação com o provedor de IA:
timeout (<=5s), retry com backoff exponencial + jitter e circuit breaker
(closed/open/half-open). O provedor de hoje é um **mock** em memória; o sistema
está pronto para receber o provedor real pela mesma porta (`ProvedorLlm`), sem
mudar a resiliência.

Uso típico (o endpoint `POST /api/v1/assist` chega no item 2):

    from core.llm import criar_llm_service

    servico = criar_llm_service()
    resposta = servico.completar(
        [{"role": "user", "content": "resuma este log"}],
        temperature=0.2,
        max_tokens=256,
    )
"""

from __future__ import annotations

from .circuit_breaker import CircuitBreaker, CircuitState
from .erros import (
    CircuitoAberto,
    LlmConexao,
    LlmConfiguracaoInvalida,
    LlmErro,
    LlmErroCliente,
    LlmErroServidor,
    LlmIndisponivel,
    LlmRateLimit,
    LlmRecuperavel,
    LlmTerminal,
    LlmTimeout,
    RespostaInvalida,
    descrever,
)
from .mock import ProvedorMock
from .portas import LlmResposta, ProvedorLlm
from .retry import RetryPolicy
from .servico import PROVIDER_MOCK, LlmService, criar_llm_service

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitoAberto",
    "LlmConexao",
    "LlmConfiguracaoInvalida",
    "LlmErro",
    "LlmErroCliente",
    "LlmErroServidor",
    "LlmIndisponivel",
    "LlmRateLimit",
    "LlmRecuperavel",
    "LlmResposta",
    "LlmService",
    "LlmTerminal",
    "LlmTimeout",
    "PROVIDER_MOCK",
    "ProvedorLlm",
    "ProvedorMock",
    "RespostaInvalida",
    "RetryPolicy",
    "criar_llm_service",
    "descrever",
]