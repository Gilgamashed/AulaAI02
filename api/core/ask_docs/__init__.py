"""Assistente de documentação com RAG (Aula 24).

Pipeline: ingestão de `README.md`/`docs/openapi.yaml` → chunks com overlap →
embeddings locais → índice SQLite → busca por cosseno → `LlmService` com
citação obrigatória das fontes. A view pública é
`core.ask_docs.views.AskDocsView`.
"""
