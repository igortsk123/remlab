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
import json
import os
import shutil
import threading
import time
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
SERVE_PREFIXES = tuple(p.strip().strip('/') for p in os.environ.get('MESH_SERVE_PREFIXES', 'renderjobs').split(',') if p.strip())
SERVE_MAX_MB = float(os.environ.get('MESH_SERVE_MAX_MB', '200'))
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
RECOUNT_S = float(os.environ.get('MESH_SIZE_RECOUNT_S', '600'))


def _walk_bytes(top: str = ROOT) -> int:
    total = 0
    for dirpath, _, files in os.walk(top):
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


def _would_refuse(extra_bytes: int = 0) -> str:
    """Почему PUT на `extra_bytes` получит 507 — или пусто, если место есть."""
    if dir_gb() + extra_bytes / 2 ** 30 > MAX_DIR_GB:
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


def serve_file(seg: list) -> str | None:
    """seg = [префикс, задание, имя]: файл в `.staging` задания или в постоянном каталоге; `.part` не отдаём."""
    name = seg[-1]
    if name.endswith('.part'):
        return None
    base = os.path.join(ROOT, seg[0])
    for d in (os.path.join(base, seg[1], '.staging'), os.path.join(base, seg[1])):
        p = os.path.join(d, name)
        if os.path.isfile(p) and _inside_real(p, base):
            return p
    return None


def serve_ls(seg: list) -> dict | None:
    """seg = [префикс] — задания (каталоги); [префикс, задание] — файлы задания (имя, размер, время). Глубже — нельзя."""
    base = os.path.join(ROOT, seg[0])
    out = {'now': time.time()}
    if len(seg) == 1:
        if not os.path.isdir(base) or not _inside_real(base, ROOT):
            return {**out, 'dirs': []}
        rows = []
        for n in sorted(os.listdir(base))[:LS_LIMIT]:
            p = os.path.join(base, n)
            if not n.startswith('.') and os.path.isdir(p) and not os.path.islink(p):
                rows.append({'name': n, 'mtime': round(os.path.getmtime(p), 1)})
        return {**out, 'dirs': rows}
    files = {}
    for d in (os.path.join(base, seg[1]), os.path.join(base, seg[1], '.staging')):
        if not os.path.isdir(d) or not _inside_real(d, base):
            continue
        for n in sorted(os.listdir(d))[:LS_LIMIT]:
            p = os.path.join(d, n)
            if n.startswith('.') or n.endswith('.part') or not os.path.isfile(p) or os.path.islink(p):
                continue
            st = os.stat(p)
            files[n] = {'name': n, 'size': st.st_size, 'mtime': round(st.st_mtime, 1)}
    return {**out, 'files': list(files.values())}


class Handler(BaseHTTPRequestHandler):
    server_version = 'remlab-mesh-sink'

    def log_message(self, fmt, *args):     # тише журнала systemd
        pass

    def _send(self, code: int, obj=None):
        body = json.dumps(obj if obj is not None else {}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        if TOKEN and self.headers.get('Authorization') == f'Bearer {TOKEN}':
            return True
        self._send(401, {'detail': 'нет токена'})
        return False

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            return self._send(200, {'ok': True, 'dir_gb': round(dir_gb(), 2),
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
            rel = rel if is_files else rel.rstrip('/')
            seg = serve_rel(rel, (3,) if is_files else (1, 2))
            if seg is None:
                return self._send(404, {'detail': 'нет такого'})
            if not is_files:
                return self._send(200, serve_ls(seg))
            p = serve_file(seg)
            if p is None:
                return self._send(404, {'detail': 'нет такого'})
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(os.path.getsize(p)))
            self.end_headers()
            with open(p, 'rb') as f:               # потоком: пакет в десятки МБ в память не читаем
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
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
        cap_mb = SERVE_MAX_MB if prefix.split('/')[0] in SERVE_PREFIXES else MAX_FILE_MB
        if n > cap_mb * 2 ** 20:
            return self._send(413, {'detail': 'файл слишком большой'})
        try:
            d = safe(prefix, '.staging')
        except ValueError:
            return self._send(400, {'detail': 'плохой путь'})
        # Место проверяем ДО чтения тела и РЕЗЕРВИРУЕМ его под этот файл — под одним замком,
        # чтобы параллельные PUT не прошли гейт все разом (04.09). При отказе сносим staging
        # этого префикса: первые файлы комплекта уже легли и иначе остались бы навсегда.
        with _lock:
            why = _would_refuse(n)
            if why:
                # байты уже легших файлов комплекта учтены — вычесть, иначе счётчик только растёт
                gone = _walk_bytes(d) if os.path.isdir(d) else 0
                shutil.rmtree(d, ignore_errors=True)
                _SIZE['bytes'] = max(0, _SIZE['bytes'] - gone)
                return self._send(507, {'detail': f'нет места: {why}'})
            _SIZE['reserved'] += n
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, name + '.part')
        got = 0
        try:
            with open(tmp, 'wb') as f:
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
                _SIZE['bytes'] += got - prev
        finally:
            with _lock:
                _SIZE['reserved'] = max(0, _SIZE['reserved'] - n)
        self._send(200, {'ok': True, 'bytes': got})

    # ---------------------------------------------------------------- POST / DELETE
    def do_POST(self):
        if not self._auth():
            return
        path = self.path.split('?')[0]
        if not path.startswith('/complete/'):
            return self._send(404, {'detail': 'нет такого'})
        n = int(self.headers.get('Content-Length') or 0)
        try:
            meta = json.loads(self.rfile.read(n) or b'{}')
            prefix = path[len('/complete/'):]
            staging, dest = safe(prefix, '.staging'), safe(prefix)
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {'detail': 'плохой запрос'})
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
                _SIZE['bytes'] = max(0, _SIZE['bytes'] - replaced)
        shutil.rmtree(staging, ignore_errors=True)
        # МАРКЕР — СТРОГО ПОСЛЕДНИМ: до этой строки комплекта «не существует» для повторов
        marker = os.path.join(dest, 'complete.json')
        before = size_of(marker)
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
        with _lock:
            _SIZE['bytes'] = max(0, _SIZE['bytes'] + size_of(marker) - before)
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
        if not os.path.isdir(p):
            return self._send(404, {'detail': 'нет такого'})
        freed = _walk_bytes(p)    # та же мера, что у счётчика (без `.part` — те в резерве)
        shutil.rmtree(p, ignore_errors=True)
        with _lock:
            _SIZE['bytes'] = max(0, _SIZE['bytes'] - freed)
        self._send(204)


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('нет MESH_SINK_TOKEN — приёмник без токена не поднимаю')
    os.makedirs(ROOT, exist_ok=True)
    print(f'приёмник на {BIND}:{PORT}, корень {ROOT}', flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
