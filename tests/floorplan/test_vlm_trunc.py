"""T-20261110-27: оборванный ответ VLM (finish=length) не теряет этажи молча.

Повтор с низким «думанием» на остаток потолка задания (`pipeline.ensure_vlm`/`_retry_truncated`), флаг `vlm_truncated:<вид>`,
перерисовка — весь лист (`redraw.crop_box`), разбор — без оборванных контуров (`bench.load_vlm`), делёж листа по заголовкам
этажей (`bench.panels_by_titles`, владелец TG 775), выбор ответа подписей (`vlm.label_kind`: labels3, старый кэш — labels2).
Лёгкие: без сети, без стенда."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import pipeline as pl  # noqa: E402
import redraw  # noqa: E402
import vlm  # noqa: E402

FULL = {'panels': '{"panels": [{"title": "Ground Floor", "poly": [[0,0],[400,0],[400,500],[0,500]], "rooms": []}, '
                  '{"title": "First Floor", "poly": [[500,0],[900,0],[900,500],[500,500]], "rooms": []}]}',
        'labels3': '{"rooms": [], "areas": [], "titles": []}', 'unlabeled': '{"spaces": []}'}
CUT = '{"panels": [{"title": "Ground Floor", "poly": [[0,0],[400,0],[400,500],[0,500]], "rooms": []}, {"title": "First Fl'


def scripted_ask(log, script, usd=0.01):
    """script: {вид: [(finish, raw), …]} — ответы по очереди; запись в calls.jsonl, как `vlm.ask`."""
    def ask(plan, kind, out, image=None, cap_usd=None, effort=None):
        log.append((kind, round(cap_usd, 4), effort))
        q = script[kind]
        finish, raw = q.pop(0) if len(q) > 1 else q[0]
        Path(out).mkdir(parents=True, exist_ok=True)
        with open(Path(out) / 'calls.jsonl', 'a') as f:
            f.write(json.dumps({'kind': kind, 'usd': usd, 'finish': finish, **({'effort': effort} if effort else {})}) + '\n')
        (Path(out) / f'raw-{plan}-{kind}.txt').write_text(raw)
    return ask


def test_truncated_answer_is_retried_with_low_effort_on_job_budget(tmp_path):
    log = []
    ask = scripted_ask(log, {'panels': [('length', CUT), ('stop', FULL['panels'])],
                             'labels3': [('stop', FULL['labels3'])], 'unlabeled': [('stop', FULL['unlabeled'])]})
    v = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=ask, cap_usd=0.09)
    assert sorted(v['asked']) == ['labels3', 'panels', 'unlabeled']
    assert v['retried'] == {'panels': 'ok'}
    retry = [c for c in log if c[2] == 'low']
    # повтор — один, вид panels, потолок = уже потрачено в папке вопроса (0,01) + остаток задания (0,09 − 0,03)
    assert retry == [('panels', 0.07, 'low')]
    assert v['usd'] == pytest.approx(0.04)
    d = vlm.parse((tmp_path / 'raw-T-panels.txt').read_text())
    assert len(d['panels']) == 2 and not d.get('_truncated')
    assert (tmp_path / 'panels' / 'raw-T-panels-try1.txt').read_text() == CUT    # первый ответ сохранён рядом
    assert pl.truncated_flags(tmp_path) == []


def test_retry_still_truncated_keeps_longer_and_flags(tmp_path):
    longer = CUT
    shorter = '{"panels": [{"title": "Gro'
    ask = scripted_ask([], {'panels': [('length', longer), ('length', shorter)],
                            'labels3': [('stop', FULL['labels3'])], 'unlabeled': [('stop', FULL['unlabeled'])]})
    v = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=ask, cap_usd=0.09)
    assert v['retried'] == {'panels': 'still'}
    assert (tmp_path / 'raw-T-panels.txt').read_text() == longer
    assert pl.truncated_flags(tmp_path) == ['vlm_truncated:panels']


def test_retry_without_budget_keeps_first_answer(tmp_path):
    calls = []

    def ask(plan, kind, out, image=None, cap_usd=None, effort=None):
        calls.append(effort)
        if effort:
            raise SystemExit('остаток мал для вызова')
        scripted_ask([], {'panels': [('length', CUT)], 'labels3': [('stop', FULL['labels3'])],
                          'unlabeled': [('stop', FULL['unlabeled'])]})(plan, kind, out, image, cap_usd)
    v = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=ask, cap_usd=0.09)
    assert v['retried'] == {'panels': 'budget'} and calls.count('low') == 1
    assert (tmp_path / 'raw-T-panels.txt').read_text() == CUT
    assert pl.truncated_flags(tmp_path) == ['vlm_truncated:panels']


def test_cached_answers_are_not_retried(tmp_path):
    """Оборванный ответ в КЭШЕ (старые задания): повтора нет (0 $), только флаг."""
    (tmp_path / 'raw-T-labels2.txt').write_text('{"rooms": []}')
    (tmp_path / 'raw-T-panels.txt').write_text(CUT)
    (tmp_path / 'raw-T-unlabeled.txt').write_text(FULL['unlabeled'])
    log = []
    v = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=scripted_ask(log, {}))
    assert log == [] and v['usd'] == 0 and v['retried'] == {}
    assert pl.truncated_flags(tmp_path) == ['vlm_truncated:panels']


def test_label_kind_new_sheet_labels3_old_cache_labels2(tmp_path, monkeypatch):
    assert vlm.label_kind(tmp_path, 'T') == 'labels3'                    # новый лист — вопрос с заголовками
    (tmp_path / 'raw-T-labels2.txt').write_text('{}')
    assert vlm.label_kind(tmp_path, 'T') == 'labels2'                    # старый кэш — без нового платного вопроса
    (tmp_path / 'raw-T-labels3.txt').write_text('{}')
    assert vlm.label_kind(tmp_path, 'T') == 'labels3'
    monkeypatch.setenv('FP_TITLES', '0')
    assert vlm.label_kind(tmp_path, 'T') == 'labels2'


def test_crop_box_truncated_panels_whole_sheet(tmp_path):
    (tmp_path / 'raw-T-panels.txt').write_text(CUT)
    assert redraw.crop_box(1994, 1171, tmp_path, 'T') == [0, 0, 1994, 1171]
    (tmp_path / 'raw-T-panels.txt').write_text(FULL['panels'])
    box = redraw.crop_box(1994, 1171, tmp_path, 'T')
    assert box != [0, 0, 1994, 1171] and box[2] > 0.85 * 1994          # оба этажа целого ответа в рамке


def test_load_vlm_ignores_truncated_panels_and_reads_titles(tmp_path, monkeypatch):
    (tmp_path / 'raw-T-panels.txt').write_text(CUT)
    (tmp_path / 'raw-T-labels3.txt').write_text(json.dumps({'rooms': [{'name': 'Kitchen', 'pt': [100, 200], 'dims_m': [3, 4]}],
                                                            'titles': [{'title': ' Ground  Floor ', 'pt': [200, 550]},
                                                                       {'title': 'First Floor', 'pt': [700, 550]},
                                                                       {'title': '', 'pt': [1, 1]}, {'title': 'X'}]}))
    monkeypatch.setenv('FP_LABELS', 'labels3')
    v = bench.load_vlm('T', str(tmp_path), (1000, 2000))
    assert v['panels'] == [] and v['panels_truncated'] is True
    assert [t['title'] for t in v['titles']] == ['Ground Floor', 'First Floor']
    assert v['titles'][1]['pt'] == (1400.0, 550.0)                       # сетка 0–1000 → px листа
    (tmp_path / 'raw-T-panels.txt').write_text(FULL['panels'])
    v = bench.load_vlm('T', str(tmp_path), (1000, 2000))
    assert len(v['panels']) == 2 and v['panels_truncated'] is False


def _sheet():
    """Лист 1000×600 px, ppm 20: два куска первого этажа (дом + пристройка слева) и кусок второго справа;
    заголовки под этажами."""
    m = np.zeros((600, 1000), np.uint8)
    for x0, y0, x1, y1 in ((50, 50, 300, 400), (320, 300, 420, 400), (600, 50, 900, 400)):
        m[y0:y1, x0:x0 + 6] = 1; m[y0:y1, x1 - 6:x1] = 1; m[y0:y0 + 6, x0:x1] = 1; m[y1 - 6:y1, x0:x1] = 1
    return m


def test_panels_by_titles_groups_pieces_by_nearest_title():
    titles = [{'title': 'Ground Floor', 'pt': (230.0, 450.0)}, {'title': 'First Floor', 'pt': (750.0, 450.0)},
              {'title': 'Cellar', 'pt': (980.0, 580.0)}]
    pan, ttl = bench.panels_by_titles(_sheet(), 20.0, titles, 1000, 600)
    assert ttl == ['Ground Floor', 'First Floor']                         # заголовок без куска — без панели
    g, f = pan
    assert g[0] <= 30 and g[2] >= 440 and f[0] >= 560                       # пристройка — к своему этажу
    assert g[5]((100, 100)) and g[5]((370, 350)) and not g[5]((700, 100))
    assert f[5]((700, 100)) and not f[5]((100, 100)) and not f[5]((500, 580))
    assert g[4][100, 100] == 1 and g[4][100, 700] == 0                     # маска панели — только её куски


def test_panels_by_titles_duplicate_titles_get_numbers():
    titles = [{'title': 'Floor', 'pt': (170.0, 450.0)}, {'title': 'Floor', 'pt': (750.0, 450.0)}]
    _, ttl = bench.panels_by_titles(_sheet(), 20.0, titles, 1000, 600)
    assert ttl == ['Floor 1', 'Floor 2']
