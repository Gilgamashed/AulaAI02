"""Topologia Kafka da Aula 10: tópicos, partições, retenção e grupos.

Diagrama (setas = `produce` do produtor, do worker e do replayer):

    POST /pedidos
        │ produce em `pedidos.criados` com key = pedido_id
        v
   ┌────────────────────────────┐
   │ .partição 0   .1     .2   │   `KAFKA_PARTICOES` = 3
   │  pedidos.criados          │   `KAFKA_RETENCAO_MS` = 7 dias
   └─────┬──────────┬──────────┘
         │          │
         │  falha recuperável (1ª..3ª)
         v          v
   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
   │ pedidos.criados      │   │ pedidos.criados      │   │ pedidos.criados      │
   │   .retry.1 (5 s)     │──▶│   .retry.2 (15 s)    │──▶│   .retry.3 (45 s)    │
   └──────────────────────┘   └──────────────────────┘   └──────────────────────┘
         │                          │                          │
         │            o replayer só devolve para o tópico principal quando
         │            a idade da mensagem atinge o degrau (o Kafka NÃO tem TTL)
         └──────────────┬───────────┴───────────┬──────────────┘
                        v                       v
                 pedidos.criados          pedidos.criados.dlq
                                          (terminal: retida para inspeção,
                                           retenção longa, ninguém consome)

Cinco decisões que valem registro:

1. **Os nomes são os mesmos das filas AMQP** (`pedidos.criados`,
   `pedidos.criados.retry.N`, `pedidos.criados.dlq`). Tópico e fila não são a
   mesma coisa, mas para a comparação entre os dois brokers ser justa, as duas
   bases precisam descrever o mesmo desenho — e o `scripts/measure_messaging.py`
   reaproveita as mesmas constantes.

2. **A key da mensagem é o `pedido_id`.** O Kafka garante que duas mensagens
   com a mesma key vão para a mesma partição, na mesma ordem. Isso dá uma
   propriedade que o RabbitMQ também tem (ordem de entrega dentro de uma fila)
   e que vale preservar: eventos do mesmo pedido nunca são processados fora de
   ordem. E como as republicações de retry e de DLQ reaproveitam a mesma key,
   a ordem por pedido se mantém em todo o caminho.

3. **Partições são o eixo de paralelismo, e são fixas.** Um consumidor em grupo
   recebe partições, não filas: com `KAFKA_PARTICOES=3` o paralelismo máximo é
   3, e o quarto consumidor ficaria ocioso. O número de partições **não pode
   ser alterado depois** sem quebrar o mapeamento key → partição (a key do
   pedido 42 mudaria de partição e a ordem por pedido se perderia). Por isso a
   topologia é declarada pela aplicação e não pelo broker.

4. **`retention.ms` é a "retenção configurável" da spec, e é ela — não o
   consumidor — que garante o tempo de vida da mensagem.** O efeito colateral é
   o oposto do RabbitMQ: lá o TTL da fila de retry expirava e *devolvia* a
   mensagem (dead-letter); aqui a retenção **apaga** a mensagem se ninguém
   consumir até lá. Por isso cada tópico de retry recebe `degrau * 2 + folga`
   (ver `retencao_retry_ms`) — e o valor é impresso no log `TopicosDeclarados`,
   para quem lê o log saber o prazo que a aplicação se comprometeu a cumprir.

5. **`auto.create.topics.enable=false` no broker.** Quem cria os tópicos é esta
   aplicação, com partições e retenção explícitas. Se o broker criasse sozinho,
   viria com 1 partição e retenção padrão do servidor — exatamente o oposto do
   que a spec pede para demonstrar.

Aula 11 — o mesmo desenho, um segundo fluxo
--------------------------------------------
O diagrama acima é o do fluxo de **pedidos**. A Aula 11 acrescenta o fluxo de
**pagamentos**, e ele é uma cópia exata do desenho com outro nome:

    POST /pedidos/{id}/pagamento
        │ produce em `pagamentos.registrados` com key = pedido_id
        v
   ┌────────────────────────────┐
   │ .partição 0   .1     .2   │   `KAFKA_PARTICOES_PAGAMENTOS` = 3
   │  pagamentos.registrados    │   `KAFKA_RETENCAO_MS` = 7 dias
   └─────┬──────────┬──────────┘
         │  .retry.1 (5 s) ─▶ .retry.2 (15 s) ─▶ .retry.3 (45 s)
         └──────────────┬───────────┬───────────┬──────────────┘
                v                   v                   v
         pagamentos.registrados  (idem)          pagamentos.registrados.dlq
                            + worker-pagamentos: cria a `Notificacao`

Por que **tópico separado** e não mais um `evento` dentro de
`pedidos.criados`: cada fluxo tem seu worker (`worker-kafka` e
`worker-pagamentos`), e consumidores no mesmo `group.id` disputam partições em
vez de dividir trabalho. Tópicos separados dão offset, DLQ e escala por fluxo —
e é o que permite subir 3 workers de pagamento sem tocar nos 3 de pedidos.

O que **não** foi duplicado: a escada (5/15/45 s), o `max_reentregas`, a
retenção e a política de headers vivem em funções que recebem o `topico` da
instância. `nomes_retry("pagamentos.registrados")` produz a escada do segundo
fluxo com a mesma função do primeiro — é o motivo de o módulo ter parado de
ler `settings.KAFKA_TOPICO_PEDIDOS` diretamente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

logger = logging.getLogger("core.messaging")

# Cabeçalhos Kafka usados pela política de reentrega. São os MESMOS nomes do
# AMQP (`topologia.HEADER_TENTATIVA` etc.) de propósito: a tabela de
# equivalência broker × broker fica trivial de conferir, e o contrato escrito
# (`docs/contracts/pedido_criado.md`) descreve um evento, não um transporte.
HEADER_TENTATIVA = "x-tentativa"
HEADER_EVENTO_ID = "x-evento-id"
HEADER_MOTIVO = "x-motivo"

# A retenção de um tópico de retry precisa ser MAIOR que o backoff do degrau,
# porque no Kafka a expiração da retenção **apaga** a mensagem em vez de
# devolvê-la. `retencao_retry_ms` dobra o degrau e soma
# `KAFKA_FOLGA_RETENCAO_RETRY_MS` (10 min) para aguentar o replayer parado.
# A folga é setting e não constante: mudar a tolerância a um replayer reiniciado
# é decisão de ambiente, não de código.


def nomes_retry(topico_base: str | None = None) -> list[tuple[int, str]]:
    """Lista `(degrau, tópico)` de retry, na ordem da escada.

    Deriva de `PEDIDO_BACKOFF_SEGUNDOS` — a mesma fonte da versão AMQP —, então
    mudar a variável de ambiente muda quantos degraus existem nos dois brokers,
    sem constante "mágica" escondida.

    O `topico_base` é o que dá ao segundo fluxo (Aula 11) a escada dele sem
    nenhuma constante nova: `pagamentos.registrados` produz
    `pagamentos.registrados.retry.1..3` pela mesma regra que produz
    `pedidos.criados.retry.1..3`. O **número de degraus e o atraso** são
    deliberadamente os mesmos nos dois fluxos — os dois precisam do mesmo
    comportamento, e duas escadas configuráveis separadamente seriam duas
    chances de errar. Só o prefixo muda. O default mantém
    `nomes_retry()` sem argumento equivalente ao que era antes da Aula 11.
    """
    base = topico_base or settings.KAFKA_TOPICO_PEDIDOS
    return [
        (indice + 1, f"{base}.retry.{indice + 1}")
        for indice in range(len(settings.PEDIDO_BACKOFF_SEGUNDOS))
    ]


def segundos_do_degrau(degrau: int) -> int:
    """Atraso (s) do degrau informado (1-based) da escada de reentrega."""
    return settings.PEDIDO_BACKOFF_SEGUNDOS[degrau - 1]


def retencao_retry_ms(degrau: int) -> int:
    """`retention.ms` do tópico de retry do degrau informado."""
    return segundos_do_degrau(degrau) * 2 * 1000 + settings.KAFKA_FOLGA_RETENCAO_RETRY_MS


@dataclass(frozen=True)
class TopologiaKafka:
    """Nomes e parâmetros resolvidos da topologia de UM fluxo (lidos das settings).

    A Aula 11 introduziu o segundo fluxo (`pagamentos.registrados`), então esta
    classe deixou de ser "a topologia" e passou a ser "a topologia de um fluxo".
    É por isso que existem `de_pedidos()` e `de_pagamentos()` em vez de um único
    `do_ambiente()` que embute o nome do tópico: nome, DLQ e grupo do consumidor
    passam a ser **parâmetros da instância**, e o resto do código (produtor,
    consumidor, replayer, admin) deixa de ter `if fluxo == "pagamentos"`
    espalhado — ele pergunta à instância.
    """

    fluxo: str
    topico: str
    topico_dlq: str
    grupo: str
    grupo_replay: str
    particoes: int
    retencao_ms: int
    retencao_dlq_ms: int

    @classmethod
    def de_pedidos(cls) -> TopologiaKafka:
        """Topologia do fluxo de pedidos (`PedidoCriado`) — o das Aulas 9/10."""
        return cls(
            fluxo="pedidos",
            topico=settings.KAFKA_TOPICO_PEDIDOS,
            topico_dlq=settings.KAFKA_TOPICO_DLQ,
            grupo=settings.KAFKA_GRUPO_CONSUMIDORES,
            grupo_replay=settings.KAFKA_GRUPO_REPLAY,
            particoes=settings.KAFKA_PARTICOES,
            retencao_ms=settings.KAFKA_RETENCAO_MS,
            retencao_dlq_ms=settings.KAFKA_RETENCAO_DLQ_MS,
        )

    @classmethod
    def de_pagamentos(cls) -> TopologiaKafka:
        """Topologia do fluxo de pagamentos (`PagamentoRegistrado`) — Aula 11.

        Só as quatro primeiras linhas diferem das de `de_pedidos`. `particoes` e
        as retenções vêm das mesmas settings do fluxo de pedidos: o eixo de
        paralelismo e o tempo de vida do evento são as mesmas decisões, e quem
        quiser mudar para o fluxo de pagamento tem
        `KAFKA_PARTICOES_PAGAMENTOS` à mão.
        """
        return cls(
            fluxo="pagamentos",
            topico=settings.KAFKA_TOPICO_PAGAMENTOS,
            topico_dlq=settings.KAFKA_TOPICO_PAGAMENTOS_DLQ,
            grupo=settings.KAFKA_GRUPO_PAGAMENTOS,
            grupo_replay=settings.KAFKA_GRUPO_PAGAMENTOS_REPLAY,
            particoes=settings.KAFKA_PARTICOES_PAGAMENTOS,
            retencao_ms=settings.KAFKA_RETENCAO_MS,
            retencao_dlq_ms=settings.KAFKA_RETENCAO_DLQ_MS,
        )

    @classmethod
    def do_fluxo(cls, fluxo: str) -> TopologiaKafka:
        """Resolve a topologia pelo nome do fluxo.

        Ponto único de tradução entre o nome que aparece no `--fluxo` do
        management command e o objeto que o resto do código usa — é o que
        permite ao comando não conhecer nenhuma das settings de nome de tópico.
        """
        if fluxo == "pedidos":
            return cls.de_pedidos()
        if fluxo == "pagamentos":
            return cls.de_pagamentos()
        raise ValueError(
            f"fluxo '{fluxo}' desconhecido; esperado 'pedidos' ou 'pagamentos'"
        )

    @classmethod
    def do_ambiente(cls) -> TopologiaKafka:
        """Alias de `de_pedidos()`, preservado por compatibilidade.

        `broker.resumo()`, `kafka_admin.purgar/resetar_offsets` e o `Replayer`
        chamavam `do_ambiente()` antes de existir um segundo fluxo, e o que eles
        querem é o fluxo **principal**. Manter o nome evita espalhar um
        `de_pedidos()` por um código que não tem por que se comprometer com a
        existência do segundo fluxo.
        """
        return cls.de_pedidos()

    @classmethod
    def todas(cls) -> list[TopologiaKafka]:
        """Topologias de **todos** os fluxos declarados.

        Usada pelo startup (quem sobe primeiro declara tudo), pelo `declarar_
        topicos_kafka` e pelo `/health`, para que nenhum desses três tenha que
        lembrar de acrescentar o fluxo novo à mão — o esquecimento seria
        silencioso, e o sintoma (tópico que não existe quando alguém publica)
        aparece bem depois, na aula seguinte, na hora errada.

        A lista vem de `broker.FLUXOS` para que o nome do fluxo tenha uma
        única fonte de verdade no pacote.
        """
        # Import local: `broker` importa `kafka_topologia` no topo (via
        # `broker_ativo`), e um import aqui no módulo criaria o ciclo.
        from .broker import FLUXOS

        return [cls.do_fluxo(fluxo) for fluxo in FLUXOS]

    def topico_retry(self, degrau: int) -> str:
        return f"{self.topico}.retry.{degrau}"

    def topicos_retry(self) -> list[str]:
        return [topico for _, topico in nomes_retry(self.topico)]

    def degrau_do_topico(self, topico: str) -> int | None:
        """Descobre o degrau a partir do nome do tópico (usado pelo replayer).

        `None` quando o tópico não é de retry, que é o que permite ao replayer
        tratar "nome desconhecido" como erro explícito em vez de tentar adivinhar
        um backoff.
        """
        prefixo = f"{self.topico}.retry."
        if not topico.startswith(prefixo):
            return None
        try:
            return int(topico[len(prefixo) :])
        except ValueError:
            return None

    def resumo(self) -> dict[str, Any]:
        """Dicionário serializável da topologia (entra no log de startup)."""
        return {
            "broker": "kafka",
            "fluxo": self.fluxo,
            "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "topico": self.topico,
            "particoes": self.particoes,
            "retencao_ms": self.retencao_ms,
            "grupo": self.grupo,
            "topico_dlq": self.topico_dlq,
            "retencao_dlq_ms": self.retencao_dlq_ms,
            "grupo_replay": self.grupo_replay,
            "auto_offset_reset": settings.KAFKA_AUTO_OFFSET_RESET,
            "topicos_retry": [
                {
                    "degrau": degrau,
                    "topico": topico,
                    "backoff_s": segundos_do_degrau(degrau),
                    "retencao_ms": retencao_retry_ms(degrau),
                }
                for degrau, topico in nomes_retry(self.topico)
            ],
            "max_reentregas": settings.PEDIDO_MAX_REENTREGAS,
        }


# =====================================================================
# Configuração do cliente (librdkafka)
# =====================================================================


def _base() -> dict[str, Any]:
    """Config comum a produtor e consumidor.

    `client.id` aparece no `kafka-consumer-groups.sh --describe` e no log do
    broker: sem ele, um bug de produção vira "uma aplicação desconhecida está
    consumindo" — e não dá para saber se é o produtor da API ou o worker.
    """
    return {
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "client.id": settings.KAFKA_CLIENT_ID,
        # Tempo máximo para o cliente relistar os tópicos do cluster: sem ele,
        # uma queda de broker deixa a publicação pendurada até o `flush`.
        "socket.timeout.ms": 5000,
    }


def config_produtor(client_id: str | None = None) -> dict[str, Any]:
    """Config do `Producer` — o equivalente ao *publisher confirm* do AMQP.

    | opção                        | por que                                              |
    | ---------------------------- | ---------------------------------------------------- |
    | `acks=all`                   | o líder espera as réplicas: nenhum `acks=1` perdido   |
    | `enable.idempotence=true`    | o broker descarta retentativas do próprio produtor   |
    | `retries` (implícito)        | com idempotência, o librdkafka retenta indefinidamente |
    | `linger.ms`                  | agrupa envios de janelas curtíssimas em um round-trip |
    | `delivery.timeout.ms`        | teto de espera pelo `acks=all`; estourado vira erro  |

    `enable.idempotence` e a diferença mais relevante para a idempotência: no
    RabbitMQ o produtor não tinha proteção alguma contra reenvio (a proteção
    era do consumidor, via `dedupe`); aqui o próprio produtor ganha um número
    de sequência que o broker usa para descartar cópias. Isso é **complementar**
    às duas barreiras já existentes (janela Redis e `UPDATE` condicional), não
    substituto: ele cobre o salto entre "enviei" e "o broker gravou", e nada
    sobre o salto entre "gravei" e "processei".
    """
    config = _base()
    config.update(
        {
            "client.id": client_id or config["client.id"],
            "acks": settings.KAFKA_ACKS,
            "enable.idempotence": True,
            "linger.ms": settings.KAFKA_LINGER_MS,
            "delivery.timeout.ms": settings.KAFKA_TIMEOUT_ENVIO_MS,
            "compression.type": settings.KAFKA_COMPRESSAO,
        }
    )
    return config


def config_consumidor(grupo: str, client_id: str) -> dict[str, Any]:
    """Config do `Consumer` — o equivalente ao `auto_ack=False` do AMQP.

    `enable.auto.commit=false` é a linha mais importante do arquivo: com ela
    ligada, o broker avança o offset por conta própria e uma queda entre o
    efeito no banco e o commit perde o efeito silenciosamente. Desligada, quem
    decide quando o offset avança é o `kafka_consumidor`, e ele só avança
    **depois** do efeito — a mesma promessa do `basic_ack` por último.

    `partition.assignment.strategy=cooperative-sticky` evita o *stop-the-world*
    do protocolo eager: ao subir o terceiro worker, as partições já atribuídas
    não são revogadas e reatribuídas todas, o que importa justamente no cenário
    que a spec pede medir (escalonar consumidores).
    """
    config = _base()
    config.update(
        {
            "client.id": client_id,
            "group.id": grupo,
            "enable.auto.commit": False,
            # O offset só é storeado quando chamamos `commit`/`store_offsets`;
            # sem isso, o librdkafka armazena o offset do `poll()` e a
            # confirmação viraria decorativa.
            "enable.auto.offset.store": False,
            "auto.offset.reset": settings.KAFKA_AUTO_OFFSET_RESET,
            "partition.assignment.strategy": "cooperative-sticky",
            # Folga enorme de propósito: o processamento leva ~13 ms e não há
            # espera bloqueante neste consumidor (o atraso fica nos tópicos de
            # retry, fora daqui). Se um dia alguém colocar `sleep` no laço,
            # este número é o que impede o consumer de ser expulso do grupo.
            "max.poll.interval.ms": 300_000,
            "session.timeout.ms": 30_000,
        }
    )
    return config


def topico_desconhecido(erro: Any) -> bool:
    """True quando o erro é `UNKNOWN_TOPIC_OR_PART` (tópico ainda não visível).

    Fica aqui, e não em `kafka_consumidor`, porque **dois** componentes
    precisam da mesma resposta a esse erro: o consumidor do tópico principal e o
    replayer dos de retry. Ambos assinam antes de o metadata do cliente refletir
    os tópicos recém-criados, e ambos recebem `UNKNOWN_TOPIC_OR_PART` uma vez,
    logo no startup.

    O `confluent_kafka` é importado sob demanda pelo mesmo motivo do resto do
    módulo: `kafka_topologia` precisa continuar importável (e testável) sem a
    biblioteca do Kafka instalada.
    """
    try:
        from confluent_kafka import KafkaError

        codigo = erro.code() if hasattr(erro, "code") else erro.errno()
    except Exception:  # noqa: BLE001 - não é um KafkaError
        return False
    return codigo == KafkaError.UNKNOWN_TOPIC_OR_PART


def topicos_declarados(topologia: TopologiaKafka) -> list[dict[str, Any]]:
    """Declaração desejada de cada tópico DE UM FLUXO (usada por `criar_topicos`).

    `replicas` vem da setting porque em cluster real `KAFKA_REPLICAS=1` seria
    ponto único de falha; com o broker único do compose, 1 é a única coisa que
    funciona.

    Os tópicos de retry saem de `topologia.topicos_retry()` (e não da função de
    módulo `nomes_retry()` sem argumento) porque é o tópico **da instância** que
    gera o prefixo — é isso que declara `pagamentos.registrados.retry.1` quando a
    instância é a do fluxo de pagamentos.
    """
    declaracao: list[dict[str, Any]] = [
        {
            "nome": topologia.topico,
            "particoes": topologia.particoes,
            "replicas": settings.KAFKA_REPLICAS,
            "config": {
                # `cleanup.policy=delete`: o tópico principal guarda a retenção
                # para poder ser reproduzido (é o "stream" da spec), não para
                # acumular para sempre.
                "retention.ms": topologia.retencao_ms,
                "cleanup.policy": "delete",
            },
        },
        {
            "nome": topologia.topico_dlq,
            "particoes": 1,
            "replicas": settings.KAFKA_REPLICAS,
            "config": {
                # Terminal: retida bem mais tempo que o fluxo normal, porque é a
                # única cópia do evento que deu problema. `7d` no resto do
                # sistema, `30d` na DLQ.
                "retention.ms": topologia.retencao_dlq_ms,
                "cleanup.policy": "delete",
            },
        },
    ]
    for degrau, topico in nomes_retry(topologia.topico):
        declaracao.append(
            {
                "nome": topico,
                "particoes": 1,
                "replicas": settings.KAFKA_REPLICAS,
                "config": {
                    "retention.ms": retencao_retry_ms(degrau),
                    "cleanup.policy": "delete",
                },
            }
        )
    return declaracao