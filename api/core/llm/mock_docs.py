"""Provedor mock especializado em RAG de documentação (Aula 24).

A Aula 14 decidiu que o provedor de IA do projeto é um mock determinístico, sem
rede e sem credenciais. Para o `/ask_docs/` não seria diferente: este provedor
cumpre a mesma porta `ProvedorLlm` e produz uma resposta **extrativa** a partir
do contexto que o serviço recuperou.

O que é mock e o que é real:

- mock: a síntese em linguagem natural (aqui, escolhe a passagem mais próxima
  da pergunta e a cita);
- real: os embeddings, o índice, o cosseno, o `top_k`, o `min_score`, o prompt
  com contexto, o guardrail e o contrato HTTP com `sources`.

Um adaptador de LLM real no futuro substitui só esta classe.
"""

from __future__ import annotations

import re
import time

from core.ask_docs.constantes import FRASE_GUARDRAIL, MARCADOR_PERGUNTA
from core.ask_docs.embeddings import tokenizar

from .erros import LlmErro
from .portas import LlmResposta

BLOCO = re.compile(
    r"\[(?P<numero>\d+)\] caminho: (?P<caminho>.*?)\n"
    r"título: (?P<titulo>.*?)\n"
    r"intervalo: (?P<intervalo>.*?)\n"
    r"trecho:\n(?P<trecho>.*?)(?=\n\n---\n\n|\n\nPERGUNTA:|\Z)",
    re.DOTALL,
)

# Linhas de navegação/estrutura não respondem uma pergunta: títulos Markdown,
# linhas de tabela, itens de lista e chaves de YAML/OpenAPI. O mock as descarta
# quando existe pelo menos uma passagem em prosa.
ESTRUTURAL = re.compile(
    r"^\s*(?:"
    r"#{1,6}\s"
    r"|\|"
    r"|[-*+]\s"
    r"|openapi:|info:|paths:|components:|schemas:|properties:|required:"
    r"|example:|examples:|type:|items:|default:|minimum:|maximum:"
    r"|pattern:|format:|enum:|allOf:|oneOf:|anyOf:|tags:|description:"
    r"|[A-Za-z_][\w./-]*:\s"
    r")"
)


class ProvedorMockDocs:
    """Resposta extrativa determinística, sempre citando a fonte escolhida."""

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

        pergunta = _extrair_pergunta(mensagens)
        blocos = _extrair_blocos(mensagens)
        if not blocos:
            texto = FRASE_GUARDRAIL
        else:
            numero, trecho = _melhor_bloco(pergunta, blocos)
            resposta = _melhor_trecho(pergunta, trecho)
            texto = f"{resposta} [{numero}]"

        limite = max(1, max_tokens * 4)
        texto = texto[:limite]
        return LlmResposta(
            texto=texto,
            tokens_prompt=sum(
                max(1, len(mensagem.get("content", "")) // 4)
                for mensagem in mensagens
            ),
            tokens_output=max(1, len(texto) // 4),
        )


def _extrair_pergunta(mensagens: list[dict[str, str]]) -> str:
    for mensagem in reversed(mensagens):
        conteudo = mensagem.get("content", "")
        if MARCADOR_PERGUNTA in conteudo:
            return conteudo.split(MARCADOR_PERGUNTA, 1)[1].strip()
    return ""


def _extrair_blocos(mensagens: list[dict[str, str]]) -> list[tuple[str, str]]:
    for mensagem in mensagens:
        conteudo = mensagem.get("content", "")
        if "CONTEXTO:" not in conteudo:
            continue
        contexto = conteudo.split("CONTEXTO:", 1)[1]
        return [
            (encontrado.group("numero"), encontrado.group("trecho").strip())
            for encontrado in BLOCO.finditer(contexto)
        ]
    return []


def _melhor_bloco(
    pergunta: str,
    blocos: list[tuple[str, str]],
) -> tuple[str, str]:
    tokens_pergunta = set(tokenizar(pergunta))

    def sobreposicao(bloco: tuple[str, str]) -> int:
        return len(tokens_pergunta & set(tokenizar(bloco[1])))

    com_prosa = [
        bloco
        for bloco in blocos
        if sobreposicao(bloco) > 0 and _tem_prosa(bloco[1])
    ]
    candidatos = com_prosa or blocos
    melhor = max(
        candidatos,
        key=lambda bloco: (sobreposicao(bloco), -int(bloco[0])),
    )
    return melhor


def _tem_prosa(trecho: str) -> bool:
    partes = [
        parte.strip()
        for parte in re.split(r"(?<=[.!?])\s+|\n{2,}", trecho)
        if parte.strip()
    ]
    return any(not ESTRUTURAL.match(parte) for parte in partes)


def _melhor_trecho(pergunta: str, trecho: str, *, max_chars: int = 800) -> str:
    tokens_pergunta = set(tokenizar(pergunta))
    partes = [
        parte.strip()
        for parte in re.split(r"(?<=[.!?])\s+|\n{2,}", trecho)
        if parte.strip()
    ]
    if not partes:
        return trecho.strip()[:max_chars]

    prosa = [parte for parte in partes if not ESTRUTURAL.match(parte)]
    candidatas = prosa or partes

    melhor = max(
        candidatas,
        key=lambda parte: (
            len(tokens_pergunta & set(tokenizar(parte))),
            len(parte),
        ),
    )
    return melhor[:max_chars]
