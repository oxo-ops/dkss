"""Small, self-contained Unicode PDF exporter with an OFL Japanese font."""
import json
from functools import lru_cache
from pathlib import Path
import unicodedata
import zipfile
import zlib


@lru_cache(maxsize=1)
def _font():
    with zipfile.ZipFile(Path(__file__).parent / 'assets/fonts/report-japanese.zip') as archive:
        return zlib.compress(archive.read('font.ttf')), json.loads(archive.read('metrics.json'))


def export_pdf(lines):
    font, metrics = _font()
    cmap = metrics['cmap']; used = {}; wrapped = []
    for line in lines:
        current = ''; width = 0
        for ch in str(line):
            size = cmap.get(str(ord(ch)), cmap['63'])[1] / 1000
            if ch == '\n' or width + size > 50:
                wrapped.append(current); current = ''; width = 0
                if ch == '\n':
                    continue
            # Control characters and unavailable glyphs stay visible as replacement marks.
            if unicodedata.category(ch) == 'Cc' or str(ord(ch)) not in cmap:
                ch = '?'
            current += ch; width += size
        wrapped.append(current)
    pages = [wrapped[i:i + 54] for i in range(0, len(wrapped), 54)] or [[]]

    def encoded(text):
        result = []
        for ch in text:
            glyph, width = cmap.get(str(ord(ch)), cmap['63'])
            used[glyph] = (ch, width)
            result.append(f'{glyph:04x}')
        return ''.join(result)

    def stream(data, extra=''):
        return f'<< /Length {len(data)} {extra} >>\nstream\n'.encode() + data + b'\nendstream'

    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'',
        b'<< /Type /Font /Subtype /Type0 /BaseFont /DKSSReportSansJP /Encoding /Identity-H /DescendantFonts [4 0 R] /ToUnicode 7 0 R >>', b'', b'',
        stream(font, '/Filter /FlateDecode'), b'']
    kids = []
    for index, page in enumerate(pages):
        pageid = len(objects) + 1; contentid = pageid + 1; kids.append(f'{pageid} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {contentid} 0 R >>'.encode())
        commands = ['BT /F1 10 Tf 14 TL 42 800 Td']
        commands.extend('<' + encoded(line) + '> Tj T*' for line in page)
        commands.extend(['ET', 'BT /F1 9 Tf 42 25 Td <' + encoded(f'{index + 1} / {len(pages)}') + '> Tj ET'])
        objects.append(stream(zlib.compress('\n'.join(commands).encode()), '/Filter /FlateDecode'))
    widths = ' '.join(f'{glyph} [{value[1]}]' for glyph, value in sorted(used.items()))
    objects[3] = ('<< /Type /Font /Subtype /CIDFontType2 /BaseFont /DKSSReportSansJP /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 5 0 R /CIDToGIDMap /Identity /DW 1000 /W [' + widths + '] >>').encode()
    bbox = ' '.join(str(v) for v in metrics['bbox'])
    objects[4] = f'<< /Type /FontDescriptor /FontName /DKSSReportSansJP /Flags 4 /FontBBox [{bbox}] /ItalicAngle 0 /Ascent {metrics["ascent"]} /Descent {metrics["descent"]} /CapHeight 733 /StemV 80 /FontFile2 6 0 R >>'.encode()
    unicode_map = ['/CIDInit /ProcSet findresource begin', '12 dict begin', 'begincmap', '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def', '/CMapName /DKSSReportUnicode def', '/CMapType 2 def', '1 begincodespacerange', '<0000> <FFFF>', 'endcodespacerange']
    items = sorted(used.items())
    for offset in range(0, len(items), 100):
        batch = items[offset:offset + 100]
        unicode_map.append(f'{len(batch)} beginbfchar')
        unicode_map.extend(f'<{glyph:04x}> <{value[0].encode("utf-16-be").hex()}>' for glyph, value in batch)
        unicode_map.append('endbfchar')
    unicode_map += ['endcmap', 'CMapName currentdict /CMap defineresource pop', 'end', 'end']
    objects[6] = stream('\n'.join(unicode_map).encode())
    objects[1] = f'<< /Type /Pages /Count {len(pages)} /Kids [{" ".join(kids)}] >>'.encode()
    out = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out)); out.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(out); out.extend(f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        out.extend(f'{offset:010d} 00000 n \n'.encode())
    out.extend(f'trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(out)
