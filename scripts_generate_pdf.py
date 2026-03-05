from pathlib import Path
import re
import textwrap
import unicodedata

md_path = Path('INSTRUCTIVO.md')
text = md_path.read_text(encoding='utf-8')
lines = text.splitlines()

entries = []
code_mode = False
code_lang = ''
code_buffer = []
for raw in lines:
    stripped = raw.rstrip('\n')
    if stripped.strip().startswith('```'):
        token = stripped.strip()[3:].strip()
        if not code_mode:
            code_mode = True
            code_lang = token or 'bash'
            code_buffer = []
        else:
            entries.append({'type': 'code', 'lang': code_lang or 'text', 'lines': code_buffer[:]})
            code_mode = False
            code_buffer = []
        continue
    if code_mode:
        code_buffer.append(stripped)
        continue
    if not stripped.strip():
        entries.append({'type': 'blank'})
        continue
    if stripped.startswith('# '):
        entries.append({'type': 'h1', 'text': stripped[2:].strip()})
    elif stripped.startswith('## '):
        entries.append({'type': 'h2', 'text': stripped[3:].strip()})
    elif stripped.startswith('### '):
        entries.append({'type': 'h3', 'text': stripped[4:].strip()})
    else:
        lstrip = stripped.lstrip()
        indent_spaces = len(stripped) - len(lstrip)
        if lstrip.startswith('- '):
            entries.append({'type': 'bullet', 'text': lstrip[2:].strip(), 'level': indent_spaces // 2})
        elif lstrip[:2].isdigit() and '.' in lstrip[:4]:
            entries.append({'type': 'number', 'text': lstrip})
        else:
            entries.append({'type': 'text', 'text': stripped.strip()})

ops = []

def add_space(amount):
    if amount > 0:
        ops.append({'type': 'space', 'amount': amount})

def wrap_txt(text, width):
    chunks = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    return chunks or ['']


INLINE_PATTERN = re.compile(r"(\*\*.+?\*\*|`.+?`|\*[^\s*][^*]*?\*|_[^\s_][^_]*?_)")


def parse_inline_segments(text):
    segments = []
    idx = 0
    for match in INLINE_PATTERN.finditer(text):
        start, end = match.span()
        if start > idx:
            segments.append({'text': text[idx:start], 'style': 'normal'})
        token = match.group()
        if token.startswith('**'):
            segments.append({'text': token[2:-2], 'style': 'bold'})
        elif token.startswith('`'):
            segments.append({'text': token[1:-1], 'style': 'code'})
        elif token.startswith('*'):
            segments.append({'text': token[1:-1], 'style': 'italic'})
        elif token.startswith('_'):
            segments.append({'text': token[1:-1], 'style': 'italic'})
        idx = end
    if idx < len(text):
        segments.append({'text': text[idx:], 'style': 'normal'})
    if not segments:
        segments.append({'text': text, 'style': 'normal'})
    return segments


def _split_word(word, width):
    if len(word) <= width:
        return [word]
    return [word[i:i + width] for i in range(0, len(word), width)]


def build_rich_lines(text, width, prefix='', continuation_prefix=''):
    tokens = parse_inline_segments(text)
    if prefix:
        tokens = [{'text': prefix, 'style': 'prefix'}] + tokens

    lines = []
    current = []
    current_len = 0

    def ensure_line():
        nonlocal current, current_len
        if not current:
            current = []
            current_len = 0
            if lines and continuation_prefix:
                current.append({'text': continuation_prefix, 'style': 'prefix'})
                current_len += len(continuation_prefix)

    for token in tokens:
        raw_text = token['text']
        if token['style'] == 'code':
            pieces = [raw_text]
        else:
            pieces = re.findall(r'\S+\s*', raw_text)
            if not pieces:
                if raw_text:
                    pieces = [raw_text]
                else:
                    continue
        for piece in pieces:
            chunks = _split_word(piece, width)
            for chunk in chunks:
                seg = chunk
                seg_len = len(seg)
                if seg_len == 0:
                    continue
                if current and current_len + seg_len > width:
                    lines.append(current)
                    current = []
                    current_len = 0
                ensure_line()
                current.append({'text': seg, 'style': token['style']})
                current_len += seg_len

    if current:
        lines.append(current)
    if not lines:
        lines = [[{'text': '', 'style': 'normal'}]]
    return lines


def font_for_style(style, base_font):
    if style == 'bold':
        return 'F2'
    if style == 'italic':
        return 'F3'
    if style == 'code':
        return 'F4'
    return base_font


def color_for_style(style, base_color):
    if style == 'code':
        return (0.12, 0.45, 0.25)
    return base_color


def estimate_text_width(text, size):
    avg = max(size * 0.55, 1.0)
    return len(text) * avg

for entry in entries:
    et = entry['type']
    if et == 'blank':
        add_space(6)
        continue
    if et == 'h1':
        add_space(12)
        ops.append({'type': 'text','text': entry['text'].upper(),'font': 'F2','size': 24,'color': (1, 1, 1),'indent': 0,'line_height': 36,'bg': {'color': (0.15, 0.32, 0.68), 'x_pad': -40, 'y_pad': 8, 'width_pad': 80}})
        add_space(10)
        continue
    if et == 'h2':
        add_space(10)
        ops.append({'type': 'text','text': entry['text'],'font': 'F2','size': 18,'color': (0.12, 0.32, 0.68),'indent': 0,'line_height': 26,'bg': {'color': (0.90, 0.96, 1.0), 'x_pad': -20, 'y_pad': 4, 'width_pad': 40}})
        add_space(6)
        continue
    if et == 'h3':
        add_space(6)
        ops.append({'type': 'text','text': entry['text'],'font': 'F3','size': 14,'color': (0.25, 0.25, 0.25),'indent': 10,'line_height': 22})
        continue
    if et == 'text':
        text_value = entry['text']
        highlight = text_value.lower().startswith('salida esperada')
        font_name = 'F1'
        font_color = (0.12, 0.12, 0.12)
        font_size = 12
        line_height = 18
        indent = 0
        if highlight:
            font_name = 'F2'
            font_color = (0.25, 0.45, 0.78)
            font_size = 13
            line_height = 22
        rich_lines = build_rich_lines(text_value, 92)
        ops.append({
            'type': 'rich_text',
            'lines': rich_lines,
            'font': font_name,
            'size': font_size,
            'color': font_color,
            'indent': indent,
            'line_height': line_height
        })
        add_space(4)
        continue
    if et == 'bullet':
        level = min(entry.get('level', 0), 3)
        indent = 18 + level * 16
        width = max(20, 80 - level * 4)
        rich_lines = build_rich_lines(entry['text'], width, prefix='- ', continuation_prefix='  ')
        ops.append({
            'type': 'rich_text',
            'lines': rich_lines,
            'font': 'F1',
            'size': 12,
            'color': (0.1, 0.1, 0.1),
            'indent': indent,
            'line_height': 18
        })
        add_space(2)
        continue
    if et == 'number':
        text_value = entry['text']
        prefix = ''
        body = text_value
        match = re.match(r'^(\d+\.)\s*(.*)$', text_value)
        if match:
            prefix = match.group(1) + ' '
            body = match.group(2)
        continuation = ' ' * len(prefix) if prefix else ''
        rich_lines = build_rich_lines(body or '', 92, prefix=prefix, continuation_prefix=continuation)
        ops.append({
            'type': 'rich_text',
            'lines': rich_lines,
            'font': 'F1',
            'size': 12,
            'color': (0.1, 0.1, 0.1),
            'indent': 12,
            'line_height': 18
        })
        add_space(2)
        continue
    if et == 'code':
        ops.append({'type': 'code','lang': entry['lang'],'lines': entry['lines']})
        add_space(8)
        continue

PAGE_W = 800
PAGE_H = 1000
MARGIN_X = 70
MARGIN_Y = 70
HEADER_H = 70
FOOTER = 50
START_Y = PAGE_H - MARGIN_Y - HEADER_H
MIN_Y = MARGIN_Y + FOOTER
TITLE = 'Instructivo Operativo MKP'
SUBTITLE = 'Guía rápida para operación diaria'

CODE_STYLES = {
    'bash': {
        'bg': (0.05, 0.07, 0.12),
        'label_bg': (0.00, 0.35, 0.55),
        'label_text': (0.85, 0.95, 1.0),
        'text': (0.60, 0.98, 0.60)
    },
    'text': {
        'bg': (0.12, 0.12, 0.12),
        'label_bg': (0.40, 0.40, 0.40),
        'label_text': (1.0, 1.0, 1.0),
        'text': (0.95, 0.92, 0.80)
    },
    'ini': {
        'bg': (0.13, 0.10, 0.16),
        'label_bg': (0.35, 0.12, 0.45),
        'label_text': (1.0, 0.95, 1.0),
        'text': (0.95, 0.88, 1.0)
    },
    'default': {
        'bg': (0.16, 0.16, 0.16),
        'label_bg': (0.20, 0.34, 0.55),
        'label_text': (0.95, 0.95, 1.0),
        'text': (0.90, 0.90, 0.90)
    }
}

pages = []
current_cmds = []
current_y = START_Y
page_number = 0

def sanitize(text: str) -> str:
    normalized = unicodedata.normalize('NFD', text)
    stripped = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.encode('latin-1', 'replace').decode('latin-1')


def latex_text(text: str) -> str:
    safe = sanitize(text)
    safe = safe.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
    return f'({safe})'


def start_page():
    global current_cmds, current_y, page_number
    if current_cmds:
        pages.append({'cmds': current_cmds, 'number': page_number})
    page_number += 1
    current_cmds = []
    band_x = MARGIN_X - 40
    band_y = PAGE_H - MARGIN_Y - HEADER_H + 10
    band_w = PAGE_W - 2 * (MARGIN_X - 40)
    band_h = HEADER_H
    current_cmds.append('0.09 0.24 0.52 rg')
    current_cmds.append(f'{band_x:.1f} {band_y:.1f} {band_w:.1f} {band_h:.1f} re f')
    current_cmds.append('1 1 1 rg')
    current_cmds.append('BT /F2 20 Tf {0:.1f} {1:.1f} Td {2} Tj ET'.format(MARGIN_X - 20, band_y + band_h - 26, latex_text(TITLE)))
    current_cmds.append('BT /F3 12 Tf {0:.1f} {1:.1f} Td {2} Tj ET'.format(MARGIN_X - 20, band_y + 16, latex_text(SUBTITLE)))
    current_y = START_Y


def finish_page():
    global current_cmds
    footer_y = MARGIN_Y - 25
    current_cmds.append('0.8 0.8 0.8 rg')
    current_cmds.append(f'{MARGIN_X - 30:.1f} {footer_y + 12:.1f} {PAGE_W - 2 * (MARGIN_X - 30):.1f} 1 re f')
    current_cmds.append('0.3 0.3 0.3 rg')
    current_cmds.append('BT /F1 10 Tf {0:.1f} {1:.1f} Td {2} Tj ET'.format(PAGE_W - MARGIN_X - 60, footer_y + 2, latex_text(f'Página {page_number}')))
    pages.append({'cmds': current_cmds, 'number': page_number})
    current_cmds = []


def ensure_space(height):
    global current_y
    if current_y - height < MIN_Y:
        finish_page()
        start_page()

start_page()

for op in ops:
    if op['type'] == 'space':
        current_y -= op['amount']
        continue
    if op['type'] == 'text':
        line_height = op.get('line_height', op.get('size', 12) + 6)
        bg = op.get('bg')
        extra = bg.get('y_pad', 0) * 2 if bg else 0
        ensure_space(line_height + extra + 4)
        if bg:
            pad_y = bg.get('y_pad', 4)
            pad_x = bg.get('x_pad', -10)
            width_pad = bg.get('width_pad', 20)
            rect_h = line_height + pad_y * 2
            rect_y = current_y - line_height - pad_y
            rect_x = MARGIN_X + op.get('indent', 0) + pad_x
            rect_w = PAGE_W - rect_x - MARGIN_X + width_pad
            color = bg.get('color', (0.9, 0.9, 0.9))
            current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*color))
            current_cmds.append(f'{rect_x:.1f} {rect_y:.1f} {rect_w:.1f} {rect_h:.1f} re f')
        color = op.get('color', (0, 0, 0))
        current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*color))
        font = op.get('font', 'F1')
        size = op.get('size', 12)
        x_pos = MARGIN_X + op.get('indent', 0)
        y_pos = current_y - line_height + (line_height - size) / 2
        current_cmds.append('BT /{font} {size} Tf {x:.1f} {y:.1f} Td {text} Tj ET'.format(font=font, size=size, x=x_pos, y=y_pos, text=latex_text(op['text'])))
        current_y -= line_height
        continue
    if op['type'] == 'rich_text':
        lines = op.get('lines') or [[{'text': '', 'style': 'normal'}]]
        line_height = op.get('line_height', op.get('size', 12) + 6)
        base_font = op.get('font', 'F1')
        base_color = op.get('color', (0, 0, 0))
        base_size = op.get('size', 12)
        bg = op.get('bg')
        extra = bg.get('y_pad', 0) * 2 if bg else 0
        block_height = line_height * len(lines)
        ensure_space(block_height + extra + 4)
        if bg:
            pad_y = bg.get('y_pad', 4)
            pad_x = bg.get('x_pad', -10)
            width_pad = bg.get('width_pad', 20)
            rect_h = block_height + pad_y * 2
            rect_y = current_y - block_height - pad_y
            rect_x = MARGIN_X + op.get('indent', 0) + pad_x
            rect_w = PAGE_W - rect_x - MARGIN_X + width_pad
            color = bg.get('color', (0.9, 0.9, 0.9))
            current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*color))
            current_cmds.append(f'{rect_x:.1f} {rect_y:.1f} {rect_w:.1f} {rect_h:.1f} re f')
        top_padding = bg.get('y_pad', 0) if bg else 0
        y_cursor = current_y - top_padding
        for line in lines:
            y_cursor -= line_height
            y_pos = y_cursor + (line_height - base_size) / 2
            x_pos = MARGIN_X + op.get('indent', 0)
            for segment in line:
                seg_text = segment.get('text', '')
                if not seg_text:
                    continue
                style = segment.get('style', 'normal')
                font = font_for_style(style, base_font)
                color = color_for_style(style, base_color)
                current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*color))
                current_cmds.append('BT /{font} {size} Tf {x:.1f} {y:.1f} Td {text} Tj ET'.format(font=font, size=base_size, x=x_pos, y=y_pos, text=latex_text(seg_text)))
                x_pos += estimate_text_width(seg_text, base_size)
        current_y -= block_height + extra
        continue
    if op['type'] == 'code':
        lines = op['lines'] or ['']
        lang = op.get('lang', 'code')
        lang_key = lang.lower()
        style = CODE_STYLES.get(lang_key, CODE_STYLES['default'])
        wrapped = []
        for line in lines:
            expanded = line.replace('\t', '    ')
            parts = textwrap.wrap(expanded, width=88, break_long_words=False, break_on_hyphens=False)
            wrapped.extend(parts or [''])
        line_height = 14
        pad_y = 12
        label_h = line_height + 6
        block_height = pad_y * 2 + label_h + line_height * len(wrapped)
        ensure_space(block_height)
        rect_x = MARGIN_X - 15
        rect_y = current_y - block_height
        rect_w = PAGE_W - 2 * (MARGIN_X - 15)
        current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*style['bg']))
        current_cmds.append(f'{rect_x:.1f} {rect_y:.1f} {rect_w:.1f} {block_height:.1f} re f')
        label_y = current_y - pad_y - line_height
        current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*style['label_bg']))
        current_cmds.append(f'{rect_x:.1f} {label_y:.1f} {rect_w:.1f} {label_h:.1f} re f')
        current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*style['label_text']))
        current_cmds.append('BT /F2 11 Tf {0:.1f} {1:.1f} Td {2} Tj ET'.format(rect_x + 18, label_y + 2, latex_text(f'[{lang}]')))
        text_y = label_y - 6
        for chunk in wrapped:
            text_y -= line_height
            current_cmds.append('{0:.3f} {1:.3f} {2:.3f} rg'.format(*style['text']))
            current_cmds.append('BT /F4 11 Tf {0:.1f} {1:.1f} Td {2} Tj ET'.format(rect_x + 22, text_y, latex_text(chunk)))
        current_y -= block_height
        continue

finish_page()

N = len(pages)
font_start = 3 + 2 * N
objects = []

def add_object(body_bytes):
    if not body_bytes.endswith(b'\n'):
        body_bytes += b'\n'
    objects.append(body_bytes)

add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
pages_kids = ' '.join(f"{3 + i} 0 R" for i in range(N))
add_object(f"<< /Type /Pages /Kids [{pages_kids}] /Count {N} >>".encode())

content_streams = [('\n'.join(p['cmds']) + '\n').encode('utf-8') for p in pages]

for i in range(N):
    content_obj = 3 + N + i
    page_obj = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Contents {content_obj} 0 R /Resources << /Font << /F1 {font_start} 0 R /F2 {font_start+1} 0 R /F3 {font_start+2} 0 R /F4 {font_start+3} 0 R >> >> >>"
    add_object(page_obj.encode())

for stream in content_streams:
    entry = b"<< /Length %d >>\nstream\n%sendstream" % (len(stream), stream)
    add_object(entry)

font_objs = [
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
]
for font in font_objs:
    add_object(font)

pdf_path = Path('INSTRUCTIVO.pdf')
with pdf_path.open('wb') as fh:
    fh.write(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(fh.tell())
        fh.write(f"{idx} 0 obj\n".encode())
        fh.write(obj)
        fh.write(b"endobj\n")
    xref_pos = fh.tell()
    fh.write(f"xref\n0 {len(objects)+1}\n".encode())
    fh.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        fh.write(f"{off:010d} 00000 n \n".encode())
    fh.write(b"trailer\n")
    fh.write(f"<< /Size {len(objects)+1} /Root 1 0 R >>\n".encode())
    fh.write(b"startxref\n")
    fh.write(f"{xref_pos}\n".encode())
    fh.write(b"%%EOF")

print('PDF listo con', N, 'páginas')
