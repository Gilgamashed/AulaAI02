from django.contrib import admin

from .models import Category, Item


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