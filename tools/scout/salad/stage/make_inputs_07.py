#!/usr/bin/env python3
"""inputs.json для `stage_trial.py --stages 07` (T-187/6, T-187/7): по каждому товару — 06-visible, UltraTex-меш манифеста И карточка + фото для Ш3в-верха.
Вход 07 боевого пути ВСЕГДА такой: `--card-json @in/card.json --photo @in/photo.png --ut-glb @in/ut.glb` (extra_in: card.json, photo.png, ut.glb). Без карточки
верх Ш3в не красится (класс материала неизвестен) — раньше это был ТИХИЙ `as_before` (23.11: f1 прошёл без карточек, узор не появился ни у одного товара).
Теперь: нет карточки/фото — товар остаётся в пакете, но в списке `no_card`/`no_photo` (печать + файл `<inputs>.top-input.json`), а 07 пишет в report.json `top_skip=no_card`.
Запуск: make_inputs_07.py <манифест.tsv> <колонка UltraTex> <inputs.json> [paths-28.tsv] [sku,sku,… (иначе все)]
env: VIS_ROOT (корень out 06), EXCLUDE (sku через запятую), CARDS_JSON (файл {sku: карточка}; иначе из БД remlab-devdb), PHOTO_DIRS (папки `<sku>.hd.rgba.png`, через «:»)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

B = os.path.expanduser('~/remlab-logs')
S7 = f'{B}/t187-1122/salad07'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'ops'))
import inputs_check as IC  # noqa: E402
# где лежит <sku>.hd.rgba.png (маска — альфа): СНАЧАЛА копии входов наборов (~/remlab-inputs/<набор>/photo, пути — input-sets.json; T-20261125-75/3), потом прежние папки логов (товары вне набора)
PHOTO_DIRS = IC.set_photo_dirs() + [f'{B}/t178-forms-1122/forms-inputs', f'{B}/t172-1121/inputs', f'{B}/t172-1121/inputs30']
CARD_ARGS = ('--card-json', '@in/card.json')
PHOTO_ARGS = ('--photo', '@in/photo.png')
UT_ARGS = ('--ut-glb', '@in/ut.glb')


def cards_from_db(skus: list[str]) -> dict[str, dict]:
    """{sku: {role, name, <params>}} из каталога (кроме отсутствующих в БД). Ошибка БД — исключение, не пустой словарь (пустой словарь = «нет карточек» = тихий откат)."""
    if not skus:
        return {}
    sql = ("select shop_mid::text||'_'||external_id, cat_role, name, coalesce(params::text,'{}') from products where shop_mid::text||'_'||external_id in ("
           + ','.join("'" + s.replace("'", '') + "'" for s in skus) + ')')
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-t', '-A', '-F', '\t', '-c', sql], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'карточки из БД: psql rc={r.returncode}: {r.stderr[-300:]}')
    out = {}
    for ln in r.stdout.splitlines():
        a = ln.split('\t')
        if len(a) >= 4:
            try:
                pr = json.loads(a[3])
            except ValueError:
                pr = {}
            out[a[0]] = dict({'role': a[1], 'name': a[2]}, **(pr if isinstance(pr, dict) else {}))
    return out


def find_photo(sku: str, photo_dirs: list[str]) -> str | None:
    return next((f'{d}/{sku}.hd.rgba.png' for d in photo_dirs if os.path.isfile(f'{d}/{sku}.hd.rgba.png')), None)


def top_args(sku: str, ut: str, card: dict | None, photo: str | None, card_dir: str) -> tuple[list[str], dict]:
    """(args, extra_in) входа 07 по товару. Карточка пишется файлом в `card_dir`; нет карточки/фото — этих аргументов нет (и это видно в `no_card`/`no_photo` вызывающего)."""
    args, extra = [], {}
    if card:
        os.makedirs(card_dir, exist_ok=True)
        cp = os.path.join(card_dir, f'{sku}.card.json')
        json.dump(card, open(cp, 'w', encoding='utf-8'), ensure_ascii=False, sort_keys=True)
        args += list(CARD_ARGS)
        extra['card.json'] = cp
    if photo:
        args += list(PHOTO_ARGS)
        extra['photo.png'] = photo
    args += list(UT_ARGS)
    extra['ut.glb'] = ut
    return args, extra


def build(rows: list[list[str]], col: str, vis_of: dict, cards: dict, photo_dirs: list[str], card_dir: str, only=None, exclude=(), vis_root: str | None = None) -> tuple[dict, dict, dict]:
    """→ (inputs, miss {sku: причина — товара нет в пакете}, top {'no_card': [...], 'no_photo': [...], 'n': N})."""
    ci = rows[0].index(col)
    out, miss, top = {}, {}, {'no_card': [], 'no_photo': []}
    for r in rows[1:]:
        sku = r[0]
        if only and sku not in only:
            continue
        if sku in exclude:
            miss[sku] = 'исключён (таймаут ничьей)'
            continue
        ut = r[ci] if len(r) > ci else ''
        cands = ([f'{vis_root}/{sku}/06-visible'] if vis_root else [vis_of.get(sku), f'{S7}/out-06x4/{sku}/06-visible', f'{S7}/out-06x3/{sku}/06-visible', f'{B}/t187-3-1122/{sku}/06-visible'])
        vis = next((c for c in cands if c and os.path.isfile(os.path.join(c, 'visible.glb'))), None)
        if not ut or not os.path.isfile(ut):
            miss[sku] = f'нет UltraTex-меша ({ut or "пусто"})'
            continue
        if not vis:
            miss[sku] = 'нет 06-visible ни в одном из мест'
            continue
        card, photo = cards.get(sku), find_photo(sku, photo_dirs)
        if not card:
            top['no_card'].append(sku)
        if not photo:
            top['no_photo'].append(sku)
        args, extra = top_args(sku, ut, card, photo, card_dir)
        out[sku] = {'vis': vis, 'args': args, 'extra_in': extra}
    top['n'] = len(out)
    return out, miss, top


def main(argv: list[str]) -> int:
    man, col, dst = argv[0:3]
    paths = argv[3] if len(argv) > 3 else f'{B}/t189-1122/paths-28.tsv'
    only = set(argv[4].split(',')) if len(argv) > 4 else None
    vis_of = {r[0]: r[2] for r in (ln.rstrip('\n').split('\t') for ln in open(paths, encoding='utf-8')) if len(r) > 2}
    rows = [ln.rstrip('\n').split('\t') for ln in open(man, encoding='utf-8') if ln.strip()]
    skus = [r[0] for r in rows[1:] if not only or r[0] in only]
    cj = os.environ.get('CARDS_JSON')
    cards = json.load(open(cj, encoding='utf-8')) if cj else cards_from_db(skus)
    photo_dirs = [d for d in os.environ.get('PHOTO_DIRS', '').split(':') if d] or PHOTO_DIRS
    card_dir = os.path.splitext(dst)[0] + '-cards'
    out, miss, top = build(rows, col, vis_of, cards, photo_dirs, card_dir, only, set(filter(None, os.environ.get('EXCLUDE', '').split(','))), os.environ.get('VIS_ROOT'))
    json.dump(out, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump({'top_input': top}, open(os.path.splitext(dst)[0] + '.top-input.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'товаров {len(out)}; пропущено {len(miss)}', miss)
    print(f'вход 07 для верха Ш3в: карточка у {len(out) - len(top["no_card"])} из {len(out)}, фото у {len(out) - len(top["no_photo"])}; без карточки: {top["no_card"]}; без фото: {top["no_photo"]}')
    print('размеры UltraTex, МБ (5 больших):', sorted(round(os.path.getsize(v['extra_in']['ut.glb']) / 2 ** 20, 1) for v in out.values())[-5:])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
