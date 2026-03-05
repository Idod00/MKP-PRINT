#!/usr/bin/env python3
"""
Servicio de monitoreo y encolado de impresiones para Linux.

Cronograma rápido:
- 2025-11-11: Primer port desde PowerShell con prefijos MKP160/MKP161.
- 2025-11-12: Normalización a MKP1/MKP2/MKP3 compartiendo driver Honeywell.
- 2025-11-12 (tarde): endurecimiento de acceso web + usuario cupsadmin documentado.

Este script replica la lógica del servicio PowerShell descrito por el usuario:
- Lee la configuración desde un archivo INI.
- Vigila una carpeta compartida (montada previamente) y escucha archivos PDF nuevos.
- Intenta imprimir cada archivo usando un comando configurable.
- Mueve los archivos impresos a una subcarpeta "Printed" y los que fallan a "Error".
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

from logging.handlers import TimedRotatingFileHandler

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver


@dataclass(frozen=True)
class WatchLocation:
    """Representa una carpeta vigilada y sus carpetas auxiliares."""

    watch_path: Path
    printed_dir: Path
    error_dir: Path


@dataclass(frozen=True)
class ServiceConfig:
    """Contiene los valores que provienen del archivo INI."""

    watch_locations: tuple[WatchLocation, ...]
    log_dir: Path
    printer_command_template: str
    printer_command_overrides: Dict[str, str]
    print_timeout_seconds: int
    file_ready_retries: int
    file_ready_delay_ms: int
    event_debounce_ms: int
    printer_aliases: Dict[str, str]
    use_polling_observer: bool

    @classmethod
    def from_parser(cls, parser: configparser.ConfigParser) -> "ServiceConfig":
        general = parser["General"]

        printed_folder_name = general.get("PrintedFolderName", "Printed")
        error_folder_name = general.get("ErrorFolderName", "Error")
        raw_watch_paths = general.get("WatchPaths", "").strip()
        watch_paths: list[Path] = []

        if raw_watch_paths:
            candidates = re.split(r"[\n,]", raw_watch_paths)
            for candidate in candidates:
                candidate_clean = candidate.strip()
                if candidate_clean:
                    watch_paths.append(Path(candidate_clean).expanduser().resolve())

        if not watch_paths:
            legacy_watch_path = general.get("WatchPath", "").strip()
            if legacy_watch_path:
                watch_paths.append(Path(legacy_watch_path).expanduser().resolve())

        if not watch_paths:
            raise ValueError("Debes especificar al menos una ruta en WatchPaths o WatchPath")

        watch_locations = tuple(
            WatchLocation(
                watch_path=watch_path,
                printed_dir=(watch_path / printed_folder_name).resolve(),
                error_dir=(watch_path / error_folder_name).resolve(),
            )
            for watch_path in watch_paths
        )

        log_dir = Path(general.get("LogBaseDir", "logs/listener")).expanduser().resolve()

        printer_command_template = general.get(
            "PrinterCommandTemplate",
            'lp -d "{printer}" "{file}"',
        )

        printer_aliases: dict[str, str] = {}
        if parser.has_section("Printers"):
            for alias, destination in parser["Printers"].items():
                alias_clean = alias.strip()
                destination_clean = destination.strip()
                if alias_clean and destination_clean:
                    printer_aliases[alias_clean.upper()] = destination_clean

        command_overrides: dict[str, str] = {}
        if parser.has_section("PrinterCommands"):
            for alias, template in parser["PrinterCommands"].items():
                alias_clean = alias.strip()
                template_clean = template.strip()
                if alias_clean and template_clean:
                    command_overrides[alias_clean.upper()] = template_clean

        return cls(
            watch_locations=watch_locations,
            log_dir=log_dir,
            printer_command_template=printer_command_template,
             printer_command_overrides=command_overrides,
            print_timeout_seconds=general.getint("PrintTimeoutSeconds", fallback=5),
            file_ready_retries=general.getint("FileReadyRetries", fallback=10),
            file_ready_delay_ms=general.getint("FileReadyDelayMs", fallback=200),
            event_debounce_ms=general.getint("EventDebounceMs", fallback=300),
            printer_aliases=printer_aliases,
            use_polling_observer=general.getboolean("UsePollingObserver", fallback=False),
        )

    def resolve_printer(self, prefix: str) -> str:
        """Devuelve la cola real a partir de un prefijo de archivo."""
        return self.printer_aliases.get(prefix.upper(), prefix)


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    log_base = log_dir / "print_service.log"
    rotating_handler = TimedRotatingFileHandler(
        log_base,
        when="midnight",
        backupCount=14,
        encoding="utf-8",
        delay=True,
    )
    rotating_handler.suffix = "%Y-%m-%d"

    def _namer(default_name: str) -> str:
        """Renombra foo.log.YYYY-MM-DD -> foo_YYYY-MM-DD.log para mantener el patrón previo."""
        default_path = Path(default_name)
        try:
            base_with_ext, date_part = default_path.name.rsplit(".", 1)
            stem, ext = os.path.splitext(base_with_ext)
        except ValueError:
            return default_name
        new_name = f"{stem}_{date_part}{ext}"
        return str(default_path.with_name(new_name))

    rotating_handler.namer = _namer

    log_format = "[%(asctime)s] [PID:%(process)d|TID:%(thread)d] [%(levelname)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S.%f"

    handlers: list[logging.Handler] = [
        rotating_handler,
        logging.StreamHandler(sys.stdout),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
    )


def wait_file_ready(file_path: Path, retries: int, delay_ms: int) -> bool:
    """Verifica si el archivo ya no está bloqueado por otra aplicación."""
    for _ in range(max(1, retries)):
        try:
            with open(file_path, "rb"):
                return True
        except OSError:
            time.sleep(max(10, delay_ms) / 1000.0)
    return False


def extract_printer_name(
    file_name: str,
    known_prefixes: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Obtiene el prefijo del archivo y admite nombres sin separador explícito."""
    base_name = Path(file_name).name
    if "_" in base_name:
        candidate = base_name.split("_", 1)[0]
        if candidate:
            return candidate

    upper_name = base_name.upper()
    if known_prefixes:
        normalized_prefixes = tuple(sorted({p.upper() for p in known_prefixes}, key=len, reverse=True))
        for prefix in normalized_prefixes:
            if upper_name.startswith(prefix):
                return base_name[: len(prefix)]

    match = re.match(r"[A-Za-z0-9]+", base_name)
    if match:
        return match.group(0)
    return None


class FileProcessor:
    """Procesa en serie los archivos detectados por el observador."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.logger = logging.getLogger("print_processor")
        self.queue: queue.Queue[Optional[tuple[Path, WatchLocation]]] = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, name="processor", daemon=True)
        self.stop_event = threading.Event()
        prefixes = {alias.upper() for alias in config.printer_aliases.keys()}
        prefixes.update(dest.upper() for dest in config.printer_aliases.values())
        self.known_prefixes = tuple(sorted(prefixes, key=len, reverse=True))

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.queue.put(None)
        self.worker.join(timeout=2)

    def enqueue(self, file_path: Path, location: WatchLocation) -> None:
        self.queue.put((file_path, location))

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is None:
                break

            try:
                file_path, location = item
                self._process_file(file_path, location)
            except Exception:
                self.logger.exception("Fallo inesperado procesando %s", item)
            finally:
                self.queue.task_done()

    def _process_file(self, full_path: Path, location: WatchLocation) -> None:
        if not full_path.exists():
            self.logger.warning("Archivo %s ya no existe cuando se intentó procesar.", full_path.name)
            return

        file_name = full_path.name
        printer_name_raw = extract_printer_name(file_name, self.known_prefixes)
        if not printer_name_raw:
            self.logger.error(
                "No se pudo inferir la impresora desde el nombre %s. Moviendo a ERROR.",
                file_name,
            )
            self._move_to_directory(full_path, location.error_dir)
            return

        printer_name = self.config.resolve_printer(printer_name_raw)

        if not wait_file_ready(full_path, self.config.file_ready_retries, self.config.file_ready_delay_ms):
            self.logger.error("Archivo %s bloqueado tras múltiples intentos. Moviendo a ERROR.", file_name)
            self._move_to_directory(full_path, location.error_dir)
            return

        if self._print_file(full_path, printer_name):
            self._move_to_directory(full_path, location.printed_dir)
        else:
            self._move_to_directory(full_path, location.error_dir)

    def _print_file(self, file_path: Path, printer: str) -> bool:
        printer_key = printer.upper()
        cmd_template = self.config.printer_command_overrides.get(
            printer_key,
            self.config.printer_command_template,
        )

        try:
            formatted = cmd_template.format(file=str(file_path), printer=printer)
        except KeyError as exc:
            self.logger.error("Plantilla de comando inválida: falta la llave %s", exc)
            return False

        command = shlex.split(formatted)
        self.logger.info("Enviando %s a la impresora %s mediante: %s", file_path.name, printer, command)

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.config.print_timeout_seconds,
                check=True,
            )
            if completed.stdout:
                self.logger.info("Salida de impresión: %s", completed.stdout.strip())
            if completed.stderr:
                self.logger.warning("Stderr de impresión: %s", completed.stderr.strip())
            self.logger.info("Impresión completada: %s", file_path.name)
            return True
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "El comando de impresión excedió %s s para %s. Se intentará terminar el proceso.",
                self.config.print_timeout_seconds,
                file_path.name,
            )
            return False
        except subprocess.CalledProcessError as exc:
            self.logger.error(
                "El comando de impresión falló (%s): %s",
                exc.returncode,
                exc.stderr.strip() if exc.stderr else exc,
            )
            return False
        except FileNotFoundError:
            self.logger.error("Comando no encontrado. ¿Está instalado el ejecutable? -> %s", command[0])
            return False

    def _move_to_directory(self, origin: Path, destination_dir: Path) -> None:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / origin.name

        if destination.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = destination_dir / f"{origin.stem}_{timestamp}{origin.suffix}"
            self.logger.warning("Archivo existente detectado. Renombrado destino a %s", destination.name)

        shutil.move(str(origin), str(destination))
        self.logger.info("Archivo movido a %s", destination)


class PdfCreatedHandler(FileSystemEventHandler):
    """Maneja eventos de creación y pasa los archivos al procesador."""

    def __init__(self, processor: FileProcessor, debounce_ms: int, location: WatchLocation) -> None:
        super().__init__()
        self.processor = processor
        self.debounce_ms = debounce_ms
        self.logger = logging.getLogger("watcher")
        self.location = location

    def _enqueue_if_pdf(self, raw_path: str) -> None:
        path = Path(raw_path)
        if path.suffix.lower() != ".pdf":
            return

        self.logger.info("Evento detectado: %s", path.name)
        time.sleep(self.debounce_ms / 1000.0)
        self.processor.enqueue(path, self.location)

    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return

        self._enqueue_if_pdf(event.src_path)

    # Algunos drivers envían eventos de "moved" en vez de "created"
    def on_moved(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._enqueue_if_pdf(event.dest_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Servicio de monitoreo de impresión para Linux.")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("watch_print.ini"),
        help="Ruta del archivo INI. Por defecto: ./watch_print.ini",
    )
    return parser.parse_args()


def load_config(path: Path) -> ServiceConfig:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")

    parser = configparser.ConfigParser()
    parser.read(path)

    if "General" not in parser:
        raise ValueError("El archivo INI debe contener la sección [General].")

    return ServiceConfig.from_parser(parser)


def ensure_directories(config: ServiceConfig) -> None:
    for location in config.watch_locations:
        for directory in (location.watch_path, location.printed_dir, location.error_dir):
            directory.mkdir(parents=True, exist_ok=True)


def enqueue_existing_pdfs(location: WatchLocation, processor: FileProcessor, logger: logging.Logger) -> None:
    """Escanea la carpeta vigilada para incorporar PDFs ya existentes al arranque."""
    try:
        pdfs = sorted(
            (p for p in location.watch_path.glob("*.pdf") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError as exc:
        logger.error("No se pudo listar PDFs existentes en %s: %s", location.watch_path, exc)
        return

    if not pdfs:
        return

    logger.info("Se encontraron %s PDFs pendientes al iniciar. Se encolarán.", len(pdfs))
    for pdf in pdfs:
        processor.enqueue(pdf, location)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    configure_logging(config.log_dir)
    logger = logging.getLogger("main")

    ensure_directories(config)

    logger.info("=== Diagnóstico de configuración cargada ===")
    logger.info("Rutas vigiladas: %s", len(config.watch_locations))
    for idx, location in enumerate(config.watch_locations, start=1):
        logger.info("  [%s] WatchPath: %s", idx, location.watch_path)
        logger.info("      PrintedDir: %s", location.printed_dir)
        logger.info("      ErrorDir: %s", location.error_dir)
    logger.info("PrinterCommandTemplate: %s", config.printer_command_template)
    if config.printer_command_overrides:
        logger.info("Overrides de impresión:")
        for alias, template in config.printer_command_overrides.items():
            logger.info("  - %s -> %s", alias, template)
    logger.info("==========================================")

    processor = FileProcessor(config)
    processor.start()

    observer_cls = PollingObserver if config.use_polling_observer else Observer
    observer = observer_cls()
    for location in config.watch_locations:
        event_handler = PdfCreatedHandler(processor, config.event_debounce_ms, location)
        observer.schedule(event_handler, str(location.watch_path), recursive=False)

    logger.info("=== Servicio iniciado ===")
    watch_paths_str = ", ".join(str(loc.watch_path) for loc in config.watch_locations)
    logger.info("Monitoreando %s carpeta(s): %s", len(config.watch_locations), watch_paths_str)

    for location in config.watch_locations:
        enqueue_existing_pdfs(location, processor, logger)

    def shutdown(signum, _frame):
        logger.info("Señal %s recibida. Cerrando servicio...", signum)
        observer.stop()
        processor.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    observer.start()
    observer.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
