"""Provedor real do Google Gemini (Aula 25).

O adaptador cumpre a mesma porta `ProvedorLlm` dos mocks e é selecionado por
`LLM_PROVIDER=gemini`. Toda a resiliência (timeout, retry e circuit breaker)
continua em `LlmService`; aqui só existe a tradução entre o contrato interno e
o SDK oficial `google-genai`.

Decisões relevantes:

- o import do SDK é tardio: uma instalação que roda só com `LLM_PROVIDER=mock`
  não precisa carregar o cliente HTTP do Google no startup;
- o cliente é injetável para que a suíte não toque a rede;
- erros do SDK são traduzidos para a taxonomia neutra de `core.llm.erros`, e a
  mensagem exposta nunca carrega a chave, o corpo da requisição ou a resposta
  bruta do provedor.
"""

from __future__ import annotations

from typing import Any

from .erros import (
    LlmConexao,
    LlmConfiguracaoInvalida,
    LlmErro,
    LlmErroCliente,
    LlmErroServidor,
    LlmModeloIndisponivel,
    LlmRateLimit,
    LlmTimeout,
    RespostaBloqueada,
    RespostaInvalida,
)
from .portas import LlmResposta

MODELO_PADRAO = "gemini-3.5-flash"

# Motivos de `finish_reason` que significam bloqueio de segurança/conteúdo.
# `MAX_TOKENS` não entra aqui: uma resposta truncada com texto continua útil;
# sem texto, a checagem de vazio já a rejeita.
_MOTIVOS_BLOQUEIO_FINALIZACAO = frozenset(
    {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    }
)
_MOTIVOS_BLOQUEIO_PROMPT = frozenset(
    {
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "IMAGE_SAFETY",
        "MODEL_ARMOR",
        "JAILBREAK",
        "OTHER",
    }
)
_MOTIVOS_IGNORADOS = frozenset({"", "UNSPECIFIED", "BLOCKED_REASON_UNSPECIFIED"})


class ProvedorGemini:
    """Implementação de `ProvedorLlm` sobre a API `generateContent`."""

    def __init__(
        self,
        *,
        api_key: str,
        modelo: str = MODELO_PADRAO,
        timeout_segundos: float = 20.0,
        cliente: Any | None = None,
    ) -> None:
        chave = (api_key or "").strip()
        if not chave:
            raise LlmConfiguracaoInvalida(
                "GEMINI_API_KEY não configurada: defina a chave no .env ou "
                "use LLM_PROVIDER=mock."
            )
        self._modelo = (modelo or MODELO_PADRAO).strip()
        self._timeout_segundos = max(0.5, float(timeout_segundos))
        self._cliente = cliente or self._criar_cliente(chave)

    def _criar_cliente(self, api_key: str) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise LlmConfiguracaoInvalida(
                "dependência google-genai não instalada; instale requirements.txt "
                "ou use LLM_PROVIDER=mock."
            ) from exc

        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(self._timeout_segundos * 1000)
            ),
        )

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        sistema, contents = _mapear_mensagens(mensagens)
        config: dict[str, Any] = {
            "temperature": float(temperature),
            "max_output_tokens": int(max_tokens),
            # Desliga o "thinking" dos modelos Flash: ele consumiria
            # `max_output_tokens` antes de produzir texto (resposta vazia com
            # orçamento curto) e elevaria a latência de uma chamada síncrona.
            "thinking_config": {"thinking_budget": 0},
        }
        if sistema:
            config["system_instruction"] = sistema

        try:
            resposta = self._cliente.models.generate_content(
                model=self._modelo,
                contents=contents,
                config=config,
            )
        except LlmErro:
            raise
        except Exception as exc:
            raise _traduzir_erro(exc) from None

        motivo_bloqueio = _motivo_bloqueio(resposta)
        if motivo_bloqueio is not None:
            raise RespostaBloqueada(
                f"Gemini bloqueou a resposta ({motivo_bloqueio})",
                motivo=motivo_bloqueio,
            )

        texto = _texto_da_resposta(resposta)
        if not texto.strip():
            raise RespostaInvalida(
                "Gemini não devolveu texto (resposta vazia ou bloqueada)"
            )

        tokens_prompt, tokens_output = _tokens_da_resposta(resposta, mensagens, texto)
        return LlmResposta(
            texto=texto.strip(),
            tokens_prompt=tokens_prompt,
            tokens_output=tokens_output,
        )


def _mapear_mensagens(
    mensagens: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]]]:
    """Separa instrução de sistema e converte o histórico para o SDK."""
    sistemas: list[str] = []
    contents: list[dict[str, Any]] = []
    for mensagem in mensagens:
        papel = str(mensagem.get("role", "user")).strip().lower()
        conteudo = str(mensagem.get("content", ""))
        if papel == "system":
            sistemas.append(conteudo)
            continue
        contents.append(
            {
                "role": "model" if papel in {"assistant", "model"} else "user",
                "parts": [{"text": conteudo}],
            }
        )
    return "\n\n".join(sistemas), contents


def _campo(obj: Any, nome: str) -> Any:
    """Lê um campo de um objeto do SDK ou de um dublê em dicionário."""
    if isinstance(obj, dict):
        return obj.get(nome)
    return getattr(obj, nome, None)


def _nome_do_motivo(valor: Any) -> str:
    """Normaliza enum/string do SDK para o nome do motivo em maiúsculas."""
    if valor is None:
        return ""
    nome = getattr(valor, "name", None)
    if isinstance(nome, str) and nome:
        return nome.upper()
    return str(valor).upper().rsplit(".", 1)[-1]


def _motivo_bloqueio(resposta: Any) -> str | None:
    """Detecta bloqueio no prompt ou no candidato, sem expor o conteúdo."""
    feedback = _campo(resposta, "prompt_feedback")
    if feedback is not None:
        motivo = _nome_do_motivo(_campo(feedback, "block_reason"))
        if motivo not in _MOTIVOS_IGNORADOS and motivo in _MOTIVOS_BLOQUEIO_PROMPT:
            return motivo

    candidatos = _campo(resposta, "candidates") or []
    for candidato in candidatos:
        motivo = _nome_do_motivo(_campo(candidato, "finish_reason"))
        if motivo in _MOTIVOS_BLOQUEIO_FINALIZACAO:
            return motivo
    return None


def _texto_da_resposta(resposta: Any) -> str:
    """Extrai texto sem depender da classe concreta (testes usam dublês)."""
    if isinstance(resposta, dict):
        texto = resposta.get("text")
    else:
        try:
            texto = resposta.text
        except (AttributeError, ValueError):
            texto = None
    if texto:
        return str(texto)

    candidatos = getattr(resposta, "candidates", None) or []
    for candidato in candidatos:
        conteudo = getattr(candidato, "content", None)
        partes = getattr(conteudo, "parts", None) or []
        textos = [str(getattr(parte, "text", "")) for parte in partes]
        if any(textos):
            return "".join(textos)
    return ""


def _tokens_da_resposta(
    resposta: Any,
    mensagens: list[dict[str, str]],
    texto: str,
) -> tuple[int, int]:
    metadados = getattr(resposta, "usage_metadata", None)
    prompt = _inteiro(getattr(metadados, "prompt_token_count", None))
    saida = _inteiro(getattr(metadados, "candidates_token_count", None))
    if prompt is None:
        prompt = sum(
            max(1, len(mensagem.get("content", "")) // 4) for mensagem in mensagens
        )
    if saida is None:
        saida = max(1, len(texto) // 4)
    return prompt, saida


def _inteiro(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return None


def _traduzir_erro(exc: Exception) -> LlmErro:
    """Converte uma exceção do SDK em erro neutro, com mensagem sanitizada."""
    codigo = _codigo_http(exc)
    if codigo in {401, 403}:
        return LlmConfiguracaoInvalida(
            f"Gemini rejeitou a credencial (HTTP {codigo}); confira GEMINI_API_KEY."
        )
    if codigo == 429:
        return LlmRateLimit(
            "Gemini aplicou rate limit (HTTP 429).",
            retry_after=_retry_after(exc),
        )
    if codigo == 404:
        return LlmModeloIndisponivel(
            "Gemini não encontrou o modelo configurado (HTTP 404); "
            "confira LLM_MODEL*."
        )
    if codigo is not None and 400 <= codigo < 500:
        return LlmErroCliente(f"Gemini rejeitou a requisição (HTTP {codigo}).")
    if codigo is not None and codigo >= 500:
        return LlmErroServidor(f"Gemini falhou no servidor (HTTP {codigo}).")

    nome = type(exc).__name__.lower()
    if "timeout" in nome:
        return LlmTimeout("Gemini não respondeu dentro do timeout.")
    if "connect" in nome or isinstance(exc, (ConnectionError, OSError)):
        return LlmConexao("Falha de conexão com o Gemini.")
    return LlmErroServidor(f"Falha inesperada do Gemini ({type(exc).__name__}).")


def _codigo_http(exc: Exception) -> int | None:
    valor = getattr(exc, "code", None)
    if valor is None:
        resposta = getattr(exc, "response", None)
        valor = getattr(resposta, "status_code", None)
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _retry_after(exc: Exception) -> float | None:
    resposta = getattr(exc, "response", None)
    headers = getattr(resposta, "headers", None)
    if not headers:
        return None
    valor = headers.get("retry-after")
    try:
        return max(0.0, float(valor)) if valor is not None else None
    except (TypeError, ValueError):
        return None
