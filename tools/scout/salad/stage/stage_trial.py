#!/usr/bin/env python3
"""ПРОБА SALAD «ЭТАПЫ 06/07» (T-189/1): перенос фото на форму (06) и заливка невидимого (07) на ноде Salad по профилю `cpu_stage` (rules/salad-resources.json). Драйвер — на общем наборе
(`kit_driver.run_probe`): деньги, потолок, гашение и проверка «0 нод» — там; здесь только «что отправить и как забрать». Одна группа, два прохода: ключ `06` (все товары, до STAGE_PROCS
одновременно) → результаты 06 забираем → ключ `07` (вход — выход 06 того же товара; до STAGE_FILL_PROCS одновременно). Считает тот же код, что у нас локально (в образе, `stage_files.txt`).

Запуск (платный, только под heavy-slot --prio 2, одна группа на пакет, потолок $1):
  heavy-slot.sh t189-stage-probe --prio 2 -- python stage_trial.py --image ghcr.io/…/mesh-stage-trial@sha256:… --inputs inputs.json --apply
Без --apply — только разбор: тело группы без секретов, проверка образа и входов (группа НЕ создаётся). `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
Тариф: low; нет машин → medium (автоматически, ядро набора); batch и high запрещены (владелец 22.11, TG 1456/1457).
КОД ЭТАПА ЕДЕТ В ЗАДАНИИ (T-193/1/1): драйвер собирает `code.tar` из `git archive <SHA>` (`code_tar.py`; `--code-ref`, по умолчанию HEAD этого дерева), кладёт его во вход каждого задания и шлёт `code_sha` +
`code_tar_sha256`; воркер считает ИМЕННО этот код (образ — только среда), в ответе `code_sha`/`_code.json` — сверяется. Срез проверяется до платной группы (импорт точек входа из чистой распаковки).
Входы — файл `inputs.json`: {"<товар>": {"glb": путь, "photo": путь RGBA-вырезки, "pose_run": папка камеры этапа 4, "body_only": false}} (список — аргументом, в код не зашит).
Только этап 07 по готовому 06: `--stages 07 --vis-root <папка с <товар>/06-visible/>` (без `--inputs`; товары — все папки с visible.glb и check.json, сузить — `--skus a,b`): вход 07 берётся оттуда, выход — в `--out`.
07 и шов одним пакетом: `--stages 07,seam --vis-root …` (шов берёт выход 07 из `--out` сразу после того, как 07 всех товаров готов).
Только шов «фото | заливка» (T-196/1) по готовым 06 и 07: `--stages seam --fill-root <папка с <товар>/07-fill/> --vis-root <папка с <товар>/06-visible/>` → `<out>/<товар>/07-seam/`.
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
from kit_driver import Gateway, say  # noqa: E402

CARD_NAME = 'GTX 1650 (4 GB)'                                  # из профиля cpu_stage: самая дешёвая карта (видеокарта этапам не нужна, у Salad нет класса без неё)
WORK_TYPE = 'cpu_stage'
PORT = 8000
WORKER = os.path.join(HERE, 'worker_stage.py')
PREFIX = 'trial-stage'
MAX_POSE_RUN_MB = 50


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    return KW.bundle(path or WORKER)


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, procs: int, fill_procs: int, threads: int, timeout_s: int,
               worker_z: str | None = None) -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'STAGE_PROCS': str(procs), 'STAGE_FILL_PROCS': str(fill_procs), 'STAGE_THREADS': str(threads),
           'STAGE_TIMEOUT_S': str(timeout_s), 'DEPLOYMENT_EPOCH': f'20261122-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE)


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
            p = os.path.join(dp, f)
            total += os.path.getsize(p)
            if limit_mb and total > limit_mb * 2 ** 20:
                raise ValueError(f'{src}: больше {limit_mb} МБ — похоже, не та папка')
            z.write(p, f'{prefix}/{os.path.relpath(p, src)}')
    return total


def add_extras(z: zipfile.ZipFile, v: dict, code_tar: bytes | None) -> None:
    """Общее для всех входов: `code.tar` (код задания) и доп. файлы товара `extra_in` {имя во входе: локальный путь} (карты зон и т. п.; в `args` — `@in/<имя>`)."""
    if code_tar:
        z.writestr('code.tar', code_tar)
    for rel, path in sorted((v.get('extra_in') or {}).items()):
        z.write(path, rel)


def input_zip_06(v: dict, code_tar: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        z.write(v['glb'], 'model.glb')
        z.write(v['photo'], 'photo.png')
        zip_dir_into(z, v['pose_run'], 'pose_run', MAX_POSE_RUN_MB)
        add_extras(z, v, code_tar)
    return buf.getvalue()


def input_zip_07(vis_dir: str, code_tar: bytes | None = None, v: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        zip_dir_into(z, vis_dir, '06-visible')
        add_extras(z, v or {}, code_tar)
    return buf.getvalue()


def input_zip_seam(vis_dir: str, fill_dir: str, code_tar: bytes | None = None, v: dict | None = None) -> bytes:
    """Вход шва (T-196/1): `06-visible/` (known*.png, conf*.png; visible.glb не нужен — не кладём) и `07-fill/filled.glb` (выход 07 того же товара)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for n in sorted(os.listdir(vis_dir)):
            if n.endswith('.png') and (n.startswith('known') or n.startswith('conf')):
                z.write(os.path.join(vis_dir, n), f'06-visible/{n}')
        z.write(os.path.join(fill_dir, 'filled.glb'), '07-fill/filled.glb')
        add_extras(z, v or {}, code_tar)
    return buf.getvalue()


def job_id(stage: str, sku: str, data: bytes, a) -> str:
    """Идемпотентный id: этап + товар + хеш входа + параметры — повтор после вытеснения ноды не плодит дубль."""
    h = hashlib.sha256(data + json.dumps([stage, a.threads], sort_keys=True).encode()).hexdigest()[:12]
    return f'{stage}-{sku}-{h}'.replace('_', '-')[:150]


def stage_dirname(stage: str) -> str:
    return {'06': '06-visible', 'seam': '07-seam'}.get(stage, '07-fill')


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
        else:
            vis = v.get('vis') or os.path.join(getattr(a, 'vis_root', '') or a.out, sku, '06-visible')
            if not os.path.isfile(os.path.join(vis, 'visible.glb')):
                skipped[sku] = 'нет выхода этапа 06 — 07 не запускался'
                continue
            data = input_zip_07(vis, code.get('tar'), v)
        jid = job_id(stage, sku, data, a)
        body = {'job_id': jid, 'stage': stage, 'sku': sku, 'input_z': base64.b64encode(zlib.compress(data, 6)).decode(), 'body_only': bool(v.get('body_only')) and stage == '06',
                'code_sha': code.get('sha', ''), 'code_tar_sha256': code.get('tar_sha256', '')}
        if v.get('args'):
            body['args'] = list(v['args'])
        c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        if c == -1:                                                                       # воркер задания не видит; job_id идемпотентен — один повтор, дубля не будет
            say(f'товар {sku}: POST без ответа, воркер задания не видит — повтор один раз')
            c, r, _tinfo = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'этап {stage} товар {sku}: POST /jobs → {c} (тело ≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ)', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'sku': sku, 'accepted': list(ids), 'post': _tinfo, 'reason': (_tinfo or {}).get('reason')}
        ids[sku] = jid
    if not ids:
        return None, {'detail': 'нечего отправлять: ' + json.dumps(skipped, ensure_ascii=False)}
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
    if running:
        return 'running', {}
    for sku, why in cur.get('skipped', {}).items():
        items[sku] = {'status': 'skipped', 'error': why}
    fails = {k: v for k, v in items.items() if v['status'] == 'failed'}
    ok = sum(1 for v in items.values() if v['status'] == 'done')
    info = {'items': items, 'ok': ok, 'total': len(items), 'metrics': {'ok': ok, 'total': len(items), 'failed': {k: v.get('error') for k, v in fails.items()}}}
    if stage == '07':
        info['metrics']['top'] = top_counts(items)
        say(f'верх Ш3в по товарам 07 (счётчик причин): {info["metrics"]["top"]}')
    os.makedirs(a.out, exist_ok=True)
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


def make_spec(a, inputs: dict) -> KD.Spec:
    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, auth, min(a.max_min * 60 + 600, 3 * 3600), a.idle_s, a.procs, a.fill_procs, a.threads, a.stage_timeout_s,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1])

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
        if stages_of(a) == ['seam']:
            bad += [f'{s}: нет 07-fill/filled.glb или 06-visible/known.png' for s, v in inputs.items()
                    if not os.path.isfile(os.path.join(v.get('fill') or os.path.join(getattr(a, 'fill_root', ''), s, '07-fill'), 'filled.glb'))
                    or not os.path.isfile(os.path.join(v.get('vis') or os.path.join(getattr(a, 'vis_root', ''), s, '06-visible'), 'known.png'))]
        elif '06' not in stages_of(a):
            root = getattr(a, 'vis_root', '')
            bad += [f'{s}: нет {(v.get("vis") or os.path.join(root, s, "06-visible"))}/visible.glb' for s, v in inputs.items()
                    if not os.path.isfile(os.path.join(v.get('vis') or os.path.join(root, s, '06-visible'), 'visible.glb'))]
        if bad:
            return False, f'входы не готовы: {bad[:4]}'
        return True, f'входы на месте: {len(inputs)} товаров'

    return KD.Spec(prefix=PREFIX, card=a.card, model='cpu-stage', jobs=stages_of(a), build_body=build, submit=lambda gw, k, t: submit_stage(gw, a, inputs, k, t),
                   poll=lambda gw, cur, t: poll_stage(gw, a, cur, t), preflight=preflight, ready_keys=('version', 'libs', 'procs', 'fill_procs'), z_keys=('KIT_WORKER_Z',),
                   worker_file=WORKER, work_type=WORK_TYPE)


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
    ap.add_argument('--allow-no-card', action='store_true', help='07 без карточек ни у одного товара (верх Ш3в не красится); по умолчанию — отказ до создания группы')
    ap.add_argument('--zones-from', default='', choices=['', 'parts', 'panels'], help='перебить rules/paint-fill.json zones_from (пусто — как в правилах)')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t189-1122/salad-out'))
    ap.add_argument('--card', default=CARD_NAME, help='класс Salad из профиля cpu_stage (запасные — в профиле)')
    ap.add_argument('--tier', default='low', choices=['low', 'medium'], help='low; нет машин → medium (автоматически); batch и high запрещены правилом владельца 22.11')
    ap.add_argument('--procs', type=int, default=4, help='заданий одновременно на ноде (по профилю: 4 vCPU)')
    ap.add_argument('--fill-procs', type=int, default=2, help='из них этапа 07 (пик памяти до 9 ГБ при 8 ГБ ноды — вариант А директора 22.11)')
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
    ap.add_argument('--worker-from-image', action='store_true')
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if KD.stop_and_verify(BR, f'{PREFIX}-{a.suffix}') else 1
    st_ = stages_of(a)
    only07 = st_ in (['07'], ['07', 'seam'])                                       # 07 по готовому 06 (и шов сразу за ним: вход шва — выход 07 из --out, одним пакетом)
    if not a.image or not (a.inputs or (a.vis_root and only07) or (a.vis_root and a.fill_root and st_ == ['seam'])):
        sys.exit('нужны --image и --inputs (или --stages 07[,seam] --vis-root, или --stages seam --fill-root --vis-root)')
    if a.inputs and a.vis_root and only07:
        sys.exit('--inputs и --vis-root вместе не нужны: у товара в inputs.json может быть поле "vis"')
    inputs = load_inputs(a.inputs) if a.inputs else (seam_inputs(a.fill_root, a.vis_root, a.skus) if st_ == ['seam'] else vis_inputs(a.vis_root, a.skus))
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
    return KD.run_probe(a, MG, BR, make_spec(a, inputs))


if __name__ == '__main__':
    sys.exit(main())
