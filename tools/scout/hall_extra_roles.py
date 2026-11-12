#!/usr/bin/env python3
"""НОВЫЕ РОЛИ ПРИХОЖЕЙ В ФИДАХ (T-20261112-72, владелец TG 907: крючки, полка, коврик — в каталог; модуль «прихожая»).
Сколько в свежих фидах товаров под новые роли прихожей и модулей «прихожая» с размерами — по магазинам и по стилю (оценка стиля есть только у товаров, прошедших в products). Без .env и без записи в базу:
разбор фидов — `load3.parse_feed` (как у `room_catalog.collect`), стиль — SELECT из product_style_scores.

  ~/venvs/scout/bin/python hall_extra_roles.py OUT_DIR      # → OUT_DIR/roles.md (счёт по ролям и стилям), roles.json
Выгрузку читает лист прихожей: hall_schemes.py OUT --extra OUT_DIR/roles.json (короткая прихожая H10). В каталог (room_catalog)
роли пока не заведены — это отдельный шаг после «ок» владельца.
"""
import glob
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(HERE, 'category-roles.json')):    # данные фидов не в git — из основной копии
    HERE = '/home/pakar/igor/remlab/tools/scout'
sys.path.insert(0, HERE)
import catalog_items as CI  # noqa: E402
import load3 as L  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

DENY = re.compile(r'ванн|полотен|кухн|кухон|рыбол|вязан|детск|игруш|для одежды в машин|авто|душ|туалет|санузл|балкон|сад|террас|'
                  r'крючок для картин|картин|штор|карниз|ёлоч|елоч|новогод|сумк|рюкзак|чехол|брелок', re.I)
RULES = {
    'крючки': re.compile(r'крючк|крючок|вешалка[- ]планка|планка с крючк|настенн\w* вешалк\w* с крючк', re.I),
    'полка': re.compile(r'полк\w*.{0,40}(прихож|шляп|головн\w* убор)|(шляпниц)|полк\w*[- ]вешалк|вешалк\w*[- ]полк|'
                        r'вешалк\w* с полк', re.I),
    'коврик': re.compile(r'(коврик|ковер|ковёр|покрыти)\w*.{0,30}(придвер|грязезащ|прихож|входн|у двери|для обуви)|'
                         r'придверн\w* коврик|коврик придверн', re.I),
    'прихожая': re.compile(r'^\s*(модульн\w* )?прихож', re.I),
}


def style_index() -> dict:
    rows = CI.fetch('select shop_mid, external_id, top_style from product_style_scores')
    return {(int(r[0]), r[1]): r[2] for r in rows}


def main():
    catrole, known = L.load_roles()
    fresh = L.load_fresh()
    styles = style_index()
    hits = defaultdict(dict)
    for z in sorted(glob.glob(os.path.join(L.FEEDS, '*.zip'))):
        fh = os.path.basename(z).split('.')[0]
        st = (fresh.get(fh) or {}).get('state')
        if st in ('broken', 'stale', 'empty') or not zipfile.is_zipfile(z):
            continue
        offs, _raw = L.parse_feed(z, catrole, known)
        for o in offs:
            nm = o.get('name') or ''
            for role, rx in RULES.items():
                if not rx.search(nm) or (role != 'прихожая' and DENY.search(nm)) or not o.get('price'):
                    continue
                p = o.get('params') or {}
                d = {k: o.get(k) for k in ('w', 'd', 'h')}
                hits[role][(o['mid'], o['eid'])] = {
                    'shop': o.get('shop'), 'name': nm, 'price': o.get('price'),
                    'dims': all(isinstance(v, (int, float)) and v > 0 for v in d.values()), 'w': d['w'], 'd': d['d'], 'h': d['h'],
                    'style': styles.get((int(o['mid']), o['eid'])), 'pic': bool(o.get('pic')), 'params': bool(p)}
    lines = ['# Новые роли прихожей в свежих фидах (T-20261112-72)', '',
             '| роль | товаров с ценой | с фото | с Ш×Г×В | с оценкой стиля | по стилям (top_style) | магазины |',
             '|---|---|---|---|---|---|---|']
    for role in RULES:
        xs = list(hits[role].values())
        sty = Counter(x['style'] for x in xs if x['style'])
        shops = Counter(x['shop'] for x in xs)
        lines.append(f"| {role} | {len(xs)} | {sum(x['pic'] for x in xs)} | {sum(x['dims'] for x in xs)} | "
                     f"{sum(1 for x in xs if x['style'])} | {', '.join(f'{k} {v}' for k, v in sty.most_common()) or '—'} | "
                     f"{', '.join(f'{k} {v}' for k, v in shops.most_common(6)) or '—'} |")
    lines.append('')
    for role in RULES:
        lines += [f'## {role} — примеры (до 15)', '']
        for (mid, eid), x in sorted(hits[role].items(), key=lambda kv: (not kv[1]['dims'], kv[1]['price']))[:15]:
            lines.append(f"- {mid}:{eid} · {x['shop']} · {x['name'][:90]} · {x['price']} ₽ · "
                         f"{'%s×%s×%s' % (x['w'], x['d'], x['h']) if x['dims'] else 'без размеров'} · стиль {x['style'] or '—'}")
        lines.append('')
    open(os.path.join(OUT, 'roles.md'), 'w', encoding='utf-8').write('\n'.join(lines))
    json.dump({r: {f'{k[0]}:{k[1]}': v for k, v in h.items()} for r, h in hits.items()},
              open(os.path.join(OUT, 'roles.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n'.join(lines[:8]))
    rc = CI.fetch("select role, count(*), count(*) filter (where w_cm>0 and d_cm>0 and h_cm>0) from room_catalog "
                  "where role in ('прихожая','вешалка','шкаф-купе') group by role order by role")
    print('room_catalog (роль, всего, с Ш×Г×В):', rc)


if __name__ == '__main__':
    main()
