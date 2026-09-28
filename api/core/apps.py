from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        """Registra os listeners de domínio da Aula 8 (invalidação de cache).

        O Django só chama `ready()` depois que todos os apps estão
        carregados — é o ponto oficial para conectar sinais. Sem este
        import, nenhum `post_save`/`post_delete` invalidaria o cache.
        """
        from . import signals  # noqa: F401  (import conecta os receivers)
