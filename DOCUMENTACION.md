# Documentación Integral MKP

## Resumen ejecutivo
Este documento consolida la información operativa del proyecto MKP para Linux: servicio de escucha de carpetas, panel web con autenticación, integración con CUPS y el instructivo detallado que veníamos manteniendo. Incluye requisitos, despliegue, mantenimiento y planes de contingencia para las impresoras Honeywell MKP y la ticketera UNNION TP22 (FPRINT1).

### Qué resuelve
- Vigila múltiples carpetas compartidas (`WatchPaths`) y enruta automáticamente cada PDF según el prefijo del archivo.
- Provee un panel web (puerto 900) con autenticación por sesiones, dashboard, monitoreo de servicios, logs y acciones de mantenimiento.
- Expone APIs y scripts para clonar colas CUPS, reiniciar servicios y diagnosticar impresoras.
- Incluye filtros personalizados (PDF→ESC/POS) para garantizar que FPRINT imprima centrado y sin truncar montos.

### Componentes principales
1. `src/print_listener.py`: servicio principal gestionado por watchdog + colas internas.
2. `webapp/`: panel operativo (FastAPI + frontend estático) con autenticación.
3. `scripts/cups_filters/pdftoescpos_mkp.py`: filtro utilizado por CUPS para convertir tickets a ESC/POS.
4. `scripts/setup_f_print1.sh`: automatiza la creación/actualización de la cola FPRINT1.
5. `watch_print.ini`: configuración central del listener, ahora con soporte multi-ruta.

A continuación se incluyen el README completo como referencia general y el instructivo detallado actualizado.

---

## Referencia general (README)

# Servicio de Monitoreo de Impresión (Linux)

Este proyecto recrea en Linux el servicio que tenías en PowerShell/Windows para escuchar una carpeta compartida (`\\10.0.0.96\mkp_print`), detectar nuevos PDF y enviarlos automáticamente a la impresora indicada en el nombre del archivo (`IMPRESORA_documento.pdf`). Los archivos exitosos se mueven a `Printed` y los fallidos a `Error`, manteniendo un registro detallado en `logs/listener/`.

## Requisitos

- Python 3.10+
- Dependencias del sistema para montar la carpeta compartida (por ejemplo, `cifs-utils` si es SMB/CIFS).
- Acceso a los comandos de impresión del sistema (por ejemplo, `lp` / `lpr` de CUPS).

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración

1. **Montar la carpeta compartida** (una vez por arranque del servidor Linux):

   ```bash
   sudo mkdir -p /mnt/mkp_print
   sudo mount -t cifs //10.0.0.96/mkp_print /mnt/mkp_print \
        -o username=INET\\lazkar,password='<REEMPLAZAR_PASSWORD>',iocharset=utf8,vers=3.0
   ```

   > Esas credenciales son las mismas que usas en Windows. Cámbialas si decides usar otro usuario o si guardas credenciales en un archivo de opciones (ej. `credentials=/root/.mkp_smb`). También puedes crear una entrada en `/etc/fstab` para que el montaje sea persistente.

2. **Configurar el servicio**:

   ```bash
   cp watch_print.ini.example watch_print.ini
   nano watch_print.ini
   ```

   Principales parámetros en `[General]`:

   - `WatchPaths`: rutas montadas que se vigilarán (separadas por coma o por líneas nuevas). Ejemplo: `/mnt/mkp_print, /mnt/f_print`. Si solo necesitas una carpeta todavía puedes usar `WatchPath`.
   - `PrintedFolderName` / `ErrorFolderName`: subcarpetas dentro del share.
   - `UsePollingObserver`: ponlo en `true` cuando la carpeta sea un share SMB/CIFS; así el servicio usa un `PollingObserver` y detecta archivos nuevos aunque el FS no emita eventos.
   - `PrinterCommandTemplate`: comando usado para imprimir. Usa `{file}` y `{printer}` como marcadores; puedes añadir opciones `lp -o media=Custom.90x70mm -o orientation-requested=4 -o landscape -o print-scaling=fill` para forzar tamaño/orientación por trabajo. Si necesitas comandos distintos por cola (por ejemplo, otro tamaño de etiqueta), define una sección `[PrinterCommands]` y declara overrides por nombre (`FPRINT1 = lp -d "{printer}" ...`); las colas que no tengan override usarán la plantilla general.
   - `PrintTimeoutSeconds`, `FileReadyRetries`, `EventDebounceMs`: afinan tiempos de espera y reintentos.

   Puedes declarar tantas carpetas montadas como necesites. Por ejemplo, si agregas una segunda carpeta `/mnt/f_print` donde se depositan archivos con prefijo `FPRINT`, basta con añadirla en `WatchPaths` y los archivos detectados se procesarán igual que los de `/mnt/mkp_print`.

   Puedes mapear prefijos de archivo a colas de CUPS usando la sección `[Printers]`. Ejemplo:

   ```ini
   [Printers]
   MKP1 = MKP1
   MKP2 = MKP2
   MKP3 = MKP3  # Cada prefijo apunta a su propia cola MKP
   ```

Con esto, cada archivo `MKP{1..3}_algo.pdf` se envía a la cola `MKP{1..3}` de CUPS y los tres comparten la misma configuración/driver.

### Configurar las colas MKP1, MKP2 y MKP3 en CUPS

1. Instala el driver Honeywell provisto en `CUPS_1.6` (o asegúrate de tener disponible el PPD apropiado) ejecutando `sudo ./build.sh` dentro de esa carpeta. Esto deja los PPD en `/usr/share/cups/model/`.
2. Elimina las colas antiguas si aún existen:

   ```bash
   sudo lpadmin -x MKP160 2>/dev/null || true
   sudo lpadmin -x MKP161 2>/dev/null || true
   ```

3. Crea las colas nuevas reutilizando el mismo PPD para las tres. Sustituye `socket://IMPRESORA` por la URI real (USB, serial, etc.) que tengas conectada a cada impresora:

   ```bash
   sudo lpadmin -p MKP1 -E -v socket://MKP1_IP -D "MKP1" -m honeywell-dp-pm45-300.ppd
   sudo lpadmin -p MKP2 -E -v socket://MKP2_IP -D "MKP2" -m honeywell-dp-pm45-300.ppd
   sudo lpadmin -p MKP3 -E -v socket://MKP3_IP -D "MKP3" -m honeywell-dp-pm45-300.ppd
   ```

   Las tres colas apuntan al mismo driver (`honeywell-dp-pm45-300.ppd` en el ejemplo), por lo que tendrán idéntica calibración y opciones predeterminadas.

4. Ajusta las opciones comunes que necesites una sola vez y replícalas:

   ```bash
   sudo lpoptions -p MKP1 -o media=Custom.65x55mm -o fit-to-page=true -o print-scaling=100
   sudo lpoptions -p MKP2 -o media=Custom.65x55mm -o fit-to-page=true -o print-scaling=100
   sudo lpoptions -p MKP3 -o media=Custom.65x55mm -o fit-to-page=true -o print-scaling=100
   ```

5. Verifica que las tres colas estén activas y aceptando trabajos:

   ```bash
  lpstat -p MKP1 MKP2 MKP3
   ```

   Una vez que las colas existen con los nuevos nombres y comparten driver, el servicio `print_listener.py` podrá enrutar trabajos automáticamente usando los prefijos `MKP1`, `MKP2` y `MKP3`.

### Agregar la ticketera UNNION TP22 (`FPRINT1`)

1. **Reúne los datos del equipo** visitando `http://10.10.20.181/`. La TP22 reporta: puerto RAW 9100, ancho útil 72 mm, `Command Set = ESC/POS`, `AutoCut = Yes`, densidad media y soporte de imágenes (facturas en PDF con QR). Anota esos parámetros porque determinan el PPD y las opciones por defecto.
2. **Instala las dependencias del filtro local**. Este repo incluye un filtro CUPS (`scripts/cups_filters/pdftoescpos_mkp.py`) y un PPD (`drivers/FPRINT1_TP22.ppd`) que rasterizan los PDF a 203 dpi y los convierten a ESC/POS. Solo necesitas los paquetes base:

   ```bash
   sudo apt install poppler-utils python3-pil
   ```

   > `pdftoppm` (de poppler-utils) genera PNGs temporales y `python3-pil` aplica el umbral, escala y emite los comandos `GS v 0`.

3. **Crea la cola en CUPS** reapuntándola al host `10.10.20.181`. El script `scripts/setup_f_print1.sh` copia automáticamente el filtro a `/usr/lib/cups/filter/pdftoescpos-mkp`, registra el PPD local y deja la cola lista con el ancho de 80 mm:

   ```bash
   sudo bash scripts/setup_f_print1.sh
   ```

   Ajusta el tamaño `Custom.80x3276mm` y los márgenes a las dimensiones reales de la bobina (58 mm → `Custom.58x200mm`, por ejemplo). La altura extendida replica la plantilla que usas en Windows para facturas largas.

4. **Mapea el prefijo** agregando (o verificando) la línea `FPRINT1 = FPRINT1` en la sección `[Printers]` de `watch_print.ini` / `watch_print.ini.example`. Desde ahora cualquier archivo `FPRINT1_algo.pdf` que llegue al share se encolará en la TP22. Como ya no hay guion bajo en el nombre, el listener tomará correctamente `FPRINT1` como prefijo incluso cuando el resto del nombre empiece inmediatamente después.
5. **Declara la plantilla específica** en `[PrinterCommands]` para no tocar la opción global de MKP. Ejemplo:

   ```ini
   [PrinterCommands]
   FPRINT1 = lp -d "{printer}" -o media=Custom.80x3276mm -o page-top=0 -o page-bottom=0 -o fit-to-page=true -o print-scaling=100 "{file}"
   ```

   El listener aplicará esta plantilla solo cuando detecte `FPRINT1`; las colas MKP seguirán usando el `PrinterCommandTemplate` general (`Custom.65x55mm`).
6. **Prueba la cola** con un PDF pequeño que tenga texto + código QR:

   ```bash
   lp -d FPRINT1 -o media=Custom.80x3276mm /ruta/a/ticket_prueba.pdf
   lpstat -p FPRINT1 -l
   ```

   Si el ticket sale truncado o descentrado, modifica el `PrinterCommandTemplate` del INI para esa impresora (`-o media`, `-o fit-to-page`, `-o scaling`) y vuelve a lanzar `print_listener.py`. Para validar que los QR se rasterizan correctamente, puedes ejecutar:

   ```bash
   cupsfilter -p /etc/cups/ppd/FPRINT1.ppd \
     -m application/vnd.cups-raster \
     /ruta/a/ticket_prueba.pdf >/tmp/FPRINT1_test.raster
   file /tmp/FPRINT1_test.raster
   ```

   El archivo temporal debería identificarse como `CUPS Raster`. Eso confirma que el PDF se convierte a bitmap antes de enviarse por ESC/POS, garantizando que los QR lleguen completos a la impresora.

   Para probar únicamente el filtro sin enviar nada a red, puedes ejecutar:

   ```bash
   scripts/cups_filters/pdftoescpos_mkp.py 99 tester demo 1 "" /ruta/a/ticket_prueba.pdf >/tmp/FPRINT1_demo.escpos
   hexdump -C /tmp/FPRINT1_demo.escpos | head
   ```

   El archivo `.escpos` resultante contiene los comandos `GS v 0`; puedes inspeccionarlo o enviarlo con `nc 10.10.20.181 9100 < /tmp/FPRINT1_demo.escpos`.

#### Script rápido para crear la cola

El script realiza todo lo necesario (instala/actualiza el filtro, copia el PPD local e invoca `lpadmin`). Úsalo como root:

```bash
sudo bash scripts/setup_f_print1.sh                     # usa socket://10.10.20.181:9100 por defecto
sudo bash scripts/setup_f_print1.sh FPRINT1 socket://10.10.20.181:9100  # URI personalizado
```

Después de ejecutarlo:

1. Confirma que `/usr/lib/cups/filter/pdftoescpos-mkp` exista y tenga permisos 755.
2. Verifica el estado de la cola: `lpstat -p FPRINT1 -l` (usa `sudo` si el entorno restringe DBus).
3. Revisa que `watch_print.ini` contenga `FPRINT1 = FPRINT1` y reinicia el listener.

### Cronograma de cambios

- Consulta `CHANGELOG/history.md` para un registro cronológico (2025-11-11 al 2025-11-12) de la migración del servicio, el renombrado de colas y la activación del acceso administrativo por web.
- Archivos críticos (`watch_print.ini`, `watch_print.ini.example`, `src/print_listener.py`) incluyen comentarios breves con los hitos más relevantes para facilitar la auditoría interna.

## Ejecución

```bash
python src/print_listener.py --config watch_print.ini
```

El servicio arrancará un `watchdog` que escucha los eventos del sistema de archivos. Cada vez que llega un PDF:

1. Espera unos milisegundos para asegurar que el archivo terminó de copiar.
2. Verifica que el archivo no esté bloqueado.
3. Calcula la impresora desde el prefijo del nombre y ejecuta el comando configurado (`lp`, `lpr`, o el que prefieras).
4. Mueve el archivo a `Printed` (renombrándolo si hay colisión) o a `Error` si hubo problemas.

Los logs quedan en `logs/listener/print_service_YYYY-MM-DD.log` (también se imprime en consola).

## Ejecución como servicio systemd (opcional)

Ejemplo de unidad (`/etc/systemd/system/print-listener.service`):

```ini
[Unit]
Description=Print Listener Service
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/ruta/a/MKP
ExecStart=/ruta/a/MKP/.venv/bin/python /ruta/a/MKP/src/print_listener.py --config /ruta/a/MKP/watch_print.ini
Restart=on-failure
User=tu_usuario

[Install]
WantedBy=multi-user.target
```

Luego:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now print-listener.service
```

## Personalización

- Si prefieres otro ejecutable (por ejemplo `PDFtoPrinter.exe` vía Wine o un script propio), solo cambia `PrinterCommandTemplate`.
- Puedes ampliar el script para soportar subcarpetas, múltiples extensiones o colas de impresión específicas modificando `src/print_listener.py`.

## Panel web de administración

El directorio `webapp/` incluye una mini aplicación FastAPI para consultar el estado del listener, revisar CUPS, clonar impresoras y leer los logs diarios desde un navegador.

### Requisitos

```bash
pip install -r requirements.txt
```

### Ejecución del panel

```bash
uvicorn webapp.app:app --host 0.0.0.0 --port 9000 --reload
```

Funciones principales del panel:

1. Tablero con el estado de `print-listener.service` y `cups.service`, con botones para reiniciar cada uno.
2. Listado de impresoras reportadas por `lpstat -p -l` y mapeo del bloque `[Printers]` del INI.
3. Formulario para clonar una impresora existente (mismo PPD y opciones clave) y opcionalmente agregarla a `watch_print.ini`.
4. Visor del log diario (`logs/listener/print_service_YYYY-MM-DD.log`) con actualización rápida.

> Ejecuta el panel como un usuario con permisos para llamar a `systemctl`, `lpadmin` y modificar `watch_print.ini` (generalmente root o un usuario del grupo `lpadmin`).

#### Autenticación básica

El panel utiliza HTTP Basic. Define las credenciales con las variables:

- `MKP_BASIC_USER`: usuario de acceso (ej. `panel`).
- `MKP_BASIC_PASSWORD_HASH`: secreto PBKDF2 en formato `iteraciones:salt_hex:hash_hex`.
- `MKP_BASIC_PBKDF_ITER`: iteraciones (default `600000`).

Puedes generar el hash manualmente:

```bash
python3 - <<'PY'
import hashlib, secrets
password = input('Contraseña: ')
iterations = 600000
salt = secrets.token_hex(16)
dk = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), iterations)
print(f"{iterations}:{salt}:{dk.hex()}")
PY
```

Exporta esos valores antes de iniciar `uvicorn` o confíalos mediante el script de instalación.

### Script de instalación automatizada

Para configurar todo con el usuario `sysadmin` (dependencias, ACLs, sudoers y servicio systemd) ejecuta como root:

```bash
bash scripts/setup_panel.sh sysadmin 9000 panel SuperSecreto123
```

El script instala las dependencias en `.venv`, otorga permisos mínimos mediante ACLs, crea `/etc/sudoers.d/mkp-panel`, genera automáticamente un secreto PBKDF2 para la autenticación básica, registra la unidad `mkp-panel.service` y la deja levantada en el puerto indicado. Si omites la contraseña se solicitará de forma interactiva.

## Verificación manual

1. Copia un PDF con formato `NOMBREIMPRESORA_algo.pdf` en la carpeta vigilada.
2. Observa la consola o el log diario para confirmar el procesamiento.
3. Comprueba que el archivo termine en la carpeta `Printed` (o `Error` si algo salió mal).

Con esto tendrás el mismo flujo de trabajo que en Windows pero adaptado a tu entorno Linux. ¡Listo! Ajusta los parámetros según el rendimiento/latencia de tu red y la cantidad de impresoras que manejes.

---

## Instructivo operativo (detalle)

# Instructivo Operativo MKP

Este documento resume los pasos para revisar el estado general del sistema de impresión MKP, diagnosticar errores frecuentes y administrar las colas CUPS (agregar/eliminar impresoras).

## 1. Estado general del proyecto

```bash
cd /root/MKP
ls -1
```

Salida esperada:
```text
BKP
CHANGELOG
CUPS_1.6
INSTRUCTIVO.md
INSTRUCTIVO.pdf
logs
README.md
requirements.txt
src
watch_print.ini
```

Carpetas clave:
- `src/print_listener.py`: servicio que detecta y envía los PDF.
- `watch_print.ini`: configuración activa del servicio (rutas, comandos, mapeo de impresoras).
- `CHANGELOG/` e `INSTRUCTIVO.md`: documentación viva.

## 2. Verificar el servicio de escucha de PDFs

### Ejecución manual
```bash
cd /root/MKP
python3 src/print_listener.py --config watch_print.ini
```

Salida esperada (fragmento):
```text
[2025-11-12 11:30:05] [INFO] Observando /mnt/mkp_print con PollingObserver
[2025-11-12 11:30:05] [INFO] Esperando archivos PDF con prefijos MKP1/MKP2/MKP3
```

El servicio escribe logs en `logs/listener/print_service_YYYY-MM-DD.log`.

### Como servicio systemd
Si se instaló como unidad (`print-listener.service`):
```bash
sudo systemctl status print-listener.service
sudo journalctl -u print-listener.service -f
```

Salida esperada (status):
```text
● print-listener.service - Print Listener Service
     Loaded: loaded (/etc/systemd/system/print-listener.service; enabled)
     Active: active (running) since Wed 2025-11-12 11:32:18 -03
   Main PID: 1820 (python3)
```

Para reiniciar tras cambios en la configuración:
```bash
sudo systemctl restart print-listener.service
```

Salida esperada:
```text
Job for print-listener.service restarted.
```

## 3. Verificar CUPS y las colas MKP

```bash
sudo systemctl status cups
lpstat -p MKP1 MKP2 MKP3
```

Salida esperada:
```text
● cups.service - CUPS Scheduler
     Active: active (running) since Wed 2025-11-12 12:22:38 -03

printer MKP1 is idle.  enabled since Tue Nov 11 15:46:20 2025
printer MKP2 is idle.  enabled since Tue Nov 11 17:25:37 2025
printer MKP3 is idle.  enabled since Wed Nov 12 10:40:15 2025
```

Logs CUPS:
```bash
tail -n 50 /var/log/cups/error_log
journalctl -u cups -f
```

Salida esperada (error_log):
```text
E [12/Nov/2025:10:21:31 -0300] [Client 88] Unable to encrypt connection: A TLS fatal alert has been received.
W [12/Nov/2025:10:29:05 -0300] Printer drivers are deprecated and will stop working in a future version of CUPS.
```

## 4. Revisar errores del sistema

1. **Servicio Python**: revisar `logs/listener/` (traza detallada por archivo procesado).
2. **CUPS**: `tail -f /var/log/cups/error_log` para mensajes de driver/conexión.
3. **Red/montaje**: verificar que `/mnt/mkp_print` esté montado y accesible.
4. **Permisos web**: usa el usuario `cupsadmin` (grupo `lpadmin`) para autenticación en `https://<servidor>:631/admin`.

## 5. Agregar una impresora nueva en CUPS

1. Identifica la URI (ej. `socket://10.10.20.160`).
2. Selecciona el PPD/driver (actualmente Honeywell PC42t 203 dpi en `/etc/cups/ppd`).
3. Ejecuta:
   ```bash
   sudo lpadmin -p MKP4 -E \
     -v socket://10.10.20.164 \
     -D "MKP4" \
     -m honeywell-dp-pc42t-203.ppd
   sudo lpoptions -p MKP4 -o media=Custom.65x55mm -o fit-to-page=true -o print-scaling=100
   ```

   Salida esperada (lpadmin):
   ```text
   lpadmin: Printer exists and will be replaced.
   ```

4. Añade el alias en `watch_print.ini` si deseas imprimir con un nuevo prefijo:
   ```ini
   [Printers]
   MKP4 = MKP4
   ```
5. Reinicia el servicio de escucha o recarga la configuración (`Ctrl+C` y volver a ejecutar) para que lea el nuevo mapeo.

### 5.1 Clonar la configuración de una impresora existente

Cuando la nueva impresora debe comportarse igual que una cola ya configurada, clona sus parámetros para ahorrar tiempo.

1. **Toma nota del origen y destino**. Ejemplo: clonar `MKP2` para crear `MKP4` apuntando al host `10.10.20.164`.
2. **Exporta las opciones actuales** del origen (sirve como checklist):
   ```bash
   sudo lpoptions -p MKP2
   ```
   Salida típica:
   ```text
   copies=1 device-uri=socket://10.10.20.162 finishings=3 media=Custom.65x55mm print-scaling=100 sides=one-sided
   ```
3. **Crea la nueva cola reutilizando el mismo PPD**:
   ```bash
   sudo lpadmin -p MKP4 -E \
     -v socket://10.10.20.164 \
     -D "MKP4" \
     -P /etc/cups/ppd/MKP2.ppd
   ```
   Salida esperada:
   ```text
   lpadmin: Printer added successfully.
   ```
   > Si `lpadmin` indica que la impresora ya existía, usa `-R` o elimina primero `MKP4` con `lpadmin -x`.
4. **Replica las opciones relevantes** (las mismas que viste en el paso 2):
   ```bash
   sudo lpoptions -p MKP4 -o media=Custom.65x55mm -o print-scaling=100 -o fit-to-page=true
   ```
   (sin salida si se aplicó correctamente)
5. **Verifica que ambas colas coincidan**:
   ```bash
   lpstat -p MKP2 MKP4 -l
   ```
   Fragmento esperado para `MKP4`:
   ```text
   printer MKP4 is idle.  enabled since Wed Nov 13 09:12:04 2025
        Connection: socket://10.10.20.164
        Form mounted: Custom.65x55mm
   ```
6. **Actualiza `watch_print.ini`** agregando el nuevo alias para que el listener pueda enrutar los PDFs:
   ```ini
   [Printers]
   MKP1 = MKP1
   MKP2 = MKP2
   MKP3 = MKP3
   MKP4 = MKP4
   ```
7. **Reinicia el servicio `print-listener`** (o vuelve a lanzarlo manualmente) para cargar el cambio y ejecutar una prueba `MKP4_demo.pdf`.

### 5.2 Ticketera UNNION TP22 como `FPRINT1`

1. Ingresa al panel web de la impresora (`http://10.10.20.181/`) y confirma los parámetros. La TP22 de fábrica indica: puerto RAW 9100, `PrintWidth = 72 mm`, `Command Set = ESC/POS`, `AutoCut = Yes`, `PrintDensity = Medium`, QR soportado (al aceptar PDF completos). Guarda esos valores; son los que vas a replicar en CUPS.
2. Instala las dependencias que usa el filtro local para rasterizar:
   ```bash
   sudo apt install poppler-utils python3-pil
   ```
   Esto habilita `pdftoppm` + Pillow para el filtro `scripts/cups_filters/pdftoescpos_mkp.py` (PDF → PNG → ESC/POS).
3. Ejecuta el asistente y deja que copie el filtro a `/usr/lib/cups/filter/pdftoescpos-mkp`, registre el PPD y cree la cola (ancho lógico 80 mm como en Windows):
   ```bash
   sudo bash scripts/setup_f_print1.sh
   ```
   Si necesitas otro ancho (58 mm, por ejemplo), corre `lpoptions -p FPRINT1 -o media=Custom.58x200mm`.
4. Edita el bloque `[Printers]` del INI para incluir `FPRINT1 = FPRINT1`. Ya está presente en `watch_print.ini.example` como referencia.
5. Añade la sección `[PrinterCommands]` si aún no existe y sobrescribe solo la plantilla de la ticketera, manteniendo intacto el `PrinterCommandTemplate` de las colas MKP:
   ```ini
   [PrinterCommands]
   FPRINT1 = lp -d "{printer}" -o media=Custom.80x3276mm -o page-top=0 -o page-bottom=0 -o fit-to-page=true -o print-scaling=100 "{file}"
   ```
   De esta manera cada trabajo con prefijo `FPRINT1` usará el ancho de 72 mm y cero márgenes sin afectar los parámetros de MKP.
6. Reinicia el listener y deja un archivo `FPRINT1_demo.pdf` en la carpeta compartida para validar. También puedes lanzar una prueba directa:
   ```bash
   lp -d FPRINT1 -o media=Custom.80x3276mm /ruta/a/ticket_prueba.pdf
   lpstat -p FPRINT1 -l
   ```
   Ajusta las opciones (`-o media`, `-o fit-to-page`, `-o scaling`) hasta que el ticket salga centrado y sin márgenes blancos. Para confirmar que CUPS rasteriza el PDF (necesario para los QR), ejecuta:
   ```bash
   cupsfilter -p /etc/cups/ppd/FPRINT1.ppd \
     -m application/vnd.cups-raster \
     /ruta/a/ticket_prueba.pdf >/tmp/FPRINT1_test.raster
   file /tmp/FPRINT1_test.raster
   ```
   El resultado debe ser un archivo `CUPS Raster`; si en su lugar obtienes texto plano, revisa el PPD/filtro. Otra opción es ejecutar el filtro en seco:
   ```bash
   scripts/cups_filters/pdftoescpos_mkp.py 88 tester demo 1 "" /ruta/a/ticket_prueba.pdf >/tmp/FPRINT1_demo.escpos
   hexdump -C /tmp/FPRINT1_demo.escpos | head
   ```
   Si observas bloques `1d 76 30`, el filtro está produciendo los comandos ESC/POS correctos; puedes inyectarlos con `nc 10.10.20.181 9100 < /tmp/FPRINT1_demo.escpos`.

> TIP: el script `scripts/setup_f_print1.sh` es idempotente: reinstala el filtro si cambió en el repo, recrea la cola `FPRINT1` con el PPD local y deja las opciones por defecto cada vez que lo ejecutes.

## 6. Eliminar una impresora

```bash
sudo lpadmin -x MKP4
sudo rm -f /etc/cups/ppd/MKP4.ppd
```

Salida esperada:
```text
lpadmin: Printer deleted.
```

Retira su entrada del bloque `[Printers]` del INI para evitar trabajos huérfanos.

## 7. Checklist después de cualquier cambio

1. `lpstat -p` para confirmar que las colas siguen habilitadas.
2. Copiar un PDF de prueba `MKP1_demo.pdf` al share y verificar que termina en `/mnt/mkp_print/impresos`.
3. Revisar `CHANGELOG/history.md` y añadir la fecha/acción para mantener trazabilidad.
4. Confirmar acceso web: `https://impresiones-mkp:631/admin` (usuario `cupsadmin`).

## 8. Recuperación rápida

- **cups.service caído**: `sudo systemctl restart cups` y revisar `journalctl -u cups`.
- **Servicio Python detenido**: volver a lanzarlo o reiniciar la unidad systemd.
- **Errores de permisos**: confirmar que el usuario que ejecuta el listener puede escribir en `/mnt/mkp_print/impresos` y `/mnt/mkp_print/error`.
