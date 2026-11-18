#!/usr/bin/env python3
"""Приёмник мешей на НАШЕЙ стороне: ноды Salad кладут результат сюда, минуя объектное хранилище.

Ставится на exit-fi (единственная машина проекта с публичным адресом). Дев-машина ноде
недоступна, поэтому сервер работает ТРАНЗИТОМ: принял → отдал по запросу → `drain.sh` утащил
на дев-машину и освободил место.

ТОЛЬКО СТАНДАРТНАЯ БИБЛИОТЕКА — намеренно. На exit-fi рядом живёт боевая VPN-нода, и ставить
туда pip с FastAPI ради приёмника файлов — лишний риск и лишние зависимости на машине, которую
нельзя ронять. `http.server` здесь достаточно: нагрузка — десяток параллельных нод.

ПОЧЕМУ ЭТО НЕ ПРОСТО «PUT В ПАПКУ»:
  * exit-fi нельзя забить: превышен `MESH_MAX_DIR_GB` или мало свободного — отвечаем 507,
    нода получает честную ошибку, задание возвращается в очередь;
  * оборванная закачка не должна выглядеть готовым результатом: файлы падают в `.staging`,
    и только POST /complete переносит комплект и последним пишет `complete.json`;
  * повтор задания после прерывания ноды обязан узнать, что работа сделана, иначе GPU
    сожжётся второй раз — GET /complete/<prefix>.

  Запуск: MESH_SINK_TOKEN=... MESH_ROOT=/opt/remlab/meshes python3 receiver.py
"""
import hashlib
import json
import re
import os
import shutil
import stat
import threading
import time
import uuid
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.environ.get('MESH_ROOT', '/opt/remlab/meshes'))
TOKEN = os.environ.get('MESH_SINK_TOKEN', '')
MAX_DIR_GB = float(os.environ.get('MESH_MAX_DIR_GB', '8'))
MIN_FREE_GB = float(os.environ.get('MESH_MIN_FREE_GB', '5'))
MAX_FILE_MB = float(os.environ.get('MESH_MAX_FILE_MB', '80'))
PORT = int(os.environ.get('MESH_SINK_PORT', '8770'))
# Слушаем ШЛЮЗ docker-сети, а не 0.0.0.0: так приёмник доступен контейнеру Caddy (он и
# терминирует TLS для нод), но НЕ поднимается на публичном интерфейсе сервера. Разница
# существенна: рядом живёт боевая VPN-нода, лишний открытый порт там не нужен.
BIND = os.environ.get('MESH_SINK_BIND', '127.0.0.1')
# РАЗДАЧА ФАЙЛОВ (T-20261117-24/2, машина рендера): контейнеру Salad нужно СКАЧАТЬ задание (сцена ≈65 МБ). Раздаём read-only и ТОЛЬКО префиксы
# из этого списка (данные, по умолчанию один — `renderjobs`); меши и всё прочее по GET /files не отдаются никогда. Потолок размера файла
# для этих префиксов на PUT — SERVE_MAX_MB (пакет сцены больше обычного 80 МБ-потолка меша).
SERVE_PREFIXES = tuple(p.strip().strip('/') for p in os.environ.get('MESH_SERVE_PREFIXES', 'renderjobs,renderassets').split(',') if p.strip())
# НЕИЗМЕНЯЕМЫЕ АССЕТЫ ЗАДАНИЙ (T-20261117-24/5, fmt 2): `renderassets/<2 hex>/<sha256 полный>` — имя файла = хеш содержимого, ключ и проверка целостности в одном.
# Свой счётчик и свой потолок (`MESH_ASSET_MAX_GB`), не счётчик заданий и не мешей; свободное место на диске — общее. PUT проверяет хеш, пишет во временный файл
# с уникальным именем и подменяет атомарно; «уже есть» — успех. Уборка по сроку/размеру — `render_gpu/jobs_purge.py` (DELETE файла ассета).
ASSET_PREFIX = 'renderassets'
ASSET_MAX_GB = float(os.environ.get('MESH_ASSET_MAX_GB', '1.5'))
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX2 = re.compile(r'^[0-9a-f]{2}$')
HAVE_MAX = 1000
# Caddy режет тело запроса на 100 МБ (`caddy/Caddyfile`), поэтому потолок пакета — 95 МБ: больший PUT всё равно не дошёл бы, пусть отказ будет понятным и нашим.
SERVE_MAX_MB = float(os.environ.get('MESH_SERVE_MAX_MB', '95'))
# Раздаваемые префиксы НЕ входят в счётчик мешей (`MAX_DIR_GB`): ворота мешей их байтов не видят. У них свой счётчик и свой потолок; свободное место на диске — общее:
SERVE_MAX_DIR_GB = float(os.environ.get('MESH_SERVE_MAX_DIR_GB', '2'))
LS_LIMIT = 500

# RLock: `dir_gb()` пересчитывает под замком и сам зовётся из-под него (гейт PUT в `_would_refuse`)
_lock = threading.RLock()
# РАЗМЕР КАТАЛОГА — ИНКРЕМЕНТАЛЬНО (04.09, Codex): раньше каждый /health и каждый PUT обходили
# весь каталог os.walk'ом; на десятках тысяч комплектов это само стало бы узким местом, а
# проверку места звали бы раз в 45 с из супервизора конвейера. Считаем один раз при старте,
# дальше прибавляем принятые байты и вычитаем удалённые. Плюс РЕЗЕРВ под активные PUT:
# несколько загрузок разом проходили гейт, каждая видела «место есть», и диск переполнялся.
#
# СЧЁТЧИК ОБЯЗАН СХОДИТЬСЯ С ДИСКОМ (20.10, mesh-12). За 6 недель без перезапуска он ушёл на +5.6 ГБ
# (6.3 ГБ при 0.74 ГБ на диске): 507 сносил `.staging` с уже учтёнными файлами, а повторная выкладка
# комплекта затирала файлы, не вычитая старые. Ворота конвейера закрываются на max−1 = 7 ГБ, так что
# фантом съел почти всё место и 17.10 остановил волну. Дыры закрыты ниже, и на случай новых —
# пересчёт обходом раз в RECOUNT_S (на сотнях комплектов — доли секунды). Недописанные `.part` в
# обход не входят: их байты уже стоят в резерве своего PUT.
_SIZE = {'bytes': 0, 'reserved': 0, 'inited': False, 'at': 0.0}
_SERVED = {'bytes': 0, 'reserved': 0, 'inited': False, 'at': 0.0}      # раздаваемые префиксы (renderjobs): свой счётчик, свой потолок
_ASSETS = {'bytes': 0, 'reserved': 0, 'inited': False, 'at': 0.0}      # ассеты заданий (renderassets): свой счётчик, свой потолок
RECOUNT_S = float(os.environ.get('MESH_SIZE_RECOUNT_S', '600'))


def is_served(prefix: str) -> bool:
    """Префикс (путь `<префикс>/…`) принадлежит раздаваемому каталогу: его байты — в `_SERVED`, не в счётчике мешей."""
    return prefix.strip('/').split('/')[0] in SERVE_PREFIXES


def is_asset(prefix: str) -> bool:
    return ASSET_PREFIX in SERVE_PREFIXES and prefix.strip('/').split('/')[0] == ASSET_PREFIX


def _acct(prefix: str) -> dict:
    return _ASSETS if is_asset(prefix) else _SERVED if is_served(prefix) else _SIZE


def _walk_bytes(top: str = ROOT) -> int:
    """Байты под `top` (без `.part`). Обход ROOT целиком раздаваемые префиксы пропускает — они в своём счётчике."""
    total = 0
    for dirpath, dirs, files in os.walk(top):
        if dirpath == ROOT:
            dirs[:] = [d for d in dirs if d not in SERVE_PREFIXES]
        for f in files:
            if f.endswith('.part'):
                continue
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total


def dir_gb() -> float:
    if not _SIZE['inited'] or time.time() - _SIZE['at'] > RECOUNT_S:
        walked = _walk_bytes()
        with _lock:
            _SIZE.update(bytes=walked, inited=True, at=time.time())
    return (_SIZE['bytes'] + _SIZE['reserved']) / 2 ** 30


def _prefix_walk(prefixes) -> int:
    return sum(_walk_bytes(os.path.join(ROOT, p)) for p in prefixes if os.path.isdir(os.path.join(ROOT, p)) and not os.path.islink(os.path.join(ROOT, p)))


def served_gb() -> float:
    """Размер каталога заданий (раздаваемые префиксы КРОМЕ ассетов) — инкрементально, как `dir_gb()`; пересчёт обходом раз в RECOUNT_S (не на каждый PUT)."""
    if not _SERVED['inited'] or time.time() - _SERVED['at'] > RECOUNT_S:
        walked = _prefix_walk(p for p in SERVE_PREFIXES if p != ASSET_PREFIX)
        with _lock:
            _SERVED.update(bytes=walked, inited=True, at=time.time())
    return (_SERVED['bytes'] + _SERVED['reserved']) / 2 ** 30


def assets_gb() -> float:
    """Размер ассетов заданий (`renderassets`) — свой счётчик, пересчёт обходом раз в RECOUNT_S."""
    if not _ASSETS['inited'] or time.time() - _ASSETS['at'] > RECOUNT_S:
        walked = _prefix_walk([ASSET_PREFIX] if ASSET_PREFIX in SERVE_PREFIXES else [])
        with _lock:
            _ASSETS.update(bytes=walked, inited=True, at=time.time())
    return (_ASSETS['bytes'] + _ASSETS['reserved']) / 2 ** 30


def _would_refuse(extra_bytes: int = 0, served: bool = False, asset: bool = False) -> str:
    """Почему PUT на `extra_bytes` получит 507 — или пусто, если место есть. Раздаваемый префикс — свой потолок (`SERVE_MAX_DIR_GB`),
    мешам — `MAX_DIR_GB`; свободное место на диске проверяется общее."""
    if asset:
        if assets_gb() + extra_bytes / 2 ** 30 > ASSET_MAX_GB:
            return f'ассеты {assets_gb():.2f} ГБ (предел {ASSET_MAX_GB:g}) — нужна уборка'
    elif served:
        if served_gb() + extra_bytes / 2 ** 30 > SERVE_MAX_DIR_GB:
            return f'каталог заданий {served_gb():.2f} ГБ (предел {SERVE_MAX_DIR_GB:g}) — нужна уборка'
    elif dir_gb() + extra_bytes / 2 ** 30 > MAX_DIR_GB:
        return f'каталог {dir_gb():.1f} ГБ (предел {MAX_DIR_GB}) — нужен drain'
    if free_gb() - extra_bytes / 2 ** 30 < MIN_FREE_GB:
        return f'свободно {free_gb():.1f} ГБ (< {MIN_FREE_GB})'
    return ''


def free_gb() -> float:
    st = os.statvfs(ROOT)
    return st.f_bavail * st.f_frsize / 2 ** 30


def safe(prefix: str, name: str = '') -> str:
    """Путь строго внутри ROOT: префикс приходит снаружи, `..` в нём быть не должно."""
    p = os.path.normpath(os.path.join(ROOT, prefix.strip('/'), name))
    if p != ROOT and not p.startswith(ROOT + os.sep):
        raise ValueError('плохой путь')
    return p


def serve_rel(rel: str, depth: tuple) -> list | None:
    """Разбор пути раздачи (после `/files/` или `/ls/`, уже раскодированного ОДИН раз). Возвращает сегменты или None.
    Правила: первый сегмент — разрешённый префикс; число сегментов из `depth`; ни пустых, ни `.`/`..`, ни скрытых (`.staging` добавляем сами),
    ни `\\`, NUL, абсолютного пути. Всё, что не подошло, — None (ответ 404: чужие префиксы не выдают даже факт существования)."""
    if not rel or '\x00' in rel or '\\' in rel or rel.startswith('/'):
        return None
    seg = rel.split('/')
    if len(seg) not in depth or any(x in ('', '.', '..') or x.startswith('.') for x in seg):
        return None
    if seg[0] not in SERVE_PREFIXES:
        return None
    return seg


def _inside_real(path: str, base: str) -> bool:
    """Путь реально внутри `base`: без симлинков по пути (ни одного звена-ссылки) и после realpath."""
    rb = os.path.realpath(base)
    rp = os.path.realpath(path)
    if rp != rb and not rp.startswith(rb + os.sep):
        return False
    cur = base
    for part in os.path.relpath(path, base).split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            return False
    return True


def serve_open(seg: list):
    """seg = [префикс, задание, имя] → (открытый файл, размер) или None. Файл ищем в `.staging` задания, затем в постоянном каталоге; `.part` не отдаём.
    Сам каталог префикса — не ссылка (проверка от ROOT), по пути ни одного звена-ссылки, файл открывается БЕЗ следования ссылкам (O_NOFOLLOW)
    и размер берётся из fstat открытого файла — подмена между проверкой и открытием отдаёт не то, что проверили, не может."""
    name = seg[-1]
    if name.endswith('.part'):
        return None
    base = os.path.join(ROOT, seg[0])
    if not _inside_real(base, ROOT):
        return None
    for d in (os.path.join(base, seg[1], '.staging'), os.path.join(base, seg[1])):
        p = os.path.join(d, name)
        if not _inside_real(p, base):
            continue
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        except OSError:
            continue
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            continue
        return os.fdopen(fd, 'rb'), st.st_size
    return None


def _scan(d: str, want_dirs: bool, limit: int | None = None) -> list:
    """Записи каталога без сортировки всего: идём по scandir и останавливаемся на `limit` подходящих (скрытые, `.part`, симлинки — не берём)."""
    limit = LS_LIMIT if limit is None else limit
    rows = []
    try:
        with os.scandir(d) as it:
            for e in it:
                n = e.name
                if n.startswith('.') or n.endswith('.part'):
                    continue
                try:
                    if e.is_symlink() or (e.is_dir(follow_symlinks=False) != want_dirs) or (not want_dirs and not e.is_file(follow_symlinks=False)):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                rows.append((n, st))
                if len(rows) >= limit:
                    break
    except OSError:
        return []
    return rows


def serve_ls(seg: list) -> dict | None:
    """seg = [префикс] — задания (каталоги); [префикс, задание] — файлы задания (имя, размер, время). Глубже — нельзя."""
    base = os.path.join(ROOT, seg[0])
    out = {'now': time.time()}
    if not _inside_real(base, ROOT):                  # сам каталог префикса — ссылка или вне корня: пусто
        return {**out, 'dirs': []} if len(seg) == 1 else {**out, 'files': []}
    if len(seg) == 1:
        return {**out, 'dirs': [{'name': n, 'mtime': round(st.st_mtime, 1)} for n, st in _scan(base, True)]}
    files = {}
    for d in (os.path.join(base, seg[1]), os.path.join(base, seg[1], '.staging')):
        if not os.path.isdir(d) or not _inside_real(d, base):
            continue
        for n, st in _scan(d, False):
            files[n] = {'name': n, 'size': st.st_size, 'mtime': round(st.st_mtime, 1)}
    return {**out, 'files': list(files.values())}


class Handler(BaseHTTPRequestHandler):
    server_version = 'remlab-mesh-sink'

    def log_message(self, fmt, *args):     # тише журнала systemd
        pass

    def _send(self, code: int, obj=None):
        body = json.dumps(obj if obj is not None else {}, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True      # клиент ушёл до ответа — тихо закрываем

    def _auth(self) -> bool:
        if TOKEN and self.headers.get('Authorization') == f'Bearer {TOKEN}':
            return True
        self._send(401, {'detail': 'нет токена'})
        return False

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            return self._send(200, {'ok': True, 'dir_gb': round(dir_gb(), 2), 'assets_gb': round(assets_gb(), 2),
                                    'free_gb': round(free_gb(), 2), 'max_dir_gb': MAX_DIR_GB,
                                    'ready': not _would_refuse()})
        if path == '/ready':
            # честный ответ «примет ли PUT сейчас» — для пред-проверки конвейера; O(1)
            why = _would_refuse()
            return self._send(200 if not why else 507,
                              {'ok': not why, 'detail': why, 'dir_gb': round(dir_gb(), 2),
                               'free_gb': round(free_gb(), 2), 'max_dir_gb': MAX_DIR_GB})
        if not self._auth():
            return
        if path == '/list':
            out = [os.path.relpath(d, ROOT) for d, _, fs in os.walk(ROOT)
                   if 'complete.json' in fs]
            return self._send(200, {'count': len(out), 'prefixes': sorted(out),
                                    'dir_gb': round(dir_gb(), 2)})
        if path.startswith('/complete/'):
            try:
                p = safe(path[len('/complete/'):], 'complete.json')
            except ValueError:
                return self._send(400, {'detail': 'плохой путь'})
            if not os.path.exists(p):
                return self._send(404, {'detail': 'не готово'})
            return self._send(200, json.load(open(p, encoding='utf-8')))
        if path.startswith('/files/') or path.startswith('/ls/'):
            is_files = path.startswith('/files/')
            rel = urllib.parse.unquote(path[len('/files/' if is_files else '/ls/'):])   # раскодируем ОДИН раз: %2e%2e → `..` → отказ
            if not is_files and rel.endswith('/'):
                rel = rel[:-1]                                      # один завершающий `/` терпим; `renderjobs//` → пустой сегмент → 404
            seg = serve_rel(rel, (3,) if is_files else (1, 2))
            if seg is None:
                return self._send(404, {'detail': 'нет такого'})
            if not is_files:
                return self._send(200, serve_ls(seg))
            opened = serve_open(seg)
            if opened is None:
                return self._send(404, {'detail': 'нет такого'})
            f, size = opened
            try:
                with f:                                    # открыт и измерен ДО заголовков: Content-Length — из fstat того же файла
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(size))
                    self.end_headers()
                    sent = 0
                    while sent < size:                     # потоком: пакет в десятки МБ в память не читаем
                        chunk = f.read(min(1 << 20, size - sent))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        sent += len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True               # клиент ушёл — тихо закрываем
            return
        self._send(404, {'detail': 'нет такого'})

    # ---------------------------------------------------------------- PUT
    def do_PUT(self):
        if not self._auth():
            return
        path = self.path.split('?')[0]
        if not path.startswith('/staging/'):
            return self._send(404, {'detail': 'нет такого'})
        rel = path[len('/staging/'):]
        prefix, _, name = rel.rpartition('/')
        if not name or name.startswith('.') or os.sep in name:
            return self._send(400, {'detail': 'плохое имя файла'})
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return self._send(400, {'detail': 'пустое тело'})
        if is_asset(prefix):
            return self._put_asset(prefix, name, n)
        served = is_served(prefix)
        acct = _acct(prefix)
        cap_mb = SERVE_MAX_MB if served else MAX_FILE_MB
        if n > cap_mb * 2 ** 20:
            return self._send(413, {'detail': 'файл слишком большой'})
        try:
            d = safe(prefix, '.staging')
        except ValueError:
            return self._send(400, {'detail': 'плохой путь'})
        if served and not _inside_real(d, ROOT):          # каталог префикса или задания — ссылка: не пишем (makedirs пошёл бы по ней)
            return self._send(400, {'detail': 'плохой путь'})
        # Место проверяем ДО чтения тела и РЕЗЕРВИРУЕМ его под этот файл — под одним замком,
        # чтобы параллельные PUT не прошли гейт все разом (04.09). При отказе сносим staging
        # этого префикса: первые файлы комплекта уже легли и иначе остались бы навсегда.
        with _lock:
            why = _would_refuse(n, served)
            if why:
                if not served:       # задания рендера не сносим: их убирает исполнитель/уборка, а не отказ PUT
                    # байты уже легших файлов комплекта учтены — вычесть, иначе счётчик только растёт
                    gone = _walk_bytes(d) if os.path.isdir(d) else 0
                    shutil.rmtree(d, ignore_errors=True)
                    _SIZE['bytes'] = max(0, _SIZE['bytes'] - gone)
                return self._send(507, {'detail': f'нет места: {why}'})
            acct['reserved'] += n                          # резерв под замком — параллельные PUT не пройдут потолок все разом
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, name + '.part')
        got = 0
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if got != n:
                os.remove(tmp)
                return self._send(400, {'detail': f'тело оборвано: {got} из {n}'})
            prev = os.path.getsize(os.path.join(d, name)) if os.path.exists(os.path.join(d, name)) else 0
            os.replace(tmp, os.path.join(d, name))
            with _lock:
                acct['bytes'] += got - prev
        finally:
            with _lock:
                acct['reserved'] = max(0, acct['reserved'] - n)     # освобождаем на ВСЕХ выходах (успех, обрыв, исключение)
        self._send(200, {'ok': True, 'bytes': got})


    # ---------------------------------------------------------------- ассеты заданий (fmt 2)
    def _put_asset(self, prefix: str, name: str, n: int):
        """PUT /staging/renderassets/<ab>/<sha256>: имя = хеш содержимого. Тело пишется во ВРЕМЕННЫЙ файл с уникальным именем (два одновременных PUT одного
        ассета не пишут в один файл), хеш и длина сверяются, затем атомарная подмена; «уже есть» (тот же размер) — успех, файл не трогаем. Место — своё
        (`ASSET_MAX_GB`) + общее свободное на диске; резерв под замком, как у заданий."""
        seg = prefix.strip('/').split('/')
        if len(seg) != 2 or not HEX2.match(seg[1]) or not HEX64.match(name) or name[:2] != seg[1]:
            return self._send(400, {'detail': 'плохое имя ассета (нужно <ab>/<sha256 полный>)'})
        if n > SERVE_MAX_MB * 2 ** 20:
            return self._send(413, {'detail': 'файл слишком большой'})
        d = os.path.join(ROOT, ASSET_PREFIX, seg[1])
        if not _inside_real(d, ROOT):                       # каталог ассетов или шарда — ссылка: не пишем
            return self._send(400, {'detail': 'плохой путь'})
        with _lock:
            why = _would_refuse(n, asset=True)
            if why:
                return self._send(507, {'detail': f'нет места: {why}'})
            _ASSETS['reserved'] += n
        tmp = os.path.join(d, f'.{name}.{uuid.uuid4().hex}.part')
        final = os.path.join(d, name)
        got = 0
        h = hashlib.sha256()
        try:
            os.makedirs(d, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, 'wb') as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
            if got != n:
                os.remove(tmp)
                return self._send(400, {'detail': f'тело оборвано: {got} из {n}'})
            if h.hexdigest() != name:
                os.remove(tmp)
                return self._send(400, {'detail': 'хеш содержимого не сходится с именем'})
            with _lock:
                prev = os.path.getsize(final) if os.path.isfile(final) and not os.path.islink(final) else 0
                existed = prev == got
                if existed:
                    os.remove(tmp)                               # тот же ассет уже лежит (хеш = имя): успех, не перезаписываем
                    os.utime(final)                              # «использован сейчас» — для уборки по давности
                else:
                    os.chmod(tmp, 0o444)
                    os.replace(tmp, final)
                    _ASSETS['bytes'] += got - prev
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return self._send(500, {'detail': f'не записано: {type(e).__name__}'})
        finally:
            with _lock:
                _ASSETS['reserved'] = max(0, _ASSETS['reserved'] - n)
        return self._send(200, {'ok': True, 'bytes': got, 'existed': existed})

    def _have(self):
        """POST /have/renderassets {"items":[{"sha256","size"}…]} → {"missing":[sha…],"have":N}. «Есть» = обычный файл (не ссылка) того же размера;
        найденное помечаем использованным сейчас (уборка по давности не снесёт ассеты заказа, который вот-вот выйдет)."""
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > 262144:
            return self._send(400, {'detail': 'плохой размер запроса'})
        try:
            items = (json.loads(self.rfile.read(n)) or {}).get('items')
        except (ValueError, AttributeError):
            return self._send(400, {'detail': 'плохой запрос'})
        if not isinstance(items, list) or len(items) > HAVE_MAX:
            return self._send(400, {'detail': f'нужен список до {HAVE_MAX}'})
        if ASSET_PREFIX not in SERVE_PREFIXES or not _inside_real(os.path.join(ROOT, ASSET_PREFIX), ROOT):
            return self._send(404, {'detail': 'ассеты не раздаются'})
        missing, have = [], 0
        for it in items:
            sha, size = (it.get('sha256'), it.get('size')) if isinstance(it, dict) else (None, None)
            if not isinstance(sha, str) or not HEX64.match(sha) or not isinstance(size, int) or isinstance(size, bool) or size < 0:
                return self._send(400, {'detail': 'элемент: нужны sha256 (64 hex) и size'})
            p = os.path.join(ROOT, ASSET_PREFIX, sha[:2], sha)
            try:
                st = os.lstat(p)
            except OSError:
                missing.append(sha)
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size != size:
                missing.append(sha)
                continue
            have += 1
            try:
                os.utime(p)
            except OSError:
                pass
        return self._send(200, {'missing': missing, 'have': have})

    # ---------------------------------------------------------------- POST / DELETE
    def do_POST(self):
        if not self._auth():
            return
        path = self.path.split('?')[0]
        if path == '/have/' + ASSET_PREFIX:
            return self._have()
        if not path.startswith('/complete/'):
            return self._send(404, {'detail': 'нет такого'})
        n = int(self.headers.get('Content-Length') or 0)
        try:
            meta = json.loads(self.rfile.read(n) or b'{}')
            prefix = path[len('/complete/'):]
            staging, dest = safe(prefix, '.staging'), safe(prefix)
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {'detail': 'плохой запрос'})
        acct = _acct(prefix)
        if is_served(prefix) and not _inside_real(dest, ROOT):
            return self._send(400, {'detail': 'плохой путь'})
        if not os.path.isdir(staging):
            return self._send(400, {'detail': 'нет загруженных файлов'})

        have = set(os.listdir(staging))
        need = set((meta.get('files') or {}).keys())
        if not need <= have:
            return self._send(400, {'detail': f'не хватает: {sorted(need - have)}'})
        for name, size in (meta.get('files') or {}).items():
            actual = os.path.getsize(os.path.join(staging, name))
            if actual != size:
                return self._send(400, {'detail': f'{name}: пришло {actual}, заявлено {size}'})

        def size_of(p: str) -> int:
            return os.path.getsize(p) if os.path.isfile(p) else 0
        for name in have:
            if name.endswith('.part'):     # чужой недописанный PUT — его байты в резерве, не наши
                continue
            # ПОВТОРНАЯ ВЫКЛАДКА затирает прежний файл: его байты уходят с диска — вычесть
            replaced = size_of(os.path.join(dest, name))
            os.replace(os.path.join(staging, name), os.path.join(dest, name))
            with _lock:
                acct['bytes'] = max(0, acct['bytes'] - replaced)
        shutil.rmtree(staging, ignore_errors=True)
        # МАРКЕР — СТРОГО ПОСЛЕДНИМ: до этой строки комплекта «не существует» для повторов
        marker = os.path.join(dest, 'complete.json')
        before = size_of(marker)
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
        with _lock:
            acct['bytes'] = max(0, acct['bytes'] + size_of(marker) - before)
        self._send(200, {'ok': True, 'files': len(have)})

    def do_DELETE(self):
        """Удаление ПОСЛЕ откачки на дев-машину. Транзит не должен копить."""
        if not self._auth():
            return
        path = self.path.split('?')[0]
        if not path.startswith('/prefix/'):
            return self._send(404, {'detail': 'нет такого'})
        try:
            p = safe(path[len('/prefix/'):])
        except ValueError:
            return self._send(400, {'detail': 'плохой путь'})
        rel_del = path[len('/prefix/'):]
        if p == ROOT or not rel_del.strip('/'):                      # пустой/корневой префикс: снёс бы весь каталог приёмника
            return self._send(400, {'detail': 'нельзя удалить корень'})
        if rel_del.strip('/') in SERVE_PREFIXES:                      # раздаваемый префикс целиком (renderjobs) — тоже нельзя, только задание внутри
            return self._send(400, {'detail': 'нельзя удалить каталог префикса целиком — только задание внутри'})
        if is_asset(rel_del):                                         # ассет — файл `renderassets/<ab>/<sha256>`; шард/весь префикс — нельзя
            seg = rel_del.strip('/').split('/')
            if len(seg) != 3 or not HEX2.match(seg[1]) or not HEX64.match(seg[2]) or seg[2][:2] != seg[1]:
                return self._send(400, {'detail': 'ассет удаляется по <ab>/<sha256>'})
            if not _inside_real(p, ROOT):
                return self._send(404, {'detail': 'нет такого'})
            try:
                st = os.lstat(p)
                if not stat.S_ISREG(st.st_mode):
                    return self._send(404, {'detail': 'нет такого'})
                with _lock:
                    os.remove(p)
                    _ASSETS['bytes'] = max(0, _ASSETS['bytes'] - st.st_size)
            except OSError:
                return self._send(404, {'detail': 'нет такого'})
            return self._send(204)
        if not os.path.isdir(p) or (is_served(rel_del) and not _inside_real(p, ROOT)):
            return self._send(404, {'detail': 'нет такого'})
        freed = _walk_bytes(p)    # та же мера, что у счётчика (без `.part` — те в резерве)
        shutil.rmtree(p, ignore_errors=True)
        with _lock:
            acct = _acct(path[len('/prefix/'):])
            acct['bytes'] = max(0, acct['bytes'] - freed)
        self._send(204)


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('нет MESH_SINK_TOKEN — приёмник без токена не поднимаю')
    os.makedirs(ROOT, exist_ok=True)
    print(f'приёмник на {BIND}:{PORT}, корень {ROOT}', flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
