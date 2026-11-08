#!/usr/bin/env python3
"""Глубина «для сцены» в сборке демо (T-20261107-25/9, план dims-effective-01): `flat215_demo.scene_dims`, копия банка для
солвера `_scene_sets`, габарит предмета `_dims_of`. Без базы и сети: строки привязки и политика подставлены.

  python3 tests_scene_dims.py
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_scene_dims')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
os.environ.setdefault('FLAT215_DEMO_OUT', os.path.join(os.environ.get('TMPDIR') or '/tmp', 'tests_scene_dims'))
import flat215_demo as FD  # noqa: E402
import room_bindings as RB  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, name: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + name, flush=True)
    if not cond:
        FAILS.append(name)


POL = RB.policy()
ROW = {'status': 'ready', 'via_family': False, 'local_3d': True, 'mesh_id': '112923_m2', 'reasons': [],
       'passport': {'effective_dims': {'d': 54, 'source': 'passport_by_mesh', 'mesh_d': 54.0, 'err': 0.0,
                                       'asset_id': 'sha256:' + 'a' * 64, 'measurement': 'raw2:t', 'catalog_w': 49}}}
FD._BIND_ROWS = {'112923:m2': ROW, '112923:sofa': {'status': 'ready', 'mesh_id': '112923_sofa', 'local_3d': True,
                                                   'passport': {}}}
FD._MESH_REP = {}
FD._EFF_POL = POL

check(POL['passport']['d_by_mesh'].get('effective') is True and POL['policy_version'] == 'v4',
      'политика: passport.d_by_mesh.effective включён, версия v4 (поле добавочное, снимок в базе годен)')
s = FD.scene_dims('112923_m2', {'w': 49, 'd': 49, 'h': 82, 'dia': None})
check(s['d'] == 54 and s['d_catalog'] == 49 and s['dims_by'] == 'паспорт по мешу' and s['w'] == 49 and s['h'] == 82,
      'стул К2: d сцены 54 (паспорт по мешу), d_catalog 49, остальное как в каталоге')
base = {'w': 200, 'd': 90, 'h': 80}
check(FD.scene_dims('112923_sofa', base) is base and FD.scene_dims('1_x', base) is base and FD.scene_dims(None, base) is base,
      'без effective_dims / без строки / без артикула — тот же объект (каталог байт в байт)')
cat_changed = {'w': 45, 'd': 45, 'h': 82}
check(FD.scene_dims('112923_m2', cat_changed) is cat_changed, 'ширина каталога сменилась — каталог')
os.environ['FLAT215_EFFECTIVE_DIMS'] = '0'
d0 = {'w': 49, 'd': 49, 'h': 82}
check(FD.scene_dims('112923_m2', d0) is d0, 'откат FLAT215_EFFECTIVE_DIMS=0 — каталог')
del os.environ['FLAT215_EFFECTIVE_DIMS']
FD._EFF_POL = json.loads(json.dumps(POL))
FD._EFF_POL['passport']['d_by_mesh']['effective'] = False
check(FD.scene_dims('112923_m2', d0) is d0, 'откат политикой effective: false — каталог (без пересборки привязки)')
FD._EFF_POL = POL

sets = [{'style': 'сканди', 'items': {'стул': {'mid': 112923, 'eid': 'm2', 'w': 49, 'd': 49, 'h': 82, 'name': 'Марти-2'},
                                       'диван': {'mid': 112923, 'eid': 'sofa', 'w': 200, 'd': 90, 'h': 80},
                                       'ковёр': None}},
        {'style': 'пустой', 'items': {}}]
before = copy.deepcopy(sets)
out = FD._scene_sets(sets)
check(sets == before, 'копия для солвера: банк в памяти не тронут (Р1: банк = каталог)')
check(out[0]['items']['стул']['d'] == 54 and 'd_catalog' not in out[0]['items']['стул']
      and 'dims_by' not in out[0]['items']['стул'], 'копия для солвера: стул К2 с глубиной 54, служебных полей нет')
check(out[0]['items']['диван'] == sets[0]['items']['диван'] and out[0]['items']['ковёр'] is None and out[1] == sets[1],
      'копия для солвера: остальное без изменений')

sk = dict(FD.scene_dims('112923_m2', {'w': 49, 'd': 49, 'h': 82, 'dia': None}), name='Марти-2')
dm = FD._dims_of({}, sk, 'стул')
check(dm['d'] == 54 and dm['d_catalog'] == 49 and dm['dims_src'] == 'паспорт по мешу' and not dm['dims_unknown'],
      '_dims_of: глубина сцены 54, dims_src «паспорт по мешу», d_catalog для подписи')
dc = FD._dims_of({}, {'w': 200, 'd': 90, 'h': 80}, 'диван')
check(dc == {'w': 200, 'd': 90, 'h': 80, 'dims_src': 'каталог', 'dims_unknown': False},
      '_dims_of: обычный товар — как раньше, без d_catalog')

print('tests_scene_dims:', 'OK' if not FAILS else f'{len(FAILS)} FAIL')
sys.exit(1 if FAILS else 0)
