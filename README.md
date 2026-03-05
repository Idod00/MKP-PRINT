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
