# gestion_clientes/permisos.py
from functools import wraps
from django.http import HttpResponseForbidden

from .models import UsuarioRol, RolPermiso


def user_tiene_permiso(user, permiso_codigo: str) -> bool:
    """
    True si el usuario tiene al menos un rol ACTIVO que tenga ACTIVO el permiso_codigo.
    - Usa tablas: UsuarioRol -> RolPermiso -> Permiso
    """
    if not user or not user.is_authenticated:
        return False

    permiso_codigo = (permiso_codigo or "").strip()
    if not permiso_codigo:
        return False

    return RolPermiso.objects.filter(
        activo=True,
        permiso__activo=True,
        permiso__codigo=permiso_codigo,
        rol__usuariorol__usuario=user,
        rol__usuariorol__activo=True,
        rol__activo=True,
    ).exists()


def permiso_requerido(permiso_codigo: str):
    """
    Decorador para vistas:
    - Si NO autorizado: retorna 403 sin redirecciones.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if user_tiene_permiso(request.user, permiso_codigo):
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("No está autorizado para ver esta vista.")
        return _wrapped
    return decorator