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


class LocalCpuExecutor:
    """Blender Cycles на процессоре DEV под общей очередью тяжёлых прогонов (`heavy_slot`): задание держит слот на ВЕСЬ путь
    (сцена + оба кадра) — между шагами память и ядра не отдаём, чтобы пара не растянулась из-за чужих прогонов."""
    name = 'local-cpu'

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

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        import render_snapshot as RS
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
        # 4) JPEG и мета — каталогом по ключу (подменой, meta последней)
        progress('save')
        from PIL import Image
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


class SaladGpuExecutor:
    """Машина рендера на Salad (отдельный план директора): тот же вход и выход. Пока адрес машины не задан (`RENDER_SALAD_URL`) —
    `ExecutorUnavailable`, и запасной путь (`Fallback`) уходит на процессор DEV без вмешательства очереди."""
    name = 'salad-gpu'

    def __init__(self, env=os.environ):
        self.url = (env.get('RENDER_SALAD_URL') or '').rstrip('/')

    def versions(self) -> dict:
        return {'executor': self.name}

    def render(self, snap: dict, out_dir: str, progress) -> dict:
        raise ExecutorUnavailable('gpu_unavailable', 'Машина рендера занята. Считаем на запасной — будет дольше.',
                                  'The render machine is busy. Using the backup — it will take longer.')


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
