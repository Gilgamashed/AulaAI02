"""Consulta em linguagem natural (Aula 21).

Página Streamlit que autentica na API, envia a pergunta ao `/ask_sql/` e
exibe o SQL gerado e o resultado. Nenhuma consulta é montada aqui: a
validação e a execução read-only acontecem na API.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.ask_sql import (
    EXEMPLOS_PERGUNTAS,
    AskSqlErro,
    login,
    perguntar,
)

st.set_page_config(
    page_title="SynapseShop - Consulta em Linguagem Natural",
    page_icon="💬",
    layout="wide",
)

st.title("Consulta em Linguagem Natural")
st.caption(
    "Pergunte em português; a API gera um SELECT somente leitura, valida e executa."
)


def _limpar_sessao() -> None:
    chaves = [chave for chave in st.session_state if chave.startswith("ask_sql_")]
    for chave in chaves:
        del st.session_state[chave]


def _formulario_login() -> None:
    st.sidebar.header("Login")

    erro_salvo = st.session_state.pop("ask_sql_login_erro", None)
    if erro_salvo:
        st.sidebar.error(erro_salvo)

    with st.sidebar.form("login_ask_sql"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")

    if not entrar:
        return

    if not usuario.strip() or not senha:
        st.sidebar.warning("Informe usuário e senha.")
        return

    try:
        token = login(usuario.strip(), senha)
    except AskSqlErro as falha:
        st.sidebar.error(str(falha))
    else:
        st.session_state["ask_sql_token"] = token
        st.session_state["ask_sql_usuario"] = usuario.strip()
        st.rerun()


def _sessao_sidebar() -> None:
    usuario = st.session_state.get("ask_sql_usuario", "admin")
    st.sidebar.success(f"Conectado como **{usuario}**")
    if st.sidebar.button("Sair"):
        _limpar_sessao()
        st.rerun()


def _mostrar_resultado() -> None:
    resultado = st.session_state.get("ask_sql_resultado")
    if resultado is None:
        return

    st.subheader("SQL gerado")
    st.code(resultado.sql, language="sql")

    esquerda, direita = st.columns([1, 3])
    esquerda.metric("Linhas", resultado.row_count)
    direita.caption(
        f"Modelo: {resultado.meta.get('modelo', 'desconhecido')} · "
        f"tokens (prompt/saída): {resultado.meta.get('tokens_prompt', 0)}/"
        f"{resultado.meta.get('tokens_output', 0)}"
    )

    if resultado.truncated:
        st.warning(
            "O resultado foi truncado no limite de linhas configurado na API."
        )

    st.subheader("Resultado")
    if not resultado.rows:
        st.info("A consulta não devolveu linhas.")
        return

    tabela = pd.DataFrame(resultado.rows)
    if resultado.columns:
        tabela = tabela.reindex(columns=resultado.columns)
    st.dataframe(tabela, width="stretch", hide_index=True)


token = st.session_state.get("ask_sql_token")
if not token:
    _formulario_login()
    st.info("Faça login com um usuário do papel **admin** para consultar.")
    st.stop()

_sessao_sidebar()

exemplo = st.selectbox(
    "Exemplos",
    ("—", *EXEMPLOS_PERGUNTAS),
    help="Escolha um exemplo para preencher o campo abaixo.",
)
if exemplo != "—" and st.session_state.get("ask_sql_exemplo_aplicado") != exemplo:
    st.session_state["ask_sql_pergunta"] = exemplo
    st.session_state["ask_sql_exemplo_aplicado"] = exemplo
    st.rerun()

with st.form("pergunta_ask_sql"):
    pergunta = st.text_input(
        "Pergunta",
        value=st.session_state.get("ask_sql_pergunta", ""),
        placeholder="Ex.: Quais os 5 últimos usuários cadastrados?",
    )
    enviar = st.form_submit_button("Consultar")

if enviar:
    if not pergunta.strip():
        st.warning("Digite uma pergunta.")
    else:
        st.session_state["ask_sql_pergunta"] = pergunta.strip()
        with st.spinner("Consultando a API..."):
            try:
                resposta = perguntar(pergunta.strip(), token)
            except AskSqlErro as falha:
                if falha.status == 401:
                    st.session_state.pop("ask_sql_token", None)
                    st.session_state["ask_sql_login_erro"] = str(falha)
                    st.rerun()
                st.session_state.pop("ask_sql_resultado", None)
                st.error(str(falha))
                if falha.examples:
                    st.caption("Exemplos que o provedor atual entende:")
                    for item in falha.examples:
                        st.markdown(f"- {item}")
            else:
                st.session_state["ask_sql_resultado"] = resposta

_mostrar_resultado()
