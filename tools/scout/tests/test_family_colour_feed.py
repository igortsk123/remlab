"""Вариант семьи на чужой модели другого цвета не идёт в ленту «Заменить» /demo и тура (T-20261112-89, владелец TG 859).

12.11 в туре ТВ-тумба «Имин 138x51 Латте» (фото 190,180,170) была зелёной: своей модели нет, сцена брала модель оливкового
варианта (текстура 99,102,68) и подкрашивала её отношением тонов двух ФОТО — видно 119,120,85 (хаки). Ночной сторож цвета судил
вариант порогом своих мешей (ΔL 44 / Δab 31,6) и пропускал (ΔL −24,5, Δab 15,4), а лента не знала отметку `family_colour_mismatch`.
Проверяем настоящие функции на подставных данных (без базы, сети и диска мешей):
  1) сторож (`mesh_color_check.judge`): подкраска от МОДЕЛИ, строгий порог варианта семьи — «Латте» mismatch;
  2) привязка (`room_bindings.measured_colour`): вердикт → отметка `mesh_color_mismatch`, вариант другой группы цвета без
     замера — `mesh_color_mismatch:unmeasured`; `colour_flagged` видит обе;
  3) лента /demo (`flat215_demo.pool_feed_check`) — «mesh_colour», проба (`trial_demo.item_has_mesh`) — модели нет;
  4) спрос (`room_mesh_demand.colour_own`, `demo_band.own_colour`) — свой меш варианту;
  5) сцена (`flat215_demo.annotate_tint`) берёт подкраску из строки замера — ту, по которой сторож судил.
    python3 tools/scout/tests/test_family_colour_feed.py"""
import os
import sys
import tempfile
import types

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_family_colour_feed')

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import demo_band as DB  # noqa: E402
import flat215_demo as FD  # noqa: E402
import mesh_color_check as M  # noqa: E402
import mesh_dark as MDK  # noqa: E402
import room_bindings as RB  # noqa: E402
import room_mesh_demand as RMD  # noqa: E402
import trial_demo as TD  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


LATTE, OLIVE = '112923:15232112731669134401', '112923:11973716130420666565'
L_, O_ = LATTE.replace(':', '_', 1), OLIVE.replace(':', '_', 1)
R = M.rules()
td = tempfile.mkdtemp(prefix='fam-colour-', dir=os.environ.get('TMPDIR'))


def card(name, rgb):
    a = np.full((80, 110, 3), 255, np.uint8)
    a[15:65, 20:90] = rgb
    p = os.path.join(td, name + '.png')
    Image.fromarray(a).save(p)
    return p


# 1) сторож
rows = M.judge([{'sku': LATTE, 'owner': OLIVE, 'via': True, 'glb': '/m/olive.glb', 'asset_id': 'sha256:olive'}],
               {'/m/olive.glb': M.summary(np.array([[99, 102, 68]] * 4))}.get, {LATTE: card('latte', [190, 180, 170])}.get, R)
row = rows[LATTE]
check('сторож: правила mcg-v2, строгий порог варианта семьи отдельно от порога своих мешей',
      R['version'] == 'mcg-v2' and R['family_thresholds']['dL'] < R['thresholds']['dL']
      and R['family_thresholds']['dab'] < R['thresholds']['dab'])
check('сторож: «Латте» подкрашена от модели (видно ≈ фото по светлоте), но оттенок мимо — mismatch',
      row['verdict'] == 'mismatch' and abs(row['seen_vs_sku']['dL']) < 5 and row['seen_vs_sku']['dab'] > R['family_thresholds']['dab'],
      str(row))
check('сторож: старое правило пропустило бы её (порог своих мешей)',
      M.verdict({'dL': -24.5, 'dab': 15.4}, R, False) == 'ok' and M.verdict({'dL': -24.5, 'dab': 15.4}, R, True) == 'mismatch')

# 2) привязка
F = types.SimpleNamespace(mesh_colour={LATTE: row})
why, warn = RB.measured_colour(LATTE, 'sha256:olive', True, F, ['family_colour_mismatch:светлый→зелёный'])
bind = {'status': 'blocked', 'via_family': True, 'mesh_id': OLIVE, 'local_3d': True,
        'reasons': ['family_colour_mismatch:светлый→зелёный'] + why}
check('привязка: вердикт замера → отметка mesh_color_mismatch, colour_flagged', why and why[0].startswith(RB.COLOUR_REASON)
      and RB.colour_flagged(bind), str(why))
why0, _ = RB.measured_colour(LATTE, 'sha256:olive', True, types.SimpleNamespace(mesh_colour={}),
                             ['family_colour_mismatch:светлый→зелёный'])
check('привязка: другая группа цвета без замера — mesh_color_mismatch:unmeasured', why0 == [f'{RB.COLOUR_REASON}:unmeasured'], str(why0))
why1, _ = RB.measured_colour(LATTE, 'sha256:olive', True, types.SimpleNamespace(mesh_colour={}), [])
check('привязка: та же группа цвета без замера — не отметка (как раньше)', why1 == [], str(why1))

# 3) лента /demo и проба
FD._BIND_ROWS = {LATTE: bind}
FD._MESH_IDX = {O_}
FD.feed_envs = lambda: ({'тв-тумба': (50, 250)}, {})
FD.color_ok = lambda msid, name: True
feed_row = {'role': 'тв-тумба', 'sid': L_, 'msid': O_, 'name': 'ТВ-тумба divan.ru Имин 138x51 Латте', 'img': 'img/x.jpg',
            'w': 138, 'd': 42, 'h': 51}
check('лента /demo (и тура — `trial_bundle.feeds_for` берёт её): «Латте» на оливковой модели — mesh_colour',
      FD.pool_feed_check(feed_row) == 'mesh_colour', FD.pool_feed_check(feed_row))
_fcm = MDK.family_colour_mismatch
MDK.family_colour_mismatch = lambda *a, **k: None          # без обогащения: судит только отметка привязки
try:
    check('проба: у «Латте» годной модели нет (ни лента, ни подмена её не возьмут)',
          not TD.item_has_mesh({'mid': '112923', 'eid': '15232112731669134401', 'name': feed_row['name']}))
finally:
    MDK.family_colour_mismatch = _fcm

# 4) спрос: свой меш
cands, own = DB.own_colour([{'sid': L_, 'msid': O_}], {L_} if RMD.colour_own(bind) else set())
check('спрос: отмеченный вариант — кандидат на СВОЙ меш (msid = свой sid)', own == {L_} and cands[0]['msid'] == L_, str(cands))

# 5) сцена берёт подкраску замера
_lt, _rt = M.load_table, FD._rep_tones
row_ok = dict(row, verdict='ok')
M.load_table = lambda path=None, R=None: ({LATTE: row_ok}, '')
FD._rep_tones = lambda need: {}
try:
    data = {'variants': [], 'feeds': {'тв-тумба': [dict(feed_row)]}}
    FD.annotate_tint(data, td)
    t = data['feeds']['тв-тумба'][0].get('tint')
    check('сцена: подкраска — из строки замера (от модели), не от тонов двух фото', t == row['tint'], f'{t} vs {row["tint"]}')
finally:
    M.load_table, FD._rep_tones = _lt, _rt

print('test_family_colour_feed:', 'OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)
