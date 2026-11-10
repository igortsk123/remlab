"""Модуль стенда для пробы агентов (agent-trial-01, T-B): слепой план → `floorplanResult`.

Лёгкие `test_area_*` (T-20261109-26) — масштаб по общей площади на синтетике: знаменатель GIA/комнаты, балкон и «excl.»,
конфликт с подписями — флаг, неправдоподобная площадь и пропущенные листы — прежний not_verified.
Тяжёлые (A/B/C, «без подписей», «без подписей, но с общей площадью листа», «размеры из текста») гоняют настоящий `bench.run_plan` на листах стенда и ответах VLM
из кэша (`~/remlab-logs/floorplan-bench/vlm-t04`, 0 $; платный вопрос — падение теста); запускать под
`tools/ops/heavy-slot.sh`. Нет кэша (CI, другая машина) — пропуск. TRIAL_TEST_FAST=1 — без C (C — 4–11 мин).
Результат сверяется с выгрузкой контракта `tests/fixtures/trial-result.schema.json` + refine «bbox — проекция контура».
"""
import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tools' / 'ops'))
import pipeline as pl  # noqa: E402

SCHEMA = json.loads((ROOT / 'tests' / 'fixtures' / 'trial-result.schema.json').read_text())
BENCH = Path('/home/pakar/remlab-logs/floorplan-bench')
VLM = BENCH / 'vlm-t04'
IMG = {'A': BENCH / 'inputs' / 'A-uk-house-125m2.jpg', 'B': BENCH / 'inputs' / 'B-uk-floor-90m2.jpg',
       'C': BENCH / 'inputs' / 'C-uk-nethercote-611m2.png'}
HAVE = VLM.is_dir() and all(p.exists() for p in IMG.values())
heavy = pytest.mark.skipif(not HAVE, reason='нет листов/кэша VLM стенда (только DEV)')


# ── сверка с JSON Schema контракта (подмножество draft 2020-12, которое выдаёт z.toJSONSchema) ──

def _is(t, v):
    return {'object': lambda: isinstance(v, dict), 'array': lambda: isinstance(v, list),
            'string': lambda: isinstance(v, str), 'boolean': lambda: isinstance(v, bool), 'null': lambda: v is None,
            'number': lambda: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
            'integer': lambda: isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()}[t]()


def check(s, v, p='$', errs=None):
    errs = [] if errs is None else errs
    if 'anyOf' in s:
        if not any(not check(sub, v, p, []) for sub in s['anyOf']):
            errs.append(f'{p}: ни один вариант anyOf')
        return errs
    t = s.get('type')
    if t and not (_is(t, v) if isinstance(t, str) else any(_is(x, v) for x in t)):
        errs.append(f'{p}: не {t}: {str(v)[:60]}')
        return errs
    if 'const' in s and v != s['const']:
        errs.append(f'{p}: != {s["const"]}')
    if 'enum' in s and v not in s['enum']:
        errs.append(f'{p}: {v!r} не из {s["enum"]}')
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        for k, ok in (('minimum', lambda a: v >= a), ('maximum', lambda a: v <= a),
                      ('exclusiveMinimum', lambda a: v > a), ('exclusiveMaximum', lambda a: v < a)):
            if k in s and not ok(s[k]):
                errs.append(f'{p}: {v} нарушает {k} {s[k]}')
    if isinstance(v, str):
        if len(v) < s.get('minLength', 0) or len(v) > s.get('maxLength', 1e9):
            errs.append(f'{p}: длина {len(v)}')
        if 'pattern' in s and not re.search(s['pattern'], v):
            errs.append(f'{p}: не по шаблону')
    if isinstance(v, list):
        if len(v) < s.get('minItems', 0) or len(v) > s.get('maxItems', 1e9):
            errs.append(f'{p}: элементов {len(v)}')
        pre = s.get('prefixItems', [])
        for i, x in enumerate(v):
            if i < len(pre):
                check(pre[i], x, f'{p}[{i}]', errs)
            elif s.get('items') is False:
                errs.append(f'{p}: лишний элемент {i}')
            elif isinstance(s.get('items'), dict):
                check(s['items'], x, f'{p}[{i}]', errs)
    if isinstance(v, dict):
        for k in s.get('required', []):
            if k not in v:
                errs.append(f'{p}: нет {k}')
        props = s.get('properties', {})
        for k, x in v.items():
            if 'propertyNames' in s:
                check(s['propertyNames'], k, f'{p}.<{k}>', errs)
            if k in props:
                check(props[k], x, f'{p}.{k}', errs)
            elif s.get('additionalProperties') is False:
                errs.append(f'{p}: лишнее поле {k}')
            elif isinstance(s.get('additionalProperties'), dict):
                check(s['additionalProperties'], x, f'{p}.{k}', errs)
    return errs


def assert_contract(res):
    json.dumps(res, allow_nan=False)                     # NaN/inf не пройдут ни JSON, ни Zod finite
    errs = check(SCHEMA, res)
    assert not errs, errs[:10]
    for p in res['panels']:
        for r in p['rooms']:                              # refine `contracts/trial.ts:room`
            xs, ys = [q[0] for q in r['contour']], [q[1] for q in r['contour']]
            b = r['bbox']
            assert abs(min(xs) - b['x']) < 1 and abs(min(ys) - b['y']) < 1, r['id']
            assert abs(max(xs) - b['x'] - b['w']) < 1 and abs(max(ys) - b['y'] - b['d']) < 1, r['id']
    assert len(json.dumps(res, separators=(',', ':'))) <= 2 * 1024 * 1024


def forbid_ask(*a, **kw):
    raise AssertionError(f'платный вызов VLM в тесте: {a}')


@pytest.fixture(scope='module')
def out_root():
    d = Path(os.environ.get('TRIAL_TEST_OUT') or Path.home() / 'remlab-logs' / 'trial-worker' /
             f'pytest-{time.strftime("%Y%m%d-%H%M%S")}')
    d.mkdir(parents=True, exist_ok=True)
    return d


def stripped_vlm(dst: Path, keep_areas: bool = False):
    """Кэш A для плана «T» без единого размера на листе (dims_m → null); общая площадь листа (125,2 м²) — только с keep_areas."""
    dst.mkdir(parents=True, exist_ok=True)
    import vlm
    d = vlm.parse((VLM / 'raw-A-labels2.txt').read_text())
    for r in d['rooms']:
        r['dims_m'] = None
    if not keep_areas:
        d['areas'] = []
    (dst / 'raw-T-labels2.txt').write_text(json.dumps(d))
    for k in ('panels', 'unlabeled'):
        shutil.copyfile(VLM / f'raw-A-{k}.txt', dst / f'raw-T-{k}.txt')
    return dst


# ── тяжёлые: настоящий стенд ──

PLANS = ['A', 'B'] + ([] if os.environ.get('TRIAL_TEST_FAST') == '1' else ['C'])


@heavy
@pytest.mark.parametrize('plan', PLANS)
def test_abc_from_vlm_cache_matches_contract(plan, out_root):
    stages = []
    res = pl.run(IMG[plan], '', out_root / plan, vlm_dir=VLM, plan=plan, ask=forbid_ask, slot=False,
                 stage=stages.append)
    assert_contract(res)
    assert res['costUsd'] == 0
    assert stages[:2] == ['labels', 'walls'] and stages[-1] == 'export'
    assert set(res['timings']) >= {'labels', 'walls', 'export'}
    rooms = [r for p in res['panels'] for r in p['rooms']]
    assert len(rooms) >= 5
    assert res['scale']['status'] in ('verified', 'listing', 'not_verified')
    if plan == 'A':
        assert res['scale']['status'] == 'verified' and res['scale']['inliers'] >= 2
        assert [p['title'] for p in res['panels']] == ['Ground Floor', 'First Floor']
        total = sum(r['areaM2'] for r in rooms)
        assert 80 < total < 160, total                     # лист — 125 м²
        kinds = {r['kind'] for r in rooms}
        assert {'kitchen', 'living', 'bedroom', 'hall', 'bathroom'} <= kinds
        kit = next(r for r in rooms if r['kind'] == 'kitchen')
        assert kit['dims']['src'] == 'plan' and sorted([kit['dims']['w'], kit['dims']['d']]) == [351.0, 684.0]
        # сантиметры: стороны контура кухни — того же порядка, что напечатанные 6,84 × 3,51 м
        assert 0.7 < max(kit['bbox']['w'], kit['bbox']['d']) / 684 < 1.3
    (out_root / f'result-{plan}.json').write_text(json.dumps(res))


@heavy
def test_no_printed_dims_is_not_verified(out_root):
    v = stripped_vlm(out_root / 'vlm-nodims')
    res = pl.run(IMG['A'], '', out_root / 'nodims', vlm_dir=v, ask=forbid_ask, slot=False)
    assert_contract(res)
    assert res['scale'] == {'status': 'not_verified', 'ppm': None, 'inliers': 0, 'n': 0}
    assert 'scale_from_wall_thickness' in res['flags']
    rooms = [r for p in res['panels'] for r in p['rooms']]
    assert rooms and all('scale_unverified' in r['flags'] for r in rooms)
    assert all('dims' not in r for r in rooms)


@heavy
def test_no_printed_dims_scale_from_sheet_area(out_root):
    """Размеров на листе нет, общая площадь листа есть (A: Total area 125,2 м²) → статус `area`, комнаты без `scale_unverified`,
    сумма комнат — доля GIA (комнаты без стен): не больше листа и не меньше 3/4."""
    v = stripped_vlm(out_root / 'vlm-area', keep_areas=True)
    res = pl.run(IMG['A'], '', out_root / 'area', vlm_dir=v, ask=forbid_ask, slot=False)
    assert_contract(res)
    sc = res['scale']
    assert sc['status'] == 'area' and sc['areaM2'] == 125.2 and sc['areaSrc'] == 'sheet' and sc['ppm'] > 0, sc
    assert 'scale_from_area' in res['flags'] and 'scale_from_wall_thickness' not in res['flags']
    rooms = [r for p in res['panels'] for r in p['rooms']]
    assert rooms and not any('scale_unverified' in r['flags'] for r in rooms)
    total = sum(r['areaM2'] for r in rooms)
    assert 0.75 * 125.2 <= total <= 125.2, total


@heavy
def test_dims_from_listing_text(out_root):
    v = stripped_vlm(out_root / 'vlm-listing')
    text = 'Room sizes\nLiving Room 4.10m x 3.45m\nKitchen/Dining Room 6.84m x 3.51m\nStudy 2.64m x 3.45m\n'
    res = pl.run(IMG['A'], text, out_root / 'listing', vlm_dir=v, ask=forbid_ask, slot=False)
    assert_contract(res)
    assert res['scale']['status'] == 'listing', res['scale']
    rooms = {r['name']: r for p in res['panels'] for r in p['rooms']}
    assert rooms['Living Room']['dims']['src'] == 'listing'
    assert 'scale_unverified' not in rooms['Living Room']['flags']


# ── лёгкие: без стенда ──

def fake_ask(log, usd=0.01):
    def ask(plan, kind, out, image=None, cap_usd=None):
        log.append((kind, cap_usd))
        Path(out).mkdir(parents=True, exist_ok=True)
        with open(Path(out) / 'calls.jsonl', 'a') as f:
            f.write(json.dumps({'kind': kind, 'usd': usd}) + '\n')
        (Path(out) / f'raw-{plan}-{kind}.txt').write_text('{"rooms": [], "panels": [], "spaces": []}')
    return ask


def test_vlm_cache_and_cap_share(tmp_path):
    (tmp_path / 'raw-T-labels2.txt').write_text('{"rooms": []}')
    calls = []
    v = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=fake_ask(calls), cap_usd=0.09)
    assert sorted(k for k, _ in calls) == ['panels', 'unlabeled']
    assert all(c == pytest.approx(0.03) for _, c in calls)        # треть потолка задания на вопрос
    assert v['usd'] == pytest.approx(0.02) and v['cached'] == ['labels2']
    calls.clear()
    v2 = pl.ensure_vlm(tmp_path / 'x.png', tmp_path, ask=fake_ask(calls))
    assert calls == [] and v2['usd'] == 0                      # повтор того же листа — 0 $


def test_vlm_errors_map_to_codes(tmp_path):
    def cap(*a, **kw):
        raise SystemExit('потолок $0.03 исчерпан')

    def net(*a, **kw):
        raise TimeoutError('gateway timeout')
    with pytest.raises(pl.TrialError) as e:
        pl.ensure_vlm(tmp_path / 'x.png', tmp_path / 'a', ask=cap)
    assert e.value.code == 'budget' and not e.value.retryable
    with pytest.raises(pl.TrialError) as e:
        pl.ensure_vlm(tmp_path / 'x.png', tmp_path / 'b', ask=net)
    assert e.value.code == 'vlm_error' and e.value.retryable


def test_cache_only_without_full_cache_is_source_gone_and_asks_nothing(tmp_path):
    """Р2-текст (T-20261109-33): план заново с текстом агента — только из кэша чтения плана, 0 $. Нет хоть одного ответа —
    `source_gone` («загрузите план заново»), платного вопроса нет."""
    (tmp_path / 'raw-T-labels2.txt').write_text('{"rooms": []}')               # кэш неполный: panels/unlabeled нет
    calls = []
    src = {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 10, 'imageH': 10}
    with pytest.raises(pl.TrialError) as e:
        pl.run(tmp_path / 'x.png', 'Гостиная 4 на 3', tmp_path / 'w', source=src, vlm_dir=tmp_path, ask=fake_ask(calls),
               cache_only=True)
    assert e.value.code == 'source_gone' and not e.value.retryable and calls == []
    rc = pl.main(['job', '--input', str(tmp_path / 'none.png'), '--mime', 'image/png', '--workdir', str(tmp_path / 'j'),
                  '--vlm-root', str(tmp_path / 'v'), '--cache-only', '--cap-usd', '0'])
    assert rc == 3 and json.loads((tmp_path / 'j' / 'error.json').read_text())['code'] in ('source_gone', 'unsupported')


def test_prepare_images(tmp_path, monkeypatch):
    from PIL import Image
    p = tmp_path / 'a.png'
    Image.new('RGBA', (3000, 1000), (0, 0, 0, 0)).save(p)
    sheet, src, fl = pl.prepare(p, 'image/png', tmp_path / 'w1')
    im = Image.open(sheet)
    assert im.mode == 'RGB' and max(im.size) == pl.MAX_SIDE and im.getpixel((5, 5)) == (255, 255, 255)
    assert src == {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 2000, 'imageH': 667} and fl == []
    j = tmp_path / 'b.jpg'
    Image.new('RGB', (800, 600), (200, 200, 200)).save(j)
    assert pl.prepare(j, 'image/jpeg', tmp_path / 'w2')[1]['mime'] == 'image/jpeg'
    bad = tmp_path / 'bad.png'
    bad.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 100)
    with pytest.raises(pl.TrialError) as e:
        pl.prepare(bad, 'image/png', tmp_path / 'w3')
    assert e.value.code == 'unsupported'
    monkeypatch.setattr(pl, 'MAX_PIXELS', 800 * 600 - 1)            # картинка-бомба: отказ по заголовку
    with pytest.raises(pl.TrialError) as e:
        pl.prepare(j, 'image/jpeg', tmp_path / 'w4')
    assert e.value.code == 'too_large'


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='нет poppler')
def test_prepare_pdf(tmp_path):
    from PIL import Image
    pages = [Image.new('RGB', (600, 800), (255, 255, 255)) for _ in range(3)]
    one, three = tmp_path / 'one.pdf', tmp_path / 'three.pdf'
    pages[0].save(one, 'PDF', resolution=72)
    pages[0].save(three, 'PDF', resolution=72, save_all=True, append_images=pages[1:])
    _, src, fl = pl.prepare(one, 'application/pdf', tmp_path / 'p1')
    assert (src['pages'], src['usedPages'], src['mime']) == (1, 1, 'application/pdf') and fl == []
    assert abs(src['imageW'] - 1250) <= 1 and abs(src['imageH'] - 1667) <= 1   # 600×800 pt при 150 dpi
    _, src, fl = pl.prepare(three, 'application/pdf', tmp_path / 'p3')
    assert (src['pages'], src['usedPages']) == (3, 2) and fl == ['pages_skipped']
    assert src['imageW'] == pl.MAX_SIDE                                  # два листа рядом → ужато до 2000
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(b'%PDF-1.4\n garbage')
    with pytest.raises(pl.TrialError) as e:
        pl.prepare(broken, 'application/pdf', tmp_path / 'pb')
    assert e.value.code == 'pdf_unreadable'


@pytest.mark.parametrize('name, kind', [
    ('Kitchen/Dining Room', 'kitchen'), ('Lounge', 'living'), ('Bedroom One', 'bedroom'), ('Bed 2', 'bedroom'),
    ('En-Suite', 'bathroom'), ('WC', 'bathroom'), ('Shower Room', 'bathroom'), ('Landing', 'hall'), ('Hall', 'hall'),
    ('Family/Breakfast room', 'kitchen'), ('Utility', 'other'), ('Garage', 'other'), ('', 'other'), ('Study', 'other'),
])
def test_room_kind(name, kind):
    assert pl.room_kind(name) == kind


def synth(n_panels=1, rooms_per=2):
    """Журнал run_plan + модели панелей (метры) без стенда — для сборки результата."""
    log = {'sweep': [{'est': 50.0}], 'panels': []}
    models = []
    G = {'rooms': [{'name': 'Lounge', 'name0': 'Lounge', 'dims_m': [4.0, 3.0], 'dims_src': 'plan'},
                   {'name': 'Bedroom #2', 'name0': 'Bedroom', 'dims_m': [3.0, 3.0], 'dims_src': 'text', 'unsure': True}]}
    for pi in range(n_panels):
        bb = [pi * 100, 0, pi * 100 + 90, 90]
        log['panels'].append({'panel': f'Floor {pi}', 'vlm_title': None, 'bbox_px': bb, 'fit': {'n': 2},
                              'inliers': [('Lounge', 'p95', 0), ('Bedroom #2', 'p95', 0)],
                              'dims': [{'id': 'Bedroom #2', 'flag_level': 2, 'status': 'loo'}],
                              'label_report': [{'name': 'WC', 'room': 9, 'space': True}]})
        floors, rooms = [], []
        for k in range(rooms_per):
            x = 5.0 * k
            floors.append({'outer': [[x, 0], [x + 4, 0], [x + 4, 3], [x, 3]], 'holes': [], 'room': k + 1})
            rooms.append({'id': k + 1, 'names': [['Lounge'], ['Bedroom #2']][k % 2], 'area_m2': 12.0 - k})
        floors.append({'outer': [[0, 4], [1, 4], [1, 5], [0, 5]], 'holes': [], 'room': 9})
        rooms.append({'id': 9, 'names': [], 'area_m2': 1.0})
        models.append({'bbox_px': bb, 'rooms': rooms, 'floors': floors,
                       'bands': [{'z0': 0.0, 'z1': 2.6, 'polys': [{'outer': [[0, 0], [9, 0], [9, 0.1], [0, 0.1]], 'holes': []}]}],
                       'openings': [{'kind': 'door', 'c': [1.0, 0.05], 'width_m': 0.8, 'exterior': False},
                                    {'kind': 'gap', 'c': [2.0, 0.05], 'width_m': 1.0, 'exterior': True}]})
    return log, models, G


def write_models(d, models):
    d.mkdir(parents=True, exist_ok=True)
    for i, m in enumerate(models):
        (d / f'model-T-{i}.json').write_text(json.dumps(m))


SRC = {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 100, 'imageH': 100}


def test_to_result_fields_and_flags(tmp_path):
    log, models, G = synth()
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0.012, {'labels': 1.0}, [], False)
    assert_contract(res)
    assert res['scale'] == {'status': 'listing', 'ppm': 50.0, 'inliers': 2, 'n': 2}   # 1 подпись с листа + 1 из текста
    rooms = {r['name']: r for r in res['panels'][0]['rooms']}
    lounge, bed, wc = rooms['Lounge'], rooms['Bedroom'], rooms['WC']
    assert lounge['id'] == 'p0-r1' and lounge['contour'][1] == [400.0, 0.0] and lounge['bbox'] == {'x': 0.0, 'y': 0.0, 'w': 400.0, 'd': 300.0}
    assert lounge['dims'] == {'w': 400.0, 'd': 300.0, 'src': 'plan'} and lounge['kind'] == 'living'
    assert bed['dims']['src'] == 'listing' and {'dims_mismatch', 'label_unclear'} <= set(bed['flags'])
    assert wc['kind'] == 'bathroom' and 'dims_estimated' in wc['flags'] and 'unlabeled' not in wc['flags']
    ops = res['panels'][0]['openings']
    assert ops[0] == {'kind': 'door', 'c': [100.0, 5.0], 'widthCm': 80.0, 'exterior': False} and ops[1]['kind'] == 'opening'
    assert res['panels'][0]['walls'][0]['z1'] == 260.0
    assert not any('fragment_merged' in r['flags'] for r in res['panels'][0]['rooms'])


def test_fragment_merged_flag(tmp_path):
    # T-19: в комнату влит обрывок за нашим закрытием (`repair.absorb_fragments`) — честный флаг у неё, у прочих нет
    log, models, G = synth()
    log['panels'][0]['absorbed'] = [{'into': 1, 'piece': 7, 'm2': 0.5}]
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False)
    assert_contract(res)
    fl = {r['name']: r['flags'] for r in res['panels'][0]['rooms']}
    assert 'fragment_merged' in fl['Lounge'] and 'fragment_merged' not in fl['Bedroom']


def test_to_result_scale_status_rules(tmp_path):
    log, models, G = synth()
    write_models(tmp_path, models)
    assert pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False)['scale']['status'] == 'listing'   # 1 с листа + 1 из текста
    G['rooms'][1]['dims_src'] = 'both'
    assert pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False)['scale']['status'] == 'verified'
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True)                                    # масштаб по толщине стены
    assert res['scale']['status'] == 'not_verified' and res['scale']['ppm'] is None
    assert all('scale_unverified' in r['flags'] for r in res['panels'][0]['rooms'])


def area_synth(gia_m2=30.0, ppm=50.0, extra_rooms=()):
    """Прогон «по толщине стены» (ppm угадан = 50 px/м, стена 10 px = 0,2 м) с GIA панели `gia_m2` при этом ppm."""
    log, models, G = synth()
    log['thickness_px'] = 10.0
    log['panels'][0].update(ppm=ppm, gia_m2=gia_m2, inliers=[], fit={'n': 0})
    for i, (name, a) in enumerate(extra_rooms):
        rid = 20 + i
        x = 20.0 + 3 * i
        models[0]['floors'].append({'outer': [[x, 0], [x + 2, 0], [x + 2, 2], [x, 2]], 'holes': [], 'room': rid})
        models[0]['rooms'].append({'id': rid, 'names': [name], 'area_m2': a})
    return log, models, G


def area(m2, conv='gia', src='text', excl=()):
    return {'m2': m2, 'src': src, 'approx': True, 'excl': list(excl), 'conv': conv, 'raw': '', 'flags': []}


def test_area_scale_when_only_wall_thickness(tmp_path):
    """Без подписей: GIA 30 м² при угаданных 50 px/м = 75 000 px²; общая 120 м² → 25 px/м, метры × 2, статус `area`."""
    log, models, G = area_synth()
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(120.0))
    assert_contract(res)
    assert res['scale'] == {'status': 'area', 'ppm': 25.0, 'inliers': 0, 'n': 0, 'areaM2': 120.0, 'areaSrc': 'text'}
    assert 'scale_from_area' in res['flags'] and 'scale_from_wall_thickness' not in res['flags']
    lounge = next(r for r in res['panels'][0]['rooms'] if r['name'] == 'Lounge')
    assert lounge['contour'][1] == [800.0, 0.0] and lounge['areaM2'] == 48.0      # 4 м → 8 м, 12 м² → 48 м²
    assert 'scale_unverified' not in lounge['flags']
    op = res['panels'][0]['openings'][0]
    assert op['c'] == [200.0, 10.0] and op['widthCm'] == 160.0
    assert res['panels'][0]['walls'][0]['polys'][0]['outer'][1] == [1800.0, 0.0] and res['panels'][0]['walls'][0]['z1'] == 260.0


def test_area_excludes_balcony_and_named_exclusions(tmp_path):
    """Балкон в GIA не входит (вычитается всегда), гараж — только когда подпись его исключает."""
    log, models, G = area_synth(gia_m2=36.0, extra_rooms=[('Balcony', 6.0)])
    write_models(tmp_path, models)
    assert pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(120.0))['scale']['ppm'] == 25.0
    log, models, G = area_synth(gia_m2=40.0, extra_rooms=[('Garage', 10.0)])
    write_models(tmp_path / 'g', models)
    assert pl.to_result(log, tmp_path / 'g', 'T', G, SRC, 0, {}, [], True, area(120.0, excl=['garage']))['scale']['ppm'] == 25.0
    with_garage = pl.to_result(log, tmp_path / 'g', 'T', G, SRC, 0, {}, [], True, area(160.0))['scale']['ppm']
    assert with_garage == 25.0                                                      # 40 × 2500 / 160


def test_area_russian_total_counts_rooms_without_walls(tmp_path):
    """«Общая площадь» (РФ) — сумма помещений без стен: комнаты 12 + 11 + 1 = 24 м² при 50 px/м → 60 000 px²; 96 м² → 25 px/м."""
    log, models, G = area_synth(gia_m2=99.0)
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(96.0, conv='rooms'))
    assert res['scale']['status'] == 'area' and res['scale']['ppm'] == 25.0


def test_area_conflicts_with_labels_is_flagged_not_used(tmp_path):
    """Подписи есть (listing) — масштаб от них; общая площадь в 4 раза больше найденной → флаг, статус и метры прежние."""
    log, models, G = area_synth()
    log['panels'][0]['inliers'] = [('Lounge', 'p95', 0), ('Bedroom #2', 'p95', 0)]
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False, area(120.0))
    assert_contract(res)
    assert res['scale']['status'] == 'listing' and res['scale']['ppm'] == 50.0 and res['scale']['areaM2'] == 120.0
    assert 'scale_area_conflict' in res['flags']
    assert next(r for r in res['panels'][0]['rooms'] if r['name'] == 'Lounge')['contour'][1] == [400.0, 0.0]
    ok = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False, area(31.0))     # совпала (±10 %) — без флага
    assert 'scale_area_conflict' not in ok['flags']


def test_area_unusable_stays_not_verified(tmp_path):
    """Площадь даёт стену 2 м (общая — не про этот лист) или не все листы PDF прочитаны → прежний not_verified с флагом."""
    log, models, G = area_synth()
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(3000.0))
    assert res['scale']['status'] == 'not_verified' and res['scale']['ppm'] is None
    assert 'area_unusable:wall_thickness' in res['flags'] and 'scale_from_wall_thickness' in res['flags']
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, ['pages_skipped'], True, area(120.0))
    assert res['scale']['status'] == 'not_verified' and 'area_pages_skipped' in res['flags']
    none = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, None)          # площади нет — как раньше
    assert none['scale'] == {'status': 'not_verified', 'ppm': None, 'inliers': 0, 'n': 0}


def _labels(log, found, lost):
    """Подписи VLM панели: `found` с найденной комнатой, имена `lost` — без комнаты (здание найдено не всё)."""
    log['panels'][0]['label_report'] = ([{'name': f'Room {i}', 'room': 1, 'space': True} for i in range(found)]
                                        + [{'name': n, 'room': None, 'space': True} for n in lost])


def test_area_needs_whole_building_found(tmp_path):
    """Подписей без комнаты > 10 % — часть здания мимо знаменателя, масштаб по площади раздул бы все метры:
    площадь не берём (`area_unusable:coverage`), прежний not_verified. Балкон без комнаты не в счёт (в площадь не входит);
    ровно 10 % — ещё можно. У плана с подписями (здесь listing) та же нехватка — только флаг, масштаб прежний."""
    log, models, G = area_synth()
    write_models(tmp_path, models)
    _labels(log, 9, ['Hay Barn', 'Cattle Yard'])                                   # 2 из 11 — 18 %
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(120.0))
    assert res['scale']['status'] == 'not_verified' and res['scale']['ppm'] is None
    assert 'area_unusable:coverage' in res['flags'] and 'scale_from_wall_thickness' in res['flags']
    _labels(log, 9, ['Balcony', 'Store'])                                          # 1 из 10 (балкон не в счёт)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], True, area(120.0))
    assert res['scale']['status'] == 'area' and res['scale']['ppm'] == 25.0
    log, models, G = synth()
    log['thickness_px'], log['panels'][0]['gia_m2'] = 10.0, 30.0
    _labels(log, 1, ['Hay Barn'])
    write_models(tmp_path / 'v', models)
    was = pl.to_result(log, tmp_path / 'v', 'T', G, SRC, 0, {}, [], False)['scale']
    res = pl.to_result(log, tmp_path / 'v', 'T', G, SRC, 0, {}, [], False, area(30.0))
    assert res['scale'] == dict(was, areaM2=30.0, areaSrc='text') and 'area_unusable:coverage' in res['flags']


def test_to_result_limits(tmp_path):
    log, models, G = synth(n_panels=6)
    write_models(tmp_path, models)
    res = pl.to_result(log, tmp_path, 'T', G, SRC, 0, {}, [], False)
    assert_contract(res)
    assert len(res['panels']) == pl.MAX_PANELS and 'panels_truncated' in res['flags']
    ring = [[math.cos(t / 1000) * 3, math.sin(t / 1000) * 3] for t in range(9000)]
    assert len(pl._ring(ring)) <= pl.MAX_RING
    assert pl._ring([[0, 0], [0, 0], [1, 1]]) is None
    empty = {'sweep': [], 'panels': [dict(log['panels'][0])]}
    write_models(tmp_path / 'e', [dict(models[0], rooms=[], floors=[])])
    with pytest.raises(pl.TrialError) as e:
        pl.to_result(empty, tmp_path / 'e', 'T', G, SRC, 0, {}, [], False)
    assert e.value.code == 'no_plan'


def test_guess_scale_shim():
    import fpcore
    g = pl._GuessScale(fpcore, 25.0)
    f = g.fit_scale([])
    assert f['s'] == pytest.approx(0.04) and f['inliers'] == []
    assert g.convention(f) == ('p95', 0, 0.0)
    assert g.stroke_thickness is fpcore.stroke_thickness


def test_slot_timeout_returns_waiting_capacity(monkeypatch):
    import contextlib
    import heavy_slot as hs

    @contextlib.contextmanager
    def busy(*a, **kw):
        raise hs.SlotTimeout('trial-floorplan')
        yield
    monkeypatch.setattr(pl, '_slot', busy)
    with pytest.raises(pl.TrialError) as e:
        pl.walls('T', Path('/nonexistent.png'), Path('/nonexistent'), {'rooms': []}, {}, lambda s: None, True, 'x')
    assert e.value.code == 'waiting_capacity' and e.value.retryable


def test_job_main_writes_error_json(tmp_path):
    bad = tmp_path / 'in.png'
    bad.write_bytes(b'not an image')
    rc = pl.main(['job', '--input', str(bad), '--mime', 'image/png', '--workdir', str(tmp_path / 'w'),
                  '--vlm-root', str(tmp_path / 'v')])
    assert rc == 3
    e = json.loads((tmp_path / 'w' / 'error.json').read_text())
    assert e['code'] == 'unsupported' and e['retryable'] is False
    assert (tmp_path / 'w' / 'stage').read_text() == 'raster'
