from django import template

register = template.Library()

@register.filter
def moneda_puntos(valor):
    try:
        valor = float(valor)
        return "${:,.0f}".format(valor).replace(",", ".")
    except (ValueError, TypeError):
        return valor
