document.addEventListener('DOMContentLoaded', function () {
  // ====== BUSCAR ACUDIENTE (ya lo tenías) ======
  const buscarBtn = document.getElementById("btn-buscar-acudiente");
  const inputCedula = document.getElementById("buscar_cedula");
  const msg = document.getElementById("acudiente-msg");

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
            // Llenar campos del formulario
            document.querySelector("#id_acudiente-nombre_completo").value = data.nombre_completo || "";
            document.querySelector("#id_acudiente-documento").value = cedula;
            document.querySelector("#id_acudiente-telefono").value = data.telefono || "";
            document.querySelector("#id_acudiente-email").value = data.email || "";

            // Select tipo_documento
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
  // IDs por defecto de Django (sin prefijo): id_valor_total, id_numero_cuotas, id_valor_cuota_pactada
  const $total   = document.getElementById('id_valor_total');
  const $cuotas  = document.getElementById('id_numero_cuotas');
  const $pactada = document.getElementById('id_valor_cuota_pactada');

  // Marcar como solo lectura y con estilo visual suave
  if ($pactada) {
    $pactada.readOnly = true;                // sigue enviándose al servidor
    $pactada.classList.add('bg-light');      // opcional: efecto visual
  }

  function toNumber(x) {
    if (x == null) return 0;
    // Acepta 1.234,56 o 1234.56
    const s = String(x).replace(/[^0-9.,]/g, '').replace(',', '.');
    const n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  function recalcCuota() {
    if (!$total || !$cuotas || !$pactada) return;
    const total  = toNumber($total.value);
    const n      = parseInt($cuotas.value || '0', 10);
    const cuota  = (total > 0 && n > 0) ? (total / n) : 0;
    $pactada.value = cuota ? cuota.toFixed(2) : '';
  }

  if ($total)  $total.addEventListener('input',  recalcCuota);
  if ($cuotas) $cuotas.addEventListener('change', recalcCuota);

  // cálculo inicial por si hay datos precargados
  recalcCuota();
});
