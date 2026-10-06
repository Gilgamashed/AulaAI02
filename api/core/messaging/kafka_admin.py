"""Administração dos tópicos Kafka: criar, purgar e inspecionar.

`kafka_topologia.py` sabe **o que** a topologia deve ser; este módulo sabe
**como pedir isso ao broker** (API de administração do `confluent_kafka`).

A criação é explícita e vem da aplicação (o broker roda com
`auto.create.topics.enable=false`) por dois motivos já registrados na
topologia: partições são o eixo de paralelismo e não podem mudar depois; e
`retention.ms` é um parâmetro que a spec pede para ser demonstrado, não algo
que se aceita como padrão do servidor.

Um módulo só para isso também evita uma dependência do `confluent_kafka` no
caminho de leitura da topologia: `kafka_topologia.py` continua importável (e
testável) num ambiente onde a biblioteca do Kafka não está instalada — que é o
caso de quem roda o RabbitMQ.
"""

from __future__ import annotations

import logging
from typing import Any

from . import kafka_topologia

# `descrever` (estado dos tópicos) é a API pública deste módulo e colidiria com
# o `descrever` de `erros.py` (descrição de exceção). O import entra com
# apelido para não obrigar quem chama a renomear a função do módulo.
from .erros import descrever as descrever_erro
from .kafka_topologia import TopologiaKafka, topicos_declarados

logger = logging.getLogger("core.messaging")

# Grupo fictício usado só para consultar watermarks (offset inicial/final).
# Um `Consumer` só entra no grupo ao fazer `subscribe`, e aqui nunca fazemos:
# o objeto serve apenas de cliente de leitura de metadados.
GRUPO_INSPECAO = "synapseshop-inspecao"


def _retencao(admin: Any, nomes: list[str]) -> dict[str, Any]:
    """`retention.ms` de cada tópico, via `describe_configs`.

    Não vem no metadata (`TopicMetadata` só traz partições e erro — foi o que o
    `AttributeError` no startup expôs), e sim na API de configuração, que é
    separada. Uma chamada para todos os tópicos: `describe_configs` aceita a
    lista inteira, e chamado por tópico custaria um round-trip por tópico no
    caminho de startup, que é justamente onde a latência importa menos que a
    clareza do erro.

    O valor sai de `ConfigEntry.value`: o resultado do future é um dicionário de
    nome para `ConfigEntry`, e `str(ConfigEntry)` é a descrição legível do
    atributo (`"ConfigEntry(retention.ms=...): value=... is_read_only=False..."`)
    — usá-lo direto no relatório imprimiria o objeto inteiro, não a retenção.

    Tópico inexistente devolve `None` em vez de exceção: a lista de nomes vem da
    topologia declarada, e o broker pode não ter todos ainda.
    """
    from confluent_kafka.admin import ConfigResource

    if not nomes:
        return {}
    recursos = [ConfigResource(ConfigResource.Type.TOPIC, nome) for nome in nomes]
    try:
        futuros = admin.describe_configs(recursos, request_timeout=10)
    except Exception as erro:  # noqa: BLE001 - descrição é informativa
        logger.warning(
            "não foi possível ler a retenção dos tópicos",
            extra={
                "evento": "TopicosDescritos",
                "resultado": "erro",
                "broker": "kafka",
                "erro": descrever_erro(erro),
            },
        )
        return {}

    saida: dict[str, Any] = {}
    for recurso, futuro in futuros.items():
        nome = recurso.name
        try:
            entrada = futuro.result().get("retention.ms")
            if entrada is None:
                saida[nome] = None
                continue
            # `ConfigEntry.value` é texto; o relatório é consumido por script, e
            # comparar retenção como string ("604800000" vs "2592000000") seria
            # comparação de string, não de número.
            saida[nome] = (
                int(entrada.value) if entrada.value.lstrip("-").isdigit() else entrada.value
            )
        except Exception as erro:  # noqa: BLE001 - um tópico sem config não derruba o resto
            logger.warning(
                "retenção não lida para o tópico",
                extra={
                    "evento": "TopicosDescritos",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": nome,
                    "erro": descrever_erro(erro),
                },
            )
            saida[nome] = None
    return saida


def criar_topicos(
    topologias: TopologiaKafka | list[TopologiaKafka] | None = None,
) -> dict[str, Any]:
    """Cria os tópicos de uma ou mais topologias. Idempotente: roda em todo startup.

    Declarar é o equivalente Kafka de `queue_declare`/`exchange_declare` do
    AMQP: existe ou não existe, e repetir com os mesmos parâmetros é no-op.
    Por isso tanto o produtor quanto o worker chamam esta função no início —
    não existe ordem de subida entre eles, e o primeiro que subir cria tudo.

    A diferença que importa: se o tópico já existe com **outro** número de
    partições, o broker aceita um aumento e recusa uma redução. Em vez de
    engolir isso, devolvemos no resumo e logamos — porque um tópico com 1
    partição quando a spec pede 3 é a diferença entre "paralelismo de 3" e
    "paralelismo de 1", e isso não pode aparecer só no console.

    Aceita uma topologia ou uma lista porque a Aula 11 tem **dois fluxos**, e o
    comando `declarar_topicos_kafka` declara os dois de uma vez: passar pelo
    `list_topics` e pelo `create_topics` duas vezes seria o dobro de chamadas
    de admin para o mesmo resultado. Um `AdminClient` e um `list_topics` para os
    dois fluxos, e o log `TopicosDeclarados` sai uma vez com o `fluxo` de cada
    tópico.
    """
    from confluent_kafka import KafkaException
    from confluent_kafka.admin import AdminClient, NewTopic

    lista = _normalizar_topologias(topologias)

    admin = AdminClient(kafka_topologia.config_produtor("synapseshop-topicos"))
    fluxos_por_topico: dict[str, str] = {}
    desejados: list[dict[str, Any]] = []
    for topologia in lista:
        fluxos_por_topico[topologia.topico] = topologia.fluxo
        fluxos_por_topico[topologia.topico_dlq] = topologia.fluxo
        for item in topicos_declarados(topologia):
            fluxos_por_topico.setdefault(item["nome"], topologia.fluxo)
            desejados.append(item)

    existentes = admin.list_topics(timeout=10)
    criar: list[Any] = []
    resumo: list[dict[str, Any]] = []
    for topico in desejados:
        anterior = existentes.topics.get(topico["nome"])
        if anterior is None:
            criar.append(
                NewTopic(
                    topico["nome"],
                    num_partitions=topico["particoes"],
                    replication_factor=topico["replicas"],
                    config=topico["config"],
                )
            )
            resumo.append(
                {
                    "topico": topico["nome"],
                    "fluxo": fluxos_por_topico.get(topico["nome"]),
                    "acao": "criado",
                    "particoes": topico["particoes"],
                    "retencao_ms": topico["config"]["retention.ms"],
                }
            )
            continue

        resumo.append(
            {
                "topico": topico["nome"],
                "fluxo": fluxos_por_topico.get(topico["nome"]),
                "acao": "ja existia",
                "particoes": len(anterior.partitions),
                "particoes_declaradas": topico["particoes"],
                # Só o declarado aparece aqui: a retenção efetiva do tópico já
                # existente é lida por `descrever`, que é o comando de
                # inspeção — o startup não precisa pagar uma chamada de
                # configuração por tópico.
                "retencao_ms": topico["config"]["retention.ms"],
            }
        )

    criados: list[str] = []
    if criar:
        futures = admin.create_topics(criar, request_timeout=20)
        for nome, futuro in futures.items():
            try:
                futuro.result()
                criados.append(nome)
            except KafkaException as erro:
                # Corrida entre API e worker subindo ao mesmo tempo: os dois
                # chegam aqui e um perde. TOPIC_ALREADY_EXISTS é sucesso, não
                # erro — é o mesmo "INSERT IF NOT EXISTS" do AMQP.
                if erro.args and erro.args[0].code() == _codigo_topico_existente():
                    logger.info(
                        "tópico já criado por outro processo",
                        extra={
                            "evento": "TopicosDeclarados",
                            "resultado": "ok",
                            "topico": nome,
                        },
                    )
                    continue
                raise

    divergences = [
        item
        for item in resumo
        if item.get("particoes_declaradas")
        and item["particoes"] != item["particoes_declaradas"]
    ]
    configuracoes = {topologia.fluxo: topologia.resumo() for topologia in lista}
    # Com um único fluxo o `detalhe` continua sendo a topologia em si (o que os
    # logs da Aula 9/10 já mostravam); com dois, entra a lista por fluxo, senão o
    # startup do `worker-pagamentos` descreveria o fluxo de pedidos como se fosse
    # o dele. `lista` nunca vem vazia (o `None` virou `todas()`), mas o `get` com
    # default evita um `StopIteration` opaco se alguém passar `[]`.
    principal = configuracoes.get("pedidos") or (
        lista[0].resumo() if lista else {}
    )
    logger.info(
        "topologia declarada",
        extra={
            "evento": "TopicosDeclarados",
            "resultado": "erro" if divergences else "ok",
            "broker": "kafka",
            "detalhe": {
                **principal,
                "fluxos": configuracoes,
                "topicos": resumo,
                "criados": criados,
            },
        },
    )
    return {
        "broker": "kafka",
        "criados": criados,
        "divergencias": divergences,
        "topicos": resumo,
        "configuracao": (
            next(iter(configuracoes.values()))
            if len(configuracoes) == 1
            else configuracoes
        ),
    }


def _codigo_topico_existente() -> Any:
    """`KafkaError.TOPIC_ALREADY_EXISTS`, importado sob demanda.

    Existe como função (e não constante de módulo) para o `confluent_kafka` não
    ser importado quando este módulo é carregado num ambiente sem a lib.
    """
    from confluent_kafka import KafkaError

    return KafkaError.TOPIC_ALREADY_EXISTS


def purgar(
    topicos: list[str] | None = None,
    topologias: TopologiaKafka | list[TopologiaKafka] | None = None,
) -> dict[str, Any]:
    """Apaga (e recria) os tópicos — o `--purgar` da medição.

    Apagar é o que limpa de verdade: em Kafka, "esvaziar" um tópico não
    existe, e um consumidor com `auto.offset.reset=earliest` voltaria a ler
    tudo o que está retido. Por isso o caminho é `delete` + `create`, e o
    `--purgar` do `scripts/measure_messaging.py` precisa deste módulo, e não de
    um comando de broker qualquer.

    Sem `topicos` e sem `topologias`, apaga os **dois** fluxos: um `--purgar`
    que limpasse só `pedidos.criados` deixaria o histórico de pagamentos intacto,
    e a medição seguinte publicaria eventos que o worker veria como duplicata —
    resultado silenciosamente errado, do tipo que só aparece no número do
    relatório final.
    """
    from confluent_kafka.admin import AdminClient

    lista = _normalizar_topologias(topologias)
    alvos = topicos or [
        topico
        for topologia in lista
        for topico in [topologia.topico, *topologia.topicos_retry(), topologia.topico_dlq]
    ]
    admin = AdminClient(kafka_topologia.config_produtor("synapseshop-purge"))

    apagados: list[str] = []
    # A chave do futuro É o nome do tópico; o resultado (`futuro.result()`) é
    # `None` na API de delete_topics, então o nome vem do mapa — e não de um
    # atributo que o resultado não expõe.
    for nome, futuro in admin.delete_topics(alvos, operation_timeout=30).items():
        try:
            futuro.result()
            apagados.append(nome)
        except Exception as erro:  # noqa: BLE001 - apagar é melhor-effort
            logger.warning(
                "não foi possível apagar o tópico",
                extra={
                    "evento": "TopicosPurgados",
                    "resultado": "erro",
                    "broker": "kafka",
                    "topico": nome,
                    "erro": descrever_erro(erro),
                },
            )

    # Recria logo em seguida: quem chama o purge quer o pipeline pronto, e a
    # criação é o mesmo caminho idempotente do startup.
    criados = criar_topicos(lista)
    return {"apagados": apagados, **criados}


def descrever(
    topologias: TopologiaKafka | list[TopologiaKafka] | None = None,
) -> dict[str, Any]:
    """Estado dos tópicos: partições, retenção, offsets, lag e membros do grupo.

    É o `--json` do `declarar_topicos_kafka`, e a fonte de verdade que o
    `scripts/measure_messaging.py` usa no lugar da Management API do RabbitMQ
    (`:15672`). Três números por partição:

    | número           | como é obtido                                       |
    | ---------------- | --------------------------------------------------- |
    | `fim`            | watermark *high* — offset da última mensagem viva   |
    | `inicio`         | watermark *low* — onde a retenção começa            |
    | `commit`         | offset que o grupo já confirmou                   |
    | `lag`            | `fim - commit` — o que ainda está por fazer         |

    `lag` é o número que responde "o worker está acompanhando?", que no AMQP
    era `messages_ready` da Management API.

    Sem argumento, descreve os dois fluxos: o `lag` de `pagamentos.registrados`
    é tão diagnóstico quanto o de `pedidos.criados`, e é justamente o que se
    quer quando um POST de pagamento devolveu 503.
    """
    from confluent_kafka import Consumer, TopicPartition
    from confluent_kafka.admin import AdminClient

    lista = _normalizar_topologias(topologias)
    admin = AdminClient(kafka_topologia.config_produtor("synapseshop-inspecao"))
    metadados = admin.list_topics(timeout=10)

    # `_grupos` roda ANTES da montagem porque é ele que sabe o offset confirmado
    # de cada partição — e ele precisa da API administrativa para isso. Ler o
    # offset pelo `Consumer` de inspeção devolveria sempre o offset do grupo de
    # inspeção (que nunca consome nada), e o relatório mostraria `commit: null`
    # e `lag: null` para sempre, inclusive com o worker perfeitamente em dia.
    grupos = [saida for topologia in lista for saida in _grupos(admin, metadados, topologia)]
    # Os tópicos são disjuntos entre os grupos (principal no do worker, retry no
    # do replayer), então um dicionário "marca -> offset" único basta.
    confirmados: dict[str, int] = {}
    for grupo in grupos:
        confirmados.update(grupo["offset_confirmado"])

    config = kafka_topologia.config_consumidor(GRUPO_INSPECAO, "synapseshop-inspecao")
    # `session.timeout.ms` baixo e `group.id` fictício: este consumidor nunca
    # assina tópico nenhum, então não entra no grupo nem aparece na lista de
    # membros. Ele existe só porque o `Consumer` é o objeto que sabe ler
    # watermarks.
    config["session.timeout.ms"] = 6000
    consumidor = Consumer(config)
    try:
        topicos: list[dict[str, Any]] = []
        alvos = [
            topico
            for topologia in lista
            for topico in [topologia.topico, *topologia.topicos_retry(), topologia.topico_dlq]
        ]
        # A retenção vem da API de configuração, não do metadata (ver
        # `_retencao`).
        retencoes = _retencao(admin, alvos)
        for nome in alvos:
            encontrado = metadados.topics.get(nome)
            if encontrado is None:
                topicos.append({"topico": nome, "existe": False, "particoes": []})
                continue

            particoes = []
            for indice in range(len(encontrado.partitions)):
                marca = TopicPartition(nome, indice)
                inicio, fim = consumidor.get_watermark_offsets(marca, timeout=10)
                commit = confirmados.get(f"{nome}:{indice}")
                particoes.append(
                    {
                        "particao": indice,
                        "inicio": inicio,
                        "fim": fim,
                        "commit": commit,
                        # `None` quando o grupo nunca confirmou nada (grupo
                        # novo): reportar 0 seria mentir sobre a fila.
                        "lag": None if commit is None else max(0, fim - commit),
                        "líder": encontrado.partitions[indice].leader,
                    }
                )
            topicos.append(
                {
                    "topico": nome,
                    "existe": True,
                    "particoes": particoes,
                    "retencao_ms": retencoes.get(nome),
                    "mensagens": sum(p["fim"] - p["inicio"] for p in particoes),
                }
            )
    finally:
        consumidor.close()

    return {"broker": "kafka", "topicos": topicos, "grupos": grupos}


def _normalizar_topologias(
    topologias: TopologiaKafka | list[TopologiaKafka] | None,
) -> list[TopologiaKafka]:
    """Transforma o argumento "uma topologia, várias ou nenhuma" em lista.

    Centraliza a mesma normalização em `criar_topicos`, `purgar` e `descrever`:
    o comportamento de "sem argumento = todos os fluxos" precisa ser o mesmo nos
    três, senão um `--purgar` limpo e um `--json` mentindo Would sejam a mesma
    omissão copiada em dois lugares.
    """
    if topologias is None:
        return TopologiaKafka.todas()
    if isinstance(topologias, TopologiaKafka):
        return [topologias]
    return list(topologias)


def _grupos(
    admin: Any, metadados: Any, topologia: TopologiaKafka
) -> list[dict[str, Any]]:
    """Membros e offset confirmado de cada grupo de consumidores relevante.

    Os offsets vêm da **API administrativa** (`list_consumer_group_offsets`),
    que aceita o nome do grupo como parâmetro. A alternativa seria criar um
    `Consumer` e chamar `committed()`, mas `committed()` responde pelo grupo do
    *próprio* consumidor — o mesmo número para `synapseshop-pedidos` e para
    `synapseshop-replay` seria devolvido, e o relatório de offsets mentiria sem
    dar nenhum sinal disso.

    Só entram no relatório partições que existem nos METADADOS: os tópicos de
    retry têm 1 partição, e pedir o offset das partições 1 e 2 de um tópico que
    não as tem é pedir um erro do broker em vez de um número.
    """
    from confluent_kafka import TopicPartition
    from confluent_kafka._model import ConsumerGroupTopicPartitions

    saida: list[dict[str, Any]] = []
    # `list_consumer_groups()` devolve o *listing* leve (id, estado, tipo) e
    # `describe_consumer_groups()` traz os membros. A listagem ainda é usada para
    # dizer "o grupo existe no cluster", porque um grupo que ainda não confirmou
    # offset não aparece na listagem, e é justo esse caso (grupo novo, antes da
    # primeira mensagem) que o relatório precisa mostrar.
    resultado = admin.list_consumer_groups(request_timeout=10).result()
    # `ListConsumerGroupsResult` (valid/errors) em uma versão, lista direta em
    # outra: aceitar os dois formatos evita prender o projeto a uma versão.
    grupos_conhecidos = {d.group_id for d in getattr(resultado, "valid", resultado)}
    descritos = admin.describe_consumer_groups(
        [topologia.grupo, topologia.grupo_replay], request_timeout=10
    )

    for grupo_id in (topologia.grupo, topologia.grupo_replay):
        descricao = descritos[grupo_id].result(timeout=15)
        membros = [
            {"member_id": m.member_id, "cliente": m.client_id} for m in descricao.members
        ]
        topicos_existentes = {
            topico: metadados.topics[topico]
            for topico in (topologia.topico, *topologia.topicos_retry())
            if topico in metadados.topics
        }
        pedidos = [
            ConsumerGroupTopicPartitions(
                group_id=grupo_id,
                topic_partitions=[
                    TopicPartition(topico, indice)
                    for topico, encontrado in topicos_existentes.items()
                    for indice in range(len(encontrado.partitions))
                ],
            )
        ]
        confirmados: dict[str, int] = {}
        try:
            resposta = admin.list_consumer_group_offsets(
                pedidos, request_timeout=10
            )[grupo_id].result(timeout=15)
        except Exception as erro:  # noqa: BLE001 - relatório não pode estourar
            logger.warning(
                "falha ao ler os offsets do grupo de consumidores",
                extra={
                    "evento": "GruposIndisponiveis",
                    "resultado": "erro",
                    "broker": "kafka",
                    "grupo": grupo_id,
                    "erro": descrever_erro(erro),
                },
            )
        else:
            for marca in resposta.topic_partitions:
                if marca.offset >= 0:
                    confirmados[f"{marca.topic}:{marca.partition}"] = marca.offset
        saida.append(
            {
                "grupo": grupo_id,
                "existe": grupo_id in grupos_conhecidos,
                "estado": str(descricao.state).rsplit(".", 1)[-1],
                "membros": membros,
                "consumidores": len(membros),
                "offset_confirmado": confirmados,
            }
        )
    return saida


def topicos_do_grupo(grupo: str, topologia: TopologiaKafka) -> list[str]:
    """Tópicos que um grupo realmente consome (usado pelo reset de offsets).

    Mover o offset de um grupo em um tópico que ele não consome não tem efeito
    nenhum, e em algumas versões do broker é recusado. Como os dois grupos deste
    projeto têm escopos distintos — o worker só o tópico principal, o replayer só
    os de retry — a lista é derivada do grupo, não da topologia inteira.
    """
    if grupo == topologia.grupo_replay:
        return topologia.topicos_retry()
    return [topologia.topico]


def resetar_offsets(
    grupo: str,
    para: str = "earliest",
    fluxo: str | None = None,
) -> dict[str, Any]:
    """Move o offset confirmado do grupo, para testar **replay**.

    É a demonstração da diferença mais visível entre um log distribuído e uma
    fila: a fila se esvazia, o log fica. Mover o offset para `earliest` faz o
    consumidor reler **toda** a retenção do tópico. E o que a aplicação faz com
    isso é o teste honesto da idempotência: cada mensagem devolvida é
    reconhecida como duplicata e **nenhum** pedido muda de estado.

    Uso operacional, e por isso é um comando separado: em produção ninguém
    ressuscita um grupo de consumidores movendo o offset para `earliest` sem
    querer.
    """
    from confluent_kafka import Consumer, TopicPartition
    from confluent_kafka._model import ConsumerGroupTopicPartitions
    from confluent_kafka.admin import AdminClient

    if para not in {"earliest", "latest"}:
        raise ValueError(f"posição inválida: {para} (use 'earliest' ou 'latest')")

    # `fluxo` só é usado para achar a topologia a partir do próprio grupo: o
    # grupo já identifica o fluxo (`synapseshop-pagamentos` só existe lá), então
    # sem o argumento o grupo é procurado em todos antes de cair no principal.
    if fluxo is not None:
        topologia = TopologiaKafka.do_fluxo(fluxo)
    else:
        combinacao = next(
            (
                t
                for t in TopologiaKafka.todas()
                if grupo in (t.grupo, t.grupo_replay)
            ),
            None,
        )
        if combinacao is None:
            raise ValueError(
                f"grupo '{grupo}' não pertence a nenhum fluxo conhecido; use "
                "--fluxo para dizer a qual topologia ele pertence."
            )
        topologia = combinacao
    admin = AdminClient(kafka_topologia.config_produtor("synapseshop-reset"))
    metadados = admin.list_topics(timeout=10)

    config = kafka_topologia.config_consumidor(GRUPO_INSPECAO, "synapseshop-reset")
    config["session.timeout.ms"] = 6000
    leitor = Consumer(config)
    try:
        marcas: list[TopicPartition] = []
        for nome in topicos_do_grupo(grupo, topologia):
            encontrado = metadados.topics.get(nome)
            if encontrado is None:
                continue
            for indice in range(len(encontrado.partitions)):
                marcas.append(TopicPartition(nome, indice))
        if not marcas:
            return {
                "grupo": grupo,
                "posicao": para,
                "particoes": [],
                "erro": "nenhum tópico do grupo existe",
            }

        for marca in marcas:
            inicio, _fim = leitor.get_watermark_offsets(marca, timeout=10)
            marca.offset = inicio if para == "earliest" else _fim
        # A assinatura real de `alter_consumer_group_offsets` recebe uma LISTA de
        # `ConsumerGroupTopicPartitions` (grupo + partições), e não
        # `(group_id, [TopicPartition])`: passar positionais quebrava com
        # `TypeError: takes 2 positional arguments but 3 were given`.
        requisicao = [ConsumerGroupTopicPartitions(group_id=grupo, topic_partitions=marcas)]
        # E devolve um DICIONARIO de futuros (um por requisição), não um futuro
        # único: só um grupo entra por chamada, mas a API é a mesma das demais
        # operações em lote, e tratar isso como futuro único estourava com
        # `AttributeError: 'dict' object has no attribute 'result'`.
        futuros = admin.alter_consumer_group_offsets(requisicao, request_timeout=20)
        for futuro in futuros.values():
            futuro.result()
    finally:
        leitor.close()

    movidos = [
        {"topico": marca.topic, "particao": marca.partition, "offset": marca.offset}
        for marca in marcas
    ]
    logger.warning(
        "offset do grupo movido (replay)",
        extra={
            "evento": "OffsetsResetados",
            "resultado": "ok",
            "broker": "kafka",
            "grupo": grupo,
            "detalhe": {"posicao": para, "particoes": movidos},
        },
    )
    return {"grupo": grupo, "posicao": para, "particoes": movidos}