#!/usr/bin/env python3
"""ИСПОЛНИТЕЛИ РЕНДЕРА «СДЕЛАТЬ ФОТО» (T-20261117-19/1, шаг 3 плана `photo-render-first-01`).

Исполнитель — интерфейс: `render(snap, out_dir, progress) -> {'timing': {...}}`. Вход — снимок расстановки (`render_snapshot.canonicalize`),
выход — каталог `out_dir` с `C1.jpg`, `C2.jpg` и `meta.json` (кэш по ключу; пишется последним, подменой — читатель видит либо всё, либо
ничего). Какой исполнитель работает — настройка `RENDER_EXECUTOR`, без особых случаев в очереди:
  local-cpu  — Blender Cycles на процессоре DEV под общей очередью тяжёлых прогонов (`tools/ops/heavy_slot.py`);
  salad-gpu  — своя группа Salad под рендер (план директора): тот же вход/выход; пока машина не настроена — `ExecutorUnavailable`;
  salad-gpu,local-cpu — основной и запасной: машину вытеснили/занята (`ExecutorUnavailable`) — честное ожидание на процессоре DEV.

Конвейер local-cpu (те же шаги и те же программы, что у проб `cycles_probe`, но сборка сцены — по снимку):
  1. данные из ОДНОГО варианта снимка (`render_snapshot.synthetic_data`) → `export_scene.py` (меши мебели, полы, проёмы, камеры);
  2. `demo_scene_dump.mjs` — сцена /demo движком страницы (headless Chromium): декор (шторы группой, картины, люстра, подушки, растения,
     радиаторы) и `scene-export.json` (отделка стен и пола) — «теми же правилами выгрузки», что у живой 3D;
  3. `render_cycles.py` в Blender — по кадру на ракурс C1, C2, настройки — `cycles_probe/render-preset.json` (в ключе кэша).
Блендер и выгрузчик запускаются отдельными процессами в своей группе: по таймауту, памяти (RSS дерева) — убивается всё дерево.
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
PROBE = os.path.join(HERE, 'cycles_probe')
PRESET_FILE = os.path.join(PROBE, 'render-preset.json')
CAMS = ('C1', 'C2')
sys.path.append(os.path.join(HERE, 'render_gpu'))     # jobs_proto (протокол заданий машины рендера); render_machine — через LocalMachine


class RenderError(Exception):
    """Сбой рендера по существу: код для страницы и пара текстов (`retry` — всегда да, рендер повторяем)."""

    def __init__(self, code: str, ru: str, en: str):
        super().__init__(ru)
        self.code, self.ru, self.en = code, ru, en


class ExecutorUnavailable(RenderError):
    """Исполнитель сейчас не может (машина рендера занята/вытеснена/не настроена) — не сбой сцены; запасной путь решает `Fallback`."""


def preset() -> dict:
    return json.load(open(PRESET_FILE, encoding='utf-8'))


def _sha(*paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        try:
            h.update(open(p, 'rb').read())
        except OSError:
            h.update(b'?')
    return h.hexdigest()[:12]


def render_version(blender: str = '') -> dict:
    """Версии, из которых складывается ключ кэша: пресет, программа рендера, выгрузчики, формат экспорта сцены, Blender."""
    exp_ver = ''
    try:
        import re
        m = re.search(r'SCENE_EXPORT_VERSION\s*=\s*(\d+)', open(os.path.join(REPO, 'lib', 'viewer3d', 'scene-export.ts'), encoding='utf-8').read())
        exp_ver = m.group(1) if m else ''
    except OSError:
        pass
    return {'preset': _sha(PRESET_FILE), 'render_cycles': _sha(os.path.join(PROBE, 'render_cycles.py')),
            'export_scene': _sha(os.path.join(PROBE, 'export_scene.py')), 'dump': _sha(os.path.join(PROBE, 'demo_scene_dump.mjs'),
                                                                                    os.path.join(PROBE, 'demo_scene_entry.ts')),
            'scene_export': exp_ver, 'blender': os.path.basename(os.path.dirname(blender)) if blender else ''}


def cache_key(scene_hash: str, versions: dict) -> str:
    """Ключ кэша кадров: хеш снимка + все версии рендера. Сменилось любое — кадры считаются заново."""
    raw = scene_hash + '|' + json.dumps(versions, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ——— процессы: таймаут, память, остановка дерева
def _children(pid: int) -> list:
    """Потомки процесса по /proc (psutil на DEV нет)."""
    kids: dict = {}
    try:
        for n in os.listdir('/proc'):
            if not n.isdigit():
                continue
            try:
                st = open(f'/proc/{n}/stat', 'rb').read().decode('utf-8', 'replace')
                ppid = int(st[st.rindex(')') + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            kids.setdefault(ppid, []).append(int(n))
    except OSError:
        return []
    out, stack = [], [pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def tree_rss_gb(pid: int) -> float:
    kb = 0
    for p in [pid] + _children(pid):
        try:
            for ln in open(f'/proc/{p}/status', encoding='utf-8'):
                if ln.startswith('VmRSS:'):
                    kb += int(ln.split()[1])
                    break
        except OSError:
            continue
    return kb / 1048576.0


def kill_tree(proc: subprocess.Popen) -> None:
    """Остановить процесс и всех его потомков: своя группа процессов (start_new_session) — сперва вежливо, затем жёстко."""
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(pgid, sig)
        except OSError:
            return
        t0 = time.time()
        while time.time() - t0 < wait:
            if proc.poll() is not None:
                return
            time.sleep(0.2)


def run_step(cmd: list, log_path: str, timeout_s: float, max_rss_gb: float, env: dict | None = None, cwd: str | None = None,
             what: str = 'шаг') -> None:
    """Запуск шага: вывод — в файл, потолок времени и памяти дерева; превышение — дерево убито, RenderError."""
    with open(log_path, 'ab') as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=cwd, env={**os.environ, **(env or {})}, start_new_session=True)
        t0 = time.time()
        reason = ''
        while proc.poll() is None:
            time.sleep(0.2)      # было 1 с: до секунды на каждый шаг (T-24/4)
            if time.time() - t0 > timeout_s:
                reason = f'время вышло ({int(timeout_s)} с)'
            elif tree_rss_gb(proc.pid) > max_rss_gb:
                reason = f'память дерева выше {max_rss_gb:g} ГБ'
            if reason:
                kill_tree(proc)
                break
        rc = proc.returncode
    if reason:
        print(f'рендер: {what} остановлен — {reason}', flush=True)
        raise RenderError('render_timeout', 'Рендер занял слишком много времени или памяти. Нажмите «Повторить».',
                          'The render took too long or too much memory. Press "Retry".')
    if rc != 0:
        tail = ''
        try:
            tail = open(log_path, 'rb').read()[-600:].decode('utf-8', 'replace')
        except OSError:
            pass
        print(f'рендер: {what} rc={rc}: {tail}', flush=True)
        raise RenderError('render_failed', 'Рендер не удался. Нажмите «Повторить».', 'The render failed. Press "Retry".')


def _dir_mb(path: str) -> float:
    tot = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot / 1048576.0


def skipped_meshes(text: str) -> list:
    """Роли, чей меш экспорт пропустил (`draft_render` печатает «  scene3d: <роль> пропущен (<причина>)»). «Вид за проёмом пропущен» — не предмет."""
    import re as _re
    return sorted({m.group(1).strip() for m in _re.finditer(r'scene3d: (.+?) пропущен \(', text) if not m.group(1).startswith('вид за проёмом')})


class SceneExecutor:
    """Общая часть исполнителей (T-20261117-24/2): сборка сцены ПО СНИМКУ (меши и камеры, декор и отделка движком страницы) и сохранение результата
    (JPEG + meta подменой каталога). Одна и та же для процессора DEV и для машины на Salad — правило сборки сцены одно, различается только то,
    ГДЕ считается Blender (`LocalCpuExecutor`, `SaladGpuExecutor`)."""
    name = 'base'

    def available(self) -> bool:
        """Возьмёт ли исполнитель заказ СЕЙЧАС (для честного срока на странице); обычный — всегда."""
        return True

    def expected(self) -> str:
        """Имя того, кто посчитает заказ, поставленный сейчас."""
        return self.name

    def __init__(self, env=os.environ):
        self.blender = env.get('RENDER_BLENDER') or os.path.expanduser('~/opt/blender-5.3.0-linux-x64/blender')
        self.node = env.get('RENDER_NODE') or shutil.which('node') or '/usr/local/bin/node'
        self.python = env.get('RENDER_PYTHON') or sys.executable
        self.work = env.get('RENDER_WORK') or os.path.expanduser('~/scout-scenes/render-cycles')
        self.public = os.path.join(REPO, 'public')
        os.makedirs(self.work, exist_ok=True)

    def versions(self) -> dict:
        return render_version(self.blender)

    def _job_dir(self, prefix: str, snap: dict) -> str:
        """Каталог задания — СВОЙ на каждый прогон (хеш сцены + случайный хвост): два прогона одной сцены не сносят друг другу файлы;
        оставшиеся от сбоев каталоги старше 6 ч убираются при следующем заказе."""
        os.makedirs(self.work, exist_ok=True)
        now = time.time()
        for d in os.listdir(self.work):
            if d.startswith(('job-', 'gjob-')):
                try:
                    if now - os.path.getmtime(os.path.join(self.work, d)) > 6 * 3600:
                        shutil.rmtree(os.path.join(self.work, d), ignore_errors=True)
                except OSError:
                    pass
        return os.path.join(self.work, f"{prefix}{snap['scene_hash'][:16]}-{uuid.uuid4().hex[:6]}")

    # ——— сборка выгрузчика сцены (esbuild) — кэш по исходникам
    def _bundle(self, log: str) -> str:
        srcs = [os.path.join(PROBE, 'demo_scene_entry.ts'), os.path.join(PROBE, 'build_entry.mjs')]
        for root in (os.path.join(REPO, 'lib', 'viewer3d'), os.path.join(REPO, 'lib', 'configurator'), os.path.join(REPO, 'data', 'flat3d')):
            for dp, _, fs in os.walk(root):
                srcs += [os.path.join(dp, f) for f in fs if f.endswith(('.ts', '.tsx', '.json'))]
        h = hashlib.sha256()
        for p in sorted(srcs):
            try:
                st = os.stat(p)
                h.update(f'{p}:{st.st_size}:{int(st.st_mtime)}'.encode())
            except OSError:
                pass
        out = os.path.join(self.work, 'bundle-' + h.hexdigest()[:12])
        if not os.path.isfile(os.path.join(out, 'entry.js')):
            # СБОРКА ВО ВРЕМЕННУЮ ПАПКУ И ПОДМЕНА ЦЕЛИКОМ (рабочий 1, 17.11: «bundle-…» подменили посреди чужого прогона — дамп упал): прежняя версия
            # писала прямо в итоговый каталог и сносила все «чужие» bundle-* — прогон со старыми исходниками терял каталог из-под рук
            tmp = f'{out}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}'
            try:
                run_step([self.node, os.path.join(PROBE, 'build_entry.mjs'), tmp], log, 300, 4, what='сборка выгрузчика')
                try:
                    os.replace(tmp, out)         # занято (другой прогон успел раньше) — берём его: содержимое одно и то же по хешу исходников
                except OSError:
                    shutil.rmtree(tmp, ignore_errors=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.utime(out)                        # «в ходу» — для уборки по возрасту
        except OSError:
            pass
        now = time.time()
        for old in os.listdir(self.work):        # уборка — только старого и не текущего: свежие каталоги могут быть в работе у соседних прогонов
            op = os.path.join(self.work, old)
            if old.startswith('bundle-') and op != out and '.tmp-' not in old:
                try:
                    if now - os.path.getmtime(op) > 6 * 3600:
                        shutil.rmtree(op, ignore_errors=True)
                except OSError:
                    pass
        return out

    # ——— кэш подготовленной сцены (T-20261117-24/10): каталоги `scene/` и `dump/` по ключу снимка. Экспорт (6–9 с на DEV) для уже виденного варианта — ссылки на файлы
    # вместо пересчёта; кладёт первый, кто собрал сцену (заказ или подогрев витрины `render_gpu/showcase_assets.py`), берёт любой заказ. Файлы кэша только читаются.
    def _prep_root(self) -> str:
        return os.environ.get('RENDER_PREP_CACHE') or os.path.expanduser('~/scout-cache/render-prepared')

    def _code_sha(self) -> str:
        """Хеш кода, из которого собирается сцена (экспорт, расстановка, меши, проёмы): сменился код — старые подготовленные сцены не годятся. Читается заново каждый заказ (8 МБ, ~15 мс)."""
        h = hashlib.sha256()
        for d in (os.path.join(REPO, 'tools', 'scout'), os.path.join(REPO, 'services', 'planner-solver', 'planner'), PROBE):
            try:
                names = sorted(n for n in os.listdir(d) if n.endswith('.py'))
            except OSError:
                names = []
            for n in names:
                try:
                    h.update(n.encode() + b'\0' + open(os.path.join(d, n), 'rb').read() + b'\0')
                except OSError:
                    h.update(n.encode() + b'?')
        return h.hexdigest()[:12]

    def _prep_key(self, snap: dict, bundle: str, pr: dict) -> str:
        v = self.versions()
        part = {k: v.get(k) for k in ('export_scene', 'dump', 'scene_export')}
        try:
            bsha = _sha(os.path.join(bundle, 'entry.js'))          # по СОДЕРЖИМОМУ сборки выгрузчика, не по имени каталога (имя зависит от пути и времени файлов: рабочая копия ≠ основная)
        except OSError:
            bsha = os.path.basename(bundle)
        part.update(code=self._code_sha(), bundle=bsha, dump_export=pr['dumpExport'], prep=PREP_CACHE_VERSION)
        return cache_key(snap['scene_hash'], part)

    @staticmethod
    def _link_tree(src: str, dst: str) -> None:
        """Каталог ссылками на файлы (жёсткие; нельзя — копия). Дерево каталогов — своё."""
        for dp, _, fs in os.walk(src):
            out = os.path.join(dst, os.path.relpath(dp, src))
            os.makedirs(out, exist_ok=True)
            for f in fs:
                try:
                    os.link(os.path.join(dp, f), os.path.join(out, f))
                except OSError:
                    shutil.copyfile(os.path.join(dp, f), os.path.join(out, f))

    def _prep_load(self, hit: str, job: str) -> bool:
        try:
            for d in ('scene', 'dump'):
                self._link_tree(os.path.join(hit, d), os.path.join(job, d))
            os.utime(os.path.join(hit, '.ok'))
            return True
        except OSError:
            for d in ('scene', 'dump'):
                shutil.rmtree(os.path.join(job, d), ignore_errors=True)
            return False

    def _prep_store(self, root: str, key: str, job: str) -> None:
        tmp = os.path.join(root, f'{key}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}')
        try:
            os.makedirs(tmp)
            for d in ('scene', 'dump'):
                self._link_tree(os.path.join(job, d), os.path.join(tmp, d))
            open(os.path.join(tmp, '.ok'), 'w').close()
            try:
                os.replace(tmp, os.path.join(root, key))         # занято (параллельный прогон записал раньше) — оставляем его, свой убираем
            except OSError:
                pass
        except OSError:
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._prep_prune(root)

    def _prep_prune(self, root: str) -> None:
        """Общее правило уборки: свежие по `.ok` остаются, пока сумма размеров (по видимому размеру файлов, ссылки считаются каждая) не выше предела, МБ
        (`RENDER_PREP_CACHE_MB`, по умолчанию `PREP_CACHE_MB`); остальные удаляются."""
        try:
            cap = float(os.environ.get('RENDER_PREP_CACHE_MB') or PREP_CACHE_MB) * 2 ** 20
            ents = []
            for e in os.scandir(root):
                ok = os.path.join(e.path, '.ok')
                if e.is_dir() and '.tmp-' not in e.name and os.path.isfile(ok):
                    ents.append((os.path.getmtime(ok), e.path))
            total = 0
            for i, (_, path) in enumerate(sorted(ents, reverse=True)):
                size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)
                total += size
                if total > cap and i > 0:             # самая свежая запись остаётся всегда
                    shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass

    def prep_has(self, snap: dict) -> bool:
        """Есть ли подготовленная сцена этого снимка в кэше (для подогрева витрины: сборка из кэша ассетов её не кладёт — собрать заново, если нет)."""
        try:
            pr = preset()
            key = self._prep_key(snap, self._bundle(os.path.join(self.work, 'prep-has.log')), pr)
            return os.path.isfile(os.path.join(self._prep_root(), key, '.ok'))
        except OSError:
            return False

    def _prepare(self, snap: dict, job: str, log: str, pr: dict, progress, timing: dict) -> str:
        """Шаги 1–2 с кэшем подготовленной сцены: есть по ключу — ссылки на файлы (`export` ≈ 0 с, `prep_hit` 1), нет — `_prepare_fresh` и в кэш. → каталог dump."""
        t1 = time.time()
        root = key = None
        try:
            root = self._prep_root()
            key = self._prep_key(snap, self._bundle(log), pr)
            hit = os.path.join(root, key)
            if os.path.isfile(os.path.join(hit, '.ok')) and self._prep_load(hit, job):
                progress('scene')
                timing['export'], timing['dump'], timing['prep_hit'] = round(time.time() - t1, 1), 0.0, 1
                return os.path.join(job, 'dump')
        except OSError:
            root = None
        dump = self._prepare_fresh(snap, job, log, pr, progress, timing)
        timing['prep_hit'] = 0
        if root and key:
            self._prep_store(root, key, job)
        return dump

    def _prepare_fresh(self, snap: dict, job: str, log: str, pr: dict, progress, timing: dict) -> str:
        """Шаги 1–2: данные варианта → `export_scene.py` (job/scene) → `demo_scene_dump.mjs` (job/dump). → каталог dump."""
        lim = pr['limits']
        t1 = time.time()
        # 1) данные одного варианта → меши и камеры
        data = {'room': snap['room'], 'rooms_geo': {snap['variant'].get('room_id') or 'living': snap['room']},
                'rules': snap.get('rules') or {}, 'apartment_id': snap['brief'].get('apartment'), 'build': snap['brief'].get('build'),
                'variants': [snap['variant']]}
        data_path = os.path.join(job, 'data.json')
        json.dump(data, open(data_path, 'w', encoding='utf-8'), ensure_ascii=False)
        progress('scene')
        env = {'PYTHONPATH': os.pathsep.join([os.path.join(REPO, 'tools', 'scout'), os.path.join(REPO, 'services', 'planner-solver')])}
        bundle = self._bundle(log)
        dump = os.path.join(job, 'dump')
        dlog = log + '.dump'
        # ЭКСПОРТ МЕШЕЙ и ДАМП СЦЕНЫ независимы (оба читают только data.json) — идут ПАРАЛЛЕЛЬНО (T-24/4: 22 + 9 с → max). Журналы раздельные:
        # «пропущен» читается только из журнала экспорта
        timing_d = {}

        def do_dump():
            t2 = time.time()
            self._dump_cached(data_path, bundle, dump, dlog, pr, lim)
            timing_d['dump'] = round(time.time() - t2, 1)

        def do_export():
            # МЕШ НЕ ПРОПУСКАЕМ МОЛЧА (T-20261117-19/2: в set4 диван выпал из кадра, подушка повисла в воздухе, а рендер «получился»): экспорт при сбое
            # меша печатает «<роль> пропущен» и идёт дальше. Один повтор (GLB уже докачан в кэш) — и если предмет снова пропущен, отказ ДО Blender'а
            miss = []
            for attempt in (1, 2):
                pos = os.path.getsize(log) if os.path.exists(log) else 0
                run_step([self.python, os.path.join(PROBE, 'export_scene.py'), '--out', job, '--scene', 'scene=0', '--data', data_path], log,
                         lim['exportSec'], lim['maxRssGb'], env=env, cwd=os.path.join(REPO, 'tools', 'scout'), what='меши и камеры')
                miss = skipped_meshes(open(log, encoding='utf-8', errors='replace').read()[pos:])
                if not miss:
                    break
                print(f'рендер: меш не взят ({", ".join(miss)}), попытка {attempt}', flush=True)
            if miss:
                raise RenderError('mesh_missing', 'Не удалось загрузить модель мебели для фото. Нажмите «Повторить».',
                                  'A furniture model could not be loaded for the photo. Press "Retry".')

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            fe, fd = ex.submit(do_export), ex.submit(do_dump)
            errs = [f.exception() for f in (fe, fd)]
        for e in errs:
            if e is not None:
                raise e
        timing['export'] = round(time.time() - t1, 1)      # оба шага параллельно: стена времени
        timing['dump'] = timing_d.get('dump', 0.0)
        try:
            with open(log, 'ab') as lf, open(dlog, 'rb') as df:
                lf.write(df.read())
            os.remove(dlog)
        except OSError:
            pass
        return dump

    def _dump_cached(self, data_path: str, bundle: str, dump: str, dlog: str, pr: dict, lim: dict) -> None:
        """Дамп сцены (Chromium, ~9 с) — кэш по хешу входа: данные варианта + сборка выгрузчика + режим. Повтор того же варианта — копия файлов (жёсткие ссылки)."""
        h = hashlib.sha256(open(data_path, 'rb').read() + b'|' + os.path.basename(bundle).encode() + b'|' + str(pr['dumpExport']).encode()).hexdigest()[:24]
        root = os.environ.get('RENDER_DUMP_CACHE') or os.path.expanduser('~/scout-cache/render-dump')
        hit = os.path.join(root, h)
        if os.path.isfile(os.path.join(hit, '.ok')):
            os.makedirs(dump, exist_ok=True)
            for f in os.listdir(hit):
                if f != '.ok':
                    try:
                        os.link(os.path.join(hit, f), os.path.join(dump, f))
                    except OSError:
                        shutil.copyfile(os.path.join(hit, f), os.path.join(dump, f))
            os.utime(os.path.join(hit, '.ok'))
            return
        run_step([self.node, os.path.join(PROBE, 'demo_scene_dump.mjs'), data_path, '0', bundle, dump, 'export=' + pr['dumpExport']], dlog,
                 lim['dumpSec'], lim['maxRssGb'], what='декор и отделка')
        try:
            os.makedirs(root, exist_ok=True)
            tmp = f'{hit}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}'
            os.makedirs(tmp)
            for f in os.listdir(dump):
                shutil.copyfile(os.path.join(dump, f), os.path.join(tmp, f))
                os.chmod(os.path.join(tmp, f), 0o444)      # после записи — только чтение (прогоны держат жёсткие ссылки на эти файлы)
            open(os.path.join(tmp, '.ok'), 'w').close()
            try:
                os.replace(tmp, hit)             # занято (параллельный прогон записал раньше) — оставляем его, свой убираем
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
            # держим 60 последних (по `.ok`), остальное — прочь
            ents = sorted((e for e in os.scandir(root) if e.is_dir() and '.tmp-' not in e.name),
                          key=lambda e: os.path.getmtime(os.path.join(e.path, '.ok')) if os.path.isfile(os.path.join(e.path, '.ok')) else 0, reverse=True)
            for e in ents[60:]:
                shutil.rmtree(e.path, ignore_errors=True)
        except OSError:
            pass

    def _finish(self, snap: dict, outs: dict, out_dir: str, pr: dict, timing: dict, t0: float, job: str) -> dict:
        """Шаг 4: JPEG и мета — каталогом по ключу (подменой, meta последней); стадия `save` объявлена вызывающим."""
        from PIL import Image  # noqa: F811
        tmp = out_dir + '.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        size, sha = None, {}
        for cam, png in outs.items():
            im = Image.open(png)
            jp = os.path.join(tmp, f'{cam}.jpg')
            if im.format == 'JPEG':
                size = [im.width, im.height]
                shutil.copyfile(png, jp)               # T-24/11: JPEG с машины (кодировал Blender) кладём как есть — перекодирование не нужно
            else:
                im = im.convert('RGB')
                size = [im.width, im.height]
                im.save(jp, 'JPEG', quality=pr['jpegQuality'], optimize=True)
            sha[cam] = hashlib.sha256(open(jp, 'rb').read()).hexdigest()     # имя кадра для «Улучшить» (как у кадров браузера: sha256 JPEG)
            mk = os.path.splitext(png)[0] + '.mask.png'
            if os.path.isfile(mk):
                pack_mask(mk, os.path.join(tmp, f'{cam}.mask.png'))              # маска поверхностей рядом с кадром (приглушение солнечных пятен «Улучшить»), палитрой
        timing['total'] = round(time.time() - t0, 1)
        meta = {'scene_hash': snap['scene_hash'], 'snapshot_version': snap['v'], 'size': size, 'sha': sha, 'versions': self.versions(), 'timing': timing,
                'executor': self.name, 'ts': int(time.time()), 'source': snap.get('source')}
        json.dump(meta, open(os.path.join(tmp, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        shutil.rmtree(out_dir, ignore_errors=True)
        os.replace(tmp, out_dir)
        shutil.rmtree(job, ignore_errors=True)
        return {'timing': timing, 'executor': self.name}


def masks_wanted() -> bool:
    """Маски поверхностей (пол/стена) после кадров — для приглушения «солнечных пятен» в «Улучшить» (T-20261118-05). Только по `RENDER_MASKS=1` (не пресет:
    пресет входит в ключ кэша кадров, а маска кадр не меняет). Пока считает только `LocalCpuExecutor`; машина Salad — отдельной задачей."""
    return os.environ.get('RENDER_MASKS') == '1'


def pack_mask(src: str, dst: str) -> None:
    """Маска поверхностей → PNG с палитрой из четырёх цветов (чёрный — прочее, красный — пол, зелёный — стена, синий — акцентная стена): каждый пиксель — к ближайшему
    (края сглаживания Blender не дают «полупол»); 1/4 кадра ≈ 2 КБ вместо 24 КБ RGB (655 КБ у полного размера). Не читается — оставляем как есть."""
    from PIL import Image
    import numpy as np
    try:
        a = np.asarray(Image.open(src).convert('RGB'))
        cls = np.where(a.max(axis=2) < 128, 0, 1 + a.argmax(axis=2)).astype('uint8')       # 0 прочее, 1 R пол, 2 G стена, 3 B акцент
        im = Image.fromarray(cls, 'P')
        im.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (768 - 12))
        im.save(dst, 'PNG', optimize=True)
    except Exception:  # noqa: BLE001
        shutil.copyfile(src, dst)


class LocalCpuExecutor(SceneExecutor):
    """Blender Cycles на процессоре DEV под общей очередью тяжёлых прогонов (`heavy_slot`): задание держит слот на ВЕСЬ путь
    (сцена + оба кадра) — между шагами память и ядра не отдаём, чтобы пара не растянулась из-за чужих прогонов."""
    name = 'local-cpu'

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        import render_snapshot as RS  # noqa: F401
        pr = preset()
        lim = pr['limits']
        if not os.path.isfile(self.blender):
            raise ExecutorUnavailable('render_unavailable', 'Рендер сейчас недоступен. Попробуйте позже.', 'Rendering is unavailable right now. Try again later.')
        sys.path.insert(0, os.path.join(REPO, 'tools', 'ops'))
        import heavy_slot as HS
        job = self._job_dir('job-', snap)
        os.makedirs(job)
        log = os.path.join(job, 'run.log')
        t0, timing = time.time(), {}
        with HS.heavy_slot('photo-render-' + snap['scene_hash'][:8], min_gb=pr['min_gb'], cores=pr['cores'], prio=1) as hs:
            timing['slot_wait'] = round(float(hs.get('waited_s', 0)), 1) if isinstance(hs, dict) else 0
            dump = self._prepare(snap, job, log, pr, progress, timing)
            # 3) Blender по кадру на ракурс
            outs = {}
            for cam in CAMS:
                progress(cam)
                t1 = time.time()
                png = os.path.join(job, f'{cam}.png')
                cmd = [self.blender, '-b', '-P', os.path.join(PROBE, 'render_cycles.py'), '--', '--scene-dir', os.path.join(job, 'scene'),
                       '--cam', cam, '--out', png, '--samples', str(pr['samples']), '--pct', str(pr['pct']), '--threads', str(pr['threads']),
                       '--demo-glb', os.path.join(dump, 'demo_nodes.glb'), '--demo-nodes', os.path.join(dump, 'demo_nodes_uuids.json'),
                       '--export', os.path.join(dump, 'scene-export.json'), '--public', self.public, *pr['flags']]
                if masks_wanted():
                    import jobs_proto as _JP
                    cmd += ['--mask-out', os.path.join(job, f'{cam}.mask.png'), '--mask-scale', str(_JP.MASK_SCALE)]     # маска пола/стен 1/4 размера после кадра — для «Улучшить»
                run_step(cmd, log, lim['blenderSecPerFrame'], lim['maxRssGb'], what=f'кадр {cam}')
                if not os.path.isfile(png):
                    raise RenderError('render_failed', 'Рендер не дал кадра. Нажмите «Повторить».', 'The render produced no frame. Press "Retry".')
                timing[cam] = round(time.time() - t1, 1)
                outs[cam] = png
            if _dir_mb(job) > lim['maxJobDiskMb']:
                raise RenderError('render_failed', 'Рендер не удался. Нажмите «Повторить».', 'The render failed. Press "Retry".')
        progress('save')
        return self._finish(snap, outs, out_dir, pr, timing, t0, job)


class LocalMachine:
    """Связь исполнителя с контроллером машины рендера (`render_gpu/render_machine.py`): состояние — чтение файла `state.json` (без Salad и без
    блокировки: запись подменой), событие заказа — `pulse`. Подменяется в тестах."""

    def __init__(self):
        import render_machine as RM
        self.RM = RM

    def rules(self) -> dict:
        return self.RM.load_rules()

    def state(self) -> dict:
        try:
            return json.load(open(os.path.join(self.RM.STATE_DIR, 'state.json'), encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def pulse(self, busy_s: float = 0.0) -> None:
        self.RM.pulse(busy_s)


# причина «машина не годна» → (код, RU, EN): текст — владельцу на странице («честное ожидание на запасной», без «ошибки»)
GATE_TEXT = {
    'off': ('gpu_off', 'Машина рендера выключена. Считаем на запасной — будет дольше.', 'The render machine is off. Using the backup — it will take longer.'),
    'warming': ('gpu_warming', 'Машина рендера ещё прогревается. Считаем на запасной — будет дольше.',
                'The render machine is still warming up. Using the backup — it will take longer.'),
    'degraded': ('gpu_degraded', 'Машина рендера не отвечает. Считаем на запасной — будет дольше.', 'The render machine is not responding. Using the backup — it will take longer.'),
    'controller_silent': ('gpu_degraded', 'Машина рендера не отвечает. Считаем на запасной — будет дольше.',
                          'The render machine is not responding. Using the backup — it will take longer.'),
}
GPU_FAILED = ('Машина рендера не справилась. Считаем на запасной — будет дольше.', 'The render machine failed. Using the backup — it will take longer.')


class _Fmt2Skip(Exception):
    """fmt 2 сейчас недоступен (приёмник без ассетов, сбой выгрузки): заказ уходит по fmt 1 — до задания машине дело не дошло."""


_SHA_MEMO: dict = {}          # (путь, размер, mtime_ns, inode) → sha256: файлы кэша PNG/дампа неизменны (read-only, жёсткие ссылки), повторный заказ хеша не считает


def file_sha256(path: str) -> tuple:
    """(sha256, размер) файла; хеш помнится по (путь, размер, mtime, inode)."""
    import jobs_proto as JP
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime_ns, st.st_ino)
    h = _SHA_MEMO.get(key)
    if h is None:
        if len(_SHA_MEMO) > 4000:
            _SHA_MEMO.clear()
        h = _SHA_MEMO[key] = JP.sha256_file(path)
    return h, st.st_size


PREP_CACHE_MB = 3000            # предел кэша подготовленных сцен (видимый размер, ссылки считаются каждая; на диске ≈ в 6 раз меньше: текстуры — ссылки на общие файлы)
PREP_CACHE_VERSION = 1          # формат записи кэша подготовленных сцен: сменился состав каталога — вверх
ASSET_RULES = 2                # версия правила «что ассет» (`asset_kind`/`asset_min_bytes`): растёт при его смене — кэш сборки витрины (`showcase_assets.py`) её учитывает
NPZ_ASSET_MIN = 64 * 1024      # мелкие npz (стены, проёмы — десятки байт…КБ) остаются в пакете: на ассет они дороже, чем в архиве


def asset_min_bytes(rel: str) -> int:
    """Меньше этого размера файл вида `asset_kind` в ассеты не идёт (едет в маленьком пакете)."""
    return NPZ_ASSET_MIN if rel.endswith('.npz') else 1


def asset_kind(rel: str) -> str | None:
    """Что из файлов задания — НЕИЗМЕНЯЕМЫЙ ассет (по хешу на приёмнике и машине), а что едет в маленьком пакете. Правило общее, без особых случаев:
    текстуры сцены (PNG), GLB декора, карты отделки (public/), программа рендера и её данные. Меши предметов сцены (`scene/m*.npz` от 64 КБ, T-24/8) — тоже ассеты. Карта сцены, мелкие npz, отделка и uuid — в пакете."""
    if rel.startswith('scene/tex/'):
        return 'tex'
    if rel.startswith('scene/') and rel.endswith('.npz'):
        return 'glb'                 # меш предмета сцены (T-24/8): тот же вид, что GLB декора — «меш»; отдельного вида нет, чтобы не пересобирать образ воркера
    if rel == 'dump/demo_nodes.glb':
        return 'glb'
    if rel.startswith('public/'):
        return 'map'
    if rel.startswith('tools/scout/') and rel.endswith('.py'):
        return 'code'
    if rel.startswith('data/flat3d/') and rel.endswith('.json'):
        return 'data'
    return None


class SaladGpuExecutor(SceneExecutor):
    """Машина рендера на Salad (T-20261117-24/2): сцена собирается на DEV тем же правилом, что у `local-cpu` (`SceneExecutor._prepare`), уходит пакетом
    в хранилище приёмника (`renderjobs/<задание>/`), воркер на машине (`render_gpu/render_worker.py`) считает ПАРУ ракурсов одним Blender
    (`--cam C1,C2 --persistent 1`) и кладёт кадры обратно; исполнитель их забирает и сохраняет как `local-cpu` (JPEG + meta). Ход % — те же стадии
    (`scene`, `C1`, `C2`, `save`): стадии C1/C2 — по `progress.json` воркера.
    Машина не включена/не прогрелась/не отвечает/не взяла задание/сбой — `ExecutorUnavailable` (решение — ДАННЫМИ из `state.json` контроллера и
    ответов воркера), запасной путь решает `Fallback`. Автостоп машины от последнего события: заказ и конец пары зовут `pulse`; пока пара в работе,
    ждущий исполнитель продлевает «занято» (`pulse --busy`)."""
    name = 'salad-gpu'

    def __init__(self, env=os.environ, sink=None, machine=None, clock=time.time, sleep=time.sleep):
        super().__init__(env)
        self.env, self._sink, self._machine, self.now, self.sleep = env, sink, machine, clock, sleep
        self._fmt2_dead_until = 0.0      # приёмник без ассетов (404 на /have): до этого момента fmt 2 не пробуем

    # ——— зависимости (лениво: DEV без машины рендера не должен падать при создании исполнителя)
    def machine(self):
        if self._machine is None:
            self._machine = LocalMachine()
        return self._machine

    def sink(self):
        if self._sink is None:
            sys.path.append(os.path.join(HERE, 'salad'))
            import jobs_proto as JP
            tok = self.env.get('RENDER_SINK_TOKEN') or self.env.get('MESH_SINK_TOKEN') or ''
            base = self.env.get('RENDER_SINK_URL') or self.env.get('MESH_SINK_URL') or 'https://remont-lab.online/mesh-sink'
            if not tok:
                try:
                    import migrate_groups
                    import sink_health
                    migrate_groups.env_from_file()      # ключ Salad и SALAD_GROUP — из salad.env (вне git), как у сторожей; токен приёмника — из группы-донора
                    tok = sink_health.sink_token()
                except Exception:  # noqa: BLE001 — нет токена = нет хранилища = запасной путь
                    tok = ''
            if not tok:
                raise ExecutorUnavailable('gpu_no_sink', *GATE_TEXT['degraded'][1:])
            self._sink = JP.Sink(base, tok)
        return self._sink

    def gate(self) -> dict:
        """Годна ли машина СЕЙЧАС (данные контроллера) → правила; иначе `ExecutorUnavailable` с парой RU/EN."""
        import jobs_proto as JP
        m = self.machine()
        rules = m.rules()
        ok, why = JP.machine_verdict(m.state(), self.now(), rules)
        if not ok:
            raise ExecutorUnavailable(*GATE_TEXT.get(why, GATE_TEXT['degraded']))
        return rules

    def available(self) -> bool:
        """Машина годна сейчас по данным контроллера (то же решение, что `gate`, без исключения). Сбой чтения — «нет»: срок честнее длинный."""
        try:
            self.gate()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _slot(self, label: str, pr: dict, prio: int = 1):
        """Общая очередь тяжёлых прогонов — только на сборку сцены на DEV (ожидание машины рендера процессор DEV не занимает). `prio` 1 — заказ человека;
        фоновые шаги (подогрев витрины, `render_gpu/showcase_assets.py`) берут 0 и уступают заказам."""
        sys.path.insert(0, os.path.join(REPO, 'tools', 'ops'))
        import heavy_slot as HS
        return HS.heavy_slot(label, min_gb=pr['min_gb'], cores=2, prio=prio)

    def _gpu_unavailable(self, code: str) -> ExecutorUnavailable:
        return ExecutorUnavailable(code, *GPU_FAILED)

    def _bundle_files(self, job: str) -> dict:
        """Состав пакета: сцена, декор/отделка, программа рендера и её данные, карты материалов, на которые ссылается отделка."""
        dump = os.path.join(job, 'dump')
        files = {'scene': os.path.join(job, 'scene'),
                 'tools/scout/cycles_probe/render_cycles.py': os.path.join(PROBE, 'render_cycles.py'),
                 'tools/scout/wall_art.py': os.path.join(REPO, 'tools', 'scout', 'wall_art.py'),      # render_cycles.py с 17.11 берёт правило картин оттуда (только stdlib)
                 'data/flat3d/wall-art.json': os.path.join(REPO, 'data', 'flat3d', 'wall-art.json'),
                 # сторож кадров (render-qa-gate-01, 18.11): render_cycles.py импортирует frame_qa всегда; правила и классы штор — данными
                 'tools/scout/cycles_probe/frame_qa.py': os.path.join(PROBE, 'frame_qa.py'),
                 'data/flat3d/frame-qa-rules.json': os.path.join(REPO, 'data', 'flat3d', 'frame-qa-rules.json'),
                 'data/flat3d/textile.json': os.path.join(REPO, 'data', 'flat3d', 'textile.json')}
        for n in ('demo_nodes.glb', 'demo_nodes_uuids.json', 'scene-export.json', 'scene_info.json', 'dump_keys.json'):   # последние два — для сторожа кадров: снимок оплачиваемых позиций и ключи выгрузки (без них предпроверка на машине слепа)
            files['dump/' + n] = os.path.join(dump, n)
        try:
            exp = json.load(open(os.path.join(dump, 'scene-export.json'), encoding='utf-8'))
        except (OSError, ValueError):
            exp = {}
        seen, stack = set(), [exp]
        while stack:                                     # карты — любые строки-пути в отделке, которые есть в public/
            v = stack.pop()
            if isinstance(v, dict):
                stack.extend(v.values())
            elif isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, str) and v.startswith('/') and len(v) < 200 and v not in seen:
                seen.add(v)
                p = os.path.normpath(os.path.join(self.public, v.lstrip('/')))
                if p.startswith(self.public + os.sep) and os.path.isfile(p):
                    files['public/' + v.lstrip('/')] = p
        return files

    def _split_assets(self, files: dict) -> tuple:
        """`_bundle_files` → (маленький пакет {путь в архиве: файл}, ассеты [ссылки {path, sha256, size, kind}], {sha256: файл на DEV}).
        Ассетом файл становится, только если путь годится как плоское имя (`valid_rel_path`), размер в пределах и число ассетов не больше потолка; иначе едет в пакете."""
        import jobs_proto as JP
        small, assets, src = {}, [], {}
        items = []
        for arc, p in files.items():
            if os.path.isdir(p):
                for dp, dn, fs in os.walk(p):
                    dn.sort()
                    items += [(os.path.join(arc, os.path.relpath(os.path.join(dp, f), p)).replace(os.sep, '/'), os.path.join(dp, f)) for f in sorted(fs)
                              if not os.path.islink(os.path.join(dp, f))]
            elif os.path.isfile(p):
                items.append((arc, p))
        for rel, p in sorted(items):
            kind = asset_kind(rel)
            if kind and len(assets) < JP.ASSET_MAX_N and JP.valid_rel_path(rel):
                sha, size = file_sha256(p)
                if asset_min_bytes(rel) <= size <= JP.ASSET_MAX_MB * 2 ** 20:
                    assets.append(JP.asset_ref(rel, sha, size, kind))
                    src.setdefault(sha, p)
                    continue
            small[rel] = p
        return small, assets, src

    def _send_fmt1(self, sink, job: str, jid: str, pr: dict, ex: dict, timing: dict, masks: bool = False) -> None:
        """fmt 1: всё одним пакетом (как в T-24/2). Не принял приёмник — `gpu_upload`; пакет больше потолка — `gpu_bundle_big`."""
        import jobs_proto as JP
        t1 = self.now()
        tgz = os.path.join(job, 'bundle.tgz')
        sha = JP.pack_bundle(self._bundle_files(job), tgz)
        bundle = f'bundle-{sha}.tgz'
        timing['pack'] = round(self.now() - t1, 1)
        cap_mb = float(ex.get('bundle_max_mb', 95))      # приёмник и Caddy не примут больше (Caddy режет тело на 100 МБ): откат на CPU сразу и с понятной причиной
        if os.path.getsize(tgz) > cap_mb * 2 ** 20:
            print(f'рендер: пакет сцены {os.path.getsize(tgz) / 2 ** 20:.0f} МБ > {cap_mb:g} МБ — на машину не отдаём', flush=True)
            raise self._gpu_unavailable('gpu_bundle_big') from None
        t1 = self.now()
        try:
            sink.put_file(f'{JP.PREFIX}/{jid}/{bundle}', tgz)
            jobj = JP.new_job(jid, bundle, sha, ['--samples', pr['samples'], '--pct', pr['pct'], '--threads', pr['threads'], *pr['flags']],
                              {'blenderSec': pr['limits']['blenderSecPerFrame']}, now=self.now(), masks=masks)
            sink.put(f'{JP.PREFIX}/{jid}/job.json', json.dumps(jobj, ensure_ascii=False).encode())       # ПОСЛЕДНИМ
        except JP.SinkError as e:
            print(f'рендер: хранилище не приняло пакет: {e}', flush=True)
            raise self._gpu_unavailable('gpu_upload') from None
        timing['upload'] = round(self.now() - t1, 1)

    def _send_fmt2(self, sink, job: str, jid: str, pr: dict, ex: dict, timing: dict, frames: str = 'png', masks: bool = False) -> None:
        """fmt 2 (T-20261117-24/5): ассеты — по хешу в `renderassets` приёмника (спросили «каких нет» и досылаем недостающее ДО `job.json`), маленький пакет —
        в каталог задания, `job.json` (v=2, манифест) ПОСЛЕДНИМ. Любой сбой до задания — `_Fmt2Skip` (заказ пойдёт по fmt 1), машине ничего не ушло."""
        import jobs_proto as JP
        t1 = self.now()
        small, assets, src = self._split_assets(self._bundle_files(job))
        timing['hash'] = round(self.now() - t1, 1)
        t1 = self.now()
        uniq = [{'sha256': h, 'size': next(a['size'] for a in assets if a['sha256'] == h)} for h in src]
        try:
            missing = list(sink.have_assets(uniq))
        except JP.SinkError as e:
            if e.code in (404, 405):                      # приёмник без ассетов (старый): не спрашиваем снова 5 минут
                self._fmt2_dead_until = self.now() + 300
            raise _Fmt2Skip(f'have: {e}') from None
        timing['have'] = round(self.now() - t1, 1)
        timing['asset_n'], timing['asset_miss'] = len(uniq), len(missing)
        timing['asset_up_mb'] = round(sum(u['size'] for u in uniq if u['sha256'] in set(missing)) / 2 ** 20, 1)
        t1 = self.now()
        par = max(1, int(ex.get('upload_par', 4)))
        try:
            with ThreadPoolExecutor(max_workers=par) as pool:
                futs = [pool.submit(sink.put_asset, h, src[h]) for h in missing]
                tp = self.now()
                tgz = os.path.join(job, 'bundle2.tgz')
                JP.pack_bundle(small, tgz)                                  # пока ассеты уходят, пакет собирается
                bsha = JP.sha256_file(tgz)
                bsize = os.path.getsize(tgz)
                timing['pack'] = round(self.now() - tp, 1)
                if bsize > float(ex.get('bundle_max_mb', 95)) * 2 ** 20:
                    raise _Fmt2Skip(f'маленький пакет {bsize / 2 ** 20:.0f} МБ — слишком велик')
                bundle = {'name': f'bundle-{bsha[:16]}.tgz', 'sha256': bsha, 'size': bsize}
                sink.put_file(f'{JP.PREFIX}/{jid}/{bundle["name"]}', tgz)
                for f in futs:
                    f.result()                                              # недостающие ассеты — ДО задания
            render = hashlib.sha256(json.dumps(self.versions(), sort_keys=True).encode()).hexdigest()[:16]
            jobj = JP.new_job2(jid, bundle, assets, ['--samples', pr['samples'], '--pct', pr['pct'], '--threads', pr['threads'], *pr['flags']],
                               {'blenderSec': pr['limits']['blenderSecPerFrame']}, render, now=self.now(), frames=frames, jpeg_q=int(pr['jpegQuality']), masks=masks)
            sink.put(f'{JP.PREFIX}/{jid}/job.json', json.dumps(jobj, ensure_ascii=False).encode())       # ПОСЛЕДНИМ
        except JP.SinkError as e:
            raise _Fmt2Skip(f'выгрузка: {e}') from None
        timing['upload'] = round(self.now() - t1, 1)
        timing['bundle_kb'] = round(bsize / 1024)

    @staticmethod
    def _frames_for(m, ex: dict) -> str:
        """Формат кадров заказа (T-24/11): `jpg`, если машина это заявила (`state.frames` из ready.json → `caps.frames`) и правило `executor.frames` не `png`;
        старый образ без поля — `png`, как раньше."""
        if str(ex.get('frames', 'auto')) == 'png':
            return 'png'
        fr = m.state().get('frames')
        return 'jpg' if isinstance(fr, list) and 'jpg' in fr else 'png'

    @staticmethod
    def _masks_for(m) -> bool:
        """Маски поверхностей в заказе (T-20261118-05/3): `RENDER_MASKS=1` И машина заявила `caps.masks` (ready.json → `state.masks`); старый образ — без масок."""
        return masks_wanted() and bool(m.state().get('masks'))

    @staticmethod
    def _check_frame(path: str, fmt: str) -> None:
        """Скачанный кадр — действительно тот формат, что в имени (иначе ValueError → gpu_download): PIL открывает, формат совпадает, размер ненулевой."""
        from PIL import Image
        with Image.open(path) as im:
            if im.format != {'jpg': 'JPEG', 'png': 'PNG'}[fmt] or im.width < 16 or im.height < 16:
                raise ValueError(f'кадр {os.path.basename(path)}: формат {im.format} {im.width}×{im.height}')

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        import jobs_proto as JP
        pr = preset()
        rules = self.gate()
        ex = rules.get('executor') or {}
        busy_s, poll_s = float(ex.get('busy_s', 90)), float(ex.get('poll_s', 3))
        pickup_s, pair_max_s = float(ex.get('pickup_s', 90)), float(ex.get('pair_max_s', 900))
        sink = self.sink()
        m = self.machine()
        job = self._job_dir('gjob-', snap)
        shutil.rmtree(job, ignore_errors=True)
        os.makedirs(job)
        log = os.path.join(job, 'run.log')
        t0, timing = self.now(), {}
        jids: list = []
        m.pulse(busy_s=600)            # ЗАКАЗ = событие: отсчёт простоя с этого момента, и пока задание в работе — машину не гасим
        try:
            with self._slot('photo-render-' + snap['scene_hash'][:8], pr) as hs:
                timing['slot_wait'] = round(float(hs.get('waited_s', 0)), 1) if isinstance(hs, dict) else 0
                self._prepare(snap, job, log, pr, progress, timing)
            use2 = bool(ex.get('fmt2')) and self.now() >= self._fmt2_dead_until
            res = None
            for fmt in ((2, 1) if use2 else (1,)):
                jid = f"{snap['scene_hash'][:12]}-{int(self.now())}-{uuid.uuid4().hex[:4]}"      # хвост: два заказа одной сцены в одну секунду не делят каталог заданий
                jids.append(jid)
                if fmt == 2:
                    try:
                        self._send_fmt2(sink, job, jid, pr, ex, timing, frames=self._frames_for(m, ex), masks=self._masks_for(m))
                    except _Fmt2Skip as e:
                        print(f'рендер: fmt 2 не вышел ({e}) — шлю по fmt 1', flush=True)
                        continue
                else:
                    self._send_fmt1(sink, job, jid, pr, ex, timing, masks=self._masks_for(m))
                try:
                    res = self._wait(sink, m, jid, progress, busy_s, poll_s, pickup_s, pair_max_s)
                except ExecutorUnavailable as e:
                    if fmt == 2 and e.code in ('gpu_asset', 'gpu_bad_job'):      # машина не приняла ассеты/версию — тот же заказ по fmt 1, не сразу на процессор
                        print(f'рендер: машина не приняла fmt 2 ({e.code}) — шлю по fmt 1', flush=True)
                        continue
                    raise
                timing['fmt'] = fmt
                break
            if res is None:
                raise self._gpu_unavailable('gpu_upload')
            t1 = self.now()
            outs = {}
            try:
                rf = res.get('frames') if res.get('frames') in ('jpg', 'png') else 'png'      # что фактически положила машина (имя = формат)
                timing['frames'] = rf
                for cam in CAMS:
                    fp = os.path.join(job, f'{cam}.{rf}')
                    sink.get_to(f'{JP.PREFIX}/{jid}/{cam}.{rf}', fp)
                    self._check_frame(fp, rf)
                    outs[cam] = fp
            except (JP.SinkError, ValueError, OSError) as e:
                print(f'рендер: кадры не скачались: {e}', flush=True)
                raise self._gpu_unavailable('gpu_download') from None
            for cam in (res.get('masks') or {}):
                # маски необязательны: не скачалась или не картинка — кадр идёт без неё (приглушение пятен просто не сработает)
                try:
                    mp = os.path.join(job, JP.mask_name(cam))
                    sink.get_to(f'{JP.PREFIX}/{jid}/{JP.mask_name(cam)}', mp)
                    from PIL import Image
                    with Image.open(mp) as im_:
                        if im_.format != 'PNG' or im_.width < 8:
                            raise ValueError('маска не PNG')
                except Exception as e:  # noqa: BLE001
                    print(f'рендер: маска {cam} не принята: {repr(e)[:100]}', flush=True)
                    try:
                        os.remove(os.path.join(job, JP.mask_name(cam)))
                    except OSError:
                        pass
            timing['download'] = round(self.now() - t1, 1)
            for k, v in (res.get('timing') or {}).items():          # C1, C2, fetch, render — как у local-cpu (кадры), плюс загрузка сцены машиной
                if isinstance(v, (int, float)):
                    timing[k] = v
            if isinstance(res.get('assets'), dict):                  # fmt 2: сколько ассетов машине пришлось докачать (0 — кэш/подогрев сработал) — для замера «подогрева»
                timing['asset_dl_n'], timing['asset_dl_mb'] = res['assets'].get('downloaded'), res['assets'].get('dl_mb')
            print(f"рендер: пара на машине, устройство {res.get('device')}, {timing.get('render')} с Blender", flush=True)
            return self._finish(snap, outs, out_dir, pr, timing, t0, job)
        finally:
            shutil.rmtree(job, ignore_errors=True)
            for j in jids:
                try:
                    sink.delete(f'{JP.PREFIX}/{j}')      # своё задание убираем сразу (место общее с мешами); не вышло — уберёт jobs_purge по сроку
                except Exception:  # noqa: BLE001
                    pass
            m.pulse(0)                 # конец пары (или отказ) — тоже событие; «занято» снято, до автостопа 20 мин от этого момента

    def _wait(self, sink, m, jid: str, progress, busy_s: float, poll_s: float, pickup_s: float, pair_max_s: float) -> dict:
        """Ждать result.json: ход — по progress.json воркера; не взяли за pickup_s / не уложились в pair_max_s / машину выключили — снять задание
        (`cancel.json`) и `ExecutorUnavailable`. Пока ждём — продлеваем «занято» (автостоп не сработает)."""
        import jobs_proto as JP
        t0 = last_beat = self.now()
        stage = None
        while True:
            now = self.now()
            if now - last_beat >= 15:
                m.pulse(busy_s=busy_s)
                last_beat = now
            try:
                res = sink.get_json(f'{JP.PREFIX}/{jid}/result.json')
            except JP.SinkError as e:
                res = None
                if e.code not in (0, 404, 500, 502, 503, 504):
                    raise self._gpu_unavailable('gpu_result') from None
            if res is not None:
                if not res.get('ok'):
                    code = (res.get('error') or {}).get('code') or 'failed'
                    print(f"рендер: машина не справилась ({code}): {res.get('note') or res.get('tail') or ''}", flush=True)
                    raise self._gpu_unavailable(code if code.startswith('gpu_') else 'gpu_' + code)
                if stage != 'save':
                    progress('save')
                return res
            try:
                pg = sink.get_json(f'{JP.PREFIX}/{jid}/progress.json')
            except JP.SinkError:
                pg = None
            if pg and pg.get('stage') in ('C1', 'C2', 'save') and pg['stage'] != stage:
                stage = pg['stage']
                progress(stage)
            elapsed = now - t0
            why = ''
            if pg is None and elapsed > pickup_s:
                why = 'gpu_no_pickup'
            elif elapsed > pair_max_s:
                why = 'gpu_timeout'
            else:
                try:
                    ok, reason = JP.machine_verdict(m.state(), now, m.rules())
                except Exception:  # noqa: BLE001
                    ok, reason = True, 'ready'
                if not ok and reason == 'off':
                    why = 'gpu_off'
            if why:
                print(f'рендер: {why} через {elapsed:.0f} с — снимаю задание, запасной путь', flush=True)
                try:
                    sink.put(f'{JP.PREFIX}/{jid}/cancel.json', json.dumps({'why': why, 'ts': now}).encode())
                except JP.SinkError:
                    pass
                raise self._gpu_unavailable(why)
            self.sleep(poll_s)


class Fallback:
    """Основной исполнитель, а если он `ExecutorUnavailable` — запасной. Ключ кэша зависит от версий ОСНОВНОГО (картинка должна быть той же)."""

    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.name = f'{primary.name}>{backup.name}'

    def versions(self) -> dict:
        return self.primary.versions() if hasattr(self.primary, 'versions') else {}

    def expected(self) -> str:
        """Кто возьмёт заказ СЕЙЧАС: основной, если он годен, иначе запасной."""
        try:
            ok = self.primary.available()
        except Exception:  # noqa: BLE001
            ok = False
        return self.primary.name if ok else self.backup.name

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        try:
            return self.primary.render(snap, out_dir, progress)
        except ExecutorUnavailable as e:
            print(f'рендер: {self.primary.name} недоступен ({e.code}) — запасной {self.backup.name}', flush=True)
            return self.backup.render(snap, out_dir, progress)


def make_executor(env=os.environ):
    """По настройке `RENDER_EXECUTOR`: `local-cpu` (по умолчанию), `salad-gpu`, либо цепочка через запятую — первый основной, второй запасной."""
    names = [n.strip() for n in (env.get('RENDER_EXECUTOR') or 'local-cpu').split(',') if n.strip()]
    table = {'local-cpu': LocalCpuExecutor, 'salad-gpu': SaladGpuExecutor}
    ex = []
    for n in names:
        if n not in table:
            raise ValueError(f'неизвестный исполнитель рендера: {n}')
        ex.append(table[n](env))
    return ex[0] if len(ex) == 1 else Fallback(ex[0], ex[1])


def _selftest() -> int:
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + name)
        bad += 0 if c else 1
    v = render_version('/x/blender-5.3/blender')
    ok(all(v[k] for k in ('preset', 'render_cycles', 'export_scene', 'dump', 'scene_export', 'blender')), 'версии рендера собраны (пресет, программа, выгрузчики, формат, Blender)')
    k1 = cache_key('h', v)
    ok(k1 == cache_key('h', dict(v)) and k1 != cache_key('h2', v) and k1 != cache_key('h', {**v, 'preset': 'other'}), 'ключ кэша: хеш снимка и каждая версия')
    log = '  scene3d: диван пропущен (string is not a file: x)\n  scene3d: вид за проёмом пропущен (e)\n  scene3d: стул 2 пропущен (boom)\n  объектов 51\n'
    ok(skipped_meshes(log) == ['диван', 'стул 2'], 'пропущенный меш предмета найден в логе экспорта, «вид за проёмом» — не предмет')
    ok(skipped_meshes('  объектов 51, ковров 1\n') == [], 'чистый лог — пропусков нет')
    pr = preset()
    ok(pr['samples'] > 0 and pr['flags'] and '--cam-h' not in pr['flags'], 'пресет: поза — умолчание Б (без своих --cam-h/--level)')
    ex = make_executor({'RENDER_EXECUTOR': 'salad-gpu,local-cpu'})
    ok(isinstance(ex, Fallback) and ex.primary.name == 'salad-gpu', 'цепочка исполнителей: основной и запасной')
    try:
        make_executor({'RENDER_EXECUTOR': 'nope'})
        ok(False, 'неизвестный исполнитель — ошибка настройки')
    except ValueError:
        ok(True, 'неизвестный исполнитель — ошибка настройки')

    class Boom:
        name = 'a'

        def render(self, *a):
            raise ExecutorUnavailable('gpu_unavailable', 'ру', 'en')

    class Good:
        name = 'b'

        def render(self, *a):
            return {'timing': {'x': 1}}
    ok(Fallback(Boom(), Good()).render({}, '', None) == {'timing': {'x': 1}}, 'недоступный основной — запасной без вмешательства очереди')
    try:
        Fallback(Boom(), Boom()).render({}, '', None)
        ok(False, 'оба недоступны — отказ')
    except ExecutorUnavailable:
        ok(True, 'оба недоступны — отказ с кодом')
    # run_step: таймаут и память убивают дерево, плохой код — ошибка
    import tempfile
    d = tempfile.mkdtemp()
    lg = os.path.join(d, 'l.log')
    try:
        run_step([sys.executable, '-c', 'import time; time.sleep(30)'], lg, 1.5, 5, what='сон')
        ok(False, 'таймаут шага — RenderError')
    except RenderError as e:
        ok(e.code == 'render_timeout' and e.ru and e.en, 'таймаут шага: дерево остановлено, RenderError с парой RU/EN')
    try:
        run_step([sys.executable, '-c', 'import sys; sys.exit(3)'], lg, 10, 5, what='код')
        ok(False, 'rc≠0 — RenderError')
    except RenderError as e:
        ok(e.code == 'render_failed', 'ненулевой код шага — RenderError')
    run_step([sys.executable, '-c', 'print(1)'], lg, 10, 5, what='ок')
    ok(True, 'успешный шаг проходит')
    # дерево: потомок в своей группе процессов уходит вместе с родителем
    marker = os.path.join(d, 'child.pid')
    code = ('import subprocess, sys, time; p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); '
            f'open({marker!r}, "w").write(str(p.pid)); time.sleep(60)')
    try:
        run_step([sys.executable, '-c', code], lg, 2, 5, what='дерево')
    except RenderError:
        pass
    time.sleep(0.5)
    try:
        cp = int(open(marker).read())
        alive = os.path.exists(f'/proc/{cp}') and open(f'/proc/{cp}/stat').read().split(')')[-1].split()[0] != 'Z'
    except (OSError, ValueError):
        alive = False
    ok(not alive, 'остановка дерева: потомок убит вместе с родителем')
    shutil.rmtree(d, ignore_errors=True)
    print('итог:', 'чисто' if not bad else f'{bad} провал(ов)')
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
