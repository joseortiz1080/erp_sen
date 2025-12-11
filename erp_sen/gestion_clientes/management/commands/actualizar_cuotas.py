from django.core.management.base import BaseCommand
from django.utils import timezone
from gestion_clientes.models import Cuota

class Command(BaseCommand):
    help = 'Actualiza el estado de las cuotas vencidas automáticamente'

    def handle(self, *args, **kwargs):
        hoy = timezone.now().date()
        cuotas_actualizadas = 0

        cuotas = Cuota.objects.filter(
            fecha_vencimiento__lt=hoy
        ).exclude(estado__in=['Pagada', 'Parcial'])

        for cuota in cuotas:
            cuota.estado = 'Vencida'
            cuota.save()
            cuotas_actualizadas += 1

        self.stdout.write(self.style.SUCCESS(
            f'{cuotas_actualizadas} cuota(s) actualizada(s) como Vencida(s).'
        ))
