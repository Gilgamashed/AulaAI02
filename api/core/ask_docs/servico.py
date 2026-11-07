"""Orquestração do assistente de documentação (Aula 24).

O caminho é sempre o mesmo:

    pergunta → embedding → busca por cosseno → guardrail → prompt → LLM → fontes

O guardrail é aplicado **antes** da LLM: se nenhum chunk atinge `min_score`, o
provedor não é chamado e a resposta é a frase padrão com `sources` vazio. Isso
torna impossível uma resposta inventada sem fonte recuperada.

As `sources` devolvidas pela API vêm da recuperação, não do texto do modelo. A
citação inline é reforçada por `_garantir_citacao` quando o provedor a omite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from core.llm import criar_llm_service

from .constantes import FRASE_GUARDRAIL
from .erros import IndiceVazio, ParametroInvalido
from .indice import IndiceRag, ResultadoBusca
from .prompt import montar_mensagens

PADRAO_CITACAO = re.compile(r"\[\d+\]")


@dataclass(frozen=True)
class Fonte:
    """Fonte citada no contrato HTTP."""

    path: str
    title: str
    range: str
    score: float


@dataclass(frozen=True)
class RespostaDocs:
    """Resposta completa do assistente de documentação."""

    answer: str
    sources: list[Fonte]


def responder(
    pergunta: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    llm: Any | None = None,
    indice: IndiceRag | None = None,
) -> RespostaDocs:
    """Executa o pipeline completo para uma pergunta sobre a documentação."""
    limite = _top_k(top_k)
    limiar = _min_score(min_score)

    indice = indice or IndiceRag(getattr(settings, "ASK_DOCS_INDEX_PATH"))
    indice.inicializar()
    if indice.total_chunks() == 0:
        raise IndiceVazio(
            "O índice de documentação ainda não foi construído. "
            "Execute `python api/manage.py indexar_docs`."
        )

    vocabulario = indice.carregar_vocabulario()
    vetor = vocabulario.vetorizar(pergunta)
    resultados = indice.buscar(
        vetor,
        top_k=limite,
        min_score=limiar,
        vocabulario=vocabulario,
    )
    if not resultados:
        return RespostaDocs(answer=FRASE_GUARDRAIL, sources=[])

    servico = llm if llm is not None else criar_llm_service(tarefa="docs")
    resposta = servico.completar(
        montar_mensagens(pergunta, resultados),
        temperature=0.0,
        max_tokens=int(getattr(settings, "ASK_DOCS_MAX_TOKENS", 600)),
    )

    answer = resposta.texto.strip() or FRASE_GUARDRAIL
    answer = _garantir_citacao(answer, resultados)

    return RespostaDocs(
        answer=answer,
        sources=[
            Fonte(
                path=resultado.path,
                title=resultado.title,
                range=f"{resultado.inicio}-{resultado.fim}",
                score=round(resultado.score, 4),
            )
            for resultado in resultados
        ],
    )


def _top_k(valor: int | None) -> int:
    if valor is None:
        valor = int(getattr(settings, "ASK_DOCS_TOP_K", 3))
    maximo = int(getattr(settings, "ASK_DOCS_MAX_TOP_K", 10))
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= maximo:
        raise ParametroInvalido(f"top_k deve ser um inteiro entre 1 e {maximo}")
    return valor


def _min_score(valor: float | None) -> float:
    if valor is None:
        valor = float(getattr(settings, "ASK_DOCS_MIN_SCORE", 0.25))
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ParametroInvalido("min_score deve ser um número entre 0.0 e 1.0")
    limiar = float(valor)
    if not 0.0 <= limiar <= 1.0:
        raise ParametroInvalido("min_score deve ser um número entre 0.0 e 1.0")
    return limiar


def _garantir_citacao(answer: str, resultados: list[ResultadoBusca]) -> str:
    """Se o provedor não citou nenhum bloco, acrescenta a linha de fontes."""
    if PADRAO_CITACAO.search(answer):
        return answer
    fontes = "; ".join(
        f"[{numero}] {resultado.path} ({resultado.inicio}-{resultado.fim})"
        for numero, resultado in enumerate(resultados, start=1)
    )
    return f"{answer}\n\nFontes: {fontes}"
