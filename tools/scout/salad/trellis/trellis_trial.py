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
            'localmesh': 'facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json',
            'mvpainter': 'shaomq/MVPainter/resolve/main/model_index.json'}      # mvpainter: веса открытые, но проверка бесплатна и ловит исчезнувший репозиторий до создания группы      # закрытые веса, без которых модель не поднимется
PORT = 8000
READINESS = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},      # НЕ /ready: пока проба не пройдена, шлюз отдаёт 503 на любой путь и прогрев не виден (урок шага 0, 18.11)
             'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3}
STARTUP = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},
           'initial_delay_seconds': 10, 'period_seconds': 60, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 20}   # API Salad: failure_threshold ≤ 20 (400 от 18.11) → 20 мин на докачку весов
NO_FAIL_STREAK = 2
TEX_ALIGNS = ('fit', 'official')      # pixal3d-tex: как кадрировать фото под форму (`worker_trellis.texture_on_shape`)
WENV_MODELS = ('pixal3d-tex', 'mvadapter-i2tex', 'mvpainter', 'supratex')      # модели, которым можно передать окружение воркера (`--worker-env`, `--debug-cuda`)
MV_YAWS = ('auto', '0', '90', '180', '270')           # mvadapter-i2tex, mvpainter: поворот формы к виду 0 — по силуэту фото или задан руками
MV_UV_SIZES = (1024, 2048, 4096)
SUPRA_TEX_SIZES = (1024, 2048, 4096)                  # supratex: размер текстуры выпуска (по умолчанию 4096, как в апстриме)
SUPRA_MEM_MB = 49152                                  # supratex: пик памяти процессов ≈ 32,4 ГиБ (замер апстрима на 3090) — 32768 МБ группы впритык; 48 ГиБ (лимит Salad 61440)
MODEL_MEM_MB = {'supratex': SUPRA_MEM_MB}             # память группы по умолчанию для моделей, которым общих 32768 МБ мало
TEXTURE_MODELS = {'mvadapter-i2tex': '-mvtex', 'mvpainter': '-mvp', 'supratex': '-supra', 'pixal3d-tex': '-tex', 'trellis2': '-tex'}      # модели «краска готовой формы» и суффикс id задания (результат — `<id>.glb`)
GPU_TIERS = ('high', 'medium', 'low', 'batch')        # тарифы Salad от дорогого к дешёвому; запасной порядок выбора класса — по ним
MVP_DEFAULT_GPU = 'RTX 5090 (32 GB)'                  # mvpainter по умолчанию (директор 19.11): 4090 (24 ГБ) может не вместить; 4090 — только явным `--gpu "RTX 4090 (24 GB)"` / `--card`
CREATE_WAIT_MIN = 30                                  # сколько минут ждать `stopped` после создания группы (параметр `--create-wait-min`)
START_RETRIES = 5                                     # повторов `/start` при коде ≥ 300
START_RETRY_S = 30                                    # пауза между попытками /start, секунд
GPU_MIN_GB = 40                                       # запасной путь: классы от 40 ГБ видеопамяти (по умолчанию — 4090; у mvpainter с чекпойнтом на процессор, issue #13)
LIVE_PRICES: dict = {}                                # (имя класса, тариф) → $/ч из API Salad (`fetch_gpu_items`); деньги считаем по ним, снимок `rules/salad-groups.json` — только если API молчит


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


DEBUG_CUDA_ENV = {'CUDA_LAUNCH_BLOCKING': '1', 'TORCH_SHOW_CPP_STACKTRACES': '1'}      # отладка CUDA: синхронные запуски ядер (ошибка — на своей строке) и стеки C++; медленнее — по умолчанию выключено


def parse_worker_env(items: list[str] | None, debug_cuda: bool = False) -> dict | None:
    """pixal3d-tex, mvadapter-i2tex и mvpainter: переменные окружения воркера из `--worker-env ИМЯ=ЗНАЧЕНИЕ` (повтор) и `--debug-cuda`. Допустимы только `PIXTEX_*`, `MVTEX_*`, `MVP_*`, `CUDA_LAUNCH_BLOCKING` и `TORCH_SHOW_CPP_STACKTRACES`
    (секреты и чужие переменные через флаг не пройдут). Ошибка в записи → None."""
    import re
    env = dict(DEBUG_CUDA_ENV) if debug_cuda else {}
    for it in items or []:
        m = re.fullmatch(r'((?:PIXTEX|MVTEX|MVP)_[A-Z0-9_]+|CUDA_LAUNCH_BLOCKING|TORCH_SHOW_CPP_STACKTRACES)=([A-Za-z0-9_:,.+\-]*)', it.strip())
        if not m:
            return None
        env[m.group(1)] = m.group(2)
    return env


def mv_options(a) -> dict | None:
    """mvadapter-i2tex: параметры задания из аргументов (`--mv-yaw`, `--mv-uv-size`, `--mv-steps`, `--mv-ref-scale`); неверное значение → None (отказ ДО группы и денег)."""
    yaw = str(getattr(a, 'mv_yaw', 'auto') or 'auto')
    uv = int(getattr(a, 'mv_uv_size', None) if getattr(a, 'mv_uv_size', None) is not None else 4096)
    steps = int(getattr(a, 'mv_steps', None) if getattr(a, 'mv_steps', None) is not None else 50)
    ref = float(getattr(a, 'mv_ref_scale', 1.0) if getattr(a, 'mv_ref_scale', None) is not None else 1.0)
    if yaw not in MV_YAWS or uv not in MV_UV_SIZES or not 1 <= steps <= 100 or not 0 <= ref <= 2:
        return None
    return {'mv_yaw': yaw, 'mv_uv_size': uv, 'mv_steps': steps, 'mv_ref_scale': ref}


def mvp_options(a) -> dict | None:
    """mvpainter: параметры задания (`--mvp-yaw`, `--mvp-steps`, `--mvp-reduce`, `--mvp-pbr`); неверное значение → None (отказ ДО группы и денег). `--mvp-reduce 1` — штатное упрощение до 30 тыс. вершин (по умолчанию),
    `0` — не упрощать (дольше и тяжелее); `--mvp-pbr 1` — PBR через IDArb (по умолчанию), `0` — только базовый цвет."""
    yaw = str(getattr(a, 'mvp_yaw', 'auto') or 'auto')
    steps = getattr(a, 'mvp_steps', None)
    steps = 75 if steps is None else int(steps)
    red, pbr = str(getattr(a, 'mvp_reduce', '1')), str(getattr(a, 'mvp_pbr', '1'))
    if yaw not in MV_YAWS or not 1 <= steps <= 150 or red not in ('0', '1') or pbr not in ('0', '1'):
        return None
    return {'mvp_yaw': yaw, 'mvp_steps': steps, 'mvp_reduce': int(red), 'mvp_pbr': int(pbr)}

def supra_options(a) -> dict | None:
    """supratex: параметры задания из аргументов (`--supra-refine`, `--supra-texture-size`, `--supra-decimation`); неверное значение → None (отказ ДО группы и денег)."""
    ts = int(getattr(a, 'supra_texture_size', None) if getattr(a, 'supra_texture_size', None) is not None else 4096)
    dec = int(getattr(a, 'supra_decimation', None) if getattr(a, 'supra_decimation', None) is not None else 500000)
    if ts not in SUPRA_TEX_SIZES or not 10000 <= dec <= 2000000:
        return None
    return {'supra_refine': bool(getattr(a, 'supra_refine', False)), 'supra_texture_size': ts, 'supra_decimation': dec}


def expand_align_jobs(jobs: list[dict], variants: list[dict]) -> list[dict]:
    """pixal3d-tex: по заданию на каждый вариант; вариантов несколько — id получает суффикс варианта (`…-fit`, `…-fit-g3`), один — id как был."""
    return [dict(j, job_id=f'{j["job_id"]}-{v["tok"].replace("+", "-")}' if len(variants) > 1 else j['job_id'], align=v['align'], tex_guidance=v['guidance'], shape_smooth=v['smooth'])
            for j in jobs for v in variants]


def price_usd_h(tier: str) -> float | None:
    """ЗАПАСНАЯ цена выбранного класса карты по тарифу — снимок `rules/salad-groups.json` (`prices_by_class_usd_h`, 24.10; занижает). Основной путь денег — `live_price_usd_h`; сюда падаем, только если Salad не ответил."""
    try:
        d = json.load(open(os.path.join(SCOUT, 'rules', 'salad-groups.json'), encoding='utf-8'))
        return float(d['prices_by_class_usd_h'][CARD['class_name']][tier])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def gpu_memory_gb(name: str) -> int | None:
    """Видеопамять из имени класса Salad: «RTX 4090 (24 GB)» → 24; не разобрать — None."""
    import re
    m = re.search(r'\((\d+)\s*GB\)', name or '')
    return int(m.group(1)) if m else None


def fetch_gpu_items(MG, fetch=None) -> list[dict] | None:
    """Все классы карт организации с ценами по тарифам (API Salad `gpu-classes`: id, name, prices[{priority, price}]) — через ключ из `MG.env_from_file()` и тот же адрес, что у `recreate_group.gpu_classes`.
    Сбой сети/ключа → None (дальше — запасная таблица из rules). Заодно кладёт цены в `LIVE_PRICES`. `fetch` — подмена в тестах: () → список классов."""
    try:
        if fetch is None:
            url = MG.API.split('/projects/')[0] + '/gpu-classes'
            req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r:
                items = json.loads(r.read()).get('items') or []
        else:
            items = fetch()
    except Exception as e:  # noqa: BLE001 — нет сети/ключа: не роняем сухой прогон
        say('gpu-classes: API не ответил:', type(e).__name__, str(e)[:100])
        return None
    for c in items:
        for x in c.get('prices') or []:
            try:
                LIVE_PRICES[(c['name'], str(x['priority']).lower())] = float(x['price'])
            except (KeyError, ValueError, TypeError):
                pass
    return items


def rules_gpu_items() -> list[dict]:
    """Запасной список классов из `rules/salad-groups.json` (снимок прайса 24.10, без id — выбрать по нему можно только после ответа API)."""
    try:
        d = json.load(open(os.path.join(SCOUT, 'rules', 'salad-groups.json'), encoding='utf-8'))
        return [{'id': None, 'name': n, 'prices': [{'priority': t, 'price': v} for t, v in pr.items()]} for n, pr in d['prices_by_class_usd_h'].items() if isinstance(pr, dict)]
    except (OSError, KeyError, ValueError, TypeError):
        return []


def gpu_table(items: list[dict], min_gb: int = GPU_MIN_GB) -> list[dict]:
    """Классы от `min_gb` ГБ: [{'name','id','gb','prices': {тариф: $/ч}}], дешёвые (по тарифу high, затем по тарифам ниже) — первыми."""
    rows = []
    for c in items:
        gb = gpu_memory_gb(c.get('name', ''))
        if gb is None or gb < min_gb:
            continue
        pr = {}
        for x in c.get('prices') or []:
            try:
                pr[str(x['priority']).lower()] = float(x['price'])
            except (KeyError, ValueError, TypeError):
                pass
        rows.append({'name': c['name'], 'id': c.get('id'), 'gb': gb, 'prices': pr})
    rows.sort(key=lambda r: tuple(r['prices'].get(t, 9e9) for t in GPU_TIERS) + (r['name'],))
    return rows


def pick_cheapest(items: list[dict], min_gb: int, tier: str) -> tuple[dict | None, str | None]:
    """Самый дешёвый класс от `min_gb` ГБ на тарифе `tier`; на нём нет ни одного — на следующем тарифе вниз (high → medium → low → batch). Возвращает (класс, тариф) или (None, None);
    тариф отличается от запрошенного — вызывающий ОБЯЗАН об этом сказать."""
    rows = gpu_table(items, min_gb)
    for t in GPU_TIERS[GPU_TIERS.index(tier):]:
        have = sorted((r for r in rows if t in r['prices'] and r['id']), key=lambda r: (r['prices'][t], r['name']))
        if have:
            return have[0], t
    return None, None


def format_gpu_table(rows: list[dict], note: str = '', min_gb: int = GPU_MIN_GB) -> str:
    """Таблица классов для печати: имя, ГБ, цены по тарифам ($/ч)."""
    out = [f'классы GPU ≥ {min_gb} ГБ, $/ч по тарифам{(" — " + note) if note else ""}:', f'  {"класс":<28}{"ГБ":>4}  ' + '  '.join(f'{t:>7}' for t in GPU_TIERS)]
    for r in rows:
        out.append(f'  {r["name"]:<28}{r["gb"]:>4}  ' + '  '.join(f'{r["prices"].get(t, float("nan")):>7.3f}' for t in GPU_TIERS))
    if not rows:
        out.append(f'  (нет ни одного класса от {min_gb} ГБ)')
    return '\n'.join(out)


_UNSET = object()


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


def live_price_usd_h(MG, class_name: str, tier: str, items=_UNSET) -> float | None:
    """ЕДИНАЯ точка денег пробы: ЖИВАЯ цена из Salad (19.11: 4090 high $0,44, а снимок в `rules/salad-groups.json` от 24.10 говорил $0,33 — траты занижались на треть). Нет ответа — None (вызывающий берёт снимок `price_usd_h`).
    Источник один — `fetch_gpu_items` (тот же запрос `gpu-classes`, он же кладёт цены в `LIVE_PRICES` и кормит таблицу `--gpu`). `items` — уже полученный ответ (None = API молчал, повторно не опрашиваем)."""
    v = LIVE_PRICES.get((class_name, tier))
    if v is not None:
        return float(v)
    if items is _UNSET:
        items = fetch_gpu_items(MG)
    return parse_live_price(items or [], class_name, tier)


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


def build_body(name: str, image: str, tier: str, model: str, hf_token: str, cpu: int, mem_mb: int, run_note: str, auth: dict, donor: dict | None = None,
               extra_env: dict | None = None) -> dict:
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
    elif donor is None and model == 'mvadapter-i2tex':   # образ MV-Adapter (`Dockerfile.mvadapter`): transformers 4.56.2 и huggingface_hub 0.35.3 уже закреплены в образе — pip на старте не нужен
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3')
    elif donor is None and model in ('mvpainter', 'supratex'):        # образы `Dockerfile.mvpainter` / `Dockerfile.supratex`: версии закреплены в образе, pip на старте не нужен; веса докачивает воркер (mvpainter ≈ 28 ГиБ, supratex ≈ 43 ГиБ; открытые, токен не обязателен)
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3')
    elif donor is None and model == 'localmesh':        # образ LocalMesh (py3.12, transformers 5.x, hub 1.x) — свои версии, pip-пины не нужны
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3')
    elif donor is None:      # TRELLIS.2: образ уже содержит воркер, но актуальный код едет через command — без пересборки образа (python3 в образе, `python` нет)
        pre = (f'for i in 1 2 3; do python3 -m pip install -q "{TRELLIS_PIP_PIN}" && break; echo "[pip] попытка $i не удалась"; sleep 5; done; '
               f'python3 -m pip list 2>/dev/null | grep -i -E "^(transformers|huggingface|tokenizers|safetensors|torch|trimesh|timm|kornia|numpy) " | tr -s " " | tr "\\n" ";"; echo')
        command, env['TRIAL_WORKER_Z'] = worker_command(python='python3', pre=pre)
    if extra_env and model in WENV_MODELS:                # только пробам краски: остальные модели эти переменные не получают
        env.update(extra_env)
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
    if not getattr(a, 'out', None):
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
    mvo = {}
    if a.model == 'mvadapter-i2tex':                      # краска MV-Adapter по готовой форме: форма обязательна, товар один, параметры из списка — иначе отказ ДО группы и денег
        mvo = mv_options(a)
        if not getattr(a, 'texture_mesh', None):
            say('mvadapter-i2tex красит готовую форму: укажите --texture-mesh <clean.glb> — группа не создаётся')
            return 2
        if len(skus) != 1 or mvo is None:
            say(f'mvadapter-i2tex: один товар в --skus (форма одна); --mv-yaw из {MV_YAWS}, --mv-uv-size из {MV_UV_SIZES}, --mv-steps 1..100, --mv-ref-scale 0..2 — группа не создаётся')
            return 2
    supo = {}
    if a.model == 'supratex':                             # SUPRA-Tex красит готовую форму (и сам её пересобирает): форма обязательна, товар один, параметры из списка — иначе отказ ДО группы и денег
        supo = supra_options(a)
        if not getattr(a, 'texture_mesh', None):
            say('supratex красит готовую форму: укажите --texture-mesh <clean.glb> — группа не создаётся')
            return 2
        if len(skus) != 1 or supo is None:
            say(f'supratex: один товар в --skus (форма одна); --supra-texture-size из {SUPRA_TEX_SIZES}, --supra-decimation 10000..2000000 — группа не создаётся')
            return 2
    if a.model == 'mvpainter':                            # краска MVPainter по готовой форме: форма обязательна, товар один, параметры из списка — иначе отказ ДО группы и денег
        mvo = mvp_options(a)
        if not getattr(a, 'texture_mesh', None):
            say('mvpainter красит готовую форму: укажите --texture-mesh <clean.glb> — группа не создаётся')
            return 2
        if len(skus) != 1 or mvo is None:
            say(f'mvpainter: один товар в --skus (форма одна); --mvp-yaw из {MV_YAWS}, --mvp-steps 1..150, --mvp-reduce 0|1, --mvp-pbr 0|1 — группа не создаётся')
            return 2
    wenv = parse_worker_env(getattr(a, 'worker_env', None), bool(getattr(a, 'debug_cuda', False)))
    if wenv is None or (wenv and a.model not in WENV_MODELS):          # переменные воркера — только пробам краски и только из белого списка; иначе отказ ДО группы и денег
        say('--worker-env: только ИМЯ=ЗНАЧЕНИЕ из PIXTEX_*, MVTEX_*, MVP_*, CUDA_LAUNCH_BLOCKING, TORCH_SHOW_CPP_STACKTRACES и только для --model pixal3d-tex / mvadapter-i2tex / mvpainter / supratex; --debug-cuda — тоже только для них — группа не создаётся')
        return 2
    MG.env_from_file()
    card = getattr(a, 'card', None) or CARD['class_name']
    gpu = getattr(a, 'gpu', None)
    if a.model == 'mvpainter' and not gpu and not getattr(a, 'card', None):
        gpu = MVP_DEFAULT_GPU                             # по имени класса из API (не `cheapest`: он скатился бы на 4090)
    min_gb = int(getattr(a, 'gpu_min_gb', None) or GPU_MIN_GB)
    items = fetch_gpu_items(MG, getattr(a, 'gpu_fetch', None))        # живые цены классов — для ВСЕХ моделей (деньги и потолок считаем по ним; снимок rules — только если API молчит)
    if a.model == 'mvpainter' or gpu:                     # таблица классов от 40 ГБ с ценами — всегда в сухом прогоне mvpainter (запасной путь, если на 24 ГБ не влезет) и по запросу (`--gpu list`)
        src = items if items is not None else rules_gpu_items()
        note = 'API Salad, сейчас' if items is not None else 'API недоступен: снимок rules/salad-groups.json от 24.10, без id'
        rows = gpu_table(src, min_gb)
        say(format_gpu_table(rows, note, min_gb))
        if not rows:                                      # в организации нет таких больших классов — показываем всё, что больше 4090 (24 ГБ): это и есть запасной путь
            say(format_gpu_table(gpu_table(src, 25), note + f'; от {min_gb} ГБ классов нет — все, что больше 24 ГБ', 25))
        if gpu == 'list':
            return 0
    if gpu and gpu != 'cheapest':                         # `--gpu "<полное имя>"` — то же, что --card; id берём из того же ответа API, если он был
        card = gpu
        hit = [c for c in (items or []) if c.get('name', '').strip().lower() == gpu.strip().lower() and c.get('id')]
        if len(hit) == 1:
            card = hit[0]['name']
            CARD.update(class_name=card, class_id=hit[0]['id'])
    elif gpu == 'cheapest':                               # самый дешёвый класс от 40 ГБ на тарифе --tier, иначе на тарифе ниже (говорим об этом)
        if items is None:
            say('--gpu cheapest: API Salad недоступен — выбрать класс по ценам нельзя, группа не создаётся')
            return 2
        row, used = pick_cheapest(items, min_gb, a.tier)
        if row is None:
            say(f'--gpu cheapest: нет класса от {min_gb} ГБ с ценой ни на одном тарифе (--gpu-min-gb меняет порог) — группа не создаётся')
            return 2
        if used != a.tier:
            say(f'!! на тарифе {a.tier} нет класса от {min_gb} ГБ — беру тариф {used}')
            a.tier = used
        card = row['name']
        CARD.update(class_name=card, class_id=row['id'])
        say(f'--gpu cheapest: {card} (тариф {used}, ${row["prices"][used]}/ч)')
    if card != CARD['class_name']:                        # другая карта (localmesh — 4060 Ti 16 ГБ): id по полному имени среди классов организации
        import recreate_group as RG
        try:
            cid = RG.pick_gpu_exact(RG.gpu_classes(), [card])[0]
        except (ValueError, IndexError) as e:
            say('карта', card, 'не найдена среди классов организации:', str(e)[:200])
            return 2
        CARD.update(class_name=card, class_id=cid)
    price = live_price_usd_h(MG, CARD['class_name'], a.tier, items=items)     # живая цена Salad (единая точка); снимок — только запасной
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
            j['job_id'] += TEXTURE_MODELS.get(a.model, '-tex')
    if a.model == 'pixal3d-tex':                          # варианты кадрирования фото (fit — подгонка по силуэту формы, official — как в апстриме): по заданию на вариант, id с суффиксом
        jobs = expand_align_jobs(jobs, aligns)
    for j in jobs:
        j['role'] = (inputs.get(j['sku']) or {}).get('role') or meta.get(j['sku'], {}).get('role')
        j['dims_cm'] = meta.get(j['sku'], {}).get('dims_cm')
    mem_mb = getattr(a, 'mem_mb', None) or MODEL_MEM_MB.get(a.model, 32768)
    body = build_body(name, a.image, a.tier, a.model, hf, a.cpu, mem_mb, a.image.split('@')[-1][:19], MG.ghcr_auth(), donor, extra_env=wenv)
    if wenv:
        say('окружение воркера (отладка/настройки):', wenv)
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
        create_wait_s = float(getattr(a, 'create_wait_min', None) or CREATE_WAIT_MIN) * 60
        t_wait = clock()
        while True:                                       # создание группы Salad бывает долгим (живая группа MV-Adapter 19.11 — дольше 10 минут); до `running` деньги не идут
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            if clock() - t_wait >= create_wait_s:
                say(f'!! группа {name} не дошла до stopped за {create_wait_s / 60:.0f} мин (состояние: {st}) — /start не шлю, гашу')
                summary['stopped_by'] = 'create_timeout'
                return 1
            sleep(5)
        t_start = clock()
        started = False
        for attempt in range(1 + START_RETRIES):          # /start на ещё не созданной группе отвечает 400 — повторяем, а не ждём молча у остановленной группы
            code, _ = MG.api(f'/{name}/start', 'POST')
            say('start HTTP', code, f'(попытка {attempt + 1} из {1 + START_RETRIES})')
            if code < 300:
                started = True
                break
            _, st2, cnt2 = BR.group_state(name)
            say(f'!! start не принят: HTTP {code}; состояние группы: {st2} {cnt2 if cnt2 else ""}'.strip())
            if attempt < START_RETRIES:
                sleep(START_RETRY_S)
        if not started:
            say(f'!! группа не стартовала за {1 + START_RETRIES} попыток /start — гашу с проверкой')
            summary['stopped_by'] = 'start_failed'
            return 1
        gw, ready_at, fail_streak = None, None, 0
        ever_ok, last_gb, last_gb_t, last_say = False, None, None, 0.0           # видимость воркера: был ли хоть один ответ /health, рост докачки весов
        last_hc = 0.0                                                             # последний опрос /health во время задания (воркер «сломан» после фатальной ошибки CUDA)
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
                          'decimation_target': a.decimation, 'texture_size': a.texture, 'detail': getattr(a, 'detail', None), 'texture_mesh_b64': tex_mesh_b64, 'role': j.get('role'), 'dims_cm': j.get('dims_cm'), 'align': j.get('align'), 'tex_guidance': j.get('tex_guidance'), 'shape_smooth': j.get('shape_smooth'), **mvo, **supo}
                    c, r = gw.call('POST', '/generate', pl, timeout=90)
                    inflight = {**j, 'submitted': t, 'http': c}
                    say('задание', j['job_id'], '→ HTTP', c)
                    if c not in (202, 409):
                        inflight.update(status='failed', error=f'POST {c} {str(r)[:120]}')
                elif inflight is not None:
                    if inflight.get('status') != 'failed' and t - last_hc >= 30:
                        last_hc = t
                        ch, hh = gw.call('GET', '/health', timeout=20)
                        if ch == 200 and (hh.get('broken') or hh.get('ok') is False):
                            cj, rj = gw.call('GET', '/job/' + inflight['job_id'], timeout=30)          # последний ответ задания (диагностика) — до остановки
                            if cj == 200 and rj.get('status') in ('done', 'failed'):
                                inflight.update(status=rj['status'], metrics=rj.get('metrics'), error=rj.get('error'), trace=rj.get('trace'), diag=rj.get('diag'))
                            else:
                                inflight.update(status='failed', error=f'воркер сломан: {hh.get("broken") or hh.get("error")}')
                            inflight['seconds'] = round(t - inflight['submitted'], 1)
                            summary['jobs'].append(inflight)
                            summary['failed'] += 1
                            summary['broken'] = hh.get('broken') or hh.get('error')
                            say('!! воркер сломан (фатальная ошибка CUDA):', summary['broken'], '— гашу сразу')
                            summary['stopped_by'] = 'worker_broken'
                            break
                    if inflight.get('status') != 'failed':
                        c, r = gw.call('GET', '/job/' + inflight['job_id'], timeout=30)
                        if c == 200 and r.get('status') in ('done', 'failed'):
                            inflight.update(status=r['status'], metrics=r.get('metrics'), error=r.get('error'), trace=r.get('trace'), diag=r.get('diag'))
                            if r['status'] == 'done':
                                cg, glb = gw.call('GET', '/glb/' + inflight['job_id'], timeout=300, raw=True)
                                if cg == 200:
                                    fp = os.path.join(a.out, inflight['job_id'] + '.glb')
                                    open(fp, 'wb').write(glb)
                                    open(fp[:-4] + '.model', 'w', encoding='utf-8').write(a.model)
                                    inflight['glb_path'] = fp
                                    vb = (r.get('metrics') or {}).get('views_jpeg_b64')          # mvadapter-i2tex/mvpainter: 6 видов (миниатюра) — рядом с GLB, из сводки убираем
                                    if vb:
                                        open(fp[:-4] + '.views.jpg', 'wb').write(base64.b64decode(vb))
                                        r['metrics']['views_jpeg_b64'] = 'saved:' + os.path.basename(fp[:-4]) + '.views.jpg'
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
                        if (inflight.get('diag') or {}).get('fatal'):         # фатальная ошибка CUDA: следующие задания только повторят её — гасим сразу, не ждём серию отказов
                            summary['broken'] = inflight.get('error')
                            say('!! фатальная ошибка CUDA в задании — воркер сломан, гашу сразу')
                            summary['stopped_by'] = 'worker_broken'
                            break
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
    ap.add_argument('--model', default='trellis2', choices=['trellis2', 'pixal3d', 'pixal3d-tex', 'mvadapter-i2tex', 'mvpainter', 'supratex', 'localmesh', 'hunyuan21'])
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
    ap.add_argument('--supra-refine', action='store_true', help='supratex: --refine апстрима (чёткий мелкий рисунок, +≈2 мин на 3090)')
    ap.add_argument('--supra-texture-size', type=int, default=4096, help='supratex: размер текстуры выпуска (1024/2048/4096; 4096 — как в апстриме)')
    ap.add_argument('--supra-decimation', type=int, default=500000, help='supratex: целевое число граней выпуска (по умолчанию 500000, как в апстриме; форма пересобирается ремешем)')
    ap.add_argument('--tex-align', default='fit', help='pixal3d-tex: варианты через запятую, по заданию на вариант: fit (подгонка фото по силуэту формы), official (как в апстриме Pixal3D); добавки: +g<сила направляющей, по умолчанию 1>, +s<проходов сглаживания формы для латента>; пример: fit,official,fit+g3,fit+s60')
    ap.add_argument('--mv-yaw', default='auto', help='mvadapter-i2tex: поворот формы к виду 0 (лицом к камере): auto — по силуэту фото, либо 0/90/180/270 (силуэты 0° и 180° зеркальны — различаются только несимметричностью предмета)')
    ap.add_argument('--mv-uv-size', type=int, default=4096, help='mvadapter-i2tex: размер развёртки при проекции видов (1024/2048/4096; 4096 — как в апстриме, самый тяжёлый по памяти)')
    ap.add_argument('--mv-steps', type=int, default=50, help='mvadapter-i2tex: шагов SDXL (по умолчанию 50, как в апстриме)')
    ap.add_argument('--mv-ref-scale', type=float, default=1.0, help='mvadapter-i2tex: сила опоры на фото (reference_conditioning_scale, по умолчанию 1,0)')
    ap.add_argument('--mvp-yaw', default='auto', help='mvpainter: поворот формы к виду 0: auto — по силуэту фото, либо 0/90/180/270')
    ap.add_argument('--mvp-steps', type=int, default=75, help='mvpainter: шагов диффузии (по умолчанию 75, как в апстриме)')
    ap.add_argument('--mvp-reduce', default='1', choices=['0', '1'], help='mvpainter: 1 — штатное упрощение формы до 30 тыс. вершин (по умолчанию, как у авторов), 0 — не упрощать')
    ap.add_argument('--mvp-pbr', default='1', choices=['0', '1'], help='mvpainter: 1 — PBR через IDArb (по умолчанию), 0 — только базовый цвет')
    ap.add_argument('--gpu', default=None, help='класс карты (для mvpainter по умолчанию RTX 5090 (32 GB); 4090 — только явно): полное имя («RTX 6000 Ada (48 GB)», то же, что --card), `cheapest` — самый дешёвый от 40 ГБ на тарифе --tier (нет на нём — тариф ниже, с предупреждением), `list` — только напечатать таблицу классов от 40 ГБ и выйти; без флага — --card (4090)')
    ap.add_argument('--gpu-min-gb', type=int, default=GPU_MIN_GB, help='порог видеопамяти для таблицы и для `--gpu cheapest` (по умолчанию 40 ГБ; в организации классов от 40 ГБ нет — самый большой RTX 5090 32 ГБ)')
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=None, help='память группы, МБ; по умолчанию 32768, для supratex 49152 (пик процессов ≈ 32,4 ГиБ)')
    ap.add_argument('--cap', type=float, default=2.0, help='потолок денег на ОДИН запуск (одну модель), $ — владелец TG 2064: $2 на модель, $10 на всю пробу')
    ap.add_argument('--max-min', type=int, default=180)
    ap.add_argument('--create-wait-min', type=float, default=CREATE_WAIT_MIN, help='сколько минут ждать, пока созданная группа станет stopped, прежде чем слать /start (деньги до running не идут)')
    ap.add_argument('--ready-min', type=int, default=75, help='сколько минут после running ждать прогрева модели (холодный старт с докачкой весов — часть результата пробы)')
    ap.add_argument('--health-min', type=int, default=20, help='сколько минут после running ждать ПЕРВОГО ответа /health, иначе стоп (воркер мёртв)')
    ap.add_argument('--disk-min-gb', type=float, default=3.0, help='стоп, если свободного места на диске контейнера меньше, ГиБ')
    ap.add_argument('--stall-min', type=int, default=10, help='сколько минут докачка весов может не расти, иначе стоп')
    ap.add_argument('--job-timeout', type=int, default=15)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=None, help='папка результатов; по умолчанию — ~/remlab-logs/mesh-models-1118/<модель>/')
    ap.add_argument('--force-out', action='store_true', help='писать, даже если там лежат файлы от другой модели (не нужно)')
    ap.add_argument('--worker-env', action='append', default=[], metavar='ИМЯ=ЗНАЧЕНИЕ', help='pixal3d-tex / mvadapter-i2tex / mvpainter: переменная окружения воркера (повторяемая), только PIXTEX_* (ALLOC_CONF, LOW_VRAM, INFERENCE_MODE, OOM_PROBE512), MVTEX_* (ALLOC_CONF, OFFLOAD), MVP_* (CKPT, LOAD_CPU, STAGE_TIMEOUT, PREFETCH), '
                    'CUDA_LAUNCH_BLOCKING, TORCH_SHOW_CPP_STACKTRACES; другим моделям не передаётся')
    ap.add_argument('--debug-cuda', action='store_true', help='pixal3d-tex / mvadapter-i2tex / mvpainter: CUDA_LAUNCH_BLOCKING=1 и TORCH_SHOW_CPP_STACKTRACES=1 в группу (ошибка CUDA — на своей строке, со стеком C++; медленнее). По умолчанию выключено')
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
