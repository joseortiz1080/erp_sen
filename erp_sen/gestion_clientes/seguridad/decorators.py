

from __future__ import annotations

from functools import wraps

from django.http import JsonResponse
from django.core.exceptions import PermissionDenied

from gestion_clientes.models import Permiso, RolPermiso, UsuarioRol


def permiso_requerido(codigo_permiso: str):
    """Decorador de permisos por vista.

    - Usa `Permiso.codigo` (no `codename`).
    - Resuelve permisos vía: auth.User -> UsuarioRol -> Rol -> RolPermiso -> Permiso.
    - Si no cumple, lanza 403 (PermissionDenied). Para AJAX retorna JSON 403.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, "user", None)

            # 1) Debe estar autenticado
            if not user or not user.is_authenticated:
                raise PermissionDenied

            # 2) Superuser pasa siempre
            if getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)

            # 3) Permiso debe existir y estar activo
            permiso = (
                Permiso.objects.filter(codigo=codigo_permiso, activo=True)
                .only("id")
                .first()
            )
            if not permiso:
                # Si el permiso no existe en DB, tratamos como NO autorizado.
                return _deny(request)

            # 4) Validación: el usuario debe tener al menos un rol activo
            #    que tenga asociado el permiso (rolpermiso) activo.
            tiene_permiso = RolPermiso.objects.filter(
                permiso_id=permiso.id,
                rol__activo=True,
                rol_id__in=UsuarioRol.objects.filter(
                    usuario_id=user.id,
                    activo=True,
                ).values_list("rol_id", flat=True),
                activo=True,
            ).exists()

            if not tiene_permiso:
                return _deny(request)

            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def _deny(request):
    """Respuesta estándar de no autorizado."""
    # AJAX / Fetch
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "No autorizado"}, status=403)

    # Navegación normal
    raise PermissionDenied