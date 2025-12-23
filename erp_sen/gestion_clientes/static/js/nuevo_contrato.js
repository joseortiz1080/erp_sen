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

  // ====== CÁLCULO AUTOMÁTICO DE VALOR CUOTA PACTADA ======
  const $total   = document.getElementById('id_valor_total');
  const $cuotas  = document.getElementById('id_numero_cuotas');
  const $pactada = document.getElementById('id_valor_cuota_pactada');

  if ($pactada) {
    $pactada.readOnly = true;
    $pactada.classList.add('bg-light');
  }

  function toNumber(x) {
    if (x == null) return 0;
    const s = String(x).replace(/[^0-9.,]/g, '').replace(',', '.');
    const n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  function recalcCuota() {
    if (!$total || !$cuotas || !$pactada) return;
    const total = toNumber($total.value);
    const n     = parseInt($cuotas.value || '0', 10);
    const cuota = (total > 0 && n > 0) ? (total / n) : 0;
    $pactada.value = cuota ? cuota.toFixed(2) : '';
  }

  if ($total)  $total.addEventListener('input',  recalcCuota);
  if ($cuotas) $cuotas.addEventListener('change', recalcCuota);
  recalcCuota();

  // ====== DÍA DE CORTE (5/20) + FECHAS ======
  const $diaCorte    = document.getElementById('dia_corte');      // select del template
  const $fechaInicio = document.getElementById('id_fecha_inicio');
  const $fechaFin    = document.getElementById('id_fecha_fin');

  // --- BLOQUEO DURO: INICIO y FIN visibles pero NO editables ---
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

  // Utils fecha
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

  // Setea fecha_inicio = mes siguiente con día 5 o 20
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

  // fecha_fin = fecha_inicio + (n - 1) meses
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

  // Eventos
  if ($diaCorte) {
    if ($fechaInicio && !$fechaInicio.value) setFechaInicioFromCorte();
    $diaCorte.addEventListener('change', setFechaInicioFromCorte);
  }
  if ($fechaInicio) $fechaInicio.addEventListener('change', recalcFechaFin);
  if ($cuotas)      $cuotas.addEventListener('change',  recalcFechaFin);

  // Inicial
  recalcFechaFin();
});