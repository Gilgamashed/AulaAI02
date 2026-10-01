from django.contrib import admin

from .models import Category, Item, Pedido


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