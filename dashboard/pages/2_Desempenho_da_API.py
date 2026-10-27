"""Dashboard de Desempenho da API (Aula 20)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dashboard.performance import (
    carregar_metricas,
    listar_endpoints,
    pedidos_por_status,
    resumir_metricas,
)

logger = logging.getLogger("dashboard.performance")

st.set_page_config(page_title="SynapseShop - Desempenho da API", page_icon="⚡", layout="wide")

st.title("Desempenho da API")
st.caption("Latência, throughput, taxa de erro, status e cache - métricas coletadas pela API")


@st.cache_data(ttl=60, show_spinner=False)
def _carregar_dados(
    data_inicio_iso: str,
    data_fim_iso: str,
    endpoints_tuple: tuple[str, ...],
    classes_tuple: tuple[str, ...],
):
    data_inicio = date.fromisoformat(data_inicio_iso)
    data_fim = date.fromisoformat(data_fim_iso)
    return carregar_metricas(
        data_inicio=data_inicio,
        data_fim=data_fim,
        endpoints=list(endpoints_tuple) if endpoints_tuple else None,
        classes_status=list(classes_tuple) if classes_tuple else None,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _listar_endpoints(data_inicio_iso: str, data_fim_iso: str):
    return listar_endpoints(
        data_inicio=date.fromisoformat(data_inicio_iso),
        data_fim=date.fromisoformat(data_fim_iso),
    )


@st.cache_data(ttl=60, show_spinner=False)
def _pedidos_por_status():
    return pedidos_por_status()


with st.sidebar:
    st.header("Filtros")
    hoje = date.today()
    data_inicio = st.date_input("Data inicial", value=hoje - timedelta(days=7))
    data_fim = st.date_input("Data final", value=hoje)
    if data_inicio > data_fim:
        st.error("A data inicial não pode ser posterior à data final.")
        st.stop()

    try:
        opcoes_endpoints = _listar_endpoints(data_inicio.isoformat(), data_fim.isoformat())
    except Exception:
        logger.exception("Falha ao listar endpoints para o filtro")
        opcoes_endpoints = []

    endpoint_selecionado = st.multiselect(
        "Endpoint",
        options=opcoes_endpoints,
        help="Sem seleção, todos os endpoints do período entram no painel.",
    )
    classes_selecionado = st.multiselect(
        "Classe de status",
        options=["2xx", "3xx", "4xx", "5xx"],
        default=["2xx", "3xx", "4xx", "5xx"],
        help="Sem seleção, todas as classes entram no painel.",
    )

try:
    registros = _carregar_dados(
        data_inicio.isoformat(),
        data_fim.isoformat(),
        tuple(endpoint_selecionado),
        tuple(classes_selecionado),
    )
except Exception:
    logger.exception("Falha ao carregar métricas de desempenho")
    st.error("Não foi possível carregar as métricas. Verifique o log do container `dashboard`.")
    st.stop()

resumo = resumir_metricas(registros)
lookups_cache = resumo["cache_hits"] + resumo["cache_misses"]
hit_rate_exibicao = f"{resumo['cache_hit_rate']:.2f}%" if lookups_cache else "—"

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total de Requisições", f"{resumo['total']:,}")
col2.metric("Latência Média (ms)", f"{resumo['latencia_media_ms']:.2f}")
col3.metric("Latência p95 (ms)", f"{resumo['p95_ms']:.2f}")
col4.metric("Erros (4xx/5xx)", f"{resumo['erros']:,}")
col5.metric("Taxa de Erro (%)", f"{resumo['taxa_erro']:.2f}%")
col6.metric("Cache Hit Rate", hit_rate_exibicao)

st.divider()

col_g1, col_g2 = st.columns(2)
with col_g1:
    st.subheader("Throughput por Hora")
    if resumo["por_hora"]:
        df_th = pd.DataFrame(resumo["por_hora"])[["hora", "count"]].set_index("hora")
        st.line_chart(df_th)
    else:
        st.info("Sem dados para o período selecionado.")

with col_g2:
    st.subheader("Latência ao Longo do Tempo (média / p95)")
    if resumo["por_hora"]:
        df_lat = pd.DataFrame(resumo["por_hora"])[["hora", "latencia_media_ms", "p95_ms"]].set_index("hora")
        st.line_chart(df_lat)
    else:
        st.info("Sem dados para o período selecionado.")

st.divider()

col_g3, col_g4 = st.columns(2)
with col_g3:
    st.subheader("Distribuição por Classe de Status")
    if resumo["por_classe"]:
        df_classe = pd.DataFrame(
            list(resumo["por_classe"].items()),
            columns=["classe", "count"],
        ).set_index("classe")
        st.bar_chart(df_classe)
        with st.expander("Detalhe por status code"):
            st.dataframe(
                pd.DataFrame(
                    list(resumo["por_status"].items()),
                    columns=["status_code", "count"],
                ),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("Sem dados para o período selecionado.")

with col_g4:
    st.subheader("Requisições por Endpoint")
    if resumo["por_endpoint"]:
        df_ep = pd.DataFrame(
            list(resumo["por_endpoint"].items()),
            columns=["endpoint", "count"],
        ).set_index("endpoint")
        st.bar_chart(df_ep)
    else:
        st.info("Sem dados para o período selecionado.")

st.divider()

st.subheader("Cache e Pedidos")
col_m1, col_m2 = st.columns(2)
with col_m1:
    st.markdown("**Cache (hit rate real do período)**")
    st.metric("Hit rate", hit_rate_exibicao)
    st.metric("Hits / Misses", f"{resumo['cache_hits']:,} / {resumo['cache_misses']:,}")
    st.metric("Bypass (cache desligado ou sem chave)", f"{resumo['cache_bypasses']:,}")
    st.caption(
        "Contadores por processo e por requisição, gravados pelo middleware. "
        "Bypass não entra no denominador da hit rate."
    )

with col_m2:
    st.markdown("**Pedidos por status (fonte: banco)**")
    try:
        status_pedidos = _pedidos_por_status()
        if status_pedidos:
            st.bar_chart(pd.Series(status_pedidos, name="pedidos"))
        else:
            st.info("Nenhum pedido registrado.")
        st.caption(
            "Não é profundidade de fila do broker: é o estado persistido de cada pedido "
            "em `core_pedido`."
        )
    except Exception:
        logger.exception("Falha ao consultar pedidos por status")
        st.info("Não foi possível consultar os pedidos por status.")

st.divider()
st.subheader("Últimas requisições")
if registros:
    df = pd.DataFrame(registros)
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"])
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)
    st.caption(
        "Retenção do log: `docker compose exec api python api/manage.py limpar_metricas --dias 30`."
    )
else:
    st.info("Nenhuma métrica registrada no período. Gere tráfego na API para visualizar os dados.")
