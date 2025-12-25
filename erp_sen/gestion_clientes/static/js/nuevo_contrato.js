document.addEventListener('DOMContentLoaded', function () {
  // ====== BUSCAR ACUDIENTE ======
  const buscarBtn   = document.getElementById("btn-buscar-acudiente");
  const inputCedula = document.getElementById("buscar_cedula");
  const msg         = document.getElementById("acudiente-msg");

  if (buscarBtn && inputCedula && msg) {
    buscarBtn.addEventListener("click", function () {
      const cedula = inputCedula.value.trim();
      if (!cedula) {
        msg.innerText = "Por favor ingresa una cédula.";
        return;
      }

      msg.innerText = "Buscando acudiente...";

      fetch(`/api/acudientes/buscar/?documento=${cedula}`)
        .then(response => {
          if (!response.ok) throw new Error("Error en la petición");
          return response.json();
        })
        .then(data => {
          if (data.existe) {
            document.querySelector("#id_acudiente-nombre_completo").value = data.nombre_completo || "";
            document.querySelector("#id_acudiente-documento").value       = cedula;
            document.querySelector("#id_acudiente-telefono").value        = data.telefono || "";
            document.querySelector("#id_acudiente-email").value           = data.email || "";

            const tipoDocField = document.querySelector("#id_acudiente-tipo_documento");
            if (tipoDocField) {
              const existeOpcion = [...tipoDocField.options].some(opt => opt.value === data.tipo_documento);
              if (existeOpcion) tipoDocField.value = data.tipo_documento;
            }

            msg.innerHTML = "✅ Acudiente encontrado y cargado.";
            msg.classList.remove("text-danger");
            msg.classList.add("text-success");
          } else {
            msg.innerText = "❌ No se encontró el acudiente.";
            msg.classList.remove("text-success");
            msg.classList.add("text-danger");
          }
        })
        .catch(error => {
          console.error("Error en la petición:", error);
          msg.innerText = "❌ Error al buscar acudiente.";
          msg.classList.remove("text-success");
          msg.classList.add("text-danger");
        });
    });
  }

  // ==========================================================
  // ====== UTILIDADES: ENTEROS + FORMATO COP =================
  // ==========================================================
  function parseCOPInt(value) {
    if (value == null) return 0;
    const raw = String(value).replace(/[^\d]/g, ''); // quita todo menos dígitos (incluye puntos, comas, $)
    const n = parseInt(raw || '0', 10);
    return isFinite(n) && n > 0 ? n : 0;
  }

  function formatCOPInt(n) {
    const v = Number(n) || 0;
    return v.toLocaleString('es-CO'); // 1.234.567
  }

  // Formatea un input a COP (sin $) y devuelve entero
  function normalizeMoneyInput($input) {
    if (!$input) return 0;

    const n = parseCOPInt($input.value);

    // Si el input es type="number", NO se le pueden poner puntos (queda inválido).
    // Solución corporativa: si es number, mostramos entero sin formato; si es text, mostramos formato COP.
    const type = ($input.getAttribute('type') || '').toLowerCase();
    if (type === 'number') {
      $input.value = String(n);
    } else {
      $input.value = (n > 0) ? formatCOPInt(n) : '';
    }
    return n;
  }

  // ==========================================================
  // ====== CAMPOS CONTRATO ===================================
  // ==========================================================
  const $total          = document.getElementById('id_valor_total');
  const $cuotaInicial   = document.getElementById('cuota_inicial');      // TU HTML
  const $valorFinanciar = document.getElementById('valor_a_financiar');  // TU HTML
  const $cuotas         = document.getElementById('id_numero_cuotas');
  const $pactada        = document.getElementById('id_valor_cuota_pactada');

  if ($valorFinanciar) {
    $valorFinanciar.readOnly = true;
    $valorFinanciar.classList.add('bg-light');
  } else {
    console.warn('No encontré el input de "Valor a financiar". Revise el id="valor_a_financiar" en el HTML.');
  }

  if ($pactada) {
    $pactada.readOnly = true;
    $pactada.classList.add('bg-light');
  }

  // ==========================================================
  // ====== CÁLCULO: VALOR A FINANCIAR ========================
  // ==========================================================
  function recalcularValorFinanciar() {
    if (!$total || !$cuotaInicial || !$valorFinanciar) return 0;

    const total   = parseCOPInt($total.value);
    const inicial = parseCOPInt($cuotaInicial.value);

    let financiar = total - inicial;
    if (financiar < 0) financiar = 0;

    // valor_a_financiar es text readonly: se puede formatear sin problema
    $valorFinanciar.value = formatCOPInt(financiar);
    return financiar;
  }

  // ==========================================================
  // ====== CÁLCULO: CUOTA PACTADA (CEIL) =====================
  // ====== usa VALOR A FINANCIAR, NO total ===================
  // ==========================================================
  function recalcCuota() {
    if (!$valorFinanciar || !$cuotas || !$pactada) return;

    const financiar = parseCOPInt($valorFinanciar.value);
    const n         = parseInt($cuotas.value || '0', 10);

    if (!(financiar > 0 && n > 0)) {
      $pactada.value = '';
      return;
    }

    const cuotaCeil = Math.ceil(financiar / n); // redondeo hacia arriba
    $pactada.value = formatCOPInt(cuotaCeil);
  }

  // ==========================================================
  // ====== EVENTOS + FORMATO EN VIVO =========================
  // ==========================================================
  if ($total) {
    // Total suele venir del form Django (puede ser text/number). Normalizamos y recalculamos.
    $total.addEventListener('input', () => {
      normalizeMoneyInput($total);
      recalcularValorFinanciar();
      recalcCuota();
    });

    $total.addEventListener('change', () => {
      normalizeMoneyInput($total);
      recalcularValorFinanciar();
      recalcCuota();
    });

    // Mejor UX: formatear al salir del campo (si es text)
    $total.addEventListener('blur', () => {
      normalizeMoneyInput($total);
      recalcularValorFinanciar();
      recalcCuota();
    });
  }

  if ($cuotaInicial) {
    // Si es text: formateo en vivo controlado
    $cuotaInicial.addEventListener('input', () => {
      // No forzamos formato cada tecla si es number.
      const type = ($cuotaInicial.getAttribute('type') || '').toLowerCase();
      if (type !== 'number') {
        normalizeMoneyInput($cuotaInicial);
      }
      recalcularValorFinanciar();
      recalcCuota();
    });

    $cuotaInicial.addEventListener('change', () => {
      normalizeMoneyInput($cuotaInicial);
      recalcularValorFinanciar();
      recalcCuota();
    });

    $cuotaInicial.addEventListener('blur', () => {
      normalizeMoneyInput($cuotaInicial);
      recalcularValorFinanciar();
      recalcCuota();
    });
  } else {
    console.warn('No encontré el input de "Cuota inicial". Revise el id="cuota_inicial" en el HTML.');
  }

  if ($cuotas) {
    $cuotas.addEventListener('change', () => {
      recalcularValorFinanciar();
      recalcCuota();
    });
  }

  // Inicial (normaliza y pinta)
  if ($total)        normalizeMoneyInput($total);
  if ($cuotaInicial) normalizeMoneyInput($cuotaInicial);
  recalcularValorFinanciar();
  recalcCuota();

  // ====== DÍA DE CORTE (5/20) + FECHAS ======
  const $diaCorte    = document.getElementById('dia_corte');
  const $fechaInicio = document.getElementById('id_fecha_inicio');
  const $fechaFin    = document.getElementById('id_fecha_fin');

  [$fechaInicio, $fechaFin].forEach(($input) => {
    if (!$input) return;
    $input.readOnly = true;
    $input.classList.add('bg-light');
    $input.addEventListener('keydown',  e => e.preventDefault());
    $input.addEventListener('keypress', e => e.preventDefault());
    $input.addEventListener('paste',    e => e.preventDefault());
    ['click','mousedown','pointerdown'].forEach(evt =>
      $input.addEventListener(evt, e => e.preventDefault())
    );
  });

  const pad2 = (n) => (n < 10 ? '0' + n : '' + n);

  function addMonthsKeepDay(d, months) {
    const y = d.getFullYear();
    const m = d.getMonth();
    const targetMonthIndex = m + months;
    const targetYear  = y + Math.floor(targetMonthIndex / 12);
    const targetMonth = (targetMonthIndex % 12 + 12) % 12;
    const lastDay     = new Date(targetYear, targetMonth + 1, 0).getDate();
    const day         = Math.min(d.getDate(), lastDay);
    return new Date(targetYear, targetMonth, day);
  }

  function setDateInput($input, dateObj) {
    if (!$input || !(dateObj instanceof Date) || isNaN(dateObj)) return;
    const yyyy = dateObj.getFullYear();
    const mm   = pad2(dateObj.getMonth() + 1);
    const dd   = pad2(dateObj.getDate());
    $input.value = `${yyyy}-${mm}-${dd}`;
  }

  function parseInputDate($input) {
    if (!$input || !$input.value) return null;
    const parts = $input.value.split('-');
    if (parts.length !== 3) return null;
    const y = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    const d = parseInt(parts[2], 10);
    const dt = new Date(y, m - 1, d);
    return isNaN(dt) ? null : dt;
  }

  function setFechaInicioFromCorte() {
    if (!$diaCorte || !$fechaInicio) return;
    const corte = parseInt($diaCorte.value || '5', 10);
    const today = new Date();
    const nextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1);
    const lastDay   = new Date(nextMonth.getFullYear(), nextMonth.getMonth() + 1, 0).getDate();
    const dia       = Math.min(corte, lastDay);
    const start     = new Date(nextMonth.getFullYear(), nextMonth.getMonth(), dia);
    setDateInput($fechaInicio, start);
    recalcFechaFin();
  }

  function recalcFechaFin() {
    if (!$fechaInicio || !$fechaFin || !$cuotas) return;
    const n  = parseInt($cuotas.value || '0', 10);
    const fi = parseInputDate($fechaInicio);
    if (!fi || !(n > 0)) {
      $fechaFin.value = '';
      return;
    }
    const ff = addMonthsKeepDay(fi, n - 1);
    setDateInput($fechaFin, ff);
  }

  if ($diaCorte) {
    if ($fechaInicio && !$fechaInicio.value) setFechaInicioFromCorte();
    $diaCorte.addEventListener('change', setFechaInicioFromCorte);
  }
  if ($fechaInicio) $fechaInicio.addEventListener('change', recalcFechaFin);
  if ($cuotas)      $cuotas.addEventListener('change',  recalcFechaFin);

  recalcFechaFin();

    // ==========================================================
  // ====== FIX GUARDADO: LIMPIAR FORMATO ANTES DE SUBMIT =====
  // ==========================================================
  const form = document.querySelector('form');

  function stripThousandsToPlainNumber(el) {
    if (!el) return;
    // deja solo dígitos
    const n = parseCOPInt(el.value);
    // si el input es readonly/text, igual debe enviar número limpio
    el.value = String(n);
  }

  if (form) {
    form.addEventListener('submit', function () {
      // Campos que NO pueden ir con "10.000.000"
      stripThousandsToPlainNumber(document.getElementById('id_valor_total'));
      stripThousandsToPlainNumber(document.getElementById('id_valor_cuota_pactada'));

      // Cuota inicial es input number, pero igual lo normalizamos por consistencia
      stripThousandsToPlainNumber(document.getElementById('cuota_inicial'));

      // valor_a_financiar es readonly text; si no existe en form Django no pasa nada, pero lo limpiamos
      stripThousandsToPlainNumber(document.getElementById('valor_a_financiar'));
    });
  }
});