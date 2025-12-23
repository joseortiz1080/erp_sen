from django.contrib import admin
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce

from .models import (
    Sede, Acudiente, Estudiante, Contrato, Pago, Nivel, Horario,
    Cuota, PagoAplicacion, Perfil
)
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

# =========================
# Catálogos / Básicos
# =========================

@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'ciudad')
    search_fields = ('nombre', 'ciudad')


@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre')
    search_fields = ('codigo', 'nombre')


@admin.register(Acudiente)
class AcudienteAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'documento', 'telefono', 'email')
    search_fields = ('nombre_completo', 'documento', 'email')


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'hora')
    search_fields = ('descripcion',)


# =========================
# Nucleares
# =========================

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'nivel', 'sede', 'acudiente')
    search_fields = ('nombre_completo',)
    list_filter = ('nivel', 'sede')


@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = (
        'estudiante',
        'acudiente',
        'fecha_inicio',
        'valor_total',
        'estado',
        'total_aplicado_via_pagos',   # calculado
        'saldo_via_aplicaciones',     # calculado
    )
    list_filter = ('estado', 'fecha_inicio')
    search_fields = ('estudiante__nombre_completo', 'acudiente__nombre_completo')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Suma de valor_pagado en las CUOTAS del contrato
        return qs.annotate(
            _total_pagado=Coalesce(
                Sum('cuota__valor_pagado'),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
            )
        )

    @admin.display(description='Total pagado', ordering='_total_pagado')
    def total_aplicado_via_pagos(self, obj):
        # Preferimos el valor anotado; si no existe, hacemos fallback agregando
        total = getattr(obj, '_total_pagado', None)
        if total is None:
            total = obj.cuota_set.aggregate(
                t=Coalesce(
                    Sum('valor_pagado'),
                    Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
                )
            )['t'] or Decimal('0')
        return total

    @admin.display(description='Saldo')
    def saldo_via_aplicaciones(self, obj):
        total_pagado = self.total_aplicado_via_pagos(obj) or Decimal('0')
        return (obj.valor_total or Decimal('0')) - total_pagado


# Para que el autocomplete funcione buscando por contrato / estudiante:
@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'contrato',
        'numero',
        'fecha_vencimiento',
        'valor',
        'valor_pagado',
        'estado',
        'saldo_via_aplicaciones',  # calculado
    )
    list_filter = ('estado', 'fecha_vencimiento')
    search_fields = ('contrato__id', 'contrato__estudiante__nombre_completo')

    @admin.display(description='Saldo')
    def saldo_via_aplicaciones(self, obj):
        valor = obj.valor or Decimal('0')
        pagado = obj.valor_pagado or Decimal('0')
        return valor - pagado


# =========================
# Pagos (lista desplegable de cuotas)
# =========================

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    """
    Flujo simple:
    - Seleccionas CONTRATO
    - Seleccionas CUOTA (de cualquier contrato, como lo tenías)
      * El modelo ya valida que la cuota pertenezca al contrato.
    - Ingresas VALOR PAGADO
    - Guardas

    Extra: al guardar, se crea/actualiza automáticamente PagoAplicacion
    para mantener el nuevo esquema consistente.
    """
    list_display = ('contrato', 'fecha_pago', 'valor_pagado', 'forma_pago', 'referencia', 'numero_factura')
    list_filter = ('fecha_pago', 'forma_pago')
    search_fields = ('contrato__estudiante__nombre_completo', 'referencia', 'numero_factura')
    autocomplete_fields = ('contrato', 'cuota')
    save_on_top = True

    fields = (
        'contrato', 'cuota', 'fecha_pago', 'valor_pagado', 'forma_pago',
        'observacion', 'referencia', 'numero_factura'
    )

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        """
        Crea/actualiza automáticamente la(s) aplicación(es) del pago:
        - Se borra cualquier aplicación previa de este pago.
        - Se crea UNA aplicación igual al valor_pagado para la cuota seleccionada.
        - Se recalcula cache y estado de la cuota para mantener coherencia.
        """
        super().save_model(request, obj, form, change)

        # Si no hay cuota seleccionada, no hacemos aplicaciones
        if not obj.cuota_id:
            PagoAplicacion.objects.filter(pago=obj).delete()
            return

        # Limpiar aplicaciones anteriores de este pago (evita duplicados al editar)
        PagoAplicacion.objects.filter(pago=obj).delete()

        # Crear aplicación 1:1 con el importe del pago
        PagoAplicacion.objects.create(
            pago=obj,
            cuota=obj.cuota,
            monto=obj.valor_pagado
        )

        # Recalcular cache y estado de la cuota en base a TODAS sus aplicaciones
        cuota = obj.cuota
        total_aplicado = cuota.aplicaciones.aggregate(
            t=Coalesce(
                Sum('monto'),
                Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
            )
        )['t'] or Decimal('0')

        cuota.valor_pagado = total_aplicado
        saldo = (cuota.valor or Decimal('0')) - total_aplicado

        if saldo <= 0:
            cuota.estado = 'Pagada'
        elif total_aplicado > 0:
            cuota.estado = 'Parcial'
        else:
            cuota.estado = 'Pendiente'

        cuota.save(update_fields=['valor_pagado', 'estado'])


# =========================
# Perfil embebido en usuarios
# =========================

class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name_plural = 'Perfil'
    fk_name = 'user'


class UsuarioAdmin(UserAdmin):
    inlines = (PerfilInline, )


admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)
# admin.site.register(Sede)