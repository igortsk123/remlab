#!/usr/bin/env python3
"""Гейт плоской формы — проверка на синтетических телах, без нод и GPU.

Гейт задумывался против кейса «кашпо вышло доской» (Codex q26). 01.09 выяснилось, что он
браковал ещё и нормальные высокие и низкие предметы: у модели отношение считалось по ТРЁМ
измерениям, а у паспорта — только по ширине и глубине. Торшер 28×28×179 давал 0.16 против
«паспортных 1.00». Здесь закреплено, что сравнивается сопоставимое.

Запуск: ~/venvs/scout/bin/python tests_gate.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def glb_box(x: float, y: float, z: float, path: str) -> str:
    import trimesh
    trimesh.creation.box(extents=(x, y, z)).export(path)
    return path


def check(name, box, dims, square, want_reject):
    import pipeline as P
    with tempfile.TemporaryDirectory() as tmp:
        g = glb_box(*box, os.path.join(tmp, 'shape.glb'))
        got = P.flat_shape(g, {'_dims': dims, '_square_role': square})
    rejected = got is not None
    assert rejected == want_reject, f'{name}: вердикт «{got}», ждали отбраковку={want_reject}'
    print(f'  ✓ {name}: {"забракован" if rejected else "принят"}')


def main() -> None:
    # ТОРШЕР: высокий и тонкий — это НОРМА, а не плоская форма
    check('торшер 28×28×179 нормальной формы', (0.28, 1.79, 0.28),
          {'w': 28, 'd': None, 'h': 179}, True, False)
    # ДИВАН: низкий и широкий — тоже норма
    check('диван 182×180×77 нормальной формы', (1.82, 0.77, 1.80),
          {'w': 182, 'd': 180, 'h': 77}, False, False)
    # СТЕЛЛАЖ: высокий и неглубокий
    check('стеллаж 80×35×200 нормальной формы', (0.80, 2.00, 0.35),
          {'w': 80, 'd': 35, 'h': 200}, False, False)
    # РАДИ ЧЕГО ГЕЙТ И ЗАВЕДЁН: кашпо вышло доской — обязано браковаться
    check('кашпо 30×30×30, а вышла доска', (0.30, 0.02, 0.30),
          {'w': 30, 'd': None, 'h': 30}, True, True)
    # диван, вышедший блином толщиной с ладонь
    check('диван 182×180×77, а вышел блин', (1.82, 0.05, 1.80),
          {'w': 182, 'd': 180, 'h': 77}, False, True)
    # без паспорта гейт не гадает
    check('нет паспорта — молчим', (1.0, 0.02, 1.0), {}, False, False)
    print('гейт плоской формы: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
