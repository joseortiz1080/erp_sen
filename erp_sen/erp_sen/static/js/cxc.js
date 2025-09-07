(function () {
  // ==== Guards básicos para evitar fallos silenciosos ====
  const cfg = document.getElementById('cxc-config');
  if (!cfg) { console.error('cxc-config no encontrado'); return; }

  const URL_APLICAR  = cfg.dataset.aplicarUrl;
  const URL_ELIMINAR = cfg.dataset.eliminarUrl;
  const HOY_DEFAULT  = cfg.dataset.hoy || '';

  if (!URL_APLICAR || !URL_ELIMINAR) {
    console.error('Faltan URLs en cxc-config (aplicar/eliminar).');
    return;
  }

  if (!window.bootstrap || !bootstrap.Modal) {
    console.error('Bootstrap JS (bundle) no está cargado antes de cxc.js.');
    return;
  }

  const modalEl = document.getElementById('modalPago');
  if (!modalEl) { console.error('#modalPago no existe en el DOM'); return; }

  // ==== tu código actual sigue aquí ====
  const modal = new bootstrap.Modal(modalEl);

  // ... (todo el resto de tu cxc.js tal cual lo tienes) ...
})();

(function () {
  // === Lee la config inyectada por el template ===
  const cfg = document.getElementById('cxc-config');
  const URL_APLICAR  = cfg?.dataset.aplicarUrl  || '';
  const URL_ELIMINAR = cfg?.dataset.eliminarUrl || '';
  const HOY_DEFAULT  = cfg?.dataset.hoy || '';

  const modalEl = document.getElementById('modalPago');
  const modal = new bootstrap.Modal(modalEl);

  const form = document.getElementById('pagoForm');
  const fCuotaId   = document.getElementById('mp-cuota-id');
  const fCuotaNum  = document.getElementById('mp-cuota-num');
  const fEst       = document.getElementById('mp-estudiante');
  const fAcu       = document.getElementById('mp-acudiente');
  const fNivel     = document.getElementById('mp-nivel');
  const fHora      = document.getElementById('mp-horario');
  const fVence     = document.getElementById('mp-vence');
  const fValorTxt  = document.getElementById('mp-valor');
  const fPagadoTxt = document.getElementById('mp-pagado');
  const fSaldoTxt  = document.getElementById('mp-saldo');
  const fFecha     = document.getElementById('mp-fecha');
  const fForma     = document.getElementById('mp-forma');
  const fFactura   = document.getElementById('mp-factura');
  const fReferencia= document.getElementById('mp-referencia');
  const fValorPay  = document.getElementById('mp-valor-pagar');
  const fAyuda     = document.getElementById('mp-ayuda');
  const tbodyHist  = document.getElementById('mp-historial-body');

  const fModo       = document.getElementById('mp-modo');
  const btnAuto     = document.getElementById('mp-btn-auto');
  const previasWrap = document.getElementById('mp-previas-wrap');
  const previasBody = document.getElementById('mp-previas-body');

  function formatCOP(n) {
    n = Number(n || 0);
    return '$ ' + n.toLocaleString('es-CO');
  }

  async function cargarHistorial(cuotaId) {
    tbodyHist.innerHTML = '<tr><td colspan="8" class="text-muted">Cargando…</td></tr>';
    try {
      const resp = await fetch(URL_APLICAR + '?cuota_id=' + encodeURIComponent(cuotaId), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || 'No se pudo obtener el historial.');

      if (!data.pagos || data.pagos.length === 0) {
        tbodyHist.innerHTML = '<tr><td colspan="8" class="text-muted">Sin pagos.</td></tr>';
      } else {
        tbodyHist.innerHTML = data.pagos.map((p, i) => {
          const valor = formatCOP(p.valor_pagado);
          const medio = p.forma_pago || '—';
          const fac   = p.numero_factura || '—';
          const ref   = p.referencia || '—';
          const obs   = p.observacion || '';
          return `<tr>
            <td>${i + 1}</td>
            <td>${p.fecha_pago}</td>
            <td>${valor}</td>
            <td>${medio}</td>
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
      const saldoActual = Number((fSaldoTxt.value || '0').replace(/[^0-9]/g, '')) || 0;
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

        // HABILITAR input de valor para distribuir
        fValorPay.disabled = false;
        fValorPay.max = '';
        fAyuda.textContent = `Puedes pagar hasta ${formatCOP(capacidadTotal)} si eliges distribución automática.`;
        previasWrap.classList.remove('d-none');
      } else {
        // Si no hay previas, habilitar sólo si hay saldo en la actual
        fValorPay.disabled = (saldoActual <= 0);
        fValorPay.max = saldoActual || '';
        fAyuda.textContent = saldoActual > 0 ? `Saldo máximo: ${formatCOP(saldoActual)}` : 'No hay saldo pendiente.';
        previasWrap.classList.add('d-none');
        previasBody.innerHTML = '';
      }

    } catch (err) {
      tbodyHist.innerHTML = `<tr><td colspan="8" class="text-danger">${err.message}</td></tr>`;
      previasWrap.classList.add('d-none');
      previasBody.innerHTML = '';
    }
  }

  // Abrir modal
  document.querySelectorAll('.btn-aplicar-pago').forEach(btn => {
    btn.addEventListener('click', () => {
      const cuotaId   = btn.dataset.cuota;
      const cuotaNum  = btn.dataset.cuotaNum || '';
      const estudiante= btn.dataset.estudiante;
      const acudiente = btn.dataset.acudiente;
      const nivel     = btn.dataset.nivel;
      const horario   = btn.dataset.horario;
      const vence     = btn.dataset.vence;
      const valor     = Number(btn.dataset.valor || 0);
      const pagado    = Number(btn.dataset.pagado || 0);
      const saldo     = Math.max(0, valor - pagado);

      fCuotaId.value   = cuotaId;
      fCuotaNum.textContent = cuotaNum ? `#${cuotaNum}` : '';
      fEst.value       = estudiante;
      fAcu.value       = acudiente;
      fNivel.value     = nivel;
      fHora.value      = horario;
      fVence.value     = vence;
      fValorTxt.value  = formatCOP(valor);
      fPagadoTxt.value = pagado ? formatCOP(pagado) : '—';
      fSaldoTxt.value  = formatCOP(saldo);
      fFecha.value     = fFecha.value || HOY_DEFAULT;
      fForma.value     = 'Banco';
      fFactura.value   = '';
      fReferencia.value= '';
      fValorPay.value  = saldo > 0 ? saldo : '';
      fValorPay.max    = saldo || '';
      // no deshabilitar aquí; se gestiona en cargarHistorial()
      fAyuda.textContent = saldo > 0 ? `Saldo máximo: ${formatCOP(saldo)}` : 'No hay saldo pendiente.';

      fModo.value = '';
      previasWrap.classList.add('d-none');
      previasBody.innerHTML = '';

      cargarHistorial(cuotaId);
      modal.show();
    });
  });

  // Auto-distribución
  if (btnAuto) {
    btnAuto.addEventListener('click', () => {
      fModo.value = 'auto';
      form.requestSubmit();
    });
  }

  // Eliminar pago por fila
  tbodyHist.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.btn-del-pago');
    if (!btn) return;
    const pagoId = btn.dataset.id;
    if (!pagoId) return;
    if (!confirm('¿Eliminar este pago? Esta acción no se puede deshacer.')) return;

    const fd = new FormData();
    fd.append('pago_id', pagoId);
    fd.append('csrfmiddlewaretoken', form.querySelector('input[name=csrfmiddlewaretoken]').value);

    const resp = await fetch(URL_ELIMINAR, {
      method: 'POST',
      body: fd,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { data = { ok: false, error: 'Respuesta inválida' }; }

    if (resp.ok && data.ok) {
      location.reload();
    } else {
      alert(data.error || 'No se pudo eliminar el pago.');
    }
  });

  // Aplicar pago
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (fValorPay.disabled) {
      alert('No hay saldo por pagar en esta cuota.');
      return;
    }

    const fd = new FormData(form);
    const resp = await fetch(URL_APLICAR, {
      method: 'POST',
      body: fd,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { data = { ok: false, error: 'Respuesta inválida' }; }

    if (resp.ok && data.ok) {
      location.reload();
      return;
    }

    const code = data.error_code || '';
    if (code === 'previas_pendientes') {
      if (Array.isArray(data.previas) && data.previas.length) {
        previasBody.innerHTML = data.previas.map(p => {
          return `<tr>
            <td class="text-center">${p.numero}</td>
            <td>${p.vence}</td>
            <td>${formatCOP(p.saldo)}</td>
          </tr>`;
        }).join('');
        previasWrap.classList.remove('d-none');
      }
      if (confirm('Hay cuotas anteriores con saldo. ¿Deseas distribuir automáticamente este pago priorizando las anteriores?')) {
        fModo.value = 'auto';
        form.requestSubmit();
        return;
      }
    } else if (code === 'supera_capacidad') {
      alert(`${data.error}\n\nCapacidad total permitida: ${formatCOP(data.capacidad_total)}`);
      return;
    }

    alert(data.error || 'No se pudo aplicar el pago.');
  });
})();
