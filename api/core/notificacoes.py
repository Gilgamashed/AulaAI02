"""Composição do texto da notificação disparada pelo worker de pagamentos.

Existe como módulo separado porque o **texto é apresentação**, e o contrato
`PagamentoRegistrado` é dado. A distinção importa: o evento descreve o que
aconteceu no pagamento (status, método, valor, canal escolhido) e pode ser
consumido por quem quiser — um dashboard, um painel, outra notificação. O texto
que o cliente lê é uma das coisas que se faz *a partir* do evento, e ele muda
por decisão de produto (e não por mudança no que aconteceu no pagamento).

Se o texto viesse dentro do evento, qualquer segundo consumidor dependeria dele
para não ter de montar o seu: o contrato cresceria por causa de um consumidor, e
trocar a redação da notificação passaria a ser alteração de contrato — com o
versionamento de evento embutido, ou seja, mais caro do que merece.

O texto é derivado só de campos do evento (`status`, `aprovado`, `motivo_recusa`,
`valor`, `metodo`), então o worker produz a mesma notificação para o mesmo
evento independentemente de quando ele for processado — que é o que permite a
reentrega gerar duplicata sem divergir de conteúdo.
"""

from __future__ import annotations

from typing import Any

# Rótulos do método de pagamento. Um `choices` do model seria o lugar óbvio, mas
# o `metodo` do evento é a string crua do contrato e o `verbose_name` do model é
# HTML de admin ("Cartão de crédito"), que não serve para um SMS. Um mapa
# explícito aqui é o que mantém as duas coisas distintas sem duplicar dado.
ROTULOS_METODO = {
    "cartao_credito": "cartão de crédito",
    "pix": "PIX",
    "boleto": "boleto",
}


def titulo_e_mensagem(evento: Any) -> tuple[str, str]:
    """`(titulo, mensagem)` da notificação correspondente a um `PagamentoRegistrado`.

    Aceita o dataclass já validado (o que o worker recebe) e não o corpo bruto:
    quem chama já passou por `validar()`, então os campos abaixo são strings e
    `Decimal` garantidos, e formatá-los aqui não precisa repetir a validação.
    """
    metodo = ROTULOS_METODO.get(evento.metodo, evento.metodo)
    valor = f"{evento.valor:.2f}"

    if evento.aprovado:
        return (
            "Pagamento aprovado",
            f"Seu pagamento de R$ {valor} via {metodo} foi aprovado.",
        )
    return (
        "Pagamento recusado",
        (
            f"Seu pagamento de R$ {valor} via {metodo} foi recusado"
            + (f": {evento.motivo_recusa}" if evento.motivo_recusa else ".")
        ),
    )