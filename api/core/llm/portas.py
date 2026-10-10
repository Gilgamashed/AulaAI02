"""Porta do provedor de LLM e contrato de resposta (Aula 14).

O item 1 da spec constrói a resiliência do `llm_service`; o provedor de hoje é
um **mock** em memória. A porta é o ponto único de acoplamento: qualquer
provedor futuro (por exemplo, um adaptador HTTP compatível com a API de *chat
completions*) precisa apenas cumprir `ProvedorLlm` e ser selecionado pela
fábrica em `servico.criar_llm_service` — a resiliência (timeout, retry e
circuit breaker) não muda.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LlmResposta:
    """Resposta de completamento do provedor, com o consumo de tokens."""

    texto: str
    tokens_prompt: int
    tokens_output: int


@runtime_checkable
class ProvedorLlm(Protocol):
    """Contrato que todo provedor de IA precisa cumprir."""

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        """Gera um completamento para `mensagens` e devolve a resposta."""
        ...