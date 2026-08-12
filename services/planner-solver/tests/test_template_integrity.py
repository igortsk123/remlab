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
ROOT = os.path.dirname(os.path.dirname(HERE))
SCOUT = os.path.join(ROOT, 'tools', 'scout')
sys.path.insert(0, os.path.join(ROOT, 'services', 'planner-solver'))
sys.path.insert(0, SCOUT)

REPORT = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')

# Пороги зафиксированы от замера и могут только УЛУЧШАТЬСЯ (правило регресс-сети).
MIN_SEATS_ON_RUG_SHARE = 0.90      # доля посадочных, стоящих на ковре
MAX_STORAGE_PER_ZONE = 2           # предметов хранения в одной зоне (правило владельца)


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
        tpl = lay.get('_templates') or {}
        orphans = sorted(r for r, v in tpl.items() if not (v or {}).get('id'))
        if orphans:
            bad[scene] = orphans
    assert not bad, f'предметы вне шаблонов: {dict(list(bad.items())[:5])}'


def test_no_phantom_dimensions():
    """Габарит поставленного == габарит SKU: солвер не подгоняет размер товара."""
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = {}
    for scene, lay, _room, ps in _scenes():
        n = int(scene.split('-')[0].replace('set', ''))
        items = (sets[n - 1].get('items') or {})
        if lay.get('_set_hash') is None:
            continue
        for p in ps:
            src = items.get(p.role) or items.get(p.role.split(' ')[0])
            if not src or not src.get('w') or p.item is None:
                continue
            got = sorted((round(p.item.w_cm), round(p.item.d_cm)))
            want = sorted((round(src['w']), round(src['d'] or 0)))
            if got != want:
                bad.setdefault(scene, []).append(f'{p.role} {got} ≠ {want}')
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
    """Зона из одного предмета — не шаблон (кроме декора, он всегда компаньон)."""
    bad = {}
    for scene, lay, _room, _ps in _scenes():
        tpl = lay.get('_templates') or {}
        cnt: dict[str, int] = {}
        for _r, v in tpl.items():
            zid = (v or {}).get('id')
            if zid and zid != 'decor':
                cnt[zid] = cnt.get(zid, 0) + 1
        lonely = sorted(z for z, c in cnt.items() if c < 2)
        if lonely:
            bad[scene] = lonely
    assert not bad, f'зоны из одного предмета: {dict(list(bad.items())[:5])}'
