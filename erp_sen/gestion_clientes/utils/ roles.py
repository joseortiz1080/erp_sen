from typing import List


def user_in_groups(user, names: List[str]) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.groups.filter(name__in=names).exists()


def user_is_global(user) -> bool:
    """
    Global = puede ver todas las sedes dentro del ERP.
    - Superusuario
    - CEO
    - CFO
    """
    return bool(getattr(user, "is_superuser", False)) or user_in_groups(user, ["CEO", "CFO"])


def user_is_secretaria(user) -> bool:
    """
    Usuario operativo con restricciones por sede.
    """
    return user_in_groups(user, ["Secretaria"])


def user_can_delete(user) -> bool:
    """
    Permiso de borrado/anulación.
    - Superusuario: SI
    - CEO: SI
    - CFO: NO
    - Secretaria: NO
    """
    return bool(getattr(user, "is_superuser", False)) or user_in_groups(user, ["CEO"])