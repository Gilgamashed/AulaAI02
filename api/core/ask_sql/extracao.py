"""Extração da consulta da resposta do provedor (Aula 21).

O provedor pode devolver markdown, uma frase antes do SQL ou o marcador
``NAO_SUPORTADO``. Esta etapa normaliza a resposta para uma única string SQL;
quem decide se ela é segura é `validacao.validar_sql`.
"""

from __future__ import annotations

import re

from .erros import PerguntaNaoSuportada, SqlNaoGerado

MARCADOR_NAO_SUPORTADO = "NAO_SUPORTADO"

_CERCA_MARKDOWN = re.compile(r"```[a-zA-Z0-9_+-]*\s*(.*?)```", re.DOTALL)
_NAO_SUPORTADO = re.compile(r"\bNAO_SUPORTADO\b", re.IGNORECASE)
_INICIO_SQL = re.compile(r"\b(?:select|with)\b", re.IGNORECASE)


def extrair_sql(texto: str) -> str:
    """Devolve só a consulta SQL contida na resposta do provedor.

    Levanta `PerguntaNaoSuportada` quando o provedor sinaliza que a pergunta
    está fora do domínio e `SqlNaoGerado` quando não há `SELECT`/`WITH`.
    """
    if texto is None:
        raise SqlNaoGerado("o provedor não devolveu texto")

    limpo = texto.strip()
    if not limpo:
        raise SqlNaoGerado("o provedor devolveu uma resposta vazia")

    if _NAO_SUPORTADO.search(limpo):
        raise PerguntaNaoSuportada(
            "a pergunta não pode ser respondida com o schema disponível"
        )

    cerca = _CERCA_MARKDOWN.search(limpo)
    if cerca:
        limpo = cerca.group(1).strip()

    inicio = _INICIO_SQL.search(limpo)
    if inicio is None:
        raise SqlNaoGerado("a resposta do provedor não contém SELECT ou WITH")

    sql = _primeiro_comando(limpo[inicio.start() :]).strip()
    if not sql:
        raise SqlNaoGerado("a resposta do provedor contém apenas um terminador")
    return sql


def _primeiro_comando(sql: str) -> str:
    """Corta no primeiro `;` fora de literal de texto (o resto é explicação)."""
    dentro_de_literal = False
    indice = 0
    while indice < len(sql):
        caractere = sql[indice]
        if caractere == "'":
            if dentro_de_literal and indice + 1 < len(sql) and sql[indice + 1] == "'":
                indice += 2
                continue
            dentro_de_literal = not dentro_de_literal
        elif caractere == ";" and not dentro_de_literal:
            return sql[:indice]
        indice += 1
    return sql
