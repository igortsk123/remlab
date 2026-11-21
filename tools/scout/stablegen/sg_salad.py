#!/usr/bin/env python3
"""ПРОБА «StableGen на Salad» (T-20261119-90/5, этап 1; решения владельца TG 1998–1999, 2005, 2014–2015). Одна ВРЕМЕННАЯ группа `trial-sg-<метка>` (RTX 4090, 1 нода): на ней ComfyUI с Qwen-Image-Edit
(GGUF), а Blender с аддоном StableGen крутится ЗДЕСЬ, без окна (`sg_drive.py`), и ходит к ноде через локальный мост `sg_relay.py` (аддон умеет только http/ws, шлюз Salad — https + ключ).
Забирается готовый GLB: форма и развёртка наши (HD-форма t94), текстуру рисует StableGen по HD-вырезке t93 как «внешнему стилю».

    ~/venvs/scout/bin/python sg_salad.py --image <тег|digest> --runs 112923_13224664101879413845:q2509q5,112923_13224664101879413845:q2511q5            # разбор: тело группы без секретов, группа НЕ создаётся
    ... --apply                                                                                                                                         # создать, прогнать по очереди, ПОГАСИТЬ
    ... --stop-only --suffix <метка>                                                                                                                    # просто /stop и проверка stopped

ПРЕДОХРАНИТЕЛИ (в этом файле, а не «по памяти»; образец — `trellis_trial.py` р.4):
  • деньги: потолок `--cap` $ (по умолчанию 4,0 на ВЕСЬ замер, холодный старт и докачка весов включены); цена — ЖИВАЯ из Salad, запасная — снимок `rules/salad-groups.json`; начисления считаем по времени
    `running` + запас; при потолке — стоп и убить Blender;
  • время: `--max-min` на жизнь ноды; за час без `running` — стоп; без «готов» за `--ready-min` — стоп; `/health` молчит `--health-min` — стоп; кэш весов не растёт `--stall-min` — стоп; диск < `--disk-min-gb` — стоп;
  • отказы: 2 прогона подряд упали — стоп (чинить в коде); ИТОГ — всегда, СТОП С ПРОВЕРКОЙ `stopped` — всегда (finally);
  • бесплатная проверка весов ПЕРЕД созданием группы: HEAD по всем адресам Hugging Face (публичные, без токена) — не 200 → группу не создаю;
  • ключ Salad — из `~/scout-scenes/salad.env` через `migrate_groups.env_from_file`; в печать и журнал не попадает (`safe_print`); боевые `mesh-`/`render-` группы не трогаю, чужая живая — отказ;
  • строка каждые 10 минут: «ход» — стадия, потрачено $, прогресс; результат каждого прогона — отдельная папка с меткой времени (старое не перезаписывается).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, os.path.join(SCOUT, 'render_gpu'))
sys.path.insert(0, HERE)

CARD = {'class_name': 'RTX 4090 (24 GB)', 'class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b'}
PORT = 8000
RELAY_PORT = 18190
READINESS = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},
             'initial_delay_seconds': 30, 'period_seconds': 10, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 3}
STARTUP = {'http': {'path': '/health', 'port': PORT, 'scheme': 'http', 'headers': []},
           'initial_delay_seconds': 10, 'period_seconds': 60, 'timeout_seconds': 5, 'success_threshold': 1, 'failure_threshold': 20}      # API Salad: failure_threshold ≤ 20
from sg_queue import BAKE_EXPECT_S, BAKE_WATCH_FACTOR, FAIL_STREAK  # noqa: E402,F401  — одни правила очереди для RunPod и Salad (sg_queue.py)
SG_HOME = os.path.expanduser('~/remlab-logs/t90-1119/sg')
HD_GLB = os.path.expanduser('~/remlab-logs/t94-1119/out/{key}-hd.glb')                      # HD-форма (без пересборки развёртки)
NEWCUT_INPUT = os.path.expanduser('~/remlab-logs/t94-1119/newcut-2149/{key}.rgba.png')       # новая вырезка (комод; диван — только если р.4 пришлёт)
HD_INPUT = os.path.expanduser('~/remlab-logs/t93-1119/hd_inputs/{key}.rgba.png')            # HD-вырезка: внешний стиль для StableGen

# вариант → имя GGUF и LoRA в списках сервера + ключи весов воркера (`worker_sg.WEIGHTS`) + подпись для кадров
VARIANTS = {
    'q2509q5': {'unet': 'Qwen-Image-Edit-2509-Q5_K_M.gguf', 'lora': 'Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors', 'weights': ['q2509_q5', 'lora2509'], 'label': 'Qwen-Image-Edit-2509 Q5_K_M'},
    'q2509q8': {'unet': 'Qwen-Image-Edit-2509-Q8_0.gguf', 'lora': 'Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors', 'weights': ['q2509_q8', 'lora2509'], 'label': 'Qwen-Image-Edit-2509 Q8_0'},
    'q2511q5': {'unet': 'Qwen-Image-Edit-2511-Q5_K_M.gguf', 'lora': 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', 'weights': ['q2511_q5', 'lora2511'], 'label': 'Qwen-Image-Edit-2511 Q5_K_M'},
    'q2511q8': {'unet': 'Qwen-Image-Edit-2511-Q8_0.gguf', 'lora': 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', 'weights': ['q2511_q8', 'lora2511'], 'label': 'Qwen-Image-Edit-2511 Q8_0'},
}
# ОПЫТЫ ночи (директор, T-90/6): те же веса 2509 Q5, меняем одно за раз. Ключ прогона «<товар>@<суффикс формы>» берёт форму из t94 out-comfy (например `…@c1024` — без щели крышки).
VARIANTS['q2509nl'] = {'unet': 'Qwen-Image-Edit-2509-Q5_K_M.gguf', 'lora': None, 'weights': ['q2509_q5'], 'no_lora': True, 'scene_props': {'steps': 24, 'cfg': 4.0},
                       'label': 'Qwen-Image-Edit-2509 Q5_K_M без Lightning-LoRA (24 шага, cfg 4)'}
# Бесплатный рычаг против «мыла» (находка 22:5x по аддону): в QWEN PRECISE `weight_exponent`=3 держится и в ФИНАЛЬНОЙ проекции, поэтому вид на точку усредняется по нескольким камерам.
# Как в пресете QWEN VORONOI — «сбросить» степень после генерации до 15 (почти «лучший вид на точку»): `weight_exponent_generation_only`=True + `weight_exponent_after_generation`=15.
SHARP_BLEND = {'weight_exponent_generation_only': True, 'weight_exponent_after_generation': 15.0}
VARIANTS['q2509mp'] = dict(VARIANTS['q2509q5'], megapixels=1.76, scene_props=dict(SHARP_BLEND),
                           label='Qwen-Image-Edit-2509 Q5_K_M + Lightning, виды 1,76 Мп (≈1328²) + резкое смешивание видов (степень 15 после генерации)')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sg_queue as Q                                                        # noqa: E402
import sg_store as ST                                                        # noqa: E402  — выход покраски → склад мешей (план painted-to-rt-01)
import sg_views                                                          # noqa: E402  (чистые функции: тексты видов, шаблоны, словарь материалов)
VARIANTS['q2509vp'] = dict(VARIANTS['q2509q5'], view_prompts=True, scene_props=dict(sg_views.CUSTOM_PROMPT_PROPS),      # T-90/7 ⑪ (Codex 20.11): фото только первому виду, зерно по силуэту, обход соседями, тексты видов по классу роли, штатные шаблоны аддона
                           label='Qwen-Image-Edit-2509 Q5_K_M + Lightning, ⑪: зерно по силуэту + обход соседями + тексты видов по классу роли и зоне + фото только первому виду (штатные шаблоны Qwen)')
# Диагностика ⑪ (директор 20.11, комод/диван дали заливку цветом): по одному признаку ⑪, 1 вид. vp_off — что отключить (text — подсказки видов, order — порядок от зерна); prompt_keep — оставить прежний короткий промпт.
VARIANTS['q2509t1'] = dict(VARIANTS['q2509vp'], vp_off=['text'], label='диагностика: промпт из каталога без подсказок видов')
VARIANTS['q2509t5'] = dict(VARIANTS['q2509q5'], view_prompts=True, short_side=True, vp_off=['order'], label='T5: q5 + короткая подпись «plain side/back of the same …» у видов сбоку/сзади (угол от переда ≥60°), фото всем видам')
VARIANTS['q2509t5b'] = dict(VARIANTS['q2509t5'], back_suffix=', same colour and material as its side panels', label='T5b: как T5, подпись зада с «same colour and material as its side panels»')
VARIANTS['q2509t5c'] = dict(VARIANTS['q2509t5b'], vp_off=[], order_mode='alternating', scene_props=dict(sg_views.CUSTOM_PROMPT_PROPS), label='T5c: подписи T5b + фото ТОЛЬКО виду-зерну (initial_only) + порядок от переда ±45/±90/±135, зад последним')
# T-90/10 (директор 20.11): подписи и фото как в T5b для видов 0–135°, порядок «зерно, ±45, ±90, ±135, 180 последним»; различие — что с видом строго сзади (|угол от зерна| > 150°)
_T5BASE = dict(VARIANTS['q2509t5b'], vp_off=[], order_mode='alternating')
VARIANTS['q2509t5d'] = dict(_T5BASE, back_mode='drop', label='T5d: T5b + порядок от переда; камеры строго сзади нет, зад из ±135')
VARIANTS['q2509t5e'] = dict(_T5BASE, back_mode='side_sample', label='T5e: T5b + порядок от переда; виду сзади вместо фото магазина — готовый вид бока (±90)')
VARIANTS['q2509t5g'] = dict(_T5BASE, back_mode='no_photo', back_limit=100.0, label='T5g: T5b + порядок от переда; фото получают виды ≤±90°, виды ±135° и 180° — без фото (только подпись и контекст чистых боков)')
VARIANTS['q2509t5h'] = dict(VARIANTS['q2509t5g'], back_suffix=', same colour and material as its side panels, top same as the front view top', label='T5h: как T5g + в подписи видов сзади «цвет и материал как у боков, верх как у переда» (общее правило: невидимые стороны = материал боков)')
VARIANTS['q2509t5i'] = dict(VARIANTS['q2509t5g'], photo_no_colour=True, label='T5i: как T5g, но у ПЕРВОГО вида (зерно, с фото) подпись без цвета (тип+материал); остальным — с цветом каталога (директор 20.11: перёд vid0 вышел серым; на всех видах с фото бока ушли в дуб — комод T5i)')
VARIANTS['q2509g1'] = dict(VARIANTS['q2509t5i'], back_mode='side_sample_sign', guard=True, scene_props={'qwen_guidance_background_color': (0.5, 0.5, 0.5)},
                           label='G1 (T-154/1): как T5i + сторож каждого вида (малиновое/цвет → повтор → без контекста → отклонить), заднему виду — образец бока по знаку угла вместо «без фото», серый фон контекста')
VARIANTS['q2509pc0'] = dict(VARIANTS['q2509g1'], parts_caption=True, label='PC0 (T-161, П6): как G1 + подпись-композиция «верх … цвета, каркас и ножки … цвета» из каталога (общая подпись, не разметка граней; утечки и выдумка сзади — меряем)')
VARIANTS['q2509pc1'] = dict(VARIANTS['q2509pc0'], parts_slots=True, label='PC1 (T-161, П6): как PC0 + слоты материала «тело/ножки» на гранях формы — только если геометрия уверенно split (кресла, диваны с ножками); слитые формы (стол-табурет, лампа) — без слотов, как PC0')
# T-160/1 (П5 тень-«вмятина», П7 блеск велюра): после всех видов аддон сам снимает свет и тени (Marigold V2 albedo) и кладёт albedo в Base Color.
# Остальные PBR-карты выключены (нужен только цвет без света). Порядок свойств важен: выбор источника albedo сам переключает автонасыщенность, потому её выключаем ПОСЛЕ (V2 цвет и так держит).
PB1_PROPS = {'pbr_decomposition': True, 'pbr_albedo_source': 'marigold_v2', 'pbr_map_albedo': True, 'pbr_map_roughness': False, 'pbr_map_metallic': False,
             'pbr_map_normal': False, 'pbr_map_height': False, 'pbr_map_ao': False, 'pbr_map_emission': False, 'pbr_replace_color_with_albedo': True,
             'pbr_albedo_auto_saturation': False}
VARIANTS['pb1'] = dict(VARIANTS['q2509g1'], weights=VARIANTS['q2509g1']['weights'] + ['mv2_base', 'mv2_lora', 'mv2_vae', 'mv2_cond'],
                       scene_props=dict(VARIANTS['q2509g1']['scene_props'], **PB1_PROPS),
                       label='PB1 (T-160/1): как G1 + снятие света и теней с видов (Marigold V2 albedo → Base Color), остальные PBR-карты выкл.')
VARIANTS['v2probe'] = dict(VARIANTS['q2509g1'], weights=['mv2_base', 'mv2_lora', 'mv2_vae', 'mv2_cond'], job='v2albedo', scene_props={},
                           label='V2-проба (T-160/1, директор 21.11): Marigold V2 albedo по ВЫРЕЗКАМ фото магазина, без Blender и запекания (только ComfyUI-граф `sg_v2_albedo.py`)')
VARIANTS['q2509t5f'] = dict(_T5BASE, back_mode='no_photo', label='T5f: T5b + порядок от переда; виду сзади фото не даём, только подпись и последовательный контекст')
VARIANTS['q2509t3'] = dict(VARIANTS['q2509vp'], label='диагностика: подсказки видов + прежний короткий промпт')
VARIANTS['q2509t4'] = dict(VARIANTS['q2509q5'], scene_props={'qwen_external_style_initial_only': True}, label='диагностика: прежний промпт, фото только первому виду')
VARIANTS['q2509edge'] = dict(VARIANTS['q2509q5'], bake_margin=32, bake_denoise=False,
                             scene_props={'sg_silhouette_margin': 8, 'sg_silhouette_feather': 24, 'refine_edge_feather_width': 60, 'discard_factor_after_generation': 75.0, **SHARP_BLEND},
                             label='Qwen-Image-Edit-2509 Q5_K_M + Lightning, края: срез по углу 75°, силуэт-запас 8, растушёвка 24/60, запас запекания 32 px, запекание без шумоподавления, резкое смешивание (степень 15)')
SHAPE_DIR = os.path.expanduser('~/remlab-logs/t94-1119/out-comfy')
SHAPE_DIRS = {'n1024': os.path.expanduser('~/remlab-logs/t90-1120/shape-uv'), 'n1024b': os.path.expanduser('~/remlab-logs/t90-1120/shape-uv')}     # форма R2b1s (TRELLIS.2 1024, ≤150 тыс. граней с UV) из Salad-группы: «товар@n1024»
SHAPE_FILE = {'n1024b': 'n1024'}                                                                                                        # имя файла формы во второй группе то же, что в первой
CUT_DIRS = {'vyb10': os.path.expanduser('~/remlab-logs/t104-1120/vyb10-1216'), 'vyb30': os.path.expanduser('~/remlab-logs/t104-1120/vyb30-1242')}    # новые вырезки цепочки цикла 6: «товар@форма+cut-vyb10»
SHAPES_RULES = os.environ.get('SG_SHAPES_RULES') or os.path.join(SCOUT, 'rules', 'stablegen-shapes.json')


def load_shape_paths(path: str = SHAPES_RULES) -> dict:
    """Формы R2b1 (TRELLIS.2 k1024, ≈150 тыс. граней, развёрнуты sg_prep_shape.py — правило директора 21:54): ID товаров — в данных
    `rules/stablegen-shapes.json` («товар|форма» → путь), не в коде (T-20261120-147). → {(товар, форма): путь}; нет файла — пусто."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        raw = json.load(fh).get('shape_paths', {})
    return {tuple(k.split('|', 1)): os.path.expanduser(v) for k, v in raw.items()}


SHAPE_PATHS = load_shape_paths()
HD20_INPUT = os.path.expanduser('~/remlab-logs/t93-1119/hd20/{key}.rgba.png')                 # HD-вырезка товаров из набора hd20 (кресло)


def say(*a) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), *a, flush=True)


def parse_runs(spec: str) -> list[tuple[str, str]]:
    """«key:q2509q5,key:q2511q5» → [(key, вариант)]; неизвестный вариант — ошибка ДО денег."""
    out = []
    for part in [p for p in (spec or '').split(',') if p.strip()]:
        key, _, var = part.strip().rpartition(':')
        if not key or var not in VARIANTS:
            raise ValueError(f'прогон «{part}»: нужен <ключ товара>:<вариант из {sorted(VARIANTS)}>')
        out.append((key, var))
    if not out:
        raise ValueError('нет прогонов (--runs)')
    return out


def weights_for(runs: list[tuple[str, str]]) -> str:
    """Какие веса качать группе: общие (текст-кодировщик, VAE) + по паре «модель + LoRA» на каждый вариант (без повторов, порядок стабильный)."""
    keys = [] if runs and all(VARIANTS[v].get('job') == 'v2albedo' for _, v in runs) else ['te', 'vae']      # V2-проба: текст-кодировщик и VAE Qwen не нужны (свои VAE и conditioning) — экономим ≈8 ГБ докачки
    for _, var in runs:
        for w in VARIANTS[var]['weights']:
            if w not in keys:
                keys.append(w)
    return ','.join(keys)


def load_weights_catalog() -> dict:
    """Каталог весов — из `worker_sg.py` БЕЗ импорта файла (воркеру нужен aiohttp, которого в окружении драйвера нет): берём литерал `WEIGHTS = {…}` разбором исходника.
    Единственное место правды о весах — воркер; драйвер лишь проверяет их адреса до денег."""
    import ast
    tree = ast.parse(open(os.path.join(HERE, 'worker_sg.py'), encoding='utf-8').read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'WEIGHTS' for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError('в worker_sg.py нет WEIGHTS')


def weight_urls(spec: str, catalog: dict) -> list[str]:
    return [f'https://huggingface.co/{repo}/resolve/main/{rel}' for repo, rel, _sub, _name in (catalog[k] for k in spec.split(','))]


def cost_usd(running_s: float, price: float, reserve_s: float = 60.0) -> float:
    """Начисления по времени `running` + запас на отставание счёта (платим с момента running)."""
    return max(0.0, running_s + (reserve_s if running_s > 0 else 0.0)) / 3600.0 * price


def price_usd_h(tier: str) -> float | None:
    try:
        d = json.load(open(os.path.join(SCOUT, 'rules', 'salad-groups.json'), encoding='utf-8'))
        return float(d['prices_by_class_usd_h'][CARD['class_name']][tier])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def resolve_card(MG, name: str) -> bool:
    """Класс карты по имени (например «RTX 5090 (32 GB)») из живого списка Salad → CARD (id для группы). Нет такого/нет ответа — False (группу не создаём)."""
    try:
        url = MG.API.split('/projects/')[0] + '/gpu-classes'
        req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            for c in json.loads(r.read()).get('items') or []:
                if c.get('name') == name and c.get('id'):
                    CARD.update({'class_name': name, 'class_id': c['id']})
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def live_price_usd_h(MG, tier: str) -> float | None:
    """ЖИВАЯ цена класса карты из Salad (снимок в rules/ бывает устаревшим: 19.11 4090 high — $0,44 против $0,33). Нет ответа — None (берём снимок)."""
    try:
        url = MG.API.split('/projects/')[0] + '/gpu-classes'
        req = urllib.request.Request(url, headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'], 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            for c in json.loads(r.read()).get('items') or []:
                if c.get('name') == CARD['class_name']:
                    for x in c.get('prices') or []:
                        if str(x.get('priority')).lower() == tier:
                            return float(x['price'])
    except Exception:  # noqa: BLE001 — нет сети/ключа/формата: запасной путь — снимок
        pass
    return None


def worker_command() -> tuple[list[str], str]:
    """Код воркера → (command, сжатый код): `python3 -u -c "exec(zlib+base64 из env TRIAL_WORKER_Z)"` — образ при правках воркера не пересобирается."""
    src = open(os.path.join(HERE, 'worker_sg.py'), 'rb').read()
    z = base64.b64encode(zlib.compress(src, 9)).decode()
    code = "import base64,os,zlib;exec(zlib.decompress(base64.b64decode(os.environ['TRIAL_WORKER_Z'])).decode())"
    return ['python3', '-u', '-c', code], z


def build_body(name: str, image: str, tier: str, weights: str, cpu: int, mem_mb: int, auth: dict) -> dict:
    command, z = worker_command()
    env = {'MODEL': 'stablegen', 'IMAGE_NOTE': image.split('@')[-1][:19], 'SG_WEIGHTS': weights, 'DATA_DIR': '/data/weights', 'OUT_DIR': '/data/out', 'PORT': str(PORT),
           'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261119-{name}', 'TRIAL_WORKER_Z': z}
    return {
        'name': name, 'display_name': name,
        'container': {'image': image, 'command': command,
                      'resources': {'cpu': cpu, 'memory': mem_mb, 'gpu_classes': [CARD['class_id']], 'storage_amount': 80 * 2 ** 30, 'shm_size': 1024},      # 80 ГиБ: веса ≈ 25–45 ГиБ + запас
                      'priority': tier, 'environment_variables': env, 'image_caching': True, 'registry_authentication': auth},
        'autostart_policy': False, 'restart_policy': 'never', 'replicas': 1, 'priority': tier, 'country_codes': [],
        'networking': {'protocol': 'http', 'port': PORT, 'auth': True, 'load_balancer': 'round_robin', 'single_connection_limit': False,
                       'client_request_timeout': 100000, 'server_response_timeout': 100000},
        'readiness_probe': READINESS, 'startup_probe': STARTUP,
    }


def safe_print(body: dict) -> None:
    b = json.loads(json.dumps(body))
    b['container'].pop('registry_authentication', None)
    for k in list(b['container']['environment_variables']):
        if any(s in k for s in ('TOKEN', 'KEY', 'SECRET', 'PASS')):
            b['container']['environment_variables'][k] = '<скрыто>'
        elif k == 'TRIAL_WORKER_Z':
            b['container']['environment_variables'][k] = f'<код воркера, {len(b["container"]["environment_variables"][k])} знаков>'
    print(json.dumps(b, ensure_ascii=False, indent=1))


def glb_has_uv(path: str) -> bool | None:
    """У формы-GLB есть TEXCOORD_0 у всех примитивов? None — файла нет/не GLB (проверка не применима). T-90/11: формы Salad приходят без UV."""
    import struct
    try:
        with open(path, 'rb') as f:
            head = f.read(20)
            if head[:4] != b'glTF':
                return None
            n = struct.unpack('<I', head[12:16])[0]
            j = json.loads(f.read(n))
    except (OSError, ValueError, struct.error):
        return None
    prims = [p for m in j.get('meshes', []) for p in m.get('primitives', [])]
    return bool(prims) and all('TEXCOORD_0' in p.get('attributes', {}) for p in prims)


def _passport_observe(role: str) -> None:
    """Пред-платной гейт паспорта типа в режиме `observe` (план mesh-type-passports-01, фаза 1): считает «заблокировал бы», решение ИГНОРИРУЕТСЯ.
    Сам по себе не бросает (`gate` ловит всё), но и импорт/вызов — в своём try: паспорт не должен менять платный путь ни при каком сбое."""
    try:
        sys.path.insert(0, os.path.dirname(HERE))
        import mesh_type_passports as MTP
        MTP.passport_preflight(role)
    except Exception as e:  # noqa: BLE001
        say(f'WARN:passport_registry: гейт покраски не вызван ({type(e).__name__}) — платный путь не меняется')


def build_cfg(key: str, var: str, out: str, server: str, cameras: int, texture: int, seed: int, timeout_s: int) -> dict:
    """Конфиг драйвера Blender для одного прогона: пресет «Qwen Precise», 8–10 камер вокруг предмета, фото-вырезка как внешний стиль (решение владельца TG 2005)."""
    v = VARIANTS[var]
    prod, _, shape = key.partition('@')                      # «товар@суффикс» → форма из SHAPE_DIR/<товар>-<суффикс>.glb, иначе HD-форма
    style = HD_INPUT.format(key=prod)
    if not os.path.exists(style) and os.path.exists(HD20_INPUT.format(key=prod)):
        style = HD20_INPUT.format(key=prod)
    if shape.endswith('+newcut'):                            # «…+newcut» — вход: новая вырезка цепочки main после T-107 (t94 newcut-2149), а не t93 hd_inputs
        shape = shape[:-len('+newcut')]
        style = NEWCUT_INPUT.format(key=prod)
    if '+cut-' in shape:                                     # «…+cut-<метка>» — вход: вырезка из папки CUT_DIRS[метка] (`<товар>.rgba.png`)
        shape, _, tag = shape.partition('+cut-')
        style = os.path.join(CUT_DIRS[tag], f'{prod}.rgba.png')
    glb = SHAPE_PATHS[(prod, shape)] if (prod, shape) in SHAPE_PATHS else os.path.join(SHAPE_DIRS.get(shape, SHAPE_DIR), f'{prod}-{SHAPE_FILE.get(shape, shape)}.glb') if shape else HD_GLB.format(key=prod)    # «товар@r2b1» — упрощённая форма с развёрткой из SHAPE_PATHS
    if glb_has_uv(glb) is False:                             # форма без развёртки — запекание не кончится; платный под не поднимаем
        raise ValueError(f'форма без UV: {glb} — сначала sg_prep_shape.py')
    cfg = {'glb': glb, 'out': out, 'server': server, 'preset': 'QWEN PRECISE', 'prompt': 'a piece of furniture',
           'cameras': {'mode': 'orbit_ring', 'num': cameras}, 'texture_resolution': texture, 'bake_samples': 16, 'seed': seed, 'timeout_s': timeout_s,
           'style_image': style, 'model_unet': v['unet'], 'lora_name': v['lora']}
    for k in ('no_lora', 'scene_props', 'megapixels', 'bake_margin', 'bake_denoise', 'view_prompts', 'vp_off', 'short_side', 'back_suffix', 'order_mode', 'back_mode', 'back_limit', 'photo_no_colour', 'guard', 'parts_caption', 'parts_slots'):
        if k in v:
            cfg[k] = v[k]
    attrs = catalog_attrs(prod)                              # T-90/10: подсказка — из каталога (роль + материал + цвет), для ВСЕХ товаров; словаря по ID нет
    cfg['cat_role'] = attrs.get('role', '')
    _passport_observe(cfg['cat_role'])                       # фаза 1 «тень»: только счётчик гейта паспорта, cfg и платный вход НЕ меняются
    cfg['catalog_name'] = attrs.get('name', '')
    cfg['colour'] = attrs.get('colour')                     # T-154/1: слово цвета каталога — сторож цвета и исключение для розового/фиолетового
    parts = None
    if v.get('parts_caption'):                               # T-161 П6: подпись-композиция «верх такого-то цвета, каркас и ножки такого-то» из каталога; двух цветов/шаблона нет → прежняя подпись + флаг
        parts = sg_views.parts_phrase(attrs.get('role', ''), attrs.get('colours'), attrs.get('top_colours'))
    cfg['parts_phrase'] = parts
    cfg['prompt'], cfg['prompt_flags'] = sg_views.build_prompt(attrs.get('role', ''), attrs.get('material'), attrs.get('colour'), parts=parts)
    cfg['prompt_bare'] = sg_views.build_prompt(attrs.get('role', ''), attrs.get('material'), None, bare=True)[0]     # T-154/1: подпись видов БЕЗ фото — без слов рисунка и без цвета (цвет подставит драйвер)
    if v.get('parts_caption') and not parts:
        cfg['prompt_flags'] = list(cfg['prompt_flags']) + ['parts_caption_unavailable']
    if v.get('parts_slots'):                                 # T-161: слоты «тело/ножки» по геометрии формы (sg_parts.py); нет уверенной разметки → без слотов, красим как сейчас + флаг
        import sg_parts
        info = sg_parts.face_slots(glb)
        cfg['parts_slots_reason'] = info['reason']
        if info['ok']:
            cfg['parts_faces'] = sg_parts.write_faces(info, os.path.join(out, 'parts-faces.json'))
        else:
            cfg['prompt_flags'] = list(cfg['prompt_flags']) + ['parts_slots_unavailable']
    if not attrs:
        cfg['prompt_flags'] = list(cfg['prompt_flags']) + ['catalog_unavailable']
    return cfg


def catalog_attrs(prod: str) -> dict:
    """role/name/material товара «магазин_внешнийid» из БД dev (`remlab-devdb`, как `category_map.py`). Материал: параметры обивки/фасада/корпуса, затем название. Нет БД или записи → {}."""
    shop, _, ext = prod.partition('_')
    if not shop.isdigit() or not ext.isdigit():
        return {}
    q = (f"select cat_role, name, coalesce(params->>'Материал обивки',''), coalesce(params->>'Материал фасада',''), coalesce(params->>'Материал корпуса',''), coalesce(params->>'Цвет основной',''), coalesce(params->>'Расцветка материала обивки',''), coalesce(params->>'Цвет шкафа: Цвет корпуса',''), coalesce(params->>'Цвет шкафа: Цвет фасада',''), coalesce(params->>'Материал столешницы: Цвет столешницы','') "
         f"from products where shop_mid::text='{shop}' and external_id='{ext}'")
    try:
        r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-At', '-F', '|', '-c', q], capture_output=True, text=True, timeout=20)
        row = r.stdout.strip().split('\n')[0].split('|') if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        row = None
    if not row or len(row) < 10:
        return {}
    role, name, upholstery, facade, body, c_main, c_uph, c_body, c_facade, c_top = row[:10]
    return {'role': role, 'name': name, 'material': sg_views.material_from_texts([upholstery, facade, body, name]),
            'colour': sg_views.colour_from_texts([name, c_uph, c_main, c_body, c_facade]),
            'colours': sg_views.colours_in_order([c_main, name]),            # T-161 П6: все цвета по порядку («Белый Светлое дерево» → white, light natural wood); верх — из «цвет столешницы», если есть
            'top_colours': sg_views.colours_in_order([c_top])}


def progress_line(stage: str, cost: float, cap: float, extra: str = '') -> str:
    return f'ход: {stage} · потрачено ≈${cost:.2f} из ${cap:.2f} {extra}'.strip()


class Gateway:
    """HTTP к ноде через шлюз группы (`https://<dns>`) с ключом Salad; без падения на сетевых сбоях (код -1)."""

    def __init__(self, base: str, key: str):
        self.base, self.key = base.rstrip('/'), key

    def call(self, method: str, path: str, timeout: int = 30):
        req = urllib.request.Request(self.base + path, method=method, headers={'Salad-Api-Key': self.key, 'User-Agent': 'remlab-mesh/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return r.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return -1, {}


def hf_head(url: str) -> int:
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'remlab-mesh/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return -1


def api_retry(MG, path: str, method: str, body, name: str, say, sleep=time.sleep, rules=None):
    """create/start группы Salad с повтором при 502/503/504 (T-153/1, признаки — rules/stablegen-transient.json → salad_api). Перед каждым повтором смотрим группу:
    создание — группа уже есть (200) → считаем созданной; старт — состояние не «stopped» → уже стартовала. Возвращает (код, ответ, число_повторов)."""
    import sg_transient
    r = (rules or sg_transient.load_rules())['salad_api']
    code, resp = MG.api(path, method, body) if body is not None else MG.api(path, method)
    for attempt in range(r['retries']):
        if code not in r['status_codes']:
            return code, resp, attempt
        sleep(sg_transient.pause_s(r, attempt))
        c2, g = MG.api(f'/{name}')
        state = ((g or {}).get('current_state') or {}).get('status') if c2 == 200 else None
        if c2 == 200 and (method == 'POST' and path == '' or state not in (None, 'stopped')):
            say(f'{method} {path or "создание"}: ответ {code}, но группа уже есть (состояние {state}) — считаю выполненным')
            return 201 if path == '' else 202, resp, attempt + 1
        say(f'{method} {path or "создание"}: краткий сбой Salad API {code} — повтор {attempt + 1}/{r["retries"]}')
        code, resp = MG.api(path, method, body) if body is not None else MG.api(path, method)
    return code, resp, r['retries']


def run(a, MG, BR, gw_factory=Gateway, sleep=time.sleep, clock=time.time, head=hf_head, popen=subprocess.Popen) -> int:
    runs = parse_runs(a.runs)
    spec = weights_for(runs)
    urls = weight_urls(spec, load_weights_catalog())
    name = f'trial-sg-{a.suffix}'
    MG.env_from_file()
    if getattr(a, 'card', None) and a.card != CARD['class_name'] and not resolve_card(MG, a.card):
        say(f'класс карты «{a.card}» не найден у Salad — стоп, денег не потрачено')
        return 3
    price = live_price_usd_h(MG, a.tier)
    price_src = 'живая (Salad gpu-classes)'
    if price is None:
        price, price_src = price_usd_h(a.tier), 'СНИМОК rules/salad-groups.json (живая цена недоступна)'
    body = build_body(name, a.image, a.tier, spec, a.cpu, a.mem_mb, MG.ghcr_auth())
    say('группа', name, CARD['class_name'], 'тариф', a.tier, 'цена $/ч', price, f'[{price_src}]', 'прогонов', len(runs), 'потолок $', a.cap, 'веса:', spec)
    if not a.apply:
        safe_print(body)
        for k, v in runs:
            say('  прогон', k, v, VARIANTS[v]['label'])
        return 0
    if price is None:
        say('цены группы нет — стоп (деньги без цены не считаем)')
        return 2
    bad = [(u.split('/resolve')[0].split('huggingface.co/')[1], c) for u in urls for c in [head(u)] if c not in (200, 302)]
    say('проверка весов на Hugging Face (бесплатно):', 'все доступны' if not bad else f'НЕДОСТУПНЫ {bad}')
    if bad:
        say('группу НЕ создаю, денег не потрачено')
        return 3
    code, d = MG.api('')
    live = [g['name'] for g in d.get('items', []) if (g.get('current_state') or {}).get('status') not in ('stopped', 'failed', None) and not g['name'].startswith(('mesh-', 'render-', 'trial-'))]
    if live:
        say(f'живые чужие группы {live} — стоп')
        return 2
    code, g = MG.api(f'/{name}')
    if code == 200:
        say(f'группа {name} уже есть — не пересоздаю молча (другая --suffix)')
        return 2
    code, resp, _n = api_retry(MG, '', 'POST', body, name, say, sleep)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        return 1
    summary = {'group': name, 'image': a.image, 'tier': a.tier, 'price_usd_h': price, 'cap_usd': a.cap, 'weights': spec, 'runs': [], 'failed': 0, 'stop_verified': False, 'stopped_by': None}
    os.makedirs(a.out, exist_ok=True)
    relay = None
    run_since = None
    queue = None
    relay_port = getattr(a, 'relay_port', None) or RELAY_PORT
    try:
        for _ in range(120):
            _, st, _c = BR.group_state(name)
            if st == 'stopped':
                break
            sleep(5)
        t_start = clock()
        code, _, _n = api_retry(MG, f'/{name}/start', 'POST', None, name, say, sleep)
        say('start HTTP', code)
        gw, ready_at, ever_ok, last_gb, last_gb_t, last_say, minute_say = None, None, False, None, None, 0.0, 0.0
        pending = list(runs)
        gb_hist = []                                              # (время, ГБ весов) — для сторожа скорости докачки

        def start_run(key, var, t):
            stamp = time.strftime('%H%M%S', time.gmtime())
            odir = os.path.join(a.out, f'{key}-{var}-{stamp}')            # новая папка с меткой времени — старое не перезаписывается
            os.makedirs(odir, exist_ok=True)
            if VARIANTS[var].get('job') == 'v2albedo':                    # V2-проба: лёгкий HTTP-клиент к ноде через мост (не тяжёлое — очередь heavy-slot не нужна); вход — вырезка из --v2-inputs
                src = {i['name']: i['path'] for i in json.load(open(a.v2_inputs, encoding='utf-8'))}[key]
                cmd = [sys.executable, os.path.join(HERE, 'sg_v2_albedo.py'), '--server', f'127.0.0.1:{relay_port}', '--in', src, '--out', os.path.join(odir, 'albedo.png'), '--timeout', str(a.job_timeout * 60)]
                proc = popen(cmd, stdout=open(os.path.join(odir, 'run.log'), 'ab'), stderr=subprocess.STDOUT)
                return {'key': key, 'variant': var, 'label': VARIANTS[var]['label'], 'dir': odir, 'proc': proc, 'started': t, 'last_say': t}
            cfg = build_cfg(key, var, os.path.join(odir, 'blender'), f'127.0.0.1:{relay_port}', a.cameras, a.texture, a.seed, a.job_timeout * 60)   # стоп «форма без UV» — здесь, до Blender
            cfg_path = os.path.join(odir, 'cfg.json')
            json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            heavy = os.path.join(SCOUT, '..', 'ops', 'heavy-slot.sh')
            cmd = [heavy, f't90-sg-{var}', '--prio', '2', '--cores', '4', '--min-gb', '3', '--timeout', str(a.job_timeout * 60), '--', os.path.join(HERE, 'sg_run.sh'), cfg_path]   # prio 2: ждёт платная нода
            proc = popen(cmd, env={**os.environ, 'SG_HOME': SG_HOME}, stdout=open(os.path.join(odir, 'run.log'), 'ab'), stderr=subprocess.STDOUT)
            return {'key': key, 'variant': var, 'label': VARIANTS[var]['label'], 'dir': odir, 'proc': proc, 'started': t, 'last_say': t}

        def finish_run(it, rc, t):
            if VARIANTS[it['variant']].get('job') == 'v2albedo':
                return rc == 0 and os.path.exists(os.path.join(it['dir'], 'albedo.png')), {}
            return rc == 0 and os.path.exists(os.path.join(it['dir'], 'blender', 'painted.glb')), {}

        def over_limits(t: float) -> str | None:
            running_s = (t - run_since) if run_since is not None else 0.0
            cost = cost_usd(running_s, price)
            summary['cost_usd_est'] = round(cost, 3)
            if cost >= a.cap:
                return 'money'
            if run_since is not None and running_s > a.max_min * 60:
                return 'time'
            if run_since is None and (t - t_start) > getattr(a, 'running_min', 60) * 60:
                return 'no_machine'
            return None

        while True:
            t = clock()
            _, st, cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                summary['to_first_running_s'] = round(t - t_start, 1)
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            why = over_limits(t)
            if t - minute_say >= 60:                  # строка раз в минуту (просьба директора 19.11): состояние группы и экземпляра, пока воркер ещё не отвечает
                minute_say = t
                i0 = ins[0] if ins else {}
                say(f'мин: группа {st} · экземпляр {i0.get("state")} started={i0.get("started")} ready={i0.get("ready")} cpu {round(i0.get("cpu_percent") or 0)}% · ≈${summary.get("cost_usd_est", 0):.2f}')
            if why:
                say(f'!! стоп по причине «{why}» (≈${summary.get("cost_usd_est")}, потолок ${a.cap}) — гашу')
                summary['stopped_by'] = why
                break
            running_s = (t - run_since) if run_since is not None else 0.0
            if run_since is not None and gw is None:
                dns = ((MG.api(f'/{name}')[1].get('networking') or {}).get('dns') or '')
                if dns:
                    gw = gw_factory(f'https://{dns}', os.environ['SALAD_API_KEY'])
                    summary['gateway'] = dns
                    say('шлюз группы получен')
            if gw is not None and ready_at is None:
                c, h = gw.call('GET', '/health', timeout=20)
                if c == 200:
                    ever_ok = True
                    if h.get('error') or h.get('phase') in ('failed', 'child_dead'):
                        say('!! прогрев упал:', h.get('error'), f'(фаза {h.get("phase")}), хвост журнала ComfyUI:', (h.get('comfy_log_tail') or [])[-5:])
                        summary['stopped_by'] = 'warm_failed'
                        summary['warm_error'] = h.get('error')
                        break
                    gb = (h.get('progress') or {}).get('hf_gb')
                    cpu = (h.get('child') or {}).get('cpu_s')
                    mark = (gb, None if cpu is None else int(cpu // 20))
                    if gb is not None and mark != last_gb:
                        last_gb, last_gb_t = mark, t
                    free = ((h.get('disk_gb') or {}).get('hf') or {}).get('free')
                    summary['disk_free_gb_min'] = free if free is None else min(free, summary.get('disk_free_gb_min', free))
                    if free is not None and free < a.disk_min_gb:
                        say(f'!! на диске осталось {free} ГиБ < {a.disk_min_gb} — гашу')
                        summary['stopped_by'] = 'disk_low'
                        break
                    if t - last_say >= 60 and not h.get('warm'):           # прогрев — строка раз в минуту (в бою ход прогонов — каждые 10 минут)
                        last_say = t
                        say(progress_line(f'прогрев, фаза {h.get("phase")}', summary['cost_usd_est'], a.cap, f'· кэш весов {gb} ГБ, диск {h.get("disk_gb")}'))
                    if h.get('phase') == 'weights' and gb is not None:
                        gb_hist.append((t, float(gb)))
                        slow = weights_slow(gb_hist, a.slow_window_s, a.min_gb_min)
                        if slow is not None:
                            say(f'!! веса качаются {slow:.2f} ГБ/мин < {a.min_gb_min} уже {a.slow_window_s // 60} мин — нода медленная, гашу (беру другую)')
                            summary['stopped_by'] = 'download_slow'
                            summary['weights_gb_min'] = round(slow, 3)
                            break
                    if h.get('phase') == 'weights' and last_gb_t is not None and t - last_gb_t > a.stall_min * 60:
                        say(f'!! докачка весов стоит {a.stall_min} мин — гашу')
                        summary['stopped_by'] = 'download_stalled'
                        break
                    if h.get('warm'):
                        ready_at = t
                        summary['to_ready_s'] = round(t - t_start, 1)
                        summary['timings'] = h.get('timings')
                        summary['info'] = gw.call('GET', '/info', timeout=30)[1]
                        say(f'нода готова: t+{t - t_start:.0f} с от /start', (summary['info'] or {}).get('gpu'), 'веса', h.get('weights_gb'))
                        relay = popen([a.relay_python, os.path.join(HERE, 'sg_relay.py'), '--listen', str(relay_port), '--target', f'https://{summary["gateway"]}', '--key-env', 'SALAD_API_KEY'],
                                      env={**os.environ, 'PYTHONPATH': a.relay_deps}, stdout=open(os.path.join(a.out, f'relay-{a.suffix}.log'), 'ab'), stderr=subprocess.STDOUT)
                        sleep(3)
                if run_since is not None and not ever_ok and running_s > a.health_min * 60:
                    say(f'!! {a.health_min} мин после running воркер не отвечает — гашу')
                    summary['stopped_by'] = 'no_health'
                    break
                if run_since is not None and ready_at is None and running_s > a.ready_min * 60:
                    say(f'!! {a.ready_min} мин после running модель не прогрелась — гашу')
                    summary['stopped_by'] = 'not_ready'
                    break
            if ready_at is not None:
                if queue is None:
                    queue = Q.RunQueue(pending, summary, start=start_run, finish=finish_run, say=say, progress=progress_line, job_timeout_s=a.job_timeout * 60, relay_port=relay_port, on_ok=ST.store_run)
                qwhy = queue.step(t, summary['cost_usd_est'], a.cap)
                if qwhy:
                    summary['stopped_by'] = qwhy
                    break
                if queue.done:
                    summary['stopped_by'] = 'done'
                    break
            sleep(10)
    finally:
        for p in ([relay] if relay else []) + (queue.procs() if queue else []):
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        ok_stop = BR.stop_and_verify(name)
        summary['stop_verified'] = ok_stop
        summary['running_s'] = round((clock() - run_since), 1) if run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'running_s', 'cost_usd_est')}, ensure_ascii=False))
    return 0 if summary['stop_verified'] and summary['stopped_by'] == 'done' else 1


def weights_slow(hist: list, window_s: float, min_gb_min: float) -> float | None:
    """Скорость докачки весов за последние window_s секунд, если она ниже min_gb_min ГБ/мин (иначе None). hist — [(время_с, ГБ)] по возрастанию времени; нужна выборка, покрывающая всё окно."""
    if len(hist) < 2:
        return None
    t1, g1 = hist[-1]
    old = [(t, g) for t, g in hist if t <= t1 - window_s]
    if not old:
        return None                                             # окно ещё не набралось
    t0, g0 = old[-1]
    rate = (g1 - g0) / ((t1 - t0) / 60)
    return rate if rate < min_gb_min else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: тег или digest, ghcr.io/igortsk123/mesh-comfy-trial:stablegen-0460')
    ap.add_argument('--runs', default=None, help='<товар>[@форма][+cut-метка]:<вариант>[,…]')   # без значения по умолчанию: ID товара в коде запрещён (T-20261120-147)
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=32768)
    ap.add_argument('--cameras', type=int, default=8, help='камер вокруг предмета (владелец TG 2005: 8–10)')
    ap.add_argument('--texture', type=int, default=2048)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--cap', type=float, default=4.0, help='потолок денег на ВЕСЬ замер, $ (владелец TG 2014–2015: $4)')
    ap.add_argument('--max-min', type=int, default=150)
    ap.add_argument('--ready-min', type=int, default=60)
    ap.add_argument('--health-min', type=int, default=8, help='минут после running без ответа /health → стоп (воркер открывает порт за секунды; 19.11 пустая нода на python:slim жгла деньги)')
    ap.add_argument('--disk-min-gb', type=float, default=3.0)
    ap.add_argument('--stall-min', type=int, default=10)
    ap.add_argument('--job-timeout', type=int, default=40, help='минут на один прогон Blender (8 видов + запекание + экспорт)')
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t90-1119/sg/salad'))
    ap.add_argument('--relay-python', default='/usr/bin/python3', help='интерпретатор моста (нужен aiohttp)')
    ap.add_argument('--relay-deps', default=os.path.join(SG_HOME, 'fake-deps'), help='папка с aiohttp для моста')
    ap.add_argument('--card', default=None, help='класс карты Salad по имени, напр. «RTX 5090 (32 GB)» (по умолчанию 4090)')
    ap.add_argument('--relay-port', type=int, default=None, help='порт моста (разные у одновременных групп)')
    ap.add_argument('--min-gb-min', type=float, default=0.5, help='скорость докачки весов, ГБ/мин: ниже столько же --slow-window-s секунд подряд — нода медленная, гасим (директор 20.11)')
    ap.add_argument('--slow-window-s', type=int, default=180)
    ap.add_argument('--running-min', type=int, default=60, help='минут от /start до running (нода выдана); дольше — группу гасим (директор 20.11: 15)')
    ap.add_argument('--v2-inputs', default=None, help='JSON [{"name","path"}] — вырезки для варианта v2probe; --runs <name>:v2probe,…')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if BR.stop_and_verify(f'trial-sg-{a.suffix}') else 1
    if not a.runs:
        sys.exit('нужен --runs <товар>[@форма][+cut-метка]:<вариант>[,…] (товар по умолчанию в коде запрещён, T-20261120-147)')
    if not a.image or ('@' not in a.image and ':' not in a.image):
        sys.exit('нужен --image: тег или digest с именем репозитория')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
