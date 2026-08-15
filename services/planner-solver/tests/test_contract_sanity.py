"""C-1 свода №11 (MASTER-zones-v5): контракт-санация по аудиту Кодекса.

Сторожа: порядок исполнения цепочки зон соответствует zone_priority.order;
каждый терм score_layout явно классифицирован в _TERM_LEVEL; канон occupancy один.
"""
import json
import os
import re

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, '..', '..', '..')


def test_chain_order_matches_zone_priority():
    """Кодекс §4: dining → seating_extra → storage → decor (данные ведут код)."""
    src = open(os.path.join(HERE, '..', 'planner', 'zones.py'), encoding='utf-8').read()
    # скоуп: ОСНОВНАЯ цепочка (от '+din' до decor); фолбэк-пути (+tpl-wall, gap-fill)
    # имеют собственную семантику и порядком данных не управляются
    i = src.find("(_din, '+din')")
    j = src.find("(place_decor, '+dc')):", i)
    src = src[i:j + 20]
    zp = json.load(open(os.path.join(HERE, '..', 'rules', 'zones.json'),
                        encoding='utf-8'))['zone_priority']
    order, tags = zp['order'], zp['tags']
    chain_tags = re.findall(r"\(place_\w+, '(\+\w+)'\)|\(_din, '(\+din)'\)", src)
    seq = [a or b for a, b in chain_tags]
    # интересует относительный порядок зон с гейтом (без media/focus-кластера)
    zone_seq = [tags.get(t) for t in seq if tags.get(t) in
                ('dining', 'seating_extra', 'storage', 'decor')]
    ranks = [order.index(z) for z in zone_seq]
    assert ranks == sorted(ranks), f'порядок цепочки нарушает order: {zone_seq}'


def test_every_score_term_classified():
    """Кодекс §8: терм без классификации молча падал в zone_quality — запрещено."""
    score_src = open(os.path.join(HERE, '..', 'planner', 'score.py'),
                     encoding='utf-8').read()
    zones_src = open(os.path.join(HERE, '..', 'planner', 'zones.py'),
                     encoding='utf-8').read()
    terms = set(re.findall(r's\.add\(\s*"(\w+)"', score_src))
    m = re.search(r'_TERM_LEVEL\s*=\s*\{(.*?)\}', zones_src, re.S)
    classified = set(re.findall(r"'(\w+)':", m.group(1)))
    # динамические термы soft-правил (f'soft_rule_{code}') классифицируются
    # поимённо в _TERM_LEVEL; остальной динамике разрешён префикс
    missing = {t for t in terms - classified if not t.startswith('soft_rule_')}
    assert not missing, f'термы без яруса: {sorted(missing)}'


def test_single_occupancy_canon():
    """Кодекс §11: tools/scout/occupancy.json — симлинк на канон, не копия."""
    p = os.path.join(ROOT, 'tools', 'scout', 'occupancy.json')
    assert os.path.islink(p), 'scout-копия occupancy обязана быть симлинком на канон'
    canon = os.path.realpath(os.path.join(HERE, '..', 'rules', 'occupancy.json'))
    assert os.path.realpath(p) == canon


def test_cardinality_semantics_at_most_one():
    zp = json.load(open(os.path.join(HERE, '..', 'rules', 'zones.json'),
                        encoding='utf-8'))['zone_priority']
    assert zp['cardinality']['media']['rule'] == 'at_most_one_carrier'
