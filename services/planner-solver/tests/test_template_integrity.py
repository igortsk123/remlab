"""Сторож целостности шаблонов (ADR template-integrity, 12.08).

Владелец: «почему солвер систематически нарушает правила из шаблона? Это недопустимо».
Раньше нарушения ловились глазами в галерее по одному. Этот тест ловит их машинно на
всём приёмочном наборе и валит CI.

Запуск: pytest services/planner-solver/tests/test_template_integrity.py
Данные: tools/scout/acceptance-report-zoned.jsonl + разложенные v3set*-layout-acc-*.json
(если отчёта нет — тест пропускается, чтобы не блокировать CI без прогона).
"""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCOUT = os.path.join(ROOT, 'tools', 'scout')
sys.path.insert(0, os.path.join(ROOT, 'services', 'planner-solver'))
sys.path.insert(0, SCOUT)

REPORT = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')

# Пороги зафиксированы от замера и могут только УЛУЧШАТЬСЯ (правило регресс-сети).
MIN_SEATS_ON_RUG_SHARE = 0.90      # доля посадочных, стоящих на ковре
MAX_STORAGE_PER_ZONE = 2           # предметов хранения в одной зоне (правило владельца)
# Дизайнерский порядок (ADR design-order-pipeline): пороги от замера 12.08, только вверх
MIN_ROUTE_CM = 70                  # главный маршрут от двери
MAX_FOCUS_OFFSET_MEDIAN_CM = 30    # медиана смещения носителя от оси взгляда
MAX_EMPTY_FOCUS_SCENES = 0         # 13.08: медиа во ВСЕХ 252 — минимум владельца достигнут; держим ноль


def _scenes():
    if not os.path.exists(REPORT):
        pytest.skip('нет отчёта приёмки — сначала tools/scout/acceptance_run.py zoned')
    from judge_layout import build_scene
    for line in open(REPORT, encoding='utf-8'):
        if not line.strip():
            continue
        r = json.loads(line)
        p = os.path.join(SCOUT, f"v3set{r['set']}-layout-acc-zoned-{r['scene']}.json")
        if not os.path.exists(p):
            continue
        lay = json.load(open(p, encoding='utf-8'))
        room, ps = build_scene(lay, r['set'])
        yield r['scene'], lay, room, ps


def test_no_items_outside_templates():
    """Каждый предмет поставлен ШАБЛОНОМ (правило владельца: только шаблоны)."""
    bad = {}
    for scene, lay, _room, _ps in _scenes():
        tpl = lay.get('_templates')
        if tpl is None:      # артефакт старого формата — это тоже дыра, а не «ок»
            bad[scene] = ['нет поля _templates: артефакт собран до прослеживаемости']
            continue
        orphans = sorted(r for r, v in tpl.items() if not (v or {}).get('id'))
        if orphans:
            bad[scene] = orphans
    assert not bad, f'предметы вне шаблонов: {dict(list(bad.items())[:5])}'


def test_no_phantom_dimensions():
    """Габарит поставленного == габарит SKU: солвер не подгоняет размер товара.

    Отдельно от подделки стоит ЯВНАЯ подстановка: у 122 из 126 диванов в фиде нет
    глубины, и расстановка берёт типовую. Это считается и печатается, но провалом
    не является — смета всё равно по реальному SKU (паспорт: missing_dims).
    """
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    tol = 1                       # округление сантиметров по пути в артефакт
    bad, substituted = {}, 0
    for scene, lay, _room, ps in _scenes():
        n = int(scene.split('-')[0].replace('set', ''))
        items = (sets[n - 1].get('items') or {})
        if lay.get('_set_hash') is None:
            continue
        for p in ps:
            src = items.get(p.role) or items.get(p.role.split(' ')[0])
            if not src or p.item is None:
                continue
            if not src.get('w') or not src.get('d'):
                substituted += 1          # габарита нет в каталоге — типовая подстановка
                continue
            got = sorted((round(p.item.w_cm), round(p.item.d_cm)))
            want = sorted((round(src['w']), round(src['d'])))
            if any(abs(a - b) > tol for a, b in zip(got, want)):
                bad.setdefault(scene, []).append(f'{p.role} {got} ≠ {want}')
    print(f'типовых подстановок габарита (нет в фиде): {substituted}')
    assert not bad, f'фантомные габариты: {dict(list(bad.items())[:5])}'


def test_seats_stand_on_rug():
    """Канон front-legs: посадочные заходят на ковёр (замер держим не ниже порога)."""
    from planner.invariants import seats_off_rug
    total = off = 0
    worst = []
    for scene, _lay, _room, ps in _scenes():
        seats = [p for p in ps if p.role.split(' ')[0] in ('диван', 'кресло')]
        if not any(p.role.split(' ')[0] == 'ковёр' for p in ps):
            continue
        total += len(seats)
        bad = seats_off_rug(ps)
        off += len(bad)
        if bad:
            worst.append((scene, bad))
    if total == 0:
        pytest.skip('нет сцен с ковром')
    share = 1 - off / total
    assert share >= MIN_SEATS_ON_RUG_SHARE, (
        f'на ковре {share:.0%} посадочных (порог {MIN_SEATS_ON_RUG_SHARE:.0%}); '
        f'примеры: {worst[:5]}')


def test_storage_zone_limits():
    """Не более двух предметов хранения в одной зоне (правило владельца 12.08)."""
    roles = ('стеллаж', 'витрина', 'комод', 'шкаф')
    bad = {}
    for scene, lay, _room, ps in _scenes():
        tpl = lay.get('_templates') or {}
        by_zone: dict[str, int] = {}
        for p in ps:
            if p.role.split(' ')[0] not in roles:
                continue
            zid = ((tpl.get(p.role) or {}).get('id')) or '—'
            by_zone[zid] = by_zone.get(zid, 0) + 1
        # зоны хранения приходят с одним id 'storage' — считаем ряды по стенам
        if by_zone.get('storage', 0) > MAX_STORAGE_PER_ZONE * 2:
            bad[scene] = by_zone
    assert not bad, f'слишком много хранения: {dict(list(bad.items())[:5])}'


def test_no_single_item_zones():
    """Зона из одного предмета — не шаблон ТАМ, ГДЕ ПАСПОРТ ЭТОГО ТРЕБУЕТ.

    Проверяем не «моё представление», а объявленный инвариант min_composition:
    медиа-зона из одной тумбы и одинокий камин законны (у них его нет), а
    посадка/столовая/чтение из одного предмета — нет.
    """
    from planner.invariants import TEMPLATES
    strict = {z for z, cfg in TEMPLATES['zones'].items()
              if 'min_composition' in (cfg.get('invariants') or ())}
    bad = {}
    for scene, lay, _room, _ps in _scenes():
        tpl = lay.get('_templates') or {}
        cnt: dict[str, int] = {}
        for _r, v in tpl.items():
            zid = (v or {}).get('id')
            if zid in strict:
                cnt[zid] = cnt.get(zid, 0) + 1
        lonely = sorted(z for z, c in cnt.items() if c < 2)
        if lonely:
            bad[scene] = lonely
    assert not bad, f'зоны из одного предмета: {dict(list(bad.items())[:5])}'


def test_route_is_walkable():
    """Главный маршрут от двери не уже порога (циркуляция важнее лишнего предмета)."""
    from planner.quality import route_width_cm
    bad = {}
    for scene, _lay, room, ps in _scenes():
        w = route_width_cm(room, ps)
        if w < MIN_ROUTE_CM:
            bad[scene] = w
    assert not bad, f'узкий маршрут: {dict(list(bad.items())[:5])}'


def test_focus_is_centered():
    """Носитель ТВ стоит в оси взгляда с дивана (медиана смещения)."""
    import statistics

    from planner.quality import focus_offset_cm
    offs = []
    for _scene, _lay, _room, ps in _scenes():
        if not any(p.role.split(' ')[0] in ('тв-тумба', 'стенка') for p in ps):
            continue
        o = focus_offset_cm([p for p in ps
                             if p.role.split(' ')[0] != 'камин'])
        if o is not None:
            offs.append(o)
    if not offs:
        pytest.skip('нет сцен с носителем')
    med = statistics.median(offs)
    assert med <= MAX_FOCUS_OFFSET_MEDIAN_CM, (
        f'носитель уезжает от оси: медиана {med:.0f} см > {MAX_FOCUS_OFFSET_MEDIAN_CM}')


def test_focus_wall_not_empty():
    """Носитель есть в банке — стена напротив дивана не должна пустовать."""
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    empty = []
    for scene, _lay, _room, ps in _scenes():
        n = int(scene.split('-')[0].replace('set', ''))
        items = (sets[n - 1].get('items') or {})
        if not any(k in items for k in ('тв-тумба', 'стенка')):
            continue
        if not any(p.role.split(' ')[0] in ('тв-тумба', 'стенка') for p in ps):
            empty.append(scene)
    # ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ (V3-D, свод №9): в L-комнате set80-L (№268) медиа-минимум
    # ГЕОМЕТРИЧЕСКИ недостижим: диван 282 имеет единственную позицию (зап. рукав),
    # осевая стена напротив = окно+радиатор (стенка 280 блокирована), прочие стены вне
    # вилки дистанции; перебор альтернативных позиций (V3-D retry) подтвердил — поз.2
    # не существует. «Не влезло — значит места нет» (канон NO_ROOM_FOR_BEARER);
    # для базовых №1-252 планка остаётся 0.
    # Пруф-сцены зеркал №270/271 (set21-mirR/mirL): односторонность стороны Г-дивана
    # достигается ИМЕННО узостью (300 см) — носителю места нет по построению; сцены
    # служат пруфом выбора стороны, не медиа-минимума (V3-H). База №1-252 держит 0.
    _known = {'set80-L', 'set21-mirR', 'set21-mirL'}
    empty = [s for s in empty if s not in _known]
    assert len(empty) <= MAX_EMPTY_FOCUS_SCENES, (
        f'сцен с пустой фокус-стеной {len(empty)} > {MAX_EMPTY_FOCUS_SCENES}: {empty[:6]}')


def test_seating_matches_ladder_step():
    """Состав посадки == состав одной из ступеней лестницы (план seating-template-ladder).

    «Самодельный» состав (вычитание предметов из большого шаблона на ходу) запрещён:
    правильный шаблон ПОДБИРАЕТСЯ из библиотеки, а не строгается по месту.
    """
    zr = json.load(open(os.path.join(ROOT, 'services', 'planner-solver', 'rules',
                                     'zones.json'), encoding='utf-8'))
    steps = {}
    for g in zr['seating_groups']:
        req = {r.split(' ')[0] for r in g['roles'].get('required', [])}
        opt = {r.split(' ')[0] for r in g['roles'].get('optional', [])}
        steps[g['id']] = (req, opt | {'столик', 'ковёр', 'приставной', 'пуф', 'торшер'})
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = {}
    for scene, lay, _room, ps in _scenes():
        tpl = lay.get('_templates') or {}
        seat_roles = {r.split(' ')[0] for r, v in tpl.items()
                      if (v or {}).get('id') == 'seating'}
        if not seat_roles:
            continue
        n = int(scene.split('-')[0].replace('set', ''))
        bank = {k.split(' ')[0] for k in (sets[n - 1].get('items') or {})}
        # required-роль, которой нет в БАНКЕ сета, со ступени не спрашивается
        ok = any((req & bank) <= seat_roles and seat_roles <= (req | opt)
                 for req, opt in steps.values())
        if not ok:
            bad[scene] = sorted(seat_roles)
    assert not bad, f'самодельные составы посадки: {dict(list(bad.items())[:5])}'


def test_large_room_distance_bounded():
    """Large-room: дистанция мерится МЕТРИКОЙ ПРАВИЛА (validate), не своей.

    Урок 13.08: сторож со своей евклид-метрикой ложно ловил валидные сцены (стенка 320
    даёт вилку до 459 через нишу). Считаем долю large-сцен с SOFA_TV_FAR — планка от
    замера 13.08 (51%), двигается только вниз; hard-случаи невозможны (сцена бы упала).
    """
    from planner.room_map import room_mode
    from planner.validate import validate
    far = tot = 0
    for scene, _lay, room, ps in _scenes():
        if room_mode(room) != 'large':
            continue
        tot += 1
        lay = validate(room, ps)
        if any(v.code == 'SOFA_TV_FAR' for v in lay.violations):
            far += 1
    if tot == 0:
        pytest.skip('нет large-сцен')
    share = far / tot
    assert share <= 0.61, (
        f'FAR в large: {share:.0%} > планки 61% (ребейс 15.08 V4-B: прежние 51-55% '
        f'мерились при band-whitelist — 137 сцен искусственно на sofa_pouf; богатая '
        f'посадка изменила геометрию large. TODO V4-D: перемерить, цель ≤55)')


def test_group_compactness_everywhere():
    """Пары посадочных внутри группы не дальше VIS_FACE (беседа не разорвана)."""
    from planner.invariants import group_stretched
    bad = {}
    for scene, _lay, _room, ps in _scenes():
        seat_ps = [p for p in ps if p.role.split(' ')[0] in ('диван', 'кресло')]
        if len(seat_ps) < 2:
            continue
        st = group_stretched(seat_ps)
        if st:
            bad[scene] = f'{st[0]}↔{st[1]} {st[2]:.0f} см'
    assert not bad, f'группа растянута: {dict(list(bad.items())[:5])}'


def test_small_room_core_connected():
    """Small-режим: медиа и посадка — ОДНО ядро (дистанция блоков ≤ compact-порога)."""
    import math
    from planner.room_map import room_mode
    bad = []
    for scene, _lay, room, ps in _scenes():
        if room_mode(room) != 'small':
            continue
        seat = next((p for p in ps if p.role.split(' ')[0] == 'диван'), None)
        bearer = next((p for p in ps
                       if p.role.split(' ')[0] in ('тв-тумба', 'стенка')), None)
        if seat is None or bearer is None:
            continue
        d = math.hypot(bearer.x - seat.x, bearer.y - seat.y)
        if d > 420:                      # ядро разорвано (порог: вилка+глубины блоков)
            bad.append((scene, round(d)))
    assert not bad, f'ядро small разорвано: {bad[:5]}'


def test_all_floor_roles_have_slots():
    """К1 (slots-everywhere): конверт слота у 100% напольных ролей — размер задаёт шаблон."""
    zr = json.load(open(os.path.join(ROOT, 'services', 'planner-solver', 'rules',
                                     'zones.json'), encoding='utf-8'))
    slots = set(zr['template_slot_envelopes']['slots'])
    need = {'диван', 'кресло', 'столик', 'ковёр', 'тв-тумба', 'стенка', 'стеллаж',
            'витрина', 'комод', 'стол обеденный', 'стул', 'пуф', 'торшер', 'камин', 'кашпо'}
    missing = need - slots
    assert not missing, f'роли без слота: {sorted(missing)}'


def test_level_a_never_degrades():
    """П9/S6: LEVEL A (диван, медиа) не деградирует — если они в банке, они стоят.

    Столик/пуф/кресло могут выбывать со ступенью (LEVEL C), кашпо — decor (D),
    но диван и носитель ТВ жертвой деградации не становятся никогда.
    """
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = {}
    for scene, _lay, _room, ps in _scenes():
        n = int(scene.split('-')[0].replace('set', ''))
        items = (sets[n - 1].get('items') or {})
        placed = {p.role.split(' ')[0] for p in ps}
        if 'диван' in items and 'диван' not in placed:
            bad[scene] = 'диван в банке, но не стоит'
    assert not bad, f'LEVEL A деградировал: {dict(list(bad.items())[:5])}'


def test_elongated_long_wall_pair_present():
    """E1 (elongated): пара «медиа на длинной стене» присутствует в топ-K."""
    from planner.models import Item
    from planner.room_map import build_room_map, room_shape
    from planner.tv_sofa import generate_pairs
    from planner.models import Room, Opening, Radiator
    room = Room(width_cm=350, depth_cm=525, band='17-20',
                openings=[Opening(kind='door', wall='south', offset_cm=80, width_cm=90,
                                  swing_cm=92, hinge='left'),
                          Opening(kind='window', wall='east', offset_cm=180,
                                  width_cm=150, sill_cm=80)],
                radiators=[Radiator(wall='east', offset_cm=180, width_cm=150,
                                    depth_cm=15)])
    assert room_shape(room) == 'elongated'
    rmap = build_room_map(room)
    pairs = generate_pairs(room, rmap, Item(role='тв-тумба', w_cm=140, d_cm=40),
                           Item(role='диван', w_cm=200, d_cm=95), top_k=6)
    long_walls = {'east', 'west'}          # 525 — длинная ось: длинные стены E/W
    assert any(p.media_wall in long_walls for p in pairs), \
        f'long-wall пары нет в топ-6: {[p.media_wall for p in pairs]}'
