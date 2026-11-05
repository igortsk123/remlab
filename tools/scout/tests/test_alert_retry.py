"""alert.sh повторяет отправку в Telegram (план ops-alert-retry, урок 551, T-20261105-31).
Без сети: в PATH подменены `curl` (исход каждой попытки — из плана: ok | код curl 28/35 | HTTP 400/429:retry_after/500)
и `sleep` (паузы записываются, не ждём). Каждый случай — своя папка с копией alert.sh и фиктивным .env.alert;
окружение как у крона (без LANG — C-локаль).
- сбой → сбой → успех: код 0, «попытка 3», паузы 15 и 45; три сбоя: код 1, `TG FAIL` с кодом curl и HTTP;
- HTTP 400 — без повтора; 429 — пауза retry_after (не больше 60 с); 500 — повтор;
- текст длиннее 4 000 знаков — части «(1/2)», «(2/2)» по строкам, длинная строка — по знакам без порванных букв;
  часть не ушла — остальные не шлём, код 1;
- токен не попадает ни в журналы, ни в вывод; ALERT_DRY=1, «TG не настроен» (код 2) и строка успеха с первой попытки — как раньше.
Папки случаев не удаляются: ALERT_TEST_DIR (иначе новая папка в tempdir).
    python3 tools/scout/tests/test_alert_retry.py"""
import os
import shutil
import subprocess
import sys
import tempfile

SCOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BASE = os.environ.get('ALERT_TEST_DIR') or tempfile.mkdtemp(prefix='alert-retry-')
TOKEN = 'FAKETOKEN-123456:abc'
fails = 0

FAKE_CURL = r'''#!/bin/bash
# подмена curl: исход попытки N — строка N файла plan; текст сообщения — в calls (через \0)
d="$FAKE_DIR"; n=$(( $(cat "$d/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$d/n"
text=""; prev=""
for a in "$@"; do [ "$prev" = --data-urlencode ] && text="${a#text=}"; prev="$a"; done
printf '%s\0' "$text" >> "$d/calls"
case "$(sed -n "${n}p" "$d/plan")" in
  ok)       printf '{"ok":true}\n200'; exit 0 ;;
  400)      printf '{"ok":false,"error_code":400}\n400'; exit 0 ;;
  500)      printf '{"ok":false,"error_code":500}\n500'; exit 0 ;;
  429:*)    o="$(sed -n "${n}p" "$d/plan")"; printf '{"ok":false,"error_code":429,"parameters":{"retry_after":%s}}\n429' "${o#429:}"; exit 0 ;;
  *)        printf '\n000'; exit "$(sed -n "${n}p" "$d/plan")" ;;
esac
'''
FAKE_SLEEP = '#!/bin/bash\necho "$1" >> "$FAKE_DIR/sleeps"\n'


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


def read(p):
    return open(p, encoding='utf-8').read() if os.path.exists(p) else ''


def run(case, text, plan=(), env_alert=True, **env):
    d = os.path.join(BASE, case)
    os.makedirs(os.path.join(d, 'bin'))
    shutil.copy(os.path.join(SCOUT, 'alert.sh'), d)
    if env_alert:
        open(os.path.join(d, '.env.alert'), 'w').write(f'TG_BOT_TOKEN={TOKEN}\nTG_CHAT_ID=42\n')
    open(os.path.join(d, 'plan'), 'w').write('\n'.join(plan) + '\n')
    for name, body in (('curl', FAKE_CURL), ('sleep', FAKE_SLEEP)):
        p = os.path.join(d, 'bin', name)
        open(p, 'w').write(body)
        os.chmod(p, 0o755)
    e = {'PATH': os.path.join(d, 'bin') + ':/usr/bin:/bin', 'HOME': d, 'FAKE_DIR': d, **env}
    r = subprocess.run(['/bin/bash', os.path.join(d, 'alert.sh'), text], env=e, capture_output=True)
    raw = open(os.path.join(d, 'calls'), 'rb').read() if os.path.exists(os.path.join(d, 'calls')) else b''
    calls = [c.decode('utf-8') for c in raw.split(b'\0')[:-1]]          # битый UTF-8 в части — исключение здесь
    out = {'rc': r.returncode, 'stdout': r.stdout.decode('utf-8', 'replace'), 'stderr': r.stderr.decode('utf-8', 'replace'),
           'sent': read(os.path.join(d, 'alert-sent.log')), 'fail': read(os.path.join(d, 'refresh-alert.log')),
           'sleeps': read(os.path.join(d, 'sleeps')).split(), 'calls': calls}
    leak = [k for k in ('stdout', 'stderr', 'sent', 'fail') if TOKEN in out[k] or 'FAKETOKEN' in out[k]]
    check(f'{case}: токена нет в журналах и выводе', not leak, str(leak))
    return out


o = run('ok-first', 'привет', ['ok'])
check('успех с первой попытки — код 0, строка как раньше', o['rc'] == 0 and o['sent'].endswith('TG ok: привет\n') and not o['sleeps'], o)

o = run('fail-fail-ok', 'сводка', ['28', '35', 'ok'])
check('сбой→сбой→успех — код 0, «попытка 3»', o['rc'] == 0 and 'TG ok (попытка 3): сводка' in o['sent'] and not o['fail'], o)
check('…паузы по умолчанию 15 и 45 с, три запроса', o['sleeps'] == ['15', '45'] and len(o['calls']) == 3, o)

o = run('fail3', 'сводка', ['28', '28', '35'], ALERT_PAUSES='0 0')
check('три сбоя — код 1, TG FAIL с кодом curl и HTTP последней', o['rc'] == 1 and 'TG FAIL (попыток 3, curl 35, HTTP 000): сводка' in o['fail']
      and not o['sent'], o)
check('…паузы из ALERT_PAUSES', o['sleeps'] == ['0', '0'], o)

o = run('http400', 'сводка', ['400', 'ok'])
check('HTTP 400 — без повтора, код 1', o['rc'] == 1 and len(o['calls']) == 1 and 'попыток 1, curl 0, HTTP 400' in o['fail'] and not o['sleeps'], o)

o = run('http429', 'сводка', ['429:7', 'ok'])
check('429 — пауза retry_after, потом успех', o['rc'] == 0 and o['sleeps'] == ['7'] and 'попытка 2' in o['sent'], o)
o = run('http429-cap', 'сводка', ['429:300', '429:300', 'ok'])
check('429 — пауза не больше 60 с', o['rc'] == 0 and o['sleeps'] == ['60', '60'], o)

o = run('http500', 'сводка', ['500', 'ok'], ALERT_PAUSES='0')
check('500 — повтор', o['rc'] == 0 and len(o['calls']) == 2 and o['sleeps'] == ['0'], o)

o = run('tries1', 'сводка', ['28', 'ok'], ALERT_TRIES='1')
check('ALERT_TRIES=1 — одна попытка', o['rc'] == 1 and len(o['calls']) == 1 and not o['sleeps'], o)

lines = [f'строка {i:03d}: ' + 'ж' * 50 for i in range(120)]                  # ~7 400 знаков
o = run('long', '\n'.join(lines), ['ok', 'ok'])
parts = [c.split('] ', 1)[1] for c in o['calls']]
check('длинный текст — 2 части «(1/2)», «(2/2)», код 0', o['rc'] == 0 and len(parts) == 2 and parts[0].startswith('(1/2) ')
      and parts[1].startswith('(2/2) '), [p[:12] for p in parts])
check('…части не длиннее 4 000 знаков, режутся по строкам, текст целиком',
      all(len(p) - 6 <= 4000 for p in parts) and '\n'.join(p[6:] for p in parts).split('\n') == lines, [len(p) for p in parts])
check('…в журнале успеха обе части', o['sent'].count('TG ok: (1/2)') == 1 and o['sent'].count('TG ok: (2/2)') == 1, o['sent'][:200])

one = 'ы' * 9000
o = run('long-line', 'шапка\n' + one, ['ok'] * 4)
parts = [c.split('] ', 1)[1] for c in o['calls']]
check('строка длиннее предела — по знакам, буквы целы (C-локаль)', o['rc'] == 0 and len(parts) == 4
      and ''.join(p.split(') ', 1)[1].replace('\n', '') for p in parts) == 'шапка' + one, [len(p) for p in parts])

o = run('long-fail', '\n'.join(lines), ['ok', '28', '28', '28', 'ok'], ALERT_PAUSES='0 0')
check('часть 2 не ушла — код 1, остальное не шлём', o['rc'] == 1 and len(o['calls']) == 4 and 'TG ok: (1/2)' in o['sent']
      and 'часть 2/2' in o['fail'], o['fail'][:200])

o = run('dry', 'привет', ['ok'], ALERT_DRY='1')
check('ALERT_DRY=1 — как раньше: текст в stdout, без запросов и журналов', o['rc'] == 0 and o['stdout'] == '[сухо] привет\n'
      and not o['calls'] and not o['sent'] and not o['fail'], o)
o = run('dry-empty', '', [], ALERT_DRY='1')
check('ALERT_DRY=1, пустой текст — громко', 'ПУСТОЙ АЛЕРТ' in o['stdout'], o)

o = run('no-config', 'привет', ['ok'], env_alert=False)
check('нет .env.alert — код 2, «TG не настроен», без запросов', o['rc'] == 2 and '(TG не настроен) привет' in o['fail'] and not o['calls'], o)

print(f'папки случаев: {BASE}')
print('FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
