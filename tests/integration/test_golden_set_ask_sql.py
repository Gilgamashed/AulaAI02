"""Regressão do golden set de texto-para-SQL com o mock determinístico.

A spec 01 usa os itens `ci_mock` como linha de base da spec 02: o mock não
pode regredir e o teste prova, via HTTP, que cada item esperado continua
retornando 200 com as colunas/linhas contratadas ou 422 nas recusas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from core.ask_sql import servico as ask_sql_servico
from core.llm.mock_sql import ProvedorMockSql

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parents[2]
GOLDEN = RAIZ / "scripts" / "avaliacao_ia" / "golden_set.json"


def _itens_ci_mock() -> list[dict]:
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [
        item
        for item in dados["itens"]
        if item["endpoint"] == "/api/v1/ask_sql/" and "ci_mock" in item["tags"]
    ]


@pytest.mark.django_db
def test_itens_ci_mock_do_golden_set_com_mock(client_admin, monkeypatch):
    call_command("seed_auth", verbosity=0)
    call_command("seed_demo", silent=True)
    monkeypatch.setattr(
        ask_sql_servico,
        "criar_llm_service",
        lambda tarefa="sql": ProvedorMockSql(),
    )

    itens = _itens_ci_mock()
    assert len(itens) >= 20

    for item in itens:
        resposta = client_admin.post(
            "/api/v1/ask_sql/",
            {"question": item["pergunta"]},
            format="json",
        )
        if item["tipo_resultado"] == "recusa_esperada":
            assert resposta.status_code == 422, (item["id"], resposta.data)
            assert resposta.data.get("detail"), item["id"]
            continue

        assert resposta.status_code == 200, (item["id"], resposta.data)
        colunas = {str(coluna).lower() for coluna in resposta.data["columns"]}
        for entrada in item["esperado"].get("colunas_min", []):
            alternativas = [entrada] if isinstance(entrada, str) else entrada
            assert any(
                str(alternativa).lower() in colunas for alternativa in alternativas
            ), (item["id"], entrada, colunas)
        assert resposta.data["row_count"] >= item["esperado"].get("linhas_min", 0), (
            item["id"],
            resposta.data["row_count"],
        )
