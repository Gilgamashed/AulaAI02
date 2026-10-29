"""Integração do `POST /api/v1/ask_sql/` (Aula 21).

Exercita o caminho HTTP completo: autenticação/papel, validação do payload,
geração determinística pelo mock, validação de segurança, execução read-only e
o contrato de resposta. Os casos de SQL malicioso usam um serviço falso para
provar que a barreira é a validação/execução, e não a boa vontade do modelo.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from core.ask_sql import servico as ask_sql_servico
from core.ask_sql.erros import ExecucaoSqlFalhou
from core.ask_sql.execucao import executar_sql
from core.llm import (
    LlmConfiguracaoInvalida,
    LlmIndisponivel,
    LlmResposta,
    LlmTerminal,
)
from core.models import Pedido

pytestmark = pytest.mark.integration

CORPO = {"question": "Quais os 5 últimos usuários cadastrados?"}


class _ServicoFake:
    """Substitui o `LlmService` devolvendo um texto fixo ou levantando um erro."""

    modelo = "fake"

    def __init__(self, *, texto: str = "", erro: Exception | None = None) -> None:
        self._texto = texto
        self._erro = erro

    def completar(self, mensagens, *, temperature, max_tokens) -> LlmResposta:
        if self._erro is not None:
            raise self._erro
        return LlmResposta(texto=self._texto, tokens_prompt=10, tokens_output=5)


def _usar_servico(monkeypatch, servico: _ServicoFake) -> None:
    monkeypatch.setattr(
        ask_sql_servico,
        "criar_llm_service",
        lambda tarefa="sql": servico,
    )


def _criar_pedido(usuario, chave: str, total: str = "10.00") -> Pedido:
    return Pedido.objects.create(
        usuario=usuario,
        total=Decimal(total),
        idempotency_key=chave,
    )


# =====================================================================
# Autenticação e autorização
# =====================================================================
def test_ask_sql_sem_token_devolve_401(api_client):
    resposta = api_client.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 401


def test_ask_sql_com_usuario_comum_devolve_403(client_autenticado):
    resposta = client_autenticado.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 403


# =====================================================================
# Payload (400)
# =====================================================================
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="sem-question"),
        pytest.param({"question": ""}, id="vazio"),
        pytest.param({"question": "   "}, id="so-espacos"),
        pytest.param({"question": 42}, id="tipo-errado"),
        pytest.param({"question": "x" * 501}, id="acima-do-limite"),
    ],
)
def test_ask_sql_payload_invalido_devolve_400(client_admin, payload):
    resposta = client_admin.post("/api/v1/ask_sql/", payload, format="json")

    assert resposta.status_code == 400


# =====================================================================
# Caminho feliz com dados reais
# =====================================================================
def test_ultimos_usuarios_devolve_sql_e_resultado(client_admin):
    User = get_user_model()
    for indice in range(4):
        User.objects.create_user(
            username=f"cliente{indice}", password="Teste@123456"
        )

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 200
    corpo = resposta.data
    assert set(corpo) == {
        "question",
        "sql",
        "columns",
        "rows",
        "row_count",
        "truncated",
        "meta",
    }
    assert corpo["question"] == CORPO["question"]
    assert corpo["sql"].startswith("SELECT")
    assert "FROM auth_user" in corpo["sql"]
    assert corpo["columns"] == [
        "id",
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "date_joined",
    ]
    assert corpo["row_count"] == 5
    assert len(corpo["rows"]) == 5
    assert corpo["rows"][0]["username"] == "cliente3"
    assert corpo["truncated"] is False
    assert corpo["meta"]["modelo"] == "mock-sql"
    assert corpo["meta"]["tokens_prompt"] > 0


def test_soma_dos_ultimos_pedidos(client_admin, usuario):
    for indice, total in enumerate(("10.00", "20.00", "30.00")):
        _criar_pedido(usuario, f"soma-{indice}", total)

    resposta = client_admin.post(
        "/api/v1/ask_sql/",
        {"question": "Qual a soma do valor dos últimos 3 pedidos?"},
        format="json",
    )

    assert resposta.status_code == 200
    assert resposta.data["columns"] == ["soma_total"]
    assert resposta.data["rows"] == [{"soma_total": 60.0}]
    assert resposta.data["row_count"] == 1


def test_usuarios_com_mais_pedidos(client_admin, usuario):
    User = get_user_model()
    outro = User.objects.create_user(username="outro_cliente", password="Teste@123456")
    _criar_pedido(usuario, "mais-1")
    _criar_pedido(usuario, "mais-2")
    _criar_pedido(outro, "mais-3")

    resposta = client_admin.post(
        "/api/v1/ask_sql/",
        {"question": "Quais usuários fizeram mais pedidos?"},
        format="json",
    )

    assert resposta.status_code == 200
    linhas = {linha["username"]: linha["total_pedidos"] for linha in resposta.data["rows"]}
    assert linhas["teste_user"] == 2
    assert linhas["outro_cliente"] == 1


def test_pergunta_fora_do_dominio_devolve_422_com_exemplos(client_admin):
    resposta = client_admin.post(
        "/api/v1/ask_sql/",
        {"question": "Qual o endereço de entrega do pedido 42?"},
        format="json",
    )

    assert resposta.status_code == 422
    assert resposta.data["detail"]
    assert resposta.data["examples"]


# =====================================================================
# Segurança: SQL gerado (mesmo que o modelo desobedeça)
# =====================================================================
@pytest.mark.parametrize(
    "sql",
    [
        pytest.param("DELETE FROM core_pedido", id="delete"),
        pytest.param("UPDATE core_pedido SET total = 0", id="update"),
        pytest.param("DROP TABLE core_pedido", id="drop"),
        pytest.param("SELECT password FROM auth_user", id="coluna-sensivel"),
        pytest.param("SELECT * FROM core_pedido", id="select-estrela"),
        pytest.param("SELECT id FROM enderecos_entrega", id="tabela-inexistente"),
        pytest.param("SELECT id FROM pg_catalog.pg_tables", id="catalogo-interno"),
        pytest.param("SELECT id FROM auth_user, core_pedido", id="juncao-virgula"),
    ],
)
def test_sql_proibido_devolve_422(client_admin, monkeypatch, sql):
    _usar_servico(monkeypatch, _ServicoFake(texto=sql))

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 422
    assert resposta.data["detail"]


def test_delete_nao_apaga_dados(client_admin, monkeypatch, usuario):
    pedido = _criar_pedido(usuario, "preservar")
    _usar_servico(monkeypatch, _ServicoFake(texto="DELETE FROM core_pedido"))

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 422
    assert Pedido.objects.filter(pk=pedido.pk).exists()


def test_sql_com_erro_de_sintaxe_devolve_422(client_admin, monkeypatch):
    _usar_servico(monkeypatch, _ServicoFake(texto="SELECT FROM"))

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 422
    assert "executada" in resposta.data["detail"]


def test_resposta_nao_suportada_do_provedor_devolve_422(client_admin, monkeypatch):
    _usar_servico(monkeypatch, _ServicoFake(texto="NAO_SUPORTADO"))

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == 422


# =====================================================================
# Falhas da camada de IA
# =====================================================================
@pytest.mark.parametrize(
    ("erro", "status_esperado"),
    [
        pytest.param(LlmConfiguracaoInvalida("config"), 500, id="configuracao"),
        pytest.param(LlmTerminal("resposta inválida"), 502, id="terminal"),
        pytest.param(LlmIndisponivel("fora do ar"), 503, id="indisponivel"),
    ],
)
def test_falhas_do_provedor_sao_traduzidas(
    client_admin, monkeypatch, erro, status_esperado
):
    _usar_servico(monkeypatch, _ServicoFake(erro=erro))

    resposta = client_admin.post("/api/v1/ask_sql/", CORPO, format="json")

    assert resposta.status_code == status_esperado


# =====================================================================
# Execução: serialização, truncamento e read-only no banco
# =====================================================================
def test_execucao_serializa_tipos_e_trunca(client_admin, usuario):
    for indice in range(3):
        _criar_pedido(usuario, f"exec-{indice}", "12.50")

    resultado = executar_sql(
        "SELECT id, total, created_at FROM core_pedido ORDER BY id",
        max_linhas=2,
        timeout_ms=3000,
    )

    assert resultado.truncado is True
    assert resultado.total_linhas == 2
    assert resultado.colunas == ["id", "total", "created_at"]
    assert isinstance(resultado.linhas[0]["total"], float)
    assert isinstance(resultado.linhas[0]["created_at"], str)


@pytest.mark.django_db(transaction=True)
def test_transacao_read_only_recusa_escrita():
    User = get_user_model()
    usuario = User.objects.create_user(username="readonly", password="Teste@123456")

    with pytest.raises(ExecucaoSqlFalhou):
        executar_sql(
            (
                "INSERT INTO core_pedido "
                "(usuario_id, status, itens, total, idempotency_key, simular_falha, "
                "tentativas, motivo_falha, created_at, updated_at) "
                f"VALUES ({usuario.pk}, 'pendente', '[]', 1, 'readonly', false, 0, "
                "'', NOW(), NOW())"
            ),
            max_linhas=10,
            timeout_ms=3000,
        )

    assert not Pedido.objects.filter(idempotency_key="readonly").exists()
    assert usuario.pk is not None
