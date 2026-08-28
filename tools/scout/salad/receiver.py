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

_lock = threading.Lock()


def dir_gb() -> float:
    total = 0
    for dirpath, _, files in os.walk(ROOT):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total / 2 ** 30


def free_gb() -> float:
    st = os.statvfs(ROOT)
    return st.f_bavail * st.f_frsize / 2 ** 30


def safe(prefix: str, name: str = '') -> str:
    """Путь строго внутри ROOT: префикс приходит снаружи, `..` в нём быть не должно."""
    p = os.path.normpath(os.path.join(ROOT, prefix.strip('/'), name))
    if p != ROOT and not p.startswith(ROOT + os.sep):
        raise ValueError('плохой путь')
    return p


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
        # Место проверяем ДО чтения тела: незачем принимать 60 МБ, чтобы потом их выбросить
        with _lock:
            if dir_gb() > MAX_DIR_GB or free_gb() < MIN_FREE_GB:
                return self._send(507, {'detail': f'нет места: каталог {dir_gb():.1f} ГБ, '
                                                  f'свободно {free_gb():.1f} ГБ — нужен drain'})
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return self._send(400, {'detail': 'пустое тело'})
        if n > MAX_FILE_MB * 2 ** 20:
            return self._send(413, {'detail': 'файл слишком большой'})
        try:
            d = safe(prefix, '.staging')
        except ValueError:
            return self._send(400, {'detail': 'плохой путь'})
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, name + '.part')
        got = 0
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
        os.replace(tmp, os.path.join(d, name))
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

        for name in have:
            os.replace(os.path.join(staging, name), os.path.join(dest, name))
        shutil.rmtree(staging, ignore_errors=True)
        # МАРКЕР — СТРОГО ПОСЛЕДНИМ: до этой строки комплекта «не существует» для повторов
        with open(os.path.join(dest, 'complete.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
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
        shutil.rmtree(p, ignore_errors=True)
        self._send(204)


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('нет MESH_SINK_TOKEN — приёмник без токена не поднимаю')
    os.makedirs(ROOT, exist_ok=True)
    print(f'приёмник на {BIND}:{PORT}, корень {ROOT}', flush=True)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
