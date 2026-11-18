#!/usr/bin/env python3
"""ПОСТОЯННЫЙ ПРОЦЕСС ВЫГРУЗКИ МЕШЕЙ И КАМЕР (T-20261118-09/1, шаг 6a): тот же `export_scene.main_export`, но без запуска интерпретатора и импортов на каждый заказ
(≈0,8 с + выход ≈0,6 с) и с кэшем РАЗОБРАННЫХ мешей между заказами (разбор GLB ≈1,5 с на гостиную; `draft_render._S3_PARTS` — тот же кэш, что у сервиса кадров).
Запускает исполнитель (`render_exec.ExportClient`); построчный протокол JSON по stdin/stdout:
  → {"cmd":"export","data":<data.json>,"idx":0,"out":<папка задания>,"log":<файл журнала>}   ← {"ok":true,"sec":..,"rss_mb":..,"parts":N} | {"ok":false,"error":"…"}
  → {"cmd":"stop"}
Вывод экспорта (в т.ч. строки TRACE и «пропущен») — в журнал заказа, как у отдельного процесса. Заказы идут по одному (клиент держит замок).
Память: после заказа кэш разобранных мешей сжимается до использованных в последних `KEEP_REQUESTS` заказах и не более `MAX_PARTS` штук; процесс выходит сам, если
RSS выше `RSS_MAX_MB` (клиент поднимет новый при следующем заказе) или простаивает `IDLE_S` секунд. Файл меша изменился (размер/время) — запись кэша сбрасывается.
Без Blender и без сети (меши — из кэша GLB сервиса, докачка как у `draft_render._scene3d_glb`)."""
import contextlib
import json
import os
import resource
import select
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

IDLE_S = float(os.environ.get('EXPORT_SERVER_IDLE_S', '120'))
RSS_MAX_MB = float(os.environ.get('EXPORT_SERVER_RSS_MB', '1400'))
MAX_PARTS = int(os.environ.get('EXPORT_SERVER_MAX_PARTS', '8'))
KEEP_REQUESTS = int(os.environ.get('EXPORT_SERVER_KEEP_REQUESTS', '3'))


def rss_mb() -> float:
    try:
        for ln in open('/proc/self/status'):
            if ln.startswith('VmRSS:'):
                return int(ln.split()[1]) / 1024.0
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


class PartsCache:
    """Надзор за `draft_render._S3_PARTS`: подпись файла (размер, время) — файл заменили, запись долой; в конце заказа — оставить недавно использованные."""

    def __init__(self, DR):
        self.DR = DR
        self.sig: dict = {}            # ключ → (размер, mtime_ns) файла на момент разбора
        self.used_at: dict = {}        # ключ → номер заказа, где использовался последний раз
        self.n = 0
        orig = DR._scene3d_parts

        def wrapped(glb):
            self.used_at[glb] = self.n
            return orig(glb)
        DR._scene3d_parts = wrapped

    @staticmethod
    def _path(key):
        k = key[0] if isinstance(key, tuple) else key
        return k if isinstance(k, str) and os.path.sep in k else None

    def begin(self):
        self.n += 1
        P = self.DR._S3_PARTS
        for key in list(P):
            path = self._path(key)
            if not path:
                continue                # служебные формы (окно, тв) строятся кодом — файла нет
            try:
                st = os.stat(path)
                cur = (st.st_size, st.st_mtime_ns)
            except OSError:
                P.pop(key, None)
                continue
            if self.sig.get(key) not in (None, cur):
                P.pop(key, None)        # файл заменили — разобрать заново
            self.sig[key] = cur

    def end(self):
        P = self.DR._S3_PARTS
        for key in list(P):
            path = self._path(key)
            if path and key not in self.sig:
                try:
                    st = os.stat(path)
                    self.sig[key] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    pass
        fresh = [k for k in P if self._path(k) and self.n - self.used_at.get(k, 0) < KEEP_REQUESTS]
        old = [k for k in P if self._path(k) and k not in fresh]
        for k in old:
            P.pop(k, None)
            self.sig.pop(k, None)
        if len(fresh) > MAX_PARTS:
            for k in sorted(fresh, key=lambda k: self.used_at.get(k, 0))[:len(fresh) - MAX_PARTS]:
                P.pop(k, None)
                self.sig.pop(k, None)

    def count(self) -> int:
        return sum(1 for k in self.DR._S3_PARTS if self._path(k))


def serve(inp=sys.stdin, out=sys.stdout):
    import export_scene as ES
    ES.preload()
    import draft_render as DR
    cache = PartsCache(DR)
    out.write(json.dumps({'ready': True, 'rss_mb': round(rss_mb())}) + '\n')
    out.flush()
    while True:
        r, _, _ = select.select([inp], [], [], IDLE_S)
        if not r:
            return 0                    # простой — выходим (следующий заказ поднимет процесс)
        line = inp.readline()
        if not line:
            return 0
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get('cmd') == 'stop':
            return 0
        t0 = time.time()
        ok, err = True, ''
        try:
            cache.begin()
            ES.reset_trace()
            D = json.load(open(req['data'], encoding='utf-8'))
            with open(req['log'], 'a', encoding='utf-8') as lf, contextlib.redirect_stdout(lf), contextlib.redirect_stderr(lf):
                try:
                    ES.main_export(D, int(req.get('idx', 0)), os.path.join(req['out'], 'scene'))
                except BaseException:   # noqa: BLE001 — любая ошибка заказа в журнал, процесс жив
                    traceback.print_exc()
                    ok, err = False, 'исключение выгрузки (см. журнал заказа)'
        except Exception as e:  # noqa: BLE001
            ok, err = False, f'{type(e).__name__}: {str(e)[:200]}'
        cache.end()
        rss = rss_mb()
        out.write(json.dumps({'ok': ok, 'error': err, 'sec': round(time.time() - t0, 2), 'rss_mb': round(rss), 'parts': cache.count()}) + '\n')
        out.flush()
        if rss > RSS_MAX_MB:
            return 0


if __name__ == '__main__':
    sys.exit(serve())
