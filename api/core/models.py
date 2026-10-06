import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


def validate_sku(value):
    if not re.fullmatch(r"[A-Z]{2,4}-[A-Z0-9-]+", value):
        raise ValidationError(
            "SKU inválido. Use o formato 'XXXX-AAAA-BBBB' (ex.: 'APL-IP15-128')."
        )


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="nome")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoria"
        verbose_name_plural = "categorias"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "categoria"
            slug, index = base, 2
            while Category.objects.filter(slug=slug).exists():
                slug = f"{base}-{index}"
                index += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Item(models.Model):
    name = models.CharField(max_length=200, verbose_name="nome")
    brand = models.CharField(max_length=100, verbose_name="marca")
    model = models.CharField(max_length=100, verbose_name="modelo")
    sku = models.CharField(
        max_length=100,
        unique=True,
        validators=[validate_sku],
        verbose_name="SKU",
    )
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="preço")
    specifications = models.JSONField(default=dict, blank=True, verbose_name="especificações")
    warranty_months = models.PositiveIntegerField(
        default=12, verbose_name="garantia (meses)"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="categoria",
    )
    is_active = models.BooleanField(default=True, verbose_name="ativo")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        # Índice essencial da listagem padrão (API `ItemViewSet` + Admin): ambas
        # ordenam por `-created_at` e, sem índice de suporte, o PostgreSQL faria
        # seq-scan + sort conforme o catálogo cresce.
        indexes = [
            models.Index(fields=["-created_at"], name="core_item_created_at_desc_idx"),
        ]

    def __str__(self):
        return f"{self.brand} {self.model} ({self.sku})"


# =====================================================================
# Aula 9 — Pedido (entidade que dá origem ao evento `PedidoCriado`)
# =====================================================================
# O pedido é a FONTE DA VERDADE do fluxo assíncrono: a API grava o pedido e
# publica o evento; o worker apenas avança o estado. Por isso o registro do
# banco, e não a mensagem, é o que se consulta para saber o que aconteceu.


class Pedido(models.Model):
    """Pedido do cliente e estado do seu processamento assíncrono."""

    # Estados possíveis. `pendente_publicacao` é o estado de exceção: o
    # pedido foi salvo, mas o broker estava fora, então o evento ainda não
    # existe (recuperado por `republicar_pedidos`).
    PENDENTE_PUBLICACAO = "pendente_publicacao"
    PENDENTE = "pendente"
    PROCESSADO = "processado"
    FALHA = "falha"

    STATUS_CHOICES = [
        (PENDENTE_PUBLICACAO, "Pendente de publicação"),
        (PENDENTE, "Pendente (aguardando o worker)"),
        (PROCESSADO, "Processado"),
        (FALHA, "Falha"),
    ]

    # PROTECT (e não CASCADE): pedido é registro de negócio e não pode
    # desaparecer junto com o usuário que o fez.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pedidos",
        verbose_name="usuário",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=PENDENTE_PUBLICACAO,
        db_index=True,
        verbose_name="status",
    )
    # Linhas do pedido em JSON, não em tabela próprias: o MVP só precisa
    # carregar o snapshot (sku + quantidade + preço unitário) que foi usado
    # no cálculo do total. Guardar o preço no momento da compra é o que
    # permite reconstituir o pedido depois de uma mudança no catálogo.
    itens = models.JSONField(default=list, verbose_name="itens")
    # Total SEMPRE calculado pelo servidor, a partir do preço do catálogo —
    # o cliente nunca informa o valor. Ver `PedidoCreateSerializer.validate`.
    total = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="total"
    )

    # Chave de idempotência do pedido. `unique=True` resolve DOIS problemas
    # com uma restrição só: (1) a API rejeita (409) a reentrega de um pedido
    # já criado com a mesma chave; (2) é o campo de comparison do contrato
    # `PedidoCriado`, com o mesmo valor que vai na mensagem.
    idempotency_key = models.CharField(
        max_length=64,
        unique=True,
        verbose_name="chave de idempotência",
    )

    # Marca o pedido para o worker falhar de propósito. Existe para validar a
    # DLQ de ponta a ponta (a spec exige "simulações de erro forçado"); só é
    # aceito pela API com PEDIDO_PERMITIR_SIMULACAO_FALHA ligado.
    simular_falha = models.BooleanField(default=False, verbose_name="simular falha")

    # Quantas vezes o worker tentou processar este pedido. Vive no banco (e
    # não só no cabeçalho da mensagem) para que o estado final continue
    # legível depois que a mensagem saiu da fila.
    tentativas = models.PositiveIntegerField(default=0, verbose_name="tentativas")
    processado_em = models.DateTimeField(null=True, blank=True, verbose_name="processado em")
    motivo_falha = models.CharField(
        max_length=200, blank=True, default="", verbose_name="motivo da falha"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        indexes = [
            # Listagem padrão do `PedidoViewSet`: filtra por usuário e ordena
            # por `-created_at` — mesma razão do índice equivalente em Item.
            models.Index(
                fields=["usuario", "-created_at"], name="core_pedido_usuario_created_i"
            ),
        ]

    def __str__(self):
        return f"Pedido {self.pk} ({self.status}) — R$ {self.total}"


# =====================================================================
# Aula 11 — Pagamento (o "gateway simulado") e Notificacao (o disparo)
# =====================================================================
# A Aula 9/10 fechou o fluxo do pedido: gravar -> publicar `PedidoCriado` ->
# o worker avança o estado. A Aula 11 acrescenta os dois passos que faltavam
# entre o "pedido existe" e o "cliente foi avisado": o pagamento e o aviso.
#
# `Pedido.status` NÃO ganhou novos valores, e essa é uma decisão: o estado do
# pedido é o do *pipeline assíncrono* (`pendente_publicacao` -> `pendente` ->
# `processado`/`falha`), e o desfecho financeiro é outra coisa. Colar
# "pago"/"recusado" em `Pedido.status` obrigaria a revisar a máquina de estados
# dos dois consumidores (e as evidências de DLQ já documentadas) para colocar um
# dado que pertence a outra entidade. Por isso o resultado do gateway mora em
# `Pagamento`.


class Pagamento(models.Model):
    """Resultado do gateway de pagamento simulado, disparado por evento.

    Um pagamento por pedido (`OneToOneField`): a regra é do negócio, e a
    restrição do banco é o que a garante. Tentar pagar de novo o mesmo pedido
    não é "criar outro pagamento" — é a repetição do mesmo pagamento, que a
    API trata como idempotência (200/409), não como um segundo registro.
    """

    # `REGISTRADO` é o estado de exceção, irmão de `Pedido.PENDENTE_PUBLICACAO`:
    # o gateway respondeu, o `Pagamento` está no banco, mas o evento que
    # dispararia a notificação não pôde ser publicado. O cliente recebe 503 e
    # um re-POST no mesmo endpoint republica — por isso o estado precisa existir
    # para que esse re-POST saiba o que fazer.
    REGISTRADO = "registrado"
    APROVADO = "aprovado"
    RECUSADO = "recusado"

    STATUS_CHOICES = [
        (REGISTRADO, "Registrado (aguardando publicação do evento)"),
        (APROVADO, "Aprovado"),
        (RECUSADO, "Recusado"),
    ]

    METODO_CARTAO = "cartao_credito"
    METODO_PIX = "pix"
    METODO_BOLETO = "boleto"

    METODO_CHOICES = [
        (METODO_CARTAO, "Cartão de crédito"),
        (METODO_PIX, "PIX"),
        (METODO_BOLETO, "Boleto"),
    ]

    # PROTECT: o pagamento é registro financeiro; perdê-lo junto com o pedido
    # apagaria a evidência de que a cobrança aconteceu.
    pedido = models.OneToOneField(
        Pedido,
        on_delete=models.PROTECT,
        related_name="pagamento",
        verbose_name="pedido",
    )

    metodo = models.CharField(
        max_length=32,
        choices=METODO_CHOICES,
        verbose_name="método",
    )
    # Snapshot de `Pedido.total` no momento da tentativa. Guardar o valor é o
    # que permite explicar a cobrança depois de qualquer ajuste no catálogo.
    valor = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="valor"
    )

    # Identificador da transação no "gateway". Numa loja real seria o id que o
    # provedor devolve; aqui é gerado no ato, e `unique=True` garante que dois
    # Pagamentos nunca representem a mesma transação.
    transacao_id = models.CharField(
        max_length=64, unique=True, verbose_name="id da transação"
    )

    # O desfecho do gateway. Fica em campo próprio, separado de `status`:
    # `aprovado` responde "o gateway aceitou?" e `status` responde "o evento
    # foi publicado?". Os dois só convergem em `APROVADO`/`RECUSADO`, e a
    # diferença entre eles é justamente o estado `REGISTRADO`.
    aprovado = models.BooleanField(default=False, verbose_name="aprovado")
    motivo_recusa = models.CharField(
        max_length=200, blank=True, default="", verbose_name="motivo da recusa"
    )

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=REGISTRADO,
        db_index=True,
        verbose_name="status",
    )

    # Chave de idempotência do pagamento, calculada pelo servidor a partir de
    # (pedido, método, desfecho) — ver `views.PedidoViewSet.pagamento`. Ela é o
    # campo de comparação do contrato `PagamentoRegistrado` e o que permite ao
    # re-POST reconhecer "é o mesmo pagamento" e republicar o evento perdido.
    idempotency_key = models.CharField(
        max_length=64,
        unique=True,
        verbose_name="chave de idempotência",
    )

    # Mesma função de `Pedido.simular_falha`: marca este pagamento para o worker
    # falhar de propósito, o que valida a escada de reentrega e a DLQ do fluxo
    # de pagamento. Só é aceito com `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` ligado.
    simular_falha = models.BooleanField(
        default=False, verbose_name="simular falha"
    )

    tentativas = models.PositiveIntegerField(
        default=0, verbose_name="tentativas"
    )
    # Preenchido pelo worker quando a Notificacao é criada. `NULL` é o que
    # separa "ainda não notificou" de "notificou" — é a condição do `UPDATE`
    # condicional que dá idempotência ao disparo.
    notificado_em = models.DateTimeField(
        null=True, blank=True, verbose_name="notificado em"
    )
    motivo_falha = models.CharField(
        max_length=200, blank=True, default="", verbose_name="motivo da falha"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        indexes = [
            # Listagem padrão do `NotificacaoViewSet`/diagnóstico: mais recentes
            # primeiro (mesma razão do índice equivalente em Pedido).
            models.Index(
                fields=["-created_at"], name="core_pagamento_created_desc_i"
            ),
            # Filtro operacional "quais pagamentos estão registrados sem
            # notificação": é a fila de trabalho do `worker-pagamentos`.
            models.Index(
                fields=["status", "notificado_em"],
                name="core_pagamento_status_notif_i",
            ),
        ]

    def __str__(self):
        return f"Pagamento {self.pk} do pedido {self.pedido_id} ({self.status})"


class Notificacao(models.Model):
    """Aviso disparado ao cliente quando o pagamento é registrado.

    Existe como registro porque o DoD pede a notificação **comprovável**: um
    log mostra que algo aconteceu, uma linha no banco mostra o quê foi
    enviado, para quem e quando. É também a base que os dashboards das aulas
    futuras vão consumir.
    """

    CANAL_EMAIL = "email"
    CANAL_SMS = "sms"
    CANAL_PUSH = "push"

    CANAL_CHOICES = [
        (CANAL_EMAIL, "E-mail"),
        (CANAL_SMS, "SMS"),
        (CANAL_PUSH, "Push"),
    ]

    # OneToOne é a **segunda barreira de idempotência** do fluxo, no banco: se
    # a janela do Redis já expirou e o `UPDATE` condicional casar zero linhas,
    # a unicidade ainda impede duas notificações para o mesmo pagamento. As três
    # barreiras juntas (Redis, `UPDATE`, unicidade) é o que torna o disparo
    # exatamente-uma-vez mesmo sob reentrega e rebalance.
    pagamento = models.OneToOneField(
        Pagamento,
        on_delete=models.PROTECT,
        related_name="notificacao",
        verbose_name="pagamento",
    )
    # Desnormalizado de propósito: `GET /api/v1/notificacoes/` filtra por dono
    # e ordena por data. Com o FK do pedido, isso é um JOIN; seguindo a cadeia
    # Notificacao -> Pagamento -> Pedido -> usuario, seriam três.
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.PROTECT,
        related_name="notificacoes",
        verbose_name="pedido",
    )

    canal = models.CharField(
        max_length=16,
        choices=CANAL_CHOICES,
        default=CANAL_EMAIL,
        verbose_name="canal",
    )
    titulo = models.CharField(max_length=120, verbose_name="título")
    mensagem = models.TextField(verbose_name="mensagem")

    # `auto_now_add` e não um campo preenchido pelo worker: a notificação é o
    # disparo, e o instante do disparo é o que interessa.
    enviada_em = models.DateTimeField(auto_now_add=True, verbose_name="enviada em")

    class Meta:
        ordering = ["-enviada_em"]
        verbose_name = "notificação"
        verbose_name_plural = "notificações"
        indexes = [
            # Filtro por dono + ordenação padrão da listagem.
            models.Index(
                fields=["pedido", "-enviada_em"], name="core_notificacao_ped_envia_i"
            ),
        ]

    def __str__(self):
        return f"Notificação {self.pk} do pedido {self.pedido_id} ({self.canal})"