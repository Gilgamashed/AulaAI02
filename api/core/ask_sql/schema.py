"""Contexto de schema enviado ao provedor de IA (Aula 21).

O modelo não recebe introspecção livre do banco: recebe exatamente a
allow-list de `constantes.py`, com tipos, relacionamentos e glossário. Além de
reduzir o prompt, isso impede que tabelas internas (`django_session`,
`core_requisicao_metrica`) e colunas sensíveis (`auth_user.password`) entrem
no contexto.

`contexto()` é a função usada pelo `prompt.py`; `validar_consistencia()` existe
para a suíte detectar divergência entre a allow-list e os models do Django.
"""

from __future__ import annotations

from .constantes import (
    COLUNAS_PERMITIDAS,
    COLUNAS_SENSIVEIS,
    GLOSSARIO,
    RELACIONAMENTOS,
    TABELAS,
    TABELAS_INDISPONIVEIS,
    TABELAS_PERMITIDAS,
)

CABECALHO = (
    "SCHEMA (use SOMENTE estas tabelas e colunas; os nomes são os nomes reais "
    "das colunas no PostgreSQL):"
)


def texto_tabelas() -> str:
    """Representa a allow-list como blocos `CREATE TABLE` legíveis por LLM."""
    blocos: list[str] = []
    for nome, tabela in TABELAS.items():
        colunas = "\n".join(
            f"  {coluna} {tipo}," for coluna, tipo in tabela["colunas"].items()
        )
        blocos.append(
            f"CREATE TABLE {nome} ( -- {tabela['rotulo']}\n{colunas}\n);"
        )
    return "\n\n".join(blocos)


def texto_relacionamentos() -> str:
    return "\n".join(f"- {relacao}" for relacao in RELACIONAMENTOS)


def texto_glossario() -> str:
    return "\n".join(f"- {termo}" for termo in GLOSSARIO)


def texto_indisponiveis() -> str:
    return "\n".join(
        f"- {tabela}: {motivo}" for tabela, motivo in TABELAS_INDISPONIVEIS.items()
    )


def contexto() -> str:
    """Monta o bloco completo de contexto de dados do prompt."""
    validar_consistencia()
    return (
        f"{CABECALHO}\n\n{texto_tabelas()}\n\n"
        f"RELACIONAMENTOS (junte com JOIN explícito):\n{texto_relacionamentos()}\n\n"
        f"GLOSSÁRIO DE NEGÓCIO:\n{texto_glossario()}\n\n"
        f"TABELAS QUE NÃO EXISTEM NESTE DOMÍNIO:\n{texto_indisponiveis()}\n\n"
        "PROIBIDO: acessar catálogos internos (pg_catalog, information_schema), "
        "tabelas do Django (django_*, auth_group*, auth_permission) e a tabela "
        "operacional core_requisicao_metrica."
    )


def validar_consistencia() -> None:
    """Falha alto se a allow-list ficar incoerente ou expuser coluna sensível."""
    if not TABELAS:
        raise RuntimeError("allow-list do ask_sql está vazia")
    if TABELAS_PERMITIDAS & set(TABELAS_INDISPONIVEIS):
        raise RuntimeError("tabela marcada como indisponível está na allow-list")
    for nome, tabela in TABELAS.items():
        if not tabela["colunas"]:
            raise RuntimeError(f"tabela {nome} não tem colunas na allow-list")
        sensiveis = set(tabela["colunas"]) & COLUNAS_SENSIVEIS
        if sensiveis:
            raise RuntimeError(
                f"tabela {nome} expõe coluna(s) sensível(is): "
                f"{', '.join(sorted(sensiveis))}"
            )
    if not COLUNAS_PERMITIDAS:
        raise RuntimeError("allow-list do ask_sql não tem colunas")
