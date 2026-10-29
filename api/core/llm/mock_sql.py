"""Provedor mock especializado em texto-para-SQL (Aula 21).

A Aula 14 decidiu que o provedor de IA do projeto é um mock determinístico, sem
rede e sem credenciais. Para o `/ask_sql/` não seria diferente: este provedor
cumpre a mesma porta `ProvedorLlm` e traduz **padrões de perguntas de negócio**
em SQL somente leitura.

O que é mock e o que é real:

- mock: a tradução português → SQL, limitada aos padrões abaixo;
- real: o prompt com schema, a extração, a validação de segurança, a execução
  read-only e o contrato HTTP. Um adaptador de LLM real no futuro substitui só
  esta classe.

Perguntas fora dos padrões devolvem `NAO_SUPORTADO`, que a extração transforma
em 422 com a lista de exemplos.
"""

from __future__ import annotations

import re
import time
import unicodedata

from .erros import LlmErro
from .portas import LlmResposta

MARCADOR_PERGUNTA = "PERGUNTA:"
MARCADOR_NAO_SUPORTADO = "NAO_SUPORTADO"
LIMITE_PADRAO = 10
LIMITE_MAXIMO = 200


class ProvedorMockSql:
    """Tradutor determinístico de perguntas de negócio em SQL."""

    def __init__(
        self,
        *,
        latencia_s: float = 0.0,
        falhar_com: LlmErro | None = None,
    ) -> None:
        self._latencia_s = max(0.0, latencia_s)
        self._falhar_com = falhar_com

    def completar(
        self,
        mensagens: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> LlmResposta:
        if self._latencia_s:
            time.sleep(self._latencia_s)
        if self._falhar_com is not None:
            raise self._falhar_com

        pergunta = _extrair_pergunta(mensagens)
        sql = _gerar_sql(pergunta)
        if sql is None:
            texto = MARCADOR_NAO_SUPORTADO
        else:
            texto = sql
        return LlmResposta(
            texto=texto,
            tokens_prompt=sum(
                max(1, len(mensagem.get("content", "")) // 4)
                for mensagem in mensagens
            ),
            tokens_output=max(1, len(texto) // 4),
        )


def _extrair_pergunta(mensagens: list[dict[str, str]]) -> str:
    conteudo = mensagens[-1].get("content", "") if mensagens else ""
    if MARCADOR_PERGUNTA in conteudo:
        return conteudo.rsplit(MARCADOR_PERGUNTA, 1)[1].strip()
    return conteudo.strip()


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return sem_acento.lower().strip()


def _contem(texto: str, *termos: str) -> bool:
    return any(termo in texto for termo in termos)


def _numero(pergunta: str, padrao: int) -> int:
    achado = re.search(r"\b(\d{1,3})\b", pergunta)
    if achado is None:
        return padrao
    return max(1, min(LIMITE_MAXIMO, int(achado.group(1))))


def _gerar_sql(pergunta: str) -> str | None:
    texto = _normalizar(pergunta)
    limite = _numero(texto, LIMITE_PADRAO)

    if _contem(texto, "endereco", "enderecos", "senha", "password"):
        return None

    if _contem(texto, "usuario", "usuarios", "cliente", "clientes") and (
        _contem(texto, "mais pedidos", "mais compras", "maior quantidade de pedidos")
        or ("top" in texto and "pedido" in texto)
    ):
        quantidade = limite
        return (
            "SELECT u.id, u.username, COUNT(p.id) AS total_pedidos\n"
            "FROM auth_user AS u\n"
            "JOIN core_pedido AS p ON p.usuario_id = u.id\n"
            "GROUP BY u.id, u.username\n"
            "ORDER BY total_pedidos DESC\n"
            f"LIMIT {quantidade}"
        )

    if "pedido" in texto and _contem(texto, "soma", "somar", "valor total"):
        quantidade = _numero(texto, 3)
        return (
            "SELECT SUM(total) AS soma_total\n"
            "FROM (\n"
            "  SELECT total FROM core_pedido\n"
            "  ORDER BY created_at DESC\n"
            f"  LIMIT {quantidade}\n"
            ") AS ultimos_pedidos"
        )

    if "ticket medio" in texto or ("media" in texto and "pedido" in texto):
        return "SELECT AVG(total) AS ticket_medio FROM core_pedido"

    if _contem(texto, "faturamento", "receita"):
        return (
            "SELECT SUM(valor) AS faturamento_aprovado\n"
            "FROM core_pagamento\n"
            "WHERE aprovado = TRUE"
        )

    if "pagamento" in texto and _contem(texto, "metodo", "forma de pagamento"):
        return (
            "SELECT metodo, COUNT(*) AS total_pagamentos, "
            "SUM(valor) AS valor_total\n"
            "FROM core_pagamento\n"
            "GROUP BY metodo\n"
            "ORDER BY total_pagamentos DESC"
        )

    if _contem(texto, "notifica", "notificacao", "notificacoes") and _contem(
        texto, "canal", "canais"
    ):
        return (
            "SELECT canal, COUNT(*) AS total_notificacoes\n"
            "FROM core_notificacao\n"
            "GROUP BY canal\n"
            "ORDER BY total_notificacoes DESC"
        )

    if _contem(texto, "usuario", "usuarios", "cliente", "clientes") and _contem(
        texto, "quantos", "quantidade", "numero", "total"
    ) and "pedido" not in texto:
        return "SELECT COUNT(*) AS total_usuarios FROM auth_user"

    if _contem(texto, "usuario", "usuarios", "cliente", "clientes") and _contem(
        texto, "ultimo", "ultimos", "recente", "recentes", "novo", "novos", "cadastr"
    ):
        quantidade = limite
        return (
            "SELECT id, username, email, first_name, last_name, is_active, "
            "date_joined\n"
            "FROM auth_user\n"
            "ORDER BY date_joined DESC\n"
            f"LIMIT {quantidade}"
        )

    if _contem(texto, "produto", "produtos", "item", "itens", "catalogo") and _contem(
        texto, "caro", "caros", "preco", "precos", "maior valor"
    ):
        quantidade = limite
        return (
            "SELECT id, name, brand, model, sku, price\n"
            "FROM core_item\n"
            "WHERE is_active = TRUE\n"
            "ORDER BY price DESC\n"
            f"LIMIT {quantidade}"
        )

    if "pedido" in texto and "status" in texto:
        return (
            "SELECT status, COUNT(*) AS total_pedidos\n"
            "FROM core_pedido\n"
            "GROUP BY status\n"
            "ORDER BY total_pedidos DESC"
        )

    if "pedido" in texto and _contem(texto, "quantos", "quantidade", "numero", "total"):
        return "SELECT COUNT(*) AS total_pedidos FROM core_pedido"

    if "pedido" in texto and _contem(
        texto, "ultimo", "ultimos", "recente", "recentes"
    ):
        quantidade = min(limite, LIMITE_MAXIMO)
        return (
            "SELECT id, usuario_id, status, total, created_at\n"
            "FROM core_pedido\n"
            "ORDER BY created_at DESC\n"
            f"LIMIT {quantidade}"
        )

    return None
