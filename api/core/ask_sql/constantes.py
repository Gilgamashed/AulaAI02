"""Allow-list do domínio exposto ao texto-para-SQL (Aula 21).

O contexto enviado ao provedor de IA não é o schema completo do PostgreSQL:
é uma **allow-list explícita** das tabelas e colunas de negócio. Duas razões:

1. segurança — `auth_user.password`, chaves de idempotência e tabelas internas
   do Django nunca precisam chegar ao prompt (e não podem ser selecionadas);
2. foco — o modelo recebe só o que responde às perguntas de negócio do MVP.

As colunas usam o nome real da coluna no banco (`usuario_id`, não `usuario`);
o glossário traduz os termos em português usados nas perguntas.
"""

from __future__ import annotations

from typing import TypedDict


class TabelaSchema(TypedDict):
    """Descrição de uma tabela liberada para o texto-para-SQL."""

    rotulo: str
    colunas: dict[str, str]


TABELAS: dict[str, TabelaSchema] = {
    "auth_user": {
        "rotulo": "usuários (clientes e administradores)",
        "colunas": {
            "id": "bigint",
            "username": "varchar(150)",
            "email": "varchar(254)",
            "first_name": "varchar(150)",
            "last_name": "varchar(150)",
            "is_active": "boolean",
            "is_staff": "boolean",
            "date_joined": "timestamptz",
            "last_login": "timestamptz NULL",
        },
    },
    "core_pedido": {
        "rotulo": "pedidos",
        "colunas": {
            "id": "bigint",
            "usuario_id": "integer",
            "status": "varchar(32)",
            "total": "numeric(10,2)",
            "itens": "jsonb",
            "tentativas": "integer",
            "created_at": "timestamptz",
            "processado_em": "timestamptz NULL",
        },
    },
    "core_pagamento": {
        "rotulo": "pagamentos",
        "colunas": {
            "id": "bigint",
            "pedido_id": "bigint",
            "metodo": "varchar(32)",
            "valor": "numeric(10,2)",
            "aprovado": "boolean",
            "motivo_recusa": "varchar(200)",
            "status": "varchar(32)",
            "created_at": "timestamptz",
            "notificado_em": "timestamptz NULL",
        },
    },
    "core_notificacao": {
        "rotulo": "notificações",
        "colunas": {
            "id": "bigint",
            "pedido_id": "bigint",
            "pagamento_id": "bigint",
            "canal": "varchar(16)",
            "titulo": "varchar(120)",
            "enviada_em": "timestamptz",
        },
    },
    "core_item": {
        "rotulo": "produtos do catálogo",
        "colunas": {
            "id": "bigint",
            "name": "varchar(200)",
            "brand": "varchar(100)",
            "model": "varchar(100)",
            "sku": "varchar(100)",
            "price": "numeric(10,2)",
            "category_id": "bigint",
            "is_active": "boolean",
            "created_at": "timestamptz",
        },
    },
    "core_category": {
        "rotulo": "categorias do catálogo",
        "colunas": {
            "id": "bigint",
            "name": "varchar(100)",
            "slug": "varchar(120)",
            "created_at": "timestamptz",
        },
    },
}

TABELAS_PERMITIDAS = frozenset(TABELAS)

COLUNAS_PERMITIDAS = frozenset(
    coluna for tabela in TABELAS.values() for coluna in tabela["colunas"]
)

# Colunas que jamais devem ser projetadas, mesmo que alguém tente burlar o
# prompt. A validação é a primeira barreira; a transação read-only é a segunda.
COLUNAS_SENSIVEIS = frozenset(
    {
        "password",
        "is_superuser",
        "idempotency_key",
        "transacao_id",
        "session_key",
        "secret",
    }
)

RELACIONAMENTOS: tuple[str, ...] = (
    "core_pedido.usuario_id -> auth_user.id",
    "core_pagamento.pedido_id -> core_pedido.id",
    "core_notificacao.pedido_id -> core_pedido.id",
    "core_notificacao.pagamento_id -> core_pagamento.id",
    "core_item.category_id -> core_category.id",
)

GLOSSARIO: tuple[str, ...] = (
    "usuários/clientes = auth_user",
    "pedidos/vendas = core_pedido",
    "pagamentos/cobranças = core_pagamento",
    "notificações/avisos = core_notificacao",
    "produtos/itens = core_item",
    "categorias = core_category",
)

# A spec cita `enderecos_entrega` como exemplo de tabela do domínio. Ela não
# existe no SynapseShop; o prompt diz isso para o modelo não inventar colunas.
TABELAS_INDISPONIVEIS: dict[str, str] = {
    "enderecos_entrega": (
        "não existe tabela de endereços de entrega neste domínio; perguntas "
        "sobre endereço não podem ser respondidas"
    )
}

EXEMPLOS_PERGUNTAS: tuple[str, ...] = (
    "Quais os 5 últimos usuários cadastrados?",
    "Qual a soma do valor dos últimos 3 pedidos?",
    "Quais usuários fizeram mais pedidos?",
    "Quantos pedidos existem por status?",
    "Quais os produtos mais caros?",
)
