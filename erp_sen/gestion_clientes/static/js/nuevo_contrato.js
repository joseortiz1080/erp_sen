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
  // ====== SWITCH: REGISTRAR CUOTA INICIAL ===================
  // ==========================================================
  // (AJUSTE MINIMO) Helper para soportar IDs Django (id_*) y IDs manuales
  function getFirstEl(ids) {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) return el;
    }
    return null;
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
  // (AJUSTE MINIMO) Soportar IDs manuales y Django por defecto (id_*)
  const $total          = getFirstEl(['valor_total', 'id_valor_total']);
  const $cuotaInicial   = getFirstEl(['cuota_inicial', 'id_cuota_inicial']);
  const $valorFinanciar = getFirstEl(['valor_a_financiar', 'id_valor_a_financiar']);
  const $cuotas         = getFirstEl(['numero_cuotas', 'id_numero_cuotas']);
  const $pactada        = getFirstEl(['valor_cuota_pactada', 'id_valor_cuota_pactada']);

  // Checkbox switch (confirmado): name="registrar_cuota_inicial"
  const $switchCuotaInicial = document.querySelector('input[name="registrar_cuota_inicial"]');
  const $wrapCuotaInicial = document.getElementById('wrap_cuota_inicial');
  // Flag hidden (0/1) para backend (confirmado): name="pago_cuota_inicial"
  const $flagPagoCuotaInicial = document.querySelector('input[name="pago_cuota_inicial"]');

  if ($valorFinanciar) {
    $valorFinanciar.readOnly = true;
    $valorFinanciar.classList.add('bg-light');
  } else {
    console.warn('No encontré el input de "Valor a financiar". Revise el id="valor_a_financiar" / "id_valor_a_financiar" en el HTML.');
  }

  if ($pactada) {
    $pactada.readOnly = true;
    $pactada.classList.add('bg-light');
  }

  // ==========================================================
  // ====== CÁLCULO: VALOR A FINANCIAR ========================
  // ==========================================================
  function recalcularValorFinanciar() {
    if (!$total || !$valorFinanciar) return 0;

    const total = parseCOPInt($total.value);
    const on = isSwitchON();

    // OFF: valor_a_financiar = valor_total
    // ON : valor_a_financiar = valor_total - cuota_inicial
    const inicial = (on && $cuotaInicial && !$cuotaInicial.disabled)
      ? parseCOPInt($cuotaInicial.value)
      : 0;

    let financiar = total - inicial;
    if (financiar < 0) financiar = 0;

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
      if ($cuotaInicial.disabled) return;
      // No forzamos formato cada tecla si es number.
      const type = ($cuotaInicial.getAttribute('type') || '').toLowerCase();
      if (type !== 'number') {
        normalizeMoneyInput($cuotaInicial);
      }
      recalcularValorFinanciar();
      recalcCuota();
      syncCuotaInicialPagoUI();
    });

    $cuotaInicial.addEventListener('change', () => {
      if ($cuotaInicial.disabled) return;
      normalizeMoneyInput($cuotaInicial);
      recalcularValorFinanciar();
      recalcCuota();
      syncCuotaInicialPagoUI();
    });

    $cuotaInicial.addEventListener('blur', () => {
      if ($cuotaInicial.disabled) return;
      normalizeMoneyInput($cuotaInicial);
      recalcularValorFinanciar();
      recalcCuota();
      syncCuotaInicialPagoUI();
    });
  } else {
    console.warn('No encontré el input de "Cuota inicial". Revise el id="cuota_inicial" en el HTML.');
  }

  // ==========================================================
  // ====== FIX BUG CUOTA PACTADA: REACCIONAR A # CUOTAS =======
  // ==========================================================
  // (AJUSTE MINIMO) Cuando cambie el número de cuotas, recalcular SIEMPRE con base en Valor a financiar.
  if ($cuotas) {
    const onCuotasChange = () => {
      // No depende del switch: recalcCuota usa SOLO valor_a_financiar.
      // Igual recalculamos valor a financiar por consistencia (si cambió antes y no disparó evento).
      recalcularValorFinanciar();
      recalcCuota();
    };
    $cuotas.addEventListener('change', onCuotasChange);
    $cuotas.addEventListener('input',  onCuotasChange); // por si en algún caso no es select
  }

  // ==========================================================
  // ====== CUOTA INICIAL: CAMPOS DE PAGO (UI) =================
  // ==========================================================
  const $ciPagoWrap = getFirstEl([
    'bloque_pago_cuota_inicial',
    'pago-cuota-inicial-wrap',
    'cuota-inicial-pago-wrap'
  ]);

  const $ciMedio = getFirstEl([
    'pago_cuota_inicial_medio_pago_id',
    'cuota_inicial_medio_pago_id'
  ]);
  const $ciRef = getFirstEl([
    'pago_cuota_inicial_referencia',
    'cuota_inicial_referencia'
  ]);
  const $ciFactura = getFirstEl([
    'pago_cuota_inicial_numero_factura',
    'cuota_inicial_numero_factura'
  ]);
  const $ciObs = getFirstEl([
    'pago_cuota_inicial_observacion',
    'cuota_inicial_observacion'
  ]);

  // ==========================================================
  // ====== CARGA CATÁLOGO: MEDIOS DE PAGO (AJAX) ==============
  // ==========================================================
  // Este <select> se llena desde el endpoint Django `listar_medios_pago`.
  // No viene pre-renderizado por el form, por eso se debe poblar por JS.
  let _mediosPagoLoaded = false;
  let _mediosPagoLoading = false;

  function getMediosPagoURL() {
    if (!$ciMedio) return '';
    // Prioridad: atributo data-medios-url del HTML.
    return ($ciMedio.getAttribute('data-medios-url') || '').trim();
  }

  function getMedioPagoSelectedFromDOM() {
    if (!$ciMedio) return '';
    // Si el backend re-renderiza con POST, dejamos el valor en data-selected.
    const ds = ($ciMedio.getAttribute('data-selected') || '').trim();
    return ds || ($ciMedio.value || '').trim();
  }

  function ensurePlaceholderOption() {
    if (!$ciMedio) return;
    // Mantener una opción vacía tipo "Seleccione...".
    const hasEmpty = [...$ciMedio.options].some(o => (o.value || '').trim() === '');
    if (!hasEmpty) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'Seleccione...';
      $ciMedio.insertBefore(opt, $ciMedio.firstChild);
    }
  }

  function populateMediosPago(medios) {
    if (!$ciMedio) return;

    const selected = getMedioPagoSelectedFromDOM();

    // Limpia todas las opciones y reconstruye (con placeholder).
    $ciMedio.innerHTML = '';
    ensurePlaceholderOption();

    // Cargar opciones del backend.
    for (const m of (medios || [])) {
      if (!m) continue;
      const opt = document.createElement('option');
      opt.value = String(m.id ?? '').trim();
      opt.textContent = String(m.nombre ?? '').trim();
      if (opt.value) $ciMedio.appendChild(opt);
    }

    // Re-seleccionar valor si aplica.
    if (selected) {
      const exists = [...$ciMedio.options].some(o => o.value === selected);
      if (exists) $ciMedio.value = selected;
    }
  }

  function loadMediosPagoOnce() {
    if (!$ciMedio) return;
    if (_mediosPagoLoaded || _mediosPagoLoading) return;

    const url = getMediosPagoURL();
    if (!url) {
      console.warn('No se encontró data-medios-url en el select de medios de pago.');
      return;
    }

    _mediosPagoLoading = true;

    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(data => {
        if (!data || data.ok !== true || !Array.isArray(data.medios)) {
          console.warn('Respuesta inesperada al cargar medios de pago:', data);
          // Aún así dejamos placeholder.
          if ($ciMedio && $ciMedio.options.length === 0) ensurePlaceholderOption();
          return;
        }
        populateMediosPago(data.medios);
        _mediosPagoLoaded = true;
      })
      .catch(err => {
        console.error('No fue posible cargar medios de pago:', err);
        // Dejar placeholder para que el usuario no quede bloqueado visualmente.
        if ($ciMedio && $ciMedio.options.length === 0) ensurePlaceholderOption();
      })
      .finally(() => {
        _mediosPagoLoading = false;
      });
  }

  function setDisabledAndClear(el, disabled) {
    if (!el) return;
    el.disabled = !!disabled;
    if (disabled) {
      el.value = '';
      el.removeAttribute('required');
    }
  }

  function isSwitchON() {
    return !!($switchCuotaInicial && $switchCuotaInicial.checked);
  }

  function setFlagPagoCuotaInicial(on) {
    if ($flagPagoCuotaInicial) {
      $flagPagoCuotaInicial.value = on ? '1' : '0';
    }
  }

  function syncCuotaInicialUIFromSwitch() {
    const on = isSwitchON();
    setFlagPagoCuotaInicial(on);
    if ($wrapCuotaInicial) {
      $wrapCuotaInicial.classList.toggle('d-none', !on);
    }
    if ($cuotaInicial) {
      $cuotaInicial.disabled = !on;
      if (!on) {
        $cuotaInicial.value = '0';
      }
    }

    recalcularValorFinanciar();
    recalcCuota();

    // AJUSTE: el bloque debe responder al ON (no al valor > 0)
    syncCuotaInicialPagoUI();
  }

  function syncCuotaInicialPagoUI() {
    if (!$ciPagoWrap) return;

    const on = isSwitchON();
    const inicial = ($cuotaInicial && !$cuotaInicial.disabled) ? parseCOPInt($cuotaInicial.value) : 0;

    // ==========================================================
    // AJUSTE DEL BUG #3:
    // - El bloque debe MOSTRARSE cuando el switch está ON.
    // - Los campos obligatorios (medio/ref) solo se vuelven required si inicial > 0.
    // ==========================================================
    const mostrarBloque = on;
    const requiereDatos = on && (inicial > 0);

    // Mostrar/ocultar bloque SOLO por ON/OFF
    $ciPagoWrap.classList.toggle('d-none', !mostrarBloque);

    // Habilitar/Deshabilitar campos: habilitados si ON (para que el usuario pueda diligenciar)
    setDisabledAndClear($ciMedio, !mostrarBloque);
    if (mostrarBloque) loadMediosPagoOnce();
    setDisabledAndClear($ciRef, !mostrarBloque);
    setDisabledAndClear($ciFactura, !mostrarBloque);
    setDisabledAndClear($ciObs, !mostrarBloque);

    // Requeridos: solo si cuota inicial > 0
    if (requiereDatos) {
      if ($ciMedio) $ciMedio.setAttribute('required', 'required');
      if ($ciRef)   $ciRef.setAttribute('required', 'required');
    } else {
      if ($ciMedio) $ciMedio.removeAttribute('required');
      if ($ciRef)   $ciRef.removeAttribute('required');
    }
  }

  if ($total) normalizeMoneyInput($total);

  if ($cuotaInicial) {
    if (!isSwitchON()) {
      $cuotaInicial.value = '0';
      $cuotaInicial.disabled = true;
    } else {
      $cuotaInicial.disabled = false;
      normalizeMoneyInput($cuotaInicial);
    }
  }

  recalcularValorFinanciar();
  recalcCuota();
  syncCuotaInicialUIFromSwitch();

  if ($switchCuotaInicial) {
    $switchCuotaInicial.addEventListener('change', () => {
      syncCuotaInicialUIFromSwitch();
    });
  }

  // ====== DÍA DE CORTE (5/20) + FECHAS ======
  const $diaCorte    = document.getElementById('dia_corte');
  const $fechaInicio = getFirstEl(['fecha_inicio', 'id_fecha_inicio']);
  const $fechaFin    = getFirstEl(['fecha_fin', 'id_fecha_fin']);

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
    const n = parseCOPInt(el.value);
    el.value = String(n);
  }

  if (form) {
    form.addEventListener('submit', function (e) {
      const on = isSwitchON();
      const ci = ($cuotaInicial && !$cuotaInicial.disabled) ? parseCOPInt($cuotaInicial.value) : 0;
      if (on && ci <= 0) {
        e.preventDefault();
        alert('Debes ingresar una cuota inicial mayor a 0 o desactivar la opción "Registrar Cuota inicial".');
        return;
      }

      stripThousandsToPlainNumber($total);
      stripThousandsToPlainNumber($pactada);

      if ($cuotaInicial && !$cuotaInicial.disabled) {
        stripThousandsToPlainNumber($cuotaInicial);
      }

      stripThousandsToPlainNumber($valorFinanciar);

      syncCuotaInicialUIFromSwitch();
    });
  }
});