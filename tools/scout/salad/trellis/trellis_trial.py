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
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, os.path.join(SCOUT, 'render_gpu'))
sys.path.insert(0, HERE)
import cutout_origin as CORIGIN  # noqa: E402 — метка происхождения входа формы (T-175/9): способ+версия цепочки, источник маски, код, хеши
import kit_driver as KD  # noqa: E402 — общий вход «отправить задание» (post_job: таймаут по размеру тела, POST без ответа → вопрос воркеру)

CARD = {'class_name': 'RTX 4090 (24 GB)', 'class_id': 'ed563892-aacd-40f5-80b7-90c9be6c759b'}
WORK_TYPES = {'trellis2': 'trellis_shape', 'pixal3d': 'mesh_pixal3d', 'pixal3d-tex': 'mesh_pixal3d', 'localmesh': 'mesh_localmesh'}      # модель → профиль ресурсов rules/salad-resources.json (T-186/1); hunyuan21 — копия боевой группы-донора
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
MODEL_MEM_MB = {'supratex': SUPRA_MEM_MB}             # НЕ применяется (память группы — только из профиля, P-066): требование к будущей строке профиля supratex — memory_mb ≥ этого
TEXTURE_MODELS = {'mvadapter-i2tex': '-mvtex', 'mvpainter': '-mvp', 'supratex': '-supra', 'pixal3d-tex': '-tex', 'trellis2': '-tex'}      # модели «краска готовой формы» и суффикс id задания (результат — `<id>.glb`)
MULTI_TEX_MODELS = ('pixal3d-tex', 'mvadapter-i2tex', 'mvpainter', 'supratex')      # модели «краска готовой формы»: несколько товаров в одной группе, у каждого своя форма (T-20261119-06/5/2)
SHAPE_KINDS = (('clean2', 'clean2 (правило очистки E)'), ('clean', 'clean (прежнее правило очистки; clean2 нет)'))      # каталог форм: сперва clean2, иначе clean
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
        oerr = CORIGIN.check(inputs[sku].get('origin'))
        if oerr:      # вход сделан не единым модулем вырезки или устарел — форма по нему не строится (платный запуск — только по актуальному входу)
            raise ValueError(f'{sku}: вход формы без актуальной метки происхождения — ' + '; '.join(oerr) + ' — сделай вход заново: salad/trellis/make_inputs.py (единый модуль вырезки)')
        for step in plan:
            for k in range(step['n']):
                jobs.append({'sku': sku, 'res': step['res'], 'rep': k, 'seed': seed, 'job_id': f'{sku.replace(":", "_")}-{step["res"]}-{seed}-{k}'})
    return jobs


FAIL_CLASSES = ('uvatlas', 'oom_gpu', 'oom_ram', 'shape_changed', 'cuda', 'other')      # категории отказа задания для счётчика в ИТОГе (T-20261119-06/6/1); `not_run` — не дошло до запуска


def slim_job(r) -> dict:
    """Ответ `GET /job/<id>` без тяжёлых полей (картинки, трассы) — в сводку отказа: статус, стадия, ход, ошибка (T-20261119-84: r2/r3 «молчали» без единого следа)."""
    if not isinstance(r, dict):
        return {'raw': str(r)[:200]}
    out = {}
    for k, v in r.items():
        if isinstance(v, str):
            out[k] = v if len(v) <= 300 else v[:300] + '…'
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (dict, list)) and len(json.dumps(v, default=str)) <= 600:
            out[k] = v
        else:
            out[k] = f'<{type(v).__name__}, пропущено>'
    return out


def unfinished_snapshot(gw, inflight: dict, now: float) -> dict:
    """Что делал воркер, когда замер остановили на середине задания (потолок денег, предел времени, исключение): `/health` (фаза, прогрев, ГБ весов, память, диск)
    и последний `GET /job/<id>`. Раньше сводка r2/r3 SUPRA хранила только «остановлено по потолку» — куда ушли 20 минут, узнать было нельзя (19.11).
    Сбой самого снимка не мешает остановке группы: ошибка уходит в поле."""
    snap = {'job_id': inflight.get('job_id'), 'seconds': round(now - inflight.get('submitted', now), 1)}
    for key, path in (('health', '/health'), ('job', '/job/' + str(inflight.get('job_id')))):
        try:
            c, r = gw.call('GET', path, timeout=20)
            snap[key] = slim_job(r) if c == 200 else {'http': c}
        except Exception as e:  # noqa: BLE001 — снимок не должен сорвать остановку (деньги важнее диагностики)
            snap[key] = {'error': f'{type(e).__name__}: {str(e)[:120]}'}
    h = snap.get('health') or {}
    snap['warmup'] = {k: h.get(k) for k in ('phase', 'warm', 'progress', 'child', 'timings', 'cgroup_gb', 'disk_gb') if k in h}
    return snap


def classify_failure(error: str | None, diag: dict | None = None) -> str:
    """Категория отказа по тексту ошибки и диагностике воркера. Порядок важен: UVAtlas (issue #65 — ждём 0, считаем отдельно) → нехватка обычной памяти (контейнер убит: код −9/137, `Killed`; issue #66) →
    нехватка видеопамяти → «форма/развёртка изменились» → фатальная ошибка CUDA → прочее."""
    text = f'{error or ""} {(diag or {}).get("kind") or ""}'
    low = text.lower()
    if 'uvatlas' in low:
        return 'uvatlas'
    if re.search(r'(код|returncode|exit code|rc)\s*[=:]?\s*(-9|137)\b', low) or re.search(r'\bkilled\b', low) or 'sigkill' in low:
        return 'oom_ram'
    if (diag or {}).get('kind') == 'oom' or 'out of memory' in low or 'outofmemory' in low:
        return 'oom_gpu'
    if re.search(r'shapechanged|форма сдвинулась|форма изменилась|развёртка изменилась|число треугольников изменилось', low):
        return 'shape_changed'
    if (diag or {}).get('fatal') or (diag or {}).get('kind') == 'fatal' or 'cuda' in low:
        return 'cuda'
    return 'other'


def job_mem(x: dict, mem_limit_gb: float | None) -> dict:
    """Пики памяти задания для итога по товару: видеопамять, обычная память процесса (VmHWM), память группы контейнера (максимум по стадиям) и лимит группы, ГБ. Берётся из метрик (done)
    или из диагностики воркера (failed: стадии до падения)."""
    m, dg = x.get('metrics') or {}, x.get('diag') or {}
    stages = [v for v in (m.get('mem') or dg.get('stage_mem') or {}).values() if isinstance(v, dict)] + ([dg['mem']] if isinstance(dg.get('mem'), dict) else [])

    def mx(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return max(vals) if vals else None
    vram = m.get('peak_vram_gb') if m.get('peak_vram_gb') is not None else mx([v.get('peak_allocated_gb') for v in stages])
    rss = m.get('peak_rss_gb') if m.get('peak_rss_gb') is not None else dg.get('peak_rss_gb')
    cg = m.get('peak_cgroup_gb') if m.get('peak_cgroup_gb') is not None else mx([v.get('cgroup_gb') for v in stages])
    return {'peak_vram_gb': vram, 'peak_rss_gb': rss, 'peak_cgroup_gb': cg, 'mem_limit_gb': mem_limit_gb}


def save_stages(out: str, sku: str, job_id: str, data: bytes) -> dict:
    """А0: архив стадий (`stages.zip` задания) → `<out>/<job_id>.stages.zip` и распаковка в `<out>/<магазин_товар>/stages/`. Пути внутри архива проверяются (только внутрь папки)."""
    import zipfile
    zp = os.path.join(out, job_id + '.stages.zip')
    open(zp, 'wb').write(data)
    dest = os.path.join(out, sku.replace(':', '_'), 'stages')
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    n = 0
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            tgt = os.path.realpath(os.path.join(dest, info.filename))
            if info.is_dir():
                continue
            if tgt != root and not tgt.startswith(root + os.sep):
                raise ValueError(f'в архиве стадий путь вне папки: {info.filename}')
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            with z.open(info) as src, open(tgt, 'wb') as dst:
                dst.write(src.read())
            n += 1
    return {'zip': zp, 'dir': dest, 'bytes': len(data), 'files': n}


def write_form_checks(out: str, sku: str, step: str, glb: str) -> dict:
    """Лесенка: рядом с GLB ступени — check.json этапов 01 и 02 в `<out>/ladder-run/<ступень>/<магазин_товар>/` (ladder_checks.py; код общий с пересчётом по готовым файлам)."""
    try:
        sys.path.insert(0, SCOUT)
        import ladder_checks as LC
        return LC.write_for_job(out, sku, step, glb)
    except Exception as e:  # noqa: BLE001 — запись проверок не должна ронять скачивание; причина — в сводку
        return {'error': f'check.json лесенки НЕ записаны: {type(e).__name__}: {str(e)[:120]}'}


def find_shape(shape_dir: str, sku: str) -> tuple[str, str] | None:
    """Форма товара из каталога форм (`~/remlab-logs/mesh-models-1118/trellis/`): `<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb`. → (путь, вид) или None."""
    stem = os.path.join(os.path.expanduser(shape_dir), sku.replace(':', '_') + '-1024-42-0')
    for kind, label in SHAPE_KINDS:
        if os.path.isfile(f'{stem}.{kind}.glb'):
            return f'{stem}.{kind}.glb', label
    return None


def resolve_shapes(a, skus: list[str]) -> tuple[dict | None, str]:
    """Формы для текстурных моделей: `{товар: путь к GLB}` либо (None, причина отказа). Источники — каталог форм `--shape-dir` (по правилу clean2 → clean, для нескольких товаров) или
    `--texture-mesh <GLB>` (один товар; прежний способ). Нет формы хотя бы у одного товара — отказ ДО группы и денег (список всех, у кого нет)."""
    tm, sd = getattr(a, 'texture_mesh', None), getattr(a, 'shape_dir', None)
    if tm and sd:
        return None, f'{a.model}: форма задаётся одним способом — либо --shape-dir <каталог форм>, либо --texture-mesh <clean.glb> (один товар), не оба — группа не создаётся'
    if not tm and not sd:
        return None, f'{a.model} красит готовую форму: укажите --shape-dir <каталог форм> (форма на каждый товар: clean2, иначе clean) или --texture-mesh <clean.glb> (один товар) — группа не создаётся'
    if not skus:
        return None, f'{a.model}: нет товаров в --skus — группа не создаётся'
    if tm:
        if len(skus) != 1:
            return None, f'{a.model}: --texture-mesh — форма одна, товаров {len(skus)}; для нескольких товаров дайте --shape-dir <каталог форм> — группа не создаётся'
        if not os.path.isfile(os.path.expanduser(tm)):
            return None, f'{a.model}: нет файла формы {tm} — группа не создаётся'
        return {skus[0]: os.path.expanduser(tm)}, ''
    found, missing = {}, []
    for sku in skus:
        hit = find_shape(sd, sku)
        if hit is None:
            missing.append(sku)
        else:
            found[sku] = hit[0]
            say('форма', sku, '→', hit[0], '—', hit[1])
    if missing:
        return None, f'{a.model}: нет формы (ни clean2, ни clean в {sd}) у товаров: {", ".join(missing)} — группа не создаётся'
    return found, ''


def parse_tex_variant(tok: str) -> dict | None:
    """pixal3d-tex: вариант прогона `<align>[+g<сила>][+s<повторов>][+f<процент>]`: `fit+g3` — подгонка фото и сила направляющей 3 (по умолчанию 1), `fit+s40` — латент формы по копии,
    сглаженной 40 проходами Тобина (краска ложится на настоящую форму), `fit+f75` — форма вписана в 75 % куба (T-20261119-92: активных вокселей ≈ 56 % от прежнего,
    форма и число треугольников те же; 20…100, по умолчанию 100). Неверная запись → None."""
    parts = tok.strip().split('+')
    if parts[0] not in TEX_ALIGNS:
        return None
    v = {'tok': tok.strip(), 'align': parts[0], 'guidance': 1.0, 'smooth': 0, 'fill': 1.0}
    for q in parts[1:]:
        try:
            if q[:1] == 'g' and 0 < float(q[1:]) <= 10:
                v['guidance'] = float(q[1:])
            elif q[:1] == 's' and 0 < int(q[1:]) <= 500:
                v['smooth'] = int(q[1:])
            elif q[:1] == 'f' and 20 <= int(q[1:]) <= 100:
                v['fill'] = int(q[1:]) / 100.0
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
    out = {'mv_yaw': yaw, 'mv_uv_size': uv, 'mv_steps': steps, 'mv_ref_scale': ref}
    if getattr(a, 'mv_keep_stages', False):                # А0 (только проба): ключ в задании появляется ТОЛЬКО с флагом — без него тело задания прежнее
        out['mv_keep_stages'] = 1
    return out


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
    return [dict(j, job_id=f'{j["job_id"]}-{v["tok"].replace("+", "-")}' if len(variants) > 1 else j['job_id'], align=v['align'], tex_guidance=v['guidance'], shape_smooth=v['smooth'], shape_fill=v['fill'])
            for j in jobs for v in variants]


LADDER_KEYS = ('ss_steps', 'ss_guidance', 'ss_rescale', 'ss_rescale_t', 'shape_steps', 'shape_guidance', 'shape_rescale', 'shape_rescale_t', 'max_num_tokens', 'export_raw', 'variants', 'seed')


def parse_ladder(path: str) -> list[dict]:
    """T-20261119-94 — лесенка формы TRELLIS.2: JSON-список ступеней `{name, input: cur|hd, res: 1024|1536, ss_steps?, shape_steps?, shape_rescale?, max_num_tokens?, export_raw?, seed?}` (seed — на ступень: перекрывает `--seed` запуска, одна группа — разные seed). Имя ступени — в id задания
    (`<товар>-<имя>`), у каждой ступени меняется РОВНО то, что записано; прочее — по умолчанию апстрима. Ошибка в файле → ValueError (до группы и денег)."""
    items = json.load(open(os.path.expanduser(path), encoding='utf-8'))
    if not isinstance(items, list) or not items:
        raise ValueError('лесенка: нужен непустой JSON-список ступеней')
    seen, out = set(), []
    for it in items:
        nm = str(it.get('name') or '')
        if not nm or not all(c.isalnum() or c in '-_.' for c in nm) or nm in seen:
            raise ValueError(f'лесенка: у ступени нужно уникальное имя из букв, цифр и «-_.»: {nm!r}')
        seen.add(nm)
        if it.get('input', 'cur') not in ('cur', 'hd') or int(it.get('res', 1024)) not in (512, 1024, 1536):
            raise ValueError(f'лесенка {nm}: input — cur или hd, res — 512, 1024 или 1536')
        bad = [k for k in it if k not in ('name', 'input', 'res') + LADDER_KEYS]
        if bad:
            raise ValueError(f'лесенка {nm}: неизвестные ключи {bad}')
        if 'seed' in it and (isinstance(it['seed'], bool) or not isinstance(it['seed'], int) or not 0 <= it['seed'] < 2 ** 31):
            raise ValueError(f'лесенка {nm}: seed — целое от 0 до 2^31-1 (правило «брак → до 2 новых seed» — seed на задание, не на запуск)')
        out.append({'name': nm, 'input': it.get('input', 'cur'), 'res': int(it.get('res', 1024)), 'params': {k: it[k] for k in LADDER_KEYS if k in it}})
    return out


def expand_ladder_jobs(jobs: list[dict], ladder: list[dict]) -> list[dict]:
    """Задание на каждую ступень лесенки для каждого товара (порядок — по ступеням: сперва все товары первой ступени, затем второй…): `res`, фото (`cur` — как в БД 30 товаров, `hd` — `<товар>.hd.rgba.png`) и параметры ступени."""
    return [dict(j, job_id=f'{j["sku"].replace(":", "_")}-{r["name"]}', res=r['res'], input=r['input'], worker_params=r['params'], seed=r['params'].get('seed', j['seed']), ladder_step=r['name']) for r in ladder for j in jobs]


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


def build_body(name: str, image: str, tier: str, model: str, hf_token: str, run_note: str, auth: dict, donor: dict | None = None,
               extra_env: dict | None = None) -> dict:
    """Тело группы Salad. `auth` — доступ к приватному реестру (`migrate_groups.ghcr_auth()`); приёмника на проде (`MESH_SINK_*`) в окружении НЕТ.
    `donor` (только hunyuan21) — боевая группа-образец: берём её переменные окружения (STAGED, PIPELINE_VERSION, …) БЕЗ секретов приёмника и очереди."""
    env = {'MODEL': model, 'IMAGE_NOTE': run_note, 'HF_TOKEN': hf_token, 'HF_HOME': '/data/hf', 'OUT_DIR': '/data/out',
           'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261118-{name}'}
    if donor is None:                                      # ресурсы — ТОЛЬКО из профиля типа работы (T-186/1); нет профиля у модели или тариф вне low/medium — отказ до группы
        prof = KD.resource_profile(WORK_TYPES.get(model, ''))
        bad = KD.tier_refusal(prof, tier)
        if bad:
            raise KD.ProfileRefused(bad)
        res = {**KD.profile_resources(prof), 'gpu_classes': [CARD['class_id']]}
    else:
        bad = KD.tier_forbidden(tier)
        if bad:
            raise KD.ProfileRefused(bad)
        res = {}
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
        res = {'cpu': dres.get('cpu', 8), 'memory': dres.get('memory', 32768), 'gpu_classes': [CARD['class_id']],
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


def run_auto(a, MG, BR, **kw) -> int:
    """`run` + ОДИН автоматический повтор упавших по памяти карты заданий на большой карте (T-186/2). Старт — малая карта профиля (5060 Ti); задание, упавшее «out of memory» / сбоем
    аллокатора CUDA (`KD.is_oom_error`), после остановки группы идёт ТЕМ ЖЕ образом отдельной следующей группой на первой большой карте `card_rule.large` (5090). Повтор не цепляется
    (у повторной группы `oom_retry=False`) — потолок 1 повтор на задание; счётчик `retries_oom` отдельно от `failed` (отказы), деньги повтора — из остатка потолка `--cap`.
    Повторяются ВСЕ ступени лесенки товара (`--ladder`) — в боевом наборе у товара одна ступень hd 1024. Ничего не падало по памяти / карта уже большая / нет `card_rule` — просто `run`."""
    rc = run(a, MG, BR, **kw)
    prof_name = WORK_TYPES.get(a.model)
    if not prof_name or not getattr(a, 'oom_retry', True) or not getattr(a, 'apply', False):
        return rc
    try:
        prof = KD.resource_profile(prof_name)
    except KD.ProfileRefused:
        return rc
    big = KD.retry_card(prof, getattr(a, 'card', None) or prof['card'])
    sp = os.path.join(a.out, f'summary-trial-{a.model}-{a.suffix}.json')
    if not big or not os.path.exists(sp):
        return rc
    summ = json.load(open(sp, encoding='utf-8'))
    bad = [j for j in summ.get('jobs', []) if j.get('status') == 'failed' and KD.is_oom_error(j.get('error'))]
    summ['failed_oom'] = len(bad)
    if not bad:
        json.dump(summ, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return rc
    import copy
    a2 = copy.copy(a)
    a2.skus = list(dict.fromkeys(j['sku'] for j in bad))
    a2.card, a2.suffix, a2.oom_retry = big, f'{a.suffix}r', False
    a2.cap = max(0.05, float(a.cap) - float(summ.get('cost_usd_est') or 0))
    say(f'ПОВТОР по памяти: {len(bad)} задан. упали на «{summ.get("tier")}»-карте профиля (нехватка памяти) → одна повторная группа на {big}, потолок ${a2.cap:.2f}')
    rc2 = run(a2, MG, BR, **kw)
    sp2 = os.path.join(a2.out, f'summary-trial-{a2.model}-{a2.suffix}.json')
    s2 = json.load(open(sp2, encoding='utf-8')) if os.path.exists(sp2) else {}
    summ['retries_oom'] = {'limit': 1, 'jobs': [j.get('job_id') for j in bad], 'card': big, 'group': s2.get('group'), 'rc': rc2,
                           'done': sum(j.get('status') == 'done' for j in s2.get('jobs', [])), 'failed': sum(j.get('status') == 'failed' for j in s2.get('jobs', [])),
                           'cost_usd_est': s2.get('cost_usd_est')}
    json.dump(summ, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    say('ПОВТОР по памяти: итог', json.dumps(summ['retries_oom'], ensure_ascii=False))
    return rc or rc2


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


def run(a, MG, BR, gw_factory=Gateway, sleep=time.sleep, clock=time.time, hf_head=None, pull_guard=None, image_gib=None) -> int:
    """Весь замер. `MG` — `migrate_groups` (API Salad), `BR` — `bench_run` (состояние группы, остановка с проверкой). Подмена обоих + `gw_factory`/`sleep`/`clock`/`hf_head` — тесты."""
    inputs = json.load(open(os.path.join(a.inputs, 'inputs.json'), encoding='utf-8'))
    skus = a.skus or [k for k, v in inputs.items() if isinstance(v, dict) and v.get('input_png_sha256')]      # без --skus — весь набор из inputs.json (30 товаров)
    perr = CORIGIN.inputs_errors(inputs, [k for k in skus if k in inputs], a.inputs)      # метка в inputs.json И внутри PNG, sha файла — ДО группы и денег
    if perr:
        say(f'ОТКАЗ: входы формы без актуальной метки происхождения ({len(perr)}): ' + ' | '.join(perr[:3]) + (' …' if len(perr) > 3 else '')
            + ' — сделай входы заново: salad/trellis/make_inputs.py (единый модуль вырезки); группа не создаётся')
        return 2
    jobs = build_jobs(skus, parse_plan(a.plan), inputs, a.seed)
    name = f'trial-{a.model}-{a.suffix}'
    if not getattr(a, 'out', None):
        a.out = default_out(a.model)
    clash = owner_conflicts(a.out, [j['job_id'] for j in jobs], a.model) if not getattr(a, 'force_out', False) else []
    if clash:                                             # отказ ДО группы и денег: чужой результат под тем же именем затёрт не будет
        say(f'ОТКАЗ: в {a.out} уже лежат файлы от другой модели для {len(clash)} заданий (первое: {clash[0]}) — укажи свою --out или --force-out')
        return 2
    aligns = [parse_tex_variant(x) for x in (getattr(a, 'tex_align', None) or 'fit').split(',') if x.strip()]
    if getattr(a, 'hold_after', 0) and (not getattr(a, 'hold_file', None) or getattr(a, 'hold_max_min', 0) <= 0):          # пауза без файла-разрешения и срока — деньги шли бы без выхода
        say('--hold-after требует --hold-file и --hold-max-min > 0 — группа не создаётся')
        return 2
    shapes: dict = {}
    if a.model in MULTI_TEX_MODELS:                       # у каждого товара своя форма (clean2 → clean из каталога форм); нет у одного — отказ ДО группы и денег
        shapes, why = resolve_shapes(a, skus)
        if shapes is None:
            say(why)
            return 2
    if a.model == 'pixal3d-tex':                          # краска Pixal3D по готовой форме: варианты кадрирования из списка — иначе отказ ДО группы и денег
        if not aligns or any(x is None for x in aligns):
            say(f'pixal3d-tex: --tex-align из {TEX_ALIGNS} с добавками +g<сила>, +s<проходов> (например fit+g3) — группа не создаётся')
            return 2
    mvo = {}
    if a.model == 'mvadapter-i2tex':                      # краска MV-Adapter по готовой форме: параметры из списка — иначе отказ ДО группы и денег
        mvo = mv_options(a)
        if mvo is None:
            say(f'mvadapter-i2tex: --mv-yaw из {MV_YAWS}, --mv-uv-size из {MV_UV_SIZES}, --mv-steps 1..100, --mv-ref-scale 0..2 — группа не создаётся')
            return 2
    supo = {}
    if a.model == 'supratex':                             # SUPRA-Tex красит готовую форму (и сам её пересобирает): параметры из списка — иначе отказ ДО группы и денег
        supo = supra_options(a)
        if supo is None:
            say(f'supratex: --supra-texture-size из {SUPRA_TEX_SIZES}, --supra-decimation 10000..2000000 — группа не создаётся')
            return 2
    if a.model == 'mvpainter':                            # краска MVPainter по готовой форме: параметры из списка — иначе отказ ДО группы и денег
        mvo = mvp_options(a)
        if mvo is None:
            say(f'mvpainter: --mvp-yaw из {MV_YAWS}, --mvp-steps 1..150, --mvp-reduce 0|1, --mvp-pbr 0|1 — группа не создаётся')
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
    prof_name = WORK_TYPES.get(a.model)
    if prof_name:                                          # профиль ресурсов (T-186/1): тариф и карта — из него; нет профиля у модели — отказ до группы и денег
        try:
            prof = KD.resource_profile(prof_name)
            bad = KD.tier_refusal(prof, a.tier) or (KD.card_refusal(prof, card) if (getattr(a, 'card', None) or gpu) else None)
        except KD.ProfileRefused as exc:
            bad = str(exc)
        if bad:
            say('ОТКАЗ по профилю ресурсов:', bad, '— группа не создаётся')
            return 3
    elif a.model != 'hunyuan21':
        say(f'ОТКАЗ по профилю ресурсов: у модели «{a.model}» нет профиля в rules/salad-resources.json — группа не создаётся')
        return 3
    if not getattr(a, 'card', None) and not gpu:           # карта не названа явно — из профиля (нет профиля: прежняя 4090 контролю hunyuan21)
        card = prof['card'] if prof_name else CARD['class_name']
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
    tex_by_sku: dict = {}                                 # товар → форма (GLB, base64): едет В ТЕЛЕ КАЖДОГО задания (`texture_mesh_b64`), воркер кладёт её рядом с заданием (`<id>.mesh.glb`)
    if shapes:                                            # текстурные модели: у каждого товара своя форма
        tex_by_sku = {sku: base64.b64encode(open(path, 'rb').read()).decode() for sku, path in shapes.items()}
    elif getattr(a, 'texture_mesh', None):                # контроль перекраски TRELLIS.2: одна готовая форма (GLB) на все задания
        one = base64.b64encode(open(os.path.expanduser(a.texture_mesh), 'rb').read()).decode()
        tex_by_sku = {j['sku']: one for j in jobs}
    if tex_by_sku:
        for j in jobs:                                    # id задания с суффиксом модели (результат — `<id>.glb`)
            j['job_id'] += TEXTURE_MODELS.get(a.model, '-tex')
    if a.model == 'pixal3d-tex':                          # варианты кадрирования фото (fit — подгонка по силуэту формы, official — как в апстриме): по заданию на вариант, id с суффиксом
        jobs = expand_align_jobs(jobs, aligns)
    if getattr(a, 'ladder', None):                         # лесенка формы TRELLIS.2 (T-20261119-94): по заданию на ступень; HD-фото — файл `<товар>.hd.rgba.png` рядом с обычным
        if a.model != 'trellis2':
            say('--ladder только для --model trellis2 — группа не создаётся')
            return 2
        try:
            ladder = parse_ladder(a.ladder)
        except (ValueError, OSError, AttributeError) as e:
            say(f'лесенка не разобрана ({e}) — группа не создаётся')
            return 2
        missing = [s for s in skus for r in ladder if r['input'] == 'hd' and not os.path.exists(os.path.join(a.inputs, f'{s.replace(":", "_")}.hd.rgba.png'))]
        if missing:
            say(f'нет HD-фото `<товар>.hd.rgba.png` в {a.inputs}: {sorted(set(missing))} — группа не создаётся')
            return 2
        jobs = expand_ladder_jobs(jobs, ladder)
    for j in jobs:
        j['role'] = (inputs.get(j['sku']) or {}).get('role') or meta.get(j['sku'], {}).get('role')
        j['dims_cm'] = meta.get(j['sku'], {}).get('dims_cm')
    body = build_body(name, a.image, a.tier, a.model, hf, a.image.split('@')[-1][:19], MG.ghcr_auth(), donor, extra_env=wenv)
    mem_limit_gb = round((body['container']['resources'].get('memory') or 0) / 1024, 1)      # лимит памяти группы — из тела (профиль); в итог по товару рядом с пиками
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
    summary = {'group': name, 'model': a.model, 'image': a.image, 'tier': a.tier, 'price_usd_h': price, 'cap_usd': a.cap, 'jobs': [], 'failed': 0,
               'stop_verified': False, 'stopped_by': None, **KD.API_COUNTERS}
    code, resp, _n = KD.api_retry(MG, '', 'POST', body, name, say, sleep, None, summary)       # общий вход: 504 → ищем группу по имени, 503 → повтор; счётчики — в итог (T-20261123-03/1)
    say('POST создание', code, str(resp)[:200] if code >= 300 else 'ok')
    if code >= 300:
        v = KD.orphan_check(MG, BR, name, say, summary)                                          # create отказал, а группа могла появиться — гасим, сирот не оставляем
        say('ИТОГ', json.dumps({'group': name, 'stopped_by': f'create_http_{code}', 'stop_verified': True if v is None else v, **{k: summary[k] for k in KD.API_COUNTERS}}, ensure_ascii=False))
        return 1
    ok_stop = False
    os.makedirs(a.out, exist_ok=True)
    t_start = run_since = None
    guard = (pull_guard or KD.PullGuard)(name) if getattr(a, 'pull_guard', True) else None     # сторож докачки образа до running (общий, kit_driver; числа — rules/salad-groups.json → pull_guard)
    if guard is not None:
        if image_gib is None:
            try:
                image_gib = KD.check_image(a.image, MG.ghcr_auth())[2]                           # манифест реестра, бесплатно; не прочитан — норма «размер неизвестен»
            except Exception:  # noqa: BLE001
                image_gib = None
        guard.configure(image_gib)
        say('сторож докачки образа: размер', f'{image_gib} ГиБ' if image_gib else 'неизвестен', f'→ допуск полной докачки {guard.verdict_kw["max_total_min"]:.0f} мин')
    gw = inflight = None                                  # finally: снимок незавершённого задания (нужен и при раннем выходе)
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
            code, _, _n = KD.api_retry(MG, f'/{name}/start', 'POST', None, name, say, sleep, None, summary)
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
        ready_at, fail_streak = None, 0
        ever_ok, last_gb, last_gb_t, last_say = False, None, None, 0.0           # видимость воркера: был ли хоть один ответ /health, рост докачки весов
        last_hc = 0.0                                                             # последний опрос /health во время задания (воркер «сломан» после фатальной ошибки CUDA)
        pending = list(jobs)
        last_wait_say = -1e9
        hold_t0 = None                                                        # пауза «проба → ок → партия» на ТЁПЛОЙ ноде (T-20261121-172): момент начала ожидания файла-разрешения
        while True:
            t = clock()
            _, st, cnt = BR.group_state(name)
            _, ins = BR.instances(name)
            if any(i.get('state') == 'running' for i in ins) and run_since is None:
                run_since = t
                summary['to_first_running_s'] = round(t - t_start, 1)
                say(f'первый running: t+{t - t_start:.0f} с от /start')
            running_s = (t - run_since) if run_since is not None else 0.0
            if guard is not None and run_since is None:
                if guard.step(t, ins):                                   # образ качается слишком медленно (T-178 22.11: 2 % на 15-й минуте) → экземпляр пересажен (бесплатно: до running не списывается)
                    summary['pull_culls'] = guard.culls
                    last_wait_say = -1e9
                if guard.give_up:
                    say(f'!! {guard.give_up} — гашу')
                    summary['stopped_by'] = 'pull_slow'
                    break
            if run_since is None and t - last_wait_say >= 120:          # до первого running лог молчал 15–25 мин (образ тянется): строка хода раз в 2 мин, P-039
                last_wait_say = t
                i0 = ins[0] if ins else {}
                say(f'ждём running: группа {st}, счётчики {cnt}, экземпляр {i0.get("state")}, образ {round((i0.get("pulling_progress") or 0) * 100)} %, прошло {t - t_start:.0f} с от /start (деньги $0 до running)')
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
                    gw.counters = summary                                          # post_job кладёт сюда retries_post
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
                if inflight is None and pending and getattr(a, 'hold_after', 0) and len(summary['jobs']) >= a.hold_after and not os.path.exists(a.hold_file):
                    if hold_t0 is None:
                        hold_t0 = t
                        say(f'пауза: сделано {len(summary["jobs"])} из {len(jobs)}; нода тёплая и ждёт файл {a.hold_file} (дальше — партия) не дольше {a.hold_max_min} мин; деньги идут, потолок ${a.cap} действует')
                    if t - hold_t0 > a.hold_max_min * 60:
                        say(f'!! разрешения (файл {a.hold_file}) нет {a.hold_max_min} мин — гашу')
                        summary['stopped_by'] = 'hold_timeout'
                        break
                    sleep(10)
                    continue
                if inflight is None and pending:
                    j = pending.pop(0)
                    png = open(os.path.join(a.inputs, f'{j["sku"].replace(":", "_")}.{"hd." if j.get("input") == "hd" else ""}rgba.png'), 'rb').read()
                    pl = {'job_id': j['job_id'], 'image_b64': base64.b64encode(png).decode(), 'pipeline_type': pipeline_type(j['res']), 'seed': j['seed'],
                          'decimation_target': a.decimation, 'texture_size': a.texture, 'detail': getattr(a, 'detail', None), 'texture_mesh_b64': tex_by_sku.get(j['sku']), 'role': j.get('role'), 'dims_cm': j.get('dims_cm'), 'align': j.get('align'), 'tex_guidance': j.get('tex_guidance'), 'shape_smooth': j.get('shape_smooth'), 'shape_fill': j.get('shape_fill'), **(j.get('worker_params') or {}), **mvo, **supo}
                    c, r, pt = KD.post_job(gw, '/generate', pl, '/job/' + j['job_id'], getattr(a, 'post_timeout', 0), say_fn=say, sleep=sleep)
                    if pt:
                        summary.setdefault('post_timeouts', []).append(pt)
                    if pt and not pt['worker_saw_job'] and not j.get('retried'):                      # воркер задание не видит: один повтор в конец очереди той же ноды (тот же job_id: гонка → 409 = принято)
                        say('задание', j['job_id'], '→ один повтор в конец очереди')
                        pending.append({**j, 'retried': True})
                        sleep(10)
                        continue
                    inflight = {**j, 'submitted': t, 'http': c}
                    say('задание', j['job_id'], '→ HTTP', c)
                    if c not in (202, 409):
                        inflight.update(status='failed', error=f'{(pt or {}).get("reason") or "POST"} {c} {str(r)[:120]}')      # reason=gateway_503 — шлюз не принял ноду за все паузы (T-20261123-04/1)
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
                                    if inflight.get('ladder_step'):                     # лесенка формы: этапы 01/02 пишут свои check.json (T-20261123-45) — сбой записи не роняет прогон, но виден в сводке
                                        inflight['form_checks'] = write_form_checks(a.out, inflight['sku'], inflight['ladder_step'], fp)
                                    if (r.get('metrics') or {}).get('has_raw'):          # TRELLIS.2: сырая форма до упаковки (simplify/remesh/decimation) — вторым файлом, по ступеням с export_raw
                                        cr, glb_raw = gw.call('GET', '/glb/' + inflight['job_id'] + '?v=raw', timeout=600, raw=True)
                                        if cr == 200:
                                            fp_raw = os.path.join(a.out, inflight['job_id'] + '.raw.glb')
                                            open(fp_raw, 'wb').write(glb_raw)
                                            inflight['glb_raw_path'] = fp_raw
                                            inflight['glb_raw_bytes'] = len(glb_raw)
                                        else:
                                            inflight['glb_raw_error'] = f'HTTP {cr}'
                                    for vn in (r.get('metrics') or {}).get('variant_files') or []:          # TRELLIS.2: варианты упаковки (T-94/2 шаг 02) — по файлу на вариант
                                        cv, glb_v = gw.call('GET', '/glb/' + inflight['job_id'] + '?v=' + vn, timeout=600, raw=True)
                                        if cv == 200:
                                            open(os.path.join(a.out, f'{inflight["job_id"]}.{vn}.glb'), 'wb').write(glb_v)
                                        else:
                                            inflight.setdefault('variant_errors', []).append(f'{vn}: HTTP {cv}')
                                    if (r.get('metrics') or {}).get('stages'):                 # mvadapter-i2tex с --mv-keep-stages: архив стадий (А0) — тем же путём, что GLB, `?v=stages`
                                        cs, zb = gw.call('GET', '/glb/' + inflight['job_id'] + '?v=stages', timeout=900, raw=True)
                                        if cs == 200:
                                            inflight['stages'] = save_stages(a.out, inflight['sku'], inflight['job_id'], zb)
                                        else:
                                            inflight['stages'] = {'error': f'архив стадий не скачался: HTTP {cs}'}
                                            say('!! архив стадий не скачался:', inflight['job_id'], f'HTTP {cs}')
                                    if (r.get('metrics') or {}).get('has_ai'):          # localmesh: вторая версия — текстура «как нарисовала модель», до проекции фото
                                        ca, glb_ai = gw.call('GET', '/glb/' + inflight['job_id'] + '?v=ai', timeout=300, raw=True)
                                        if ca == 200:
                                            fp_ai = os.path.join(a.out, inflight['job_id'] + '.ai.glb')
                                            open(fp_ai, 'wb').write(glb_ai)
                                            inflight['glb_ai_path'] = fp_ai
                                else:
                                    inflight.update(status='failed', error=f'GLB не скачался: HTTP {cg}')
                        elif t - inflight['submitted'] > a.job_timeout * 60:
                            inflight.update(status='failed', error=f'задание не закончилось за {a.job_timeout} мин', last_job=slim_job(r) if c == 200 else {'http': c})
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
        if gw is not None and inflight is not None and inflight.get('status') not in ('done', 'failed'):
            summary['unfinished'] = unfinished_snapshot(gw, inflight, clock())   # потолок/таймаут/исключение посреди задания: что видел воркер — ДО остановки группы
        try:
            if gw is not None:                                           # последний /health перед стопом: пики памяти/VRAM/диска для `resource_profile.py --suggest` (T-186/1)
                c_fin, h_fin = gw.call('GET', '/health', timeout=20)
                if c_fin == 200:
                    summary['last_health'] = {'body': h_fin}
                else:
                    say('последний /health перед стопом: HTTP', c_fin, '— пики в итог не попали')
        except Exception as exc:  # noqa: BLE001 — стоп группы важнее; причину пишем в журнал
            say('последний /health перед стопом не получен:', repr(exc)[:160])
        if prof_name:
            summary['work_type'] = prof_name
        ok_stop = BR.stop_and_verify(name)
        summary['stop_verified'] = ok_stop
        if tex_by_sku:                                    # итог по товару (в группе их может быть несколько): статус, секунды, GLB, причина отказа; не дошедшие до запуска — not_run
            done_jobs = {x['job_id']: x for x in summary['jobs']}
            summary['by_sku'] = {}
            per_sku = {}
            for j in jobs:
                per_sku[j['sku']] = per_sku.get(j['sku'], 0) + 1
            for j in jobs:                                # ключ — товар; если у товара несколько заданий (варианты --tex-align) — id задания
                x = done_jobs.get(j['job_id'])
                summary['by_sku'][j['sku'] if per_sku[j['sku']] == 1 else j['job_id']] = (
                    {'job_id': j['job_id'], 'status': x.get('status'), 'seconds': x.get('seconds'), 'glb': x.get('glb_path'), 'error': x.get('error'),
                     'fail_class': classify_failure(x.get('error'), x.get('diag')) if x.get('status') == 'failed' else None, **job_mem(x, mem_limit_gb)} if x else
                    {'job_id': j['job_id'], 'status': 'not_run', 'seconds': None, 'glb': None, 'error': None, 'fail_class': None, **job_mem({}, mem_limit_gb)})
            for sku, v in summary['by_sku'].items():
                say('товар', sku, v['status'], v['fail_class'] or '', f'видео {v["peak_vram_gb"]} ГБ, процесс {v["peak_rss_gb"]} ГБ, группа {v["peak_cgroup_gb"]} из {v["mem_limit_gb"]} ГБ',
                    v['glb'] or v['error'] or '')
        fc = {k: 0 for k in FAIL_CLASSES}                  # счётчик отказов по категориям (для любой модели) + не дошедшие до запуска
        for x in summary['jobs']:
            if x.get('status') == 'failed':
                fc[classify_failure(x.get('error'), x.get('diag'))] += 1
        fc['not_run'] = max(0, len(jobs) - len(summary['jobs']))
        summary['fail_classes'] = fc
        summary['running_s'] = round((clock() - run_since), 1) if run_since is not None else 0.0
        summary['cost_usd_est'] = round(cost_usd(summary['running_s'], price), 3)
        json.dump(summary, open(os.path.join(a.out, f'summary-{name}.json'), 'w'), ensure_ascii=False, indent=1)
        say('ИТОГ', json.dumps({k: summary.get(k) for k in ('group', 'stopped_by', 'stop_verified', 'failed', 'fail_classes', 'running_s', 'cost_usd_est', *KD.API_COUNTERS)}, ensure_ascii=False))
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
    ap.add_argument('--card', default=None, help='класс карты по полному имени ("RTX 4060 Ti (16 GB)" для localmesh)')
    ap.add_argument('--detail', default='high', choices=['draft', 'standard', 'high', 'max'], help='localmesh: ярус качества (high = форма 1024, 16 шагов, 250 тыс. граней)')
    ap.add_argument('--ladder', default=None, help='trellis2: JSON со ступенями лесенки формы (имя, input cur|hd, res, шаги/rescale формы, max_num_tokens, export_raw) — по заданию на ступень на товар; HD-фото — `<товар>.hd.rgba.png` в --inputs')
    ap.add_argument('--texture-mesh', default=None, help='контроль: готовая форма (GLB) — TRELLIS.2 только перекрасит её по фото (один товар в --skus); у текстурных моделей (pixal3d-tex, mvadapter-i2tex, mvpainter, supratex) — форма ОДНОГО товара')
    ap.add_argument('--shape-dir', default=None, help='текстурные модели (pixal3d-tex, mvadapter-i2tex, mvpainter, supratex): каталог форм — у каждого товара из --skus своя форма `<магазин_товар>-1024-42-0.clean2.glb`, иначе `.clean.glb`; '
                    'товаров может быть несколько (одна группа, одна загрузка весов); нет формы хотя бы у одного — отказ до группы')
    ap.add_argument('--supra-refine', action='store_true', help='supratex: --refine апстрима (чёткий мелкий рисунок, +≈2 мин на 3090)')
    ap.add_argument('--supra-texture-size', type=int, default=4096, help='supratex: размер текстуры выпуска (1024/2048/4096; 4096 — как в апстриме)')
    ap.add_argument('--supra-decimation', type=int, default=500000, help='supratex: целевое число граней выпуска (по умолчанию 500000, как в апстриме; форма пересобирается ремешем)')
    ap.add_argument('--tex-align', default='fit', help='pixal3d-tex: варианты через запятую, по заданию на вариант: fit (подгонка фото по силуэту формы), official (как в апстриме Pixal3D); добавки: +g<сила направляющей, по умолчанию 1>, +s<проходов сглаживания формы для латента>; пример: fit,official,fit+g3,fit+s60')
    ap.add_argument('--mv-yaw', default='auto', help='mvadapter-i2tex: поворот формы к виду 0 (лицом к камере): auto — по силуэту фото, либо 0/90/180/270 (силуэты 0° и 180° зеркальны — различаются только несимметричностью предмета)')
    ap.add_argument('--mv-uv-size', type=int, default=4096, help='mvadapter-i2tex: размер развёртки при проекции видов (1024/2048/4096; 4096 — как в апстриме, самый тяжёлый по памяти)')
    ap.add_argument('--mv-steps', type=int, default=50, help='mvadapter-i2tex: шагов SDXL (по умолчанию 50, как в апстриме)')
    ap.add_argument('--mv-ref-scale', type=float, default=1.0, help='mvadapter-i2tex: сила опоры на фото (reference_conditioning_scale, по умолчанию 1,0)')
    ap.add_argument('--mv-keep-stages', action='store_true', help='mvadapter-i2tex, только проба (А0): воркер сохраняет стадии без потерь (виды 768 и 1536, карты 4096/2048, запекание из одного вида 0, рендеры в камере вида 0) в stages.zip; драйвер кладёт их в <out>/<магазин_товар>/stages/. По умолчанию выключено — ничего не меняет')
    ap.add_argument('--mvp-yaw', default='auto', help='mvpainter: поворот формы к виду 0: auto — по силуэту фото, либо 0/90/180/270')
    ap.add_argument('--mvp-steps', type=int, default=75, help='mvpainter: шагов диффузии (по умолчанию 75, как в апстриме)')
    ap.add_argument('--mvp-reduce', default='1', choices=['0', '1'], help='mvpainter: 1 — штатное упрощение формы до 30 тыс. вершин (по умолчанию, как у авторов), 0 — не упрощать')
    ap.add_argument('--mvp-pbr', default='1', choices=['0', '1'], help='mvpainter: 1 — PBR через IDArb (по умолчанию), 0 — только базовый цвет')
    ap.add_argument('--gpu', default=None, help='класс карты (для mvpainter по умолчанию RTX 5090 (32 GB); 4090 — только явно): полное имя («RTX 6000 Ada (48 GB)», то же, что --card), `cheapest` — самый дешёвый от 40 ГБ на тарифе --tier (нет на нём — тариф ниже, с предупреждением), `list` — только напечатать таблицу классов от 40 ГБ и выйти; без флага — --card (4090)')
    ap.add_argument('--gpu-min-gb', type=int, default=GPU_MIN_GB, help='порог видеопамяти для таблицы и для `--gpu cheapest` (по умолчанию 40 ГБ; в организации классов от 40 ГБ нет — самый большой RTX 5090 32 ГБ)')
    ap.add_argument('--hold-after', type=int, default=0, help='пауза на тёплой ноде: после N готовых заданий (проба) не слать следующие, пока не появится файл --hold-file (разрешение партии); 0 — без паузы')
    ap.add_argument('--hold-file', default=None, help='файл-разрешение (создаёт ведущий/рабочий после «ок» по пробе); нужен вместе с --hold-after')
    ap.add_argument('--hold-max-min', type=int, default=30, help='сколько минут ждать файл-разрешение, иначе группа гасится (потолок денег --cap действует и в паузе)')
    ap.add_argument('--tier', default='low', choices=['low', 'medium'], help='low; нет машин — повторить с medium вручную (платить не за что); batch/high запрещены (владелец TG 1456/1457)')
    ap.add_argument('--cap', type=float, default=2.0, help='потолок денег на ОДИН запуск (одну модель), $ — владелец TG 2064: $2 на модель, $10 на всю пробу')
    ap.add_argument('--max-min', type=int, default=180)
    ap.add_argument('--create-wait-min', type=float, default=CREATE_WAIT_MIN, help='сколько минут ждать, пока созданная группа станет stopped, прежде чем слать /start (деньги до running не идут)')
    ap.add_argument('--ready-min', type=int, default=75, help='сколько минут после running ждать прогрева модели (холодный старт с докачкой весов — часть результата пробы)')
    ap.add_argument('--health-min', type=int, default=20, help='сколько минут после running ждать ПЕРВОГО ответа /health, иначе стоп (воркер мёртв)')
    ap.add_argument('--disk-min-gb', type=float, default=3.0, help='стоп, если свободного места на диске контейнера меньше, ГиБ')
    ap.add_argument('--no-pull-guard', dest='pull_guard', action='store_false', help='выключить сторож докачки образа до running (по умолчанию включён: медленная докачка → пересадка экземпляра)')
    ap.add_argument('--stall-min', type=int, default=10, help='сколько минут докачка весов может не расти, иначе стоп')
    ap.add_argument('--job-timeout', type=int, default=15)
    ap.add_argument('--post-timeout', type=int, default=0, help='секунд ждать ответ на POST /generate; 0 (по умолчанию) — по размеру тела: base_s + per_mb_s × МБ, не больше max_s '
                    '(`rules/salad-groups.json` → gateway_post). T-178 22.11: шлюз Salad отвечает 76–90+ с на холодной ноде, при зашитых 90 с первое задание сорвалось')
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--out', default=None, help='папка результатов; по умолчанию — ~/remlab-logs/mesh-models-1118/<модель>/')
    ap.add_argument('--force-out', action='store_true', help='писать, даже если там лежат файлы от другой модели (не нужно)')
    ap.add_argument('--worker-env', action='append', default=[], metavar='ИМЯ=ЗНАЧЕНИЕ', help='pixal3d-tex / mvadapter-i2tex / mvpainter: переменная окружения воркера (повторяемая), только PIXTEX_* (ALLOC_CONF, LOW_VRAM, INFERENCE_MODE, OOM_PROBE512), MVTEX_* (ALLOC_CONF, OFFLOAD), MVP_* (CKPT, LOAD_CPU, STAGE_TIMEOUT, PREFETCH), '
                    'CUDA_LAUNCH_BLOCKING, TORCH_SHOW_CPP_STACKTRACES; другим моделям не передаётся')
    ap.add_argument('--debug-cuda', action='store_true', help='pixal3d-tex / mvadapter-i2tex / mvpainter: CUDA_LAUNCH_BLOCKING=1 и TORCH_SHOW_CPP_STACKTRACES=1 в группу (ошибка CUDA — на своей строке, со стеком C++; медленнее). По умолчанию выключено')
    ap.add_argument('--no-oom-retry', dest='oom_retry', action='store_false', help='выключить автоповтор упавших по памяти заданий на большой карте (по умолчанию: один повтор, T-186/2)')
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
    return run_auto(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
