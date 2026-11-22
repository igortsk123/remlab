#!/usr/bin/env python3
"""Воркер сравнения моделей разметки частей (Ш5 / T-183, T-20261121-179). Один образ = одна модель (env MODEL: p3sam | partllm).
Вход: список glb за одну ноду (очередь). Выход на КАЖДЫЙ меш — папка <OUT>/<job>/<sid>/: `faces.npy` int32[F] — метка части на каждую грань в порядке граней входного glb
(trimesh force='mesh', process=False; -1 = без метки) и `meta.json` {model, sid, sec_cold, sec_warm, peak_vram_gb, n_parts, names, rc, error, ...}. Отказ — rc!=0 и текст в error, молчаливых пропусков нет.
Время: sec_cold у ПЕРВОГО меша после загрузки весов, sec_warm у остальных (другое поле — None). Загрузка весов — `load_s` в /health и в meta.
HTTP (только stdlib, как главный процесс worker_trellis.py: /health отвечает сразу, веса грузятся в фоне):
  GET  /health                 → 200 {ok, model, phase, warm, error, load_s, queue, gpu, uptime_s, jobs:{id:{state,done,total}}}
  POST /run                    {"job_id","items":[{"sid","glb_b64"|"glb_url"|"path"}],"params":{…}} → 202; меши идут по одному (один GPU)
  GET  /job/<id>               → {state: queued|running|done, done, total, results:[meta…]}
  GET  /file/<id>/<sid>/<имя>  → faces.npy | meta.json | samples.npz | прочее из папки меша;  GET /archive/<id> → tar.gz всей папки задания
CLI (без сервера): python worker_parts.py --cli --list list.json --out <папка> [--job id]   (list.json: [{"sid","path"}, …] или {"items":[…]}).
Проверка без GPU и без весов: MODEL=fake (метки по высоте граней) — `--cli` и сервер работают так же."""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # локально kit_worker лежит на уровень выше (на ноде он регистрируется в sys.modules через bundle)
import kit_worker as KW  # noqa: E402

MODEL = os.environ.get('MODEL', 'fake')
OUT_DIR = os.environ.get('OUT_DIR', '/data/out')
PORT = int(os.environ.get('PORT', '8000'))
STATE = KW.State()                                  # kit: фаза weights→loading→ready/broken, ход задания (begin_job/step/note) → /health
WARM = [False]
LOAD_S = [None]
VERSION = 'parts-kit-1'
JOBS: dict = {}
LOCK = threading.Lock()
QUEUE: list = []
WORK = None
BACKEND = None


def nvidia_smi() -> dict:
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,driver_version', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
        n, tot, used, drv = [x.strip() for x in r.stdout.strip().splitlines()[0].split(',')]
        return {'name': n, 'mem_total_mb': float(tot), 'mem_used_mb': float(used), 'driver': drv}
    except Exception:  # noqa: BLE001
        return {}


def load_faces(path: str):
    """Порядок граней входа — как в боевых скриптах: trimesh force='mesh', process=False."""
    import trimesh
    return trimesh.load(path, force='mesh', process=False)


def peak_vram_gb() -> float | None:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
    except Exception:  # noqa: BLE001
        pass
    return None


CUR_SAMPLER = None
def set_step(step: str, line: str = None) -> None:
    """Шаг и последняя строка лога модели → kit State.job (виден в /health.job, урок b1: 15 мин молчания)."""
    STATE.step(step, line)


gpu_util_mem = KW.gpu_util_mem


class VramSampler:
    """Раз в секунду: загрузка GPU (nvidia-smi utilization.gpu), занятая видеопамять и ядра CPU, занятые ЭТИМ процессом (os.times: user+sys всех потоков).
    Пик памяти — по nvidia-smi (то, что видит карта), отдельно от torch allocated/reserved. samples = [(t, gpu%, mem_mb, cores)]."""
    def __init__(self):
        self.peak_mb = 0.0
        self.samples = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        last_t, last_cpu = time.time(), sum(os.times()[:2])
        while not self._stop.is_set():
            u, mem = gpu_util_mem()
            now, cpu = time.time(), sum(os.times()[:2])
            cores = (cpu - last_cpu) / max(now - last_t, 1e-6)
            last_t, last_cpu = now, cpu
            if mem:
                self.peak_mb = max(self.peak_mb, mem)
            self.samples.append((now, u, mem, round(cores, 2)))
            self._stop.wait(1.0)

    def __enter__(self):
        global CUR_SAMPLER
        CUR_SAMPLER = self
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()


def stage_table(lines: list, sampler) -> list:
    """lines = [(время конца стадии, имя, секунды)] из печати Timer модели; по семплам sampler — средняя загрузка GPU и ядер CPU в окне стадии."""
    out = []
    for t_end, name, sec in lines:
        t0 = t_end - sec
        w = [x for x in (sampler.samples if sampler else []) if t0 <= x[0] <= t_end]
        gu = [x[1] for x in w if x[1] is not None]
        cu = [x[3] for x in w]
        row = {'stage': name, 'sec': round(sec, 2), 'samples': len(w),
               'gpu_util_mean': round(sum(gu) / len(gu), 1) if gu else None, 'cores_mean': round(sum(cu) / len(cu), 2) if cu else None}
        if sec >= 1.0 and row['gpu_util_mean'] is not None:
            row['device'] = 'gpu' if row['gpu_util_mean'] >= 30 else 'cpu'
        out.append(row)
    return out


class TimedOut:
    """stdout-ловушка: запоминает время каждой строки (Timer печатает в конце стадии)."""
    def __init__(self):
        self.lines = []
        self._buf = ''

    def write(self, x):
        self._buf += x
        while '\n' in self._buf:
            ln, self._buf = self._buf.split('\n', 1)
            self.lines.append((time.time(), ln))
            if ln.strip():
                set_step('after: ' + ln.strip()[:80], ln.strip()[:160])
        return len(x)

    def flush(self):
        pass


def torch_peaks() -> dict:
    try:
        import torch
        if torch.cuda.is_available():
            return {'alloc': round(torch.cuda.max_memory_allocated() / 2 ** 30, 2), 'reserved': round(torch.cuda.max_memory_reserved() / 2 ** 30, 2)}
    except Exception:  # noqa: BLE001
        pass
    return {}


def reset_peak() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- модели
class FakeBackend:
    """Для проверки обвязки без GPU: метка = номер «этажа» по высоте центра грани (4 части)."""
    def load(self) -> dict:
        return {}

    def segment(self, mesh, params: dict, outdir: str) -> dict:
        import numpy as np
        c = mesh.triangles_center[:, 1]
        q = np.quantile(c, [0.25, 0.5, 0.75])
        lab = np.digitize(c, q).astype(np.int32)
        return {'faces': lab, 'names': None}


class P3SamBackend:
    """P3-SAM (Hunyuan3D-Part): метки частей без имён. Код — /opt/Hunyuan3D-Part/P3-SAM/demo/auto_mask.py (AutoMask.predict_aabb).
    Параметры (POST params): point_num, prompt_num (в коде mesh_sam они ЖЁСТКО заданы 100000/400 и затирают аргументы — при загрузке правим копию файла),
    decimate_faces (0 = как есть; иначе прореживание до N граней + перенос меток на полный меш по ближайшей грани), threshold, prompt_bs, seed.
    В meta: stages (время по стадиям из Timer кода P3-SAM), decimate_s, transfer_s, patched (правка копии удалась)."""
    def load(self) -> dict:
        import numpy as np  # noqa: F401
        root = os.environ.get('P3SAM_ROOT', '/opt/Hunyuan3D-Part')
        demo = f'{root}/P3-SAM/demo'
        self.patched = False
        pdir = '/tmp/p3sam_patched'
        try:
            src = open(f'{demo}/auto_mask.py', encoding='utf-8').read()
            old = '    point_num = 100000\n    prompt_num = 400\n'
            if src.count(old) == 1:
                os.makedirs(pdir, exist_ok=True)
                open(f'{pdir}/auto_mask.py', 'w', encoding='utf-8').write(src.replace(old, ''))
                self.patched = True
        except Exception as e:  # noqa: BLE001
            print(f'[worker] правка копии auto_mask не удалась: {e}', flush=True)
        for p in (f'{root}/P3-SAM/demo', f'{root}/P3-SAM', f'{root}/XPart/partgen'):
            sys.path.insert(0, p)
        if self.patched:
            sys.path.insert(0, pdir)
        os.chdir(demo)
        import auto_mask as AM
        self.AM = AM
        AM.Timer.STATE = 1          # время по стадиям: печатает сам код модели, мы ловим вывод
        ck = os.environ.get('P3SAM_CKPT', '/opt/weights/hy3d-part/p3sam/p3sam.safetensors')
        self.am = AM.AutoMask(ck)
        return {'ckpt': ck, 'patched': self.patched, 'auto_mask_file': getattr(AM, '__file__', None)}

    @staticmethod
    def _decimate(m, target: int):
        import numpy as np
        import trimesh
        n = len(m.faces)
        if target <= 0 or n <= target:
            return m, None
        try:
            import fast_simplification as FS
            v, f = FS.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32), target_count=int(target), agg=7)
        except ImportError:
            d = m.simplify_quadric_decimation(face_count=int(target))
            v, f = d.vertices, d.faces
        return trimesh.Trimesh(vertices=v, faces=f, process=False), True

    def segment(self, mesh, params: dict, outdir: str) -> dict:
        import io
        import re
        import contextlib
        import numpy as np
        AM = self.AM
        m = mesh.copy()
        m.merge_vertices()        # швы текстуры → один шов геометрии (нужно соседству граней); число и порядок граней не меняются
        n_in = len(mesh.faces)
        if len(m.faces) != n_in:
            raise RuntimeError(f'merge_vertices изменил число граней {n_in}->{len(m.faces)}')
        pn, qn = int(params.get('point_num', 100000)), int(params.get('prompt_num', 400))
        if (pn != 100000 or qn != 400) and not self.patched:
            raise RuntimeError('point_num/prompt_num заданы, а правка копии auto_mask не применилась — значения были бы молча проигнорированы')
        dec = int(params.get('decimate_faces', 0))
        set_step('decimate')
        t0 = time.time()
        work, did = self._decimate(m, dec)
        set_step('predict_aabb')
        dec_s = round(time.time() - t0, 2)
        AM.set_seed(int(params.get('seed', 42)))
        buf = TimedOut()
        with contextlib.redirect_stdout(buf):
            _aabb, face_ids, _mesh = self.am.predict_aabb(
                work, point_num=pn, prompt_num=qn,
                threshold=float(params.get('threshold', 0.95)), post_process=bool(int(params.get('post_process', 0))),
                save_mid_res=False, show_info=False, clean_mesh_flag=False, seed=int(params.get('seed', 42)), is_parallel=False,
                prompt_bs=int(params.get('prompt_bs', 32)))
        stages = {}
        st_lines = []
        for t_end, ln in buf.lines:
            mm = re.search(r'>>>>>>代码(.+?) 运行时间: ([0-9.]+) 秒', ln)
            if mm:
                stages[mm.group(1)] = round(float(mm.group(2)), 2)
                st_lines.append((t_end, mm.group(1), float(mm.group(2))))
        table = stage_table(st_lines, CUR_SAMPLER)
        fid = np.asarray(face_ids).astype(np.int64)
        if fid.shape[0] != len(work.faces):
            raise RuntimeError(f'модель вернула {fid.shape[0]} меток на {len(work.faces)} граней')
        set_step('transfer')
        t1 = time.time()
        if did:       # перенос на полный меш: метка ближайшей грани прореженного (по центрам граней)
            from scipy.spatial import cKDTree
            _, j = cKDTree(np.asarray(work.triangles_center)).query(np.asarray(m.triangles_center))
            fid = fid[j]
        tr_s = round(time.time() - t1, 2)
        if fid.shape[0] != n_in:
            raise RuntimeError(f'после переноса {fid.shape[0]} меток на {n_in} граней')
        return {'faces': fid.astype(np.int32), 'names': None,
                'extra': {'stages': stages, 'stage_table': table, 'cpu_count': os.cpu_count(), 'cpu_affinity': len(os.sched_getaffinity(0)), 'decimate_s': dec_s, 'transfer_s': tr_s, 'n_faces_work': int(len(work.faces)), 'patched': self.patched, 'params': {'point_num': pn, 'prompt_num': qn, 'decimate_faces': dec}}}


# chat_template.jinja весов PartLLM@0c546a88 (git blob 4a8b1a04): образ собран с allow_patterns без *.jinja, а процессор без шаблона падает в apply_chat_template.
# Код воркера едет в env группы (образ не пересобираем), поэтому шаблон вшит строкой, а не файлом.
# ОБХОД для образа 38990c38: Dockerfile.partllm теперь качает все мелкие файлы ревизии (ignore_patterns), при следующей сборке образа шаблон лежит сам и вшитый можно удалить.
PARTLLM_CHAT_TEMPLATE = '{%- if tools %}\n    {{- \'<|im_start|>system\\n\' }}\n    {%- if messages[0].role == \'system\' %}\n        {%- if messages[0].content is string %}\n            {{- messages[0].content }}\n        {%- else %}\n            {%- for content in messages[0].content %}\n                {%- if \'text\' in content %}\n                    {{- content.text }}\n                {%- endif %}\n            {%- endfor %}\n        {%- endif %}\n        {{- \'\\n\\n\' }}\n    {%- endif %}\n    {{- "# Tools\\n\\nYou may call one or more functions to assist with the user query.\\n\\nYou are provided with function signatures within <tools></tools> XML tags:\\n<tools>" }}\n    {%- for tool in tools %}\n        {{- "\\n" }}\n        {{- tool | tojson }}\n    {%- endfor %}\n    {{- "\\n</tools>\\n\\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\\n<tool_call>\\n{\\"name\\": <function-name>, \\"arguments\\": <args-json-object>}\\n</tool_call><|im_end|>\\n" }}\n{%- else %}\n    {%- if messages[0].role == \'system\' %}\n        {{- \'<|im_start|>system\\n\' }}\n        {%- if messages[0].content is string %}\n            {{- messages[0].content }}\n        {%- else %}\n            {%- for content in messages[0].content %}\n                {%- if \'text\' in content %}\n                    {{- content.text }}\n                {%- endif %}\n            {%- endfor %}\n        {%- endif %}\n        {{- \'<|im_end|>\\n\' }}\n    {%- endif %}\n{%- endif %}\n{%- set image_count = namespace(value=0) %}\n{%- set video_count = namespace(value=0) %}\n{%- set point_cloud_count = namespace(value=0) %}\n{%- set point_cloud_count = namespace(value=0) %}\n{%- for message in messages %}\n    {%- if message.role == "user" %}\n        {{- \'<|im_start|>\' + message.role + \'\\n\' }}\n        {%- if message.content is string %}\n            {{- message.content }}\n        {%- else %}\n            {%- for content in message.content %}\n                {%- if content.type == \'image\' or \'image\' in content or \'image_url\' in content %}\n                    {%- set image_count.value = image_count.value + 1 %}\n                    {%- if add_vision_id %}Picture {{ image_count.value }}: {% endif -%}\n                    <|vision_start|><|image_pad|><|vision_end|>\n                {%- elif content.type == \'video\' or \'video\' in content %}\n                    {%- set video_count.value = video_count.value + 1 %}\n                    {%- if add_vision_id %}Video {{ video_count.value }}: {% endif -%}\n                    <|vision_start|><|video_pad|><|vision_end|>\n                {%- elif content.type == \'point_cloud\' or \'point_cloud\' in content %}\n                    {%- set point_cloud_count.value = point_cloud_count.value + 1 %}\n                    {%- if add_vision_id %}Point Cloud {{ point_cloud_count.value }}: {% endif -%}\n                    <|point_cloud_start|><|point_cloud_pad|><|point_cloud_end|>\n                {%- elif \'text\' in content %}\n                    {{- content.text }}\n                {%- endif %}\n            {%- endfor %}\n        {%- endif %}\n        {{- \'<|im_end|>\\n\' }}\n    {%- elif message.role == "assistant" %}\n        {{- \'<|im_start|>\' + message.role + \'\\n\' }}\n        {%- if message.content is string %}\n            {{- message.content }}\n        {%- else %}\n            {%- for content_item in message.content %}\n                {%- if \'text\' in content_item %}\n                    {{- content_item.text }}\n                {%- endif %}\n            {%- endfor %}\n        {%- endif %}\n        {%- if message.tool_calls %}\n            {%- for tool_call in message.tool_calls %}\n                {%- if (loop.first and message.content) or (not loop.first) %}\n                    {{- \'\\n\' }}\n                {%- endif %}\n                {%- if tool_call.function %}\n                    {%- set tool_call = tool_call.function %}\n                {%- endif %}\n                {{- \'<tool_call>\\n{"name": "\' }}\n                {{- tool_call.name }}\n                {{- \'", "arguments": \' }}\n                {%- if tool_call.arguments is string %}\n                    {{- tool_call.arguments }}\n                {%- else %}\n                    {{- tool_call.arguments | tojson }}\n                {%- endif %}\n                {{- \'}\\n</tool_call>\' }}\n            {%- endfor %}\n        {%- endif %}\n        {{- \'<|im_end|>\\n\' }}\n    {%- elif message.role == "tool" %}\n        {%- if loop.first or (messages[loop.index0 - 1].role != "tool") %}\n            {{- \'<|im_start|>user\' }}\n        {%- endif %}\n        {{- \'\\n<tool_response>\\n\' }}\n        {%- if message.content is string %}\n            {{- message.content }}\n        {%- else %}\n            {%- for content in message.content %}\n                {%- if content.type == \'image\' or \'image\' in content or \'image_url\' in content %}\n                    {%- set image_count.value = image_count.value + 1 %}\n                    {%- if add_vision_id %}Picture {{ image_count.value }}: {% endif -%}\n                    <|vision_start|><|image_pad|><|vision_end|>\n                {%- elif content.type == \'video\' or \'video\' in content %}\n                    {%- set video_count.value = video_count.value + 1 %}\n                    {%- if add_vision_id %}Video {{ video_count.value }}: {% endif -%}\n                    <|vision_start|><|video_pad|><|vision_end|>\n                {%- elif content.type == \'point_cloud\' or \'point_cloud\' in content %}\n                    {%- set point_cloud_count.value = point_cloud_count.value + 1 %}\n                    {%- if add_vision_id %}Point Cloud {{ point_cloud_count.value }}: {% endif -%}\n                    <|point_cloud_start|><|point_cloud_pad|><|point_cloud_end|>\n                {%- elif \'text\' in content %}\n                    {{- content.text }}\n                {%- endif %}\n            {%- endfor %}\n        {%- endif %}\n        {{- \'\\n</tool_response>\' }}\n        {%- if loop.last or (messages[loop.index0 + 1].role != "tool") %}\n            {{- \'<|im_end|>\\n\' }}\n        {%- endif %}\n    {%- endif %}\n{%- endfor %}\n{%- if add_generation_prompt %}\n    {{- \'<|im_start|>assistant\\n\' }}\n{%- endif %}\n'
PARTLLM_CHAT_TEMPLATE_BLOB = '4a8b1a04e7feba3aecd145d6620c37649cfaca60'


def ensure_chat_template(mp: str) -> bool:
    """Нет chat_template.jinja в папке весов — пишем вшитый. True, если записали."""
    p = os.path.join(mp, 'chat_template.jinja')
    if os.path.isfile(p):
        return False
    os.makedirs(mp, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(PARTLLM_CHAT_TEMPLATE)
    return True


def partllm_argv(mp: str, prompt_set: str, args_dir: str = '/tmp/partllm-args') -> list:
    """argv для `test_mask_pred.parse_args`. В репозитории PartLLM @e17509bc НЕТ `infer_config.yaml`, а `--config` по умолчанию = он, и `apply_yaml_config` открывает файл без проверки
    (pl1 22.11: FileNotFoundError на прогреве, $0,016). Пустой YAML = «все значения по умолчанию из argparse» (infer.sh апстрима тоже ничего сверх CLI не передаёт)."""
    os.makedirs(args_dir, exist_ok=True)
    cfg = os.path.join(args_dir, 'infer_config.yaml')
    with open(cfg, 'w') as f:
        f.write('{}\n')
    return ['partllm', '--config', cfg, '--glb_dir', '/tmp', '--output_dir', args_dir, '--model_path', mp, '--config_path', mp,
            '--sem_mode', 'semantic', '--prompt_set', prompt_set]


class PartLlmBackend:
    """PartLLM (full-shape, без имён на входе: модель сама называет части). В процессе: веса грузятся один раз (cold/warm), далее по мешу
    prepare_geometry_from_glb → run_inference → process_and_save (их же код, `test_mask_pred.py main_glb_dir`). На выходе faces.npy = ЭКЗЕМПЛЯРЫ частей (instance_labels.npy,
    если есть, иначе face_labels), классы по именам — extra.class_faces → `faces_class.npy`; имена — meta.names (по классам). ПОРЯДОК ГРАНЕЙ: их combined_mesh строится
    trimesh.load(process=True)+scene2meshes → сверяем центроиды граней с нашим glb (process=False) в нормированных координатах: identity | remapped (ближайший центроид) | fail.
    НЕ проверено на GPU: нумерация классов и фон (последний класс логитов [S+1] — предположительно фон) — см. extra.n_classes / names."""
    def load(self) -> dict:
        root = os.environ.get('PARTLLM_ROOT', '/opt/PartLLM')
        for p in (f'{root}/recipe/part_seg/tools/inference', f'{root}/recipe/part_seg', root):
            sys.path.insert(0, p)
        os.chdir(root)
        import test_mask_pred as T
        self.T = T
        mp = os.environ.get('MODEL_PATH', '/opt/weights/partllm')
        self.prompt_set = os.environ.get('PARTLLM_PROMPT_SET', 'general')
        wrote_tpl = ensure_chat_template(mp)
        sys.argv = partllm_argv(mp, self.prompt_set)
        self.args = T.parse_args()
        T.set_global_seed(self.args.seed)
        self.model, self.processor, _tok, self.hf_config, self.encoder_type = T.load_model(self.args)
        return {'model_path': mp, 'prompt_set': self.prompt_set, 'chat_template_written': wrote_tpl}

    def segment(self, mesh, params: dict, outdir: str) -> dict:
        import numpy as np
        from scipy.spatial import cKDTree
        T = self.T
        gran = params.get('prompt_set', self.prompt_set)
        gp = T.build_glb_open_prompts('semantic', gran)
        gran_name, tmpl = gp[0]
        geo = T.prepare_geometry_from_glb(os.path.join(outdir, 'input.glb'), self.model, self.hf_config, self.encoder_type,
                                          apply_z_positive=self.args.apply_z_positive, clean_mesh=False)
        inputs, user_prompt = T.prepare_prompt_from_template(tmpl, geo, self.processor, self.model)
        response, mask_logits, pca = T.run_inference(self.model, inputs, geo['utonia_point_dict'], self.processor, self.args)
        sd = os.path.join(outdir, 'partllm')
        os.makedirs(sd, exist_ok=True)
        T.process_and_save(response, mask_logits, inputs, {'model_id': 'x', 'prompt_mode': f'open/{gran_name}', 'granularity': gran_name},
                           sd, self.args, 0, user_prompt, None, mesh_vis_info=geo['mesh_vis_info'], pca_capture=pca)
        if pca is not None:
            pca.detach()
        fl = os.path.join(sd, 'face_labels.npy')
        if not os.path.isfile(fl):
            raise RuntimeError('PartLLM не записал face_labels.npy (маски нет: mask_logits=None?)')
        cls = np.load(fl).astype(np.int64)
        il = os.path.join(sd, 'instance_labels.npy')
        inst = np.load(il).astype(np.int64) if os.path.isfile(il) else None
        lab = inst if inst is not None else cls
        cm = geo['mesh_vis_info']['combined_mesh']
        n_in = len(mesh.faces)
        # сверка порядка граней: центроиды в координатах «центр bbox, диагональ 1»
        def norm_c(m):
            v = np.asarray(m.vertices, dtype=np.float64)
            lo, hi = v.min(0), v.max(0)
            return (np.asarray(m.triangles_center, dtype=np.float64) - (lo + hi) / 2) / max(float(np.linalg.norm(hi - lo)), 1e-12)
        mine, theirs = norm_c(mesh), norm_c(cm)
        if len(cm.faces) == n_in and float(np.abs(mine - theirs).max()) < 1e-3:
            order, out, out_cls = {'order_check': 'identity', 'max_centroid_diff': float(np.abs(mine - theirs).max())}, lab, cls
        else:
            d, idx = cKDTree(theirs).query(mine)
            order = {'order_check': 'remapped', 'faces_theirs': int(len(cm.faces)), 'faces_input': int(n_in), 'max_nn_dist': float(d.max()), 'p99_nn_dist': float(np.quantile(d, 0.99))}
            if float(np.quantile(d, 0.99)) > 5e-3:
                raise RuntimeError(f'порядок граней не восстановлен: {order}')
            out, out_cls = lab[idx], cls[idx]
        np.save(os.path.join(outdir, 'faces_class.npy'), out_cls.astype(np.int32))
        parts = T.parse_response_parts(response)
        names = [p['label'] for p in parts]
        extra = dict(order, n_classes=int(mask_logits.shape[1]) if mask_logits is not None else None, instances=inst is not None, response=response[:2000], prompt=gran_name)
        return {'faces': out.astype(np.int32), 'names': names, 'extra': extra}


def make_backend():
    return {'fake': FakeBackend, 'p3sam': P3SamBackend, 'partllm': PartLlmBackend}[MODEL]()


# ---------------------------------------------------------------- пакет
def fetch_glb(it: dict, dst: str) -> None:
    if it.get('glb_b64'):
        open(dst, 'wb').write(base64.b64decode(it['glb_b64']))
    elif it.get('glb_url'):
        urllib.request.urlretrieve(it['glb_url'], dst)
    elif it.get('path'):
        if os.path.abspath(it['path']) != os.path.abspath(dst):
            open(dst, 'wb').write(open(it['path'], 'rb').read())
    else:
        raise ValueError('нет glb_b64 / glb_url / path')


def run_item(it: dict, params: dict, jobdir: str, first: bool) -> dict:
    import numpy as np
    sid = str(it['sid'])
    d = os.path.join(jobdir, sid)
    os.makedirs(d, exist_ok=True)
    meta = {'model': MODEL, 'sid': sid, 'sec_cold': None, 'sec_warm': None, 'peak_vram_gb': None, 'n_parts': None, 'names': None, 'rc': 0, 'error': None, 'load_s': LOAD_S[0]}
    t = time.time()
    try:
        src = os.path.join(d, 'input.glb')
        STATE.step('fetch_glb')
        fetch_glb(it, src)
        STATE.step('load_mesh')
        mesh = load_faces(src)
        meta['n_faces'] = int(len(mesh.faces))
        reset_peak()
        t = time.time()
        with VramSampler() as vs:
            res = BACKEND.segment(mesh, params, d)
        sec = round(time.time() - t, 2)
        meta['sec_cold' if first else 'sec_warm'] = sec
        tp = torch_peaks()
        meta['peak_torch_alloc_gb'] = tp.get('alloc')
        meta['peak_torch_reserved_gb'] = tp.get('reserved')
        meta['peak_smi_gb'] = round(vs.peak_mb / 1024, 2)
        meta['peak_vram_gb'] = meta['peak_smi_gb'] or tp.get('reserved')     # то, что реально занято на карте (nvidia-smi)
        STATE.step('save')
        f = np.asarray(res['faces']).astype(np.int32)
        assert f.shape == (meta['n_faces'],), (f.shape, meta['n_faces'])
        np.save(os.path.join(d, 'faces.npy'), f)
        labs = sorted(int(x) for x in np.unique(f) if x >= 0)
        meta['n_parts'] = len(labs)
        meta['share_unlabeled'] = round(float((f < 0).mean()), 4)
        if res.get('names') is not None:
            meta['names'] = res['names']
        if res.get('extra'):
            meta['extra'] = res['extra']
    except Exception as e:  # noqa: BLE001
        meta['rc'] = 1
        meta['error'] = f'{type(e).__name__}: {e}'[:800]
        meta['trace'] = traceback.format_exc()[-1500:]
        meta['sec_cold' if first else 'sec_warm'] = round(time.time() - t, 2)
        meta['peak_vram_gb'] = peak_vram_gb()
        print(f'[worker] {sid} ОТКАЗ: {meta["error"]}', flush=True)
        if KW.fatal_cuda(e):                                  # урок 744: после фатальной CUDA (и OOM) процесс живёт испорченным — заданий больше не берём
            STATE.phase, STATE.error = 'broken', 'broken: ' + meta['error'][:200]
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w'), ensure_ascii=False, indent=1)
    return meta


def run_job(job_id: str, items: list, params: dict) -> None:
    jobdir = os.path.join(OUT_DIR, job_id)
    os.makedirs(jobdir, exist_ok=True)
    j = JOBS[job_id]
    j['state'] = 'running'
    STATE.busy = True
    try:
        for k, it in enumerate(items):
            STATE.begin_job(f'{job_id}/{it.get("sid")}')       # ход виден в /health.job: шаг, секунды шага, GPU %, последняя строка Timer модели
            if STATE.phase == 'broken':
                m = {'model': MODEL, 'sid': str(it.get('sid')), 'rc': 1, 'error': 'воркер сломан: ' + str(STATE.error)}
            else:
                first = not WARM[0]
                print(f'[worker] {job_id} {k + 1}/{len(items)} {it.get("sid")}', flush=True)
                m = run_item(it, params, jobdir, first)
                if m['rc'] == 0:
                    WARM[0] = True
            j['results'].append(m)
            j['done'] = k + 1
            STATE.end_job()
        json.dump({'job_id': job_id, 'results': j['results']}, open(os.path.join(jobdir, 'summary.json'), 'w'), ensure_ascii=False, indent=1)
        j['state'] = 'done'
    finally:
        STATE.end_job()
        STATE.busy = False


def worker_loop(q: list) -> None:
    while True:
        with LOCK:
            nxt = q.pop(0) if q else None
        if nxt is None:
            time.sleep(0.5)
            continue
        while STATE.phase not in ('ready', 'broken'):          # сервер принимает задания во время прогрева — ждём его
            time.sleep(1)
        try:
            run_job(*nxt)
        except Exception as e:  # noqa: BLE001
            JOBS[nxt[0]]['state'] = 'done'
            JOBS[nxt[0]]['error'] = f'{type(e).__name__}: {e}'[:400]
            print('[worker] job failed:', traceback.format_exc(), flush=True)


def load_backend() -> None:
    """Шаг прогрева kit (фаза `loading`): веса уже в образе — читаются с диска в память карты. Исключение → фаза `broken` (kit.run_warm), драйвер гасит ноду."""
    global BACKEND
    t = time.time()
    BACKEND = make_backend()
    info = BACKEND.load()
    LOAD_S[0] = round(time.time() - t, 1)
    STATE.weights = {'in_image': True, 'info': info}
    print(f'[worker] модель {MODEL} загружена за {LOAD_S[0]} с', flush=True)


def check_deps() -> None:
    """Зависимости — ТОЛЬКО из образа (п.1 рецепта: докачки при старте нет; урок b1 — pip при старте мог поменять numpy/numba). Нет пакета — прогрев падает сразу (фаза broken, $ минуты),
    а не тихий откат на медленный trimesh."""
    if MODEL != 'p3sam':
        return
    try:
        import fast_simplification  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('в образе нет fast-simplification — пересобрать образ (Dockerfile.p3sam), докачку при старте не делаем') from exc
    STATE.note('fast_simplification: есть в образе')


def health_extra() -> dict:
    return {'model': MODEL, 'warm': WARM[0], 'load_s': LOAD_S[0], 'queue': len(QUEUE), 'gpu': nvidia_smi(),
            'cores_now': (CUR_SAMPLER.samples[-1][3] if CUR_SAMPLER and CUR_SAMPLER.samples else None),
            'jobs': {k: {'state': v['state'], 'done': v['done'], 'total': v['total']} for k, v in JOBS.items()}}


class PartsHandler(KW.KitHandler):
    """`/health` и `/shutdown` — в kit; здесь пути модели: POST /run, GET /job/<id>, /file/<job>/<sid>/<имя>, /archive/<job>."""

    def handle_get(self, path: str) -> bool:
        p = path.split('?')[0].strip('/').split('/')
        try:
            if p[0] == 'job' and len(p) == 2:
                j = JOBS.get(p[1])
                self.send_json(200 if j else 404, j or {'error': 'нет такого задания'})
                return True
            if p[0] == 'file' and len(p) >= 4:
                fp = os.path.realpath(os.path.join(OUT_DIR, p[1], p[2], '/'.join(p[3:])))
                if not fp.startswith(os.path.realpath(OUT_DIR) + os.sep) or not os.path.isfile(fp):
                    self.send_json(404, {'error': 'нет файла'})
                else:
                    self.send_bytes(200, open(fp, 'rb').read(), 'application/octet-stream')
                return True
            if p[0] == 'archive' and len(p) == 2:
                jd = os.path.realpath(os.path.join(OUT_DIR, p[1]))
                if not jd.startswith(os.path.realpath(OUT_DIR) + os.sep) or not os.path.isdir(jd):
                    self.send_json(404, {'error': 'нет задания'})
                    return True
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode='w:gz') as tf:
                    for root, _d, files in os.walk(jd):
                        for fn in files:
                            if fn == 'input.glb':
                                continue                  # вход не отдаём обратно
                            tf.add(os.path.join(root, fn), arcname=os.path.relpath(os.path.join(root, fn), OUT_DIR))
                self.send_bytes(200, buf.getvalue(), 'application/gzip')
                return True
        except Exception as e:  # noqa: BLE001
            self.send_json(500, {'error': f'{type(e).__name__}: {e}'[:300]})
            return True
        return False

    def handle_post(self, path: str) -> bool:
        if path.split('?')[0] != '/run':
            return False
        try:
            body = self.read_json(200 * 2 ** 20)              # 4 меша по ~10 МБ в base64 — с запасом
            if body is None:
                return True
            items = body.get('items') or []
            if not items:
                self.send_json(400, {'error': 'items пуст'})
                return True
            jid = str(body.get('job_id') or f'job{int(time.time())}')
            if jid in JOBS and JOBS[jid]['state'] != 'done':
                self.send_json(409, {'error': 'задание с таким id уже идёт'})
                return True
            if STATE.phase == 'broken':
                self.send_json(503, {'error': STATE.error})
                return True
            if STATE.busy or QUEUE:                            # один GPU — одно задание за раз; драйвер при 429 ждёт, не считает провалом (kit_driver)
                self.send_json(429, {'error': 'нода занята'})
                return True
            JOBS[jid] = {'state': 'queued', 'done': 0, 'total': len(items), 'results': []}
            with LOCK:
                QUEUE.append((jid, items, body.get('params') or {}))
            self.send_json(202, {'job_id': jid, 'queued': len(items)})
        except Exception as e:  # noqa: BLE001
            self.send_json(400, {'error': f'{type(e).__name__}: {e}'[:300]})
        return True


def main() -> int:
    global OUT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument('--cli', action='store_true')
    ap.add_argument('--list')
    ap.add_argument('--out', default=OUT_DIR)
    ap.add_argument('--job', default=f'cli{int(time.time())}')
    ap.add_argument('--params', default='{}')
    a = ap.parse_args()
    if a.cli:
        OUT_DIR = a.out
        os.makedirs(OUT_DIR, exist_ok=True)
        data = json.load(open(a.list))
        items = data['items'] if isinstance(data, dict) else data
        try:
            load_backend()
        except Exception as e:  # noqa: BLE001
            print('загрузка не удалась:', f'{type(e).__name__}: {e}', file=sys.stderr)
            return 2
        STATE.phase = 'ready'
        JOBS[a.job] = {'state': 'queued', 'done': 0, 'total': len(items), 'results': []}
        run_job(a.job, items, json.loads(a.params))
        bad = [r for r in JOBS[a.job]['results'] if r.get('rc')]
        print(f'готово: {len(items) - len(bad)}/{len(items)} ок, отказов {len(bad)}; {os.path.join(OUT_DIR, a.job)}')
        return 1 if bad else 0
    OUT_DIR = os.environ.get('OUT_DIR', OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)
    stop = threading.Event()
    wd = KW.Watchdog(float(os.environ.get('MAX_LIFETIME_S', 4 * 3600)), float(os.environ.get('IDLE_S', 1200)))
    handler = PartsHandler.bind(STATE, wd, stop, VERSION, root_dir='/opt/weights', health_extra=health_extra)
    threading.Thread(target=worker_loop, args=(QUEUE,), daemon=True).start()
    print(f'[worker] kit HTTP :{PORT}, модель {MODEL}, out {OUT_DIR}', flush=True)
    return KW.serve(handler, STATE, wd, stop, [('loading', check_deps), ('loading', load_backend)], port=PORT)


if __name__ == '__main__':
    sys.exit(main())
