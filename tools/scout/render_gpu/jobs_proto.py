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
Токен приёмника нигде не печатается."""
import hashlib
import io
import json
import os
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

PREFIX = 'renderjobs'
PROTO = 1
CAMS = ('C1', 'C2')
UA = 'remlab-render/1.0'


class SinkError(Exception):
    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


class Sink:
    """Клиент приёмника: PUT в `/staging/…`, чтение `GET /files/…` и `/ls/…`. Повторы — на сетевых сбоях и 5xx."""

    def __init__(self, base: str, token: str, retries: int = 3, timeout: float = 120):
        self.base, self.token, self.retries, self.timeout = base.rstrip('/'), token, retries, timeout

    def _req(self, method: str, path: str, data=None, headers=None):
        h = {'Authorization': f'Bearer {self.token}', 'User-Agent': UA, **(headers or {})}
        return urllib.request.Request(f'{self.base}{path}', data=data, method=method, headers=h)

    def _do(self, make, what: str):
        last = None
        for i in range(self.retries):
            try:
                return make()
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise SinkError(f'{what}: HTTP {e.code}', e.code) from None
                last = SinkError(f'{what}: HTTP {e.code}', e.code)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last = SinkError(f'{what}: {type(e).__name__}')
            time.sleep(min(2 ** i, 8))
        raise last

    def put(self, rel: str, data: bytes) -> None:
        """rel — `<prefix>/<job>/<name>`; PUT идёт в `/staging/…` (так принимает приёмник)."""
        def go():
            with urllib.request.urlopen(self._req('PUT', f'/staging/{urllib.parse.quote(rel)}', data, {'Content-Type': 'application/octet-stream'}),
                                        timeout=self.timeout) as r:
                r.read()
        self._do(go, f'PUT {rel}')

    def put_file(self, rel: str, path: str) -> None:
        """Файл (пакет в десятки МБ) — потоком, не читая в память: приёмнику нужен Content-Length."""
        size = os.path.getsize(path)

        def go():
            with open(path, 'rb') as f:
                req = self._req('PUT', f'/staging/{urllib.parse.quote(rel)}', f, {'Content-Type': 'application/octet-stream', 'Content-Length': str(size)})
                with urllib.request.urlopen(req, timeout=max(self.timeout, 600)) as r:
                    r.read()
        self._do(go, f'PUT {rel}')

    def get(self, rel: str) -> bytes:
        def go():
            with urllib.request.urlopen(self._req('GET', f'/files/{urllib.parse.quote(rel)}'), timeout=self.timeout) as r:
                return r.read()
        return self._do(go, f'GET {rel}')

    def get_to(self, rel: str, dest: str) -> int:
        """Скачать файл потоком в `dest` (через `.part`, потом подмена); → размер."""
        def go():
            tmp = dest + '.part'
            n = 0
            with urllib.request.urlopen(self._req('GET', f'/files/{urllib.parse.quote(rel)}'), timeout=max(self.timeout, 600)) as r, open(tmp, 'wb') as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    n += len(chunk)
            os.replace(tmp, dest)
            return n
        return self._do(go, f'GET {rel}')

    def get_json(self, rel: str):
        return json.loads(self.get(rel))

    def ls(self, rel: str) -> dict:
        """`<prefix>` → {'dirs': [{name, mtime}]}, `<prefix>/<job>` → {'files': [{name, size, mtime}]}; 404 → пусто."""
        def go():
            with urllib.request.urlopen(self._req('GET', f'/ls/{urllib.parse.quote(rel)}'), timeout=self.timeout) as r:
                return json.loads(r.read())
        try:
            return self._do(go, f'LS {rel}')
        except SinkError as e:
            if e.code == 404:
                return {'dirs': [], 'files': []}
            raise

    def delete(self, rel: str) -> int:
        """DELETE /prefix/… (счётчик приёмника сходится только так); 404 — уже нет."""
        try:
            self._do(lambda: urllib.request.urlopen(self._req('DELETE', f'/prefix/{urllib.parse.quote(rel)}'), timeout=60).read(), f'DELETE {rel}')
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


def unpack_bundle(path: str, dest: str) -> list:
    """Распаковка в `dest` с фильтром `data` (без выхода за каталог, ссылок наружу, устройств). → список имён верхнего уровня."""
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(path, 'r:gz') as tf:
        tf.extractall(dest, filter='data')
    return sorted(os.listdir(dest))


def file_sha12(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


# ——— задание
def new_job(job_id: str, bundle: str, sha: str, args: list, limits: dict, cams=CAMS, now=None) -> dict:
    return {'v': PROTO, 'job_id': job_id, 'bundle': bundle, 'sha': sha, 'cams': list(cams), 'args': [str(a) for a in args],
            'limits': dict(limits), 'created': round(now if now is not None else time.time(), 1)}


def validate_job(job: dict) -> str:
    """'' — годится; иначе причина (воркер отвечает result.json с ошибкой, а не исполняет)."""
    if not isinstance(job, dict) or job.get('v') != PROTO:
        return 'версия протокола'
    jid, bun = str(job.get('job_id', '')), str(job.get('bundle', ''))
    if not jid or '/' in jid or jid.startswith('.') or not bun or '/' in bun or bun.startswith('.'):
        return 'имя задания/пакета'
    if not job.get('cams') or any(c not in CAMS for c in job['cams']):
        return 'ракурсы'
    args = job.get('args')
    if not isinstance(args, list) or any((not isinstance(a, str)) or '\x00' in a for a in args):
        return 'аргументы'
    # пути и сцену задаёт воркер сам — задание не может подменить их своими флагами
    own = {'--scene-dir', '--out', '--cam', '--demo-glb', '--demo-nodes', '--export', '--public', '--device', '--persistent'}
    if any(a in own for a in args):
        return 'аргумент зарезервирован воркером'
    return ''


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
