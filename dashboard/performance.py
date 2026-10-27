"""Consultas e agregações seguras para o dashboard de desempenho (Aula 20).

Todas as consultas usam SQLAlchemy Core com *bind parameters* (nenhuma
interpolação de valor em SQL) e leem a tabela `core_requisicao_metrica`, que
o middleware da API alimenta.

A hit rate de cache exibida aqui é **real**: o middleware grava, por
requisição, os deltas de `core.cache_metrics` (hits/misses/bypasses). Não é
uma estimativa derivada da latência.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    func,
    or_,
    select,
)
from sqlalchemy.engine import Engine

from .db import get_engine
from .security import normalizar_limite

metadata = MetaData()

requisicao_metrica = Table(
    "core_requisicao_metrica",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("metodo", String(10), nullable=False),
    Column("endpoint", String(200), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("latencia_ms", Float, nullable=False),
    Column("cache_hits", Integer, nullable=False, server_default="0"),
    Column("cache_misses", Integer, nullable=False, server_default="0"),
    Column("cache_bypasses", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

pedidos = Table(
    "core_pedido",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("status", String(32), nullable=False),
)

CLASSES_STATUS = ("2xx", "3xx", "4xx", "5xx")
LIMITE_MAXIMO = 50000


def _inicio_do_dia(valor: date) -> datetime:
    return datetime.combine(valor, time.min, tzinfo=timezone.utc)


def _fim_do_dia(valor: date) -> datetime:
    return datetime.combine(valor, time.max, tzinfo=timezone.utc)


def _validar_periodo(data_inicio: date | None, data_fim: date | None) -> None:
    if data_inicio and data_fim and data_inicio > data_fim:
        raise ValueError("A data inicial não pode ser posterior à data final")


def _filtrar_por_classe(consulta, classes: Sequence[str] | None):
    if not classes:
        return consulta
    condicoes = []
    for classe in classes:
        classe_norm = classe.strip()
        if classe_norm == "2xx":
            condicoes.append((requisicao_metrica.c.status_code >= 200) & (requisicao_metrica.c.status_code < 300))
        elif classe_norm == "3xx":
            condicoes.append((requisicao_metrica.c.status_code >= 300) & (requisicao_metrica.c.status_code < 400))
        elif classe_norm == "4xx":
            condicoes.append((requisicao_metrica.c.status_code >= 400) & (requisicao_metrica.c.status_code < 500))
        elif classe_norm == "5xx":
            condicoes.append((requisicao_metrica.c.status_code >= 500) & (requisicao_metrica.c.status_code < 600))
    if not condicoes:
        return consulta
    return consulta.where(or_(*condicoes))


def listar_endpoints(
    engine: Engine | None = None,
    *,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> list[str]:
    _validar_periodo(data_inicio, data_fim)
    consulta = select(requisicao_metrica.c.endpoint).distinct().order_by(requisicao_metrica.c.endpoint)
    if data_inicio:
        consulta = consulta.where(requisicao_metrica.c.created_at >= _inicio_do_dia(data_inicio))
    if data_fim:
        consulta = consulta.where(requisicao_metrica.c.created_at <= _fim_do_dia(data_fim))
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).scalars().all()
    return [str(linha) for linha in linhas]


def carregar_metricas(
    engine: Engine | None = None,
    *,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    endpoints: Sequence[str] | None = None,
    classes_status: Sequence[str] | None = None,
    limite: int = LIMITE_MAXIMO,
) -> list[dict[str, Any]]:
    _validar_periodo(data_inicio, data_fim)
    limite_final = min(normalizar_limite(limite), LIMITE_MAXIMO)
    consulta = select(
        requisicao_metrica.c.id,
        requisicao_metrica.c.metodo,
        requisicao_metrica.c.endpoint,
        requisicao_metrica.c.status_code,
        requisicao_metrica.c.latencia_ms,
        requisicao_metrica.c.cache_hits,
        requisicao_metrica.c.cache_misses,
        requisicao_metrica.c.cache_bypasses,
        requisicao_metrica.c.created_at,
    )
    if data_inicio:
        consulta = consulta.where(requisicao_metrica.c.created_at >= _inicio_do_dia(data_inicio))
    if data_fim:
        consulta = consulta.where(requisicao_metrica.c.created_at <= _fim_do_dia(data_fim))
    if endpoints:
        consulta = consulta.where(requisicao_metrica.c.endpoint.in_(list(endpoints)))
    consulta = _filtrar_por_classe(consulta, classes_status)
    consulta = consulta.order_by(requisicao_metrica.c.created_at.desc()).limit(limite_final)
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).mappings().all()
    resultado = []
    for linha in linhas:
        item = dict(linha)
        try:
            item["latencia_ms"] = float(item["latencia_ms"] or 0)
        except (TypeError, ValueError):
            item["latencia_ms"] = 0.0
        resultado.append(item)
    return resultado


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(ordenados):
        return float(ordenados[-1])
    return float(ordenados[f] + (k - f) * (ordenados[c] - ordenados[f]))


def _classe_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "outros"


def resumir_metricas(registros: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not registros:
        return {
            "total": 0,
            "latencia_media_ms": 0.0,
            "p95_ms": 0.0,
            "erros": 0,
            "taxa_erro": 0.0,
            "por_hora": [],
            "por_status": {},
            "por_classe": {},
            "por_endpoint": {},
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_bypasses": 0,
            "cache_hit_rate": 0.0,
        }

    latencias: list[float] = []
    erros = 0
    por_status: dict[str, int] = defaultdict(int)
    por_classe: dict[str, int] = defaultdict(int)
    por_endpoint: dict[str, int] = defaultdict(int)
    por_hora: dict[datetime, list[float]] = defaultdict(list)
    por_hora_count: dict[datetime, int] = defaultdict(int)
    cache_hits = cache_misses = cache_bypasses = 0

    for reg in registros:
        try:
            lat = float(reg.get("latencia_ms") or 0)
        except (TypeError, ValueError):
            lat = 0.0
        latencias.append(lat)
        status = int(reg.get("status_code") or 0)
        if status >= 400:
            erros += 1
        por_status[str(status)] += 1
        por_classe[_classe_status(status)] += 1
        por_endpoint[str(reg.get("endpoint") or "")] += 1
        cache_hits += int(reg.get("cache_hits") or 0)
        cache_misses += int(reg.get("cache_misses") or 0)
        cache_bypasses += int(reg.get("cache_bypasses") or 0)
        created = reg.get("created_at")
        if isinstance(created, datetime):
            bucket = created.replace(minute=0, second=0, microsecond=0)
            por_hora[bucket].append(lat)
            por_hora_count[bucket] += 1

    latencia_media = sum(latencias) / len(latencias) if latencias else 0.0
    p95 = _percentil(latencias, 0.95)
    total = len(registros)
    taxa_erro = (erros / total * 100.0) if total else 0.0
    lookups_cache = cache_hits + cache_misses
    cache_hit_rate = (cache_hits / lookups_cache * 100.0) if lookups_cache else 0.0

    por_hora_lista = []
    for bucket in sorted(por_hora_count.keys()):
        lats = por_hora[bucket]
        por_hora_lista.append(
            {
                "hora": bucket,
                "count": por_hora_count[bucket],
                "latencia_media_ms": (sum(lats) / len(lats)) if lats else 0.0,
                "p95_ms": _percentil(lats, 0.95),
            }
        )

    classes_ordenadas = {
        classe: por_classe[classe]
        for classe in (*CLASSES_STATUS, "outros")
        if por_classe.get(classe)
    }

    return {
        "total": total,
        "latencia_media_ms": round(latencia_media, 2),
        "p95_ms": round(p95, 2),
        "erros": erros,
        "taxa_erro": round(taxa_erro, 2),
        "por_hora": por_hora_lista,
        "por_status": dict(sorted(por_status.items())),
        "por_classe": classes_ordenadas,
        "por_endpoint": dict(sorted(por_endpoint.items(), key=lambda x: x[1], reverse=True)),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_bypasses": cache_bypasses,
        "cache_hit_rate": round(cache_hit_rate, 2),
    }


def pedidos_por_status(engine: Engine | None = None) -> dict[str, int]:
    """Foto dos pedidos por status no banco (não é o backlog da fila).

    O broker não expõe profundidade de fila por HTTP; o que o Postgres sabe é
    o estado de cada pedido. A página rotula o bloco nesses termos para não
    sugerir uma medição de fila que não existe.
    """
    consulta = select(pedidos.c.status, func.count().label("qtd")).group_by(pedidos.c.status)
    with (engine or get_engine()).connect() as conexao:
        linhas = conexao.execute(consulta).all()
    return {str(status): int(qtd) for status, qtd in linhas}
