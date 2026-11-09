"""Сравнение слепого прогона с эталоном (T-20261109-04): разбор сторон эталона и пары по имени/размеру."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import blind_cmp as bc  # noqa: E402


def test_parse_sides_forms():
    assert bc.parse_sides('3.77 x 4.20') == ((3.77, 4.2), False, False)
    assert bc.parse_sides('~3.5 x 2.1')[1] is True
    assert bc.parse_sides('-') == (None, False, True)
    s, _, _ = bc.parse_sides("12'3\" x 6'9\"")
    assert abs(s[0] - 3.734) < 0.01 and abs(s[1] - 2.057) < 0.01


def test_pair_same_names_by_nearest_size_and_flags_ambiguous():
    refs = [{'name': 'Bedroom', 'sheet': 'First', 'sides': (3.0, 4.0)},
            {'name': 'Bedroom', 'sheet': 'First', 'sides': (2.5, 2.6)},
            {'name': 'Kitchen', 'sheet': 'Ground', 'sides': (4.0, 3.0)}]
    ours = [{'name': 'Bedroom', 'panel': 'First Floor', 'label': (2.5, 2.6), 'ours': (2.5, 2.6)},
            {'name': 'Bedroom', 'panel': 'First Floor', 'label': (4.0, 3.0), 'ours': (4.0, 3.0)},
            {'name': 'kitchen', 'panel': 'Ground Floor', 'label': None, 'ours': (3.1, 4.0)},
            {'name': 'Study', 'panel': 'Ground Floor', 'label': None, 'ours': None}]
    res, unpaired = bc.pair(refs, ours)
    assert res[0][0] == 1 and res[1][0] == 0 and res[2][0] == 2
    assert res[0][1] is False                       # альтернатива далеко по размеру — однозначно
    assert unpaired == [3]
    assert abs(bc.err((3.0, 4.0), (4.1, 2.9)) - 0.1) < 1e-9
