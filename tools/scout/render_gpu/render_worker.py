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

FMT 2 (T-20261117-24/5): в задании (v=2) — маленький пакет + манифест ассетов {path, sha256, size, kind}. Ассеты воркер берёт из своего кэша по хешу `/work/blobs/<sha256>`
(хеш и размер сверяются при КАЖДОМ взятии: файл мог испортиться или подмениться), недостающее скачивает с приёмника (`renderassets/<ab>/<sha256>`, до ASSET_PAR потоков,
один поток на один хеш), проверяет хеш после скачивания и собирает рабочий каталог жёсткими ссылками из кэша. Любая беда с ассетом — `result.json` с кодом `asset`
(исполнитель повторит заказ по fmt 1), частичного кадра не бывает. Кэш ассетов ограничен по размеру (BLOB_GB), давние убираются, ассеты текущего задания — нет.

Переменные: MESH_SINK_URL, MESH_SINK_TOKEN (из группы), WORK (/work), JOB_POLL_S (1), JOB_MAX_AGE_S (7200), CACHE_N (3), CACHE_GB (1.5), BLOB_GB (4), ASSET_PAR (4)."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jobs_proto as JP  # noqa: E402
import machine_agent as MA  # noqa: E402

WORK = os.environ.get('WORK', '/work')
POLL = float(os.environ.get('JOB_POLL_S', '1'))      # было 3 с: ожидание задания в среднем 1,5 с (T-24/4)
MAX_AGE = float(os.environ.get('JOB_MAX_AGE_S', '7200'))
CACHE_N = int(os.environ.get('CACHE_N', '3'))
CACHE_GB = float(os.environ.get('CACHE_GB', '1.5'))
BLOB_GB = float(os.environ.get('BLOB_GB', '4'))
ASSET_PAR = int(os.environ.get('ASSET_PAR', '4'))
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


class AssetError(Exception):
    """Беда с ассетом или пакетом fmt 2: не скачался, не сошёлся хеш/размер, плохой путь. Исполнитель получает код `asset` и повторяет заказ по fmt 1."""


_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def trim_blobs(blob_dir: str, keep: set, max_gb: float = BLOB_GB) -> list:
    """Кэш ассетов по хешу ограничен по размеру: удаляем самые давние (по mtime = «когда брали последний раз»), кроме `keep` (ассеты текущего задания).
    Трогаем только файлы с именем-хешем (временные скачивания и чужое — нет). → удалённые имена."""
    try:
        rows = [(os.path.getmtime(os.path.join(blob_dir, f)), f, os.path.getsize(os.path.join(blob_dir, f))) for f in os.listdir(blob_dir) if _HEX64.match(f)]
    except OSError:
        return []
    total = sum(r[2] for r in rows)
    gone = []
    for t, f, sz in sorted(r for r in rows if r[1] not in keep):
        if total <= max_gb * 2 ** 30:
            break
        try:
            os.remove(os.path.join(blob_dir, f))
        except OSError:
            continue
        gone.append(f)
        total -= sz
    return gone


def blob_ok(path: str, sha: str, size: int) -> bool:
    """Файл кэша годен: обычный файл (не ссылка), размер и полный sha256 сходятся. Проверка при КАЖДОМ взятии."""
    try:
        st = os.lstat(path)
        return os.path.isfile(path) and not os.path.islink(path) and st.st_size == size and JP.sha256_file(path) == sha
    except OSError:
        return False


def place_asset(blob: str, work: str, rel: str) -> None:
    """Положить ассет в рабочий каталог жёсткой ссылкой на файл кэша (на одном диске — мгновенно, места не занимает); нет ссылки — копия. Путь уже проверен
    `valid_rel_path`; здесь ещё раз: каталог после realpath внутри рабочего, цель не существует (ассет не затирает файл пакета)."""
    target = os.path.join(work, rel)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    rw = os.path.realpath(work)
    if os.path.realpath(parent) != rw and not os.path.realpath(parent).startswith(rw + os.sep):
        raise AssetError(f'путь ассета вне рабочего каталога: {rel}')
    if os.path.lexists(target):
        raise AssetError(f'путь ассета занят: {rel}')
    try:
        os.link(blob, target)
    except OSError:
        shutil.copyfile(blob, target)


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
        self._locks: dict = {}
        self._locks_guard = threading.Lock()
        os.makedirs(os.path.join(WORK, 'cache'), exist_ok=True)
        os.makedirs(os.path.join(WORK, 'blobs'), exist_ok=True)

    def _lock(self, key: str) -> threading.Lock:
        """Один замок на хеш: одну и ту же вещь два потока (или два заказа подряд) не скачивают разом."""
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

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
            try:
                names = {f['name'] for f in self.sink.ls(f'{JP.PREFIX}/{n}').get('files', [])}
            except JP.SinkError as e:      # сетевой сбой/таймаут посреди перечня: не падать (воркер умирал — T-24/4, живая пара 23:34), пропустить до следующего круга
                log('ls задания', n, e)
                return None
            if 'result.json' in names or 'cancel.json' in names:
                self.done.add(n)
                continue
            if 'job.json' in names:
                return n
        return None

    def fetch_bundle(self, job: dict) -> str:
        cache = os.path.join(WORK, 'cache')
        dst = os.path.join(cache, f"bundle-{job['sha']}.tgz")
        if os.path.isfile(dst) and JP.file_sha12(dst) != job['sha']:      # из кэша берём только проверенное: файл мог испортиться
            os.remove(dst)
        if not os.path.isfile(dst):
            self.sink.get_to(f"{JP.PREFIX}/{job['job_id']}/{job['bundle']}", dst)
            if JP.file_sha12(dst) != job['sha']:
                os.remove(dst)
                raise JP.SinkError('пакет сцены: sha не сходится')
        os.utime(dst)
        trim_cache(cache, os.path.basename(dst))
        return dst

    def fetch_asset(self, sha: str, size: int) -> tuple:
        """Ассет в кэше `/work/blobs/<sha>`: годный (хеш+размер) — берём; иначе скачиваем, проверяем, подменяем атомарно. → (путь, скачано байт)."""
        blob = os.path.join(WORK, 'blobs', sha)
        with self._lock(sha):
            if blob_ok(blob, sha, size):
                os.utime(blob)
                return blob, 0
            if os.path.lexists(blob):
                os.remove(blob)                         # испорчен или подменён — не доверяем, перекачиваем
            tmp = os.path.join(WORK, 'blobs', f'.dl-{sha[:12]}-{uuid.uuid4().hex[:8]}')
            try:
                n = self.sink.get_asset_to(sha, tmp)
                if n != size or JP.sha256_file(tmp) != sha:
                    raise AssetError(f'ассет {sha[:12]}: хеш или размер не сходятся ({n} из {size})')
                os.chmod(tmp, 0o444)
                os.replace(tmp, blob)
            except JP.SinkError as e:
                raise AssetError(f'ассет {sha[:12]}: {e}') from None
            finally:
                for p in (tmp, tmp + '.part'):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            return blob, size

    def prepare_v2(self, job: dict, work: str) -> dict:
        """fmt 2: маленький пакет (проверка полного sha256 и размера при каждом взятии из кэша, лимиты распаковки) + ассеты по хешу → рабочий каталог.
        → статистика {assets, downloaded, dl_mb}. Любая беда — `AssetError`."""
        b = job['bundle']
        cache = os.path.join(WORK, 'cache')
        dst = os.path.join(cache, b['name'])
        by_sha: dict = {}
        for a in job['assets']:
            if by_sha.setdefault(a['sha256'], a['size']) != a['size']:
                raise AssetError('один хеш — два размера')
        with ThreadPoolExecutor(max_workers=max(1, ASSET_PAR)) as pool:
            futs = {sha: pool.submit(self.fetch_asset, sha, size) for sha, size in by_sha.items()}      # ассеты качаются, пока берётся маленький пакет
            if os.path.isfile(dst) and not blob_ok(dst, b['sha256'], b['size']):
                os.remove(dst)
            if not os.path.isfile(dst):
                try:
                    self.sink.get_to(f"{JP.PREFIX}/{job['job_id']}/{b['name']}", dst)
                except JP.SinkError as e:
                    raise AssetError(f'пакет: {e}') from None
                if not blob_ok(dst, b['sha256'], b['size']):
                    os.remove(dst)
                    raise AssetError('пакет: хеш или размер не сходятся')
            os.utime(dst)
            trim_cache(cache, b['name'])
            try:
                JP.unpack_bundle(dst, work)
            except Exception as e:  # noqa: BLE001 — tarfile.* и лимиты: пакет не годен
                raise AssetError(f'пакет не распакован: {type(e).__name__}: {e}'[:200]) from None
            got = {sha: f.result() for sha, f in futs.items()}
        for a in job['assets']:
            place_asset(got[a['sha256']][0], work, a['path'])
        dl = [v[1] for v in got.values() if v[1]]
        trim_blobs(os.path.join(WORK, 'blobs'), set(by_sha))
        return {'assets': len(job['assets']), 'downloaded': len(dl), 'dl_mb': round(sum(dl) / 2 ** 20, 1)}

    def run_job(self, jid: str) -> dict:
        job = self.sink.get_json(f'{JP.PREFIX}/{jid}/job.json')
        why = JP.validate_job(job, expect_id=jid)
        if why:
            return err('bad_job', 'Задание рендера не принято машиной.', 'The render job was rejected by the machine.', note=why)
        work = os.path.join(WORK, 'job')
        shutil.rmtree(work, ignore_errors=True)
        timing: dict = {}
        t0 = time.time()
        self.progress(jid, 'scene')
        stats: dict = {}
        try:
            if job['v'] == JP.PROTO2:
                stats = self.prepare_v2(job, work)
            else:
                bundle = self.fetch_bundle(job)
                JP.unpack_bundle(bundle, work)
        except AssetError as e:
            shutil.rmtree(work, ignore_errors=True)
            return err('asset', 'Машина рендера не получила файлы сцены.', 'The render machine could not get the scene files.', note=str(e)[:200])
        except Exception as e:  # noqa: BLE001
            return err('bundle', 'Машина рендера не получила сцену.', 'The render machine could not get the scene.', note=f'{type(e).__name__}: {e}'[:200])
        timing['fetch'] = round(time.time() - t0, 1)
        cmd = build_cmd(job, work)
        if not os.path.isfile(cmd[cmd.index('-P') + 1]):
            return err('bundle', 'В пакете сцены нет программы рендера.', 'The scene bundle has no renderer.')
        limit = float(job.get('limits', {}).get('blenderSec', 1500)) * len(job['cams'])
        res_extra = {'fmt': job['v'], **({'assets': stats} if stats else {})}
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
        return {'ok': True, 'timing': timing, 'device': device, 'files': files, **res_extra}

    def loop(self) -> None:
        while True:
            if not MA.STATE.get('ready'):
                time.sleep(POLL)
                continue
            try:
                jid = self.pick()
            except Exception as e:  # noqa: BLE001 — воркер не должен умирать от сбоя перечня заданий
                log('pick сбой', type(e).__name__, str(e)[:160])
                jid = None
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
