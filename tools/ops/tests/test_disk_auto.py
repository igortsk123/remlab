"""Тесты автоуборки диска (T-20261125-89, владелец TG 2769): забытые наблюдатели tail, сторож роста, прогноз «часов до стопа», одна реализация занятости, правила в dev-disk.json.
Процессы подделываем каталогом `proc` (cmdline, stat, fd, environ) — настоящих процессов не трогаем.
Запуск: `python -m pytest tools/ops/tests/test_disk_auto.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import logs_archive as la  # noqa: E402

GB = 1024 ** 3
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def reset_monitor(monkeypatch):
    monkeypatch.setattr(la, 'MONITOR_MAX_H', None)
    monkeypatch.setattr(la, 'MONITOR_NOTES', [])


def fake_proc(root: Path, pid: int, args: list, age_h: float | None = None, cwd: str | None = None, fds: list | None = None, env: str | None = None, now: float | None = None):
    """Подделка /proc/<pid>: cmdline, stat (starttime при age_h), cwd, fd/*, environ."""
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in args) + b'\0')
    if age_h is not None:
        now = time.time() if now is None else now
        (root / 'stat').write_text(f'cpu 1 2 3\nbtime {int(now) - 1000 * 3600}\n')
        (d / 'stat').write_text(f'{pid} ({os.path.basename(args[0])}) S ' + ' '.join(['0'] * 18) + f' {int((1000 - age_h) * 3600 * 100)} 0 0\n')   # starttime в тиках от btime (btime = now − 1000 ч)
    if cwd:
        os.symlink(cwd, d / 'cwd')
    (d / 'fd').mkdir(exist_ok=True)
    for i, t in enumerate(fds or []):
        os.symlink(t, d / 'fd' / str(3 + i))
    if env is not None:
        (d / 'environ').write_bytes(env.encode().replace(b'\n', b'\0'))


@pytest.mark.parametrize('args,expected', [
    (['tail', '-F', '/x/a.log'], True),
    (['tail', '-f', '/x/a.log'], True),
    (['tail', '-fn50', '/x/a.log'], True),
    (['tail', '--follow=name', '/x/a.log'], True),
    (['bash', '-c', 'tail -F /x/a.log | grep -E "a|b"'], True),
    (['bash', '-c', 'tail -F /x/a.log 2>&1 | grep --line-buffered x | awk "{print}"'], True),
    (['bash', '-c', 'stdbuf -oL tail -F /x/a.log | sed s/a/b/'], True),
    (['tail', '-n', '5', '/x/a.log'], False),                                # без -f: разовое чтение
    (['bash', '-c', 'tail -F /x/a.log > /x/b.log'], False),                  # пишет
    (['bash', '-c', 'tail -F /x/a.log; rm -rf /x/y'], False),
    (['bash', '-c', 'tail -F /x/a.log | python3 handler.py'], False),        # труба в программу, не фильтр
    (['bash', '-c', 'tail -F /x/a.log || true'], False),
    (['bash', '-c', 'cd /x && tail -F a.log | grep x'], False),
    (['python3', 'tail', '-F', 'x'], False),
    (['grep', 'x', '/x/a.log'], False),
    ([], False),
])
def test_is_monitor_cmd(args, expected):
    assert la.is_monitor_cmd(args) is expected


def test_stale_tail_does_not_hold_but_young_tail_and_other_processes_do(tmp_path):
    folder = tmp_path / 'src' / 't183-2'
    folder.mkdir(parents=True)
    log = folder / 'x.log'
    log.write_text('x')
    proc = tmp_path / 'proc'
    proc.mkdir()
    fake_proc(proc, 100, ['tail', '-F', str(log)], age_h=30, fds=[str(log)])                      # забытый: 30 ч
    assert la.busy_by(str(folder), proc_root=str(proc), monitor_max_h=None) != ''                 # порога нет — держит, как раньше
    assert la.busy_by(str(folder), proc_root=str(proc), monitor_max_h=12) == ''                   # старше 12 ч — не держит
    assert any('наблюдатель старше 12 ч — не держит' in n and 'pid 100' in n for n in la.MONITOR_NOTES)
    proc2 = tmp_path / 'proc2'
    proc2.mkdir()
    fake_proc(proc2, 101, ['bash', '-c', f'tail -F {log} | grep x'], age_h=1, fds=[str(log)])     # свежий: 1 ч
    assert 'pid 101' in la.busy_by(str(folder), proc_root=str(proc2), monitor_max_h=12)
    proc3 = tmp_path / 'proc3'
    proc3.mkdir()
    fake_proc(proc3, 102, ['python3', 'run.py', str(log)], age_h=300, cwd=str(folder))             # старый, но НЕ наблюдатель — держит
    assert 'pid 102' in la.busy_by(str(folder), proc_root=str(proc3), monitor_max_h=12)
    proc4 = tmp_path / 'proc4'
    proc4.mkdir()
    fake_proc(proc4, 103, ['tail', '-F', str(log)], fds=[str(log)])                                # возраст прочитать нельзя — считаем свежим, держит
    assert 'pid 103' in la.busy_by(str(folder), proc_root=str(proc4), monitor_max_h=12)


def test_live_refs_stale_monitor_does_not_hold_folder(tmp_path):
    src = tmp_path / 'src'
    (src / 't195').mkdir(parents=True)
    proc = tmp_path / 'proc'
    proc.mkdir()
    fake_proc(proc, 200, ['bash', '-c', f'tail -F {src}/t195/run.log | grep ERR'], age_h=48)
    fake_proc(proc, 201, ['python3', 'job.py', f'{src}/t200/out'], age_h=1)
    hd = tmp_path / 'hd'
    hd.mkdir()
    assert 't195' in la.live_refs(str(src), proc_root=str(proc), heavy_dir=str(hd))
    live = la.live_refs(str(src), proc_root=str(proc), heavy_dir=str(hd), monitor_max_h=12)
    assert 't195' not in live and 't200' in live                                                   # прогон держит, наблюдатель — нет
    assert any('наблюдатель старше 12 ч — не держит' in n for n in la.MONITOR_NOTES)


def test_one_busy_implementation_cwd_cmdline_fd_pythonpath(tmp_path):
    d = tmp_path / 'wt'
    d.mkdir()
    proc = tmp_path / 'proc'
    proc.mkdir()
    fake_proc(proc, 1, ['sleep', '1'], cwd=str(d))
    fake_proc(proc, 2, ['cat', str(d / 'a.txt')])
    fake_proc(proc, 3, ['sleep', '1'], fds=[str(d / 'open.log')])
    fake_proc(proc, 4, ['python3', 'x.py'], env=f'HOME=/h\nPYTHONPATH=/other:{d}/lib:/z\n')
    fake_proc(proc, 5, ['sleep', '1'], cwd=str(tmp_path / 'wt-другая'))
    snap = la.proc_snapshot(str(proc))
    assert len(snap) == 5
    for pid, what in ((1, 'cwd внутри'), (2, 'в командной строке'), (3, 'открыт файл внутри'), (4, 'PYTHONPATH внутри')):
        one = la.proc_snapshot(str(proc))
        one = [e for e in one if e['pid'] == str(pid)]
        assert f'pid {pid}: {what}' == la.held_in(str(d), one), (pid, la.held_in(str(d), one))
    assert la.held_in(str(tmp_path / 'wt-иная'), snap) == ''
    assert la.busy_by(str(d), proc_root=str(proc)).endswith('внутри') or 'командной' in la.busy_by(str(d), proc_root=str(proc))


def test_holders_from_heavy_slot_are_in_snapshot(tmp_path):
    d = tmp_path / 'wt'
    d.mkdir()
    proc = tmp_path / 'proc'
    (proc / '777').mkdir(parents=True)
    hd = tmp_path / 'hd'
    hd.mkdir()
    (hd / 'holder1').write_text(f'pid=777\nlabel=mesh run\ncmd=python3 run.py --out {d}/out\n')
    snap = la.proc_snapshot(str(proc), holders=True, heavy_dir=str(hd))
    assert 'держатель heavy-slot «mesh run»' in la.held_in(str(d), snap)
    assert la.held_in(str(d), la.proc_snapshot(str(proc), holders=False, heavy_dir=str(hd))) == ''


def test_hdd_mounted_and_hours_to_stop():
    assert la.hdd_mounted('/proc') == '/proc' and la.hdd_mounted('/нет/такого') == '' and la.hdd_mounted('/') == ''
    assert la.hours_to_stop(40, 15, 30, 6) == pytest.approx(5.0)            # 5 ГБ/ч, запас 25 ГБ
    assert la.hours_to_stop(15, 15, 30, 6) == 0 and la.hours_to_stop(10, 15, 30, 6) == 0
    assert la.hours_to_stop(40, 15, 0, 6) is None and la.hours_to_stop(40, 15, -3, 6) is None


RULE = {'grow_alert_gb': 20, 'grow_window_h': 24, 'grow_top': 3, 'grow_alert_every_h': 6, 'forecast_window_h': 6, 'forecast_warn_h': 12, 'src': '/нет'}


def gc(tmp_path, sizes, t, free=None, rules=None, sent=None):
    return la.growth_check(dict(RULE, **(rules or {})), now=t, du=lambda src: sizes, state_path=str(tmp_path / 'snap.json'), free=free, stop_gb=15 if free is not None else None)


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(la, 'alert', lambda text: sent.append(text))
    return sent


def test_growth_first_snapshot_no_verdict_then_alert_with_top3(tmp_path, alerts):
    msg, warn = gc(tmp_path, {'a': 10 * GB, 'b': 5 * GB, 'gone': 50 * GB}, NOW)
    assert 'вердикта нет' in msg and warn == '' and alerts == []
    msg, warn = gc(tmp_path, {'a': 10 * GB, 'b': 5 * GB, 'gone': 50 * GB}, NOW + 1800)         # меньше часа истории — всё ещё без вердикта
    assert 'вердикта нет' in msg and warn == ''
    # через сутки: a +30, c +4, d +2, e +1, b без изменений; папка gone (-50) ушла на HDD — рост НЕ скрывает (считаем сумму положительных)
    now2 = NOW + 24 * 3600
    msg, warn = gc(tmp_path, {'a': 40 * GB, 'b': 5 * GB, 'c': 4 * GB, 'd': 2 * GB, 'e': 1 * GB}, now2)
    assert 'ТРЕВОГА' in msg and warn.startswith('WARN:disk_grow:') and '37 ГБ' in warn
    top = warn.split('больше всех: ')[1].split('; ')
    assert [t.split(' +')[0] for t in top] == ['a', 'c', 'd'] and len(top) == 3                  # три самые растущие
    assert len(alerts) == 1 and 'WARN:disk_grow' in alerts[0]
    msg, warn = gc(tmp_path, {'a': 41 * GB, 'b': 5 * GB, 'c': 4 * GB, 'd': 2 * GB, 'e': 1 * GB}, now2 + 3600)   # час спустя: WARN в дайджест снова, тревога в TG — нет (grow_alert_every_h)
    assert warn.startswith('WARN:disk_grow:') and len(alerts) == 1
    gc(tmp_path, {'a': 70 * GB, 'b': 5 * GB, 'c': 4 * GB}, now2 + 7 * 3600)                        # через 7 ч (окно сравнивает со снимком now2: +30) — повтор тревоги
    assert len(alerts) == 2


def test_growth_below_threshold_is_quiet_and_disabled_without_rules(tmp_path, alerts):
    gc(tmp_path, {'a': 10 * GB}, NOW)
    msg, warn = gc(tmp_path, {'a': 25 * GB}, NOW + 24 * 3600)                                     # +15 < 20
    assert warn == '' and '+15.0 ГБ' in msg and alerts == []
    assert la.growth_check({'src': '/x', 'grow_alert_gb': None, 'grow_window_h': None}, du=lambda s: {}) == ('', '')   # нет порогов в rules — сторож выключен


def test_forecast_hours_to_stop_warns_below_12h_with_top3(tmp_path, alerts):
    gc(tmp_path, {'a': 10 * GB, 'b': 1 * GB}, NOW, free=40)
    msg, warn = gc(tmp_path, {'a': 40 * GB, 'b': 1 * GB, 'c': 3 * GB}, NOW + 6 * 3600, free=40)   # +33 ГБ за 6 ч = 5,5 ГБ/ч; (40−15)/5,5 ≈ 4,5 ч < 12
    assert 'прогноз' in msg and '≈ 4.5 ч' in msg
    assert 'WARN:disk_stop:' in warn and 'до стопа (15 ГБ) ≈ 5 ч' in warn and 'растут: a +30.0 ГБ; c +3.0 ГБ' in warn
    assert any('WARN:disk_stop' in a for a in alerts)


def test_forecast_quiet_when_enough_time_or_no_growth(tmp_path, alerts):
    gc(tmp_path, {'a': 10 * GB}, NOW, free=300)
    msg, warn = gc(tmp_path, {'a': 14 * GB}, NOW + 6 * 3600, free=300)                            # 0,7 ГБ/ч; (300−15)/0,7 ≈ 427 ч
    assert 'прогноз' in msg and 'WARN:disk_stop' not in warn
    msg, warn = gc(tmp_path, {'a': 14 * GB}, NOW + 12 * 3600, free=300)                           # роста нет
    assert 'до стопа не дойдём' in msg or 'прогноз' in msg
    assert alerts == []


def test_du_children_skips_symlinks_hidden_and_files(tmp_path):
    src = tmp_path / 'src'
    (src / 't1').mkdir(parents=True)
    (src / 't1' / 'f.bin').write_bytes(b'\0' * 100_000)
    (src / '.hidden').mkdir()
    (src / 'single.log').write_text('x')
    (tmp_path / 'hdd' / 'moved').mkdir(parents=True)
    os.symlink(tmp_path / 'hdd' / 'moved', src / 't2')
    out = la.du_children(str(src))
    assert set(out) == {'t1'} and out['t1'] >= 100_000


def test_rules_file_has_t89_keys_with_why():
    r = la.rules()
    assert r['monitor_max_h'] == 12 and r['grow_alert_gb'] == 20 and r['grow_window_h'] == 24 and r['grow_top'] == 3
    assert r['forecast_window_h'] == 6 and r['forecast_warn_h'] == 12 and r['grow_alert_every_h'] == 6
    assert r['worktrees_block'] is False                                                        # папки с копиями кода тоже уезжают (ссылка на месте)
    d = json.loads((OPS.parent / 'scout' / 'rules' / 'dev-disk.json').read_text(encoding='utf-8'))
    a = d['archive']
    for why in ('_monitor_why', '_grow_why', '_forecast_why', '_worktrees_block_why'):
        assert 'T-20261125-89' in a.get(why, '') or 'T-89' in a.get(why, ''), why
    assert 'T-20261125-89' in d['_worktree_prune_why']
    assert 'TG 2769' in a['_monitor_why'] and 'TG 2769' in a['_grow_why'] and 'TG 2769' in d['_worktree_prune_why']
    assert d['start_min_free_gb'] == 15                                                         # граница «стоп» для прогноза — один источник


def test_hourly_unit_runs_prune_then_archive_with_growth():
    svc = (OPS.parent.parent / 'infra' / 'server' / 'dev-disk' / 'remlab-logs-archive-hourly.service').read_text(encoding='utf-8')
    lines = [ln for ln in svc.splitlines() if ln.startswith('ExecStart')]
    assert len(lines) == 2
    assert 'worktree_prune.py --apply' in lines[0] and lines[0].startswith('ExecStart=-')       # сперва снятие копий; его сбой перенос не отменяет
    assert 'logs_archive.py --apply --digest --if-low --growth' in lines[1]
    assert svc.index(lines[0]) < svc.index(lines[1])
