"""Testes de integração das métricas da API (Aula 20)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import RequisicaoMetrica


def _criar_metrica(**overrides) -> RequisicaoMetrica:
    dados = {
        "metodo": "GET",
        "endpoint": "/api/v1/items/",
        "status_code": 200,
        "latencia_ms": 12.5,
    }
    dados.update(overrides)
    return RequisicaoMetrica.objects.create(**dados)


@pytest.mark.integration
@pytest.mark.django_db
def test_middleware_registra_metrica_e_normaliza_path():
    client = APIClient()
    resp = client.get("/api/v1/items/")
    assert resp.status_code in (200, 401, 403)
    metricas = RequisicaoMetrica.objects.all()
    assert metricas.exists()
    alguma = metricas.first()
    assert alguma.endpoint.startswith("/api/v1/items") or alguma.endpoint == "/api/v1/items/"
    # Não deve conter IDs numéricos crus quando normalizado
    for metrica in metricas:
        assert "/123/" not in metrica.endpoint or "{id}" in metrica.endpoint


@pytest.mark.integration
@pytest.mark.django_db
def test_middleware_registra_cache_hit_real():
    """Duas listagens iguais: a segunda é HIT e o delta vai para a linha dela.

    O cache da suíte é LocMem (settings_test), mas o caminho exercitado é o
    mesmo de produção (`cache_aside` + coletor de métricas).
    """
    client = APIClient()
    assert client.get("/api/v1/items/").status_code == 200
    assert client.get("/api/v1/items/").status_code == 200

    primeira = RequisicaoMetrica.objects.order_by("id").first()
    segunda = RequisicaoMetrica.objects.order_by("-id").first()
    assert primeira is not None and segunda is not None
    assert primeira.cache_misses == 1
    assert primeira.cache_hits == 0
    assert segunda.cache_misses == 0
    assert segunda.cache_hits == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_middleware_ignora_health_e_rotas_fora_da_api():
    client = APIClient()
    antes = RequisicaoMetrica.objects.count()
    assert client.get("/health").status_code == 200
    client.get("/rota-fora-da-api/")
    client.get("/admin/login/")
    assert RequisicaoMetrica.objects.count() == antes


@pytest.mark.integration
@pytest.mark.django_db
def test_middleware_respeita_toggle(settings):
    settings.API_METRICS_ENABLED = False
    client = APIClient()
    antes = RequisicaoMetrica.objects.count()
    client.get("/api/v1/items/")
    assert RequisicaoMetrica.objects.count() == antes


@pytest.mark.integration
@pytest.mark.django_db
def test_middleware_nao_derruba_requisicao_se_a_gravacao_falhar(monkeypatch):
    """A métrica é acessória: falha ao gravar não pode virar 500 no cliente."""
    def _falhar(*args, **kwargs):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(RequisicaoMetrica.objects, "create", _falhar)

    client = APIClient()
    assert client.get("/api/v1/items/").status_code == 200


@pytest.mark.integration
@pytest.mark.django_db
def test_limpar_metricas_poda_por_retencao():
    antiga = _criar_metrica()
    recente = _criar_metrica()
    RequisicaoMetrica.objects.filter(pk=antiga.pk).update(
        created_at=timezone.now() - timedelta(days=40)
    )

    call_command("limpar_metricas", dias=30)

    assert not RequisicaoMetrica.objects.filter(pk=antiga.pk).exists()
    assert RequisicaoMetrica.objects.filter(pk=recente.pk).exists()


@pytest.mark.integration
@pytest.mark.django_db
def test_limpar_metricas_dry_run_nao_apaga():
    antiga = _criar_metrica()
    RequisicaoMetrica.objects.filter(pk=antiga.pk).update(
        created_at=timezone.now() - timedelta(days=40)
    )

    call_command("limpar_metricas", dias=30, dry_run=True)

    assert RequisicaoMetrica.objects.filter(pk=antiga.pk).exists()
