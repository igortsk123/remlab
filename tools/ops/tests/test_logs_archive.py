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


# ───────────── --worktrees (T-20261123-38): сухой список рабочих копий git ─────────────
def _g(repo, *a):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.email=a@b', '-c', 'user.name=t', *a], check=True, capture_output=True)


@pytest.fixture
def wtw(tmp_path):
    """Репо с main = origin/main и рабочими копиями под tmp/logs: влитая, невлитая, грязная, с node_modules-ссылкой, сирота."""
    repo, src = tmp_path / 'repo', tmp_path / 'logs'
    repo.mkdir()
    src.mkdir()
    _g(repo, 'init', '-q', '-b', 'main')
    (repo / 'a.txt').write_text('1')
    _g(repo, 'add', '.')
    _g(repo, 'commit', '-qm', 'c1')
    _g(repo, 'update-ref', 'refs/remotes/origin/main', 'main')
    for name in ('merged', 'unmerged', 'dirty', 'nm', 'orphan', 'fresh', 'gone', 'busy'):
        _g(repo, 'worktree', 'add', '-q', '-b', f'br-{name}', str(src / name), 'main')
    (src / 'unmerged' / 'b.txt').write_text('2')
    _g(src / 'unmerged', 'add', '.')
    _g(src / 'unmerged', 'commit', '-qm', 'c2')
    (src / 'dirty' / 'tmp.txt').write_text('x')
    (src / 'nm' / 'node_modules').symlink_to(repo)                       # ссылка node_modules — допустима
    (src / 'nm' / '.gitignore').write_text('node_modules\n')              # ... если проигнорирована; сам .gitignore — правка, закоммитим
    _g(src / 'nm', 'add', '.')
    _g(src / 'nm', 'commit', '-qm', 'ign')
    _g(src / 'nm', 'update-ref', 'refs/remotes/origin/main', 'HEAD')      # nm влит: сдвигаем origin/main вперёд позже вместе с остальными
    _g(repo, 'update-ref', 'refs/remotes/origin/main', 'main')            # вернуть: origin/main = main (c1)
    shutil.rmtree(src / 'orphan')                                          # сирота: каталога нет, запись в git осталась
    old = NOW - 20 * 3600
    for n in ('merged', 'unmerged', 'dirty', 'nm', 'gone', 'busy'):
        for dp, dn, fn in os.walk(src / n):
            if '.git' in dp.split(os.sep) or os.path.islink(dp):
                continue
            for f in fn + dn:
                fp = os.path.join(dp, f)
                if not os.path.islink(fp):
                    os.utime(fp, (old, old))
        os.utime(src / n, (old, old))
    r = {'src': str(src), 'refs_exclude': [], 'wt': dict(la.WT_DEFAULTS, base='origin/main', big_mb=0.001, jobs=2)}
    return repo, src, r


def _by(infos):
    return {os.path.basename(i['path']): i for i in infos}


def test_worktrees_verdicts(wtw):
    repo, src, r = wtw
    wts = la.list_worktrees(str(repo), str(src))
    assert len(wts) == 8
    infos = _by([la.wt_info(w, str(repo), r, NOW, busy=lambda p: 'pid 7: cwd внутри' if p.endswith('busy') else '') for w in wts])
    assert infos['merged']['verdict'] == 'can' and infos['merged']['merged'] and infos['merged']['why'] == [], infos['merged']['why']
    assert infos['unmerged']['verdict'] == 'hold' and any('не влито' in w for w in infos['unmerged']['why'])
    assert infos['dirty']['verdict'] == 'hold' and any('не чисто' in w for w in infos['dirty']['why'])
    assert infos['busy']['verdict'] == 'hold' and any('занята' in w for w in infos['busy']['why'])
    assert infos['orphan']['verdict'] == 'orphan' and 'prune' in infos['orphan']['why'][0]
    assert infos['fresh']['verdict'] == 'hold' and any('правили' in w for w in infos['fresh']['why'])


def test_worktrees_fresh_is_held(wtw):
    repo, src, r = wtw
    (src / 'merged' / 'f.dat').write_bytes(b'z')                         # свежий файл (но не отслеживается → ещё и «не чисто»)
    w = [w for w in la.list_worktrees(str(repo), str(src)) if w['path'].endswith('/merged')][0]
    i = la.wt_info(w, str(repo), r, NOW, busy=lambda p: '')
    assert i['verdict'] == 'hold' and any('правили' in x for x in i['why'])


def test_worktrees_node_modules_symlink_allowed(wtw):
    repo, src, r = wtw
    nm = [w for w in la.list_worktrees(str(repo), str(src)) if w['path'].endswith('/nm')][0]
    i = la.wt_info(nm, str(repo), r, NOW, busy=lambda p: '')
    assert not i['dirty'] and i['freed'] < 10_000                          # ссылка в размер не входит; коммит .gitignore — не влит в origin/main:
    assert i['verdict'] == 'hold' and any('не влито' in x for x in i['why'])


def test_worktrees_branch_deleted_unmerged_is_maybe(wtw):
    repo, src, r = wtw
    g = [w for w in la.list_worktrees(str(repo), str(src)) if w['path'].endswith('/gone')][0]
    (src / 'gone' / 'x.txt').write_text('q')
    _g(src / 'gone', 'add', '.')
    _g(src / 'gone', 'commit', '-qm', 'only-here')
    old = NOW - 20 * 3600
    for dp, dn, fn in os.walk(src / 'gone'):
        if '.git' in dp.split(os.sep):
            continue
        for f in fn + dn:
            os.utime(os.path.join(dp, f), (old, old))
    os.utime(src / 'gone', (old, old))
    g = dict(g, head=subprocess.run(['git', '-C', str(src / 'gone'), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(), branch='нет-такой-ветки')
    i = la.wt_info(g, str(repo), r, NOW, busy=lambda p: '')
    assert i['branch_gone'] and not i['merged'] and i['verdict'] == 'maybe' and 'НЕ влит' in i['why'][0], i['why']


def test_worktrees_big_outputs_listed_with_refs(wtw):
    repo, src, r = wtw
    (src / 'unmerged' / 'out-big').mkdir()
    (src / 'unmerged' / 'out-big' / 'a.bin').write_bytes(b'x' * 5000)
    (repo / 'plan.md').write_text('смотри out-big там\n')
    _g(repo, 'add', '.')
    _g(repo, 'commit', '-qm', 'plan')
    (src / 'merged' / 'shots').mkdir()
    (src / 'merged' / 'shots' / 'a.png').write_bytes(b'y' * 3000)
    infos = [la.wt_info(w, str(repo), r, NOW, busy=lambda p: '') for w in la.list_worktrees(str(repo), str(src))]
    big = {x['entry']: x for x in la.big_outputs(infos, str(repo), r)}
    assert big['out-big/']['ref'] is True and big['shots/']['ref'] is False and big['shots/']['freed'] == 3000
    assert 'node_modules' not in ' '.join(big)


def test_worktrees_cli_dry_and_no_apply(wtw, monkeypatch, capsys, tmp_path):
    repo, src, r = wtw
    rules = tmp_path / 'rules.json'
    rules.write_text('{"archive": {"src": "%s", "dst": "%s/hdd", "worktrees": {"big_mb": 0.001, "jobs": 2}}}' % (src, tmp_path))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules))
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setattr(la, 'busy_by', lambda p, proc_root='/proc': '')
    assert la.main(['--worktrees', '--apply']) == 2                          # снимать код не умеет: только сухо
    assert la.main(['--worktrees']) == 0
    out = capsys.readouterr().out
    assert 'сухо, ничего не удалено' in out and '== СИРОТЫ' in out and '== КРУПНЫЕ ВЫХОДЫ' in out and 'ДЕРЖИМ' in out
    assert all((src / n).exists() for n in ('merged', 'unmerged', 'dirty'))   # ничего не тронуто


def test_worktrees_only_ignored_cache_is_separate_verdict(wtw):
    repo, src, r = wtw
    (repo / '.git' / 'info' / 'exclude').write_text('cache-x/\n')
    (src / 'merged' / 'cache-x').mkdir()
    (src / 'merged' / 'cache-x' / 'a.pyc').write_bytes(b'c')
    old = NOW - 20 * 3600
    for q in (src / 'merged' / 'cache-x' / 'a.pyc', src / 'merged' / 'cache-x', src / 'merged'):
        os.utime(q, (old, old))
    w = [w for w in la.list_worktrees(str(repo), str(src)) if w['path'].endswith('/merged')][0]
    i = la.wt_info(w, str(repo), r, NOW, busy=lambda p: '')
    assert i['verdict'] == 'can_ign' and 'только игнорируемое' in i['why'][0] and 'cache-x' in i['why'][0]
    (src / 'merged' / 'real.txt').write_text('n')                          # нетрекаемый файл — уже обычное «держим»
    os.utime(src / 'merged' / 'real.txt', (old, old))
    i = la.wt_info(w, str(repo), r, NOW, busy=lambda p: '')
    assert i['verdict'] == 'hold'


# ───────────── T-20261124-20: адаптивный порог суток и часовой запуск ─────────────
ADAPT = [{'free_lt_gb': 20, 'days': 1}, {'free_lt_gb': 25, 'days': 2}]


def test_effective_days_three_levels():
    r = {'days': 5, 'adaptive': ADAPT}
    assert la.effective_days(r, 14.4)[0] == 1            # < 20 → 1 сут
    assert la.effective_days(r, 19.99)[0] == 1
    assert la.effective_days(r, 20.0)[0] == 2            # граница: 20 уже не «< 20»
    assert la.effective_days(r, 24.9)[0] == 2            # < 25 → 2 сут
    assert la.effective_days(r, 25.0)[0] == 5            # иначе правило
    assert la.effective_days(r, 300)[0] == 5
    assert '14.4' in la.effective_days(r, 14.4)[1] and 'адаптивный' in la.effective_days(r, 14.4)[1]


def test_effective_days_never_raises_above_rule_and_order_independent():
    assert la.effective_days({'days': 1, 'adaptive': ADAPT}, 24)[0] == 1          # ступень «2 сут» не поднимает порог выше обычного 1
    assert la.effective_days({'days': 5, 'adaptive': list(reversed(ADAPT))}, 15)[0] == 1
    assert la.effective_days({'days': 5}, 1)[0] == 5                               # ступеней нет — как раньше
    assert la.top_free_lt({'adaptive': ADAPT}) == 25 and la.top_free_lt({}) == 0


def test_rules_file_has_adaptive_steps_matching_director_spec():
    r = la.rules()
    assert sorted((s['free_lt_gb'], s['days']) for s in r['adaptive']) == [(20, 1), (25, 2)]
    assert r['worktrees_block'] is False and r['days'] == 5   # T-89 п.5: папки с копиями кода тоже уезжают (ссылка на месте)


def _main_env(monkeypatch, world, tmp_path, free):
    src, dst, repo, r = world
    rules = tmp_path / 'rules.json'
    rules.write_text('{"archive": {"src": "%s", "dst": "%s", "days": 5, "min_hdd_free_gb": 0, "never": [], "adaptive": [{"free_lt_gb": 20, "days": 1}, {"free_lt_gb": 25, "days": 2}]}}' % (src, dst))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules))
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setenv('LOGS_ARCHIVE_LOCK', str(tmp_path / 'lock'))
    monkeypatch.setattr(la, 'busy_by', lambda p, proc_root='/proc': '')
    monkeypatch.setattr(la, 'free_gb', lambda p: free)
    return src, dst


def test_main_uses_threshold_by_free_space(world, monkeypatch, capsys, tmp_path):
    src, dst = _main_env(monkeypatch, world, tmp_path, 14.4)
    mk(src / 't-1d', {'a': 100}, 1.5)                      # 1,5 суток: при обычных 5 остаётся, при 1 уезжает
    assert la.main([]) == 0
    out = capsys.readouterr().out
    assert 'адаптивный порог 1 сут' in out and 'перенесу t-1d' in out
    _main_env(monkeypatch, world, tmp_path, 22.0)          # 22 ГБ → 2 сут: 1,5 суток ещё свежая
    la.main([])
    out = capsys.readouterr().out
    assert 'порог 2 сут' in out and 'перенесу t-1d' not in out and 'свежая' in out
    _main_env(monkeypatch, world, tmp_path, 80.0)          # много места — обычные 5 сут
    la.main([])
    assert 'обычный порог 5 сут' in capsys.readouterr().out


def test_explicit_days_overrides_adaptive(world, monkeypatch, capsys, tmp_path):
    src, dst = _main_env(monkeypatch, world, tmp_path, 14.4)
    mk(src / 't-3d', {'a': 100}, 3)
    la.main(['--days', '9'])
    out = capsys.readouterr().out
    assert 'перенесу t-3d' not in out and 'адаптивный' not in out


def test_if_low_exits_fast_when_space_is_enough(world, monkeypatch, capsys, tmp_path):
    src, dst = _main_env(monkeypatch, world, tmp_path, 40.0)
    mk(src / 't-old', {'a': 100}, 30)
    assert la.main(['--apply', '--digest', '--if-low']) == 0
    assert 'не нужен' in capsys.readouterr().out
    assert (src / 't-old').is_dir() and not (src / 't-old').is_symlink() and not dst.exists()     # ничего не тронуто


def test_if_low_applies_adaptive_move_and_keeps_worktrees_and_refs(world, monkeypatch, capsys, tmp_path):
    src, dst = _main_env(monkeypatch, world, tmp_path, 14.4)
    mk(src / 't-day', {'a': 1000}, 1.5)                    # 1,5 суток, без ссылок → уезжает
    mk(src / 'ref-1123', {'a': 100}, 1.5)                  # имя в плане → остаётся и на ступени 1 сут
    mk(src / 'wt-1', {'a': 100}, 1.5)
    (src / 'wt-1' / '.git').write_text('gitdir: x')        # рабочая копия git → остаётся (worktrees_block)
    os.utime(src / 'wt-1' / '.git', (NOW - 1.5 * DAY, NOW - 1.5 * DAY))
    mk(src / 'fresh', {'a': 100}, 0.2)                     # правили 5 часов назад → свежая
    assert la.main(['--apply', '--digest', '--if-low']) == 0
    out = capsys.readouterr().out
    assert (src / 't-day').is_symlink() and (dst / 't-day' / 'a').exists()
    assert (src / 'ref-1123').is_dir() and not (src / 'ref-1123').is_symlink()
    assert (src / 'wt-1').is_dir() and not (src / 'wt-1').is_symlink()
    assert (src / 'fresh').is_dir() and not (src / 'fresh').is_symlink()
    assert 'DIGEST:' in out and 'порог 1 сут' in out


def test_lock_blocks_second_run(world, monkeypatch, capsys, tmp_path):
    src, dst = _main_env(monkeypatch, world, tmp_path, 14.4)
    mk(src / 't-day', {'a': 100}, 3)
    held = la.take_lock()
    assert held is not None
    try:
        assert la.take_lock() is None                       # второй процесс замок не получит
        assert la.main(['--apply', '--if-low']) == 0
        assert 'замок занят' in capsys.readouterr().out
        assert (src / 't-day').is_dir() and not (src / 't-day').is_symlink()
    finally:
        held.close()
    again = la.take_lock()
    assert again is not None                                # после отпускания — свободен
    again.close()


def test_hourly_units_exist_and_do_not_enable_themselves():
    root = Path(__file__).resolve().parents[3] / 'infra' / 'server' / 'dev-disk'
    svc, tmr = (root / 'remlab-logs-archive-hourly.service').read_text(encoding='utf-8'), (root / 'remlab-logs-archive-hourly.timer').read_text(encoding='utf-8')
    assert 'logs_archive.py --apply --digest --if-low' in svc and 'DISK_GUARD=0' in svc
    assert 'OnCalendar=*-*-* *:' in tmr and 'ВКЛЮЧАЕТ ТОЛЬКО ВЛАДЕЛЕЦ' in tmr
    assert 'WantedBy' in tmr and 'enable' in tmr            # включение описано в комментарии, само не включается
    night = (root / 'remlab-logs-archive.timer').read_text(encoding='utf-8')
    assert '01:10:00' in night                              # ночной таймер не тронут


# ───────────── T-20261124-67: что держит папку — код и живой прогон, не память; удаление со второго диска ─────────────
def _commit(repo, msg='z'):
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.email=a@b', '-c', 'user.name=t', 'commit', '-qm', msg], check=True)


def _scoped(world):
    src, dst, repo, r = world
    (repo / '.memory_bank' / 'plans').mkdir(parents=True)
    (repo / '.memory_bank' / '_intake').mkdir()
    (repo / 'tools').mkdir()
    (repo / '.memory_bank' / '_intake' / 'brief.md').write_text('вход — remlab-logs/mem-only-1, ещё раз mem-only-1; и mem-only-2\n')
    (repo / 'tools' / 'tool.py').write_text("IN = '~/remlab-logs/code-ref-1/in.json'\n")
    _commit(repo)
    r = dict(r, refs_scope=['tools', '.github'], memory_paths=['.memory_bank'])
    return src, dst, repo, r


def test_memory_only_mention_moves_with_docs_note_but_code_ref_holds(world):
    src, dst, repo, r = _scoped(world)
    mk(src / 'mem-only-1', {'a': 100}, 9)                         # упомянута только в брифе памяти → переносится, пометка «в N доках»
    mk(src / 'mem-only-2', {'a': 100}, 9)
    mk(src / 'code-ref-1', {'a': 100}, 9)                         # имя в коде tools/ → держит
    mk(src / 'ref-1123', {'a': 100}, 9)                           # имя только в plan.md в КОРНЕ репо (вне refs_scope) → тоже не держит
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: '', live=lambda: {})
    assert names(todo) == ['mem-only-1', 'mem-only-2', 'ref-1123']
    docs = {c['name']: c['docs'] for c in todo}
    assert docs['mem-only-1'] == 1 and docs['ref-1123'] == 0     # «упомянута в N доках» — только справка
    assert 'ссылка в репозитории' in dict(skipped)['code-ref-1']
    r2 = {k: v for k, v in r.items() if k != 'refs_scope'}        # без refs_scope — прежнее поведение: держит и память
    todo, skipped = la.candidates(r2, str(repo), now=NOW, busy=lambda p: '', live=lambda: {})
    assert names(todo) == [] and {'mem-only-1', 'mem-only-2', 'code-ref-1', 'ref-1123'} <= set(dict(skipped))


def _fake_proc(tmp_path, src):
    """Заглушки процессов: 101 — прогон с путём в командной строке; 102 — прогон с `--rules файл` (out_root, base_root, glob, catalog внутри); 103 — держатель heavy-slot только в holder-файле."""
    proc = tmp_path / 'proc'
    for pid, args in {
        '101': ['python3', 'run.py', '--out', f'{src}/live-cmd/out'],
        '102': ['python3', 'tools/assets/loop5.py', f'--rules={tmp_path}/rules-live.json', '--all'],
        '104': ['bash', '-c', 'sleep 1'],
    }.items():
        (proc / pid).mkdir(parents=True)
        (proc / pid / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in args) + b'\0')
    (proc / '103').mkdir()
    (tmp_path / 'rules-live.json').write_text('{"out_root": "%s/live-out/r1", "base_root": "~/nonexistent-home-zz/x", "shard_inputs_glob": "%s/shard*/inputs/*.json", '
                                              '"catalog": "%s/live-cat/c.json", "parts_root": "%s/live-nest/p", "note": "x"}' % (src, src, src, src))
    (tmp_path / 'inner.json').write_text('{"deep": "%s/live-deep/z"}' % src)                          # файл, на который ссылается файл из командной строки (вложенность)
    (tmp_path / 'rules-live.json').write_text((tmp_path / 'rules-live.json').read_text().replace('"note": "x"', '"inputs": "%s/inner.json"' % tmp_path))
    hd = tmp_path / 'heavy'
    hd.mkdir()
    (hd / 'holder').write_text(f'label=t-live\npid=103\ncmd=python3 -I stage.py --inputs {src}/live-holder/in.json\nprio=1\n')
    (hd / 'holder9').write_text(f'label=dead\npid=999999\ncmd=python3 x.py {src}/dead-holder/a\n')   # держатель мёртв (нет /proc/999999) — не держит
    return proc, hd


def test_live_refs_cmdline_rules_file_nested_glob_and_holder(tmp_path):
    src = tmp_path / 'logs'
    src.mkdir()
    proc, hd = _fake_proc(tmp_path, src)
    live = la.live_refs(str(src), proc_root=str(proc), heavy_dir=str(hd))
    for n in ('live-cmd', 'live-out', 'live-cat', 'live-nest', 'live-deep', 'live-holder'):
        assert la.hold_of(n, live), n                                  # путь из командной строки / из --rules / из вложенного файла / из holder heavy-slot
    assert la.hold_of('shard-01', live) and la.hold_of('shard9', live)   # шаблон `shard*` держит все совпавшие
    assert not la.hold_of('dead-holder', live) and not la.hold_of('unrelated', live)
    assert 'командная строка' in live['live-cmd'] and 'rules-live.json' in live['live-out'] and 'inner.json' in live['live-deep'] and 'heavy-slot' in live['live-holder']


def test_live_runs_hold_their_dirs_in_candidates_and_move_one(world, tmp_path):
    src, dst, repo, r = world
    proc, hd = _fake_proc(tmp_path, src)
    live = lambda: la.live_refs(str(src), proc_root=str(proc), heavy_dir=str(hd))
    for n in ('live-cmd', 'live-out', 'live-deep', 'live-holder', 'shard-77', 'free-old'):
        mk(src / n, {'a': 100}, 9)
    todo, skipped = la.candidates(r, str(repo), now=NOW, busy=lambda p: '', live=live)
    assert names(todo) == ['free-old']                                # остальные — вход/выход живого прогона
    sk = dict(skipped)
    assert all('живого прогона' in sk[n] for n in ('live-cmd', 'live-out', 'live-deep', 'live-holder', 'shard-77'))
    c = {'name': 'live-out', 'path': str(src / 'live-out'), 'total': 100, 'freed': 100}          # процесс взял папку между списком и переносом
    ok, line = la.move_one(c, dict(r, days=5), now=NOW, busy=lambda p: '', live=live)
    assert not ok and 'живого прогона' in line and (src / 'live-out').is_dir() and not (src / 'live-out').is_symlink()


def _old_link(src, dst, name, days=20):
    """Папка уже на HDD (файлы старше), на основном диске — ссылка, созданная `days` суток назад."""
    mk(dst / name, {'a.bin': 1000, 'b/c.bin': 500}, days)
    os.symlink(dst / name, src / name)
    t = NOW - days * DAY
    os.utime(src / name, (t, t), follow_symlinks=False)


def _hdd_world(world):
    src, dst, repo, r = _scoped(world)
    (repo / 'tools' / 'tool2.py').write_text("X = 'hdd-code'\n")
    (repo / '.memory_bank' / 'plans' / 'live-plan.md').write_text('---\nstatus: in_progress\n---\nвход — hdd-plan-act\n')
    (repo / '.memory_bank' / 'plans' / 'old-plan.md').write_text('---\nstatus: completed\n---\nбыл вход — hdd-plan-done\n')
    (repo / '.memory_bank' / 'plans' / 'nostatus.md').write_text('вход — hdd-plan-nostatus\n')
    _commit(repo, 'h')
    dst.mkdir(exist_ok=True)
    for n in ('hdd-free', 'hdd-code', 'hdd-plan-act', 'hdd-plan-done', 'hdd-plan-nostatus', 'hdd-live'):
        _old_link(src, dst, n)
    _old_link(src, dst, 'hdd-young', 3)                                # лежит 3 суток — рано
    mk(dst / 'hdd-touched', {'a': 10}, 20)                             # давно лежит, но внутри свежий файл
    (dst / 'hdd-touched' / 'new.bin').write_bytes(b'y')
    os.symlink(dst / 'hdd-touched', src / 'hdd-touched')
    os.utime(src / 'hdd-touched', (NOW - 20 * DAY,) * 2, follow_symlinks=False)
    return src, dst, repo, dict(r, hdd_prune={'days': 14})


def test_hdd_prune_list_excludes_code_live_active_plans_and_young(world):
    src, dst, repo, r = _hdd_world(world)
    todo, skipped = la.hdd_candidates(r, str(repo), now=NOW, live=lambda: {'hdd-live': 'pid 1: x'})
    assert names(todo) == ['hdd-free', 'hdd-plan-done']                # завершённый план не держит; действующий и без status — держат
    sk = dict(skipped)
    assert 'код' in sk['hdd-code'] and 'живого прогона' in sk['hdd-live'] and 'live-plan.md' in sk['hdd-plan-act'] and 'nostatus.md' in sk['hdd-plan-nostatus']
    assert 'меньше' in sk['hdd-young'] and 'менялась' in sk['hdd-touched']
    assert all(c['total'] == 1500 and c['age_d'] >= 19 for c in todo)
    assert all((dst / n).is_dir() for n in sk)                          # список сухой — ничего не удалено


def test_hdd_prune_one_removes_dir_and_dangling_link_only_inside_dst(world, tmp_path):
    src, dst, repo, r = _hdd_world(world)
    todo, _ = la.hdd_candidates(r, str(repo), now=NOW, live=lambda: {})
    c = next(x for x in todo if x['name'] == 'hdd-free')
    ok, line = la.prune_one(c, r, now=NOW, live=lambda: {})
    assert ok and 'удалено' in line and not (dst / 'hdd-free').exists() and not os.path.lexists(src / 'hdd-free')    # папка и висячая ссылка убраны
    other = tmp_path / 'elsewhere'
    mk(other, {'a': 1}, 30)                                           # вне dst — не трогаем
    ok, line = la.prune_one({'name': 'elsewhere', 'path': str(other), 'total': 1}, r, now=NOW, live=lambda: {})
    assert not ok and other.is_dir() and 'не папка прямо в' in line
    c2 = next(x for x in todo if x['name'] == 'hdd-plan-done')
    ok, line = la.prune_one(c2, r, now=NOW, live=lambda: {'hdd-plan-done': 'pid 7: x'})      # стала живой — пропуск
    assert not ok and (dst / 'hdd-plan-done').is_dir() and os.path.islink(src / 'hdd-plan-done')


def test_main_prune_hdd_dry_by_default_and_apply_needs_flag(world, monkeypatch, capsys, tmp_path):
    src, dst, repo, r = _hdd_world(world)
    rules = tmp_path / 'rules2.json'
    import json as _j
    rules.write_text(_j.dumps({'archive': {**{k: v for k, v in r.items()}, 'src': str(src), 'dst': str(dst)}}))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules))
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setenv('LOGS_ARCHIVE_LOCK', str(tmp_path / 'lock'))
    monkeypatch.setenv('HEAVY_SLOT_DIR', str(tmp_path / 'noheavy'))
    monkeypatch.setattr(la, 'busy_by', lambda p, proc_root='/proc': '')
    monkeypatch.setattr(la, 'live_refs', lambda src, proc_root='/proc', heavy_dir=None: {'hdd-live': 'pid 1'})
    monkeypatch.setattr(la, 'free_gb', lambda p: 100.0)
    assert la.main([]) == 0
    out = capsys.readouterr().out
    assert 'удалил бы hdd-free' in out and 'удалил бы hdd-plan-done' in out and 'сухо — удалил бы' in out
    assert (dst / 'hdd-free').is_dir()                                 # сухо: ничего не удалено
    assert la.main(['--apply', '--digest']) == 0                       # обычный перенос --apply на HDD ничего не удаляет
    capsys.readouterr()
    assert (dst / 'hdd-free').is_dir() and (dst / 'hdd-plan-done').is_dir()
    assert la.main(['--prune-hdd', '--apply', '--digest']) == 0
    out = capsys.readouterr().out
    assert 'DIGEST:логи на HDD: удалено 2 из 2' in out
    assert not (dst / 'hdd-free').exists() and not (dst / 'hdd-plan-done').exists() and not os.path.lexists(src / 'hdd-free')
    for n in ('hdd-code', 'hdd-plan-act', 'hdd-plan-nostatus', 'hdd-live', 'hdd-young', 'hdd-touched'):
        assert (dst / n).is_dir() and os.path.islink(src / n), n


def test_rules_file_has_scope_and_hdd_prune():
    import json as _j
    a = _j.load(open(os.path.join(os.path.dirname(la.__file__), '..', 'scout', 'rules', 'dev-disk.json'), encoding='utf-8'))['archive']
    assert {'tools', 'app', 'lib', '.github'} <= set(a['refs_scope']) and '.memory_bank' not in a['refs_scope'] and a['hdd_prune']['days'] == 14


# --- T-20261125-75/2: ~/remlab-inputs (входы наборов) скрипт не трогает никогда -------------------------------------------------------------------

@pytest.fixture
def inputs_dir(tmp_path, monkeypatch):
    d = tmp_path / 'remlab-inputs'
    mk(d / 'set29', {'photo/a.png': 100, 'MANIFEST.tsv': 50}, 30)           # старше любого порога: без защиты ушла бы первой
    monkeypatch.setattr(la, 'PROTECTED_DEFAULT', [str(d)])
    return d


def test_protected_by_matches_inside_equal_and_parent(world, inputs_dir, tmp_path):
    src, dst, repo, r = world
    real = os.path.realpath(inputs_dir)
    assert la.protected_by(str(inputs_dir / 'set29' / 'photo' / 'a.png'), r) == real
    assert la.protected_by(str(inputs_dir), r) == real
    assert la.protected_by(str(tmp_path), r) == real                        # родитель содержит защищённую папку — тоже нельзя
    assert la.protected_by(str(src), r) == '' and la.protected_by(str(dst), r) == ''
    link = tmp_path / 'via-link'
    link.symlink_to(inputs_dir)
    assert la.protected_by(str(link / 'set29'), r) == real                  # через ссылку — по realpath
    assert la.protected_by(str(src / 'x'), dict(r, protected=[str(src)])) == os.path.realpath(src)   # правило archive.protected добавляет папки


def test_protected_inputs_are_skipped_by_candidates_hdd_candidates_move_and_prune(world, inputs_dir):
    src, dst, repo, r = world
    r1 = dict(r, src=str(inputs_dir))
    todo, skipped = la.candidates(r1, str(repo), now=NOW, busy=lambda p: '', live=lambda: {}, refs=lambda names, repo: set())
    assert todo == [] and any('защищено' in why for _, why in skipped)       # папка набора не кандидат на перенос
    ok, line = la.move_one({'name': 'set29', 'path': str(inputs_dir / 'set29'), 'total': 1, 'freed': 1}, dict(r1, days=5), now=NOW, busy=lambda p: '', live=lambda: {})
    assert not ok and 'защищено' in line and (inputs_dir / 'set29' / 'photo' / 'a.png').is_file() and not (inputs_dir / 'set29').is_symlink()
    r2 = dict(r, dst=str(inputs_dir))
    todo, skipped = la.hdd_candidates(r2, str(repo), now=NOW, refs=lambda names, repo: set(), live=lambda: {}, plans=lambda names, repo: {})
    assert todo == [] and any('защищено' in why for _, why in skipped)       # и не кандидат на удаление с «HDD»
    ok, line = la.prune_one({'name': 'set29', 'path': str(inputs_dir / 'set29'), 'total': 1}, r2, now=NOW, live=lambda: {})
    assert not ok and 'защищено' in line and (inputs_dir / 'set29' / 'MANIFEST.tsv').is_file()


def test_main_refuses_src_or_dst_that_is_protected(world, inputs_dir, monkeypatch, tmp_path, capsys):
    src, dst, repo, r = world
    import json as _j
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setenv('LOGS_ARCHIVE_LOCK', str(tmp_path / 'lock'))
    monkeypatch.setattr(la, 'free_gb', lambda p: 100.0)
    for bad in ({'src': str(inputs_dir), 'dst': str(dst)}, {'src': str(src), 'dst': str(inputs_dir)}, {'src': str(inputs_dir / 'set29'), 'dst': str(dst)}):
        rules = tmp_path / 'rules-bad.json'
        rules.write_text(_j.dumps({'archive': {**r, **bad, 'days': 0}}))
        monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules))
        for args in ([], ['--apply', '--digest'], ['--prune-hdd', '--apply', '--digest'], ['--worktrees']):
            assert la.main(args) == 2, (bad, args)
            assert 'отказ' in capsys.readouterr().err
    assert (inputs_dir / 'set29' / 'photo' / 'a.png').is_file() and (inputs_dir / 'set29' / 'MANIFEST.tsv').is_file() and not dst.exists()


def test_rules_default_protected_cannot_be_switched_off_and_file_names_it(tmp_path, monkeypatch):
    import json as _j
    monkeypatch.setattr(la, 'PROTECTED_DEFAULT', ['~/remlab-inputs'])
    p = tmp_path / 'r.json'
    p.write_text(_j.dumps({'archive': {'protected': []}}))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(p))
    assert la.rules()['protected'] == ['~/remlab-inputs']                  # пустой список в правиле защиту не снимает
    p.write_text(_j.dumps({'archive': {'protected': ['~/other-keep']}}))
    assert la.rules()['protected'] == ['~/remlab-inputs', '~/other-keep']
    a = _j.load(open(os.path.join(os.path.dirname(la.__file__), '..', 'scout', 'rules', 'dev-disk.json'), encoding='utf-8'))['archive']
    assert '~/remlab-inputs' in a['protected']


# ───────────── забытые ждуны и серверы не держат ПЕРЕНОС (T-20261126-96/1; владелец TG 3006→3008, решение Fable 26.11) ─────────────
WAIT_LOOP = ['bash', '-c', 'cd {d}; while [ ! -f {d}/ALLDONE ]; do sleep 20; done; ls {d}/res_*.json | wc -l; TZ=Europe/London date +%H:%M']


@pytest.fixture
def stale_env(monkeypatch):
    monkeypatch.setattr(la, 'STALE_NOTES', [])
    monkeypatch.setattr(la, 'MONITOR_MAX_H', None)


def _fp(root, pid, args, age_h=None, ppid=0, cwd=None):
    """Подделка /proc/<pid>: cmdline, stat (ppid и starttime при age_h; btime = now − 1000 ч), cwd."""
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in args) + b'\0')
    (root / 'stat').write_text(f'cpu 1 2 3\nbtime {int(time.time()) - 1000 * 3600}\n')
    start = int((1000 - age_h) * 3600 * 100) if age_h is not None else 0
    (d / 'stat').write_text(f'{pid} ({os.path.basename(args[0])}) S {ppid} ' + ' '.join(['0'] * 17) + f' {start} 0 0\n')
    (d / 'fd').mkdir(exist_ok=True)
    if cwd:
        os.symlink(cwd, d / 'cwd')


def _world_proc(tmp_path):
    folder = tmp_path / 'logs' / 't2102-1124'
    folder.mkdir(parents=True)
    proc = tmp_path / 'proc'
    proc.mkdir()
    hd = tmp_path / 'heavy'
    hd.mkdir()
    return folder, proc, hd


def test_stale_waiter_over_12h_does_not_hold_but_only_when_threshold_given(tmp_path, stale_env):
    folder, proc, hd = _world_proc(tmp_path)
    _fp(proc, 100, [a.format(d=folder) for a in WAIT_LOOP], age_h=60, cwd=str(folder))
    _fp(proc, 101, ['sleep', '20'], age_h=0.001, ppid=100, cwd=str(folder))                  # `sleep 20` из цикла: cwd тот же, возраст секунды
    assert 'pid 10' in la.busy_by(str(folder), proc_root=str(proc), heavy_dir=str(hd))         # порога нет (правило выключено) — держит, как раньше
    assert la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd)) == ''   # ждун >12 ч и его sleep — не держат
    assert len(la.STALE_NOTES) == 1 and 'забытый ждун/сервер — не держит: pid 100 (60 ч, ждун)' in la.STALE_NOTES[0] and 'bash -c' in la.STALE_NOTES[0]
    assert '100' in str(la.stale_waiters(['100', '101'], str(proc), 12, str(hd))) and len(la.STALE_NOTES) == 1   # строка — один раз на pid; процесс не убит
    assert (proc / '100').is_dir()


def test_stale_waiter_under_12h_still_holds(tmp_path, stale_env):
    folder, proc, hd = _world_proc(tmp_path)
    _fp(proc, 100, [a.format(d=folder) for a in WAIT_LOOP], age_h=5, cwd=str(folder))
    assert 'pid 100' in la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))
    assert la.STALE_NOTES == []
    _fp(proc, 102, [a.format(d=folder) for a in WAIT_LOOP], cwd=str(folder))                  # возраст не прочитать — считаем свежим
    assert 'pid 10' in la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))


@pytest.mark.parametrize('line', [
    'cd {d}; while true; do python3 job.py {d}/x; sleep 20; done',                               # тяжёлое внутри цикла
    'while [ ! -f {d}/a ]; do node build.js; sleep 5; done',
    'while [ ! -f {d}/a ]; do sleep 5; done; rm -rf {d}/tmp',                                    # после цикла — удаление
    'while [ ! -f {d}/a ]; do sleep 5; done > {d}/wait.log',                                     # пишет в файл папки
    'until grep -q ok {d}/r.log; do sleep 5; done && python3 -I stage.py',
    'while [ ! -f {d}/a ]; do sleep 5; done; $(python3 x.py)',
    'sleep 99999',                                                                                # нет цикла: это не ждун по правилу
])
def test_loop_with_heavy_or_writes_is_not_a_waiter_and_keeps_holding(tmp_path, stale_env, line):
    folder, proc, hd = _world_proc(tmp_path)
    _fp(proc, 100, ['bash', '-c', line.format(d=folder)], age_h=60, cwd=str(folder))
    assert la.is_wait_cmd(['bash', '-c', line.format(d=folder)]) == ''
    assert 'pid 100' in la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))
    assert la.STALE_NOTES == []


@pytest.mark.parametrize('args,expected', [
    (['bash', '-c', "cd /x; until [ $(grep -c '^[a-z0-9]*2 {' /x/a.log) -ge 5 ] || ! pgrep -f grain3.py >/dev/null 2>&1; do sleep 15; done; grep -v '^    ' /x/a.log | cut -c1-300; date"], 'ждун'),
    (['bash', '-c', 'while [ ! -f /x/ALLDONE ]; do sleep 20; done; ls /x/res_*.json | wc -l'], 'ждун'),
    (['timeout', '3600', 'bash', '-c', 'until [ -f /x/a ]; do sleep 2; done'], 'ждун'),
    (['bash', '-lc', 'F=~/remlab-logs/t168/b.out; touch $F; N=$(wc -l < $F); while true; do L=$(wc -l < $F); if [ "$L" -gt "$N" ]; then tail -n +$((N+1)) $F | cut -c1-420 | sed "s/^/R10: /"; N=$L; fi; sleep 60; done'], 'ждун'),
    (['bash', '-lc', 'D=~/x; while true; do for f in $D/*/yaw.txt; do [ -f "$f" ] || continue; echo $f; done; sleep 30; done'], 'ждун'),
    (['bash', '-lc', 'L=/x; while true; do [ -f $L/a.done ] && echo "done: $(wc -l < $L/a.tsv)" && break; sleep 120; done'], 'ждун'),
    (['bash', '-lc', 'F=/x/b.out; while true; do sed -i s/a/b/ $F; sleep 5; done'], ''),                 # sed -i пишет
    (['bash', '-lc', 'D=/x; while true; do k=$(basename $(dirname $D)); sleep 5; done'], 'ждун'),         # вложенные $(…) раскрываются изнутри: всё лёгкое
    (['bash', '-lc', 'D=/x; while true; do k=$(python3 x.py $(dirname $D)); sleep 5; done'], ''),        # тяжёлое в подстановке — не ждун
    (['bash', '-lc', 'while true; do case "$a" in *x*) ;; esac; sleep 5; done'], ''),                     # case — не разбираем
    (['python3', '-m', 'http.server', '8000'], 'сервер'),
    (['python3', '-u', '-m', 'http.server', '--directory', '/x'], 'сервер'),
    (['python3', '-m', 'http.server', '--cgi'], ''),                                              # --cgi исполняет скрипты
    (['python3', '-m', 'pytest'], ''),
    (['bash', '-c', 'while [ ! -f /x/a ]; do tail -F /x/b.log; done'], ''),                         # tail -F внутри цикла — не ожидание файла
    (['bash', '-c', 'while [ ! -f /x/a ]; do sleep 1; done; mv /x/a /y'], ''),
    (['bash', '-c', 'echo "ждём"; sleep 5'], ''),                                                  # без while/until
    (['ssh', 'host', 'while true; do sleep 1; done'], ''),
    ([], ''),
])
def test_is_wait_cmd(args, expected):
    assert la.is_wait_cmd(args) == expected


def test_stale_http_server_does_not_hold(tmp_path, stale_env):
    folder, proc, hd = _world_proc(tmp_path)
    _fp(proc, 200, ['python3', '-m', 'http.server', '8765'], age_h=62, cwd=str(folder))
    assert 'pid 200' in la.busy_by(str(folder), proc_root=str(proc), heavy_dir=str(hd))
    assert la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd)) == ''
    assert 'pid 200 (62 ч, сервер)' in la.STALE_NOTES[0]
    _fp(proc, 201, ['python3', '-m', 'http.server', '8766'], age_h=2, cwd=str(folder))
    assert 'pid 201' in la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))   # свежий сервер держит


def test_heavy_slot_holder_always_holds_even_if_it_looks_like_a_stale_waiter(tmp_path, stale_env):
    folder, proc, hd = _world_proc(tmp_path)
    loop = [a.format(d=folder) for a in WAIT_LOOP]
    _fp(proc, 300, loop, age_h=90, cwd=str(folder))
    (hd / 'holder').write_text(f'label=t-wait\npid=300\ncmd=bash -c sleep\nprio=1\n')              # он сам держит слот
    assert 'pid 300' in la.busy_by(str(folder), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))
    assert la.STALE_NOTES == []
    folder2 = tmp_path / 'logs' / 't2'
    folder2.mkdir()
    _fp(proc, 310, ['heavy-slot.sh', 't-job', '--', 'x'], age_h=90)                                # предок держит слот, ждун — его потомок
    (hd / 'holder2').write_text('label=t-job\npid=310\ncmd=heavy-slot.sh t-job -- x\nprio=1\n')
    _fp(proc, 311, [a.format(d=folder2) for a in WAIT_LOOP], age_h=90, ppid=310, cwd=str(folder2))
    assert 'pid 311' in la.busy_by(str(folder2), proc_root=str(proc), stale_h=12, heavy_dir=str(hd))


def test_transfer_relaxes_but_prune_and_worktree_prune_keep_holding(world, tmp_path, stale_env, monkeypatch):
    src, dst, repo, r = world
    folder, proc, hd = _world_proc(tmp_path)
    mk(src / 'wait-1', {'a': 100}, 9)
    mk(src / 'free-old', {'a': 100}, 9)
    _fp(proc, 100, ['bash', '-c', f'while [ ! -f {src}/wait-1/ALLDONE ]; do sleep 20; done'], age_h=60, cwd=str(src / 'wait-1'))
    orig_busy, orig_live = la.busy_by, la.live_refs
    monkeypatch.setattr(la, 'busy_by', lambda p, **kw: orig_busy(p, proc_root=str(proc), heavy_dir=str(hd), **kw))
    monkeypatch.setattr(la, 'live_refs', lambda s, **kw: orig_live(s, proc_root=str(proc), heavy_dir=str(hd), **kw))
    todo, skipped = la.candidates(r, str(repo), now=NOW)                                         # в правилах порога нет — держит, как раньше
    assert names(todo) == ['free-old'] and 'живого прогона' in dict(skipped)['wait-1']
    todo, skipped = la.candidates(dict(r, stale_holder_hours=12), str(repo), now=NOW)             # порог есть — перенос свободен
    assert names(todo) == ['free-old', 'wait-1'] and la.STALE_NOTES
    c = {'name': 'wait-1', 'path': str(src / 'wait-1'), 'total': 100, 'freed': 100}
    ok, line = la.move_one(c, dict(r, days=5, stale_holder_hours=12), now=NOW, rsync=lambda cm: 0)   # и move_one перепроверяет с тем же послаблением
    assert 'занята' not in line and 'живого прогона' not in line
    # удаление с HDD: тот же ждун держит папку, как раньше (послабление — только для переноса)
    assert 'wait-1' in orig_live(str(src), proc_root=str(proc), heavy_dir=str(hd))
    assert 'wait-1' not in orig_live(str(src), proc_root=str(proc), heavy_dir=str(hd), stale_h=12)
    dst.mkdir(exist_ok=True)
    _old_link(src, dst, 'hdd-wait')
    _fp(proc, 101, ['bash', '-c', f'until [ -f {src}/hdd-wait/OK ]; do sleep 5; done'], age_h=70, cwd=str(tmp_path))
    hp, hs = la.hdd_candidates(dict(r, hdd_prune={'days': 14}, stale_holder_hours=12), str(repo), now=NOW)
    assert 'hdd-wait' not in names(hp) and 'живого прогона' in dict(hs)['hdd-wait']
    # worktree_prune держит так же (stale_h он не передаёт)
    snap = la.proc_snapshot(str(proc), None, holders=True, heavy_dir=str(hd))
    assert any(e['pid'] == '101' for e in snap)


def test_main_prints_stale_line_and_digest_and_does_not_kill(world, tmp_path, stale_env, monkeypatch, capsys):
    src, dst, repo, r = world
    folder, proc, hd = _world_proc(tmp_path)
    mk(src / 'wait-2', {'a': 100}, 9)
    _fp(proc, 100, ['bash', '-c', f'while [ ! -f {src}/wait-2/ALLDONE ]; do sleep 20; done'], age_h=60, cwd=str(src / 'wait-2'))
    orig_busy, orig_live = la.busy_by, la.live_refs
    monkeypatch.setattr(la, 'busy_by', lambda p, **kw: orig_busy(p, proc_root=str(proc), heavy_dir=str(hd), **kw))
    monkeypatch.setattr(la, 'live_refs', lambda s, **kw: orig_live(s, proc_root=str(proc), heavy_dir=str(hd), **kw))
    import json as _j
    rules_file = tmp_path / 'rules.json'
    rules_file.write_text(_j.dumps({'archive': {'src': str(src), 'dst': str(dst), 'days': 5, 'min_hdd_free_gb': 0, 'stale_holder_hours': 12}}))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(rules_file))
    monkeypatch.setenv('LOGS_ARCHIVE_REPO', str(repo))
    monkeypatch.setattr(la, 'take_lock', lambda: object())
    monkeypatch.setattr(la, 'move_one', lambda c, rr, **kw: (True, f'{c["name"]}: ok'))
    monkeypatch.setattr(la, 'hdd_candidates', lambda *a, **k: ([], []))
    monkeypatch.setattr(la, 'free_gb', lambda p: 100.0)
    assert la.main(['--apply', '--digest']) == 0
    out = capsys.readouterr().out
    assert 'wait-2' in out and 'забытый ждун/сервер — не держит: pid 100 (60 ч, ждун)' in out
    assert any(ln.startswith('DIGEST:забытый ждун/сервер — не держит: pid 100') for ln in out.splitlines())
    assert (proc / '100' / 'cmdline').exists()                                                    # процесс не тронут


def test_rules_file_has_stale_holder_hours_and_default_is_off(tmp_path, monkeypatch):
    import json as _j
    a = _j.load(open(os.path.join(os.path.dirname(la.__file__), '..', 'scout', 'rules', 'dev-disk.json'), encoding='utf-8'))['archive']
    assert a['stale_holder_hours'] == 12 and a['monitor_max_h'] == 12
    p = tmp_path / 'r.json'
    p.write_text(_j.dumps({'archive': {}}))
    monkeypatch.setenv('LOGS_ARCHIVE_RULES', str(p))
    assert la.rules()['stale_holder_hours'] is None                                              # нет ключа — выключено, держит как раньше
