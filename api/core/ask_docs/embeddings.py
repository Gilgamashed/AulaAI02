"""Embeddings locais determinísticos e similaridade por cosseno (Aula 24).

O projeto decidiu, na Aula 14, não depender de rede nem de credenciais para a
camada de IA. O RAG mantém a decisão: em vez de um modelo neural, o vetor é uma
representação lexical **TF-IDF com vocabulário exato**, normalizada em L2.

Por que vocabulário exato e não *hashing*: com dimensão fixa, colisões de hash
faziam perguntas fora do domínio ("capital da França") pontuarem em passagens
curtas. O vocabulário elimina a colisão; termos desconhecidos simplesmente não
entram no vetor.

O que é real e o que é aproximação:

- real: a vetorização, o índice, a similaridade por cosseno, o `top_k`, o
  `min_score` e a citação das fontes;
- aproximação: a semântica é lexical. Palavras sinônimas não se aproximam sem
  compartilhar radicais/tokens. A limitação está documentada no README.
"""

from __future__ import annotations

import math
import re
import unicodedata
from array import array
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

PADRAO_MAX_TERMOS_EMBEDDING = 64

TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        # português
        "a",
        "ao",
        "aos",
        "aquela",
        "aquele",
        "aquilo",
        "as",
        "ate",
        "com",
        "como",
        "da",
        "das",
        "de",
        "dela",
        "dele",
        "depois",
        "do",
        "dos",
        "e",
        "ela",
        "ele",
        "em",
        "entre",
        "era",
        "essa",
        "esse",
        "esta",
        "este",
        "eu",
        "foi",
        "ha",
        "isso",
        "isto",
        "ja",
        "mais",
        "mas",
        "me",
        "mesmo",
        "meu",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "ou",
        "para",
        "pela",
        "pelo",
        "por",
        "qual",
        "quando",
        "que",
        "quem",
        "se",
        "sem",
        "ser",
        "seu",
        "sua",
        "sao",
        "so",
        "tambem",
        "tem",
        "um",
        "uma",
        # inglês (o README/OpenAPI têm trechos em inglês)
        "an",
        "and",
        "are",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem pontuação."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    """Tokens normalizados usados no índice e na pergunta."""
    return TOKEN.findall(_normalizar(texto))


def _tokens_uteis(texto: str) -> list[str]:
    return [token for token in tokenizar(texto) if token not in STOPWORDS]


def calcular_idf(textos: Iterable[str]) -> dict[str, float]:
    """IDF suavizado por documento (chunk), calculado sobre o corpus indexado."""
    documentos = [set(_tokens_uteis(texto)) for texto in textos]
    total = len(documentos)
    if total == 0:
        return {}

    frequencia: Counter[str] = Counter()
    for termos in documentos:
        frequencia.update(termos)

    return {
        termo: math.log((total + 1) / (freq + 1)) + 1.0
        for termo, freq in frequencia.items()
    }


@dataclass(frozen=True)
class Vocabulario:
    """IDF e índice de cada termo; a dimensão do vetor é o tamanho do índice."""

    idf: dict[str, float] = field(default_factory=dict)
    indices: dict[str, int] = field(default_factory=dict)

    @property
    def dim(self) -> int:
        return len(self.indices)

    def vetorizar(
        self,
        texto: str,
        *,
        max_termos: int = PADRAO_MAX_TERMOS_EMBEDDING,
    ) -> array:
        """Gera um vetor TF-IDF normalizado no espaço do vocabulário."""
        if max_termos < 1:
            raise ValueError("max_termos deve ser >= 1")

        tokens = [
            token
            for token in _tokens_uteis(texto)
            if token in self.indices
        ]
        vetor = [0.0] * self.dim
        if not tokens or self.dim == 0:
            return array("f", vetor)

        frequencias = Counter(tokens)
        pesos: dict[str, float] = {}
        for termo, freq in frequencias.items():
            pesos[termo] = (1.0 + math.log(freq)) * self.idf.get(termo, 1.0)

        selecionados = sorted(pesos.items(), key=lambda item: (-item[1], item[0]))
        for termo, peso in selecionados[:max_termos]:
            vetor[self.indices[termo]] += peso

        norma = math.sqrt(math.fsum(valor * valor for valor in vetor))
        if norma == 0.0:
            return array("f", vetor)

        return array("f", [valor / norma for valor in vetor])


def construir_vocabulario(textos: Iterable[str]) -> Vocabulario:
    """Constrói IDF + índices determinísticos a partir dos chunks."""
    idf = calcular_idf(textos)
    indices = {termo: posicao for posicao, termo in enumerate(sorted(idf))}
    return Vocabulario(idf=idf, indices=indices)


def cosseno(a: Sequence[float], b: Sequence[float]) -> float:
    """Similaridade por cosseno entre dois vetores (normalizados ou não)."""
    if len(a) != len(b):
        raise ValueError("vetores de dimensões diferentes")
    produto = math.fsum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, produto))


def serializar(vetor: Sequence[float]) -> bytes:
    """Serializa o vetor para BLOB (float32, ordem nativa do processo)."""
    return array("f", vetor).tobytes()


def desserializar(blob: bytes, *, dim: int) -> array:
    """Reconstrói o vetor e valida a dimensão gravada no índice."""
    vetor = array("f")
    vetor.frombytes(blob)
    if len(vetor) != dim:
        raise ValueError(
            f"embedding com dimensão {len(vetor)} diferente da esperada ({dim})"
        )
    return vetor
