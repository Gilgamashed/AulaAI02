"""Painel analítico Streamlit (Aulas 19, 20 e 25).

Filtros dinâmicos, cache com TTL, tabelas e gráficos. Todas as consultas usam
o módulo seguro parametrizado. A Aula 25 acrescenta os indicadores de vendas:
receita total, ticket médio, receita por dia e produtos mais vendidos.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from dashboard.queries import (
    agregar_vendas,
    carregar_nomes_produtos,
    carregar_pedidos,
)
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
        incluir_itens=True,
    )


@st.cache_data(ttl=60, show_spinner=False)
def _carregar_vendas_cache(
    registros: list[dict],
) -> dict:
    """Agrega os indicadores de vendas com o mesmo cache de 60 s da listagem."""
    skus = [
        str(item.get("sku"))
        for registro in registros
        for item in (registro.get("itens") or [])
        if isinstance(item, dict) and item.get("sku")
    ]
    nomes = carregar_nomes_produtos(skus)
    return agregar_vendas(registros, nomes)


st.title("SynapseShop - Painel de Vendas")
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
    vendas = _carregar_vendas_cache(registros)
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

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Receita total", f"R$ {vendas['receita_total']:,.2f}")
col2.metric("Ticket médio", f"R$ {vendas['ticket_medio']:,.2f}")
col3.metric("Pedidos processados", vendas["pedidos_processados"])
col4.metric(
    "Pedidos com falha",
    int((df["status"] == "falha").sum()) if "status" in df.columns else 0,
)
col5.metric("Total de registros", len(df))

st.subheader("Receita por dia")
receita_dia = pd.DataFrame(vendas["receita_por_dia"])
if receita_dia.empty:
    st.info("Nenhum pedido processado no período selecionado.")
else:
    st.bar_chart(receita_dia.set_index("data")["receita"], use_container_width=True)

st.subheader("Produtos mais vendidos")
produtos = pd.DataFrame(vendas["produtos"])
if produtos.empty:
    st.info("Nenhum item de pedido processado no período selecionado.")
else:
    por_quantidade = produtos.sort_values(
        by=["quantidade", "receita"], ascending=[False, False]
    ).head(10)
    por_receita = produtos.sort_values(
        by=["receita", "quantidade"], ascending=[False, False]
    ).head(10)
    aba_quantidade, aba_receita = st.tabs(["Por quantidade", "Por receita"])
    with aba_quantidade:
        st.dataframe(
            por_quantidade[["sku", "nome", "quantidade", "receita"]],
            use_container_width=True,
            hide_index=True,
        )
    with aba_receita:
        st.dataframe(
            por_receita[["sku", "nome", "quantidade", "receita"]],
            use_container_width=True,
            hide_index=True,
        )

st.subheader("Quantidade por status")
contagem_status = df["status"].value_counts()
st.bar_chart(contagem_status)

st.subheader("Tabela de pedidos")
st.dataframe(
    df.drop(columns=["itens"], errors="ignore"),
    use_container_width=True,
    hide_index=True,
)
