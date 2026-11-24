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
    assert r['worktrees_block'] is True and r['days'] == 5


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
