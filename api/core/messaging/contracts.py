"""Contratos de mensagem da API (versão 1).

Este arquivo é a implementação dos contratos; as versões para humanos estão em
`docs/contracts/`. As duas precisam andar juntas — o documento explica o
*porquê*, este código garante o *o quê*.

Há **dois** contratos nesta etapa, e a distinção é a mesma que a API:

| Contrato              | Quem produz                        | O que descreve               |
| --------------------- | ---------------------------------- | ---------------------------- |
| `PedidoCriado`        | `POST /api/v1/pedidos`             | um pedido passou a existir   |
| `PagamentoRegistrado` | `POST /api/v1/pedidos/{id}/pagamento/` | o gateway respondeu     |

Formato do corpo de `PedidoCriado` (JSON):

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

Formato do corpo de `PagamentoRegistrado` (JSON):

```json
{
  "evento": "PagamentoRegistrado",
  "versao": 1,
  "evento_id": "b1d2c4e5-7f70-4a1a-8b2c-3d4e5f607182",
  "idempotency_key": "7c3e...64 hex",
  "origem": "synapseshop-api",
  "ocorrido_em": "2026-09-30T12:00:03.120Z",
  "publicado_em": 1759243203120,
  "pagamento": {
    "id": 7,
    "pedido_id": 42,
    "usuario_id": 2,
    "status": "aprovado",
    "metodo": "pix",
    "valor": "1299.90",
    "aprovado": true,
    "motivo_recusa": "",
    "canal_notificacao": "email"
  }
}
```

Regras de projeto:

* **Campos mínimos de negócio, e só eles.** O consumidor do pedido precisa do
  `id` (o que atualizar), do `usuario_id`, do `total` e dos `itens` com o preço
  unitário. Não vai `descricao`, `created_at` nem `updated_at` do model: o
  evento descreve o fato "um pedido foi criado", não um dump do registro. O
  mesmo vale para o pagamento, com uma exceção deliberada:
  `canal_notificacao` entra porque o worker **cria** a notificação com ele — e
  descobrir o canal com um segundo lookup gastaria uma leitura do banco que a
  mensagem já podia evitar.
* **A mesma `envelope` nos dois contratos.** `evento`, `versao`, `evento_id`,
  `idempotency_key`, `origem`, `ocorrido_em` e `publicado_em` são idênticos — é
  isso que permite a um único consumidor tratar os dois eventos, logar com os
  mesmos campos e passar pela mesma política de reentrega. O que muda é o nome
  do bloco de negócio (`pedido` ou `pagamento`).
* **`publicado_em` em epoch ms.** É o relógio do produtor, usado pelo worker
  para medir o tempo de fila. Sem ele, a latência end-to-end seria
  irreprodutível depois do fato.
* **`total` e `preco_unitario` como string.** `Decimal` não existe em JSON;
  serializar como float introduz erro de arredondamento no valor cobrado.
  A string é a única forma fiel, e o consumidor converte com `Decimal`.
* **Versão explícita.** `versao` permite aceitar um `v2` futuro sem quebrar
  consumidores `v1` (que rejeitam o que não conhecem — ver `validar`).
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
EVENTO_PAGAMENTO_REGISTRADO = "PagamentoRegistrado"
VERSAO_CONTRATO = 1
ORIGEM = "synapseshop-api"


class ContratoInvalido(Exception):
    """Payload que não cumpre um dos contratos v1.

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
    ocorreu_em: str
    publicado_em_ms: int
    pedido_id: int
    usuario_id: int
    status: str
    total: Decimal
    itens: tuple[ItemPedido, ...]

    @property
    def total_em_centavos(self) -> int:
        return int((self.total * 100).quantize(Decimal(1)))

    @property
    def fluxo(self) -> str:
        """Nome do fluxo, usado na chave de dedupe e nos logs."""
        return "pedidos"

    def chave_dedupe(self) -> str:
        """Chave da janela de idempotência deste evento.

        O **nome do fluxo entra na chave** e isso não é cosmético: o
        `PagamentoRegistrado` compartilha a `envelope` com o `PedidoCriado`, e
        sem o prefixo uma chave de pagamento poderia — no mesmo par de 64 hex
        — colidir com a chave de um pedido. Ver `dedupe._chave_cache`.
        """
        return f"pedidos:{self.idempotency_key}"


@dataclass(frozen=True)
class PagamentoRegistrado:
    """Evento do gateway de pagamento, já validado."""

    evento: str
    versao: int
    evento_id: str
    idempotency_key: str
    origem: str
    ocorreu_em: str
    publicado_em_ms: int
    pagamento_id: int
    pedido_id: int
    usuario_id: int
    status: str
    metodo: str
    valor: Decimal
    aprovado: bool
    motivo_recusa: str
    canal_notificacao: str

    @property
    def fluxo(self) -> str:
        """Nome do fluxo, usado na chave de dedupe e nos logs."""
        return "pagamentos"

    def chave_dedupe(self) -> str:
        """Chave da janela de idempotência deste evento.

        A chave é o `idempotency_key` do **pagamento**, e não o do pedido. Os
        dois contratos compartilham o formato da `envelope`, e é justamente por
        isso que o prefixo de fluxo não é opcional.
        """
        return f"pagamentos:{self.idempotency_key}"


# União dos dois contratos: o que o consumidor pode receber depois de `validar`.
Evento = PedidoCriado | PagamentoRegistrado


def agora_iso() -> str:
    """Timestamp ISO-8601 em UTC, com milissegundos."""
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _envelope(evento: str, idempotency_key: str) -> dict[str, Any]:
    """Metadados comuns aos dois contratos.

    `publicado_em` (epoch ms) é o relógio do produtor: é o que permite ao
    consumidor medir o tempo de fila sem depender de comparar strings de data.
    """
    return {
        "evento": evento,
        "versao": VERSAO_CONTRATO,
        "evento_id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "origem": ORIGEM,
        "ocorrido_em": agora_iso(),
        "publicado_em": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    }


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
        **_envelope(EVENTO_PEDIDO_CRIADO, idempotency_key),
        "pedido": {
            "id": pedido.pk,
            "usuario_id": pedido.usuario_id,
            "status": pedido.status,
            "total": str(pedido.total),
            "itens": itens,
        },
    }


def construir_pagamento_registrado(pagamento: Any) -> dict[str, Any]:
    """Monta o corpo do evento a partir de uma instância de `Pagamento`.

    `canal_notificacao` não é uma coluna do `Pagamento`: é a escolha do cliente
    no `POST /pagamento/`. Ela viaja no evento porque o worker cria a
    notificação — se ele tivesse de ler o canal de outro lugar, o evento não
    descreveria o fato inteiro.

    `motivo_recusa` vai **sempre**, mesmo vazio: um consumidor que fizesse
    `.get("motivo_recusa")` para decidir se houve recusa quebraria se o campo
    sumisse, e a distinção entre "aprovado" e "recusado" é `aprovado`, que é
    obrigatório.

    O `status` publicado é o **desfecho** (`aprovado`/`recusado`) e não o estado
    provisório `registrado` em que o `Pagamento` está no banco quando o evento
    é construído. `registrado` responde "o evento já foi publicado?", que é uma
    pergunta sobre a *publicação* e não sobre o *fato*; e o contrato valida a
    coerência entre `status` e `aprovado`, então publicar o estado provisório faria
    o próprio contrato recusar a mensagem.

    `pagamento.pedido` precisa estar carregado (`select_related("pedido")`) para
    o `usuario_id`: um attribute access a cada publicação seria uma query
    silenciosa no caminho do POST.
    """
    desfecho = "aprovado" if pagamento.aprovado else "recusado"
    return {
        **_envelope(EVENTO_PAGAMENTO_REGISTRADO, pagamento.idempotency_key),
        "pagamento": {
            "id": pagamento.pk,
            "pedido_id": pagamento.pedido_id,
            "usuario_id": pagamento.pedido.usuario_id,
            "status": desfecho,
            "metodo": pagamento.metodo,
            "valor": str(pagamento.valor),
            "aprovado": bool(pagamento.aprovado),
            "motivo_recusa": pagamento.motivo_recusa or "",
            "canal_notificacao": getattr(pagamento, "canal_notificacao", "email"),
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


def _texto_opcional(corpo: dict[str, Any], campo: str, padrao: str) -> str:
    """Texto que pode faltar ou vir vazio, com um padrão explícito.

    Diferente de `_texto`: aqui a ausência **é** informação válida (um
    pagamento aprovado não tem motivo de recusa), então `""` é um valor legítimo
    e não um payload quebrado.
    """
    valor = corpo.get(campo, padrao)
    if valor is None:
        return padrao
    if not isinstance(valor, str):
        raise ContratoInvalido(f"campo '{campo}' deve ser texto")
    return valor


def _inteiro(corpo: dict[str, Any], campo: str) -> int:
    valor = _obrigatorio(corpo, campo)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ContratoInvalido(f"campo '{campo}' deve ser inteiro")
    return valor


def _booleano(corpo: dict[str, Any], campo: str) -> bool:
    valor = _obrigatorio(corpo, campo)
    if not isinstance(valor, bool):
        raise ContratoInvalido(f"campo '{campo}' deve ser booleano")
    return valor


def _decimal(corpo: dict[str, Any], campo: str) -> Decimal:
    valor = _obrigatorio(corpo, campo)
    try:
        return Decimal(str(valor))
    except Exception as erro:  # qualquer texto não é Decimal
        raise ContratoInvalido(f"campo '{campo}' não é decimal: {erro}") from erro


def _envelope_comum(corpo: dict[str, Any]) -> tuple[str, int, str, str, str, str, int]:
    """Valida (e devolve) os campos da `envelope` compartilhada.

    O `evento` já foi conferido pelo despachante `validar`, então aqui só se
    verifica a **versão** — que é a regra de compatibilidade: um consumidor v1
    rejeita o que não conhece, em vez de tentar ler um campo a mais.
    """
    versao = _inteiro(corpo, "versao")
    if versao != VERSAO_CONTRATO:
        raise ContratoInvalido(
            f"versão {versao} do contrato não suportada (esperado {VERSAO_CONTRATO})"
        )
    return (
        _texto(corpo, "evento"),
        versao,
        _texto(corpo, "evento_id"),
        _texto(corpo, "idempotency_key"),
        _texto(corpo, "origem"),
        _texto(corpo, "ocorrido_em"),
        _inteiro(corpo, "publicado_em"),
    )


def validar_pedido_criado(corpo: dict[str, Any]) -> PedidoCriado:
    """Valida um corpo `PedidoCriado` v1 e devolve o evento tipado.

    Levanta `ContratoInvalido` com o motivo — a mensagem é o que vai para o
    log e para a DLQ, então ela precisa ser acionável por quem for tratar.
    """
    evento, versao, evento_id, chave, origem, ocorrido_em, publicado_em = (
        _envelope_comum(corpo)
    )

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
        evento_id=evento_id,
        idempotency_key=chave,
        origem=origem,
        ocorreu_em=ocorrido_em,
        publicado_em_ms=publicado_em,
        pedido_id=_inteiro(pedido, "id"),
        usuario_id=_inteiro(pedido, "usuario_id"),
        status=_texto(pedido, "status"),
        total=_decimal(pedido, "total"),
        itens=tuple(itens),
    )


def validar_pagamento_registrado(corpo: dict[str, Any]) -> PagamentoRegistrado:
    """Valida um corpo `PagamentoRegistrado` v1 e devolve o evento tipado."""
    evento, versao, evento_id, chave, origem, ocorrido_em, publicado_em = (
        _envelope_comum(corpo)
    )

    pagamento = _obrigatorio(corpo, "pagamento")
    if not isinstance(pagamento, dict):
        raise ContratoInvalido("campo 'pagamento' não é um objeto JSON")

    aprovado = _booleano(pagamento, "aprovado")
    motivo_recusa = _texto_opcional(pagamento, "motivo_recusa", "")

    # A recusa é um estado **inconsistente** do contrato, não apenas um texto
    # faltando: `aprovado: false` sem motivo não diz nada de acionável para quem
    # for notificar o cliente, e `aprovado: true` com motivo é um evento que
    # mente sobre o próprio desfecho.
    if not aprovado and not motivo_recusa:
        raise ContratoInvalido(
            "campo 'pagamento.motivo_recusa' é obrigatório quando 'aprovado' é false"
        )
    if aprovado and motivo_recusa:
        raise ContratoInvalido(
            "campo 'pagamento.motivo_recusa' não faz sentido com 'aprovado' true"
        )

    # `status` e `aprovado` precisam concordar. Publicar `status: "registrado"`
    # com `aprovado: true` é o tipo de contradição que passa pelo consumidor sem
    # erro e aparece depois no relatório como "aprovado, mas registrado para
    # sempre" — muito mais difícil de diagnosticar do que um payload recusado
    # aqui. O `registrado` é estado **local do produtor** (o evento ainda não
    # foi publicado), e o evento descreve o desfecho do gateway.
    status = _texto(pagamento, "status")
    esperado = "aprovado" if aprovado else "recusado"
    if status != esperado:
        raise ContratoInvalido(
            f"campo 'pagamento.status' ({status!r}) não confere com 'aprovado' "
            f"({aprovado}): o desfecho esperado é {esperado!r}"
        )

    return PagamentoRegistrado(
        evento=evento,
        versao=versao,
        evento_id=evento_id,
        idempotency_key=chave,
        origem=origem,
        ocorreu_em=ocorrido_em,
        publicado_em_ms=publicado_em,
        pagamento_id=_inteiro(pagamento, "id"),
        pedido_id=_inteiro(pagamento, "pedido_id"),
        usuario_id=_inteiro(pagamento, "usuario_id"),
        status=_texto(pagamento, "status"),
        metodo=_texto(pagamento, "metodo"),
        valor=_decimal(pagamento, "valor"),
        aprovado=aprovado,
        motivo_recusa=motivo_recusa,
        canal_notificacao=_texto_opcional(pagamento, "canal_notificacao", "email"),
    )


def validar(corpo: dict[str, Any]) -> Evento:
    """Despacha no validador correspondente ao `evento` do corpo.

    O consumidor chama **isto**, e não `validar_pedido_criado` /
    `validar_pagamento_registrado` diretamente: o roteamento por
    `corpo["evento"]` é o que faz o mesmo laço de consumo atender aos dois
    contratos sem que o `kafka_consumidor` precise de um `if` por tipo de evento
    em cada etapa.

    Um `evento` desconhecido é `ContratoInvalido` (terminal, DLQ): preferimos
    registrar que **não** sabemos o que é a mensagem a tentar adivinhá-la.
    """
    if not isinstance(corpo, dict):
        raise ContratoInvalido("corpo do evento não é um objeto JSON")

    evento = _texto(corpo, "evento")
    if evento == EVENTO_PEDIDO_CRIADO:
        return validar_pedido_criado(corpo)
    if evento == EVENTO_PAGAMENTO_REGISTRADO:
        return validar_pagamento_registrado(corpo)
    raise ContratoInvalido(f"evento '{evento}' não é suportado")