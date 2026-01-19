from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from .models import Acudiente, Estudiante, Contrato, Ingreso, Sede, MedioPago
from gestion_clientes.models import (
    Gasto,
    ConceptoGasto,
    MedioPago,
    Sede,
)


# ==========================================================
#  FORMULARIOS AUXILIARES (existentes)
# ==========================================================
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


# ==========================================================
#  ACUDIENTE
# ==========================================================
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


# ==========================================================
#  ESTUDIANTE
# ==========================================================
class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        # ✅ AJUSTE MÍNIMO: excluir acudiente porque se asigna en backend (commit=False)
        exclude = ['valor_paquete_total', 'acudiente']
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
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Requeridos (se deja igual)
        for f in ["nombre_completo", "tipo_documento", "documento", "fecha_nacimiento",
                "nivel", "sede", "estado", "horario"]:
            if f in self.fields:
                self.fields[f].required = True
                self.fields[f].error_messages["required"] = "Este campo es obligatorio."

        # =========================
        # SEGURIDAD POR SEDE (dropdown + validación server-side)
        # =========================
        if 'sede' in self.fields:
            self.fields['sede'].queryset = Sede.objects.none()

            if not user:
                return

            # Admin / CEO / CFO / superuser: ven todas
            if user.is_superuser or user.groups.filter(name__in=['Admin', 'CEO', 'CFO']).exists():
                self.fields['sede'].queryset = Sede.objects.all()
                return

            # Resto (ej: Secretaria, Coordinador): solo sedes asignadas
            perfil = getattr(user, 'perfil', None)
            if perfil:
                if hasattr(perfil, 'sedes'):  # ManyToMany
                    self.fields['sede'].queryset = perfil.sedes.all()
                elif getattr(perfil, 'sede_id', None):  # ForeignKey
                    self.fields['sede'].queryset = Sede.objects.filter(pk=perfil.sede_id)

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


# ==========================================================
#  CONTRATO (AJUSTADO PARA COP ENTEROS + PUNTOS)
# ==========================================================
class ContratoForm(forms.ModelForm):
    """
    Clave: sobrescribimos los fields a CharField para que Django NO intente
    parsear como DecimalField antes de nuestros clean_*.
    """

    # Hasta 24 cuotas
    numero_cuotas = forms.TypedChoiceField(
        choices=[(i, str(i)) for i in range(1, 25)],
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    # ✅ Sobrescritura crítica (evita "Enter a number" / "decimal places")
    valor_total = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control text-end",
            "inputmode": "numeric",
            "placeholder": "10.000.000"
        }),
        error_messages={"required": "Este campo es obligatorio."}
    )

    # ✅ También como texto (viene calculado del JS en formato COP)
    valor_cuota_pactada = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control text-end bg-light",
            "readonly": "readonly",
            "inputmode": "numeric",
        })
    )

    # ✅ Campo que viene del HTML/JS (aunque NO esté en el modelo Contrato)
    cuota_inicial = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control text-end",
            "inputmode": "numeric",
            "placeholder": "0"
        })
    )

    # ✅ Campo calculado en front (readonly), lo recibimos para consistencia
    valor_a_financiar = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control text-end bg-light",
            "readonly": "readonly",
            "inputmode": "numeric",
        })
    )

    class Meta:
        model = Contrato
        fields = ['fecha_inicio', 'fecha_fin', 'valor_total', 'valor_cuota_pactada', 'numero_cuotas', 'estado']
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date", "class": "form-control", "readonly": "readonly"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date", "class": "form-control", "readonly": "readonly"}),
            "estado": forms.HiddenInput(),
        }
        exclude = ("fecha_creacion",)

    # ---------------------------
    # Normalizador COP (ENTEROS)
    # ---------------------------
    def _cop_to_decimal_int(self, raw, field_label="valor"):
        """
        Acepta:
          "10.000.000" / "$ 10.000.000" / "10000000" -> Decimal("10000000")
          "416.667" -> Decimal("416667")

        Política actual: SIN DECIMALES (solo enteros COP).
        """
        if raw is None:
            raise ValidationError(f"El {field_label} es obligatorio.")

        s = str(raw).strip()
        if not s:
            raise ValidationError(f"El {field_label} es obligatorio.")

        s = s.replace("$", "").replace(" ", "")
        digits = re.sub(r"[^\d]", "", s)

        if digits == "":
            raise ValidationError(f"Formato de {field_label} inválido. Ej: 10.000.000")

        try:
            return Decimal(digits)
        except (InvalidOperation, ValueError):
            raise ValidationError(f"Formato de {field_label} inválido. Ej: 10.000.000")

    def clean_valor_total(self):
        value = self._cop_to_decimal_int(self.cleaned_data.get("valor_total"), "valor total")
        if value <= 0:
            raise ValidationError("El valor total debe ser mayor a cero.")
        return value

    def clean_valor_cuota_pactada(self):
        raw = self.cleaned_data.get("valor_cuota_pactada")
        if raw in (None, "", "0", 0):
            return Decimal("0")
        return self._cop_to_decimal_int(raw, "valor cuota pactada")

    def clean_cuota_inicial(self):
        raw = self.cleaned_data.get("cuota_inicial")
        if raw in (None, "", "0", 0):
            return Decimal("0")
        value = self._cop_to_decimal_int(raw, "cuota inicial")
        if value < 0:
            raise ValidationError("La cuota inicial no puede ser negativa.")
        return value

    def clean_valor_a_financiar(self):
        raw = self.cleaned_data.get("valor_a_financiar")
        if raw in (None, "", "0", 0):
            return Decimal("0")
        value = self._cop_to_decimal_int(raw, "valor a financiar")
        if value < 0:
            return Decimal("0")
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

        # ✅ Cálculo de cuota pactada basado en VALOR A FINANCIAR (total - cuota inicial)
        total = cleaned.get("valor_total")  # Decimal (por clean_valor_total)
        inicial = cleaned.get("cuota_inicial") or Decimal("0")
        n = cleaned.get("numero_cuotas")

        if total is not None:
            financiar = total - inicial
            if financiar < 0:
                financiar = Decimal("0")

            # coherencia backend (aunque no sea field del modelo)
            cleaned["valor_a_financiar"] = financiar

            if n:
                try:
                    cuota = (Decimal(financiar) / Decimal(n))
                    cuota_entera = int(cuota.to_integral_value(rounding=ROUND_CEILING))
                    cleaned["valor_cuota_pactada"] = Decimal(cuota_entera)
                except Exception:
                    self.add_error("valor_total", "No fue posible calcular el valor de la cuota.")

        cleaned["estado"] = "Activo"
        return cleaned


# ==========================================================
#  INGRESO
# ==========================================================
class IngresoForm(forms.ModelForm):

    medio_pago = forms.ModelChoiceField(
        queryset=MedioPago.objects.filter(activo=True).order_by('nombre'),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Ingreso
        fields = ['fecha_pago', 'valor_pagado', 'medio_pago',
                'observacion', 'referencia', 'numero_factura', 'sede']

        labels = {
            'fecha_pago': 'Fecha',
            'valor_pagado': 'Valor',
            'medio_pago': 'Medio de pago',
            'observacion': 'Observación',
            'referencia': 'Referencia / Recibo',
            'numero_factura': 'Factura',
            'sede': 'Sede',
        }

        widgets = {
            'fecha_pago': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'valor_pagado': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
            'medio_pago': forms.Select(attrs={'class': 'form-select'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'referencia': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'No. remisión / recibo'}),
            'numero_factura': forms.TextInput(attrs={'class': 'form-control'}),
            'sede': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['sede'].queryset = Sede.objects.none()

        if not user:
            return

        if user.is_superuser or user.groups.filter(name__in=['Admin', 'CEO', 'CFO']).exists():
            self.fields['sede'].queryset = Sede.objects.all()
        else:
            perfil = getattr(user, 'perfil', None)
            if perfil:
                if hasattr(perfil, 'sedes'):  # ManyToMany
                    self.fields['sede'].queryset = perfil.sedes.all()
                elif getattr(perfil, 'sede_id', None):  # ForeignKey
                    self.fields['sede'].queryset = Sede.objects.filter(pk=perfil.sede_id)

class GastoForm(forms.ModelForm):
    class Meta:
        model = Gasto
        fields = [
            'sede', 'fecha_gasto', 'concepto_gasto', 'medio_pago',
            'valor', 'referencia_factura', 'referencia', 'observacion'
        ]
        widgets = {
            'fecha_gasto': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'referencia_factura': forms.TextInput(attrs={'class': 'form-control'}),
            'referencia': forms.TextInput(attrs={'class': 'form-control'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        sedes_qs = kwargs.pop('sedes_qs', None)
        super().__init__(*args, **kwargs)

        self.fields['sede'].widget.attrs.update({'class': 'form-select'})
        self.fields['concepto_gasto'].widget.attrs.update({'class': 'form-select'})
        self.fields['medio_pago'].widget.attrs.update({'class': 'form-select'})

        self.fields['concepto_gasto'].queryset = ConceptoGasto.objects.filter(activo=1).order_by('categoria', 'nombre')
        self.fields['medio_pago'].queryset = MedioPago.objects.all().order_by('nombre')

        if sedes_qs is not None:
            self.fields['sede'].queryset = sedes_qs

    def clean_valor(self):
        v = self.cleaned_data.get('valor')
        if v is None or v <= 0:
            raise forms.ValidationError("El valor debe ser mayor a 0.")
        return v

    def clean_referencia_factura(self):
        x = (self.cleaned_data.get('referencia_factura') or '').strip()
        if not x:
            raise forms.ValidationError("La referencia / factura es obligatoria.")
        return x