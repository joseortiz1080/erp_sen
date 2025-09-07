from decimal import Decimal

from django.contrib.auth import authenticate, login, logout

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Sum, F, DecimalField, Value, Q, Exists, OuterRef, Subquery,
    BooleanField, Case, When
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from django.views.decorators.http import require_GET

from .models import Estudiante, Contrato, Cuota, Pago, Nivel, Horario, Sede



@require_POST
@login_required
def logout_view(request):
    logout(request)               # limpia completamente la sesión
    return redirect('login')      # <— ÚNICO CAMBIO: coincide con name='login' en urls.py

@login_required
def vista_inicial(request):
    return render(request, 'inicio.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username') or ''
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('vista_inicial')  # TODO: redirigir según rol
        return render(request, 'login.html', {'error': True})
    return render(request, 'login.html')


@login_required
def dashboard_view(request):
    return render(request, 'dashboard.html')


@login_required
def listar_estudiantes(request):
    estudiantes = (
        Estudiante.objects
        .select_related('nivel', 'sede', 'acudiente', 'horario')
        .order_by('id')  # Orden ascendente por ID
    )
    return render(request, 'listar_estudiantes.html', {'estudiantes': estudiantes})


@login_required
def detalle_estudiante(request, id):
    estudiante = get_object_or_404(
        Estudiante.objects.select_related('nivel', 'sede', 'acudiente', 'horario'),
        id=id
    )
    contratos = Contrato.objects.filter(estudiante=estudiante).order_by('-id')
    contrato_activo = contratos.first() if contratos.exists() else None
    cuotas = contrato_activo.cuota_set.all() if contrato_activo else []
    return render(request, 'detalle_estudiante.html', {
        'estudiante': estudiante,
        'contrato': contrato_activo,
        'cuotas': cuotas,
    })


@login_required
def listado_cxc(request):
    """
    Listado de CUOTAS (una fila por cuota) con filtros y paginación.
    - Muestra todas las cuotas (vencidas, pendientes, parciales y pagadas).
    - Filtros: q, estado, nivel, horario, fv_desde/fv_hasta, medio, factura, referencia, con_pago, sede.
    - Anota: total pagado por cuota, último pago (fecha/medio/factura/obs/referencia), SALDO y es_vencida_roja.
    """
    sede_usuario_id = getattr(request.user, 'sede_id', None)
    hoy = now().date()

    # --------- Subqueries: último pago por cuota ---------
    pagos_ordenados = Pago.objects.filter(cuota_id=OuterRef('pk')).order_by('-fecha_pago', '-id')
    ultimo_pago_fecha      = Subquery(pagos_ordenados.values('fecha_pago')[:1])
    ultimo_pago_medio      = Subquery(pagos_ordenados.values('forma_pago')[:1])
    ultimo_pago_obs        = Subquery(pagos_ordenados.values('observacion')[:1])
    ultimo_pago_factura    = Subquery(pagos_ordenados.values('numero_factura')[:1])
    ultimo_pago_referencia = Subquery(pagos_ordenados.values('referencia')[:1])  # NUEVO

    # --------- Base queryset ---------
    qs = (
        Cuota.objects
        .select_related(
            'contrato__estudiante',
            'contrato__estudiante__acudiente',
            'contrato__estudiante__nivel',
            'contrato__estudiante__horario',
            'contrato__estudiante__sede',
            'contrato',
        )
        .annotate(
            pagado=Coalesce(
                Sum('pagos__valor_pagado'),
                Value(Decimal('0.00'), output_field=DecimalField())
            ),
            ultimo_pago_fecha=ultimo_pago_fecha,
            ultimo_pago_medio=ultimo_pago_medio,
            ultimo_pago_obs=ultimo_pago_obs,
            ultimo_pago_factura=ultimo_pago_factura,
            ultimo_pago_referencia=ultimo_pago_referencia,  # NUEVO
        )
        .annotate(saldo=F('valor') - F('pagado'))
        .annotate(
            es_vencida_roja=Case(
                When(Q(fecha_vencimiento__lt=hoy) & Q(valor__gt=F('pagado')), then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        .order_by('contrato__estudiante__id', 'fecha_vencimiento', 'numero')
    )

    # --------- Seguridad por sede ---------
    if sede_usuario_id:  # usuario atado a sede
        qs = qs.filter(contrato__estudiante__sede_id=sede_usuario_id)

    # --------- Parámetros de filtro ---------
    q_text     = (request.GET.get('q') or '').strip()
    estado     = (request.GET.get('estado') or '').strip()          # Pendiente/Parcial/Vencida/Pagada
    nivel_id   = (request.GET.get('nivel') or '').strip()
    horario_id = (request.GET.get('horario') or '').strip()
    fv_desde   = (request.GET.get('fv_desde') or '').strip()        # YYYY-MM-DD
    fv_hasta   = (request.GET.get('fv_hasta') or '').strip()
    medio      = (request.GET.get('medio') or '').strip()           # Banco/Nequi/Transferencia/Efectivo/Otro
    factura    = (request.GET.get('factura') or '').strip()
    referencia = (request.GET.get('referencia') or '').strip()      # <-- NUEVO parámetro
    con_pago   = (request.GET.get('con_pago') or '').strip()        # 'si' / 'no'
    sede_id    = (request.GET.get('sede') or '').strip() if not sede_usuario_id else ''  # solo globales

    # Texto libre (incluye referencia)
    if q_text:
        filtros = (
            Q(contrato__estudiante__nombre_completo__icontains=q_text) |
            Q(contrato__estudiante__documento__icontains=q_text) |
            Q(contrato__estudiante__acudiente__documento__icontains=q_text) |
            Q(contrato__estudiante__acudiente__nombre_completo__icontains=q_text) |
            Q(pagos__numero_factura__icontains=q_text) |
            Q(pagos__referencia__icontains=q_text)  # NUEVO
        )
        if q_text.isdigit():
            filtros |= Q(contrato_id=int(q_text))
        qs = qs.filter(filtros).distinct()

    # Estado de la cuota
    if estado:
        qs = qs.filter(estado=estado)
    # Nivel y horario
    if nivel_id:
        qs = qs.filter(contrato__estudiante__nivel_id=nivel_id)
    if horario_id:
        qs = qs.filter(contrato__estudiante__horario_id=horario_id)

    # Rango de vencimiento
    if fv_desde:
        qs = qs.filter(fecha_vencimiento__gte=fv_desde)
    if fv_hasta:
        qs = qs.filter(fecha_vencimiento__lte=fv_hasta)

    # Medio
    if medio:
        qs = qs.annotate(tiene_medio=Exists(
            Pago.objects.filter(cuota_id=OuterRef('pk'), forma_pago=medio)
        )).filter(tiene_medio=True)

    # Factura
    if factura:
        qs = qs.annotate(tiene_factura=Exists(
            Pago.objects.filter(cuota_id=OuterRef('pk'), numero_factura__icontains=factura)
        )).filter(tiene_factura=True)

    # Referencia
    if referencia:
        qs = qs.annotate(tiene_referencia=Exists(
            Pago.objects.filter(cuota_id=OuterRef('pk'), referencia__icontains=referencia)
        )).filter(tiene_referencia=True)

    # Con pago / sin pago
    if con_pago == 'si':
        qs = qs.filter(pagado__gt=0)
    elif con_pago == 'no':
        qs = qs.filter(pagado__lte=0)

    # Sede
    if sede_id:
        qs = qs.filter(contrato__estudiante__sede_id=sede_id)

    # --------- Catálogos ---------
    niveles  = Nivel.objects.all().order_by('nombre')
    horarios = Horario.objects.all().order_by('descripcion')
    sedes    = Sede.objects.all().order_by('nombre') if not sede_usuario_id else []

    ESTADOS = ['Pendiente', 'Parcial', 'Vencida', 'Pagada']
    MEDIOS  = ['Banco', 'Nequi', 'Transferencia', 'Efectivo', 'Otro']

    # --------- Paginación ---------
    try:
        per_page = int(request.GET.get('per_page', 50))
    except ValueError:
        per_page = 50
    page = request.GET.get('page', 1)

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    context = {
        'cuotas': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,

        # filtros activos
        'q': q_text, 'estado': estado, 'nivel_id': nivel_id, 'horario_id': horario_id,
        'fv_desde': fv_desde, 'fv_hasta': fv_hasta, 'medio': medio,
        'factura': factura, 'referencia': referencia, 'con_pago': con_pago, 'sede_id': sede_id,
        'per_page': per_page,

        # catálogos
        'niveles': niveles,
        'horarios': horarios,
        'sedes': sedes,
        'ESTADOS': ESTADOS,
        'MEDIOS': MEDIOS,

        'hoy': hoy,  # para comparaciones en template si lo necesitas
    }
    return render(request, 'listado_cxc.html', context)


@login_required
def aplicar_pago(request):
    """
    GET  => retorna historial de pagos de una cuota en JSON (para el modal) + previas con saldo.
            Parámetro requerido: ?cuota_id=<id>
    POST => crea un Pago. Por defecto BLOQUEA si hay cuotas previas con saldo.
            Si se envía modo=auto, distribuye el pago primero en previas (más antiguas) y luego en la actual.
    """
    from django.utils.dateparse import parse_date  # import local

    # --- Helper de seguridad/sede ---
    def obtener_cuota_segura(cuota_id_str):
        cuota = get_object_or_404(
            Cuota.objects.select_related('contrato', 'contrato__estudiante__sede'),
            pk=cuota_id_str
        )
        sede_usuario_id = getattr(request.user, 'sede_id', None)
        if sede_usuario_id and cuota.contrato.estudiante.sede_id != sede_usuario_id:
            return None, JsonResponse({'ok': False, 'error': 'No tiene permisos sobre esta sede.'}, status=403)
        return cuota, None

    # --- Helper: QS de previas (mismo contrato, numero menor) con saldo usando aggregate ---
    def previas_pendientes_for_get(cuota):
        return (
            Cuota.objects
            .filter(contrato_id=cuota.contrato_id, numero__lt=cuota.numero)
            .annotate(
                pagado=Coalesce(
                    Sum('pagos__valor_pagado'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
                saldo=F('valor') - F('pagado'),
            )
            .filter(saldo__gt=0)
            .order_by('numero')
        )

    def serializar_previas(qs):
        return [
            {
                'cuota_id': c.id,
                'numero': c.numero,
                'vence': c.fecha_vencimiento.strftime('%Y-%m-%d'),
                'saldo': str(c.saldo),
            }
            for c in qs
        ]

    # =========================
    # GET: historial de pagos
    # =========================
    if request.method == 'GET':
        cuota_id = (request.GET.get('cuota_id') or '').strip()
        if not cuota_id:
            return JsonResponse({'ok': False, 'error': 'Falta cuota_id.'}, status=400)

        cuota, resp_error = obtener_cuota_segura(cuota_id)
        if resp_error:
            return resp_error

        pagos_qs = (
            Pago.objects
            .filter(cuota_id=cuota.id)
            .order_by('fecha_pago', 'id')
            .values('id', 'fecha_pago', 'valor_pagado', 'forma_pago', 'numero_factura', 'referencia', 'observacion')
        )

        pagos = []
        for p in pagos_qs:
            medio = p['forma_pago'] or ''
            medio = 'Banco' if medio == 'Transferencia' else medio
            pagos.append({
                'id': p['id'],
                'fecha_pago': p['fecha_pago'].strftime('%Y-%m-%d'),
                'valor_pagado': str(p['valor_pagado']),
                'forma_pago': medio,
                'numero_factura': p['numero_factura'] or '',
                'referencia': p['referencia'] or '',
                'observacion': p['observacion'] or '',
            })

        previas_qs = previas_pendientes_for_get(cuota)
        return JsonResponse({'ok': True, 'pagos': pagos, 'previas_pendientes': serializar_previas(previas_qs)})

    # ========================= #
    # POST: aplicar pago        #
    # ========================= #
    cuota_id = (request.POST.get('cuota_id') or '').strip()
    valor_str = (request.POST.get('valor_pagado') or '').strip()
    forma_pago = (request.POST.get('forma_pago') or '').strip()
    numero_factura = (request.POST.get('numero_factura') or '').strip() or None
    referencia = (request.POST.get('referencia') or '').strip()   # referencia obligatoria
    observacion = (request.POST.get('observacion') or '').strip()
    fecha_str = (request.POST.get('fecha_pago') or '').strip()
    modo = (request.POST.get('modo') or '').strip()  # '', 'auto'

    # Validación de cuota_id primero
    if not cuota_id:
        return JsonResponse({'ok': False, 'error': 'Falta cuota_id.'}, status=400)

    # Obtener cuota y validar sede
    cuota, resp_error = obtener_cuota_segura(cuota_id)
    if resp_error:
        return resp_error

    # Si no viene valor, diferenciamos el caso de cuota sin saldo
    saldo_actual_previo = (cuota.valor or Decimal('0.00')) - (cuota.valor_pagado or Decimal('0.00'))
    if not valor_str:
        if saldo_actual_previo <= 0:
            return JsonResponse({
                'ok': False,
                'error': 'No hay saldo por pagar en esta cuota.',
                'error_code': 'sin_saldo'
            }, status=400)
        return JsonResponse({
                'ok': False,
                'error': 'Falta el valor a pagar.',
                'error_code': 'faltan_datos'
            }, status=400)

    # Referencia obligatoria
    if not referencia:
        return JsonResponse({'ok': False, 'error': 'La referencia es obligatoria.'}, status=400)

    # Valor numérico y > 0
    try:
        valor = Decimal(valor_str)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Valor inválido.'}, status=400)
    if valor <= 0:
        return JsonResponse({'ok': False, 'error': 'El valor debe ser mayor a cero.'}, status=400)

    # Fecha
    from django.utils.dateparse import parse_date  # import local
    fecha_pago = parse_date(fecha_str) if fecha_str else None
    if not fecha_pago:
        fecha_pago = now().date()

    with transaction.atomic():
        # Bloquear cuota actual y previas
        cuotas_locked = list(
            Cuota.objects.select_for_update()
            .filter(Q(id=cuota.id) | Q(contrato_id=cuota.contrato_id, numero__lt=cuota.numero))
            .select_related('contrato')
            .order_by('numero')
        )
        by_id = {c.id: c for c in cuotas_locked}
        cuota = by_id[cuota.id]
        previas_locked = [c for c in cuotas_locked if c.id != cuota.id]

        def saldo_de(c: Cuota) -> Decimal:
            return (c.valor or Decimal('0.00')) - (c.valor_pagado or Decimal('0.00'))

        previas_con_saldo = [c for c in previas_locked if saldo_de(c) > 0]
        saldo_actual = saldo_de(cuota)

        # Si hay previas con saldo y no es modo auto, bloquear
        if previas_con_saldo and modo != 'auto':
            previas_json = [
                {
                    'cuota_id': c.id,
                    'numero': c.numero,
                    'vence': c.fecha_vencimiento.strftime('%Y-%m-%d'),
                    'saldo': str(saldo_de(c))
                }
                for c in previas_con_saldo
            ]
            return JsonResponse({
                'ok': False,
                'error': 'Existen cuotas anteriores con saldo pendiente. Debe cubrirlas primero o usar distribución automática.',
                'error_code': 'previas_pendientes',
                'previas': previas_json,
            }, status=400)

        # En modo auto validar capacidad total (previas + actual)
        if modo == 'auto':
            capacidad_total = sum((saldo_de(c) for c in previas_con_saldo), Decimal('0.00')) + saldo_actual
            if valor > capacidad_total:
                return JsonResponse({
                    'ok': False,
                    'error': f'El valor ({valor}) supera la capacidad total disponible ({capacidad_total}).',
                    'error_code': 'supera_capacidad',
                    'capacidad_total': str(capacidad_total),
                    'previas': [
                        {
                            'cuota_id': c.id,
                            'numero': c.numero,
                            'vence': c.fecha_vencimiento.strftime('%Y-%m-%d'),
                            'saldo': str(saldo_de(c))
                        }
                        for c in previas_con_saldo
                    ],
                }, status=400)

        # Helper: crear pago y actualizar cuota
        def aplicar_a_cuota(c: Cuota, monto: Decimal) -> Decimal:
            if monto <= 0:
                return Decimal('0.00')
            saldo_c = saldo_de(c)
            aplicar = min(monto, saldo_c)
            if aplicar <= 0:
                return Decimal('0.00')

            Pago.objects.create(
                contrato=c.contrato,
                cuota=c,
                fecha_pago=fecha_pago,
                valor_pagado=aplicar,
                forma_pago=forma_pago,
                numero_factura=numero_factura,
                referencia=referencia,
                observacion=observacion
            )

            c.valor_pagado = (c.valor_pagado or Decimal('0.00')) + aplicar
            if c.valor_pagado >= c.valor:
                c.estado = 'Pagada'
            elif c.valor_pagado > 0:
                c.estado = 'Parcial'
            else:
                c.estado = 'Pendiente'
            c.save(update_fields=['valor_pagado', 'estado'])
            return aplicar

        distribucion = []

        if previas_con_saldo and modo == 'auto':
            monto = valor
            # Primero previas
            for c_prev in previas_con_saldo:
                aplicado = aplicar_a_cuota(c_prev, monto)
                if aplicado > 0:
                    distribucion.append({'cuota_id': c_prev.id, 'numero': c_prev.numero, 'aplicado': str(aplicado)})
                    monto -= aplicado
                if monto <= 0:
                    break
            # Remanente a la actual
            if monto > 0:
                aplicado = aplicar_a_cuota(cuota, monto)
                if aplicado > 0:
                    distribucion.append({'cuota_id': cuota.id, 'numero': cuota.numero, 'aplicado': str(aplicado)})
        else:
            # Flujo normal: tope en saldo de la actual
            if valor > saldo_actual:
                return JsonResponse({'ok': False, 'error': f'El valor supera el saldo de la cuota: {saldo_actual}.'}, status=400)
            aplicado = aplicar_a_cuota(cuota, valor)
            distribucion.append({'cuota_id': cuota.id, 'numero': cuota.numero, 'aplicado': str(aplicado)})

    return JsonResponse({'ok': True, 'distribucion': distribucion})


@login_required
@require_POST
def eliminar_pago(request):
    """
    Elimina un pago por su ID y actualiza la cuota (valor_pagado y estado).
    POST: pago_id
    """
    pago_id = (request.POST.get('pago_id') or '').strip()
    if not pago_id:
        return JsonResponse({'ok': False, 'error': 'Falta pago_id.'}, status=400)

    # Cargar pago con control por sede
    pago = get_object_or_404(
        Pago.objects.select_related('cuota__contrato__estudiante__sede', 'cuota'),
        pk=pago_id
    )

    # Si el pago no está asociado a cuota
    if pago.cuota_id is None:
        pago.delete()
        return JsonResponse({'ok': True})

    sede_usuario_id = getattr(request.user, 'sede_id', None)
    if sede_usuario_id and pago.cuota.contrato.estudiante.sede_id != sede_usuario_id:
        return JsonResponse({'ok': False, 'error': 'No tiene permisos sobre esta sede.'}, status=403)

    with transaction.atomic():
        # Bloquear la cuota y eliminar el pago
        cuota = Cuota.objects.select_for_update().get(pk=pago.cuota_id)
        pago.delete()

        # Recalcular total pagado y estado
        nuevo_pagado = cuota.pagos.aggregate(
            total=Coalesce(
                Sum('valor_pagado'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )['total'] or Decimal('0.00')

        cuota.valor_pagado = nuevo_pagado
        if nuevo_pagado >= cuota.valor:
            cuota.estado = 'Pagada'
        elif nuevo_pagado > 0:
            cuota.estado = 'Parcial'
        else:
            # No forzamos 'Vencida' aquí; otra rutina puede marcar por fecha
            cuota.estado = 'Pendiente'
        cuota.save(update_fields=['valor_pagado', 'estado'])

    return JsonResponse({'ok': True})
