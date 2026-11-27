#!/usr/bin/env python3
"""Тест сторожа «браузер в крон-шаге — только через heavy-slot» (T-20261127-175/demo-live-slot): боевое дерево чистое; шаг demo_live под очередью с заявкой 3 ГБ / 3 ядра;
отрицательный контроль — старая строка шага (мимо очереди) красная и называет шаг; сломанная/не запустившаяся проверка — код ≠0 и строка с причиной (не «чисто»).
Шаг при «не дождался очереди» (код 124) — красный с причиной «очередь heavy-slot занята больше N мин»; другие коды heavy-slot и успех проходят как есть (проверено на заглушках).

ОГРАНИЧЕНИЕ СТОРОЖА (честно): не видит имена файлов, собранные в переменных (`"$DIR/$name"`), вызовы через `eval`/`xargs`, крон-входы вне `infra/dev/crontab` и шагов
`refresh_daily.sh`; обфускацию не ловит — страховка от забытой обёртки, не граница безопасности. Два известных шага мимо очереди — «ДОЛГ» в `exempt` (до обёртки).
Запуск: python tools/scout/tests/test_heavy_slot_guard.py (стандартная библиотека, нужен git)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_heavy_slot_guard')
GUARD = os.path.join(ROOT, 'tools', 'ops', 'heavy_slot_guard.py')
RULES = 'tools/scout/rules/heavy-slot-guard.json'
REFRESH = 'tools/scout/refresh_daily.sh'
CRONTAB = 'infra/dev/crontab'
NEED = [RULES, REFRESH, CRONTAB, 'tools/ops/demo-live.sh', 'tools/ops/demo-warm.sh', 'tools/ops/demo-warm.mjs', 'tools/ops/node-env.sh', 'tools/ops/demo-walk/page-check.mjs',
        'tools/ops/heavy-slot.sh']
FAILS = []


def check(name, cond, info=''):
    if not cond:
        FAILS.append(name + (' — ' + str(info)[:300] if info else ''))


def guard(*args):
    r = subprocess.run([sys.executable, '-I', GUARD, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    return r.returncode, (r.stdout + r.stderr)


def copy_world():
    """Копия нужных файлов боевого дерева во временный git-репозиторий (сторож берёт список файлов из git)."""
    d = tempfile.mkdtemp(prefix='hsg-')
    for rel in NEED:
        dst = os.path.join(d, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), dst)
    subprocess.run(['git', 'init', '-q', d], check=True)
    return d


def commit_all(d):
    subprocess.run(['git', '-C', d, 'add', '-A'], check=True)


def edit(d, rel, fn):
    p = os.path.join(d, rel)
    s = open(p, encoding='utf-8').read()
    t = fn(s)
    assert t != s, 'правка не применилась: ' + rel
    open(p, 'w', encoding='utf-8').write(t)


# ---- 1. боевое дерево: чисто, и шаг demo_live — под очередью с заявкой из задачи
rc, out = guard()
check('боевое дерево чистое (код 0)', rc == 0, out)
check('боевое дерево: итоговая строка', 'идут через heavy-slot' in out, out)
src = open(os.path.join(ROOT, REFRESH), encoding='utf-8').read()
m = re.search(r'^step demo_live (.*)$', src, re.M)
check('шаг demo_live есть в refresh_daily.sh', bool(m))
line = m.group(1) if m else ''
check('demo_live: вызов через heavy-slot.sh с меткой demo-live', 'bash ../ops/heavy-slot.sh demo-live ' in line, line)
check('demo_live: заявка 3 ГБ и 3 ядра', '--min-gb 3' in line and '--cores 3' in line, line)
check('demo_live: ожидание очереди ограничено (--timeout), число — последним аргументом', '--timeout "$0"' in line and re.search(r"' (\d+)$", line) is not None, line)
check('demo_live: сама проверка после `--`', '-- bash ../ops/demo-live.sh;' in line, line)
check('demo_live: ожидание — не больше часа (шаг своего таймаута не имеет)', re.search(r"' (\d+)$", line) is not None and int(re.search(r"' (\d+)$", line).group(1)) <= 3600, line)

# ---- 1б. поведение шага на заглушках: не дождался (124) → красный с причиной; успех и иные коды — как есть
d = tempfile.mkdtemp(prefix='hsg-run-')
os.makedirs(os.path.join(d, 'tools', 'scout'))
os.makedirs(os.path.join(d, 'tools', 'ops'))


def run_step(slot_rc, live_rc=0):
    open(os.path.join(d, 'tools', 'ops', 'heavy-slot.sh'), 'w').write(
        '#!/bin/bash\n[ "$SLOT_RC" = 0 ] && { shift 1; while [ "$1" != -- ]; do shift; done; shift; exec "$@"; }\nexit "$SLOT_RC"\n')
    open(os.path.join(d, 'tools', 'ops', 'demo-live.sh'), 'w').write('#!/bin/bash\necho live-ran\nexit %d\n' % live_rc)
    r = subprocess.run(['bash', '-c', line], cwd=os.path.join(d, 'tools', 'scout'), env=dict(os.environ, SLOT_RC=str(slot_rc)),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout + r.stderr


rc, out = run_step(124)
check('не дождался очереди (124) → шаг красный (код 124)', rc == 124, (rc, out))
check('не дождался очереди → причина «очередь heavy-slot занята больше 60 мин»', 'очередь heavy-slot занята больше 60 мин' in out and 'ERROR:demo_live' in out, out)
check('не дождался очереди → проверка демо не запускалась', 'live-ran' not in out, out)
rc, out = run_step(0)
check('слот взят → проверка демо идёт, код 0, без ERROR', rc == 0 and 'live-ran' in out and 'ERROR' not in out, (rc, out))
rc, out = run_step(0, live_rc=1)
check('слот взят, проверка красная → код 1 доходит до шага', rc == 1 and 'live-ran' in out and 'ERROR' not in out, (rc, out))
rc, out = run_step(3)
check('иной код heavy-slot (3) → как есть, без ложной причины про очередь', rc == 3 and 'занята' not in out, (rc, out))
shutil.rmtree(d, ignore_errors=True)
rules = json.load(open(os.path.join(ROOT, RULES), encoding='utf-8'))
for k, why in rules['exempt'].items():
    check('исключение %s: причина ≥15 знаков' % k, isinstance(why, str) and len(why) >= 15)
check('demo_live в исключения не спрятан', 'step:demo_live' not in rules['exempt'])
b, s = re.compile(rules['browser_pattern']), re.compile(rules['slot_pattern'])
check('шаблон: запуск playwright виден', b.search('pnpm exec playwright test -c playwright.live.config.ts') is not None)
check('шаблон: настройка PLAYWRIGHT_* — не запуск', b.search('export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"') is None)
check('шаблон: heavy-slot.sh виден как очередь', s.search('bash ../ops/heavy-slot.sh demo-live') is not None)

# ---- 2. отрицательный контроль: старая строка шага (мимо очереди) → красный, назван шаг и файл с браузером; вернули → чисто
d = copy_world()
commit_all(d)
rc, out = guard('--root', d)
check('копия мира (как в main) чистая', rc == 0, out)
edit(d, REFRESH, lambda t: re.sub(r'^step demo_live .*$', 'step demo_live bash ../ops/demo-live.sh', t, flags=re.M))
commit_all(d)
rc, out = guard('--root', d)
check('шаг без heavy-slot → код ≠0', rc != 0, out)
check('шаг без heavy-slot → назван шаг и файл с браузером', 'step:demo_live' in out and 'demo-live.sh' in out, out)
edit(d, REFRESH, lambda t: re.sub(r'^step demo_live .*$', 'step demo_live bash ../ops/heavy-slot.sh demo-live --min-gb 3 --cores 3 --timeout 3600 -- bash ../ops/demo-live.sh', t, flags=re.M))
rc, out = guard('--root', d)
check('вернули обёртку → чисто', rc == 0, out)
# новый шаг с playwright мимо очереди → красный (сторож не про один demo_live)
edit(d, REFRESH, lambda t: t + '\nstep nov_shot bash -c "cd .. && pnpm exec playwright test -c x.config.ts"\n')
rc, out = guard('--root', d)
check('новый шаг с playwright без очереди → красный, назван', rc != 0 and 'step:nov_shot' in out, out)
shutil.rmtree(d, ignore_errors=True)

# ---- 3. сломанная / не запустившаяся проверка — код ≠0 и строка с причиной
d = copy_world()
commit_all(d)
open(os.path.join(d, RULES), 'w', encoding='utf-8').write('{плохой json')
rc, out = guard('--root', d)
check('битый файл правил → код ≠0 с причиной', rc != 0 and 'не запустился' in out, out)
os.remove(os.path.join(d, RULES))
rc, out = guard('--root', d)
check('нет файла правил → код ≠0 с причиной', rc != 0 and 'не запустился' in out, out)
shutil.rmtree(d, ignore_errors=True)

d = copy_world()
commit_all(d)
open(os.path.join(d, REFRESH), 'w', encoding='utf-8').write('# шагов нет\n')
open(os.path.join(d, CRONTAB), 'w', encoding='utf-8').write('# пусто\n')
commit_all(d)
rc, out = guard('--root', d)
check('входов не нашли → код ≠0 (слепая проверка)', rc != 0 and 'слепая' in out, out)
shutil.rmtree(d, ignore_errors=True)

d = tempfile.mkdtemp(prefix='hsg-nogit-')          # не git-репозиторий: список файлов не получить
os.makedirs(os.path.join(d, 'tools', 'scout', 'rules'))
shutil.copy(os.path.join(ROOT, RULES), os.path.join(d, RULES))
rc, out = guard('--root', d)
check('нет git-репозитория → код ≠0 с причиной', rc != 0 and 'не запустился' in out, out)
shutil.rmtree(d, ignore_errors=True)

# ---- 4. исключения: без причины и мёртвое — красные
d = copy_world()
commit_all(d)
r2 = json.load(open(os.path.join(d, RULES), encoding='utf-8'))
r2['exempt']['step:demo_warm'] = 'коротко'
json.dump(r2, open(os.path.join(d, RULES), 'w', encoding='utf-8'), ensure_ascii=False)
rc, out = guard('--root', d)
check('исключение без причины → красный', rc != 0 and 'без причины' in out, out)
r2['exempt']['step:demo_warm'] = 'ДОЛГ: прогрев кадров без очереди, обернуть отдельной задачей'
r2['exempt']['step:уже_нет'] = 'такого шага давно нет в refresh_daily'
json.dump(r2, open(os.path.join(d, RULES), 'w', encoding='utf-8'), ensure_ascii=False)
rc, out = guard('--root', d)
check('мёртвое исключение → красный', rc != 0 and 'такого входа нет' in out, out)
shutil.rmtree(d, ignore_errors=True)

# ---- 5. собственная самопроверка сторожа
rc, out = guard('--selftest')
check('selftest сторожа: код 0', rc == 0, out)
check('selftest сторожа: строка итога', 'ошибок 0' in out, out)

print('test_heavy_slot_guard: ошибок %d' % len(FAILS))
for f in FAILS:
    print('  ПРОВАЛ: ' + f)
sys.exit(1 if FAILS else 0)
