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
