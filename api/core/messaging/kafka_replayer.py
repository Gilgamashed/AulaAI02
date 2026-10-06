"""Replayer dos tópicos de retry: onde o backoff da Aula 9 acontece no Kafka.

O RabbitMQ resolve a espera da escada de reentrega sozinho — a mensagem fica na
fila de retry com TTL e o broker a devolve para a fila principal quando o prazo
vence (dead lettering). **O Kafka não tem esse mecanismo**: `retention.ms`
**apaga** a mensagem, e não existe "voltar para o tópico anterior". Um delay
nativo (`kafka-delayed-topic`) exigiria plugin no broker, e a spec pede
declarar a topologia pela aplicação.

Então a espera é feita aqui, comparando a **idade da mensagem** com o backoff do
seu degrau:

    worker falha ─▶ produz em `pedidos.criados.retry.1`  (x-tentativa: 1)
                        │
                  replayer (grupo `…-replay`, 1 partition cada retry topic)
                        │  idade < 5 s ─▶ pause(partição) e dorme o que falta
                        │  idade >= 5 s ─▶ produz de volta em `pedidos.criados`
                        ▼
                  worker processa de novo (x-tentativa: 1) ─▶ degrau 2, etc.

Três decisões que valem registro:

1. **A idade vem do timestamp do BROKER**, lido em `message.timestamp()`, e não
   do relógio do processo. Se fosse o relógio local, `sleep` acumula erro e a
   mensagem seria devolvida cedo (ou tarde); com o timestamp do broker, o atraso
   é medido no mesmo relógio que o	publicou, que é a mesma razão pela qual a
   retenção do retry é `2 × degrau + folga`.

2. **A espera é feita com `pause()`/`resume()` na partição, não com `sleep` no
   laço inteiro.** O `sleep` bloquearia o replayer inteiro e, com
   `KAFKA_PARTICOES`/vários degraus, um retry parado atrasaria todos os outros.
   Como cada tópico de retry tem **1 partição**, pausar a partição equivale a
   pausar só aquela mensagem.

3. **O replayer roda dentro do processo `worker-kafka`** (thread daemon
   iniciada por `kafka_consumidor`), com um grupo próprio
   (`KAFKA_GRUPO_REPLAY`) e um `Consumer` por tópico de retry. Grupo próprio é o
   que impede o replayer de disputar partições com o worker principal; e, com
   `--scale worker-kafka=N`, as N réplicas dividem o trabalho sem duplicar
   porque cada mensagem pertence a um único membro do grupo.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from django.conf import settings

from . import kafka_produtor
from .erros import descrever
from .kafka_topologia import (
    TopologiaKafka,
    config_consumidor,
    nomes_retry,
    segundos_do_degrau,
    topico_desconhecido,
)

logger = logging.getLogger("core.messaging")




class Replayer:
    """Devolve ao tópico principal as mensagens de retry cujo degrau venceu.

    Não é thread-safe por si só, mas **não precisa ser**: cada instância é
    usada por exatamente uma thread (a daemon criada em
    `kafka_consumidor._iniciar_replayer`), e cada `Consumer` do librdkafka é
    usado só por essa thread — misturar consumidores entre threads é a causa
    clássica de `Local: Erroneous state` no cliente.
    """

    def __init__(self, topologia: TopologiaKafka, passo_s: float | None = None) -> None:
        self._topologia = topologia
        self._passo_s = passo_s or settings.KAFKA_REPLAYER_PASSO_S
        #folga para a reentrega depois do resume (ver _aguardar_reentrega)
        self._tolerancia_s = max(2.0, self._passo_s * 2)
        self._consumidores: dict[str, Any] = {}
        # `topico -> {particao: {"retoma_em": epoch, "offset": int}}`: o que
        # está pausado, até quando e **qual mensagem** está em mãos.
        self._pausados: dict[str, dict[int, dict[str, Any]]] = {}
        # `topico -> epoch da última retomada`: mede quanto tempo a partição
        # levou para devolver a mensagem depois de `resume()` — é o atraso que
        # o backoff de um degrau realmente teve.
        self._retomados: dict[str, float] = {}
        self._parando = threading.Event()
        self.replayadas = 0

    # ------------------------------------------------------------------
    def rodar(self) -> None:
        """Varre os tópicos de retry até `parar()` (thread daemon)."""
        logger.info(
            "replayer iniciado",
            extra={
                "evento": "ReplayerIniciado",
                "resultado": "ok",
                "broker": "kafka",
                "grupo": self._topologia.grupo_replay,
                "detalhe": {
                    "topicos": self._topologia.topicos_retry(),
                    "backoff_s": [
                        segundos_do_degrau(degrau) for degrau, _ in nomes_retry()
                    ],
                    "passo_s": self._passo_s,
                },
            },
        )
        while not self._parando.is_set():
            for topico in self._topologia.topicos_retry():
                if self._parando.is_set():
                    break
                try:
                    self._varrer(topico)
                except Exception as erro:  # noqa: BLE001 - o replayer não pode morrer
                    logger.error(
                        "erro ao varrer o tópico de retry",
                        extra={
                            "evento": "ReplayerErro",
                            "resultado": "erro",
                            "broker": "kafka",
                            "topico": topico,
                            "erro": descrever(erro),
                        },
                    )
                    self._fechar_consumidor(topico)
                    self._parando.wait(2)
            # A folga entre varreduras só vale quando **não há backoff
            # pendente**: com alguma partição pausada, esperar `passo_s` aqui
            # somaria um atraso fixo a cada prazo que vence — e o prazo é a
            # única coisa que este laço controla. Sem pausa, o laço inteiro é
            # `3 × poll(passo_s)` e a folga evita varrer os três degraus em
            # sequência contínua.
            self._parando.wait(0 if self._pausados else self._passo_s)

        self._fechar_tudo()
        logger.info(
            "replayer encerrado",
            extra={
                "evento": "ReplayerEncerrado",
                "resultado": "ok",
                "broker": "kafka",
                "detalhe": f"{self.replayadas} mensagem(ns) devolvida(s) ao principal",
            },
        )

    def parar(self) -> None:
        """Sinaliza o fim do laço (chamado no encerramento do worker)."""
        self._parando.set()

    # ------------------------------------------------------------------
    def _varrer(self, topico: str) -> None:
        """Processa uma mensagem do tópico de retry, se houver."""
        consumidor = self._consumidor(topico)
        retomado = self._retomar(consumidor, topico)
        mensagem = self._aguardar_reentrega(consumidor, topico, retomado)
        if mensagem is None:
            return
        erro = mensagem.error()
        if erro is not None:
            if topico_desconhecido(erro):
                # Mesmo caso do consumidor: tópico de retry recém-criado ainda
                # ausente no metadata. O replayer tenta de novo no próximo
                # passo, sem log.
                return
            logger.warning(
                "erro ao consumir o tópico de retry",
                extra={
                    "evento": "ReplayerErro",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": topico,
                    "erro": descrever(erro),
                },
            )
            return
        self._avaliar(mensagem)

    def _avaliar(self, mensagem: Any) -> None:
        """Pausa a mensagem (backoff) ou a devolve ao tópico principal."""
        topico = mensagem.topic()
        degrau = self._topologia.degrau_do_topico(topico)
        if degrau is None:
            # Só alcançável se alguém criar um tópico `*.retry.N` fora da
            # topologia declarada. Pausar é a resposta segura: sem degrau não há
            # backoff conhecido, e devolver seria chute.
            logger.error(
                "tópico de retry desconhecido; mensagem retida",
                extra={
                    "evento": "ReplayerTopicoDesconhecido",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": topico,
                },
            )
            self._pausar(mensagem, 60)
            return

        backoff_s = segundos_do_degrau(degrau)
        idade_s = _idade_s(mensagem)
        if idade_s < backoff_s:
            self._pausar(mensagem, backoff_s - idade_s)
            logger.info(
                "mensagem de retry aguardando o degrau",
                extra={
                    "evento": "RetryAguardando",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fila": topico,
                    "topico": topico,
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "tentativa": degrau,
                    # `duracao_ms` aqui é o **restante** do backoff, e é
                    # calculado do relógio do broker — por isso não é o mesmo
                    # número do log de `PedidoFalha`.
                    "duracao_ms": round((backoff_s - idade_s) * 1000, 3),
                    "idade_ms": round(idade_s * 1000, 3),
                    "motivo": f"degrau {degrau} vence em {backoff_s}s",
                },
            )
            return

        chave = mensagem.key()
        try:
            # Republica no principal **antes** de confirmar o offset do retry:
            # se esta publicação falhar, o offset não é confirmado e a mensagem
            # é reprocessada. Perder uma reentrega silenciosamente seria pior
            # do que reentregar uma duplicata — que a idempotência absorve.
            kafka_produtor.republicar(
                self._topologia.topico,
                mensagem.value() or b"",
                chave=chave.decode("utf-8", errors="replace") if chave else None,
                cabecalhos=kafka_produtor.cabecalhos_de(mensagem),
                client_id="synapseshop-replayer",
            )
        except Exception as erro:  # noqa: BLE001 - PublicacaoFalhou e Kafka
            logger.error(
                "falha ao devolver a mensagem de retry ao tópico principal",
                extra={
                    "evento": "ReplayerFalha",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": topico,
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "tentativa": degrau,
                    "erro": descrever(erro),
                },
            )
            self._devolver(mensagem)
            return

        self._confirmar(mensagem)
        self.replayadas += 1
        retomado_em = self._retomados.pop(topico, None)
        logger.info(
            "mensagem de retry devolvida ao tópico principal",
            extra={
                "evento": "RetryLiberada",
                "resultado": "ok",
                "broker": "kafka",
                "fila": topico,
                "topico": topico,
                "destino": self._topologia.topico,
                "particao": mensagem.partition(),
                "offset": mensagem.offset(),
                "tentativa": degrau,
                "duracao_ms": round(idade_s * 1000, 3),
                # Quanto o backoff de verdade custou acima do-degree. Não é
                # zero: depende de quanto o laço leva para volver ao degrau,
                # e é o número que separa "o backoff é 45s" de "o pedido só
                # foi reprocessado 49s depois".
                "espera_ms": (
                    round((time.time() - retomado_em) * 1000, 3)
                    if retomado_em is not None
                    else None
                ),
                "motivo": f"degrau {degrau} ({backoff_s}s) vencido",
            },
        )

    # ------------------------------------------------------------------
    # Pausa / retomada por partição
    # ------------------------------------------------------------------
    def _pausar(self, mensagem: Any, restante_s: float) -> None:
        """Pausa a partição até o prazo vencer, guardando o offset da mensagem.

        Pausar a partição **não** impede a entrega: o `poll()` já consumiu a
        mensagem e a posição de leitura do librdkafka avançou para o offset
        seguinte. Por isso o offset é guardado aqui — sem ele, o `resume()`
        saltaria a mensagem e o degrau nunca venceria.

        O offset **não** é confirmado: se o processo morrer durante o backoff, a
        mensagem volta no rebalance (ou fica até a retenção do tópico expirar),
        que é o comportamento desejado para uma espera.
        """
        from confluent_kafka import TopicPartition

        self._pausados.setdefault(mensagem.topic(), {})[mensagem.partition()] = {
            "retoma_em": time.time() + max(0.0, restante_s),
            "offset": mensagem.offset(),
        }
        consumidor = self._consumidores.get(mensagem.topic())
        if consumidor is None:
            return
        try:
            consumidor.pause([TopicPartition(mensagem.topic(), mensagem.partition())])
        except Exception as erro:  # noqa: BLE001 - pausa é melhor-esforço
            logger.error(
                "falha ao pausar a partição de retry",
                extra={
                    "evento": "ReplayerPausaFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "erro": descrever(erro),
                },
            )

    def _espera(self, topico: str) -> float:
        """Tempo de espera do `poll()` deste tópico.

        Tópico com partição **pausada** é o único que tem algo a entregar: a
        mensagem rebobinada por `_retomar` assim que o prazo vence. Polar rápido
        nele encurta o atraso do backoff — sem isso, o laço (que visita os degraus
        em sequência) somaria um `passo_s` por tópico e o degrau de 45 s custaria
        45 s + o ciclo inteiro. Tópico sem pausa usa `passo_s`, que é o intervalo
        de folga entre varreduras.
        """
        if self._pausados.get(topico):
            return min(self._passo_s, 0.2)
        return self._passo_s

    def _aguardar_reentrega(self, consumidor: Any, topico: str, retomado: bool) -> Any:
        """Um `poll()`; logo após um `resume()`, insiste um pouco mais.

        Tirar uma partição da pausa **não** é instantâneo no librdkafka: depois
        do `resume()` a mensagem rebobinada leva cerca de 1s para voltar a ser
        entregue. Um único `poll(passo_s)` de 1s perde essa corrida por
        milissegundos, e a entrega só acontece na próxima volta do laço — 3s
        somados ao backoff, em cada degrau. Insistir por `tolerancia_s`
        devolve a mensagem no mesmo instante do `resume()`.

        A insistência só acontece **depois de um resume**. Tópico ocioso
        (sem pausa e sem retomada) paga um `poll()` e segue: esperar aqui sem
        motivo atrasaria os outros degraus do laço.
        """
        mensagem = consumidor.poll(self._espera(topico))
        if mensagem is not None or not retomado:
            return mensagem
        limite = time.perf_counter() + self._tolerancia_s
        while mensagem is None and time.perf_counter() < limite:
            mensagem = consumidor.poll(0.2)
        return mensagem

    def _retomar(self, consumidor: Any, topico: str) -> bool:
        """Entrega de novo a mensagem pausada cujo prazo venceu.

        Rebobinar (`seek`) **antes** do `resume()` é o que fecha o ciclo: a
        posição volta ao offset guardado em `_pausar` e a partição volta a ser
        lida dali, de modo que `_avaliar` reprocesse a mesma mensagem e, com o
        backoff vencido, a devolva ao tópico principal.
        """
        from confluent_kafka import TopicPartition

        pendentes = self._pausados.get(topico)
        if not pendentes:
            return False
        agora = time.time()
        vencidas = {
            particao: dados["offset"]
            for particao, dados in pendentes.items()
            if dados["retoma_em"] <= agora
        }
        if not vencidas:
            return False
        for particao in vencidas:
            pendentes.pop(particao, None)
        self._retomados[topico] = time.time()
        try:
            for particao, offset in vencidas.items():
                consumidor.seek(TopicPartition(topico, particao, offset))
            consumidor.resume([TopicPartition(topico, p) for p in vencidas])
            logger.info(
                "partição de retry liberada após o backoff",
                extra={
                    "evento": "RetryRetomado",
                    "resultado": "ok",
                    "broker": "kafka",
                    "topico": topico,
                    "detalhe": f"partições {sorted(vencidas)}",
                    "offset": sorted(vencidas.values()),
                },
            )
        except Exception as erro:  # noqa: BLE001 - retomada é melhor-esforço
            logger.error(
                "falha ao retomar a partição de retry",
                extra={
                    "evento": "ReplayerRetomadaFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": topico,
                    "detalhe": f"partições {vencidas}",
                    "erro": descrever(erro),
                },
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Offsets
    # ------------------------------------------------------------------
    def _confirmar(self, mensagem: Any) -> None:
        """Confirma o offset da mensagem de retry já devolvida ao principal."""
        consumidor = self._consumidores.get(mensagem.topic())
        if consumidor is None:
            return
        try:
            consumidor.commit(message=mensagem, asynchronous=False)
        except Exception as erro:  # noqa: BLE001 - redelivery é absorvido pela dedupe
            logger.error(
                "falha ao confirmar o offset de retry; a mensagem pode voltar",
                extra={
                    "evento": "OffsetCommitFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "erro": descrever(erro),
                },
            )

    def _devolver(self, mensagem: Any) -> None:
        """Não confirma e volta a posição para esta mensagem do retry."""
        from confluent_kafka import TopicPartition

        consumidor = self._consumidores.get(mensagem.topic())
        if consumidor is None:
            return
        try:
            consumidor.seek(
                TopicPartition(mensagem.topic(), mensagem.partition(), mensagem.offset())
            )
        except Exception as erro:  # noqa: BLE001 - devolução é melhor-esforço
            logger.error(
                "falha ao devolver a mensagem de retry; ela voltará no rebalance",
                extra={
                    "evento": "ReplayerDevolucaoFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "erro": descrever(erro),
                },
            )

    # ------------------------------------------------------------------
    # Consumidor
    # ------------------------------------------------------------------
    def _consumidor(self, topico: str) -> Any:
        """Consumer do grupo de replay para este tópico de retry (1 por tópico)."""
        existente = self._consumidores.get(topico)
        if existente is not None:
            return existente
        from confluent_kafka import Consumer

        degrau = self._topologia.degrau_do_topico(topico)
        consumidor = Consumer(
            config_consumidor(
                self._topologia.grupo_replay,
                f"synapseshop-replayer-degrau-{degrau}",
            )
        )
        consumidor.subscribe([topico])
        self._consumidores[topico] = consumidor
        logger.info(
            "consumidor de replay conectado",
            extra={
                "evento": "ReplayerConectado",
                "resultado": "ok",
                "broker": "kafka",
                "topico": topico,
                "grupo": self._topologia.grupo_replay,
            },
        )
        return consumidor

    def _fechar_consumidor(self, topico: str) -> None:
        consumidor = self._consumidores.pop(topico, None)
        if consumidor is None:
            return
        try:
            consumidor.close()
        except Exception as erro:  # noqa: BLE001 - encerramento não pode estourar
            logger.warning(
                "falha ao fechar o consumidor de replay",
                extra={
                    "evento": "ReplayerEncerrando",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": topico,
                    "erro": descrever(erro),
                },
            )

    def _fechar_tudo(self) -> None:
        for topico in list(self._consumidores):
            self._fechar_consumidor(topico)


def _idade_s(mensagem: Any) -> float:
    """Idade da mensagem em segundos, pelo timestamp do broker.

    `Message.timestamp()` devolve `(tipo, epoch_ms)`. Sem timestamp válido
    (tópico recém-criado, ou o campo zerado), a idade é tratada como **já
    vencida** — devolver a mensagem para nova tentativa é melhor do que prendê-la
    para sempre por causa de um metadado ausente. `seek()` por offset não é
    opção aqui: a origem da mensagem é a retenção do degrau, não um timestamp.
    """
    try:
        _tipo, epoch_ms = mensagem.timestamp()
    except Exception:  # noqa: BLE001 - metadado ausente
        epoch_ms = 0
    if not epoch_ms or epoch_ms <= 0:
        logger.warning(
            "mensagem sem timestamp do broker; tratando como vencida",
            extra={
                "evento": "RetrySemTimestamp",
                "resultado": "erro",
                "broker": "kafka",
                "topico": mensagem.topic(),
                "particao": mensagem.partition(),
                "offset": mensagem.offset(),
            },
        )
        return float("inf")
    return max(0.0, time.time() - (epoch_ms / 1000.0))