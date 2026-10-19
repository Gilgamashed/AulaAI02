"""Testes da política de reentrega compartilhada pelos dois brokers.

`core.messaging.politica` é a fonte única de mecanismo que antes vivia duplicado
no consumidor AMQP (Aula 9) e no consumidor Kafka (Aulas 10-11): leitura do
contador `x-tentativa`, decisão da escada (retry × DLQ) e desserialização do
corpo. São funções puras — nenhum delas toca broker, banco ou rede — então o
lugar delas é a suíte unitária, mesmo estando o `*/messaging/*` fora do gate
de cobertura.
"""

from __future__ import annotations

import json

import pytest

from core.messaging.contracts import ContratoInvalido
from core.messaging.politica import (
    HEADER_EVENTO_ID,
    HEADER_MOTIVO,
    HEADER_TENTATIVA,
    Destino,
    degrau_de,
    decidir_reentrega,
    desserializar_corpo,
    tentativa_de,
)

pytestmark = pytest.mark.unit


def test_cabecalhos_sao_os_mesmos_do_contrato_escrito():
    """Os nomes fazem parte do contrato (`docs/contracts/pedido_criado.md`).

    Renomear um deles quebra a compatibilidade com mensagens já em trânsito e
    com o `inspecionar_dlq_kafka`; o teste impede a mudança silenciosa.
    """
    assert HEADER_TENTATIVA == "x-tentativa"
    assert HEADER_EVENTO_ID == "x-evento-id"
    assert HEADER_MOTIVO == "x-motivo"


class TestTentativaDe:
    def test_contador_presente_e_lido(self):
        assert tentativa_de({"x-tentativa": "2"}) == 2

    def test_sem_headers_comeca_em_zero(self):
        assert tentativa_de({}) == 0
        assert tentativa_de(None) == 0

    def test_valor_corrompido_nao_explode(self):
        """Header não numérico vira 0 (primeira tentativa), nunca exceção.

        O contador viaja em banda de texto nos dois brokers; um valor torto
        não pode derrubar o laço de consumo.
        """
        assert tentativa_de({"x-tentativa": "abc"}) == 0
        assert tentativa_de({"x-tentativa": None}) == 0


class TestDecidirReentrega:
    def test_no_meio_da_escada_reentrega(self):
        destino = decidir_reentrega(0, max_reentregas=3, degraus=3)
        assert destino is Destino.RETRY

    def test_ultima_tentativa_consumida_vai_para_dlq(self):
        destino = decidir_reentrega(3, max_reentregas=3, degraus=3)
        assert destino is Destino.DLQ_ESGOTADA

    def test_degraus_insuficientes_vai_para_dlq_sem_retry_fantasma(self):
        """Mais reentregas permitidas do que degraus configurados.

        Com `degraus=2` os tópicos/filas `retry.1` e `retry.2` existem; na
        tentativa 2 o próximo degrau seria o 3, que ninguém declarou.
        Reentregar é impossível — a única rota honesta é a DLQ, e o chamador
        loga a inconsistência de política.
        """
        destino = decidir_reentrega(2, max_reentregas=5, degraus=2)
        assert destino is Destino.DLQ_SEM_DEGRAU

    def test_degrau_e_um_indexado_a_partir_de_um(self):
        assert degrau_de(0) == 1
        assert degrau_de(2) == 3


class TestDesserializarCorpo:
    def test_objeto_json_valido_vira_dict(self):
        assert desserializar_corpo(b'{"pedido_id": 7}') == {"pedido_id": 7}

    def test_json_quebrado_e_contrato_invalido(self):
        """Reentregar não conserta JSON: falha terminal, caminho para a DLQ."""
        with pytest.raises(ContratoInvalido):
            desserializar_corpo(b"{nao e json")

    def test_corpo_nao_utf8_e_contrato_invalido(self):
        with pytest.raises(ContratoInvalido):
            desserializar_corpo(b"\xff\xfe")

    def test_json_nao_objeto_e_contrato_invalido(self):
        """Top-level lista/escalar não tem campos do contrato para validar."""
        with pytest.raises(ContratoInvalido):
            desserializar_corpo(json.dumps([1, 2, 3]).encode("utf-8"))
