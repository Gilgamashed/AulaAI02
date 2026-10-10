"""Testes do `AssistSerializer` — o "payload inválido" do DoD (Aula 14, item 4).

O item 4 do DoD pede explicitamente provas de que o endpoint rejeita **payload
inválido**. As regras de guarda vivem no serializer (nada aqui é interpretado —
o conteúdo vai direto ao prompt do provedor), então a maior parte da margem é
testada nesta camada; o HTTP de confirmação (400) fica na integração.
"""

from __future__ import annotations

import pytest

from core.serializers import AssistSerializer

pytestmark = pytest.mark.unit


def _validar(payload: dict) -> AssistSerializer:
    serializer = AssistSerializer(data=payload)
    serializer.is_valid()
    return serializer


# =====================================================================
# Caminho feliz
# =====================================================================
def test_logs_simples_como_string_viram_lista():
    serializer = AssistSerializer(data={"mode": "summarize", "logs": "erro no checkout"})

    assert serializer.is_valid()
    assert serializer.validated_data["logs"] == ["erro no checkout"]
    assert serializer.validated_data["mode"] == "summarize"


def test_logs_como_lista_sao_normalizados_e_aparados():
    serializer = AssistSerializer(
        data={"mode": "explain", "logs": ["  linha 1  ", "linha 2"]}
    )

    assert serializer.is_valid()
    assert serializer.validated_data["logs"] == ["linha 1", "linha 2"]


def test_defaults_de_temperature_e_max_tokens():
    serializer = AssistSerializer(data={"mode": "summarize", "logs": ["x"]})

    assert serializer.is_valid()
    assert serializer.validated_data["temperature"] == 0.2
    assert serializer.validated_data["max_tokens"] == 256


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("temperature", 0.0),
        ("temperature", 1.0),
        ("max_tokens", 1),
        ("max_tokens", 4096),
    ],
)
def test_extremos_validos_da_faixa(campo, valor):
    payload = {"mode": "summarize", "logs": ["x"], campo: valor}

    assert AssistSerializer(data=payload).is_valid()


def test_excesso_de_caracteres_aceito_no_limite():
    logs = ["a" * AssistSerializer.LOGS_MAX_CARACTERES]

    assert AssistSerializer(data={"mode": "summarize", "logs": logs}).is_valid()


# =====================================================================
# Payload inválido
# =====================================================================
@pytest.mark.parametrize(
    "logs_invalido",
    [
        pytest.param(42, id="numero"),
        pytest.param({"a": 1}, id="objeto"),
        pytest.param(True, id="booleano"),
    ],
)
def test_logs_de_tipo_invalido_sao_rejeitados(logs_invalido):
    serializer = _validar({"mode": "summarize", "logs": logs_invalido})

    assert not serializer.is_valid()
    assert "logs" in serializer.errors


def test_lista_vazia_e_rejeitada():
    serializer = _validar({"mode": "summarize", "logs": []})

    assert not serializer.is_valid()
    assert "logs" in serializer.errors


def test_lista_com_item_nao_string_e_rejeitada():
    serializer = _validar({"mode": "summarize", "logs": ["ok", 3]})

    assert not serializer.is_valid()
    assert "logs" in serializer.errors


@pytest.mark.parametrize(
    "item_vazio",
    [
        pytest.param("", id="vazio"),
        pytest.param("   ", id="so-espacos"),
    ],
)
def test_item_vazio_de_log_e_rejeitado(item_vazio):
    serializer = _validar({"mode": "summarize", "logs": [item_vazio]})

    assert not serializer.is_valid()
    assert "logs" in serializer.errors


def test_logs_acima_do_limite_de_caracteres_e_rejeitado():
    logs = ["a" * (AssistSerializer.LOGS_MAX_CARACTERES + 1)]

    serializer = _validar({"mode": "summarize", "logs": logs})

    assert not serializer.is_valid()
    assert "logs" in serializer.errors


def test_mode_invalido_e_rejeitado():
    serializer = _validar({"mode": "traduzir", "logs": ["x"]})

    assert not serializer.is_valid()
    assert "mode" in serializer.errors


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("temperature", -0.1),
        ("temperature", 1.5),
        ("max_tokens", 0),
        ("max_tokens", 5000),
    ],
)
def test_valores_fora_da_faixa_sao_rejeitados(campo, valor):
    payload = {"mode": "summarize", "logs": ["x"], campo: valor}

    serializer = _validar(payload)

    assert not serializer.is_valid()
    assert campo in serializer.errors