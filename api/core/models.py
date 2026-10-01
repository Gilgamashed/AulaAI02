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