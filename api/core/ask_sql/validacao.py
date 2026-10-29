"""Validação do SQL gerado pelo provedor (Aula 21).

O DoD exige **apenas SELECT**. Esta camada é a barreira que não depende de o
modelo obedecer ao prompt:

- um único comando, começando por `SELECT` ou `WITH`;
- sem comentários, sem identificadores entre aspas e sem literais de dólar;
- allow-list de tabelas e de colunas qualificadas;
- bloqueio de colunas sensíveis, `SELECT *`, `FOR UPDATE` e funções perigosas;
- `LIMIT` obrigatório e limitado a `ASK_SQL_MAX_LINHAS`.

A execução (`execucao.py`) repete a garantia no banco com transação read-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .constantes import COLUNAS_SENSIVEIS, TABELAS
from .erros import SqlInvalido, SqlProibido

MAX_CARACTERES_SQL = 8000

PALAVRAS_PROIBIDAS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "merge",
    "vacuum",
    "analyze",
    "reindex",
    "refresh",
    "comment",
    "copy",
    "call",
    "set",
    "reset",
    "lock",
    "listen",
    "notify",
    "prepare",
    "execute",
    "deallocate",
    "declare",
    "into",
    "returning",
    "explain",
    "show",
    "security",
    "owner",
)

FUNCOES_PROIBIDAS = (
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "set_config",
    "current_setting",
    "dblink",
    "lo_import",
    "lo_export",
    "nextval",
    "setval",
)

_PALAVRAS_RESERVADAS = frozenset(
    {
        "where",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "full",
        "cross",
        "on",
        "using",
        "group",
        "order",
        "limit",
        "offset",
        "having",
        "union",
        "intersect",
        "except",
        "window",
        "fetch",
        "for",
        "as",
        "select",
        "from",
        "with",
        "and",
        "or",
    }
)

_REFERENCIA_TABELA = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)", re.IGNORECASE
)
_ALIAS_TABELA = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*)"
    r"(?:\s+(?:as\s+)?([a-zA-Z_][\w]*))?",
    re.IGNORECASE,
)
_QUALIFICADO = re.compile(r"\b([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\b")
_CTE = re.compile(r"\b([a-zA-Z_][\w]*)\s+as\s*\(", re.IGNORECASE)
_LIMITE = re.compile(r"\blimit\s+(all|\d+)\b", re.IGNORECASE)
_JUNCAO_POR_VIRGULA = re.compile(
    r"\b(?:from|join)\s+[a-zA-Z_][\w.]*"
    r"(?:\s+(?:as\s+)?[a-zA-Z_][\w]*)?\s*,",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlValidado:
    """Consulta pronta para execução e o limite efetivamente aplicado."""

    sql: str
    limite: int


def validar_sql(sql: str, *, max_linhas: int) -> SqlValidado:
    """Valida a consulta e garante um `LIMIT` dentro do teto configurado."""
    if max_linhas < 1:
        raise ValueError("max_linhas deve ser >= 1")

    consulta = _normalizar(sql)
    estrutural = _mascarar_literais(consulta)

    _validar_forma(estrutural)
    _validar_palavras(estrutural)
    _validar_projecao(estrutural)
    _validar_tabelas(estrutural)
    _validar_colunas(estrutural)

    return SqlValidado(sql=_aplicar_limite(consulta, estrutural, max_linhas), limite=max_linhas)


def _normalizar(sql: str) -> str:
    if not isinstance(sql, str):
        raise SqlInvalido("a consulta não é texto")
    consulta = sql.strip()
    if not consulta:
        raise SqlInvalido("a consulta está vazia")
    if len(consulta) > MAX_CARACTERES_SQL:
        raise SqlInvalido(
            f"a consulta excede {MAX_CARACTERES_SQL} caracteres"
        )
    if "\x00" in consulta:
        raise SqlInvalido("a consulta contém caractere nulo")
    if "--" in consulta or "/*" in consulta or "*/" in consulta:
        raise SqlInvalido("comentários não são permitidos na consulta")
    if '"' in consulta:
        raise SqlInvalido("identificadores entre aspas não são permitidos")
    if "$" in consulta:
        raise SqlInvalido("literais de dólar não são permitidos")

    if consulta.endswith(";"):
        consulta = consulta[:-1].rstrip()
    return consulta


def _mascarar_literais(sql: str) -> str:
    """Troca o conteúdo de literais por espaços, preservando as posições.

    A análise estrutural precisa enxergar `FROM`/`JOIN` e palavras-chave, mas
    não o texto dentro de `WHERE titulo = '...'` (que pode conter `--`, `from`
    ou o nome de uma coluna sensível sem ser uma referência real).
    """
    saida: list[str] = []
    dentro = False
    indice = 0
    while indice < len(sql):
        caractere = sql[indice]
        if not dentro:
            saida.append(caractere)
            if caractere == "'":
                dentro = True
            indice += 1
            continue
        if caractere == "'":
            if indice + 1 < len(sql) and sql[indice + 1] == "'":
                saida.extend((" ", " "))
                indice += 2
                continue
            dentro = False
            saida.append("'")
            indice += 1
            continue
        saida.append(" ")
        indice += 1

    if dentro:
        raise SqlInvalido("literal de texto não fechado na consulta")
    return "".join(saida)


def _validar_forma(estrutural: str) -> None:
    if not re.match(r"^\s*(?:select|with)\b", estrutural, re.IGNORECASE):
        raise SqlProibido("a consulta deve começar por SELECT ou WITH")
    if ";" in estrutural:
        raise SqlProibido("a consulta deve conter um único comando")
    if re.search(r"\bfor\s+(?:update|share|no\s+key\s+update|key\s+share)\b", estrutural, re.I):
        raise SqlProibido("bloqueio de linhas (FOR UPDATE/FOR SHARE) não é permitido")
    if re.search(r"\b(?:nowait|skip\s+locked)\b", estrutural, re.IGNORECASE):
        raise SqlProibido("cláusulas de bloqueio não são permitidas")


def _validar_palavras(estrutural: str) -> None:
    for palavra in PALAVRAS_PROIBIDAS:
        if re.search(rf"\b{palavra}\b", estrutural, re.IGNORECASE):
            raise SqlProibido(f"comando/palavra proibida na consulta: {palavra}")
    for funcao in FUNCOES_PROIBIDAS:
        if re.search(rf"\b{funcao}\s*\(", estrutural, re.IGNORECASE):
            raise SqlProibido(f"função proibida na consulta: {funcao}")
    if re.search(r"\bpg_[a-zA-Z0-9_]+\s*\(", estrutural, re.IGNORECASE):
        raise SqlProibido("funções do catálogo interno do PostgreSQL não são permitidas")


def _validar_projecao(estrutural: str) -> None:
    if re.search(
        r"\bselect\s+(?:distinct\s+)?\*", estrutural, re.IGNORECASE
    ):
        raise SqlProibido("SELECT * não é permitido; liste as colunas")
    if re.search(r"\b[a-zA-Z_][\w]*\s*\.\s*\*", estrutural):
        raise SqlProibido("SELECT tabela.* não é permitido; liste as colunas")
    if re.search(r",\s*\*", estrutural):
        raise SqlProibido("SELECT * não é permitido; liste as colunas")


def _validar_tabelas(estrutural: str) -> None:
    ctes = {
        nome.lower()
        for nome in _CTE.findall(estrutural)
        if estrutural.lstrip().lower().startswith("with")
    }

    if _JUNCAO_POR_VIRGULA.search(estrutural):
        raise SqlProibido(
            "junção por vírgula não é permitida; use JOIN ... ON explícito"
        )

    for referencia in _REFERENCIA_TABELA.findall(estrutural):
        nome = referencia.lower()
        if nome in ctes:
            continue
        if "." in nome:
            esquema, _, tabela = nome.partition(".")
            if esquema != "public" or tabela not in TABELAS:
                raise SqlProibido(f"tabela fora da allow-list: {referencia}")
            continue
        if nome not in TABELAS:
            raise SqlProibido(f"tabela fora da allow-list: {referencia}")


def _validar_colunas(estrutural: str) -> None:
    for coluna in COLUNAS_SENSIVEIS:
        if re.search(rf"\b{coluna}\b", estrutural, re.IGNORECASE):
            raise SqlProibido(f"coluna sensível não pode ser consultada: {coluna}")

    aliases = _aliases(estrutural)
    for prefixo, coluna in _QUALIFICADO.findall(estrutural):
        tabela = prefixo.lower()
        if tabela in aliases:
            tabela = aliases[tabela]
        elif tabela not in TABELAS:
            continue
        colunas = TABELAS[tabela]["colunas"]
        if coluna.lower() not in colunas:
            raise SqlProibido(
                f"coluna fora da allow-list: {prefixo}.{coluna}"
            )


def _aliases(estrutural: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for tabela, alias in _ALIAS_TABELA.findall(estrutural):
        nome_tabela = tabela.lower()
        if nome_tabela not in TABELAS:
            continue
        if not alias or alias.lower() in _PALAVRAS_RESERVADAS:
            continue
        aliases[alias.lower()] = nome_tabela
    return aliases


def _aplicar_limite(consulta: str, estrutural: str, max_linhas: int) -> str:
    achado = _LIMITE.search(estrutural)
    if achado is None:
        if re.search(r"\blimit\b", estrutural, re.IGNORECASE):
            raise SqlInvalido("LIMIT inválido; use um número inteiro")
        return f"{consulta} LIMIT {max_linhas}"

    valor = achado.group(1)
    if valor.lower() != "all" and int(valor) < 1:
        raise SqlInvalido("LIMIT deve ser maior que zero")
    if valor.lower() != "all" and int(valor) <= max_linhas:
        return consulta

    inicio, fim = achado.span()
    return f"{consulta[:inicio]}LIMIT {max_linhas}{consulta[fim:]}"
