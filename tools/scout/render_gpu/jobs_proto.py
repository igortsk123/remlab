"""ПРОТОКОЛ ЗАДАНИЙ МАШИНЕ РЕНДЕРА (T-20261117-24/2): общий для исполнителя (DEV, `render_exec.SaladGpuExecutor`), воркера в контейнере
(`render_worker.py`) и уборки (`jobs_purge.py`). ТОЛЬКО стандартная библиотека — воркер работает на python из Blender.

Хранилище — приёмник `mesh-sink` (`receiver.py`), ТОЛЬКО префикс `renderjobs/` (раздача `GET /files`, `GET /ls` — только он). Один каталог на задание:
    renderjobs/<job_id>/bundle-<sha12>.tgz  — сцена: scene/ (меши), dump/ (декор, отделка), render_cycles.py, wall-art.json, карты public/
    renderjobs/<job_id>/job.json            — ПОСЛЕДНИМ: {v, job_id, bundle, sha, cams, args, limits, created}
    renderjobs/<job_id>/progress.json       — от воркера: {stage: scene|C1|C2|save, ts}
    renderjobs/<job_id>/C1.png, C2.png      — кадры (скачивает исполнитель)
    renderjobs/<job_id>/result.json         — от воркера ПОСЛЕДНИМ: {ok, timing, device, files, error:{code,ru,en}}
    renderjobs/<job_id>/cancel.json         — от исполнителя: «не бери, я ушёл на запасной» (воркер проверяет до начала)
Читатель видит задание только когда есть job.json, результат — только когда есть result.json (как complete.json у мешей).

FMT 2 (T-20261117-24/5, Э2а): неизменяемые тяжёлые файлы (текстуры PNG, GLB декора, карты отделки, программа рендера) лежат НЕ в пакете задания, а в отдельном
префиксе приёмника `renderassets/<ab>/<sha256 полный>` (имя = хеш содержимого; PUT проверяет хеш; `POST /have/renderassets` отвечает «каких нет»).
Исполнитель досылает недостающее ДО `job.json`; в `job.json` (v=2) — короткий манифест {path, sha256, size, kind} + маленький пакет (карта сцены, npz, отделка).
Воркер на машине держит ассеты в своём кэше по хешу (хеш и размер сверяются при КАЖДОМ взятии), собирает рабочий каталог жёсткими ссылками и рендерит тем же Blender.
v=1 (всё в одном пакете) работает как раньше; нет `have` у приёмника, ошибка ассета, несовместимая версия — исполнитель идёт на fmt 1, затем на CPU.
Токен приёмника нигде не печатается."""
import hashlib
import http.client
import io
import json
import os
import re
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PREFIX = 'renderjobs'
ASSET_PREFIX = 'renderassets'
HOT_DIR = '_hot'                       # «горячий список»: каталог рядом с заданиями (не задание: файла job.json в нём нет)
HOT_REL = f'{PREFIX}/{HOT_DIR}/hot.json'
PROTO = 1
PROTO2 = 2
SUPPORTED = (PROTO, PROTO2)
CAMS = ('C1', 'C2')
FRAMES = ('png', 'jpg', 'both')     # формат кадров с машины (T-24/11): png — как раньше; jpg — кодирует Blender; both — jpg и png из одного результата (ТОЛЬКО приёмка ΔE)
MASK_SCALE = 0.25                  # маски поверхностей (пол/стена) для приглушения солнечных пятен «Улучшить» (T-20261118-05/3): 1/4 размера кадра — достаточно для окна σ12
FRAMES_CAPS = ('png', 'jpg')       # что умеет воркер (машина заявляет в ready.json: caps.frames); `both` — отладочный, в заявку не входит
UA = 'remlab-render/1.0'


class SinkError(Exception):
    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


class Sink:
    """Клиент приёмника: PUT в `/staging/…`, чтение `GET /files/…` и `/ls/…`. Повторы — на сетевых сбоях и 5xx.
    ПОСТОЯННОЕ СОЕДИНЕНИЕ (T-20261118-09/5 ❸): на каждый поток — свой `http.client` с keep-alive; новое TCP+TLS на каждый вызов (urllib) стоило ≈0,19 с с DEV и ≈0,45 с с машины,
    на готовом соединении — ≈0,05 с (замер 18.11). Оборвалось соединение (сервер закрыл простаивающее) — один раз заново на свежем. Протокол и ответы те же."""

    def __init__(self, base: str, token: str, retries: int = 3, timeout: float = 120):
        self.base, self.token, self.retries, self.timeout = base.rstrip('/'), token, retries, timeout
        self._u = urllib.parse.urlparse(self.base)
        self._tl = threading.local()

    def _conn(self, timeout: float):
        c = getattr(self._tl, 'c', None)
        if c is None:
            cls = http.client.HTTPSConnection if self._u.scheme == 'https' else http.client.HTTPConnection
            c = self._tl.c = cls(self._u.hostname, self._u.port, timeout=timeout)
        c.timeout = timeout
        if c.sock is not None:
            c.sock.settimeout(timeout)
        return c

    def _drop(self) -> None:
        c = getattr(self._tl, 'c', None)
        self._tl.c = None
        if c is not None:
            try:
                c.close()
            except OSError:
                pass

    def _call(self, method: str, path: str, data=None, headers=None, timeout=None, to_file=None):
        """Один запрос по постоянному соединению → (статус, тело | размер, записанный в to_file). Ответ вычитывается ПОЛНОСТЬЮ (иначе соединение не переиспользовать).
        Статус ≥ 400 — `urllib.error.HTTPError`, как раньше (дальше `_do`). Сбой связи на ПЕРЕИСПОЛЬЗУЕМОМ соединении — один повтор на новом."""
        h = {'Authorization': f'Bearer {self.token}', 'User-Agent': UA, **(headers or {})}
        full = (self._u.path.rstrip('/') or '') + path
        timeout = timeout or self.timeout
        for attempt in (1, 2):
            fresh = getattr(self._tl, 'c', None) is None
            try:
                c = self._conn(timeout)
                if hasattr(data, 'seek'):
                    data.seek(0)
                c.request(method, full, body=data, headers=h)
                r = c.getresponse()
                if r.status >= 400:
                    r.read()
                    if r.will_close:
                        self._drop()
                    raise urllib.error.HTTPError(f'{self.base}{path}', r.status, r.reason, r.headers, None)
                if to_file is None:
                    body = r.read()
                    if r.will_close:
                        self._drop()
                    return r.status, body
                n = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    to_file.write(chunk)
                    n += len(chunk)
                if r.will_close:
                    self._drop()
                return r.status, n
            except (http.client.HTTPException, OSError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    raise
                self._drop()
                if attempt == 1 and not fresh and not isinstance(e, TimeoutError):
                    if to_file is not None:
                        to_file.seek(0)
                        to_file.truncate()
                    continue                      # соединение было «старое» — закрыто сервером в простое: один раз на новом (таймаут не повторяем: ждали бы дважды)
                raise

    def _do(self, make, what: str):
        last = None
        for i in range(self.retries):
            try:
                return make()
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise SinkError(f'{what}: HTTP {e.code}', e.code) from None
                last = SinkError(f'{what}: HTTP {e.code}', e.code)
            except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as e:
                last = SinkError(f'{what}: {type(e).__name__}')
            time.sleep(min(2 ** i, 8))
        raise last

    def put(self, rel: str, data: bytes) -> None:
        """rel — `<prefix>/<job>/<name>`; PUT идёт в `/staging/…` (так принимает приёмник)."""
        self._do(lambda: self._call('PUT', f'/staging/{urllib.parse.quote(rel)}', data, {'Content-Type': 'application/octet-stream'}), f'PUT {rel}')

    def put_file(self, rel: str, path: str) -> None:
        """Файл (пакет в десятки МБ) — потоком, не читая в память: приёмнику нужен Content-Length."""
        size = os.path.getsize(path)

        def go():
            with open(path, 'rb') as f:
                return self._call('PUT', f'/staging/{urllib.parse.quote(rel)}', f, {'Content-Type': 'application/octet-stream', 'Content-Length': str(size)},
                                  timeout=max(self.timeout, 600))
        self._do(go, f'PUT {rel}')

    def post_json(self, path: str, obj) -> dict:
        body = json.dumps(obj, ensure_ascii=False).encode()
        return self._do(lambda: json.loads(self._call('POST', path, body, {'Content-Type': 'application/json'})[1]), f'POST {path}')

    def have_assets(self, items: list) -> list:
        """Какие из {sha256, size} на приёмнике ОТСУТСТВУЮТ (список sha). 404/405 = приёмник старый (без fmt 2) — `SinkError` с кодом."""
        out: list = []
        for i in range(0, len(items), 500):
            out += self.post_json(f'/have/{ASSET_PREFIX}', {'items': items[i:i + 500]}).get('missing', [])
        return out

    def put_asset(self, sha: str, path: str) -> None:
        self.put_file(f'{ASSET_PREFIX}/{sha[:2]}/{sha}', path)

    def get_asset_to(self, sha: str, dest: str) -> int:
        return self.get_to(f'{ASSET_PREFIX}/{sha[:2]}/{sha}', dest)

    def get(self, rel: str) -> bytes:
        return self._do(lambda: self._call('GET', f'/files/{urllib.parse.quote(rel)}')[1], f'GET {rel}')

    def get_to(self, rel: str, dest: str) -> int:
        """Скачать файл потоком в `dest` (через `.part`, потом подмена); → размер."""
        def go():
            tmp = dest + '.part'
            with open(tmp, 'wb') as f:
                _, n = self._call('GET', f'/files/{urllib.parse.quote(rel)}', timeout=max(self.timeout, 600), to_file=f)
            os.replace(tmp, dest)
            return n
        return self._do(go, f'GET {rel}')

    def get_json(self, rel: str):
        return json.loads(self.get(rel))

    def ls(self, rel: str) -> dict:
        """`<prefix>` → {'dirs': [{name, mtime}]}, `<prefix>/<job>` → {'files': [{name, size, mtime}]}; 404 → пусто."""
        def go():
            return json.loads(self._call('GET', f'/ls/{urllib.parse.quote(rel)}')[1])
        try:
            return self._do(go, f'LS {rel}')
        except SinkError as e:
            if e.code == 404:
                return {'dirs': [], 'files': []}
            raise

    def delete(self, rel: str) -> int:
        """DELETE /prefix/… (счётчик приёмника сходится только так); 404 — уже нет."""
        try:
            self._do(lambda: self._call('DELETE', f'/prefix/{urllib.parse.quote(rel)}', timeout=60), f'DELETE {rel}')
            return 1
        except SinkError as e:
            if e.code == 404:
                return 0
            raise


# ——— пакет сцены
def pack_bundle(files: dict, dest: str) -> str:
    """files: {путь внутри архива: путь на диске | каталог}. Архив воспроизводимый (имена по порядку, mtime=0, владелец 0) — одинаковая
    сцена даёт одинаковый sha. → sha256[:12] содержимого архива; файл — `dest`."""
    import gzip
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0, compresslevel=6) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tf:
            items = []
            for arc, src in files.items():
                if os.path.isdir(src):
                    for dp, dn, fs in os.walk(src):
                        dn.sort()
                        for f in sorted(fs):
                            p = os.path.join(dp, f)
                            if not os.path.islink(p):
                                items.append((os.path.join(arc, os.path.relpath(p, src)), p))
                elif os.path.isfile(src):
                    items.append((arc, src))
            for arc, p in sorted(items):
                ti = tarfile.TarInfo(arc.replace(os.sep, '/'))
                ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = os.path.getsize(p), 0, 0o644, 0, 0, '', ''
                with open(p, 'rb') as f:
                    tf.addfile(ti, f)
    data = buf.getvalue()
    with open(dest, 'wb') as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()[:12]


UNPACK_MAX_FILES = 3000
UNPACK_MAX_MB = 600


def unpack_bundle(path: str, dest: str, max_files: int = UNPACK_MAX_FILES, max_mb: float = UNPACK_MAX_MB) -> list:
    """Распаковка в `dest` с фильтром `data` (без выхода за каталог, ссылок наружу, устройств) и лимитами: число файлов и распакованный объём
    проверяются ДО записи (пакет-бомба не заполнит диск). → список имён верхнего уровня; нарушение лимита — ValueError."""
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(path, 'r:gz') as tf:
        members = tf.getmembers()
        total = sum(m.size for m in members if m.isreg())
        if len(members) > max_files or total > max_mb * 2 ** 20 or any(not (m.isreg() or m.isdir()) for m in members):
            raise ValueError(f'пакет не по лимитам: {len(members)} записей, {total / 2 ** 20:.0f} МБ')
        tf.extractall(dest, filter='data')
    return sorted(os.listdir(dest))


def sha256_file(path: str) -> str:
    """Полный sha256 файла (потоком)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def file_sha12(path: str) -> str:
    return sha256_file(path)[:12]


# ——— задание
def new_job(job_id: str, bundle: str, sha: str, args: list, limits: dict, cams=CAMS, now=None, masks: bool = False) -> dict:
    job = {'v': PROTO, 'job_id': job_id, 'bundle': bundle, 'sha': sha, 'cams': list(cams), 'args': [str(a) for a in args],
           'limits': dict(limits), 'created': round(now if now is not None else time.time(), 1)}
    if masks:
        job['masks'] = 1                  # маски поверхностей после кадров — только машине, заявившей caps.masks (старый воркер отвергнет лишнее поле)
    return job


ASSET_KINDS = ('tex', 'glb', 'map', 'code', 'data')
ASSET_MAX_N = 600                      # число ассетов в одном задании
ASSET_MAX_MB = 95                      # один ассет (потолок PUT приёмника)
ASSET_TOTAL_MB = 1500                  # сумма по заданию
_COMP = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$')      # один сегмент пути: не `.`/`..`, не скрытый, без пробелов и слэшей
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_JOB_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}$')
_ARG = re.compile(r'^[A-Za-z0-9_.,:=+\- ]{1,100}$')      # значение может быть с пробелами («Khronos PBR Neutral», пресет v3): воркер запускает Blender списком, без оболочки


def _arg_ok(a) -> bool:
    """Аргумент: строка из безопасных знаков; флаг (`-…`) — без пробелов; значение — без пробелов по краям и двойных."""
    if not isinstance(a, str) or not _ARG.match(a):
        return False
    if a.startswith('-'):
        return ' ' not in a
    return a == a.strip() and '  ' not in a

_BUNDLE1 = re.compile(r'^bundle-[0-9a-f]{12}\.tgz$')
_BUNDLE2 = re.compile(r'^bundle-[0-9a-f]{16}\.tgz$')
# флаги, которые воркер ставит сам — задание не может подменить пути и сцену своими
OWN_FLAGS = {'--scene-dir', '--out', '--cam', '--demo-glb', '--demo-nodes', '--export', '--public', '--device', '--persistent', '--jpeg-quality', '--also-png', '--mask-out', '--mask-scale'}


def valid_rel_path(p) -> bool:
    """Путь внутри рабочего каталога задания: до 6 сегментов, каждый — плоское имя (`_COMP`); без `..`, `.`, скрытых, `\\`, NUL, абсолютных."""
    if not isinstance(p, str) or not p or len(p) > 400 or p.startswith('/') or '\x00' in p or '\\' in p:
        return False
    parts = p.split('/')
    return len(parts) <= 6 and all(_COMP.match(x) for x in parts)


def asset_ref(path: str, sha256: str, size: int, kind: str) -> dict:
    return {'path': path, 'sha256': sha256, 'size': int(size), 'kind': kind}


def manifest_sha(bundle: dict, assets: list) -> str:
    """Хеш ВСЕГО манифеста (маленький пакет + ссылки на ассеты) в каноническом виде: порядок ссылок и пробелы не влияют. Воркер пересчитывает и сверяет."""
    canon = json.dumps({'bundle': {k: bundle.get(k) for k in ('name', 'sha256', 'size')}, 'assets': sorted(({k: a.get(k) for k in ('path', 'sha256', 'size', 'kind')}
                        for a in assets), key=lambda a: a['path'])}, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()


HOT_MAX_N = 2000


def new_hot(assets: list, now=None, note: str = '') -> dict:
    """Горячий список (T-24/7, «подогрев»): какие ассеты нужны витрине (/demo, туры) — DEV пишет его на приёмник после того, как ассеты залиты; машина при прогреве подтягивает их
    в свой кэш, уборка приёмника их не трогает. `assets` — [{sha256, size}], порядок = важность (вперёд — нужнее). Дубли хешей убираются."""
    seen, out = set(), []
    for a in assets:
        h = a.get('sha256')
        if h in seen or not isinstance(h, str) or not re.match(r'^[0-9a-f]{64}$', h):
            continue
        seen.add(h)
        out.append({'sha256': h, 'size': int(a.get('size') or 0)})
    return {'v': 1, 'ts': round(now if now is not None else time.time(), 1), 'n': len(out), 'mb': round(sum(a['size'] for a in out) / 2 ** 20, 1), 'note': str(note)[:200], 'assets': out}


def parse_hot(obj) -> list:
    """Горячий список из присланного JSON → [(sha256, size)] только годных записей (хеш из 64 hex, размер 1…ASSET_MAX_MB МБ), не больше HOT_MAX_N. Чужое/битое — пусто."""
    if not isinstance(obj, dict) or obj.get('v') != 1 or not isinstance(obj.get('assets'), list):
        return []
    out, seen = [], set()
    for a in obj['assets'][:HOT_MAX_N]:
        if not isinstance(a, dict):
            continue
        h, n = a.get('sha256'), a.get('size')
        if not (isinstance(h, str) and re.match(r'^[0-9a-f]{64}$', h)) or h in seen:
            continue
        if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= ASSET_MAX_MB * 2 ** 20):
            continue
        seen.add(h)
        out.append((h, n))
    return out


def new_job2(job_id: str, bundle: dict, assets: list, args: list, limits: dict, render: str, cams=CAMS, now=None, frames: str = 'png', jpeg_q: int = 92, masks: bool = False) -> dict:
    """fmt 2: `bundle` = {name, sha256, size} маленького пакета; `assets` — список `asset_ref`; `render` — хеш версий рендера (диагностика и сверка)."""
    job = {'v': PROTO2, 'job_id': job_id, 'schema': PROTO2, 'render': str(render)[:32], 'manifest_sha': manifest_sha(bundle, assets),
           'bundle': {k: bundle[k] for k in ('name', 'sha256', 'size')}, 'assets': [dict(a) for a in assets], 'cams': list(cams),
           'args': [str(a) for a in args], 'limits': dict(limits), 'created': round(now if now is not None else time.time(), 1)}
    if frames != 'png':
        job['frames'], job['jpeg_q'] = frames, int(jpeg_q)            # нет поля = png (старые воркеры его не знают: шлём только машине, заявившей caps.frames)
    if masks:
        job['masks'] = 1
    return job


def mask_name(cam: str) -> str:
    """Имя файла маски поверхностей ракурса в каталоге задания (и в каталоге рендера рядом с кадром)."""
    return f'{cam}.mask.png'


def frame_names(frames: str, cam: str) -> list:
    """Имена файлов кадра в каталоге задания по формату: имя = формат (`C1.jpg` — JPEG, `C1.png` — PNG)."""
    return {'png': [f'{cam}.png'], 'jpg': [f'{cam}.jpg'], 'both': [f'{cam}.jpg', f'{cam}.png']}[frames]


def _num(x, lo, hi) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi


def _common_check(job: dict) -> str:
    cams = job.get('cams')
    if not isinstance(cams, list) or not cams or len(cams) > len(CAMS) or len(set(cams)) != len(cams) or any(c not in CAMS for c in cams):
        return 'ракурсы'
    args = job.get('args')
    if not isinstance(args, list) or len(args) > 64 or not all(_arg_ok(a) for a in args):
        return 'аргументы'
    # пути и сцену задаёт воркер сам — задание не может подменить их своими флагами
    if any(a in OWN_FLAGS for a in args):
        return 'аргумент зарезервирован воркером'
    lim = job.get('limits')
    if not isinstance(lim, dict) or set(lim) - {'blenderSec'} or ('blenderSec' in lim and not _num(lim['blenderSec'], 10, 7200)):
        return 'лимиты'
    if not _num(job.get('created'), 0, 4e9):
        return 'время создания'
    return ''


def validate_job(job: dict, expect_id: str | None = None) -> str:
    """'' — годится; иначе причина (воркер отвечает result.json с ошибкой, а не исполняет). `expect_id` — имя каталога, где лежит задание: `job_id` обязан
    ему равняться (задание не может выдать себя за чужое). Схема строгая: лишние ключи, чужие типы, неизвестные флаги и лимиты — отказ."""
    if not isinstance(job, dict) or job.get('v') not in SUPPORTED:
        return 'версия протокола'
    if 'masks' in job and (job['masks'] != 1 or isinstance(job['masks'], bool)):
        return 'маски'
    jid = job.get('job_id')
    if not isinstance(jid, str) or not _JOB_ID.match(jid) or (expect_id is not None and jid != expect_id):
        return 'имя задания'
    if job['v'] == PROTO:
        if set(job) - {'v', 'job_id', 'bundle', 'sha', 'cams', 'args', 'limits', 'created', 'masks'}:
            return 'лишние поля'
        if not isinstance(job.get('bundle'), str) or not _BUNDLE1.match(job['bundle']) or not isinstance(job.get('sha'), str) or not re.match(r'^[0-9a-f]{12}$', job['sha']):
            return 'имя пакета'
        return _common_check(job)
    # v = 2
    if set(job) - {'v', 'job_id', 'schema', 'render', 'manifest_sha', 'bundle', 'assets', 'cams', 'args', 'limits', 'created', 'frames', 'jpeg_q', 'masks'}:
        return 'лишние поля'
    if 'frames' in job and job['frames'] not in FRAMES:
        return 'формат кадров'
    if 'jpeg_q' in job and ('frames' not in job or not isinstance(job['jpeg_q'], int) or isinstance(job['jpeg_q'], bool) or not 50 <= job['jpeg_q'] <= 100):
        return 'качество JPEG'
    if job.get('schema') != PROTO2:
        return 'версия схемы'
    b = job.get('bundle')
    if not isinstance(b, dict) or set(b) != {'name', 'sha256', 'size'} or not isinstance(b['name'], str) or not _BUNDLE2.match(b['name']) \
            or not isinstance(b['sha256'], str) or not _HEX64.match(b['sha256']) or b['name'] != f"bundle-{b['sha256'][:16]}.tgz" or not _num(b['size'], 1, ASSET_MAX_MB * 2 ** 20):
        return 'пакет'
    assets = job.get('assets')
    if not isinstance(assets, list) or len(assets) > ASSET_MAX_N:
        return 'ассеты'
    seen, total = set(), 0
    for a in assets:
        if not isinstance(a, dict) or set(a) != {'path', 'sha256', 'size', 'kind'} or not valid_rel_path(a['path']) or a['path'] in seen \
                or not isinstance(a['sha256'], str) or not _HEX64.match(a['sha256']) or not isinstance(a['size'], int) or isinstance(a['size'], bool) \
                or not 1 <= a['size'] <= ASSET_MAX_MB * 2 ** 20 or a['kind'] not in ASSET_KINDS:
            return 'ассет: ' + str(a.get('path') if isinstance(a, dict) else a)[:80]
        seen.add(a['path'])
        total += a['size']
    if total > ASSET_TOTAL_MB * 2 ** 20:
        return 'ассеты: слишком много'
    if not isinstance(job.get('render'), str) or len(job['render']) > 32:
        return 'версия рендера'
    if job.get('manifest_sha') != manifest_sha(b, assets):
        return 'хеш манифеста не сходится'
    return _common_check(job)


# ——— решение «машина годна» — ДАННЫМИ из состояния контроллера
def machine_verdict(state: dict, now: float, rules: dict) -> tuple[bool, str]:
    """(можно ли отдавать задание машине, причина-код). Чистая функция от `state.json` контроллера и правил:
    желаемое «включено», группа прогрелась в этом запуске, нет деградации, контроллер жив (последняя отметка свежа)."""
    if state.get('desired') != 'on':
        return False, 'off'
    if state.get('warm_gen') != state.get('gen') or not state.get('gen'):
        return False, 'warming'
    if state.get('degraded_since'):
        return False, 'degraded'
    if now - float(state.get('last_tick') or 0) > rules.get('controller_stale_s', 300):
        return False, 'controller_silent'
    return True, 'ready'
