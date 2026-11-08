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
    LlmModeloIndisponivel,
    LlmRateLimit,
    LlmRecuperavel,
    LlmTerminal,
    LlmTimeout,
    RespostaBloqueada,
    RespostaInvalida,
    descrever,
)
from .gemini import ProvedorGemini
from .mock import ProvedorMock
from .mock_docs import ProvedorMockDocs
from .mock_sql import ProvedorMockSql
from .portas import LlmResposta, ProvedorLlm
from .retry import RetryPolicy
from .servico import (
    PROVIDER_AUTO,
    PROVIDER_GEMINI,
    PROVIDER_MOCK,
    TAREFA_ASSIST,
    TAREFA_DOCS,
    TAREFA_SQL,
    LlmService,
    criar_llm_service,
    modelos_efetivos,
    provedor_primario,
)

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
    "LlmModeloIndisponivel",
    "LlmRateLimit",
    "LlmRecuperavel",
    "LlmResposta",
    "LlmService",
    "LlmTerminal",
    "LlmTimeout",
    "PROVIDER_AUTO",
    "PROVIDER_GEMINI",
    "PROVIDER_MOCK",
    "ProvedorGemini",
    "ProvedorLlm",
    "ProvedorMock",
    "ProvedorMockDocs",
    "ProvedorMockSql",
    "RespostaBloqueada",
    "RespostaInvalida",
    "RetryPolicy",
    "TAREFA_ASSIST",
    "TAREFA_DOCS",
    "TAREFA_SQL",
    "criar_llm_service",
    "descrever",
    "modelos_efetivos",
    "provedor_primario",
]