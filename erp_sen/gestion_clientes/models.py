# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
from django.db import models
from decimal import Decimal
from django.contrib.auth.models import User
# from .models import Sede
from django.db.models.signals import post_save
from django.dispatch import receiver


class Horario(models.Model):
    hora = models.TimeField(unique=True)  # Ejemplo: 08:00:00
    descripcion = models.CharField(max_length=50, help_text='Ej: 8:00 am, 2:00 pm')

    class Meta:
        db_table = 'gestion_clientes_horario'
        managed = False

    def __str__(self):
        return self.descripcion


class Sede(models.Model):
    nombre = models.CharField(max_length=100)
    ciudad = models.CharField(max_length=100)
    direccion = models.TextField()

    class Meta:
        db_table = 'gestion_clientes_sede'
        managed = False

    def __str__(self):
        return f"{self.nombre} - {self.ciudad}"


class Acudiente(models.Model):
    TIPOS_DOCUMENTO = [
        ('CC', 'Cédula'),
        ('TI', 'Tarjeta de Identidad'),
        ('CE', 'Cédula de Extranjería'),
        ('PAS', 'Pasaporte'),
    ]

    nombre_completo = models.CharField(max_length=150)
    tipo_documento = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO)
    documento = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = 'gestion_clientes_acudiente'
        managed = False

    def __str__(self):
        return self.nombre_completo


class Nivel(models.Model):
    codigo = models.CharField(max_length=10, unique=True)  # Ej: A1, B2, Kids
    nombre = models.CharField(max_length=50)               # Ej: Básico A1
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'gestion_clientes_nivel'
        managed = False

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Estudiante(models.Model):
    ESTADOS = [
        ('Activo', 'Activo'),
        ('Aplazado', 'Aplazado'),
        ('Retirado', 'Retirado'),
        ('Graduado', 'Graduado'),
    ]

    TIPOS_DOCUMENTO = [
        ('CC', 'Cédula'),
        ('TI', 'Tarjeta de Identidad'),
        ('CE', 'Cédula de Extranjería'),
        ('PAS', 'Pasaporte'),
    ]

    nombre_completo = models.CharField(max_length=150)
    tipo_documento = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO, default='CC')
    documento = models.CharField(max_length=20, unique=True)

    fecha_nacimiento = models.DateField()
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT)
    acudiente = models.ForeignKey(Acudiente, on_delete=models.PROTECT)
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT)

    estado = models.CharField(max_length=10, choices=ESTADOS, default='Activo')
    observacion = models.TextField(blank=True, null=True)
    horario = models.ForeignKey(Horario, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        db_table = 'gestion_clientes_estudiante'
        managed = False

    def __str__(self):
        return f"{self.nombre_completo} ({self.tipo_documento} {self.documento})" if self.documento else self.nombre_completo


class Contrato(models.Model):
    ESTADOS = (
        ('Activo', 'Activo'),
        ('Finalizado', 'Finalizado'),
        ('Anulado', 'Anulado'),
    )

    acudiente = models.ForeignKey('Acudiente', on_delete=models.PROTECT, related_name='contratos')
    estudiante = models.ForeignKey('Estudiante', on_delete=models.PROTECT, related_name='contratos')

    # Fechas: la app las calcula; fecha_fin puede quedar nula mientras se arma el contrato
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)

    # Valores
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    valor_cuota_pactada = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Cuotas
    numero_cuotas = models.PositiveSmallIntegerField()

    # Estado del contrato: SIEMPRE arranca en Activo (forzado también en views.py)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='Activo')

    class Meta:
        db_table = 'gestion_clientes_contrato'
        managed = False
        ordering = ['-id']

    def __str__(self):
        return f'Contrato #{self.id} — {self.estudiante.nombre_completo}'


class Cuota(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    numero = models.IntegerField()  # Ej: cuota 1, 2, ...
    fecha_vencimiento = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)

    # Campo legacy (cache) — se recomienda reemplazar por sumatoria de aplicaciones:
    valor_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    estado = models.CharField(
        max_length=20,
        choices=[
            ('Pendiente', 'Pendiente'),
            ('Pagada', 'Pagada'),
            ('Vencida', 'Vencida'),
            ('Parcial', 'Parcial'),
        ],
        default='Pendiente'
    )

    class Meta:
        db_table = 'gestion_clientes_cuota'
        managed = False
        unique_together = (('contrato', 'numero'),)
        ordering = ['fecha_vencimiento', 'numero']
        indexes = [
            models.Index(fields=['fecha_vencimiento']),
            models.Index(fields=['estado']),
        ]

    # === Métodos existentes (compatibilidad) ===
    def calcular_saldo(self):
        return (self.valor or Decimal('0')) - (self.valor_pagado or Decimal('0'))

    # === Nuevos métodos recomendados (vía aplicaciones) ===
    def pagado_via_aplicaciones(self):
        from django.db import models as dj_models
        return (self.aplicaciones.aggregate(total=dj_models.Sum('monto'))['total']) or Decimal('0')

    def saldo_via_aplicaciones(self):
        return (self.valor or Decimal('0')) - self.pagado_via_aplicaciones()

    def __str__(self):
        return f"Cuota {self.numero} de contrato {self.contrato.id}"

class MedioPago(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'gestion_finanzas_medio_pago'
        managed = False

    def __str__(self):
        return self.nombre

class Pago(models.Model):
    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE
    )

    # =========================
    # NUEVO (OFICIAL)
    # =========================
    medio_pago = models.ForeignKey(
        MedioPago,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column='medio_pago_id',
        related_name='pagos'
    )

    # =========================
    # LEGACY (NO TOCAR AÚN)
    # =========================
    cuota = models.ForeignKey(
        Cuota,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pagos',
        help_text='[LEGACY] No usar en nuevo flujo; usar PagoAplicacion.'
    )

    fecha_pago = models.DateField(db_index=True)
    valor_pagado = models.DecimalField(max_digits=10, decimal_places=2)
    forma_pago = models.CharField(max_length=50)
    # LEGACY — se eliminará después
#    FORMA_PAGO = [
#('Efectivo', 'Efectivo'),
 #       ('Transferencia', 'Transferencia'),
  #      ('Banco', 'Banco'),
   #     ('Nequi', 'Nequi'),
    #    ('Otro', 'Otro'),
    #]
    
    #forma_pago = models.CharField(
     #   max_length=50,
      #  choices=FORMA_PAGO,
       # help_text='[LEGACY] No usar en nuevo flujo'
    #)
    
    

    observacion = models.TextField(blank=True, null=True)
    referencia = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Soporte / recibo / referencia'
    )

    numero_factura = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        db_index=True
    )

    class Meta:
        db_table = 'gestion_clientes_pago'
        managed = False
        indexes = [
            models.Index(fields=['fecha_pago']),
            models.Index(fields=['numero_factura']),
            models.Index(fields=['referencia']),
            models.Index(fields=['medio_pago']),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.cuota and self.cuota.contrato_id != self.contrato_id:
            raise ValidationError("La cuota seleccionada no pertenece a este contrato.")

        if self.valor_pagado is None or self.valor_pagado <= Decimal('0'):
            raise ValidationError("El valor del pago debe ser mayor a cero.")

    def __str__(self):
        return f"Pago #{self.id} | {self.fecha_pago} | ${self.valor_pagado}"


class PagoAplicacion(models.Model):
    """
    Detalle de distribución del Pago (cabecera) sobre una o varias cuotas.
    Fuente de verdad para 'pagado' y 'saldo' de cada cuota.
    """
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE)
    cuota = models.ForeignKey(Cuota, on_delete=models.CASCADE, related_name='aplicaciones')
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'gestion_clientes_pagoaplicacion'
        managed = False
        # Un mismo pago no debe tener más de una fila aplicando a la MISMA cuota.
        unique_together = (('pago', 'cuota'),)
        indexes = [
            models.Index(fields=['pago']),
            models.Index(fields=['cuota']),
        ]
        constraints = [
            models.CheckConstraint(check=models.Q(monto__gt=0), name='pagoap_monto_gt_0'),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.monto is None or self.monto <= Decimal('0'):
            raise ValidationError("El monto aplicado debe ser mayor a cero.")
        # Coherencia de contrato entre pago y cuota
        if self.pago and self.cuota and self.pago.contrato_id != self.cuota.contrato_id:
            raise ValidationError("El pago y la cuota pertenecen a contratos diferentes.")

    def __str__(self):
        return f"Pago #{self.pago_id} → Cuota #{self.cuota_id}: ${self.monto}"

class ConceptoIngreso(models.Model):
    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=120, unique=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(db_column='created_at')

    class Meta:
        db_table = 'gestion_finanzas_concepto_ingreso'
        managed = False

    def __str__(self):
        return self.nombre

class Ingreso(models.Model):
    TIPOS_REGISTRO = [
        ('otro_ingreso', 'Otro ingreso'),
        ('pago_cuota', 'Pago de cuota'),
    ]

    id = models.BigAutoField(primary_key=True)

    sede = models.ForeignKey(
        'gestion_clientes.Sede',
        on_delete=models.PROTECT,
        db_column='sede_id'
    )

    # ===============================
    # 🔹 CONCEPTO CONTABLE DEL INGRESO
    # ===============================
    concepto_ingreso = models.ForeignKey(
        'gestion_clientes.ConceptoIngreso',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column='concepto_ingreso_id',
        related_name='ingresos'
    )

    # Texto libre legacy (no se elimina)
    #tipo_ingreso = models.CharField(max_length=50)

    valor_pagado = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_pago = models.DateField()
    forma_pago = models.CharField(max_length=50)

    referencia = models.CharField(max_length=100, null=True, blank=True)
    observacion = models.TextField(null=True, blank=True)

    tipo_registro = models.CharField(
        max_length=20,
        choices=TIPOS_REGISTRO,
        default='otro_ingreso',
        db_column='tipo_registro'
    )

    usuario_registro = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        db_column='usuario_registro_id'
    )

    pago = models.ForeignKey(
        'gestion_clientes.Pago',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='pago_id'
    )

    contrato = models.ForeignKey(
        'gestion_clientes.Contrato',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='contrato_id'
    )

    cuota = models.ForeignKey(
        'gestion_clientes.Cuota',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='cuota_id'
    )

    numero_factura = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        db_column='numero_factura'
    )

    creado_en = models.DateTimeField(auto_now_add=True, db_column='creado_en')
    actualizado_en = models.DateTimeField(auto_now=True, db_column='actualizado_en')

    class Meta:
        db_table = 'gestion_financiera_ingreso'
        managed = False
        verbose_name = 'Ingreso'
        verbose_name_plural = 'Ingresos'

    def __str__(self):
        return f"Ingreso #{self.id} - {self.valor_pagado} ({self.fecha_pago})"
class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    sedes = models.ManyToManyField(
        Sede,
        blank=True,
        related_name="perfiles",                 # evita choques de reverse accessor
        db_table="gestion_clientes_perfil_sedes" # usa tu tabla real
    )

    class Meta:
        db_table = "gestion_clientes_perfil"
        managed = False

    def __str__(self):
        return self.user.username
    
