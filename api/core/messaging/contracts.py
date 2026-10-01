"""Contrato da mensagem `PedidoCriado` (versão 1).

Este arquivo é a implementação do contrato; a versão para humanos está em
`docs/contracts/pedido_criado.md`. As duas precisam andar juntas — o
documento explica o *porquê*, este código garante o *o quê*.

Formato do corpo (JSON):

```json
{
  "evento": "PedidoCriado",
  "versao": 1,
  "evento_id": "0f9c1e6c-2c1f-4a0a-9a3f-6b1d2c4e5f70",
  "idempotency_key": "9f2c...64 hex",
  "origem": "synapseshop-api",
  "ocorrido_em": "2026-09-30T12:00:00.000Z",
  "publicado_em": 1759243200123,
  "pedido": {
    "id": 42,
    "usuario_id": 2,
    "status": "pendente",
    "total": "1299.90",
    "itens": [
      {"sku": "APL-IP15-128", "quantidade": 1, "preco_unitario": "1299.90"}
    ]
  }
}
```

Regras de projeto:

* **Campos mínimos de negócio, e só eles.** O consumidor precisa do `id` (o
  que atualizar), do `usuario_id`, do `total` e dos `itens` com o preço
  unitário. Não vai `descricao`, `created_at` nem `updated_at` do model: o
  evento descreve o fato "um pedido foi criado", não um dump do registro.
* **`publicado_em` em epoch ms.** É o relógio do produtor, usado pelo worker
  para medir o tempo de fila. Sem ele, a latência end-to-end seria
  irreprodutível depois do fato.
* **`total` e `preco_unitario` como string.** `Decimal` não existe em JSON;
  serializar como float introduz erro de arredondamento no valor cobrado.
  A string é a única forma fiel, e o consumidor converte com `Decimal`.
* **Versão explícita.** `versao` permite aceitar um `v2` futuro sem quebrar
  consumidores `v1` (que rejeitam o que não conhecem — ver `validar_evento`).
* **Validação é explícita, não implícita.** O consumidor não confia no
  produtor: um payload que não bate com o contrato vira DLQ na hora.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

EVENTO_PEDIDO_CRIADO = "PedidoCriado"
VERSAO_CONTRATO = 1
ORIGEM = "synapseshop-api"


class ContratoInvalido(Exception):
    """Payload que não cumpre o contrato `PedidoCriado` v1.

    Falha **não recuperável**: reentregar dez vezes um JSON malformado não o
    torna válido, então o consumidor manda direto para a DLQ.
    """


@dataclass(frozen=True)
class ItemPedido:
    """Linha do pedido dentro do evento."""

    sku: str
    quantidade: int
    preco_unitario: Decimal


@dataclass(frozen=True)
class PedidoCriado:
    """Evento desserializado e já validado."""

    evento: str
    versao: int
    evento_id: str
    idempotency_key: str
    origem: str
    ocorrido_em: str
    publicado_em_ms: int
    pedido_id: int
    usuario_id: int
    status: str
    total: Decimal
    itens: tuple[ItemPedido, ...]

    @property
    def total_em_centavos(self) -> int:
        return int((self.total * 100).quantize(Decimal(1)))


def agora_iso() -> str:
    """Timestamp ISO-8601 em UTC, com milissegundos."""
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def construir_pedido_criado(pedido: Any, idempotency_key: str) -> dict[str, Any]:
    """Monta o corpo do evento a partir de uma instância de `Pedido`.

    `pedido.itens` é um `JSONField` gravado pelo serializer, já no formato
    `{"sku", "quantidade", "preco_unitario"}` — o snapshot do preço no
    momento da compra.
    """
    itens = [
        {
            "sku": item["sku"],
            "quantidade": int(item["quantidade"]),
            "preco_unitario": str(item["preco_unitario"]),
        }
        for item in pedido.itens
    ]
    return {
        "evento": EVENTO_PEDIDO_CRIADO,
        "versao": VERSAO_CONTRATO,
        "evento_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "origem": ORIGEM,
        "ocorrido_em": agora_iso(),
        # Epoch ms para o consumidor medir o tempo de fila sem depender de
        # comparar strings de data.
        "publicado_em": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
        "pedido": {
            "id": pedido.pk,
            "usuario_id": pedido.usuario_id,
            "status": pedido.status,
            "total": str(pedido.total),
            "itens": itens,
        },
    }


def serializar(corpo: dict[str, Any]) -> bytes:
    """Serializa o corpo do evento em bytes UTF-8."""
    return json.dumps(corpo, ensure_ascii=False).encode("utf-8")


def _obrigatorio(corpo: dict[str, Any], campo: str) -> Any:
    if campo not in corpo:
        raise ContratoInvalido(f"campo ausente no contrato: '{campo}'")
    return corpo[campo]


def _texto(corpo: dict[str, Any], campo: str) -> str:
    valor = _obrigatorio(corpo, campo)
    if not isinstance(valor, str) or not valor:
        raise ContratoInvalido(f"campo '{campo}' deve ser texto não vazio")
    return valor


def _inteiro(corpo: dict[str, Any], campo: str) -> int:
    valor = _obrigatorio(corpo, campo)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ContratoInvalido(f"campo '{campo}' deve ser inteiro")
    return valor


def _decimal(corpo: dict[str, Any], campo: str) -> Decimal:
    valor = _obrigatorio(corpo, campo)
    try:
        return Decimal(str(valor))
    except Exception as erro:  # qualquer texto não é Decimal
        raise ContratoInvalido(f"campo '{campo}' não é decimal: {erro}") from erro


def validar_evento(corpo: dict[str, Any]) -> PedidoCriado:
    """Valida o corpo contra o contrato v1 e devolve o evento tipado.

    Levanta `ContratoInvalido` com o motivo — a mensagem é o que vai para o
    log e para a DLQ, então ela precisa ser acionável por quem for tratar.
    """
    if not isinstance(corpo, dict):
        raise ContratoInvalido("corpo do evento não é um objeto JSON")

    evento = _texto(corpo, "evento")
    if evento != EVENTO_PEDIDO_CRIADO:
        raise ContratoInvalido(
            f"evento '{evento}' não é suportado (esperado '{EVENTO_PEDIDO_CRIADO}')"
        )

    versao = _inteiro(corpo, "versao")
    if versao != VERSAO_CONTRATO:
        raise ContratoInvalido(
            f"versão {versao} do contrato não suportada (esperado {VERSAO_CONTRATO})"
        )

    idempotency_key = _texto(corpo, "idempotency_key")
    publicado_em = _inteiro(corpo, "publicado_em")

    pedido = _obrigatorio(corpo, "pedido")
    if not isinstance(pedido, dict):
        raise ContratoInvalido("campo 'pedido' não é um objeto JSON")

    itens_brutos = _obrigatorio(pedido, "itens")
    if not isinstance(itens_brutos, list) or not itens_brutos:
        raise ContratoInvalido("campo 'pedido.itens' deve ser uma lista não vazia")

    itens: list[ItemPedido] = []
    for posicao, item in enumerate(itens_brutos):
        if not isinstance(item, dict):
            raise ContratoInvalido(f"pedido.itens[{posicao}] não é um objeto")
        sku = _texto(item, "sku")
        quantidade = _inteiro(item, "quantidade")
        if quantidade < 1:
            raise ContratoInvalido(
                f"pedido.itens[{posicao}].quantidade deve ser >= 1"
            )
        itens.append(
            ItemPedido(
                sku=sku,
                quantidade=quantidade,
                preco_unitario=_decimal(item, "preco_unitario"),
            )
        )

    return PedidoCriado(
        evento=evento,
        versao=versao,
        evento_id=_texto(corpo, "evento_id"),
        idempotency_key=idempotency_key,
        origem=_texto(corpo, "origem"),
        ocorrido_em=_texto(corpo, "ocorrido_em"),
        publicado_em_ms=publicado_em,
        pedido_id=_inteiro(pedido, "id"),
        usuario_id=_inteiro(pedido, "usuario_id"),
        status=_texto(pedido, "status"),
        total=_decimal(pedido, "total"),
        itens=tuple(itens),
    )
