"""Produtor **Kafka**: publica `PedidoCriado` e `PagamentoRegistrado` (Aulas 10 e 11).

Equivalente Kafka de `produtor.py` (AMQP). Quatro garantias importam aqui:

1. **`acks=all` + `enable.idempotence=true`**, com o relatório de entrega
   (*delivery report*) verificado antes de responder. É o equivalente ao
   *publisher confirm* do RabbitMQ: `produce()` sozinho só enfileira no cliente,
   e quem garante a gravação durável em todas as réplicas é o ACK do broker. O
   POST só vira 201 depois do ACK — publicar e responder 201 antes seria um
   pedido fantasma.

2. **`enable.idempotence` (produtor idempotente).** O librdkafka anexa um número
   de sequência a cada mensagem e o broker descarta cópias repetidas do mesmo
   produtor. Cobre a janela "enviei, mas o ACK não chegou" — o caso clássico em
   que um retry do cliente duplica o evento. Note que isto **não** substitui a
   idempotência de negócio: ele garante efeito único *na publicação*, e o
   efeito no banco continua protegido pela janela do Redis e pelo `UPDATE`
   condicional.

3. **Uma conexão para o processo inteiro, não uma por publicação.** O
   `Producer` do librdkafka é thread-safe e mantém o buffer de envio, então a
   conexão é criada uma vez e reaproveitada por todas as threads do gunicorn.
   Isso não é otimização: é a correção direta do gargalo medido na Aula 10
   (RabbitMQ), onde cada POST abria uma conexão AMQP nova e redeclaria a
   topologia inteira — 29,8 ms de mediana de `duracao_ms` por publicação, com o
   limite do pipeline inteiro (≈11 POST/s) nesse caminho.

4. **Um `publicar` genérico, duaselines de log.** A Aula 11 publicou um segundo
   evento (`PagamentoRegistrado`) em um segundo tópico. O caminho de transporte
   é idêntico, então ele vive em `publicar()`; o que muda entre as duas
   publicações é só o contrato montado, a `TopologiaKafka` e o nome do log
   (`PedidoPublicado`/`PagamentoPublicado`).

O `key` da mensagem é o **`pedido_id`** nos dois eventos, e isso é uma escolha
compartilhada: é o `key` que garante que eventos do mesmo pedido caiam na mesma
partição, na mesma ordem (ver `kafka_topologia`). No pagamento isso importa
ainda mais — assim o `PedidoCriado` e o `PagamentoRegistrado` do pedido 42 nunca
são lidos fora de ordem, mesmo com as partições repartidas entre workers.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from django.conf import settings

from .. import models
from . import contracts, kafka_admin
from .broker import PublicacaoFalhou
from .erros import descrever
from .kafka_topologia import (
    HEADER_EVENTO_ID,
    HEADER_MOTIVO,
    HEADER_TENTATIVA,
    TopologiaKafka,
    config_produtor,
)

logger = logging.getLogger("core.messaging")

# `Producer` do librdkafka é thread-safe, mas a *construção* não é (ela registra
# callbacks e abre socket). O lock garante que duas threads do gunicorn não
# construam dois produtores em paralelo no primeiro POST.
_produtores: dict[str, Any] = {}
_trava = threading.Lock()


def _produtor(client_id: str) -> Any:
    """Producer singleton por processo (um por `client.id`).

    Por processo e não global compartilhado: o processo da API e o processo do
    worker são processos distintos, cada um com seu próprio cache. Criar a cada
    publicação perderia justamente o ganho de pool que motivou o módulo.
    """
    with _trava:
        existente = _produtores.get(client_id)
        if existente is not None:
            return existente
        from confluent_kafka import Producer

        novo = Producer(config_produtor(client_id))
        _produtores[client_id] = novo
        logger.info(
            "produtor kafka criado",
            extra={
                "evento": "ProdutorCriado",
                "resultado": "ok",
                "broker": "kafka",
                "detalhe": {
                    "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                    "acks": settings.KAFKA_ACKS,
                    "linger_ms": settings.KAFKA_LINGER_MS,
                    "idempotence": True,
                },
            },
        )
        return novo


def _entregar(
    produtor: Any,
    topico: str,
    valor: bytes,
    chave: str | None,
    cabecalhos: list[tuple[str, str]],
) -> Any:
    """Produz e espera o ACK do broker. Devolve o `delivery report`.

    O `flush(timeout)` é o que transforma "enfileirei" em "o broker confirmou":
    sem ele, o `produce()` só deposita no buffer de envio local. O callback
    guarda o erro do relatório — quando `err` não é `None`, a mensagem **não**
    foi gravada, e o contrato do POST exige 503 nesse caso.
    """
    relatorio: dict[str, Any] = {}

    def _ao_entregar(erro, mensagem) -> None:
        relatorio["erro"] = erro
        relatorio["particao"] = mensagem.partition() if mensagem is not None else None
        relatorio["offset"] = mensagem.offset() if mensagem is not None else None

    produtor.produce(
        topic=topico,
        value=valor,
        key=chave.encode("utf-8") if chave else None,
        headers=cabecalhos,
        on_delivery=_ao_entregar,
    )
    restante = produtor.flush(settings.KAFKA_TIMEOUT_ENVIO_S)
    if relatorio.get("erro") is not None:
        raise PublicacaoFalhou(
            f"broker não confirmou a publicação em {topico}: "
            f"{relatorio['erro']}"
        )
    if restante:
        raise PublicacaoFalhou(
            f"{restante} mensagem(ns) sem ACK em {topico} após "
            f"{settings.KAFKA_TIMEOUT_ENVIO_S}s"
        )
    return relatorio


def publicar(
    topologia: TopologiaKafka,
    corpo: dict[str, Any],
    *,
    chave: str,
    client_id: str,
) -> dict[str, Any]:
    """Produce um corpo já montado e espera o ACK. Devolve as coordenadas.

    É o caminho comum aos dois eventos (`PedidoCriado` e `PagamentoRegistrado`):
    declarar a topologia, obter o produtor do processo, produzir com
    `acks=all` + `enable.idempotence` e **esperar o relatório de entrega**. A
    separação existe porque o que muda entre os eventos não é o transporte — é o
    contrato (quem monta o corpo), a topologia (qual `group.id`) e o nome do
    log. Colocar essas três coisas num único função "publicar pedido" obrigaria
    a duplicar o bloco do `try/except` para o segundo evento, e é justamente
    bloco de `try/except` que não deve ser copiado.

    O corpo é montado **antes** de falar com o broker (por quem chama): se a
    serialização falhar, é um bug do contrato e não uma indisponibilidade, e a
    mensagem de erro precisa dizer isso.
    """
    dados = contracts.serializar(corpo)
    inicio = time.perf_counter()
    try:
        # Idempotente: quem subir primeiro (API ou worker) cria os tópicos. Cada
        # produtor declara só a topologia do SEU fluxo — são tópicos e grupos
        # independentes, e declarar o outro aqui criaria dependência entre
        # workers que não existe.
        kafka_admin.criar_topicos(topologia)
        produtor = _produtor(client_id)
        relatorio = _entregar(
            produtor,
            topologia.topico,
            dados,
            chave=chave,
            cabecalhos=[
                (HEADER_TENTATIVA, "0"),
                (HEADER_EVENTO_ID, corpo["evento_id"]),
            ],
        )
    except PublicacaoFalhou:
        raise
    except Exception as erro:
        # Mesmo tratamento do AMQP: erro de socket/DNS precisa virar 503 com o
        # registro mantido em `pendente_*`, e não 500. `KafkaException` e
        # `OSError` não compartilham nenhuma classe base, daí o `Exception`.
        raise PublicacaoFalhou(f"publicação falhou: {erro}") from erro
    return {
        "particao": relatorio.get("particao"),
        "offset": relatorio.get("offset"),
        "duracao_ms": round((time.perf_counter() - inicio) * 1000, 3),
    }


def _log_publicado(
    topologia: TopologiaKafka,
    corpo: dict[str, Any],
    pedido_id: int,
    relatorio: dict[str, Any],
    *,
    evento_log: str,
    pagamento_id: int | None = None,
    extras: dict[str, Any] | None = None,
) -> None:
    """Linha de log `*Publicado`, idêntica na forma para os dois eventos.

    Um único formato é o que permite `docker compose logs | grep Publicado`
    mostrar as duas publicações sem precisar saber de qual fluxo veio — e o que
    faz um `PagamentoRegistrado` aparecer na mesma tabela de evidência que o
    `PedidoCriado` das Aulas 9/10.
    """
    extra: dict[str, Any] = {
        "evento": evento_log,
        "resultado": "ok",
        "broker": "kafka",
        "fluxo": topologia.fluxo,
        "evento_id": corpo["evento_id"],
        "chave_idempotencia": corpo["idempotency_key"],
        "pedido_id": pedido_id,
        "topico": topologia.topico,
        "particao": relatorio.get("particao"),
        "offset": relatorio.get("offset"),
        "duracao_ms": relatorio.get("duracao_ms"),
        "tentativa": 0,
    }
    if pagamento_id is not None:
        extra["pagamento_id"] = pagamento_id
    if extras:
        extra.update(extras)
    logger.info("evento publicado", extra=extra)


def publicar_pedido_criado(pedido: models.Pedido, idempotency_key: str) -> dict[str, Any]:
    """Publica o `PedidoCriado` e devolve os dados de publicação.

    Levanta `PublicacaoFalhou` em qualquer erro do broker; a view responde 503 e
    o pedido fica em `pendente_publicacao`.
    """
    corpo = contracts.construir_pedido_criado(pedido, idempotency_key)
    topologia = TopologiaKafka.de_pedidos()

    inicio = time.perf_counter()
    try:
        relatorio = publicar(
            topologia, corpo, chave=str(pedido.pk), client_id="synapseshop-api-produtor"
        )
    except PublicacaoFalhou as erro:
        _log_falha(pedido, corpo, erro, time.perf_counter() - inicio)
        raise

    _log_publicado(topologia, corpo, pedido.pk, relatorio, evento_log="PedidoPublicado")
    return {
        "evento_id": corpo["evento_id"],
        "broker": "kafka",
        "topico": topologia.topico,
        # `fila` continua no retorno: é a chave que o `measure_messaging.py` já
        # lia, e manter o nome é o que permite comparar as medições dos dois
        # brokers sem tocar no instrumento.
        "fila": topologia.topico,
        "chave": str(pedido.pk),
        "particao": relatorio.get("particao"),
        "offset": relatorio.get("offset"),
        "duracao_ms": relatorio.get("duracao_ms"),
        "ocorrido_em": corpo["ocorrido_em"],
        "publicado_em": corpo["publicado_em"],
    }


def publicar_pagamento_registrado(pagamento: models.Pagamento) -> dict[str, Any]:
    """Publica o `PagamentoRegistrado` e devolve os dados de publicação.

    O `key` da mensagem é o **`pedido_id`**, não o `pagamento_id`, e a razão é
    a mesma que vale para o `PedidoCriado`: o Kafka garante que mensagens com a
    mesma key caem na mesma partição, na mesma ordem. Assim os dois eventos de um
    mesmo pedido nunca são lidos fora de ordem pelos workers, mesmo com as
    partições repartidas entre vários processos.
    """
    corpo = contracts.construir_pagamento_registrado(pagamento)
    topologia = TopologiaKafka.de_pagamentos()

    inicio = time.perf_counter()
    try:
        relatorio = publicar(
            topologia,
            corpo,
            chave=str(pagamento.pedido_id),
            client_id="synapseshop-api-produtor",
        )
    except PublicacaoFalhou as erro:
        _log_falha_pagamento(pagamento, corpo, erro, time.perf_counter() - inicio)
        raise

    _log_publicado(
        topologia,
        corpo,
        pagamento.pedido_id,
        relatorio,
        evento_log="PagamentoPublicado",
        pagamento_id=pagamento.pk,
        extras={"detalhe": pagamento.metodo},
    )
    return {
        "evento_id": corpo["evento_id"],
        "broker": "kafka",
        "fluxo": topologia.fluxo,
        "topico": topologia.topico,
        "fila": topologia.topico,
        "chave": str(pagamento.pedido_id),
        "particao": relatorio.get("particao"),
        "offset": relatorio.get("offset"),
        "duracao_ms": relatorio.get("duracao_ms"),
        "ocorrido_em": corpo["ocorrido_em"],
        "publicado_em": corpo["publicado_em"],
    }


def republicar(
    topico: str,
    corpo: bytes,
    chave: str | None,
    cabecalhos: list[tuple[str, str]],
    *,
    client_id: str = "synapseshop-worker-republica",
) -> Any:
    """Republica uma mensagem já resolvida (retry ou DLQ), esperando o ACK.

    É o caminho das DLQs internas. Espera o ACK **antes** de o consumidor
    confirmar o offset original: se esta publicação falhar, o offset não é
    confirmado e a mensagem volta a ser processada — nada se perde. É a mesma
    ordem do `republicar` do AMQP, que só dá `ack` na original depois da
    republicação confirmada.
    """
    produtor = _produtor(client_id)
    return _entregar(produtor, topico, corpo, chave, cabecalhos)


def com_tentativa(
    cabecalhos: list[tuple[str, str]],
    tentativa: int,
    *,
    motivo: str | None = None,
) -> list[tuple[str, str]]:
    """Copia os cabeçalhos com o contador de tentativa incrementado.

    O contador viaja na própria mensagem, então sobrevive à passagem pelo
    tópico de retry, ao restart do worker e à leitura por qualquer outro
    consumidor. É o que permite decidir "reentregar ou mandar para a DLQ" sem
    depender de memória do processo.

    `motivo` vai no cabeçalho `x-motivo`: quando alguém inspecionar uma mensagem
    presa na DLQ, a causa da falha está no cabeçalho, sem precisar correlacionar
    com o log de outro processo.
    """
    saida = [
        (nome, valor)
        for nome, valor in cabecalhos
        if nome not in {HEADER_TENTATIVA, HEADER_MOTIVO}
    ]
    saida.append((HEADER_TENTATIVA, str(tentativa)))
    if motivo:
        saida.append((HEADER_MOTIVO, motivo[:200]))
    return saida


def cabecalhos_de(mensagem: Any) -> list[tuple[str, str]]:
    """Cabeçalhos de uma mensagem consumida, normalizados para `str`.

    O Kafka devolve cabeçalhos como lista de tuplas de bytes (o valor). O
    produtor escreve str, mas uma ferramenta externa poderia ter escrito
    qualquer coisa — daí a normalização, para que `com_tentativa` e a leitura do
    contador de tentativa nunca quebrem por causa de um tipo.
    """
    saida: list[tuple[str, str]] = []
    for nome, valor in mensagem.headers() or []:
        if valor is None:
            saida.append((str(nome), ""))
        elif isinstance(valor, (bytes, bytearray)):
            saida.append((str(nome), valor.decode("utf-8", errors="replace")))
        else:
            saida.append((str(nome), str(valor)))
    return saida


def fechar() -> None:
    """Espera o que estiver no buffer e fecha os produtores do processo.

    Chamado no encerramento do worker e no do management command. Sem isto, um
    SIGTERM perto de um `produce()` pode deixar a mensagem no buffer local e
    perdê-la — o ACK nunca viria.
    """
    with _trava:
        pendentes = list(_produtores.items())
        _produtores.clear()
    for _tag, produtor in pendentes:
        try:
            produtor.flush(settings.KAFKA_TIMEOUT_ENVIO_S)
        except Exception as erro:  # noqa: BLE001 - encerramento não pode estourar
            logger.warning(
                "falha ao fechar o produtor kafka",
                extra={
                    "evento": "ProdutorFechando",
                    "resultado": "erro",
                    "broker": "kafka",
                    "erro": descrever(erro),
                },
            )


def _log_falha(
    pedido: models.Pedido,
    corpo: dict[str, Any],
    erro: Exception,
    duracao_ms: float,
) -> None:
    logger.error(
        "falha ao publicar o evento",
        extra={
            "evento": "PedidoPublicacaoFalhou",
            "resultado": "erro",
            "broker": "kafka",
            "fluxo": "pedidos",
            "evento_id": corpo.get("evento_id"),
            "chave_idempotencia": corpo.get("idempotency_key"),
            "pedido_id": pedido.pk,
            "duracao_ms": round(duracao_ms, 3),
            "erro": descrever(erro),
            "motivo": (
                "pedido mantido em "
                f"{settings.PEDIDO_ESTADO_INICIAL}; rode `republicar_pedidos` "
                "ou reenvie o POST com a mesma Idempotency-Key"
            ),
        },
    )


def _log_falha_pagamento(
    pagamento: models.Pagamento,
    corpo: dict[str, Any],
    erro: Exception,
    duracao_ms: float,
) -> None:
    """Equivalente de `_log_falha` para o `PagamentoRegistrado`.

    O `motivo` aponta a cura e é ela que diferencia este caso do pedido: reenviar
    o POST **do pagamento** republica o evento, porque a chave de idempotência é
    calculada pelo servidor a partir de (pedido, método, desfecho). Não é preciso
    nenhum comando de recuperação — o próprio endpoint é a recuperação.
    """
    logger.error(
        "falha ao publicar o evento",
        extra={
            "evento": "PagamentoPublicacaoFalhou",
            "resultado": "erro",
            "broker": "kafka",
            "fluxo": "pagamentos",
            "evento_id": corpo.get("evento_id"),
            "chave_idempotencia": corpo.get("idempotency_key"),
            "pedido_id": pagamento.pedido_id,
            "pagamento_id": pagamento.pk,
            "duracao_ms": round(duracao_ms, 3),
            "erro": descrever(erro),
            "motivo": (
                "pagamento mantido em 'registrado'; reenvie o POST em "
                "/api/v1/pedidos/%s/pagamento/ para republicar o evento"
                % pagamento.pedido_id
            ),
        },
    )