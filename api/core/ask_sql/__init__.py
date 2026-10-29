"""Texto-para-SQL seguro (Aula 21).

Pipeline: prompt com schema → `LlmService` → extração → validação → execução
em transação read-only. A view pública é `core.ask_sql.views.AskSqlView`.
"""
