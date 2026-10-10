"""Provedor mock do llm_service (Aula 14).

Por decisão da squad, o provedor atual é **apenas um mock**: o sistema não
depende de nenhuma API de IA externa nem de credenciais, e o sistema fica
pronto para receber o provedor real no futuro (um novo adaptador que cumpre
`ProvedorLlm`). O mock não toca rede e devolve uma resposta determinística em
memória.

Dois parâmetros opcionais existem para exercitar a camada de resiliência em
desenvolvimento e nos testes que chegam ao fim da spec:

- `latencia_s`: simula um provedor lento (permite provar o timeout);
- `falhar_com`: simula uma falha do provedor (permite provar retry/circuit
  breaker pelo caminho real do `LlmService`).
"""

from __future__ import annotations

import time

from .erros import LlmErro
from .portas import LlmResposta


class ProvedorMock:
    """Provedor determinístico em memória — sem rede e sem segredos."""

    def __init__(
        self,
        *,
        latencia_s: float = 0.0,
        falhar_com: LlmErro | None = None,
    ) -> None:
        self._latencia_s = max(0.0, latencia_s)
        self._falhar_com = falhar_com

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        if self._latencia_s:
            time.sleep(self._latencia_s)
        if self._falhar_com is not None:
            raise self._falhar_com
        conteudo = mensagens[-1]["content"] if mensagens else ""
        texto = f"Assistente (mock): {conteudo}"[:max_tokens]
        return LlmResposta(
            texto=texto,
            tokens_prompt=sum(max(1, len(m.get("content", "")) // 4) for m in mensagens),
            tokens_output=max(1, len(texto) // 4),
        )