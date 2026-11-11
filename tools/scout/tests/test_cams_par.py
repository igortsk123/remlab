"""Ракурсы тура параллельно и к сроку (T-20261111-23, `tools/scout/cams_par.py`). Вместо node — маленький питон-процесс:
пишет файл итога куска через заданное время (или падает). Проверяем: куски идут параллельно, к сроку готовые пары попадают в
данные, недосчитанные процессы сняты, сбой куска не валит остальные, строка лога честно говорит «X из Y».
    pytest tools/scout/tests/test_cams_par.py"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import cams_par as CP  # noqa: E402

FAKE = ('import json, sys, time\n'
        'ids, part, delay, rc = sys.argv[1].split(","), sys.argv[2], float(sys.argv[3]), int(sys.argv[4])\n'
        'time.sleep(delay)\n'
        'if rc: print("сбой подбора"); sys.exit(rc)\n'
        'json.dump({"shared": len(ids) > 1, "vars": {i: {"cams": [{"name": "C1", "x": 1}], "cam_level": 0, '
        '"cam_cover": {"covered": 1, "missing": []}} for i in ids}}, open(part, "w"))\n')


def _setup(tmp_path, ids):
    fake = tmp_path / 'fake_node.py'
    fake.write_text(FAKE, encoding='utf-8')
    data = tmp_path / 'bundle.json'
    data.write_text(json.dumps({'variants': [{'id': i, 'items': []} for i in ids]}), encoding='utf-8')
    return str(fake), str(data)


def _cmd(fake, delay_of, rc_of=lambda ids: 0):
    return lambda ids, part: [sys.executable, fake, ','.join(ids), part, str(delay_of(ids)), str(rc_of(ids))]


def test_parallel_all_done(tmp_path):
    ids = [f'v{i}' for i in range(8)]
    fake, data = _setup(tmp_path, ids)
    t = time.monotonic()
    line = CP.cams('/root', data, 4, 30, units=[[i] for i in ids], cmd_of=_cmd(fake, lambda ids: 0.6))
    took = time.monotonic() - t
    assert line.startswith('ракурсы окна в данных: вариантов 8 из 8'), line
    assert took < 8 * 0.6, took                                   # параллельно: 2 круга, а не 8 подряд
    D = json.load(open(data))
    assert all(v['cams'] and v['cam_level'] == 0 for v in D['variants']) and D['cams_shared'] is False
    assert not [f for f in os.listdir(tmp_path) if 'cams-par' in f]   # временные файлы убраны


def test_deadline_keeps_finished_and_kills_rest(tmp_path):
    """Срок вышел: готовые куски — в данные, долгий процесс снят, его вариант без пары (страница досчитает)."""
    ids = ['living', 'b1', 'slow']
    fake, data = _setup(tmp_path, ids)
    t = time.monotonic()
    line = CP.cams('/root', data, 2, 2.0, units=[[i] for i in ids], cmd_of=_cmd(fake, lambda ids: 30 if ids == ['slow'] else 0.2))
    assert time.monotonic() - t < 6                                # не ждали долгий процесс
    assert line.startswith('WARN:trial_cams: ракурсы окна в данных: вариантов 2 из 3') and 'slow' in line, line
    D = json.load(open(data))
    assert [bool(v.get('cams')) for v in D['variants']] == [True, True, False]


def test_failed_unit_does_not_stop_others(tmp_path):
    ids = ['a', 'b', 'c']
    fake, data = _setup(tmp_path, ids)
    line = CP.cams('/root', data, 3, 30, units=[[i] for i in ids], cmd_of=_cmd(fake, lambda ids: 0.1, lambda ids: 3 if ids == ['b'] else 0))
    assert 'вариантов 2 из 3' in line and 'сбои: кусок b: rc=3 сбой подбора' in line, line


def test_shared_unit_and_none_done(tmp_path):
    fake, data = _setup(tmp_path, ['s1', 's2'])
    line = CP.cams('/root', data, 4, 30, units=[['s1', 's2']], cmd_of=_cmd(fake, lambda ids: 0.1))
    assert line.startswith('ракурсы окна в данных: вариантов 2 из 2 (за') and 'процессов 1' in line, line
    assert json.load(open(data))['cams_shared'] is True
    fake, data = _setup(tmp_path, ['x'])
    before = open(data, 'rb').read()
    line = CP.cams('/root', data, 4, 30, units=[['x']], cmd_of=_cmd(fake, lambda ids: 0, lambda ids: 1))
    assert line.startswith('WARN:trial_cams: ракурсы 0 из 1') and open(data, 'rb').read() == before


def test_units_failure_is_warn(tmp_path):
    def run(cmd, **kw):
        raise OSError('нет node')
    _, data = _setup(tmp_path, ['a'])
    try:
        CP.units_of('/root', data, run=run)
    except OSError:
        pass
    else:
        raise AssertionError('ожидали исключение')
