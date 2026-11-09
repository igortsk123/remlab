#!/usr/bin/env python3
"""ЗАМЕР ФОТО НА ЛИСТЕ ЭТАЛОНОВ у живых вариантов демо (T-20261109-17) — бесплатно: в модель НИЧЕГО не отправляется.

Зачем: `improve_mode.paid_gate` теперь отказывает, когда у листа меньше `MIN_PHOTO_SHARE` карточек с настоящим фото. Порог не должен
остановить нормальную ночную досъёмку (`tools/ops/demo-realistic.mjs`) — её варианты и меряем.

Источники — те же, что у ночи и у покупателя:
  * опубликованное демо (`https://remont-lab.online/demo/demo-data.json`) — что видит покупатель и чем пользуется кнопка;
  * новая сборка ДО публикации (`/home/pakar/scout-scenes/flat215-demo/demo-data.json`, `DEMO_LOCAL` ночи): страница берёт её
    данные, а адрес фото строит от прода (`index.html:payload` — `base + img`), то есть фото новых товаров могут ещё не лежать там.

Позиции — как у запроса страницы (`payload().items`: роль, название товара, фото по полному адресу), фото — как у сервера
(`draft_render.photo`, экземпляр «стул 2» наследует фото роли, как `scene_from_request`), счёт — `improve_mode.sheet_counts`
(та же группировка, что у листа). Отдельно — отвечает ли прод по адресу фото прямо сейчас (кэш DEV может прятать дыру).

  ~/venvs/scout/bin/python tools/scout/paid_gate_census.py [--out DIR] [--local PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402

LIVE = 'https://remont-lab.online/demo/demo-data.json'
LOCAL = '/home/pakar/scout-scenes/flat215-demo/demo-data.json'
IMG_BASE = 'https://remont-lab.online/demo/'
OUT_ROOT = os.path.expanduser('~/remlab-logs/paid-gate')


def items_of(v: dict) -> list:
    """Позиции запроса страницы: роль, название, фото по полному адресу (`index.html:payload`)."""
    out = []
    for it in v.get('items') or []:
        sku = it.get('sku') or {}
        img = sku.get('img')
        out.append({'role': it.get('role'), 'name': sku.get('name') or None,
                    'img': (img if re.match(r'^https?:', img or '') else IMG_BASE + img) if img else None})
    return out


def photos_of(items: list) -> dict:
    """Фото как у сервера (`draft_render.scene_from_request`): по адресу, экземпляр пары — фото базовой роли."""
    ph = {it['role']: DR.photo(it['img']) for it in items if it.get('role') and it.get('img')}
    for it in items:
        r = it.get('role')
        if r and ph.get(r) is None:
            b = ph.get(DR._base_role(r))
            if b is not None:
                ph[r] = b
    return ph


def on_prod(url: str, memo: dict) -> bool:
    if url not in memo:
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'remlab-census'})
            with urllib.request.urlopen(req, timeout=15) as f:
                memo[url] = f.status == 200 and (f.headers.get('Content-Type') or '').startswith('image/')
        except Exception:  # noqa: BLE001
            memo[url] = False
    return memo[url]


def census(data: dict, source: str, memo: dict) -> list:
    rows = []
    for v in data.get('variants') or []:
        items = items_of(v)
        ph = photos_of(items)
        n, k = IM.sheet_counts(items, ph)
        named = [it for it in items if it.get('name')]
        no_photo = sorted({it['role'] for it in named if ph.get(it['role']) is None})
        no_prod = sorted({it['role'] for it in named if it.get('img') and not on_prod(it['img'], memo)})
        rows.append({'source': source, 'room': v.get('room_id') or 'living', 'style': v.get('style') or '', 'title': v.get('title') or '',
                     'id': v.get('id') or '', 'n_items': n, 'n_photos': k, 'share': round(k / n, 3) if n else 0.0,
                     'pass': bool(n) and k >= IM.MIN_PHOTO_SHARE * n, 'no_photo': no_photo, 'not_on_prod': no_prod,
                     'no_img_in_data': sorted({it['role'] for it in named if not it.get('img')})})
    return rows


def table(rows: list) -> str:
    md = ['| источник | комната | стиль | вариант | позиций | с фото | доля | порог | без фото | нет на проде |', '|' + '---|' * 10]
    for r in rows:
        md.append(f"| {r['source']} | {r['room']} | {r['style']} | {r['title']} | {r['n_items']} | {r['n_photos']} | {r['share']:.2f} | "
                  f"{'проходит' if r['pass'] else 'ОТКАЗ'} | {', '.join(r['no_photo']) or '—'} | {', '.join(r['not_on_prod']) or '—'} |")
    return '\n'.join(md) + '\n'


def new_dir(root: str) -> str:
    stem = os.path.join(root, 'run-' + datetime.now().strftime('%H%M'))
    for i in range(1, 100):
        d = stem if i == 1 else f'{stem}-{i}'
        if not os.path.exists(d):
            return d
    raise RuntimeError('нет свободного имени папки')


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description='Фото на листе эталонов у живых вариантов демо (бесплатно).')
    ap.add_argument('--out', default=None)
    ap.add_argument('--local', default=LOCAL, help='demo-data.json новой сборки (ночь до публикации); "" — не мерить')
    a = ap.parse_args(argv)
    memo, rows = {}, []
    live = json.loads(urllib.request.urlopen(LIVE, timeout=60).read().decode())
    rows += census(live, 'опубликовано', memo)
    if a.local and os.path.exists(a.local):
        rows += census(json.load(open(a.local, encoding='utf-8')), 'новая сборка', memo)
    out = a.out or new_dir(OUT_ROOT)
    os.makedirs(out, exist_ok=False)
    bad = [r for r in rows if not r['pass']]
    md = (f"# Фото на листе эталонов — замер {datetime.now().isoformat(timespec='minutes')}\n\n"
          f"Порог `improve_mode.MIN_PHOTO_SHARE` = {IM.MIN_PHOTO_SHARE}. В модель ничего не отправлено.\n\n" + table(rows) +
          f"\nвсего вариантов: {len(rows)}; ниже порога: {len(bad)}\n")
    open(os.path.join(out, 'table.md'), 'w', encoding='utf-8').write(md)
    json.dump(rows, open(os.path.join(out, 'census.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(md)
    print(f'итог: {out}')
    print('в модель НИЧЕГО не отправлено')
    return 0


if __name__ == '__main__':
    sys.exit(main())
