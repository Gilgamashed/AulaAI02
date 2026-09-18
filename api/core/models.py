import re

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

    def __str__(self):
        return f"{self.brand} {self.model} ({self.sku})"