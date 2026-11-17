"""Orquestração do texto-para-SQL (Aula 21).

O caminho é sempre o mesmo, independentemente de o provedor ser o mock desta
aula ou um LLM real no futuro:

    pergunta → prompt (schema) → LlmService → extração → validação → execução

Nenhuma etapa opcional: mesmo que o provedor devolva SQL perfeito, ele passa
pela validação e roda em transação read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from core.llm import criar_llm_service

from .execucao import ResultadoSql, executar_sql
from .extracao import extrair_sql
from .prompt import montar_mensagens
from .validacao import validar_sql

# Tetos de segurança usados quando o setting correspondente não está definido.
# Podem ser sobrescritos por ASK_SQL_MAX_LINHAS, ASK_SQL_TIMEOUT_MS e
# ASK_SQL_MAX_TOKENS no .env — e também por argumento explícito na chamada.
PADRAO_MAX_LINHAS = 200
PADRAO_TIMEOUT_MS = 3000
PADRAO_MAX_TOKENS = 500


@dataclass(frozen=True)
class ConsultaRespondida:
    """Resultado completo de uma pergunta de negócio.

    Imutável (``frozen=True``): depois de montada, a resposta não muda. A view
    só serializa este objeto para JSON.
    """

    pergunta: str  # pergunta original, já sem espaços nas pontas
    sql: str  # SQL final, depois da validação e do LIMIT aplicado
    resultado: ResultadoSql  # colunas, linhas e truncamento vindos do banco
    meta: dict[str, Any]  # tokens e modelo usado, para métricas/custo


def responder(
    pergunta: str,
    *,
    llm: Any | None = None,
    max_linhas: int | None = None,
    timeout_ms: int | None = None,
    max_tokens: int | None = None,
) -> ConsultaRespondida:
    """Executa o pipeline completo para uma pergunta em linguagem natural.

    O parâmetro ``llm`` existe para testes: a suíte injeta um serviço fake e
    não chama o provedor real. Em produção ele fica ``None`` e o serviço é
    criado a partir do ``LLM_PROVIDER`` configurado.
    """
    # 1) Resolve os limites: argumento explícito > setting > padrão do módulo.
    limite = _inteiro(max_linhas, "ASK_SQL_MAX_LINHAS", PADRAO_MAX_LINHAS)
    tempo_limite = _inteiro(timeout_ms, "ASK_SQL_TIMEOUT_MS", PADRAO_TIMEOUT_MS)
    tokens = _inteiro(max_tokens, "ASK_SQL_MAX_TOKENS", PADRAO_MAX_TOKENS)

    # 2) Escolhe o provedor de IA (Gemini/mock/auto) para a tarefa "sql".
    servico = llm if llm is not None else criar_llm_service(tarefa="sql")

    # 3) Chama o LLM. O prompt já carrega as regras e a allow-list do schema;
    #    temperature=0.0 busca a resposta mais determinística possível.
    resposta = servico.completar(
        montar_mensagens(pergunta),
        temperature=0.0,
        max_tokens=tokens,
    )

    # 4) Extrai o SQL do texto do modelo. Se a resposta for NAO_SUPORTADO ou
    #    não contiver SELECT/WITH, a exceção interrompe o fluxo aqui.
    sql = extrair_sql(resposta.texto)

    # 5) Valida o SQL sem confiar no modelo: allow-list, comandos proibidos,
    #    colunas sensíveis, SELECT * e LIMIT obrigatório.
    validado = validar_sql(sql, max_linhas=limite)

    # 6) Executa apenas o SQL validado, em transação READ ONLY e com timeout.
    #    É a última barreira: mesmo que algo passe, o banco não aceita escrita.
    resultado = executar_sql(
        validado.sql,
        max_linhas=validado.limite,
        timeout_ms=tempo_limite,
    )

    # 7) Monta a resposta final, preservando o SQL executado para auditoria.
    return ConsultaRespondida(
        pergunta=pergunta.strip(),
        sql=validado.sql,
        resultado=resultado,
        meta={
            # Tokens medidos pelo serviço: base para custo e observabilidade.
            "tokens_prompt": resposta.tokens_prompt,
            "tokens_output": resposta.tokens_output,
            # Nome do modelo efetivo (ex.: "gemini-3.5-flash-lite" ou "mock-sql").
            # O fallback do getattr evita quebrar com serviços de teste.
            "modelo": getattr(servico, "modelo", getattr(settings, "LLM_MODEL", "mock")),
        },
    )


def _inteiro(valor: int | None, nome_setting: str, padrao: int) -> int:
    """Resolve o limite: argumento explícito ou setting, sempre >= 1.

    Valores menores que 1 são rejeitados porque um LIMIT 0 (ou timeout
    negativo) tornaria a consulta inútil ou inválida.
    """
    if valor is None:
        valor = int(getattr(settings, nome_setting, padrao))
    if valor < 1:
        raise ValueError(f"{nome_setting} deve ser >= 1")
    return valor
