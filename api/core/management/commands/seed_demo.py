"""Massa de demonstração para a apresentação final (Aula 25).

O comando é manual, idempotente e sem rede. Ele complementa o `seed_auth`
(que cria os papéis e os usuários demo) com catálogo, pedidos históricos,
pagamentos e notificações, para que o painel de vendas e o roteiro de
apresentação tenham o que mostrar sem depender de cliques prévios.

Decisões:

- chaves estáveis (`sku`, `idempotency_key`) tornam a segunda execução um
  no-op — nenhum dado é apagado ou duplicado;
- as datas são ajustadas com `update()` depois do `create`, porque
  `created_at`/`enviada_em` são `auto_now_add` e não aceitam valor no insert;
- os snapshots de item seguem o mesmo formato gravado pela API
  (`sku`, `quantidade`, `preco_unitario`, `produto_id`), para que a massa seja
  indistinguível de um pedido real.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import notificacoes
from core.models import Category, Item, Notificacao, Pagamento, Pedido

CATEGORIAS: tuple[dict[str, Any], ...] = (
    {
        "name": "Smartphones",
        "slug": "smartphones",
        "description": "Celulares e smartphones das principais marcas.",
    },
    {
        "name": "Notebooks",
        "slug": "notebooks",
        "description": "Notebooks para trabalho, estudo e uso doméstico.",
    },
    {
        "name": "Áudio",
        "slug": "audio",
        "description": "Fones, headsets e caixas de som.",
    },
    {
        "name": "Acessórios",
        "slug": "acessorios",
        "description": "Periféricos e acessórios para o dia a dia.",
    },
)

PRODUTOS: tuple[dict[str, Any], ...] = (
    {
        "sku": "SMT-IP15-128",
        "name": "iPhone 15 128 GB",
        "brand": "Apple",
        "model": "iPhone 15",
        "category": "smartphones",
        "price": Decimal("4999.00"),
        "description": "Smartphone com tela Super Retina XDR de 6,1 polegadas.",
        "specifications": {
            "tela": "6,1 polegadas",
            "armazenamento": "128 GB",
            "cor": "Preto",
        },
        "warranty_months": 12,
    },
    {
        "sku": "SMT-GLX-S24",
        "name": "Galaxy S24 256 GB",
        "brand": "Samsung",
        "model": "Galaxy S24",
        "category": "smartphones",
        "price": Decimal("4299.00"),
        "description": "Smartphone com tela Dynamic AMOLED e recursos de IA.",
        "specifications": {
            "tela": "6,2 polegadas",
            "armazenamento": "256 GB",
            "cor": "Cinza",
        },
        "warranty_months": 12,
    },
    {
        "sku": "SMT-MOT-G54",
        "name": "Moto G54 5G",
        "brand": "Motorola",
        "model": "Moto G54",
        "category": "smartphones",
        "price": Decimal("1799.00"),
        "description": "Smartphone 5G com bateria de longa duração.",
        "specifications": {
            "tela": "6,5 polegadas",
            "armazenamento": "256 GB",
            "cor": "Azul",
        },
        "warranty_months": 12,
    },
    {
        "sku": "NBT-DLL-I5",
        "name": "Inspiron 15 Core i5",
        "brand": "Dell",
        "model": "Inspiron 15",
        "category": "notebooks",
        "price": Decimal("4599.00"),
        "description": "Notebook para produtividade com processador Intel Core i5.",
        "specifications": {
            "processador": "Intel Core i5",
            "memoria": "16 GB",
            "armazenamento": "512 GB SSD",
        },
        "warranty_months": 24,
    },
    {
        "sku": "NBT-ACC-A515",
        "name": "Aspire 5 Core i5",
        "brand": "Acer",
        "model": "Aspire 5",
        "category": "notebooks",
        "price": Decimal("3299.00"),
        "description": "Notebook leve com tela Full HD e SSD.",
        "specifications": {
            "processador": "Intel Core i5",
            "memoria": "8 GB",
            "armazenamento": "256 GB SSD",
        },
        "warranty_months": 12,
    },
    {
        "sku": "NBT-LNV-I7",
        "name": "ThinkPad E14 Core i7",
        "brand": "Lenovo",
        "model": "ThinkPad E14",
        "category": "notebooks",
        "price": Decimal("5899.00"),
        "description": "Notebook corporativo com teclado resistente e segurança.",
        "specifications": {
            "processador": "Intel Core i7",
            "memoria": "16 GB",
            "armazenamento": "512 GB SSD",
        },
        "warranty_months": 24,
    },
    {
        "sku": "AUD-SNY-WH1000",
        "name": "WH-1000XM5",
        "brand": "Sony",
        "model": "WH-1000XM5",
        "category": "audio",
        "price": Decimal("2499.00"),
        "description": "Headset over-ear com cancelamento de ruído ativo.",
        "specifications": {
            "tipo": "over-ear",
            "conexao": "Bluetooth 5.2",
            "bateria": "até 30 horas",
        },
        "warranty_months": 12,
    },
    {
        "sku": "AUD-JBL-TUNE770",
        "name": "Tune 770NC",
        "brand": "JBL",
        "model": "Tune 770NC",
        "category": "audio",
        "price": Decimal("699.00"),
        "description": "Fone Bluetooth com cancelamento de ruído adaptativo.",
        "specifications": {
            "tipo": "over-ear",
            "conexao": "Bluetooth 5.3",
            "bateria": "até 70 horas",
        },
        "warranty_months": 12,
    },
    {
        "sku": "AUD-APL-AIRP2",
        "name": "AirPods Pro 2",
        "brand": "Apple",
        "model": "AirPods Pro 2",
        "category": "audio",
        "price": Decimal("2199.00"),
        "description": "Fone intra-auricular com cancelamento ativo de ruído.",
        "specifications": {
            "tipo": "intra-auricular",
            "conexao": "Bluetooth 5.3",
            "bateria": "até 6 horas",
        },
        "warranty_months": 12,
    },
    {
        "sku": "ACS-LOG-MX3S",
        "name": "MX Master 3S",
        "brand": "Logitech",
        "model": "MX Master 3S",
        "category": "acessorios",
        "price": Decimal("549.00"),
        "description": "Mouse sem fio ergonômico com sensor de 8.000 DPI.",
        "specifications": {
            "conexao": "Bluetooth e receptor USB",
            "sensor": "8.000 DPI",
            "bateria": "recarregável",
        },
        "warranty_months": 12,
    },
    {
        "sku": "ACS-KEY-K380",
        "name": "K380 Multi-Device",
        "brand": "Logitech",
        "model": "K380",
        "category": "acessorios",
        "price": Decimal("249.00"),
        "description": "Teclado compacto para até três dispositivos.",
        "specifications": {
            "conexao": "Bluetooth",
            "layout": "ABNT2",
            "bateria": "2 pilhas AAA",
        },
        "warranty_months": 12,
    },
    {
        "sku": "ACS-USB-HUB7",
        "name": "Hub USB-C 7 em 1",
        "brand": "Ugreen",
        "model": "CM512",
        "category": "acessorios",
        "price": Decimal("199.00"),
        "description": "Hub com HDMI, USB 3.0, cartão SD e carga PD.",
        "specifications": {
            "portas": "HDMI + 3x USB + SD + microSD + USB-C",
            "video": "4K a 30 Hz",
            "carga": "PD 100 W",
        },
        "warranty_months": 12,
    },
)

# Pedidos históricos: `dias_atras` distribui a série nos últimos 30 dias.
# Todo pedido com `pagamento` está em `processado` (o fluxo do worker concluiu);
# os demais exercitam a lista com pendente/falha.
PEDIDOS: tuple[dict[str, Any], ...] = (
    {
        "chave": "seed-demo-01",
        "usuario": "demo_user",
        "dias_atras": 29,
        "status": Pedido.PROCESSADO,
        "itens": (("SMT-IP15-128", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-02",
        "usuario": "demo_admin",
        "dias_atras": 28,
        "status": Pedido.PROCESSADO,
        "itens": (("NBT-DLL-I5", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_CARTAO,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-03",
        "usuario": "demo_admin",
        "dias_atras": 27,
        "status": Pedido.PROCESSADO,
        "itens": (("AUD-SNY-WH1000", 1), ("ACS-LOG-MX3S", 1)),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_PUSH,
        },
    },
    {
        "chave": "seed-demo-04",
        "usuario": "demo_admin",
        "dias_atras": 25,
        "status": Pedido.PROCESSADO,
        "itens": (("SMT-GLX-S24", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_CARTAO,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-05",
        "usuario": "demo_admin",
        "dias_atras": 23,
        "status": Pedido.PROCESSADO,
        "itens": (("ACS-KEY-K380", 2), ("ACS-USB-HUB7", 1)),
        "pagamento": {
            "metodo": Pagamento.METODO_BOLETO,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-06",
        "usuario": "demo_admin",
        "dias_atras": 21,
        "status": Pedido.PROCESSADO,
        "itens": (("AUD-JBL-TUNE770", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_CARTAO,
            "aprovado": False,
            "motivo_recusa": "Saldo insuficiente",
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-07",
        "usuario": "demo_admin",
        "dias_atras": 19,
        "status": Pedido.PROCESSADO,
        "itens": (("NBT-ACC-A515", 1), ("ACS-USB-HUB7", 2)),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_PUSH,
        },
    },
    {
        "chave": "seed-demo-08",
        "usuario": "demo_admin",
        "dias_atras": 17,
        "status": Pedido.PROCESSADO,
        "itens": (("AUD-APL-AIRP2", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_BOLETO,
            "aprovado": False,
            "motivo_recusa": "Boleto vencido",
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-09",
        "usuario": "demo_admin",
        "dias_atras": 15,
        "status": Pedido.PROCESSADO,
        "itens": (("SMT-MOT-G54", 1), ("ACS-KEY-K380", 1)),
        "pagamento": {
            "metodo": Pagamento.METODO_CARTAO,
            "aprovado": True,
            "canal": Notificacao.CANAL_SMS,
        },
    },
    {
        "chave": "seed-demo-10",
        "usuario": "demo_admin",
        "dias_atras": 13,
        "status": Pedido.PROCESSADO,
        "itens": (("NBT-LNV-I7", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-11",
        "usuario": "demo_user",
        "dias_atras": 11,
        "status": Pedido.PENDENTE,
        "itens": (("AUD-JBL-TUNE770", 2),),
    },
    {
        "chave": "seed-demo-12",
        "usuario": "demo_admin",
        "dias_atras": 10,
        "status": Pedido.PENDENTE,
        "itens": (("ACS-LOG-MX3S", 1),),
    },
    {
        "chave": "seed-demo-13",
        "usuario": "demo_admin",
        "dias_atras": 9,
        "status": Pedido.FALHA,
        "itens": (("SMT-IP15-128", 1),),
        "tentativas": 3,
        "motivo_falha": "Falha simulada no processamento do pedido.",
    },
    {
        "chave": "seed-demo-14",
        "usuario": "demo_admin",
        "dias_atras": 8,
        "status": Pedido.PROCESSADO,
        "itens": (("AUD-SNY-WH1000", 1),),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-15",
        "usuario": "demo_admin",
        "dias_atras": 7,
        "status": Pedido.PENDENTE,
        "itens": (("ACS-USB-HUB7", 3),),
    },
    {
        "chave": "seed-demo-16",
        "usuario": "demo_admin",
        "dias_atras": 6,
        "status": Pedido.FALHA,
        "itens": (("NBT-DLL-I5", 1),),
        "tentativas": 3,
        "motivo_falha": "Falha simulada no processamento do pedido.",
    },
    {
        "chave": "seed-demo-17",
        "usuario": "demo_admin",
        "dias_atras": 5,
        "status": Pedido.PENDENTE,
        "itens": (("SMT-GLX-S24", 1),),
    },
    {
        "chave": "seed-demo-18",
        "usuario": "demo_admin",
        "dias_atras": 4,
        "status": Pedido.PROCESSADO,
        "itens": (("AUD-APL-AIRP2", 1), ("ACS-USB-HUB7", 1)),
        "pagamento": {
            "metodo": Pagamento.METODO_CARTAO,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
    {
        "chave": "seed-demo-19",
        "usuario": "demo_admin",
        "dias_atras": 2,
        "status": Pedido.PROCESSADO,
        "itens": (("SMT-MOT-G54", 2),),
        "pagamento": {
            "metodo": Pagamento.METODO_PIX,
            "aprovado": True,
            "canal": Notificacao.CANAL_SMS,
        },
    },
    {
        "chave": "seed-demo-20",
        "usuario": "demo_admin",
        "dias_atras": 1,
        "status": Pedido.PROCESSADO,
        "itens": (("NBT-ACC-A515", 1), ("ACS-KEY-K380", 1)),
        "pagamento": {
            "metodo": Pagamento.METODO_BOLETO,
            "aprovado": True,
            "canal": Notificacao.CANAL_EMAIL,
        },
    },
)


class Command(BaseCommand):
    """Cria a massa mínima de demonstração de forma idempotente."""

    help = (
        "Cria catálogo, pedidos, pagamentos e notificações de demonstração "
        "(idempotente; exige que `seed_auth` já tenha rodado)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--silent",
            action="store_true",
            help="Não imprime o resumo ao final (uso em scripts).",
        )

    def handle(self, *args, **options) -> None:
        silencioso = bool(options.get("silent"))
        usuarios = self._carregar_usuarios()
        agora = timezone.now()

        categorias = self._criar_categorias()
        produtos = self._criar_produtos(categorias)
        pedidos = self._criar_pedidos(usuarios, produtos, agora)
        pagamentos, notificacoes_criadas = self._criar_pagamentos_e_notificacoes(
            pedidos, agora
        )

        if not silencioso:
            self.stdout.write(
                self.style.SUCCESS(
                    "Massa demo pronta: "
                    f"{len(categorias)} categorias, {len(produtos)} produtos, "
                    f"{len(pedidos)} pedidos, {pagamentos} pagamentos e "
                    f"{notificacoes_criadas} notificações."
                )
            )

    # ------------------------------------------------------------------
    # Blocos do seed
    # ------------------------------------------------------------------
    @staticmethod
    def _carregar_usuarios() -> dict[str, Any]:
        User = get_user_model()
        nomes = {"demo_admin", "demo_user"}
        usuarios = {
            usuario.username: usuario
            for usuario in User.objects.filter(username__in=nomes)
        }
        faltando = sorted(nomes - set(usuarios))
        if faltando:
            raise CommandError(
                "Usuários demo ausentes: "
                f"{', '.join(faltando)}. Execute `python api/manage.py seed_auth` "
                "antes de `seed_demo`."
            )
        return usuarios

    def _criar_categorias(self) -> dict[str, Category]:
        categorias: dict[str, Category] = {}
        for dados in CATEGORIAS:
            categoria, _ = Category.objects.get_or_create(
                name=dados["name"],
                defaults={
                    "slug": dados["slug"],
                    "description": dados["description"],
                },
            )
            categorias[dados["slug"]] = categoria
        return categorias

    @staticmethod
    def _criar_produtos(categorias: dict[str, Category]) -> dict[str, Item]:
        produtos: dict[str, Item] = {}
        for dados in PRODUTOS:
            produto, _ = Item.objects.get_or_create(
                sku=dados["sku"],
                defaults={
                    "name": dados["name"],
                    "brand": dados["brand"],
                    "model": dados["model"],
                    "description": dados["description"],
                    "price": dados["price"],
                    "specifications": dados["specifications"],
                    "warranty_months": dados["warranty_months"],
                    "category": categorias[dados["category"]],
                    "is_active": True,
                },
            )
            produtos[dados["sku"]] = produto
        return produtos

    def _criar_pedidos(
        self,
        usuarios: dict[str, object],
        produtos: dict[str, Item],
        agora,
    ) -> dict[str, Pedido]:
        pedidos: dict[str, Pedido] = {}
        for indice, dados in enumerate(PEDIDOS, start=1):
            itens = []
            total = Decimal("0")
            for sku, quantidade in dados["itens"]:
                produto = produtos[sku]
                total += produto.price * quantidade
                itens.append(
                    {
                        "sku": produto.sku,
                        "quantidade": quantidade,
                        "preco_unitario": f"{produto.price:.2f}",
                        "produto_id": produto.pk,
                    }
                )
            total = total.quantize(Decimal("0.01"))
            criado_em = agora - timedelta(
                days=int(dados["dias_atras"]), hours=indice % 6
            )
            processado_em = (
                criado_em + timedelta(minutes=2)
                if dados["status"] == Pedido.PROCESSADO
                else None
            )

            pedido, novo = Pedido.objects.get_or_create(
                idempotency_key=dados["chave"],
                defaults={
                    "usuario": usuarios[dados["usuario"]],
                    "status": dados["status"],
                    "itens": itens,
                    "total": total,
                    "tentativas": int(dados.get("tentativas", 0)),
                    "motivo_falha": str(dados.get("motivo_falha", "")),
                    "processado_em": processado_em,
                },
            )
            if novo:
                Pedido.objects.filter(pk=pedido.pk).update(
                    created_at=criado_em,
                    updated_at=criado_em + timedelta(minutes=3),
                )
                pedido.refresh_from_db()
            pedidos[dados["chave"]] = pedido
        return pedidos

    def _criar_pagamentos_e_notificacoes(
        self,
        pedidos: dict[str, Pedido],
        agora,
    ) -> tuple[int, int]:
        pagamentos = 0
        notificacoes_criadas = 0
        for indice, dados in enumerate(PEDIDOS, start=1):
            configuracao = dados.get("pagamento")
            if configuracao is None:
                continue

            pedido = pedidos[dados["chave"]]
            aprovado = bool(configuracao["aprovado"])
            motivo = str(configuracao.get("motivo_recusa", ""))
            criado_em = agora - timedelta(
                days=int(dados["dias_atras"]), hours=indice % 6
            ) + timedelta(minutes=4)

            pagamento, novo_pagamento = Pagamento.objects.get_or_create(
                idempotency_key=f"{dados['chave']}-pagamento",
                defaults={
                    "pedido": pedido,
                    "metodo": configuracao["metodo"],
                    "valor": pedido.total,
                    "transacao_id": f"seed-demo-tx-{indice:02d}",
                    "aprovado": aprovado,
                    "motivo_recusa": motivo,
                    "status": (
                        Pagamento.APROVADO if aprovado else Pagamento.RECUSADO
                    ),
                    "notificado_em": criado_em + timedelta(minutes=2),
                },
            )
            pagamentos += 1
            if novo_pagamento:
                Pagamento.objects.filter(pk=pagamento.pk).update(
                    created_at=criado_em,
                    updated_at=criado_em + timedelta(minutes=2),
                )

            titulo, mensagem = notificacoes.titulo_e_mensagem(
                SimpleNamespace(
                    metodo=pagamento.metodo,
                    valor=pagamento.valor,
                    aprovado=pagamento.aprovado,
                    motivo_recusa=pagamento.motivo_recusa,
                )
            )
            notificacao, nova_notificacao = Notificacao.objects.get_or_create(
                pagamento=pagamento,
                defaults={
                    "pedido": pedido,
                    "canal": configuracao["canal"],
                    "titulo": titulo,
                    "mensagem": mensagem,
                },
            )
            if nova_notificacao:
                Notificacao.objects.filter(pk=notificacao.pk).update(
                    enviada_em=criado_em + timedelta(minutes=2)
                )
                notificacoes_criadas += 1

        return pagamentos, notificacoes_criadas
