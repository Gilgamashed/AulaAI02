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
    LlmErro,
    LlmErroCliente,
    LlmIndisponivel,
    LlmModeloIndisponivel,
    LlmTerminal,
    LlmTimeout,
    RespostaBloqueada,
    RespostaInvalida,
)
from .gemini import MODELO_PADRAO as MODELO_GEMINI_PADRAO
from .gemini import ProvedorGemini
from .metricas import FALHA, SUCESSO, TERMINAL, llm_metrics
from .mock import ProvedorMock
from .mock_docs import ProvedorMockDocs
from .mock_sql import ProvedorMockSql
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
        fallback_provedor: ProvedorLlm | None = None,
        provedor_nome: str = "mock",
        fallback_nome: str = "mock",
        fallback_modelo: str = "mock",
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
        self._fallback_provedor = fallback_provedor
        self._provedor_nome = provedor_nome
        self._fallback_nome = fallback_nome
        self._fallback_modelo = fallback_modelo

    @property
    def modelo(self) -> str:
        """Modelo informacional usado nos metadados das respostas."""
        return self._modelo

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
        mensagens_seguras = self._redigir_mensagens(mensagens)
        inicio = time.monotonic()

        if not self._breaker.permitir_chamada():
            llm_metrics.record_bloqueada()
            if self._fallback_provedor is not None:
                return self._executar_fallback(
                    mensagens_seguras,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    motivo="circuito_aberto",
                    inicio=inicio,
                )
            raise CircuitoAberto(
                "circuito aberto: chamadas ao provedor estão suspensas "
                "até o cooldown do circuit breaker"
            )

        def chamada() -> LlmResposta:
            return self._com_timeout(
                lambda: self._provedor.completar(
                    mensagens_seguras, temperature=temperature, max_tokens=max_tokens
                )
            )

        try:
            resposta = self._retry.executar(chamada)
        except LlmConfiguracaoInvalida as falha:
            # Credencial inválida ou dependência ausente: não é retentável,
            # mas em `auto` o mock ainda pode atender a demonstração.
            llm_metrics.record(TERMINAL, latencia_ms=self._latencia_ms(inicio))
            if self._fallback_provedor is not None:
                return self._executar_fallback(
                    mensagens_seguras,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    motivo=self._motivo_falha(falha),
                    inicio=inicio,
                )
            raise
        except LlmTerminal as falha:
            # Falha que retentar não corrige (ex.: 4xx do cliente). Aproveitar a
            # política de retry para "não tentar de novo" e propagar de imediato,
            # sem registrar falha no breaker: 4xx não é sintoma de provedor.
            llm_metrics.record(TERMINAL, latencia_ms=self._latencia_ms(inicio))
            if self._fallback_provedor is not None and self._fallback_elegivel(falha):
                return self._executar_fallback(
                    mensagens_seguras,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    motivo=self._motivo_falha(falha),
                    inicio=inicio,
                )
            raise
        except LlmIndisponivel as falha:
            # Chegou aqui já traduzido pelo retry (esgotou as tentativas após
            # falhas recuperáveis). Conta como UMA falha no breaker e propaga
            # como está — nada a reembrulhar.
            self._breaker.registrar_falha()
            llm_metrics.record(FALHA, latencia_ms=self._latencia_ms(inicio))
            if self._fallback_provedor is not None:
                return self._executar_fallback(
                    mensagens_seguras,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    motivo=self._motivo_falha(falha),
                    inicio=inicio,
                )
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
            llm_metrics.marcar_primario_sucesso(self._provedor_nome)
            logger.info(
                "resposta gerada pelo provedor",
                extra={
                    "evento": "LlmRespostaOk",
                    "resultado": "ok",
                    "provedor": self._provedor_nome,
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

    @staticmethod
    def _motivo_falha(falha: LlmErro) -> str:
        """Motivo sanitizado para logs/métricas; nunca inclui prompt ou chave."""
        return f"{type(falha).__name__}: {falha}"[:160]

    @staticmethod
    def _fallback_elegivel(falha: LlmTerminal) -> bool:
        """Só disponibilidade técnica cai para o mock; segurança e 400 não."""
        if isinstance(falha, RespostaBloqueada):
            return False
        if isinstance(falha, LlmModeloIndisponivel):
            return True
        if isinstance(falha, RespostaInvalida):
            return True
        if isinstance(falha, LlmErroCliente):
            return False
        return False

    def _executar_fallback(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        motivo: str,
        inicio: float,
    ) -> LlmResposta:
        """Atende pelo mock depois de esgotar a resiliência do provedor primário."""
        fallback = self._fallback_provedor
        if fallback is None:  # pragma: no cover - chamado só quando configurado
            raise AssertionError("fallback chamado sem provedor de fallback")

        llm_metrics.record_fallback(motivo, provedor=self._fallback_nome)
        logger.warning(
            "provedor primário indisponível; usando fallback",
            extra={
                "evento": "LlmFallback",
                "resultado": "fallback",
                "provedor_primario": self._provedor_nome,
                "provedor_fallback": self._fallback_nome,
                "modelo_primario": self._modelo,
                "modelo_fallback": self._fallback_modelo,
                "motivo": motivo,
            },
        )

        try:
            resposta = self._com_timeout(
                lambda: fallback.completar(
                    mensagens, temperature=temperature, max_tokens=max_tokens
                )
            )
        except Exception as falha:
            llm_metrics.record_fallback_falha()
            raise LlmIndisponivel(
                "provedor primário e fallback indisponíveis"
            ) from falha

        resposta = self._redigir_resposta(resposta)
        latencia_ms = self._latencia_ms(inicio)
        custo_usd = self._custo_estimado(resposta)
        llm_metrics.record_fallback_sucesso(
            tokens_prompt=resposta.tokens_prompt,
            tokens_output=resposta.tokens_output,
            custo_usd=custo_usd,
        )
        logger.info(
            "resposta gerada pelo fallback",
            extra={
                "evento": "LlmRespostaFallback",
                "resultado": "ok",
                "provedor": self._fallback_nome,
                "modelo": self._fallback_modelo,
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
PROVIDER_AUTO = "auto"
PROVIDER_MOCK = "mock"
PROVIDER_GEMINI = "gemini"
PROVIDERS = frozenset({PROVIDER_AUTO, PROVIDER_MOCK, PROVIDER_GEMINI})
TAREFA_ASSIST = "assist"
TAREFA_SQL = "sql"
TAREFA_DOCS = "docs"
TAREFAS = frozenset({TAREFA_ASSIST, TAREFA_SQL, TAREFA_DOCS})

_instancias: dict[str, LlmService] = {}
_trava_singleton = threading.Lock()


def criar_llm_service(tarefa: str = TAREFA_ASSIST) -> LlmService:
    """Singleton do llm_service por tarefa, montado a partir das settings.

    Cada tarefa tem o próprio provedor e o próprio circuit breaker: uma falha
    no assistente não deve abrir o circuito do texto-para-SQL (e vice-versa).
    """
    if tarefa not in TAREFAS:
        raise LlmConfiguracaoInvalida(f"tarefa de IA desconhecida: '{tarefa}'")
    with _trava_singleton:
        if tarefa not in _instancias:
            from django.conf import settings

            _instancias[tarefa] = _montar(settings, tarefa)
    return _instancias[tarefa]


def _provedor_configurado(cfg: Any) -> str:
    """Valida e normaliza `LLM_PROVIDER` (`auto`, `gemini` ou `mock`)."""
    provedor_bruto = str(getattr(cfg, "LLM_PROVIDER", PROVIDER_AUTO)).strip().lower()
    if provedor_bruto not in PROVIDERS:
        raise LlmConfiguracaoInvalida(
            f"LLM_PROVIDER='{provedor_bruto}' desconhecido. Valores aceitos: "
            f"{', '.join(sorted(PROVIDERS))}."
        )
    return provedor_bruto


def _provedor_primario(cfg: Any, configurado: str) -> str:
    """Resolve `auto` para Gemini quando há chave; senão, mock."""
    if configurado != PROVIDER_AUTO:
        return configurado
    chave = str(getattr(cfg, "GEMINI_API_KEY", "")).strip()
    return PROVIDER_GEMINI if chave else PROVIDER_MOCK


def provedor_primario(cfg: Any) -> str:
    """Provedor que será tentado primeiro, já resolvendo o modo `auto`."""
    return _provedor_primario(cfg, _provedor_configurado(cfg))


def _criar_mock(tarefa: str) -> ProvedorLlm:
    """Mock especializado da tarefa, usado como modo estrito ou fallback."""
    if tarefa == TAREFA_SQL:
        return ProvedorMockSql()
    if tarefa == TAREFA_DOCS:
        return ProvedorMockDocs()
    return ProvedorMock()


def _modelo_mock(tarefa: str) -> str:
    """Rótulo informacional do mock, independente do modelo Gemini configurado."""
    if tarefa == TAREFA_SQL:
        return "mock-sql"
    if tarefa == TAREFA_DOCS:
        return "mock-docs"
    return "mock"


def _montar(cfg: Any, tarefa: str = TAREFA_ASSIST) -> LlmService:
    """Lê a configuração e compõe retry + breaker + provedor da tarefa."""
    configurado = _provedor_configurado(cfg)
    primario = _provedor_primario(cfg, configurado)

    timeout_segundos = float(getattr(cfg, "LLM_TIMEOUT_SEGUNDOS", 5.0))
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
    modelo = _modelo_da_tarefa(cfg, tarefa, primario)
    fallback_modelo = _modelo_mock(tarefa)
    fallback: ProvedorLlm | None = None

    if configurado == PROVIDER_AUTO and primario == PROVIDER_MOCK:
        logger.warning(
            "GEMINI_API_KEY ausente/vazia; usando mock",
            extra={
                "evento": "LlmFallbackConfiguracao",
                "resultado": "fallback",
                "motivo": "GEMINI_API_KEY ausente/vazia",
            },
        )

    if primario == PROVIDER_GEMINI:
        try:
            provedor: ProvedorLlm = ProvedorGemini(
                api_key=str(getattr(cfg, "GEMINI_API_KEY", "")),
                modelo=modelo,
                timeout_segundos=timeout_segundos,
            )
        except LlmConfiguracaoInvalida as falha:
            if configurado != PROVIDER_AUTO:
                raise
            logger.warning(
                "Gemini indisponível na montagem; usando mock",
                extra={
                    "evento": "LlmFallbackConfiguracao",
                    "resultado": "fallback",
                    "motivo": _motivo_montagem(falha),
                },
            )
            primario = PROVIDER_MOCK
            modelo = fallback_modelo
            provedor = _criar_mock(tarefa)
        else:
            if configurado == PROVIDER_AUTO:
                fallback = _criar_mock(tarefa)
    else:
        provedor = _criar_mock(tarefa)
        if configurado == PROVIDER_AUTO:
            modelo = fallback_modelo

    return LlmService(
        provedor,
        retry=retry,
        breaker=breaker,
        timeout_segundos=timeout_segundos,
        modelo=modelo,
        redacao_ativa=bool(getattr(cfg, "LLM_REDACAO_ATIVA", True)),
        custo_input_por_1m=float(getattr(cfg, "LLM_CUSTO_INPUT_POR_1M_TOKENS", 0.0)),
        custo_output_por_1m=float(getattr(cfg, "LLM_CUSTO_OUTPUT_POR_1M_TOKENS", 0.0)),
        fallback_provedor=fallback,
        provedor_nome=primario,
        fallback_nome=PROVIDER_MOCK,
        fallback_modelo=fallback_modelo,
    )


def _motivo_montagem(falha: LlmConfiguracaoInvalida) -> str:
    """Motivo sanitizado para o warning de fallback na montagem."""
    return f"{type(falha).__name__}: {falha}"[:160]


def modelos_efetivos(cfg: Any) -> dict[str, str]:
    """Modelo efetivo de cada tarefa, sem instanciar provedor nem cliente.

    A resolução repete a da fábrica — inclusive `auto` e a troca dos defaults
    `mock*` pelo modelo Gemini padrão — para que a telemetria mostre o modelo
    que realmente será enviado ao provedor, e não o valor bruto da setting.
    """
    try:
        configurado = _provedor_configurado(cfg)
    except LlmConfiguracaoInvalida:
        configurado = PROVIDER_MOCK
    primario = _provedor_primario(cfg, configurado)
    if configurado == PROVIDER_AUTO and primario == PROVIDER_MOCK:
        return {
            tarefa: _modelo_mock(tarefa)
            for tarefa in (TAREFA_ASSIST, TAREFA_SQL, TAREFA_DOCS)
        }
    return {
        tarefa: _modelo_da_tarefa(cfg, tarefa, primario)
        for tarefa in (TAREFA_ASSIST, TAREFA_SQL, TAREFA_DOCS)
    }


def _modelo_da_tarefa(cfg: Any, tarefa: str, provedor: str) -> str:
    """Resolve o modelo da tarefa para o provedor primário já resolvido.

    Ao trocar `LLM_PROVIDER` para `gemini`, as variáveis `LLM_MODEL*` podem
    continuar nos valores históricos do mock (`mock`, `mock-sql`,
    `mock-docs`). Nesse caso o adaptador usa o modelo Gemini padrão em vez de
    enviar um nome inexistente ao provedor.
    """
    nome_setting = (
        "LLM_MODEL_SQL"
        if tarefa == TAREFA_SQL
        else "LLM_MODEL_DOCS"
        if tarefa == TAREFA_DOCS
        else "LLM_MODEL"
    )
    padrao_mock = (
        "mock-sql"
        if tarefa == TAREFA_SQL
        else "mock-docs"
        if tarefa == TAREFA_DOCS
        else "mock"
    )
    padrao = MODELO_GEMINI_PADRAO if provedor == PROVIDER_GEMINI else padrao_mock
    modelo = str(getattr(cfg, nome_setting, padrao)).strip()
    if not modelo:
        return padrao
    if provedor == PROVIDER_GEMINI and modelo.lower().startswith("mock"):
        return MODELO_GEMINI_PADRAO
    return modelo