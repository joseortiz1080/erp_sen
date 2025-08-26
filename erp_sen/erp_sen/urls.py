from django.contrib import admin
from django.urls import path
from gestion_clientes.views import login_view, vista_inicial, dashboard_view

urlpatterns = [
    path('', login_view, name='login'),
    path('inicio/', vista_inicial, name='vista_inicial'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('admin/', admin.site.urls),
]
