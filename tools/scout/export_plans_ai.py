#!/usr/bin/env python3
"""Экспорт 252 планов в формат «для другого ИИ» (запрос владельца 14.08).

На каждый план — три слоя:
  plan-NNN.json — структурный (комната/проёмы/предметы/шаблоны/метрики);
  plan-NNN.md   — семантика словами + ASCII-карта (1 клетка ≈ 20 см);
  plan-NNN.png  — чертёж (копия из галереи).
Плюс index.json (агрегаты) и README.md (как читать).

Вход: acceptance-scenes.json, sets3.json, acceptance-report-zoned.jsonl,
~/scout-scenes/acc-gallery/*.json|png. Выход: ~/scout-scenes/plans-export/.
"""
import json
import math
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
GAL = os.path.expanduser('~/scout-scenes/acc-gallery')
OUT = os.path.expanduser('~/scout-scenes/plans-export')

WALL_RU = {'south': 'южной', 'north': 'северной', 'west': 'западной', 'east': 'восточной'}
FACING = {0: 'на север', 90: 'на восток', 180: 'на юг', 270: 'на запад'}


def wall_of(room_w, room_d, x, y, w, d, rot):
    """Ближайшая стена по тылу предмета (грубо, для семантики)."""
    r = int(rot) % 360
    back = {0: y, 180: room_d - y, 90: x, 270: room_w - x}.get(r, 0)
    wall = {0: 'south', 180: 'north', 90: 'west', 270: 'east'}.get(r)
    return wall, back


def semantic(scene_id, room, items, rep, set_meta):
    w, d = room['w'], room['d']
    lines = []
    shape = 'вытянутая' if max(w, d) / max(min(w, d), 1) >= 1.4 else 'прямоугольная'
    if room.get('contour'):
        shape = 'сложной формы (контур с нишей/выступом)'
    lines.append(f"Комната {w}×{d} см ({w * d / 1e4:.1f} м²), {shape}.")
    for op in room.get('openings', []):
        kind = 'Дверь' if op['kind'] in ('door', 'balcony') else 'Окно'
        lines.append(f"{kind} на {WALL_RU.get(op['wall'], op['wall'])} стене, "
                     f"отступ {op['offset_cm']:.0f} см, ширина {op['width_cm']:.0f} см"
                     + (f", подоконник {op.get('sill_cm')} см" if op.get('sill_cm') else '')
                     + '.')
    tv = None
    sofa = None
    lines.append('')
    lines.append('Расстановка:')
    for role, it in items.items():
        rot = int(it.get('rot', 0)) % 360
        wall, back = wall_of(w, d, it['x'], it['z'], it.get('w') or 0,
                             it.get('d') or 0, rot)
        pos = (f"у {WALL_RU.get(wall, '?')} стены" if back - (it.get('d') or 0) / 2 <= 15
               else ('отдельно (floating), спинка/тыл к ' + WALL_RU.get(wall, '?')
                     + f' стене в {back - (it.get("d") or 0) / 2:.0f} см'))
        lines.append(f"- {role} {it.get('w', '?')}×{it.get('d', '?')} см, центр "
                     f"({it['x']:.0f},{it['z']:.0f}), фронт {FACING.get(rot, rot)}, {pos}.")
        if role == 'диван':
            sofa = it
        if role in ('тв-тумба', 'стенка'):
            tv = it
    if sofa is not None and tv is not None:
        dist = math.hypot(tv['x'] - sofa['x'], tv['z'] - sofa['z'])
        lines.append('')
        lines.append(f"Дистанция диван↔носитель ТВ: {dist:.0f} см.")
    m = []
    din = (rep or {}).get('_dining') or {}
    if din:
        m.append(f"столовая: режим {din.get('mode')}, остров возможен="
                 f"{din.get('island_feasible')}, причина={din.get('why_selected')}"
                 + (f", фолбэк={din.get('fallback_reason')}"
                    if din.get('fallback_reason') else ''))
    if rep:
        m.append(f"шаблоны зон: {rep.get('templates')}")
        if rep.get('unused'):
            m.append('в банке сета (не понадобилось): ' + ', '.join(rep['unused']))
        m.append(f"soft-score {rep.get('soft_score')}")
    art = items  # noqa
    lines.append('')
    lines.append('Метрики: ' + '; '.join(m) + '.')
    return '\n'.join(lines)


def ascii_map(room, items):
    cell = 20.0
    w, d = room['w'], room['d']
    cols, rows = int(w // cell) + 1, int(d // cell) + 1
    grid = [['.' for _ in range(cols)] for _ in range(rows)]
    CH = {'диван': 'S', 'кресло': 'A', 'столик': 't', 'стол': 'T', 'стул': 'c',
          'тв-тумба': 'V', 'стенка': 'V', 'стеллаж': 'H', 'витрина': 'G',
          'комод': 'M', 'ковёр': '·', 'кашпо': 'p', 'торшер': 'l', 'пуф': 'o',
          'камин': 'F', 'приставной': 'n', 'зеркало': 'z'}
    letters = {}
    for role, it in sorted(items.items()):
        if 'x' not in it:
            continue
        base = role.split(' ')[0]
        ch = CH.get(base, base[0].upper())
        letters.setdefault(ch, base)
        rot = int(it.get('rot', 0)) % 180
        iw = (it.get('w') or 40)
        idp = (it.get('d') or 40)
        if rot == 90:
            iw, idp = idp, iw
        x0, x1 = it['x'] - iw / 2, it['x'] + iw / 2
        y0, y1 = it['z'] - idp / 2, it['z'] + idp / 2
        for r in range(rows):
            for c in range(cols):
                cx, cy = c * cell + cell / 2, r * cell + cell / 2
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    if grid[r][c] == '.' or ch != '·':
                        grid[r][c] = ch
    for op in room.get('openings', []):
        ch = 'D' if op['kind'] in ('door', 'balcony') else 'W'
        a, b = op['offset_cm'], op['offset_cm'] + op['width_cm']
        for t in range(int(a // cell), int(b // cell) + 1):
            if op['wall'] == 'south' and 0 <= t < cols:
                grid[0][t] = ch
            elif op['wall'] == 'north' and 0 <= t < cols:
                grid[rows - 1][t] = ch
            elif op['wall'] == 'west' and 0 <= t < rows:
                grid[t][0] = ch
            elif op['wall'] == 'east' and 0 <= t < rows:
                grid[t][cols - 1] = ch
    # y растёт на север → печатаем сверху север (переворот)
    body = '\n'.join(''.join(row) for row in reversed(grid))
    legend = '  '.join(f'{k}={v}' for k, v in sorted(letters.items()))
    return (f'Карта (1 клетка ≈ 20 см; верх = север, D = дверь, W = окно):\n'
            f'```\n{body}\n```\n{legend}')


def main():
    scenes = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))
    sets_ = json.load(open(os.path.join(HERE, 'sets3.json')))
    reps = {}
    for line in open(os.path.join(HERE, 'acceptance-report-zoned.jsonl')):
        r = json.loads(line)
        reps[r['scene']] = r
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    index = []
    for i, sc in enumerate(scenes, 1):
        sid = sc['id']
        art_p = os.path.join(GAL, sid + '.json')
        if not os.path.exists(art_p):
            continue
        art = json.load(open(art_p))
        room = art['_room']
        items = {k: v for k, v in art.items()
                 if not k.startswith('_') and isinstance(v, dict) and 'x' in v}
        set_meta = sets_[sc['set'] - 1]
        rep = dict(reps.get(sid, {}))
        rep['_dining'] = art.get('_dining')   # диагностика dining — из артефакта (пакет B)
        num = f'{i:03d}'
        data = {
            'plan': i, 'scene': sid,
            'room': room,
            'set': {'band': set_meta.get('band'), 'm2': set_meta.get('m2'),
                    'style': set_meta.get('style'), 'tier': set_meta.get('tier')},
            'placements': items,
            'zone_templates': art.get('_templates'),
            'metrics': {'route_cm': art.get('_route_cm'),
                        'fill_pct': art.get('_fill_pct'),
                        'soft_score': rep.get('soft_score')},
            'dining': art.get('_dining'),
            'axes': art.get('_axes'),
            'zones': art.get('_zones'),
            'mirror': art.get('_mirror'),
            'seating_search': art.get('_seating_search'),
            'axis_contract': art.get('_axis_contract'),
            'media_validation': art.get('_media_validation'),
            'bank_unused': rep.get('unused', []),
            'zones_tag': rep.get('templates'),
        }
        json.dump(data, open(os.path.join(OUT, f'plan-{num}.json'), 'w'),
                  ensure_ascii=False, indent=1)
        md = (f'# План №{i} — {sid}\n\n'
              + semantic(sid, room, items, rep, set_meta)
              + '\n\n' + ascii_map(room, items) + '\n')
        open(os.path.join(OUT, f'plan-{num}.md'), 'w').write(md)
        png = os.path.join(GAL, sid + '.png')
        if os.path.exists(png):
            shutil.copy(png, os.path.join(OUT, f'plan-{num}.png'))
        index.append({'plan': i, 'scene': sid, 'm2': set_meta.get('m2'),
                      'zones': rep.get('templates'),
                      'dining': '+din' in (rep.get('templates') or ''),
                      'route_cm': art.get('_route_cm')})
    json.dump({'plans': index,
               'totals': {'count': len(index),
                          'dining': sum(1 for x in index if x['dining'])}},
              open(os.path.join(OUT, 'index.json'), 'w'), ensure_ascii=False, indent=1)
    _mt = os.path.join(HERE, 'missing_templates.md')
    if os.path.exists(_mt):
        shutil.copy(_mt, os.path.join(OUT, 'missing_templates.md'))
    open(os.path.join(OUT, 'README.md'), 'w').write(
        f'# Экспорт планов расстановки ({len(index)} сцен) для анализа ИИ\n\n'
        'На каждый план три файла:\n'
        '- `plan-NNN.json` — структурный: комната (см, контур, проёмы), предметы '
        '(роль, габариты, центр x/z, поворот), шаблоны зон, метрики (маршрут, '
        'заполнение), банк неиспользованного.\n'
        '- `plan-NNN.md` — то же словами (позиции относительно стен, фронты, '
        'дистанция диван-ТВ) + ASCII-карта (1 клетка ≈ 20 см, верх = север).\n'
        '- `plan-NNN.png` — чертёж.\n\n'
        'Система координат: сантиметры, (0,0) — юго-западный угол, x на восток, '
        'z (в JSON) / y на север. Поворот: 0 = фронт на север, 90 = восток, '
        '180 = юг, 270 = запад.\n'
        '`index.json` — сводка по всем планам.\n')
    print(f'OK: {len(index)} планов → {OUT}')


if __name__ == '__main__':
    main()
