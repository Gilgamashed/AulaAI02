"""`manage.py declarar_topicos_kafka` — cria e inspeciona a topologia Kafka.

A declaração é **da aplicação**, não do broker: o `apache/kafka` do compose roda
com `auto.create.topics.enable=false`, e este comando (ou o próprio produtor/
worker, que chamam `criar_topicos` no startup) é quem decide quantas partições
e qual retenção cada tópico tem. Ver `core.messaging.kafka_topologia` para o
porquê de cada parâmetro.

Uso típico, na ordem em que a README descreve a aula:

    # 1. cria a topologia (idempotente: pode repetir)
    python manage.py declarar_topicos_kafka

    # 2. confere partições, retenção, offsets confirmados e lag
    python manage.py declarar_topicos_kafka --json

    # 3. demonstra o replay: move o offset do grupo para o início do log
    python manage.py declarar_topicos_kafka --resetar-offsets earliest

    # 4. limpa tudo e recria (é o `--purgar` da medição)
    python manage.py declarar_topicos_kafka --purgar

A Aula 11 dá um segundo fluxo, `pagamentos.registrados`. Sem argumento, o
comando age nos **dois**: declarar só o de pedidos deixaria o tópico de
pagamentos ausente, e o sintoma (falha ao publicar) só apareceria no POST de
pagamento, no meio da demonstração. Com `--fluxo`, dá para olhar um fluxo por
vez — que é o que interessa quando se está depurando.
"""

from __future__ import annotations

import json

from core.messaging import broker as mensageria
from core.messaging import kafka_admin, kafka_topologia
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Declara a topologia Kafka (tópicos, partições e retenção), inspeciona "
        "offsets/lag, move o offset do grupo para replay e purga os tópicos. "
        "Sem --fluxo, age nos fluxos 'pedidos' e 'pagamentos'. Só faz sentido "
        "com MENSAGERIA_BROKER=kafka."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fluxo",
            choices=mensageria.FLUXOS,
            default=None,
            help=(
                "Restringe a operação a um fluxo ('pedidos' ou 'pagamentos'). "
                "Padrão: os dois."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="como_json",
            help="Saída em JSON (é o formato que o measure_messaging.py consome).",
        )
        parser.add_argument(
            "--purgar",
            action="store_true",
            help=(
                "Apaga os tópicos da topologia e recria em seguida. É o que "
                "limpa de verdade: em Kafka não existe 'esvaziar' um tópico, e "
                "com auto.offset.reset=earliest um consumidor voltaria a ler "
                "tudo que ainda estivesse retido."
            ),
        )
        parser.add_argument(
            "--resetar-offsets",
            metavar="POSICAO",
            default=None,
            help=(
                "Move o offset confirmado do grupo para 'earliest' ou 'latest' "
                "— é o teste de replay: o consumidor relê o log e a "
                "idempotência precisa impedir qualquer efeito duplicado."
            ),
        )
        parser.add_argument(
            "--grupo",
            default=None,
help=(
                "Grupo usado pelo --resetar-offsets. Padrão: o grupo de "
                "consumidores do fluxo escolhido (KAFKA_GRUPO_CONSUMIDORES no "
                "fluxo de pedidos). Use KAFKA_GRUPO_REPLAY para repontuar "
                "também as mensagens de retry."
            ),
        )

    def handle(self, *args, **options) -> None:
        if mensageria.broker_ativo() != mensageria.KAFKA:
            raise CommandError(
                "este comando é do Kafka, mas MENSAGERIA_BROKER="
                f"'{settings.MENSAGERIA_BROKER}'. Para o RabbitMQ não há "
                "tópicos: use a Management API (:15672) ou `manage.py "
                "consumir_pedidos --destino <fila>`."
            )

        # `None` = todos os fluxos; com --fluxo, só o escolhido. A lista vem de
        # `TopologiaKafka.todas()` para que um terceiro fluxo futuro apareça aqui
        # sem precisar lembrar deste comando.
        topologias = (
            [kafka_topologia.TopologiaKafka.do_fluxo(options["fluxo"])]
            if options["fluxo"]
            else kafka_topologia.TopologiaKafka.todas()
        )
        principal = topologias[0]
        saida: dict | None = None

        if options["purgar"]:
            self.stdout.write(
                "purgando os tópicos da topologia ("
                f"{', '.join(t.fluxo for t in topologias)})..."
            )
            # `topologias=` por nome: o primeiro parâmetro de `purgar` é a lista
            # de NOMES de tópico, e passar a lista de topologias ali apagaria
            # objetos, não tópicos.
            saida = kafka_admin.purgar(topologias=topologias)
        elif options["resetar_offsets"]:
            grupo = options["grupo"] or principal.grupo
            self.stdout.write(f"movendo o offset do grupo '{grupo}' para {options['resetar_offsets']}...")
            saida = kafka_admin.resetar_offsets(
                grupo, options["resetar_offsets"], fluxo=options["fluxo"]
            )
        elif options["como_json"]:
            saida = kafka_admin.descrever(topologias)
        else:
            saida = kafka_admin.criar_topicos(topologias)

        if options["como_json"]:
            self.stdout.write(json.dumps(saida, indent=2, ensure_ascii=False, default=str))
            return

        self._relatorio(saida, options)

    def _relatorio(self, saida: dict, options) -> None:
        """Impressão legível, por subcomando — o `--json` é para máquina."""
        if options["resetar_offsets"]:
            if saida.get("erro"):
                self.stderr.write(f"erro: {saida['erro']}")
                return
            self.stdout.write(
                f"grupo {saida['grupo']} -> {saida['posicao']} "
                f"({len(saida['particoes'])} partição(ões))"
            )
            for item in saida["particoes"]:
                self.stdout.write(
                    f"  {item['topico']}[{item['particao']}] = {item['offset']}"
                )
            return

        for topico in saida.get("topicos", []):
            acao = topico.get("acao", "")
            if acao:
                self.stdout.write(
                    f"  {topico['topico']}: {acao} "
                    f"({topico.get('particoes')} partições, "
                    f"retenção {topico.get('retencao_ms')} ms)"
                )
                if topico.get("particoes_declaradas") and (
                    topico["particoes"] != topico["particoes_declaradas"]
                ):
                    self.stderr.write(
                        f"    ATENÇÃO: existem {topico['particoes']} partições e a "
                        f"setting pede {topico['particoes_declaradas']}. "
                        "O broker aceita aumentar e recusa reduzir: para corrigir, "
                        "apague o tópico (--purgar) sabendo que os offsets vão "
                        "junto."
                    )
            elif topico.get("existe"):
                self.stdout.write(
                    f"  {topico['topico']}: {topico['mensagens']} mensagem(ns), "
                    f"retenção {topico.get('retencao_ms')} ms"
                )
                for particao in topico["particoes"]:
                    self.stdout.write(
                        f"    partição {particao['particao']}: "
                        f"início {particao['inicio']} fim {particao['fim']} "
                        f"commit {particao['commit']} lag {particao['lag']}"
                    )
            else:
                self.stdout.write(f"  {topico['topico']}: não existe")

        for grupo in saida.get("grupos", []):
            self.stdout.write(
                f"  grupo {grupo['grupo']}: {grupo['consumidores']} consumidor(es), "
                f"{len(grupo['offset_confirmado'])} offset(s) confirmado(s)"
            )

        for divergencia in saida.get("divergencias", []) or []:
            self.stderr.write(
                f"  divergência: {divergencia['topico']} com "
                f"{divergencia['particoes']} partições, mas a setting pede "
                f"{divergencia['particoes_declaradas']}"
            )