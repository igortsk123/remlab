"""T-20261110-27/2: делёж листа — целые контуры VLM, сведённые по заголовку (`bench.vlm_groups`), если с ними сходятся
заголовки этажей (`bench.titles_vs_vlm`); иначе — куски по заголовкам с флагами (`bench.panels_by_titles`); потолок панелей 6
(`pipeline.MAX_PANELS` = контракт). Лёгкие: без сети, без стенда."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import pipeline as pl  # noqa: E402


def P(title, x0, y0, x1, y1):
    return {'title': title, 'poly': np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)}


def test_vlm_groups_same_title_one_panel_untitled_apart():
    ps = [P('Ground Floor', 0, 0, 10, 10), P('Outbuildings', 20, 0, 30, 10), P('First  floor', 40, 0, 50, 10),
          P('outbuildings', 20, 20, 30, 30), P('', 60, 0, 70, 10), P(None, 80, 0, 90, 10), P('First Floor', 40, 20, 50, 30)]
    assert bench.vlm_groups(ps) == [('Ground Floor', [0]), ('Outbuildings', [1, 3]), ('First floor', [2, 6]),
                                    ('', [4]), ('', [5])]


def test_titles_vs_vlm_agree_and_mixed_up():
    ps = [P('Ground Floor', 0, 0, 100, 100), P('First Floor', 200, 0, 300, 100), P('Cellar', 200, 200, 260, 260)]
    ts = [{'title': 'Ground Floor', 'pt': (50.0, 120.0)}, {'title': 'First Floor', 'pt': (250.0, 110.0)}]
    assert bench.titles_vs_vlm(ts, ps) == [('Ground Floor', 'Ground Floor'), ('First Floor', 'First Floor')]
    mixed = [P('Outbuildings', 0, 0, 100, 100), P('Ground Floor', 200, 0, 300, 100)]     # контуры перепутаны
    tv = bench.titles_vs_vlm(ts, mixed)
    assert tv[0] == ('Ground Floor', 'Outbuildings')
    assert any(bench.norm_title(a) != bench.norm_title(b) for a, b in tv)


def _sheet():
    """Лист 1000×600 px, ppm 20 (как в test_vlm_trunc): дом + пристройка слева, второй этаж справа."""
    m = np.zeros((600, 1000), np.uint8)
    for x0, y0, x1, y1 in ((50, 50, 300, 400), (320, 300, 420, 400), (600, 50, 900, 400)):
        m[y0:y1, x0:x0 + 6] = 1; m[y0:y1, x1 - 6:x1] = 1; m[y0:y0 + 6, x0:x1] = 1; m[y1 - 6:y1, x0:x1] = 1
    return m


def test_panels_by_titles_flags_guess_and_merged():
    # заголовки под этажами в 1 м (20 px): у пристройки своего нет (дом ближе 2 м — нет) → panel_title_guess
    fl = []
    bench.panels_by_titles(_sheet(), 20.0, [{'title': 'Ground Floor', 'pt': (170.0, 420.0)},
                                            {'title': 'First Floor', 'pt': (750.0, 420.0)}], 1000, 600, fl)
    assert 'panel_title_guess' in fl and 'panel_titles_merged' not in fl
    # у каждого куска свой заголовок рядом → без флагов
    fl = []
    bench.panels_by_titles(_sheet(), 20.0, [{'title': 'Ground Floor', 'pt': (170.0, 420.0)},
                                            {'title': 'Annexe', 'pt': (370.0, 420.0)},
                                            {'title': 'First Floor', 'pt': (750.0, 420.0)}], 1000, 600, fl)
    assert fl == []
    # два разных заголовка внутри одного куска (дом и постройки слиплись) → panel_titles_merged
    fl = []
    bench.panels_by_titles(_sheet(), 20.0, [{'title': 'Ground Floor', 'pt': (100.0, 100.0)},
                                            {'title': 'Outbuildings', 'pt': (250.0, 350.0)},
                                            {'title': 'Annexe', 'pt': (370.0, 420.0)},
                                            {'title': 'First Floor', 'pt': (750.0, 420.0)}], 1000, 600, fl)
    assert fl == ['panel_titles_merged']


def test_max_panels_matches_contract():
    s = json.loads((ROOT / 'tests' / 'fixtures' / 'trial-result.schema.json').read_text())
    assert s['properties']['panels']['maxItems'] == pl.MAX_PANELS == 6
