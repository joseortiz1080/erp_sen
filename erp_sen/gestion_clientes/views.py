from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import (
    Sum, F, DecimalField, Value, Q, Exists, OuterRef, Subquery,
    IntegerField, Count, BooleanField, Case, When
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.timezone import now
from django.views.decorators.http import require_POST, require_GET

from .forms import AcudienteForm, EstudianteForm, ContratoForm, IngresoForm
from .models import (
    Estudiante, Contrato, Cuota, Ingreso, Pago, Nivel, Horario, Sede, Acudiente,
    MedioPago, ConceptoIngreso
)

@require_GET
@login_required
def listar_medios_pago(request):
    """
    Retorna medios de pago activos desde gestion_finanzas_medio_pago
    """
    medios = list(
        MedioPago.objects
        .filter(activo=True)
        .order_by('nombre')
        .values('id', 'nombre')
    )
    return JsonResponse({'ok': True, 'medios': medios})

# ============================
# (B) Helper unificado de sede
# ============================
def user_sede_ids(user):
    """
    Devuelve el conjunto de IDs de sede a los que el usuario tiene acceso.
    - Soporta un posible atributo legacy `user.sede_id`.
    - Si existe Perfil con ManyToMany `sedes`, usa ese universo.
    - Si no hay restricción, retorna set() (sin filtro por sede).
    """
    sid = getattr(user, 'sede_id', None)
    if sid:
        return {sid}
    perfil = getattr(user, 'perfil', None)
    if perfil:
        return set(perfil.sedes.values_list('id', flat=True))
    return set()


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


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


from django.db.models import Count, IntegerField, DecimalField, Value, F, Sum, OuterRef, Subquery
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.utils.timezone import now

@login_required
def listar_estudiantes(request):
    contrato_valor_sq = Subquery(
        Contrato.objects
        .filter(estudiante_id=OuterRef('pk'))
        .order_by('-id')
        .values('valor_total')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    numero_cuotas_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'))
        .values('contrato__estudiante_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    cuotas_pagadas_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'), estado='Pagada')
        .values('contrato__estudiante_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    cuotas_vencidas_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'), estado='Vencida')
        .values('contrato__estudiante_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    total_pagado_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'))
        .values('contrato__estudiante_id')
        .annotate(total=Coalesce(Sum('valor_pagado'), Value(Decimal('0.00'))))
        .values('total')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    saldo_total_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'))
        .values('contrato__estudiante_id')
        .annotate(saldo=Coalesce(Sum(F('valor') - F('valor_pagado')),
                                Value(Decimal('0.00'))))
        .values('saldo')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    cuotas_parciales_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'), estado='Parcial')
        .values('contrato__estudiante_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    proximo_vto_sq = Subquery(
        Cuota.objects
        .filter(contrato__estudiante_id=OuterRef('pk'), valor__gt=F('valor_pagado'))
        .order_by('fecha_vencimiento')
        .values('fecha_vencimiento')[:1]
    )

    estudiantes = (
        Estudiante.objects
        .select_related('nivel', 'sede', 'acudiente', 'horario')
        .annotate(
            # ya definidos:
            contrato_valor=Coalesce(contrato_valor_sq, Value(Decimal('0.00'))),
            numero_cuotas=Coalesce(numero_cuotas_sq, Value(0)),
            cuotas_pagadas=Coalesce(cuotas_pagadas_sq, Value(0)),
            cuotas_vencidas=Coalesce(cuotas_vencidas_sq, Value(0)),
            total_pagado=Coalesce(total_pagado_sq, Value(Decimal('0.00'))),
            saldo_total=Coalesce(saldo_total_sq, Value(Decimal('0.00'))),

            # NUEVO:
            cuotas_parciales=Coalesce(cuotas_parciales_sq, Value(0)),

            proximo_vto=proximo_vto_sq,
            
            estado_cartera=Case(
            When(cuotas_vencidas__gt=0, then=Value('En mora')),
            default=Value('Al día'),
            output_field=models.CharField()
),
        )
        
        .order_by('-id')
    )

    return render(request, 'listar_estudiantes.html', {'estudiantes': estudiantes})


@login_required
def detalle_estudiante(request, id):
    hoy = now().date()

    estudiante = get_object_or_404(
        Estudiante.objects.select_related('nivel', 'sede', 'acudiente', 'horario'),
        id=id
    )

    contratos = Contrato.objects.filter(estudiante=estudiante).order_by('-id')
    contrato_activo = contratos.first() if contratos.exists() else None

    cuotas = []
    kpis = {
        'saldo_pendiente': Decimal('0.00'),
        'total_pagado': Decimal('0.00'),
        'vencidas_count': 0,
        'vencidas_valor': Decimal('0.00'),
        'proximo_vencimiento': None,
        'ultimo_pago_fecha': None,
        'ultimo_pago_valor': None,
        'ultimo_pago_medio': None,
    }

    if contrato_activo:
        cuotas = (
            Cuota.objects
            .filter(contrato=contrato_activo)
            .annotate(
                pagado=Coalesce(
                    Sum('pagos__valor_pagado'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
            )
            .annotate(
                saldo=F('valor') - F('pagado'),
                es_vencida_roja=Case(
                    When(Q(fecha_vencimiento__lt=hoy) & Q(valor__gt=F('pagado')), then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField()
                )
            )
            .order_by('numero')
        )

        resumen = cuotas.aggregate(
            saldo_pendiente=Coalesce(Sum('saldo'), Value(Decimal('0.00'))),

            vencidas_count=Coalesce(Sum(
                Case(
                    When(es_vencida_roja=True, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField()
                )
            ), Value(0)),

            vencidas_valor=Coalesce(Sum(
                Case(
                    When(es_vencida_roja=True, then=F('saldo')),
                    default=Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            ), Value(Decimal('0.00'))),
        )

        kpis['saldo_pendiente'] = resumen['saldo_pendiente'] or Decimal('0.00')
        kpis['vencidas_count'] = int(resumen['vencidas_count'] or 0)
        kpis['vencidas_valor'] = resumen['vencidas_valor'] or Decimal('0.00')

        kpis['proximo_vencimiento'] = (
            cuotas
            .filter(saldo__gt=0)
            .order_by('fecha_vencimiento')
            .values_list('fecha_vencimiento', flat=True)
            .first()
        )

        total_pagado = (
            Pago.objects
            .filter(contrato=contrato_activo)
            .aggregate(total=Coalesce(Sum('valor_pagado'), Value(Decimal('0.00'))))
        )['total']

        # ✅ ESTA LÍNEA ES LA QUE TE FALTA
        kpis['total_pagado'] = total_pagado or Decimal('0.00')

        ultimo_pago = (
            Pago.objects
            .filter(contrato=contrato_activo)
            .order_by('-fecha_pago', '-id')
            .values('fecha_pago', 'valor_pagado', 'medio_pago__nombre')[:1]
        )

        if ultimo_pago:
            up = ultimo_pago[0]
            medio = up.get('medio_pago__nombre') or ''

            kpis['ultimo_pago_fecha'] = up['fecha_pago']
            kpis['ultimo_pago_valor'] = up['valor_pagado']
            kpis['ultimo_pago_medio'] = medio

    return render(request, 'detalle_estudiante.html', {
        'estudiante': estudiante,
        'contrato': contrato_activo,
        'cuotas': cuotas,
        'hoy': hoy,
        'kpis': kpis,
    })
    
@login_required
def listado_cxc(request):
    """
    Listado de CUOTAS (una fila por cuota) con filtros y paginación.
    - Muestra todas las cuotas (vencidas, pendientes, parciales y pagadas).
    - Filtros: q, estado, nivel, horario, fv_desde/fv_hasta, medio, factura, referencia, con_pago, sede.
    - Anota: total pagado por cuota, último pago (fecha/medio/factura/obs/referencia), SALDO y es_vencida_roja.
    """
    hoy = now().date()
    sede_ids = user_sede_ids(request.user)

    # --------- Subqueries: último pago por cuota (legacy) ---------
    pagos_ordenados = Pago.objects.filter(cuota_id=OuterRef('pk')).order_by('-fecha_pago', '-id')
    ultimo_pago_fecha      = Subquery(pagos_ordenados.values('fecha_pago')[:1])
    ultimo_pago_medio      = Subquery(pagos_ordenados.values('medio_pago__nombre')[:1])
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
            ultimo_pago_referencia=ultimo_pago_referencia,
        )
        .annotate(saldo=F('valor') - F('pagado'))
        .annotate(
            es_vencida_roja=Case(
                When(Q(fecha_vencimiento__lt=hoy) & Q(valor__gt=F('pagado')), then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        .order_by('-id', 'contrato__estudiante__id', 'fecha_vencimiento', 'numero')
    )

    # --------- Seguridad por sede (B) ---------
    if sede_ids:
        qs = qs.filter(contrato__estudiante__sede_id__in=sede_ids)

    # --------- Parámetros de filtro ---------
    q_text     = (request.GET.get('q') or '').strip()
    estado     = (request.GET.get('estado') or '').strip()          # Pendiente/Parcial/Vencida/Pagada
    nivel_id   = (request.GET.get('nivel') or '').strip()
    horario_id = (request.GET.get('horario') or '').strip()
    fv_desde   = (request.GET.get('fv_desde') or '').strip()        # YYYY-MM-DD
    fv_hasta   = (request.GET.get('fv_hasta') or '').strip()
    medio      = (request.GET.get('medio') or '').strip()           # Banco/Nequi/Transferencia/Efectivo/Otro
    factura    = (request.GET.get('factura') or '').strip()
    referencia = (request.GET.get('referencia') or '').strip()
    # Si el usuario NO está restringido por sede_ids, se permite filtrar por sede desde GET
    sede_id    = (request.GET.get('sede') or '').strip() if not sede_ids else ''

    # Texto libre (incluye referencia)
    if q_text:
        filtros = (
            Q(contrato__estudiante__nombre_completo__icontains=q_text) |
            Q(contrato__estudiante__documento__icontains=q_text) |
            Q(contrato__estudiante__acudiente__documento__icontains=q_text) |
            Q(contrato__estudiante__acudiente__nombre_completo__icontains=q_text) |
            Q(pagos__numero_factura__icontains=q_text) |
            Q(pagos__referencia__icontains=q_text)
        )
        # (C) mejorar manejo cuando q es numérico (posible contrato_id)
        if q_text.isdigit():
            qs = qs.filter(Q(contrato_id=int(q_text)) | filtros).distinct()
        else:
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
            Pago.objects.filter(
                cuota_id=OuterRef('pk'),
                medio_pago__nombre__iexact=medio
            )
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
    if (request.GET.get('con_pago') or '').strip() == 'si':
        qs = qs.filter(pagado__gt=0)
    elif (request.GET.get('con_pago') or '').strip() == 'no':
        qs = qs.filter(pagado__lte=0)

    # Filtro por sede desde GET solo si NO hay restricción previa
    if sede_id:
        qs = qs.filter(contrato__estudiante__sede_id=sede_id)

    # --------- Catálogos ---------
    niveles  = Nivel.objects.all().order_by('nombre')
    horarios = Horario.objects.all().order_by('descripcion')
    # Si el usuario ya está restringido por sede_ids, no mostramos selector global de sedes
    sedes    = [] if sede_ids else list(Sede.objects.all().order_by('nombre'))

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
        'factura': factura, 'referencia': referencia, 'con_pago': (request.GET.get('con_pago') or '').strip(),
        'sede_id': sede_id,
        'per_page': per_page,

        # catálogos
        'niveles': niveles,
        'horarios': horarios,
        'sedes': sedes,
        'ESTADOS': ESTADOS,
        'MEDIOS': MEDIOS,

        'hoy': hoy,
    }
    return render(request, 'listado_cxc.html', context)


@login_required
def aplicar_pago(request):
    """
    GET  => Retorna historial de pagos de una cuota en JSON (para el modal) + previas con saldo.
            Parámetro requerido: ?cuota_id=<id>

    POST => Crea un Pago.
            - Bloquea si hay cuotas previas con saldo.
            - Si modo=auto, distribuye el pago primero en previas y luego en la actual.
            - Registra automáticamente el ingreso contable.
    """
    from django.utils.dateparse import parse_date

    # =====================================================
    # Helper de seguridad por sede
    # =====================================================
    def obtener_cuota_segura(cuota_id_str):
        cuota = get_object_or_404(
            Cuota.objects.select_related('contrato', 'contrato__estudiante__sede'),
            pk=cuota_id_str
        )
        sede_ids = user_sede_ids(request.user)
        if sede_ids and cuota.contrato.estudiante.sede_id not in sede_ids:
            return None, JsonResponse(
                {'ok': False, 'error': 'No tiene permisos sobre esta sede.'},
                status=403
            )
        return cuota, None

    # =====================================================
    # Helper: cuotas previas con saldo (para GET)
    # =====================================================
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
                saldo=F('valor') - F('pagado')
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

    # =====================================================
    # GET → historial de pagos (modal)
    # =====================================================
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
            .values(
                'id',
                'fecha_pago',
                'valor_pagado',
                'medio_pago__nombre',
                'numero_factura',
                'referencia',
                'observacion'
            )
        )

        pagos = []
        for p in pagos_qs:
            medio = (p.get('medio_pago__nombre') or '')
            medio = 'Banco' if medio == 'Transferencia' else medio
            pagos.append({
                'id': p['id'],
                'fecha_pago': p['fecha_pago'].strftime('%Y-%m-%d'),
                'valor_pagado': str(p['valor_pagado']),
                'medio_pago': medio,
                'numero_factura': p['numero_factura'] or '',
                'referencia': p['referencia'] or '',
                'observacion': p['observacion'] or '',
            })

        previas_qs = previas_pendientes_for_get(cuota)

        return JsonResponse({
            'ok': True,
            'pagos': pagos,
            'previas_pendientes': serializar_previas(previas_qs)
        })

    # =====================================================
    # POST → aplicar pago
    # =====================================================
    cuota_id = (request.POST.get('cuota_id') or '').strip()
    valor_str = (request.POST.get('valor_pagado') or '').strip()
    numero_factura = (request.POST.get('numero_factura') or '').strip() or None
    referencia = (request.POST.get('referencia') or '').strip()
    observacion = (request.POST.get('observacion') or '').strip()
    fecha_str = (request.POST.get('fecha_pago') or '').strip()
    modo = (request.POST.get('modo') or '').strip()  # '', 'auto'
    fecha_pago = parse_date(fecha_str) if fecha_str else now().date()
    forma_pago_txt = (request.POST.get('forma_pago') or '').strip()

    if not forma_pago_txt:
        return JsonResponse({'ok': False, 'error': 'Debe seleccionar un medio de pago.'}, status=400)

    medio_pago = MedioPago.objects.filter(
        nombre__iexact=forma_pago_txt,
        activo=True
    ).first()

    if not medio_pago:
        return JsonResponse(
            {'ok': False, 'error': 'Medio de pago no válido o inactivo.'},
            status=400
        )
    
    if not cuota_id:
        return JsonResponse({'ok': False, 'error': 'Falta cuota_id.'}, status=400)

    cuota, resp_error = obtener_cuota_segura(cuota_id)
    if resp_error:
        return resp_error

    saldo_actual_previo = (cuota.valor or Decimal('0.00')) - (cuota.valor_pagado or Decimal('0.00'))

    if not valor_str:
        if saldo_actual_previo <= 0:
            return JsonResponse({'ok': False, 'error': 'No hay saldo por pagar.'}, status=400)
        return JsonResponse({'ok': False, 'error': 'Falta el valor a pagar.'}, status=400)

    if not referencia:
        return JsonResponse({'ok': False, 'error': 'La referencia es obligatoria.'}, status=400)

    try:
        valor = Decimal(valor_str)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Valor inválido.'}, status=400)

    if valor <= 0:
        return JsonResponse({'ok': False, 'error': 'El valor debe ser mayor a cero.'}, status=400)

    forma_pago_txt = (request.POST.get('forma_pago') or '').strip()

    if not forma_pago_txt:
        return JsonResponse({'ok': False, 'error': 'Debe seleccionar un medio de pago.'}, status=400)

    medio_pago = MedioPago.objects.filter(
        nombre__iexact=forma_pago_txt,
        activo=True
    ).first()

    if not medio_pago:
        return JsonResponse(
            {'ok': False, 'error': 'Medio de pago no válido o inactivo.'},
            status=400
        )

    # =====================================================
    # Validación previa (FUERA del atomic) para evitar returns dentro de la transacción
    # =====================================================
    if modo != 'auto':
        previas_exist = (
            Cuota.objects
            .filter(contrato_id=cuota.contrato_id, numero__lt=cuota.numero)
            .annotate(saldo=F('valor') - F('valor_pagado'))
            .filter(saldo__gt=0)
            .exists()
        )
        if previas_exist:
            return JsonResponse({
                'ok': False,
                'error': 'Existen cuotas anteriores con saldo pendiente.',
                'error_code': 'previas_pendientes'
            }, status=400)

    # =====================================================
    # Excepción controlada para romper atomic con rollback sin return interno
    # =====================================================
    class _AbortarPago(Exception):
        def __init__(self, payload, status=400):
            self.payload = payload
            self.status = status
            super().__init__(payload.get('error', 'Abortado'))

    # =====================================================
    # TRANSACCIÓN
    # =====================================================
    try:
        with transaction.atomic():

            cuotas_locked = list(
                Cuota.objects.select_for_update()
                .filter(
                    Q(id=cuota.id) |
                    Q(contrato_id=cuota.contrato_id, numero__lt=cuota.numero)
                )
                .select_related('contrato')
                .order_by('numero')
            )

            cuota = next(c for c in cuotas_locked if c.id == cuota.id)
            previas_locked = [c for c in cuotas_locked if c.id != cuota.id]

            def saldo_de(c):
                return (c.valor or Decimal('0.00')) - (c.valor_pagado or Decimal('0.00'))

            previas_con_saldo = [c for c in previas_locked if saldo_de(c) > 0]
            saldo_actual = saldo_de(cuota)

            # Re-validación con locks (consistencia)
            if previas_con_saldo and modo != 'auto':
                raise _AbortarPago({
                    'ok': False,
                    'error': 'Existen cuotas anteriores con saldo pendiente.',
                    'error_code': 'previas_pendientes'
                }, status=400)

            if modo == 'auto':
                capacidad_total = sum((saldo_de(c) for c in previas_con_saldo), Decimal('0.00')) + saldo_actual
                if valor > capacidad_total:
                    raise _AbortarPago({
                        'ok': False,
                        'error': 'El valor supera la capacidad disponible.'
                    }, status=400)

            # =====================================================
            # Registrar ingreso (tu modelo actual SOLO usa forma_pago texto)
            # =====================================================
            def registrar_ingreso(cuota_obj, aplicar_monto, pago_obj, fecha_pago, usuario, numero_factura):
                Ingreso.objects.create(
                    sede=cuota_obj.contrato.estudiante.sede,
                    #estudiante=cuota_obj.contrato.estudiante,
                    concepto_ingreso=ConceptoIngreso.objects.get(pk=1),

                    valor_pagado=aplicar_monto,
                    fecha_pago=fecha_pago,

                    forma_pago=medio_pago.nombre,

                    referencia=referencia or None,
                    observacion=observacion or None,
                    tipo_registro='pago_cuota',
                    usuario_registro=usuario,
                    pago=pago_obj,
                    contrato=cuota_obj.contrato,
                    cuota=cuota_obj,
                    numero_factura=numero_factura
                )

            # =====================================================
            # Aplicación de pago (crea Pago + Ingreso + actualiza Cuota)
            # =====================================================
            def aplicar_a_cuota(c, monto):
                aplicar = min(monto, saldo_de(c))
                if aplicar <= 0:
                    return Decimal('0.00')

                pago_obj = Pago.objects.create(
                    contrato=c.contrato,
                    cuota=c,
                    fecha_pago=fecha_pago,
                    valor_pagado=aplicar,
                    medio_pago=medio_pago,
                    numero_factura=numero_factura,
                    referencia=referencia,
                    observacion=observacion,
                )

                registrar_ingreso(c, aplicar, pago_obj, fecha_pago, request.user, numero_factura)

                c.valor_pagado = (c.valor_pagado or Decimal('0.00')) + aplicar
                c.estado = 'Pagada' if c.valor_pagado >= c.valor else 'Parcial'
                c.save(update_fields=['valor_pagado', 'estado'])
                return aplicar

            distribucion = []
            monto = valor

            if previas_con_saldo and modo == 'auto':
                for c_prev in previas_con_saldo:
                    aplicado = aplicar_a_cuota(c_prev, monto)
                    monto -= aplicado
                    if aplicado > 0:
                        distribucion.append({'cuota_id': c_prev.id, 'aplicado': str(aplicado)})
                    if monto <= 0:
                        break

            if monto > 0:
                aplicado = aplicar_a_cuota(cuota, monto)
                if aplicado > 0:
                    distribucion.append({'cuota_id': cuota.id, 'aplicado': str(aplicado)})

            return JsonResponse({'ok': True, 'distribucion': distribucion})

    except _AbortarPago as ex:
        return JsonResponse(ex.payload, status=ex.status)

    except ConceptoIngreso.DoesNotExist:
        return JsonResponse({
            'ok': False,
            'error': 'No existe ConceptoIngreso con pk=1 (configuración contable incompleta).'
        }, status=500)

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

    sede_ids = user_sede_ids(request.user)
    if sede_ids and pago.cuota.contrato.estudiante.sede_id not in sede_ids:
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

        hoy = now().date()

        if nuevo_pagado >= cuota.valor:
            cuota.estado = 'Pagada'
        elif cuota.fecha_vencimiento < hoy and nuevo_pagado < cuota.valor:
            cuota.estado = 'Vencida'
        elif nuevo_pagado > 0 and nuevo_pagado < cuota.valor:
            cuota.estado = 'Parcial'
        else:
            cuota.estado = 'Pendiente'

        cuota.valor_pagado = nuevo_pagado
        cuota.save(update_fields=['valor_pagado', 'estado'])

    return JsonResponse({'ok': True})


@login_required
def nuevo_contrato(request):
    # =========================
    # IMPORTS LOCALES (Opción A aplicada)
    # =========================
    from django.utils.dateparse import parse_date
    from django.db import IntegrityError, transaction
    from calendar import monthrange
    from datetime import date
    from decimal import Decimal, ROUND_HALF_UP
    import re  # ✅ CORRECCIÓN APLICADA (Pylance / runtime)

    # =========================
    # Helpers
    # =========================

    def _p(key_pref, key_plain, default=None):
        val = request.POST.get(key_pref)
        if val is None or val == "":
            val = request.POST.get(key_plain, default)
        return val

    def add_months(d: date, months: int) -> date:
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        last_day = monthrange(y, m)[1]
        return date(y, m, min(d.day, last_day))

    def compute_fecha_inicio_from_corte(corte: int) -> date:
        today = date.today()
        y = today.year + (today.month // 12)
        m = (today.month % 12) + 1
        last_day = monthrange(y, m)[1]
        dia = min(corte, last_day)
        return date(y, m, dia)

    # Helper: normaliza COP "10.000.000" / "$ 10.000.000" / "10000000"
    def cop_to_decimal(raw, default=Decimal('0.00')):
        if raw is None:
            return default
        s = str(raw).strip()
        if not s:
            return default
        s = s.replace("$", "").replace(" ", "")
        digits = re.sub(r"[^\d]", "", s)
        if digits == "":
            return default
        try:
            return Decimal(digits)
        except Exception:
            return default

    # =========================
    # POST
    # =========================
    if request.method == 'POST':

        estudiante_form = EstudianteForm(request.POST, prefix='estudiante')

        post_contrato = request.POST.copy()
        if not post_contrato.get('estado'):
            post_contrato['estado'] = 'Activo'
        contrato_form = ContratoForm(post_contrato)

        # ---- ACUDIENTE (lookup por documento) ----
        doc_acu = _p('acudiente-documento', 'documento', '')
        acudiente_existente = None
        if doc_acu:
            acudiente_existente = Acudiente.objects.filter(documento=doc_acu).first()

        if acudiente_existente:
            acudiente_form = AcudienteForm(prefix='acudiente')
        else:
            acudiente_form = AcudienteForm(request.POST, prefix='acudiente')

        # =========================
        # VALIDACIONES
        # =========================
        if not acudiente_existente and not acudiente_form.is_valid():
            messages.error(request, f"Acudiente inválido: {acudiente_form.errors}")
            return render(request, 'nuevo_contrato.html', {
                'form_acudiente': acudiente_form,
                'form_estudiante': estudiante_form,
                'form_contrato': contrato_form,
            })

        if not estudiante_form.is_valid():
            messages.error(request, f"Estudiante inválido: {estudiante_form.errors}")
            return render(request, 'nuevo_contrato.html', {
                'form_acudiente': acudiente_form,
                'form_estudiante': estudiante_form,
                'form_contrato': contrato_form,
            })

        if not contrato_form.is_valid():
            messages.error(request, f"Contrato inválido: {contrato_form.errors}")
            return render(request, 'nuevo_contrato.html', {
                'form_acudiente': acudiente_form,
                'form_estudiante': estudiante_form,
                'form_contrato': contrato_form,
            })

        # =========================
        # GUARDADO ATÓMICO
        # =========================
        try:
            with transaction.atomic():

                # ACUDIENTE
                if acudiente_existente:
                    acudiente = acudiente_existente
                else:
                    acudiente = acudiente_form.save()

                # ESTUDIANTE
                estudiante = estudiante_form.save(commit=False)
                estudiante.acudiente = acudiente
                estudiante.save()

                # CONTRATO (evitar duplicado)
                if Contrato.objects.filter(estudiante=estudiante).exists():
                    raise ValueError('Este estudiante ya tiene un contrato registrado.')

                contrato = contrato_form.save(commit=False)
                contrato.acudiente = acudiente
                contrato.estudiante = estudiante

                # Día de corte
                try:
                    dia_corte = int((request.POST.get('dia_corte') or '5').strip())
                except ValueError:
                    dia_corte = 5
                if dia_corte not in (5, 20):
                    dia_corte = 5

                fecha_inicio = compute_fecha_inicio_from_corte(dia_corte)

                # =========================
                # CÁLCULO CUOTAS (COP ENTEROS) basado en VALOR A FINANCIAR
                # =========================
                total = Decimal(contrato.valor_total)
                n = int(contrato.numero_cuotas)

                # cuota_inicial viene del HTML: name="cuota_inicial"
                cuota_inicial = cop_to_decimal(request.POST.get('cuota_inicial'), default=Decimal('0'))
                if cuota_inicial < 0:
                    cuota_inicial = Decimal('0')

                financiar = total - cuota_inicial
                if financiar < 0:
                    financiar = Decimal('0')

                # ✅ CUOTA BASE ENTERA (sin decimales)
                valor_base = (financiar / Decimal(n)).to_integral_value(rounding=ROUND_HALF_UP)

                # ✅ Residuo exacto (entero) para cuadrar la suma total
                residuo = financiar - (valor_base * n)

                # Guardamos en contrato la cuota pactada (entera) y fechas
                contrato.valor_cuota_pactada = valor_base
                contrato.estado = 'Activo'
                contrato.fecha_inicio = fecha_inicio
                contrato.fecha_fin = add_months(fecha_inicio, n - 1)
                contrato.save()

                # =========================
                # CUOTAS (COP ENTEROS) basadas en financiar
                # =========================
                for i in range(1, n + 1):
                    vence = add_months(fecha_inicio, i - 1)
                    valor_i = valor_base

                    # ✅ Ajuste del residuo solo en la última cuota
                    if i == n and residuo != Decimal('0'):
                        valor_i = valor_base + residuo

                    Cuota.objects.create(
                        contrato=contrato,
                        numero=i,
                        fecha_vencimiento=vence,
                        valor=valor_i
                    )

            return redirect('listar_estudiantes')

        except ValueError as e:
            contrato_form.add_error(None, str(e))
        except IntegrityError as e:
            contrato_form.add_error(None, f'Error de integridad: {e}')
        except Exception as e:
            contrato_form.add_error(None, f'No se pudo crear el contrato: {e}')

        return render(request, 'nuevo_contrato.html', {
            'form_acudiente': acudiente_form,
            'form_estudiante': estudiante_form,
            'form_contrato': contrato_form,
        })

    # =========================
    # GET
    # =========================
    return render(request, 'nuevo_contrato.html', {
        'form_acudiente': AcudienteForm(prefix='acudiente'),
        'form_estudiante': EstudianteForm(prefix='estudiante'),
        'form_contrato': ContratoForm(),
    })
    
@require_GET
def buscar_acudiente_por_documento(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    documento_raw = request.GET.get("documento")
    if not documento_raw or not documento_raw.strip():
        return JsonResponse({"existe": False, "error": "Documento inválido"}, status=400)

    documento = documento_raw.strip()

    try:
        acudiente = Acudiente.objects.get(documento=documento)
        data = {
            "existe": True,
            "nombre_completo": acudiente.nombre_completo,
            "tipo_documento": acudiente.tipo_documento,
            "telefono": acudiente.telefono,
            "email": acudiente.email,
        }
    except Acudiente.DoesNotExist:
        data = {"existe": False}

    return JsonResponse(data)


@login_required
def nuevo_ingreso(request):
    ES_CLEVEL = request.user.is_superuser or request.user.groups.filter(
        name__in=['Admin', 'CEO', 'CFO']
    ).exists()

    if request.method == 'POST':
        form = IngresoForm(request.POST, user=request.user)
        if form.is_valid():
            ingreso = form.save(commit=False)
            ingreso.usuario_registro = request.user

            if not ES_CLEVEL:
                perfil = getattr(request.user, 'perfil', None)
                if not perfil or perfil.sedes.count() == 0:
                    messages.error(request, 'Tu usuario no tiene sede asignada.')
                    return redirect('nuevo_ingreso')

                # Validar que la sede elegida está entre las permitidas
                if ingreso.sede not in perfil.sedes.all():
                    messages.error(request, 'No tienes permiso para registrar en esa sede.')
                    return redirect('nuevo_ingreso')

            # 🔹 Forzar tipo_registro a 'otro_ingreso' cuando viene del formulario
            ingreso.tipo_registro = 'otro_ingreso'
            ingreso.save()
            messages.success(request, 'Ingreso registrado correctamente.')
            return redirect('nuevo_ingreso')
        else:
            messages.error(request, 'Error al guardar el ingreso. Revisa los campos.')
    else:
        form = IngresoForm(user=request.user)

    # --------- Listado de ingresos ---------
    if ES_CLEVEL:
        ingresos = (
            Ingreso.objects
            .filter(tipo_registro='otro_ingreso')
            .select_related('sede', 'usuario_registro')
            .order_by('-id')
        )
    else:
        ingresos = (
            Ingreso.objects
            .filter(usuario_registro=request.user, tipo_registro='otro_ingreso')
            .select_related('sede', 'usuario_registro')
            .order_by('-id')
        )

    return render(request, 'nuevo_ingreso.html', {
        'form': form,
        'ingresos': ingresos,
    })