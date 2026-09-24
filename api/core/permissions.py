from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """
    Permissão personalizada da Aula 7: libera apenas usuários do papel
    "admin" (grupo homônimo do django.contrib.auth) ou superusuários.

    Motivo: o built-in `IsAdminUser` do DRF testa `is_staff`, mas a spec
    pede papéis explícitos ("admin" e "user"). Como decidimos reutilizar o
    auth do Django sem customizar `AUTH_USER_MODEL` (decisão da Aula 6),
    o papel de administrador é representado por um Group — e esta classe
    avalia a associação ao grupo.
    """

    message = "Ação restrita ao papel 'admin'."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            # Sem usuário autenticado não há como ser admin: o retorno False
            # vira 403 (ou 401, se o esquema de autenticação exigir credencial).
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name="admin").exists()
