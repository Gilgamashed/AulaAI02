import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

ADMIN_GROUP = "admin"
USER_GROUP = "user"


class Command(BaseCommand):
    """
    Seed idempotente da Aula 7.

    Cria os dois papéis (Django Groups) exigidos pela spec — "admin" e
    "user" — e dois usuários demo com senhas documentadas no README.

    Papéis = Groups do django.contrib.auth: reutilizamos o auth do Django
    sem customizar AUTH_USER_MODEL (decisão da Aula 6), então "papel" é
    representado por grupo. O usuário admin é `staff` (acessa o Django
    Admin) e pertence ao grupo "admin"; o usuário comum pertence a "user".

    Senhas vêm de SEED_*_PASSWORD (`.env`) com fallback DEV — nunca use
    as credenciais padrão em produção.
    """

    help = (
        "Cria os papéis 'admin'/'user' (Groups) e usuários demo "
        "(idempotente). Use SEED_*_PASSWORD para definir senhas via .env."
    )

    def handle(self, *args, **options):
        User = get_user_model()

        # 1) Papéis: get_or_create torna o comando executável N vezes.
        admin_group, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
        user_group, _ = Group.objects.get_or_create(name=USER_GROUP)

        # 2) Usuário demo administrador (papel "admin" + staff p/ Admin).
        admin_username = os.environ.get("SEED_ADMIN_USERNAME", "demo_admin")
        admin_password = os.environ.get(
            "SEED_ADMIN_PASSWORD", "demo-admin@Synapse2026"
        )
        admin_user, created_admin = User.objects.get_or_create(
            username=admin_username,
            defaults={"is_staff": True, "is_active": True},
        )
        admin_user.groups.set([admin_group])
        if created_admin:
            # Só define a senha no primeiro import para não sobrescrever
            # credenciais alteradas manualmente em execuções seguintes.
            admin_user.set_password(admin_password)
            admin_user.save()

        # 3) Usuário demo comum (papel "user", sem acesso ao Admin).
        user_username = os.environ.get("SEED_USER_USERNAME", "demo_user")
        user_password = os.environ.get(
            "SEED_USER_PASSWORD", "demo-user@Synapse2026"
        )
        demo_user, created_user = User.objects.get_or_create(
            username=user_username,
            defaults={"is_active": True},
        )
        demo_user.groups.set([user_group])
        if created_user:
            demo_user.set_password(user_password)
            demo_user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Papéis criados: '{ADMIN_GROUP}' e '{USER_GROUP}'. "
                f"Usuários: {admin_username} (admin), {user_username} (user)."
            )
        )
