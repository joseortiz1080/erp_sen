from django.contrib import admin
from .models import Sede, Acudiente, Estudiante, Contrato, Pago, Nivel, Horario

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

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('nombre_completo', 'nivel', 'sede', 'acudiente')
    search_fields = ('nombre_completo',)
    list_filter = ('nivel', 'sede')

@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'acudiente', 'fecha_inicio', 'valor_total', 'estado')
    list_filter = ('estado', 'fecha_inicio')
    search_fields = ('estudiante__nombre_completo', 'acudiente__nombre_completo')

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('contrato', 'fecha_pago', 'valor_pagado', 'forma_pago', 'referencia')  # ✅ Campo agregado
    list_filter = ('fecha_pago', 'forma_pago')
    search_fields = ('contrato__estudiante__nombre_completo', 'referencia')  # ✅ Se agregó búsqueda por referencia

@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'hora')
    search_fields = ('descripcion',)
