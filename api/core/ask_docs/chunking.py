"""Divisão de documentos em chunks com sobreposição (Aula 24).

A unidade de divisão é o token aproximado por espaço em branco (`\\S+`). Para
cada bloco guardamos também o intervalo de **caracteres** no texto original —
é esse intervalo que o contrato HTTP devolve em `sources[].range`.

O overlap é medido em tokens: com `tokens=400` e `overlap=80`, o próximo bloco
começa no token 320 do anterior. O último bloco sempre termina no fim do
documento, mesmo que tenha menos de 400 tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN = re.compile(r"\S+")
PASSAGEM = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass(frozen=True)
class Bloco:
    """Um chunk de texto com a posição exata no documento original."""

    indice: int
    texto: str
    inicio: int
    fim: int


def dividir(
    texto: str,
    *,
    tokens: int = 400,
    overlap: int = 80,
) -> list[Bloco]:
    """Divide `texto` em blocos de `tokens` com `overlap` tokens de sobreposição."""
    if tokens < 1:
        raise ValueError("tokens deve ser >= 1")
    if overlap < 0 or overlap >= tokens:
        raise ValueError("overlap deve estar entre 0 e tokens - 1")

    marcas = list(TOKEN.finditer(texto))
    if not marcas:
        return []

    passo = tokens - overlap
    blocos: list[Bloco] = []
    inicio_token = 0
    indice = 0

    while inicio_token < len(marcas):
        fim_token = min(inicio_token + tokens, len(marcas))
        inicio_char = marcas[inicio_token].start()
        fim_char = marcas[fim_token - 1].end()
        blocos.append(
            Bloco(
                indice=indice,
                texto=texto[inicio_char:fim_char],
                inicio=inicio_char,
                fim=fim_char,
            )
        )
        if fim_token >= len(marcas):
            break
        inicio_token += passo
        indice += 1

    return blocos


def dividir_passagens(texto: str, *, min_chars: int = 12) -> list[str]:
    """Divide um chunk em passagens (frases/parágrafos) para refinar o score."""
    return [
        parte.strip()
        for parte in PASSAGEM.split(texto)
        if len(parte.strip()) >= min_chars
    ]
