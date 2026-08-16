"""Свод №13: Q1 identity-адаптер (secondary scope), Q2 правила с provenance, Q3 media-формы."""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules')
SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def _z():
    return json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))


# ---------- Q1 ----------
def test_secondary_scope_roles_declared_and_excluded_from_ladder():
    z = _z()
    sec = z['zone_priority']['secondary_scope_roles']
    assert set(sec) == {'кресло 3', 'кресло 4'}
    src = open(os.path.join(SCOUT, 'solver_run.py'), encoding='utf-8').read()
    assert 'RAW_BANK' in src and 'BANK_DISPOSITION' in src and "_input_bank" in src and "_bank_unused" in src


def test_ladder_counts_exclude_secondary():
    from collections import Counter
    from planner.models import Item, Room
    from planner.zones import pick_ladder, zone_rules
    sec = set(zone_rules()['zone_priority']['secondary_scope_roles'])
    items = [Item(role=r, w_cm=80, d_cm=85, h_cm=80) for r in ('кресло', 'кресло 3', 'кресло 4')]
    items.append(Item(role='диван', w_cm=220, d_cm=95, h_cm=85))
    room = Room(width_cm=700, depth_cm=600, openings=[])
    counts = Counter(i.role.split(' ')[0] for i in items if i.role not in sec)
    assert counts['кресло'] == 1
    steps = [g['id'] for g in pick_ladder(room, dict(counts))]
    assert 'sofa_4armchairs' not in steps


# ---------- Q2 ----------
def test_view_contracts_have_status_and_provenance():
    vc = _z()['view_contracts']
    for k, v in vc.items():
        if k.startswith('_'):
            continue
        assert v.get('status') in ('measured', 'hypothesis'), k
        assert len(str(v.get('provenance', ''))) > 20, k
    assert vc['media_seat_angle_max_deg']['value'] == 45
    assert vc['dining_view_cone']['status'] == 'hypothesis'   # shadow (решение владельца)


def test_tall_on_tv_wall_exempts_installation_only():
    o = json.load(open(os.path.join(RULES, 'occupancy.json'), encoding='utf-8'))
    assert o['layout_rules']['tall_on_tv_wall_exempt_installation'] is True
    from planner import validate as V
    src = open(V.__file__, encoding='utf-8').read()
    assert "getattr(p, 'tpl_variant', '') == 'installation'" in src


# ---------- Q3 ----------
def test_media_shapes_in_passport_at_end_of_cascade():
    groups = {g['id']: g for g in _z()['seating_groups']}
    for gid in ('sofa_armchair', 'sectional_armchair'):
        sh = groups[gid]['shapes']
        assert 'media_parallel' in sh and 'media_half' in sh
        assert sh.index('media_parallel') > sh.index('default'), 'media-формы — в конце каскада (greedy не меняется)'
        assert groups[gid].get('intent') == 'media_primary'
    assert 'media_bridge' in groups['sofa_2armchairs']['shapes']


def test_media_shapes_orient_armchair_to_tv():
    """Локальная система блока: диван rot 0 смотрит на +y (к ТВ)."""
    from planner.models import Item
    from planner.template import build_block
    by = {'диван': Item(role='диван', w_cm=220, d_cm=95, h_cm=85),
          'кресло': Item(role='кресло', w_cm=80, d_cm=85, h_cm=80),
          'столик': Item(role='столик', w_cm=110, d_cm=60, h_cm=45)}
    b = build_block('sofa_armchair', by, variant='media_parallel')
    assert b is not None
    rots = [rel[3] for rel in b.rel if rel[0].role == 'кресло']
    assert rots and int(rots[0]) % 360 == 0
    by2 = dict(by, **{'кресло 2': Item(role='кресло 2', w_cm=80, d_cm=85, h_cm=80)})
    b2 = build_block('sofa_2armchairs', by2, variant='media_bridge')
    assert b2 is not None
    r2 = sorted(int(rel[3]) % 360 for rel in b2.rel if rel[0].role.startswith('кресло'))
    assert r2 == [45, 315]


# ---------- Q3 бюджет ----------
def test_beam_budget_unified_and_families_only_large():
    z = _z(); b = z['beam']
    cap = b['full_chain_cap']
    assert cap['small'] <= 8 and cap['large_xl'] <= 3 and cap['large'] <= 4 and cap['transitional'] <= 6
    assert set(b['family_enabled_modes']) == {'large', 'large_xl'}
    assert 'transitional' in b['budget_by_mode'] and 'medium' not in b['budget_by_mode']
    assert 'max_full_attempts' not in b


def test_artifacts_respect_full_chain_cap():
    """На артефактах последнего экзамена: attempted ≤ cap режима; TIMEOUT = 0."""
    import glob
    z = _z(); cap = z['beam']['full_chain_cap']
    arts = glob.glob(os.path.join(SCOUT, 'v3set*-layout-acc-zoned-*.json'))
    if not arts:
        import pytest; pytest.skip('нет артефактов')
    over = []
    for f in arts:
        a = json.load(open(f, encoding='utf-8'))
        cc = ((a.get('_beam') or {}).get('composition_certificate') or {})
        mode = cc.get('mode'); att = (cc.get('budget') or {}).get('attempted')
        if mode in cap and att is not None and att > cap[mode]:
            over.append((os.path.basename(f), mode, att))
    assert not over, f'превышен full_chain_cap: {over[:5]}'
    rep = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')
    if os.path.exists(rep):
        tos = [json.loads(l)['scene'] for l in open(rep, encoding='utf-8')
               if l.strip() and 'TIMEOUT' in str(json.loads(l).get('fails'))]
        assert not tos, f'TIMEOUT в экзамене: {tos}'
