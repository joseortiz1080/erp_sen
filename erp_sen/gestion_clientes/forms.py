from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import re
from .models import Acudiente, Estudiante, Contrato
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from .models import Ingreso,Sede

class AcudienteExistenteForm(forms.Form):
    acudiente_existente = forms.ModelChoiceField(
        queryset=Acudiente.objects.order_by('nombre_completo'),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )


class EstudianteExistenteForm(forms.Form):
    estudiante_existente = forms.ModelChoiceField(
        queryset=Estudiante.objects.order_by('nombre_completo'),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )


class AcudienteForm(forms.ModelForm):
    email = forms.EmailField(
        required=True,
        error_messages={"required": "Este campo es obligatorio."},
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = Acudiente
        fields = '__all__'
        widgets = {
            "nombre_completo": forms.TextInput(attrs={"class": "form-control"}),
            "tipo_documento": forms.Select(attrs={"class": "form-select"}),
            "documento": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ["nombre_completo", "tipo_documento", "documento", "telefono", "email"]:
            if f in self.fields:
                self.fields[f].required = True
                self.fields[f].error_messages["required"] = "Este campo es obligatorio."

    def clean_nombre_completo(self):
        nombre = (self.cleaned_data.get("nombre_completo") or "").strip()
        if len(nombre) < 3:
            raise ValidationError("El nombre debe tener al menos 3 caracteres.")
        return nombre

    def clean_telefono(self):
        tel = (self.cleaned_data.get("telefono") or "").strip()
        if not re.fullmatch(r"[0-9\-\+\(\)\s]+", tel):
            raise ValidationError("El teléfono solo puede contener dígitos y separadores (+ - ( ) y espacios).")
        digits = re.sub(r"\D", "", tel)
        if len(digits) < 7 or len(digits) > 15:
            raise ValidationError("El teléfono debe tener entre 7 y 15 dígitos.")
        return tel


class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        exclude = ['valor_paquete_total']
        widgets = {
            "nombre_completo": forms.TextInput(attrs={"class": "form-control"}),
            "tipo_documento": forms.Select(attrs={"class": "form-select"}),
            "documento": forms.TextInput(attrs={"class": "form-control"}),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "nivel": forms.Select(attrs={"class": "form-select"}),
            "sede": forms.Select(attrs={"class": "form-select"}),
            "estado": forms.Select(attrs={"class": "form-select"}),
            "observacion": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "horario": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ["nombre_completo", "tipo_documento", "documento", "fecha_nacimiento",
                "nivel", "sede", "estado", "horario"]:
            if f in self.fields:
                self.fields[f].required = True
                self.fields[f].error_messages["required"] = "Este campo es obligatorio."

    def clean_nombre_completo(self):
        nombre = (self.cleaned_data.get("nombre_completo") or "").strip()
        if len(nombre) < 3:
            raise ValidationError("El nombre del estudiante debe tener al menos 3 caracteres.")
        return nombre

    def clean_fecha_nacimiento(self):
        fn = self.cleaned_data.get("fecha_nacimiento")
        if fn and fn > timezone.now().date():
            raise ValidationError("La fecha de nacimiento no puede ser futura.")
        return fn


class ContratoForm(forms.ModelForm):
    # Ahora hasta 24 cuotas
    numero_cuotas = forms.TypedChoiceField(
        choices=[(i, str(i)) for i in range(1, 25)],
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = Contrato
        fields = ['fecha_inicio', 'fecha_fin', 'valor_total', 'valor_cuota_pactada', 'numero_cuotas', 'estado']
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date", "class": "form-control", "readonly": "readonly"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date", "class": "form-control", "readonly": "readonly"}),  # se calcula
            "valor_total": forms.TextInput(attrs={
                "class": "form-control text-end",
                "inputmode": "numeric",
                "placeholder": "12.000.000,00"
            }),
            "valor_cuota_pactada": forms.NumberInput(attrs={
                "class": "form-control text-end",
                "step": "0.01",
                "readonly": "readonly"
            }),
            "estado": forms.HiddenInput(),  # oculto; lo forzamos a "Activo"
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ["fecha_inicio", "valor_total", "numero_cuotas", "estado"]:
            if f in self.fields:
                self.fields[f].required = True
                self.fields[f].error_messages["required"] = "Este campo es obligatorio."
        if "fecha_fin" in self.fields:
            self.fields["fecha_fin"].required = False
        if "valor_cuota_pactada" in self.fields:
            self.fields["valor_cuota_pactada"].required = False
            self.fields["valor_cuota_pactada"].disabled = False
        # Estado por defecto
        if "estado" in self.fields:
            self.fields["estado"].initial = "Activo"

    def clean_valor_total(self):
        raw = self.cleaned_data.get("valor_total")
        if raw is None:
            raise ValidationError("El valor total es obligatorio.")
        s = str(raw).strip()
        if not s:
            raise ValidationError("El valor total es obligatorio.")
        s = s.replace("$", "").replace(" ", "")
        try:
            if "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", "")
            elif "," in s:
                s = s.replace(".", "").replace(",", ".")
            value = Decimal(s)
        except (InvalidOperation, ValueError):
            raise ValidationError("Formato de número inválido. Ej: 12.000.000,00")
        if value <= 0:
            raise ValidationError("El valor total debe ser mayor a cero.")
        return value

    def clean_fecha_inicio(self):
        d = self.cleaned_data.get('fecha_inicio')
        if d and d.day not in (5, 20):
            raise ValidationError('La fecha de inicio debe ser el día 5 o 20 del mes.')
        return d

    def clean(self):
        cleaned = super().clean()
        fi = cleaned.get("fecha_inicio")
        ff = cleaned.get("fecha_fin")
        if fi and ff and ff < fi:
            self.add_error("fecha_fin", "La fecha fin no puede ser anterior a la fecha de inicio.")
        total = cleaned.get("valor_total")
        n = cleaned.get("numero_cuotas")
        if total is not None and n:
            try:
                cuota = (Decimal(total) / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cleaned["valor_cuota_pactada"] = cuota
            except Exception:
                self.add_error("valor_total", "No fue posible calcular el valor de la cuota.")
        # Forzar estado Activo
        cleaned["estado"] = "Activo"
        return cleaned

from django import forms
from .models import Ingreso, Sede

class IngresoForm(forms.ModelForm):
    class Meta:
        model = Ingreso
        fields = ['fecha_pago', 'tipo_ingreso', 'valor_pagado', 'forma_pago',
                'observacion', 'referencia', 'numero_factura', 'sede']
        labels = {
            'fecha_pago': 'Fecha',
            'tipo_ingreso': 'Concepto',
            'valor_pagado': 'Valor',
            'forma_pago': 'Método',
            'observacion': 'Observación',
            'referencia': 'Referencia / Recibo',
            'numero_factura': 'Factura',
            'sede': 'Sede',
        }
        widgets = {
            'fecha_pago': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'tipo_ingreso': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Certificado, Libro, Bus, etc.'}),
            'valor_pagado': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'forma_pago': forms.Select(choices=[
                ('Efectivo', 'Efectivo'),
                ('Banco', 'Banco'),
                ('Transferencia', 'Transferencia'),
                ('Nequi', 'Nequi'),
                ('Otro', 'Otro'),
            ], attrs={'class': 'form-select'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'referencia': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'No. remisión / recibo'}),
            'numero_factura': forms.TextInput(attrs={'class': 'form-control'}),
            'sede': forms.Select(attrs={'class': 'form-select'}),
        }


    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)  # 👈 NECESARIO
        super().__init__(*args, **kwargs)

        # Por defecto, no mostrar nada
        self.fields['sede'].queryset = Sede.objects.none()

        if not user:
            return

        # Si es Admin / CEO / CFO → todas las sedes
        if user.is_superuser or user.groups.filter(name__in=['Admin', 'CEO', 'CFO']).exists():
            self.fields['sede'].queryset = Sede.objects.all()
        else:
            # Si tiene perfil con sedes
            perfil = getattr(user, 'perfil', None)
            if perfil:
                if hasattr(perfil, 'sedes'):  # ManyToMany
                    self.fields['sede'].queryset = perfil.sedes.all()
                elif getattr(perfil, 'sede_id', None):  # ForeignKey
                    self.fields['sede'].queryset = Sede.objects.filter(pk=perfil.sede_id)
