from django.db import models

class Horario(models.Model):
    hora = models.TimeField(unique=True)  # Ejemplo: 08:00:00
    descripcion = models.CharField(max_length=50, help_text='Ej: 8:00 am, 2:00 pm')

    def __str__(self):
        return self.descripcion

class Sede(models.Model):
    nombre = models.CharField(max_length=100)
    ciudad = models.CharField(max_length=100)
    direccion = models.TextField()

    def __str__(self):
        return f"{self.nombre} - {self.ciudad}"

class Acudiente(models.Model):
    nombre_completo = models.CharField(max_length=150)
    tipo_documento = models.CharField(max_length=10, choices=[('CC', 'Cédula'), ('TI', 'Tarjeta de Identidad')])
    documento = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20)
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.nombre_completo

class Nivel(models.Model):
    codigo = models.CharField(max_length=10, unique=True)  # Ej: A1, B2, Kids
    nombre = models.CharField(max_length=50)               # Ej: Básico A1
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

class Estudiante(models.Model):
    ESTADOS = [
        ('Activo', 'Activo'),
        ('Aplazado', 'Aplazado'),
        ('Retirado', 'Retirado'),
        ('Graduado', 'Graduado'),
    ]

    nombre_completo = models.CharField(max_length=150)
    fecha_nacimiento = models.DateField()
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT)
    acudiente = models.ForeignKey(Acudiente, on_delete=models.PROTECT)
    sede = models.ForeignKey(Sede, on_delete=models.PROTECT)

    valor_paquete_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estado = models.CharField(max_length=10, choices=ESTADOS, default='Activo')
    observacion = models.TextField(blank=True, null=True)
    horario = models.ForeignKey(Horario, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return self.nombre_completo

class Contrato(models.Model):
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE)
    acudiente = models.ForeignKey(Acudiente, on_delete=models.CASCADE)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    valor_cuota_pactada = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    numero_cuotas = models.IntegerField(default=1)
    estado = models.CharField(max_length=20, choices=[
        ('Activo', 'Activo'), ('Finalizado', 'Finalizado')
    ])

    def calcular_total_pagado(self):
        return sum(p.valor_pagado for p in self.pago_set.all())

    def calcular_saldo(self):
        return self.valor_total - self.calcular_total_pagado()

    def __str__(self):
        return f"Contrato de {self.estudiante} - {self.estado}"

class Cuota(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    numero = models.IntegerField()  # Ej: cuota 1, 2, ...
    fecha_vencimiento = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    valor_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=20, choices=[
        ('Pendiente', 'Pendiente'),
        ('Pagada', 'Pagada'),
        ('Vencida', 'Vencida'),
        ('Parcial', 'Parcial'),
    ], default='Pendiente')

    def calcular_saldo(self):
        return self.valor - self.valor_pagado

    def __str__(self):
        return f"Cuota {self.numero} de contrato {self.contrato.id}"

class Pago(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    fecha_pago = models.DateField()
    valor_pagado = models.DecimalField(max_digits=10, decimal_places=2)
    forma_pago = models.CharField(max_length=50, choices=[
        ('Efectivo', 'Efectivo'), ('Transferencia', 'Transferencia'), ('Otro', 'Otro')
    ])
    observacion = models.TextField(blank=True, null=True)

    # NUEVO CAMPO
    referencia = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.fecha_pago} - ${self.valor_pagado}"

