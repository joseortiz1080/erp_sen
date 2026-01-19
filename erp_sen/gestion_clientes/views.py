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
    Estudiante, Contrato, Cuota, Ingreso, Nivel, Horario, Sede, Acudiente,
    MedioPago, ConceptoIngreso, PagoAplicacion, ConsecutivoComprobante,
    Permiso, Rol, RolPermiso, UsuarioRol, ConceptoGasto, Gasto, MedioPago
)
from django.views.decorators.csrf import ensure_csrf_cookie

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse

from django.template import TemplateDoesNotExist
from functools import wraps

from django.contrib import messages
from .forms import GastoForm
from .models import Sede
from django.db import transaction


# ============================
# Roles y permisos (ERP SEN)
# ============================

def user_has_perm(user, codigo_permiso: str) -> bool:
    """
    Permisos por roles (modelos propios).
    - Superuser: True
    - Permiso: campo `codigo` (según tu error: NO es codename)
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    codigo_permiso = (codigo_permiso or "").strip()
    if not codigo_permiso:
        return False

    # Import local para no tocar demasiado el header
    from .models import Permiso

    return Permiso.objects.filter(
        codigo=codigo_permiso,
        activo=True,
        roles__usuarios=user,
        roles__activo=True,
    ).exists()



def permiso_requerido(codigo_permiso: str):
    """Decorador que bloquea con 403 si no tiene permiso.

    Nota:
    - Debe usarse junto con @login_required en las vistas para que el anónimo
      sea redirigido a login (y no reciba 403).
    - Preserva metadata del view (name/doc) para no romper reverse/CBVs/tests.
    """
    def _decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not user_has_perm(request.user, codigo_permiso):
                # 403 centralizado (handler403)
                raise PermissionDenied("No está autorizado para ver esta vista.")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return _decorator



def custom_403(request, exception=None):
    """Handler 403 central.

    - Renderiza 403.html si existe.
    - Si no existe, devuelve HTML mínimo (para no romper producción).
    """
    msg = None
    try:
        msg = str(exception) if exception else None
    except Exception:
        msg = None

    try:
        return render(request, "403.html", {"mensaje": msg}, status=403)
    except TemplateDoesNotExist:
        texto = msg or "No está autorizado para ver esta vista."
        return HttpResponse(
            f"<h1>403 - No autorizado</h1><p>{texto}</p>",
            status=403
        )


# ============================
# Administración: Roles y Permisos
# ============================
@login_required
@permiso_requerido("admin_roles_permisos")
def admin_roles_permisos(request):
    """Administración: asignación de permisos a roles.

    Flujo esperado por el template:
    - GET con ?rol_id=... => carga checks del rol
    - POST => guarda (reemplazo total) y redirige a la misma vista con el rol seleccionado

    Nota técnica:
    - Usamos el M2M `Rol.permisos` (Django gestiona la tabla through `RolPermiso`).
    - Evitamos borrar/crear manualmente en `RolPermiso` para no desalinearnos del M2M.
    """

    # Roles y permisos activos
    roles = (
        Rol.objects.filter(activo=True)
        .annotate(permisos_count=Count('permisos', distinct=True))
        .order_by('nombre')
    )
    permisos = Permiso.objects.filter(activo=True).order_by('codigo', 'nombre')

    # GET: rol seleccionado (acepta alias para evitar desalineación template/urls)
    rol_id_get = (
        request.GET.get('rol_id')
        or request.GET.get('rol')
        or request.GET.get('role_id')
        or ''
    ).strip()

    rol_seleccionado = None
    if rol_id_get:
        rol_seleccionado = get_object_or_404(Rol, id=rol_id_get, activo=True)

    # POST: puede ser “Cargar” (redirige a GET con rol_id) o “Guardar” (reemplazo total)
    if request.method == 'POST':
        rol_id = (
            request.POST.get('rol_id')
            or request.POST.get('rol')
            or request.POST.get('role_id')
            or ''
        ).strip()

        # Si el template envía un botón tipo “cargar” por POST, lo tratamos como navegación
        if 'cargar' in request.POST or 'btn_cargar' in request.POST:
            if rol_id:
                return redirect(f"{request.path}?rol_id={rol_id}")
            messages.error(request, 'Seleccione un rol para cargar.')
            return redirect('admin_roles_permisos')

        # Guardar permisos
        permisos_ids = (
            request.POST.getlist('permisos')
            or request.POST.getlist('permisos[]')
        )

        if not rol_id:
            messages.error(request, 'Seleccione un rol para guardar permisos.')
            return redirect('admin_roles_permisos')

        rol = get_object_or_404(Rol, id=rol_id, activo=True)

        # Normalizar IDs (evita basura en POST)
        try:
            permisos_ids_int = {int(x) for x in permisos_ids}
        except Exception:
            permisos_ids_int = set()

        permisos_validos_ids = list(
            Permiso.objects
            .filter(id__in=permisos_ids_int, activo=True)
            .values_list('id', flat=True)
        )

        with transaction.atomic():
            # Reemplazo total del set de permisos del rol
            rol.permisos.set(permisos_validos_ids)

        messages.success(request, f"Permisos actualizados para el rol: {rol.nombre}")
        return redirect(f"{request.path}?rol_id={rol.id}")

    # IDs asignados (para checks del template)
    permisos_asignados_ids = set()
    if rol_seleccionado:
        permisos_asignados_ids = set(
            rol_seleccionado.permisos.filter(activo=True).values_list('id', flat=True)
        )

    return render(request, 'seguridad/admin_roles_permisos.html', {
        'roles': roles,
        'permisos': permisos,
        'rol_seleccionado': rol_seleccionado,
        'permisos_asignados_ids': permisos_asignados_ids,
        'rol_id_get': rol_id_get,
    })


# --- NUEVA VISTA: asignación de roles a usuarios (después de admin_roles_permisos) ---

@login_required
@permiso_requerido("admin_usuarios_roles")
def admin_usuarios_roles(request):
    """Administración: asignación de ROLES a usuarios (auth.User).

    Vista (opción 1): mostrar `username + email`.

    - GET: lista usuarios del sistema y roles activos; marca roles asignados.
    - POST:
        A) Guardado MASIVO (recomendado): recibe checkboxes con nombre `roles_<user_id>`
           y reemplaza el set completo de roles de cada usuario enviado.
        B) Guardado POR USUARIO: si viene `user_id`, usa `roles` como lista de IDs.

    Seguridad:
    - Requiere login.
    - Requiere permiso `gestionar_roles` (o superuser por regla en `user_has_perm`).
    """
    from django.contrib.auth.models import User

    roles = Rol.objects.filter(activo=True).order_by('nombre')

    # -----------------------------
    # GET: filtros/paginación (para no cargar miles de usuarios en producción)
    # -----------------------------
    q_text = (request.GET.get('q') or '').strip()
    try:
        per_page = int(request.GET.get('per_page', 50))
    except ValueError:
        per_page = 50
    page = request.GET.get('page', 1)

    usuarios_qs = User.objects.all().order_by('username', 'email')

    if q_text:
        usuarios_qs = usuarios_qs.filter(
            Q(username__icontains=q_text) |
            Q(email__icontains=q_text) |
            Q(first_name__icontains=q_text) |
            Q(last_name__icontains=q_text)
        )

    # -----------------------------
    # POST: guardar asignaciones
    # -----------------------------
    if request.method == 'POST':
        # Caso B: guardado por usuario (si tu template lo usa)
        user_id = (request.POST.get('user_id') or '').strip()
        if user_id:
            roles_ids = request.POST.getlist('roles')  # lista de IDs seleccionados

            try:
                usuario = User.objects.get(id=user_id)
            except User.DoesNotExist:
                messages.error(request, 'El usuario indicado no existe.')
                return redirect('admin_usuarios_roles')

            roles_validos = list(
                Rol.objects.filter(id__in=roles_ids, activo=True).values_list('id', flat=True)
            )

            with transaction.atomic():
                UsuarioRol.objects.filter(usuario=usuario).delete()
                if roles_validos:
                    UsuarioRol.objects.bulk_create(
                        [UsuarioRol(usuario=usuario, rol_id=r_id) for r_id in roles_validos]
                    )

            messages.success(request, f"Roles actualizados para el usuario: {usuario.username}")
            return redirect('admin_usuarios_roles')

        # Caso A: guardado masivo (checkboxes roles_<user_id>)
        # Ej: roles_12 = ["1", "3"]
        keys = [k for k in request.POST.keys() if k.startswith('roles_')]
        if not keys:
            messages.warning(request, 'No se recibieron cambios de roles para guardar.')
            return redirect('admin_usuarios_roles')

        user_ids = []
        for k in keys:
            try:
                user_ids.append(int(k.split('_', 1)[1]))
            except Exception:
                continue

        if not user_ids:
            messages.warning(request, 'No se identificaron usuarios válidos para actualizar.')
            return redirect('admin_usuarios_roles')

        # Solo usuarios existentes
        usuarios_map = {u.id: u for u in User.objects.filter(id__in=user_ids)}

        # IDs de roles válidos (activos)
        roles_validos_set = set(roles.values_list('id', flat=True))

        with transaction.atomic():
            # Borrado en bloque de asignaciones actuales de esos usuarios
            UsuarioRol.objects.filter(usuario_id__in=usuarios_map.keys()).delete()

            bulk = []
            for uid in usuarios_map.keys():
                raw_ids = request.POST.getlist(f'roles_{uid}')
                for rid_str in raw_ids:
                    try:
                        rid = int(rid_str)
                    except Exception:
                        continue
                    if rid in roles_validos_set:
                        bulk.append(UsuarioRol(usuario_id=uid, rol_id=rid))

            if bulk:
                UsuarioRol.objects.bulk_create(bulk)

        messages.success(request, 'Roles actualizados correctamente.')
        return redirect('admin_usuarios_roles')

    # -----------------------------
    # GET: mapa usuario_id -> set(rol_id)
    # (solo roles activos)
    # -----------------------------
    asignados = UsuarioRol.objects.filter(
        rol__activo=True,
        usuario__is_active=True,
    ).values_list('usuario_id', 'rol_id')

    mapa = {}
    for u_id, r_id in asignados:
        mapa.setdefault(u_id, set()).add(r_id)

    paginator = Paginator(usuarios_qs, per_page)
    page_obj = paginator.get_page(page)

    return render(request, 'seguridad/admin_usuarios_roles.html', {
        'roles': roles,
        'usuarios': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'q': q_text,
        'per_page': per_page,
        'mapa': mapa,
    })


@require_GET
@login_required
def listar_medios_pago(request):
    """
    Retorna medios de pago activos.
    UI: excluye 'Banco' sin eliminarlo de BD (se mantiene para cargues masivos).
    """
    medios = list(
        MedioPago.objects
        .filter(activo=True)
        .exclude(nombre__iexact='Banco')
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
@permiso_requerido("ver_inicio")
def vista_inicial(request):
    return render(request, 'inicio.html')


@ensure_csrf_cookie
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username') or ''
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('vista_inicial')
        return render(request, 'login.html', {'error': True})
    return render(request, 'login.html')

def generar_rc(request, sede):
    """
    Genera un número de comprobante RC único por:
    - sede
    - año
    Formato:
    RC-SEDE-AÑO-XXXXXXXX
    """
    if sede is None:
        raise ValueError('generar_rc: sede no puede ser None')
    year = now().year
    prefijo = 'RC'

    with transaction.atomic():
        consecutivo_obj, created = (
            ConsecutivoComprobante.objects
            .select_for_update()
            .get_or_create(
                sede_id=sede.id,
                prefijo=prefijo,
                year=year,
                defaults={'consecutivo': 0}
            )
        )

        consecutivo_obj.consecutivo += 1
        consecutivo_obj.save(update_fields=['consecutivo'])

        rc = f"{prefijo}-{sede.id}-{year}-{str(consecutivo_obj.consecutivo).zfill(8)}"
        return rc

@login_required
@permiso_requerido("ver_dashboard")
def dashboard_view(request):
    import json
    import calendar
    from datetime import date
    from django.db.models import Sum, F, Value, Q, DecimalField
    from django.db.models.functions import Coalesce, TruncMonth, Cast
    from django.db.models import DateField
    from django.utils.dateparse import parse_date

    hoy = now().date()
    sede_ids = user_sede_ids(request.user)

    # =====================================================
    # Helpers de fechas
    # =====================================================
    def _month_start(y: int, m: int) -> date:
        return date(y, m, 1)

    def _month_end(y: int, m: int) -> date:
        last_day = calendar.monthrange(y, m)[1]
        return date(y, m, last_day)
    
    def _add_months(d: date, months: int) -> date:
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        day = min(d.day, calendar.monthrange(y, m)[1])
        return date(y, m, day)

    # =====================================================
    # QuerySets base (respetando sede)
    # =====================================================
    estudiantes_qs = Estudiante.objects.all()
    contratos_qs = Contrato.objects.all()
    cuotas_qs = Cuota.objects.select_related('contrato__estudiante__sede')
    ingresos_qs = Ingreso.objects.select_related('sede').filter(estado='ACTIVO')

    # (NUEVO) Gastos base
    gastos_qs = Gasto.objects.select_related('sede').filter(estado='ACTIVO')

    if sede_ids:
        estudiantes_qs = estudiantes_qs.filter(sede_id__in=sede_ids)
        contratos_qs = contratos_qs.filter(estudiante__sede_id__in=sede_ids)
        cuotas_qs = cuotas_qs.filter(contrato__estudiante__sede_id__in=sede_ids)
        ingresos_qs = ingresos_qs.filter(sede_id__in=sede_ids)

        # (NUEVO) Seguridad por sede para gastos
        gastos_qs = gastos_qs.filter(sede_id__in=sede_ids)

    # =====================================================
    # (NUEVO) Años disponibles (por data real en ingresos)
    # =====================================================
    years_dates = ingresos_qs.dates('fecha_pago', 'year', order='ASC')
    years = [d.year for d in years_dates] or [hoy.year]  # fallback limpio

    # =====================================================
    # (NUEVO) Método de filtro (selector exclusivo)
    # metodo: total | anio_meses | rango
    # =====================================================
    metodo = (request.GET.get("metodo") or "total").strip().lower()
    if metodo not in ("total", "anio_meses", "rango"):
        metodo = "total"

    # Inputs para año/meses
    anio_str = (request.GET.get("anio") or "").strip()
    mes_inicio_str = (request.GET.get("mes_inicio") or "").strip()
    mes_fin_str = (request.GET.get("mes_fin") or "").strip()

    # Inputs para rango libre
    fecha_desde_str = (request.GET.get("fecha_desde") or "").strip()
    fecha_hasta_str = (request.GET.get("fecha_hasta") or "").strip()

    fecha_desde = None
    fecha_hasta = None
    rango_label = ""

    # =====================================================
    # Cálculo determinista del rango según método
    # =====================================================
    if metodo == "total":
        # Total historia: sin inicio, fin=hoy (cap)
        fecha_desde = None
        fecha_hasta = hoy
        rango_label = "Histórico total"

    elif metodo == "anio_meses":
        # Año obligatorio (si viene vacío, tomamos el último año con data)
        try:
            anio = int(anio_str) if anio_str else (years[-1] if years else hoy.year)
        except ValueError:
            anio = (years[-1] if years else hoy.year)

        # Meses opcionales: si no vienen => año completo
        try:
            mes_inicio = int(mes_inicio_str) if mes_inicio_str else 1
        except ValueError:
            mes_inicio = 1

        try:
            mes_fin = int(mes_fin_str) if mes_fin_str else 12
        except ValueError:
            mes_fin = 12

        # Guardrails meses 1..12
        mes_inicio = max(1, min(12, mes_inicio))
        mes_fin = max(1, min(12, mes_fin))

        # Normalizar: si vienen invertidos
        if mes_inicio > mes_fin:
            mes_inicio, mes_fin = mes_fin, mes_inicio

        fecha_desde = _month_start(anio, mes_inicio)
        fecha_hasta = _month_end(anio, mes_fin)

        # Cap hasta hoy si están pidiendo un periodo futuro
        if fecha_hasta > hoy:
            fecha_hasta = hoy

        # Label corporativo
        if mes_inicio == 1 and mes_fin == 12:
            rango_label = f"Año {anio}"
        elif mes_inicio == mes_fin:
            rango_label = f"{anio} - {calendar.month_name[mes_inicio]}"
        else:
            rango_label = f"{anio} - {calendar.month_name[mes_inicio]} a {calendar.month_name[mes_fin]}"

    else:
        # metodo == "rango"
        fd = parse_date(fecha_desde_str) if fecha_desde_str else None
        fh = parse_date(fecha_hasta_str) if fecha_hasta_str else None

        # Reglas: ambos obligatorios; si falta uno, degradamos a total para evitar ambigüedad
        if not fd or not fh:
            metodo = "total"
            fecha_desde = None
            fecha_hasta = hoy
            rango_label = "Histórico total"
        else:
            # Normalizar orden
            if fd > fh:
                fd, fh = fh, fd

            # Cap fin a hoy
            if fh > hoy:
                fh = hoy

            fecha_desde = fd
            fecha_hasta = fh
            rango_label = f"{fecha_desde.strftime('%Y-%m-%d')} a {fecha_hasta.strftime('%Y-%m-%d')}"

    # =====================================================
    # KPIs operativos (no temporales por falta de campo base)
    # =====================================================
    total_estudiantes = estudiantes_qs.count()
    estudiantes_activos = estudiantes_qs.filter(estado='Activo').count()
    contratos_activos = contratos_qs.filter(estado='Activo').count()

    # =====================================================
    # KPIs financieros/temporales (SÍ responden al rango)
    # - Cuotas vencidas en el rango: por fecha_vencimiento
    # - Ingresos del periodo: por fecha_pago
    # =====================================================
    cuotas_con_saldo = (
        cuotas_qs
        .exclude(numero=0)
        .annotate(
            pagado=Coalesce(
                Sum('aplicaciones__valor_aplicado', filter=Q(aplicaciones__ingreso__estado='ACTIVO')),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
        )
        .annotate(saldo=F('valor') - F('pagado'))
    )

    # Vencidas "en el periodo" (si fecha_desde es None, queda hasta fecha_hasta)
    cuotas_vencidas_qs = cuotas_con_saldo.filter(
        fecha_vencimiento__lte=fecha_hasta,
        saldo__gt=0
    )
    if fecha_desde:
        cuotas_vencidas_qs = cuotas_vencidas_qs.filter(fecha_vencimiento__gte=fecha_desde)

    cuotas_vencidas = cuotas_vencidas_qs.count()
    saldo_vencido = (
        cuotas_vencidas_qs.aggregate(
            total=Coalesce(Sum('saldo'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2))
        )['total']
        or Decimal('0.00')
    )

    # Ingresos del periodo (si fecha_desde None => histórico hasta fecha_hasta)
    ingresos_periodo_qs = ingresos_qs.filter(fecha_pago__lte=fecha_hasta)
    if fecha_desde:
        ingresos_periodo_qs = ingresos_periodo_qs.filter(fecha_pago__gte=fecha_desde)

    ingresos_periodo = (
        ingresos_periodo_qs.aggregate(
            total=Coalesce(Sum('valor_pagado'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2))
        )['total']
        or Decimal('0.00')
    )

    # =====================================================
    # (NUEVO) Gastos del periodo (mismo rango)
    # =====================================================
    gastos_periodo_qs = gastos_qs.filter(fecha_gasto__lte=fecha_hasta)
    if fecha_desde:
        gastos_periodo_qs = gastos_periodo_qs.filter(fecha_gasto__gte=fecha_desde)

    gastos_periodo = (
        gastos_periodo_qs.aggregate(
            total=Coalesce(Sum('valor'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2))
        )['total']
        or Decimal('0.00')
    )

    # =====================================================
    # (NUEVO) Saldo del periodo (ingresos - gastos)
    # =====================================================
    saldo_periodo = (ingresos_periodo or Decimal('0.00')) - (gastos_periodo or Decimal('0.00'))

    # =====================================================
    # (NUEVO) Resumen por sede (ingreso, gasto, saldo) - mismo rango
    # =====================================================
    ingresos_por_sede_rows = (
        ingresos_periodo_qs
        .values('sede_id', 'sede__nombre')
        .annotate(total_ingresos=Coalesce(Sum('valor_pagado'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('sede__nombre')
    )

    gastos_por_sede_rows = (
        gastos_periodo_qs
        .values('sede_id', 'sede__nombre')
        .annotate(total_gastos=Coalesce(Sum('valor'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('sede__nombre')
    )

    sede_map = {}
    for r in ingresos_por_sede_rows:
        sede_map[r['sede_id']] = {
            'sede_id': r['sede_id'],
            'sede_nombre': r['sede__nombre'] or '',
            'ingresos': r['total_ingresos'] or Decimal('0.00'),
            'gastos': Decimal('0.00'),
            'saldo': Decimal('0.00'),
        }

    for r in gastos_por_sede_rows:
        if r['sede_id'] not in sede_map:
            sede_map[r['sede_id']] = {
                'sede_id': r['sede_id'],
                'sede_nombre': r['sede__nombre'] or '',
                'ingresos': Decimal('0.00'),
                'gastos': r['total_gastos'] or Decimal('0.00'),
                'saldo': Decimal('0.00'),
            }
        else:
            sede_map[r['sede_id']]['gastos'] = r['total_gastos'] or Decimal('0.00')

    resumen_por_sede = []
    for _, v in sede_map.items():
        v['saldo'] = (v['ingresos'] or Decimal('0.00')) - (v['gastos'] or Decimal('0.00'))
        resumen_por_sede.append(v)

    resumen_por_sede.sort(key=lambda x: (x['sede_nombre'] or ''))

    # =====================================================
    # (NUEVO) Resumen por medio de pago (ingreso, gasto, saldo) - mismo rango
    # =====================================================
    ingresos_por_medio_rows = (
        ingresos_periodo_qs
        .exclude(medio_pago_id__isnull=True)
        .values('medio_pago_id', 'medio_pago__nombre')
        .annotate(total_ingresos=Coalesce(Sum('valor_pagado'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('medio_pago__nombre')
    )

    gastos_por_medio_rows = (
        gastos_periodo_qs
        .exclude(medio_pago_id__isnull=True)
        .values('medio_pago_id', 'medio_pago__nombre')
        .annotate(total_gastos=Coalesce(Sum('valor'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('medio_pago__nombre')
    )

    medio_map = {}
    for r in ingresos_por_medio_rows:
        medio_map[r['medio_pago_id']] = {
            'medio_id': r['medio_pago_id'],
            'medio_nombre': r['medio_pago__nombre'] or '',
            'ingresos': r['total_ingresos'] or Decimal('0.00'),
            'gastos': Decimal('0.00'),
            'saldo': Decimal('0.00'),
        }

    for r in gastos_por_medio_rows:
        if r['medio_pago_id'] not in medio_map:
            medio_map[r['medio_pago_id']] = {
                'medio_id': r['medio_pago_id'],
                'medio_nombre': r['medio_pago__nombre'] or '',
                'ingresos': Decimal('0.00'),
                'gastos': r['total_gastos'] or Decimal('0.00'),
                'saldo': Decimal('0.00'),
            }
        else:
            medio_map[r['medio_pago_id']]['gastos'] = r['total_gastos'] or Decimal('0.00')

    resumen_por_medio = []
    for _, v in medio_map.items():
        v['saldo'] = (v['ingresos'] or Decimal('0.00')) - (v['gastos'] or Decimal('0.00'))
        resumen_por_medio.append(v)

    resumen_por_medio.sort(key=lambda x: (x['medio_nombre'] or ''))

    # =====================================================
    # (NUEVO) Resumen combinado: Sede -> Medio -> Totales
    # Jerarquía requerida:
    # - Sede
    #   - Método de pago
    #   - Total sede
    # - Total instituto
    # =====================================================

    # Ingresos por sede+medio
    ingresos_sede_medio_rows = (
        ingresos_periodo_qs
        .exclude(medio_pago_id__isnull=True)
        .values('sede_id', 'sede__nombre', 'medio_pago_id', 'medio_pago__nombre')
        .annotate(
            total_ingresos=Coalesce(
                Sum('valor_pagado'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by('sede__nombre', 'medio_pago__nombre')
    )

    # Gastos por sede+medio
    gastos_sede_medio_rows = (
        gastos_periodo_qs
        .exclude(medio_pago_id__isnull=True)
        .values('sede_id', 'sede__nombre', 'medio_pago_id', 'medio_pago__nombre')
        .annotate(
            total_gastos=Coalesce(
                Sum('valor'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by('sede__nombre', 'medio_pago__nombre')
    )

    # Mapa Sede -> Medio
    sede_medio_map = {}

    for r in ingresos_sede_medio_rows:
        sid = r['sede_id']
        mid = r['medio_pago_id']
        sede_nombre = r.get('sede__nombre') or ''
        medio_nombre = r.get('medio_pago__nombre') or ''

        if sid not in sede_medio_map:
            sede_medio_map[sid] = {
                'sede_id': sid,
                'sede_nombre': sede_nombre,
                'medios': {},
                'total_ingresos': Decimal('0.00'),
                'total_gastos': Decimal('0.00'),
                'total_saldo': Decimal('0.00'),
            }

        if mid not in sede_medio_map[sid]['medios']:
            sede_medio_map[sid]['medios'][mid] = {
                'medio_id': mid,
                'medio_nombre': medio_nombre,
                'ingresos': Decimal('0.00'),
                'gastos': Decimal('0.00'),
                'saldo': Decimal('0.00'),
            }

        sede_medio_map[sid]['medios'][mid]['ingresos'] = r.get('total_ingresos') or Decimal('0.00')

    for r in gastos_sede_medio_rows:
        sid = r['sede_id']
        mid = r['medio_pago_id']
        sede_nombre = r.get('sede__nombre') or ''
        medio_nombre = r.get('medio_pago__nombre') or ''

        if sid not in sede_medio_map:
            sede_medio_map[sid] = {
                'sede_id': sid,
                'sede_nombre': sede_nombre,
                'medios': {},
                'total_ingresos': Decimal('0.00'),
                'total_gastos': Decimal('0.00'),
                'total_saldo': Decimal('0.00'),
            }

        if mid not in sede_medio_map[sid]['medios']:
            sede_medio_map[sid]['medios'][mid] = {
                'medio_id': mid,
                'medio_nombre': medio_nombre,
                'ingresos': Decimal('0.00'),
                'gastos': Decimal('0.00'),
                'saldo': Decimal('0.00'),
            }

        sede_medio_map[sid]['medios'][mid]['gastos'] = r.get('total_gastos') or Decimal('0.00')

    # Lista final ordenada + totales por sede
    resumen_sede_medio = []
    for _, sede_obj in sede_medio_map.items():
        medios_list = []
        total_ing = Decimal('0.00')
        total_gas = Decimal('0.00')

        for _, m in sede_obj['medios'].items():
            ing = m.get('ingresos') or Decimal('0.00')
            gas = m.get('gastos') or Decimal('0.00')
            m['saldo'] = ing - gas
            total_ing += ing
            total_gas += gas
            medios_list.append(m)

        medios_list.sort(key=lambda x: (x.get('medio_nombre') or ''))
        sede_obj['medios'] = medios_list

        sede_obj['total_ingresos'] = total_ing
        sede_obj['total_gastos'] = total_gas
        sede_obj['total_saldo'] = total_ing - total_gas

        # Solo sedes con movimiento por medio
        if medios_list:
            resumen_sede_medio.append(sede_obj)

    resumen_sede_medio.sort(key=lambda x: (x.get('sede_nombre') or ''))

    # =====================================================
    # Series para gráficas (mismo rango)
    # =====================================================
    ingresos_rows = (
        ingresos_periodo_qs
        .annotate(mes=TruncMonth('fecha_pago'))
        .values('mes')
        .annotate(total=Coalesce(Sum('valor_pagado'), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('mes')
    )

    labels = []
    values = []
    for r in ingresos_rows:
        mes = r['mes']
        labels.append(mes.strftime('%Y-%m') if mes else '')
        values.append(float(r['total'] or 0))

    top_sedes_rows = (
        ingresos_periodo_qs
        .values('sede__nombre')
        .annotate(
            total_ingresos=Coalesce(
                Sum('valor_pagado'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by('-total_ingresos')[:5]
    )

    top_sedes_labels = [r['sede__nombre'] or '' for r in top_sedes_rows]
    top_sedes_ingresos = [float(r['total_ingresos'] or 0) for r in top_sedes_rows]

    # Gastos de esas mismas sedes (mismo orden del ranking)
    gastos_map = {
        (r['sede__nombre'] or ''): float(r['total_gastos'] or 0)
        for r in (
            gastos_periodo_qs
            .values('sede__nombre')
            .annotate(
                total_gastos=Coalesce(
                    Sum('valor'),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )
    }

    top_sedes_gastos = [gastos_map.get(nombre, 0.0) for nombre in top_sedes_labels]

    # =====================================================
    # (NUEVO) Gráfico principal: Proyección vs Ejecución
    # Proyección: Cuota.valor por mes de fecha_vencimiento
    # Ejecución: PagoAplicacion.valor_aplicado por mes de fecha_aplicacion
    # Filtra: Ingreso.estado='ACTIVO'
    # Incluye: cuota 0
    # Horizonte: 24 meses (12 atrás + 12 adelante)
    # =====================================================

    inicio_24m = _add_months(hoy.replace(day=1), -11)
    fin_tmp = _add_months(hoy.replace(day=1), 12)
    fin_24m = _month_end(fin_tmp.year, fin_tmp.month)

    # ---------- PROYECCIÓN ----------
    proyeccion_rows = (
        cuotas_qs
        .filter(
            fecha_vencimiento__gte=inicio_24m,
            fecha_vencimiento__lte=fin_24m
        )
        .annotate(mes=TruncMonth('fecha_vencimiento'))
        .values('mes')
        .annotate(
            total=Coalesce(
                Sum('valor'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by('mes')
    )

    # ---------- EJECUCIÓN ----------
    ejecucion_rows = (
        PagoAplicacion.objects
        .select_related('ingreso', 'cuota')
        .filter(
            fecha_aplicacion__gte=inicio_24m,
            fecha_aplicacion__lte=fin_24m,
            ingreso__estado='ACTIVO'
        )
        .annotate(mes=TruncMonth(Cast('fecha_aplicacion', DateField())))
        .values('mes')
        .annotate(
            total=Coalesce(
                Sum('valor_aplicado'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .order_by('mes')
    )

    # ---------- Normalización 24 meses ----------
    proj_map = {r['mes'].strftime('%Y-%m'): (r['total'] or 0) for r in proyeccion_rows if r.get('mes')}
    ejec_map = {r['mes'].strftime('%Y-%m'): (r['total'] or 0) for r in ejecucion_rows if r.get('mes')}

    labels_pe = []
    proyeccion_vals = []
    ejecucion_vals = []

    cursor = inicio_24m
    for _ in range(24):
        ym = cursor.strftime('%Y-%m')
        labels_pe.append(ym)
        proyeccion_vals.append(float(proj_map.get(ym, 0) or 0))
        ejecucion_vals.append(float(ejec_map.get(ym, 0) or 0))
        cursor = _add_months(cursor, 1)
        
    # =====================================================
    # Context
    # =====================================================
    context = {
        'kpis': {
            'total_estudiantes': total_estudiantes,
            'estudiantes_activos': estudiantes_activos,
            'contratos_activos': contratos_activos,
            'cuotas_vencidas': cuotas_vencidas,
            'saldo_vencido': saldo_vencido,
            # mantenemos la key para no romper el template actual
            'ingresos_mes': ingresos_periodo,
        },
        'chart_ingresos_6m': json.dumps({'labels': labels, 'values': values}),
        'chart_top_sedes': json.dumps({
            'labels': top_sedes_labels,
            'ingresos': top_sedes_ingresos,
            'gastos': top_sedes_gastos
        }),
        'chart_proyeccion_vs_ejecucion': json.dumps({
            'labels': labels_pe,
            'proyeccion': proyeccion_vals,
            'ejecucion': ejecucion_vals
            }),
        'hoy': hoy,

        # Filtro UI
        'metodo': metodo,
        'years': years,
        'anio': anio_str,
        'mes_inicio': mes_inicio_str,
        'mes_fin': mes_fin_str,
        'fecha_desde': fecha_desde.strftime('%Y-%m-%d') if fecha_desde else '',
        'fecha_hasta': fecha_hasta.strftime('%Y-%m-%d') if fecha_hasta else '',
        'rango_label': rango_label,

        # =====================================================
        # (NUEVO) Finanzas ejecutivas (periodo)
        # =====================================================
        'ingresos_periodo': ingresos_periodo,
        'gastos_periodo': gastos_periodo,
        'saldo_periodo': saldo_periodo,

        'resumen_por_sede': resumen_por_sede,
        'resumen_por_medio': resumen_por_medio,
        'resumen_sede_medio': resumen_sede_medio,
    }

    return render(request, 'dashboard.html', context)




@login_required
@permiso_requerido("listar_estudiantes")
def listar_estudiantes(request):
    hoy = now().date()
    sede_ids = user_sede_ids(request.user)

    # --------- Parámetros de filtro (mismo estándar de /cxc/) ---------
    q_text = (request.GET.get('q') or '').strip()
    nivel_id = (request.GET.get('nivel') or '').strip()
    horario_id = (request.GET.get('horario') or '').strip()
    sede_id = (request.GET.get('sede') or '').strip() if not sede_ids else ''
    mora = (request.GET.get('mora') or '').strip()  # 'si' / 'no' / ''

    try:
        per_page = int(request.GET.get('per_page', 50))
    except ValueError:
        per_page = 50
    page = request.GET.get('page', 1)

    # ==========================================================
    # REGLA DE NEGOCIO (ERP): KPIs SIEMPRE por CONTRATO ACTIVO
    # - contrato_activo_id = último contrato del estudiante
    # - Cuota #0 NO entra a cartera/KPIs
    # ==========================================================

    contrato_activo_id_sq = Subquery(
        Contrato.objects
        .filter(estudiante_id=OuterRef('pk'))
        .order_by('-id')
        .values('id')[:1]
    )

    contrato_valor_sq = Subquery(
        Contrato.objects
        .filter(id=OuterRef('contrato_activo_id'))
        .values('valor_total')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    numero_cuotas_sq = Subquery(
        Cuota.objects
        .filter(contrato_id=OuterRef('contrato_activo_id'))
        .exclude(numero=0)
        .values('contrato_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    cuotas_pagadas_sq = Subquery(
        Cuota.objects
        .filter(contrato_id=OuterRef('contrato_activo_id'), estado='Pagada')
        .exclude(numero=0)
        .values('contrato_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    cuotas_parciales_sq = Subquery(
        Cuota.objects
        .filter(contrato_id=OuterRef('contrato_activo_id'), estado='Parcial')
        .exclude(numero=0)
        .values('contrato_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    # Cuotas vencidas = cuotas del contrato activo con saldo > 0 y vencimiento < hoy
    cuotas_vencidas_sq = Subquery(
        Cuota.objects
        .filter(
            contrato__estudiante_id=OuterRef('pk'),
            fecha_vencimiento__lt=hoy,
            estado__in=['Parcial', 'Vencida'],
        )
        .exclude(numero=0)
        .values('contrato__estudiante_id')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1],
        output_field=IntegerField()
    )

    total_pagado_sq = Subquery(
        PagoAplicacion.objects
        .filter(cuota__contrato_id=OuterRef('contrato_activo_id'), ingreso__estado='ACTIVO')
        .values('cuota__contrato_id')
        .annotate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
        .values('total')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    # Saldo total = SUM(valor) - SUM(aplicado_activo) del contrato activo
    saldo_total_sq = Subquery(
        Cuota.objects
        .filter(contrato_id=OuterRef('contrato_activo_id'))
        .exclude(numero=0)
        .values('contrato_id')
        .annotate(
            total_valor=Coalesce(
                Sum('valor'),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
            total_pagado=Coalesce(
                Sum(
                    'aplicaciones__valor_aplicado',
                    filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),
        )
        .annotate(total=F('total_valor') - F('total_pagado'))
        .values('total')[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    # Próximo vencimiento = primera cuota con saldo > 0 (contrato activo)
    proximo_vto_sq = Subquery(
        Cuota.objects
        .filter(contrato_id=OuterRef('contrato_activo_id'))
        .exclude(numero=0)
        .annotate(
            pagado=Coalesce(
                Sum(
                    'aplicaciones__valor_aplicado',
                    filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                ),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
        .annotate(saldo=F('valor') - F('pagado'))
        .filter(saldo__gt=0)
        .order_by('fecha_vencimiento')
        .values('fecha_vencimiento')[:1]
    )

    # --------- Base queryset ---------
    qs = (
        Estudiante.objects
        .select_related('nivel', 'sede', 'acudiente', 'horario')
        .annotate(
            contrato_activo_id=contrato_activo_id_sq,
        )
        .annotate(
            contrato_valor=Coalesce(contrato_valor_sq, Value(Decimal('0.00'))),
            numero_cuotas=Coalesce(numero_cuotas_sq, Value(0)),
            cuotas_pagadas=Coalesce(cuotas_pagadas_sq, Value(0)),
            cuotas_parciales=Coalesce(cuotas_parciales_sq, Value(0)),
            cuotas_vencidas=Coalesce(cuotas_vencidas_sq, Value(0)),
            total_pagado=Coalesce(total_pagado_sq, Value(Decimal('0.00'))),
            saldo_total=Coalesce(saldo_total_sq, Value(Decimal('0.00'))),
            proximo_vto=proximo_vto_sq,
        )
        .annotate(
            en_mora=Case(
                When(
                    Q(contrato_activo_id__isnull=False) & Q(saldo_total__gt=0) & Q(proximo_vto__lt=hoy),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        .annotate(
            estado_cartera=Case(
                When(en_mora=True, then=Value('En mora')),
                default=Value('Al día'),
            )
        )
        .order_by('-id')
    )

    # --------- Seguridad por sede ---------
    if sede_ids:
        qs = qs.filter(sede_id__in=sede_ids)

    # --------- Filtro texto libre (estudiante/acudiente/documento) ---------
    if q_text:
        filtros = (
            Q(nombre_completo__icontains=q_text) |
            Q(documento__icontains=q_text) |
            Q(acudiente__nombre_completo__icontains=q_text) |
            Q(acudiente__documento__icontains=q_text)
        )

        # Si es numérico, permitir búsqueda directa por ID del estudiante
        if q_text.isdigit():
            qs = qs.filter(Q(id=int(q_text)) | filtros)
        else:
            qs = qs.filter(filtros)

    # --------- Nivel / Horario ---------
    if nivel_id:
        qs = qs.filter(nivel_id=nivel_id)
    if horario_id:
        qs = qs.filter(horario_id=horario_id)

    # --------- Mora (estado cartera) ---------
    if mora == 'si':
        qs = qs.filter(en_mora=True)
    elif mora == 'no':
        qs = qs.filter(en_mora=False)

    # --------- Sede desde GET (solo si NO hay restricción previa) ---------
    if sede_id:
        qs = qs.filter(sede_id=sede_id)

    # --------- Catálogos ---------
    niveles = Nivel.objects.all().order_by('nombre')
    horarios = Horario.objects.all().order_by('descripcion')
    sedes = [] if sede_ids else list(Sede.objects.all().order_by('nombre'))

    # --------- Paginación ---------
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    context = {
        'estudiantes': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,

        # filtros activos
        'q': q_text,
        'nivel_id': nivel_id,
        'horario_id': horario_id,
        'mora': mora,
        'sede_id': sede_id,
        'per_page': per_page,

        # catálogos
        'niveles': niveles,
        'horarios': horarios,
        'sedes': sedes,
    }

    return render(request, 'listar_estudiantes.html', context)


@login_required
@permiso_requerido("ver_detalle_estudiante")
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
        'cuota_inicial': Decimal('0.00'),
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
                    Sum(
                        'aplicaciones__valor_aplicado',
                        filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
            )
            .order_by('numero')
        )

        # -----------------------------
        # KPIs en Python (evita Sum sobre anotaciones con aggregates)
        # -----------------------------
        cuotas_list = list(cuotas)
        saldo_pendiente = Decimal('0.00')
        vencidas_count = 0
        vencidas_valor = Decimal('0.00')

        for c in cuotas_list:
            pagado_c = getattr(c, 'pagado', Decimal('0.00')) or Decimal('0.00')
            valor_c = c.valor or Decimal('0.00')
            saldo_c = valor_c - pagado_c
            # guardamos saldo/es_vencida_roja para el template
            c.saldo = saldo_c
            c.es_vencida_roja = bool(c.fecha_vencimiento and c.fecha_vencimiento < hoy and saldo_c > 0)

            saldo_pendiente += saldo_c
            if c.es_vencida_roja:
                vencidas_count += 1
                vencidas_valor += saldo_c

        cuotas = cuotas_list

        kpis['saldo_pendiente'] = saldo_pendiente
        kpis['vencidas_count'] = int(vencidas_count)
        kpis['vencidas_valor'] = vencidas_valor

        # Alinear con el template: {{ estudiante.cuotas_vencidas|default:0 }}
        # (solo contrato activo, según regla de negocio)
        estudiante.cuotas_vencidas = kpis['vencidas_count']

        kpis['proximo_vencimiento'] = None
        for c in cuotas:
            if c.saldo > 0:
                kpis['proximo_vencimiento'] = c.fecha_vencimiento
                break

        total_pagado = (
            PagoAplicacion.objects
            .filter(cuota__contrato=contrato_activo, ingreso__estado='ACTIVO')
            .aggregate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
        )['total']

        # ✅ ESTA LÍNEA ES LA QUE TE FALTA
        kpis['total_pagado'] = total_pagado or Decimal('0.00')

        # Cuota inicial (Cuota #0). En el flujo PRO, esta cuota se crea cuando se registra cuota inicial.
        cuota_inicial_val = (
            Cuota.objects
            .filter(contrato=contrato_activo, numero=0)
            .aggregate(total=Coalesce(Sum('valor'), Value(Decimal('0.00'))))
        )['total']
        kpis['cuota_inicial'] = cuota_inicial_val or Decimal('0.00')

        ultimo_ap = (
            PagoAplicacion.objects
            .filter(cuota__contrato=contrato_activo, ingreso__estado='ACTIVO')
            .select_related('ingreso')
            .order_by('-ingreso__fecha_pago', '-ingreso_id')
            .values('ingreso__fecha_pago', 'ingreso__valor_pagado', 'forma_pago')[:1]
        )

        if ultimo_ap:
            up = ultimo_ap[0]
            kpis['ultimo_pago_fecha'] = up['ingreso__fecha_pago']
            kpis['ultimo_pago_valor'] = up['ingreso__valor_pagado']
            kpis['ultimo_pago_medio'] = (up.get('forma_pago') or '').strip()

    return render(request, 'detalle_estudiante.html', {
        'estudiante': estudiante,
        'contrato': contrato_activo,
        'cuotas': cuotas,
        'hoy': hoy,
        'kpis': kpis,
    })
    
@login_required
@permiso_requerido("ver_cartera")
def listado_cxc(request):
    """
    Listado de CUOTAS (una fila por cuota) con filtros y paginación.
    - Muestra todas las cuotas (vencidas, pendientes, parciales y pagadas).
    - Filtros: q, estado, nivel, horario, fv_desde/fv_hasta, medio, factura, referencia, con_pago, sede.
    - Anota: total pagado por cuota, último pago (fecha/medio/factura/obs/referencia), SALDO y es_vencida_roja.
    """
    hoy = now().date()
    sede_ids = user_sede_ids(request.user)


# --------- Subqueries: último ingreso/aplicación por cuota (PRO) ---------
    apps_ordenadas = (
        PagoAplicacion.objects
        .filter(cuota_id=OuterRef('pk'), ingreso__estado='ACTIVO')
        .select_related('ingreso')
        .order_by('-ingreso__fecha_pago', '-ingreso_id')
    )

    ultimo_pago_fecha      = Subquery(apps_ordenadas.values('ingreso__fecha_pago')[:1])
    ultimo_pago_medio      = Subquery(apps_ordenadas.values('forma_pago')[:1])  # ✅ aquí, NO observacion
    ultimo_pago_obs        = Subquery(apps_ordenadas.values('ingreso__observacion')[:1])
    ultimo_pago_factura    = Subquery(apps_ordenadas.values('ingreso__numero_factura')[:1])
    ultimo_pago_referencia = Subquery(apps_ordenadas.values('ingreso__referencia')[:1])

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
                Sum(
                    'aplicaciones__valor_aplicado',
                    filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                ),
                Value(Decimal('0.00'), output_field=DecimalField(max_digits=12, decimal_places=2))
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

    # Texto libre (incluye documento, nombres, contrato, RC, factura, referencia)
    if q_text:
        filtros = (
            # Estudiante
            Q(contrato__estudiante__nombre_completo__icontains=q_text) |
            Q(contrato__estudiante__documento__icontains=q_text) |

            # Acudiente
            Q(contrato__estudiante__acudiente__nombre_completo__icontains=q_text) |
            Q(contrato__estudiante__acudiente__documento__icontains=q_text) |

            # Factura / Referencia / RC (cabecera Ingreso)
            Q(aplicaciones__ingreso__numero_factura__icontains=q_text) |
            Q(aplicaciones__ingreso__referencia__icontains=q_text) |
            Q(aplicaciones__ingreso__numero_comprobante__icontains=q_text)
        )

        # Si es numérico, permitir también búsqueda directa por ID de contrato
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

    # Medio (PRO): viene de PagoAplicacion.forma_pago y/o Ingreso.medio_pago.nombre
    if medio:
        qs = qs.annotate(tiene_medio=Exists(
            PagoAplicacion.objects.filter(
                cuota_id=OuterRef('pk'),
                ingreso__estado='ACTIVO'
            ).filter(
                Q(forma_pago__icontains=medio) |
                Q(ingreso__medio_pago__nombre__icontains=medio)
            )
        )).filter(tiene_medio=True)

    # Factura
    if factura:
        qs = qs.annotate(tiene_factura=Exists(
            PagoAplicacion.objects.filter(
                cuota_id=OuterRef('pk'),
                ingreso__numero_factura__icontains=factura
            )
        )).filter(tiene_factura=True)

    # Referencia
    if referencia:
        qs = qs.annotate(tiene_referencia=Exists(
            PagoAplicacion.objects.filter(
                cuota_id=OuterRef('pk'),
                ingreso__referencia__icontains=referencia
            )
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
@permiso_requerido("registrar_pago")
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
                    Sum(
                        'aplicaciones__valor_aplicado',
                        filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                    ),
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
    # Helper: saldo REAL (vía PagoAplicacion) para validaciones fuera del atomic
    # =====================================================
    def saldo_real_fuera_atomic(cuota_obj):
        pagado_real = (
            PagoAplicacion.objects
            .filter(cuota_id=cuota_obj.id, ingreso__estado='ACTIVO')
            .aggregate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
        )['total'] or Decimal('0.00')
        return (cuota_obj.valor or Decimal('0.00')) - pagado_real

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

        # Historial: el JS (cxc.js) espera `pagos` como array.
        # En el flujo PRO, cada Ingreso (RC) es un "pago".
        ingreso_ids = list(
            PagoAplicacion.objects
            .filter(cuota_id=cuota.id, ingreso__estado='ACTIVO')  # ✅ SOLO activos
            .values_list('ingreso_id', flat=True)
            .distinct()
        )

        pagos = []
        rcs = []  # detalle extendido (opcional) para futuras vistas
        if ingreso_ids:
            ingresos = (
                Ingreso.objects
                .filter(id__in=ingreso_ids)
                .select_related('medio_pago')
                .order_by('-fecha_pago', '-id')
            )

            # Todas las aplicaciones de esos RC (para mostrar la cascada por cuotas)
            apps_all = (
                PagoAplicacion.objects
                .filter(ingreso_id__in=ingreso_ids, ingreso__estado='ACTIVO')  # ✅ SOLO activos
                .select_related('cuota')
                .order_by('ingreso_id', 'cuota__numero')
                .values('ingreso_id', 'cuota_id', 'cuota__numero', 'valor_aplicado')
            )

            apps_por_ingreso = {}
            for row in apps_all:
                apps_por_ingreso.setdefault(row['ingreso_id'], []).append({
                    'cuota_id': row['cuota_id'],
                    'cuota_numero': row['cuota__numero'],
                    'valor_aplicado': str(row['valor_aplicado']),
                })

            for ing in ingresos:
                # ✅ RC se envía en su propio campo (no mezclar con observación)
                rc_txt = (ing.numero_comprobante or '').strip()
                obs_txt = (ing.observacion or '').strip()

                # ✅ Formato que espera el JS actual:
                pagos.append({
                    'id': ing.id,  # el JS lo usa para eliminar (pago_id)
                    'fecha_pago': ing.fecha_pago.strftime('%Y-%m-%d') if ing.fecha_pago else '',
                    'valor_pagado': str(ing.valor_pagado),
                    'medio_pago': (getattr(ing.medio_pago, 'nombre', None) or '').strip(),
                    'numero_factura': ing.numero_factura or '',
                    'referencia': ing.referencia or '',
                    'observacion': obs_txt or '',
                    'numero_comprobante': rc_txt,
                })

                # Detalle extendido (no requerido por el JS, pero útil para auditoría)
                rcs.append({
                    'ingreso_id': ing.id,
                    'numero_comprobante': ing.numero_comprobante or '',
                    'fecha_pago': ing.fecha_pago.strftime('%Y-%m-%d') if ing.fecha_pago else '',
                    'valor_rc': str(ing.valor_pagado),
                    'estado': getattr(ing, 'estado', 'ACTIVO'),
                    'medio_pago': (getattr(ing.medio_pago, 'nombre', None) or '').strip(),
                    'numero_factura': ing.numero_factura or '',
                    'referencia': ing.referencia or '',
                    'observacion': (ing.observacion or '').strip(),
                    'aplicaciones': apps_por_ingreso.get(ing.id, []),
                })

        previas_qs = previas_pendientes_for_get(cuota)
        previas = serializar_previas(previas_qs)

        # Totales para el modal (para mostrar aviso + sumatoria y habilitar botón "Distribuir")
        total_previas = (
            previas_qs.aggregate(total=Coalesce(Sum('saldo'), Value(Decimal('0.00'))))
        )['total'] or Decimal('0.00')

        saldo_actual = saldo_real_fuera_atomic(cuota)
        capacidad_total = total_previas + saldo_actual

        # Flags/aliases para compatibilidad con el JS anterior del modal
        tiene_previas = len(previas) > 0
        saldo_maximo = capacidad_total  # si hay previas, el máximo incluye previas + actual

        return JsonResponse({
            'ok': True,

            # NUEVO (estructura actual)
            'previas': previas,
            'previas_count': len(previas),
            'total_previas': str(total_previas),
            'saldo_actual': str(saldo_actual),
            'capacidad_total': str(capacidad_total),
            'pagos': pagos,
            'rcs': rcs,

            # ALIASES (compatibilidad)
            # - Algunos JS antiguos esperan estos nombres para pintar el listado y el saldo máximo.
            'previas_pendientes': previas,
            'total_previas_pendientes': str(total_previas),
            'saldo_maximo': str(saldo_maximo),
            'tiene_previas_pendientes': tiene_previas,
            'mensaje_previas_pendientes': (
                'Existen cuotas anteriores con saldo pendiente.' if tiene_previas else ''
            ),
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
    medio_pago_id = (request.POST.get('medio_pago_id') or request.POST.get('medio_pago') or '').strip()

    if not medio_pago_id:
        return JsonResponse({'ok': False, 'error': 'Debe seleccionar un medio de pago.'}, status=400)

    medio_pago = MedioPago.objects.filter(id=medio_pago_id, activo=True).first()
    if not medio_pago:
        return JsonResponse({'ok': False, 'error': 'Medio de pago no válido o inactivo.'}, status=400)

    # Bloqueo lógico: no permitir "Banco" por UI ni por POST manipulado
    if (medio_pago.nombre or '').strip().casefold() == 'banco':
        return JsonResponse(
            {'ok': False, 'error': 'No se permite registrar pagos con el medio "Banco".'},
            status=400
        )
        
    if not cuota_id:
        return JsonResponse({'ok': False, 'error': 'Falta cuota_id.'}, status=400)

    cuota, resp_error = obtener_cuota_segura(cuota_id)
    if resp_error:
        return resp_error

    # Saldo REAL para la cuota (NO usar cache legacy `valor_pagado` para reglas de negocio)
    saldo_actual_previo = saldo_real_fuera_atomic(cuota)

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

    # =====================================================
    # Validación previa (FUERA del atomic) para evitar returns dentro de la transacción
    # =====================================================
    if modo != 'auto':
        # Validación REAL (vía PagoAplicacion), no por cache legacy
        previas_exist = (
            Cuota.objects
            .filter(contrato_id=cuota.contrato_id, numero__lt=cuota.numero)
            .annotate(
                pagado=Coalesce(
                    Sum(
                        'aplicaciones__valor_aplicado',
                        filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
                saldo=F('valor') - F('pagado')
            )
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

            # Pre-cargar lo ya aplicado por cuota (fuente de verdad)
            cuota_ids_locked = [c.id for c in cuotas_locked]
            pagado_map = {
                row['cuota_id']: (row['total'] or Decimal('0.00'))
                for row in (
                    PagoAplicacion.objects
                    .filter(cuota_id__in=cuota_ids_locked, ingreso__estado='ACTIVO')
                    .values('cuota_id')
                    .annotate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
                )
            }

            def pagado_de(c):
                return pagado_map.get(c.id, Decimal('0.00'))

            def saldo_de(c):
                return (c.valor or Decimal('0.00')) - pagado_de(c)

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
            # PRO: Ingreso (cabecera RC) + PagoAplicacion (detalle)
            # - No usamos la tabla legacy `gestion_clientes_pago`.
            # - Un solo Ingreso por transacción (comprobante RC).
            # - PagoAplicacion distribuye el monto sobre una o varias cuotas.
            # =====================================================


            # Observación: solo lo que el usuario escribió (NO mezclar medio de pago aquí)
            obs_full = (observacion or '').strip() or None

            ingreso_obj = Ingreso.objects.create(
                sede=cuota.contrato.estudiante.sede,
                concepto_ingreso=ConceptoIngreso.objects.get(pk=1),
                valor_pagado=valor,
                fecha_pago=fecha_pago,
                referencia=referencia or None,
                observacion=obs_full,
                tipo_registro='pago_cuota',
                usuario_registro=request.user,
                contrato=cuota.contrato,
                cuota=cuota,  # ✅ cuota “principal” (la del modal)
                numero_factura=numero_factura,
                numero_comprobante=generar_rc(request, cuota.contrato.estudiante.sede),
                medio_pago=medio_pago,
                estado='ACTIVO'
            )

            # =====================================================
            # Aplicación de pago (crea PagoAplicacion + actualiza cache en Cuota)
            # =====================================================
            def aplicar_a_cuota(c, monto):
                aplicar = min(monto, saldo_de(c))
                if aplicar <= 0:
                    return Decimal('0.00')

                PagoAplicacion.objects.create(
                    ingreso=ingreso_obj,
                    cuota=c,
                    usuario_id=request.user.id,
                    fecha_aplicacion=now(),  # datetime
                    valor_aplicado=aplicar,
                    forma_pago=medio_pago.nombre,
                    numero_factura=numero_factura,
                    referencia=referencia or None,
                    observacion=observacion or None
                )

                # Actualizamos cache legacy para compatibilidad visual (no es fuente de verdad)
                nuevo_pagado = pagado_de(c) + aplicar
                pagado_map[c.id] = nuevo_pagado

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

            return JsonResponse({'ok': True, 'ingreso_id': ingreso_obj.id, 'distribucion': distribucion})

    except _AbortarPago as ex:
        return JsonResponse(ex.payload, status=ex.status)

    except ConceptoIngreso.DoesNotExist:
        return JsonResponse({
            'ok': False,
            'error': 'No existe ConceptoIngreso con pk=1 (configuración contable incompleta).'
        }, status=500)

@login_required
@permiso_requerido("anular_pago")
@require_POST
def eliminar_pago(request):
    """
    PRO: Elimina un comprobante RC (Ingreso) por su ID y revierte sus aplicaciones.

    Compatibilidad:
    - El frontend puede seguir enviando `pago_id`, pero aquí se interpreta como `ingreso_id`.

    POST: pago_id (ingreso_id)
    """
    ingreso_id = (request.POST.get('pago_id') or '').strip()
    motivo = (request.POST.get('motivo') or '').strip() or None

    if not ingreso_id:
        return JsonResponse({'ok': False, 'error': 'Falta pago_id.'}, status=400)

    ingreso = get_object_or_404(
        Ingreso.objects.select_related('contrato__estudiante__sede', 'contrato'),
        pk=ingreso_id
    )

    sede_ids = user_sede_ids(request.user)

    if ingreso.contrato_id is None:
        return JsonResponse({'ok': False, 'error': 'Este ingreso no está asociado a un contrato.'}, status=400)

    sede_ingreso_id = getattr(ingreso.contrato.estudiante, 'sede_id', None)
    if sede_ids and sede_ingreso_id not in sede_ids:
        return JsonResponse({'ok': False, 'error': 'No tiene permisos sobre esta sede.'}, status=403)

    # Si ya está anulado, no repetir la operación
    if getattr(ingreso, 'estado', 'ACTIVO') == 'ANULADO':
        return JsonResponse({'ok': True, 'ya_estaba_anulado': True})

    with transaction.atomic():
        # Cuotas afectadas por este RC
        cuota_ids = list(
            PagoAplicacion.objects
            .filter(ingreso_id=ingreso.id)
            .values_list('cuota_id', flat=True)
            .distinct()
        )

        cuotas = []
        if cuota_ids:
            cuotas = list(Cuota.objects.select_for_update().filter(id__in=cuota_ids))

        # 1) Anular cabecera RC (mantener trazabilidad)
        ingreso.estado = 'ANULADO'
        ingreso.fecha_anulacion = now()
        ingreso.motivo_anulacion = motivo
        ingreso.usuario_anulacion_id = request.user.id
        ingreso.save(update_fields=['estado', 'fecha_anulacion', 'motivo_anulacion', 'usuario_anulacion_id'])

        # 2) Recalcular cache por cuota EXCLUYENDO ingresos anulados
        hoy = now().date()
        for c in cuotas:
            nuevo_pagado = (
                PagoAplicacion.objects
                .filter(cuota_id=c.id, ingreso__estado='ACTIVO')
                .aggregate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
            )['total'] or Decimal('0.00')

            c.valor_pagado = nuevo_pagado

            if nuevo_pagado >= (c.valor or Decimal('0.00')):
                c.estado = 'Pagada'
            else:
                saldo = (c.valor or Decimal('0.00')) - nuevo_pagado
                if saldo <= 0:
                    c.estado = 'Pagada'
                elif c.fecha_vencimiento and c.fecha_vencimiento < hoy:
                    c.estado = 'Vencida'
                elif nuevo_pagado > 0:
                    c.estado = 'Parcial'
                else:
                    c.estado = 'Pendiente'

            c.save(update_fields=['valor_pagado', 'estado'])

    return JsonResponse({'ok': True})

@login_required
@permiso_requerido("crear_contrato")
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

    # =========================
    # Render helper: preserva estado de UI (switch cuota inicial + campos de pago)
    # - Evita que el formulario “se reinicie” cuando hay errores backend
    # =========================
    def _render_nuevo_contrato_error(acudiente_form, estudiante_form, contrato_form, extra_context=None):
        """Renderiza el template preservando estado del switch de cuota inicial y valores posteados."""
        extra_context = extra_context or {}

        registrar_ci_raw = (request.POST.get('registrar_cuota_inicial') or '').strip().lower()
        registrar_ci_on = registrar_ci_raw in ('1', 'on', 'true', 'yes')

        cuota_inicial_raw = request.POST.get('cuota_inicial')
        cuota_inicial_val = (str(cuota_inicial_raw).strip() if cuota_inicial_raw is not None else '')

        pago_ci = {
            'medio_pago_id': (request.POST.get('pago_cuota_inicial_medio_pago_id') or '').strip(),
            'referencia': (request.POST.get('pago_cuota_inicial_referencia') or '').strip(),
            'numero_factura': (request.POST.get('pago_cuota_inicial_numero_factura') or '').strip(),
            'observacion': (request.POST.get('pago_cuota_inicial_observacion') or '').strip(),
        }

        ctx = {
            'form_acudiente': acudiente_form,
            'form_estudiante': estudiante_form,
            'form_contrato': contrato_form,

            # UI state (no rompe nada aunque el template aún no lo use)
            'registrar_ci_on': registrar_ci_on,
            'cuota_inicial_value': cuota_inicial_val,
            'pago_cuota_inicial': pago_ci,
        }
        ctx.update(extra_context)
        return render(request, 'nuevo_contrato.html', ctx)

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

        estudiante_form = EstudianteForm(request.POST, prefix='estudiante', user=request.user)

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
            acudiente_form = AcudienteForm(instance=acudiente_existente, prefix='acudiente')
        else:
            acudiente_form = AcudienteForm(request.POST, prefix='acudiente')

        # =========================
        # VALIDACIONES
        # =========================
        if not acudiente_existente and not acudiente_form.is_valid():
            messages.error(request, "Revisa los datos del acudiente. Hay campos obligatorios o inválidos.")
            return _render_nuevo_contrato_error(acudiente_form, estudiante_form, contrato_form)

        if not estudiante_form.is_valid():
            messages.error(request, "Revisa los datos del estudiante. Hay campos obligatorios o inválidos.")
            return _render_nuevo_contrato_error(acudiente_form, estudiante_form, contrato_form)

        if not contrato_form.is_valid():
            messages.error(request, "Revisa los datos del contrato. Hay campos obligatorios o inválidos.")
            return _render_nuevo_contrato_error(acudiente_form, estudiante_form, contrato_form)

        # =========================
        # VALIDACIONES (BACKEND) CUOTA INICIAL + PAGO CI
        # - No confiar solo en JS/required
        # - Si el switch está ON => cuota inicial obligatoria y > 0
        # - Si cuota inicial > 0 => medio de pago y referencia obligatorios y válidos
        # =========================
        registrar_ci_raw = (request.POST.get('registrar_cuota_inicial') or '').strip().lower()
        registrar_ci_on = registrar_ci_raw in ('1', 'on', 'true', 'yes')

        cuota_inicial_raw = request.POST.get('cuota_inicial')
        cuota_inicial_raw_str = (str(cuota_inicial_raw).strip() if cuota_inicial_raw is not None else '')

        if registrar_ci_on:
            # 1) Cuota inicial obligatoria y > 0 (aunque el JS la convierta a "0")
            ci_val = cop_to_decimal(cuota_inicial_raw_str, default=Decimal('0'))
            if ci_val <= 0:
                messages.error(
                    request,
                    'No se pudo guardar: la cuota inicial es obligatoria y debe ser mayor a 0 cuando activas “Registrar Cuota inicial”.'
                )
                return _render_nuevo_contrato_error(
                    acudiente_form,
                    estudiante_form,
                    contrato_form,
                    extra_context={
                        'error_cuota_inicial': 'La cuota inicial es obligatoria y debe ser mayor a 0 cuando activas “Registrar Cuota inicial”.'
                    }
                )

            # 2) Si cuota inicial > 0 => medio de pago y referencia obligatorios
            medio_ci_id = (request.POST.get('pago_cuota_inicial_medio_pago_id') or '').strip()
            ref_ci = (request.POST.get('pago_cuota_inicial_referencia') or '').strip()

            errores_pago_ci = {}

            if not medio_ci_id:
                errores_pago_ci['error_pago_cuota_inicial_medio'] = 'Debes seleccionar un medio de pago.'
            else:
                # Validar que el medio exista y esté activo
                if not MedioPago.objects.filter(id=medio_ci_id, activo=True).exists():
                    errores_pago_ci['error_pago_cuota_inicial_medio'] = 'El medio de pago seleccionado no es válido o está inactivo.'

            if not ref_ci:
                errores_pago_ci['error_pago_cuota_inicial_referencia'] = 'Debes ingresar una referencia.'

            if errores_pago_ci:
                messages.error(request, 'No se pudo guardar: completa los datos de pago de la cuota inicial.')
                return _render_nuevo_contrato_error(
                    acudiente_form,
                    estudiante_form,
                    contrato_form,
                    extra_context=errores_pago_ci
                )

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

                # Cálculo cuotas basado en VALOR A FINANCIAR
                total = Decimal(contrato.valor_total)
                n = int(contrato.numero_cuotas)

                cuota_inicial = cop_to_decimal(request.POST.get('cuota_inicial'), default=Decimal('0'))
                if cuota_inicial < 0:
                    cuota_inicial = Decimal('0')

                financiar = total - cuota_inicial
                if financiar < 0:
                    financiar = Decimal('0')

                valor_base = (financiar / Decimal(n)).to_integral_value(rounding=ROUND_HALF_UP)
                residuo = financiar - (valor_base * n)

                contrato.valor_cuota_pactada = valor_base
                contrato.estado = 'Activo'
                contrato.fecha_inicio = fecha_inicio
                contrato.fecha_fin = add_months(fecha_inicio, n - 1)
                contrato.save()

                # CUOTA 0: cuota inicial pagada + RC + aplicación
                if registrar_ci_on and cuota_inicial > 0:
                    medio_ci_id = (request.POST.get('pago_cuota_inicial_medio_pago_id') or '').strip()
                    ref_ci = (request.POST.get('pago_cuota_inicial_referencia') or '').strip()
                    fac_ci = (request.POST.get('pago_cuota_inicial_numero_factura') or '').strip() or None
                    obs_ci = (request.POST.get('pago_cuota_inicial_observacion') or '').strip() or None

                    medio_ci = MedioPago.objects.filter(id=medio_ci_id, activo=True).first()
                    if not medio_ci:
                        raise ValueError('El medio de pago de la cuota inicial no es válido o está inactivo.')

                    cuota0 = Cuota.objects.create(
                        contrato=contrato,
                        numero=0,
                        fecha_vencimiento=now().date(),
                        valor=cuota_inicial,
                        valor_pagado=cuota_inicial,
                        estado='Pagada'
                    )

                    ingreso_ci = Ingreso.objects.create(
                        sede=estudiante.sede,
                        concepto_ingreso=ConceptoIngreso.objects.get(pk=7),
                        valor_pagado=cuota_inicial,
                        fecha_pago=now().date(),
                        referencia=ref_ci or None,
                        observacion=obs_ci,
                        tipo_registro='CUOTA_INICIAL',
                        usuario_registro=request.user,
                        contrato=contrato,
                        cuota=cuota0,
                        numero_factura=fac_ci,
                        numero_comprobante=generar_rc(request, estudiante.sede),
                        medio_pago=medio_ci,
                        estado='ACTIVO'
                    )

                    PagoAplicacion.objects.create(
                        ingreso=ingreso_ci,
                        cuota=cuota0,
                        usuario_id=request.user.id,
                        fecha_aplicacion=now(),
                        valor_aplicado=cuota_inicial,
                        forma_pago=medio_ci.nombre,
                        numero_factura=fac_ci,
                        referencia=ref_ci or None,
                        observacion=obs_ci
                    )

                # CUOTAS (1..n)
                for i in range(1, n + 1):
                    vence = add_months(fecha_inicio, i - 1)
                    valor_i = valor_base
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

        return _render_nuevo_contrato_error(acudiente_form, estudiante_form, contrato_form)

    # =========================
    # GET
    # =========================
    return render(request, 'nuevo_contrato.html', {
        'form_acudiente': AcudienteForm(prefix='acudiente'),
        'form_estudiante': EstudianteForm(prefix='estudiante', user=request.user),
        'form_contrato': ContratoForm(),
    })
    
@require_GET
@login_required
def buscar_acudiente_por_documento(request):
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
@permiso_requerido("registrar_ingreso")
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
            ingreso.numero_comprobante = generar_rc(request, ingreso.sede)
            ingreso.estado = 'ACTIVO'
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
            .filter(tipo_registro='otro_ingreso', estado='ACTIVO')
            .select_related('sede', 'usuario_registro')
            .order_by('-id')
        )
    else:
        ingresos = (
            Ingreso.objects
            .filter(usuario_registro=request.user, tipo_registro='otro_ingreso', estado='ACTIVO')
            .select_related('sede', 'usuario_registro')
            .order_by('-id')
        )

    return render(request, 'nuevo_ingreso.html', {
        'form': form,
        'ingresos': ingresos,
    })


@login_required
@permiso_requerido("ver_reporte_ingresos")
def reporte_ingresos_manuales(request):
    """Reporte para conciliación de ingresos MANUALES.

    Alcance:
    - Solo ingresos creados desde el formulario (tipo_registro='otro_ingreso').
    - Muestra todos los campos relevantes para auditoría/conciliación (RC, factura, referencia, observación,
    - medio de pago, sede, usuario, concepto, estado y datos de anulación).
    - Respeta seguridad por sede con `user_sede_ids`.

    Filtros (GET):
    - q: búsqueda libre (RC, factura, referencia, observación, usuario)
    - estado: ACTIVO / ANULADO / ''
    - sede: (solo si el usuario NO está restringido por sedes)
    - medio_pago_id
    - concepto_id
    - fecha_desde / fecha_hasta (YYYY-MM-DD)
    - per_page
    """
    sede_ids = user_sede_ids(request.user)

    q_text = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()
    fecha_desde = (request.GET.get('fecha_desde') or '').strip()
    fecha_hasta = (request.GET.get('fecha_hasta') or '').strip()
    medio_pago_id = (request.GET.get('medio_pago_id') or '').strip()
    concepto_id = (request.GET.get('concepto_id') or '').strip()

    # Si el usuario NO está restringido por sede_ids, se permite filtrar por sede desde GET
    sede_id = (request.GET.get('sede') or '').strip() if not sede_ids else ''

    try:
        per_page = int(request.GET.get('per_page', 50))
    except ValueError:
        per_page = 50
    page = request.GET.get('page', 1)

    qs = (
        Ingreso.objects
        .filter(tipo_registro='otro_ingreso')
        .select_related(
            'sede',
            'usuario_registro',
            'usuario_anulacion',
            'medio_pago',
            'concepto_ingreso',
            'contrato',
            'cuota',
        )
        .order_by('-fecha_pago', '-id')
    )

    # Seguridad por sede
    if sede_ids:
        qs = qs.filter(sede_id__in=sede_ids)

    # Filtro por sede (solo si el user NO está restringido)
    if sede_id:
        qs = qs.filter(sede_id=sede_id)

    # Estado
    if estado:
        qs = qs.filter(estado=estado)

    # Rango de fechas
    if fecha_desde:
        qs = qs.filter(fecha_pago__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_pago__lte=fecha_hasta)

    # Medio pago / concepto
    if medio_pago_id:
        qs = qs.filter(medio_pago_id=medio_pago_id)
    if concepto_id:
        qs = qs.filter(concepto_ingreso_id=concepto_id)

    # Texto libre: RC, factura, referencia, observación, usuario
    if q_text:
        qs = qs.filter(
            Q(numero_comprobante__icontains=q_text) |
            Q(numero_factura__icontains=q_text) |
            Q(referencia__icontains=q_text) |
            Q(observacion__icontains=q_text) |
            Q(usuario_registro__username__icontains=q_text)
        ).distinct()

    # Catálogos para filtros
    medios = list(MedioPago.objects.filter(activo=True).order_by('nombre'))
    conceptos = list(ConceptoIngreso.objects.all().order_by('nombre'))
    sedes = [] if sede_ids else list(Sede.objects.all().order_by('nombre'))

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    context = {
        'ingresos': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'per_page_options': [25, 50, 100, 200],
        # filtros activos
        'q': q_text,
        'estado': estado,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'medio_pago_id': medio_pago_id,
        'concepto_id': concepto_id,
        'sede_id': sede_id,
        'per_page': per_page,

        # catálogos
        'medios': medios,
        'conceptos': conceptos,
        'sedes': sedes,

        # columnas sugeridas para el template (conciliación)
        'columns': [
            'id', 'fecha_pago', 'numero_comprobante', 'valor_pagado', 'medio_pago',
            'numero_factura', 'referencia', 'observacion', 'concepto_ingreso',
            'sede', 'usuario_registro', 'estado', 'fecha_anulacion', 'motivo_anulacion', 'usuario_anulacion'
        ],
    }

    return render(request, 'reporte_ingresos.html', context)

@require_GET
@login_required
@permiso_requerido("buscar_estudiante")
def buscar_estudiante(request):
    """
    Buscador puntual para Secretaría:
    - No lista al entrar (solo busca si viene ?q=...)
    - Muestra la MISMA info de listar_estudiantes (KPIs/annotations)
    - Máximo 10 resultados
    - Sin paginación
    - Restringido por sedes del usuario
    """
    hoy = now().date()
    sede_ids = user_sede_ids(request.user)

    LIMIT_RESULTADOS = 10

    # Si el usuario no tiene sedes asignadas, no puede operar el buscador
    if not sede_ids:
        return render(request, 'buscar_estudiante.html', {
            'q': '',
            'buscado': False,
            'resultados': [],
            'error': 'Tu usuario no tiene sede asignada. Contacta al administrador.',
        })

    q_text = (request.GET.get('q') or '').strip()
    buscado = bool(q_text)

    resultados = []
    if buscado:
        # --------- Subqueries/KPIs por estudiante (IGUAL QUE listar_estudiantes) ---------
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
            .exclude(numero=0)
            .values('contrato__estudiante_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1],
            output_field=IntegerField()
        )

        cuotas_pagadas_sq = Subquery(
            Cuota.objects
            .filter(contrato__estudiante_id=OuterRef('pk'), estado='Pagada')
            .exclude(numero=0)
            .values('contrato__estudiante_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1],
            output_field=IntegerField()
        )

        cuotas_vencidas_sq = Subquery(
            Cuota.objects
            .filter(
                contrato__estudiante_id=OuterRef('pk'),
                fecha_vencimiento__lt=hoy,
                estado__in=['Parcial', 'Vencida'],
            )
            .exclude(numero=0)
            .values('contrato__estudiante_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1],
            output_field=IntegerField()
        )

        total_pagado_sq = Subquery(
            PagoAplicacion.objects
            .filter(cuota__contrato__estudiante_id=OuterRef('pk'), ingreso__estado='ACTIVO')
            .values('cuota__contrato__estudiante_id')
            .annotate(total=Coalesce(Sum('valor_aplicado'), Value(Decimal('0.00'))))
            .values('total')[:1],
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )

        saldo_total_sq = Subquery(
            Cuota.objects
            .filter(contrato__estudiante_id=OuterRef('pk'))
            .exclude(numero=0)
            .values('contrato__estudiante_id')
            .annotate(
                total_valor=Coalesce(
                    Sum('valor'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
                total_pagado=Coalesce(
                    Sum(
                        'aplicaciones__valor_aplicado',
                        filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
            )
            .annotate(total=F('total_valor') - F('total_pagado'))
            .values('total')[:1],
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )

        cuotas_parciales_sq = Subquery(
            Cuota.objects
            .filter(contrato__estudiante_id=OuterRef('pk'), estado='Parcial')
            .exclude(numero=0)
            .values('contrato__estudiante_id')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1],
            output_field=IntegerField()
        )

        proximo_vto_sq = Subquery(
            Cuota.objects
            .filter(contrato__estudiante_id=OuterRef('pk'))
            .exclude(numero=0)
            .annotate(
                pagado=Coalesce(
                    Sum(
                        'aplicaciones__valor_aplicado',
                        filter=Q(aplicaciones__ingreso__estado='ACTIVO')
                    ),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
            .annotate(saldo=F('valor') - F('pagado'))
            .filter(saldo__gt=0)
            .order_by('fecha_vencimiento')
            .values('fecha_vencimiento')[:1]
        )

        qs = (
            Estudiante.objects
            .select_related('nivel', 'sede', 'acudiente', 'horario')
            .filter(sede_id__in=sede_ids)
            .annotate(
                contrato_valor=Coalesce(contrato_valor_sq, Value(Decimal('0.00'))),
                numero_cuotas=Coalesce(numero_cuotas_sq, Value(0)),
                cuotas_pagadas=Coalesce(cuotas_pagadas_sq, Value(0)),
                cuotas_vencidas=Coalesce(cuotas_vencidas_sq, Value(0)),
                total_pagado=Coalesce(total_pagado_sq, Value(Decimal('0.00'))),
                saldo_total=Coalesce(saldo_total_sq, Value(Decimal('0.00'))),
                cuotas_parciales=Coalesce(cuotas_parciales_sq, Value(0)),
                proximo_vto=proximo_vto_sq,
            )
            .annotate(
                en_mora=Case(
                    When(Q(saldo_total__gt=0) & Q(proximo_vto__lt=hoy), then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField()
                )
            )
            .annotate(
                estado_cartera=Case(
                    When(en_mora=True, then=Value('En mora')),
                    default=Value('Al día'),
                )
            )
            .order_by('-id')
        )

        # Búsqueda: estudiante/acudiente/documento + ID numérico
        filtros = (
            Q(nombre_completo__icontains=q_text) |
            Q(documento__icontains=q_text) |
            Q(acudiente__nombre_completo__icontains=q_text) |
            Q(acudiente__documento__icontains=q_text)
        )
        if q_text.isdigit():
            qs = qs.filter(Q(id=int(q_text)) | filtros)
        else:
            qs = qs.filter(filtros)

        resultados = list(qs[:LIMIT_RESULTADOS])

    return render(request, 'buscar_estudiante.html', {
        'q': q_text,
        'buscado': buscado,
        'resultados': resultados,
        'error': None,
        'hoy': hoy,
        'limit': LIMIT_RESULTADOS,
    })

@login_required
@permiso_requerido("gastos_crear")
def crear_gasto(request):
    """Crea un gasto (CE) con consecutivo por sede/año.

    Reglas:
    - Usuario restringido por sedes: solo puede crear en sus sedes.
    - Usuario global (superuser / CEO / CFO / Dev_icaro): puede crear en cualquier sede.
    """
    from datetime import date
    from django.db import connection
    from django.utils import timezone

    # -----------------------------
    # Helper: usuario global (misma regla aplicada en gastos)
    # -----------------------------
    def es_usuario_global(user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        if (getattr(user, "username", "") or "").strip() == "Dev_icaro":
            return True
        return user.groups.filter(name__in=["CEO", "CFO"]).exists()

    puede_ver_todas = es_usuario_global(request.user)

    sede_ids = user_sede_ids(request.user)

    # Blindaje: si NO es global y no tiene sedes asignadas => no puede crear
    if (not puede_ver_todas) and (not sede_ids):
        return render(request, "403.html", status=403)

    # Sedes disponibles para el formulario
    sedes_qs = (
        Sede.objects.all().order_by("nombre")
        if puede_ver_todas
        else Sede.objects.filter(id__in=sede_ids).order_by("nombre")
    )

    if request.method == "POST":
        form = GastoForm(request.POST, sedes_qs=sedes_qs)

        if not form.is_valid():
            messages.error(request, "Revise los campos marcados. Hay errores de validación.")
            # CLAVE: aquí el usuario debe ver errores (ver nota de template abajo)
            return render(request, "crear_gasto.html", {"form": form})

        sede = form.cleaned_data["sede"]
        year = date.today().year

        # Seguridad adicional: si no es global, validar sede dentro de asignadas
        if (not puede_ver_todas) and sede_ids and (sede.id not in set(sede_ids)):
            return render(request, "403.html", status=403)

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # 1) Bloqueo del consecutivo CE por sede/año
                    cursor.execute(
                        """
                        SELECT consecutivo
                        FROM gestion_finanzas_consecutivo_comprobante
                        WHERE sede_id=%s AND prefijo='CE' AND year=%s
                        FOR UPDATE
                        """,
                        [sede.id, year],
                    )
                    row = cursor.fetchone()
                    if not row:
                        messages.error(
                            request,
                            "No existe consecutivo CE para esta sede/año. Contacte al administrador."
                        )
                        return render(request, "crear_gasto.html", {"form": form})

                    consecutivo_actual = int(row[0] or 0)
                    nuevo = consecutivo_actual + 1
                    numero_ce = f"CE-{sede.id}-{year}-{nuevo:08d}"

                    # 2) Crear gasto
                    g = form.save(commit=False)
                    g.numero_comprobante = numero_ce
                    g.usuario_registro_id = request.user.id
                    g.estado = "ACTIVO"
                    g.creado_en = timezone.now()
                    g.actualizado_en = timezone.now()
                    g.save()

                    # 3) Actualizar consecutivo CE
                    cursor.execute(
                        """
                        UPDATE gestion_finanzas_consecutivo_comprobante
                        SET consecutivo=%s
                        WHERE sede_id=%s AND prefijo='CE' AND year=%s
                        """,
                        [nuevo, sede.id, year],
                    )

            messages.success(request, f"Gasto creado correctamente: {numero_ce}")
            return redirect("listar_gastos")

        except Exception:
            messages.error(
                request,
                "No fue posible guardar el gasto. Verifique consecutivo CE y datos del formulario."
            )
            return render(request, "crear_gasto.html", {"form": form})

    # -----------------------------
    # GET
    # -----------------------------
    initial = {}

    # Precarga: si solo tiene 1 sede (y no es global), dejarla seleccionada
    if (not puede_ver_todas) and sede_ids and len(set(sede_ids)) == 1:
        initial["sede"] = sedes_qs.first()

    initial["fecha_gasto"] = date.today()

    form = GastoForm(initial=initial, sedes_qs=sedes_qs)
    return render(request, "crear_gasto.html", {"form": form})

@login_required
@permiso_requerido("gastos_ver")
def listar_gastos(request):
    """
    Listado de gastos (CE) con filtros y seguridad por sedes.
    - Si el usuario NO es global => restringe por sedes asignadas (user_sede_ids) y por usuario_registro.
    - Si el usuario ES global (CEO/CFO/Admin) => puede ver todo y filtrar por cualquier sede.

    Nota: En este ERP, si un usuario NO es global y NO tiene sedes asignadas,
    NO debe ver información (blindaje).
    """
    from datetime import datetime
    from django.db.models import Q
    from django.core.paginator import Paginator

    hoy = now().date()

    # ---- Seguridad: sedes asignadas ----
    sede_ids_usuario = user_sede_ids(request.user)

    # =====================================================
    # (FIX) Definir usuarios globales sin depender de `tiene_permiso`
    # Global = Superuser OR Groups(CEO/CFO) OR username Dev_icaro
    # =====================================================
    def es_usuario_global(user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        if (user.username or "").strip() == "Dev_icaro":
            return True
        # Por grupos (lo que ya usas en tu ERP)
        return user.groups.filter(name__in=["CEO", "CFO"]).exists()

    puede_ver_todas = es_usuario_global(request.user)

    # Blindaje: si no es global y no tiene sedes asignadas => no puede ver gastos
    if (not puede_ver_todas) and (not sede_ids_usuario):
        return render(request, "403.html", status=403)

    # ---- Parámetros de filtro ----
    q_text = (request.GET.get('q') or '').strip()
    estado = (request.GET.get('estado') or '').strip()  # ACTIVO / ANULADO / ''
    sede_id = (request.GET.get('sede') or '').strip()
    concepto_id = (request.GET.get('concepto') or '').strip()
    medio_id = (request.GET.get('medio') or '').strip()
    fecha_desde = (request.GET.get('fecha_desde') or '').strip()
    fecha_hasta = (request.GET.get('fecha_hasta') or '').strip()

    # ---- Paginación: opciones corporativas + validación ----
    per_page_choices = [25, 50, 100, 200]

    try:
        per_page = int(request.GET.get('per_page', 50))
    except (TypeError, ValueError):
        per_page = 50

    if per_page not in per_page_choices:
        per_page = 50

    page = request.GET.get('page', 1)

    # ---- detectar si hay filtros activos ----
    hay_filtros = any([
        q_text,
        estado,
        sede_id,
        concepto_id,
        medio_id,
        fecha_desde,
        fecha_hasta,
        request.GET.get('per_page'),
    ])

    # ---- Query base ----
    qs = Gasto.objects.select_related(
        'sede', 'concepto_gasto', 'medio_pago', 'usuario_registro'
    ).all()

    # ---- Restricción por sedes (si aplica) ----
    if (not puede_ver_todas) and sede_ids_usuario:
        qs = qs.filter(sede_id__in=sede_ids_usuario)

    # ---- Restricción por usuario (si aplica) ----
    # Si NO es global => solo ve sus propios gastos.
    if not puede_ver_todas:
        qs = qs.filter(usuario_registro_id=request.user.id)

    # Filtro sede (blindado)
    if sede_id:
        try:
            sede_id_int = int(sede_id)
            if (puede_ver_todas) or (sede_id_int in (sede_ids_usuario or [])):
                qs = qs.filter(sede_id=sede_id_int)
        except ValueError:
            pass

    if estado:
        qs = qs.filter(estado=estado)

    if concepto_id:
        try:
            qs = qs.filter(concepto_gasto_id=int(concepto_id))
        except ValueError:
            pass

    if medio_id:
        try:
            qs = qs.filter(medio_pago_id=int(medio_id))
        except ValueError:
            pass

    # Fechas
    if fecha_desde:
        try:
            d = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
            qs = qs.filter(fecha_gasto__gte=d)
        except ValueError:
            pass

    if fecha_hasta:
        try:
            h = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
            qs = qs.filter(fecha_gasto__lte=h)
        except ValueError:
            pass

    # Búsqueda libre
    if q_text:
        qs = qs.filter(
            Q(numero_comprobante__icontains=q_text) |
            Q(referencia_factura__icontains=q_text) |
            Q(referencia__icontains=q_text) |
            Q(observacion__icontains=q_text) |
            Q(motivo_anulacion__icontains=q_text) |
            Q(usuario_registro__username__icontains=q_text)
        )

    # Orden
    qs = qs.order_by('-fecha_gasto', '-id')

    # Paginación
    paginator = Paginator(qs, per_page)
    gastos_page = paginator.get_page(page)

    # ---- Combos para filtros ----
    if (not puede_ver_todas) and sede_ids_usuario:
        sedes_filtro = Sede.objects.filter(id__in=sede_ids_usuario).order_by('nombre')
    else:
        sedes_filtro = Sede.objects.all().order_by('nombre')

    conceptos = ConceptoGasto.objects.filter(activo=1).order_by('categoria', 'nombre')
    medios = MedioPago.objects.all().order_by('nombre')

    context = {
        'hoy': hoy,
        'gastos': gastos_page,
        'sedes': sedes_filtro,
        'conceptos': conceptos,
        'medios': medios,

        # filtros actuales
        'q': q_text,
        'estado': estado,
        'sede_id': sede_id,
        'concepto_id': concepto_id,
        'medio_id': medio_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'per_page': per_page,
        'per_page_choices': per_page_choices,

        'hay_filtros': hay_filtros,

        # flags
        'puede_ver_todas': puede_ver_todas,
        'sede_ids_usuario': sede_ids_usuario,
    }

    return render(request, 'listar_gastos.html', context)

@login_required
@permiso_requerido("gastos_anular")
@require_POST
def anular_gasto(request, gasto_id):
    """
    Anula un gasto (CE) SIN eliminarlo.
    - Cambia estado a ANULADO
    - Registra: fecha_anulacion, motivo_anulacion, usuario_anulacion_id
    - Respeta seguridad por sedes (si el usuario está restringido)
    """
    motivo = (request.POST.get('motivo_anulacion') or '').strip()

    if not motivo:
        messages.error(request, "Debe indicar el motivo de anulación.")
        return redirect('listar_gastos')

    gasto = get_object_or_404(
        Gasto.objects.select_related('sede'),
        pk=gasto_id
    )

    # --- Seguridad (misma regla de listar_gastos) ---
    sede_ids_usuario = user_sede_ids(request.user)

    def es_usuario_global(user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        if (user.username or "").strip() == "Dev_icaro":
            return True
        return user.groups.filter(name__in=["CEO", "CFO"]).exists()

    puede_ver_todas = es_usuario_global(request.user)

    # 1) Si NO es global: validar sede asignada
    if sede_ids_usuario and (not puede_ver_todas) and (gasto.sede_id not in sede_ids_usuario):
        return render(request, "403.html", status=403)

    # 2) Si NO es global: solo puede anular sus propios gastos
    if (not puede_ver_todas) and (gasto.usuario_registro_id != request.user.id):
        return render(request, "403.html", status=403)

    if gasto.estado == "ANULADO":
        messages.warning(request, f"Este gasto ya estaba anulado: {gasto.numero_comprobante}")
        return redirect('listar_gastos')

    with transaction.atomic():
        gasto.estado = "ANULADO"
        gasto.fecha_anulacion = now()
        gasto.motivo_anulacion = motivo
        gasto.usuario_anulacion_id = request.user.id
        gasto.actualizado_en = now()
        gasto.save(update_fields=[
            "estado", "fecha_anulacion", "motivo_anulacion",
            "usuario_anulacion_id", "actualizado_en"
        ])

    messages.success(request, f"Gasto anulado: {gasto.numero_comprobante}")
    return redirect('listar_gastos')