#!/usr/bin/env python3
"""Лист «со всех сторон» на товар браузером (T-20261123-27/1): фото слева + 6 видов (перед, 3/4, бок, зад, другой бок, верх), белый фон, одна PNG на товар.
Тот же просмотрщик, что у шага 08-frames и у страницы (model-viewer, нейтральный свет), поэтому лист показывает то, что увидит покупатель, а не отдельный рендер.
Один Chromium на весь список; модель грузится один раз на товар, вид меняется камерой (numpy-рендер `sides.py` — ≈5 мин на товар, здесь — секунды).
Числа видов, размеров и съёмки — `data/flat3d/sides-sheet.json` (в коде их нет). «Перед» = азимут камеры фото (06-visible/check.json: extra.camera.az).

  sides_sheet.py batch --items items.json --out ПАПКА [--node node]
  items.json: [{"id": "...", "glb": "…material.glb", "photo": "фото.png|jpg", "az": 12.5}] — az можно заменить на "check06": "<путь к 06-visible/check.json>".
Выход: ПАПКА/<id>.png и ПАПКА/times.json {id: {seconds, ok, notes}}. Рабочая папка `_work` (кадры видов) удаляется в конце, если не задан --keep-work.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

JS = os.path.join(HERE, 'sides_sheet.js')
RULES_PATH = os.path.join(HERE, '..', '..', 'data', 'flat3d', 'sides-sheet.json')


def load_rules(rules: dict | None = None) -> dict:
    if rules is not None:
        return rules
    with open(RULES_PATH, encoding='utf-8') as f:
        return json.load(f)


def az_of(item: dict) -> float | None:
    if item.get('az') is not None:
        return float(item['az'])
    try:
        with open(item['check06'], encoding='utf-8') as f:
            return float(json.load(f)['extra']['camera']['az'])
    except (KeyError, OSError, ValueError, TypeError):
        return None


def orbits_for(sh: dict, az: float, radius: str | None = None) -> list:
    """Орбиты видов листа: theta = азимут фото + dtheta, polar = 90 − высота камеры."""
    radius = radius or sh['radius']
    return [{'tag': f'{i}', 'orbit': f"{(az + v['dtheta']) % 360:.1f}deg {90 - v['elev']:g}deg {radius}"} for i, v in enumerate(sh['views'])]


def build_spec(sh: dict, out: str, items: list, clay: bool = False) -> dict:
    return {'out': out, 'clay': dict(sh['clay']) if clay else None, 'site': dict(sh['site']) if sh.get('site', {}).get('enabled') else None, 'light': sh['light'], 'viewer': {'width': sh['size'], 'height': sh['size'], 'settle_ms': sh['settle_ms'], 'load_timeout_s': sh['load_timeout_s']},
            'libs': dict(sh['libs']), 'chromium_args': sh['chromium_args'],
            'items': [{'id': it['id'], 'glb': it['glb'], 'orbits': orbits_for(sh, it['_az'])} for it in items]}


def assemble(sh: dict, photo_path: str | None, views_dir: str, dst: str, suffix: str = '') -> None:
    from PIL import Image, ImageDraw, ImageFont
    S, hp = int(sh['size']), int(sh['header_px'])
    try:
        font = ImageFont.truetype(sh['font'], int(sh['font_px']))
    except OSError:
        font = ImageFont.load_default()
    sheet = Image.new('RGB', (S * (len(sh['views']) + 1), S + hp), 'white')
    d = ImageDraw.Draw(sheet)
    d.text((5, 4), 'ФОТО', fill='black', font=font)
    try:
        ph = Image.open(photo_path).convert('RGBA')
        bg = Image.new('RGBA', ph.size, tuple(sh['photo_bg']) + (255,))
        bg.alpha_composite(ph)
        ph = bg.convert('RGB')
        ph.thumbnail((S, S))
        sheet.paste(ph, (0, hp + (S - ph.height) // 2))
    except Exception:
        d.text((5, hp + 6), 'нет фото', fill='black', font=font)
    for i, v in enumerate(sh['views']):
        x = (i + 1) * S
        d.text((x + 5, 4), v['name'], fill='black', font=font)
        p = os.path.join(views_dir, f'{i}{suffix}.png')
        if os.path.exists(p):
            sheet.paste(Image.open(p).convert('RGB'), (x, hp))
        else:
            d.text((x + 5, hp + 6), 'не нарисован', fill='black', font=font)
    sheet.save(dst)


def batch(items: list, out: str, node: str = 'node', rules: dict | None = None, keep_work: bool = False, render_fn=None, clay: bool = False) -> dict:
    sh = load_rules(rules)
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, '_work')
    todo, times = [], {}
    for it in items:
        az = az_of(it)
        if az is None or not os.path.exists(it['glb']):
            times[it['id']] = {'ok': False, 'seconds': 0, 'notes': ['нет азимута камеры фото' if az is None else f"нет файла {it['glb']}"]}
            continue
        todo.append(dict(it, _az=az))
    spec = build_spec(sh, work, todo, clay)
    os.makedirs(work, exist_ok=True)
    sp = os.path.join(work, 'spec.json')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    t0 = time.time()
    if todo:
        r = (render_fn or (lambda s: subprocess.run([shutil.which(node) or node, JS, s], capture_output=True, text=True)))(sp)
        print((r.stdout + r.stderr).strip()[-300:])
    rep = {}
    rj = os.path.join(work, 'items.json')
    if os.path.exists(rj):
        rep = json.load(open(rj, encoding='utf-8'))
    for it in todo:
        r_ = rep.get(it['id']) or {'ok': False, 'seconds': 0, 'notes': ['съёмка не дошла до товара']}
        if r_.get('tags'):                                               # частично снятые виды тоже собираем: пустые клетки подписаны
            assemble(sh, it.get('photo'), os.path.join(work, it['id']), os.path.join(out, it['id'] + '.png'))
            if clay:                                                     # второй лист — «глина» (те же виды, белый материал): рядом, <id>.clay.png
                assemble(sh, None, os.path.join(work, it['id']), os.path.join(out, it['id'] + '.clay.png'), '.clay')
        times[it['id']] = {'ok': bool(r_.get('ok')), 'seconds': r_.get('seconds'), 'notes': r_.get('notes', [])[:3]}
    times['_total'] = {'seconds': round(time.time() - t0, 1), 'items': len(items)}
    tp = os.path.join(out, 'times.json')
    prev = {}
    if os.path.exists(tp):                                                 # повторный запуск на части списка (дорисовать недостающие) не стирает записи остальных
        try:
            prev = json.load(open(tp, encoding='utf-8'))
        except ValueError:
            prev = {}
    prev.update({k: v for k, v in times.items() if not k.startswith('_')})
    prev['_total'] = times['_total']
    with open(tp, 'w', encoding='utf-8') as f:
        json.dump(prev, f, ensure_ascii=False, indent=1)
    times = prev
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return times


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('batch')
    b.add_argument('--items', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--node', default='node')
    b.add_argument('--keep-work', action='store_true')
    b.add_argument('--clay', action='store_true', help='кроме листа — второй лист «глина» <id>.clay.png (для sides_eval)')
    a = ap.parse_args(argv)
    items = json.load(open(a.items, encoding='utf-8'))
    t = batch(items, a.out, a.node, keep_work=a.keep_work, clay=a.clay)
    bad = [k for k, v in t.items() if not k.startswith('_') and not v['ok']]
    tot = t['_total']
    print(f"в списке {len(items)}, не вышли {len([b for b in bad if b in {i['id'] for i in items}])}, {tot['seconds']} с" + (f", не вышли: {bad}" if bad else ''))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
