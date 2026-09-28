"""Invalidação de cache orientada a eventos de domínio (Aula 8).

O cache é invalidado **por evento de negócio**, não por esquecimento: cada
gravação no banco dispara um sinal do Django e um *handler* traduz esse
evento em "quais chaves de cache deixaram de ser verdadeiras".

| Evento de domínio  | Gatilho                       | Chaves invalidadas                                  |
| ------------------ | ----------------------------- | --------------------------------------------------- |
| `ItemCriado`       | `post_save` (created)         | `item:<id>`, `item:<id>:detalhes`, geração da lista  |
| `ItemAtualizado`   | `post_save` (updated)         | `item:<id>`, `item:<id>:detalhes`, geração da lista  |
| `ItemRemovido`     | `post_delete`                 | `item:<id>`, `item:<id>:detalhes`, geração da lista  |
| `Categoria*`       | `post_save`/`post_delete`     | `categoria:<id>`, geração das listas de categoria **e de itens** |

Três decisões importantes:

1. **Sinais, não hooks na view.** A regra de invalidação fica num único lugar
   e vale para *qualquer* caminho de escrita: API, Django Admin, shell de
   gestão ou seed. Se a view chamasse `cache.delete`, um `Item.objects.update()`
   silenciosamente deixaria o cache velho.
2. **`transaction.on_commit`.** O sinal dispara *dentro* da transação; se ela
   for revertida, o cache válido não pode ser destruído. O `on_commit` adia a
   invalidação para depois do `COMMIT` — o cache só é invalidado quando o
   dado novo é definitivo (o TTL cobre a janela entre o commit e a próxima
   leitura).
3. **Desnormalização é uma fonte de erro de cache.** O payload do item
   carrega `category_name` (ver `ItemSerializer`). Renomear uma categoria
   mudaria esse dado, então o evento de categoria também invalida a listagem
   de itens — não só a de categorias.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import cache as cache_api
from .models import Category, Item


# =====================================================================
# Handlers de evento
# =====================================================================
def _invalidar_item(item_id: int, evento: str) -> None:
    """Aplica a regra de invalidação de um `Item` que foi gravado/removido."""
    cache_api.invalidate_detail(
        cache_api.detail_key(cache_api.PREFIXO_ITEM, item_id),
        cache_api.NS_ITEM_DETALHE,
        evento,
    )
    cache_api.invalidate_detail(
        cache_api.details_key(cache_api.PREFIXO_ITEM, item_id),
        cache_api.NS_ITEM_DETALHES,
        evento,
    )
    # A listagem embute todos os itens (qualquer alteração muda a página 1,
    # a contagem e as páginas seguintes) -> invalida a geração inteira.
    cache_api.invalidate_list(cache_api.NS_ITEM_LIST, evento)


def _invalidar_categoria(category_id: int, evento: str) -> None:
    """Aplica a regra de invalidação de uma `Category`."""
    cache_api.invalidate_detail(
        cache_api.detail_key(cache_api.PREFIXO_CATEGORY, category_id),
        cache_api.NS_CATEGORY_DETAIL,
        evento,
    )
    cache_api.invalidate_list(cache_api.NS_CATEGORY_LIST, evento)
    # `category_name` vem desnormalizado no payload dos itens: a listagem de
    # itens também é invalidada quando a categoria muda (ou é removida).
    cache_api.invalidate_list(cache_api.NS_ITEM_LIST, evento)


@receiver(post_save, sender=Item)
def item_salvo(sender, instance: Item, created: bool, **kwargs) -> None:
    """`ItemCriado` / `ItemAtualizado` -> invalida detalhe + listagem."""
    evento = "ItemCriado" if created else "ItemAtualizado"
    # `on_commit` garante que só invalidamos depois do commit da transação.
    transaction.on_commit(lambda: _invalidar_item(instance.pk, evento))


@receiver(post_delete, sender=Item)
def item_removido(sender, instance: Item, **kwargs) -> None:
    """`ItemRemovido` -> a listagem e o detalhe do registro saem do cache."""
    transaction.on_commit(lambda: _invalidar_item(instance.pk, "ItemRemovido"))


@receiver(post_save, sender=Category)
def categoria_salva(sender, instance: Category, created: bool, **kwargs) -> None:
    """`CategoriaCriada` / `CategoriaAtualizada` -> detalhe + ambas as listas."""
    evento = "CategoriaCriada" if created else "CategoriaAtualizada"
    transaction.on_commit(lambda: _invalidar_categoria(instance.pk, evento))


@receiver(post_delete, sender=Category)
def categoria_removida(sender, instance: Category, **kwargs) -> None:
    """`CategoriaRemovida` -> detalhe + ambas as listas."""
    transaction.on_commit(lambda: _invalidar_categoria(instance.pk, "CategoriaRemovida"))


# Este módulo precisa ser importado para que os `@receiver` acima sejam
# registrados — quem faz isso é `CoreConfig.ready()`.
__all__ = [
    "categoria_removida",
    "categoria_salva",
    "item_removido",
    "item_salvo",
]
