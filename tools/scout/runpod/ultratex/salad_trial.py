#!/usr/bin/env python3
"""ДРАЙВЕР ПРОБЫ UltraTex НА SALAD, карта RTX 5090 (32 ГБ) — T-20261121-178/1; с 21.11 (T-178/2) на ОБЩЕМ НАБОРЕ Salad: охрана денег, ожидание образа, сторожа, гашение и учёт — `kit_driver.py`, здесь только функция модели.
(владелец TG 841: «запускают и на 16 ГБ»; директор: Salad 5090, потолок $1 на пробу, $4 всего, prio 2). Одна ВРЕМЕННАЯ группа `trial-ultratex-<метка>` (1 нода, воркер с `ULTRATEX_OFFLOAD=swap`): форма + фото → GLB с текстурой UltraTex.

    salad_trial.py --image <имя@sha256:digest> --jobs <ключ>[,<ключ>…] --shape-dir … --inputs … --out …        # разбор: тело группы без секретов, проверка образа, группа НЕ создаётся
    heavy-slot.sh <метка> --prio 2 -- salad_trial.py … --apply                                               # создать, прогнать по очереди, ПОГАСИТЬ и проверить 0 нод
    salad_trial.py --stop-only --suffix <метка>

Платное — ТОЛЬКО под `heavy-slot --prio 2` (драйвер сам проверяет), образ — только по digest, сжатый ≤ 35 ГиБ (kit_driver.MAX_IMAGE_GIB) (манифест, бесплатно). ПРЕДОХРАНИТЕЛИ — `kit_driver.Watch`: потолок `--probe-cap` ($1) до первого готового
задания, затем `--cap` ($4); деньги — по времени `running` × ЖИВАЯ цена; `--running-min` выдача ноды, `--start-min` запуск контейнера, `--health-min` без /health, `--ready-min` прогрев, `--stall-min` докачка, `--job-min` задание,
2 неудачи подряд — стоп; ИТОГ, «стоп с проверкой stopped» и строка в общий учёт денег — всегда. Допуск к закрытым весам FLUX.2 (HEAD с токеном) — ДО создания группы. Ключи Salad и HF — из `~/scout-scenes/salad.env`.
Образ С ВЕСАМИ (сборка 22.11 `build-ultratex-weights`, run 45010968680): `ghcr.io/igortsk123/mesh-ultratex-trial@sha256:64532605855c623d5dfb3df7081b08e31005ccc4a09d4446783aa3dbe6940aa4` — 28 слоёв, сжатый 20,88 ГиБ (≤35), крупнейший слой 3,9; DiT+AE+LoRA вшиты, Qwen3-8B нет (пустой текст — `text-cache/`, посчитан на ЦП; контроль k2 — перед пакетом).
В метриках задания (из воркера): `vram_peak_gb`, `vram_phases_gb`, `sample_s`, `offload_moves_s`, `sparse`, `total_s`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..', '..', 'salad'))
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'render_gpu')))     # bench_run (group_state/instances/stop_and_verify)
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
from kit_driver import Gateway, cost_usd, effective_cap, head, safe_print, say, weights_stalled  # noqa: E402,F401 — имена прежнего драйвера (тесты, вызовы)

CARD_NAME = 'RTX 5090 (32 GB)'
CUDA_ARCHS = ('12.0',)          # образ ultratex-bw: torch 2.8.0 cu128 (как trellis2-bw, sm_120 там проверен); не та карта → отказ до группы (урок 742)
PORT = 8000
MODEL_HEADS = (
    'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B/resolve/main/flux-2-klein-base-9b.safetensors',
    'https://huggingface.co/black-forest-labs/FLUX.2-dev/resolve/main/ae.safetensors',
)
READINESS, STARTUP = KD.probes(PORT)


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    """Код воркера → (command, сжатый код для env KIT_WORKER_Z): модуль набора `kit_worker` + файл модели; образ при правках воркера не пересобирается."""
    return KW.bundle(path or os.path.join(HERE, 'worker_ultratex.py'))


def build_body(name: str, image: str, tier: str, class_id: str, cpu: int, mem_mb: int, auth: dict, hf_token: str, life_s: int, idle_s: int, worker_z: str | None = None,
               diag: bool = False, extra_env: dict | None = None) -> dict:
    env = {'ULTRATEX_OFFLOAD': 'swap', 'ULTRATEX_SPARSE': 'auto', 'ULTRATEX_ROOT': '/workspace/ultratex', 'PORT': str(PORT), 'HF_TOKEN': hf_token,
           'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'NVIDIA_DRIVER_CAPABILITIES': 'all', 'DEPLOYMENT_EPOCH': f'20261121-{name}'}
    if diag:                                                   # диагностика карты: веса не нужны (ни скачивания, ни ключа HF)
        env.pop('HF_TOKEN')
        env['ULTRATEX_NO_WEIGHTS'] = '1'
    env.update(extra_env or {})
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env,
                         {'cpu': cpu, 'memory': mem_mb, 'storage_amount': (20 if diag else 80) * 2 ** 30, 'shm_size': 2048},     # 80 ГиБ: веса в образе ≈18 без Qwen3-8B (его заменяет text-cache) + запас
                         auth, command)


def lookup_class(MG, name: str, tier: str) -> tuple[str | None, float | None]:
    return KD.gpu_class(MG, name, tier)


def parse_jobs(spec: str) -> list[str]:
    return [x.strip() for x in spec.split(',') if x.strip()]


JOB_PARAM_KEYS = ('resolution', 'steps', 'guidance', 'seed', 'texture_size')


def split_job(job: str) -> tuple[str, str]:
    """Задание `<товар>` или `<товар>@<вариант>` → (товар, вариант). Вариант — имя из --variants: тот же товар считается несколько раз с разными параметрами (пара «штатно | лёгкий»)."""
    prod, _, var = job.partition('@')
    return prod, var


def parse_variants(spec) -> dict:
    """--variants: JSON-файл или строка `{"имя": {resolution?, steps?, guidance?, seed?, texture_size?}}`; пусто → {}. Лишний ключ или не число — отказ ДО группы и денег."""
    if not spec:
        return {}
    raw = open(os.path.expanduser(spec), encoding='utf-8').read() if os.path.exists(os.path.expanduser(spec)) else spec
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise SystemExit(f'--variants: не JSON ({e})')
    if not isinstance(d, dict):
        raise SystemExit('--variants: нужен объект {"имя": {параметры}}')
    for name, v in d.items():
        bad = [k for k in v if k not in JOB_PARAM_KEYS] if isinstance(v, dict) else ['не объект']
        if bad or not name.replace('-', '').replace('_', '').isalnum():
            raise SystemExit(f'--variants {name}: ключи только {JOB_PARAM_KEYS}, имя из букв/цифр/-/_; лишнее: {bad}')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v.values()):
            raise SystemExit(f'--variants {name}: значения — числа')
    return d


def job_params(a, variants: dict, job: str) -> dict:
    """Параметры /generate для задания: общие из --resolution/--steps/--seed/--texture, поверх — переопределения варианта (если у задания есть @вариант)."""
    base = {'resolution': a.resolution, 'steps': a.steps, 'seed': a.seed, 'texture_size': a.texture}
    var = split_job(job)[1]
    if var:
        if var not in variants:
            raise SystemExit(f'задание «{job}»: варианта «{var}» нет в --variants {sorted(variants)}')
        base.update(variants[var])
    return base


def parse_env(items) -> dict:
    """--env K=V (повторяемый): переменные воркера для группы — ULTRATEX_MEM_CHUNK, ULTRATEX_CFG, ULTRATEX_VRAM_FRAC…; секретов сюда не кладём."""
    out = {}
    for it in items or []:
        k, _, v = it.partition('=')
        if not (k.startswith('ULTRATEX_') or k == 'PYTORCH_CUDA_ALLOC_CONF') or not _:
            raise SystemExit(f'--env только ULTRATEX_*=значение или PYTORCH_CUDA_ALLOC_CONF=значение, получено «{it}»')
        out[k] = v
    return out


def make_diag_spec(a) -> KD.Spec:
    """Диагностика карты БЕЗ весов: одно задание POST /diag (слив VRAM, ядро на реальных длинах, DiT на случайных весах). Прогрев — секунды, не 26 минут."""
    params = json.loads(a.diag_params) if a.diag_params else {}

    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, a.cpu, a.mem_mb, auth, '', min(a.max_min * 60 + 600, 3 * 3600), a.idle_s,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1], diag=True, extra_env=parse_env(getattr(a, 'env', None)))

    def submit(gw, k, t):
        jid = f'diag-{int(t)}'
        c, r = gw.call('POST', '/diag', dict(params, job_id=jid), timeout=60)
        say(f'диагностика: POST /diag → {c}', str(r)[:120] if c != 202 else '')
        return ({'key': k, 'id': jid, 't0': t}, {}) if c == 202 else (None, {'http': c, 'detail': r})

    def poll(gw, cur, t):
        c, r = gw.call('GET', f'/result/{cur["id"]}', timeout=30)
        if c == 200 and r.get('status') == 'done':
            os.makedirs(a.out, exist_ok=True)
            json.dump(r.get('metrics'), open(os.path.join(a.out, 'diag.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            return 'done', {'metrics': r.get('metrics')}
        if c == 200 and r.get('status') == 'failed':
            if r.get('metrics'):                                           # частичные итоги прошедших частей (d1 21.11: сбой одной части стёр остальное)
                os.makedirs(a.out, exist_ok=True)
                json.dump(r.get('metrics'), open(os.path.join(a.out, 'diag-partial.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            return 'failed', {'status': 'failed', 'error': r.get('error'), 'trace': r.get('trace'), 'metrics': r.get('metrics')}
        return 'running', {}

    return KD.Spec(prefix='trial-ultratex', card=CARD_NAME, model='ultratex-diag', jobs=['diag'], build_body=build, submit=submit, poll=poll, preflight=None,
                   ready_keys=('version', 'offload', 'sparse'), z_keys=('KIT_WORKER_Z',), worker_file=os.path.join(HERE, 'worker_ultratex.py'), cuda_archs=CUDA_ARCHS)


def make_spec(a, head_fn=head) -> KD.Spec:
    if getattr(a, 'diag', False):
        return make_diag_spec(a)
    jobs = parse_jobs(a.jobs)
    variants = parse_variants(getattr(a, 'variants', ''))
    unknown = sorted({split_job(j)[1] for j in jobs} - set(variants) - {''})
    if unknown:
        raise SystemExit(f'задания с вариантами {unknown}: нет в --variants {sorted(variants)}')      # отказ до группы и денег
    hf = os.environ.get('HF_TOKEN', '')

    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, a.cpu, a.mem_mb, auth, os.environ.get('HF_TOKEN', ''), min(a.max_min * 60 + 600, 3 * 3600), a.idle_s,
                          worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1], extra_env=dict(parse_env(getattr(a, 'env', None)), **({'ULTRATEX_DIAG_FIRST': '1'} if getattr(a, 'diag_first', False) else {})))

    def preflight():
        missing = [k for k in jobs for pk in [split_job(k)[0]] for p in (os.path.join(a.shape_dir, a.shape_name.format(key=pk)), os.path.join(a.inputs, f'{pk}.rgba.png')) if not os.path.exists(p)]
        if missing:
            return False, f'нет входных файлов: {missing[:4]}'
        token = os.environ.get('HF_TOKEN', hf)
        bad = [(u.split('/resolve')[0].split('huggingface.co/')[1], c) for u in MODEL_HEADS for c in [head_fn(u, token)] if c not in (200, 302)]
        return (not bad), ('допуск к закрытым весам FLUX.2: есть' if not bad else f'допуска к весам FLUX.2 НЕТ {bad}')

    def submit(gw, k, t):
        pk = split_job(k)[0]
        glb = open(os.path.join(a.shape_dir, a.shape_name.format(key=pk)), 'rb').read()
        png = open(os.path.join(a.inputs, f'{pk}.rgba.png'), 'rb').read()
        jid = f'{k}-{int(t)}'.replace('_', '-').replace('@', '-')[:150]
        c, r, pt = KD.post_job(gw, '/generate', dict({'job_id': jid, 'image_b64': base64.b64encode(png).decode(), 'glb_b64': base64.b64encode(glb).decode()}, **job_params(a, variants, k)),
                               f'/result/{jid}', getattr(a, 'post_timeout', 0))        # таймаут по размеру тела; -1 → сперва спросить воркера (kit_driver.post_job)
        say(f'задание {k}: POST /generate → {c}', str(r)[:120] if c != 202 else '')
        return ({'key': k, 'id': jid, 't0': t, 'post': pt}, {}) if c == 202 else (None, {'http': c, 'detail': r, 'post': pt})

    def poll(gw, cur, t):
        c, r = gw.call('GET', f'/result/{cur["id"]}', timeout=30)
        if c == 200 and r.get('status') == 'done':
            c2, data = gw.call('GET', f'/result/{cur["id"]}/glb', timeout=300, raw=True)
            if c2 == 200 and data:
                path = os.path.join(a.out, f'{cur["key"]}.ultratex.glb')
                open(path, 'wb').write(data)
                json.dump(r.get('metrics'), open(os.path.join(a.out, f'{cur["key"]}.metrics.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                return 'done', {'glb': path, 'bytes': len(data), 'metrics': r.get('metrics')}
            return 'failed', {'status': 'glb_not_received', 'http': c2}
        if c == 200 and r.get('status') == 'failed':
            return 'failed', {'status': 'failed', 'error': r.get('error'), 'trace': r.get('trace')}
        return 'running', {}

    sent = [0]
    hold = {'t0': None}
    _submit = submit

    def submit(gw, k, t):                                              # noqa: F811 — считаем отправленные для затвора контроля
        sent[0] += 1
        return _submit(gw, k, t)

    def before_job(nxt, cost, cap):
        """Плановые стопы пакета: файл `<out>/STOP` (после текущего задания); затвор контроля `--gate-first-min N`: после ПЕРВОГО задания (контрольный товар) остальные не шлём,
        пока владелец пакета не положил `<out>/GO` (проверил кадры, текст-кэш, /health); нет GO за N минут — плановый стоп; первое не получено — аварийный стоп."""
        if os.path.exists(os.path.join(a.out, 'STOP')):
            return 'файл-стоп STOP'
        n = int(getattr(a, 'gate_first_min', 0) or 0)
        if n and sent[0] == 1 and not os.path.exists(os.path.join(a.out, 'GO')):
            if not os.path.exists(os.path.join(a.out, f'{jobs[0]}.ultratex.glb')):
                return '!контрольное задание (первое) не получено — остальные не шлю'
            now = time.time()
            hold['t0'] = hold['t0'] or now
            if now - hold['t0'] > n * 60:
                return f'контроль первого товара не подтверждён (нет файла GO) за {n} мин'
            return KD.HOLD
        return None

    return KD.Spec(prefix='trial-ultratex', card=CARD_NAME, model='ultratex', jobs=jobs, build_body=build, submit=submit, poll=poll, preflight=preflight, before_job=before_job,
                   ready_keys=('version', 'offload', 'sparse', 'gate'), z_keys=('KIT_WORKER_Z',), worker_file=os.path.join(HERE, 'worker_ultratex.py'), cuda_archs=CUDA_ARCHS)


def run(a, MG, BR, head_fn=head, **kw) -> int:
    return KD.run_probe(a, MG, BR, make_spec(a, head_fn), **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: имя@sha256:digest (по тегу — отказ, ADR-0137)')
    ap.add_argument('--jobs', default='', help='ключи товаров через запятую (форма: <shape-dir>/<shape-name>; фото: <inputs>/<ключ>.rgba.png)')
    ap.add_argument('--shape-dir', default='')
    ap.add_argument('--shape-name', default='{key}.prep.glb')
    ap.add_argument('--inputs', default='')
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t178-1121/salad-out'))
    ap.add_argument('--tier', default='high', choices=['batch', 'low', 'medium', 'high'])
    ap.add_argument('--cpu', type=int, default=8)
    ap.add_argument('--mem-mb', type=int, default=49152)
    ap.add_argument('--resolution', type=int, default=2048)
    ap.add_argument('--steps', type=int, default=25)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--texture', type=int, default=4096)
    ap.add_argument('--variants', default='', help='JSON (файл или строка) вариантов параметров: {"имя": {resolution, steps, guidance, seed, texture_size}}; задание `<товар>@<имя>` берёт общие параметры и переопределяет их вариантом (пара «штатно | лёгкий»)')
    ap.add_argument('--probe-cap', type=float, default=1.0, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=4.0, help='общий потолок после первого успеха, $')
    ap.add_argument('--max-min', type=int, default=120)
    ap.add_argument('--running-min', type=int, default=30, help='минут от /start до running (нода выдана)')
    ap.add_argument('--health-min', type=int, default=8, help='минут от запуска контейнера (started=True) до первого ответа /health')
    ap.add_argument('--start-min', type=int, default=20, help='минут от running до запуска контейнера (started=True); до него шлюз отдаёт 503')
    ap.add_argument('--ready-min', type=int, default=30, help='общий потолок прогрева: минут от running до «готов»')
    ap.add_argument('--stall-min', type=int, default=5, help='докачка весов: папка не выросла за столько минут — стоп')
    ap.add_argument('--stall-gb', type=float, default=0.05, help='минимальный рост папки весов за окно, ГБ')
    ap.add_argument('--worker-from-image', action='store_true', help='запускать воркер из образа, а не код из env группы')
    ap.add_argument('--post-timeout', type=int, default=0, help='секунд ждать ответ на POST /generate; 0 (по умолчанию) — по размеру тела из rules/salad-groups.json → gateway_post (kit_driver.post_timeout_s)')
    ap.add_argument('--job-min', type=int, default=0, help='срезать задание дольше N минут; 0 (по умолчанию) — до потолка пробы (p4 21.11: срезка на 30-й минуте лишила результата)')
    ap.add_argument('--fail-streak', type=int, default=2, help='сколько заданий подряд могут не удаться до стопа (по умолчанию 2)')
    ap.add_argument('--gate-first-min', type=int, default=0, help='затвор контроля: после первого задания ждать файл <out>/GO (N минут), только потом остальные; 0 — без затвора. Файл <out>/STOP — плановый стоп между заданиями')
    ap.add_argument('--idle-s', type=int, default=900)
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--diag', action='store_true', help='диагностика карты БЕЗ весов (ULTRATEX_NO_WEIGHTS=1): слив VRAM в системную память, ядро на реальных длинах, пик DiT на случайных весах')
    ap.add_argument('--diag-first', action='store_true', help='пакет на одной ноде: затвор диагностики (ядро на 71k + DiT на случайных весах, ≈5 мин) → красное: стоп до докачки весов; зелёное: веса, прогрев и задания (ULTRATEX_DIAG_FIRST=1)')
    ap.add_argument('--diag-params', default='', help='JSON к заданию /diag: lengths, chunk, runs, dit_length, vram_frac…')
    ap.add_argument('--env', action='append', default=[], help='ULTRATEX_*=значение для воркера группы (повторяемый): ULTRATEX_MEM_CHUNK, ULTRATEX_CFG, ULTRATEX_VRAM_FRAC, ULTRATEX_PROBE_L')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if KD.stop_and_verify(BR, f'trial-ultratex-{a.suffix}') else 1
    if a.diag:
        if not a.image:
            sys.exit('нужен --image')
    elif not a.jobs or not a.image or not a.shape_dir or not a.inputs:
        sys.exit('нужны --image, --jobs, --shape-dir, --inputs')
    return run(a, MG, BR)


if __name__ == '__main__':
    sys.exit(main())
