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
            time.sleep(1.0)
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

    def __init__(self, env=os.environ):
        self.blender = env.get('RENDER_BLENDER') or os.path.expanduser('~/opt/blender-5.3.0-linux-x64/blender')
        self.node = env.get('RENDER_NODE') or shutil.which('node') or '/usr/local/bin/node'
        self.python = env.get('RENDER_PYTHON') or sys.executable
        self.work = env.get('RENDER_WORK') or os.path.expanduser('~/scout-scenes/render-cycles')
        self.public = os.path.join(REPO, 'public')
        os.makedirs(self.work, exist_ok=True)

    def versions(self) -> dict:
        return render_version(self.blender)

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
            run_step([self.node, os.path.join(PROBE, 'build_entry.mjs'), out], log, 300, 4, what='сборка выгрузчика')
            for old in [d for d in os.listdir(self.work) if d.startswith('bundle-') and os.path.join(self.work, d) != out]:
                shutil.rmtree(os.path.join(self.work, old), ignore_errors=True)
        return out

    def _prepare(self, snap: dict, job: str, log: str, pr: dict, progress, timing: dict) -> str:
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
        # МЕШ НЕ ПРОПУСКАЕМ МОЛЧА (T-20261117-19/2: в set4 диван выпал из кадра, подушка повисла в воздухе, а рендер «получился»): экспорт при сбое
        # меша печатает «<роль> пропущен» и идёт дальше. Один повтор (GLB уже докачан в кэш) — и если предмет снова пропущен, отказ ДО Blender'а
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
        timing['export'] = round(time.time() - t1, 1)
        t1 = time.time()
        # 2) сцена движком страницы → декор и отделка
        bundle = self._bundle(log)
        dump = os.path.join(job, 'dump')
        run_step([self.node, os.path.join(PROBE, 'demo_scene_dump.mjs'), data_path, '0', bundle, dump, 'export=' + pr['dumpExport']], log,
                 lim['dumpSec'], lim['maxRssGb'], what='декор и отделка')
        timing['dump'] = round(time.time() - t1, 1)
        return dump

    def _finish(self, snap: dict, outs: dict, out_dir: str, pr: dict, timing: dict, t0: float, job: str) -> dict:
        """Шаг 4: JPEG и мета — каталогом по ключу (подменой, meta последней); стадия `save` объявлена вызывающим."""
        from PIL import Image  # noqa: F811
        tmp = out_dir + '.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        size, sha = None, {}
        for cam, png in outs.items():
            im = Image.open(png).convert('RGB')
            size = [im.width, im.height]
            jp = os.path.join(tmp, f'{cam}.jpg')
            im.save(jp, 'JPEG', quality=pr['jpegQuality'], optimize=True)
            sha[cam] = hashlib.sha256(open(jp, 'rb').read()).hexdigest()     # имя кадра для «Улучшить» (как у кадров браузера: sha256 JPEG)
        timing['total'] = round(time.time() - t0, 1)
        meta = {'scene_hash': snap['scene_hash'], 'snapshot_version': snap['v'], 'size': size, 'sha': sha, 'versions': self.versions(), 'timing': timing,
                'executor': self.name, 'ts': int(time.time()), 'source': snap.get('source')}
        json.dump(meta, open(os.path.join(tmp, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        shutil.rmtree(out_dir, ignore_errors=True)
        os.replace(tmp, out_dir)
        shutil.rmtree(job, ignore_errors=True)
        return {'timing': timing}


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
        job = os.path.join(self.work, 'job-' + snap['scene_hash'][:16])
        shutil.rmtree(job, ignore_errors=True)
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
                    import sink_health
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

    def _slot(self, label: str, pr: dict):
        """Общая очередь тяжёлых прогонов — только на сборку сцены на DEV (ожидание машины рендера процессор DEV не занимает)."""
        sys.path.insert(0, os.path.join(REPO, 'tools', 'ops'))
        import heavy_slot as HS
        return HS.heavy_slot(label, min_gb=pr['min_gb'], cores=2, prio=1)

    def _gpu_unavailable(self, code: str) -> ExecutorUnavailable:
        return ExecutorUnavailable(code, *GPU_FAILED)

    def _bundle_files(self, job: str) -> dict:
        """Состав пакета: сцена, декор/отделка, программа рендера и её данные, карты материалов, на которые ссылается отделка."""
        dump = os.path.join(job, 'dump')
        files = {'scene': os.path.join(job, 'scene'),
                 'tools/scout/cycles_probe/render_cycles.py': os.path.join(PROBE, 'render_cycles.py'),
                 'data/flat3d/wall-art.json': os.path.join(REPO, 'data', 'flat3d', 'wall-art.json')}
        for n in ('demo_nodes.glb', 'demo_nodes_uuids.json', 'scene-export.json'):
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

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        import jobs_proto as JP
        pr = preset()
        rules = self.gate()
        ex = rules.get('executor') or {}
        busy_s, poll_s = float(ex.get('busy_s', 90)), float(ex.get('poll_s', 3))
        pickup_s, pair_max_s = float(ex.get('pickup_s', 90)), float(ex.get('pair_max_s', 900))
        sink = self.sink()
        m = self.machine()
        job = os.path.join(self.work, 'gjob-' + snap['scene_hash'][:16])
        shutil.rmtree(job, ignore_errors=True)
        os.makedirs(job)
        log = os.path.join(job, 'run.log')
        t0, timing = self.now(), {}
        jid = f"{snap['scene_hash'][:12]}-{int(t0)}"
        m.pulse(busy_s=600)            # ЗАКАЗ = событие: отсчёт простоя с этого момента, и пока задание в работе — машину не гасим
        try:
            with self._slot('photo-render-' + snap['scene_hash'][:8], pr) as hs:
                timing['slot_wait'] = round(float(hs.get('waited_s', 0)), 1) if isinstance(hs, dict) else 0
                self._prepare(snap, job, log, pr, progress, timing)
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
                                  {'blenderSec': pr['limits']['blenderSecPerFrame']}, now=self.now())
                sink.put(f'{JP.PREFIX}/{jid}/job.json', json.dumps(jobj, ensure_ascii=False).encode())       # ПОСЛЕДНИМ
            except JP.SinkError as e:
                print(f'рендер: хранилище не приняло пакет: {e}', flush=True)
                raise self._gpu_unavailable('gpu_upload') from None
            timing['upload'] = round(self.now() - t1, 1)
            res = self._wait(sink, m, jid, progress, busy_s, poll_s, pickup_s, pair_max_s)
            t1 = self.now()
            outs = {}
            try:
                for cam in CAMS:
                    png = os.path.join(job, f'{cam}.png')
                    sink.get_to(f'{JP.PREFIX}/{jid}/{cam}.png', png)
                    outs[cam] = png
            except JP.SinkError as e:
                print(f'рендер: кадры не скачались: {e}', flush=True)
                raise self._gpu_unavailable('gpu_download') from None
            timing['download'] = round(self.now() - t1, 1)
            for k, v in (res.get('timing') or {}).items():          # C1, C2, fetch, render — как у local-cpu (кадры), плюс загрузка сцены машиной
                if isinstance(v, (int, float)):
                    timing[k] = v
            print(f"рендер: пара на машине, устройство {res.get('device')}, {timing.get('render')} с Blender", flush=True)
            return self._finish(snap, outs, out_dir, pr, timing, t0, job)
        finally:
            shutil.rmtree(job, ignore_errors=True)
            try:
                sink.delete(f'{JP.PREFIX}/{jid}')      # своё задание убираем сразу (место общее с мешами); не вышло — уберёт jobs_purge по сроку
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
