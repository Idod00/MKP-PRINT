#!/usr/bin/env bash
set -euo pipefail

# Script para crear/configurar la cola FPRINT1 (UNNION TP22) en CUPS.
# Uso:
#   sudo bash scripts/setup_f_print1.sh [PRINTER_NAME] [PRINTER_URI]
# Ejemplo:
#   sudo bash scripts/setup_f_print1.sh FPRINT1 socket://10.10.20.181:9100

PRINTER_NAME="${1:-FPRINT1}"
PRINTER_URI="${2:-socket://10.11.2.10:9100}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_PPD_PATH="$(realpath "${SCRIPT_DIR}/../drivers/FPRINT1_TP22.ppd")"
FILTER_SRC="$(realpath "${SCRIPT_DIR}/../scripts/cups_filters/pdftoescpos_mkp.py")"
FILTER_DST="/usr/lib/cups/filter/pdftoescpos-mkp"
DISPLAY_NAME="${PRINTER_NAME} - Ticketera UNNION TP22"

if [[ -f "${LOCAL_PPD_PATH}" ]]; then
  echo "[INFO] Se detectó el PPD local ${LOCAL_PPD_PATH} (filtro pdftoescpos-mkp)."
  MODEL_SPEC=""
  LOCAL_MODEL=1
  if [[ -f "${FILTER_SRC}" ]]; then
    if [[ ! -x "${FILTER_DST}" ]]; then
      echo "[INFO] Instalando filtro en ${FILTER_DST}..."
      install -m 755 "${FILTER_SRC}" "${FILTER_DST}"
    else
      if ! cmp -s "${FILTER_SRC}" "${FILTER_DST}"; then
        echo "[INFO] Actualizando filtro en ${FILTER_DST}..."
        install -m 755 "${FILTER_SRC}" "${FILTER_DST}"
      else
        echo "[INFO] Filtro pdftoescpos-mkp ya actualizado en ${FILTER_DST}."
      fi
    fi
  else
    echo "[WARN] No se encontró el filtro local (${FILTER_SRC}). Asegúrate de instalarlo manualmente."
  fi
else
  echo "[INFO] Buscando driver ESC/POS disponible en el sistema..."
  LPINFO_OUTPUT=$(lpinfo -m 2>/dev/null || true)
  MATCH_LINE=$(printf '%s\n' "${LPINFO_OUTPUT}" | grep -i -E "escpos|tp22|unnion|thermal" | head -n1 || true)
  MODEL=""
  if [[ -n "${MATCH_LINE}" ]]; then
    MODEL=$(awk '{print $1}' <<<"${MATCH_LINE}")
  fi
  if [[ -z "${MODEL}" ]]; then
    MODEL="drv:///sample.drv/escpos.ppd"
    if [[ -z "${LPINFO_OUTPUT}" ]]; then
      echo "[WARN] No se pudo consultar 'lpinfo -m' (¿CUPS restringido?). Se usará fallback: ${MODEL}"
    else
      echo "[WARN] No se encontraron PPD específicos en 'lpinfo -m'. Se usará fallback: ${MODEL}"
    fi
    echo "       Asegúrate de tener instalado 'printer-driver-escpos' u otro paquete compatible."
  else
    echo "[INFO] Se utilizará el modelo '${MODEL}'."
  fi
  MODEL_SPEC="${MODEL}"
  LOCAL_MODEL=0
fi

echo "[INFO] Eliminando cola previa (si existiera)..."
lpadmin -x "${PRINTER_NAME}" 2>/dev/null || true

echo "[INFO] Creando la cola ${PRINTER_NAME} apuntando a ${PRINTER_URI}..."
if [[ "${LOCAL_MODEL}" -eq 1 ]]; then
  lpadmin -p "${PRINTER_NAME}" -E \
    -v "${PRINTER_URI}" \
    -D "${DISPLAY_NAME}" \
    -P "${LOCAL_PPD_PATH}"
else
  lpadmin -p "${PRINTER_NAME}" -E \
    -v "${PRINTER_URI}" \
    -D "${DISPLAY_NAME}" \
    -m "${MODEL_SPEC}"
fi

echo "[INFO] Aplicando opciones predeterminadas (80x3276 mm, densidad media)..."
lpoptions -p "${PRINTER_NAME}" \
  -o media=Custom.80x3276mm \
  -o page-top=0 -o page-bottom=0 \
  -o fit-to-page=true \
  -o print-density=Medium \
  -o print-scaling=100

echo "[INFO] Cola configurada. Estado actual:"
lpstat -p "${PRINTER_NAME}" -l || true

cat <<'EOF'
[INFO] Próximos pasos sugeridos:
  1) Ejecuta una prueba:
       lp -d FPRINT1 -o media=Custom.80x3276mm /ruta/a/ticket_prueba.pdf
  2) Verifica que CUPS rasterice (para QR):
       cupsfilter -p /etc/cups/ppd/FPRINT1.ppd \
         -m application/vnd.cups-raster \
         /ruta/a/ticket_prueba.pdf >/tmp/FPRINT1_test.raster
       file /tmp/FPRINT1_test.raster
  3) Si todo es correcto, agrega/valida 'FPRINT1 = FPRINT1' en watch_print.ini
     y reinicia el listener.
EOF
