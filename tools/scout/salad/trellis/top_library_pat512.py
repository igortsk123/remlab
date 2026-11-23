#!/usr/bin/env python3
"""Узоры бинов библиотеки верха (Ш3в) 512×512 для этапа 07 (T-187/7): `<сканы>/<бин>/diff.jpg` → `data/flat3d/top-library/pat512/<бин>.jpg` (JPEG q95, ~2 МБ на 28 бинов). Этап 07 читает ТОЛЬКО эти файлы
(rules/top-prior.json → `library_pat`), поэтому узор верха одинаков локально и на Salad (файлы едут в срезе кода `code_tar.py`); сканы (171 МБ) — вне репозитория и вне образа.
Бины — ключи `data/flat3d/top-library/library.json` → items. Новый бин в библиотеке → запустить скрипт и закоммитить файл.
  python3 top_library_pat512.py <папка сканов (<бин>/diff.jpg)> [--out <папка узоров>]"""
from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
SIDE, QUALITY = 512, 95


def build(raw: str, out: str, lib_json: str) -> list:
    os.makedirs(out, exist_ok=True)
    made = []
    for k in sorted(json.load(open(lib_json, encoding='utf-8'))['items']):
        src = os.path.join(raw, k, 'diff.jpg')
        if not os.path.isfile(src):
            raise SystemExit(f'нет скана {src}')
        Image.open(src).convert('RGB').resize((SIDE, SIDE)).save(os.path.join(out, k + '.jpg'), 'JPEG', quality=QUALITY)
        made.append(k)
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('raw')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'flat3d', 'top-library', 'pat512'))
    ap.add_argument('--library', default=os.path.join(ROOT, 'data', 'flat3d', 'top-library', 'library.json'))
    a = ap.parse_args(argv)
    made = build(os.path.expanduser(a.raw), a.out, a.library)
    size = sum(os.path.getsize(os.path.join(a.out, k + '.jpg')) for k in made)
    print(f'{len(made)} узоров → {a.out}, {size / 1e6:.1f} МБ')
    return 0


if __name__ == '__main__':
    sys.exit(main())
