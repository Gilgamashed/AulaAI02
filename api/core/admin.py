from django.contrib import admin

from .models import Category, Item, Notificacao, Pagamento, Pedido


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "brand", "model", "price", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "brand", "model", "sku")


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    """Admin do pedido — é onde se diagnostica um pedido preso na DLQ.

    As colunas de diagnóstico (`tentativas`, `motivo_falha` e o filtro por
    status) existem porque a mensagem que parou na DLQ não aparece aqui: o
    admin mostra o **efeito** do processamento, que é a parte que interessa
    ao negócio.
    """

    list_display = (
        "id",
        "usuario",
        "status",
        "total",
        "tentativas",
        "processado_em",
        "pagamento",
        "created_at",
    )
    list_filter = ("status", "simular_falha")
    search_fields = ("idempotency_key", "motivo_falha")
    readonly_fields = (
        "idempotency_key",
        "itens",
        "total",
        "tentativas",
        "processado_em",
        "created_at",
        "updated_at",
    )


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    """Admin do pagamento — diagnóstico de um `registrado` que nunca notificou.

    O filtro por `status` é o que responde "o que está travado agora": linhas em
    `registrado` com `notificado_em` vazio são pagamentos cujo evento não foi
    publicado (re-POST no endpoint cura) ou cuja notificação ficou presa na DLQ.
    """

    list_display = (
        "id",
        "pedido",
        "status",
        "metodo",
        "valor",
        "aprovado",
        "transacao_id",
        "tentativas",
        "notificado_em",
        "created_at",
    )
    list_filter = ("status", "metodo", "aprovado", "simular_falha")
    search_fields = ("transacao_id", "idempotency_key", "motivo_recusa", "motivo_falha")
    readonly_fields = (
        "idempotency_key",
        "transacao_id",
        "valor",
        "tentativas",
        "notificado_em",
        "created_at",
        "updated_at",
    )


@admin.register(Notificacao)
class NotificacaoAdmin(admin.ModelAdmin):
    """Admin da notificação: o registro do que foi disparado ao cliente."""

    list_display = (
        "id",
        "pedido",
        "pagamento",
        "canal",
        "titulo",
        "enviada_em",
    )
    list_filter = ("canal",)
    search_fields = ("titulo", "mensagem")
    readonly_fields = ("enviada_em",)