#!/usr/bin/env python3
"""Property-based фаззинг солвера по легальным контурам — T3 truth-first (рефери §19).

Генерирует детерминированную серию осевых комнат (прямоугольник + ниши/выступы/эркеры),
решает зонным движком в процессе (без subprocess) и проверяет ИНВАРИАНТЫ, а не «чистоту»:
  1. no crash — ни одна легальная комната не роняет солвер исключением;
  2. determinism — повторное решение даёт побайтно те же размещения;
  3. bounded runtime — сцена решается быстрее лимита;
  4. honest ok — layout.ok=True действительно означает 0 HARD при повторной валидации.

Синтетика НЕ заменяет real-бенч (acceptance_real.py) — она ловит другой класс дефектов:
краевые формы, на которых код падает или становится недетерминированным.

  ~/venvs/scout/bin/python fuzz_rooms.py [N=60] [--time-limit 90]
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
from planner.models import Item, Opening, Room          # noqa: E402
from planner.validate import validate, Severity         # noqa: E402
from planner.zones import solve_zoned                   # noqa: E402

ITEMS = [  # типовой состав media-гостиной (typical-dims)
    ('диван', 220, 95, 85), ('тв-тумба', 160, 42, 50), ('столик', 110, 60, 42),
    ('кресло', 80, 85, 90), ('торшер', 35, 35, 160),
]


def gen_room(rng: random.Random) -> Room:
    """Легальная осевая комната: базовый прямоугольник + 0–2 ортогональные ниши/выступы."""
    w = rng.randrange(300, 700, 10)
    d = rng.randrange(280, 620, 10)
    contour = [(0, 0), (w, 0), (w, d), (0, d)]
    for _ in range(rng.randint(0, 2)):
        side = rng.choice(['n', 'e'])
        cut_w = rng.randrange(60, min(200, w // 2), 10)
        cut_d = rng.randrange(40, 120, 10)
        off = rng.randrange(50, (w if side == 'n' else d) - cut_w - 50, 10)
        if side == 'n':   # ниша/выступ по северной стене
            contour = [(0, 0), (w, 0), (w, d), (off + cut_w, d), (off + cut_w, d - cut_d),
                       (off, d - cut_d), (off, d), (0, d)]
        else:             # по восточной
            contour = [(0, 0), (w, 0), (w, off), (w - cut_d, off), (w - cut_d, off + cut_w),
                       (w, off + cut_w), (w, d), (0, d)]
        break            # одна модификация за комнату — контур остаётся простым
    door_w = 90
    door_off = rng.randrange(20, max(30, w - door_w - 40), 10)
    m2 = w * d / 10000
    band = ('14-16' if m2 <= 16 else '17-20' if m2 <= 20 else '21-25' if m2 <= 25 else
            '26-30' if m2 <= 30 else '31-40' if m2 <= 40 else '41-50' if m2 <= 50 else '50+')
    return Room(width_cm=w, depth_cm=d, band=band, contour=contour,
                openings=[Opening(kind='door', wall='south', offset_cm=door_off,
                                  width_cm=door_w, swing_cm=92)])


def placements_sig(layout) -> str:
    return '|'.join(f'{p.role}:{p.x:.0f},{p.y:.0f},{p.rot}' for p in layout.placements)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
    tl = float(sys.argv[sys.argv.index('--time-limit') + 1]) if '--time-limit' in sys.argv else 90.0
    items = [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in ITEMS]
    fails = []
    for i in range(n):
        rng = random.Random(1000 + i)      # детерминированная серия — без Date.now
        room = gen_room(rng)
        tag = f'#{i} {room.width_cm}x{room.depth_cm} ({len(room.contour or [])} вершин)'
        t0 = time.time()
        try:
            layouts1, grp = solve_zoned(room, list(items))
        except Exception as e:            # noqa: BLE001 — инвариант «no crash» и есть предмет теста
            fails.append(f'{tag}: CRASH {type(e).__name__}: {e}')
            continue
        dt = time.time() - t0
        if dt > tl:
            fails.append(f'{tag}: TIMEOUT {dt:.1f}s > {tl}')
            continue
        if not layouts1:
            continue                       # нет решения — не дефект инварианта
        best = layouts1[0]
        try:
            layouts2, _ = solve_zoned(room, list(items))
        except Exception as e:            # noqa: BLE001
            fails.append(f'{tag}: NONDETERMINISTIC CRASH on rerun: {e}')
            continue
        if not layouts2 or placements_sig(best) != placements_sig(layouts2[0]):
            fails.append(f'{tag}: NONDETERMINISTIC (повтор дал другую раскладку)')
        if best.ok:
            lay = validate(room, best.placements)
            hard = [v for v in lay.violations if v.severity is Severity.HARD]
            if hard:
                fails.append(f'{tag}: DISHONEST ok=True при HARD {[v.code for v in hard]}')
        if (i + 1) % 10 == 0:
            print(f'  {i + 1}/{n}... (последняя {dt:.1f}s, группа {grp})', flush=True)
    print(f'\nфаззинг: {n} комнат, инвариант-провалов {len(fails)}')
    for f in fails[:15]:
        print(' ', f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
