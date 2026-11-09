"""Проба агента: обёртка «гостиная по загруженному плану» (план agent-trial-03-living, L-B; T-20261109-12).

  1) папка пробы — строго `TRIAL_SCENES_ROOT/<id>`; живая папка демо и папка скриптов — отказ;
  2) путь flat215 прежний: входы солвера `flat215_demo.solve_layouts` (команда, cwd, env) — байт в байт снимок
     `fixtures/trial-flat215-solver-inputs.json` (снят на коде main 7e972eca: эта ветка flat215_demo.py не меняет), а
     `solver_run.py` без `LAYOUT_OUT_DIR` пишет туда же, где раньше (HERE);
  3) проба не пишет в живые пути: ни `~/scout-scenes/flat215-demo`, ни `tools/scout/v3set*` (с поддельным и с НАСТОЯЩИМ солвером);
  4) геометрии по форме дивана, набор-геометрия из самых крупных реальных товаров, подстановка: спинка у стены остаётся у
     стены, столик держит зазор от фронта дивана, стулья — зазор до стола, диван — к оси ТВ внутри следа геометрии;
  5) геометрию не расставить — стили этой формы считаются своими наборами; не вышло и так — стиль с причиной, не пустой «ок».
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_trial_demo.py -q"""
import glob
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SCOUT)
import trial_demo as TD  # noqa: E402
import trial_room as TR  # noqa: E402
from planner.geometry import footprint  # noqa: E402
from planner.models import Item, Placement  # noqa: E402

GOLDEN = os.path.join(HERE, 'fixtures', 'trial-flat215-solver-inputs.json')
LIVE_DEMO = os.path.expanduser('~/scout-scenes/flat215-demo')


def _tree_state(root: str) -> dict:
    out = {}
    if not os.path.isdir(root):
        return out
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
                out[p] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return out


def _live_state() -> dict:
    st = _tree_state(LIVE_DEMO)
    for p in glob.glob(os.path.join(SCOUT, 'v3set*')):
        s = os.stat(p)
        st[p] = (s.st_size, s.st_mtime_ns)
    return st


# ───────────────────────── 1) папка пробы ─────────────────────────

def test_out_dir_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    assert TD.out_dir('E-0_run.1') == os.path.join(os.path.realpath(tmp_path), 'E-0_run.1')
    for bad in ('../x', 'a/b', '', '.hidden', 'x' * 80):
        with pytest.raises(TD.TrialPathError):
            TD.out_dir(bad)
    monkeypatch.setattr(TD, 'TRIAL_ROOT', os.path.expanduser('~/scout-scenes'))
    with pytest.raises(TD.TrialPathError):
        TD.out_dir('flat215-demo')                     # живая папка демо
    monkeypatch.setattr(TD, 'TRIAL_ROOT', os.path.dirname(SCOUT))
    with pytest.raises(TD.TrialPathError):
        TD.out_dir('scout')                            # папка скриптов (`v3set*` рядом с solver_run.py)


def test_band_for():
    assert TD.band_for(16.9) == ('14-16', [])
    assert TD.band_for(34.8) == ('31-40', [])
    assert TD.band_for(12.0) == ('14-16', ['band_below_min'])
    assert TD.band_for(60.0) == ('50+', [])


# ───────────────────────── 2) путь flat215 прежний ─────────────────────────

def _flat215_inputs(monkeypatch, tmp_path) -> list:
    import flat215_demo as FD
    calls = []

    class R:
        returncode = 0
        stderr = ''

    def fake_run(cmd, cwd=None, env=None, **kw):
        keys = ('SETS_SNAPSHOT', 'SCENE_OPENINGS', 'SCENE_RADIATORS', 'LAYOUT_SUFFIX', 'LAYOUT_SIGNATURE_FILE',
                'LAYOUT_OUT_DIR', 'SCENE_CONTOUR')
        e = {k: (env[k].replace(FD.HERE, '<HERE>') if k in env else None) for k in keys}
        calls.append({'cmd': [c.replace(FD.HERE, '<HERE>') for c in cmd[1:]], 'cwd': cwd.replace(FD.HERE, '<HERE>'),
                      'env': e})
        return R()
    monkeypatch.setattr(FD.subprocess, 'run', fake_run)
    monkeypatch.setattr(FD, 'layout_path', lambda n: str(tmp_path / f'nope-{n}.json'))   # «не свежая» — солвер зовётся
    for k in ('SCENE_CONTOUR', 'LAYOUT_OUT_DIR'):
        monkeypatch.delenv(k, raising=False)
    flat = json.load(open(os.path.join(SCOUT, 'flat215.json'), encoding='utf-8'))
    FD.solve_layouts(flat, only=[3, 41])
    return calls


def test_flat215_solver_inputs_unchanged(monkeypatch, tmp_path):
    got = _flat215_inputs(monkeypatch, tmp_path)
    if os.environ.get('TRIAL_WRITE_GOLDEN') == '1':
        json.dump(got, open(GOLDEN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    want = json.load(open(GOLDEN, encoding='utf-8'))
    assert json.dumps(got, ensure_ascii=False, sort_keys=True) == json.dumps(want, ensure_ascii=False, sort_keys=True)
    assert all(c['env']['LAYOUT_OUT_DIR'] is None for c in got)


def test_solver_run_default_output_is_here():
    src = open(os.path.join(SCOUT, 'solver_run.py'), encoding='utf-8').read()
    assert "_OUTD=os.environ.get('LAYOUT_OUT_DIR') or HERE" in src
    assert "os.path.join(HERE,f'{TAG}{n}-layout" not in src            # все выходы раскладки — через _OUTD
    assert src.count("os.path.join(_OUTD,f'{TAG}{n}-layout{_sfx}") == 2


# ───────────────────────── 4) геометрии и подстановка ─────────────────────────

def it(mid, w, d, name='', **kw):
    return dict({'mid': mid, 'eid': str(mid), 'name': name or f'товар {mid}', 'w': w, 'd': d, 'h': 80}, **kw)


def style(name, sofa, bearer=('тв-тумба', 150, 40), extra=None, band='17-20'):
    items = {'диван': sofa, bearer[0]: it(900 + bearer[1], bearer[1], bearer[2])}
    items.update(extra or {})
    return {'band': band, 'style': name, 'items': items, 'set_id': f'set-{name}'}


def test_shape_groups_and_conservative_geometry():
    sts = [style('сканди', it(1, 200, 95, 'Диван прямой', h=75), extra={'столик': it(11, 100, 60), 'комод': it(21, 90, 40)}),
           style('лофт', it(2, 230, 100, 'Диван прямой', h=95), ('стенка', 220, 45), extra={'столик': it(12, 110, 55)}),
           style('минимализм', it(3, 180, 90, 'Диван прямой'), extra={'столик': it(13, 80, 50)}),
           style('джапанди', it(4, 260, 170, 'Диван угловой'), extra={'столик': it(14, 90, 90)})]
    groups = TD.shape_groups(sts, '17-20')
    assert [g['shape'] for g in groups] == ['straight', 'corner']
    geo = groups[0]['set']['items']
    assert geo['диван']['w'] == 230                               # самый крупный реальный товар роли
    assert geo['тв-тумба']['w'] == 220 and geo['тв-тумба']['_bearer_from'] == 'стенка'   # стенка = носитель ТВ
    assert geo['столик']['mid'] == 12                             # по площади: 110×55 = 6050 > 100×60 = 6000
    assert geo['диван']['h'] == 75 and geo['диван']['_h_from'] == {'h': 95, 'low_style': 'сканди'}  # высота — самого низкого
    assert 'комод' not in geo                                     # роль одного стиля из трёх — не в геометрии
    assert [st['style'] for st, _ in groups[1]['styles']] == ['джапанди']
    assert 'столик' in groups[1]['set']['items']                  # группа из одного стиля — его роли целиком


def _facing(fx, fy):
    from planner.geometry import facing_vector
    return next(r for r in (0, 90, 180, 270) if tuple(round(v) for v in facing_vector(r)) == (fx, fy))


def test_substitute_keeps_wall_gaps_and_followers():
    W, D = 500.0, 400.0
    r_up = _facing(0, 1)                                          # спинкой к стене y=0, лицом вглубь
    r_dn = _facing(0, -1)

    def P(role, x, y, w, d, rot=r_up):
        return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=80))
    geo = [P('диван', 250, 50, 240, 100),                         # спинка у стены y=0
           P('столик', 250, 170, 110, 60),                        # зазор 40 от фронта (y=100 → 140)
           P('тв-тумба', 300, 380, 150, 40, r_dn),                # у стены y=400, ось ТВ правее центра дивана
           P('стол обеденный', 420, 250, 100, 100),
           P('стул', 420, 327.5, 45, 45, r_dn)]                  # стул под столом, зазор 5 (стол до 300 → стул с 305)
    st = {'style': 'сканди', 'items': {'диван': it(1, 180, 80, 'Диван прямой'), 'столик': it(2, 80, 50),
                                       'тв-тумба': it(3, 120, 40), 'стол обеденный': it(4, 80, 80),
                                       'стул': it(5, 45, 45)}}
    ps, absent, rows = TD.substitute(geo, st, W, D)
    by = {p.role: p for p in ps}
    sb, tb = footprint(by['диван']).bounds, footprint(by['столик']).bounds
    assert sb[1] == pytest.approx(0.0)                            # спинка осталась у стены (не «парит»)
    assert tb[1] - sb[3] == pytest.approx(40.0)                   # тот же зазор диван↔столик
    gb = footprint(geo[0]).bounds
    assert gb[0] - 0.01 <= sb[0] and sb[2] <= gb[2] + 0.01        # диван — внутри следа геометрии
    assert by['диван'].x == pytest.approx(280.0)                  # к оси ТВ (300), упор в край следа (370−90)
    assert (tb[0] + tb[2]) / 2 == pytest.approx(by['диван'].x)    # столик — по оси дивана
    vb = footprint(by['тв-тумба']).bounds
    assert vb[3] == pytest.approx(400.0)                          # носитель — у своей стены
    cb, kb = footprint(by['стул']).bounds, footprint(by['стол обеденный']).bounds
    assert cb[1] - kb[3] == pytest.approx(5.0)                    # стул — тот же зазор до стола
    assert absent == [] and {r['role'] for r in rows} == set(by)
    st2 = {'style': 'лофт', 'items': {'диван': it(1, 180, 80, 'Диван прямой'), 'тв-тумба': it(3, 120, 40)}}
    ps2, absent2, _ = TD.substitute(geo, st2, W, D)
    assert absent2 == ['стол обеденный', 'столик', 'стул'] or sorted(absent2) == ['стол обеденный', 'столик', 'стул']


# ───────────────────────── 3) не пишет в живые пути; 5) отказ геометрии ─────────────────────────

RECT = [(0, 0), (500, 0), (500, 400), (0, 400)]


def plan():
    return {'version': 1, 'units': 'cm', 'source': {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
            'scale': {'status': 'listing', 'ppm': 50, 'inliers': 3, 'n': 3},
            'panels': [{'id': 'p0', 'title': '', 'walls': [],
                        'rooms': [{'id': 'r1', 'name': 'Living', 'kind': 'living', 'contour': [list(p) for p in RECT],
                                   'bbox': {'x': 0, 'y': 0, 'w': 500, 'd': 400}, 'areaM2': 20, 'flags': []}],
                        'openings': [{'kind': 'window', 'c': [250, 0], 'widthCm': 150, 'exterior': True},
                                     {'kind': 'door', 'c': [450, 400], 'widthCm': 80, 'exterior': False}]}],
            'flags': [], 'timings': {}, 'costUsd': 0}


def bank():
    return [style('сканди', it(1, 200, 95, 'Диван прямой'), extra={'столик': it(11, 100, 60)}, band='17-20'),
            style('лофт', it(2, 210, 95, 'Диван прямой'), extra={'столик': it(12, 90, 50)}, band='17-20')]


def no_hard(monkeypatch):
    """Подставная расстановка геометрически условна (нормы дистанций не проходит): в тестах логики сборки нормы отключаем."""
    monkeypatch.setattr(TD, "hard_of", lambda room, ps: [])


def fake_solver(fail_geometry=False):
    calls = []

    def run(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=1):
        calls.append({'n': n, 'tag': tag, 'layouts': layouts, 'sets_file': sets_file})
        st = json.load(open(sets_file, encoding='utf-8'))[n - 1]
        ops = TD.TR_strip(TR.solver_openings(cand, cfg, hinge))
        if fail_geometry and st['set_id'].startswith('trial-geometry'):
            art = {'_infeasible_reason': {'code': 'MEDIA_MISSING'}}
        else:
            s, t = st['items']['диван'], st['items']['тв-тумба']
            art = {'диван': {'x': 250, 'z': 400 - s['d'] / 2, 'rot': _facing(0, -1), 'w': s['w'], 'd': s['d']},
                   'тв-тумба': {'x': 250, 'z': 20 + t['d'] / 2 + 60, 'rot': _facing(0, 1), 'w': t['w'], 'd': t['d']}}
        path = os.path.join(layouts, f'v3set{n}-layout-{tag}.json')
        json.dump(art, open(path, 'w', encoding='utf-8'))
        return {'rc': 0, 'seconds': 0.01, 'artifact': path, 'openings': ops, 'stderr': '', 'art': art, 'missing': []}
    run.calls = calls
    return run


def test_build_writes_only_trial_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    no_hard(monkeypatch)
    before = _live_state()
    sv = fake_solver()
    scene = TD.build('t1', plan(), sets=bank(), solver=sv, pick=lambda sets, band: [1, 2] if band == '17-20' else [])
    assert _live_state() == before
    out = os.path.join(os.path.realpath(tmp_path), 't1')
    assert scene['out'] == out and all(c['layouts'] == os.path.join(out, 'layouts') for c in sv.calls)
    files = sorted(os.path.relpath(p, out) for p in _tree_state(out))
    assert {'scene.json', 'trial-sets.json', 'adapter.json'} <= set(files)
    s = json.load(open(os.path.join(out, 'scene.json'), encoding='utf-8'))
    assert s['band'] == '17-20' and [v['style'] for v in s['variants']] == ['сканди', 'лофт']
    assert all(v['items'] for v in s['variants']) and s['openings_core']
    assert {'adapter_s', 'solver_s', 'assembly_s', 'total_s'} <= set(s['timings'])


def _assert_openings_contract(s: dict) -> None:
    """Контракт со стадией героя (`trial_hero.py`, докстрока и `payload_from_trial`): у сцены ok/partial `openings_core` —
    всегда список проёмов ядра в полях `planner.models.Opening`, без служебных `_…`; иначе кадр — отказ `trial_no_openings`."""
    assert isinstance(s['openings_core'], list) and s['openings_core']
    for o in s['openings_core']:
        assert o['kind'] in ('window', 'door', 'balcony', 'opening') and o['wall'] in TR.WALLS
        assert o['offset_cm'] >= 0 and o['width_cm'] > 0
        assert not any(str(k).startswith('_') for k in o)


def test_scene_always_has_openings_core_for_hero(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    s = TD.build('h1', plan(), sets=bank(), solver=fake_solver(), pick=lambda sets, band: [1, 2] if band == '17-20' else [])
    assert s['status'] in ('ok', 'partial')
    _assert_openings_contract(json.load(open(os.path.join(s['out'], 'scene.json'), encoding='utf-8')))


def test_openings_core_present_when_first_geometry_failed(tmp_path, monkeypatch):
    """Первая геометрия не расставлена, вторая — да: сцена `partial`, а проёмы ядра на месте (они не зависят от мебели)."""
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    good = fake_solver()

    def half(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=1):
        if n == 1 or json.load(open(sets_file, encoding='utf-8'))[n - 1].get('style') == 'сканди':
            path = os.path.join(layouts, f'v3set{n}-layout-{tag}.json')
            art = {'_infeasible_reason': {'code': 'MEDIA_MISSING'}}
            json.dump(art, open(path, 'w', encoding='utf-8'))
            return {'rc': 0, 'seconds': 0.0, 'artifact': path, 'openings': [], 'stderr': '', 'art': art, 'missing': []}
        return good(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=n)
    s = TD.build('h2', plan(), sets=bank(), solver=half, pick=lambda sets, band: [1, 2] if band == '17-20' else [])
    assert s['status'] == 'partial'
    _assert_openings_contract(s)


def test_run_solver_env_points_into_trial_dir(tmp_path, monkeypatch):
    seen = {}

    class P:
        returncode = 1

        def __init__(self, cmd, cwd=None, env=None, **kw):
            seen.update(cmd=cmd, cwd=cwd, env=env)

        def communicate(self, timeout=None):
            return '', 'x'
    monkeypatch.setattr(TD.subprocess, 'Popen', P)
    monkeypatch.setenv('SCENE_CONTOUR', '[[0,0]]')
    ad = TR.adapt(plan())
    TD.run_solver(ad['candidates'][0], TR.rules(), str(tmp_path / 'trial-sets.json'), str(tmp_path / 'layouts'),
                  'left', 'trial-x', 10, n=2)
    assert seen['env']['LAYOUT_OUT_DIR'] == str(tmp_path / 'layouts')
    assert seen['env']['SETS_SNAPSHOT'] == str(tmp_path / 'trial-sets.json')
    assert 'SCENE_CONTOUR' not in seen['env'] and seen['env']['SCENE_RADIATORS'] == '[]'
    assert seen['cmd'][1:5] == ['solver_run.py', '2', '--v3', '500'] and seen['cwd'] == TD.HERE
    assert all(not k.startswith('_') for o in json.loads(seen['env']['SCENE_OPENINGS']) for k in o)


def test_geometry_failure_falls_back_to_own_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    no_hard(monkeypatch)
    sv = fake_solver(fail_geometry=True)
    s = TD.build('t2', plan(), sets=bank(), solver=sv, pick=lambda sets, band: [1, 2] if band == '17-20' else [])
    assert 'own_layouts' in s['flags']
    assert [g['kind'] for g in s['geometries']] == ['own', 'own']
    assert all(v['items'] for v in s['variants'])
    assert {c['n'] for c in sv.calls} >= {1, 2, 3}                 # геометрия (1), затем свои наборы (2, 3)


def test_failed_layout_is_reported_not_empty_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))

    def never(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=1):
        path = os.path.join(layouts, f'v3set{n}-layout-{tag}.json')
        json.dump({'_infeasible_reason': {'code': 'MEDIA_MISSING'}}, open(path, 'w'))
        return {'rc': 0, 'seconds': 0.0, 'artifact': path, 'openings': [], 'stderr': '',
                'art': {'_infeasible_reason': {'code': 'MEDIA_MISSING'}}, 'missing': []}
    s = TD.build('t3', plan(), sets=bank(), solver=never, pick=lambda sets, band: [1, 2] if band == '17-20' else [])
    assert s['status'] == 'failed' and s['problems'][0]['code'] == 'solver_failed'


def test_refusal_written_as_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    p = plan()
    p['scale']['status'] = 'not_verified'
    s = TD.build('t4', p, sets=bank(), solver=fake_solver(), pick=lambda sets, band: [1, 2])
    assert s['status'] == 'refused' and s['refusal']['code'] == 'scale_unverified'
    assert os.path.exists(os.path.join(s['out'], 'scene.json'))


# ───────────────────────── 6) исход по комнате и очередь машины ─────────────────────────

def _pick12(sets, band):
    return [1, 2] if band == '17-20' else []


def test_own_set_trimmed_to_geometry_roles():
    geo = {'items': {'диван': {}, 'тв-тумба': {}, 'столик': {}}}
    st = {'style': 'лофт', 'items': {'диван': it(1, 200, 95), 'стенка': it(2, 220, 45), 'столик': it(3, 90, 50),
                                     'кресло': it(4, 80, 80), 'кресло 3': it(5, 80, 80), 'стол обеденный': it(6, 120, 80)}}
    got = TD.trim_to_geometry(st, geo)
    assert sorted(got['items']) == ['диван', 'стенка', 'столик']   # носитель ТВ стиля сохранён, лишние роли сняты
    assert len(st['items']) == 6                                   # исходный набор не тронут (из него берутся товары)


def test_beam_off_only_for_large_core():
    assert TD.beam_off({'w': 690, 'd': 505}) is True
    assert TD.beam_off({'w': 445, 'd': 380}) is False


def test_outcome_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    no_hard(monkeypatch)
    s = TD.build('o1', plan(), sets=bank(), solver=fake_solver(), pick=_pick12)
    disk = json.load(open(os.path.join(s['out'], 'scene.json'), encoding='utf-8'))
    assert disk['outcome']['state'] == 'ready' and disk['outcome']['code'] is None
    assert disk['outcome']['styles_ok'] == disk['outcome']['styles_total'] == 2


def test_outcome_refused_scale_not_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    p = plan()
    p['scale']['status'] = 'not_verified'
    s = TD.build('o2', p, sets=bank(), solver=fake_solver(), pick=_pick12)
    assert s['outcome']['state'] == 'refused' and s['outcome']['code'] == 'scale_unverified' and s['outcome']['detail']


def test_outcome_refused_solver_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))

    def never(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=1):
        path = os.path.join(layouts, f'v3set{n}-layout-{tag}.json')
        art = {'_infeasible_reason': {'code': 'MEDIA_MISSING'}}
        json.dump(art, open(path, 'w', encoding='utf-8'))
        return {'rc': 0, 'seconds': 0.0, 'artifact': path, 'openings': [], 'stderr': '', 'art': art, 'missing': []}
    s = TD.build('o3', plan(), sets=bank(), solver=never, pick=_pick12)
    assert s['outcome']['state'] == 'refused' and s['outcome']['code'] == 'solver_failed' and s['outcome']['detail']


def test_outcome_partial_names_lost_styles():
    scene = {'status': 'partial', 'problems': [{'code': 'layout_failed'}],
             'variants': [{'style': 'сканди', 'post_ok': True, 'hard': [], 'problems': []},
                          {'style': 'лофт', 'post_ok': False, 'hard': [], 'problems': [{'code': 'layout_failed'}]}]}
    o = TD.outcome_of(scene)
    assert o['state'] == 'partial' and o['code'] == 'styles_missing' and 'лофт' in o['detail'] and 'layout_failed' in o['detail']
    assert (o['styles_ok'], o['styles_total']) == (1, 2)


def test_solver_stage_runs_under_machine_slot(tmp_path, monkeypatch):
    """Настоящий решатель идёт через общую очередь; прогоны — внутри слота; ожидание очереди не считается бюджетом."""
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    events = []
    sv = fake_solver()

    def spy(*a, **kw):
        events.append('solve')
        return sv(*a, **kw)

    class Slot:
        def __init__(self, label):
            events.append(('slot', label))

        def __enter__(self):
            events.append('enter')
            return {'waited_s': 500.0}

        def __exit__(self, *a):
            events.append('exit')
            return False
    s = TD.build('q1', plan(), sets=bank(), solver=spy, pick=_pick12, slot=Slot)
    assert events[0] == ('slot', 'trial-living-q1') and events[1] == 'enter' and events[-1] == 'exit' and 'solve' in events
    assert events.index('exit') > max(i for i, e in enumerate(events) if e == 'solve')
    assert s['timings']['queue_s'] == 500.0 and s['timings']['total_s'] < 400       # очередь не съела бюджет
    assert 'over_budget' not in s['flags']


def test_real_runner_selects_machine_slot():
    src = open(TD.__file__, encoding='utf-8').read()
    assert '(slot or (machine_slot if solver is run_solver else _no_slot))' in src


def test_queue_timeout_is_honest_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))

    class SlotTimeout(Exception):
        pass

    class Slot:
        def __init__(self, label):
            pass

        def __enter__(self):
            raise SlotTimeout('очередь')

        def __exit__(self, *a):
            return False
    s = TD.build('q2', plan(), sets=bank(), solver=fake_solver(), pick=_pick12, slot=Slot)
    assert s['status'] == 'failed' and s['outcome']['state'] == 'refused' and s['outcome']['code'] == 'queue_timeout'


def test_style_with_hard_after_substitution_gets_own_layout_or_is_hidden(tmp_path, monkeypatch):
    """Товар стиля на месте геометрии нарушает правила: пробуем своим набором; не вышло — стиль скрыт с причиной, не показан."""
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    calls = []
    sv = fake_solver()

    def solver(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=1):
        calls.append(n)
        return sv(cand, cfg, sets_file, layouts, hinge, tag, timeout, n=n)
    real_hard = lambda room, ps: []                               # нормы подставной расстановки не проверяем
    # нарушение только у товара «лофт» (ширина 210) — и на месте геометрии, и в своей расстановке
    monkeypatch.setattr(TD, 'hard_of', lambda room, ps: ['WINDOW_BLOCKED|диван'] if any(p.role == 'диван' and p.item.w_cm == 210 and p.item.name for p in ps) else real_hard(room, ps))
    s = TD.build('h3', plan(), sets=bank(), solver=solver, pick=_pick12)
    by = {v['style']: v for v in s['variants']}
    assert max(calls) == 3                                         # геометрия + свой набор «лофта» (номер 3 в снимке)
    assert by['лофт'].get('failed') and by['лофт']['placements_core'] == [] and by['лофт']['hard'] == []
    assert by['лофт']['problems'][0]['code'] == 'style_rejected' and 'WINDOW_BLOCKED' in by['лофт']['problems'][0]['why']
    assert by['сканди']['post_ok'] and by['сканди']['items']
    assert s['outcome']['state'] == 'partial' and s['outcome']['styles_ok'] == 1


def test_chair_at_window_is_dropped_but_last_chair_is_kept(monkeypatch):
    """Лишний стул у окна убираем, диван у окна не трогаем (его снимет общая проверка), последний стул оставляем."""
    class P:
        def __init__(self, role):
            self.role = role
    ps = [P('диван'), P('стул'), P('стул 2')]
    monkeypatch.setattr(TD, 'hard_of', lambda room, x: ['WINDOW_BLOCKED|стул 2', 'WINDOW_BLOCKED|диван'])
    kept, gone = TD.drop_window_chairs(None, ps)
    assert gone == ['стул 2'] and [p.role for p in kept] == ['диван', 'стул']
    monkeypatch.setattr(TD, 'hard_of', lambda room, x: ['WINDOW_BLOCKED|стул', 'WINDOW_BLOCKED|стул 2'])
    kept, gone = TD.drop_window_chairs(None, ps)
    assert gone == [] and len(kept) == 3
    monkeypatch.setattr(TD, 'hard_of', lambda room, x: [])
    assert TD.drop_window_chairs(None, ps) == (ps, [])


@pytest.mark.skipif(os.environ.get('TRIAL_SLOW') == '0', reason='TRIAL_SLOW=0 — без настоящего солвера')
def test_real_solver_writes_only_trial_dir(tmp_path, monkeypatch):
    """Настоящий `solver_run.py` (zoned) на ядре 500×400: раскладки — только в папке пробы."""
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))
    before = _live_state()
    s = TD.build('real', plan(), sets=bank(), pick=lambda sets, band: [1, 2] if band == '17-20' else [],
                 slot=TD._no_slot)                                 # в тесте — без общей очереди машины (маленькая комната, секунды)
    assert _live_state() == before
    assert s['status'] in ('ok', 'partial'), s.get('problems')
    assert any(v['items'] for v in s['variants'])
    lay = os.listdir(os.path.join(s['out'], 'layouts'))
    assert lay and all(f.startswith('v3set') and '-trial-' in f for f in lay)
