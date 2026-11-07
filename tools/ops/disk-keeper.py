#!/usr/bin/env python3
"""СТОРОЖ МЕСТА НА ДИСКЕ DEV (T-20261107-48): убирает старые РАБОЧИЕ папки задач по белому списку, без вопросов владельцу.

ЗАЧЕМ. 07.11 на / pakardev осталось 10–21 ГБ из 391 при резерве соседнего проекта 25 ГБ. Черновики, выводы и снимки задач
(~/remlab-scratch, ~/remlab-logs, ~/onb06-out, рабочие папки в ~/scout-scenes) копились без уборки — их никто не читает после
приёмки задачи.

ЧТО УХОДИТ (правила — tools/scout/rules/dev-disk.json):
  * подпапка корня из белого списка, где самый свежий файл (и сама папка) старше `dir_days` суток; в контейнерах корня
    (`containers`, например ~/remlab-scratch/tmp) — их подпапки, сам контейнер остаётся;
  * одиночные журналы *.log в корне (и в контейнерах) старше `log_days` суток, кроме `keep_files`;
  * в ~/scout-scenes — ТОЛЬКО папки по шаблонам `only`; `never` не трогается ни при каком шаблоне.
ЧТО НЕ УХОДИТ НИКОГДА:
  * `keep` и `never` корня; ссылки (symlink) и чужие файлы; сам корень и контейнер;
  * папка, которую называет код (tools, infra, lib, app, scripts, .github): `<корень>/<имя>` в тексте, а для ~/scout-scenes ещё
    и имя в кавычках в файле, где упомянут корень (`os.path.join(OUT, 'frames')`) — она чей-то вход или источник правила.
Удаление — shutil.rmtree внутри Python; перед удалением возраст проверяется заново (свежий файл появился — папка остаётся).

ВЫВОД. Сухой режим по умолчанию: «удалю X» по каждой папке и итог. `--apply` удаляет. `--digest` — строка
`DIGEST:диск: свободно N ГБ, убрано M ГБ` для ночной сводки; свободно меньше `warn_free_gb` — `WARN:disk_free:` (шаг warn).
  python3 tools/ops/disk-keeper.py              # сухой прогон
  python3 tools/ops/disk-keeper.py --apply --digest
  python3 tools/ops/disk-keeper.py --selftest
Переопределения для проверки: DISK_KEEPER_HOME (вместо ~), DISK_KEEPER_RULES (файл правил), DISK_KEEPER_REPO (где искать код)."""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('DISK_KEEPER_REPO') or os.path.abspath(os.path.join(HERE, '..', '..'))
RULES = os.environ.get('DISK_KEEPER_RULES') or os.path.join(REPO, 'tools', 'scout', 'rules', 'dev-disk.json')
CODE_DIRS = ('tools', 'infra', 'lib', 'app', 'scripts', '.github')
GB = 1024 ** 3


def home():
    return os.environ.get('DISK_KEEPER_HOME') or os.path.expanduser('~')


def expand(p):
    return os.path.join(home(), p[2:]) if p.startswith('~/') else p


def newest_after(path, cutoff):
    """True, если в дереве есть файл или папка новее `cutoff` (обход до первой находки; ссылки не разворачиваем)."""
    try:
        if os.lstat(path).st_mtime > cutoff:
            return True
    except OSError:
        return True   # не прочли — считаем живой
    for dp, dn, fn in os.walk(path, followlinks=False):
        for n in dn + fn:
            try:
                if os.lstat(os.path.join(dp, n)).st_mtime > cutoff:
                    return True
            except OSError:
                continue
    return False


def newest_days(path):
    t = 0.0
    for dp, dn, fn in os.walk(path, followlinks=False):
        for n in [dp] + [os.path.join(dp, x) for x in fn]:
            try:
                t = max(t, os.lstat(n).st_mtime)
            except OSError:
                pass
    return (time.time() - t) / 86400 if t else 0.0


def du(path):
    """Сколько места вернёт удаление: файл с жёсткими ссылками считается, только если ВСЕ его ссылки внутри дерева (стенд паритета
    раскладывает прогоны жёсткими ссылками — наивная сумма показывала 26,7 ГБ при 15 ГБ на диске)."""
    if os.path.isfile(path) or os.path.islink(path):
        try:
            st = os.lstat(path)
            return st.st_blocks * 512 if st.st_nlink == 1 else 0
        except OSError:
            return 0
    s, multi = 0, {}
    for dp, dn, fn in os.walk(path, followlinks=False):
        for n in fn:
            try:
                st = os.lstat(os.path.join(dp, n))
            except OSError:
                continue
            if st.st_nlink == 1:
                s += st.st_blocks * 512
            else:
                k = (st.st_dev, st.st_ino)
                seen = multi.get(k, (0, st.st_nlink, st.st_blocks))
                multi[k] = (seen[0] + 1, st.st_nlink, st.st_blocks)
    return s + sum(b * 512 for c, nl, b in multi.values() if c >= nl)


def code_mentions(roots):
    """Имена подпапок, которые называет код: {корень: {имя, 'tmp/имя', …}}. Источник — git ls-files репо (без памяти и доков)."""
    names = {r: set() for r in roots}
    try:
        files = subprocess.run(['git', '-C', REPO, 'ls-files', '--', *CODE_DIRS], capture_output=True, text=True,
                               timeout=60).stdout.split('\n')
    except (OSError, subprocess.SubprocessError):
        return None
    pats = {r: re.compile(re.escape(r) + r'/([\w.-]+)(?:/([\w.-]+))?') for r in roots}
    for f in files:
        p = os.path.join(REPO, f)
        if not f or not os.path.isfile(p) or os.path.getsize(p) > 4 * 2 ** 20:
            continue
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        for r, rx in pats.items():
            if r not in text:
                continue
            for a, b in rx.findall(text):
                names[r].add(a)
                if b:
                    names[r].add(a + '/' + b)
            if r == 'scout-scenes':   # путь через join: имя в кавычках в файле, где назван корень
                names[r].update(re.findall(r"""['"]([\w.-]+)['"]""", text))
    return names


def plan(rules, mentions, now=None):
    """Список к удалению [(путь, байт, вид, причина)] и оставленных с причиной [(путь, причина)]."""
    now = now or time.time()
    d_cut = now - float(rules.get('dir_days', 7)) * 86400
    l_cut = now - float(rules.get('log_days', 14)) * 86400
    uid = os.getuid()
    out, kept = [], []
    for R in rules['roots']:
        root = expand(R['path'])
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        rname = os.path.basename(root.rstrip('/'))
        only = [re.compile(x) for x in R.get('only') or []]
        never = set(R.get('never') or [])
        keep = set(R.get('keep') or [])
        keep_files = set(R.get('keep_files') or [])
        said = mentions.get(rname, set()) if mentions is not None else None
        conts = [c for c in R.get('containers') or [] if os.path.isdir(os.path.join(root, c))]
        for base, prefix in [(root, '')] + [(os.path.join(root, c), c + '/') for c in conts]:
            for name in sorted(os.listdir(base)):
                rel = prefix + name
                p = os.path.join(base, name)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if os.path.islink(p) or st.st_uid != uid:
                    continue
                if os.path.isdir(p):
                    if not prefix and name in conts:
                        continue
                    if rel in keep or name in never or rel in never:
                        kept.append((p, 'в списке keep/never'))
                        continue
                    if only and not any(rx.search(name) for rx in only):
                        continue   # не рабочая папка — молча мимо (белый список)
                    if said is None:
                        kept.append((p, 'код не прочитан — не трогаю'))
                        continue
                    if rel in said or (not prefix and name in said):
                        kept.append((p, 'называет код'))
                        continue
                    if newest_after(p, d_cut):
                        continue
                    out.append((p, du(p), 'папка', f'свежий файл {newest_days(p):.0f} сут'))
                elif R.get('logs') and fnmatch.fnmatch(name, '*.log') and name not in keep_files and st.st_mtime < l_cut:
                    out.append((p, st.st_blocks * 512, 'журнал', f'{(now - st.st_mtime) / 86400:.0f} сут'))
    return out, kept


def inside(p, rules):
    """Путь — подпапка/файл корня из правил на глубине 1–2 и не сам корень или контейнер (страховка перед rmtree)."""
    rp = os.path.realpath(p)
    for R in rules['roots']:
        root = os.path.realpath(expand(R['path']))
        rel = os.path.relpath(rp, root)
        if rel.startswith('..') or rel == '.':
            continue
        parts = rel.split(os.sep)
        if len(parts) == 1 and parts[0] not in (R.get('containers') or []):
            return True
        if len(parts) == 2 and parts[0] in (R.get('containers') or []):
            return True
    return False


def remove(items, rules, now=None):
    now = now or time.time()
    d_cut = now - float(rules.get('dir_days', 7)) * 86400
    freed, fails = 0, []
    for p, size, kind, _ in items:
        if not inside(p, rules) or os.path.islink(p):
            fails.append(f'{p}: вне корней правил')
            continue
        try:
            if kind == 'папка':
                if newest_after(p, d_cut):   # пока считали — кто-то записал
                    fails.append(f'{p}: появился свежий файл, оставлена')
                    continue
                errs = []
                shutil.rmtree(p, onerror=lambda f, x, e: errs.append(f'{x}: {e[1]}'))
                if errs:
                    fails.append(f'{p}: {len(errs)} ошибок, первая {errs[0]}')
                freed += size - (du(p) if os.path.exists(p) else 0)
            else:
                os.remove(p)
                freed += size
        except OSError as e:
            fails.append(f'{p}: {e}')
    return freed, fails


def main(argv):
    if '--selftest' in argv:
        return selftest()
    apply = '--apply' in argv
    rules = json.load(open(RULES, encoding='utf-8'))
    roots = {os.path.basename(expand(R['path']).rstrip('/')) for R in rules['roots']}
    mentions = code_mentions(roots)
    items, kept = plan(rules, mentions)
    total = sum(s for _, s, _, _ in items)
    by_root = {}
    for p, s, kind, why in items:
        print(f"{'удаляю' if apply else 'удалю'}: {p} — {s / 2 ** 20:.0f} МБ ({kind}, {why})")
        r = os.path.relpath(p, home()).split(os.sep)[0]
        by_root[r] = by_root.get(r, 0) + s
    for p, why in kept:
        print(f'оставлено: {p} — {why}')
    if mentions is None:
        print('WARN:disk_keeper: список папок, которые называет код, не прочитан (git) — проверенные кодом папки не тронуты')
    freed, fails = (remove(items, rules) if apply else (0, []))
    for f in fails[:10]:
        print(f'не удалено: {f}')
    if fails:
        print(f'WARN:disk_keeper: не удалено {len(fails)} из {len(items)} (первое: {fails[0][:150]})')
    free = shutil.disk_usage(home()).free / GB
    parts = ', '.join(f'{r} {s / GB:.1f}' for r, s in sorted(by_root.items(), key=lambda x: -x[1]))
    if apply:
        line = f'диск: свободно {free:.0f} ГБ, убрано {freed / GB:.1f} ГБ' + (f' ({parts})' if parts else '')
    else:
        line = f'диск: свободно {free:.0f} ГБ, уберу {total / GB:.1f} ГБ — сухой прогон' + (f' ({parts})' if parts else '')
    print(('DIGEST:' if '--digest' in argv else '') + line)
    warn = float(rules.get('warn_free_gb', 30))
    if free < warn:
        print(f'WARN:disk_free: на диске DEV свободно {free:.0f} ГБ (порог {warn:.0f}) — ночная сборка и волна мешей встанут на '
              f'полном диске; крупнейшее — ~/scout-scenes/meshes-hunyuan (болванки — ADR-0233, решает владелец)')
    return 0


def selftest():
    import tempfile
    sys.path.insert(0, os.path.join(REPO, 'tools', 'scout'))
    try:
        import remlab_tmp
        remlab_tmp.use('disk_keeper_selftest')
    except ImportError:
        pass
    bad = []

    def ok(cond, msg):
        print(('  ok  ' if cond else '  FAIL ') + msg)
        if not cond:
            bad.append(msg)

    h = tempfile.mkdtemp(prefix='disk-keeper-')
    os.environ['DISK_KEEPER_HOME'] = h
    old = time.time() - 10 * 86400
    oldlog = time.time() - 20 * 86400

    def mk(rel, t=None, body='x' * 5000):
        p = os.path.join(h, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').write(body)
        if t:
            os.utime(p, (t, t))
        return p

    def age(rel, t):   # папки — после файлов: запись файла двигает mtime папки
        for dp, dn, fn in os.walk(os.path.join(h, rel), topdown=False):
            os.utime(dp, (t, t))

    mk('remlab-scratch/t1/a.txt', old)
    mk('remlab-scratch/t2/a.txt', old)
    mk('remlab-scratch/t2/sub/fresh.txt')                       # свежий файл глубоко — папка живая
    mk('remlab-scratch/parity/run-1/x', old)                    # keep
    mk('remlab-scratch/tmp/t9/x', old)                          # подпапка контейнера
    mk('remlab-scratch/tmp/node-compile-cache/x', old)          # keep контейнера
    mk('remlab-scratch/old.log', oldlog)
    mk('remlab-scratch/new.log')
    mk('remlab-scratch/said/x', old)                            # называет код
    mk('remlab-logs/t5/x', old)
    mk('remlab-logs/heavy-slot.log', oldlog)                    # keep_files
    mk('remlab-logs/z.log', oldlog)
    mk('scout-scenes/t32-work/x', old)
    mk('scout-scenes/pinwork/x', old)
    mk('scout-scenes/meshes-hunyuan/t1/shape.glb', old)        # never
    mk('scout-scenes/mesh-color/x', old)                        # не рабочая — не в only
    mk('scout-scenes/t77-frames/x', old)                        # рабочая, но код зовёт её по имени в кавычках
    a = mk('remlab-logs/hl/a', body='y' * 40000)                # жёсткие ссылки: внутри дерева — считаются, наружу — нет
    os.link(a, os.path.join(h, 'remlab-logs/hl/b'))
    ok(du(os.path.join(h, 'remlab-logs/hl')) >= 40000, 'du: обе ссылки внутри — файл посчитан один раз')
    os.link(a, os.path.join(h, 'remlab-scratch/outside-link'))
    ok(du(os.path.join(h, 'remlab-logs/hl')) == 0, 'du: ссылка наружу — удаление места не вернёт, 0')
    for x in ('remlab-logs/hl/a', 'remlab-logs/hl/b', 'remlab-scratch/outside-link'):
        os.remove(os.path.join(h, x))
    os.rmdir(os.path.join(h, 'remlab-logs/hl'))
    for d in ('remlab-scratch/t1', 'remlab-scratch/parity', 'remlab-scratch/tmp/t9', 'remlab-scratch/tmp/node-compile-cache',
              'remlab-scratch/said', 'remlab-logs/t5', 'scout-scenes/t32-work', 'scout-scenes/pinwork', 'scout-scenes/meshes-hunyuan',
              'scout-scenes/mesh-color', 'scout-scenes/t77-frames'):
        age(d, old)
    age('remlab-scratch/t2', old)
    os.utime(os.path.join(h, 'remlab-scratch/t2/sub/fresh.txt'))
    os.symlink(os.path.join(h, 'remlab-scratch/t1'), os.path.join(h, 'remlab-scratch/link-old'))
    rules = json.load(open(RULES, encoding='utf-8'))
    mentions = {'remlab-scratch': {'said'}, 'remlab-logs': set(), 'onb06-out': set(), 'scout-scenes': {'t77-frames'}}
    items, kept = plan(rules, mentions)
    got = {os.path.relpath(p, h) for p, _, _, _ in items}
    want = {'remlab-scratch/t1', 'remlab-scratch/tmp/t9', 'remlab-scratch/old.log', 'remlab-logs/t5', 'remlab-logs/z.log',
            'scout-scenes/t32-work', 'scout-scenes/pinwork'}
    ok(got == want, f'к удалению ровно белый список старого: лишнее {sorted(got - want)}, нет {sorted(want - got)}')
    ok('remlab-scratch/t2' not in got, 'свежий файл в глубине держит папку')
    ok(not any('meshes-hunyuan' in g or 'mesh-color' in g for g in got), 'хранилище мешей и не-рабочие папки scout-scenes не трогаются')
    ok('remlab-logs/heavy-slot.log' not in got, 'живой журнал keep_files остаётся')
    ok('remlab-scratch/link-old' not in got, 'ссылка не трогается')
    ok(any(p.endswith('remlab-scratch/said') and w == 'называет код' for p, w in kept), 'папка, которую называет код, — оставлена с причиной')
    ok(any(p.endswith('t77-frames') for p, _ in kept), 'scout-scenes: имя в кавычках в коде — оставлена')
    items2, kept2 = plan(rules, None)
    ok(not any(os.path.isdir(p) for p, _, _, _ in items2), 'код не прочитан — ни одной папки к удалению')
    ok(inside(os.path.join(h, 'remlab-scratch/t1'), rules) and not inside(os.path.join(h, 'remlab-scratch/tmp'), rules)
       and not inside(os.path.join(h, 'remlab-scratch'), rules) and not inside(h, rules), 'страховка: корень и контейнер — вне удаляемого')
    # гонка: между расчётом и удалением в папке появился файл — остаётся
    mk('remlab-scratch/t1/late.txt')
    freed, fails = remove(items, rules)
    ok(os.path.isdir(os.path.join(h, 'remlab-scratch/t1')) and any('свежий файл' in f for f in fails), 'гонка: свежий файл — папка оставлена')
    ok(not os.path.exists(os.path.join(h, 'remlab-scratch/tmp/t9')) and os.path.isdir(os.path.join(h, 'remlab-scratch/tmp')),
       'подпапка контейнера удалена, контейнер на месте')
    ok(not os.path.exists(os.path.join(h, 'scout-scenes/t32-work')) and os.path.exists(os.path.join(h, 'scout-scenes/meshes-hunyuan/t1/shape.glb')),
       'рабочая папка scout-scenes удалена, болванка на месте')
    ok(not os.path.exists(os.path.join(h, 'remlab-logs/z.log')) and os.path.exists(os.path.join(h, 'remlab-logs/heavy-slot.log')),
       'старый журнал удалён, живой на месте')
    ok(os.path.exists(os.path.join(h, 'remlab-scratch/t2/sub/fresh.txt')) and os.path.islink(os.path.join(h, 'remlab-scratch/link-old')),
       'живая папка и ссылка целы')
    ok(freed > 0, f'убрано байт: {freed}')
    # сухой прогон через main: ничего не удаляет, строка DIGEST и WARN при пороге
    mk('remlab-logs/t6/x', old)
    age('remlab-logs/t6', old)
    rules_t = dict(rules, warn_free_gb=10 ** 9)
    rp = os.path.join(h, 'rules.json')
    json.dump(rules_t, open(rp, 'w'))
    env = dict(os.environ, DISK_KEEPER_HOME=h, DISK_KEEPER_RULES=rp)
    r = subprocess.run([sys.executable, os.path.abspath(__file__), '--digest'], capture_output=True, text=True, env=env, timeout=120)
    ok(r.returncode == 0 and os.path.isdir(os.path.join(h, 'remlab-logs/t6')), 'сухой прогон ничего не удаляет')
    ok('DIGEST:диск: свободно' in r.stdout and 'сухой прогон' in r.stdout and 'удалю: ' in r.stdout, 'сухой прогон: «удалю» и строка DIGEST')
    ok('WARN:disk_free:' in r.stdout, 'свободно меньше порога — WARN:disk_free')
    r = subprocess.run([sys.executable, os.path.abspath(__file__), '--apply', '--digest'], capture_output=True, text=True, env=env, timeout=120)
    ok(r.returncode == 0 and not os.path.exists(os.path.join(h, 'remlab-logs/t6')) and 'убрано' in r.stdout, '--apply удаляет и пишет «убрано»')
    shutil.rmtree(h, ignore_errors=True)
    print(f"\n{'OK' if not bad else 'FAIL'}: провалов {len(bad)}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
