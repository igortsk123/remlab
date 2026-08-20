"""Q5+ свода №13: КОНТРАКТ ПОЗЫ (rot) для 3D/LLM — pose-hash round-trip и orientation в экспорте.

- rot в артефакте == rot в plan-NNN.json (float, не int; 0° и 180° — разный фронт при одном footprint);
- у каждого направленного предмета в экспорте есть orientation (yaw, фронт-вектор, intent, relation);
- facing_target пересчитывается из координат: угловая ошибка соответствует relation
  (faces ≤15°, angled_toward ≤45°), дистанция ≤250 см.
"""
import glob
import json
import math
import os

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')
EXPORT = os.path.expanduser('~/scout-scenes/plans-export')
DIRECTIONAL = ('диван', 'кресло', 'тв-тумба', 'стенка', 'камин', 'стул')


def _pairs(limit=60):
    idx_p = os.path.join(EXPORT, 'index.json')
    if not os.path.exists(idx_p):
        return []
    # контракт позы сверяет артефакты ПОЛНОГО прогона с экспортом; нет отчёта приёмки —
    # значит прогон не делался или прерван, артефакты и экспорт из разных состояний,
    # и тест обязан скипаться, а не падать (19.08)
    if not os.path.exists(os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')):
        return []
    idx = json.load(open(idx_p, encoding='utf-8'))['plans']
    out = []
    for it in idx[:limit]:
        n = int(it['scene'].split('-')[0][3:])
        art_p = os.path.join(SCOUT, f"v3set{n}-layout-acc-zoned-{it['scene']}.json")
        exp_p = os.path.join(EXPORT, f"plan-{it['plan']:03d}.json")
        if os.path.exists(art_p) and os.path.exists(exp_p):
            out.append((json.load(open(art_p, encoding='utf-8')), json.load(open(exp_p, encoding='utf-8'))))
    return out


def test_pose_hash_round_trip():
    pairs = _pairs()
    if not pairs:
        import pytest
        pytest.skip('нет экспорта plans-export')
    bad = []
    for art, exp in pairs:
        for role, v in exp['placements'].items():
            a = art.get(role)
            if not isinstance(a, dict) or 'x' not in a:
                continue
            if abs(float(a.get('rot', 0)) % 360 - float(v.get('rot', 0)) % 360) > 0.01 \
                    or abs(float(a['x']) - float(v['x'])) > 0.01:
                bad.append((exp['scene'], role))
    assert not bad, f'pose mismatch артефакт↔экспорт: {bad[:5]}'


def test_orientation_present_and_consistent():
    pairs = _pairs()
    if not pairs:
        import pytest
        pytest.skip('нет экспорта plans-export')
    missing, incons = [], []
    for _, exp in pairs:
        pl = exp['placements']
        for role, v in pl.items():
            if role.split(' ')[0] not in DIRECTIONAL:
                continue
            o = v.get('orientation')
            if not o:
                missing.append((exp['scene'], role))
                continue
            rot = float(v.get('rot', 0)) % 360
            if abs(o['yaw_deg'] - rot) > 0.01:
                incons.append((exp['scene'], role, 'yaw'))
            ft = o.get('facing_target')
            if ft:
                cx, cz = float(v['x']), float(v.get('z', v.get('y', 0)))
                dx, dz = ft['point_cm']['x'] - cx, ft['point_cm']['z'] - cz
                bearing = math.degrees(math.atan2(dx, dz)) % 360
                err = abs((bearing - rot + 180) % 360 - 180)
                if abs(err - ft['angular_error_deg']) > 0.6 or ft['distance_cm'] > 250.5:
                    incons.append((exp['scene'], role, 'target'))
                if (o['relation'] == 'faces' and err > 15.5) or (o['relation'] == 'angled_toward' and err > 45.5):
                    incons.append((exp['scene'], role, 'relation'))
    assert not missing, f'нет orientation: {missing[:5]}'
    assert not incons, f'orientation несогласована: {incons[:5]}'
