#!/usr/bin/env python3
"""
Filtro CUPS para convertir PDF -> ESC/POS (Ticketera UNNION TP22).

Convierte cada página del PDF en PNG vía `pdftoppm`, escala al ancho útil
(80 mm ~ 640 puntos a 203 dpi), lo umbraliza y emite comandos ESC/POS
`GS v 0` en ráfagas para enviarlos a la impresora térmica.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

# 80 mm @ 203 dpi ≈ 640 puntos (ajustar a múltiplo de 8 para ESC/POS)
MAX_WIDTH_DOTS = 640          # ancho físico de 80 mm
PRINTABLE_WIDTH_DOTS = 576    # ancho útil real (~72 mm) reportado por la TP22
CONTENT_MARGIN_DOTS = 0       # sin margen, priorizar ancho total
PRINT_DPI = 203
CHUNK_ROWS = 128  # cantidad de filas por ráfaga ESC/POS
TRIM_THRESHOLD = 250  # brillo mínimo para considerar que hay contenido
TRIM_MARGIN_ROWS = 6   # filas extra para no cortar demasiado
TRIM_MARGIN_COLS = 6   # columnas extra
BLACK_THRESHOLD = 200  # valores < umbral = tinta


def debug(msg: str) -> None:
    sys.stderr.write(f"[pdftoescpos-mkp] {msg}\n")
    sys.stderr.flush()


def run_pdftoppm(pdf_path: Path, tmpdir: Path) -> Iterable[Path]:
    output_prefix = tmpdir / "page"
    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(PRINT_DPI),
        str(pdf_path),
        str(output_prefix),
    ]
    debug(f"Ejecutando {' '.join(cmd)}")
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    images = sorted(tmpdir.glob("page-*.png"))
    if not images:
        # El PDF puede tener una sola página y pdftoppm usa sufijo -1
        single = tmpdir / "page.png"
        if single.exists():
            images = [single]
    if not images:
        raise RuntimeError("pdftoppm no generó PNGs")
    return images


def _trim_vertical_whitespace(img: Image.Image) -> Image.Image:
    """Recorta el excedente superior/inferior sin tinta visible."""
    width, height = img.size
    pixels = img.load()

    def _row_has_ink(row: int) -> bool:
        return any(pixels[x, row] < TRIM_THRESHOLD for x in range(width))

    top = 0
    while top < height and not _row_has_ink(top):
        top += 1

    if top >= height:
        return img

    bottom = height - 1
    while bottom > top and not _row_has_ink(bottom):
        bottom -= 1

    top = max(0, top - TRIM_MARGIN_ROWS)
    bottom = min(height, bottom + 1 + TRIM_MARGIN_ROWS)
    return img.crop((0, top, width, bottom))


def _trim_horizontal_whitespace(img: Image.Image) -> Image.Image:
    """Recorta márgenes blancos laterales antes de escalar."""
    width, height = img.size
    pixels = img.load()

    def _col_has_ink(col: int) -> bool:
        return any(pixels[col, y] < TRIM_THRESHOLD for y in range(height))

    left = 0
    while left < width and not _col_has_ink(left):
        left += 1

    if left >= width:
        return img

    right = width - 1
    while right > left and not _col_has_ink(right):
        right -= 1

    left = max(0, left - TRIM_MARGIN_COLS)
    right = min(width, right + 1 + TRIM_MARGIN_COLS)
    if right <= left:
        return img
    return img.crop((left, 0, right, height))


def prepare_image(image_path: Path) -> Image.Image:
    debug(f"Procesando imagen {image_path}")
    img = Image.open(image_path).convert("L")
    img = _trim_vertical_whitespace(img)
    img = _trim_horizontal_whitespace(img)
    width, height = img.size
    debug(f"Dimensiones tras recorte: {width}x{height}")
    if width <= 0:
        return img

    base_width = min(MAX_WIDTH_DOTS - 2 * CONTENT_MARGIN_DOTS, PRINTABLE_WIDTH_DOTS)
    target_width = max(8, base_width)
    target_width = max(8, (target_width + 7) // 8 * 8)  # múltiplo de 8
    scale = target_width / float(width)
    new_width = target_width
    new_height = int(round(height * scale))
    if new_width != width or new_height != height:
        img = img.resize((new_width, new_height), Image.LANCZOS)
    debug(f"Escalado a {img.width}x{img.height} (target={target_width})")
    img = ImageOps.autocontrast(img)

    if new_width < MAX_WIDTH_DOTS:
        canvas = Image.new("L", (MAX_WIDTH_DOTS, img.height), color=255)
        offset = max(0, min(CONTENT_MARGIN_DOTS, MAX_WIDTH_DOTS - new_width))
        if offset:
            debug(f"Aplicando offset fijo {offset} (ancho final {MAX_WIDTH_DOTS})")
        canvas.paste(img, (offset, 0))
        return canvas
    return img


def _iter_row_bytes(img: Image.Image) -> Iterable[bytes]:
    """Devuelve la imagen umbralizada empaquetada (1 bit = tinta)."""
    width, height = img.size
    pixels = img.load()
    bytes_per_row = width // 8

    for y in range(height):
        row = bytearray(bytes_per_row)
        byte = 0
        bit_count = 0
        idx = 0
        for x in range(width):
            byte = (byte << 1) | (1 if pixels[x, y] < BLACK_THRESHOLD else 0)
            bit_count += 1
            if bit_count == 8:
                row[idx] = byte
                idx += 1
                byte = 0
                bit_count = 0
        yield bytes(row)


def emit_page(img: Image.Image, out) -> None:
    width = img.width
    bytes_per_row = width // 8
    rows = list(_iter_row_bytes(img))
    total_rows = len(rows)
    debug(f"Emitiendo página {width}x{total_rows} (bytes/row={bytes_per_row})")

    row = 0
    while row < total_rows:
        chunk_rows = rows[row : row + CHUNK_ROWS]
        chunk_len = len(chunk_rows)
        chunk_data = b"".join(chunk_rows)
        xL = bytes_per_row & 0xFF
        xH = (bytes_per_row >> 8) & 0xFF
        yL = chunk_len & 0xFF
        yH = (chunk_len >> 8) & 0xFF
        out.write(b"\x1dv0\x00")
        out.write(bytes([xL, xH, yL, yH]))
        out.write(chunk_data)
        out.write(b"\n")
        row += chunk_len
    # alimenta un poco entre páginas
    out.write(b"\n\n")


def main() -> int:
    if len(sys.argv) < 6:
        debug("Uso: pdftoescpos_mkp job-id user title copies options [file]")
        return 2

    job_id, user, title, copies, options = sys.argv[1:6]
    input_path = Path(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] != "-" else None
    debug(f"Job {job_id} - {title} ({user}) opciones={options}")

    with tempfile.TemporaryDirectory(prefix="pdftoescpos_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        pdf_path = tmpdir / "input.pdf"
        if input_path:
            pdf_path.write_bytes(Path(input_path).read_bytes())
        else:
            pdf_path.write_bytes(sys.stdin.buffer.read())

        images = run_pdftoppm(pdf_path, tmpdir)
        out = sys.stdout.buffer
        out.write(b"\x1b@\x1b3\x05")  # reset + feed reducido
        for image_path in images:
            img = prepare_image(image_path)
            emit_page(img, out)
        out.write(b"\x1dV\x42\x00")  # corte parcial
        out.flush()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - loguear y fallar
        debug(f"ERROR: {exc}")
        raise
