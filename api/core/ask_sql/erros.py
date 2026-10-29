"""Erros do texto-para-SQL (Aula 21).

Separá-los do `core.llm.erros` é deliberado: a camada de IA continua neutra de
tarefa. Aqui ficam os erros que só existem depois que o provedor respondeu —
SQL ausente, pergunta fora do domínio, SQL proibido e falha de execução — para
a view traduzi-los em 422/503 sem inspecionar strings.
"""

from __future__ import annotations


class AskSqlErro(Exception):
    """Base dos erros de geração/validação/execução de SQL."""


class PerguntaNaoSuportada(AskSqlErro):
    """O provedor declarou que a pergunta está fora do schema disponível."""


class SqlNaoGerado(AskSqlErro):
    """A resposta do provedor não contém uma consulta SQL."""


class SqlInvalido(AskSqlErro):
    """A consulta gerada não passou na validação de segurança."""


class SqlProibido(SqlInvalido):
    """A consulta gerada usa tabela/coluna/comando fora da allow-list."""


class ExecucaoSqlFalhou(AskSqlErro):
    """O PostgreSQL recusou a consulta (sintaxe, permissão, timeout etc.)."""


class BancoIndisponivel(AskSqlErro):
    """Não foi possível falar com o banco de dados."""
