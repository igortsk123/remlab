"""Утренняя сводка ночного прогона не уходит пустой (T-20261104-11).
- refresh_digest.py на фикстуре RES_FILE: FAIL-шаг (enrich) и WARN, порванный обрезкой `cut -c1-200` посреди буквы, — текст
  собран, статус записан (до 04.11 вставка падала на UnicodeDecodeError и владельцу уходило «алерт без текста»);
- сломанный вход (нет RES_FILE, мусор в числах) — громкое «СВОДКА НЕ СОБРАЛАСЬ» с ошибкой и FAIL-шагами, статус overall=FAIL;
- finish() из refresh_daily.sh целиком, как в кроне (env -i, C-локаль, настоящие step() и cut): текст с FAIL; python не
  запустился — аварийный текст из bash;
- alert.sh: пустой/пробельный текст — громкая строка, не «алерт без текста».
Без TG и прода: alert.sh только с ALERT_DRY=1, а в finish() — заглушка; publish_status, products_count и rm — заглушки.
    ~/venvs/scout/bin/python tools/scout/tests/test_refresh_digest.py"""
import json
import os
import subprocess
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_refresh_digest')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
sys.path.insert(0, SCOUT)
import refresh_digest as RD  # noqa: E402

fails = 0
LONG = 'кандидат банка: ячейка не удержана — размер конвенции поменялся, а не на массовое выбытие товаров; ' * 3


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


def cron_env(**kw):
    """Окружение как у крона: без LANG/LC_* (C-локаль), минимальный PATH."""
    return {'HOME': os.environ.get('HOME', '/tmp'), 'PATH': '/usr/bin:/bin', 'SHELL': '/bin/bash', **kw}


def fixture(d):
    res = os.path.join(d, 'res.tsv')
    cut = ('\t'.join(['layout_page', 'warn', '3', '']).encode() + LONG.encode()[:199] + b'\n')   # 199 байт — буква пополам
    with open(res, 'wb') as f:
        f.write(b'feeds\tok\t0\t\nenrich\tFAIL\t0\t\njudge\tskipped\t0\t\n' + cut)
    log = os.path.join(d, 'refresh.log')
    open(log, 'w', encoding='utf-8').write('=== 2026-11-03 10:40:00 старт ===\nДЕЛЬТА вчера\n'
                                           '=== 2026-11-04 10:40:00 старт ===\nДЕЛЬТА новых: 27\nDIGEST:кандидат банка: удержано 80\n')
    fresh = os.path.join(d, 'ff.json')
    json.dump({'a': {'state': 'fresh'}, 'b': {'state': 'stale'}}, open(fresh, 'w'))
    return dict(REFRESH_RC='0', STATUS_FILE=os.path.join(d, 'refresh-status.json'), RES_FILE=res, TODAY='2026-11-04',
                STARTED='2026-11-04T10:40:00Z', FEEDS_OK='1', DL_OK='10', DL_TOTAL='10', DEAD='', PRODUCTS='17672',
                LOG_FILE=log, FRESH_FILE=fresh)


def run_digest(env):
    r = subprocess.run([sys.executable, os.path.join(SCOUT, 'refresh_digest.py')], env=cron_env(**env),
                       capture_output=True, cwd=SCOUT)
    return r.returncode, r.stdout.decode('utf-8'), r.stderr.decode('utf-8', 'replace')


with tempfile.TemporaryDirectory() as d:
    env = fixture(d)
    rc, out, err = run_digest(env)
    st = json.load(open(env['STATUS_FILE'], encoding='utf-8'))
    check('сводка собрана при порванной букве WARN (C-локаль, как в кроне)', rc == 0 and out.startswith('remlab каталог 2026-11-04: прогон С ОШИБКАМИ'), out + err)
    check('FAIL-шаг виден в тексте', 'FAIL: enrich' in out, out)
    check('WARN в тексте, без битого хвоста', 'WARN layout_page ×3: кандидат банка' in out and '�' not in out, out)
    check('дельта и DIGEST — только сегодняшние', 'дельта: новых: 27' in out and 'кандидат банка: удержано 80' in out and 'вчера' not in out, out)
    check('пропущенные и свежесть фидов', 'пропущено (openai.off): judge' in out and 'свежих 1/2' in out, out)
    check('статус записан: overall=FAIL, fails=[enrich], дата', st['overall'] == 'FAIL' and st['fails'] == ['enrich'] and st['date'] == '2026-11-04', st)
    w = RD.read_res(env['RES_FILE'])['layout_page']
    check('read_res: порванный хвост срезан, а не заменён «�»', w[0] == 'warn' and LONG.startswith(w[2]) and len(w[2]) >= 90, w)

with tempfile.TemporaryDirectory() as d:
    env = fixture(d)
    env['RES_FILE'] = os.path.join(d, 'нет.tsv')
    rc, out, err = run_digest(env)
    st = json.load(open(env['STATUS_FILE'], encoding='utf-8'))
    check('нет RES_FILE — громко «СВОДКА НЕ СОБРАЛАСЬ» с ошибкой', 'СВОДКА НЕ СОБРАЛАСЬ — FileNotFoundError' in out, out)
    check('…и минимальный статус overall=FAIL с ошибкой', st['overall'] == 'FAIL' and 'FileNotFoundError' in st['digest_error'], st)
    check('…traceback — в stderr', 'Traceback' in err, err)
    env = fixture(d)
    env['PRODUCTS'] = 'Error response from daemon'
    rc, out, err = run_digest(env)
    check('мусор в числах — громко, со списком FAIL-шагов', 'СВОДКА НЕ СОБРАЛАСЬ — ValueError' in out and 'FAIL шагов: enrich' in out, out)

with tempfile.TemporaryDirectory() as d:     # важная строка `DIGEST:!` — всегда, вне лимита 6 последних (T-20261107-04/2)
    env = fixture(d)
    DEMO = 'демо не собрано и не опубликовано: состояние банка комнат не определено (bedroom) — на проде вчерашнее'
    open(env['LOG_FILE'], 'a', encoding='utf-8').write(f'DIGEST:!{DEMO}\n' + ''.join(f'DIGEST:обычная {i}\n' for i in range(1, 10)))
    rc, out, err = run_digest(env)
    lines = out.splitlines()
    check('DIGEST:! — в сводке за 9 обычными строками (лимит 6 её бы срезал), с ❗ и без «!»',
          rc == 0 and f'❗ {DEMO}' in lines and f'!{DEMO}' not in out, out)
    check('DIGEST:! — сразу за шапкой (дельтой), до обычных; обычных — 6 последних',
          lines.index(f'❗ {DEMO}') == lines.index('дельта: новых: 27') + 1
          and [x for x in lines if x.startswith('обычная')] == [f'обычная {i}' for i in range(4, 10)], out)
    yesterday = fixture(d)
    open(yesterday['LOG_FILE'], 'w', encoding='utf-8').write(f'=== 2026-11-03 10:40:00 старт ===\nDIGEST:!{DEMO}\n'
                                                            '=== 2026-11-04 10:40:00 старт ===\n')
    rc, out, err = run_digest(yesterday)
    check('DIGEST:! — только сегодняшняя ночь (вчерашняя важная строка не повторяется)', rc == 0 and DEMO not in out, out)

DRIVER = r'''
set -u
SRC="$1"; D="$2"; PY="$3"
cd "$(dirname "$SRC")"
LOG="$D/refresh.log"; STATUS="$D/refresh-status.json"; today=2026-11-04
declare -A RES; declare -A WARNS; declare -A WARNN
STARTED=2026-11-04T10:40:00Z; ok=1; dl_ok=10; dl_total=10; dead=""
STEP_TMP="$D/step.tmp"
eval "$(sed -n '/^step() {/,/^}/p; /^finish() {/,/^}/p' "$SRC")"
products_count() { echo 17672; }
publish_status() { echo "(тест) publish_status пропущен"; }
bash() { if [ "${1:-}" = alert.sh ]; then printf '%s' "${2-}" > "$D/alert.txt"; else command bash "$@"; fi; }
rm() { :; }
echo "=== 2026-11-04 10:40:00 старт ===" >> "$LOG"
step feeds true
step layout_page printf 'WARN:pins: %s\n' "$LONG"
step enrich false
trap finish EXIT
exit 0
'''


def run_finish(py):
    with tempfile.TemporaryDirectory() as d:
        drv = os.path.join(d, 'drv.sh')
        open(drv, 'w', encoding='utf-8').write(DRIVER)
        r = subprocess.run(['/bin/bash', drv, os.path.join(SCOUT, 'refresh_daily.sh'), d, py],
                           env=cron_env(LONG=LONG, ALERT_DRY='1'), capture_output=True)
        text = open(os.path.join(d, 'alert.txt'), encoding='utf-8').read() if os.path.exists(os.path.join(d, 'alert.txt')) else None
        st = os.path.exists(os.path.join(d, 'refresh-status.json'))
        return r, text, st


r, text, st = run_finish(sys.executable)
check('finish() как в кроне: текст ушёл в alert.sh, FAIL виден', bool(text) and 'FAIL: enrich' in text and 'WARN layout_page' in text,
      f'{text!r} {r.stderr.decode("utf-8", "replace")[-400:]}')
check('finish() как в кроне: статус записан', st)
r, text, st = run_finish('/bin/false')
check('python не запустился — аварийный текст из bash со списком FAIL', bool(text) and text.startswith('remlab каталог 2026-11-04: СВОДКА НЕ СОБРАЛАСЬ')
      and 'FAIL шагов: enrich' in text, repr(text))

for arg, name in (([''], 'пустой'), (['   \n'], 'пробельный'), ([], 'без аргумента')):
    r = subprocess.run(['/bin/bash', os.path.join(SCOUT, 'alert.sh'), *arg], env=cron_env(ALERT_DRY='1'), capture_output=True)
    out = r.stdout.decode('utf-8')
    check(f'alert.sh: {name} текст — громко', 'ПУСТОЙ АЛЕРТ' in out and 'без текста' not in out, out)
r = subprocess.run(['/bin/bash', os.path.join(SCOUT, 'alert.sh'), 'привет'], env=cron_env(ALERT_DRY='1'), capture_output=True)
check('alert.sh: обычный текст — как есть (сухо)', r.stdout.decode('utf-8').strip() == '[сухо] привет', r.stdout)

print('FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
