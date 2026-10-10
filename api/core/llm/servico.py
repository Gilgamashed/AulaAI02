"""LlmService — fachada da camada de IA (Aula 14).

Compõe as três garantias do item 1 da spec em volta de um `ProvedorLlm`:

- **timeout** (guarda genérica): a chamada ao provedor roda num executor e a
  espera é limitada a `timeout_segundos` (`future.result(timeout=...)`); o
  estouro vira `LlmTimeout`. É genérica porque serve a qualquer provedor — o
  mock de hoje e o adaptador HTTP do futuro, que ainda terá o timeout nativo do
  cliente de transporte;
- **retry**: `RetryPolicy` com backoff exponencial + jitter sobre falhas
  recuperáveis;
- **circuit breaker**: `CircuitBreaker` decide antes (fail-fast) e atualiza o
  estado depois.

`criar_llm_service()` é o ponto único de montagem lendo as settings do Django —
onde o provedor real será selecionado no futuro via `LLM_PROVIDER`, sem tocar
na resiliência.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .circuit_breaker import CircuitBreaker
from .erros import (
    CircuitoAberto,
    LlmConfiguracaoInvalida,
    LlmIndisponivel,
    LlmTerminal,
    LlmTimeout,
)
from .metricas import FALHA, SUCESSO, TERMINAL, llm_metrics
from .mock import ProvedorMock
from .portas import LlmResposta, ProvedorLlm
from .redacao import redigir
from .retry import RetryPolicy

logger = logging.getLogger("core.llm")


class LlmService:
    """Garante timeout + retry + circuit breaker sobre um provedor de IA."""

    def __init__(
        self,
        provedor: ProvedorLlm,
        *,
        retry: RetryPolicy,
        breaker: CircuitBreaker,
        timeout_segundos: float = 5.0,
        modelo: str = "mock",
        executor: concurrent.futures.ThreadPoolExecutor | None = None,
        redacao_ativa: bool = True,
        custo_input_por_1m: float = 0.0,
        custo_output_por_1m: float = 0.0,
    ) -> None:
        self._provedor = provedor
        self._retry = retry
        self._breaker = breaker
        self._timeout_segundos = max(0.0, timeout_segundos)
        self._modelo = modelo
        self._executor = executor or concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._redacao_ativa = redacao_ativa
        self._custo_input_por_1m = max(0.0, custo_input_por_1m)
        self._custo_output_por_1m = max(0.0, custo_output_por_1m)

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        """Gera um completamento aplicando breaker → retry → timeout.

        Antes de tocar o provedor, as mensagens passam pela redação de PII/
        segredos (`redacao.redigir`); a resposta também é redigida antes de sair
        (defesa contra eco do provedor). Cada desfecho alimenta `llm_metrics`.
        """
        if not self._breaker.permitir_chamada():
            llm_metrics.record_bloqueada()
            raise CircuitoAberto(
                "circuito aberto: chamadas ao provedor estão suspensas "
                "até o cooldown do circuit breaker"
            )

        mensagens_seguras = self._redigir_mensagens(mensagens)
        inicio = time.monotonic()
        chamada: Callable[[], LlmResposta] = lambda: self._com_timeout(
            lambda: self._provedor.completar(
                mensagens_seguras, temperature=temperature, max_tokens=max_tokens
            )
        )

        try:
            resposta = self._retry.executar(chamada)
        except LlmTerminal:
            # Falha que retentar não corrige (ex.: 4xx do cliente). Aproveitar a
            # política de retry para "não tentar de novo" e propagar de imediato,
            # sem registrar falha no breaker: 4xx não é sintoma de provedor.
            llm_metrics.record(TERMINAL, latencia_ms=self._latencia_ms(inicio))
            raise
        except LlmIndisponivel:
            # Chegou aqui já traduzido pelo retry (esgotou as tentativas após
            # falhas recuperáveis). Conta como UMA falha no breaker e propaga
            # como está — nada a reembrulhar.
            self._breaker.registrar_falha()
            llm_metrics.record(FALHA, latencia_ms=self._latencia_ms(inicio))
            raise
        else:
            self._breaker.registrar_sucesso()
            resposta = self._redigir_resposta(resposta)
            latencia_ms = self._latencia_ms(inicio)
            custo_usd = self._custo_estimado(resposta)
            llm_metrics.record(
                SUCESSO,
                tokens_prompt=resposta.tokens_prompt,
                tokens_output=resposta.tokens_output,
                custo_usd=custo_usd,
                latencia_ms=latencia_ms,
            )
            logger.info(
                "resposta gerada pelo provedor",
                extra={
                    "evento": "LlmRespostaOk",
                    "resultado": "ok",
                    "modelo": self._modelo,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "tokens_prompt": resposta.tokens_prompt,
                    "tokens_output": resposta.tokens_output,
                    "custo_usd": custo_usd,
                    "latencia_ms": latencia_ms,
                },
            )
            return resposta

    def _redigir_mensagens(
        self, mensagens: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Aplica a redação ao conteúdo de cada mensagem, se ativada."""
        if not self._redacao_ativa:
            return mensagens
        return [
            {**mensagem, "content": redigir(mensagem.get("content", ""))}
            for mensagem in mensagens
        ]

    def _redigir_resposta(self, resposta: LlmResposta) -> LlmResposta:
        """Impede que o provedor devolva (meco) PII que deveria estar oculta."""
        if not self._redacao_ativa:
            return resposta
        return replace(resposta, texto=redigir(resposta.texto))

    def _custo_estimado(self, resposta: LlmResposta) -> float:
        """Custo estimado em USD a partir do preço por 1M de tokens."""
        return round(
            resposta.tokens_prompt / 1_000_000 * self._custo_input_por_1m
            + resposta.tokens_output / 1_000_000 * self._custo_output_por_1m,
            6,
        )

    @staticmethod
    def _latencia_ms(inicio: float) -> float:
        return round((time.monotonic() - inicio) * 1000.0, 3)

    def _com_timeout(self, fn: Callable[[], LlmResposta]) -> LlmResposta:
        """Executa `fn` num worker, limitando a espera a `timeout_segundos`.

        A thread que estourou o deadline continua viva no executor (não dá para
        cancelar um `fn` bloqueante); é o preço conhecido da guarda genérica. O
        adaptador HTTP do futuro terá o timeout nativo do cliente, que cancela a
        chamada no próprio transporte.
        """
        futuro = self._executor.submit(fn)
        try:
            return futuro.result(timeout=self._timeout_segundos)
        except TimeoutError:
            raise LlmTimeout(
                f"provedor não respondeu dentro de {self._timeout_segundos}s"
            ) from None


# ---------------------------------------------------------------------
# Fábrica (singleton por processo) — padrão do produtor Kafka
# (core/messaging/kafka_produtor.py): quem sobe a API com gunicorn tem
# várias threads no mesmo processo, e o estado do circuit breaker precisa
# ser compartilhado entre elas.
# ---------------------------------------------------------------------
PROVIDER_MOCK = "mock"

_instancia: LlmService | None = None
_trava_singleton = threading.Lock()


def criar_llm_service() -> LlmService:
    """Singleton do llm_service, montado a partir das settings do Django."""
    global _instancia
    with _trava_singleton:
        if _instancia is None:
            from django.conf import settings

            _instancia = _montar(settings)
    return _instancia


def _montar(cfg: Any) -> LlmService:
    """Lê a configuração e compõe retry + breaker + mock com as políticas."""
    provedor_bruto = str(getattr(cfg, "LLM_PROVIDER", PROVIDER_MOCK)).strip().lower()
    if provedor_bruto != PROVIDER_MOCK:
        raise LlmConfiguracaoInvalida(
            f"LLM_PROVIDER='{provedor_bruto}' desconhecido. Hoje só existe o "
            f"provedor '{PROVIDER_MOCK}'; o adaptador do provedor real entra em "
            "uma iteração futura sem mudar a camada de resiliência."
        )

    retry = RetryPolicy(
        max_tentativas=int(getattr(cfg, "LLM_MAX_TENTATIVAS", 3)),
        base_segundos=float(getattr(cfg, "LLM_BACKOFF_BASE_SEGUNDOS", 1.0)),
        fator=float(getattr(cfg, "LLM_BACKOFF_FATOR", 2.0)),
        jitter=bool(getattr(cfg, "LLM_BACKOFF_JITTER", True)),
    )
    breaker = CircuitBreaker(
        limite_falhas=int(getattr(cfg, "LLM_CB_LIMITE_FALHAS", 5)),
        cooldown_segundos=float(getattr(cfg, "LLM_CB_COOLDOWN_SEGUNDOS", 30.0)),
        max_tentativas_half_open=int(getattr(cfg, "LLM_CB_MAX_TENTATIVAS_HALF_OPEN", 2)),
    )
    return LlmService(
        ProvedorMock(),
        retry=retry,
        breaker=breaker,
        timeout_segundos=float(getattr(cfg, "LLM_TIMEOUT_SEGUNDOS", 5.0)),
        modelo=str(getattr(cfg, "LLM_MODEL", "mock")),
        redacao_ativa=bool(getattr(cfg, "LLM_REDACAO_ATIVA", True)),
        custo_input_por_1m=float(getattr(cfg, "LLM_CUSTO_INPUT_POR_1M_TOKENS", 0.0)),
        custo_output_por_1m=float(getattr(cfg, "LLM_CUSTO_OUTPUT_POR_1M_TOKENS", 0.0)),
    )