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
