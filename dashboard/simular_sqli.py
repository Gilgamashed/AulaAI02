"""Simulação controlada de SQL Injection (Aula 19).

Executa apenas consultas parametrizadas. O payload é tratado como valor
literal e, portanto, não altera a estrutura da consulta.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from .db import get_engine
from .queries import contar_pedidos, pedidos
from .security import PAYLOAD_SQLI


def executar_simulacao(
    engine: Engine | None = None,
    payload: str = PAYLOAD_SQLI,
) -> dict[str, Any]:
    """Compara a contagem total com a contagem do payload tratado como valor."""
    engine_final = engine or get_engine()
    total = contar_pedidos(engine_final)
    consulta = (
        select(func.count())
        .select_from(pedidos)
        .where(pedidos.c.status == payload)
    )
    with engine_final.connect() as conexao:
        linhas_com_payload = int(conexao.execute(consulta).scalar_one())

    return {
        "payload": payload,
        "total_pedidos": total,
        "linhas_com_payload": linhas_com_payload,
        "mitigado": not (total > 0 and linhas_com_payload == total),
    }


def main() -> int:
    try:
        resultado = executar_simulacao()
    except Exception as exc:
        print(json.dumps({"erro": str(exc), "mitigado": None}, ensure_ascii=False))
        return 2

    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["mitigado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
