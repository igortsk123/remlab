"""ГЕЙТ ЗАПИСИ ПЕРЕКРАСКИ ПО ВАРИАНТАМ СЕМЬИ (`salad/recolor_variants_gate.py`, T-20261119-03/1): без базы, сети и мешей — цвета меша и «фото»
вариантов заданы числами (фото — однотонные вырезки PNG), правила — настоящие `rules/mesh-color-guard.json`, вердикты — настоящий `mesh_color_check.judge`.
Числа — из замеров 18–19.11 (T-52/5): ① семья с тёмным представителем и светлыми вариантами (шкаф) — ОТКАЗ: два варианта упираются в потолок множителя
и темнеют, один ok→mismatch; ② семья дивана с четырьмя вариантами — ПРОПУСК: улучшение или то же, горчичный и до, и после «расхождение»;
③ диван с кремовым вариантом — ОТКАЗ (новый потолок); ④ семья, где все варианты и так в расхождении, — пропуск; ⑤ защитные: нет вариантов, цвет не менялся,
вариант без фото не считается, нет таблицы — ok=None (запись без прогноза не идёт), порядок причин, текст отказа.
    python tools/scout/tests/test_recolor_variants_gate.py   (нужны numpy и pillow)"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
sys.path.insert(0, os.path.join(HERE, '..'))
import recolor_variants_gate as G  # noqa: E402
import remlab_tmp  # noqa: E402
TMP = remlab_tmp.use('test_recolor_variants_gate')   # временное — на диске, убирается при выходе (T-20261107-13)

fails = []


def check(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))
    if not cond:
        fails.append(name)


def photos(colours: dict) -> dict:
    """Однотонные вырезки (прозрачный фон, товар в центре) → {sku: путь}; None — фото нет."""
    out = {}
    for sku, rgb in colours.items():
        if rgb is None:
            out[sku] = None
            continue
        a = np.zeros((120, 160, 4), np.uint8)
        a[20:100, 30:130] = (*rgb, 255)
        p = os.path.join(TMP, sku.replace(':', '_') + '.png')
        Image.fromarray(a, 'RGBA').save(p)
        out[sku] = p
    return out


# ── ① шкаф №37: тёмный представитель, три светлых варианта — отказ ──
V37 = {'f:v1': (176, 168, 160), 'f:v2': (200, 201, 202), 'f:v3': (216, 209, 193)}
P = photos(V37)
g = G.gate('f:rep', sorted(V37), P.get, (103, 103, 104), (83, 82, 80))
check('шкаф: отказ (варианты уходят в потолок множителя)', g['ok'] is False, str(g['reasons'])[:200])
check('шкаф: у двух вариантов новый упор «потолок» (у третьего потолок был и до перекраски — его причина другая)',
      sum('потолок' in r for r in g['reasons']) == 2 and not any('f:v3' in r and 'потолок' in r for r in g['reasons']), str(g['reasons'])[:300])
check('шкаф: у светлейшего варианта ещё и ok → mismatch', any('f:v3' in r and 'ok → mismatch' in r for r in g['reasons']), str(g['reasons'])[:300])
check('шкаф: в отчёте есть до/после по каждому', len(g['per_variant']) == 3 and all('before' in x and 'after' in x for x in g['per_variant']))

# ── ② диван №54: перекраска не вредит вариантам (горчичный и до, и после mismatch) — пропуск ──
V54 = {'f:a': (146, 135, 129), 'f:b': (125, 125, 126), 'f:c': (179, 126, 48), 'f:d': (114, 137, 141)}
P = photos(V54)
g = G.gate('f:rep', sorted(V54), P.get, (188, 143, 150), (134, 102, 105))
check('диван с четырьмя вариантами: пропуск', g['ok'] is True, str(g['reasons'])[:300])
check('диван: горчичный и до, и после расхождение — не в счёт',
      [x for x in g['per_variant'] if x['sku'] == 'f:c'][0]['before']['verdict'] == 'mismatch'
      and [x for x in g['per_variant'] if x['sku'] == 'f:c'][0]['after']['verdict'] == 'mismatch' and not g['reasons'])
check('диван: у ok-вариантов после перекраски упора нет', all(not x['after']['упор'] for x in g['per_variant'] if x['sku'] != 'f:c'))

# ── ③ диван №35: кремовый вариант упирается в потолок — отказ ──
V35 = {'f:g': (95, 95, 97), 'f:c': (212, 201, 190)}
P = photos(V35)
g = G.gate('f:rep', sorted(V35), P.get, (165, 151, 142), (102, 91, 86))
check('диван с кремовым вариантом: отказ', g['ok'] is False and any('f:c' in r and 'потолок' in r for r in g['reasons']), str(g['reasons'])[:300])
check('диван: графитовый вариант в причинах не фигурирует', not any('f:g' in r for r in g['reasons']))

# ── ④ все варианты уже в расхождении (№34): «не хуже» — пропуск ──
V34 = {'f:p': (221, 215, 205), 'f:q': (72, 77, 73)}
P = photos(V34)
g = G.gate('f:rep', sorted(V34), P.get, (209, 71, 91), (101, 22, 29))
check('все варианты и до, и после mismatch: пропуск', g['ok'] is True and not g['reasons'], str(g['reasons'])[:200])

# ── ⑤ защитные ──
g = G.gate('f:rep', [], {}.get, (100, 100, 100), (90, 90, 90))
check('нет вариантов — пропуск, 0 вариантов', g['ok'] is True and g['n_variants'] == 0 and 'нет вариантов' in g['note'])
P = photos(V37)
g = G.gate('f:rep', sorted(V37), P.get, (103, 103, 104), (103, 103, 104))
check('цвет меша не менялся — отказа нет', g['ok'] is True, str(g['reasons'])[:200])
P = photos({'f:v1': (176, 168, 160), 'f:v2': None})
g = G.gate('f:rep', ['f:v1', 'f:v2'], P.get, (103, 103, 104), (103, 103, 104))
check('вариант без фото не считается (unknown), остальные считаются', g['ok'] is True and len(g['per_variant']) == 2, str(g['per_variant'][1]['after']['verdict']))
P = photos({'f:v1': None, 'f:v2': None})
g = G.gate('f:rep', ['f:v1', 'f:v2'], P.get, (103, 103, 104), (83, 82, 80))
check('фото нет ни у одного варианта — ok=None (пустое «не хуже» за пропуск не считаем)', g['ok'] is None and 'фото вариантов не найдены' in g['reasons'][0], str(g['reasons']))
rows = {'f:rep': {'owner': 'f:rep', 'via_family': False}, 'f:v1': {'owner': 'f:rep', 'via_family': True}, 'f:v2': {'owner': 'f:rep', 'via_family': True},
        'g:x': {'owner': 'g:rep', 'via_family': True}, 'f:rep2': {'owner': 'f:rep', 'via_family': False}}
check('варианты семьи: только owner = семья и через семью, без представителя', G.family_variants('f:rep', rows) == ['f:v1', 'f:v2'])
g = G.gate_for_family('f:rep', 'нет.glb', 'нет.glb', table_path=os.path.join(TMP, 'нет-таблицы.json'))
check('нет таблицы цвета — ok=None (запись без прогноза не идёт)', g['ok'] is None and 'нет таблицы' in g['reasons'][0], str(g))
g = G.gate_for_family('f:rep', 'нет.glb', 'нет.glb', rows={'f:rep': {'owner': 'f:rep', 'via_family': False}})
check('в таблице нет вариантов — пропуск без чтения мешей', g['ok'] is True and g['n_variants'] == 0, str(g))
g = G.gate_for_family('f:rep', 'нет.glb', 'нет.glb', rows=rows, photo_of={}.get)
check('меш не открылся — ok=None с причиной', g['ok'] is None and g['reasons'], str(g)[:200])
check('текст отказа — одной строкой с причиной', G.refusal_text({'reasons': ['f:v1: новый упор: потолок']}).startswith('варианты семьи — f:v1'))

# ── ⑥ путь записи `recolor_put_v2.put`: шкаф №37 — отказ без единой записи, диван №54 — пропуск и запись, --no-gate, выбор поколения ──
import json  # noqa: E402
import recolor_put_v2 as PUT  # noqa: E402

ROOT = os.path.join(TMP, 'v2')


def make_gen(sku: str, gens: dict) -> None:
    for gname, body in gens.items():
        d = f'{ROOT}/{sku.replace(":", "_")}/{gname}'
        os.makedirs(d, exist_ok=True)
        open(f'{d}/model.glb', 'wb').write(body)
        json.dump({'seed': 1}, open(f'{d}/manifest.json', 'w'))


def stub(photos_of, old, new):
    """Гейт с настоящей `gate` на заданных числах (вместо чтения таблицы и мешей с диска)."""
    return lambda fam, nglb, oglb, tp: G.gate(fam, sorted(photos_of), photos(photos_of).get, old, new)


new_glb = os.path.join(TMP, 'новый.glb')
open(new_glb, 'wb').write(b'NEW-GLB')
make_gen('f:cab', {'g1': b'OLD-37'})
r = PUT.put('f:cab', new_glb, 37, root=ROOT, apply=True, gate_fn=stub(V37, (103, 103, 104), (83, 82, 80)))
check('запись №37 (шкаф): гейт отказал', r['refused'] is True and not r['ok'], str(r['gate']['reasons'])[:120])
check('запись №37: model.glb не тронут, orig и manifest.pre-recolor не созданы',
      open(f'{ROOT}/f_cab/g1/model.glb', 'rb').read() == b'OLD-37' and not os.path.exists(f'{ROOT}/f_cab/g1/model.orig.glb')
      and not os.path.exists(f'{ROOT}/f_cab/g1/manifest.pre-recolor.json') and 'recolor' not in json.load(open(f'{ROOT}/f_cab/g1/manifest.json')))
make_gen('f:sofa', {'g1': b'OLD-54'})
r = PUT.put('f:sofa', new_glb, 54, root=ROOT, apply=True, gate_fn=stub(V54, (188, 143, 150), (134, 102, 105)))
man = json.load(open(f'{ROOT}/f_sofa/g1/manifest.json'))
check('запись №54 (диван): гейт пропустил, записано', r['ok'] and not r['refused'] and open(f'{ROOT}/f_sofa/g1/model.glb', 'rb').read() == b'NEW-GLB')
check('запись №54: orig = старый файл, в manifest.recolor — результат гейта',
      open(f'{ROOT}/f_sofa/g1/model.orig.glb', 'rb').read() == b'OLD-54' and man['recolor']['variants_gate']['ok'] is True
      and man['recolor']['variants_gate']['n_variants'] == 4 and man['recolor']['task'] == PUT.TASK)
make_gen('f:dry', {'g1': b'OLD'})
r = PUT.put('f:dry', new_glb, 1, root=ROOT, apply=False, gate_fn=stub(V54, (188, 143, 150), (134, 102, 105)))
check('сухой прогон: гейт считается, ничего не пишется', r['ok'] and r['dry'] and open(f'{ROOT}/f_dry/g1/model.glb', 'rb').read() == b'OLD')
make_gen('f:nogate', {'g1': b'OLD'})
r = PUT.put('f:nogate', new_glb, 1, root=ROOT, apply=True, use_gate=False, gate_fn=stub(V37, (103, 103, 104), (83, 82, 80)))
check('--no-gate: гейт не вызывается, запись идёт, в manifest — variants_gate=null',
      r['ok'] and json.load(open(f'{ROOT}/f_nogate/g1/manifest.json'))['recolor']['variants_gate'] is None)
make_gen('f:unk', {'g1': b'OLD'})
r = PUT.put('f:unk', new_glb, 1, root=ROOT, apply=True, gate_fn=lambda *a: {'ok': None, 'reasons': ['нет таблицы цвета вариантов (mesh_colour_missing)']})
check('гейт не посчитался (ok=None) — отказ записи, без прогноза не пишем',
      r['refused'] and open(f'{ROOT}/f_unk/g1/model.glb', 'rb').read() == b'OLD')
make_gen('f:multi', {'g1': b'A', 'g2': b'B'})
try:
    PUT.pick_generation('f:multi', None, ROOT)
    check('несколько поколений без --gen — отказ', False)
except AssertionError as e:
    check('несколько поколений без --gen — отказ', 'укажи живое' in str(e))
check('--gen выбирает указанное поколение', PUT.pick_generation('f:multi', 'g2', ROOT).endswith('/f_multi/g2'))
rj = os.path.join(TMP, 'results-0.json')
json.dump([{'k': 5, 'was': {'de_med': 24.51}, 'now': {'de_med': 3.75}}, {'k': 6}], open(rj, 'w'))
check('ΔE00 было/стало — из results-N.json по k', PUT.de_of(rj, 5) == (24.51, 3.75) and PUT.de_of(rj, 7) == (None, None) and PUT.de_of(None, 5) == (None, None))

print('\nПРОВАЛЕНО: ' + ', '.join(fails) if fails else '\nвсё прошло')
sys.exit(1 if fails else 0)
