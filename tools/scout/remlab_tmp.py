"""ВРЕМЕННАЯ ПАПКА — НА ДИСКЕ, НЕ В /tmp (T-20261107-13). Один помощник для тестов, селфтестов и ночных скриптов.

/tmp на DEV — tmpfs ~788 МБ с квотой на пользователя (usrquota), общий с чужими проектами и папками сессий Claude; при пиках
запись падает `OSError: [Errno 122] Disk quota exceeded` (EDQUOT). 07.11 так мигали test_bank_rehearsal (seeds-0940),
test_alert_retry (подмена curl потеряла запись вызова), Playwright у рабочих; ночью — demo_rt (T-20261107-02).
Куда: `REMLAB_TMP` (если задан — всегда), иначе `~/remlab-scratch/tmp` (создаётся, если есть ~/remlab-scratch); в CI
(`CI`/`GITHUB_ACTIONS`) без REMLAB_TMP — системная (None → tempfile как обычно). То же правило в shell —
`tools/ops/remlab-tmp.sh`.

    import remlab_tmp as RTMP
    RTMP.use('test_x')                 # процесс целиком: tempfile.* и TMPDIR детей — в своей папке rt-test_x-*, при выходе убрать
    with RTMP.tmpdir('stand-') as d:   # одна папка: убрать в finally (и при исключении)
        ...
    RTMP.keep('провал')                # не убирать папку процесса (путь — в вывод); или REMLAB_KEEP_TMP=1

Уборка забытого (процесс убит сигналом — atexit не сработал): `tools/ops/tmp-sweep.sh` — папки rt-* в REMLAB_TMP старше порога."""
import atexit
import contextlib
import os
import shutil
import sys
import tempfile

DEFAULT = os.path.join('~', 'remlab-scratch', 'tmp')
SESSION_PREFIX = 'rt-'
_session = {'dir': None, 'pid': None, 'keep': None}


def in_ci(env: dict | None = None) -> bool:
    e = os.environ if env is None else env
    return bool(e.get('CI') or e.get('GITHUB_ACTIONS'))


def root(env: dict | None = None) -> str | None:
    """Папка временного на диске или None (системная). REMLAB_TMP — создаётся; ~/remlab-scratch/tmp — только если есть
    ~/remlab-scratch (на чужой машине и в CI не заводим)."""
    e = os.environ if env is None else env
    given = e.get('REMLAB_TMP')
    cands = [(given, True)] if given else []
    if not in_ci(e):
        d = os.path.join(e['HOME'], DEFAULT[2:]) if e.get('HOME') else os.path.expanduser(DEFAULT)
        cands.append((d, os.path.isdir(os.path.dirname(d))))
    for d, make in cands:
        try:
            if make:
                os.makedirs(d, exist_ok=True)
        except OSError:
            continue
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return d
    return None


def _keep_env() -> bool:
    return os.environ.get('REMLAB_KEEP_TMP', '') not in ('', '0')


@contextlib.contextmanager
def tmpdir(prefix: str = 'rt-', keep_on_error: bool = False):
    """Своя временная папка в root(): убрать в finally; оставить — REMLAB_KEEP_TMP=1 или исключение при keep_on_error."""
    d = tempfile.mkdtemp(prefix=prefix, dir=root())
    ok = False
    try:
        yield d
        ok = True
    finally:
        if _keep_env() or (keep_on_error and not ok):
            print(f'временная папка оставлена: {d}', file=sys.stderr)
        else:
            shutil.rmtree(d, ignore_errors=True)


def _cleanup():
    d = _session['dir']
    if not d or _session['pid'] != os.getpid():          # форк-потомок папку родителя не убирает
        return
    if _session['keep'] is not None or _keep_env():
        print(f'временная папка оставлена ({_session["keep"] or "REMLAB_KEEP_TMP"}): {d}', file=sys.stderr)
        return
    shutil.rmtree(d, ignore_errors=True)


def use(name: str) -> str:
    """Весь процесс — во временной папке `rt-<name>-*` внутри root(): tempfile.tempdir и TMPDIR (python/node/bash/Chromium
    детей) указывают туда; при выходе процесса папка удаляется. Повторный вызов — та же папка."""
    if _session['dir'] and _session['pid'] == os.getpid() and os.path.isdir(_session['dir']):
        return _session['dir']
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in name)[:40] or 'proc'
    d = tempfile.mkdtemp(prefix=f'{SESSION_PREFIX}{safe}-', dir=root())
    first = _session['dir'] is None
    _session.update(dir=d, pid=os.getpid(), keep=None)
    tempfile.tempdir = d
    os.environ['TMPDIR'] = d
    if first:
        atexit.register(_cleanup)
    return d


def keep(reason: str = 'оставить') -> None:
    """Папку процесса не убирать (провал теста — разбор по файлам)."""
    _session['keep'] = reason


def child_env(env: dict | None = None) -> dict:
    """Окружение для дочернего процесса: TMPDIR = root(), если TMPDIR не задан (heavy_slot)."""
    e = dict(os.environ if env is None else env)
    if not e.get('TMPDIR'):
        r = root(e)
        if r:
            e['TMPDIR'] = r
    return e


def _selftest() -> int:
    import subprocess
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ok  ' if cond else '  FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    base = tempfile.mkdtemp(prefix='remlab-tmp-selftest-', dir=root())
    try:
        env0 = {k: v for k, v in os.environ.items() if k not in ('REMLAB_TMP', 'CI', 'GITHUB_ACTIONS', 'TMPDIR', 'REMLAB_KEEP_TMP')}
        code = ('import sys; sys.path.insert(0, %r); import remlab_tmp as R; print(R.root())'
                % os.path.dirname(os.path.abspath(__file__)))
        run = lambda **kw: subprocess.run([sys.executable, '-c', code], env={**env0, **kw}, capture_output=True, text=True).stdout.strip()
        want = os.path.join(base, 'given')
        ok('REMLAB_TMP задан — он (и создаётся)', run(REMLAB_TMP=want) == want and os.path.isdir(want))
        ok('REMLAB_TMP задан и в CI — он', run(REMLAB_TMP=want, CI='true') == want)
        ok('CI без REMLAB_TMP — системная (None)', run(CI='true') == 'None' and run(GITHUB_ACTIONS='true') == 'None')
        home = os.path.join(base, 'home')
        os.makedirs(os.path.join(home, 'remlab-scratch'))
        ok('без REMLAB_TMP — ~/remlab-scratch/tmp', run(HOME=home) == os.path.join(home, 'remlab-scratch', 'tmp'))
        bare = os.path.join(base, 'bare')
        os.makedirs(bare)
        ok('нет ~/remlab-scratch — системная, папку не заводим', run(HOME=bare) == 'None'
           and not os.path.exists(os.path.join(bare, 'remlab-scratch')))

        os.environ['REMLAB_TMP'] = want
        try:
            with tmpdir('t-') as d:
                inside = os.path.dirname(d) == want and os.path.isdir(d)
            ok('tmpdir — в root(), убрана после with', inside and not os.path.exists(d))
            try:
                with tmpdir('t-') as d2:
                    raise RuntimeError('x')
            except RuntimeError:
                pass
            ok('tmpdir — убрана и при исключении', not os.path.exists(d2))
            try:
                with tmpdir('t-', keep_on_error=True) as d3:
                    raise RuntimeError('x')
            except RuntimeError:
                pass
            ok('tmpdir keep_on_error — оставлена при исключении', os.path.isdir(d3))
            shutil.rmtree(d3, ignore_errors=True)
        finally:
            os.environ.pop('REMLAB_TMP', None)

        prog = ('import sys, os, tempfile, subprocess; sys.path.insert(0, %r); import remlab_tmp as R; d = R.use("t:x");'
                'f = tempfile.mkdtemp(); c = subprocess.run(["bash", "-c", "echo $TMPDIR"], capture_output=True, text=True).stdout.strip();'
                'print(d, f, c); sys.stdout.flush(); pid = os.fork()\n'
                'if pid == 0: os._exit(0) if len(sys.argv) < 2 else sys.exit(0)\n'
                'os.waitpid(pid, 0); print(os.path.isdir(d))\n'
                'if "keep" in sys.argv: R.keep("провал")' % os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, '-c', prog, 'exit'], env={**env0, 'REMLAB_TMP': want}, capture_output=True, text=True)
        lines = r.stdout.split('\n')
        d, f, c = (lines[0].split() + ['', '', ''])[:3]
        ok('use — папка rt-<имя>-* в root(), tempfile и TMPDIR детей — в ней',
           os.path.dirname(d) == want and os.path.basename(d).startswith('rt-t-x-') and os.path.dirname(f) == d and c == d,
           r.stdout + r.stderr)
        ok('use — форк-потомок (sys.exit) папку родителя не убрал', lines[1:2] == ['True'], r.stdout)
        ok('use — при выходе папка убрана', d and not os.path.exists(d))
        r = subprocess.run([sys.executable, '-c', prog, 'exit', 'keep'], env={**env0, 'REMLAB_TMP': want}, capture_output=True, text=True)
        d = r.stdout.split()[0] if r.stdout.split() else ''
        ok('keep — папка оставлена, путь в stderr', d and os.path.isdir(d) and d in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, '-c', prog, 'exit'], env={**env0, 'REMLAB_TMP': want, 'REMLAB_KEEP_TMP': '1'},
                           capture_output=True, text=True)
        d = r.stdout.split()[0] if r.stdout.split() else ''
        ok('REMLAB_KEEP_TMP=1 — папка оставлена', d and os.path.isdir(d))

        e = child_env({'PATH': '/bin', 'REMLAB_TMP': want})
        ok('child_env — TMPDIR = root(), если не задан', e.get('TMPDIR') == want)
        ok('child_env — заданный TMPDIR не трогаем', child_env({'TMPDIR': '/x', 'REMLAB_TMP': want})['TMPDIR'] == '/x')
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print('remlab_tmp selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if sys.argv[1:] == ['--selftest'] else 2)
