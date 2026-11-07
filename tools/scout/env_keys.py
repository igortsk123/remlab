#!/usr/bin/env python3
"""Ключи и общие журналы скриптов scout — одно место для основной копии и worktree (T-20261105-52).

ЗАЧЕМ. `tools/scout/.env` в git не лежит (gitignore), поэтому в worktree (`.claude/worktrees/<имя>`) его нет. Резолверы
скриптов искали ключ «свой .env → корень репо → /home/pakar/mltest/.env» и в worktree молча брали старый ключ чужого
проекта: платный прогон получал 401 (T-20261105-48/2), а фолбэк без LLM ложился в кэш. Журнал расходов
`openai-spend.jsonl` писался рядом со скриптом — расход из worktree не видел дневной лимит `openai_budget`.

Порядок поиска ключа `get(name)`:
  1) переменная окружения;
  2) своё дерево: `tools/scout/.env`, `<корень>/.env.local`, `<корень>/.env`;
  3) из worktree — основная копия (путь через `git rev-parse --git-common-dir`, не зашитый): те же три файла;
  4) ЧУЖОЙ проект `/home/pakar/mltest/.env` — явным последним и с громким WARN (там старые ключи).
Значения ключей модуль не печатает никогда; `--where` показывает только, из какого файла взят ключ.

`shared(name)` — путь общего файла прогона (журнал расходов) в `tools/scout` ОСНОВНОЙ копии: из worktree пишем туда же.

  python3 env_keys.py --where [ИМЯ ...]   # откуда взялся бы каждый ключ (без значений)
  python3 env_keys.py --ping              # бесплатная проверка, что ключ жив: шлюз /v1/credits, OpenAI /v1/models (код ответа)
  python3 env_keys.py --selftest
"""
import functools
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEGACY = ('/home/pakar/mltest/.env',)   # чужой проект: только последним и с WARN
KNOWN = ('VERCEL_AI_GATEWAY_KEY', 'OPENAI_API_KEY', 'FAL_KEY')
_warned: set = set()


@functools.lru_cache(maxsize=None)
def _git(here: str, *args: str) -> str | None:
    try:
        r = subprocess.run(['git', '-C', here, 'rev-parse', '--path-format=absolute', *args],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def tree_root(here: str = HERE) -> str:
    """Корень своего дерева (основной копии или worktree); вне git — два уровня вверх от tools/scout, как раньше."""
    return _git(here, '--show-toplevel') or os.path.abspath(os.path.join(here, '..', '..'))


def main_root(here: str = HERE) -> str:
    """Корень ОСНОВНОЙ копии: родитель общего `.git` (`--git-common-dir`). Не worktree или вне git — своё дерево."""
    common = _git(here, '--git-common-dir')
    if common and os.path.basename(common.rstrip('/')) == '.git':
        return os.path.dirname(common.rstrip('/'))
    return tree_root(here)


def in_worktree(here: str = HERE) -> bool:
    return os.path.realpath(main_root(here)) != os.path.realpath(tree_root(here))


def _scout_rel(here: str) -> str:
    return os.path.relpath(os.path.abspath(here), tree_root(here))


def env_files(here: str = HERE, legacy: tuple = LEGACY) -> list:
    """[(путь, метка)] по порядку поиска; метка: своё | основная копия | ЧУЖОЙ."""
    def trio(root: str, scout: str) -> list:
        return [os.path.join(scout, '.env'), os.path.join(root, '.env.local'), os.path.join(root, '.env')]
    own_root = tree_root(here)
    out = [(p, 'своё') for p in trio(own_root, os.path.abspath(here))]
    if in_worktree(here):
        mr = main_root(here)
        out += [(p, 'основная копия') for p in trio(mr, os.path.join(mr, _scout_rel(here)))]
    out += [(p, 'ЧУЖОЙ') for p in legacy]
    seen, uniq = set(), []
    for p, lab in out:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append((p, lab))
    return uniq


def _read(path: str, name: str) -> str | None:
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                m = re.match(rf'(?:export\s+)?{re.escape(name)}=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"\'')
    except (OSError, UnicodeDecodeError):
        return None
    return None


def where(name: str, here: str = HERE, legacy: tuple = LEGACY) -> tuple:
    """(значение, путь, метка) или (None, None, None). Путь 'env' — из переменной окружения."""
    v = os.environ.get(name)
    if v and v.strip():
        return v.strip(), 'env', 'окружение'
    for p, lab in env_files(here, legacy):
        v = _read(p, name)
        if v:
            return v, p, lab
    return None, None, None


def get(name: str, here: str = HERE, legacy: tuple = LEGACY) -> str | None:
    """Значение ключа или None. Ключ из чужого проекта — WARN в stderr (один раз на имя), без значения."""
    v, p, lab = where(name, here, legacy)
    if lab == 'ЧУЖОЙ' and name not in _warned:
        _warned.add(name)
        print(f'WARN:env_keys: {name} взят из ЧУЖОГО проекта {p} — ключ там может быть мёртв (401); '
              f'положите его в {os.path.join(main_root(here), _scout_rel(here), ".env")}', file=sys.stderr, flush=True)
    return v


def need(name: str, here: str = HERE) -> str:
    v = get(name, here)
    if not v:
        raise SystemExit(f'нет {name} — ни в окружении, ни в .env (см. .memory_bank/_secrets/ACCESS.md; '
                         f'`python3 tools/scout/env_keys.py --where {name}`)')
    return v


def shared(name: str, here: str = HERE) -> str:
    """Общий файл прогона (журнал расходов) — в tools/scout ОСНОВНОЙ копии, из worktree тоже."""
    return os.path.join(main_root(here), _scout_rel(here), name)


PING = {'VERCEL_AI_GATEWAY_KEY': 'https://ai-gateway.vercel.sh/v1/credits', 'OPENAI_API_KEY': 'https://api.openai.com/v1/models'}


def ping(name: str, here: str = HERE) -> str:
    """Бесплатный GET с ключом (баланс шлюза / список моделей) → «200 ok» | «401 …» | «нет ключа». Значение не печатается."""
    import urllib.error
    import urllib.request
    v = get(name, here)
    if not v:
        return 'нет ключа'
    req = urllib.request.Request(PING[name], headers={'Authorization': f'Bearer {v}'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f'{r.status} ok'
    except urllib.error.HTTPError as e:
        return f'{e.code} {e.reason}'
    except OSError as e:
        return f'сеть: {type(e).__name__}'


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('env_keys-selftest')
    import tempfile
    bad = 0

    def ok(label: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + label)
        bad += not cond

    with tempfile.TemporaryDirectory() as td:
        main = os.path.join(td, 'main')
        os.makedirs(os.path.join(main, 'tools', 'scout'))
        g = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'init.defaultBranch=main']
        run = lambda *a, cwd=main: subprocess.run([*g, *a], cwd=cwd, capture_output=True, text=True, check=True)  # noqa: E731
        run('init', '-q')
        open(os.path.join(main, 'tools', 'scout', 'x.py'), 'w').write('')
        open(os.path.join(main, '.gitignore'), 'w').write('.env\n.env.local\n*.jsonl\n')
        run('add', '-A')
        run('commit', '-qm', 'init')
        wt = os.path.join(main, '.claude', 'worktrees', 'w1')
        run('worktree', 'add', '-q', wt, '-b', 'wt-w1')
        m_scout, w_scout = os.path.join(main, 'tools', 'scout'), os.path.join(wt, 'tools', 'scout')
        open(os.path.join(m_scout, '.env'), 'w').write('T52_KEY="main-scout"\nT52_ROOT_ONLY=x\n')
        open(os.path.join(main, '.env.local'), 'w').write('T52_ROOT_KEY=main-root\n')
        leg = os.path.join(td, 'legacy.env')
        open(leg, 'w').write('T52_KEY=legacy\nT52_LEGACY_ONLY=old\n')
        for k in ('T52_KEY', 'T52_ROOT_KEY', 'T52_LEGACY_ONLY', 'T52_NONE'):
            os.environ.pop(k, None)

        ok('worktree узнаётся: основная копия — через --git-common-dir', in_worktree(w_scout)
           and os.path.realpath(main_root(w_scout)) == os.path.realpath(main)
           and not in_worktree(m_scout))
        v, p, lab = where('T52_KEY', w_scout, (leg,))
        ok('из worktree без своего .env — ключ основной копии, а не чужого проекта',
           v == 'main-scout' and lab == 'основная копия' and os.path.realpath(p) == os.path.realpath(os.path.join(m_scout, '.env')))
        v, p, lab = where('T52_ROOT_KEY', w_scout, (leg,))
        ok('из worktree — и .env.local корня основной копии', v == 'main-root' and lab == 'основная копия')
        open(os.path.join(w_scout, '.env'), 'w').write('T52_KEY=own\n')
        ok('свой .env worktree — первым', where('T52_KEY', w_scout, (leg,))[0] == 'own')
        os.environ['T52_KEY'] = 'from-env'
        ok('переменная окружения — раньше файлов', where('T52_KEY', w_scout, (leg,))[0] == 'from-env')
        os.environ.pop('T52_KEY')
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            v = get('T52_LEGACY_ONLY', w_scout, (leg,))
        ok('чужой проект — последним, с громким WARN и без значения в сообщении',
           v == 'old' and 'WARN:env_keys' in err.getvalue() and 'old' not in err.getvalue().replace('T52_LEGACY_ONLY', ''))
        ok('порядок: своё → основная копия → ЧУЖОЙ', [lab for _, lab in env_files(w_scout, (leg,))]
           == ['своё'] * 3 + ['основная копия'] * 3 + ['ЧУЖОЙ'])
        ok('нет ключа нигде — None', get('T52_NONE', w_scout, (leg,)) is None)
        ok('журнал расходов из worktree — в tools/scout основной копии',
           os.path.realpath(os.path.dirname(shared('openai-spend.jsonl', w_scout))) == os.path.realpath(m_scout)
           and os.path.realpath(os.path.dirname(shared('openai-spend.jsonl', m_scout))) == os.path.realpath(m_scout))
        plain = os.path.join(td, 'plain', 'tools', 'scout')
        os.makedirs(plain)
        ok('вне git — своё дерево (два уровня вверх), без worktree',
           not in_worktree(plain) and os.path.realpath(shared('j.jsonl', plain)) == os.path.realpath(os.path.join(plain, 'j.jsonl')))
    import openai_budget
    ok('журнал openai_budget — общий путь (env_keys.shared), из worktree — в основной копии',
       openai_budget.SPEND_LOG == shared('openai-spend.jsonl', HERE))
    print(f'FAILS {bad}')
    return bad


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    if '--ping' in sys.argv:
        bad = 0
        for n in PING:
            v, p, lab = where(n)
            res = ping(n)
            bad += not res.startswith('200')
            print(f'  {n}: {res}' + (f' — {lab} ({p})' if v else ''))
        sys.exit(1 if bad else 0)
    if '--where' in sys.argv:
        names = [a for a in sys.argv[sys.argv.index('--where') + 1:] if not a.startswith('-')] or list(KNOWN)
        print(f'дерево: {tree_root()}' + (f' (worktree; основная копия {main_root()})' if in_worktree() else ''))
        for n in names:
            v, p, lab = where(n)
            print(f'  {n}: ' + (f'{lab} — {p}' if v else 'НЕТ'))
        sys.exit(0)
    print(__doc__)
