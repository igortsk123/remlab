#!/usr/bin/env python3
"""Ворота «этап красит только заявленную маску» (T-20261124-23/г; директор 24.11): общая проверка для ВСЕХ этапов ≥06 покраски.

ЗАЧЕМ. Круг 29 (T-23/в) показал: 08 цвет не меняет, а лицо портят 07b (тексели «synth») и шов после него (даже реальные тексели по фото). Без измерения «что этап
тронул сверх заявленного» такое видно только по кадрам. Здесь — прямое сравнение карты цвета ДО и ПОСЛЕ этапа по маскам этапа 6.

ЧТО СЧИТАЕТ (по каждой геометрии GLB, потом сумма; все пороги и перечень этапов — в `tools/scout/rules/stage-mask-gate.json`, не в коде):
  • (справочно) `by_prov` — [всего, изменилось] по каждому значению prov 0..4;
  • фото-тексели — `prov.png` этапа 6 со значениями из `photo_prov` (1 direct, 2 splat, 3 hole): всего / изменилось (хоть один канал RGB);
  • synth — `synth_prov` (4: тон с острого угла, не фото): всего / изменилось;
  • прочие занятые (prov 0 на гранях развёртки) — изменилось;
  • лицо по нормали (нормаль грани · ось лица ≥ `face_cos`; ось — единый свидетель `front_axis.resolve_from_files`, либо `front=(ось, знак)`): всего / изменилось, из них
    не-фото; нет оси — лицо «не измерено» (None), остальное считается.
ВОРОТА: `photo_changed` ≤ `max_changed.photo` (0). Не измерено (нет prov/текстуры, разный размер карты, сбой чтения) — `ok=None`, `unmeasured=True`: для приёмки это отказ.

Код ничего не пишет в выход этапа и не меняет покраску: `attach()` дописывает `extra.stage_mask` в check.json этапа (поле `passed` не трогает).
ID товаров в код не попадают. Запуск:
  stage_mask_gate.py measure --before a.glb --after b.glb --visible RUN/SKU/06-visible [--check06 …/check.json] [--front 2,-1] [--stage-dir DIR] [--rules R]
  stage_mask_gate.py table --run RUN_OUT_Q [--sku …] [--out table.md] [--json out.json]     # этап × товар по цепочке `chain` правил
Тесты: tests_stage_mask_gate.py."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, '..', '..'), os.path.join(HERE, '..')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
RULES_PATH = os.path.join(HERE, '..', '..', 'rules', 'stage-mask-gate.json')


def load_rules(path: str | None = None) -> dict:
    with open(path or RULES_PATH, encoding='utf-8') as f:
        return json.load(f)


def _map_path(visible: str, base: str, i: int) -> str:
    return os.path.join(visible, f'{base}.png' if i == 0 else f'{base}{i}.png')


def _load_map(visible: str, base: str, i: int, shape: tuple[int, int]) -> np.ndarray | None:
    """Карта этапа 6 для геометрии i в размер текстуры (NEAREST); нет файла — None."""
    from PIL import Image
    p = _map_path(visible, base, i)
    if not os.path.exists(p):
        return None
    a = Image.open(p).convert('L')
    if a.size != (shape[1], shape[0]):
        a = a.resize((shape[1], shape[0]), Image.NEAREST)
    return np.asarray(a)


def front_from_files(glb: str, check06: str | None) -> tuple[int, int] | None:
    """(ось 0|2, знак) лица из единого свидетеля front_axis; нет данных — None."""
    if not check06 or not os.path.exists(check06):
        return None
    try:
        import front_axis as FA
        ax = (FA.resolve_from_files(glb, check06) or {}).get('axis')
    except Exception:  # noqa: BLE001 — нет оси = лицо «не измерено», остальное считаем
        return None
    return (int(ax[0]), int(ax[1])) if ax else None


def pixel_normals_dot(g: dict, front: tuple[int, int], T: int) -> np.ndarray:
    """Для каждого пикселя карты T×T — нормаль грани · ось лица (занятый пиксель развёртки), у пустых −2."""
    import tex_coverage as TC
    F = np.asarray(g['F'], np.int64)
    UV = np.asarray(g['UV'], np.float64)
    V = np.asarray(g['V'], np.float64)
    xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    ids = np.asarray(TC.raster(xy, F, T)[0]).reshape(-1)
    n3 = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n3 = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    d = np.full(ids.shape, -2.0)
    occ = ids >= 0
    d[occ] = n3[ids[occ].astype(np.int64), front[0]] * front[1]
    return d.reshape(T, T)


def measure_arrays(tex_b: np.ndarray, tex_a: np.ndarray, prov: np.ndarray | None, face_dot: np.ndarray | None, rules: dict) -> dict:
    """Счётчики по одной геометрии; tex_* (H,W,3) uint8, prov (H,W) uint8 | None, face_dot (H,W) float | None (−2 — не занято)."""
    if tex_b.shape != tex_a.shape:
        return {'status': 'shape', 'why': f'размер карты изменился {tex_b.shape[:2]}→{tex_a.shape[:2]}'}
    if prov is None:
        return {'status': 'no_prov', 'why': 'нет prov.png этапа 6'}
    diff = (tex_b != tex_a).any(axis=2)
    photo = np.isin(prov, rules['photo_prov'])
    synth = np.isin(prov, rules['synth_prov'])
    other = ~photo & ~synth
    m = {'status': 'ok', 'photo_total': int(photo.sum()), 'photo_changed': int((photo & diff).sum()), 'synth_total': int(synth.sum()), 'synth_changed': int((synth & diff).sum()),
         'other_changed': int((other & diff).sum()), 'by_prov': {str(v): [int((prov == v).sum()), int(((prov == v) & diff).sum())] for v in range(5)}, 'face_total': None, 'face_changed': None, 'face_nonphoto_changed': None}
    if face_dot is not None:
        face = face_dot >= float(rules['face_cos'])
        m.update(face_total=int(face.sum()), face_changed=int((face & diff).sum()), face_nonphoto_changed=int((face & ~photo & diff).sum()))
    return m


_SUM = ('photo_total', 'photo_changed', 'synth_total', 'synth_changed', 'other_changed', 'face_total', 'face_changed', 'face_nonphoto_changed')


def measure(before: str, after: str, visible: str, rules: dict | None = None, front: tuple[int, int] | None = None, check06: str | None = None) -> dict:
    """Сравнение GLB до/после этапа по маскам этапа 6 → {'status': ok|unmeasured, 'why', 'geoms', счётчики…, 'front'}. Сбой чтения — unmeasured, не исключение."""
    R = rules or load_rules()
    try:
        import tex_coverage as TC
        gb, ga = TC.load_geoms(before), TC.load_geoms(after)
    except Exception as e:  # noqa: BLE001
        return {'status': 'unmeasured', 'why': f'не прочитан GLB: {type(e).__name__}: {str(e)[:160]}'}
    if len(gb) != len(ga):
        return {'status': 'unmeasured', 'why': f'число геометрий изменилось {len(gb)}→{len(ga)}'}
    if front is None:
        front = front_from_files(after, check06 or os.path.join(visible, 'check.json'))
    tot = {k: None for k in _SUM}
    by_prov: dict = {}
    for i, (b, a) in enumerate(zip(gb, ga)):
        tb, ta = b['tex'], a['tex']
        T = tb.shape[0]
        prov = _load_map(visible, 'prov', i, tb.shape[:2])
        fd = pixel_normals_dot(b, front, T) if (front is not None and tb.shape[0] == tb.shape[1] and tb.shape == ta.shape) else None
        m = measure_arrays(tb, ta, prov, fd, R)
        if m['status'] != 'ok':
            return {'status': 'unmeasured', 'why': f'геометрия {i}: {m["why"]}', 'geoms': len(gb)}
        for v, (n_, c_) in m['by_prov'].items():
            by_prov[v] = [by_prov.get(v, [0, 0])[0] + n_, by_prov.get(v, [0, 0])[1] + c_]
        for k in _SUM:
            if m[k] is None:
                continue
            tot[k] = (tot[k] or 0) + m[k]
    res = {'status': 'ok', 'geoms': len(gb), 'front': None if front is None else list(front), 'by_prov': by_prov, **tot}
    if front is None:
        res['face_note'] = 'нет оси лица — лицо не измерено'
    return res


def gate(m: dict, rules: dict | None = None) -> dict:
    """Ворота по счётчикам: ok True/False; None + unmeasured — не измерено (для приёмки отказ)."""
    R = rules or load_rules()
    if m.get('status') != 'ok':
        return {'ok': None, 'unmeasured': True, 'violations': [], 'why': m.get('why', 'не измерено')}
    v = []
    lim = int(R['max_changed']['photo'])
    if m['photo_changed'] > lim:
        v.append(f"photo_changed {m['photo_changed']} > {lim} (из {m['photo_total']})")
    return {'ok': not v, 'unmeasured': False, 'violations': v}


def attach(stage_dir: str, m: dict, g: dict) -> None:
    """Дописывает `extra.stage_mask` в `<stage_dir>/check.json` (атомарно); поле passed и остальное не трогает. Нет check.json — ничего не делает (False)."""
    p = os.path.join(stage_dir, 'check.json')
    try:
        doc = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return
    doc.setdefault('extra', {})['stage_mask'] = {**m, 'gate': g}
    fd, tmp = tempfile.mkstemp(prefix='.check-', suffix='.tmp', dir=stage_dir)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, p)


def chain_pairs(sku_dir: str, rules: dict) -> list[tuple[str, str, str]]:
    """По цепочке правил: [(этап, до, после)] — только этапы, у которых есть выход; «до» — первый существующий из кандидатов."""
    out = []
    for c in rules['chain']:
        afts = c['after'] if isinstance(c['after'], list) else [c['after']]
        aft = next((os.path.join(sku_dir, a) for a in afts if os.path.isfile(os.path.join(sku_dir, a))), None)
        bef = next((os.path.join(sku_dir, b) for b in c['before'] if os.path.isfile(os.path.join(sku_dir, b))), None)
        if aft and bef:
            out.append((c['stage'], bef, aft))
    return out


def table(run_q: str, skus: list[str] | None, rules: dict | None = None) -> dict:
    """Этап × товар по готовому выходу прогона (`<run>/out/q`): {sku: {этап: {measure, gate}}}."""
    R = rules or load_rules()
    res = {}
    for sku in sorted(skus or [d for d in os.listdir(run_q) if os.path.isdir(os.path.join(run_q, d)) and d[0].isdigit()]):
        sd = os.path.join(run_q, sku)
        vis = os.path.join(sd, '06-visible')
        res[sku] = {}
        for stage, bef, aft in chain_pairs(sd, R):
            m = measure(bef, aft, vis, R)
            res[sku][stage] = {'m': m, 'gate': gate(m, R)}
    return res


def table_md(res: dict, rules: dict | None = None) -> str:
    R = rules or load_rules()
    stages = [c['stage'] for c in R['chain']]
    lines = ['| товар | ' + ' | '.join(f'{s}: фото изм. / synth изм. / лицо изм.' for s in stages) + ' |', '|---|' + '---|' * len(stages)]
    for sku, d in res.items():
        cells = []
        for s in stages:
            r = d.get(s)
            if r is None:
                cells.append('—')
            elif r['m']['status'] != 'ok':
                cells.append('не измерено: ' + r['m'].get('why', '')[:60])
            else:
                m = r['m']
                f = '?' if m['face_changed'] is None else str(m['face_changed'])
                cells.append(('❌ ' if r['gate']['ok'] is False else '') + f"{m['photo_changed']}/{m['photo_total']} · {m['synth_changed']}/{m['synth_total']} · {f}")
        lines.append(f'| …{sku[-10:]} | ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('measure')
    p.add_argument('--before', required=True)
    p.add_argument('--after', required=True)
    p.add_argument('--visible', required=True)
    p.add_argument('--check06', default=None)
    p.add_argument('--front', default=None, help='ось,знак — например 2,-1')
    p.add_argument('--stage-dir', default=None, help='дописать extra.stage_mask в check.json этапа')
    p.add_argument('--rules', default=None)
    t = sub.add_parser('table')
    t.add_argument('--run', required=True, help='папка out/q прогона')
    t.add_argument('--sku', action='append')
    t.add_argument('--out', default=None)
    t.add_argument('--json', default=None)
    t.add_argument('--rules', default=None)
    a = ap.parse_args(argv)
    R = load_rules(a.rules)
    if a.cmd == 'measure':
        fr = tuple(int(x) for x in a.front.split(',')) if a.front else None
        m = measure(a.before, a.after, a.visible, R, fr, a.check06)
        g = gate(m, R)
        if a.stage_dir:
            attach(a.stage_dir, m, g)
        print(json.dumps({'measure': m, 'gate': g}, ensure_ascii=False))
        return 0 if g['ok'] else 1
    res = table(a.run, a.sku, R)
    md = table_md(res, R)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(md)
    if a.json:
        json.dump(res, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
