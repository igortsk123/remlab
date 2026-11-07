"""СОСТОЯНИЕ «CI gate» НА MAIN — по публичному API GitHub, без токена (T-20261107-41).

07.11 гейт был красным с 15:38 почти три часа и ~25 пушей подряд: падал один шаг, а следующие за ним шаги того же
job не исполнялись вовсе — никто не смотрел. Скрипт отвечает одной строкой «зелёный / красный: шаг X, коммит Y».

    bash tools/ops/ci-status.sh             # строка; код 0 — зелёный, 1 — красный, 2 — API не ответил
    bash tools/ops/ci-status.sh --digest    # ночь (refresh_daily): DIGEST-строка (красный — закреплённая DIGEST:! и WARN:ci_status); код 0
    python3 tools/ops/ci_status.py --selftest

Правило: берётся последний ЗАВЕРШЁННЫЙ прогон workflow «CI gate» на ветке (отменённый/пропущенный не решает — смотрим
следующий). Красный — с какого прогона подряд (первый красный после последнего зелёного) и сколько часов; упавшие шаги —
из `/runs/{id}/jobs` (job: шаг). Репозиторий — из `git remote get-url origin`, иначе igortsk123/remlab.
Подмена для проверок: CI_STATUS_FIXTURE=<папка> с runs.json и jobs-<id>.json вместо сети; CI_STATUS_NOW=<ISO> — «сейчас»."""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

API = 'https://api.github.com'
REPO_DEFAULT = 'igortsk123/remlab'
DECISIVE = {'success', 'failure', 'timed_out', 'startup_failure'}


def repo_of_remote(url: str) -> str:
    m = re.search(r'github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', (url or '').strip())
    return f'{m.group(1)}/{m.group(2)}' if m else REPO_DEFAULT


def repo_here() -> str:
    try:
        url = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=10,
                             cwd=os.path.dirname(os.path.abspath(__file__))).stdout
    except (OSError, subprocess.SubprocessError):
        url = ''
    return repo_of_remote(url)


def fetch(path: str):
    """GET API (или файл подмены). Исключение — наверх: «неизвестно»."""
    fx = os.environ.get('CI_STATUS_FIXTURE')
    if fx:
        m = re.search(r'/actions/runs/(\d+)/jobs', path)
        with open(os.path.join(fx, f'jobs-{m.group(1)}.json' if m else 'runs.json'), encoding='utf-8') as f:
            return json.load(f)
    req = urllib.request.Request(API + path, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'remlab-ci-status'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def verdict(runs: list, workflow: str = 'CI gate') -> dict:
    """Из списка прогонов (новые первыми, как отдаёт API): последний решающий, начало красной полосы."""
    rs = [r for r in runs if r.get('name') == workflow and r.get('status') == 'completed' and r.get('conclusion') in DECISIVE]
    rs.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    if not rs:
        return {'state': 'unknown', 'why': f'нет завершённых прогонов «{workflow}»'}
    last = rs[0]
    if last['conclusion'] == 'success':
        return {'state': 'green', 'last': last}
    first, closed = last, False
    for r in rs[1:]:
        if r['conclusion'] == 'success':
            closed = True
            break
        first = r
    return {'state': 'red', 'last': last, 'first': first, 'closed': closed, 'n': rs.index(first) + 1}


def failed_steps(jobs: dict) -> list:
    out = []
    for j in (jobs or {}).get('jobs') or []:
        if j.get('conclusion') not in ('failure', 'timed_out'):
            continue
        bad = [s.get('name', '?') for s in j.get('steps') or [] if s.get('conclusion') in ('failure', 'timed_out')]
        out.append(f"{j.get('name', '?')}: {bad[0] if bad else 'job упал без шага'}" + (f' (+{len(bad) - 1})' if len(bad) > 1 else ''))
    return out


def _hours(h: float) -> str:
    return (f'{h:.1f}'.replace('.', ',') if h < 10 else f'{h:.0f}') + ' ч'


def line(v: dict, steps: list, now: datetime, branch: str = 'main') -> str:
    if v['state'] == 'unknown':
        return f'CI на {branch}: неизвестно — {v["why"]}'
    last = v['last']
    sha = (last.get('head_sha') or '')[:8]
    if v['state'] == 'green':
        return f'CI на {branch}: зелёный · коммит {sha} · {_ts(last["created_at"]).strftime("%d.%m %H:%M")} UTC'
    first = v['first']
    age = _hours((now - _ts(first['created_at'])).total_seconds() / 3600)
    since = age if v['closed'] else f'≥ {age} (зелёного в выборке нет)'
    what = '; '.join(steps) if steps else 'шаг не известен'
    return (f'CI на {branch}: красный {since}, прогонов подряд {v["n"]} · шаг {what} · коммит {sha}'
            + (f' (первый красный {(first.get("head_sha") or "")[:8]})' if first is not last else ''))


def status(repo: str, branch: str, workflow: str, now: datetime, wfile: str = 'ci.yml') -> tuple[str, int]:
    try:
        # прогоны ОДНОГО workflow: общий список /actions/runs делят memory-audit и выкладка — 100 строк были ~1,5 ч гейта
        runs = fetch(f'/repos/{repo}/actions/workflows/{wfile}/runs?branch={branch}&status=completed&per_page=100').get('workflow_runs') or []
    except Exception as e:  # сеть, лимит API, плохой JSON — честное «неизвестно», не зелёный
        return f'CI на {branch}: неизвестно — API GitHub не ответил ({type(e).__name__}: {str(e)[:80]})', 2
    v = verdict(runs, workflow)
    steps = []
    if v['state'] == 'red':
        try:
            steps = failed_steps(fetch(f'/repos/{repo}/actions/runs/{v["last"]["id"]}/jobs'))
        except Exception as e:
            steps = [f'не прочитан ({type(e).__name__})']
    return line(v, steps, now, branch), {'green': 0, 'red': 1}.get(v['state'], 2)


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    branch = argv[argv.index('--branch') + 1] if '--branch' in argv else 'main'
    workflow = argv[argv.index('--workflow') + 1] if '--workflow' in argv else 'CI gate'
    repo = argv[argv.index('--repo') + 1] if '--repo' in argv else repo_here()
    now = _ts(os.environ['CI_STATUS_NOW']) if os.environ.get('CI_STATUS_NOW') else datetime.now(timezone.utc)
    wfile = argv[argv.index('--workflow-file') + 1] if '--workflow-file' in argv else 'ci.yml'
    text, rc = status(repo, branch, workflow, now, wfile)
    if '--digest' in argv:
        # красный — закреплённой строкой «❗» (`refresh_digest.py`: DIGEST:! — всегда, сразу за заголовком), остальное — обычной
        print(('DIGEST:!' if rc == 1 else 'DIGEST:') + text)
        if rc == 1:
            print('WARN:ci_status: ' + text.split(': ', 1)[1])
        return 0
    print(text)
    return rc


def _run(i, sha, concl, at, status='completed', name='CI gate'):
    return {'id': i, 'name': name, 'head_sha': sha * 5, 'status': status, 'conclusion': concl, 'created_at': at}


def _selftest() -> int:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scout'))
    import remlab_tmp
    remlab_tmp.use('ci-status')
    import tempfile
    bad = []

    def check(cond, msg, got=None):
        print(('OK   ' if cond else 'FAIL ') + msg + ('' if cond else f': {got!r}'))
        if not cond:
            bad.append(msg)

    now = _ts('2026-11-07T18:00:00Z')
    # подставной ответ API: новые первыми, чужой workflow и незавершённый вперемешку
    runs = [_run(9, 'e9a1', None, '2026-11-07T17:59:00Z', status='in_progress'),
            _run(8, 'cc0b', 'failure', '2026-11-07T17:58:00Z'),
            _run(7, 'aaaa', 'success', '2026-11-07T17:57:00Z', name='memory-audit'),
            _run(6, '11cb', 'cancelled', '2026-11-07T17:56:00Z'),
            _run(5, '6f23', 'failure', '2026-11-07T15:38:00Z'),
            _run(4, '7584', 'success', '2026-11-07T15:35:00Z'),
            _run(3, '9e0b', 'failure', '2026-11-07T13:00:00Z')]
    v = verdict(runs)
    check(v['state'] == 'red' and v['last']['id'] == 8 and v['first']['id'] == 5 and v['closed'] and v['n'] == 2,
          'красный: последний решающий (в работе, чужой и отменённый не решают), полоса — с первого красного после зелёного', v)
    jobs = {'jobs': [{'name': 'planner', 'conclusion': 'success', 'steps': []},
                     {'name': 'gate', 'conclusion': 'failure', 'steps': [
                         {'name': 'Run pnpm install', 'conclusion': 'success'},
                         {'name': 'Run node tools/ops/demo-realistic.mjs --selftest', 'conclusion': 'failure'},
                         {'name': 'Run pnpm test', 'conclusion': 'skipped'}]}]}
    st = failed_steps(jobs)
    check(st == ['gate: Run node tools/ops/demo-realistic.mjs --selftest'], 'упавший шаг — job: шаг, пропущенные не в счёт', st)
    t = line(v, st, now)
    check(t.startswith('CI на main: красный 2,4 ч, прогонов подряд 2 · шаг gate: Run node tools/ops/demo-realistic.mjs')
          and 'коммит cc0bcc0b' in t and 'первый красный 6f236f23' in t, 'строка красного: часы с первого красного, шаг, коммиты', t)
    v2 = verdict([_run(2, 'abcd', 'success', '2026-11-07T17:00:00Z'), _run(1, 'dddd', 'failure', '2026-11-07T16:00:00Z')])
    t2 = line(v2, [], now)
    check(v2['state'] == 'green' and t2 == 'CI на main: зелёный · коммит abcdabcd · 07.11 17:00 UTC', 'зелёный — последний решающий', t2)
    v3 = verdict([_run(2, 'abcd', 'failure', '2026-11-07T06:00:00Z')])
    check(v3['state'] == 'red' and not v3['closed'] and '≥ 12 ч (зелёного в выборке нет)' in line(v3, [], now),
          'зелёного в выборке нет — «≥ N ч»', line(v3, [], now))
    check(verdict([_run(1, 'x', None, '2026-11-07T17:00:00Z', status='in_progress')])['state'] == 'unknown', 'нет завершённых — неизвестно')
    check(repo_of_remote('git@github.com:igortsk123/remlab.git') == 'igortsk123/remlab'
          and repo_of_remote('https://github.com/a-b/c.d') == 'a-b/c.d' and repo_of_remote('') == REPO_DEFAULT, 'репозиторий из origin')
    # весь путь скрипта: подмена API файлами, коды выхода и --digest
    d = tempfile.mkdtemp(prefix='ci-status-')
    with open(os.path.join(d, 'runs.json'), 'w', encoding='utf-8') as f:
        json.dump({'workflow_runs': runs}, f)
    with open(os.path.join(d, 'jobs-8.json'), 'w', encoding='utf-8') as f:
        json.dump(jobs, f)
    sh = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ci-status.sh')
    env = dict(os.environ, CI_STATUS_FIXTURE=d, CI_STATUS_NOW='2026-11-07T18:00:00Z')
    r = subprocess.run(['bash', sh], capture_output=True, text=True, env=env)
    check(r.returncode == 1 and r.stdout.startswith('CI на main: красный'), 'ci-status.sh: красный — код 1', (r.returncode, r.stdout, r.stderr))
    r = subprocess.run(['bash', sh, '--digest'], capture_output=True, text=True, env=env)
    ls = r.stdout.splitlines()
    check(r.returncode == 0 and len(ls) == 2 and ls[0].startswith('DIGEST:!CI на main: красный 2,4 ч')
          and ls[1].startswith('WARN:ci_status: красный'), '--digest: закреплённая DIGEST:! + WARN, код 0 (шаг ночи warn, не FAIL)', (r.returncode, ls))
    with open(os.path.join(d, 'runs.json'), 'w', encoding='utf-8') as f:
        json.dump({'workflow_runs': runs[5:]}, f)   # без новых красных: последний решающий — зелёный 7584
    r = subprocess.run(['bash', sh], capture_output=True, text=True, env=env)
    check(r.returncode == 0 and 'зелёный · коммит 75847584' in r.stdout, 'ci-status.sh: зелёный — код 0', (r.returncode, r.stdout))
    r = subprocess.run(['bash', sh, '--digest'], capture_output=True, text=True, env=env)
    check(r.stdout.startswith('DIGEST:CI на main: зелёный') and 'WARN' not in r.stdout, '--digest зелёный: одна строка без WARN', r.stdout)
    with open(os.path.join(d, 'runs.json'), 'w', encoding='utf-8') as f:
        f.write('{не json')
    r = subprocess.run(['bash', sh], capture_output=True, text=True, env=env)
    check(r.returncode == 2 and 'неизвестно — API GitHub не ответил' in r.stdout, 'сломанный ответ API — «неизвестно», код 2, не зелёный', (r.returncode, r.stdout))
    r = subprocess.run(['bash', sh, '--digest'], capture_output=True, text=True, env=env)
    check(r.returncode == 0 and r.stdout.startswith('DIGEST:CI на main: неизвестно') and 'WARN' not in r.stdout,
          '--digest неизвестно: строка DIGEST, без WARN', r.stdout)
    print(f'ci_status selftest: ошибок {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
