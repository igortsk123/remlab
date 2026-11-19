#!/usr/bin/env python3
"""T-20261118-52/5, T-20261119-03/1: ЗАПИСЬ ПЕРЕКРАШЕННОГО GLB В ИСТОЧНИК ПОКОЛЕНИЯ v2 — с ГЕЙТОМ по вариантам семьи. Ничего не удаляет.

  ~/venvs/scout/bin/python recolor_put_v2.py <sku> <новый.glb> <k> [--gen ПОКОЛЕНИЕ] [--result results-N.json] [--apply] [--no-gate]

Поколение: `--gen` (живое — то, чей sha совпадает в реестре, привязке, галерее и на проде) или единственное поколение с `model.glb` (больше одного
без `--gen` — отказ). ΔE00 «было/стало» — из записи `k` файла `--result` (`recolor_lp.py run`: `was.de_med`/`now.de_med`).
ГЕЙТ (`recolor_variants_gate.py`): если у семейства есть варианты с подкраской и после перекраски хоть у одного стало хуже, чем без неё (новый упор
множителя в потолок/пол/SPREAD, ok → не ok, новое расхождение) — запись ОТКАЗАНА, код 3, причины построчно; `--no-gate` — только по слову директора.
Гейт не смог посчитаться (нет таблицы цвета, меш не открылся) — тоже отказ: без прогноза не пишем. Гейт идёт и в сухом прогоне (без `--apply`).
Шаги записи: model.orig.glb ← копия текущего model.glb (если ещё нет); manifest.pre-recolor.json (если нет); model.glb ← новый (tmp + rename);
manifest.json: поле `recolor` {status, de_was, de_now, sha_before, sha_after, source, task, at, variants_gate}. Откат — `recolor_rollback.sh`.
Дальше — окно без волны: ingest_registry → recolor_carry_orientation → room_bindings --build → gallery_build → rsync -c → runtime_mesh."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import recolor_variants_gate as GATE  # noqa: E402

V2 = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
TASK = 'T-20261119-03/1'


def sha(p: str) -> str:
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def pick_generation(sku: str, gen: str | None, root: str | None = None) -> str:
    """Каталог поколения: явный `gen` или единственное с model.glb (иначе AssertionError с перечнем)."""
    base = f'{root or V2}/{sku.replace(":", "_")}'
    have = [d for d in sorted(os.listdir(base)) if os.path.exists(f'{base}/{d}/model.glb')]
    if gen:
        assert gen in have, f'поколения {gen} с моделью нет: {have}'
        return f'{base}/{gen}'
    assert len(have) == 1, f'поколений с моделью: {have} — укажи живое через --gen'
    return f'{base}/{have[0]}'


def de_of(result: str | None, k: int) -> tuple:
    """(de_was, de_now) записи k из results-N.json recolor_lp; нет файла — None."""
    if not result:
        return None, None
    for r in json.load(open(result, encoding='utf-8')):
        if r.get('k') == k:
            return (r.get('was') or {}).get('de_med'), (r.get('now') or {}).get('de_med')
    return None, None


def put(sku: str, new: str, k: int, gen: str | None = None, result: str | None = None, apply: bool = False, use_gate: bool = True,
        root: str | None = None, table_path: str | None = None, gate_fn=None) -> dict:
    """→ {'ok', 'refused', 'gate', 'dir', 'rec'}; refused=True — гейт отказал (ничего не записано)."""
    g_dir = pick_generation(sku, gen, root)
    before, after = sha(f'{g_dir}/model.glb'), sha(new)
    assert before != after, 'файл тот же'
    gate = None
    if use_gate:
        gate = (gate_fn or GATE.gate_for_family)(sku, new, f'{g_dir}/model.glb', table_path)
        if not gate.get('ok'):
            return {'ok': False, 'refused': True, 'gate': gate, 'dir': g_dir}
    de_was, de_now = de_of(result, k)
    rec = {'status': 'ok', 'de_was': de_was, 'de_now': de_now, 'sha_before': before, 'sha_after': after, 'source': os.path.basename(new),
           'task': TASK, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'variants_gate': (None if gate is None else {'ok': gate['ok'], 'n_variants': gate.get('n_variants'), 'reasons': gate.get('reasons')})}
    if not apply:
        return {'ok': True, 'refused': False, 'gate': gate, 'dir': g_dir, 'rec': rec, 'dry': True}
    orig = f'{g_dir}/model.orig.glb'
    if not os.path.exists(orig):
        shutil.copy2(f'{g_dir}/model.glb', orig)
    assert sha(orig) == before or sha(orig) != after, 'orig'
    shutil.copy2(new, f'{g_dir}/model.glb.tmp')
    os.replace(f'{g_dir}/model.glb.tmp', f'{g_dir}/model.glb')
    mp = f'{g_dir}/manifest.json'
    if not os.path.exists(f'{g_dir}/manifest.pre-recolor.json'):
        shutil.copy2(mp, f'{g_dir}/manifest.pre-recolor.json')
    man = json.load(open(mp, encoding='utf-8'))
    man['recolor'] = rec
    json.dump(man, open(mp + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(mp + '.tmp', mp)
    return {'ok': True, 'refused': False, 'gate': gate, 'dir': g_dir, 'rec': rec, 'dry': False}


def main() -> int:
    a = sys.argv[1:]
    if len(a) < 3:
        print(__doc__)
        return 2

    def opt(name):
        return a[a.index(name) + 1] if name in a else None
    sku, new, k = a[0], a[1], int(a[2])
    res = put(sku, new, k, opt('--gen'), opt('--result'), '--apply' in a, '--no-gate' not in a)
    print('поколение', res['dir'])
    g = res.get('gate')
    if res['refused']:
        print('ОТКАЗ записи: ' + GATE.refusal_text(g))
        print(json.dumps(g, ensure_ascii=False))
        return 3
    if g is not None:
        print('гейт вариантов: ok, вариантов %s' % g.get('n_variants'))
    print('recolor', json.dumps(res['rec'], ensure_ascii=False))
    print('(сухо)' if res['dry'] else 'записано: model.glb sha %s' % res['rec']['sha_after'][:16])
    return 0


if __name__ == '__main__':
    sys.exit(main())
