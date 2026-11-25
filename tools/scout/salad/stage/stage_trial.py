#!/usr/bin/env python3
"""ПРОБА SALAD «ЭТАПЫ 06/07» (T-189/1): перенос фото на форму (06) и заливка невидимого (07) на ноде Salad по профилю `cpu_stage` (rules/salad-resources.json). Драйвер — на общем наборе
(`kit_driver.run_probe`): деньги, потолок, гашение и проверка «0 нод» — там; здесь только «что отправить и как забрать». Одна группа, два прохода: ключ `06` (все товары, до STAGE_PROCS
одновременно) → результаты 06 забираем → ключ `07` (вход — выход 06 того же товара; до STAGE_FILL_PROCS одновременно). Считает тот же код, что у нас локально (в образе, `stage_files.txt`).

Запуск (платный, только под heavy-slot --prio 2, одна группа на пакет, потолок $1):
  heavy-slot.sh t189-stage-probe --prio 2 -- python stage_trial.py --image ghcr.io/…/mesh-stage-trial@sha256:… --inputs inputs.json --apply
Без --apply — только разбор: тело группы без секретов, проверка образа и входов (группа НЕ создаётся). `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
Тариф: только low (владелец 24.11, TG 2626); нет машин → остановка без повышения до medium; batch, medium и high запрещены (tools/scout/rules/salad-resources.json allowed_tiers).
КОД ЭТАПА ЕДЕТ В ЗАДАНИИ (T-193/1/1): драйвер собирает `code.tar` из `git archive <SHA>` (`code_tar.py`; `--code-ref`, по умолчанию HEAD этого дерева), кладёт его во вход каждого задания и шлёт `code_sha` +
`code_tar_sha256`; воркер считает ИМЕННО этот код (образ — только среда), в ответе `code_sha`/`_code.json` — сверяется. Срез проверяется до платной группы (импорт точек входа из чистой распаковки).
Входы — файл `inputs.json`: {"<товар>": {"glb": путь, "photo": путь RGBA-вырезки, "pose_run": папка камеры этапа 4, "body_only": false}} (список — аргументом, в код не зашит).
Только этап 07 по готовому 06: `--stages 07 --vis-root <папка с <товар>/06-visible/>` (без `--inputs`; товары — все папки с visible.glb и check.json, сузить — `--skus a,b`): вход 07 берётся оттуда, выход — в `--out`.
07 и шов одним пакетом: `--stages 07,seam --vis-root …` (шов берёт выход 07 из `--out` сразу после того, как 07 всех товаров готов).
Только шов «фото | заливка» (T-196/1) по готовым 06 и 07: `--stages seam --fill-root <папка с <товар>/07-fill/> --vis-root <папка с <товар>/06-visible/>` → `<out>/<товар>/07-seam/`.
Этап 08 «материал» (T-220/1): `--stages 07,seam,08 --vis-root … --catalog catalog_all.json --pose-root <папки с <товар>/04-camera/>` (или `--stages 08 --fill-root … --vis-root …`): вход — `07-seam/seam.glb` (нет шва —
`07-fill/filled.glb`), `06-visible/`, `04-camera/check.json`, `product.json` из каталога, части `03-parts/` (если `--parts-root`) и фото → `<out>/<товар>/08-material/` (кадра нет: `--no-frame`, Blender на ноде не ставим).
Выход: `<out>/<товар>/06-visible/…`, `<out>/<товар>/07-fill/…` (sha256 сверен), `<out>/items-06.json`, `<out>/items-07.json` (время, пик памяти этапа, метрики).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, SALAD)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SALAD, 'parts'))                                           # parts_to_npz (флаг zones_from, выбор parts.npz для 07)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'render_gpu')))       # bench_run (group_state/instances/stop_and_verify)
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
import worker_stage as WS  # noqa: E402
import code_tar as CT  # noqa: E402
import parts_to_npz as PN  # noqa: E402
import chain_queue as CQ  # noqa: E402
from kit_driver import Gateway, say  # noqa: E402

CARD_NAME = 'GTX 1650 (4 GB)'                                  # из профиля cpu_stage: самая дешёвая карта (видеокарта этапам не нужна, у Salad нет класса без неё)
WORK_TYPE = 'cpu_stage'
PORT = 8000
WORKER = os.path.join(HERE, 'worker_stage.py')
PREFIX = 'trial-stage'
MAX_POSE_RUN_MB = 50
KEEP_SUFFIX = '.pre-backpanel.glb'


def camera_body_only(pose_run: str) -> bool:
    """«Корпус лёг, низ формы — нет» (T-20261124-02): 06 идёт с --body-only, если в 04-camera/check.json истинен хоть один флаг из rules/paint-run-all.json (dynamic.body_only_args.if_extra_true_any) —
    то же правило, что у paint_run_all (копии нет). Камера без check.json или без флагов — False. Явное body_only в inputs.json остаётся (вручную можно только включить)."""
    try:
        d = json.load(open(os.path.join(ROOT, 'tools', 'scout', 'rules', 'paint-run-all.json'), encoding='utf-8'))['dynamic']['body_only_args']
        ex = (json.load(open(os.path.join(pose_run or '', '04-camera', 'check.json'), encoding='utf-8')).get('extra') or {})
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return any(bool(ex.get(k)) for st, k in d.get('if_extra_true_any', []) if st == '04-camera')


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    return KW.bundle(path or WORKER)


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, procs: int, fill_procs: int, threads: int, timeout_s: int,
               worker_z: str | None = None, variant: str = '') -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'STAGE_PROCS': str(procs), 'STAGE_FILL_PROCS': str(fill_procs), 'STAGE_THREADS': str(threads),
           'STAGE_TIMEOUT_S': str(timeout_s), 'DEPLOYMENT_EPOCH': f'20261122-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE, variant=variant)


def load_inputs(path: str) -> dict[str, dict]:
    d = json.load(open(path, encoding='utf-8'))
    if not isinstance(d, dict) or not d:
        raise ValueError(f'{path}: нужен непустой словарь {{товар: {{glb, photo, pose_run}}}}')
    return d


def input_problems(inputs: dict[str, dict]) -> list[str]:
    """Бесплатная проверка до создания группы: все файлы на месте и камера этапа 4 полная (то же, что требует воркер)."""
    bad = []
    for sku, v in inputs.items():
        for k in ('glb', 'photo'):
            if not os.path.isfile(v.get(k) or ''):
                bad.append(f'{sku}: нет {k}: {v.get(k)}')
        pr = v.get('pose_run') or ''
        miss = [n for n in WS.NEED_06 if n.startswith('pose_run/') and not os.path.isfile(os.path.join(pr, n[len('pose_run/'):]))]
        if miss:
            bad.append(f'{sku}: в камере {pr} нет {miss}')
    return bad


def zip_dir_into(z: zipfile.ZipFile, src: str, prefix: str, limit_mb: float | None = None) -> int:
    total = 0
    for dp, dn, fn in os.walk(src):
        dn[:] = [d for d in dn if d != '__pycache__']
        for f in sorted(fn):
            if f.endswith(KEEP_SUFFIX):
                continue                                         # исходник до «зад корпусной» (visible.pre-backpanel.glb) нужен только людям, в задания не едет
            p = os.path.join(dp, f)
            total += os.path.getsize(p)
            if limit_mb and total > limit_mb * 2 ** 20:
                raise ValueError(f'{src}: больше {limit_mb} МБ — похоже, не та папка')
            z.write(p, f'{prefix}/{os.path.relpath(p, src)}')
    return total


def add_extras(z: zipfile.ZipFile, v: dict, code_tar: bytes | None, key: str = 'extra_in') -> None:
    """Общее для всех входов: `code.tar` (код задания) и доп. файлы товара `extra_in` {имя во входе: локальный путь} (карты зон и т. п.; в `args` — `@in/<имя>`).
    `key` — какой набор: у этапа 08 свой, `extra_in_08` (product.json, части `03-parts/…`, фото), чтобы не раздувать входы 06/07."""
    if code_tar:
        z.writestr('code.tar', code_tar)
    have = set(z.namelist())                                  # имя, уже лежащее во входе (photo.png этапа 06), доп. файл не перекрывает: дубль в zip = при распаковке побеждает последний (пакет 23.11: UserWarning Duplicate name)
    for rel, path in sorted((v.get(key) or {}).items()):
        if rel not in have:
            z.write(path, rel)


def input_zip_08(vis_dir: str, fill_dir: str, seam_dir: str, cam_check: str, code_tar: bytes | None = None, v: dict | None = None) -> bytes:
    """Вход 08 (T-220/1): `06-visible/{check.json,known.png,visible.glb}` (цвет частей с фото), `04-camera/check.json`, модель — `07-seam/seam.glb`, если шов отработал, иначе `07-fill/filled.glb`
    (на ноде берётся шов, если он во входе), плюс `extra_in_08` товара: `product.json`, `03-parts/parts.npz` + `parts.json`, `photo.png`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for n in ('check.json', 'known.png', 'visible.glb'):
            p = os.path.join(vis_dir, n)
            if os.path.isfile(p):
                z.write(p, f'06-visible/{n}')
        seam = os.path.join(seam_dir, 'seam.glb')
        if os.path.isfile(seam):
            z.write(seam, '07-seam/seam.glb')
        else:
            z.write(os.path.join(fill_dir, 'filled.glb'), '07-fill/filled.glb')
        z.write(cam_check, '04-camera/check.json')
        f07 = os.path.join(fill_dir, 'check.json')
        if os.path.isfile(f07):                                  # заслон 08 «только после зелёного 07» (T-20261124-10): без check.json 07 этап 08 на ноде красный
            z.write(f07, '07-fill/check.json')
        add_extras(z, v or {}, code_tar, 'extra_in_08')
    return buf.getvalue()


def seam_model_08(a, sku: str, v: dict) -> tuple[str, str, str, str]:
    """(06-visible, 07-fill, 07-seam, 04-camera/check.json) товара для 08: из `v` (vis/fill/seam/pose_run) или из `--out` (выходы этой же цепочки)."""
    root = getattr(a, 'out', '')
    vis = v.get('vis') or os.path.join(getattr(a, 'vis_root', '') or root, sku, '06-visible')
    fil = v.get('fill') or os.path.join(getattr(a, 'fill_root', '') or root, sku, '07-fill')
    sea = v.get('seam') or os.path.join(root, sku, '07-seam')
    cam = os.path.join(v.get('pose_run') or '', '04-camera', 'check.json')
    if not os.path.isfile(cam):
        for pr in [x for x in str(getattr(a, 'pose_root', '') or '').split(',') if x]:        # --pose-root: папки с <товар>/04-camera/check.json (камера этапа 4)
            for base in (pr, *sorted(os.path.join(pr, g) for g in (os.listdir(pr) if os.path.isdir(pr) else []) if os.path.isdir(os.path.join(pr, g, sku)))):
                c = os.path.join(base, sku, '04-camera', 'check.json')
                if os.path.isfile(c):
                    return vis, fil, sea, c
    return vis, fil, sea, cam


def attach_08(inputs: dict, catalog: str, out: str) -> dict:
    """Входы этапа 08 по каждому товару (`extra_in_08`): `product.json` из выгрузки каталога (`--catalog`, формат paint_run_all: [{sid,name,role,params}] — params не выдумываем), части этапа 3
    (`03-parts/parts.npz` + `parts.json`) — те же, что у 07 (`extra_in['parts.npz']`, если `attach_parts` их принял), фото (`photo`) — для сверки тона стекла. → {товар: {product, parts, photo}} (в `inputs-08.json`).
    Нет записи каталога — товар без product.json (08 не отправится: причина в items)."""
    cat = {str(r.get('sid')): r for r in json.load(open(catalog, encoding='utf-8'))} if catalog else {}
    d = os.path.join(out, '_in08')
    rep = {}
    for sku, v in inputs.items():
        ex = v.setdefault('extra_in_08', {})
        rec = cat.get(sku)
        if rec:
            os.makedirs(os.path.join(d, sku), exist_ok=True)
            pj = os.path.join(d, sku, 'product.json')
            json.dump({'sid': sku, 'name': rec.get('name') or '', 'role': rec.get('role') or '', 'params': rec.get('params') or {}}, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            ex['product.json'] = pj
        npz = (v.get('extra_in') or {}).get('parts.npz')
        pjson = os.path.join(os.path.dirname(npz), 'parts.json') if npz else ''
        why = 'нет parts.npz+parts.json' if not (npz and os.path.isfile(pjson)) else parts_roles_problem(pjson)
        if not why:
            ex['03-parts/parts.npz'], ex['03-parts/parts.json'] = npz, pjson
            rj = os.path.join(os.path.dirname(npz), 'roles.json')
            if os.path.isfile(rj):
                ex['03-parts/roles.json'] = rj
        ph = v.get('photo') or (v.get('extra_in') or {}).get('photo.png') or ''                 # фото — вырезка товара: поле photo входа 06 или photo.png входа 07
        if os.path.isfile(ph):
            ex['photo.png'] = ph
        rep[sku] = {'product': 'product.json' in ex, 'parts': '03-parts/parts.npz' in ex, 'photo': 'photo.png' in ex, 'parts_why': why}
    return rep


def attach_06(inputs: dict, catalog: str, out: str) -> dict:
    """Роль товара во вход 06 (`extra_in_06['product.json']`, как у 08): из выгрузки каталога (`--catalog`, [{sid,name,role,params}]). По роли `tex_visible` после переноса запускает шаг «зад корпусной»
    (`back_panel_stage`: допуск по паспорту типа). Нет записи/роли — файла нет, шаг не идёт (причина в отчёте). → {товар: {product, role}}."""
    cat = {str(r.get('sid')): r for r in json.load(open(catalog, encoding='utf-8'))} if catalog else {}
    d = os.path.join(out, '_in06')
    rep = {}
    for sku, v in inputs.items():
        rec = cat.get(sku)
        role = (rec or {}).get('role') or ''
        if rec and role:
            os.makedirs(os.path.join(d, sku), exist_ok=True)
            pj = os.path.join(d, sku, 'product.json')
            json.dump({'sid': sku, 'name': rec.get('name') or '', 'role': role, 'params': rec.get('params') or {}}, open(pj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            v.setdefault('extra_in_06', {})['product.json'] = pj
        rep[sku] = {'product': bool(rec and role), 'role': role}
    return rep


def parts_roles_problem(parts_json: str) -> str:
    """'' если у КАЖДОЙ части этапа 3 есть роль (parts.json `role`, либо рядом roles.json с ней): 08 читает `p["role"]` без запаса. Части PartLLM до моста T-17 ролей не несут — тогда 08 идёт без частей
    (по форме, как локально без 03-parts), а причина пишется в inputs-08.json. Иначе — причина строкой."""
    try:
        parts = json.load(open(parts_json, encoding='utf-8'))['parts']
    except (OSError, ValueError, KeyError) as exc:
        return f'parts.json не читается: {type(exc).__name__}'
    rj = os.path.join(os.path.dirname(parts_json), 'roles.json')
    roles = json.load(open(rj, encoding='utf-8')) if os.path.isfile(rj) else {}
    bad = [p.get('id') for p in parts if not p.get('role') and not (roles.get(str(p.get('id'))) or {}).get('role')]
    return f'у {len(bad)} из {len(parts)} частей нет роли (PartLLM без моста T-17): 08 без частей' if bad else ''


def input_zip_06(v: dict, code_tar: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        z.write(v['glb'], 'model.glb')
        z.write(v['photo'], 'photo.png')
        zip_dir_into(z, v['pose_run'], 'pose_run', MAX_POSE_RUN_MB)
        add_extras(z, v, code_tar)
        add_extras(z, v, None, 'extra_in_06')                    # product.json (роль → допуск «зад корпусной» после 06); у входов без каталога набор пуст
    return buf.getvalue()


def input_zip_07(vis_dir: str, code_tar: bytes | None = None, v: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        zip_dir_into(z, vis_dir, '06-visible')
        add_extras(z, v or {}, code_tar)
    return buf.getvalue()


def input_zip_seam(vis_dir: str, fill_dir: str, code_tar: bytes | None = None, v: dict | None = None) -> bytes:
    """Вход шва (T-196/1): `06-visible/` (known*.png, conf*.png, prov*.png; visible.glb не нужен — не кладём) и `07-fill/filled.glb` (выход 07 того же товара).
    `prov*.png` — карта провенанса этапа 6: по ней `load_known_png` убирает synth (prov 4) из «известного» (T-28/1); без неё шов на ноде считал synth фото, а локально — нет
    (…0015317 в k29c: 522 165 / 214 567 против 101 026 / 95 611 при том же входе; T-20261124-23/в3)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for n in sorted(os.listdir(vis_dir)):
            if n.endswith('.png') and (n.startswith('known') or n.startswith('conf') or n.startswith('prov')):
                z.write(os.path.join(vis_dir, n), f'06-visible/{n}')
        z.write(os.path.join(fill_dir, 'filled.glb'), '07-fill/filled.glb')
        add_extras(z, v or {}, code_tar)
    return buf.getvalue()


def job_id(stage: str, sku: str, data: bytes, a) -> str:
    """Идемпотентный id: этап + товар + хеш входа + параметры — повтор после вытеснения ноды не плодит дубль."""
    h = hashlib.sha256(data + json.dumps([stage, a.threads], sort_keys=True).encode()).hexdigest()[:12]
    return f'{stage}-{sku}-{h}'.replace('_', '-')[:150]


def stage_dirname(stage: str) -> str:
    return {'06': '06-visible', 'seam': '07-seam', '08': '08-material'}.get(stage, '07-fill')


def job_args(stage: str, v: dict) -> list[str]:
    """`args` товара из inputs.json — ТОЛЬКО для 07 (`--card-json @in/card.json`, `--photo …`: флаги tex_fill); 06 (tex_visible), шов и 08 их не знают и падают на «unrecognized arguments»
    (проба и пакет 23.11: шов, затем 06 при общем inputs на всю цепочку). Исключение — `--product-json @in/product.json` у 06, когда во входе есть product.json (роль → зад корпусной)."""
    if stage == '06':
        return ['--product-json', '@in/product.json'] if 'product.json' in (v.get('extra_in_06') or {}) else []
    return list(v.get('args') or []) if stage == '07' else []


def submit_stage(gw, a, inputs: dict, stage: str, t: float) -> tuple[dict | None, dict]:
    """Отправить задания этапа по одному на товар (POST /jobs; zip входа — zlib+base64). Для 07 вход — выход 06 (нет выхода — товар пропущен, причина в items)."""
    ids: dict[str, str] = {}
    skipped: dict[str, str] = {}
    code = getattr(a, 'code', None) or {}                                                  # {sha, tar, tar_sha256} — срез кода по SHA (`code_tar.build`)
    for sku, v in inputs.items():
        if stage == '06':
            data = input_zip_06(v, code.get('tar'))
        elif stage == 'seam':
            vis = v.get('vis') or os.path.join(getattr(a, 'vis_root', '') or a.out, sku, '06-visible')
            fil = v.get('fill') or os.path.join(getattr(a, 'fill_root', '') or a.out, sku, '07-fill')
            if not os.path.isfile(os.path.join(fil, 'filled.glb')) or not os.path.isfile(os.path.join(vis, 'known.png')):
                skipped[sku] = 'нет выхода 07 (filled.glb) или known.png этапа 06 — шов не запускался'
                continue
            data = input_zip_seam(vis, fil, code.get('tar'), v)
        elif stage == '08':
            vis, fil, sea, cam = seam_model_08(a, sku, v)
            ex = v.get('extra_in_08') or {}
            miss = [n for n, p in (('06-visible/check.json', os.path.join(vis, 'check.json')), ('04-camera/check.json', cam), ('product.json', ex.get('product.json') or ''))
                    if not os.path.isfile(p)]
            if not os.path.isfile(os.path.join(sea, 'seam.glb')) and not os.path.isfile(os.path.join(fil, 'filled.glb')):
                miss.append('модель 07 (seam.glb / filled.glb)')
            if miss:
                skipped[sku] = f'нет входа 08: {miss} — этап 08 не запускался'
                continue
            data = input_zip_08(vis, fil, sea, cam, code.get('tar'), v)
        else:
            vis = v.get('vis') or os.path.join(getattr(a, 'vis_root', '') or a.out, sku, '06-visible')
            if not os.path.isfile(os.path.join(vis, 'visible.glb')):
                skipped[sku] = 'нет выхода этапа 06 — 07 не запускался'
                continue
            data = input_zip_07(vis, code.get('tar'), v)
        jid = job_id(stage, sku, data, a)
        body = {'job_id': jid, 'stage': stage, 'sku': sku, 'input_z': base64.b64encode(zlib.compress(data, 6)).decode(), 'body_only': (bool(v.get('body_only')) or camera_body_only(v.get('pose_run'))) and stage == '06',
                'code_sha': code.get('sha', ''), 'code_tar_sha256': code.get('tar_sha256', '')}
        if job_args(stage, v):
            body['args'] = job_args(stage, v)
        c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        if c == -1:                                                                       # воркер задания не видит; job_id идемпотентен — один повтор, дубля не будет
            say(f'товар {sku}: POST без ответа, воркер задания не видит — повтор один раз')
            c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'этап {stage} товар {sku}: POST /jobs → {c} (тело ≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ)', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'sku': sku, 'accepted': list(ids), 'post': _tinfo, 'reason': (_tinfo or {}).get('reason')}
        ids[sku] = jid
    if not ids:
        return None, {'detail': 'нечего отправлять: ' + json.dumps(skipped, ensure_ascii=False), 'nothing_to_send': True}
    return {'key': stage, 'id': f'stage{stage}-{int(t)}', 't0': t, 'ids': ids, 'skipped': skipped, 'got': {}}, {}


def poll_stage(gw, a, cur: dict, t: float) -> tuple[str, dict]:
    """Все задания этапа закончились? Готовые забираем (sha256 сверяем, выход кладём в `<out>/<товар>/<этап>/`), счёт отказов с причинами ведём. Пока кто-то идёт — 'running'.
    «Этап не прошёл» (metrics.passed=false) — НЕ отказ набора: выход и check.json есть, это результат (как у локального счёта)."""
    stage = cur['key']
    items, running = {}, 0
    for sku, jid in cur['ids'].items():
        if sku in cur['got']:
            items[sku] = cur['got'][sku]
            continue
        c, v = gw.call('GET', f'/jobs/{jid}', timeout=30)
        if c == 404:                                       # воркер задание не знает: контейнер ноды перезапущен (память/сбой) — записи о задании нет, результат потерян; ждать нечего (T-34: тёплая нода 14:43, опрос шёл вечно)
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': 'job_lost: воркер не знает задание (404) — нода перезапущена, результат потерян'}
            continue
        if c != 200:
            running += 1                                   # шлюз моргнул — не провал; зависание ловят потолок денег и сторож хода
            continue
        if v.get('status') in ('queued', 'running'):
            running += 1
            continue
        if v.get('status') == 'failed':
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': v.get('error'), 'wall_s': v.get('wall_s'), 'peak_gb': v.get('peak_gb')}
            continue
        c2, data = gw.call('GET', f'/jobs/{jid}/result', timeout=300, raw=True)
        if c2 != 200 or not data:
            running += 1
            continue
        rec = {k: v.get(k) for k in ('wall_s', 'run_s', 'queue_s', 'peak_gb', 'metrics', 'bytes', 'sha256', 'files', 'code_sha', 'code_tar_sha256', 'cmd')}
        want_sha = (getattr(a, 'code', None) or {}).get('sha')
        if want_sha and v.get('code_sha') != want_sha:
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'code_sha не сошёлся: отправлен {want_sha}, посчитано на коде {v.get("code_sha")}', **rec}
            continue
        got = hashlib.sha256(data).hexdigest()
        if got != v.get('sha256'):
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'sha256 не сошёлся: ждали {v.get("sha256")}, получили {got}', **rec}
            continue
        out = os.path.join(a.out, sku, stage_dirname(stage))
        os.makedirs(out, exist_ok=True)
        try:
            names = WS.safe_extract(data, out)
        except ValueError as exc:
            cur['got'][sku] = items[sku] = {'status': 'failed', 'error': f'результат не распаковался: {exc}', **rec}
            continue
        cur['got'][sku] = items[sku] = {'status': 'done', 'unpacked': len(names), **rec}
        if stage == '07':
            items[sku]['top'] = top_state(out)
            items[sku]['texture_source'] = texture_source(out)
    if running:
        return 'running', {}
    for sku, why in cur.get('skipped', {}).items():
        items[sku] = {'status': 'skipped', 'error': why}
    fails = {k: v for k, v in items.items() if v['status'] == 'failed'}
    ok = sum(1 for v in items.values() if v['status'] == 'done')
    info = {'items': items, 'ok': ok, 'total': len(items), 'metrics': {'ok': ok, 'total': len(items), 'failed': {k: v.get('error') for k, v in fails.items()}}}
    if stage == '07':
        info['metrics']['texture_source'] = text_counts(items)
        info['metrics']['top'] = top_counts(items)
        say(f'верх Ш3в по товарам 07 (счётчик причин): {info["metrics"]["top"]}')
    os.makedirs(a.out, exist_ok=True)
    if getattr(a, 'queue', ''):                                                       # очередь: ноды пишут в общий out — запись по товару, а не общая на этап (иначе перезатрут друг друга)
        for sku_, rec_ in items.items():
            os.makedirs(os.path.join(a.out, sku_), exist_ok=True)
            json.dump({sku_: rec_}, open(os.path.join(a.out, sku_, f'items-{stage}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    else:
        json.dump(items, open(os.path.join(a.out, f'items-{stage}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return ('failed', {'status': 'failed', 'error': f'отказов {len(fails)} из {len(items)}: {list(fails)}', **info}) if fails else ('done', info)


def top_state(out_dir: str) -> str:
    """Что сделал хук верха Ш3в в 07 (из report.json распакованного выхода): `applied` | причина пропуска `top_skip` (no_card…) | `top_source` хука (as_before/photo_top/…) | `нет отчёта`."""
    try:
        rep = json.load(open(os.path.join(out_dir, 'report.json'), encoding='utf-8')).get('report', {}).get('top_prior') or {}
    except (OSError, ValueError):
        return 'нет отчёта'
    if rep.get('applied'):
        return 'applied'
    return str(rep.get('top_skip') or rep.get('top_source') or 'нет отчёта')


def texture_source(out_dir: str) -> str:
    """Откуда у 07 запасная микрофактура (из report.json выхода): `ultratex` | `trellis` | … | `нет отчёта`. ADR-0466: UltraTex выключен — пакет, где тут `ultratex`, шёл на коде без выключателя."""
    try:
        doc = json.load(open(os.path.join(out_dir, 'report.json'), encoding='utf-8'))
    except (OSError, ValueError):
        return 'нет отчёта'
    rep = doc.get('report', doc)
    if 'relief_source' not in rep:
        return 'нет отчёта'
    return str(rep['relief_source'] or 'none')                      # report.relief_source: null (запасной микрофактуры не брали) | 'ultratex' | 'trellis'


def text_counts(items: dict) -> dict:
    """{источник микрофактуры 07: сколько товаров} — в итог пакета (ultratex > 0 = код без выключателя, ADR-0466)."""
    c: dict = {}
    for v in items.values():
        if v.get('status') == 'done':
            c[v.get('texture_source', 'нет отчёта')] = c.get(v.get('texture_source', 'нет отчёта'), 0) + 1
    return c


def top_counts(items: dict) -> dict:
    """{состояние верха: сколько товаров} по items пакета 07 — в итог пакета: «no_card: 28» сразу видно, а не «тихо as_before»."""
    c: dict = {}
    for v in items.values():
        if v.get('status') == 'done':
            c[v.get('top', 'нет отчёта')] = c.get(v.get('top', 'нет отчёта'), 0) + 1
    return c


def top_input_problems(inputs: dict) -> tuple[list[str], list[str]]:
    """Вход 07 боевого пути обязан нести карточку и фото для верха Ш3в (`--card-json @in/card.json`, `--photo @in/photo.png`). → (товары без карточки, товары без фото); проверка бесплатная, до создания группы."""
    no_card = [s for s, v in inputs.items() if '--card-json' not in (v.get('args') or []) or not os.path.isfile((v.get('extra_in') or {}).get('card.json') or '')]
    no_photo = [s for s, v in inputs.items() if '--photo' not in (v.get('args') or []) or not os.path.isfile((v.get('extra_in') or {}).get('photo.png') or '')]
    return no_card, no_photo


def stages_of(a) -> list[str]:
    st = [x for x in str(getattr(a, 'stages', '06,07')).split(',') if x]
    if not st or any(x not in WS.DRIVER_STAGES for x in st):
        raise ValueError(f'--stages: список из {list(WS.DRIVER_STAGES)}, получено {st}')
    return st


def vis_inputs(root: str, only: str = '') -> dict[str, dict]:
    """Товары для «только 07»: папки `<root>/<товар>/06-visible/` с visible.glb и check.json (выход этапа 06 любого прогона)."""
    want = {s for s in only.split(',') if s}
    out = {}
    for sku in sorted(os.listdir(root)):
        v = os.path.join(root, sku, '06-visible')
        if os.path.isfile(os.path.join(v, 'visible.glb')) and os.path.isfile(os.path.join(v, 'check.json')) and (not want or sku in want):
            out[sku] = {}
    return out


def attach_parts(inputs: dict, parts_root: str, vis_root: str, mode: str) -> dict:
    """Части PartLLM в задание 07 (T-198/1): `mode` = zones_from (`parts`|`panels`). По каждому товару кладёт `extra_in['parts.npz']`, если mode=parts и файл годный (число граней = граням GLB этапа 6;
    ещё не посчитан — граням формы `glb` из inputs), иначе 07 идёт по панелям. → {товар: {source: parts|panels, reason}} (пишется в zones-07.json)."""
    out = {}
    for sku, v in inputs.items():
        vg = os.path.join(v.get('vis') or os.path.join(vis_root, sku, '06-visible'), 'visible.glb')
        face_glb = vg if os.path.isfile(vg) else v.get('glb')
        if mode == 'parts' and not face_glb:
            npz, why = None, 'panels: нет GLB, с которым сверить число граней'
        else:
            npz, why = PN.pick_parts(parts_root, sku, face_glb, mode)
        if npz:
            v.setdefault('extra_in', {})['parts.npz'] = npz
        out[sku] = {'source': 'parts' if npz else 'panels', 'reason': why}
    return out


def seam_inputs(fill_root: str, vis_root: str, only: str = '') -> dict[str, dict]:
    """Товары для «только шов»: `<fill_root>/<товар>/07-fill/filled.glb` и `<vis_root>/<товар>/06-visible/known.png` (оба выхода любого прогона)."""
    want = {s for s in only.split(',') if s}
    out = {}
    for sku in sorted(os.listdir(fill_root)):
        if os.path.isfile(os.path.join(fill_root, sku, '07-fill', 'filled.glb')) and os.path.isfile(os.path.join(vis_root, sku, '06-visible', 'known.png')) and (not want or sku in want):
            out[sku] = {}
    return out


NODE_DEFAULTS = {'low': (4, 2), 'big': (4, 4)}                                     # размер ноды → (заданий всего, из них этапа 07); big — T-34 A/B 23.11: ×4 быстрее на 07 при той же цене за товар
BATCH_MIN = 2                                                                      # пакет от стольких товаров идёт на big, одиночный товар — на low (T-20261124-09)


def resolve_node(variant: str | None, procs: int, fill_procs: int, n_products: int) -> tuple[str, int, int]:
    """Размер ноды и число заданий. Явные `--variant/--procs/--fill-procs` главнее; не заданы — big для пакета (≥BATCH_MIN товаров), low для одного.
    → ('' для low | 'big', procs, fill_procs): пустая строка — формат `kit_driver.profile_resources` (нет варианта = базовая строка профиля)."""
    v = variant if variant else ('big' if n_products >= BATCH_MIN else 'low')
    if v not in NODE_DEFAULTS:
        raise ValueError(f'размер ноды «{v}» неизвестен: {sorted(NODE_DEFAULTS)}')
    dp, df = NODE_DEFAULTS[v]
    return ('' if v == 'low' else v), (procs or dp), (fill_procs or df)


def make_spec(a, inputs: dict) -> KD.Spec:
    def build(name, class_id, auth):
        warm = float(getattr(a, 'keep_warm', 0) or 0)
        life_s = int(float(getattr(a, 'warm_life_min', 120)) * 60) if warm else min(a.max_min * 60 + 600, 3 * 3600)
        return build_body(name, a.image, a.tier, class_id, auth, life_s, int(warm * 60) if warm else a.idle_s, a.procs, a.fill_procs, a.threads, a.stage_timeout_s,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1], variant=getattr(a, 'variant', '') or '')

    def preflight():
        try:                                                                              # срез кода по SHA: сборка и проверка импорта ДО создания платной группы
            a.code = CT.build(getattr(a, 'repo', '') or ROOT, getattr(a, 'code_ref', '') or 'HEAD')
        except CT.CodeTarError as exc:
            return False, f'код задания не собран: {exc}'
        if not getattr(a, 'no_code_check', False):
            why = CT.selfcheck(a.code['tar'], a.code['entries'])
            if why:
                return False, f'срез кода {a.code["sha"][:8]} неполон: {why}'
        say(f'код задания: SHA {a.code["sha"]}, tar {len(a.code["tar"]) / 1024:.0f} КБ, {len(a.code["files"])} файлов, sha256 {a.code["tar_sha256"][:16]}…, вне срезов: {a.code["outside"]}')
        bad = input_problems(inputs) if '06' in stages_of(a) else []
        if '08' in stages_of(a):                                                          # 08: камера этапа 4 и запись каталога обязательны — иначе товар не отправится (счётчик пропусков в items-08)
            bad += [f'{s}: нет 04-camera/check.json (--pose-root / pose_run)' for s, v in inputs.items() if not os.path.isfile(seam_model_08(a, s, v)[3])]
        if stages_of(a) in (['seam'], ['08'], ['seam', '08']):
            bad += [f'{s}: нет 07-fill/filled.glb или 06-visible/known.png' for s, v in inputs.items()
                    if not os.path.isfile(os.path.join(v.get('fill') or os.path.join(getattr(a, 'fill_root', '') or a.out, s, '07-fill'), 'filled.glb'))
                    or not os.path.isfile(os.path.join(v.get('vis') or os.path.join(getattr(a, 'vis_root', '') or a.out, s, '06-visible'), 'known.png'))]
        elif '06' not in stages_of(a):
            root = getattr(a, 'vis_root', '')
            bad += [f'{s}: нет {(v.get("vis") or os.path.join(root, s, "06-visible"))}/visible.glb' for s, v in inputs.items()
                    if not os.path.isfile(os.path.join(v.get('vis') or os.path.join(root, s, '06-visible'), 'visible.glb'))]
        if bad:
            return False, f'входы не готовы: {bad[:4]}'
        return True, f'входы на месте: {len(inputs)} товаров'

    submit, poll, jobs, ordered = (lambda gw, k, t: submit_stage(gw, a, inputs, k, t)), (lambda gw, cur, t: poll_stage(gw, a, cur, t)), stages_of(a), True
    if getattr(a, 'queue', ''):                                                       # общая очередь (T-34): один «задание-цепочка», товары идут 07→шов→08 по одному, без барьера этапов
        q = CQ.Queue(os.path.expanduser(a.queue))
        node = a.suffix
        q.release_stale(node)                                                         # товары, оставшиеся за этой нодой от убитого процесса, — обратно в очередь
        slots = int(getattr(a, 'slots', 0) or a.fill_procs)
        nodes = int(getattr(a, 'nodes', 0) or 0)
        if nodes > 0:                                                                 # ноды готовы не одновременно: без потолка первая заберёт сразу `slots` товаров, пока соседи греются
            slots = max(1, min(slots, -(-sum(q.counts().values()) // nodes)))
        chain = CQ.Chain(q, node, stages_of(a), slots,
                         lambda gw, sku, row, stage, t: submit_stage(gw, a, {sku: row}, stage, t), lambda gw, cur, t: poll_stage(gw, a, cur, t),
                         requeue_max=int(getattr(a, 'requeue_max', 1)), say=say)
        submit = lambda gw, k, t: ({'key': k, 'id': f'chain-{node}-{int(t)}', 't0': t}, {})            # noqa: E731
        poll = lambda gw, cur, t: chain.step(gw, t)                                    # noqa: E731
        jobs, ordered = ['chain'], False
    return KD.Spec(prefix=PREFIX, card=a.card, model='cpu-stage', jobs=jobs, build_body=build, submit=submit,
                   poll=poll, preflight=preflight, ready_keys=('version', 'libs', 'procs', 'fill_procs'), z_keys=('KIT_WORKER_Z',),
                   worker_file=WORKER, work_type=WORK_TYPE, variant=getattr(a, 'variant', '') or '', ordered=ordered)             # этапы идут по порядку: повтор после сбоя шлюза — в начало очереди (T-220/1)


def stop_only(a, stop) -> int:
    """`--stop-only`: 0 — погашено (или тёплая нода погашена с проверкой «0 нод»), 1 — остановка не подтверждена, 3 — отказ: нода занята прогоном или у неё чужая метка владельца."""
    name = f'{PREFIX}-{a.suffix}'
    status, msg = KD.warm_stop(getattr(a, 'warm_dir', '') or KD.WARM_DIR, name, stop, getattr(a, 'warm_owner', '') or '')
    say(f'{name}: {msg}')
    return {'stopped': 0, 'failed': 1, 'refused': 3}[status]


def warm_release_cmd(a, stop) -> int:
    """`--warm-release --warm-owner X`: погасить тёплые ноды прогона X (метка владельца). 0 — всё свои погашены или своих нет, 1 — остановка не подтверждена."""
    res = KD.warm_release(getattr(a, 'warm_dir', '') or KD.WARM_DIR, getattr(a, 'warm_owner', '') or '', stop)
    for name, status, msg in res:
        say(f'тёплая нода {name}: {msg}')
    say(f'warm-release: погашено {sum(1 for r in res if r[1] == "stopped")} из {len(res)} (владелец {getattr(a, "warm_owner", "") or "—"})')
    return 1 if any(r[1] == 'failed' for r in res) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: имя@sha256:digest (по тегу — отказ, ADR-0137)')
    ap.add_argument('--inputs', default='', help='inputs.json: {товар: {glb, photo, pose_run, body_only}}')
    ap.add_argument('--stages', default='06,07', help='какие этапы гнать: 06,07 | 07 (только заливка по готовому 06 — нужен --vis-root)')
    ap.add_argument('--vis-root', default='', help='папка с <товар>/06-visible/ (вход 07 при --stages 07)')
    ap.add_argument('--fill-root', default='', help='папка с <товар>/07-fill/ (вход шва при --stages seam; 06-visible — из --vis-root)')
    ap.add_argument('--code-ref', default='HEAD', help='SHA/ветка, чей код этапов едет в задании (code.tar из git archive; по умолчанию HEAD дерева драйвера)')
    ap.add_argument('--repo', default=ROOT, help='корень репозитория для git archive')
    ap.add_argument('--no-code-check', action='store_true', help='не проверять импорт точек входа из чистой распаковки (только если нет библиотек этапов)')
    ap.add_argument('--skus', default='', help='при --vis-root: только эти товары (по умолчанию все с готовым 06)')
    ap.add_argument('--parts-root', default='', help='корень частей PartLLM `<товар>/03-parts/parts.npz` (parts_to_npz.py convert): едет в задание 07; источник зон — флаг zones_from')
    ap.add_argument('--catalog', default='', help='этап 08: выгрузка каталога [{sid,name,role,params}] (catalog_all.json) — из неё product.json товара')
    ap.add_argument('--pose-root', default='', help='этап 08: папки (через запятую) с <товар>/04-camera/check.json (камера этапа 4; допускается уровень g0/g1/g2); у товара может быть и поле pose_run')
    ap.add_argument('--allow-no-card', action='store_true', help='07 без карточек ни у одного товара (верх Ш3в не красится); по умолчанию — отказ до создания группы')
    ap.add_argument('--zones-from', default='', choices=['', 'parts', 'panels'], help='перебить rules/paint-fill.json zones_from (пусто — как в правилах)')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t189-1122/salad-out'))
    ap.add_argument('--card', default=CARD_NAME, help='класс Salad из профиля cpu_stage (запасные — в профиле)')
    ap.add_argument('--tier', default='low', choices=['low'], help='только low (владелец 24.11, TG 2626); medium, batch и high запрещены')
    ap.add_argument('--procs', type=int, default=0, help='заданий одновременно на ноде; 0 — по размеру ноды (NODE_DEFAULTS: low 4, big 4)')
    ap.add_argument('--variant', default=None, choices=['low', 'big'], help='размер ноды из профиля cpu_stage: low = 4 vCPU / 8 ГБ, big = 8 vCPU / 16 ГБ. Не задан — по пакету (T-20261124-09): ≥2 товаров → big, один товар → low. Тёплой ноде другого размера — своё имя (--suffix)')
    ap.add_argument('--fill-procs', type=int, default=0, help='из них этапа 07; 0 — по размеру ноды (NODE_DEFAULTS: low 2 — пик 07 ≈3 ГБ при 8 ГБ ноды, big 4 — 4×3,3 ≈13 ГБ из 16)')
    ap.add_argument('--threads', type=int, default=1, help='потоков BLAS/OpenMP на одно задание')
    ap.add_argument('--stage-timeout-s', type=int, default=900)
    ap.add_argument("--stuck-min", type=float, default=30.0, help="сторож «завис»: шаг не менялся и GPU<5 %% дольше N мин → гашу; для CPU-этапов 06/07 GPU всегда ≈0, считают долго (07 с ничьей — до 10 мин на товар на 0,12 ядра): 30; 0 — выкл")
    ap.add_argument('--probe-cap', type=float, default=1.0, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=1.0, help='общий потолок, $')
    ap.add_argument('--max-min', type=int, default=60)
    ap.add_argument('--running-min', type=int, default=30)
    ap.add_argument('--health-min', type=int, default=8)
    ap.add_argument('--start-min', type=int, default=20)
    ap.add_argument('--ready-min', type=int, default=30)
    ap.add_argument('--stall-min', type=int, default=5)
    ap.add_argument('--stall-gb', type=float, default=0.05)
    ap.add_argument('--job-min', type=int, default=0)
    ap.add_argument('--idle-s', type=int, default=900)
    ap.add_argument('--keep-warm', type=float, default=0.0, help='T-34: не гасить ноду после прогона — она сама остановится через N мин простоя (воркер IDLE_S); следующий прогон с тем же --suffix и образом подхватит её без прогрева (0 — как раньше)')
    ap.add_argument('--warm-life-min', type=float, default=120.0, help='с --keep-warm: предел жизни воркера, мин (MAX_LIFETIME_S); подхват ноды, у которой осталось меньше --warm-min-left-min, — перезапуск')
    ap.add_argument('--warm-min-left-min', type=float, default=25.0)
    ap.add_argument('--warm-dir', default='', help='папка записей и замков тёплых нод (по умолчанию ~/remlab-logs/warm-nodes)')
    ap.add_argument('--worker-from-image', action='store_true')
    ap.add_argument('--suffix', default='', help='суффикс имени группы; не задан — время + `-v<версия воркера>` (T-58/3: по имени группы видно, какой воркер внутри)')
    ap.add_argument('--series', default='', help='T-58/3: ключ серии (loop5 — его run-id; не задан — --warm-owner или имя папки --queue). Штатный стоп серии (--stop-series КЛЮЧ) пишет метку: '
                                                 'драйвер читает её перед каждым созданием группы и на каждом шаге цикла, гасит свои группы с проверкой «0 нод» и выходит сам')
    ap.add_argument('--stop-series', default='', metavar='КЛЮЧ', help='T-58/3: штатный стоп серии КЛЮЧ — записать метку и выйти; живые драйверы серии сами погасят свои группы (ни kill, ни pkill)')
    ap.add_argument('--stop-reason', default='', help='с --stop-series: причина в метке')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--queue', default='', help='T-34: общая очередь товаров (папка): все ноды-процессы берут из неё товар, как освободился слот, и ведут его по всем --stages без барьера; '
                                                'очередь наполняется из --inputs (повторно — не дублирует); с --suffix каждой ноды разный')
    ap.add_argument('--slots', type=int, default=0, help='с --queue: товаров в работе на ноде одновременно (0 = --fill-procs)')
    ap.add_argument('--nodes', type=int, default=0, help='с --queue: сколько нод делят очередь; потолок товаров на ноду = ceil(товаров/нод) (0 — без потолка, только --slots)')
    ap.add_argument('--requeue-max', type=int, default=1, help='с --queue: сколько раз упавший товар возвращается в очередь (другая нода) до окончательного отказа')
    ap.add_argument('--stop-only', action='store_true', help='погасить группу `--suffix`; тёплую ноду с записью — только если не занята прогоном и (при --warm-owner) метка владельца совпадает; иначе отказ, код 3')
    ap.add_argument('--warm-owner', default='', help='метка владельца тёплой ноды (loop5 — его run-id): ставится при создании/подхвате; с --stop-only/--warm-release чужую метку не гасим')
    ap.add_argument('--warm-release', action='store_true', help='конец прогона: погасить тёплые ноды с меткой --warm-owner (ровно свои; подхваченные другим прогоном не трогает)')
    ap.add_argument('--sweep-warm', action='store_true', help='T-34: погасить тёплые ноды, которым пора (предел жизни вышел или простой > idle_min по записи ~/remlab-logs/warm-nodes); занятые прогоном не трогает')
    a = ap.parse_args()
    a.variant_given = a.variant is not None
    if a.stop_series:
        mod = KD._sc()
        if mod is None:
            sys.exit('ворота предела недоступны — метку стопа серии не записать')
        say(f'стоп серии {a.stop_series}: метка {mod.series_stop(a.stop_series, reason=a.stop_reason)}; драйверы серии погасят свои группы и выйдут сами')
        return 0
    a.series = a.series or a.warm_owner or (os.path.basename(os.path.normpath(os.path.expanduser(a.queue))) if a.queue else '')
    a.suffix = a.suffix or (time.strftime('%m%d%H%M', time.gmtime()) + (f'-v{KD.worker_version(a.image, WORKER)}' if a.image else ''))
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return stop_only(a, lambda n: KD.stop_and_verify(BR, n))
    if a.warm_release:
        MG.env_from_file()
        return warm_release_cmd(a, lambda n: KD.stop_and_verify(BR, n))
    if a.sweep_warm:                                                               # T-34: воркер при простое выходит, но Salad его поднимает заново — гасим тёплые ноды сами
        MG.env_from_file()
        res = KD.warm_sweep(KD.WARM_DIR, time.time(), lambda n: KD.stop_and_verify(BR, n))
        for name, why, ok in res:
            say(f'тёплая нода {name}: {why} → {"погашена" if ok else "❗ ОСТАНОВКА НЕ ПОДТВЕРЖДЕНА"}')
        say(f'sweep-warm: погашено {sum(1 for r in res if r[2])} из {len(res)}')
        return 0 if all(r[2] for r in res) else 1
    st_ = stages_of(a)
    only07 = st_ in (['07'], ['07', 'seam'], ['07', 'seam', '08'])                 # 07 по готовому 06 (и шов, и 08 сразу за ним: вход — выход предыдущего из --out, одним пакетом)
    from_fill = st_ in (['seam'], ['08'], ['seam', '08'])                          # по готовым 06 и 07: товары — папки `<fill-root>/<товар>/07-fill/filled.glb` + `<vis-root>/<товар>/06-visible/known.png`
    if not a.image or not (a.inputs or (a.vis_root and only07) or (a.vis_root and a.fill_root and from_fill)):
        sys.exit('нужны --image и --inputs (или --stages 07[,seam[,08]] --vis-root, или --stages seam|08|seam,08 --fill-root --vis-root)')
    if '08' in st_ and not a.catalog:
        sys.exit('этапу 08 нужен --catalog (выгрузка каталога [{sid,name,role,params}]): из неё берётся product.json товара')
    if a.inputs and a.vis_root and only07:
        sys.exit('--inputs и --vis-root вместе не нужны: у товара в inputs.json может быть поле "vis"')
    inputs = load_inputs(a.inputs) if a.inputs else (seam_inputs(a.fill_root, a.vis_root, a.skus) if from_fill else vis_inputs(a.vis_root, a.skus))
    if not inputs:
        sys.exit('нет товаров для пакета')
    if '07' in stages_of(a):
        no_card, no_photo = top_input_problems(inputs)
        say(f'вход 07 для верха Ш3в: карточка у {len(inputs) - len(no_card)} из {len(inputs)}, фото у {len(inputs) - len(no_photo)}; без карточки: {no_card[:10]}{"…" if len(no_card) > 10 else ""}')
        if len(no_card) == len(inputs) and not a.allow_no_card:
            sys.exit('ни у одного товара нет карточки (card.json): Ш3в-верх не сработает нигде (тихий as_before). Собери вход через make_inputs_07.py или передай --allow-no-card')
    if a.parts_root:
        mode = a.zones_from or PN.zones_mode()
        zl = attach_parts(inputs, os.path.expanduser(a.parts_root), a.vis_root or a.out, mode)
        os.makedirs(a.out, exist_ok=True)
        json.dump({'zones_from': mode, 'skus': zl}, open(os.path.join(a.out, 'zones-07.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        say(f'зоны 07: zones_from={mode}, parts у {sum(1 for z in zl.values() if z["source"] == "parts")} из {len(zl)}; без parts: ' + str({k: z['reason'] for k, z in zl.items() if z['source'] != 'parts'})[:300])
    if '06' in st_ and a.catalog:
        rep06 = attach_06(inputs, os.path.expanduser(a.catalog), a.out)
        os.makedirs(a.out, exist_ok=True)
        json.dump(rep06, open(os.path.join(a.out, 'inputs-06.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        say(f'вход 06: роль (для «зад корпусной») у {sum(1 for r in rep06.values() if r["product"])} из {len(rep06)}')
    if '08' in st_:
        rep08 = attach_08(inputs, os.path.expanduser(a.catalog), a.out)
        os.makedirs(a.out, exist_ok=True)
        json.dump(rep08, open(os.path.join(a.out, 'inputs-08.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        say(f'вход 08: product.json у {sum(1 for r in rep08.values() if r["product"])} из {len(rep08)}, части (parts.npz) у {sum(1 for r in rep08.values() if r["parts"])}, фото у {sum(1 for r in rep08.values() if r["photo"])}')
    if a.queue:
        q = CQ.Queue(os.path.expanduser(a.queue))
        added = q.fill(inputs)                                                        # строки с уже готовыми extra_in (части, product.json): все ноды кладут одно и то же, дубля нет
        say(f'очередь {a.queue}: добавлено {added}, состояние {q.counts()}')
        if not q.todo():
            say('очередь пуста — нечего считать, группу не создаю')
            return 0
    a.variant, a.procs, a.fill_procs = resolve_node(getattr(a, 'variant', None), a.procs, a.fill_procs, len(inputs))
    say(f'нода: {a.variant or "low"} ({"8 vCPU / 16 ГБ" if a.variant == "big" else "4 vCPU / 8 ГБ"}), заданий {a.procs}, из них этапа 07 — {a.fill_procs}; пакет из {len(inputs)} товаров' + ('' if getattr(a, 'variant_given', False) else ' (размер выбран по пакету: ≥2 → big, один → low)'))
    return KD.run_probe(a, MG, BR, make_spec(a, inputs))


if __name__ == '__main__':
    sys.exit(main())
