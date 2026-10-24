"""Painel analítico Streamlit (Aula 19).

Filtros dinâmicos, cache com TTL, tabelas e gráficos. Todas as consultas
usam o módulo seguro parametrizado.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dashboard.queries import carregar_pedidos
from dashboard.security import STATUS_PEDIDO

st.set_page_config(
    page_title="SynapseShop - Painel Analítico",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=60, show_spinner=False)
def _carregar_pedidos_cache(
    status_tuple: tuple[str, ...],
    data_inicio_iso: str | None,
    data_fim_iso: str | None,
    pedido_id: int | None,
    ordem_coluna: str,
    ordem_direcao: str,
) -> list[dict]:
    data_inicio = date.fromisoformat(data_inicio_iso) if data_inicio_iso else None
    data_fim = date.fromisoformat(data_fim_iso) if data_fim_iso else None
    return carregar_pedidos(
        status_list=list(status_tuple) if status_tuple else None,
        data_inicio=data_inicio,
        data_fim=data_fim,
        pedido_id=pedido_id,
        ordem_coluna=ordem_coluna,
        ordem_direcao=ordem_direcao,
    )


st.title("SynapseShop - Painel de Pedidos")
st.caption("Conexão segura com SSL/TLS, consultas parametrizadas e cache (TTL 60s)")

with st.sidebar:
    st.header("Filtros")
    hoje = date.today()
    data_inicio = st.date_input("Data inicial", value=hoje - timedelta(days=30))
    data_fim = st.date_input("Data final", value=hoje)
    status_selecionados = st.multiselect("Status", options=list(STATUS_PEDIDO))
    pedido_id_str = st.text_input("ID do pedido (opcional)")
    st.header("Ordenação")
    ordem_coluna = st.selectbox("Coluna", options=["created_at", "id", "total", "status"])
    ordem_direcao = st.selectbox("Direção", options=["desc", "asc"])

pedido_id = None
if pedido_id_str.strip():
    try:
        pedido_id = int(pedido_id_str.strip())
    except ValueError:
        st.sidebar.error("ID do pedido deve ser numérico")

try:
    registros = _carregar_pedidos_cache(
        tuple(sorted(set(status_selecionados))),
        data_inicio.isoformat(),
        data_fim.isoformat(),
        pedido_id,
        ordem_coluna,
        ordem_direcao,
    )
except Exception as exc:
    st.error("Não foi possível carregar os dados com os filtros atuais.")
    st.caption(str(exc))
    st.stop()

if not registros:
    st.info("Nenhum pedido encontrado para os filtros selecionados.")
    st.stop()

df = pd.DataFrame(registros)
if "total" in df.columns:
    df["total"] = pd.to_numeric(df["total"])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total de registros", len(df))
col2.metric("Valor total", f"R$ {df['total'].sum():,.2f}" if "total" in df.columns else "N/A")
col3.metric("Pedidos aprovados/processados", int((df["status"] == "processado").sum()) if "status" in df.columns else 0)
col4.metric("Pedidos com falha", int((df["status"] == "falha").sum()) if "status" in df.columns else 0)

st.subheader("Tabela de pedidos")
st.dataframe(df, use_container_width=True, hide_index=True)

st.subheader("Quantidade por status")
contagem_status = df["status"].value_counts()
st.bar_chart(contagem_status)
