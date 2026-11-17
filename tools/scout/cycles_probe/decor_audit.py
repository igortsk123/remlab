"""ПРОБА T-20261117-02/2, п.1: аудит набора — каждая позиция (мебель и декор) → есть ли в 3D-сцене /demo, чем представлена, почему нет.
  ~/venvs/scout/bin/python cycles_probe/decor_audit.py <demo-data.json> <индекс варианта> <scene_info.json от demo_scene_dump.mjs> [<mesh3d-cache>]
Правила отбора — те же, что у страницы (`tools/scout/flat215-demo/index.html:5835` isCloth3d, `in3dDecor`), здесь они только читаются."""
import json
import os
import re
import sys

dataf, idx, infof = sys.argv[1], int(sys.argv[2]), sys.argv[3]
cache = sys.argv[4] if len(sys.argv) > 4 else os.path.expanduser('~/scout-scenes/mesh3d-cache')
D = json.load(open(dataf, encoding='utf-8'))
v = D['variants'][idx]
info = json.load(open(infof, encoding='utf-8'))
SOFT = (D.get('rules') or {}).get('soft_roles') or ['плед', 'подушка', 'покрывало', 'полка', 'шторы']
base = lambda r: re.sub(r'\s+\d+$', '', str(r or '')).strip()
slots = {s['role']: s for s in info['slots']}
nodes = info['nodes']


def has_mesh(sk):
    sid = (sk or {}).get('msid')
    return bool(sid) and os.path.exists(os.path.join(cache, sid + '.glb'))


def cloth3d(x):
    p, l, k = x.get('place') or {}, x.get('look') or {}, x.get('sku') or {}
    return (not x.get('list_only') and x.get('strategy') == 'textile_abstract' and bool(k.get('name')) and p.get('kind') in ('curtain', 'throw', 'pillow')
            and bool(re.match(r'^#[0-9a-fA-F]{6}$', l.get('hex') or '')) and l.get('of') == str(k.get('sid') or k.get('name') or ''))


rows = []
for it in v['items']:
    sk = it.get('sku') or {}
    s = slots.get(it['role'])
    how = ('меш товара' if has_mesh(sk) else 'коробка/плоскость') if s else '—'
    rows.append(('мебель', it['role'], sk.get('name', '')[:46], 'в 3D' if s else 'нет', how, '' if s else 'нет места в сцене'))
for d in v.get('decor') or []:
    sk = d.get('sku') or {}
    role, strat = d.get('role'), d.get('strategy')
    s = slots.get(role) or slots.get('decor:' + str(role)) or None
    if s is None:
        s = next((x for x in info['slots'] if x['slotId'].split('#')[0].endswith(':' + str(role))), None)
    reason = ''
    if d.get('list_only'):
        reason = 'list_only (только в списке и цене)'
    elif base(role) in SOFT and not cloth3d(d):
        reason = 'мягкое без места/цвета (demo-24): в 3D не ставится'
    elif s is None:
        reason = 'ни одно правило не дало места (не влезло / нет опоры)'
    elif s.get('unplaced'):
        reason = 'есть в сцене, но не повешено (нет места)'
    if strat == 'procedural_plane':
        how = 'плоскость с фото товара + рамка'
    elif strat == 'textile_abstract':
        how = 'меш товара' if (has_mesh(sk) and (d.get('place') or {}).get('kind') == 'pillow') else 'условная форма цветом товара'
    else:
        how = 'меш товара' if has_mesh(sk) else 'меша нет'
    rows.append(('декор', role, (sk.get('name') or '')[:46], 'в 3D' if (s and not reason) else 'нет', how if s and not reason else (how + ' (потенциально)'), reason))
print(f"вариант {v['id']} · {v['style']} · комната {v['room_id']}: мебели {len(v['items'])}, декора {len(v.get('decor') or [])}, всего позиций {len(rows)}")
print('| тип | роль | товар | в 3D /demo | чем | почему нет |\n|---|---|---|---|---|---|')
for r in rows:
    print('| ' + ' | '.join(r) + ' |')
n3d = sum(r[3] == 'в 3D' for r in rows)
print(f'\nв 3D: {n3d} из {len(rows)}; по виду: ' + ', '.join(f'{k} {sum(1 for r in rows if r[3] == "в 3D" and r[4] == k)}' for k in sorted({r[4] for r in rows if r[3] == "в 3D"})))
