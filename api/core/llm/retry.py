"""Política de retry com backoff exponencial e jitter (Aula 14).

O item 1 da spec pede uma política de *retry* com **backoff exponencial mais
*jitter*** (ex.: 3 tentativas). `RetryPolicy` decide o atraso entre tentativas e
só re-tenta falhas **recuperáveis** (`LlmRecuperavel`); falhas terminais
(`LlmTerminal`) propagam de imediato — retentar um 4xx do cliente não o torna
válido.

Detalhes que preparam os testes do fim da spec:

- `executar` aceita um `sleep` injetável (para não dormir de verdade nos testes);
- o `rng` do jitter é injetável (`random.Random`) para o atraso ser
  determinístico.
"""

from __future__ import annotations

import logging
import random
import time as tempo
from collections.abc import Callable
from typing import TypeVar

from .erros import LlmIndisponivel, LlmRateLimit, LlmRecuperavel, LlmTerminal, descrever

T = TypeVar("T")

logger = logging.getLogger("core.llm")


def _retry_after(falha: LlmRecuperavel) -> float:
    """Tempo sugerido pelo provedor num rate limit (`LlmRateLimit.retry_after`)."""
    if isinstance(falha, LlmRateLimit) and falha.retry_after:
        return max(0.0, float(falha.retry_after))
    return 0.0


class RetryPolicy:
    """Atraso exponencial + jitter e a decisão de retentar ou não."""

    def __init__(
        self,
        *,
        max_tentativas: int = 3,
        base_segundos: float = 1.0,
        fator: float = 2.0,
        jitter: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        if max_tentativas < 1:
            raise ValueError("max_tentativas precisa ser >= 1")
        if base_segundos < 0:
            raise ValueError("base_segundos não pode ser negativa")
        if fator <= 0:
            raise ValueError("fator precisa ser > 0")
        self._max_tentativas = max_tentativas
        self._base_segundos = base_segundos
        self._fator = fator
        self._jitter = jitter
        self._rng = rng if rng is not None else random.Random()

    @property
    def max_tentativas(self) -> int:
        return self._max_tentativas

    def atraso(self, tentativa: int) -> float:
        """Backoff exponencial (1-based) com *full jitter*.

        `base * fator ** (tentativa - 1)` e, com jitter ativo, um valor uniforme
        em `[0, base)` — o *full jitter* recomendado para estouros de rate
        limit: evita que N clientes dormindo o mesmo valor devolvam outro pico
        de requisições no mesmo instante.
        """
        base = self._base_segundos * (self._fator ** (tentativa - 1))
        if not self._jitter:
            return base
        return self._rng.uniform(0.0, base)

    def executar(
        self,
        fn: Callable[[], T],
        *,
        sleep: Callable[[float], None] | None = None,
    ) -> T:
        """Executa `fn` com até `max_tentativas` tentativas e devolve o resultado.

        Falhas `LlmTerminal` nunca são retentadas. No caso recuperável, dorme o
        backoff entre tentativas (respeitando `retry_after` de `LlmRateLimit`
        quando presente) e, ao esgotar a política, levanta `LlmIndisponivel` a
        partir da última falha.
        """
        dormir: Callable[[float], None] = sleep if sleep is not None else tempo.sleep
        ultima_falha: LlmRecuperavel | None = None

        for tentativa in range(1, self._max_tentativas + 1):
            try:
                return fn()
            except LlmTerminal:
                raise
            except LlmRecuperavel as falha:
                ultima_falha = falha
                if tentativa >= self._max_tentativas:
                    break
                atraso = max(self.atraso(tentativa), _retry_after(falha))
                logger.warning(
                    "chamada ao provedor falhou; nova tentativa",
                    extra={
                        "evento": "LlmTentativaFalhou",
                        "resultado": "erro",
                        "tentativa": tentativa,
                        "max_tentativas": self._max_tentativas,
                        "atraso_s": round(atraso, 3),
                        "erro": descrever(falha),
                    },
                )
                dormir(atraso)

        raise LlmIndisponivel(
            f"provedor de IA indisponível após {self._max_tentativas} tentativas"
        ) from ultima_falha