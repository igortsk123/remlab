"""Тесты ночного переноса логов на HDD `tools/ops/logs_archive.py` (T-20261123-35) — только временные папки и подставные данные.

«HDD» — папка в tmp_path, репозиторий — свой временный git-репо, процессы — подставная функция `busy`. Настоящие ~/remlab-logs и /mnt/hdd не трогаются.
Запуск: `python -m pytest tools/ops/tests/test_logs_archive.py -q`."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import logs_archive as la  # noqa: E402

DAY = 86400
NOW = time.time()
pytestmark = pytest.mark.skipif(shutil.which('rsync') is None or shutil.which('git') is None, reason='нужны rsync и git')


def mk(path: Path, files: dict, age_days: float) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name, size in files.items():
        f = path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b'x' * size)
        t = NOW - age_days * DAY
        os.utime(f, (t, t))
    t = NOW - age_days * DAY
    for d in [path] + [p for p in path.rglob('*') if p.is_dir()]:
        os.utime(d, (t, t))
    return path


@pytest.fixture
def world(tmp_path):
    src, dst, repo = tmp_path / 'logs', tmp_path / 'hdd', tmp_path / 'repo'
    src.mkdir()
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    (repo / 'plan.md').write_text('вход пакета — remlab-logs/ref-1123/out, а старая папка нигде не названа\n')
    subprocess.run(['git', '-C', str(repo), '-c', 'user.email=a@b', '-c', 'user.name=t', 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.email=a@b', '-c', 'user.name=t', 'commit', '-qm', 'x'], check=True)
    r = {'src': str(src), 'dst': str(dst), 'days': 5, 'min_hdd_free_gb': 0, 'never': []}
    return src, dst, repo, r


def names(lst):
    return sorted(c['name'] if isinstance(c, dict) else c[0] for c in lst)


def test_picks_old_unreferenced_only(world):
    src, dst, repo, r = world
    mk(src / 't77-old', {'a.bin': 4000, 'sub/b.bin': 1000}, 9)         # старая, без ссылок → к переносу
    mk(src / 'ref-1123', {'a.bin': 100}, 9)                            # старая, но имя в плане → остаётся
    mk(src / 'fresh-1123', {'a.bin': 100}, 1)                          # свежая
    mk(src / 'mixed-1123', {'old.bin': 100}, 9)                        # внутри один свежий файл → свежая
    (src / 'mixed-1123' / 'new.bin').write_bytes(b'y')
    (src / 'plain.log').write_text('одиночный журнал')                 # файл — не папка
    os.symlink(src / 't77-old', src / 'already-moved')                  # ссылка — уже перенесена
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    assert names(todo) == ['t77-old']
    sk = dict(skipped)
    assert 'ссылка' in sk['ref-1123'] and 'свежая' in sk['fresh-1123'] and 'свежая' in sk['mixed-1123']
    assert 'plain.log' not in sk and 'already-moved' not in sk
    c = todo[0]
    assert c['total'] == 5000 and c['freed'] == 5000


def test_busy_worktree_and_never_are_kept(world):
    src, dst, repo, r = world
    r['never'] = ['keepme']
    mk(src / 'keepme', {'a': 10}, 9)
    mk(src / 'busy-1', {'a': 10}, 9)
    mk(src / 'wt-1', {'a': 10}, 9)
    (src / 'wt-1' / '.git').write_text('gitdir: x')                     # рабочая копия git
    os.utime(src / 'wt-1' / '.git', (NOW - 9 * DAY, NOW - 9 * DAY))
    os.utime(src / 'wt-1', (NOW - 9 * DAY, NOW - 9 * DAY))
    mk(src / 'ok-1', {'a': 10}, 9)
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: 'pid 1: cwd внутри' if p.endswith('busy-1') else '')
    assert names(todo) == ['ok-1']
    sk = dict(skipped)
    assert sk['keepme'] == 'в never' and 'рабочая копия' in sk['wt-1'] and 'занята' in sk['busy-1']
    r['worktrees_block'] = False                                          # владелец разрешил: рабочие копии тоже уезжают (ссылка на месте), полный клон — нет
    (src / 'clone-1').mkdir()
    (src / 'clone-1' / '.git').mkdir()
    mk(src / 'clone-1', {'a': 10}, 9)
    os.utime(src / 'clone-1' / '.git', (NOW - 9 * DAY, NOW - 9 * DAY))
    os.utime(src / 'clone-1', (NOW - 9 * DAY, NOW - 9 * DAY))
    todo2, skipped2 = la.candidates(r, str(repo), now=NOW, busy=lambda p: 'pid 1: cwd внутри' if p.endswith('busy-1') else '')
    assert names(todo2) == ['ok-1', 'wt-1'] and 'полный клон' in dict(skipped2)['clone-1']


def test_hardlinked_files_do_not_count_as_freed(world, tmp_path):
    src, dst, repo, r = world
    mk(src / 'h-1', {'own.bin': 3000}, 9)
    other = tmp_path / 'other.bin'
    other.write_bytes(b'z' * 2000)
    os.link(other, src / 'h-1' / 'shared.bin')                          # вторая жёсткая ссылка живёт вне папки
    total, freed = la.sizes(str(src / 'h-1'))
    assert total == 5000 and freed == 3000


def test_same_inode_counted_once(world):
    src, dst, repo, r = world
    mk(src / 'd-1', {'a.bin': 1000}, 9)
    os.link(src / 'd-1' / 'a.bin', src / 'd-1' / 'b.bin')
    total, freed = la.sizes(str(src / 'd-1'))
    assert total == 1000 and freed == 0                                 # обе ссылки внутри: nlink==2 → после переноса rsync -H сохранит пару, но «освободит» по правилу links==1 — 0


def test_apply_moves_and_leaves_symlink(world):
    src, dst, repo, r = world
    mk(src / 't77-old', {'a.bin': 4000, 'sub/b.bin': 1000}, 9)
    todo, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    ok, line = la.move_one(todo[0], r, now=NOW, busy=lambda p: '')
    assert ok, line
    link = src / 't77-old'
    assert link.is_symlink() and os.readlink(link) == str(dst / 't77-old')
    assert (dst / 't77-old' / 'sub' / 'b.bin').read_bytes() == b'x' * 1000 and (link / 'a.bin').stat().st_size == 4000   # пути работают через ссылку
    todo2, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    assert todo2 == []                                                  # повтор — ничего: ссылка уже стоит


def test_rsync_failure_keeps_data_and_no_link(world):
    src, dst, repo, r = world
    mk(src / 'zq-1', {'a.bin': 100}, 9)
    todo, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    ok, line = la.move_one(todo[0], r, now=NOW, busy=lambda p: '', rsync=lambda cmd: 23)
    assert not ok and '❗' in line and (src / 'zq-1').is_dir() and not (src / 'zq-1').is_symlink() and (src / 'zq-1' / 'a.bin').exists()


def test_not_emptied_dir_gets_no_link(world):
    src, dst, repo, r = world
    mk(src / 'n-1', {'a.bin': 100}, 9)
    todo, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')

    def fake_rsync(cmd):                                                # «копия прошла», но исходный файл остался (например, вырос во время копии)
        return 0
    ok, line = la.move_one(todo[0], r, now=NOW, busy=lambda p: '', rsync=fake_rsync)
    assert not ok and 'не опустела' in line and (src / 'n-1' / 'a.bin').exists() and not (src / 'n-1').is_symlink()


def test_fresh_file_appearing_before_move_skips(world):
    src, dst, repo, r = world
    mk(src / 'late-1', {'a.bin': 100}, 9)
    todo, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    (src / 'late-1' / 'new.bin').write_bytes(b'n')                      # пока шли по списку, кто-то записал
    ok, line = la.move_one(todo[0], r, now=time.time(), busy=lambda p: '')
    assert not ok and 'свежий файл' in line and not (src / 'late-1').is_symlink()


def test_hdd_space_check_skips(world, monkeypatch):
    src, dst, repo, r = world
    mk(src / 'big-1', {'a.bin': 100}, 9)
    todo, _ = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    monkeypatch.setattr(la, 'hdd_free_gb', lambda d: 1.0)
    r2 = dict(r, min_hdd_free_gb=50)
    ok, line = la.move_one(todo[0], r2, now=NOW, busy=lambda p: '')
    assert not ok and '❗' in line and 'HDD' in line and (src / 'big-1').is_dir() and not (src / 'big-1').is_symlink()


def test_repo_check_failure_moves_nothing(world, tmp_path):
    src, dst, repo, r = world
    mk(src / 'x-1', {'a.bin': 100}, 9)
    todo, skipped = la.candidates(r, str(tmp_path / 'нет-такого-репо'), now=NOW, busy=lambda p: '')
    assert todo == [] and 'ссылка в репозитории' in dict(skipped)['x-1']   # не смогли проверить ссылки → считаем, что они есть


def test_busy_by_detects_cwd_and_cmdline(tmp_path):
    proc = tmp_path / 'proc' / '4242'
    (proc / 'fd').mkdir(parents=True)
    d = tmp_path / 'dir-x'
    d.mkdir()
    os.symlink(str(d / 'sub'), proc / 'cwd')
    (proc / 'cmdline').write_bytes(b'python\x00script\x00')
    assert 'cwd' in la.busy_by(str(d), proc_root=str(tmp_path / 'proc'))
    os.unlink(proc / 'cwd')
    os.symlink('/', proc / 'cwd')
    (proc / 'cmdline').write_bytes(f'python\x00{d}/run.py\x00'.encode())
    assert 'командной строке' in la.busy_by(str(d), proc_root=str(tmp_path / 'proc'))
    (proc / 'cmdline').write_bytes(b'python\x00other\x00')
    assert la.busy_by(str(d), proc_root=str(tmp_path / 'proc')) == ''


def test_main_dry_lists_without_touching(world, monkeypatch, capsys, tmp_path):
    src, dst, repo, r = world
    mk(src / 't77-old', {'a.bin': 2000}, 9)
    rules = tmp_path / 'rules.json'
    rules.write_text('{"archive": {"src": "%s", "dst": "%s", "days": 5, "min_hdd_free_gb": 0, "never": []}}' % (src, dst))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules))
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setattr(la, 'busy_by', lambda p, proc_root='/proc': '')
    assert la.main([]) == 0
    out = capsys.readouterr().out
    assert 'сухо' in out and 'перенесу t77-old' in out and (src / 't77-old').is_dir() and not (src / 't77-old').is_symlink() and not dst.exists()


def test_systemd_units_exist_and_do_not_enable_themselves():
    root = Path(__file__).resolve().parents[3] / 'infra' / 'server' / 'dev-disk'
    svc, tmr = (root / 'remlab-logs-archive.service').read_text(encoding='utf-8'), (root / 'remlab-logs-archive.timer').read_text(encoding='utf-8')
    assert 'logs_archive.py --apply' in svc and 'OnCalendar=' in tmr and 'Persistent=true' in tmr
    assert 'ВКЛЮЧАЕТ ТОЛЬКО ВЛАДЕЛЕЦ' in tmr


def test_refs_exclude_ignores_history_but_not_code(world):
    src, dst, repo, r = world
    (repo / '.memory_bank' / 'changelog').mkdir(parents=True)
    (repo / '.memory_bank' / 'changelog' / 'log.md').write_text('делали в jrn-777, вывод в папке jrn-777\n')
    (repo / 'tool.py').write_text("OUT = 'code-888'\n")
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.email=a@b', '-c', 'user.name=t', 'commit', '-qm', 'y'], check=True)
    mk(src / 'jrn-777', {'a': 10}, 9)
    mk(src / 'code-888', {'a': 10}, 9)
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    assert names(todo) == [] and set(dict(skipped)) >= {'jrn-777', 'code-888'}          # без исключений держит и журнал
    r['refs_exclude'] = ['.memory_bank/changelog']
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: '')
    assert names(todo) == ['jrn-777'] and 'ссылка в репозитории' in dict(skipped)['code-888']   # журнал не держит, код — держит
