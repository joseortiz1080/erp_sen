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
    logout_view,           # logout  ← IMPORTANTE
)

urlpatterns = [
    path('', login_view, name='login'),
    path('inicio/', vista_inicial, name='vista_inicial'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('admin/', admin.site.urls),

    path('estudiantes/', listar_estudiantes, name='listar_estudiantes'),
    path('estudiantes/<int:id>/', detalle_estudiante, name='detalle_estudiante'),

    path('cxc/', listado_cxc, name='listado_cxc'),
    path('pago/aplicar/', aplicar_pago, name='aplicar_pago'),
    path('pago/eliminar/', eliminar_pago, name='eliminar_pago'),

    path('logout/', logout_view, name='logout'),  # ← usa la vista importada, no "views.logout_view"
]
