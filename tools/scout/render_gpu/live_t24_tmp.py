"""ОДНОРАЗОВАЯ проверка вживую T-24/1 (не коммитить): on → прогрелась → status → повторный on → автостоп (3 мин) → stopped;
затем потолок на копеечном $ (стоп по потолку). Сообщения владельцу — сухо (RENDER_MACHINE_DRY): в журнал, не в Telegram."""
import os
import subprocess
import sys
import time

RM = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_machine.py')
PY = os.path.expanduser('~/venvs/scout/bin/python')
ENV = dict(os.environ, RENDER_MACHINE_DRY='1')


def run(cmd, over=None):
    env = dict(ENV)
    if over:
        env['RENDER_MACHINE_OVERRIDE'] = over
    r = subprocess.run([PY, RM] + cmd, capture_output=True, text=True, env=env, timeout=600)
    print(time.strftime('%H:%M:%S', time.gmtime()), '$', ' '.join(cmd), '→', (r.stdout.strip() or r.stderr.strip())[:300], flush=True)
    return r.stdout


def until(pred_text, over, limit_s, step=45):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        out = run(['tick'], over)
        if pred_text in out or 'остановк' in out and 'stop' in out:
            pass
        st = run(['status', '--json'], over)
        if pred_text in st:
            return True
        time.sleep(step)
    return False


OVER = '{"idle_stop_min": 3}'
print('=== 1. status до', flush=True)
run(['status'], OVER)
print('=== 2. on', flush=True)
run(['on', '--by', 'live-test'], OVER)
t0 = time.time()
warm = False
while time.time() - t0 < 900:
    out = run(['tick'], OVER)
    if 'готова, фото считается' in out or 'warm' in out:
        warm = True
    s = run(['status'], OVER)
    if 'прогрелась' in s:
        warm = True
        break
    time.sleep(40)
print('=== прогрелась:', warm, 'за', round(time.time() - t0), 'с', flush=True)
print('=== 3. повторный on (та же группа, без перезапуска)', flush=True)
run(['on', '--by', 'live-test-2'], OVER)
run(['status'], OVER)
print('=== 4. автостоп: ждём 3 мин простоя без pulse', flush=True)
t1 = time.time()
while time.time() - t1 < 420:
    out = run(['tick'], OVER)
    if 'stop' in out.split('действия=')[-1]:
        break
    time.sleep(40)
for _ in range(8):
    s = run(['status', '--json'], OVER)
    if '"status": "stopped"' in s:
        break
    run(['tick'], OVER)
    time.sleep(20)
print('=== 5. потолок на малом $ посреди работы', flush=True)
import json
sp = json.loads(run(['status', '--json'], OVER))['spent_usd']
CAP = json.dumps({'idle_stop_min': 3, 'day_cap_usd': round(sp + 0.003, 5)})
print('потрачено сегодня', sp, 'потолок для проверки', CAP, flush=True)
run(['on', '--by', 'cap-test'], CAP)
t2 = time.time()
while time.time() - t2 < 600:
    out = run(['tick'], CAP)
    if 'stop' in out.split('действия=')[-1]:
        break
    time.sleep(30)
for _ in range(8):
    s_ = run(['status', '--json'], CAP)
    if '"status": "stopped"' in s_:
        break
    run(['tick'], CAP)
    time.sleep(20)
print('=== повторный on при исчерпанном потолке', flush=True)
run(['on', '--by', 'cap-test-2'], CAP)
print('=== итог: off и проверка', flush=True)
run(['off', '--by', 'live-test'], OVER)
run(['status', '--json'], OVER)
