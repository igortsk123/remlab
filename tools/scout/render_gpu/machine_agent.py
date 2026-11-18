"""АГЕНТ ГОТОВНОСТИ РЕНДЕР-МАШИНЫ (T-20261117-24/1). Работает ВНУТРИ контейнера Salad (python из Blender), цель образа `agent`.

Что делает: на старте — `ready_probe.py` (GPU + малый настоящий Cycles-проход с OIDN, как «/ready»), затем раз в `AGENT_BEAT_S` секунд
кладёт на приёмник (`MESH_SINK_URL`/`MESH_SINK_TOKEN`) файл `rendermachine/ready.json`:
    {"boot_id", "ts", "ready", "device", "probe_sec", "probe_rc", "gpu_ok", "note"}
Контроллер (`render_machine.py tick`) читает его по ssh: «прогрелась» = группа `running` И `ready.json` свежий (моложе `ready_stale_s`),
написан ПОСЛЕ старта этого запуска (`ts` > время `/start`) и `ready: true`. Пропал свежий файл — машина «не отвечает».
Боевой воркер (T-24/2, `render_exec.py`) обязан писать ТОТ ЖЕ файл тем же форматом — этот агент заменяется им, контроллер не меняется.

Переменные: MESH_SINK_URL, MESH_SINK_TOKEN (из группы), AGENT_PREFIX (rendermachine), AGENT_BEAT_S (30), BLENDER_DIR, APP (/app).
Токен нигде не печатается."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

APP = os.environ.get('APP', '/app')
BL = os.environ.get('BLENDER_DIR', '/opt/blender') + '/blender'
PREFIX = os.environ.get('AGENT_PREFIX', 'rendermachine')
BEAT = int(os.environ.get('AGENT_BEAT_S', '30'))
BOOT = uuid.uuid4().hex[:12]
STATE = {'boot_id': BOOT, 'ts': 0, 'ready': False, 'device': None, 'probe_sec': None, 'probe_rc': None, 'gpu_ok': None, 'note': 'старт'}


def log(*a):
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def put(name, data):
    base = os.environ.get('MESH_SINK_URL', '').rstrip('/')
    if not base:
        return False
    try:
        req = urllib.request.Request(f'{base}/staging/{PREFIX}/{name}', data=data, method='PUT',
                                     headers={'Authorization': f"Bearer {os.environ.get('MESH_SINK_TOKEN', '')}",
                                              'Content-Type': 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True
    except Exception as e:  # noqa: BLE001 — недоставка видна контроллеру как «нет свежего файла»; причина — в журнале контейнера
        log('sink PUT', name, 'ОШИБКА', type(e).__name__, str(e)[:100])
        return False


def beat():
    STATE['ts'] = round(time.time(), 1)
    return put('ready.json', json.dumps(STATE, ensure_ascii=False).encode())


def gpu_alive():
    try:
        r = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and 'GPU' in r.stdout
    except Exception:  # noqa: BLE001
        return False


def probe():
    t = time.time()
    p = subprocess.run([BL, '-b', '--python-exit-code', '1', '-P', f'{APP}/ready_probe.py', '--', '--device', 'auto', '--require-gpu', '1',
                        '--out', '/tmp/ready.png'], capture_output=True, text=True)
    txt = p.stdout + p.stderr
    lines = [ln for ln in txt.splitlines() if ln.startswith(('DEVICE_', 'PROBE_'))]
    dev = next((ln.split(' ', 1)[1] for ln in lines if ln.startswith('PROBE_DEVICE')), None)
    STATE.update(probe_rc=p.returncode, probe_sec=round(time.time() - t, 1), device=dev, ready=(p.returncode == 0 and any(ln.startswith('PROBE_OK') for ln in lines)),
                 note='; '.join(lines[-3:])[:300])
    log('ready_probe rc', p.returncode, STATE['note'])


def main():
    log('агент готовности, boot', BOOT)
    beat()
    probe()
    STATE['gpu_ok'] = gpu_alive()
    beat()
    while True:
        time.sleep(BEAT)
        STATE['gpu_ok'] = gpu_alive()
        if not STATE['gpu_ok']:
            STATE['ready'] = False
            STATE['note'] = 'nvidia-smi не видит GPU'
        beat()


if __name__ == '__main__':
    sys.exit(main())
