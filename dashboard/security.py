"""Regras de segurança para consultas do dashboard (Aula 19).

Diretriz Zero Interpolação: valores sempre via *bind parameters*. Nomes de
coluna usados em `ORDER BY` passam por uma allow-list explícita.
"""

from __future__ import annotations

from collections.abc import Iterable

STATUS_PEDIDO = (
    "pendente_publicacao",
    "pendente",
    "processado",
    "falha",
)

COLUNAS_ORDENACAO = ("id", "created_at", "total", "status")
DIRECOES_ORDENACAO = ("asc", "desc")
LIMITE_MAXIMO = 500
PAYLOAD_SQLI = "abc' OR '1'='1"


def validar_status(status_list: Iterable[str] | None) -> list[str]:
    """Normaliza e valida a lista de status (allow-list de valores)."""
    if not status_list:
        return []
    valores = list(dict.fromkeys(status_list))
    invalidos = sorted(set(valores) - set(STATUS_PEDIDO))
    if invalidos:
        raise ValueError(f"Status inválido(s): {', '.join(invalidos)}")
    return valores


def resolver_ordenacao(
    coluna: str | None = None,
    direcao: str | None = None,
) -> tuple[str, str]:
    """Valida a ordenação recebida da interface contra uma allow-list."""
    coluna_final = (coluna or "created_at").strip().lower()
    if coluna_final not in COLUNAS_ORDENACAO:
        raise ValueError(f"Coluna não permitida para ordenação: {coluna!r}")

    direcao_final = (direcao or "desc").strip().lower()
    if direcao_final not in DIRECOES_ORDENACAO:
        raise ValueError(f"Direção de ordenação inválida: {direcao!r}")
    return coluna_final, direcao_final


def normalizar_limite(limite: int) -> int:
    """Impede consultas sem limite ou com limite excessivo."""
    if not isinstance(limite, int) or limite < 1:
        raise ValueError("O limite deve ser um inteiro positivo")
    return min(limite, LIMITE_MAXIMO)
