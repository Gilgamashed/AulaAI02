"""Helpers de medição compartilhados pelos scripts `measure_*.py`.

`percentil` e `cabecalhos` eram reescritos, byte a byte, em `measure_cache.py`
e `measure_messaging.py`; divergir entre os dois faria os relatórios da Aula 8
e da Aula 9/10 medirem coisas diferentes com o mesmo nome. Este módulo fica ao
lado dos scripts (mesmo diretório), então `python scripts/measure_cache.py`
o encontra sem configuração extra de `sys.path`.
"""

from __future__ import annotations

import math


def cabecalhos(token: str | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Cabeçalhos comuns: JSON puro (nada de HTML da browsable API) + JWT + extras."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return headers


def percentil(amostras: list[float], p: float) -> float:
    """Percentil pelo método do rank mais próximo (p95 = 95% abaixo dele).

    Não usamos `statistics.quantiles` porque ela interpola e exige n>=2;
    com poucas amostras o rank mais próximo é mais honesto.
    """
    if not amostras:
        return 0.0
    ordenadas = sorted(amostras)
    posicao = max(1, math.ceil(p / 100 * len(ordenadas)))
    return ordenadas[posicao - 1]
