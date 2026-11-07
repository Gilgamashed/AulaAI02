"""Contrato de entrada do `POST /api/v1/ask_docs/` (Aula 24)."""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from .constantes import (
    MAX_CARACTERES_PERGUNTA,
    PADRAO_MAX_TOP_K,
    PADRAO_MIN_SCORE,
    PADRAO_TOP_K,
)


class AskDocsSerializer(serializers.Serializer):
    """Valida `{question, top_k, min_score}` antes da recuperação."""

    question = serializers.CharField(
        max_length=MAX_CARACTERES_PERGUNTA,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "blank": "O campo question não pode ser vazio.",
            "max_length": (
                f"A pergunta deve ter no máximo {MAX_CARACTERES_PERGUNTA} "
                "caracteres."
            ),
        },
    )
    top_k = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=int(getattr(settings, "ASK_DOCS_MAX_TOP_K", PADRAO_MAX_TOP_K)),
        default=int(getattr(settings, "ASK_DOCS_TOP_K", PADRAO_TOP_K)),
        error_messages={
            "min_value": "top_k deve ser maior ou igual a 1.",
            "max_value": (
                "top_k não pode ser maior que "
                f"{int(getattr(settings, 'ASK_DOCS_MAX_TOP_K', PADRAO_MAX_TOP_K))}."
            ),
        },
    )
    min_score = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        default=float(getattr(settings, "ASK_DOCS_MIN_SCORE", PADRAO_MIN_SCORE)),
        error_messages={
            "min_value": "min_score deve estar entre 0.0 e 1.0.",
            "max_value": "min_score deve estar entre 0.0 e 1.0.",
        },
    )

    def validate(self, attrs: dict) -> dict:
        """Recusa tipos não numéricos/booleanos que o DRF converteria."""
        bruto = self.initial_data.get("question")
        if not isinstance(bruto, str):
            raise serializers.ValidationError(
                {"question": "O campo question deve ser um texto."}
            )

        if "top_k" in self.initial_data:
            valor_top_k = self.initial_data["top_k"]
            if isinstance(valor_top_k, bool) or not isinstance(valor_top_k, int):
                raise serializers.ValidationError(
                    {"top_k": "O campo top_k deve ser um inteiro."}
                )

        if "min_score" in self.initial_data:
            valor_score = self.initial_data["min_score"]
            if isinstance(valor_score, bool) or not isinstance(
                valor_score, (int, float)
            ):
                raise serializers.ValidationError(
                    {"min_score": "O campo min_score deve ser um número."}
                )

        return attrs
