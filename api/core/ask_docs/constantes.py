"""Constantes do assistente de documentação (Aula 24)."""

from __future__ import annotations

PADRAO_TOP_K = 3
PADRAO_MAX_TOP_K = 10
PADRAO_MIN_SCORE = 0.25
PADRAO_CHUNK_TOKENS = 400
PADRAO_CHUNK_OVERLAP = 80
PADRAO_MAX_TOKENS = 600
MAX_CARACTERES_PERGUNTA = 500

FONTES_PADRAO = ("README.md", "docs/openapi.yaml")

TITULOS_PADRAO = {
    "README.md": "Documentação SynapseShop",
    "docs/openapi.yaml": "Contrato OpenAPI SynapseShop",
}

FRASE_GUARDRAIL = (
    "Não encontrei essa informação na documentação do projeto. "
    "Tente reformular a pergunta ou consulte o README.md e o contrato OpenAPI."
)

MARCADOR_PERGUNTA = "PERGUNTA:"
