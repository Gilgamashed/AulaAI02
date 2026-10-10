"""Circuit breaker do llm_service (Aula 14): closed/open/half-open.

Padrão clássico de resiliência sobre as chamadas ao provedor de IA:

- **closed (fechado):** fluxo normal. Cada falha incrementa o contador; ao
  atingir `limite_falhas`, o circuito abre (fail-fast);
- **open (aberto):** nenhuma chamada chega ao provedor — `permitir_chamada()`
  devolve `False` e o `LlmService` responde `CircuitoAberto`. Após
  `cooldown_segundos`, passa a meio-aberto;
- **half-open (meio-aberto):** deixa passar até `max_tentativas_half_open`
  chamadas de sonda. Um sucesso fecha o circuito (zera o contador); uma falha
  reabre o circuito imediatamente.

Thread-safe: o gunicorn serve várias threads no mesmo processo e o breaker é
singleton por processo (ver `servico.criar_llm_service`).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger("core.llm")


class CircuitState(str, Enum):
    """Estados possíveis do circuito."""

    FECHADO = "closed"
    ABERTO = "open"
    MEIO_ABERTO = "half-open"


class CircuitBreaker:
    """Decide se a chamada pode seguir e evolui entre os três estados."""

    def __init__(
        self,
        *,
        limite_falhas: int = 5,
        cooldown_segundos: float = 30.0,
        max_tentativas_half_open: int = 2,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        if limite_falhas < 1:
            raise ValueError("limite_falhas precisa ser >= 1")
        if cooldown_segundos < 0:
            raise ValueError("cooldown_segundos não pode ser negativa")
        if max_tentativas_half_open < 1:
            raise ValueError("max_tentativas_half_open precisa ser >= 1")
        self._limite_falhas = limite_falhas
        self._cooldown_segundos = cooldown_segundos
        self._max_tentativas_half_open = max_tentativas_half_open
        self._relogio = relogio
        self._estado = CircuitState.FECHADO
        self._falhas = 0
        self._aberto_desde: float | None = None
        self._tentativas_half_open = 0
        self._trava = threading.Lock()

    @property
    def estado(self) -> CircuitState:
        with self._trava:
            return self._estado

    @property
    def falhas(self) -> int:
        with self._trava:
            return self._falhas

    def permitir_chamada(self) -> bool:
        """`True` se a chamada pode seguir; `False` força `CircuitoAberto`."""
        with self._trava:
            if self._estado is CircuitState.ABERTO:
                decorrido = self._relogio() - (self._aberto_desde or 0.0)
                if decorrido >= self._cooldown_segundos:
                    self._estado = CircuitState.MEIO_ABERTO
                    # A própria chamada que abriu o meio-aberto é a 1ª sonda:
                    # com `max_tentativas_half_open=2`, passam exatamente 2
                    # chamadas de sonda (esta e mais uma) antes de voltar a
                    # recusar — não `max + 1`.
                    self._tentativas_half_open = 1
                    self._log("circuito meio-aberto: sondando o provedor", resultado_extra="ok")
                    return True
                return False
            if self._estado is CircuitState.MEIO_ABERTO:
                if self._tentativas_half_open >= self._max_tentativas_half_open:
                    return False
                self._tentativas_half_open += 1
                return True
            return True

    def registrar_sucesso(self) -> None:
        """Sucesso após falha: zera o contador e fecha o circuito se sondando."""
        with self._trava:
            sondando = self._estado is CircuitState.MEIO_ABERTO
            if self._estado is not CircuitState.FECHADO:
                self._estado = CircuitState.FECHADO
            self._falhas = 0
            self._tentativas_half_open = 0
            self._aberto_desde = None
            if sondando:
                self._log("circuito fechado após sonda bem-sucedida")

    def registrar_falha(self) -> None:
        """Registra falha; pode abrir o circuito (ou reabri-lo em meio-aberto)."""
        with self._trava:
            if self._estado is CircuitState.FECHADO:
                self._falhas += 1
                if self._falhas >= self._limite_falhas:
                    self._abrir(motivo="limite de falhas consecutivas atingido")
            elif self._estado is CircuitState.MEIO_ABERTO:
                self._abrir(motivo="sonda em meio-aberto falhou")

    def reset(self) -> None:
        """Zera contadores e volta ao estado fechado (testes)."""
        with self._trava:
            self._estado = CircuitState.FECHADO
            self._falhas = 0
            self._aberto_desde = None
            self._tentativas_half_open = 0

    def _abrir(self, *, motivo: str) -> None:
        self._estado = CircuitState.ABERTO
        self._aberto_desde = self._relogio()
        self._tentativas_half_open = 0
        self._log("circuito aberto: chamadas suspensas", resultado_extra="erro", motivo=motivo)

    def _log(
        self,
        mensagem: str,
        *,
        resultado_extra: str = "ok",
        motivo: str | None = None,
    ) -> None:
        extra: dict[str, object] = {
            "evento": "CircuitoTransicao",
            "resultado": resultado_extra,
            "estado": self._estado.value,
            "falhas": self._falhas,
            "limite_falhas": self._limite_falhas,
            "cooldown_s": self._cooldown_segundos,
        }
        if motivo is not None:
            extra["motivo"] = motivo
        if resultado_extra == "ok":
            logger.info(mensagem, extra=extra)
        else:
            logger.warning(mensagem, extra=extra)