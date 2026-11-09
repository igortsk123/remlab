"""Текст объявления (T-20261109-04): разбор строк риелтора и сопоставление с подписями плана по имени."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import listing as ls  # noqa: E402


@pytest.mark.parametrize('line, name, dims, unit', [
    ('Lounge L:3.77m W:4.20m', 'Lounge', (3.77, 4.20), 'm'),
    ('Lounge 3.77m x 4.20m', 'Lounge', (3.77, 4.20), 'm'),
    ('Lounge 3.77 x 4.20', 'Lounge', (3.77, 4.20), 'm'),
    ('Kitchen/Diner: 5.10m × 3.05m', 'Kitchen/Diner', (5.10, 3.05), 'm'),
    ("Bedroom Two 12'3\" x 6'9\"", 'Bedroom Two', (3.734, 2.057), 'ft'),
    ("Bedroom 1 4.10m (13'5\") x 3.20m (10'6\") max", 'Bedroom 1', (4.10, 3.20), 'm'),
    ('Sitting Room - 5,16 m x 4,68 m', 'Sitting Room', (5.16, 4.68), 'm'),
])
def test_parse_line_formats(line, name, dims, unit):
    r = ls.parse_line(line)
    assert r is not None
    assert r['name'] == name
    assert r['dims_m'] == pytest.approx(dims, abs=0.002)
    assert r['unit'] == unit


def test_parse_line_notes_and_feet_check():
    r = ls.parse_line("Living Room 6.02m x 3.96m (19'9\" x 13'0\") into bay")
    assert 'into bay' in r['notes']
    assert 'conflict' not in r
    r = ls.parse_line("Study 3.20m x 2.10m (13'9\" x 6'11\")")        # 13'9" = 4,19 м — чтение не сошлось
    assert r['conflict'] == 'метры ≠ футы'
    r = ls.parse_line('Master Bedroom 4.50m x 3.60m (max)')
    assert r['notes'] == ['max']


def test_parse_line_without_two_sizes_is_none():
    assert ls.parse_line('Ground Floor') is None
    assert ls.parse_line('Gross internal area 125 sq m') is None
    assert ls.parse_line('Garden 30m') is None


def test_parse_listing_name_on_line_above():
    rows = ls.parse_listing('GROUND FLOOR\nLounge\n3.77m x 4.20m\n\nKitchen 3.10m x 2.40m\n')
    assert [(r['name'], r['dims_m']) for r in rows] == [('Lounge', (3.77, 4.20)), ('Kitchen', (3.10, 2.40))]


def test_norm_name_numbers_case_separators():
    assert ls.norm_name('Bedroom One') == ls.norm_name('BEDROOM 1') == ls.norm_name('bedroom 01')
    assert ls.norm_name('Kitchen/Diner') == ls.norm_name('Kitchen & Diner') == ls.norm_name('kitchen and diner')
    assert ls.norm_name('Bedroom Two') != ls.norm_name('Bedroom 1')


def test_match_takes_text_size_and_flags_orphans():
    plan = [{'name': 'Lounge', 'dims': None}, {'name': 'Bedroom 1', 'dims': None}, {'name': 'Bathroom', 'dims': None},
            {'name': 'Kitchen', 'dims': (3.1, 2.4)}]
    rows = ls.parse_listing('Lounge L:3.77m W:4.20m\nBedroom One 3.50m x 3.00m max\nKitchen 2.40m x 3.10m\n'
                            'Utility 2.00m x 1.50m\n')
    got, orphans = ls.match(plan, rows)
    by = {g['name']: g for g in got}
    assert by['Lounge']['dims'] == (3.77, 4.20) and by['Lounge']['dims_src'] == 'text'
    assert by['Bedroom 1']['dims'] == (3.5, 3.0) and 'текст: max' in by['Bedroom 1']['text_flags']
    assert by['Kitchen']['dims_src'] == 'both'                         # порядок сторон не важен
    assert by['Bathroom']['dims'] is None and 'нет в тексте' in by['Bathroom']['text_flags']
    assert [o['name'] for o in orphans] == ['Utility']


def test_match_duplicate_names_not_guessed():
    plan = [{'name': 'Bedroom', 'dims': None}, {'name': 'Bedroom', 'dims': None}]
    rows = ls.parse_listing('Bedroom 3.00m x 3.00m\nBedroom 4.00m x 3.50m\n')
    got, orphans = ls.match(plan, rows)
    assert all(g['dims'] is None for g in got)
    assert all('повтор имени — текст не взят' in g['text_flags'] for g in got)
    assert len(orphans) == 2


def test_match_text_disagrees_with_plan_keeps_plan_and_flags():
    got, _ = ls.match([{'name': 'Study', 'dims': (3.2, 2.93)}], ls.parse_listing('Study 3.60m x 2.93m'))
    assert got[0]['dims'] == (3.2, 2.93)
    assert any('≠ план' in f for f in got[0]['text_flags'])


# ── общая площадь (T-20261109-26) ──

@pytest.mark.parametrize('text, m2, conv, approx', [
    ('Total area 72.5 m²', 72.5, 'gia', False),
    ('Approx. Gross Internal Area 780 sq ft', 72.46, 'gia', True),
    ('Approximate total area\n1,347 sq ft / 125.2 sq m', 125.2, 'gia', True),
    ('GIA: 90.3 sqm (973 sq ft)', 90.3, 'gia', False),
    ('Общая площадь 54,3 м²', 54.3, 'rooms', False),
    ('Квартира, площадь общая — 61 кв. м', 61.0, 'rooms', False),
    ('Lovely flat.\n780 sq ft of space', 72.46, 'gia', False),
])
def test_total_area_formats(text, m2, conv, approx):
    a = ls.total_area(text)
    assert a is not None and a['m2'] == pytest.approx(m2, abs=0.05)
    assert a['conv'] == conv and a['approx'] is approx and a['src'] == 'text'


def test_total_area_keyed_wins_and_ambiguous_is_none():
    txt = 'Lounge 3.77m x 4.20m\nBedroom 1 12.4 m²\nTotal area 72.5 m² (excl. balcony and garage)\n'
    a = ls.total_area(txt)
    assert a['m2'] == 72.5 and set(a['excl']) == {'balcon', 'garage'}
    assert ls.total_area('Bedroom 1 12.4 m²\nBedroom 2 9.8 m²') is None          # две разные площади без ключа — не угадываем
    assert ls.total_area('Total area 72.5 m²\nTotal area 95 m²') is None           # две разные «общие»
    assert ls.total_area('Lounge 3.77m x 4.20m\nKitchen 12\'3" x 6\'9"') is None  # размеры комнат — не площадь
    assert ls.total_area('') is None and ls.total_area('Total area 3 m²') is None
    assert 'area_m2_ne_sqft' in ls.total_area('Total area 72.5 m² / 900 sq ft')['flags']


def test_sheet_area_total_label_or_sum_of_parts():
    rows = [{'label': 'Farmhouse', 'm2': 213.1}, {'label': 'Garage', 'm2': 71.6}, {'label': 'Total', 'm2': 804.1}]
    assert ls.sheet_area(rows)['m2'] == 804.1 and ls.sheet_area(rows)['flags'] == []
    parts = ls.sheet_area([{'label': 'Ground Floor', 'm2': 63.9}, {'label': 'First Floor', 'm2': 61.3}])
    assert parts['m2'] == 125.2 and parts['flags'] == ['area_sum_of_parts']
    ex = ls.sheet_area([{'label': 'Approximate total area (excl. balconies)', 'm2': 90.3}])
    assert ex['excl'] == ['balcon'] and ex['approx'] and ex['src'] == 'sheet'
    assert ls.sheet_area([]) is None and ls.sheet_area([{'label': 'x', 'm2': 'n/a'}]) is None


def test_pick_area_text_and_sheet():
    t, s = ls.total_area('Total area 90 m²'), ls.sheet_area([{'label': 'Total', 'm2': 91.0}])
    a, fl = ls.pick_area(t, s)
    assert a['src'] == 'both' and a['m2'] == 90 and fl == []
    a, fl = ls.pick_area(t, ls.sheet_area([{'label': 'Total', 'm2': 120.0}]))
    assert a is None and fl == ['area_conflict']                                    # разошлись > 5 % — опоры нет, флаг
    assert ls.pick_area(None, s)[0]['src'] == 'sheet' and ls.pick_area(None, None) == (None, [])
