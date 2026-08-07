#!/usr/bin/env python3
"""Z5 (MASTER-zones-first, правка владельца 07.08): ЗАФИКСИРОВАННЫЙ приёмочный набор сцен —
финальная приёмка НЕ на десятке (анти-оверфит), а на ~250 заранее зафиксированных сценах:
126 сетов × вариации геометрии (базовый прямоугольник, вытянутый 1:1.5, Э8-контуры с эркером/
пилонами/трапецией-ступенями, масштабированные под метраж сета).

Файл acceptance-scenes.json создаётся ОДИН раз и коммитится; пересоздание — только --force
(иначе набор «плывёт» под текущий движок и приёмка теряет смысл). Детерминизм: никакого
random — всё от номера сета.
Запуск: ~/venvs/scout/bin/python acceptance_scenes.py [--force]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'acceptance-scenes.json')

# Осевые Э8-контуры (референс-планировки владельца 07.08), базовая площадь ~19–21 м²;
# юг (y=0) сплошной — дверная логика solver_run валидна без изменений
CONTOURS = {
    'bay': [(0, 0), (500, 0), (500, 380), (350, 380), (350, 440), (150, 440),
            (150, 380), (0, 380)],
    'pylons': [(0, 0), (600, 0), (600, 200), (560, 200), (560, 260), (600, 260),
               (600, 460), (0, 460)],
    'trapezoid': [(0, 0), (520, 0), (520, 420), (390, 420), (390, 470), (260, 470),
                  (260, 520), (0, 520)],
}


def _area_m2(pts):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2 / 10_000


def _scaled(name, m2):
    """Контур, отмасштабированный под метраж сета (форма референса сохраняется)."""
    pts = CONTOURS[name]
    k = (m2 / _area_m2(pts)) ** 0.5
    return [(round(x * k / 5) * 5, round(y * k / 5) * 5) for x, y in pts]


def build():
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    scenes = []
    names = list(CONTOURS)
    for i, s in enumerate(sets, 1):
        m2 = float(s.get('m2') or 15)
        # базовый прямоугольник ~1:1.15 (как боевой прогон) — ВСЕ сеты
        scenes.append(dict(id=f'set{i}-base', set=i, kind='rect', ratio=1.15))
        # вытянутый 1:1.5 — каждый второй (узкие комнаты ломают разговорный круг)
        if i % 2 == 0:
            w = int((m2 * 10000 / 1.5) ** 0.5 // 5 * 5)
            d = int(m2 * 10000 / w // 5 * 5)
            scenes.append(dict(id=f'set{i}-long', set=i, kind='rect', w=w, d=d))
        # Э8-контур — каждый второй (ротация трёх референсов), масштаб под метраж
        if i % 2 == 1:
            nm = names[(i // 2) % len(names)]
            scenes.append(dict(id=f'set{i}-{nm}', set=i, kind='contour',
                               contour=_scaled(nm, m2)))
    return scenes


if __name__ == '__main__':
    if os.path.exists(OUT) and '--force' not in sys.argv:
        cur = json.load(open(OUT))
        print(f'набор уже зафиксирован: {len(cur)} сцен ({OUT}); пересоздание — --force')
        sys.exit(0)
    scenes = build()
    json.dump(scenes, open(OUT, 'w'), ensure_ascii=False, indent=1)
    kinds = {}
    for sc in scenes:
        kinds[sc['id'].split('-')[-1]] = kinds.get(sc['id'].split('-')[-1], 0) + 1
    print(f'зафиксировано {len(scenes)} сцен: {kinds}')
