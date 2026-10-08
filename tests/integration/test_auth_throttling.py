"""Integração: throttling do login (Aula 7) com a cota voltando a ser baixa.

O `settings_test` sobe todas as cotas para 1000/min de propósito — a suíte
não pode estourar cota por acidente. O 429 então não apareceria nunca, e é
exatamente o comportamento que a spec da Aula 7 exige provar. O fixture
`throttling_baixo` do conftest sobrepõe só o scope `login` de volta para
1/min, e este arquivo prova as três coisas:

* credencial válida emite o par access/refresh (o login funciona);
* a 2ª tentativa dentro da janela de 1/min cai na cota → 429;
* sem o override, os mesmos POSTs não estouram cota (o isolamento entre
  testes funciona, via `_estado_limpo`).
"""

import pytest

pytestmark = pytest.mark.integration

# Os testes pedem a fixture `db` mesmo com credencial inválida: o `simplejwt`
# consulta a tabela de usuários durante o `authenticate`, e sem acesso ao banco
# a própria autenticação (que deveria devolver 401) estoura antes da cota.

CORPO_INVALIDO = {"username": "nao-existe", "password": "senha-errada"}


def test_login_valido_emite_token(api_client, usuario, throttling_baixo):
    resposta = api_client.post(
        "/api/v1/auth/token/",
        {"username": "teste_user", "password": "Teste@123456"},
        format="json",
    )

    assert resposta.status_code == 200
    assert "access" in resposta.data
    assert "refresh" in resposta.data


def test_burst_de_login_atinge_a_cota_429(api_client, throttling_baixo, db):
    primeira = api_client.post("/api/v1/auth/token/", CORPO_INVALIDO, format="json")
    assert primeira.status_code == 401  # credencial ruim, mas sem throttling

    segunda = api_client.post("/api/v1/auth/token/", CORPO_INVALIDO, format="json")
    assert segunda.status_code == 429


def test_sem_cota_baixa_logins_nao_estouram_cota(api_client, db):
    # Sem `throttling_baixo`, a taxa é a do settings_test (1000/min): três
    # tentativas inválidas precisam devolver 401, nunca 429 — se um 429
    # aparecer aqui, é vazamento do teste anterior.
    for _ in range(3):
        resposta = api_client.post("/api/v1/auth/token/", CORPO_INVALIDO, format="json")
        assert resposta.status_code == 401