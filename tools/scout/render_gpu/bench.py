#!/usr/bin/env python3
"""ЗАМЕР РЕНДЕРА НА КАРТЕ SALAD (T-20261117-22) — работает ВНУТРИ контейнера цели `bench`. Очередь и кнопки не делает: только измеряет.

Что делает: описание машины → /ready-проверка (`ready_probe.py`: GPU + малый настоящий Cycles) → план прогонов `BENCH_PLAN`
(«сцена:устройство:повторов», по умолчанию living:auto:3,bedroom:auto:2,living:cuda:1): пара C1+C2 в ОДНОМ процессе Blender, 64 выборки,
OIDN. Каждый прогон — строка в events.json (время процесса, сборка сцены, каждый кадр, загрузка видеокарты по nvidia-smi) и кадры PNG.
Всё уходит на приёмник (`MESH_SINK_URL`/`MESH_SINK_TOKEN`, префикс renderbench-1117/<RUN_ID>/) после КАЖДОГО шага — оборвут ноду, данные
останутся. В конце — строка DONE и ожидание (контейнер не перезапускается; группу гасит оператор). Секретов в образе нет: адрес и токен — env группы.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

T0 = time.time()
RUN_ID = os.environ.get('RUN_ID', 'run')
PREFIX = f'renderbench-1117/{RUN_ID}'
BL = os.environ.get('BLENDER_DIR', '/opt/blender') + '/blender'
APP = '/app'
OUT = '/tmp/out'
SAMPLES = int(os.environ.get('BENCH_SAMPLES', '64'))
PCT = int(os.environ.get('BENCH_PCT', '75'))                       # 2048×1488 × 75 % = 1536×1116
PLAN = os.environ.get('BENCH_PLAN', 'living:auto:3,bedroom:auto:2,living:cuda:1')
SCENES = {'living': ('lv-set10', 'lv-set10'), 'bedroom': ('lv-bed1', 'lv-bed1')}
EV = {'run_id': RUN_ID, 'started_epoch': T0, 'machine': {}, 'ready': {}, 'steps': []}
os.makedirs(OUT, exist_ok=True)


def log(*a):
    print(f'[{time.time() - T0:7.1f}s]', *a, flush=True)


def tls_diag():
    """Один раз при первой ошибке TLS: что видит нода (издатель сертификата, пути CA, часы) — разбор по журналу контейнера."""
    import socket
    import ssl
    host = (os.environ.get('MESH_SINK_URL', '').split('//')[-1].split('/')[0]) or 'remont-lab.online'
    try:
        log('TLS_DIAG paths', ssl.get_default_verify_paths(), 'SSL_CERT_FILE', os.environ.get('SSL_CERT_FILE'),
            'exists', os.path.exists(os.environ.get('SSL_CERT_FILE', '/nonexistent')), 'openssl', ssl.OPENSSL_VERSION,
            'utc', time.strftime('%F %T', time.gmtime()))
        cx = ssl.create_default_context()
        cx.check_hostname = False
        cx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=15) as sk, cx.wrap_socket(sk, server_hostname=host) as ss:
            der = ss.getpeercert(True)
        open('/tmp/peer.pem', 'w').write(ssl.DER_cert_to_PEM_cert(der))
        d = ssl._ssl._test_decode_cert('/tmp/peer.pem')
        log('TLS_DIAG peer', 'issuer', d.get('issuer'), 'subject', d.get('subject'), 'from', d.get('notBefore'), 'to', d.get('notAfter'))
    except Exception as e:  # noqa: BLE001
        log('TLS_DIAG ошибка диагностики', type(e).__name__, str(e)[:200])


_DIAG_DONE = []


def sink(method, name, data=None, ctype='application/octet-stream'):
    base = os.environ.get('MESH_SINK_URL', '').rstrip('/')
    if not base:
        return None
    t = time.time()
    try:
        req = urllib.request.Request(f'{base}{name}', data=data, method=method,
                                     headers={'Authorization': f"Bearer {os.environ.get('MESH_SINK_TOKEN', '')}", 'Content-Type': ctype})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
        return round(time.time() - t, 2)
    except Exception as e:  # noqa: BLE001 — выгрузка не должна ронять замер, но причина видна в журнале
        log('sink', method, name, 'ОШИБКА', type(e).__name__, str(e)[:100])
        if not _DIAG_DONE:
            _DIAG_DONE.append(1)
            tls_diag()
        return None


def push_events():
    sink('PUT', f'/staging/{PREFIX}/events.json', json.dumps(EV, ensure_ascii=False, indent=1).encode(), 'application/json')


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError as e:          # например nvidia-smi на машине без драйвера — это тоже данные замера, а не причина упасть
        return subprocess.CompletedProcess(cmd, 127, '', f'нет команды: {e}')


def machine():
    m = {'salad_instance': os.environ.get('SALAD_INSTANCE_ID'), 'salad_machine': os.environ.get('SALAD_MACHINE_ID'),
         'nproc': os.cpu_count()}
    try:
        m['mem_gb'] = round(int([l for l in open('/proc/meminfo') if l.startswith('MemTotal')][0].split()[1]) / 2 ** 20, 1)
        m['cpu'] = [l.split(':', 1)[1].strip() for l in open('/proc/cpuinfo') if l.startswith('model name')][0]
    except Exception as e:  # noqa: BLE001
        m['cpuinfo_error'] = str(e)[:80]
    q = run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total,clocks.max.sm,power.limit,pcie.link.gen.current', '--format=csv,noheader'])
    m['nvidia_smi'] = (q.stdout or q.stderr).strip()[:300]
    m['blender'] = run([BL, '-b', '--version']).stdout.strip().splitlines()[:1]
    m['image_bench'] = os.environ.get('IMAGE_NOTE', '')
    du = run(['du', '-sm', '/scenes'])
    m['scenes_mb'] = du.stdout.split()[0] if du.stdout else None
    return m


class GpuSampler(threading.Thread):
    """Раз в секунду: загрузка видеокарты, видеопамять, мощность — доказательство, что рендер шёл на GPU."""
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            q = run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,power.draw', '--format=csv,noheader,nounits'])
            try:
                u, mem, p = [float(x) for x in q.stdout.strip().split(',')]
                self.rows.append((u, mem, p))
            except ValueError:
                pass
            time.sleep(1.0)

    def summary(self):
        if not self.rows:
            return {'samples': 0}
        us = [r[0] for r in self.rows]
        return {'samples': len(us), 'util_max': max(us), 'util_mean': round(sum(us) / len(us), 1),
                'mem_max_mb': max(r[1] for r in self.rows), 'power_max_w': max(r[2] for r in self.rows)}


def blender_pair(scene, device, tag, samples=None, persistent=0, threads=None):
    export, dump = SCENES[scene]
    out = f'{OUT}/{tag}-{{cam}}.png'
    cmd = [BL, '-b', '--python-exit-code', '1', '-P', f'{APP}/render_cycles.py', '--',
           '--scene-dir', f'/scenes/{scene}/export', '--cam', 'C1,C2', '--out', out,
           '--samples', str(samples or SAMPLES), '--persistent', str(persistent), '--threads', str(threads or 8), '--pct', str(PCT), '--device', device,
           '--demo-glb', f'/scenes/{scene}/dump/demo_nodes.glb', '--demo-nodes', f'/scenes/{scene}/dump/demo_nodes_uuids.json',
           '--export', f'/scenes/{scene}/dump/scene-export.json', '--public', '/scenes/public',
           '--view', '2', '--exposure', '-0.15', '--sun-angle', '4', '--fill', '40', '--lamp-k', '3000', '--chandelier', '0', '--lamps', '5',
           '--sheer', '0.5', '--normal-k', '3.5', '--rug-erode', '0.025', '--cam-h', '1.35', '--level', '1', '--shift-y', '-0.12']
    smp = GpuSampler()
    smp.start()
    t = time.time()
    p = run(cmd)
    wall = time.time() - t
    smp.stop = True
    text = p.stdout + p.stderr
    open(f'{OUT}/{tag}.log', 'w', encoding='utf-8').write(text)
    step = {'tag': tag, 'scene': scene, 'device_arg': device, 'rc': p.returncode, 'wall_s': round(wall, 1), 'frames': [], 'gpu': smp.summary()}
    for ln in text.splitlines():
        if ln.startswith('SCENE_BUILD_SEC'):
            step['scene_build_s'] = float(ln.split()[1])
        elif ln.startswith('RENDER_SEC'):
            w = ln.split()
            step['frames'].append({'cam': w[w.index('cam') + 1], 'sec': float(w[1])})
        elif ln.startswith('DEVICE_USED'):
            step['device_used'] = ln[len('DEVICE_USED '):]
        elif ln.startswith(('DEVICE_FAIL', 'DEVICE_LIST')):
            step.setdefault('device_notes', []).append(ln)
    if p.returncode != 0 or len(step['frames']) != 2:
        step['error_tail'] = text.strip().splitlines()[-6:]          # упавший прогон виден в events.json, а не молча «готов»
    if 'device_used' not in step:
        step['device_used'] = 'CPU' if '--device' in cmd and device == 'cpu' else '?'
    return step


def upload_frames(step):
    for cam in ('C1', 'C2'):
        f = f"{OUT}/{step['tag']}-{cam}.png"
        if os.path.exists(f):
            data = open(f, 'rb').read()
            sec = sink('PUT', f"/staging/{PREFIX}/{step['tag']}-{cam}.png", data)
            step.setdefault('upload', []).append({'file': os.path.basename(f), 'mb': round(len(data) / 2 ** 20, 2), 'sec': sec})
    f = f"{OUT}/{step['tag']}.log"
    sink('PUT', f"/staging/{PREFIX}/{step['tag']}.log", open(f, 'rb').read())


def main():
    log('старт бенча', RUN_ID, 'план', PLAN)
    EV['machine'] = machine()
    log('машина', json.dumps(EV['machine'], ensure_ascii=False))
    push_events()

    t = time.time()
    p = run([BL, '-b', '-P', f'{APP}/ready_probe.py', '--', '--device', 'auto', '--require-gpu', os.environ.get('BENCH_REQUIRE_GPU', '1'), '--out', f'{OUT}/ready.png'])
    txt = p.stdout + p.stderr
    open(f'{OUT}/ready.log', 'w', encoding='utf-8').write(txt)
    EV['ready'] = {'rc': p.returncode, 'wall_s': round(time.time() - t, 1),
                   'lines': [l for l in txt.splitlines() if l.startswith(('DEVICE_', 'PROBE_'))]}
    log('ready', EV['ready'])
    sink('PUT', f'/staging/{PREFIX}/ready.log', txt.encode())
    push_events()
    if p.returncode == 3:
        log('GPU не поднялся — замер на CPU бессмыслен, останавливаюсь (RESULT: no_gpu)')
        EV['result'] = 'no_gpu'
        EV['steps'] = []
        push_events()
        return

    for item in PLAN.split(','):
        scene, device, n, *opt = item.split(':')                    # необязательно: :выборки:persistent:потоки (проба накладных расходов)
        o_s, o_p, o_t = (int(x) for x in (opt + ['0', '0', '0'][len(opt):])) if opt else (0, 0, 0)
        for i in range(1, int(n) + 1):
            tag = f'{scene}-{device}-{i}' + (f'-s{o_s}p{o_p}t{o_t}' if opt else '')
            log('прогон', tag)
            step = blender_pair(scene, device, tag, o_s or None, o_p, o_t or None)
            step['t_since_start_s'] = round(time.time() - T0, 1)
            upload_frames(step)
            EV['steps'].append(step)
            push_events()
            log('прогон готов', json.dumps({k: step[k] for k in ('tag', 'rc', 'wall_s', 'device_used', 'frames')}, ensure_ascii=False))
    EV['result'] = 'done'
    EV['finished_epoch'] = time.time()
    EV['total_s'] = round(time.time() - T0, 1)
    push_events()
    log('DONE')                                   # кадры и журнал лежат в .staging приёмника (без /complete) — оператор забирает их по ssh


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001
        EV['result'] = f'error: {type(e).__name__}: {e}'
        push_events()
        log('ОШИБКА', EV['result'])
    if os.environ.get('BENCH_EXIT') == '1':       # локальная проверка на DEV: выйти, не ждать оператора
        sys.exit(0)
    while True:                                   # контейнер живёт, пока группу не погасит оператор (Salad перезапустил бы сам и повторил бы платный замер)
        time.sleep(60)
