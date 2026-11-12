"""T-20261112-52: превью чертежа агента рядом с нашим планом (`tools/floorplan/source_preview.py`, `pipeline.sheet_frame`,
`trial_bundle.source_meta`, `reissue.sources_main`). Лёгкие: синтетический лист, без сети и стенда."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.append(str(ROOT / 'tools' / 'scout'))          # в конец: у scout свой pipeline.py
import pipeline as pl  # noqa: E402
import reissue as RS  # noqa: E402
import source_preview as SP  # noqa: E402
import trial_bundle as TB  # noqa: E402


def rect(rid, x0, y0, x1, y1):
    return {'id': rid, 'bbox': {'x': x0, 'y': y0, 'w': x1 - x0, 'd': y1 - y0}, 'contour': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def two_floors():
    """Лист 1200×500: этаж 1 — вырез с (100, 50), 0,5 px/см; этаж 2 — с (700, 50), 0,4 px/см (свой масштаб — каждый этаж к своей панели)."""
    p0 = {'id': 'p0', 'sheet': {'x0': 100, 'y0': 50, 'pxPerCm': 0.5}, 'rooms': [rect('a', 0, 0, 600, 400), rect('b', 600, 0, 900, 400)]}
    p1 = {'id': 'p1', 'sheet': {'x0': 700, 'y0': 50, 'pxPerCm': 0.4}, 'rooms': [rect('c', 0, 0, 800, 500)]}
    return {'source': {'mime': 'application/pdf', 'pages': 3, 'usedPages': 2}, 'panels': [p0, p1]}


def sheet(tmp_path, w=1200, h=500):
    im = Image.new('RGB', (w, h), (255, 255, 255))
    im.paste((200, 0, 0), (100, 50, 100 + 450, 50 + 200))      # этаж 1: 900×400 см × 0,5
    im.paste((0, 0, 200), (700, 50, 700 + 320, 50 + 200))      # этаж 2: 800×500 см × 0,4
    p = tmp_path / 'sheet.png'
    im.save(p)
    return p


def test_crop_is_rooms_plus_pad_in_sheet_pixels():
    p = two_floors()['panels'][0]
    pad = SP.PAD_CM * 0.5
    assert SP._crop(p, 1200, 500) == [100 - pad, 50 - pad, 450 + 2 * pad, 200 + 2 * pad]
    assert SP._crop(p, 300, 200) == [80, 30, 220, 170]             # в пределах листа
    assert SP._crop({'id': 'x', 'rooms': p['rooms']}, 1200, 500) is None          # нет рамки (старый результат)
    assert SP._crop({'id': 'x', 'sheet': p['sheet'], 'rooms': []}, 1200, 500) is None


def test_make_two_floors_stacked_webp_without_exif(tmp_path):
    out = tmp_path / 'source.webp'
    meta = SP.make(sheet(tmp_path), two_floors(), out)
    assert [c['panel'] for c in meta['crops']] == ['p0', 'p1']
    a, b = meta['crops']
    assert a['sheet'] == [80, 30, 490, 240] and b['sheet'] == [684, 34, 352, 232]
    assert a['at'] == [0, 0, 490, 240] and b['at'] == [0, 240 + SP.GAP_PX, 352, 232]     # стопкой — так длинная сторона меньше
    assert (meta['w'], meta['h']) == (490, 240 + SP.GAP_PX + 232)
    data = out.read_bytes()
    assert data[:4] == b'RIFF' and data[8:12] == b'WEBP' and b'EXIF' not in data
    with Image.open(io.BytesIO(data)) as im:
        assert im.size == (meta['w'], meta['h'])
        px = im.convert('RGB').getpixel((a['at'][0] + 20 + 10, a['at'][1] + 20 + 10))   # внутри этажа 1 (отступ 20 px)
        assert px[0] > 150 and px[2] < 80
        q = im.convert('RGB').getpixel((b['at'][0] + 16 + 10, b['at'][1] + 16 + 10))
        assert q[2] > 150 and q[0] < 80
    assert not list(tmp_path.glob('.*.tmp'))


def test_make_large_sheet_scaled_to_max_side(tmp_path):
    res = {'panels': [{'id': 'p0', 'sheet': {'x0': 0, 'y0': 0, 'pxPerCm': 4.0}, 'rooms': [rect('a', 0, 0, 800, 300)]}]}
    meta = SP.make(sheet(tmp_path, 3400, 1300), res, tmp_path / 's.webp')
    assert max(meta['w'], meta['h']) <= SP.MAX_SIDE_PX
    c = meta['crops'][0]
    assert c['sheet'][2] / c['at'][2] == pytest.approx(c['sheet'][3] / c['at'][3], rel=0.01)   # пропорции выреза те же


def test_make_without_frames_writes_nothing(tmp_path):
    res = {'panels': [{'id': 'p0', 'rooms': [rect('a', 0, 0, 100, 100)]}]}
    assert SP.make(sheet(tmp_path), res, tmp_path / 's.webp') is None and not (tmp_path / 's.webp').exists()


def test_page_mapping_puts_drawing_exactly_under_our_rooms(tmp_path):
    """Формула страницы (`index.html:trSrcPlan` + `trPlanLayout`): вырез в метрах схемы = ox + ((X − x0)/pxPerCm − bbox_x0)/100.
    Комната «a» этажа 1 в схеме [0..6]×[0.7..4.7] м; её пиксели на картинке после переноса — ровно там же."""
    res = two_floors()
    meta = SP.make(sheet(tmp_path), res, tmp_path / 's.webp')
    tf = {'p0': {'ox': 0.0, 'top': 0.7, 'x0': 0, 'y0': 0}, 'p1': {'ox': 9 + 1.5, 'top': 0.7, 'x0': 0, 'y0': 0}}
    for c in meta['crops']:
        f, t = next(p['sheet'] for p in res['panels'] if p['id'] == c['panel']), tf[c['panel']]
        mx = t['ox'] + ((c['sheet'][0] - f['x0']) / f['pxPerCm'] - t['x0']) / 100
        my = t['top'] + ((c['sheet'][1] - f['y0']) / f['pxPerCm'] - t['y0']) / 100
        mw = c['sheet'][2] / f['pxPerCm'] / 100
        assert mx == pytest.approx(t['ox'] - SP.PAD_CM / 100) and my == pytest.approx(t['top'] - SP.PAD_CM / 100)
        rooms = next(p['rooms'] for p in res['panels'] if p['id'] == c['panel'])
        assert mx + mw == pytest.approx(t['ox'] + max(r['bbox']['x'] + r['bbox']['w'] for r in rooms) / 100 + SP.PAD_CM / 100)


def test_sheet_frame_matches_bench_scale():
    """Рамка панели = угол выреза `bbox_px` + см × ppm/(k·100) — как `outdoor.exits` и `bench.poly_m`."""
    P = {'ppm': 50.0, 'bbox_px': [120, 80, 400, 300]}
    assert pl.sheet_frame(P) == {'x0': 120, 'y0': 80, 'pxPerCm': 0.5}
    assert pl.sheet_frame(P, 1.25) == {'x0': 120, 'y0': 80, 'pxPerCm': 0.4}
    assert pl.sheet_frame({'ppm': 0, 'bbox_px': [0, 0, 1, 1]}) is None and pl.sheet_frame({'ppm': 50}) is None


def test_add_preview_failure_does_not_break_job(tmp_path, capsys):
    res = {'source': {}, 'panels': []}
    pl.add_preview(res, tmp_path / 'missing.png', tmp_path)
    assert 'preview' not in res['source'] and 'preview:' in capsys.readouterr().err


def test_bundle_source_meta_pages_and_crops():
    res = two_floors()
    res['source']['preview'] = {'w': 10, 'h': 5, 'crops': [{'panel': 'p0', 'sheet': [1, 2, 3, 4], 'at': [0, 0, 10, 5]}]}
    assert TB.source_meta(res) == {'source': {'w': 10, 'h': 5, 'crops': res['source']['preview']['crops'], 'pdf': True,
                                              'pages': 3, 'used': 2}}
    assert TB.source_meta(two_floors()) == {}
    TB.assert_public(TB.source_meta(res), [], goods=True)                 # ни ссылок, ни запрещённых полей


class Api:
    def __init__(self, rows):
        self.rows = rows

    def call(self, method, path, body=None, read_max=None):
        jid = path.rsplit('/', 1)[-1]
        r = self.rows.get(jid)
        return (200, {'ok': True, **r}) if r else (410, {'ok': False, 'error': 'expired'})


def test_reissue_sources_dry_list(capsys):
    """`reissue.py --sources`: только список — у каких туров жив исходник; ничего не ставит (одни GET)."""
    api = Api({'A' * 22: {'hasSource': True}, 'B' * 22: {'hasSource': False}, 'C' * 22: {'hasSource': True, 'hasPreview': True}})
    assert RS.sources_main(api, ['A' * 22, 'B' * 22, 'C' * 22, 'D' * 22]) == 0
    out = capsys.readouterr().out
    assert 'есть файл, без превью — 1' in out and 'файла нет — 1' in out and 'превью уже есть — 1' in out and 'пропущен — 1' in out


def test_reissue_sources_flag_wired(monkeypatch):
    seen = {}
    monkeypatch.setattr(RS, 'sources_main', lambda api, ids: seen.setdefault('ids', ids) and 0)
    cfg = SimpleNamespace(token='t' * 40)
    assert RS.main(['--sources', '--job', 'A' * 22], api=Api({}), cfg=cfg) == 0 and seen['ids'] == ['A' * 22]
