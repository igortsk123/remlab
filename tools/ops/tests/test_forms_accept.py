"""T-180/7: кадры приёмки формы — число файлов = товары × виды × света; виды и свет идут из ОДНОЙ таблицы в forms_render.py (в команде Blender нет своих копий)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import forms_render as FR  # noqa: E402


def test_views_one_source_and_roles():
    assert set(FR.VIEWS) <= set(FR.VIEW_DEFS) and set(FR.ACCEPT_VIEWS) <= set(FR.VIEW_DEFS) and set(FR.SEAT_VIEWS) <= set(FR.VIEW_DEFS)
    assert FR.VIEW_DEFS['az180'][0] == 180 and FR.VIEW_DEFS['az090'][0] == 90                          # строго сзади и строго сбоку
    assert 30 <= FR.VIEW_DEFS['top40'][1] <= 45                                                       # косой сверху 30–45°
    assert FR.accept_views('ваза') == FR.ACCEPT_VIEWS and FR.accept_views('') == FR.ACCEPT_VIEWS
    for r in ('диван', 'Кресло', 'стул', 'кушетка'):
        assert FR.accept_views(r) == FR.ACCEPT_VIEWS + FR.SEAT_VIEWS
    assert FR.accept_views('стол обеденный') == FR.ACCEPT_VIEWS and FR.accept_views('столик') == FR.ACCEPT_VIEWS     # «стул» ≠ «стол»


def test_files_count_equals_items_times_views(tmp_path):
    roles = {'a_1': 'ваза', 'b_2': 'диван', 'c_3': 'шкаф', 'd_4': 'кресло'}
    total = 0
    for sku, role in roles.items():
        views = FR.accept_views(role)
        names = FR.frame_names(views, FR.ACCEPT_LIGHTS)
        assert len(names) == len(set(names)) == len(views) * len(FR.ACCEPT_LIGHTS)
        assert FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS) == []                        # пока ничего нет
        d = tmp_path / sku
        d.mkdir()
        for n in names[:-1]:
            (d / n).write_bytes(b'p')
        assert FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS) == []                        # без последнего кадра товар не готов
        (d / names[-1]).write_bytes(b'p')
        assert [os.path.basename(x) for x in FR.frames_of(str(tmp_path), sku, views, FR.ACCEPT_LIGHTS)] == names
        total += len(names)
    files = sum(len(fs) for _, _, fs in os.walk(tmp_path))
    assert files == total == 10 + 12 + 10 + 12                                                         # 4 товара: 2 сидячих по 6 видов × 2 света, 2 прочих по 5 × 2


def test_render_cmd_takes_views_from_table():
    cmd = FR.render_cmd('/g.glb', '/o', FR.accept_views('диван'), FR.ACCEPT_LIGHTS, 16, 2)
    spec = cmd[cmd.index('--views') + 1].split(',')
    assert [s.split(':')[0] for s in spec] == list(FR.accept_views('диван'))
    assert all(tuple(float(x) for x in s.split(':')[1:]) == FR.VIEW_DEFS[s.split(':')[0]] for s in spec)
    assert cmd[cmd.index('--lights') + 1] == 'key,graze' and '--shade' not in cmd
    assert '--shade' in FR.render_cmd('/g.glb', '/o', FR.VIEWS, ('key',), 16, 2, 'recalc')
    assert os.path.isfile(FR.RENDER_STAND)                                                            # стенд лежит там, куда указывает команда
    page = FR.frame_names(FR.VIEWS)                                                                  # страница этапа (T-180/5) — прежние имена
    assert page == ['01_az000_clay.png', '02_az225_clay.png']


def _fake_run(calls, out_dir_holder):
    """Подмена subprocess.run: «рендер» (команда с --out) создаёт кадры, остальное (form_gate) только записывает команду."""
    class P:
        returncode = 0

    def run(cmd, *a, **k):
        if '--views' in cmd:
            sku_out = cmd[cmd.index('--out') + 1]
            os.makedirs(sku_out, exist_ok=True)
            for n in FR.frame_names(FR.accept_views('шкаф'), FR.ACCEPT_LIGHTS):
                open(os.path.join(sku_out, n), 'wb').write(b'p')
        else:
            calls.append(cmd)
        return P()
    return run


def _run_main(monkeypatch, tmp_path, extra):
    glbs = tmp_path / 'glbs'
    glbs.mkdir()
    (glbs / 'a_1-hd.glb').write_bytes(b'g')
    out = tmp_path / 'out'
    calls = []
    monkeypatch.setattr(FR.subprocess, 'run', _fake_run(calls, out))
    monkeypatch.setattr(sys, 'argv', ['forms_render.py', '--glbs', str(glbs), '--out', str(out), '--ids', 'a_1', '--no-slot', '--accept'] + extra)
    rc = FR.main()
    return rc, calls, out


def test_form_gate_runs_after_accept_frames_by_default(monkeypatch, tmp_path):
    rc, calls, out = _run_main(monkeypatch, tmp_path, ['--photos', str(tmp_path), '--vlm-cache', str(tmp_path / 'c')])
    assert rc == 0 and len(calls) == 1
    cmd = calls[0]
    assert any(c.endswith('form_gate.py') for c in cmd)
    assert cmd[cmd.index('--skus') + 1] == 'a_1' and cmd[cmd.index('--out') + 1] == str(out)
    assert '--photos' in cmd and '--vlm-cache' in cmd


def test_form_gate_off_by_flag_and_without_accept(monkeypatch, tmp_path):
    rc, calls, _ = _run_main(monkeypatch, tmp_path, ['--no-form-gate'])
    assert rc == 0 and calls == []


def test_form_gate_failure_does_not_break_render(monkeypatch, tmp_path):
    monkeypatch.setattr(FR.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(OSError('нет python')))
    assert FR.run_form_gate(str(tmp_path), str(tmp_path), ['a_1'], {}) == 1               # сбой запуска — код 1 у шага, не исключение
    assert FR.run_form_gate(str(tmp_path), str(tmp_path), [], {}) == 0                    # нечего проверять


def test_form_gate_vlm_on_by_default_and_flags_pass_through(monkeypatch, tmp_path):
    rc, calls, _ = _run_main(monkeypatch, tmp_path, [])
    cmd = calls[0]
    assert rc == 0 and '--no-vlm' not in cmd and '--vlm-all' not in cmd and '--vlm-budget' not in cmd      # оценщик идёт сам: фото и кэш form_gate находит/ставит сам, потолок — из rules
    tmp2 = tmp_path / 'second'
    tmp2.mkdir()
    rc, calls, _ = _run_main(monkeypatch, tmp2, ['--no-vlm', '--vlm-all', '--vlm-budget', '0.05'])
    cmd = calls[0]
    assert '--no-vlm' in cmd and '--vlm-all' in cmd and cmd[cmd.index('--vlm-budget') + 1] == '0.05'
