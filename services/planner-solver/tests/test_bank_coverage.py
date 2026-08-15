"""C-6 свода №11 (MASTER-zones-v5): банк покрывает соседнюю ступень посадки."""
import json
import os

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def test_sofa_banks_have_armchair_alternative():
    """Сет с диваном от 17 м² содержит кресло (или явный coverage_gap)."""
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = []
    for i, st in enumerate(sets, 1):
        items = st.get('items') or {}
        if (st.get('m2') or 0) < 17 or 'диван' not in items:
            continue
        if 'кресло' in items:
            continue
        if any('coverage_gap' in str(g) for g in (st.get('gaps') or [])):
            continue
        bad.append(i)
    assert not bad, f'сеты с диваном без кресла и без coverage_gap: {bad[:10]}'
