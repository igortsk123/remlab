"""ПРОБА T-20261117-02/3: свод по ВСЕМ наборам гостиных и спален /demo — что в списке, что в 3D (по сцене, собранной движком /demo), чем представлено.
  python3 audit_all.py <demo-data.json> <папка с v00/…/scene_info.json от demo_scene_dump.mjs> <выход README.md> [<mesh3d-cache>]
Правила отбора (`in3dDecor`, `isCloth3d`, `liveDecor`) — как на странице (`tools/scout/flat215-demo/index.html:5835`), здесь они только читаются."""
import json
import os
import re
import sys
from collections import Counter, defaultdict

dataf, root, out = sys.argv[1], sys.argv[2], sys.argv[3]
cache = sys.argv[4] if len(sys.argv) > 4 else os.path.expanduser('~/scout-scenes/mesh3d-cache')
D = json.load(open(dataf, encoding='utf-8'))
SOFT = (D.get('rules') or {}).get('soft_roles') or ['плед', 'подушка', 'покрывало', 'полка', 'шторы']
base = lambda r: re.sub(r'\s+\d+$', '', str(r or '')).strip()


def has_mesh(sk):
    sid = (sk or {}).get('msid')
    return bool(sid) and os.path.exists(os.path.join(cache, sid + '.glb'))


def cloth3d(x):
    p, l, k = x.get('place') or {}, x.get('look') or {}, x.get('sku') or {}
    return (not x.get('list_only') and x.get('strategy') == 'textile_abstract' and bool(k.get('name')) and p.get('kind') in ('curtain', 'throw', 'pillow')
            and bool(re.match(r'^#[0-9a-fA-F]{6}$', l.get('hex') or '')) and l.get('of') == str(k.get('sid') or k.get('name') or ''))


def kind_of(role, decor):
    b = base(role)
    if b == 'ваза':
        return 'ваза'
    if b in ('кашпо',) or 'растен' in b or 'цвет' in b:
        return 'растение / кашпо'
    if b == 'картина':
        return 'картина'
    if b == 'лампа':
        return 'лампа настольная (на комоде)'
    if b == 'торшер':
        return 'торшер'
    if b == 'люстра':
        return 'люстра'
    if b == 'шторы':
        return 'штора'
    if b in ('плед', 'покрывало'):
        return 'плед'
    if b == 'подушка':
        return 'подушка'
    if b == 'ковёр':
        return 'ковёр'
    return 'мелочь (прочий декор)' if decor else 'мебель'


rows = []   # (вариант, комната, стиль, тип позиции, вид, роль, товар, в3D, чем, причина)
for idx, v in enumerate(D['variants']):
    pf = os.path.join(root, f'v{idx:02d}', 'scene_info.json')
    if not os.path.exists(pf):
        continue
    info = json.load(open(pf, encoding='utf-8'))
    slots = {s['role']: s for s in info['slots']}
    slots_by_tail = {s['slotId'].split('#')[0].split(':')[-1]: s for s in info['slots']}
    for kind, lst in (('мебель', v['items']), ('декор', v.get('decor') or [])):
        for it in lst:
            sk = it.get('sku') or {}
            role = it['role']
            s = slots.get(role) or slots_by_tail.get(role)
            strat = it.get('strategy')
            why, how = '', ''
            if kind == 'декор':
                if it.get('list_only'):
                    why = 'list_only'
                elif base(role) in SOFT and not cloth3d(it):
                    why = 'мягкое без места/цвета (demo-24)'
            if not why and s is None:
                why = 'нет меша' if not has_mesh(sk) and strat not in ('procedural_plane', 'textile_abstract') else 'не поставлено (нет места/опоры)'
            if not why and s.get('unplaced'):
                why = 'не повешено (нет места)'
            if not why:
                if base(role) == 'ковёр':
                    how = 'плоскость с фото товара'
                elif strat == 'procedural_plane':
                    how = 'плоскость с фото + рамка'
                elif strat == 'textile_abstract':
                    how = 'меш товара' if (has_mesh(sk) and (it.get('place') or {}).get('kind') == 'pillow') else 'условная ткань цветом товара'
                else:
                    how = 'меш товара' if has_mesh(sk) else 'коробка (меша нет)'
            rows.append((v['id'], v.get('room_id'), v['style'], kind, kind_of(role, kind == 'декор'), role, (sk.get('name') or '')[:50], not why, how, why))

L = []
L.append('# Аудит всех наборов /demo: что в 3D и чем представлено (T-20261117-02/3)\n')
L.append('Сцена каждого варианта собрана движком /demo (headless Chromium, `demo_scene_dump.mjs`); «в 3D» = позиция есть среди мест сцены и не помечена '
         '«не повешено». Коробка = модели нет, /demo рисует коробку габарита. 0 ₽, код проекта не менялся.\n')
L.append('## 1. По наборам\n')
L.append('| набор | комната | стиль | позиций в списке | в 3D | меш | плоскость/рамка | условная ткань | коробка | нет в 3D (почему) |\n|---|---|---|---:|---:|---:|---:|---:|---:|---|')
byv = defaultdict(list)
for r in rows:
    byv[r[0]].append(r)
for vid, rs in byv.items():
    c = Counter(r[8] for r in rs if r[7])
    miss = '; '.join(f'{r[5]} ({r[9]})' for r in rs if not r[7]) or '—'
    plane = c['плоскость с фото товара'] + c['плоскость с фото + рамка']
    L.append(f'| {vid} | {rs[0][1]} | {rs[0][2]} | {len(rs)} | {sum(r[7] for r in rs)} | {c["меш товара"]} | {plane} | {c["условная ткань цветом товара"]} | {c["коробка (меша нет)"]} | {miss} |')
L.append('\n## 2. По типам предметов (все наборы вместе)\n')
L.append('| тип | всего в списках | в 3D | как представлено | не в 3D — почему |\n|---|---:|---:|---|---|')
order = ['ваза', 'растение / кашпо', 'картина', 'лампа настольная (на комоде)', 'торшер', 'люстра', 'штора', 'плед', 'подушка', 'ковёр', 'мелочь (прочий декор)']
byk = defaultdict(list)
for r in rows:
    byk[r[4]].append(r)
for k in order + ['мебель']:
    rs = byk.get(k, [])
    if not rs:
        L.append(f'| {k} | 0 | 0 | в данных наборов таких позиций нет | — |')
        continue
    hows = Counter(r[8] for r in rs if r[7])
    why = Counter(r[9] for r in rs if not r[7])
    L.append(f'| {k} | {len(rs)} | {sum(r[7] for r in rs)} | ' + (', '.join(f'{h} {n}' for h, n in hows.items()) or '—') + ' | ' + (', '.join(f'{w} {n}' for w, n in why.items()) or '—') + ' |')
tot, t3 = len(rows), sum(r[7] for r in rows)
L.append(f'\nИтого: позиций {tot}, в 3D {t3}, не в 3D {tot - t3}. Наборов: {len(byv)}.\n')
open(out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('\n'.join(L))
