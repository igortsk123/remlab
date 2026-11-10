"""Тесты уборки диска DEV второго круга `tools/ops/disk_clean.py` — только на временной папке и подставных данных.

Настоящие данные, docker и база не трогаются: база и docker — подставными функциями, git — настоящий, но в своём временном репо.
Запуск: `python -m pytest tools/ops/tests/test_disk_clean.py -q`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import disk_clean as dc  # noqa: E402

OLD = time.time() - 30 * 86400
NOREFS = ([], [])


def age(path, t=OLD):
    for dp, dn, fn in os.walk(path, topdown=False):
        for n in fn:
            os.utime(os.path.join(dp, n), (t, t), follow_symlinks=False)
        os.utime(dp, (t, t))


def mk(p: Path, body=b'x' * 5000):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('DISK_CLEAN_HOME', str(tmp_path))
    return tmp_path


def git(*a, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
    subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture()
def repo(home):
    r = home / 'igor' / 'remlab'
    r.mkdir(parents=True)
    git('init', '-q', '-b', 'main', cwd=r)
    mk(r / 'a.txt')
    git('add', '.', cwd=r)
    git('commit', '-qm', 'init', cwd=r)
    wt = r / '.claude' / 'worktrees'
    for name in ('merged', 'unmerged', 'dirty', 'untracked', 'fresh', 'picked', 'busy'):
        git('worktree', 'add', '-q', '-b', f'worktree-{name}', str(wt / name), cwd=r)
    git('commit', '-q', '--allow-empty', '-m', 'своё', cwd=wt / 'unmerged')
    mk(wt / 'picked' / 'p.txt')                               # коммит ветки перенесён в main cherry-pick'ом
    git('add', '.', cwd=wt / 'picked')
    git('commit', '-qm', 'перенос', cwd=wt / 'picked')
    git('cherry-pick', 'worktree-picked', cwd=r)
    mk(wt / 'dirty' / 'a.txt', b'changed')
    mk(wt / 'untracked' / 'draft.md')
    for name in ('merged', 'unmerged', 'dirty', 'untracked', 'picked', 'busy'):
        age(wt / name)
    return r


RULE_WT = {'id': 'worktrees', 'kind': 'worktree', 'repo': '~/igor/remlab', 'dir': '.claude/worktrees', 'main': 'main', 'idle_h': 48}


def test_worktree_only_merged_clean_idle(repo):
    busy = str(repo / '.claude' / 'worktrees' / 'busy')
    items, kept = dc.rule_worktree(RULE_WT, ([busy + '/sub'], []), time.time())
    got = {os.path.basename(i['target']) for i in items}
    assert got == {'merged', 'picked'}, got
    why = {os.path.basename(t): w for t, w in kept}
    assert 'не влита' in why['unmerged'] and '1 коммитов' in why['unmerged']
    assert 'незакоммиченное' in why['dirty']
    assert 'незакоммиченное' in why['untracked'], 'неотслеживаемый черновик держит копию'
    assert 'менялась' in why['fresh']
    assert why['busy'] == 'в ней работает процесс'
    assert all(i['act'][0] == 'git-wt' for i in items)


def test_worktree_node_modules_link(repo, home):
    """Ссылка node_modules → основная копия: не «правка»; при удалении снимается ссылка, цель цела."""
    target = home / 'shared-nm'
    mk(target / 'pkg' / 'index.js')
    wt = repo / '.claude' / 'worktrees'
    git('worktree', 'add', '-q', '-b', 'worktree-linked', str(wt / 'linked'), cwd=repo)
    os.symlink(target, wt / 'linked' / 'node_modules')
    age(wt / 'linked')
    os.utime(wt / 'linked' / 'node_modules', (OLD, OLD), follow_symlinks=False)
    rule = dict(RULE_WT, untracked_links=['node_modules'])
    items, kept = dc.rule_worktree(rule, NOREFS, time.time())
    it = next(i for i in items if i['target'].endswith('linked'))
    assert it['act'][3:] == [str(wt / 'linked' / 'node_modules')]
    items2, kept2 = dc.rule_worktree(RULE_WT, NOREFS, time.time())   # без untracked_links — та же ссылка держит копию
    assert 'незакоммиченное' in dict((os.path.basename(t), w) for t, w in kept2)['linked']
    freed, err = dc.remove(it, {})
    assert err is None and not (wt / 'linked').exists() and (target / 'pkg' / 'index.js').exists()


def test_worktree_keep_and_locked(repo):
    git('worktree', 'lock', str(repo / '.claude' / 'worktrees' / 'picked'), cwd=repo)
    busy = str(repo / '.claude' / 'worktrees' / 'busy')
    items, kept = dc.rule_worktree(dict(RULE_WT, keep=['merged']), ([busy], []), time.time())
    assert not items
    why = {os.path.basename(t): w for t, w in kept}
    assert why['merged'] == 'в списке keep' and why['picked'] == 'locked'


def test_worktree_remove_keeps_branch(repo):
    items, _ = dc.rule_worktree(RULE_WT, NOREFS, time.time())
    it = next(i for i in items if i['target'].endswith('merged'))
    freed, err = dc.remove(it, {})
    assert err is None and not os.path.exists(it['target'])
    out = subprocess.run(['git', 'branch', '--list', 'worktree-merged'], cwd=repo, capture_output=True, text=True).stdout
    assert 'worktree-merged' in out, 'ветка остаётся'


def test_worktree_remove_refuses_dirty(repo):
    p = str(repo / '.claude' / 'worktrees' / 'dirty')
    freed, err = dc.remove({'rule': 'worktrees', 'target': p, 'bytes': 1, 'act': ['git-wt', str(repo), p]}, {})
    assert err and os.path.isdir(p), 'грязную копию git без --force не отдаёт, даже если кандидат подсунут'


def test_cache_dirs(home):
    old = home / 'remlab-logs' / 'floorplan-bench' / 'cache-t01'
    mk(old / 'an-1.pkl')
    age(old)
    new = home / 'remlab-logs' / 'floorplan-bench' / 'cache-t02'
    mk(new / 'an-2.pkl')
    held = home / 'remlab-logs' / 'floorplan-bench' / 'cache-t03'
    mk(held / 'an-3.pkl')
    age(held)
    keep = home / 'remlab-logs' / 'floorplan-bench' / 'inputs'
    mk(keep / 'A.jpg')
    age(keep)
    R = {'id': 'bench_cache', 'kind': 'cache_dirs', 'globs': ['~/remlab-logs/floorplan-bench/cache-*'], 'idle_days': 7}
    items, kept = dc.rule_cache_dirs(R, ([], [f'FP_CACHE={held} python bench.py']), time.time())
    assert [os.path.basename(i['target']) for i in items] == ['cache-t01']
    assert {os.path.basename(t) for t, _ in kept} == {'cache-t02', 'cache-t03'}
    assert items[0]['bytes'] > 0
    again, _ = dc.rule_cache_dirs(R, NOREFS, time.time())
    assert 'cache-t01' in {os.path.basename(i['target']) for i in again}, 'свой обход (atime папки) не делает кэш «свежим»'


def test_cache_read_recently_is_kept(home):
    p = home / 'c' / 'cache-x'
    f = mk(p / 'an.pkl')
    age(p)
    os.utime(f, (time.time(), OLD))     # читали сейчас, писали давно
    items, _ = dc.rule_cache_dirs({'id': 'c', 'globs': ['~/c/cache-*'], 'idle_days': 7}, NOREFS, time.time())
    assert not items


def mesh_tree(home):
    root = home / 'scout-scenes' / 'meshes-hunyuan' / 'meshes' / 'hunyuan21' / 'v2'
    gens = {}
    for sku, gs in {'112923_1': ['aaaa0001', 'aaaa0002', 'aaaa0003'], '112923_2': ['bbbb0001', 'bbbb0002'],
                    '112923_3': ['cccc0001'], '112923_4': ['dddd0001', 'dddd0002'], '112923_5': ['eeee0001', 'eeee0002']}.items():
        for k, g in enumerate(gs):
            d = root / sku / g
            for f in ('model.glb', 'shape.glb', 'input.png', 'cutout.png', 'source.jpg'):
                mk(d / f)
            mk(d / 'manifest.json', b'{}')
            mk(d / 'verdict.json', b'{}')
            age(d, OLD + k * 3600)       # последнее — самое свежее
            gens[g] = d
    mk(gens['bbbb0001'] / 'repair.json', b'{}')
    age(gens['bbbb0001'], OLD)
    return root, gens


def test_mesh_old_generations(home):
    root, gens = mesh_tree(home)
    mk(home / 'reg.json', json.dumps({'a': {'local_path': f'{root}/112923_5/eeee0001/model.glb'}}).encode())
    R = {'id': 'mesh_old_gen', 'root': '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2', 'min_age_days': 14,
         'heavy': ['*.glb', 'input.png', 'cutout.png', 'source.jpg'], 'keep_markers': ['repair.json'],
         'refs_sql': ['q1'], 'keep_sku_sql': ['q2'], 'refs_files': ['~/reg.json']}

    def db(sqls):
        if sqls == ['q1']:
            return [f'file://{root}/112923_1/aaaa0001/model.glb']
        return ['112923:4']          # товар в очереди переделки — sku в базе через двоеточие

    items, kept = dc.rule_mesh_generations(R, NOREFS, time.time(), db=db)
    got = {os.path.basename(i['target']) for i in items}
    assert got == {'aaaa0002'}, got
    why = {os.path.basename(t): w for t, w in kept}
    assert 'база' in why['aaaa0001'] and 'база' in why['eeee0001']
    assert why['bbbb0001'] == 'есть запись починки'
    assert why['dddd0001'] == 'товар в очереди переделки'
    assert 'cccc0001' not in why and 'aaaa0003' not in why, 'единственное и самое свежее — не кандидаты и не шум'
    it = items[0]
    assert {os.path.basename(f) for f in it['act'][2:]} == {'model.glb', 'shape.glb', 'input.png', 'cutout.png', 'source.jpg'}
    freed, err = dc.remove(it, {})
    assert err is None and freed > 0
    left = sorted(os.listdir(gens['aaaa0002']))
    assert left == ['manifest.json', 'verdict.json'], 'json-записи остаются'


def test_mesh_db_down_gives_nothing(home):
    mesh_tree(home)
    R = {'id': 'm', 'root': '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2', 'refs_sql': ['q'], 'keep_sku_sql': ['q']}
    items, kept = dc.rule_mesh_generations(R, NOREFS, time.time(), db=lambda s: None)
    assert not items and '(WARN)' in kept[0][1]


def test_mesh_young_generation_kept(home):
    root, gens = mesh_tree(home)
    os.utime(gens['aaaa0002'] / 'verdict.json')
    R = {'id': 'm', 'root': '~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2', 'min_age_days': 14}
    items, kept = dc.rule_mesh_generations(R, NOREFS, time.time(), db=lambda s: [])
    assert 'aaaa0002' not in {os.path.basename(i['target']) for i in items}
    assert 'aaaa0001' in {os.path.basename(i['target']) for i in items}


def test_docker_volumes_only_ours_and_old():
    now = time.time()
    d = {'ls': (0, 'v-ours-old\nv-ours-new\nv-foreign\nv-unknown\n'),
         'sizes': {'v-ours-old': 150 * 10 ** 6, 'v-ours-new': 10, 'v-foreign': 10 ** 9},
         'created': {'v-ours-old': now - 30 * 86400, 'v-ours-new': now - 86400, 'v-foreign': now - 90 * 86400},
         'owner': {'v-ours-old': 'наш', 'v-ours-new': 'наш', 'v-foreign': 'pg чужой'}}
    items, kept = dc.rule_docker_volumes({'id': 'pg_volumes', 'min_age_days': 7}, NOREFS, now, docker=d)
    assert [i['target'] for i in items] == ['том v-ours-old'] and items[0]['act'] == ['docker-vol', 'v-ours-old']
    assert len(kept) == 3 and any('не проверен' in w for _, w in kept)


def test_docker_containers():
    now = time.time()
    d = {'ps': (0, 't31-pg\texited\nt33-pg\trunning\nremlab-devdb\texited\ntamara-api\texited\nremlab-trial-pages-pg\texited\n'),
         'finished': {'t31-pg': now - 10 * 86400, 'remlab-trial-pages-pg': now - 86400}}
    R = {'id': 'pg_stands', 'name_re': r'^(t\d+[a-z]?-pg|remlab-[\w-]+-pg)$', 'never': ['remlab-devdb'], 'exited_days': 7}
    items, kept = dc.rule_docker_containers(R, NOREFS, now, docker=d)
    assert [i['target'] for i in items] == ['контейнер t31-pg']
    assert not any('tamara' in t for t, _ in kept), 'чужие имена даже не рассматриваются'


def test_forbidden_paths(home):
    for p in ('igor/remlab/.memory_bank/x', 'a/_secrets/b', 'a/.env.local'):
        assert dc.forbidden(str(home / p))
    assert not dc.forbidden(str(home / 'remlab-logs' / 'x'))
    p = home / 'igor' / 'remlab' / '.memory_bank' / 'cache-1'
    mk(p / 'f')
    freed, err = dc.remove({'rule': 'x', 'target': str(p), 'bytes': 1, 'act': ['rmtree', str(p)]}, {})
    assert err and p.exists()


def test_history_rate(tmp_path):
    now = time.time()
    (tmp_path / 'free.tsv').write_text(f'{now - 86400:.0f}\t{50 * dc.GB}\t0\n')
    rate = dc.history(str(tmp_path), 40 * dc.GB, 0, now)
    assert round(rate) == 10
    assert dc.history(str(tmp_path / 'none'), 1, 0, now, write=False) is None


def write_rules(home, approved):
    old = home / 'remlab-logs' / 'floorplan-bench' / 'cache-t01'
    mk(old / 'an.pkl')
    age(old)
    rules = {'log_dir': '~/remlab-logs/disk-clean', 'log_keep': 2, 'forecast_warn_days': 3,
             'rules': [{'id': 'bench_cache', 'kind': 'cache_dirs', 'approved': approved,
                        'globs': ['~/remlab-logs/floorplan-bench/cache-*'], 'idle_days': 7}]}
    p = home / 'rules.json'
    p.write_text(json.dumps(rules))
    return p, old


def run(home, rules, *args):
    env = dict(os.environ, DISK_CLEAN_HOME=str(home), DISK_CLEAN_RULES=str(rules))
    return subprocess.run([sys.executable, str(Path(dc.__file__)), *args], capture_output=True, text=True, env=env, timeout=120)


def test_main_dry_and_digest(home):
    rules, old = write_rules(home, approved=False)
    r = run(home, rules, '--digest')
    assert r.returncode == 0, r.stderr
    assert old.exists(), 'сухой прогон ничего не удаляет'
    assert 'уберу [bench_cache, ждёт одобрения]' in r.stdout
    assert 'DIGEST:диск-уборка (сухо, правила ждут одобрения)' in r.stdout and 'одобрено правил 0/1' in r.stdout
    logs = os.listdir(home / 'remlab-logs' / 'disk-clean')
    assert 'free.tsv' in logs and any(x.endswith('.log') for x in logs)


def test_main_apply_needs_approval(home):
    rules, old = write_rules(home, approved=False)
    run(home, rules, '--apply')
    assert old.exists(), '--apply без одобрения правила ничего не удаляет'
    rules, old = write_rules(home, approved=True)
    r = run(home, rules, '--apply', '--digest')
    assert r.returncode == 0 and not old.exists() and 'удаляю [bench_cache]' in r.stdout and 'убрано' in r.stdout


def test_log_rotation(home):
    rules, _ = write_rules(home, approved=False)
    d = home / 'remlab-logs' / 'disk-clean'
    d.mkdir(parents=True, exist_ok=True)
    for x in ('2026-01-01_000000.log', '2026-01-02_000000.log', '2026-01-03_000000.log', 'чужой.log'):
        (d / x).write_text('x')
    run(home, rules)
    left = sorted(os.listdir(d))
    assert '2026-01-01_000000.log' not in left and 'чужой.log' in left and len([x for x in left if x.startswith('2026-')]) == 2
