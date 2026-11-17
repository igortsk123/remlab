"""ВОРКЕР МАШИНЫ РЕНДЕРА (T-20261117-24/2). Работает ВНУТРИ контейнера Salad (python из Blender), цель образа `worker`; заменяет `machine_agent.py`.

Что делает:
  1. то же, что агент готовности: `ready_probe` на старте и `rendermachine/ready.json` раз в `AGENT_BEAT_S` секунд (тот же формат — контроллер не меняется);
     готов (`STATE['ready']`) — только после проверки GPU;
  2. опрашивает приёмник (`GET /ls/renderjobs`), берёт задание с `job.json`, без `result.json` и `cancel.json`: скачивает пакет сцены (кэш по sha, ≤ CACHE_N штук
     и ≤ CACHE_GB), распаковывает, одним Blender считает ПАРУ ракурсов (`--cam C1,C2 --persistent 1`, `--device auto`), кладёт `C1.png`, `C2.png`,
     в конце `result.json`; по ходу — `progress.json` (стадии scene → C1 → C2 → save, как у LocalCpuExecutor);
  3. программа рендера и данные — ИЗ ПАКЕТА (`render_cycles.py`, `wall-art.json`, карты): правка рендера не требует новой сборки образа, а картинка
     машины всегда той версии, что у DEV. Флаги рендера (сэмплы, пресет) — из `job.json:args`, пути воркер подставляет сам.
Один процесс — одно задание за раз (машина одна). Токен нигде не печатается.

Переменные: MESH_SINK_URL, MESH_SINK_TOKEN (из группы), WORK (/work), JOB_POLL_S (1), JOB_MAX_AGE_S (7200), CACHE_N (3), CACHE_GB (1.5)."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jobs_proto as JP  # noqa: E402
import machine_agent as MA  # noqa: E402

WORK = os.environ.get('WORK', '/work')
POLL = float(os.environ.get('JOB_POLL_S', '1'))      # было 3 с: ожидание задания в среднем 1,5 с (T-24/4)
MAX_AGE = float(os.environ.get('JOB_MAX_AGE_S', '7200'))
CACHE_N = int(os.environ.get('CACHE_N', '3'))
CACHE_GB = float(os.environ.get('CACHE_GB', '1.5'))
BL = MA.BL
log = MA.log


def err(code: str, ru: str, en: str, **kw) -> dict:
    return {'ok': False, 'error': {'code': code, 'ru': ru, 'en': en}, **kw}


def trim_cache(cache_dir: str, keep: str, max_n: int = CACHE_N, max_gb: float = CACHE_GB) -> list:
    """Кэш пакетов по sha ограничен по числу и по размеру: удаляем самые давние, кроме `keep` (пакет текущего задания). → удалённые имена
    (удаление — только в собственном рабочем каталоге воркера, на одноразовой машине)."""
    try:
        rows = [(os.path.getmtime(os.path.join(cache_dir, f)), f, os.path.getsize(os.path.join(cache_dir, f))) for f in os.listdir(cache_dir) if f.endswith('.tgz')]
    except OSError:
        return []
    others = sorted(r for r in rows if r[1] != keep)
    total = sum(r[2] for r in rows)
    count = len(rows)
    gone = []
    for t, f, sz in others:
        if count <= max_n and total <= max_gb * 2 ** 30:
            break
        os.remove(os.path.join(cache_dir, f))
        gone.append(f)
        count -= 1
        total -= sz
    return gone


def build_cmd(job: dict, work: str) -> list:
    """Команда Blender: пути — воркера (внутри пакета), флаги рендера — из задания. Чистая функция."""
    scene, dump = os.path.join(work, 'scene'), os.path.join(work, 'dump')
    return [BL, '-b', '--python-exit-code', '1', '-P', os.path.join(work, 'tools', 'scout', 'cycles_probe', 'render_cycles.py'), '--',
            '--scene-dir', scene, '--cam', ','.join(job['cams']), '--out', os.path.join(work, '{cam}.png'),
            '--demo-glb', os.path.join(dump, 'demo_nodes.glb'), '--demo-nodes', os.path.join(dump, 'demo_nodes_uuids.json'),
            '--export', os.path.join(dump, 'scene-export.json'), '--public', os.path.join(work, 'public'),
            '--device', 'auto', '--persistent', '1', *job['args']]


def parse_progress(line: str, cams: list) -> tuple[str | None, dict]:
    """Строка вывода Blender → (новая стадия | None, добавка к timing). `RENDER_SEC <с> cam C1 frame 1/2 …` — кадр готов, дальше следующий ракурс или save."""
    if line.startswith('RENDER_SEC '):
        parts = line.split()
        try:
            sec, cam = float(parts[1]), parts[parts.index('cam') + 1]
        except (ValueError, IndexError):
            return None, {}
        i = cams.index(cam) if cam in cams else -1
        nxt = cams[i + 1] if 0 <= i + 1 < len(cams) else 'save'
        return nxt, {cam: round(sec, 1)}
    return None, {}


class Worker:
    def __init__(self, sink: 'JP.Sink'):
        self.sink = sink
        self.done: set = set()
        os.makedirs(os.path.join(WORK, 'cache'), exist_ok=True)

    def progress(self, jid: str, stage: str) -> None:
        try:
            self.sink.put(f'{JP.PREFIX}/{jid}/progress.json', json.dumps({'stage': stage, 'ts': round(time.time(), 1)}).encode())
        except JP.SinkError as e:
            log('progress PUT', stage, 'ОШИБКА', e)

    def pick(self):
        """Первое готовое к работе задание (старые — вперёд) или None."""
        now = time.time()
        try:
            dirs = self.sink.ls(JP.PREFIX).get('dirs', [])
        except JP.SinkError as e:
            log('ls', e)
            return None
        for d in sorted(dirs, key=lambda x: x.get('mtime', 0)):
            n = d['name']
            if n in self.done or now - float(d.get('mtime', 0)) > MAX_AGE:
                continue
            names = {f['name'] for f in self.sink.ls(f'{JP.PREFIX}/{n}').get('files', [])}
            if 'result.json' in names or 'cancel.json' in names:
                self.done.add(n)
                continue
            if 'job.json' in names:
                return n
        return None

    def fetch_bundle(self, job: dict) -> str:
        cache = os.path.join(WORK, 'cache')
        dst = os.path.join(cache, f"bundle-{job['sha']}.tgz")
        if not os.path.isfile(dst):
            self.sink.get_to(f"{JP.PREFIX}/{job['job_id']}/{job['bundle']}", dst)
            if JP.file_sha12(dst) != job['sha']:
                os.remove(dst)
                raise JP.SinkError('пакет сцены: sha не сходится')
        os.utime(dst)
        trim_cache(cache, os.path.basename(dst))
        return dst

    def run_job(self, jid: str) -> dict:
        job = self.sink.get_json(f'{JP.PREFIX}/{jid}/job.json')
        why = JP.validate_job(job)
        if why:
            return err('bad_job', 'Задание рендера не принято машиной.', 'The render job was rejected by the machine.', note=why)
        work = os.path.join(WORK, 'job')
        shutil.rmtree(work, ignore_errors=True)
        timing: dict = {}
        t0 = time.time()
        self.progress(jid, 'scene')
        try:
            bundle = self.fetch_bundle(job)
            JP.unpack_bundle(bundle, work)
        except Exception as e:  # noqa: BLE001
            return err('bundle', 'Машина рендера не получила сцену.', 'The render machine could not get the scene.', note=f'{type(e).__name__}: {e}'[:200])
        timing['fetch'] = round(time.time() - t0, 1)
        cmd = build_cmd(job, work)
        if not os.path.isfile(cmd[cmd.index('-P') + 1]):
            return err('bundle', 'В пакете сцены нет программы рендера.', 'The scene bundle has no renderer.')
        limit = float(job.get('limits', {}).get('blenderSec', 1500)) * len(job['cams'])
        self.progress(jid, job['cams'][0])
        t1 = time.time()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True,
                                env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        tail, device, killed = [], '', ''

        def watchdog():
            nonlocal killed
            while proc.poll() is None:
                if time.time() - t1 > limit:
                    killed = 'timeout'
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except OSError:
                        pass
                    return
                time.sleep(2)
        threading.Thread(target=watchdog, daemon=True).start()
        for line in proc.stdout:
            line = line.rstrip()
            tail = (tail + [line])[-25:]
            if line.startswith('DEVICE_USED'):
                device = line.split(' ', 1)[1]
                if device.startswith('CPU'):       # GPU не поднялся: считать на CPU машины ×30 медленнее — не нужно, пусть исполнитель решит
                    killed = 'cpu'
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except OSError:
                        pass
            nxt, add = parse_progress(line, job['cams'])
            if add:
                timing.update(add)
            if nxt:
                self.progress(jid, nxt)
        rc = proc.wait()
        timing['render'] = round(time.time() - t1, 1)
        if killed == 'cpu':
            return err('gpu_failed', 'Видеокарта машины не взялась за рендер.', 'The machine GPU did not take the render.', device=device)
        if killed == 'timeout':
            return err('render_timeout', 'Рендер занял слишком много времени.', 'The render took too long.', device=device)
        frames = {c: os.path.join(work, f'{c}.png') for c in job['cams']}
        if rc != 0 or not all(os.path.isfile(p) and os.path.getsize(p) > 0 for p in frames.values()):
            log('blender rc', rc, ' | '.join(tail[-6:]))
            return err('render_failed', 'Рендер не удался.', 'The render failed.', device=device, rc=rc, tail='\n'.join(tail[-8:])[-600:])
        self.progress(jid, 'save')
        files = {}
        for c, p in frames.items():
            self.sink.put_file(f'{JP.PREFIX}/{jid}/{c}.png', p)
            files[c] = os.path.getsize(p)
        timing['total'] = round(time.time() - t0, 1)
        return {'ok': True, 'timing': timing, 'device': device, 'files': files}

    def loop(self) -> None:
        while True:
            if not MA.STATE.get('ready'):
                time.sleep(POLL)
                continue
            jid = self.pick()
            if not jid:
                time.sleep(POLL)
                continue
            log('задание', jid)
            MA.STATE['busy'] = jid
            try:
                res = self.run_job(jid)
            except Exception as e:  # noqa: BLE001 — воркер не должен умирать от одного задания
                res = err('worker', 'Сбой машины рендера.', 'The render machine failed.', note=f'{type(e).__name__}: {str(e)[:160]}')
            finally:
                MA.STATE['busy'] = None
                shutil.rmtree(os.path.join(WORK, 'job'), ignore_errors=True)
            if not res.get('cancelled'):
                res['job_id'], res['boot_id'], res['ts'] = jid, MA.BOOT, round(time.time(), 1)
                try:
                    self.sink.put(f'{JP.PREFIX}/{jid}/result.json', json.dumps(res, ensure_ascii=False).encode())   # ПОСЛЕДНИМ
                except JP.SinkError as e:
                    log('result PUT ОШИБКА', e)      # исполнитель не дождётся и уйдёт на запасной; второй раз GPU не жжём
            self.done.add(jid)
            log('задание', jid, 'ok' if res.get('ok') else res.get('error', {}).get('code') or 'отменено')


def main() -> int:
    base, tok = os.environ.get('MESH_SINK_URL', ''), os.environ.get('MESH_SINK_TOKEN', '')
    if not base or not tok:
        log('нет MESH_SINK_URL/MESH_SINK_TOKEN — воркер не работает')
        return 2
    threading.Thread(target=MA.main, daemon=True, name='agent').start()      # готовность и отметка ready.json — как у агента
    Worker(JP.Sink(base, tok)).loop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
