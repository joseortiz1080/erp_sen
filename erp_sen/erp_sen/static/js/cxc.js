(function () {
  // =========================
  // Guards básicos
  // =========================
  const cfg = document.getElementById('cxc-config');
  if (!cfg) { console.error('cxc-config no encontrado'); return; }

  const URL_APLICAR  = cfg.dataset.aplicarUrl || '';
  const URL_ELIMINAR = cfg.dataset.eliminarUrl || '';
  const HOY_DEFAULT  = cfg.dataset.hoy || '';
  const URL_MEDIOS  = cfg.dataset.mediosUrl || '';

  if (!URL_APLICAR || !URL_ELIMINAR || !URL_MEDIOS) {
  console.error('Faltan URLs en cxc-config (aplicar/eliminar/medios).');
  return;
  } 

  if (!window.bootstrap || !bootstrap.Modal) {
    console.error('Bootstrap JS (bundle) no está cargado antes de cxc.js.');
    return;
  }

  const modalEl = document.getElementById('modalPago');
  if (!modalEl) { console.error('#modalPago no existe en el DOM'); return; }

  const modal = new bootstrap.Modal(modalEl);

  // =========================
  // DOM refs
  // =========================
  const form = document.getElementById('pagoForm');
  if (!form) { console.error('#pagoForm no existe'); return; }

  const fCuotaId    = document.getElementById('mp-cuota-id');
  const fCuotaNum   = document.getElementById('mp-cuota-num');
  const fEst        = document.getElementById('mp-estudiante');
  const fAcu        = document.getElementById('mp-acudiente');
  const fNivel      = document.getElementById('mp-nivel');
  const fHora       = document.getElementById('mp-horario');
  const fVence      = document.getElementById('mp-vence');
  const fValorTxt   = document.getElementById('mp-valor');
  const fPagadoTxt  = document.getElementById('mp-pagado');
  const fSaldoTxt   = document.getElementById('mp-saldo');
  const fFecha      = document.getElementById('mp-fecha');
  const fForma      = document.getElementById('mp-medio');
  const fFactura    = document.getElementById('mp-factura');
  const fReferencia = document.getElementById('mp-referencia');
  const fValorPay   = document.getElementById('mp-valor-pagar');
  const fAyuda      = document.getElementById('mp-ayuda');
  const tbodyHist   = document.getElementById('mp-historial-body');

  const fModo       = document.getElementById('mp-modo');
  const btnAuto     = document.getElementById('mp-btn-auto');
  const previasWrap = document.getElementById('mp-previas-wrap');
  const previasBody = document.getElementById('mp-previas-body');

  if (!tbodyHist) { console.error('#mp-historial-body no existe'); return; }

  function formatCOP(n) {
    n = Number(n || 0);
    return '$ ' + n.toLocaleString('es-CO');
  }

  function parseMoneyFromText(txt) {
    return Number(String(txt || '').replace(/[^0-9]/g, '')) || 0;
  }

  async function safeJson(resp, contextLabel) {
    const ct = (resp.headers.get('content-type') || '').toLowerCase();

    if (!ct.includes('application/json')) {
      const raw = await resp.text();
      console.error(`[${contextLabel}] Respuesta NO JSON`, {
        status: resp.status,
        statusText: resp.statusText,
        contentType: ct,
        bodyPreview: raw.slice(0, 800),
      });
      return { __non_json__: true, status: resp.status, rawPreview: raw.slice(0, 800) };
    }

    try {
      return await resp.json();
    } catch (e) {
      console.error(`[${contextLabel}] JSON inválido`, e);
      return { __json_parse_error__: true };
    }
  }

  function manejarErrorHTTP(resp, data, accion = 'la operación') {
    const status = resp?.status || data?.status || 0;

    // 1) Permisos: siempre priorizar el mensaje del backend
    if (status === 403) {
      alert(data?.error || `No estás autorizado para ${accion}.`);
      return true;
    }

    // 2) Respuesta no-JSON / parse error
    if (data && (data.__non_json__ || data.__json_parse_error__)) {
      alert(`Respuesta inválida del servidor al ${accion} (HTTP ${status}).`);
      return true;
    }

    // 3) Error funcional controlado por backend
    if (data && data.error) {
      alert(data.error);
      return true;
    }

    // 4) Fallback
    alert(`Error inesperado al ${accion} (HTTP ${status || '—'}).`);
    return true;
  }

  function renderHistorialError(msg) {
    tbodyHist.innerHTML = `<tr><td colspan="8" class="text-danger">${msg}</td></tr>`;
    previasWrap?.classList.add('d-none');
    previasBody && (previasBody.innerHTML = '');
  }

  let mediosCargados = false;

async function cargarMedios() {
  if (mediosCargados) return;

  if (!fForma) { console.error('#mp-forma no existe'); return; }

  // placeholder
  fForma.innerHTML = '<option value="">Cargando medios…</option>';

  try {
    const resp = await fetch(URL_MEDIOS, {
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      credentials: 'same-origin'
    });

    const data = await safeJson(resp, 'medios_pago');
    if (!resp.ok || !data.ok || !Array.isArray(data.medios)) {
      throw new Error(data.error || `No se pudieron cargar medios (HTTP ${resp.status}).`);
    }

    // opciones
  fForma.innerHTML = '<option value="">Seleccione…</option>' +
  data.medios.map(m => `<option value="${m.id}">${m.nombre}</option>`).join('');

    mediosCargados = true;

  } catch (err) {
    console.error(err);
    fForma.innerHTML = '<option value="">Error cargando medios</option>';
  }
}


  async function cargarHistorial(cuotaId) {
    tbodyHist.innerHTML = '<tr><td colspan="8" class="text-muted">Cargando…</td></tr>';

    try {
      const resp = await fetch(URL_APLICAR + '?cuota_id=' + encodeURIComponent(cuotaId), {
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        },
        credentials: 'same-origin'
      });

      const data = await safeJson(resp, 'historial');

      if (data.__non_json__ || data.__json_parse_error__) {
        if (resp.status === 403) {
          manejarErrorHTTP(resp, data, 'ver el historial');
          renderHistorialError(data?.error || 'No estás autorizado para ver el historial de pagos.');
        } else {
          renderHistorialError(`Respuesta inválida del servidor (HTTP ${data.status}). Ver consola.`);
        }
        return;
      }

      if (resp.status === 403) {
        manejarErrorHTTP(resp, data, 'ver el historial');
        renderHistorialError(data?.error || 'No estás autorizado para ver el historial de pagos.');
        return;
      }

      if (!resp.ok || !data.ok) {
        throw new Error(data.error || `No se pudo obtener el historial (HTTP ${resp.status}).`);
      }

      if (!Array.isArray(data.pagos) || data.pagos.length === 0) {
        tbodyHist.innerHTML = '<tr><td colspan="8" class="text-muted">Sin pagos.</td></tr>';
      } else {
        tbodyHist.innerHTML = data.pagos.map((p, i) => {
          const rc    = p.numero_comprobante || '—';
          const valor = formatCOP(p.valor_pagado);
          const fac   = p.numero_factura || '—';
          const ref   = p.referencia || '—';
          const obs   = p.observacion || '';
          return `<tr>
            <td>${i + 1}</td>
            <td>${p.fecha_pago}</td>
            <td>${rc}</td>
            <td>${valor}</td>
            <td>${fac}</td>
            <td>${ref}</td>
            <td>${obs}</td>
            <td class="text-center">
              <button type="button"
                      class="btn btn-sm btn-outline-danger btn-del-pago"
                      data-id="${p.id}">
                Eliminar
              </button>
            </td>
          </tr>`;
        }).join('');
      }

      // ---- Previas con saldo / habilitar valor ----
      const saldoActual = parseMoneyFromText(fSaldoTxt?.value);
      const previas = Array.isArray(data.previas_pendientes) ? data.previas_pendientes : [];

      if (previas.length > 0) {
        previasBody.innerHTML = previas.map(p => {
          return `<tr>
            <td class="text-center">${p.numero}</td>
            <td>${p.vence}</td>
            <td>${formatCOP(p.saldo)}</td>
          </tr>`;
        }).join('');

        const sumaPrevias = previas.reduce((acc, it) => acc + Number(it.saldo || 0), 0);
        const capacidadTotal = saldoActual + sumaPrevias;

        fValorPay.disabled = false;
        fValorPay.max = ''; // sin tope en auto
        fAyuda.textContent = `Puedes pagar hasta ${formatCOP(capacidadTotal)} si eliges distribución automática.`;

        previasWrap.classList.remove('d-none');
      } else {
        fValorPay.disabled = (saldoActual <= 0);
        fValorPay.max = saldoActual || '';
        fAyuda.textContent = saldoActual > 0 ? `Saldo máximo: ${formatCOP(saldoActual)}` : 'No hay saldo pendiente.';

        previasWrap.classList.add('d-none');
        previasBody.innerHTML = '';
      }

    } catch (err) {
      console.error(err);
      renderHistorialError(err.message);
    }
  }

  // =========================
  // Abrir modal
  // =========================
  document.querySelectorAll('.btn-aplicar-pago').forEach(btn => {
    btn.addEventListener('click', () => {
      cargarMedios();
      const cuotaId    = btn.dataset.cuota;
      const cuotaNum   = btn.dataset.cuotaNum || '';
      const estudiante = btn.dataset.estudiante || '';
      const acudiente  = btn.dataset.acudiente || '';
      const nivel      = btn.dataset.nivel || '';
      const horario    = btn.dataset.horario || '';
      const vence      = btn.dataset.vence || '';
      const valor      = Number(btn.dataset.valor || 0);
      const pagado     = Number(btn.dataset.pagado || 0);
      const saldo      = Math.max(0, valor - pagado);

      fCuotaId.value = cuotaId || '';
      if (fCuotaNum) fCuotaNum.textContent = cuotaNum ? `#${cuotaNum}` : '';

      fEst.value   = estudiante;
      fAcu.value   = acudiente;
      fNivel.value = nivel;
      fHora.value  = horario;
      fVence.value = vence;

      fValorTxt.value  = formatCOP(valor);
      fPagadoTxt.value = pagado ? formatCOP(pagado) : '—';
      fSaldoTxt.value  = formatCOP(saldo);

      fFecha.value = fFecha.value || HOY_DEFAULT;
      if (fForma) fForma.value = '';
      fFactura.value = '';
      fReferencia.value = '';

      fValorPay.value = saldo > 0 ? saldo : '';
      fValorPay.max   = saldo || '';
      fAyuda.textContent = saldo > 0 ? `Saldo máximo: ${formatCOP(saldo)}` : 'No hay saldo pendiente.';

      if (fModo) fModo.value = '';
      previasWrap.classList.add('d-none');
      previasBody.innerHTML = '';

      if (!cuotaId) {
        alert('No se encontró el ID de la cuota.');
        return;
      }

      cargarHistorial(cuotaId);
      modal.show();
    });
  });

  // =========================
  // Auto-distribución
  // =========================
  if (btnAuto) {
    btnAuto.addEventListener('click', () => {
      if (fModo) fModo.value = 'auto';
      form.requestSubmit();
    });
  }

  // =========================
  // Eliminar pago por fila
  // =========================
  tbodyHist.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.btn-del-pago');
    if (!btn) return;

    const pagoId = btn.dataset.id;
    if (!pagoId) return;

    if (!confirm('¿Eliminar este pago? Esta acción no se puede deshacer.')) return;

    const csrf = form.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
    const fd = new FormData();
    fd.append('pago_id', pagoId);
    fd.append('csrfmiddlewaretoken', csrf);

    const resp = await fetch(URL_ELIMINAR, {
      method: 'POST',
      body: fd,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    });

    const data = await safeJson(resp, 'eliminar_pago');

    if (data.__non_json__ || data.__json_parse_error__) {
      manejarErrorHTTP(resp, data, 'eliminar el pago');
      return;
    }

    if (resp.ok && data.ok) {
      location.reload();
    } else {
      manejarErrorHTTP(resp, data, 'eliminar el pago');
    }
  });

  // =========================
  // Aplicar pago (robusto + diagnóstico)
  // =========================
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (fValorPay.disabled) {
      alert('No hay saldo por pagar en esta cuota.');
      return;
    }

    const btnAplicar =
      document.getElementById('btnAplicarPago') ||
      form.querySelector('button[type="submit"]') ||
      document.querySelector('#modalPago .btn.btn-primary');

    if (btnAplicar) btnAplicar.disabled = true;

    try {
      const resp = await fetch(URL_APLICAR, {
        method: 'POST',
        body: new FormData(form),
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json'
        },
        credentials: 'same-origin'
      });

      const data = await safeJson(resp, 'aplicar_pago');

      if (data.__non_json__ || data.__json_parse_error__) {
        manejarErrorHTTP(resp, data, 'aplicar el pago');
        return;
      }

      if (resp.status === 403) {
        manejarErrorHTTP(resp, data, 'aplicar el pago');
        return;
      }

      if (resp.ok && data.ok) {
        location.reload();
        return;
      }

      manejarErrorHTTP(resp, data, 'aplicar el pago');

    } catch (err) {
      console.error(err);
      alert('Error de red o JS al aplicar el pago. Revisa consola.');
    } finally {
      if (btnAplicar) btnAplicar.disabled = false;
    }
  });

})();