from django.contrib import admin
from django.urls import path

from gestion_clientes.views import (
    login_view,            # login
    vista_inicial,         # /
    dashboard_view,        # dashboard
    listar_estudiantes,    # estudiantes
    detalle_estudiante,    # estudiantes/<id>
    listado_cxc,           # cxc
    aplicar_pago,          # pago/aplicar
    eliminar_pago,         # pago/eliminar
    nuevo_contrato,        # nuevo-contrato
    logout_view,           # logout
    buscar_acudiente_por_documento,
    nuevo_ingreso,
    listar_medios_pago,
    reporte_ingresos_manuales,  # reporte conciliación ingresos manuales
    buscar_estudiante,
    custom_403,
    admin_roles_permisos,
    admin_usuarios_roles,
)

urlpatterns = [
    path('', login_view, name='login'),
    path('inicio/', vista_inicial, name='vista_inicial'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('admin/', admin.site.urls),

    path('estudiantes/', listar_estudiantes, name='listar_estudiantes'),
    path('estudiantes/buscar/', buscar_estudiante, name='buscar_estudiante'),
    path('estudiantes/<int:id>/', detalle_estudiante, name='detalle_estudiante'),

    path('cxc/', listado_cxc, name='listado_cxc'),
    path('pago/aplicar/', aplicar_pago, name='aplicar_pago'),
    path('pago/eliminar/', eliminar_pago, name='eliminar_pago'),
    path('nuevo-contrato/', nuevo_contrato, name='nuevo_contrato'),
    path('logout/', logout_view, name='logout'),

    path('api/acudientes/buscar/', buscar_acudiente_por_documento, name='buscar_acudiente'),
    path('ingresos/nuevo/', nuevo_ingreso, name='nuevo_ingreso'),
    path('ingresos/reporte/', reporte_ingresos_manuales, name='reporte_ingresos_manuales'),
    path('api/medios-pago/', listar_medios_pago, name='listar_medios_pago'),
    path('seguridad/roles-permisos/', admin_roles_permisos, name='admin_roles_permisos'),
    path('seguridad/usuarios-roles/', admin_usuarios_roles, name='admin_usuarios_roles'),
]

# Custom error handlers
handler403 = custom_403
