from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def has_perm(context, codigo_permiso: str):
    """Retorna True/False si el usuario autenticado tiene el permiso por código.

    Uso en templates:
        {% load authz %}
        {% has_perm "ver_dashboard" as can_dashboard %}
        {% if can_dashboard %} ... {% endif %}

    Reglas:
    - Superuser: True
    - Si no hay usuario autenticado o el código viene vacío: False
    """
    request = context.get("request")
    user = getattr(request, "user", None)

    if not user or not getattr(user, "is_authenticated", False):
        return False

    # Superuser bypass
    if getattr(user, "is_superuser", False):
        return True

    codigo_permiso = (codigo_permiso or "").strip()
    if not codigo_permiso:
        return False

    # Import local para evitar ciclos
    from gestion_clientes.models import Permiso

    return Permiso.objects.filter(
        codigo=codigo_permiso,
        activo=True,
        roles__usuarios=user,
        roles__activo=True,
    ).exists()


@register.filter
def get_item(d, key):
    """Permite acceder a diccionarios en templates: {{ mapa|get_item:u.id }}"""
    if d is None:
        return None
    try:
        return d.get(key)
    except Exception:
        return None