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


def test_large_banks_have_second_armchair_alternative():
    """P4 свода №12 (владелец №174): large-банк (≥25 м² = room_mode large) с диваном и
    креслом содержит кресло 2 (пара → sofa_2armchairs достижим) или явный coverage_gap."""
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = []
    for i, st in enumerate(sets, 1):
        items = st.get('items') or {}
        if (st.get('m2') or 0) < 25 or 'диван' not in items or 'кресло' not in items:
            continue
        if 'кресло 2' in items or int(items['кресло'].get('qty') or 1) >= 2:
            continue   # qty=2 — пара уже в банке (кресло 2 = экземпляр первого SKU)
        if any('кресло 2' in str(g) for g in (st.get('gaps') or [])):
            continue
        bad.append(i)
    assert not bad, f'large-сеты без второго кресла и без gap: {bad[:10]}'


def test_second_pod_pair_is_one_sku_from_25m2():
    """Q5 свода №13: с 25 м² банк содержит пару кресел 3/4 ОДНОГО SKU (pair_key) или явный gap;
    кресло 2 (alt) — экземпляр основного кресла (не другой магазин)."""
    sets = json.load(open(os.path.join(SCOUT, 'sets3.json'), encoding='utf-8'))
    bad = []
    for i, st in enumerate(sets, 1):
        it = st.get('items') or {}
        m2 = st.get('m2') or 0
        if m2 >= 25 and 'диван' in it:
            if 'кресло 3' in it and 'кресло 4' in it:
                k3 = f"{it['кресло 3'].get('mid')}:{it['кресло 3'].get('eid')}"
                k4 = f"{it['кресло 4'].get('mid')}:{it['кресло 4'].get('eid')}"
                if k3 != k4:
                    bad.append((i, 'пара 3/4 разных SKU'))
                # Q5 (Codex, каталог): pod-комплект АТОМАРЕН — пара + столик 2 (малая поверхность),
                # без поверхности пары нет (владелец №181: «пара визави без стола — зачем»)
                s2 = it.get('столик 2')
                if not s2 or s2.get('pod_key') != it['кресло 3'].get('pod_key'):
                    bad.append((i, 'пара 3/4 без столика 2 (pod_key)'))
                else:
                    dia, w, d = s2.get('dia'), s2.get('w') or 0, s2.get('d') or 0
                    if not ((dia and 35 <= dia <= 70) or (0 < w <= 70 and 0 < d <= 70)):
                        bad.append((i, f'столик 2 не малый: {dia or (w, d)}'))
                for r in ('кресло 3', 'кресло 4'):
                    if (it[r].get('w') or 999) > 100 or (it[r].get('d') or 999) > 105:
                        bad.append((i, f'{r} не компактное {it[r].get("w")}×{it[r].get("d")}'))
            elif not any('quiet_pod' in str(g) or 'кресло 3/4' in str(g) for g in (st.get('gaps') or [])):
                bad.append((i, 'нет pod-комплекта и нет gap'))
        if 'кресло 2' in it and it['кресло 2'].get('alt') and 'кресло' in it:
            if (it['кресло 2'].get('mid'), it['кресло 2'].get('eid')) != (it['кресло'].get('mid'), it['кресло'].get('eid')):
                bad.append((i, 'alt-кресло 2 не экземпляр основного'))
    assert not bad, f'Q5 нарушения банка: {bad[:8]}'
