#!/usr/bin/env python3
"""Быстрый разбор сцены по ИМЕНИ из галереи (заявка владельца 12.08: он проверяет
/test/acceptance-plans/ и кидает названия вида «set6-base»).

Печатает всё, что нужно для разбора замечания: комната, применённые зоны,
что поставлено, что осталось в банке сета, пересечения и близкие пары.

  ~/venvs/scout/bin/python scene.py set6-base
  ~/venvs/scout/bin/python scene.py set6-base --why      # + причины отказов блоков
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

ZN = {'tpl': 'посадка', 'tpl-min': 'посадка(мин)', 'tv': 'медиа', 'tvfp': 'медиа+камин',
      'fp': 'камин', 'din': 'столовая', 'st': 'хранение', 'st2': 'хранение-2',
      'st3': 'хранение-3', 'pf': 'пуф', 'dc': 'декор', 'rd': 'чтение', 'qz': 'тихая',
      'notpl': 'НЕТ СХЕМЫ', 'fb': 'фолбэк'}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    sid = sys.argv[1].strip()
    rep = {}
    path = os.path.join(HERE, 'acceptance-report-zoned.jsonl')
    for line in open(path):
        if line.strip():
            r = json.loads(line)
            rep[r['scene']] = r
    r = rep.get(sid)
    if r is None:
        near = [s for s in rep if sid.split('-')[0] in s]
        print(f'сцена «{sid}» не найдена. Похожие: {near[:8]}')
        return
    n = r['set']
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    st = sets[n - 1]
    tags = (r.get('group') or '').split('+')
    zones = ' · '.join(ZN.get(t, t) for t in tags[1:]) if len(tags) > 1 else '—'
    ub = r.get('used_of_bank')
    print(f'{sid}  (сет №{n}, {st.get("m2")} м², band {st.get("band")}, '
          f'стиль {st.get("style")})')
    print(f'  зоны: {tags[0]} → {zones}')
    print(f'  из банка: {ub[0]}/{ub[1]}' if ub else '', f'| заполнение {r.get("fill_pct")}%')
    print(f'  не использовано: {r.get("unused") or r.get("skipped") or []}')

    lay_path = os.path.join(HERE, f'v3set{n}-layout-acc-zoned-{sid}.json')
    if os.path.exists(lay_path):
        from judge_layout import build_scene
        from planner.geometry import footprint
        lay = json.load(open(lay_path))
        room, ps = build_scene(lay, n)
        f = {p.role: footprint(p) for p in ps}
        print(f'  комната {room.width_cm:.0f}×{room.depth_cm:.0f} см; поставлено '
              f'{len(ps)}: {", ".join(p.role for p in ps)}')
        for i, a in enumerate(ps):
            for bb in ps[i + 1:]:
                ov = f[a.role].intersection(f[bb.role]).area / 1e4
                if ov > 0.01 and 'ковёр' not in (a.role, bb.role):
                    print(f'    ⚠ пересечение {a.role} × {bb.role}: {ov:.2f} м²')
                if ov > 0.01 and 'ковёр' in (a.role, bb.role):
                    other = bb.role if a.role == 'ковёр' else a.role
                    print(f'    ковёр под «{other}»: {ov:.2f} м²')
    if '--why' in sys.argv:
        print('\n  причины отказов блоков:')
        env = dict(os.environ, ZONES_DEBUG='1', LAYOUT_ENGINE='zoned',
                   LAYOUT_SUFFIX=f'-why-{sid}')
        out = subprocess.run(
            [os.path.expanduser('~/venvs/scout/bin/python'),
             os.path.join(HERE, 'solver_run.py'), str(n), '--v3'],
            capture_output=True, text=True, env=env, cwd=HERE, timeout=600).stderr
        for line in out.splitlines():
            if 'ZDBG' in line:
                print('   ', line.replace('ZDBG ', ''))


if __name__ == '__main__':
    main()
