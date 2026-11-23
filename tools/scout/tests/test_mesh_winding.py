#!/usr/bin/env python3
"""Мерка 09 «обход граней согласован + объём наружу» (T-20261123-42): куб и его порча на заглушках, без файлов и сети; ID товаров нет.
Случаи: куб наружу — 1,0 и объём > 0; куб с ОДНОЙ вывернутой гранью — несогласованные рёбра и flipped_faces; куб целиком наизнанку — обход согласован, объём < 0;
вершины, разрезанные швом развёртки (дубли позиций), склеиваются; открытая сетка → na с причиной (не «прошло»); у судьи `judge` вывернутая грань и вывернутая сетка → hard `winding`
и итог refused, чистая — ok; в реестре решений обе строки hard и порог не копируется. Запуск: python tools/scout/tests/test_mesh_winding.py (нужен numpy)"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import numpy as np  # noqa: E402
import mesh_winding as MW  # noqa: E402
import paint_decisions as PD  # noqa: E402
import paint_surface_checks as P  # noqa: E402

FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
# 12 граней, нормали НАРУЖУ (против часовой стрелки, если смотреть снаружи)
F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], int)

a = MW.analyze(V, F)
ok(a['status'] == 'ok' and a['consistency'] == 1.0 and a['flipped_faces_pct'] == 0.0, f'куб наружу: согласован ({a.get("consistency")})')
ok(abs(a['volume_rel'] - 1.0 / 1.0 * (1.0 / 1.0)) < 1e-9 or a['volume_rel'] > 0.9, f'объём куба / габарит ≈ 1 ({a["volume_rel"]})')

F1 = F.copy()
F1[5] = F1[5][::-1]                                                  # ОДНА вывернутая грань
b = MW.analyze(V, F1)
ok(b['consistency'] < 0.99 and b['flipped_faces_pct'] > 0, f'одна вывернутая грань видна: согласованность {b["consistency"]}, вывернутых граней {b["flipped_faces_pct"]} %')
ok(b['volume_rel'] > 0, 'одна грань объём куба не переворачивает (объём всё ещё > 0 — поэтому нужна и мерка согласованности)')

c = MW.analyze(V, F[:, ::-1])                                        # сетка целиком наизнанку
ok(c['consistency'] == 1.0 and c['volume_rel'] < 0, f'куб наизнанку: обход согласован, объём < 0 ({c["volume_rel"]}) — ловит мерка объёма')

# вершины, разрезанные швом развёртки: каждая грань со своими 3 вершинами (дубли позиций) — склейка по положению даёт тот же результат
Vs = V[F].reshape(-1, 3)
Fs = np.arange(len(Vs)).reshape(-1, 3)
d = MW.analyze(Vs, Fs)
ok(d['status'] == 'ok' and d['consistency'] == 1.0 and d['volume_rel'] > 0, 'вершины-дубли (шов развёртки) склеены по положению: куб согласован')
Fs2 = Fs.copy()
Fs2[5] = Fs2[5][::-1]
ok(MW.analyze(Vs, Fs2)['consistency'] < 0.99, 'выворот грани виден и на разрезанных вершинах')

e = MW.analyze(V, F[:2])                                             # две грани — не замкнутая сетка
ok(e['status'] == 'na' and 'мен' in e['why'], f'меньше 4 граней → na с причиной ({e.get("why")})')
f = MW.analyze(V, F[:8])
ok(f['status'] == 'ok' and f['boundary_pct'] > 0, f'открытая сетка: граница справочно ({f.get("boundary_pct")} %), согласованность считается по парным рёбрам')

# судья этапа 09: порог из rules, hard → refused
R = P.rules()
cl = {'top_vs_photo': {'status': 'na', 'why': 'нет'}, 'empty_flat': {'status': 'na'}, 'group_bleed': {'status': 'na'}}
good = P.judge(dict(cl, winding=a), R)
ok(good['status'] == 'ok' and good['metrics']['winding_consistency']['ok'] and good['metrics']['winding_volume_rel']['ok'], 'чистая сетка: winding в пороге, итог ok')
badf = P.judge(dict(cl, winding=b), R)
ok(badf['status'] == 'refused' and 'winding' in badf['hard_failed'], f'вывернутая грань → hard winding, итог {badf["status"]}')
badv = P.judge(dict(cl, winding=c), R)
ok(badv['status'] == 'refused' and 'winding' in badv['hard_failed'] and badv['metrics']['winding_consistency']['ok'] and not badv['metrics']['winding_volume_rel']['ok'], 'сетка наизнанку → hard winding по объёму')
none = P.judge(dict(cl), R)
ok(none['metrics']['winding_consistency']['value'] is None and 'error' in none['metrics']['winding_consistency'] and none['status'] != 'refused', 'нет результата мерки → «не посчитано» (error), а не прошло и не отказ')
na = P.judge(dict(cl, winding=e), R)
ok('na' in na['metrics']['winding_volume_rel'] and na['status'] != 'refused', 'сетка без пар рёбер → na с причиной')
msg = P.classify(None, None, None)
ok(msg['status'] == 'missing', 'нет GLB → missing (как раньше)')

# правила и реестр
ok(R['winding']['consistency_min'] < 1.0 and R['winding']['soft'] is False, 'правило: порог < 1,0 (шум склейки), жёсткое (soft=false)')
txt = open(P.RULES, encoding='utf-8').read() + open(PD.RULES, encoding='utf-8').read()
ok(not re.search(r'\b\d{5,6}_\d{6,}\b', txt), 'ID товаров в правилах нет')
REG = PD.load()
ids = {x['id']: x for x in REG['decisions']}
ok(all(k in ids and ids[k]['severity'] == 'hard' and ids[k]['stage'] == 'surface' for k in ('09.winding_consistency', '09.winding_volume')), 'в реестре решений обе строки winding — hard, этап surface')
ok(all('threshold' not in json.dumps(ids[k]).replace('threshold_ref', '') for k in ('09.winding_consistency', '09.winding_volume')), 'порог в реестре — ссылкой, не числом')
sv = {'stage': 'surface', 'status': 'refused', 'reason': '', 'metrics': {k: v for k, v in badf['metrics'].items()}}
dd = PD.decide_one(ids['09.winding_consistency'], {}, {'surface': sv})
ok(dd['state'] == 'fail', f'решение 09.winding_consistency на вывернутой грани: {dd["state"]}')
dg = PD.decide_one(ids['09.winding_consistency'], {}, {'surface': {'stage': 'surface', 'status': 'ok', 'metrics': good['metrics']}})
ok(dg['state'] == 'pass', f'на чистой — {dg["state"]}')

print('FAIL' if FAIL else 'ВСЁ ЗЕЛЁНОЕ', FAIL)
sys.exit(1 if FAIL else 0)
