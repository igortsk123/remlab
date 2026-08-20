"""Гейт ситуационного паспорта (ADR-0112, 19.08): канон = функция × якорь × форма.

Каждая схема обязана объявлять `anchor` и `form` из реестра, иметь `when`/`why`/`status`,
а каждая ФОРМА, реально исполняемая движком (shapes в zones.json), обязана существовать
как схема паспорта — иначе «библиотека канонов» не покрывает то, что работает в бою.
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), '..')


def _rules(name):
    with open(os.path.join(ROOT, 'rules', name), encoding='utf-8') as f:
        return json.load(f)


def _schemes():
    t = _rules('templates.json')
    return [(z, s) for z, zv in (t.get('zones') or {}).items() for s in (zv.get('schemes') or [])]


def test_every_scheme_declares_anchor_and_form():
    reg = set((_rules('templates.json').get('anchor_registry') or {}).get('types') or [])
    assert reg, 'нет реестра типов якоря (templates.anchor_registry)'
    bad = []
    for z, s in _schemes():
        a, f = s.get('anchor'), s.get('form')
        if not a or not f:
            bad.append(f"{z}.{s['id']}: нет anchor/form")
            continue
        # допускаются составные значения: object:fireplace, wall_segment|free_region, unresolved
        heads = {x.split(':')[0] for x in str(a).split('|')}
        if not heads <= (reg | {'unresolved'}):
            bad.append(f"{z}.{s['id']}: якорь «{a}» вне реестра {sorted(reg)}")
    assert not bad, 'паспорта без ситуации: ' + '; '.join(bad)


def test_every_scheme_has_rationale_and_status():
    bad = [f"{z}.{s['id']}" for z, s in _schemes()
           if not s.get('when') or not s.get('why') or not s.get('status')]
    assert not bad, 'схемы без when/why/status: ' + ', '.join(bad)


def test_runtime_shapes_exist_as_schemes():
    """Каждая ФОРМА, которую движок реально перебирает (zones.json seating_groups.shapes),
    должна быть покрыта каноном: либо id схемы, либо её `runtime_variants` (зеркала и
    переименования не создают новых канонов — 19.08, аудит Codex)."""
    zn = _rules('zones.json')
    have = set()
    for z, sch in _schemes():
        if z != 'seating':
            continue
        have.add(sch['id'])
        have |= set(sch.get('runtime_variants') or [])
    shapes = set()
    for g in (zn.get('seating_groups') or []):
        shapes |= set(g.get('shapes') or [])
    missing = sorted(shapes - have)
    assert not missing, f'формы исполняются, но не описаны в паспорте: {missing}'


def test_group_shape_pairs_are_covered():
    """Единица учёта канона — (группа, форма), а не форма: один `default` у разных групп —
    это разные композиции (диван+кресло, диван+торшер, два дивана визави)."""
    zn = _rules('zones.json')
    schemes = [sch for z, sch in _schemes() if z == 'seating']
    bad = []
    for g in (zn.get('seating_groups') or []):
        if g.get('status', 'active') != 'active':
            continue
        for shape in (g.get('shapes') or []):
            ok = any(shape in (set(sch.get('runtime_variants') or []) | {sch['id']})
                     and (not sch.get('groups') or g['id'] in sch['groups'])
                     for sch in schemes)
            if not ok:
                bad.append(f"{g['id']}.{shape}")
    assert not bad, 'пары (группа, форма) без канона: ' + ', '.join(bad)
