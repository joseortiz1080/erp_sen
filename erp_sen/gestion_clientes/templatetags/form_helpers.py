from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def add_class(field, css):
    """
    Añade clases CSS a un BoundField. Si recibe un string (HTML ya renderizado),
    inyecta la clase de forma segura.
    """
    try:
        widget = field.field.widget
        attrs = widget.attrs.copy()
        current = attrs.get("class", "")
        attrs["class"] = (current + " " + css).strip()
        return field.as_widget(attrs=attrs)
    except Exception:
        # fallback si 'field' es string HTML ya renderizado
        s = str(field)
        if 'class="' in s:
            return mark_safe(s.replace('class="', f'class="{css} ', 1))
        # intenta inyectar según el tag de entrada
        for tag in ("input", "select", "textarea"):
            if f"<{tag} " in s:
                return mark_safe(s.replace(f"<{tag} ", f'<{tag} class="{css}" ', 1))
        return mark_safe(s)

@register.filter
def attr(field, args):
    """
    Uso: {{ campo|attr:"placeholder:Texto,rows:4" }}
    """
    try:
        pairs = [p for p in args.split(",") if ":" in p]
        new_attrs = {}
        for p in pairs:
            k, v = p.split(":", 1)
            new_attrs[k.strip()] = v.strip()
        return field.as_widget(attrs={**field.field.widget.attrs, **new_attrs})
    except Exception:
        # Si es string, no hay forma fiable de agregar atributos; devuélvelo tal cual
        return field
