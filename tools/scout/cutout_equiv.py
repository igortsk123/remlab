#!/usr/bin/env python3
"""ЗАПИСЬ «ВХОД РАВНОЗНАЧЕН» — ПРОГРАММА СРАВНЕНИЯ ДВУХ ВЫРЕЗОК (T-20261127-175/10; вердикт Fable по cut9 `proverka-t175-cut9.md` § 2–3).

ЗАЧЕМ. Форма девяти товаров построена из входа, вырезанного старой цепочкой; новая вырезка отличается сдвигом кромки на пиксель. Строить формы заново незачем, но «обойти проверку» нечестно:
проверка перед кругом пропускает такую форму по записи «вход равнозначен: да», которую пишет ЭТА программа, а не рука. Запись нельзя вписать: проверка перед кругом пересчитывает хеши файлов и сами числа.

ЧТО СРАВНИВАЕТ (маски по альфе > 127, холсты обязаны совпасть — иначе «нет»; определения — как в скрипте Fable `fable-1126/v29/eq9.py`):
  mismatch_pct      · несовпадение масок, % площади старой маски (XOR / площадь старой)
  far_px            · пикселей различия дальше 2 px от другой маски (ушло + добавилось): ловит потерянную проволоку/ножку, которую доля площади не видит
  far_area_pct      · они же в % площади старой маски
  far_largest_px    · крупнейший связный кусок таких пикселей
  color_mean_abs    · средний |Δ| цвета RGB по общим пикселям — ТОЛЬКО запись, на итог не влияет (на форму цвет входа не влияет)
ПОРОГИ (Fable, предварительные, `rules/circle-origin.json` → `equiv`; оба условия вместе): far_px ≤ 30 И far_area_pct ≤ 0,02 И mismatch_pct ≤ 1,0. Итог `equal: true/false`.
Перепроверить на сравнении 200 фото (шаг 9.6).

ЗАПИСЬ (json рядом с формой, `<форма>.equiv.json`): schema, kind «equivalence», photo {path, sha256} (исходное фото — для пересчёта), old {path, sha256, chain} (вход, из которого построена форма: старая цепочка),
new {path, sha256, chain_version} (что даёт единый модуль СЕЙЧАС), against_chain_version, numbers, thresholds, equal, code_version (хеш этого файла + git HEAD репо), date.
ПРОВЕРКА (`verify`): файлы есть и хеши = записанным (подделка/подмена → отказ); числа пересчитываются из файлов и должны дать тот же итог; `against_chain_version` == актуальной — иначе запись УСТАРЕЛА.
ПЕРЕСЧЁТ (`refresh`): устарела → команда `equiv.recompute_cmd` из правил (шаблон с {photo} {out}) заново режет фото единым модулем, сравнение и запись пересчитываются сами; команды нет (единый модуль вырезки T-175/9 не влит) — отказ.

CLI: cutout_equiv.py compare СТАРАЯ.png НОВАЯ.png --against ВЕРСИЯ --out ЗАПИСЬ.json [--photo ФОТО] [--old-chain make_hd_inputs] [--new-chain-version V]; verify ЗАПИСЬ.json --current ВЕРСИЯ.
Нужны numpy, pillow, opencv (CI-job `planner` и venv scout). Без сети, платного, секретов.
Тест: python3 tools/scout/tests/test_circle_origin.py"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DEFAULT_TH = {'far_px_max': 30, 'far_area_pct_max': 0.02, 'mismatch_pct_max': 1.0, 'alpha_min': 127, 'far_dist_px': 2}
SCHEMA = 1


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def code_version() -> str:
    """Хеш этого файла + git HEAD (если репо) — версия кода сравнения."""
    v = sha256_file(os.path.abspath(__file__))[:12]
    try:
        g = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        g = ''
    return f'{v}+{g}' if g else v


def compare(old_png: str, new_png: str, th: dict | None = None) -> dict:
    """Числа сравнения двух вырезок и итог `equal` по порогам (см. шапку). Холсты разные — equal False, причина в `why`."""
    import cv2
    import numpy as np
    from PIL import Image
    T = {**DEFAULT_TH, **(th or {})}
    ia, ib = Image.open(old_png).convert('RGBA'), Image.open(new_png).convert('RGBA')
    a, b = np.asarray(ia), np.asarray(ib)
    if a.shape != b.shape:
        return {'equal': False, 'why': f'холсты разные: {a.shape[:2]} и {b.shape[:2]}', 'numbers': {}}
    A, B = a[..., 3] > T['alpha_min'], b[..., 3] > T['alpha_min']
    area = int(A.sum())
    if area == 0:
        return {'equal': False, 'why': 'старая маска пуста', 'numbers': {}}
    dA = cv2.distanceTransform((~A).astype(np.uint8), cv2.DIST_L2, 5)
    dB = cv2.distanceTransform((~B).astype(np.uint8), cv2.DIST_L2, 5)
    lost = A & ~B & (dB > T['far_dist_px'])
    add = B & ~A & (dA > T['far_dist_px'])
    far = (lost | add).astype(np.uint8)
    k, _lab, st, _c = cv2.connectedComponentsWithStats(far, connectivity=8)
    big = int(st[1:, cv2.CC_STAT_AREA].max()) if k > 1 else 0
    both = A & B
    color = float(np.abs(a[..., :3][both].astype(int) - b[..., :3][both].astype(int)).mean()) if both.any() else 0.0
    n = {'area_old_px': area, 'mismatch_pct': round(100.0 * int((A ^ B).sum()) / area, 4), 'far_lost_px': int(lost.sum()), 'far_added_px': int(add.sum()),
         'far_px': int(lost.sum() + add.sum()), 'far_area_pct': round(100.0 * int(lost.sum() + add.sum()) / area, 4), 'far_largest_px': big, 'color_mean_abs': round(color, 3)}
    fails = []
    if n['far_px'] > T['far_px_max']:
        fails.append(f"пикселей различия дальше {T['far_dist_px']} px: {n['far_px']} > {T['far_px_max']}")
    if n['far_area_pct'] > T['far_area_pct_max']:
        fails.append(f"они же {n['far_area_pct']} % площади > {T['far_area_pct_max']} %")
    if n['mismatch_pct'] > T['mismatch_pct_max']:
        fails.append(f"несовпадение {n['mismatch_pct']} % > {T['mismatch_pct_max']} %")
    return {'equal': not fails, 'why': '; '.join(fails), 'numbers': n}


def build_record(old_png: str, new_png: str, against: str, th: dict | None = None, photo: str | None = None, old_chain: str = '', new_chain_version: str | None = None) -> dict:
    res = compare(old_png, new_png, th)
    return {'schema': SCHEMA, 'kind': 'equivalence',
            'photo': {'path': photo, 'sha256': sha256_file(photo) if photo and os.path.exists(photo) else None},
            'old': {'path': os.path.abspath(old_png), 'sha256': sha256_file(old_png), 'chain': old_chain or 'неизвестна'},
            'new': {'path': os.path.abspath(new_png), 'sha256': sha256_file(new_png), 'chain_version': new_chain_version or against},
            'against_chain_version': against, 'numbers': res['numbers'], 'thresholds': {**DEFAULT_TH, **(th or {})}, 'equal': res['equal'], 'why': res['why'],
            'code_version': code_version(), 'date': datetime.date.today().isoformat()}


def verify(rec: dict, current: str | None, th: dict | None = None) -> tuple:
    """(статус, причина, числа): equal | not_equal | stale | forged | unreadable. Хеши и числа ПЕРЕСЧИТЫВАЮТСЯ из файлов; рукой вписанное не пройдёт."""
    if not isinstance(rec, dict) or rec.get('kind') != 'equivalence':
        return 'unreadable', 'не запись «вход равнозначен»', {}
    for part in ('old', 'new'):
        p = (rec.get(part) or {}).get('path')
        if not p or not os.path.exists(p):
            return 'forged', f'файла {part} нет: {p}', {}
        if sha256_file(p) != (rec[part] or {}).get('sha256'):
            return 'forged', f'хеш {part} не совпал с файлом {p}: запись не от этого файла (подмена/подделка)', {}
    if not current:
        return 'stale', 'актуальная версия цепочки не определена — сравнивать не с чем', {}
    if rec.get('against_chain_version') != current or (rec.get('new') or {}).get('chain_version') != current:
        return 'stale', f'запись сделана против версии «{rec.get("against_chain_version")}», актуальная «{current}»', {}
    res = compare(rec['old']['path'], rec['new']['path'], {**(rec.get('thresholds') or {}), **(th or {})})
    if bool(rec.get('equal')) != res['equal']:
        return 'forged', f'итог в записи ({rec.get("equal")}) ≠ пересчитанному ({res["equal"]}): запись вписана не программой сравнения', res['numbers']
    if not res['equal']:
        return 'not_equal', res['why'], res['numbers']
    return 'equal', '', res['numbers']


def refresh(rec_path: str, current: str, cmd_tpl: list | None, th: dict | None = None) -> tuple:
    """Пересчёт устаревшей записи: `cmd_tpl` ({photo}, {out}) режет фото единым модулем → новое сравнение → запись перезаписана. → (запись|None, причина)."""
    try:
        rec = json.load(open(rec_path, encoding='utf-8'))
    except (OSError, ValueError):
        return None, 'запись не читается'
    if not cmd_tpl:
        return None, 'команда пересчёта (rules equiv.recompute_cmd) не задана: единый модуль вырезки (T-175/9) не влит'
    photo = (rec.get('photo') or {}).get('path')
    if not photo or not os.path.exists(photo) or sha256_file(photo) != (rec['photo'] or {}).get('sha256'):
        return None, 'исходного фото нет или хеш не совпал — пересчитать не из чего'
    out = os.path.splitext(rec_path)[0] + f'.new-{current}.png'
    argv = [t.replace('{photo}', photo).replace('{out}', out) for t in cmd_tpl]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0 or not os.path.exists(out):
        return None, f'команда пересчёта упала rc={p.returncode}: {(p.stdout + p.stderr)[-200:]}'
    new = build_record(rec['old']['path'], out, current, {**(rec.get('thresholds') or {}), **(th or {})}, photo, rec['old'].get('chain', ''))
    with open(rec_path, 'w', encoding='utf-8') as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    return new, ''


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description='запись «вход равнозначен» — сравнение двух вырезок (T-175/10)')
    sp = ap.add_subparsers(dest='cmd', required=True)
    c = sp.add_parser('compare')
    c.add_argument('old')
    c.add_argument('new')
    c.add_argument('--against', required=True, help='актуальная версия цепочки, против которой сравнивается новая вырезка')
    c.add_argument('--out', required=True)
    c.add_argument('--photo', default=None)
    c.add_argument('--old-chain', default='')
    v = sp.add_parser('verify')
    v.add_argument('record')
    v.add_argument('--current', required=True)
    a = ap.parse_args(argv)
    if a.cmd == 'compare':
        rec = build_record(a.old, a.new, a.against, None, a.photo, a.old_chain)
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        print(f"равнозначен: {'да' if rec['equal'] else 'нет'} {rec['numbers']} {rec['why']}")
        return 0 if rec['equal'] else 1
    st, why, n = verify(json.load(open(a.record, encoding='utf-8')), a.current)
    print(st, why, n)
    return 0 if st == 'equal' else 1


if __name__ == '__main__':
    sys.exit(main())
