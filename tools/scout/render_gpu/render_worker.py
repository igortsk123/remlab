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

ПОДОГРЕВ (T-20261117-24/7): после готовности (и потом раз в HOT_REFRESH_S, если список обновился) воркер читает «горячий список» витрины `renderjobs/_hot/hot.json`
(его пишет DEV, `showcase_assets.py`: ассеты /demo и туров, уже лежащие на приёмнике) и подтягивает недостающее в `/work/blobs` — до HOT_GB (по порядку списка), HOT_PAR потоков,
каждый ассет проверяется как обычно (хеш+размер). ЗАКАЗ ПРИОРИТЕТНЕЕ: пока пара считается (`STATE['busy']`), новые скачивания подогрева не начинаются; тот же хеш, что нужен
заказу, качается один раз (замок на хеш). Горячие ассеты не выселяются из кэша по размеру (`trim_blobs` keep). Список битый/пустой/нет — ничего не делаем.

Переменные: MESH_SINK_URL, MESH_SINK_TOKEN (из группы), WORK (/work), JOB_POLL_S (1), JOB_MAX_AGE_S (7200), CACHE_N (3), CACHE_GB (1.5), BLOB_GB (4), ASSET_PAR (4),
HOT_GB (2.5), HOT_PAR (2), HOT_REFRESH_S (600)."""
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
POLL = float(os.environ.get('JOB_POLL_S', '0.5'))    # было 3 с (T-24/4), потом 1 с; T-24/11 — 0,5 с: ожидание задания в среднем 0,25 с
MAX_AGE = float(os.environ.get('JOB_MAX_AGE_S', '7200'))
CACHE_N = int(os.environ.get('CACHE_N', '3'))
CACHE_GB = float(os.environ.get('CACHE_GB', '1.5'))
BLOB_GB = float(os.environ.get('BLOB_GB', '4'))
ASSET_PAR = int(os.environ.get('ASSET_PAR', '4'))
HOT_GB = float(os.environ.get('HOT_GB', '2.5'))               # подогрев: не больше этого объёма (кэш ассетов BLOB_GB = 4 — запас под задание)
HOT_PAR = int(os.environ.get('HOT_PAR', '2'))
HOT_REFRESH_S = float(os.environ.get('HOT_REFRESH_S', '600'))
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


def frames_of(job: dict) -> str:
    """Формат кадров задания: png (нет поля — как раньше) | jpg (кодирует Blender) | both (jpg и png из одного результата — ТОЛЬКО приёмка ΔE)."""
    return job.get('frames', 'png')


def qa_reports(work: str, fr: str, cams: list) -> dict:
    """Отчёты сторожа кадров (`<кадр>.qa.json`, их пишет `render_cycles.py`) → `{камера: урезанный отчёт}` для `result.json`. Нет отчёта/модуля — камеры в словаре нет
    (исполнитель такой кадр не блокирует): старая версия пакета или сторож выключен. Модуль берём из пакета задания — той же версии, что рендерила."""
    out: dict = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('frame_qa_pkg', os.path.join(work, 'tools', 'scout', 'cycles_probe', 'frame_qa.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        log('сторож: модуль пакета не загружен', repr(e)[:100])
        return out
    for c in cams:
        try:
            with open(os.path.join(work, JP.frame_names(fr, c)[0]) + '.qa.json', encoding='utf-8') as f:
                out[c] = mod.brief_report(json.load(f))
        except (OSError, ValueError):
            continue
        except Exception as e:  # noqa: BLE001
            log('сторож: отчёт кадра не разобран', c, repr(e)[:100])
    return out


def build_cmd(job: dict, work: str) -> list:
    """Команда Blender: пути — воркера (внутри пакета), флаги рендера — из задания. Чистая функция."""
    scene, dump = os.path.join(work, 'scene'), os.path.join(work, 'dump')
    fr = frames_of(job)
    fmt = ['--jpeg-quality', str(job.get('jpeg_q', 92))] if fr in ('jpg', 'both') else []
    if fr == 'both':
        fmt += ['--also-png', os.path.join(work, '{cam}.png')]
    mk = ['--mask-out', os.path.join(work, JP.mask_name('{cam}')), '--mask-scale', str(JP.MASK_SCALE)] if job.get('masks') else []
    return [BL, '-b', '--python-exit-code', '1', '-P', os.path.join(work, 'tools', 'scout', 'cycles_probe', 'render_cycles.py'), '--',
            '--scene-dir', scene, '--cam', ','.join(job['cams']), '--out', os.path.join(work, '{cam}.png' if fr == 'png' else '{cam}.jpg'),
            '--demo-glb', os.path.join(dump, 'demo_nodes.glb'), '--demo-nodes', os.path.join(dump, 'demo_nodes_uuids.json'),
            '--export', os.path.join(dump, 'scene-export.json'), '--public', os.path.join(work, 'public'),
            '--device', 'auto', '--persistent', '1', *fmt, *mk, *job['args']]


def cam_of_line(line: str) -> str | None:
    """`RENDER_SEC <с> cam C1 …` → 'C1' (кадр записан на диск: Blender печатает строку ПОСЛЕ write_still); иначе None."""
    if not line.startswith('RENDER_SEC '):
        return None
    parts = line.split()
    try:
        return parts[parts.index('cam') + 1]
    except (ValueError, IndexError):
        return None


class FrameUploader:
    """Выгрузка кадров в приёмник ПОКА Blender считает следующий (T-24/11): `start(cam)` — поток на файл(ы) кадра, `join()` — дождаться и вернуть
    {имя файла: размер}; сбой любой выгрузки поднимается из `join()` (воркер вернёт ошибку задания, как при выгрузке после рендера)."""

    def __init__(self, sink, jid: str, work: str, frames: str):
        self.sink, self.jid, self.work, self.frames = sink, jid, work, frames
        self.threads: list = []
        self.sizes: dict = {}
        self.errors: list = []
        self.started: set = set()

    def start(self, cam: str) -> None:
        if cam in self.started:
            return
        self.started.add(cam)
        for name in JP.frame_names(self.frames, cam):
            t = threading.Thread(target=self._one, args=(name,), daemon=True)
            t.start()
            self.threads.append(t)

    def _one(self, name: str) -> None:
        p = os.path.join(self.work, name)
        try:
            if not os.path.isfile(p) or os.path.getsize(p) <= 0:
                raise JP.SinkError(f'кадр {name} не записан')
            self.sink.put_file(f'{JP.PREFIX}/{self.jid}/{name}', p)
            self.sizes[name] = os.path.getsize(p)
        except Exception as e:  # noqa: BLE001
            self.errors.append(e)

    def join(self) -> dict:
        for t in self.threads:
            t.join()
        if self.errors:
            raise self.errors[0]
        return dict(self.sizes)


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


class CallLog:
    """Журнал обращений воркера к приёмнику (T-24/12, МЕРКА): (что, смещение от начала задания с, длительность с). Пишет `TimedSink`; `reset()` — в начале каждого круга
    выбора задания, поэтому к заданию попадают обращения последнего (успешного) выбора; обращения потока подогрева (`hot`, ассеты вне задания) не учитываются."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items: list = []

    def reset(self) -> None:
        with self.lock:
            self.items = []

    def add(self, op: str, t_start: float, dur: float) -> None:
        with self.lock:
            self.items.append((op, t_start, dur))

    def snapshot(self, t0: float) -> list:
        """→ [[что, смещение от t0 (до задания — отрицательное), с]] по времени; ассеты схлопнуты в одну строку «ассеты ×N» (сумма, максимум в `max`)."""
        with self.lock:
            it = sorted(self.items, key=lambda x: x[1])
        out, assets, shown = [], [x for x in it if x[0] == 'ассет'], False
        for op, ts, d in it:
            if op == 'hot':
                continue
            if op == 'ассет':
                if not shown:
                    shown = True
                    out.append({'op': f'ассеты ×{len(assets)}', 't': round(ts - t0, 2), 's': round(sum(x[2] for x in assets), 2), 'max': round(max(x[2] for x in assets), 2)})
                continue
            out.append({'op': op, 't': round(ts - t0, 2), 's': round(d, 2)})
        return out


def call_label(method: str, rel: str, data=None) -> str:
    """Короткое имя обращения: ls корня / ls задания / job.json / progress.json:<стадия> / result.json / выгрузка C1.jpg / пакет / ассет / hot."""
    if method == 'ls':
        return 'ls корня' if rel == JP.PREFIX else 'ls задания'
    if method in ('get_asset_to', 'put_asset'):
        return 'ассет'
    base = rel.rsplit('/', 1)[-1]
    if rel == JP.HOT_REL:
        return 'hot'
    if base == 'progress.json':
        try:
            return 'progress.json:' + str(json.loads(data).get('stage'))
        except (TypeError, ValueError, AttributeError):
            return 'progress.json'
    if base.startswith('bundle-'):
        return 'пакет'
    if method == 'put_file' and base[:1] == 'C':
        return 'выгрузка ' + base
    return base


class TimedSink:
    """Обёртка над `Sink`: каждое обращение (get/get_json/get_to/put/put_file/ls/ассеты) меряется и пишется в `CallLog`; всё остальное — как у `Sink`."""
    TIMED = ('get', 'get_json', 'get_to', 'put', 'put_file', 'ls', 'get_asset_to', 'put_asset')

    def __init__(self, sink, log: 'CallLog'):
        self._sink, self.calls = sink, log

    def __getattr__(self, name):
        attr = getattr(self._sink, name)
        if name not in self.TIMED:
            return attr

        def timed(*a, **kw):
            t = time.time()
            try:
                return attr(*a, **kw)
            finally:
                rel = a[0] if a and isinstance(a[0], str) else ''
                self.calls.add(call_label(name, rel, a[1] if name == 'put' and len(a) > 1 else None), t, time.time() - t)
        return timed


class AsyncProgress:
    """Запись `progress.json` вне критического пути (T-24/12): `set` не ждёт сети, поток пишет ПОСЛЕДНЕЕ значение (промежуточные могут пропасть — важна текущая стадия);
    `close(jid)` — сбросить непосланное и дождаться уже идущей записи, чтобы `progress.json` не появился после `result.json`."""

    def __init__(self, sink):
        self.sink = sink
        self.cond = threading.Condition()
        self.pending = None
        self.busy = False
        self.thread = None

    def set(self, jid: str, stage: str) -> None:
        with self.cond:
            self.pending = (jid, stage, round(time.time(), 1))
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name='progress')
                self.thread.start()
            self.cond.notify_all()

    def _run(self) -> None:
        while True:
            with self.cond:
                while self.pending is None:
                    self.cond.wait()
                jid, stage, ts = self.pending
                self.pending = None
                self.busy = True
            try:
                self.sink.put(f'{JP.PREFIX}/{jid}/progress.json', json.dumps({'stage': stage, 'ts': ts}).encode())
            except Exception as e:  # noqa: BLE001
                log('progress PUT', stage, 'ОШИБКА', e)
            finally:
                with self.cond:
                    self.busy = False
                    self.cond.notify_all()

    def close(self, jid: str, timeout: float = 15.0) -> None:
        end = time.time() + timeout
        with self.cond:
            if self.pending and self.pending[0] == jid:
                self.pending = None
            while self.busy and time.time() < end:
                self.cond.wait(0.2)


class Worker:
    def __init__(self, sink: 'JP.Sink'):
        self.calls = CallLog()
        self.sink = TimedSink(sink, self.calls)
        self.prog = AsyncProgress(self.sink)
        self.pre: dict = {}                           # job.json, уже прочитанный при выборе (одним заходом вместе с ls): имя → задание
        self.prev_put = None                          # длительность предыдущей записи result.json (в этом результате её ещё нет)
        self.done: set = set()
        self.hot: set = set()                         # горячие хеши текущего списка: из кэша по размеру не выселяются
        self.hot_ts = None                            # метка списка, который уже подтянут
        self.warm_stat: dict = {}
        self._locks: dict = {}
        self._locks_guard = threading.Lock()
        os.makedirs(os.path.join(WORK, 'cache'), exist_ok=True)
        os.makedirs(os.path.join(WORK, 'blobs'), exist_ok=True)

    def _lock(self, key: str) -> threading.Lock:
        """Один замок на хеш: одну и ту же вещь два потока (или два заказа подряд) не скачивают разом."""
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def progress(self, jid: str, stage: str) -> None:
        self.prog.set(jid, stage)

    def _probe(self, n: str) -> dict:
        """Каталог-кандидат: `ls` и чтение `job.json` — ОДНИМ заходом (два обращения параллельно, T-24/12). → {names | err, job}."""
        out: dict = {'job': None}

        def read_job():
            try:
                out['job'] = self.sink.get_json(f'{JP.PREFIX}/{n}/job.json')
            except Exception:  # noqa: BLE001 — нет файла/сбой: run_job прочитает сам
                out['job'] = None
        th = threading.Thread(target=read_job, daemon=True)
        th.start()
        try:
            out['names'] = {f['name'] for f in self.sink.ls(f'{JP.PREFIX}/{n}').get('files', [])}
        except JP.SinkError as e:
            out['err'] = e
        th.join()
        return out

    def pick(self):
        """Первое готовое к работе задание (старые — вперёд) или None."""
        now = time.time()
        self.calls.reset()
        try:
            dirs = self.sink.ls(JP.PREFIX).get('dirs', [])
        except JP.SinkError as e:
            log('ls', e)
            return None
        for d in sorted(dirs, key=lambda x: x.get('mtime', 0)):
            n = d['name']
            if n == JP.HOT_DIR:                    # горячий список витрины — не задание
                continue
            if n in self.done or now - float(d.get('mtime', 0)) > MAX_AGE:
                continue
            pr = self._probe(n)
            if 'err' in pr:      # сетевой сбой/таймаут посреди перечня: не падать (воркер умирал — T-24/4, живая пара 23:34), пропустить до следующего круга
                log('ls задания', n, pr['err'])
                return None
            names = pr['names']
            if 'result.json' in names or 'cancel.json' in names:
                self.done.add(n)
                continue
            if 'job.json' in names:
                if isinstance(pr['job'], dict):
                    self.pre[n] = pr['job']
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
        trim_blobs(os.path.join(WORK, 'blobs'), set(by_sha) | self.hot)
        return {'assets': len(job['assets']), 'downloaded': len(dl), 'dl_mb': round(sum(dl) / 2 ** 20, 1)}

    def warm(self, items: list, busy=lambda: bool(MA.STATE.get('busy')), sleep=time.sleep) -> dict:
        """Подтянуть в кэш ассеты горячего списка [(sha, size)] (по порядку, до HOT_GB, HOT_PAR потоков). Пока идёт пара (`busy()`), новый ассет не начинаем: заказ приоритетнее.
        Ошибка одного ассета (не скачался/не сошёлся хеш) — считаем и идём дальше. → {n, taken, dl_mb, errors, s}."""
        todo, total = [], 0
        for sha, size in items:
            if total + size > HOT_GB * 2 ** 30:
                break
            total += size
            todo.append((sha, size))
        self.hot = {h for h, _ in todo}
        t0 = time.time()
        st = {'n': len(todo), 'taken': 0, 'dl_mb': 0.0, 'errors': 0, 'cut': len(items) - len(todo)}

        def one(item):
            sha, size = item
            while busy():
                sleep(0.5)
            return self.fetch_asset(sha, size)
        with ThreadPoolExecutor(max_workers=max(1, HOT_PAR)) as pool:
            futs = [pool.submit(one, it) for it in todo]
            for f in futs:
                try:
                    _, got = f.result()
                except Exception as e:  # noqa: BLE001 — подогрев не должен ронять воркер: ошибка ассета не страшна, заказ докачает сам
                    st['errors'] += 1
                    log('подогрев: ассет не взят', type(e).__name__, str(e)[:120])
                    continue
                st['taken'] += 1
                st['dl_mb'] += got / 2 ** 20
        st['dl_mb'], st['s'] = round(st['dl_mb'], 1), round(time.time() - t0, 1)
        trim_blobs(os.path.join(WORK, 'blobs'), self.hot)
        return st

    def warm_loop(self) -> None:
        """Фоновый поток: после готовности — прогрев по горячему списку; потом раз в HOT_REFRESH_S смотрим, не обновился ли он."""
        while True:
            if not MA.STATE.get('ready'):
                time.sleep(POLL)
                continue
            if 'hot' not in MA.STATE:
                MA.STATE['hot'] = {'done': False}       # T-24/10: контроллер объявляет «прогрелась» после первого прохода по горячему списку (поле уходит в ready.json)
            try:
                hot = self.sink.get_json(JP.HOT_REL)
                items = JP.parse_hot(hot)
                if items and hot.get('ts') != self.hot_ts:
                    self.warm_stat = self.warm(items)
                    if not self.warm_stat['errors']:
                        self.hot_ts = hot.get('ts')              # были ошибки — в следующий круг пробуем снова
                    log('подогрев: список', hot.get('n'), 'шт.', self.warm_stat)
            except (JP.SinkError, ValueError):
                pass                                 # списка нет/приёмник не отвечает — ничего не делаем, заказы идут как обычно
            except Exception as e:  # noqa: BLE001
                log('подогрев сбой', type(e).__name__, str(e)[:160])
            if not MA.STATE['hot'].get('done'):
                ws = self.warm_stat or {}
                MA.STATE['hot'] = {'done': True, 'n': ws.get('n', 0), 'taken': ws.get('taken', 0), 'errors': ws.get('errors', 0), 's': ws.get('s', 0)}
            time.sleep(HOT_REFRESH_S)

    def run_job(self, jid: str) -> dict:
        """Задание целиком; в ответ добавлены `calls` (журнал обращений к приёмнику, T-24/12) и `prev_result_put_s`. Запись хода — вне критического пути, перед возвратом закрыта."""
        self.t_job = time.time()
        try:
            res = self._run_job(jid)
        finally:
            self.prog.close(jid)
        res['calls'] = self.calls.snapshot(self.t_job)
        if self.prev_put is not None:
            res['prev_result_put_s'] = self.prev_put
        return res

    def _run_job(self, jid: str) -> dict:
        job = self.pre.pop(jid, None) or self.sink.get_json(f'{JP.PREFIX}/{jid}/job.json')
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
        log('сцена готова: fmt', job['v'], f"{timing['fetch']} с", stats or '')
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
        fr = frames_of(job)
        up = FrameUploader(self.sink, jid, work, fr)       # T-24/11: кадр уходит в приёмник, пока Blender считает следующий

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
            _tt = round(time.time() - t1, 2)
            if 'bl_first_line' not in timing:
                timing['bl_first_line'] = _tt                    # T-20261118-09/3: куда уходят секунды Blender — запуск процесса до первой строки
            if line.startswith('SCENE_BUILD_SEC '):
                timing['bl_scene_ready'] = _tt                   # сборка сцены в Blender закончена (от запуска процесса)
                try:
                    timing['bl_scene_py'] = round(float(line.split()[1]), 2)      # то же по часам самой программы (от её начала)
                except (ValueError, IndexError):
                    pass
            if line.startswith('DEVICE_USED'):
                timing['bl_device_ready'] = _tt
            if line.startswith('RENDER_SEC '):
                timing[f'bl_end_{cam_of_line(line) or "x"}'] = _tt      # кадр готов (от запуска процесса)
            if line.startswith('DEVICE_USED'):
                device = line.split(' ', 1)[1]
                if device.startswith('CPU'):       # GPU не поднялся: считать на CPU машины ×30 медленнее — не нужно, пусть исполнитель решит
                    killed = 'cpu'
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except OSError:
                        pass
            cam_done = cam_of_line(line)
            if cam_done in job['cams']:
                up.start(cam_done)
            if line.startswith('MASK_SEC '):
                try:
                    timing['mask'] = round(float(line.split()[1]), 2)      # цена прохода масок (смена материалов + 1 выборка на ракурс)
                except (ValueError, IndexError):
                    pass
            nxt, add = parse_progress(line, job['cams'])
            if add:
                timing.update(add)
            if nxt:
                self.progress(jid, nxt)
        rc = proc.wait()
        timing['render'] = round(time.time() - t1, 1)
        timing['bl_exit'] = round(time.time() - t1, 2)
        if killed == 'cpu':
            return err('gpu_failed', 'Видеокарта машины не взялась за рендер.', 'The machine GPU did not take the render.', device=device)
        if killed == 'timeout':
            return err('render_timeout', 'Рендер занял слишком много времени.', 'The render took too long.', device=device)
        names = [n for c in job['cams'] for n in JP.frame_names(fr, c)]
        paths = [os.path.join(work, n) for n in names]
        if rc != 0 or not all(os.path.isfile(p) and os.path.getsize(p) > 0 for p in paths):
            log('blender rc', rc, ' | '.join(tail[-6:]))
            return err('render_failed', 'Рендер не удался.', 'The render failed.', device=device, rc=rc, tail='\n'.join(tail[-8:])[-600:])
        self.progress(jid, 'save')
        for c in job['cams']:
            up.start(c)                  # на случай, если строку RENDER_SEC не разобрали (старый render_cycles): повторно не уйдёт
        tu = time.time()
        sizes = up.join()
        timing['upload_tail'] = round(time.time() - tu, 1)      # сколько выгрузка тянулась ПОСЛЕ конца Blender (0 — всё ушло параллельно)
        files = {c: sizes[JP.frame_names(fr, c)[0]] for c in job['cams']}
        if fr == 'both':
            files.update({n: sizes[n] for n in names if n.endswith('.png')})
        if job.get('masks'):
            # маски поверхностей — НЕОБЯЗАТЕЛЬНЫ: нет файла или выгрузка не вышла — кадры уйдут без них (приглушение пятен просто не сработает), задание не падает
            tm_ = time.time()
            ms = {}
            for c in job['cams']:
                mp = os.path.join(work, JP.mask_name(c))
                try:
                    if os.path.isfile(mp) and os.path.getsize(mp) > 0:
                        self.sink.put_file(f'{JP.PREFIX}/{jid}/{JP.mask_name(c)}', mp)
                        ms[c] = os.path.getsize(mp)
                except Exception as e:  # noqa: BLE001
                    log('маска не ушла', c, repr(e)[:100])
            res_extra['masks'] = ms
            timing['mask_up'] = round(time.time() - tm_, 2)
        qa = qa_reports(work, fr, job['cams'])
        if qa:
            res_extra['qa'] = qa          # урезанные отчёты сторожа по кадрам: исполнитель решает по ним, публиковать ли пару (ворота, T-20261118-03/7)
        timing['total'] = round(time.time() - t0, 1)
        return {'ok': True, 'timing': timing, 'device': device, 'files': files, 'frames': fr, **res_extra}

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
                    tp = time.time()
                    self.sink.put(f'{JP.PREFIX}/{jid}/result.json', json.dumps(res, ensure_ascii=False).encode())   # ПОСЛЕДНИМ
                    self.prev_put = round(time.time() - tp, 2)
                except JP.SinkError as e:
                    log('result PUT ОШИБКА', e)      # исполнитель не дождётся и уйдёт на запасной; второй раз GPU не жжём
            self.done.add(jid)
            log('задание', jid, 'ok' if res.get('ok') else res.get('error', {}).get('code') or 'отменено')


def main() -> int:
    base, tok = os.environ.get('MESH_SINK_URL', ''), os.environ.get('MESH_SINK_TOKEN', '')
    if not base or not tok:
        log('нет MESH_SINK_URL/MESH_SINK_TOKEN — воркер не работает')
        return 2
    MA.STATE['caps'] = {'frames': list(JP.FRAMES_CAPS), 'masks': 1}      # T-24/11: что воркер умеет (уходит в ready.json → state контроллера → исполнитель шлёт jpg только такой машине)
    threading.Thread(target=MA.main, daemon=True, name='agent').start()      # готовность и отметка ready.json — как у агента
    w = Worker(JP.Sink(base, tok))
    threading.Thread(target=w.warm_loop, daemon=True, name='warm').start()      # подогрев кэша ассетов — своим потоком, заказ приоритетнее
    w.loop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
