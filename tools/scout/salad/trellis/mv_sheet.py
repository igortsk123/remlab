#!/usr/bin/env python3
"""T-20261119-06/2: лист «эталон | наша краска» для пробы mvadapter-i2tex — кадры 0° и 45° (текстура), слева лучший гибрид (форма TRELLIS.2 + краска Hunyuan), справа результат пробы.
Только для быстрого сравнения; на оценку владельцу кадры идут ОТДЕЛЬНЫМИ файлами полного размера (`01_az000_tex.png` … `04_az045_clay.png` в обеих папках), не листом.

  python3 mv_sheet.py <папка кадров эталона> <папка кадров пробы> <выход.png> [--width 800]   (в обеих папках — кадры `render_stand.py`: NN_az000_tex.png и т. д.)
  python3 mv_sheet.py --selftest
"""
from __future__ import annotations

import os
import sys

ROWS = (('az000', 'tex', '0°'), ('az045', 'tex', '45°'))


def find_frame(folder: str, view: str, mode: str) -> str | None:
    """Кадр `<NN>_<view>_<mode>.png` в папке (номер NN не важен: у разных прогонов он совпадает, но не требуем)."""
    if not os.path.isdir(folder):
        return None
    for n in sorted(os.listdir(folder)):
        if n.endswith(f'_{view}_{mode}.png'):
            return os.path.join(folder, n)
    return None


def make_sheet(ref_dir: str, ours_dir: str, out: str, width: int = 800) -> dict:
    """Лист: строки — 0° и 45°, столбцы — эталон | проба; подписи сверху. Возвращает {'sheet', 'missing': [...]} — нет кадра → серая плашка с пометкой, лист всё равно собирается."""
    from PIL import Image, ImageDraw
    cells, missing = [], []
    for view, mode, _lab in ROWS:
        for who, folder in (('ref', ref_dir), ('ours', ours_dir)):
            p = find_frame(folder, view, mode)
            if p is None:
                missing.append(f'{who}:{view}_{mode}')
            cells.append(Image.open(p).convert('RGB') if p else None)
    base = next((c for c in cells if c is not None), None)
    h = int(width * (base.height / base.width)) if base else int(width * 0.75)
    top = 28
    sheet = Image.new('RGB', (width * 2, (h + top) * len(ROWS)), (235, 235, 235))
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(cells):
        r, k = divmod(i, 2)
        x, y = k * width, r * (h + top)
        d.text((x + 8, y + 8), ('эталон (гибрид)' if k == 0 else 'mvadapter-i2tex') + ' | ' + ROWS[r][2], fill=(20, 20, 20))
        if c is not None:
            sheet.paste(c.resize((width, h), Image.Resampling.LANCZOS), (x, y + top))
        else:
            d.text((x + 8, y + top + 8), 'кадра нет', fill=(160, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sheet.save(out)
    return {'sheet': out, 'missing': missing}


def _selftest() -> int:
    import tempfile
    from PIL import Image
    bad = 0
    with tempfile.TemporaryDirectory() as t:
        a, b = os.path.join(t, 'ref'), os.path.join(t, 'ours')
        os.makedirs(a)
        os.makedirs(b)
        for folder, col in ((a, (200, 10, 10)), (b, (10, 10, 200))):
            for n, (v, m) in enumerate((('az000', 'tex'), ('az000', 'clay'), ('az045', 'tex'), ('az045', 'clay')), 1):
                Image.new('RGB', (160, 120), col).save(os.path.join(folder, f'{n:02d}_{v}_{m}.png'))
        r = make_sheet(a, b, os.path.join(t, 'o', 'sheet.png'), 80)
        im = Image.open(r['sheet'])
        ok = im.size == (160, (60 + 28) * 2) and not r['missing'] and im.getpixel((10, 40))[0] > 150 and im.getpixel((100, 40))[2] > 150
        print('  ' + ('✓' if ok else '✗') + ' лист: 2 строки × 2 столбца, слева эталон (красный), справа проба (синий)')
        bad += not ok
        os.remove(os.path.join(b, '03_az045_tex.png'))
        r2 = make_sheet(a, b, os.path.join(t, 'o', 'sheet2.png'), 80)
        ok2 = r2['missing'] == ['ours:az045_tex'] and os.path.exists(r2['sheet'])
        print('  ' + ('✓' if ok2 else '✗') + ' нет кадра пробы → лист собирается, пропуск назван')
        bad += not ok2
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    w = int(sys.argv[sys.argv.index('--width') + 1]) if '--width' in sys.argv else 800
    if '--width' in sys.argv:
        args.remove(sys.argv[sys.argv.index('--width') + 1])
    if len(args) != 3:
        sys.exit(__doc__)
    print(make_sheet(args[0], args[1], args[2], w))
