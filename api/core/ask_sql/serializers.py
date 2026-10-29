"""Contrato de entrada do `POST /api/v1/ask_sql/` (Aula 21)."""

from __future__ import annotations

from rest_framework import serializers

MAX_CARACTERES_PERGUNTA = 500


class AskSqlSerializer(serializers.Serializer):
    """Valida `{"question": "..."}` antes de acionar a camada de IA."""

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

    def validate(self, attrs: dict) -> dict:
        """Recusa tipos não textuais: `CharField` converteria `42` em `"42"`."""
        bruto = self.initial_data.get("question")
        if not isinstance(bruto, str):
            raise serializers.ValidationError(
                {"question": "O campo question deve ser um texto."}
            )
        return attrs
