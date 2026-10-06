"""Consumidor Kafka: o *worker* dos eventos `PedidoCriado` (Aula 10) e
`PagamentoRegistrado` (Aula 11).

Executado pelo management command `consumir_pedidos` (ver também os serviços
`worker-kafka` e `worker-pagamentos` do docker-compose). Uma iteração do laço,
para uma mensagem:

    poll() (commit manual, enable.auto.commit=false)
        │
        ├─ 1. desserializa e valida contra o contrato do fluxo
        │       └─ inválido ────────────────────────────────> DLQ (terminal)
        │
        ├─ 2. reserva a janela de idempotência (Redis SET NX EX)
        │       └─ já reservada ──> `<Evento>Duplicado` + commit (sem efeito)
        │
        ├─ 3. aplica o efeito do evento
        │       ├─ fluxo `pedidos`:   UPDATE condicional `pendente -> processado`
        │       └─ fluxo `pagamentos`: UPDATE condicional `registrado -> aprovado|recusado`
        │                              (+ gravacao da notificacao)
        │
        ├─ 4a. sucesso ──> confirma a janela, log, commit
        └─ 4b. falha recuperável
                ├─ tentativa < max_reentregas ──> produz no tópico de retry
                │                              do degrau, conta tentativa,
                │                              commit
                └─ tentativas esgotadas ─────> entidade marcada como `falha`
                                               e mensagem na DLQ, commit

O princípio que organiza o código é **o mesmo da Aula 9**: o commit vem
sempre por último, e só depois que a mensagem foi resolvida de fato — por
efeito aplicado, por republicação confirmada, ou por descarte consciente
(duplicata). A ordem inversa é o caminho clássico do "evento perdido": o
processo morre entre o commit e o trabalho, e ninguém percebe.

O laço consome **uma mensagem por vez** (`poll()` devolve uma), coerente com
essa garantia: enquanto o efeito não está confirmado, o worker não puxa a
próxima. É também o que torna seguro o `seek()` de devolução usado no caminho
de republicação falha.

Sobre partições e ordem: cada consumidor recebe partições inteiras e nunca
mais de uma por vez, então a ordem dentro de uma partição (isto é, por pedido,
porque a key é o `pedido_id`) é preservada no caminho normal. Com 3 partições e
3 consumidores, cada um é dono de uma partição — é esse o paralelismo que o
RabbitMQ não tinha (lá o paralelismo vinha de vários consumidores na mesma
fila, e a medição mostrou que 3 consumidores na verdade *pioravam* a latência).

Os **dois fluxos são independentes** de ponta a ponta: tópico, `group.id`,
janela de dedupe, escada de reentrega e DLQ. O que é compartilhado é o
*mecanismo* (este arquivo), não o estado — por isso o worker de pagamentos não
consome `pedidos.criados` mesmo com a mesma imagem e o mesmo código.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .. import models, notificacoes
from . import dedupe, kafka_admin, kafka_produtor
from .broker import FLUXO_PEDIDOS, FLUXO_PAGAMENTOS
from .contracts import ContratoInvalido, PedidoCriado, PagamentoRegistrado, validar
from .erros import descrever
from .kafka_replayer import Replayer
from .kafka_topologia import (
    HEADER_TENTATIVA,
    TopologiaKafka,
    config_consumidor,
    topico_desconhecido,
)
from .metricas import DLQ, DUPLICADO, FALHA, PROCESSADO, mensageria_metrics

logger = logging.getLogger("core.messaging")

# Nome do evento no log, por fluxo. Um nome por fluxo (e não um nome por
# situação) é o que permite o mesmo `grep` no `docker compose logs` responder
# "como está o fluxo X?" sem precisar saber, antes de olhar, qual das duas
# entidades estava em jogo: `PagamentoProcessado` e `PedidoProcessado` se
# distinguem pelo prefixo, e a chave `fluxo` desambigua sem ambiguidade.
PREFIXO_LOG = {FLUXO_PEDIDOS: "Pedido", FLUXO_PAGAMENTOS: "Pagamento"}

# Estados que o worker pode avançar para `processado`. `processado` está
# fora de propósito: é a guarda contra o efeito duplicado no banco.
# (Idêntico ao do consumidor AMQP — o estado do pedido não depende do broker.)
ESTADOS_PROCESSAVEIS = (
    models.Pedido.PENDENTE,
    models.Pedido.PENDENTE_PUBLICACAO,
    models.Pedido.FALHA,
)

# Análogo para o pagamento: o worker só avança a partir de `registrado`, e
# `aprovado`/`recusado` ficam fora de propósito pelo mesmo motivo — são a guarda
# contra o efeito duplicado no banco.
ESTADOS_PAGAMENTO_PROCESSAVEIS = (models.Pagamento.REGISTRADO,)


class MensagemIncorreta(Exception):
    """Falha TERMINAL: reentregar não muda nada, então vai direto para a DLQ.

    Difere de uma exceção qualquer do banco, que pode ser transitória. Aqui a
    mensagem está logicamente errada: o pedido não existe, ou a chave de
    idempotência não é a do pedido. Reprocessar dez vezes reproduz o mesmo
    erro e só gasta broker.
    """


class FalhaInjetada(Exception):
    """Falha **de propósito** (header `X-Simular-Falha` no POST).

    Não é um bug: é o mecanismo que prova, ponta a ponta, que a escada de
    reentrega e a DLQ funcionam de verdade — com uma entidade real, um log por
    tentativa e a mensagem parada na DLQ do fluxo no fim
    (`pedidos.criados.dlq` ou `pagamentos.registrados.dlq`).

    Recupérável por definição (é uma exceção comum no laço), então segue o
    mesmo caminho de qualquer falha transitória: reentrega com backoff e, ao
    esgotar, DLQ.
    """


class ConsumidorKafka:
    """Laço de consumo do Kafka com política de reentrega e DLQ.

    Uma instância atende **um fluxo**. O `fluxo` decide o tópico, o `group.id`, o
tipo de evento aceito e o nome dos logs — é o que permite o mesmo laço (a mesma
escada de reentrega, o mesmo commit manual, a mesma DLQ) atender o
`PedidoCriado` das Aulas 9/10 e o `PagamentoRegistrado` da Aula 11: a diferença
    entre os dois fica confinada ao efeito aplicado, em vez de espalhada pelo
    laço inteiro.
    """

    def __init__(
        self,
        topico: str | None = None,
        max_mensagens: int | None = None,
        *,
        fluxo: str = FLUXO_PEDIDOS,
    ) -> None:
        self.fluxo = fluxo
        # A topologia é resolvida aqui, e não em `rodar()`, porque `_conectar` já
        # precisa do `group.id` antes do primeiro `poll()`. Deixá-la para `rodar`
        # obrigaria a duplicar a resolução em dois lugares.
        self._topologia: TopologiaKafka = TopologiaKafka.do_fluxo(fluxo)
        self.topico_nome = topico or self._topologia.topico
        self.max_mensagens = max_mensagens
        self.recebidas = 0
        self.consumidor: Any = None
        self._parando = False
        self._replayer: Replayer | None = None
        self._thread_replayer: threading.Thread | None = None

    @property
    def topologia(self) -> TopologiaKafka:
        """Topologia do fluxo, já resolvida."""
        return self._topologia

    @property
    def grupo(self) -> str:
        """`group.id` do consumidor deste fluxo."""
        return self._topologia.grupo

    @property
    def client_id(self) -> str:
        """`client.id` do consumidor deste fluxo.

        Distinto por fluxo de propósito: o `client.id` aparece no
        `kafka-consumer-groups.sh --describe` e no log do broker, e é ele que
        permite dizer, ao olhar o cluster, qual processo está lendo o quê.
        """
        return f"synapseshop-worker-{self.fluxo}"

    def descricao_destino(self) -> str:
        """Texto do destino, para o console do management command."""
        return (
            f"o tópico Kafka '{self.topico_nome}' "
            f"(fluxo '{self.fluxo}', grupo '{self.grupo}')"
        )

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def rodar(self) -> dict[str, Any]:
        """Consome até parar (SIGTERM, `--max-mensagens` ou tópico vazio)."""
        self.consumidor = self._conectar_com_tentativas()
        try:
            # Idempotente: quem subir primeiro (API ou worker) cria os tópicos.
            kafka_admin.criar_topicos(self._topologia)
            self.consumidor.subscribe([self.topico_nome])
            self._iniciar_replayer()
            self._instalar_parada_graciosa()
            logger.info(
                "worker iniciado",
                extra={
                    "evento": "WorkerIniciado",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fluxo": self.fluxo,
                    "fila": self.topico_nome,
                    "topico": self.topico_nome,
                    "grupo": self.grupo,
                    "detalhe": {
                        **self.topologia.resumo(),
                        "particoes": self.topologia.particoes,
                        "max_mensagens": self.max_mensagens,
                        "auto_commit": False,
                    },
                },
            )
            self._laco()
        finally:
            self._encerrar()

        resumo = mensageria_metrics.snapshot()
        resumo["broker"] = "kafka"
        resumo["fluxo"] = self.fluxo
        resumo["fila"] = self.topico_nome
        resumo["recebidas_no_processo"] = self.recebidas
        logger.info(
            "worker encerrado",
            extra={
                "evento": "WorkerEncerrado",
                "resultado": "ok",
                "broker": "kafka",
                "fila": self.topico_nome,
                "topico": self.topico_nome,
                "detalhe": resumo,
            },
        )
        return resumo

    def _laco(self) -> None:
        while not self._parando:
            mensagem = self.consumidor.poll(1.0)
            if mensagem is None:
                continue
            erro = mensagem.error()
            if erro is not None:
                self._log_erro_poll(erro)
                continue
            self._tratar(mensagem)

    def _conectar_com_tentativas(self, tentativas: int = 5) -> Any:
        """Conecta ao cluster, tolerando o broker ainda estar subindo.

        `Consumer()` não abre socket de imediato — a conexão acontece em
        background — então "construiu o objeto" não prova que o broker está de
        pé. Por isso a checagem real é um `list_topics`, que é uma requisição de
        metadados de verdade.

        Erro de conexão não é problema do consumidor: sair com código diferente
        de zero deixa o `restart: unless-stopped` do compose reexecutar o
        worker, o comportamento desejado para uma dependência que caiu (em vez
        de um processo vivo consumindo zumbido de erro).
        """
        from confluent_kafka import Consumer

        ultimo_erro: Exception | None = None
        for tentativa in range(1, tentativas + 1):
            consumidor = None
            try:
                consumidor = Consumer(
                    config_consumidor(self.grupo, self.client_id)
                )
                consumidor.list_topics(timeout=5)
                return consumidor
            except Exception as erro:  # noqa: BLE001 - KafkaException e OSError
                ultimo_erro = erro
                if consumidor is not None:
                    consumidor.close()
                logger.warning(
                    "broker indisponível; nova tentativa",
                    extra={
                        "evento": "WorkerSemConexao",
                        "resultado": "erro",
                        "broker": "kafka",
                        "fluxo": self.fluxo,
                        "fila": self.topico_nome,
                        "tentativa": tentativa,
                        "erro": descrever(erro),
                    },
                )
                if tentativa < tentativas:
                    time.sleep(5)
        raise SystemExit(
            f"consumidor: broker indisponível após {tentativas} tentativas: {ultimo_erro}"
        )

    def _log_erro_poll(self, erro: Any) -> None:
        """Erro vindo do `poll()` — separado de `except` porque é assíncrono.

        Um caso é **silenciado**: `UNKNOWN_TOPIC_OR_PART`. Ele aparece logo no
        startup, porque o `subscribe()` é assinado no instante em que a topologia
        está sendo criada e o metadata do cliente ainda não reflete os tópicos
        novos. O librdkafka relista sozinho em poucos milissegundos e o consumo
        começa normalmente — logar isso como aviso transformaria um detalhe
        benigno em ruído que esconde falha real, e a primeira impressão de quem
        roda `docker compose logs -f worker-kafka` seria um muro de erros.

        Os demais erros (rede, metadata, rebalance) são registrados e ignorados:
        o librdkafka reconecta sozinho, e matar o worker por causa de um aviso
        transitório seria converter um aviso em indisponibilidade.
        """
        if topico_desconhecido(erro):
            return
        logger.warning(
            "erro ao consumir",
            extra={
                "evento": "ErroConsumo",
                "resultado": "erro",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "fila": self.topico_nome,
                "erro": descrever(erro),
            },
        )

    def _iniciar_replayer(self) -> None:
        """Sobe o replayer dos tópicos de retry no mesmo processo.

        Por que no mesmo processo: o replayer é parte da política de reentrega,
        não um serviço independente — se ele não estiver no ar junto, a escada de
        5/15/45 s fica parada e as mensagens de retry vencem na retenção. Como
        o compose escala `worker-kafka` com `--scale`, cada instância também
        tem seu replayer, todos no mesmo grupo (`KAFKA_GRUPO_REPLAY`), o que
        distribui a responsabilidade entre eles sem duplicar trabalho.
        """
        self._replayer = Replayer(self.topologia)
        self._thread_replayer = threading.Thread(
            target=self._replayer.rodar,
            name="kafka-replayer",
            daemon=True,
        )
        self._thread_replayer.start()

    def _instalar_parada_graciosa(self) -> None:
        """SIGTERM/SIGINT param o consumo sem perder mensagem em trânsito.

        `docker compose stop` e `docker compose down` mandam SIGTERM. Como o
        commit é manual e chega por último, uma morte abrupta devolveria a
        mensagem ao tópico (comportamento correto, mas ruidoso no log). Parar de
        forma explícita torna o encerramento previsível.
        """

        def _parar(signum, _frame):
            if self._parando:
                return
            self._parando = True
            logger.info(
                "sinal de parada recebido; finalizando consumo",
                extra={
                    "evento": "WorkerParando",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fila": self.topico_nome,
                    "detalhe": signal.Signals(signum).name,
                },
            )

        signal.signal(signal.SIGTERM, _parar)
        signal.signal(signal.SIGINT, _parar)

    def _encerrar(self) -> None:
        """Fecha o consumidor e o produtor, depois derruba o replayer."""
        if self._replayer is not None:
            self._replayer.parar()
        if self._thread_replayer is not None:
            self._thread_replayer.join(timeout=5)
        if self.consumidor is not None:
            try:
                # `close()` faz o commit das mensagens pendentes e sai do grupo.
                self.consumidor.close()
            except Exception as erro:  # noqa: BLE001 - encerramento não pode estourar
                logger.warning(
                    "falha ao fechar o consumidor",
                    extra={
                        "evento": "WorkerEncerrando",
                        "resultado": "erro",
                        "broker": "kafka",
                        "erro": descrever(erro),
                    },
                )
        kafka_produtor.fechar()

    # ------------------------------------------------------------------
    # Offset: o `ack` do Kafka
    # ------------------------------------------------------------------
    def _confirmar(self, mensagem: Any) -> None:
        """Confirma o offset **após** a mensagem ter sido resolvida.

        Equivalente ao `basic_ack` do AMQP. `commit(message=…)` grava
        `offset + 1` do grupo de forma síncrona, e o erro é logado em vez de
        propagado: falhar no commit NÃO invalida o efeito já aplicado no banco,
        e a consequência (redelivery) é exatamente a que a idempotência segura.

        Rebalance em andamento é um caso à parte e **não** é falha: o broker
        invalida a `generation_id` quando as partições mudam de dono, então um
        commit concorrente com o rebalance é recusado com `ILLEGAL_GENERATION`
        (ou `REBALANCE_IN_PROGRESS`). A mensagem volta para o consumo — quem
        recebe a partição agora — e o offset confirmado para ela é o do novo
        dono. Registrar isso como ERROR foi medido nesta aula: subir e derrubar
        réplicas com `--scale` produzia um `OffsetCommitFalhou` vermelho a cada
        rebalance, parecendo defeito no consumer quando é o comportamento
        documentado do protocolo. O evento sai em INFO com o motivo explícito.
        """
        try:
            self.consumidor.commit(message=mensagem, asynchronous=False)
        except Exception as erro:  # noqa: BLE001 - commit falhando não é fatal
            rebalance = _erro_de_rebalance(erro)
            extra = {
                "evento": "OffsetCommitIgnorado" if rebalance else "OffsetCommitFalhou",
                "resultado": "rebalance" if rebalance else "erro",
                "broker": "kafka",
                "fila": mensagem.topic(),
                "particao": mensagem.partition(),
                "offset": mensagem.offset(),
                "erro": descrever(erro),
            }
            if rebalance:
                extra["motivo"] = (
                    "rebalance invalidou a geração do grupo; a partição já tem "
                    "outro dono e o offset desta mensagem é confirmado por ele"
                )
                logger.info("commit recusado por rebalance; sem efeito", extra=extra)
            else:
                logger.error(
                    "falha ao confirmar o offset; a mensagem pode ser reentregue",
                    extra=extra,
                )

    def _devolver(self, mensagem: Any) -> None:
        """Não confirma o offset e volta a posição para esta mensagem.

        É o `nack(requeue=True)` do AMQP. O `seek()` é necessário porque a
        posição do consumidor no librdkafka avança no `poll()`, independente do
        commit: sem ele, a mensagem ficaria "presa" até um rebalance, e a
        reentrega queimar o degrau da escada sem nenhuma nova tentativa.
        """
        from confluent_kafka import TopicPartition

        try:
            self.consumidor.seek(
                TopicPartition(mensagem.topic(), mensagem.partition(), mensagem.offset())
            )
        except Exception as erro:  # noqa: BLE001 - devolução é melhor-esforço
            logger.error(
                "falha ao devolver a mensagem; ela voltará no rebalance",
                extra={
                    "evento": "ReentregaFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "fila": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "erro": descrever(erro),
                },
            )

    # ------------------------------------------------------------------
    # Tratamento de uma mensagem
    # ------------------------------------------------------------------
    def _tratar(self, mensagem: Any) -> None:
        """Trata UMA mensagem, da validação do contrato ao commit final."""
        self.recebidas += 1
        mensageria_metrics.record_recebida()
        inicio = time.perf_counter()
        cabecalhos = kafka_produtor.cabecalhos_de(mensagem)
        tentativa = _tentativa(cabecalhos)
        corpo = mensagem.value() or b""

        try:
            evento = self._validar(corpo)
        except ContratoInvalido as erro:
            # Payload quebrado: reentregar não conserta JSON. DLQ imediata.
            self._mandar_para_dlq(
                mensagem, cabecalhos, corpo, tentativa, motivo=descrever(erro), invalido=True
            )
            return

        atraso_ms = max(0, int(time.time() * 1000) - evento.publicado_em_ms)
        logger.info(
            "mensagem recebida",
            extra={
                "evento": "MensagemRecebida",
                "resultado": "ok",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "pagamento_id": getattr(evento, "pagamento_id", None),
                "fila": self.topico_nome,
                "topico": mensagem.topic(),
                "particao": mensagem.partition(),
                "offset": mensagem.offset(),
                "tentativa": tentativa,
                "atraso_fila_ms": round(atraso_ms, 3),
            },
        )

        if not dedupe.reservar(evento):
            # Duplicata reconhecida pela janela: não há efeito a aplicar.
            self._confirmar(mensagem)
            mensageria_metrics.record(DUPLICADO)
            logger.info(
                "mensagem duplicada descartada",
                extra={
                    "evento": f"{PREFIXO_LOG[self.fluxo]}Duplicado",
                    "resultado": "duplicado",
                    "broker": "kafka",
                    "fluxo": self.fluxo,
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "pagamento_id": getattr(evento, "pagamento_id", None),
                    "fila": self.topico_nome,
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "tentativa": tentativa,
                    "atraso_fila_ms": round(atraso_ms, 3),
                    "motivo": "chave de idempotência já reservada no Redis",
                },
            )
            self._checar_limite()
            return

        try:
            aplicado = self._aplicar_efeito(evento, tentativa)
        except MensagemIncorreta as erro:
            # Terminal: libera a janela (a chave não pode vazar) e joga na DLQ.
            dedupe.liberar(evento)
            self._registrar_falha(evento, descrever(erro), terminal=True)
            self._mandar_para_dlq(mensagem, cabecalhos, corpo, tentativa, motivo=descrever(erro))
            self._checar_limite()
            return
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira reentrega
            dedupe.liberar(evento)
            # A tentativa é registrada DENTRO de `_reentregar_ou_dlq`, uma única
            # vez por mensagem processada com erro. Registrar aqui e de novo no
            # ramo terminal inflaria `Pedido.tentativas` em 1 na última
            # tentativa — e é justamente o número que o operador lê para saber
            # quantas vezes o pedido falhou.
            self._reentregar_ou_dlq(mensagem, cabecalhos, corpo, evento, tentativa, erro)
            self._checar_limite()
            return

        # Sucesso (ou duplicata reconhecida no banco): a janela é confirmada
        # e só então a mensagem sai do fluxo.
        dedupe.confirmar(evento)
        self._confirmar(mensagem)
        duracao_ms = (time.perf_counter() - inicio) * 1000

        if aplicado:
            mensageria_metrics.record(PROCESSADO)
            logger.info(
                # Pelo nome do fluxo, e não "pedido processado": o campo
                # `evento` já dizia `PagamentoProcessado` logo abaixo, e a
                # mensagem fixa deixaria o log do fluxo de pagamento se
                # anunciando como se fosse o de pedidos — o tipo de coisa que
                # faz alguém procurar o worker errado ao ler um incidente.
                f"{self.fluxo} processado",
                extra={
                    "evento": f"{PREFIXO_LOG[self.fluxo]}Processado",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fluxo": self.fluxo,
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "pagamento_id": getattr(evento, "pagamento_id", None),
                    "fila": self.topico_nome,
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "tentativa": tentativa,
                    "atraso_fila_ms": round(atraso_ms, 3),
                    "duracao_ms": round(duracao_ms, 3),
                },
            )
        else:
            # O `<Entidade>Duplicado` já foi logado em `_aplicar_efeito`, com o
            # motivo exato (UPDATE casou 0 linhas).
            mensageria_metrics.record(DUPLICADO)
            logger.info(
                "duplicata confirmada pelo banco",
                extra={
                    "evento": "MensagemEncerrada",
                    "resultado": "duplicado",
                    "broker": "kafka",
                    "fluxo": self.fluxo,
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "pagamento_id": getattr(evento, "pagamento_id", None),
                    "fila": self.topico_nome,
                    "topico": mensagem.topic(),
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                    "tentativa": tentativa,
                    "duracao_ms": round(duracao_ms, 3),
                },
            )
        self._checar_limite()

    def _checar_limite(self) -> None:
        """Para o laço depois de resolver a mensagem atual (`--max-mensagens`).

        A checagem vem **depois** de resolver (o commit/ack já aconteceu), e não
        no `finally` como no AMQP: aqui quem controla o laço é o `while` do
        `_laco`, e uma flag é mais explícita do que um `stop_consuming`.
        """
        if self.max_mensagens and self.recebidas >= self.max_mensagens:
            self._parando = True
            logger.info(
                "limite de mensagens atingido; encerrando consumo",
                extra={
                    "evento": "WorkerLimiteAtingido",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fila": self.topico_nome,
                    "detalhe": f"{self.recebidas}/{self.max_mensagens} mensagens",
                },
            )

# ------------------------------------------------------------------
    # Etapas
    # ------------------------------------------------------------------
    def _validar(self, corpo: bytes) -> PedidoCriado | PagamentoRegistrado:
        """Desserializa e valida contra o contrato **deste fluxo**.

        A validação é feita pelo despachante `contracts.validar`, que escolhe o
        contrato pelo tipo de evento declarado no próprio payload, e não por uma
        suposição do worker sobre o fluxo. A diferença é observável: se alguém
        publicar um `PedidoCriado` em `pagamentos.registrados`, o `validar`
        devolve o `PedidoCriado` (um contrato válido) e o efeito nem é tentado —
        o `_aplicar_efeito_pagamento` rejeita a combinação com `MensagemIncorreta`
        e a mensagem vai para a DLQ **do fluxo de pagamento**. Silenciar isso
        (validar sempre contra o contrato do fluxo do worker) seria trocar uma
        falha visível por um efeito aplicado no lugar errado.
        """
        try:
            bruto = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            raise ContratoInvalido(f"corpo não é JSON UTF-8 válido: {erro}") from erro
        return validar(bruto)

    def _aplicar_efeito(
        self, evento: PedidoCriado | PagamentoRegistrado, tentativa: int
    ) -> bool:
        """Aplica o efeito do evento e diz se ele foi aplicado de fato.

        O `UPDATE` condicional é a **segunda** barreira de idempotência (a
        primeira é a janela do Redis): mesmo que a chave de dedupe tenha
        expirado ou o Redis esteja fora, o `status` deixando de ser o estado
        inicial faz o `UPDATE` casar zero linhas e o consumidor trata como
        duplicata.

        A condição sobre `idempotency_key` fecha o outro lado da moeda: sem
        ela, uma mensagem desorientada (id certo, chave de outro pedido/pagamento)
        processaria a entidade errada.

        As flags `simular_falha` são lidas do **banco**, e não do evento, de
        propósito: elas são decisões operacionais, não parte dos contratos, e o
        banco é a única autoridade sobre o estado atual.
        """
        if self.fluxo == FLUXO_PAGAMENTOS:
            return self._aplicar_efeito_pagamento(evento, tentativa)
        return self._aplicar_efeito_pedido(evento, tentativa)

    def _aplicar_efeito_pedido(self, evento: PedidoCriado, tentativa: int) -> bool:
        """Efeito do `PedidoCriado`: avança o pedido para `processado`."""
        if not isinstance(evento, PedidoCriado):
            raise MensagemIncorreta(
                f"evento '{evento.evento}' não pertence ao fluxo '{self.fluxo}'"
            )
        if models.Pedido.objects.filter(pk=evento.pedido_id, simular_falha=True).exists():
            raise FalhaInjetada(
                "falha injetada (X-Simular-Falha): pedido marcado para falhar"
            )

        agora = timezone.now()
        with transaction.atomic():
            atualizados = models.Pedido.objects.filter(
                pk=evento.pedido_id,
                idempotency_key=evento.idempotency_key,
                status__in=ESTADOS_PROCESSAVEIS,
            ).update(
                status=models.Pedido.PROCESSADO,
                processado_em=agora,
                updated_at=agora,
                tentativas=F("tentativas") + 1,
                motivo_falha="",
            )

        if atualizados:
            return True

        # Zero linhas: ou o pedido já foi processado (duplicata real), ou a
        # mensagem não corresponde ao pedido.
        existente = models.Pedido.objects.filter(pk=evento.pedido_id).first()
        if existente is None:
            raise MensagemIncorreta(f"pedido {evento.pedido_id} não existe no banco")
        if existente.idempotency_key != evento.idempotency_key:
            raise MensagemIncorreta(
                "chave de idempotência do evento não confere com a do pedido"
            )
        logger.info(
            "efeito já aplicado anteriormente; descartando",
            extra={
                "evento": f"{PREFIXO_LOG[self.fluxo]}Duplicado",
                "resultado": "duplicado",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "fila": self.topico_nome,
                "tentativa": tentativa,
                "motivo": "pedido já estava processado (UPDATE casou 0 linhas)",
            },
        )
        return False

    def _aplicar_efeito_pagamento(
        self, evento: PagamentoRegistrado, tentativa: int
    ) -> bool:
        """Efeito do `PagamentoRegistrado`: desfecho **e** notificação.

        As duas escritas vivem na **mesma** `transaction.atomic()`, e é isso que
        fecha o race entre os dois workers: se o desfecho entrasse numa
        transação e a notificação em outra, o `get_or_create` da notificação
        ainda poderia falhar depois de o `UPDATE` ter virado `recusado` — e aí a
        reentrega (ou a DLQ) trataria como falha uma notificação que já tinha
        sido escrita. Junto, ou as duas entram, ou nenhuma.

        A notificação é criada com `get_or_create` e não com `create`: o
        `OneToOne` entre `Pagamento` e `Notificacao` é a garantia real de
        unicidade, mas ela só vira erro no banco — e o caminho de erro aqui é
        reentrega, que gastaria degraus de backoff para provar algo que já está
        gravado.
        """
        if not isinstance(evento, PagamentoRegistrado):
            raise MensagemIncorreta(
                f"evento '{evento.evento}' não pertence ao fluxo '{self.fluxo}'"
            )
        if models.Pagamento.objects.filter(
            pk=evento.pagamento_id, simular_falha=True
        ).exists():
            raise FalhaInjetada(
                "falha injetada (simular_falha): pagamento marcado para falhar"
            )

        agora = timezone.now()
        with transaction.atomic():
            pagamento = (
                models.Pagamento.objects.select_related("pedido")
                .filter(
                    pk=evento.pagamento_id,
                    idempotency_key=evento.idempotency_key,
                    status__in=ESTADOS_PAGAMENTO_PROCESSAVEIS,
                )
                .first()
            )
            if pagamento is not None:
                pagamento.status = (
                    models.Pagamento.APROVADO
                    if evento.aprovado
                    else models.Pagamento.RECUSADO
                )
                pagamento.aprovado = evento.aprovado
                pagamento.motivo_recusa = (
                    "" if evento.aprovado else evento.motivo_recusa
                )
                pagamento.notificado_em = agora
                pagamento.updated_at = agora
                pagamento.save(
                    update_fields=[
                        "status",
                        "aprovado",
                        "motivo_recusa",
                        "notificado_em",
                        "updated_at",
                    ]
                )

                # A "entrega" é a própria gravação da linha: não há SMTP nem
                # SMS nesta aula, e fingir que há (ou dormir para simular
                # latência) só adicionaria um timer ao caminho de erro sem
                # provar nada. `enviada_em` fica de fora dos `defaults` porque é
                # `auto_now_add` — passar seria mentira, o banco grava o
                # instante do disparo de qualquer forma.
                #
                # O texto vem de `core.notificacoes`, não do evento: o evento
                # descreve o pagamento, e a redação da notificação é
                # apresentação — muda por decisão de produto sem que isso seja
                # alteração de contrato.
                titulo, mensagem = notificacoes.titulo_e_mensagem(evento)
                models.Notificacao.objects.get_or_create(
                    pagamento=pagamento,
                    defaults={
                        "pedido": pagamento.pedido,
                        "canal": evento.canal_notificacao,
                        "titulo": titulo,
                        "mensagem": mensagem,
                    },
                )
                return True

        # Zero linhas: ou o pagamento já foi resolvido (duplicata real), ou a
        # mensagem não corresponde ao pagamento.
        existente = models.Pagamento.objects.filter(pk=evento.pagamento_id).first()
        if existente is None:
            raise MensagemIncorreta(
                f"pagamento {evento.pagamento_id} não existe no banco"
            )
        if existente.idempotency_key != evento.idempotency_key:
            raise MensagemIncorreta(
                "chave de idempotência do evento não confere com a do pagamento"
            )
        logger.info(
            "efeito já aplicado anteriormente; descartando",
            extra={
                "evento": f"{PREFIXO_LOG[self.fluxo]}Duplicado",
                "resultado": "duplicado",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "pagamento_id": evento.pagamento_id,
                "fila": self.topico_nome,
                "tentativa": tentativa,
                "motivo": (
                    f"pagamento já estava em '{existente.status}' "
                    "(UPDATE casou 0 linhas)"
                ),
            },
        )
        return False

    def _registrar_falha(
        self,
        evento: PedidoCriado | PagamentoRegistrado,
        motivo: str,
        *,
        terminal: bool,
    ) -> None:
        """Grava a tentativa e a causa na entidade do evento (evidência no banco).

        A escrita é separada da transação que aplicou o efeito: aquela foi
        desfeita pelo erro, e é justamente o registro da falha que precisa
        sobreviver a ele.

        `terminal` só faz sentido para o pedido, que tem um estado `falha`. O
        pagamento não ganha um estado terminal equivalente porque o desfecho já
        é `aprovado` ou `recusado`, e sobrescrevê-lo com "falhou" apagaria a
        resposta do gateway — que é justamente o que o cliente pagou precisa ver.
        Por isso o pagamento fica em `registrado`, com `motivo_falha` e
        `tentativas` preenchidos: dá para ver que o worker tentou e por quê,
        sem inventar um desfecho que o gateway não mandou.
        """
        campos: dict[str, Any] = {
            "tentativas": F("tentativas") + 1,
            "motivo_falha": motivo[:200],
        }
        if isinstance(evento, PagamentoRegistrado):
            models.Pagamento.objects.filter(pk=evento.pagamento_id).update(**campos)
            return
        if terminal:
            campos["status"] = models.Pedido.FALHA
        models.Pedido.objects.filter(pk=evento.pedido_id).update(**campos)

    # ------------------------------------------------------------------
    # Política de falhas: reentrega com backoff ou DLQ
    # ------------------------------------------------------------------
    def _reentregar_ou_dlq(
        self,
        mensagem: Any,
        cabecalhos: list[tuple[str, str]],
        corpo: bytes,
        evento: PedidoCriado,
        tentativa: int,
        erro: Exception,
    ) -> None:
        max_reentregas = settings.PEDIDO_MAX_REENTREGAS
        degraus = len(settings.PEDIDO_BACKOFF_SEGUNDOS)
        motivo = descrever(erro)

        # `tentativa >= max_reentregas`: a escada acabou. Já `tentativa + 1 >
        # degraus`: a política pede mais reentregas do que existem degraus
        # configurados — sem tópico de retry para este degrau, a única rota
        # honesta é a DLQ (e o log deixa isso explícito).
        if tentativa >= max_reentregas:
            # Terminal: última tentativa consumida. `tentativas` chega a
            # `max_reentregas` no total, que é o número que a escada promete.
            self._registrar_falha(evento, motivo, terminal=True)
            self._mandar_para_dlq(mensagem, cabecalhos, corpo, tentativa, motivo=motivo)
            return
        if tentativa + 1 > degraus:
            logger.error(
                "política de reentrega inconsistente: faltam degraus de backoff",
                extra={
                    "evento": "PoliticaInconsistente",
                    "resultado": "erro",
                    "broker": "kafka",
                    "pedido_id": evento.pedido_id,
                    "tentativa": tentativa,
                    "detalhe": (
                        f"max_reentregas={max_reentregas} > "
                        f"degraus configurados={degraus}"
                    ),
                },
            )
            self._registrar_falha(evento, motivo, terminal=True)
            self._mandar_para_dlq(mensagem, cabecalhos, corpo, tentativa, motivo=motivo)
            return

        degrau = tentativa + 1
        topico_retry = self.topologia.topico_retry(degrau)
        # A tentativa é gasta aqui, e não depois da republicação: a mensagem
        # foi processada com erro de qualquer jeito — se o `republicar` falhar,
        # a devolução da offset devolve a tentativa ao consumer em vez de
        # mascará-la.
        self._registrar_falha(evento, motivo, terminal=False)
        try:
            # A republicação vai **primeiro**; o offset da original só é
            # confirmado depois. Se esta publicação falhar, o offset não é
            # confirmado e a mensagem volta — trocar uma falha visível por uma
            # perda silenciosa seria o pior resultado possível.
            kafka_produtor.republicar(
                topico_retry,
                corpo,
                chave=mensagem.key() and mensagem.key().decode("utf-8", errors="replace"),
                cabecalhos=kafka_produtor.com_tentativa(cabecalhos, degrau, motivo=motivo),
            )
        except Exception as erro_republicacao:  # noqa: BLE001 - PublicacaoFalhou e Kafka
            logger.error(
                "falha ao republicar para retry; mensagem volta ao tópico principal",
                extra={
                    "evento": "ReentregaFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "pedido_id": evento.pedido_id,
                    "fila": self.topico_nome,
                    "tentativa": tentativa,
                    "erro": descrever(erro_republicacao),
                },
            )
            self._devolver(mensagem)
            return

        self._confirmar(mensagem)
        mensageria_metrics.record(FALHA)
        mensageria_metrics.record_reentrega()
        logger.warning(
            "falha no processamento; mensagem reentregue",
            extra={
                "evento": f"{PREFIXO_LOG[self.fluxo]}Falha",
                "resultado": "falha",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "pagamento_id": getattr(evento, "pagamento_id", None),
                "fila": topico_retry,
                "topico": topico_retry,
                "tentativa": degrau,
                # O atraso não é medido aqui: é o backoff do degrau, que o
                # replayer faz valer comparando a idade da mensagem. Fica
                # explícito para quem lê o log não achar que a espera foi do
                # worker.
                "duracao_ms": settings.PEDIDO_BACKOFF_SEGUNDOS[degrau - 1] * 1000,
                "erro": motivo,
                "motivo": (
                    f"reentrega {degrau}/{max_reentregas} em "
                    f"{settings.PEDIDO_BACKOFF_SEGUNDOS[degrau - 1]}s"
                ),
            },
        )

    def _mandar_para_dlq(
        self,
        mensagem: Any,
        cabecalhos: list[tuple[str, str]],
        corpo: bytes,
        tentativa: int,
        *,
        motivo: str,
        invalido: bool = False,
    ) -> None:
        """Move a mensagem para a DLQ (rota terminal) e encerra a tentativa."""
        if invalido:
            mensageria_metrics.record_invalida()

        try:
            kafka_produtor.republicar(
                self.topologia.topico_dlq,
                corpo,
                chave=mensagem.key() and mensagem.key().decode("utf-8", errors="replace"),
                cabecalhos=kafka_produtor.com_tentativa(cabecalhos, tentativa, motivo=motivo),
                client_id="synapseshop-worker-dlq",
            )
        except Exception as erro_dlq:  # noqa: BLE001 - PublicacaoFalhou e Kafka
            logger.error(
                "falha ao enviar para a DLQ; mensagem volta ao tópico principal",
                extra={
                    "evento": "DlqFalhou",
                    "resultado": "erro",
                    "broker": "kafka",
                    "fila": self.topico_nome,
                    "tentativa": tentativa,
                    "erro": descrever(erro_dlq),
                },
            )
            self._devolver(mensagem)
            return

        self._confirmar(mensagem)
        mensageria_metrics.record(DLQ)
        logger.error(
            "mensagem encaminhada para a DLQ",
            extra={
                "evento": f"{PREFIXO_LOG[self.fluxo]}Dlq",
                "resultado": "dlq",
                "broker": "kafka",
                "fluxo": self.fluxo,
                "fila": self.topologia.topico_dlq,
                "topico": self.topologia.topico_dlq,
                "tentativa": tentativa,
                "erro": motivo,
                "motivo": (
                    "contrato inválido (falha terminal, sem reentrega)"
                    if invalido
                    else f"tentativas esgotadas ({tentativa}/{settings.PEDIDO_MAX_REENTREGAS})"
                ),
            },
        )


def _erro_de_rebalance(erro: Exception) -> bool:
    """Diz se o erro é o broker recusando o commit por rebalance em andamento.

    Três sinais equivalentes, porque a exceção chega embrulhada em formatos
    diferentes conforme o ponto onde o commit falhou:

    * `KafkaError` do `confluent_kafka` — o caso direto;
    * `KafkaException` com `_KafkaError` embutido;
    * o texto da mensagem, como último recurso (o `descrever()` já o concatena).

    Os códigos são de `KafkaError`: `REBALANCE_IN_PROGRESS` (-175) e
    `ILLEGAL_GENERATION` (-22). Nenhum dos dois indica perda de mensagem — a
    partição já tem outro dono, e o offset é confirmado por ele.
    """
    codigos_rebalance = {-175, -22, -136}
    try:
        from confluent_kafka import KafkaException

        candidatos: list[Any] = [erro]
        if isinstance(erro, KafkaException):
            internos = getattr(erro, "args", ())
            candidatos.extend(internos)
        for candidato in candidatos:
            codigo = getattr(candidato, "code", None)
            if callable(codigo):  # KafkaError.code() é método, não atributo
                try:
                    # Só `TypeError` é coberto: `KafkaError` não
                    # herda de `BaseException`, então num `except` ele
                    # nunca casa com nada e só pareceria estar protegendo
                    # contra um erro do broker que este ponto não vê.
                    codigo = codigo()
                except TypeError:
                    codigo = None
            if isinstance(codigo, int) and codigo in codigos_rebalance:
                return True
    except ImportError:
        pass

    texto = descrever(erro).lower()
    return any(
        marca in texto
        for marca in (
            "illegal_generation",
            "rebalance_in_progress",
            "group generation id is not valid",
            "not valid for group",
        )
    )


def _tentativa(cabecalhos: list[tuple[str, str]]) -> int:
    """Contador de tentativas que viaja nos cabeçalhos da mensagem.

    O `x-tentativa` é o NOSSO contador: sobrevive a qualquer coisa que o broker
    faça com a mensagem e fica explícito no código. (No AMQP ele convivia com
    o `x-death` do próprio RabbitMQ; no Kafka não existe equivalente de
    broker, porque a retenção não "devolve" a mensagem — ela apaga.)
    """
    dicionario = dict(cabecalhos)
    try:
        return int(dicionario.get(HEADER_TENTATIVA, 0))
    except (TypeError, ValueError):
        return 0