"""Временное — на диске и с уборкой (T-20261107-13). /tmp на DEV — tmpfs ~788 МБ с квотой на пользователя, общий с чужими
проектами и папками сессий Claude; при пиках запись падает EDQUOT (07.11: test_bank_rehearsal, test_alert_retry, Playwright).
Тесты и селфтесты оставляли там папки навсегда (db-migrate-selftest 79, heavy-slot-selftest 25, alert-retry 13, tmp* 300+).
Проверяем:
- помощник `tools/scout/remlab_tmp.py` (его --selftest): REMLAB_TMP → ~/remlab-scratch/tmp → в CI системная; tmpdir/use убирают;
- каждый python-тест с временным (tempfile, /tmp) подключает `remlab_tmp.use(…)`; каждый селфтест модуля с tempfile — тоже
  (в теле функции); сама проверка ловит подложенный тест без помощника;
- shell: `remlab-tmp.sh` в CI берёт RUNNER_TEMP; `remlab_tmp_dir` + `remlab_tmp_trap` — успех убирает, провал оставляет;
  селфтесты db-migrate-safe и heavy-slot — через них;
- `heavy_slot.py` даёт команде TMPDIR на диске (заданный — не трогает); `nightly_exam.sh` экспортирует TMPDIR до экзамена;
- `tmp-sweep.sh --dry` предлагает только старые rt-* / *-selftest.* в REMLAB_TMP, свежие и живые — нет.
    python3 tools/scout/tests/test_tmp_hygiene.py"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
ROOT = os.path.abspath(os.path.join(SCOUT, '..', '..'))
sys.path.append(SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_tmp_hygiene')

BAD = []
TEST_GLOBS = [('tools/scout/tests', 'test_'), ('tools/scout/salad', 'tests_'), ('tools/scout', 'tests_'), ('tools/assets/tests', 'test_')]
# свои правила временного: стенд в ~/.cache (dbtest), REMLAB_TMP через BR.tmp_root, этот тест и проверка жёсткого /tmp
TEST_EXEMPT = {'tools/scout/tests/mesh_owner_audit_dbtest.py', 'tools/scout/tests/pipeline_chain_dbtest.py',
               'tools/scout/tests/test_bank_rehearsal.py', 'tools/scout/tests/test_no_hard_tmp.py',
               'tools/scout/tests/test_tmp_hygiene.py'}
USES_TMP = re.compile(r'^(?!\s*#).*(tempfile\.|[\'"]/tmp[/\'"])', re.M)


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def test_files():
    out = []
    for d, pre in TEST_GLOBS:
        p = os.path.join(ROOT, d)
        for n in sorted(os.listdir(p)):
            if n.startswith(pre) and n.endswith('.py'):
                out.append(f'{d}/{n}')
    return out


def tests_without_helper(files, read=lambda f: open(os.path.join(ROOT, f), encoding='utf-8').read()):
    return [f for f in files if f not in TEST_EXEMPT and USES_TMP.search(read(f)) and 'remlab_tmp.use(' not in read(f)]


def selftests_without_helper(files, read=lambda f: open(os.path.join(ROOT, f), encoding='utf-8').read()):
    """Функции _selftest/selftest с tempfile.* без remlab_tmp.use( в теле."""
    miss = []
    for f in files:
        src = read(f)
        if 'tempfile' not in src:
            continue
        for n in ast.parse(src).body:
            if isinstance(n, ast.FunctionDef) and n.name in ('_selftest', 'selftest'):
                seg = ast.get_source_segment(src, n) or ''
                if 'tempfile.' in seg and 'remlab_tmp.use(' not in seg:
                    miss.append(f'{f}:{n.name}')
    return miss


def module_files():
    out = []
    for d in ('tools/scout', 'tools/scout/salad', 'tools/assets'):
        for n in sorted(os.listdir(os.path.join(ROOT, d))):
            if n.endswith('.py') and not n.startswith(('test_', 'tests_')) and n != 'remlab_tmp.py':
                out.append(f'{d}/{n}')
    return out


def sh(cmd, **env):
    return subprocess.run(['bash', '-c', cmd], cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def main():
    print('помощник remlab_tmp.py:')
    r = subprocess.run([sys.executable, os.path.join(SCOUT, 'remlab_tmp.py'), '--selftest'], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    ok(r.returncode == 0, 'remlab_tmp --selftest' + ('' if r.returncode == 0 else ': ' + (r.stdout + r.stderr)[-400:]))
    ok(os.path.dirname(tempfile.gettempdir()) == (remlab_tmp.root() or os.path.dirname(tempfile.gettempdir()))
       and os.path.basename(tempfile.gettempdir()).startswith('rt-test_tmp_hygiene-'),
       f'use: tempfile этого теста — в своей папке rt-* ({tempfile.gettempdir()})')

    print('python-тесты и селфтесты:')
    miss = tests_without_helper(test_files())
    ok(not miss, 'тесты с временным подключают remlab_tmp.use' + ('' if not miss else ': ' + ', '.join(miss)))
    miss = selftests_without_helper(module_files())
    ok(not miss, 'селфтесты модулей с tempfile подключают remlab_tmp.use' + ('' if not miss else ': ' + ', '.join(miss)))
    fake = {'tools/scout/tests/test_fake.py': 'import tempfile\nd = tempfile.mkdtemp()\n',
            'tools/scout/tests/test_fake_ok.py': 'import remlab_tmp\nremlab_tmp.use("x")\nimport tempfile\n',
            'tools/scout/fake_mod.py': 'import tempfile\ndef _selftest():\n    with tempfile.TemporaryDirectory() as t:\n        pass\n'}
    ok(tests_without_helper(list(fake)[:2], read=fake.get) == ['tools/scout/tests/test_fake.py'],
       'проверка ловит подложенный тест без помощника и пропускает с ним')
    ok(selftests_without_helper(['tools/scout/fake_mod.py'], read=fake.get) == ['tools/scout/fake_mod.py:_selftest'],
       'проверка ловит подложенный селфтест без помощника')

    print('shell — remlab-tmp.sh:')
    with tempfile.TemporaryDirectory() as t:
        r = sh('unset REMLAB_TMP; . tools/ops/remlab-tmp.sh; echo "$REMLAB_TMP"', CI='true', RUNNER_TEMP=os.path.join(t, 'rt'))
        ok(r.stdout.strip() == os.path.join(t, 'rt'), f'в CI без REMLAB_TMP — RUNNER_TEMP ({r.stdout.strip()!r})')
        r = sh('. tools/ops/remlab-tmp.sh; echo "$REMLAB_TMP"', CI='true', RUNNER_TEMP=os.path.join(t, 'rt'),
               REMLAB_TMP=os.path.join(t, 'given'))
        ok(r.stdout.strip() == os.path.join(t, 'given'), 'в CI заданный REMLAB_TMP — он')
        prog = '. tools/ops/remlab-tmp.sh; T=$(remlab_tmp_dir sh-selftest) || exit 9; remlab_tmp_trap "$T"; echo "$T"; touch "$T/f"; exit %d'
        r0 = sh(prog % 0, REMLAB_TMP=os.path.join(t, 'r'))
        d0 = r0.stdout.strip()
        ok(r0.returncode == 0 and d0.startswith(os.path.join(t, 'r', 'sh-selftest.')) and not os.path.exists(d0),
           f'remlab_tmp_dir + trap: успех — папка убрана ({d0!r})')
        r1 = sh(prog % 3, REMLAB_TMP=os.path.join(t, 'r'))
        d1 = r1.stdout.strip()
        ok(r1.returncode == 3 and os.path.isdir(d1) and f'оставлена: {d1}' in r1.stderr, 'провал — папка оставлена, путь в stderr, код тот же')
        r2 = sh(prog % 0, REMLAB_TMP=os.path.join(t, 'r'), REMLAB_KEEP_TMP='1')
        ok(os.path.isdir(r2.stdout.strip()), 'REMLAB_KEEP_TMP=1 — оставлена')
        r3 = sh('. tools/ops/remlab-tmp.sh; remlab_tmp_trap /etc', REMLAB_TMP=os.path.join(t, 'r'))
        ok(r3.returncode == 1 and 'не внутри' in r3.stderr, 'trap на папку вне REMLAB_TMP — отказ')
    for rel in ('tools/ops/db-migrate-safe-selftest.sh', 'tools/ops/heavy-slot-selftest.sh'):
        s = open(os.path.join(ROOT, rel), encoding='utf-8').read()
        ok('remlab_tmp_dir ' in s and 'remlab_tmp_trap "$T"' in s and ':-/tmp}' not in s, f'{rel}: папка через remlab_tmp_dir + trap')

    print('heavy_slot и ночь:')
    with tempfile.TemporaryDirectory() as t:
        env = {k: v for k, v in os.environ.items() if k != 'TMPDIR'}
        r = subprocess.run([sys.executable, 'tools/ops/heavy_slot.py', 't113-selftest', '--no-slot', '--min-gb', '0', '--',
                            'bash', '-c', 'echo "$TMPDIR"'], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env={**env, 'REMLAB_TMP': os.path.join(t, 'h'), 'HEAVY_SLOT_DIR': os.path.join(t, 'slot'),
                                'HEAVY_SLOT_LOG': os.path.join(t, 'hs.log')})
        ok(r.stdout.strip() == os.path.join(t, 'h'), f'heavy_slot: команде TMPDIR = REMLAB_TMP ({r.stdout.strip()!r})')
        r = subprocess.run([sys.executable, 'tools/ops/heavy_slot.py', 't113-selftest', '--no-slot', '--min-gb', '0', '--',
                            'bash', '-c', 'echo "$TMPDIR"'], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           env={**env, 'TMPDIR': '/x/given', 'REMLAB_TMP': os.path.join(t, 'h'),
                                'HEAVY_SLOT_DIR': os.path.join(t, 'slot'), 'HEAVY_SLOT_LOG': os.path.join(t, 'hs.log')})
        ok(r.stdout.strip() == '/x/given', 'heavy_slot: заданный TMPDIR не трогает')
    ne = open(os.path.join(ROOT, 'tools/scout/nightly_exam.sh'), encoding='utf-8').read()
    i_src, i_exp, i_exam = ne.find('. ../ops/remlab-tmp.sh'), ne.find('export TMPDIR="$REMLAB_TMP"'), ne.find('./run.sh exam')
    ok(0 < i_src < i_exp < i_exam, 'nightly_exam: remlab-tmp.sh и export TMPDIR — до экзамена')

    print('tmp-sweep — забытые папки в REMLAB_TMP:')
    with tempfile.TemporaryDirectory() as t:
        rt = os.path.join(t, 'rtmp')
        old = time.time() - 3 * 86400
        for name, fresh_inside in (('rt-old-aaaa', False), ('db-migrate-selftest.bbbb', False), ('rt-live-cccc', True),
                                   ('keepme-dddd', False)):
            d = os.path.join(rt, name)
            os.makedirs(d)
            f = os.path.join(d, 'f')
            open(f, 'w').close()
            if not fresh_inside:
                os.utime(f, (old, old))
            os.utime(d, (old, old))
        os.makedirs(os.path.join(rt, 'rt-new-eeee'))
        r = sh('bash tools/ops/tmp-sweep.sh --dry', REMLAB_TMP=rt)
        listed = re.findall(r'удалю папку: (\S+)', r.stdout)
        names = sorted(os.path.basename(x) for x in listed)
        ok(names == ['db-migrate-selftest.bbbb', 'rt-old-aaaa'], f'--dry: только старые rt-*/*-selftest.* ({names})')
        ok(all(x.startswith(rt + '/') for x in listed), 'папки — только в REMLAB_TMP, не в /tmp')
        ok(all(os.path.isdir(os.path.join(rt, n)) for n in os.listdir(rt)) and len(os.listdir(rt)) == 5, '--dry ничего не удалил')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
