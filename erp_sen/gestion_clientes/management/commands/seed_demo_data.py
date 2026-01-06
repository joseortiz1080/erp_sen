from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now
from decimal import Decimal
from datetime import date

from gestion_clientes.models import (
    Sede, Nivel, Horario,
    Acudiente, Estudiante, Contrato, Cuota,
    Ingreso, PagoAplicacion,
    MedioPago, ConceptoIngreso
)

class Command(BaseCommand):
    help = "Carga datos de prueba (acudientes, estudiantes, contratos, cuotas, ingresos y aplicaciones)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario_id", type=int, default=1, help="ID del auth_user que registra los ingresos.")
        parser.add_argument("--reset", action="store_true", help="Borra SOLO data operativa (no catálogos). Úsalo solo si estás seguro.")

    @transaction.atomic
    def handle(self, *args, **opts):
        usuario_id = opts["usuario_id"]
        hoy = now().date()

        # ==========================
        # (0) RESET controlado (opcional)
        # ==========================
        if opts["reset"]:
            self.stdout.write(self.style.WARNING("RESET activado: borrando data operativa..."))
            # Orden de borrado por FKs:
            PagoAplicacion.objects.all().delete()
            Ingreso.objects.all().delete()
            Cuota.objects.all().delete()
            Contrato.objects.all().delete()
            Estudiante.objects.all().delete()
            Acudiente.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("RESET OK."))

        # ==========================
        # (1) Validar catálogos existentes (según tus pantallas)
        # ==========================
        sedes = list(Sede.objects.all().order_by("id"))
        niveles = list(Nivel.objects.all().order_by("id"))
        horarios = list(Horario.objects.all().order_by("id"))
        medios_pago = list(MedioPago.objects.filter(activo=True).order_by("id"))
        conceptos = {c.nombre.lower(): c for c in ConceptoIngreso.objects.filter(activo=True)}

        if not sedes or not niveles or not horarios or not medios_pago:
            raise Exception("Faltan catálogos base (sedes/niveles/horarios/medios_pago). Revisa antes de sembrar data.")

        # Intentamos mapear conceptos por nombre (según tu lista)
        concepto_cuota = None
        concepto_cuota_inicial = None
        for c in ConceptoIngreso.objects.filter(activo=True):
            n = (c.nombre or "").strip().lower()
            if n == "cuota":
                concepto_cuota = c
            if n in ["cuota inicial", "cuota_inicial"]:
                concepto_cuota_inicial = c

        if not concepto_cuota:
            raise Exception("No existe ConceptoIngreso 'Cuota'. Crea ese catálogo antes.")
        # cuota inicial es opcional según tu paso 1D

        # ==========================
        # (2) Crear 10 acudientes
        # ==========================
        acudientes = []
        for i in range(1, 11):
            doc = f"90010020{i:02d}"
            acud, _ = Acudiente.objects.get_or_create(
                documento=doc,
                defaults=dict(
                    nombre_completo=f"Acudiente Demo {i}",
                    tipo_documento="CC",
                    telefono=f"320555{i:04d}",
                    email=f"acudiente{i}@demo.com"
                )
            )
            acudientes.append(acud)

        # ==========================
        # (3) Crear 50 estudiantes (5 por acudiente)
        # ==========================
        estudiantes = []
        contador = 1
        for a in acudientes:
            for k in range(1, 6):
                doc_est = f"901{a.id:03d}{k:02d}{contador:03d}"
                sede = sedes[(contador - 1) % len(sedes)]
                nivel = niveles[(contador - 1) % len(niveles)]
                horario = horarios[(contador - 1) % len(horarios)]

                est, _ = Estudiante.objects.get_or_create(
                    documento=doc_est,
                    defaults=dict(
                        nombre_completo=f"Estudiante Demo {a.id}-{k}",
                        tipo_documento="CC",
                        fecha_nacimiento=date(2010, 1, 1),
                        nivel=nivel,
                        acudiente=a,
                        sede=sede,
                        estado="Activo",
                        observacion="",
                        horario=horario
                    )
                )
                estudiantes.append(est)
                contador += 1

        # ==========================
        # (4) Crear 10 contratos (1 por acudiente, asociado a 1 estudiante)
        #     - 10 con cuota inicial, otros no (tú definiste: 10 con cuota inicial)
        # ==========================
        contratos = []
        for idx, a in enumerate(acudientes, start=1):
            est = Estudiante.objects.filter(acudiente=a).order_by("id").first()

            # Valor total demo (variación simple)
            valor_total = Decimal("2400000.00") + Decimal(idx * 100000)

            # Contrato: alternamos día de corte por lote (5 y 20)
            dia_corte = 5 if idx <= 5 else 20

            # Fecha inicio: este mes con el día de corte
            fecha_inicio = hoy.replace(day=dia_corte)

            contrato = Contrato.objects.create(
                acudiente=a,
                estudiante=est,
                fecha_inicio=fecha_inicio,
                fecha_fin=None,
                valor_total=valor_total,
                numero_cuotas=24,  # tú pediste 24
                valor_cuota_pactada=(valor_total / Decimal("24")).quantize(Decimal("0.01")),
                estado="Activo"
            )
            contratos.append((contrato, dia_corte))

        # ==========================
        # (5) Crear cuotas operativas (24 por contrato)
        #     - Regla: 25 cuotas con vencimiento día 5 y 25 con vencimiento día 20 (tú lo pediste).
        #       Como tu universo real aquí es 10 contratos * 24 = 240 cuotas,
        #       lo que haré es: asegurar que en el total queden MANY vencimientos al 5 y al 20,
        #       y además marcar varias vencidas (fechas pasadas).
        # ==========================
        def sumar_meses(fecha, meses):
            y = fecha.year + (fecha.month - 1 + meses) // 12
            m = (fecha.month - 1 + meses) % 12 + 1
            d = min(fecha.day, 28)  # evitar invalid dates
            return date(y, m, d)

        cuotas_por_contrato = {}
        for contrato, dia_corte in contratos:
            cuotas = []
            base = contrato.fecha_inicio
            for n in range(1, 25):
                venc = sumar_meses(base, n-1).replace(day=dia_corte)
                cuota = Cuota.objects.create(
                    contrato=contrato,
                    numero=n,
                    fecha_vencimiento=venc,
                    valor=(contrato.valor_total / Decimal("24")).quantize(Decimal("0.01")),
                    valor_pagado=Decimal("0.00"),
                    estado="Pendiente"
                )
                cuotas.append(cuota)
            cuotas_por_contrato[contrato.id] = cuotas

        # Marcar algunas vencidas: tomamos 2 cuotas por contrato con fecha vencimiento en el pasado
        for contrato, _dia in contratos:
            cuotas = cuotas_por_contrato[contrato.id]
            for q in cuotas[:2]:
                q.fecha_vencimiento = hoy.replace(day=1)  # este mes día 1 (pasado vs hoy día 30)
                q.estado = "Vencida"
                q.save(update_fields=["fecha_vencimiento", "estado"])

        # ==========================
        # (6) Crear ingresos + aplicaciones (PagoAplicacion) para simular recaudo
        #     - 10 contratos con cuota inicial (Ingreso tipo_registro 'otro_ingreso' o 'pago_cuota' según tu estándar)
        #     - Pagos a 24 cuotas: vamos a pagar 12 cuotas por contrato (para que queden saldos y vencidas reales)
        # ==========================
        medio_default = medios_pago[0]

        for i, (contrato, _dia) in enumerate(contratos, start=1):
            cuotas = cuotas_por_contrato[contrato.id]

            # --- Cuota inicial (solo si existe el concepto en catálogo)
            if concepto_cuota_inicial:
                valor_inicial = (contrato.valor_total * Decimal("0.10")).quantize(Decimal("0.01"))
                ing0 = Ingreso.objects.create(
                    sede=contrato.estudiante.sede,
                    concepto_ingreso=concepto_cuota_inicial,
                    valor_pagado=valor_inicial,
                    fecha_pago=hoy,
                    numero_comprobante=None,
                    medio_pago=medio_default,
                    referencia=f"INI-{contrato.id}",
                    observacion="Cuota inicial demo",
                    tipo_registro="otro_ingreso",
                    estado="ACTIVO",
                    usuario_registro_id=usuario_id,
                    contrato=contrato,
                    cuota=None,
                    numero_factura=None
                )
                # Aplicamos a la cuota 1 como ejemplo (administrativo)
                PagoAplicacion.objects.create(
                    ingreso=ing0,
                    cuota=cuotas[0],
                    usuario_id=usuario_id,
                    fecha_aplicacion=now(),
                    valor_aplicado=valor_inicial,
                    forma_pago=medio_default.nombre,
                    numero_factura=None,
                    referencia=f"INI-{contrato.id}",
                    observacion="Aplicación cuota inicial demo"
                )

            # --- Pagos a cuotas (simulación)
            # Pagamos 12 cuotas por contrato (mitad), dejando 12 pendientes.
            for q in cuotas[:12]:
                valor_pago = q.valor  # pago completo
                ing = Ingreso.objects.create(
                    sede=contrato.estudiante.sede,
                    concepto_ingreso=concepto_cuota,
                    valor_pagado=valor_pago,
                    fecha_pago=hoy,
                    numero_comprobante=None,
                    medio_pago=medio_default,
                    referencia=f"PAGO-{contrato.id}-{q.numero}",
                    observacion="Pago cuota demo",
                    tipo_registro="pago_cuota",
                    estado="ACTIVO",
                    usuario_registro_id=usuario_id,
                    contrato=contrato,
                    cuota=q,
                    numero_factura=None
                )
                PagoAplicacion.objects.create(
                    ingreso=ing,
                    cuota=q,
                    usuario_id=usuario_id,
                    fecha_aplicacion=now(),
                    valor_aplicado=valor_pago,
                    forma_pago=medio_default.nombre,
                    numero_factura=None,
                    referencia=f"PAGO-{contrato.id}-{q.numero}",
                    observacion="Aplicación pago demo"
                )
                # Actualizamos cache legacy en Cuota (si tu UI aún lo usa)
                q.valor_pagado = (q.valor_pagado or Decimal("0.00")) + valor_pago
                q.estado = "Pagada"
                q.save(update_fields=["valor_pagado", "estado"])

        self.stdout.write(self.style.SUCCESS("✅ Seed demo finalizado: acudientes, estudiantes, contratos, cuotas, ingresos y aplicaciones creadas."))