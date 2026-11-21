#!/usr/bin/env python3
"""Кадры сравнения зада «stat | trellis | trellis_relief» (этап 7, T-164): из выходов пробы `<выход>/stat`, `<выход>/trellis`, `<выход>/trellis_relief` (файлы `<метка>-after-az180-зад.png`, `results.jsonl`)
собирает по товару `<выход>/frames/<метка>-zad-stat_trellis_relief.png` (слева направо stat, trellis (Б), trellis_relief (C); подпись в углу — источник и мерки) и `…-mery.txt`.
  python3 tex_fill_compare_frames.py <выход>
Нет кадра источника (нет черновика, сбой) — на его месте серая панель с пометкой. Стандартная библиотека + PIL."""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _recs(d: str) -> dict:
    out = {}
    fp = os.path.join(d, 'results.jsonl')
    if os.path.exists(fp):
        for line in open(fp, encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r.get('run')] = r
    return out


def _mery(r: dict | None) -> str:
    if not r:
        return 'нет результата'
    if r.get('error'):
        return 'сбой: ' + str(r['error'])[:60]
    if r.get('refused'):
        return 'этап 6 отказал'
    m = r.get('metrics') or {}
    g = lambda k: (m.get(k) or {}).get('value')  # noqa: E731
    f = lambda v: '—' if v is None else f'{v:.2f}'  # noqa: E731
    return f"ΔE {f(g('dE00_front_back'))} · ступени {f(g('filled_faces_step_pct'))} % · {'прошёл' if r.get('passed') else 'не прошёл'}"


def _label(im: Image.Image, x: int, text: str, font) -> None:
    d = ImageDraw.Draw(im)
    w = d.textlength(text, font=font)
    d.rectangle((x + 14, 14, x + 14 + w + 24, 62), fill=(255, 255, 255))
    d.text((x + 26, 20), text, fill=(20, 20, 20), font=font)


def main(argv: list) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = argv[0]
    srcs = ('stat', 'trellis', 'trellis_relief')
    recs = {k: _recs(os.path.join(out, k)) for k in srcs}
    fd = os.path.join(out, 'frames')
    os.makedirs(fd, exist_ok=True)
    font = _font(28)
    n = 0
    for label in sorted(recs['stat']):
        a = os.path.join(out, 'stat', f'{label}-after-az180-зад.png')
        if not os.path.exists(a):
            continue
        ia = Image.open(a).convert('RGB')
        ims, texts = [ia], [f"stat · {_mery(recs['stat'].get(label))}"]
        for k in srcs[1:]:
            b = os.path.join(out, k, f'{label}-after-az180-зад.png')
            ims.append(Image.open(b).convert('RGB') if os.path.exists(b) else Image.new('RGB', ia.size, (245, 245, 245)))
            texts.append(f"{k} · {_mery(recs[k].get(label)) if label in recs[k] else 'нет черновика'}")
        W = sum(i.width for i in ims) + 12 * (len(ims) - 1)
        im = Image.new('RGB', (W, ia.height), (255, 255, 255))
        x = 0
        for i_, t_ in zip(ims, texts):
            im.paste(i_, (x, 0))
            _label(im, x, t_, font)
            x += i_.width + 12
        base = f'{label}-zad-stat_trellis_relief'
        im.save(os.path.join(fd, base + '.png'))
        with open(os.path.join(fd, base + '-mery.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(texts) + '\n')
        n += 1
    print(f'кадров сравнения: {n} → {fd}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
