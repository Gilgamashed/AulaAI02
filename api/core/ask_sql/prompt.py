"""Template de prompt do texto-para-SQL (Aula 21).

O prompt tem três partes: regras fixas (system), o contexto de schema
(`schema.contexto()`) e a pergunta do usuário. O marcador ``PERGUNTA:`` separa
a pergunta das instruções — o provedor mock o usa para localizar a entrada, e
um provedor real recebe a mesma estrutura.

As regras são a primeira camada de segurança. A validação (`validacao.py`) e a
transação read-only (`execucao.py`) não dependem de o modelo obedecer.
"""

from __future__ import annotations

from .schema import contexto

MARCADOR_PERGUNTA = "PERGUNTA:"

REGRAS = """\
Você traduz perguntas de negócio em UMA consulta SQL de leitura para PostgreSQL.

Regras obrigatórias:
1. Responda APENAS com a consulta SQL. Sem explicação, sem markdown, sem cercas
   de código e sem ponto e vírgula final.
2. Use somente SELECT (inclusive WITH ... SELECT). Nunca INSERT, UPDATE,
   DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, CALL, SET ou comandos de
   transação.
3. Use somente as tabelas e colunas do SCHEMA abaixo. Não invente tabelas,
   colunas, endereços ou dados.
4. Junte tabelas com JOIN explícito e condição ON. Nunca use junção por vírgula.
5. Nunca use SELECT *; liste as colunas. Em agregações, dê um alias ao
   resultado (ex.: COUNT(*) AS total_pedidos).
6. "últimos N" significa ORDER BY <data> DESC LIMIT N. "maiores/mais caros"
   significa ORDER BY <valor> DESC. Sempre limite a no máximo 200 linhas.
7. Não use comentários (-- ou /* */), nem funções de sistema/arquivo
   (pg_sleep, pg_read_file, dblink, set_config).
8. Datas relevantes: auth_user.date_joined, auth_user.last_login,
   core_pedido.created_at, core_pagamento.created_at,
   core_notificacao.enviada_em. Valores monetários: core_pedido.total,
   core_pagamento.valor, core_item.price.
9. Se a pergunta não puder ser respondida com este schema, responda exatamente
   NAO_SUPORTADO.

EXEMPLOS:
Pergunta: Quais os 3 últimos pedidos?
SQL: SELECT id, usuario_id, status, total, created_at FROM core_pedido ORDER BY created_at DESC LIMIT 3

Pergunta: Quantos pedidos existem por status?
SQL: SELECT status, COUNT(*) AS total_pedidos FROM core_pedido GROUP BY status ORDER BY total_pedidos DESC
"""


def sistema() -> str:
    """Instrução de sistema completa (regras + contexto de schema)."""
    return f"{REGRAS}\n{contexto()}"


def montar_mensagens(pergunta: str) -> list[dict[str, str]]:
    """Monta a conversa (system + user) enviada ao `LlmService`."""
    return [
        {"role": "system", "content": sistema()},
        {"role": "user", "content": f"{MARCADOR_PERGUNTA} {pergunta.strip()}"},
    ]
