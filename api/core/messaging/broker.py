"""Seletor de broker: decide **qual transporte** publica e consome o evento.

A Aula 9 implementou o fluxo em RabbitMQ (AMQP 0-9-1) e a Aula 10 em Apache
Kafka. Os dois transports ficam no repositório e o escolha é feita por **uma
variável de ambiente** (`MENSAGERIA_BROKER`), o que faz três coisas de uma vez:

1. mantém o RabbitMQ intacto e reproduzível (--profile rabbitmq no compose);
2. deixa a escolha auditável num único lugar — o `GET /health` e o log
   `WorkerIniciado` dizem qual broker está ativo;
3. permite medir os dois **na mesma máquina e na mesma sessão**, que é a única
   forma de comparação que vale (ver README, "Por que os números foram medidos
   de novo, em pares").

Por que a seleção é por ambiente e não um parâmetro do `POST /pedidos`: o
broker é uma decisão de *infraestrutura*, não de requisição. Um cliente não
deveria poder escolher por onde o evento de negócio vai sair — no máximo o
*ambiente* escolhe, e o ambiente é o mesmo para o produtor e para o consumidor.

Os **imports são preguiçosos** (dentro das funções, não no topo do módulo) por
uma razão prática: `confluent_kafka` só é necessário quando o broker ativo é
Kafka. Com o RabbitMQ como broker, o código roda mesmo em um ambiente onde a
dependência do Kafka não está instalada — o que é exatamente o caso de um
`manage.py` local usado só para `republicar_pedidos`.

**`kafka` é o padrão.** A Aula 10 substituiu o RabbitMQ como broker do projeto,
mas o transporte da Aula 9 continua aqui, funcional e reproduzível
(`docker compose --profile rabbitmq up -d`), para a comparação entre os dois.
É por isso que o `BROKER_PADRAO` abaixo é `KAFKA` e não `RABBITMQ`: sem a
variável de ambiente — ou com um valor inválido — o projeto sobe no broker da
aula corrente.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger("core.messaging")

RABBITMQ = "rabbitmq"
KAFKA = "kafka"
BROKERS = (KAFKA, RABBITMQ)
# Broker usado quando `MENSAGERIA_BROKER` está ausente ou não é reconhecido.
BROKER_PADRAO = KAFKA

# Nomes dos fluxos de evento. São as mesmas strings que `TopologiaKafka.fluxo`
# devolve, e a lista é a autoridade para o `--fluxo` do management command: um
# fluxo novo precisa entrar aqui para ser selecionável.
FLUXO_PEDIDOS = "pedidos"
FLUXO_PAGAMENTOS = "pagamentos"
FLUXOS = (FLUXO_PEDIDOS, FLUXO_PAGAMENTOS)


class PublicacaoFalhou(Exception):
    """O evento não pôde ser publicado (broker fora, topologia, timeout).

    Exceção **independente do transporte** e definida aqui por isso: mora neste
    módulo, e não em `produtor.py`, para que a view e o comando
    `republicar_pedidos` capturem o mesmo tipo venha o evento do RabbitMQ ou do
    Kafka. `produtor.py` reexporta este mesmo nome, então
    `produtor.PublicacaoFalhou` continua válido.

    Levanta para a view responder **503** e manter o pedido em
    `pendente_publicacao`. A alternativa — responder 201 e tentar publicar
    depois — é o outbox pattern, que exige mais uma tabela e um processo
    agendador: fora do escopo desta aula.
    """


def broker_ativo() -> str:
    """Broker configurado, validado contra a lista de transportes suportados.

    Um valor desconhecido **cai para o padrão da aula corrente (Kafka)** e vira
    log de aviso em vez de `KeyError` no meio do POST: subir a API com uma
    variável digitada errado não pode custar o serviço inteiro, e a linha de
    aviso diz exatamente o que aconteceu. Ainda assim, o `GET /health` expõe o
    valor bruto para o erro ficar visível de fora também (ver `views.health`).
    """
    bruto = str(getattr(settings, "MENSAGERIA_BROKER", BROKER_PADRAO)).strip().lower()
    if bruto in BROKERS:
        return bruto
    logger.warning(
        "MENSAGERIA_BROKER desconhecido; usando o padrão",
        extra={
            "evento": "BrokerDesconhecido",
            "resultado": "erro",
            "broker": bruto,
            "detalhe": f"valor aceito: {', '.join(BROKERS)}; usando '{BROKER_PADRAO}'",
        },
    )
    return BROKER_PADRAO


def publicar_pedido_criado(pedido: Any, idempotency_key: str) -> dict[str, Any]:
    """Publica o `PedidoCriado` no broker ativo e devolve os dados da publicação.

    A assinatura e o retorno são os mesmos para os dois transportes — é o que
    permite à view não saber qual é. O corpo do retorno também mantém os mesmos
    campos (`evento_id`, `fila`, `duracao_ms`, `publicado_em`), acrescidos de
    `broker` e, no Kafka, de `particao`/`offset`: as chaves `fila` e `duracao_ms`
    já são lidas pelo `scripts/measure_messaging.py` e pelos logs, então mantê-las
    é o que permite comparar as duas métricas sem tocar no instrumento de
    medição.
    """
    if broker_ativo() == KAFKA:
        from . import kafka_produtor

        return kafka_produtor.publicar_pedido_criado(pedido, idempotency_key)

    from . import produtor

    return produtor.publicar_pedido_criado(pedido, idempotency_key)


def publicar_pagamento_registrado(pagamento: Any) -> dict[str, Any]:
    """Publica o `PagamentoRegistrado` (Aula 11).

    **Só existe no Kafka**, e a falta de suporte no AMQP é explícita: com
    `MENSAGERIA_BROKER=rabbitmq` esta função levanta `PublicacaoFalhou` com uma
    mensagem que diz o que fazer, em vez de tentar um `AttributeError` numa
    implementação AMQP que ninguém escreveu.

    A alternativa — implementar também no RabbitMQ — foi descartada de
    propósito nesta aula: duplicaria topologia, produtor, consumidor, replayer e
    DLQ do segundo fluxo numa base de código que a Aula 9 já documentou como
    superada pelo Kafka, e nada na spec exige os dois. O RabbitMQ da Aula 9
    continua integralmente funcionando para o `PedidoCriado`. Se um dia o fluxo
    de pagamento precisar rodar em AMQP, é uma `Topologia` nova
    (`pagamentos.registrados` + `.retry.N` + `.dlq`) mais este ramo — o contrato,
    a janela de dedupe e o efeito no banco são os mesmos, e não precisam ser
    reescritos.
    """
    if broker_ativo() != KAFKA:
        raise PublicacaoFalhou(
            "o fluxo de pagamento só está implementado no Kafka: com "
            "MENSAGERIA_BROKER=rabbitmq não há tópico de "
            "'pagamentos.registrados'. Suba com MENSAGERIA_BROKER=kafka para "
            "usar o POST /api/v1/pedidos/{id}/pagamento/."
        )
    from . import kafka_produtor

    return kafka_produtor.publicar_pagamento_registrado(pagamento)


def criar_consumidor(
    destino: str | None = None,
    max_mensagens: int | None = None,
    *,
    fluxo: str = FLUXO_PEDIDOS,
) -> Any:
    """Instancia o consumidor do broker ativo.

    `fluxo` decide **qual** stream o worker atende (`pedidos` na Aula 9/10,
    `pagamentos` na Aula 11) e é ignorado no RabbitMQ — lá só existe o fluxo de
    pedidos, e fingir o contrário exigiria implementar uma topologia AMQP do
    segundo fluxo. A assimetria fica explícita no `help` do comando, em vez de
    fingir que os dois brokers têm a mesma topologia.

    `destino` faz sentido no RabbitMQ (`--fila`, usada para reprocessar a
    DLQ em ambiente de teste). No Kafka ele também é respeitado, mas apenas
    como **tópico**: um fluxo já determina tópico, retries e DLQ, então passar
    `destino` aqui é o jeito de apontar o consumidor para um tópico específico
    (é o que o replayer faz). O que não faz sentido no Kafka é `--fila`, e o
    erro de fluxo incompatível é explícito logo abaixo.
    """
    if broker_ativo() == KAFKA:
        from .kafka_consumidor import ConsumidorKafka

        return ConsumidorKafka(
            topico=destino, max_mensagens=max_mensagens, fluxo=fluxo
        )

    if fluxo != FLUXO_PEDIDOS:
        raise PublicacaoFalhou(
            f"o fluxo '{fluxo}' só está implementado no Kafka; com "
            "MENSAGERIA_BROKER=rabbitmq só existe o fluxo 'pedidos'."
        )

    from .consumidor import Consumidor

    return Consumidor(fila=destino, max_mensagens=max_mensagens)


def resumo() -> dict[str, Any]:
    """Descrição do broker ativo, para `/health` e para o log de startup.

    O formato do fluxo **principal** continua no primeiro nível (as chaves
    `topico`, `grupo`, `topicos_retry` etc. não mudaram de lugar), e o segundo
    fluxo da Aula 11 entra na chave `fluxos`. Assim o `/health`, o
    `measure_messaging.py` e o `TopicosDeclarados` continuam lendo as mesmas
    chaves de antes, e quem quiser o fluxo de pagamento pergunta por ele.
    """
    broker = broker_ativo()
    if broker == KAFKA:
        from .kafka_topologia import TopologiaKafka

        principal = TopologiaKafka.de_pedidos()
        fluxos = {fluxo: TopologiaKafka.do_fluxo(fluxo).resumo() for fluxo in FLUXOS}
        return {
            "broker": broker,
            **principal.resumo(),
            # Inclui o fluxo principal de novo (é `fluxos['pedidos']`). A
            # duplicação é deliberada: quem lê as chaves de topo continua
            # funcionando, e quem pergunta por um fluxo pelo nome tem os dois.
            "fluxos": fluxos,
        }
    from . import topologia

    return {"broker": broker, **topologia.Topologia.do_ambiente().resumo()}