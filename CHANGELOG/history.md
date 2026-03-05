# Cronograma de Cambios

> Nota: las fechas siguen el huso horario del servidor (ART).

## 2025-11-11
- Se migró el servicio de monitoreo original de PowerShell a Python (`src/print_listener.py`) manteniendo la lógica de carpetas `impresos` y `error`.
- Se montó el recurso compartido `/mnt/mkp_print` y se probaron los primeros envíos con prefijos MKP160/MKP161.

## 2025-11-12 (mañana)
- Ajustamos la plantilla `PrinterCommandTemplate` para etiquetas 65x55 mm en `watch_print.ini`.
- Se documentó en `README.md` el uso de tres colas homogéneas y se preparó el renombrado a MKP1/MKP2/MKP3.
- Se renombraron las colas en `/etc/cups/printers.conf` y los PPD correspondientes (Honeywell PC42t 203 dpi) para que compartan driver.

## 2025-11-12 (tarde)
- Se habilitó la administración web autenticada: actualización de `cupsd.conf`, creación del usuario `cupsadmin` dentro de `lpadmin` y reinicio de `cups.service`.
- Se creó este registro en `CHANGELOG/` y se añadieron comentarios de cronograma en los archivos clave para facilitar futuras auditorías.

## 2025-11-13
- Se documentó cómo incorporar la ticketera UNNION TP22 como `FPRINT1` (driver genérico ESC/POS) en `README.md` e `INSTRUCTIVO.md`.
- Se agregó el alias `FPRINT1` en `watch_print.ini` / `.example` para habilitar pruebas desde el servicio automático.

## 2025-11-18
- Se añadió el filtro local `scripts/cups_filters/pdftoescpos_mkp.py` + PPD `drivers/FPRINT1_TP22.ppd` para convertir PDF → ESC/POS sin depender de paquetes externos.
- Nuevo script `scripts/setup_f_print1.sh` ahora instala el filtro, recrea la cola `FPRINT1` y documenta el proceso en README/INSTRUCTIVO.
- Se incorporó soporte para overrides en `[PrinterCommands]` y se ajustó la plantilla de `FPRINT1` al formato 80x3276 mm que se usa en Windows (el filtro también escala ahora a 80 mm, eliminando márgenes sobrantes).

## 2025-11-19
- `src/print_listener.py` ahora acepta múltiples carpetas vigiladas vía `WatchPaths`, mantiene compatibilidad con `WatchPath` y ajusta las colas de procesamiento/movimiento de archivos por directorio. `watch_print.ini`, `.example` y `README.md` documentan el nuevo parámetro (ejemplo `/mnt/mkp_print` + `/mnt/f_print`).
- El dashboard web (`webapp/static/index.html|app.js|styles.css`) se reorganizó en vistas separadas: Dashboard, Servicios, Logs y Configuración, con métricas discriminadas por origen (MKP/FPRINT) y logs divididos en exitosos vs. errores.
- Se habilitó autenticación basada en sesiones firmadas (`/api/auth/login|logout|session`) con una landing page exclusiva (`webapp/static/login.html|login.js`). `/dashboard` requiere sesión activa y las APIs redirigen al login cuando expira la cookie.
- Ajustamos el filtro `scripts/cups_filters/pdftoescpos_mkp.py` para centrar/normalizar los tickets FPRINT: recorte horizontal, escalado fijo a 80 mm y margen configurable (`CONTENT_MARGIN_DOTS`). Tras reinstalar el filtro, FPRINT ya no pierde montos ni se desplaza.
- Se creó `DOCUMENTACION.md` + `scripts/generate_documentacion_pdf.py`, generando `DOCUMENTACION.pdf` con el README completo, el instructivo y un resumen ejecutivo para entregar un único PDF integral.
- Ajustes finos posteriores (noviembre): `pdftoescpos_mkp` se depuró con logs, eliminó el padding lateral y fija el escalado al ancho imprimible real de la TP22 (~72 mm = 576 dots). Así garantizamos que todo el texto/QR entre sin recortes aun cuando el PDF venga a 80 mm; los 640 dots de salida sólo se usan para respetar el protocolo ESC/POS.
