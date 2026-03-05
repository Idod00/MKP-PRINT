import types
import sys
import unittest
from pathlib import Path

# Stubs para evitar depender de watchdog durante las pruebas unitarias.
sys.modules.setdefault("watchdog", types.SimpleNamespace())
sys.modules.setdefault("watchdog.events", types.SimpleNamespace(FileSystemEventHandler=object))
sys.modules.setdefault("watchdog.observers", types.SimpleNamespace(Observer=object))
sys.modules.setdefault("watchdog.observers.polling", types.SimpleNamespace(PollingObserver=object))

from src.print_listener import PdfCreatedHandler, WatchLocation, extract_printer_name


class ExtractPrinterNameTests(unittest.TestCase):
    def test_prefijo_con_separador_se_devuelve_directo(self):
        self.assertEqual(extract_printer_name("MKP3_demo.pdf"), "MKP3")

    def test_detecta_prefijo_conocido_sin_separador(self):
        nombre = extract_printer_name("FPRINT11234.pdf", known_prefixes=["FPRINT1"])
        self.assertEqual(nombre, "FPRINT1")

    def test_respeta_mayusculas_originales(self):
        nombre = extract_printer_name("mkp2Ticket.pdf", known_prefixes=["MKP2"])
        self.assertEqual(nombre, "mkp2")

    def test_caida_fallback_retorna_bloque_alfa_numerico(self):
        self.assertEqual(extract_printer_name("GENERIC123.pdf"), "GENERIC123")


class PdfCreatedHandlerTests(unittest.TestCase):
    def test_on_moved_usa_dest_path(self):
        class _Processor:
            def __init__(self):
                self.items = []

            def enqueue(self, path, location):
                self.items.append((path, location))

        processor = _Processor()
        location = WatchLocation(
            watch_path=Path("/tmp/watch"),
            printed_dir=Path("/tmp/watch/Printed"),
            error_dir=Path("/tmp/watch/Error"),
        )
        handler = PdfCreatedHandler(processor=processor, debounce_ms=0, location=location)

        event = types.SimpleNamespace(
            is_directory=False,
            src_path="/tmp/watch/.tmp123",
            dest_path="/tmp/watch/PICK2_ticket.pdf",
        )
        handler.on_moved(event)

        self.assertEqual(len(processor.items), 1)
        self.assertEqual(processor.items[0][0], Path("/tmp/watch/PICK2_ticket.pdf"))
        self.assertEqual(processor.items[0][1], location)


if __name__ == "__main__":
    unittest.main()
