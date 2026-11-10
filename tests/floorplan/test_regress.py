"""Регресс по комнатам (T-20261110-38/3): двери и окна комнаты, метки «сломано/исправлено», отказ сравнивать код с собой."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import regress as rg  # noqa: E402


def _room(name, x0, y0, x1, y1, kind='bedroom'):
    return {'id': name, 'name': name, 'kind': kind, 'areaM2': (x1 - x0) * (y1 - y0) / 1e4,
            'contour': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def _res(doors, windows=((150, 0),)):
    """Две комнаты 0–300 и 300–600 по x; двери — середины на общей стене x=300 (или где задано), окна — на y=0."""
    ops = [{'kind': 'door', 'c': list(c), 'widthCm': 80} for c in doors]
    ops += [{'kind': 'window', 'c': list(c), 'widthCm': 120} for c in windows]
    return {'panels': [{'id': 'p0', 'rooms': [_room('Bedroom', 0, 0, 300, 400), _room('Hall', 300, 0, 600, 400, 'hall')],
                        'openings': ops}]}


def test_summarize_assigns_shared_door_to_both_rooms():
    s = rg.summarize(_res([(300, 200)]))
    assert s['doors'] == 1 and s['windows'] == 1 and s['rooms'] == 2
    assert s['named']['p0/Bedroom'][0]['doors'] == 1 and s['named']['p0/Hall'][0]['doors'] == 1
    assert s['named']['p0/Bedroom'][0]['windows'] == 1 and s['named']['p0/Hall'][0]['windows'] == 0


def test_lost_all_doors_is_broken_fewer_is_changed():
    rows, tot = rg.compare({'s': _res([(300, 100), (300, 300)])}, {'s': _res([])})
    marks = {(k, m) for _, k, m, _ in rows}
    assert ('p0/Bedroom', 'СЛОМАНО') in marks and tot['СЛОМАНО'] == 2
    rows, tot = rg.compare({'s': _res([(300, 100), (300, 300)])}, {'s': _res([(300, 100)])})
    assert 'СЛОМАНО' not in tot and ('s', 'p0/Bedroom', 'ИНАЧЕ', 'дверей 2 → 1, окон 1 → 1') in rows


def test_missing_room_and_failed_sheet_are_broken_accept_marks_intended():
    b = _res([(300, 200)])
    b['panels'][0]['rooms'].pop()
    rows, tot = rg.compare({'s': _res([(300, 200)])}, {'s': b, 't': {'_error': 'pipeline_error'}} | {})
    assert ('s', 'p0/Hall', 'СЛОМАНО', 'комнаты нет') in rows
    rows, tot = rg.compare({'s': _res([(300, 200)]), 't': _res([])}, {'s': _res([(300, 200)]), 't': {'_error': 'x'}})
    assert ('t', '*', 'СЛОМАНО', 'лист не собрался: x') in rows
    rows, tot = rg.compare({'s': _res([(300, 200)])}, {'s': b}, accept={('s', 'p0/Hall'): 'кладовка, не комната'})
    assert tot.get('СЛОМАНО') is None and tot['ПРИНЯТО'] == 1


def test_same_name_rooms_paired_by_nearest_centre():
    a = [{'c': (0, 0), 'n': 'a0'}, {'c': (500, 0), 'n': 'a1'}]
    b = [{'c': (490, 10), 'n': 'b1'}]
    pairs, oa, ob = rg.pair_rooms(a, b)
    assert [(x['n'], y['n']) for x, y in pairs] == [('a1', 'b1')] and [x['n'] for x in oa] == ['a0'] and not ob


def test_cmp_refuses_same_code(tmp_path):
    for side in ('a', 'b'):
        d = tmp_path / side
        (d / 's').mkdir(parents=True)
        (d / 's' / 'result.json').write_text(json.dumps(_res([(300, 200)])))
        (d / 'manifest.json').write_text(json.dumps({'code_sha': 'abc', 'rev': 'x', 'env': {}, 'cases': {'s': {}}}))
    assert rg.main(['cmp', str(tmp_path / 'a'), str(tmp_path / 'b'), '--no-core']) == 3
    assert rg.main(['cmp', str(tmp_path / 'a'), str(tmp_path / 'b'), '--no-core', '--allow-same']) == 0


def test_code_sha_tracks_floorplan_sources(tmp_path):
    fp = tmp_path / 'tools' / 'floorplan'
    fp.mkdir(parents=True)
    (fp / 'bench.py').write_text('x = 1\n')
    h1 = rg.code_sha(tmp_path)
    (fp / 'bench.py').write_text('x = 2\n')
    assert rg.code_sha(tmp_path) != h1


def test_read_cases_expands_home_and_optional_columns(tmp_path):
    f = tmp_path / 'c.tsv'
    f.write_text('# комментарий\nx\t~/a.png\t-\ny\t/b.png\t/l.txt\t~/v\n')
    c = rg.read_cases(f)
    assert c[0]['listing'] is None and c[0]['vlm_dir'] is None and not c[0]['image'].startswith('~')
    assert c[1]['listing'] == '/l.txt' and c[1]['vlm_dir'].endswith('/v')
