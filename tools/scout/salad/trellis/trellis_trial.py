#!/usr/bin/env python3
"""ЗАМЕР ГЕНЕРАТОРА МЕШЕЙ НА SALAD (T-20261118-91, план `mesh-models-trial-01`): своя ВРЕМЕННАЯ группа `trial-<модель>-<метка>` (4090, 1 нода), без очереди
и БЕЗ приёмника на проде — результат забирается по HTTP через шлюз группы. Боевые группы и очередь мешей не трогает.

    ~/venvs/scout/bin/python trellis_trial.py --model trellis2 --image <digest|тег> --inputs <папка inputs/> \\
        --skus 112923:13224664101879413845 [...] --plan 1024:1,1536:1            # разбор: печатает тело группы без секретов, ничего не создаёт
    ... --apply                                                                    # создать, запустить, прогнать план, забрать GLB, ПОГАСИТЬ
    ... --stop-only --suffix <метка>                                               # просто /stop и проверка stopped

ПРЕДОХРАНИТЕЛИ (все — в этом файле, а не «по памяти»):
  • деньги: потолок `--cap` $ (по умолчанию 3,0 на ВЕСЬ замер, холодные старты включены), цена — по классу карты и тарифу из `rules/salad-groups.json`; начисления
    считаем по времени `running` инстанса (платим за running) + запас на отставание счёта; при потолке — стоп;
  • время: `--max-min` (по умолчанию 90) на жизнь ноды; за час без `running` — стоп (платили 0); без «готов» за `--ready-min` после running — стоп;
  • отказы: счётчик заданий упавших/не дождавшихся; 2 подряд упавших — стоп (чинить в коде, не жечь деньги);
  • СТОП С ПРОВЕРКОЙ `stopped` — всегда (finally), в том числе при исключении и Ctrl-C;
  • бесплатная проверка закрытых весов ПЕРЕД созданием группы: HEAD к `facebook/dinov3-…/config.json` с токеном — не 200 → не запускаем (решение директора 18.11);
  • токен Hugging Face и ключ Salad — из `~/scout-scenes/salad.env` через готовые функции, в журнал/печать не попадают (`safe_print` скрывает);
  • только RTX 4090 (приказ директора 18.11); боевые `mesh-`/`render-` группы и чужие живые группы не трогаем (чужая живая — отказ).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, os.path.join(SCOUT, 'render_gpu'))
sys.path.insert(0, HERE)

CARD = {'class_name': 'RTX 4090 (24 GB)', 'class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b'}
HF_GATED = {'trellis2': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json',
            'pixal3d': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json',
            'pixal3d-tex': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json',
            'localmesh': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json'}      # закрытые веса, без которых модель не поднимется
PORT = 8000
READINESS = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},      # НЕ /ready: пока проба не пройдена, шлюз отдаёт 503 на любой путь и прогрев не виден (урок шага 0, 18.11)
             'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3}
STARTUP = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},
           'initial_delay_seconds': 10, 'period_seconds': 60, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 20}   # API Salad: failure_threshold ≤ 20 (400 от 18.11) → 20 мин на докачку весов
NO_FAIL_STREAK = 2
TEX_ALIGNS = ('fit', 'official')      # pixal3d-tex: как кадрировать фото под форму (`worker_trellis.texture_on_shape`)


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


RESULTS_ROOT = os.path.expanduser('~/remlab-logs/mesh-models-1118')


def default_out(model: str) -> str:
    """Папка результатов — СВОЯ у каждой модели (`trellis2/`, `hunyuan21/`, `pixal3d/`, `localmesh/`, `pixal3d-tex/`). До 19.11 все писали в `trellis/` под одним именем
    `<ключ>-1024-42-0.glb`: Hunyuan-контроль затёр 12 GLB TRELLIS.2 (и наоборот 2) — кадры и таблицы по ним смешались."""
    return os.path.join(RESULTS_ROOT, model)


def owner_conflicts(out: str, job_ids: list[str], model: str) -> list[str]:
    """Задания, чей GLB в папке уже есть от ДРУГОЙ модели: по метке `<id>.model` рядом; без метки файл в старой общей папке `trellis/` считается чужим для любой модели,
    кроме trellis2 (и то только по метке — потому «безымянный» файл там не трогаем). Пусто — писать можно."""
    bad = []
    legacy = os.path.basename(os.path.normpath(out)) == 'trellis'
    for jid in job_ids:
        glb = os.path.join(out, jid + '.glb')
        tag = os.path.join(out, jid + '.model')
        if os.path.exists(tag):
            if open(tag, encoding='utf-8').read().strip() != model:
                bad.append(jid)
        elif os.path.exists(glb) and (legacy or os.path.basename(os.path.normpath(out)) != model):
            bad.append(jid)
    return bad


def parse_plan(plan: str) -> list[dict]:
    """`1024:1,1536:1` → [{'res': 1024, 'n': 1}, …]; допустимо 512 / 1024 / 1536 (pipeline_type цепочки TRELLIS.2: 512, 1024_cascade, 1536_cascade)."""
    out = []
    for part in [p for p in plan.split(',') if p.strip()]:
        res, _, n = part.partition(':')
        if int(res) not in (512, 1024, 1536):
            raise ValueError(f'разрешение {res}: допустимы 512, 1024, 1536')
        out.append({'res': int(res), 'n': int(n or 1)})
    return out


def pipeline_type(res: int) -> str:
    return {512: '512', 1024: '1024_cascade', 1536: '1536_cascade'}[res]


def build_jobs(skus: list[str], plan: list[dict], inputs: dict, seed: int = 42) -> list[dict]:
    """Список заданий: для каждого товара — по плану (разрешение × повторов). `inputs` — `inputs.json` (адрес фото, sha вырезки)."""
    jobs = []
    for sku in skus:
        if sku not in inputs or 'input_png_sha256' not in inputs[sku]:
            raise ValueError(f'{sku}: нет вырезки в inputs.json — сперва make_inputs.py')
        for step in plan:
            for k in range(step['n']):
                jobs.append({'sku': sku, 'res': step['res'], 'rep': k, 'seed': seed, 'job_id': f'{sku.replace(":", "_")}-{step["res"]}-{seed}-{k}'})
    return jobs


TEX_MESH_SUFFIX = '.clean2.glb'


def texture_mesh_path(dirpath: str, job: dict, suffix: str = TEX_MESH_SUFFIX) -> str:
    """Готовая форма задания для `--texture-mesh-dir`: `<папка>/<ключ товара>-<разрешение>-<seed>-<n><суффикс>` (имя задания до приписки `-tex`)."""
    return os.path.join(os.path.expanduser(dirpath), job['job_id'] + suffix)


def shape_only_glb(path: str) -> bytes:
    """Форма для покраски: геометрия и развёртка (UV) без вшитых текстур — покраске нужны только они, а тело запроса воркера ограничено 40 МБ (форма с двумя текстурами 2048² и 477 тыс. граней — 23 МБ, в base64 ≈ 31 МБ).
    UV сохраняются как есть: покраска берёт их, если они есть, и сама разворачивает форму, если их нет (`trellis2_texturing.py`). Нет trimesh или форма не читается — отдаём файл как есть."""
    raw = open(os.path.expanduser(path), 'rb').read()
    try:
        import io

        import trimesh
        sc = trimesh.load(io.BytesIO(raw), file_type='glb', force='scene')
        geoms = list(sc.geometry.values())
        if len(geoms) != 1:
            return raw
        g = geoms[0]
        uv = getattr(g.visual, 'uv', None)
        g.visual = trimesh.visual.TextureVisuals(uv=uv) if uv is not None else trimesh.visual.ColorVisuals()
        out = sc.export(file_type='glb')
        return out if len(out) < len(raw) else raw
    except Exception as e:  # noqa: BLE001 — запасной путь: файл как есть
        say('форма без текстур не собрана, уходит как есть:', str(e)[:120])
        return raw


def parse_tex_variant(tok: str) -> dict | None:
    """pixal3d-tex: вариант прогона `<align>[+g<сила>][+s<повторов>]`: `fit+g3` — подгонка фото и сила направляющей 3 (по умолчанию 1), `fit+s40` — латент формы по копии,
    сглаженной 40 проходами Тобина (краска ложится на настоящую форму). Неверная запись → None."""
    parts = tok.strip().split('+')
    if parts[0] not in TEX_ALIGNS:
        return None
    v = {'tok': tok.strip(), 'align': parts[0], 'guidance': 1.0, 'smooth': 0}
    for q in parts[1:]:
        try:
            if q[:1] == 'g' and 0 < float(q[1:]) <= 10:
                v['guidance'] = float(q[1:])
            elif q[:1] == 's' and 0 < int(q[1:]) <= 500:
                v['smooth'] = int(q[1:])
            else:
                return None
        except ValueError:
            return None
    return v


def expand_align_jobs(jobs: list[dict], variants: list[dict]) -> list[dict]:
    """pixal3d-tex: по заданию на каждый вариант; вариантов несколько — id получает суффикс варианта (`…-fit`, `…-fit-g3`), один — id как был."""
    return [dict(j, job_id=f'{j["job_id"]}-{v["tok"].replace("+", "-")}' if len(variants) > 1 else j['job_id'], align=v['align'], tex_guidance=v['guidance'], shape_smooth=v['smooth'])
            for j in jobs for v in variants]


def price_usd_h(tier: str) -> float | None:
    """Цена 4090 по тарифу из `rules/salad-groups.json` (`prices_by_class_usd_h`); нет — None (деньги без цены не считаем)."""
    try:
        d = json.load(open(os.path.join(SCOUT, 'rules', 'salad-groups.json'), encoding='utf-8'))
        return float(d['prices_by_class_usd_h'][CARD['class_name']][tier])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def parse_live_price(items: list, class_name: str, tier: str) -> float | None:
    """Живая цена класса карты и тарифа из ответа Salad `GET /gpu-classes` (`items[].prices[]`: priority, price); нет — None."""
    for c in items or []:
        if c.get('name') == class_name:
            for x in c.get('prices') or []:
                if str(x.get('priority')).lower() == tier:
                    try:
                        return float(x['price'])
                    except (KeyError, TypeError, ValueError):
                        return None
    return None


def live_price_usd_h(MG, class_name: str, tier: str) -> float | None:
    """ЖИВАЯ цена из Salad (19.11: 4090 high $0,44, а снимок в `rules/salad-groups.json` от 24.10 говорил $0,33 — траты занижались на треть). Нет ответа — None (берём снимок)."""
    try:
        import urllib.request
        url = MG.API.split('/projects/')[0] + '/gpu-classes'
        req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return parse_live_price(json.loads(r.read()).get('items') or [], class_name, tier)
    except Exception:  # noqa: BLE001 — нет сети/ключа/формата: запасной путь — снимок
        return None


def cost_usd(running_s: float, price: float, reserve_s: float = 60.0) -> float:
    """Начисления по времени `running` + запас на отставание счёта (платим с момента running, ADR-0135)."""
    return max(0.0, running_s + (reserve_s if running_s > 0 else 0.0)) / 3600.0 * price


# TRELLIS.2 писан под transformers 4.x (`DINOv3ViTModel.layer`); в образе без пина встал 5.20.2 → AttributeError (шаг 0, s0e). Пока образ не пересобран с пином,
# версия ставится при старте контейнера (с повторами; 4.56.* — первая с DINOv3, `.layer` проверен по исходникам v4.56.0/4.56.2/4.57.0)
TRELLIS_PIP_PIN = "transformers==4.56.2"


def worker_command(path: str | None = None, python: str = 'python', pre: str = '') -> tuple[list[str], str]:
    """Код воркера → (command, сжатый код) для боевого образа: `python -u -c "exec(zlib+base64 из env TRIAL_WORKER_Z)"` — как боевые группы
    несут свой код в `command`; образ не пересобирается. Код едет переменной окружения (≈ 3 КБ после сжатия), а не в аргументе."""
    import zlib
    src = open(path or os.path.join(HERE, 'worker_trellis.py'), 'rb').read()
    z = base64.b64encode(zlib.compress(src, 9)).decode()
    code = "import base64,os,zlib;exec(zlib.decompress(base64.b64decode(os.environ['TRIAL_WORKER_Z'])).decode())"
    if pre:        # сперва подготовка (pip с повторами), затем воркер процессом-заменой (exec), чтобы сигналы и код выхода шли воркеру
        return ['bash', '-c', f'{pre}\nexec {python} -u -c "$0"', code], z
    return [python, '-u', '-c', code], z


def build_body(name: str, image: str, tier: str, model: str, hf_token: str, cpu: int, mem_mb: int, run_note: str, auth: dict, donor: dict | None = None) -> dict:
    """Тело группы Salad. `auth` — доступ к приватному реестру (`migrate_groups.ghcr_auth()`); приёмника на проде (`MESH_SINK_*`) в окружении НЕТ.
    `donor` (только hunyuan21) — боевая группа-образец: берём её переменные окружения (STAGED, PIPELINE_VERSION, …) БЕЗ секретов приёмника и очереди."""
    env = {'MODEL': model, 'IMAGE_NOTE': run_note, 'HF_TOKEN': hf_token, 'HF_HOME': '/data/hf', 'OUT_DIR': '/data/out',
           'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261118-{name}'}
    res = {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [CARD['class_id']], 'storage_amount': 80 * 2 ** 30, 'shm_size': 1024}      # 80 ГиБ: кэш HF ≈ 42 ГиБ + запас на 30 результатов (директор 19.11)
    command = None
    if donor is None and model in ('pixal3d', 'pixal3d-tex'):        # образ Pixal3D: transformers 4.57.3 требует huggingface-hub <1.0, а в образе оказался 2.4.0 (px0, 19.11: ImportError на прогреве) — пин при старте, пересборка не нужна
        pre = ('for i in 1 2 3; do python3 -m pip install -q "huggingface_hub==0.35.3" && break; echo "[pip] попытка $i не удалась"; sleep 5; done; '
               'python3 -m pip list 2>/dev/null | grep -i -E "^(transformers|huggingface|tokenizers|safetensors|torch|diffusers|natten) " | tr -s " " | tr "\\n" ";"; echo')
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3', pre=pre)
        if model == 'pixal3d':      # px2 (19.11): CUDA out of memory в декодере текстуры на 24 ГБ — меньше фрагментации и меньше токенов
            env['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
            env['PIXAL3D_MAX_TOKENS'] = '32768'
    elif donor is None and model == 'localmesh':        # образ LocalMesh (py3.12, transformers 5.x, hub 1.x) — свои версии, pip-пины не нужны
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3')
    elif donor is None:      # TRELLIS.2: образ уже содержит воркер, но актуальный код едет через command — без пересборки образа (python3 в образе, `python` нет)
        pre = (f'for i in 1 2 3; do python3 -m pip install -q "{TRELLIS_PIP_PIN}" && break; echo "[pip] попытка $i не удалась"; sleep 5; done; '
               f'python3 -m pip list 2>/dev/null | grep -i -E "^(transformers|huggingface|tokenizers|safetensors|torch|trimesh|timm|kornia|numpy) " | tr -s " " | tr "\\n" ";"; echo')
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3', pre=pre)
    if donor is not None:
        denv = (donor.get('container') or {}).get('environment_variables') or {}
        env = {k: v for k, v in denv.items() if not k.startswith(('MESH_SINK', 'QUEUE')) and k not in ('STORAGE_BACKEND', 'DEPLOYMENT_EPOCH')}
        env.update({'MODEL': model, 'IMAGE_NOTE': run_note, 'OUT_DIR': '/tmp/trial-out', 'DEPLOYMENT_EPOCH': f'20261118-{name}'})
        command, env['TRIAL_WORKER_Z'] = worker_command()
        dres = donor['container']['resources']
        res = {'cpu': dres.get('cpu', cpu), 'memory': dres.get('memory', mem_mb), 'gpu_classes': [CARD['class_id']],
               'storage_amount': dres.get('storage_amount', 60 * 2 ** 30), 'shm_size': dres.get('shm_size', 1024)}
    body = {
        'name': name, 'display_name': name,
        'container': {
            'image': image,
            'resources': res,
            'priority': tier, 'environment_variables': env, 'image_caching': True, 'registry_authentication': auth,
        },
        'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': tier, 'country_codes': [],
        'networking': {'protocol': 'http', 'port': PORT, 'auth': True, 'load_balancer': 'round_robin', 'single_connection_limit': False,
                       'client_request_timeout': 100000, 'server_response_timeout': 100000},
        'readiness_probe': READINESS, 'startup_probe': STARTUP,
    }
    if command:
        body['container']['command'] = command
    return body


def safe_print(body: dict) -> None:
    b = json.loads(json.dumps(body))
    b['container'].pop('registry_authentication', None)
    for k in list(b['container']['environment_variables']):
        if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            b['container']['environment_variables'][k] = '<скрыто>'
        elif k == 'TRIAL_WORKER_Z':
            b['container']['environment_variables'][k] = f'<код воркера, {len(b["container"]["environment_variables"][k])} знаков>'
    print(json.dumps(b, ensure_ascii=False, indent=1))


class Gateway:
    """HTTP к ноде через шлюз группы (`https://<dns>`) с ключом Salad. Всё — с таймаутами и без падения на сетевых сбоях (код -1)."""

    def __init__(self, base: str, key: str):
        self.base, self.key = base.rstrip('/'), key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 60, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            'Salad-Api-Key': self.key, 'User-Agent': 'remlab-mesh/1.0', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else {}))
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, (b if raw else json.loads(b))
            except ValueError:
                return e.code, {'detail': b[:200].decode(errors='replace')}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return -1, {}


def run(a, MG, BR, gw_factory=Gateway, sleep=time.sleep, clock=time.time, hf_head=None) -> int:
    """Весь замер. `MG` — `migrate_groups` (API Salad), `BR` — `bench_run` (состояние группы, остановка с проверкой). Подмена обоих + `gw_factory`/`sleep`/`clock`/`hf_head` — тесты."""
    inputs = json.load(open(os.path.join(a.inputs, 'inputs.json'), encoding='utf-8'))
    skus = a.skus or [k for k, v in inputs.items() if isinstance(v, dict) and v.get('input_png_sha256')]      # без --skus — весь набор из inputs.json (30 товаров)
    jobs = build_jobs(skus, parse_plan(a.plan), inputs, a.seed)
    name = f'trial-{a.model}-{a.suffix}'
    if not a.out:
        a.out = default_out(a.model)
    clash = owner_conflicts(a.out, [j['job_id'] for j in jobs], a.model) if not getattr(a, 'force_out', False) else []
    if clash:                                             # отказ ДО группы и денег: чужой результат под тем же именем затёрт не будет
        say(f'ОТКАЗ: в {a.out} уже лежат файлы от другой модели для {len(clash)} заданий (первое: {clash[0]}) — укажи свою --out или --force-out')
        return 2
    aligns = [parse_tex_variant(x) for x in (getattr(a, 'tex_align', None) or 'fit').split(',') if x.strip()]
    if a.model == 'pixal3d-tex':                          # краска Pixal3D по готовой форме: без формы работать нечему — отказ ДО группы и денег
        if not getattr(a, 'texture_mesh', None):
            say('pixal3d-tex красит готовую форму: укажите --texture-mesh <clean.glb> — группа не создаётся')
            return 2
        if len(skus) != 1 or not aligns or any(x is None for x in aligns):
            say(f'pixal3d-tex: один товар в --skus (форма одна) и --tex-align из {TEX_ALIGNS} с добавками +g<сила>, +s<проходов> (например fit+g3) — группа не создаётся')
            return 2
    MG.env_from_file()
    card = getattr(a, 'card', None) or CARD['class_name']
    if card != CARD['class_name']:                        # другая карта (localmesh — 4060 Ti 16 ГБ): id по полному имени среди классов организации
        import recreate_group as RG
        try:
            cid = RG.pick_gpu_exact(RG.gpu_classes(), [card])[0]
        except (ValueError, IndexError) as e:
            say('карта', card, 'не найдена среди классов организации:', str(e)[:200])
            return 2
        CARD.update(class_name=card, class_id=cid)
    price = live_price_usd_h(MG, CARD['class_name'], a.tier)                  # живая цена Salad; снимок — только запасной
    price_src = 'живая (Salad gpu-classes)'
    if price is None:
        price, price_src = price_usd_h(a.tier), 'СНИМОК rules/salad-groups.json (живая цена недоступна)'
    hf = os.environ.get('HF_TOKEN', '')
    donor = None
    if a.model == 'hunyuan21':                            # контроль: боевой образ и ресурсы берём у боевой группы-образца (в ней нет нашего кода — он едет в command)
        code, donor = MG.api(f'/{a.donor}')
        if code != 200 or 'container' not in donor:
            say(f'группа-образец {a.donor} не прочитана: HTTP {code} — стоп')
            return 2
        a.image = a.image or donor['container']['image']
        hf = ''                                           # веса вшиты в образ, токен Hugging Face контролю не нужен
    meta = {}
    sp = a.set or os.path.join(os.path.dirname(os.path.abspath(a.inputs)), 'set30.json')
    if os.path.exists(sp):
        meta = {c['sku']: c for c in json.load(open(sp, encoding='utf-8'))}                       # роль и габариты (нужны контролю Hunyuan)
    tex_mesh_b64 = None
    if getattr(a, 'texture_mesh', None):                  # контроль перекраски: одна готовая форма (GLB) уходит в задание, id задания с суффиксом -tex
        tex_mesh_b64 = base64.b64encode(open(os.path.expanduser(a.texture_mesh), 'rb').read()).decode()
        for j in jobs:
            j['job_id'] += '-tex'
    if getattr(a, 'texture_mesh_dir', None):              # контроль «родная краска TRELLIS.2 на ТЕХ ЖЕ формах» (T-20261118-91/9): у каждого товара своя готовая форма из папки
        if a.model != 'trellis2' or getattr(a, 'texture_mesh', None):
            say('--texture-mesh-dir — только для --model trellis2 и без --texture-mesh — группа не создаётся')
            return 2
        miss = []
        for j in jobs:
            j['tex_mesh'] = texture_mesh_path(a.texture_mesh_dir, j, getattr(a, 'texture_mesh_suffix', None) or TEX_MESH_SUFFIX)
            if not os.path.exists(j['tex_mesh']):
                miss.append(j['tex_mesh'])
        if miss:                                          # отказ ДО группы и денег: форма нужна каждому заданию
            say(f'ОТКАЗ: нет готовой формы для {len(miss)} заданий (первая: {miss[0]}) — группа не создаётся')
            return 2
        for j in jobs:
            j['job_id'] += '-tex'
    if a.model == 'pixal3d-tex':                          # варианты кадрирования фото (fit — подгонка по силуэту формы, official — как в апстриме): по заданию на вариант, id с суффиксом
        jobs = expand_align_jobs(jobs, aligns)
    for j in jobs:
        j['role'] = (inputs.get(j['sku']) or {}).get('role') or meta.get(j['sku'], {}).get('role')
        j['dims_cm'] = meta.get(j['sku'], {}).get('dims_cm')
    body = build_body(name, a.image, a.tier, a.model, hf, a.cpu, a.mem_mb, a.image.split('@')[-1][:19], MG.ghcr_auth(), donor)
    say('группа', name, CARD['class_name'], 'тариф', a.tier, 'цена $/ч', price, f'[{price_src}]', 'заданий', len(jobs), 'потолок $', a.cap)
    if not a.apply:
        safe_print(body)
        for j in jobs:
            print('  задание', j['job_id'])
        return 0
    if price is None:
        say('цены группы нет в rules/salad-groups.json — стоп (деньги без цены не считаем)')
        return 2
    gated = HF_GATED.get(a.model)
    if gated:                                           # БЕСПЛАТНО, до создания группы
        if hf_head is None:
            import hf_access
            hf_head = hf_access.head
        code = hf_head(gated, hf) if hf else 0
        say('проверка закрытых весов', gated.split('/resolve')[0], '→ HTTP', code or 'нет HF_TOKEN')
        if code not in (200, 302):
            say('закрытые веса недоступны — группу НЕ создаю, денег не потрачено')
            return 3
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None)
            and not g['name'].startswith(('mesh-', 'render-', 'trial-'))]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    code, g = MG.api(f'/{name}')
    if code == 200:
        say(f'группа {name} уже есть ({(g.get("current_state") or {}).get("status")}) — не пересоздаю молча (другая --suffix)')
        return 2
    code, resp = MG.api('', 'POST', body)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return 1
    ok_stop = False
    summary = {'group': name, 'model': a.model, 'image': a.image, 'tier': a.tier, 'price_usd_h': price, 'cap_usd': a.cap, 'jobs': [], 'failed': 0,
               'stop_verified': False, 'stopped_by': None}
    os.makedirs(a.out, exist_ok=True)
    t_start = run_since = None
    try:
        for _ in range(120):                              # создание группы Salad иногда идёт 2–10 минут
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            sleep(5)
        t_start = clock()
        code, _ = MG.api(f'/{name}/start', 'POST')
        say('start HTTP', code)
        gw, ready_at, fail_streak = None, None, 0
        ever_ok, last_gb, last_gb_t, last_say = False, None, None, 0.0           # видимость воркера: был ли хоть один ответ /health, рост докачки весов
        pending = list(jobs)
        inflight = None
        while True:
            t = clock()
            _, st, cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                summary['to_first_running_s'] = round(t - t_start, 1)
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            running_s = (t - run_since) if run_since is not None else 0.0
            cost = cost_usd(running_s, price)
            summary['cost_usd_est'] = round(cost, 3)
            if cost >= a.cap:
                say(f'!! ПОТОЛОК ДЕНЕГ: ≈${cost:.2f} ≥ ${a.cap} — гашу')
                summary['stopped_by'] = 'money'
                break
            if run_since is not None and running_s > a.max_min * 60:
                say(f'!! предел времени {a.max_min} мин — гашу')
                summary['stopped_by'] = 'time'
                break
            if run_since is None and (t - t_start) > 3600:
                say('!! за час нода не вышла в running — гашу (платили 0)')
                summary['stopped_by'] = 'no_machine'
                break
            if run_since is not None and gw is None:
                g2 = MG.api(f'/{name}')[1]
                dns = ((g2.get('networking') or {}).get('dns') or '')
                if dns:
                    gw = gw_factory(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    say('шлюз группы получен')
            if gw is not None and ready_at is None:
                c, h = gw.call('GET', '/health', timeout=20)
                if c == 200:
                    ever_ok = True
                    summary['health'] = h
                    if h.get('error') or h.get('phase') in ('failed', 'child_dead'):
                        say('!! прогрев упал:', h.get('error'), f'(фаза {h.get("phase")}, ребёнок {h.get("child")}, память группы {h.get("cgroup_gb")}) — гашу')
                        summary['stopped_by'] = 'warm_failed'
                        break
                    gb = (h.get('progress') or {}).get('hf_gb')
                    cpu = (h.get('child') or {}).get('cpu_s')
                    mark = (gb, None if cpu is None else int(cpu // 20))       # «живой» ход: растёт кэш весов ИЛИ ребёнок жжёт процессор (строит модель)
                    if gb is not None and mark != last_gb:
                        last_gb, last_gb_t = mark, t
                    free = ((h.get('disk_gb') or {}).get('hf') or {}).get('free')
                    summary['disk_free_gb_min'] = free if free is None else min(free, summary.get('disk_free_gb_min', free))
                    if free is not None and free < a.disk_min_gb:
                        say(f'!! на диске контейнера осталось {free} ГиБ < {a.disk_min_gb} — гашу (кэш весов + результаты не помещаются)')
                        summary['stopped_by'] = 'disk_low'
                        break
                    if t - last_say >= 120 and not h.get('warm'):
                        last_say = t
                        say(f'прогрев: фаза {h.get("phase")}, в кэше HF {gb} ГБ, диск {h.get("disk_gb")}, ребёнок {h.get("child")}')
                    if h.get('phase') == 'weights' and last_gb_t is not None and t - last_gb_t > a.stall_min * 60:
                        say(f'!! загрузка стоит {a.stall_min} мин (кэш {gb} ГБ не растёт, процессор ребёнка {cpu} с не растёт) — гашу')
                        summary['stopped_by'] = 'download_stalled'
                        break
                    if h.get('warm'):
                        ready_at = t
                        summary['to_ready_s'] = round(t - t_start, 1)
                        summary['timings'] = h.get('timings')
                        c2, info = gw.call('GET', '/info', timeout=30)
                        summary['info'] = info if c2 == 200 else None
                        say(f'нода готова: t+{t - t_start:.0f} с от /start', (summary.get('info') or {}).get('gpu'))
                if run_since is not None and not ever_ok and running_s > a.health_min * 60:
                    say(f'!! {a.health_min} мин после running воркер не отвечает на /health — гашу (процесс мёртв или недоступен)')
                    summary['stopped_by'] = 'no_health'
                    break
                if run_since is not None and ready_at is None and running_s > a.ready_min * 60:
                    say(f'!! {a.ready_min} мин после running модель не прогрелась — гашу')
                    summary['stopped_by'] = 'not_ready'
                    break
            if ready_at is not None:
                if inflight is None and pending:
                    j = pending.pop(0)
                    png = open(os.path.join(a.inputs, f'{j["sku"].replace(":", "_")}.rgba.png'), 'rb').read()
                    pl = {'job_id': j['job_id'], 'image_b64': base64.b64encode(png).decode(), 'pipeline_type': pipeline_type(j['res']), 'seed': j['seed'],
                          'decimation_target': a.decimation, 'texture_size': a.texture, 'detail': getattr(a, 'detail', None),
                          'texture_mesh_b64': base64.b64encode(shape_only_glb(j['tex_mesh'])).decode() if j.get('tex_mesh') else tex_mesh_b64, 'role': j.get('role'), 'dims_cm': j.get('dims_cm'), 'align': j.get('align'), 'tex_guidance': j.get('tex_guidance'), 'shape_smooth': j.get('shape_smooth')}
                    c, r = gw.call('POST', '/generate', pl, timeout=90)
                    inflight = {**j, 'submitted': t, 'http': c}
                    say('задание', j['job_id'], '→ HTTP', c)
                    if c not in (202, 409):
                        inflight.update(status='failed', error=f'POST {c} {str(r)[:120]}')
                elif inflight is not None:
                    if inflight.get('status') != 'failed':
                        c, r = gw.call('GET', '/job/' + inflight['job_id'], timeout=30)
                        if c == 200 and r.get('status') in ('done', 'failed'):
                            inflight.update(status=r['status'], metrics=r.get('metrics'), error=r.get('error'), trace=r.get('trace'))
                            if r['status'] == 'done':
                                cg, glb = gw.call('GET', '/glb/' + inflight['job_id'], timeout=300, raw=True)
                                if cg == 200:
                                    fp = os.path.join(a.out, inflight['job_id'] + '.glb')
                                    open(fp, 'wb').write(glb)
                                    open(fp[:-4] + '.model', 'w', encoding='utf-8').write(a.model)
                                    inflight['glb_path'] = fp
                                    inflight['glb_bytes'] = len(glb)
                                    if (r.get('metrics') or {}).get('has_ai'):          # localmesh: вторая версия — текстура «как нарисовала модель», до проекции фото
                                        ca, glb_ai = gw.call('GET', '/glb/' + inflight['job_id'] + '?v=ai', timeout=300, raw=True)
                                        if ca == 200:
                                            fp_ai = os.path.join(a.out, inflight['job_id'] + '.ai.glb')
                                            open(fp_ai, 'wb').write(glb_ai)
                                            inflight['glb_ai_path'] = fp_ai
                                else:
                                    inflight.update(status='failed', error=f'GLB не скачался: HTTP {cg}')
                        elif t - inflight['submitted'] > a.job_timeout * 60:
                            inflight.update(status='failed', error=f'задание не закончилось за {a.job_timeout} мин')
                    if inflight.get('status') in ('done', 'failed'):
                        inflight['seconds'] = round(t - inflight['submitted'], 1)
                        summary['jobs'].append(inflight)
                        fail_streak = fail_streak + 1 if inflight['status'] == 'failed' else 0
                        summary['failed'] += inflight['status'] == 'failed'
                        say('задание', inflight['job_id'], inflight['status'], inflight.get('error') or '', f'{inflight["seconds"]} с')
                        inflight = None
                        if fail_streak >= a.fail_streak:
                            say(f'!! {a.fail_streak} задания подряд упали — гашу (чинить в коде, не жечь деньги)')
                            summary['stopped_by'] = 'failures'
                            break
                if inflight is None and not pending:
                    summary['stopped_by'] = 'done'
                    break
            sleep(10)
    finally:
        ok_stop = BR.stop_and_verify(name)
        summary['stop_verified'] = ok_stop
        summary['running_s'] = round((clock() - run_since), 1) if run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] == 'done' else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='trellis2', choices=['trellis2', 'pixal3d', 'pixal3d-tex', 'localmesh', 'hunyuan21'])
    ap.add_argument('--donor', default='mesh-q-low-1', help='hunyuan21: боевая группа-образец (образ, ресурсы, env без секретов приёмника)')
    ap.add_argument('--set', default=None, help='JSON набора (роль, габариты); по умолчанию set30.json рядом с папкой inputs')
    ap.add_argument('--fail-streak', type=int, default=NO_FAIL_STREAK, help='сколько упавших заданий подряд гасят замер (контролю Hunyuan — больше: боевые ворота брака)')
    ap.add_argument('--image', help='образ группы: тег или digest в ghcr.io/igortsk123/mesh-hunyuan')
    ap.add_argument('--inputs', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis/inputs30'))
    ap.add_argument('--skus', nargs='*', default=[])
    ap.add_argument('--plan', default='1024:1', help='разрешения × повторов: 1024:1,1536:1')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--decimation', type=int, default=500000)
    ap.add_argument('--texture', type=int, default=2048)
    ap.add_argument('--card', default=CARD['class_name'], help='класс карты по полному имени ("RTX 4060 Ti (16 GB)" для localmesh)')
    ap.add_argument('--detail', default='high', choices=['draft', 'standard', 'high', 'max'], help='localmesh: ярус качества (high = форма 1024, 16 шагов, 250 тыс. граней)')
    ap.add_argument('--texture-mesh', default=None, help='контроль: готовая форма (GLB) — TRELLIS.2 только перекрасит её по фото (один товар в --skus)')
    ap.add_argument('--texture-mesh-dir', default=None, help='контроль «родная краска TRELLIS.2 на тех же формах»: папка готовых форм, у каждого товара своя (<ключ>-<разрешение>-<seed>-<n><суффикс>); много товаров — одна группа')
    ap.add_argument('--texture-mesh-suffix', default=None, help=f'суффикс файла формы в --texture-mesh-dir (по умолчанию {TEX_MESH_SUFFIX})')
    ap.add_argument('--tex-align', default='fit', help='pixal3d-tex: варианты через запятую, по заданию на вариант: fit (подгонка фото по силуэту формы), official (как в апстриме Pixal3D); добавки: +g<сила направляющей, по умолчанию 1>, +s<проходов сглаживания формы для латента>; пример: fit,official,fit+g3,fit+s60')
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=32768)
    ap.add_argument('--cap', type=float, default=2.0, help='потолок денег на ОДИН запуск (одну модель), $ — владелец TG 2064: $2 на модель, $10 на всю пробу')
    ap.add_argument('--max-min', type=int, default=180)
    ap.add_argument('--ready-min', type=int, default=75, help='сколько минут после running ждать прогрева модели (холодный старт с докачкой весов — часть результата пробы)')
    ap.add_argument('--health-min', type=int, default=20, help='сколько минут после running ждать ПЕРВОГО ответа /health, иначе стоп (воркер мёртв)')
    ap.add_argument('--disk-min-gb', type=float, default=3.0, help='стоп, если свободного места на диске контейнера меньше, ГиБ')
    ap.add_argument('--stall-min', type=int, default=10, help='сколько минут докачка весов может не расти, иначе стоп')
    ap.add_argument('--job-timeout', type=int, default=15)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=None, help='папка результатов; по умолчанию — ~/remlab-logs/mesh-models-1118/<модель>/')
    ap.add_argument('--force-out', action='store_true', help='писать, даже если там лежат файлы от другой модели (не нужно)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if BR.stop_and_verify(f'trial-{a.model}-{a.suffix}') else 1
    if not a.image and a.model != 'hunyuan21':            # контролю образ берётся у боевой группы-образца
        sys.exit('нужен --image')
    if a.image and '@' not in a.image and ':' not in a.image:
        sys.exit('--image: тег или digest с именем репозитория')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
