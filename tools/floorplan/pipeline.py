#!/usr/bin/env python3
"""Модуль стенда для пробы агентов (план agent-trial-01-upload-grey-tour, T-B): слепой план → `floorplanResult`.

Без `gold/<план>.json` и без `bench.CFG[план]`: «золото» — подписи VLM (`labels2`) + текст объявления
(`bench.blind_gold`), маска — `bench.auto_cfg`, дальше прежний `bench.run_plan`. Результат — JSON по
`contracts/trial.ts:floorplanResult` (сантиметры, x вправо, y вниз по листу; выгрузка схемы —
`tests/fixtures/trial-result.schema.json`).

  run:  python tools/floorplan/pipeline.py run <картинка> <папка> [--listing файл] [--vlm-dir папка] [--no-slot]
  job:  python tools/floorplan/pipeline.py job --input F --mime M --workdir W [--listing-file L] [--vlm-root R] [--job-id ID]
        (так зовёт воркер `tools/floorplan/worker.py`: шаг — в W/stage, деньги — в W/spent, итог — W/result.json или
        W/error.json {code, retryable, detail}; код выхода 0 — результат, 3 — ошибка задания, 1 — сбой модуля)

Шаги: raster (PDF → PNG `pdftoppm` / картинка → PNG, лимиты) → labels (VLM `labels2|panels|unlabeled` параллельно,
кэш по хэшу файла, потолок денег на задание) → walls/repair (`run_plan` под `heavy_slot`) → export (сбор моделей
`model-*-<i>.json` по комнатам) → [redraw — только с `FP_REDRAW=1|force`: перерисовка шумного листа и приёмка против
разбора оригинала, `redraw_stage` / `tools/floorplan/redraw.py`; по умолчанию выкл.].
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / 'ops'))

PLAN = 'T'                       # имя «плана» для файлов стенда (raw-T-*.txt, model-T-*.json)
KINDS = ('labels2', 'panels', 'unlabeled')
CAP_USD = 0.10                   # VLM на задание (план: ≤ $0,10); каждому из трёх вопросов — треть
MAX_PIXELS = 40_000_000          # картинка ≤ 40 Мп (картинка-бомба — отказ до декодирования)
MAX_SIDE = 2000                  # лист приводится к ≤ 2000 px по длинной стороне: перебор масштаба стенда — 18…134 px/м
PDF_PAGES, PDF_DPI = 2, 150
PDF_TIMEOUT_S, PDF_AS_BYTES = 30, 1 << 30
WALL_T_M = 0.20                  # без подписей: масштаб по толщине стены (D–G: толщина/ppm = 0,18…0,27 м) — not_verified;
                                 # есть общая площадь (текст/лист) — масштаб по ней, статус `area` (`scale_of`, T-20261109-26)
SLOT_LABEL, SLOT_MIN_GB, SLOT_TIMEOUT_S = 'trial-floorplan', 2.5, 60
MAX_PANELS, MAX_ROOMS, MAX_OPENINGS, MAX_POLYS, MAX_HOLES, MAX_RING = 6, 80, 400, 400, 200, 4000   # панелей 4 → 6 (T-27/2: Nethercote — 5)
RESULT_MAX_BYTES = 2 * 1024 * 1024 - 64 * 1024
MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}


class TrialError(Exception):
    """Ошибка задания с кодом из `contracts/trial.ts:trialFailCode` (страница видит код, подробности — только база)."""

    def __init__(self, code: str, retryable: bool = False, detail: str = ''):
        super().__init__(f'{code}: {detail}')
        self.code, self.retryable, self.detail = code, retryable, detail[:2000]


# ── raster: файл задания → лист PNG ────────────────────────────────────────────────────────────────────────────────

def _limited(cmd: list, timeout: float = PDF_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Чужой разборщик (poppler, GPL — отдельным процессом) под `timeout` и `prlimit --as`."""
    full = ['prlimit', f'--as={PDF_AS_BYTES}', '--'] + cmd if shutil.which('prlimit') else cmd
    try:
        return subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TrialError('pdf_unreadable', False, f'{cmd[0]}: timeout {timeout}s') from None


def pdf_pages(pdf: Path, out: Path) -> tuple[list[Path], int]:
    """Первые PDF_PAGES листов PDF → PNG (150 dpi; огромный лист — dpi ниже, чтобы ≤ MAX_PIXELS). → (картинки, всего листов)."""
    info = _limited(['pdfinfo', str(pdf)])
    if info.returncode != 0:
        raise TrialError('pdf_unreadable', False, 'pdfinfo: ' + (info.stderr or '').strip()[:300])
    meta = dict(ln.split(':', 1) for ln in info.stdout.splitlines() if ':' in ln)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    if meta.get('Encrypted', 'no').lower().startswith('yes'):
        raise TrialError('pdf_unreadable', False, 'encrypted')
    try:
        pages = int(meta.get('Pages', '0'))
    except ValueError:
        pages = 0
    if pages < 1:
        raise TrialError('pdf_unreadable', False, 'no pages')
    dpi = PDF_DPI
    m = re.match(r'([\d.]+)\s*x\s*([\d.]+)\s*pts', meta.get('Page size', ''))
    if m:
        w_in, h_in = float(m.group(1)) / 72, float(m.group(2)) / 72
        if w_in * h_in * dpi * dpi > MAX_PIXELS:
            dpi = max(20, int(math.sqrt(MAX_PIXELS / (w_in * h_in))))
    use = min(pages, PDF_PAGES)
    out.mkdir(parents=True, exist_ok=True)
    r = _limited(['pdftoppm', '-r', str(dpi), '-png', '-f', '1', '-l', str(use), str(pdf), str(out / 'page')], timeout=PDF_TIMEOUT_S)
    imgs = sorted(out.glob('page-*.png'))
    if r.returncode != 0 or not imgs:
        raise TrialError('pdf_unreadable', False, 'pdftoppm: ' + (r.stderr or '').strip()[:300])
    return imgs, pages


def _open_image(path: Path):
    from PIL import Image
    import warnings
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', Image.DecompressionBombWarning)   # порог — своей проверкой ниже
            im = Image.open(path)
        w, h = im.size
        if w * h > MAX_PIXELS:
            raise TrialError('too_large', False, f'{w}x{h} > {MAX_PIXELS} px')
        im.load()
    except TrialError:
        raise
    except Image.DecompressionBombError as e:
        raise TrialError('too_large', False, str(e)[:300]) from None
    except Exception as e:  # noqa: BLE001 — битая картинка: код для страницы, причина — в деталях
        raise TrialError('unsupported', False, f'{type(e).__name__}: {str(e)[:300]}') from None
    return im


def _flat_rgb(im):
    from PIL import Image
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return im.convert('RGB')


def prepare(input_path: Path, mime: str, workdir: Path) -> tuple[Path, dict, list]:
    """Файл задания → `sheet.png` (RGB, длинная сторона ≤ MAX_SIDE). → (лист, source для результата, флаги)."""
    from PIL import Image
    workdir.mkdir(parents=True, exist_ok=True)
    flags = []
    if mime == 'application/pdf':
        imgs, pages = pdf_pages(input_path, workdir / 'pages')
        ims = [_flat_rgb(_open_image(p)) for p in imgs]
        if pages > len(ims):
            flags.append('pages_skipped')
        gap = 40
        W, H = sum(i.width for i in ims) + gap * (len(ims) - 1), max(i.height for i in ims)
        sheet = Image.new('RGB', (W, H), (255, 255, 255))   # листы рядом: этажи на разных листах — разные панели
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0))
            x += i.width + gap
        used = len(ims)
    else:
        im = _open_image(input_path)
        real = MIMES.get(im.format or '')
        if real is None:
            raise TrialError('unsupported', False, f'format {im.format}')
        if real != mime:
            flags.append('mime_mismatch')
        sheet, pages, used, mime = _flat_rgb(im), 1, 1, real
    if max(sheet.size) > MAX_SIDE:
        k = MAX_SIDE / max(sheet.size)
        sheet = sheet.resize((max(1, round(sheet.width * k)), max(1, round(sheet.height * k))), Image.LANCZOS)
    out = workdir / 'sheet.png'
    sheet.save(out, 'PNG')
    return out, {'mime': mime, 'pages': pages, 'usedPages': used, 'imageW': sheet.width, 'imageH': sheet.height}, flags


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ── labels: VLM с кэшем ────────────────────────────────────────────────────────────────────────────────────────────

def _spent(d: Path) -> float:
    import vlm
    return vlm.spent(d)[0] if d.exists() else 0.0


def kinds(vdir: Path, plan: str = PLAN) -> tuple:
    """Вопросы VLM к листу: подписи (`labels3` с заголовками этажей; старый кэш — `labels2`, `vlm.label_kind`) + panels + unlabeled."""
    import vlm
    return (vlm.label_kind(vdir, plan),) + KINDS[1:]


def _retry_truncated(ask, plan, kind, sub, image, cap):
    """Ответ оборван лимитом (finish=length; у Gemini лимит включает рассуждение — Nethercote: 7952 из 8284 ушли на «думание»):
    один повтор с низким «думанием» на остаток денег задания. Из двух ответов остаётся тот, где больше целых элементов
    (оборванный JSON `vlm.parse` чинит до последнего целого). Денег на повтор нет — остаётся первый ответ.
    → 'ok' | 'still' | 'budget'"""
    import vlm
    raw = sub / f'raw-{plan}-{kind}.txt'
    first = sub / f'raw-{plan}-{kind}-try1.txt'
    shutil.copyfile(raw, first)
    key = vlm.LIST_KEY.get(kind, 'rooms')
    try:
        ask(plan, kind, str(sub), str(image), cap_usd=cap, effort='low')
    except SystemExit:                                   # потолок: на повтор не хватает — первый ответ, флаг выставит run
        shutil.copyfile(first, raw)
        return 'budget'
    if vlm.last_call(sub).get('finish') != 'length':
        return 'ok'
    n = lambda p: len((vlm.parse(p.read_text()) or {}).get(key) or [])   # noqa: E731
    if n(first) > n(raw):
        shutil.copyfile(first, raw)
    return 'still'


def ensure_vlm(image: Path, vdir: Path, plan: str = PLAN, ask=None, cap_usd: float = CAP_USD) -> dict:
    """Ответы VLM (`kinds`: labels3|panels|unlabeled) в `vdir/raw-<plan>-<вид>.txt`: есть файл — кэш (0 $), нет — вопрос
    параллельно (сеть — вне слота CPU). Каждый вопрос — в своей подпапке со своим `calls.jsonl` и потолком
    cap_usd / 3: худший случай трёх одновременных вызовов не выходит за потолок задания. Оборванный ответ (finish=length) —
    один повтор с низким «думанием» на остаток потолка задания (`_retry_truncated`, T-27), по очереди после первых вызовов.
    → {'usd': потрачено сейчас, 'cached': [...], 'asked': [...], 'retried': {вид: ok|still|budget}}"""
    import vlm
    ask = ask or vlm.ask
    vdir.mkdir(parents=True, exist_ok=True)
    KS = kinds(vdir, plan)
    todo = [k for k in KS if not (vdir / f'raw-{plan}-{k}.txt').exists()]
    share = cap_usd / len(KS)
    before = {k: _spent(vdir / k) for k in todo}

    def one(kind):
        sub = vdir / kind
        try:
            ask(plan, kind, str(sub), str(image), cap_usd=share)
        except SystemExit as e:                    # потолок денег vlm.ask — SystemExit
            raise TrialError('budget', False, f'{kind}: {e}') from None
        except TrialError:
            raise
        except Exception as e:  # noqa: BLE001 — сеть, 429, таймаут шлюза: повторяемо
            raise TrialError('vlm_error', True, f'{kind}: {type(e).__name__}: {str(e)[:300]}') from None
        raw = sub / f'raw-{plan}-{kind}.txt'
        if not raw.exists():
            raise TrialError('vlm_error', True, f'{kind}: no answer')
        tmp = vdir / f'.raw-{plan}-{kind}.tmp'
        shutil.copyfile(raw, tmp)
        os.replace(tmp, vdir / f'raw-{plan}-{kind}.txt')

    errs = []
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as ex:
            for f in [ex.submit(one, k) for k in todo]:
                try:
                    f.result()
                except TrialError as e:
                    errs.append(e)
    used = lambda: sum(max(0.0, _spent(vdir / k) - before[k]) for k in todo)   # noqa: E731
    retried = {}
    if not errs:
        for k in todo:
            sub = vdir / k
            if vlm.last_call(sub).get('finish') != 'length':
                continue
            retried[k] = _retry_truncated(ask, plan, k, sub, image, _spent(sub) + max(0.0, cap_usd - used()))
            tmp = vdir / f'.raw-{plan}-{k}.tmp'
            shutil.copyfile(sub / f'raw-{plan}-{k}.txt', tmp)
            os.replace(tmp, vdir / f'raw-{plan}-{k}.txt')
    usd = used()
    if errs:
        e = next((x for x in errs if not x.retryable), errs[0])
        e.usd = usd
        raise e
    return {'usd': round(usd, 6), 'cached': [k for k in KS if k not in todo], 'asked': todo, 'retried': retried}


def truncated_flags(vlm_dir: Path, plan: str = PLAN) -> list:
    """`vlm_truncated:<вид>` — ответ VLM в кэше задания оборван (и повтор не помог, или кэш старый): не молча (T-27)."""
    import vlm
    out = []
    for k in kinds(vlm_dir, plan):
        p = vlm_dir / f'raw-{plan}-{k}.txt'
        if p.exists() and (vlm.parse(p.read_text()) or {}).get('_truncated'):
            out.append(f'vlm_truncated:{k}')
    return out


# ── walls: run_plan под слотом ─────────────────────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def _patched(mod, name, value):
    old = getattr(mod, name)
    setattr(mod, name, value)
    try:
        yield
    finally:
        setattr(mod, name, old)


class _GuessScale:
    """Обёртка `fpcore` для листа без единой подписи размера: `run_plan` без масштаба падает («масштаб не найден»),
    поэтому пустой набор наблюдений получает масштаб по толщине стены (`inliers` пустой → статус not_verified),
    а манера подписи без инлаеров — P95. Остальное — сам `fpcore`. ПРАВКА В bench.py (предложена ведущему):
    `run_plan(..., ppm_fallback=None)` вместо этой обёртки."""

    def __init__(self, fc, ppm):
        self._fc, self._ppm = fc, ppm

    def __getattr__(self, k):
        return getattr(self._fc, k)

    def fit_scale(self, obs, *a, **kw):
        if not obs:
            return {'s': 1.0 / self._ppm, 's0': 1.0 / self._ppm, 'sx': 1.0 / self._ppm, 'sy': 1.0 / self._ppm,
                    'inliers': [], 'n': 0, 'guess': True}
        return self._fc.fit_scale(obs, *a, **kw)

    def convention(self, fit):
        if not fit.get('inliers'):
            return 'p95', 0, 0.0
        return self._fc.convention(fit)


def _slot(enabled: bool, job: str):
    if not enabled:
        return contextlib.nullcontext({'waited_s': 0.0})
    import heavy_slot as hs
    return hs.heavy_slot(SLOT_LABEL, min_gb=SLOT_MIN_GB, timeout=SLOT_TIMEOUT_S, cmd=f'trial {job}')


def walls(plan: str, image: Path, out: Path, G: dict, C: dict, stage, slot: bool, job: str) -> tuple[dict, dict]:
    """`run_plan` под общей очередью тяжёлых DEV. → (журнал run_plan, {'slot_wait', 'guess_ppm'})."""
    import bench
    import cv2
    import heavy_slot as hs
    meta = {'slot_wait': 0.0, 'guess_ppm': None}
    orig_repair = bench.do_repair
    said = []

    def repair_stage(*a, **kw):
        if not said:
            said.append(1)
            stage('repair')
        return orig_repair(*a, **kw)

    def go(fc_mod):
        with _patched(bench, 'do_repair', repair_stage), _patched(bench, 'fc', fc_mod):
            return bench.run_plan(plan, str(image.parent), str(out), gold=G, cfg=C)

    try:
        with _slot(slot, job) as info:
            meta['slot_wait'] = round(float(info.get('waited_s') or 0.0), 1)
            stage('walls')
            has_dims = any('dims_m' in g for g in G['rooms'])
            if has_dims:
                try:
                    return go(bench.fc), meta
                except SystemExit as e:
                    if 'масштаб не найден' not in str(e):
                        raise
            img = cv2.imread(str(image), cv2.IMREAD_COLOR)
            t = bench.fc.stroke_thickness(bench.build_mask(img, C))
            if t <= 0:
                raise TrialError('no_plan', False, 'no walls found')
            meta['guess_ppm'] = t / WALL_T_M
            return go(_GuessScale(bench.fc, meta['guess_ppm'])), meta
    except hs.SlotTimeout:
        raise TrialError('waiting_capacity', True, f'heavy slot > {SLOT_TIMEOUT_S}s') from None
    except SystemExit as e:
        raise TrialError('no_plan', False, f'run_plan: {e}') from None


# ── export: модели панелей → floorplanResult ───────────────────────────────────────────────────────────────────────

KIND_RULES = (
    ('bathroom', r'\bbath|\bshower|\bw\.?c\b|toilet|en.?suite|cloak|lavatory'),
    ('kitchen', r'kitchen|breakfast|\bdiner\b'),
    ('bedroom', r'\bbed(room)?s?\b|nursery|\bmaster\b'),
    ('living', r'living|lounge|sitting|reception|family|drawing|dining|\bsnug\b|day room|garden room'),
    ('hall', r'\bhall|landing|corridor|entrance|porch|lobby|stair|vestibule'),
)


def _alias(name: str) -> str:
    import listing
    return listing.alias_key(name or '')


def room_kind(name: str) -> str:
    s = (name or '').lower()
    for kind, rx in KIND_RULES:
        if re.search(rx, s):
            return kind
    return 'other'


def _cm(p, nd=1):
    return [round(float(p[0]) * 100, nd), round(float(p[1]) * 100, nd)]


def _ring(pts, nd=1):
    """Кольцо в см: без повторов подряд, ≥ 3 точек, ≤ MAX_RING (прореживание). None — вырожденное."""
    out = []
    for p in pts:
        q = _cm(p, nd)
        if not all(math.isfinite(v) for v in q):
            return None
        if not out or q != out[-1]:
            out.append(q)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    if len(out) > MAX_RING:
        k = math.ceil(len(out) / MAX_RING)
        out = out[::k]
    return out if len(out) >= 3 else None


def _shoelace(r) -> float:
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2


def _room_flags(names, G_by, dims_by, scale_ok):
    fl = []
    if not scale_ok:
        fl.append('scale_unverified')
    if len(names) > 1:
        fl.append('merged')
    for n in names:
        row = dims_by.get(n)
        g = G_by.get(n, {})
        if row:
            if row.get('status') == 'мерка без подписи':
                fl.append('dims_estimated')
            elif row.get('flag_level', 0) >= 2:
                fl.append('dims_mismatch')
            elif row.get('flag_level', 0) == 1:
                fl.append('dims_uncertain')
        if g.get('unsure'):
            fl.append('label_unclear')
        if any('≠' in t or t.startswith('текст:') for t in g.get('text_flags') or []):
            fl.append('listing_mismatch')
    return list(dict.fromkeys(fl))[:30]


AREA_WALL_T_M = (0.08, 0.60)      # масштаб по общей площади даёт стену такой толщины — иначе площадь не про этот лист
AREA_CONFLICT_REL = 0.10          # подписи/текст против общей площади: расхождение масштаба > 10 % — флаг (опора подписей остаётся)
# Знаменатель честен, только если найдено всё здание: подпись VLM без найденной комнаты = кусок площади мимо знаменателя,
# и масштаб по площади раздувает ВСЕ метры (стенд без размеров: E 14/65 без комнаты → +33 %, F 4/25 — два корпуса → +21 %,
# G 5/73 → +5 %; с размерами ≤ 3/65). Доля потерянных подписей больше этой — площадь не берём (`area_unusable:coverage`).
AREA_MISSED_MAX = 0.10


def _excluded(names, excl) -> bool:
    import listing
    s = ' '.join(names or []).lower()
    return any(r in s for r in tuple(listing.OPEN_AIR) + tuple(excl or ()))


def area_scale(log: dict, models: dict, area: dict) -> dict:
    """Общая площадь → масштаб ВСЕГО листа (px/м). Знаменатель — пиксели² того же, что считает площадь:
    • `gia` (британская Total/GIA, RICS): по внутренней грани наружных стен С внутренними стенами — `bench.gia_px`
      каждой панели (`gia_m2 × ppm²`);
    • `rooms` (русская «общая площадь»): сумма помещений без стен — комнаты моделей (`area_m2 × ppm²`).
    Балконы/террасы/лоджии (в GIA и в «общую» не входят) и то, что подпись исключает («excl. garage»), — вычитаются
    по именам комнат. Проверки: найдено всё здание (подписей VLM без комнаты ≤ AREA_MISSED_MAX, `coverage`), стена по
    этому масштабу правдоподобной толщины (`wall_thickness`). → {'ppm', 'px2', 'excluded_px2', 'wall_t_m', 'missed', 'ok', 'why'}."""
    labs = [q for P in log['panels'] for q in P.get('label_report') or []
            if not _excluded([str(q.get('name') or '')], area.get('excl'))]
    lost = [q for q in labs if q.get('room') is None]
    missed = (len(lost), len(labs))
    if labs and len(lost) / len(labs) > AREA_MISSED_MAX:
        return {'ok': False, 'why': 'coverage', 'missed': missed}
    px2 = ex = 0.0
    for P in log['panels']:
        ppm = float(P.get('ppm') or 0)
        m = models.get(tuple(P['bbox_px']))
        if ppm <= 0 or m is None:
            continue
        rooms_px = sum(float(r.get('area_m2') or 0) * ppm * ppm for r in m.get('rooms', []))
        ex_px = sum(float(r.get('area_m2') or 0) * ppm * ppm for r in m.get('rooms', []) if _excluded(r.get('names'), area.get('excl')))
        px2 += (float(P.get('gia_m2') or 0) * ppm * ppm if area['conv'] == 'gia' else rooms_px) - ex_px
        ex += ex_px
    if px2 <= 0:
        return {'ok': False, 'why': 'no_area_px', 'missed': missed}
    ppm = math.sqrt(px2 / float(area['m2']))
    t_m = float(log.get('thickness_px') or 0) / ppm
    ok = AREA_WALL_T_M[0] <= t_m <= AREA_WALL_T_M[1]
    return {'ok': ok, 'why': None if ok else 'wall_thickness', 'ppm': ppm, 'px2': round(px2), 'excluded_px2': round(ex),
            'wall_t_m': round(t_m, 3), 'missed': missed}


def _scale_model(m: dict, k: float) -> dict:
    """Модель панели в метрах × k (масштаб по площади поверх прогона по толщине стены): контуры, стены, проёмы, площади."""
    def ring(r):
        return [[p[0] * k, p[1] * k] for p in r]
    out = dict(m)
    out['floors'] = [dict(f, outer=ring(f['outer']), holes=[ring(h) for h in f.get('holes') or []]) for f in m.get('floors', [])]
    out['rooms'] = [dict(r, area_m2=float(r.get('area_m2') or 0) * k * k) for r in m.get('rooms', [])]
    out['bands'] = [dict(b, polys=[dict(p, outer=ring(p['outer']), holes=[ring(h) for h in p.get('holes') or []])
                                   for p in b.get('polys', [])]) for b in m.get('bands', [])]
    out['openings'] = [dict(o, c=[o['c'][0] * k, o['c'][1] * k], width_m=float(o.get('width_m') or 0) * k)
                       for o in m.get('openings', [])]
    return out


def scale_of(log: dict, G: dict, guess: bool, area: dict | None = None, models: dict | None = None,
             skipped: bool = False) -> tuple[dict, list, dict]:
    """Порядок опор: подписи плана (verified, ≥ 2 инлаера с размером с листа) → размеры текстом (listing) → общая площадь
    (area: только при угаданном по толщине стены масштабе) → толщина стены (not_verified, плашка `Scale not verified`).
    Общая площадь при подписях/тексте — только сверка: разошлась > AREA_CONFLICT_REL — флаг `scale_area_conflict`.
    → (scale, флаги результата, k — множитель метров моделей по bbox панели: пусто, кроме `area`)."""
    scale, fl, k = _scale_labels(log, G, guess), [], {}
    if not area:
        return scale, fl, k
    scale.update(areaM2=round(float(area['m2']), 1), areaSrc=area['src'])
    if skipped:                                               # общая — про все листы PDF, а прочитаны не все
        return scale, fl + ['area_pages_skipped'], k
    a = area_scale(log, models or {}, area)
    if not a['ok']:
        return scale, fl + [f"area_unusable:{a['why']}"], k
    if scale['status'] == 'not_verified':
        # панели — куски одного листа: пиксель один, масштаб листа один; метры панели × (её прежний ppm / новый)
        k = {tuple(P['bbox_px']): float(P['ppm']) / a['ppm'] for P in log['panels'] if float(P.get('ppm') or 0) > 0}
        scale.update(status='area', ppm=round(a['ppm'], 3))
        fl += ['scale_from_area'] + [f for f in area.get('flags') or []]
    else:
        # сверка: площадь по найденному масштабу (у каждой панели свой) против общей, в линейной мере
        got = sum(_area_m2_of(P, models or {}, area) for P in log['panels'])
        if got > 0 and abs(math.sqrt(got / float(area['m2'])) - 1) > AREA_CONFLICT_REL:
            fl.append('scale_area_conflict')
    return scale, fl, k


def _area_m2_of(P: dict, models: dict, area: dict) -> float:
    """Площадь панели в м² по её собственному масштабу, в той же мере, что общая (gia / rooms, без исключённого)."""
    m = models.get(tuple(P['bbox_px']))
    if m is None:
        return 0.0
    ex = sum(float(r.get('area_m2') or 0) for r in m.get('rooms', []) if _excluded(r.get('names'), area.get('excl')))
    base = float(P.get('gia_m2') or 0) if area['conv'] == 'gia' else sum(float(r.get('area_m2') or 0) for r in m.get('rooms', []))
    return max(0.0, base - ex)


def _scale_labels(log: dict, G: dict, guess: bool) -> dict:
    """verified — подписи плана сошлись (≥ 2 инлаера с размером с листа); listing — опора на размеры из текста;
    иначе not_verified (тур есть, плашка `Scale not verified`)."""
    src = {g['name']: g.get('dims_src') for g in G['rooms']}
    plan_inl = text_inl = n = 0
    for P in log['panels']:
        for (rid, _c, _p) in (P.get('inliers') or []):
            s = src.get(rid)
            if s in ('plan', 'both'):
                plan_inl += 1
            elif s == 'text':
                text_inl += 1
        n += int((P.get('fit') or {}).get('n') or 0)
    if guess:
        status = 'not_verified'
    elif plan_inl >= 2:
        status = 'verified'
    elif text_inl >= 1:
        status = 'listing'
    else:
        status = 'not_verified'
    ppm = None
    if status != 'not_verified' and log.get('sweep'):
        ppm = round(float(log['sweep'][0]['est']), 3)
    return {'status': status, 'ppm': ppm, 'inliers': plan_inl + text_inl, 'n': n}


def panel_result(pi: int, P: dict, model: dict, G_by: dict, scale_ok: bool, nd: int = 1) -> dict:
    dims_by = {d['id']: d for d in P.get('dims') or []}
    spaces = {}
    for q in P.get('label_report') or []:
        if q.get('space') and q.get('room') is not None:
            spaces.setdefault(q['room'], []).append(q['name'])
    absorbed = {int(x['into']) for x in P.get('absorbed') or []}   # T-19: в комнату влит обрывок за нашим закрытием
    rooms = []
    for mr in model.get('rooms', []):
        rid = mr['id']
        rings = [r for r in (_ring(f['outer'], nd) for f in model.get('floors', []) if f.get('room') == rid) if r]
        if not rings:
            continue
        contour = max(rings, key=_shoelace)
        names = list(mr.get('names') or [])
        shown = [G_by.get(n, {}).get('name0', n) for n in names] or spaces.get(rid, [])
        xs, ys = [p[0] for p in contour], [p[1] for p in contour]
        w, d = round(max(xs) - min(xs), nd), round(max(ys) - min(ys), nd)
        if w <= 0 or d <= 0:
            continue
        fl = _room_flags(names, G_by, dims_by, scale_ok)
        if not shown:
            fl.insert(0, 'unlabeled')
        if rid in absorbed:
            fl.append('fragment_merged')
        kind = room_kind(shown[0] if shown else '')
        g1 = G_by.get(names[0], {}) if len(names) == 1 else {}
        if kind == 'other' and g1.get('text_match') == 'alias' and g1.get('text_name'):
            # T-20261110-33: подпись листа сама неясна («ES», «ST.»), а строка объявления сопоставлена с ней по синониму — имя и вид
            # из строки («En-Suite» → санузел); подпись листа остаётся в разметке стенда
            shown = [str(g1['text_name'])]
            kind = room_kind(shown[0])
            fl.append('name_from_listing')
        if kind == 'other' and shown:
            kind = room_kind(_alias(shown[0]))                # «ES» = en-suite, «W.C.» = wc — синонимы `listing.alias_key`
        room = {'id': f'p{pi}-r{rid}'[:40], 'name': ' + '.join(dict.fromkeys(shown))[:80],
                'kind': kind, 'contour': contour,
                # bbox — проекция контура (refine контракта: расхождение < 1 см)
                'bbox': {'x': min(xs), 'y': min(ys), 'w': w, 'd': d},
                'areaM2': max(0.0, round(float(mr.get('area_m2') or 0.0), 2)), 'flags': fl}
        g = G_by.get(names[0]) if len(names) == 1 else None
        if g and g.get('dims_m') and min(g['dims_m']) > 0:
            a, b = (round(v * 100, 1) for v in g['dims_m'][:2])
            if abs(b - w) + abs(a - d) < abs(a - w) + abs(b - d):
                a, b = b, a                         # w — вдоль x листа, d — вдоль y (напечатано могло быть наоборот)
            room['dims'] = {'w': a, 'd': b, 'src': 'listing' if g.get('dims_src') == 'text' else 'plan'}
        elif 'dims_estimated' not in fl:
            fl.append('dims_estimated')             # размера нет ни на плане, ни в тексте — мерка по масштабу листа
        rooms.append(room)
    rooms.sort(key=lambda r: -r['areaM2'])
    walls = []
    for b in model.get('bands', [])[:20]:
        polys = []
        for p in b.get('polys', []):
            outer = _ring(p['outer'], nd)
            if outer:
                holes = [h for h in (_ring(h, nd) for h in p.get('holes', [])) if h]
                polys.append({'outer': outer, 'holes': sorted(holes, key=_shoelace, reverse=True)[:MAX_HOLES]})
        polys.sort(key=lambda p: _shoelace(p['outer']), reverse=True)
        walls.append({'z0': round(b['z0'] * 100, 1), 'z1': round(b['z1'] * 100, 1), 'polys': polys[:MAX_POLYS]})
    openings = []
    for o in model.get('openings', []):
        wcm = round(float(o.get('width_m') or 0) * 100, 1)
        c = _cm(o['c'], nd)
        if wcm > 0 and all(math.isfinite(v) for v in c):
            openings.append({'kind': o['kind'] if o.get('kind') in ('door', 'window') else 'opening', 'c': c,
                             'widthCm': wcm, 'exterior': bool(o.get('exterior'))})
    title = str(P.get('vlm_title') or P.get('panel') or f'Plan {pi + 1}')
    return {'id': f'p{pi}', 'title': title[:120], 'rooms': rooms[:MAX_ROOMS], 'walls': walls,
            'openings': openings[:MAX_OPENINGS], '_trunc': len(rooms) > MAX_ROOMS}


def _models(out: Path, plan: str) -> dict:
    ms = {}
    for p in out.glob(f'model-{plan}-*.json'):
        m = json.loads(p.read_text())
        ms[tuple(m['bbox_px'])] = m
    return ms


def to_result(log: dict, out: Path, plan: str, G: dict, source: dict, cost: float, timings: dict, flags: list,
              guess: bool, area: dict | None = None) -> dict:
    G_by = {g['name']: g for g in G['rooms']}
    models = _models(out, plan)
    flags = list(flags)
    scale, afl, k = scale_of(log, G, guess, area, models, 'pages_skipped' in flags)
    if k:
        models = {bb: _scale_model(m, k[bb]) if bb in k else m for bb, m in models.items()}
    if guess and scale['status'] != 'area':
        flags.append('scale_from_wall_thickness')
    flags += afl
    flags += log.get('panel_flags') or []        # T-27/2: делёж листа без опоры (panel_title_guess, panel_titles_merged, vlm_panels_disagree)
    if not G['rooms']:
        flags.append('no_labels')
    for nd in (1, 0):
        panels = []
        for pi, P in enumerate(log['panels']):
            m = models.get(tuple(P['bbox_px']))
            if m is None:
                continue
            panels.append(panel_result(pi, P, m, G_by, scale['status'] != 'not_verified', nd))
        panels = [p for p in panels if p['rooms'] or any(w['polys'] for w in p['walls'])]
        if not any(p['rooms'] for p in panels):
            raise TrialError('no_plan', False, 'no rooms found')
        fl = list(flags)
        if len(panels) > MAX_PANELS:
            fl.append('panels_truncated')
            keep = sorted(range(len(panels)), key=lambda i: -sum(r['areaM2'] for r in panels[i]['rooms']))[:MAX_PANELS]
            panels = [panels[i] for i in sorted(keep)]
        if any(p.pop('_trunc') for p in panels):
            fl.append('rooms_truncated')
        res = {'version': 1, 'units': 'cm', 'source': source, 'scale': scale, 'panels': panels,
               'flags': list(dict.fromkeys(fl))[:30], 'timings': {k: round(float(v), 2) for k, v in timings.items()},
               'costUsd': round(float(cost), 6)}
        if len(json.dumps(res, separators=(',', ':'))) <= RESULT_MAX_BYTES:
            return res
    raise TrialError('pipeline_error', False, 'result > 2 MB')


# ── перерисовка шумного листа (FP_REDRAW, T-20261110-17; по умолчанию выкл.) ──────────────────────────────────────

def redraw_stage(res: dict, rmode: str, *, image: Path, vlm_dir: Path, plan: str, G: dict, log: dict, out: Path,
                 workdir: Path, slot: bool, job: str, vlm_usd: float, T: dict, fl: list, area, source: dict,
                 spent=None, cache_only: bool = False, draw=None) -> dict:
    """Разбор оригинала `res` уже готов. Тревожный (`redraw.alarm`; `force` — всегда) → перерисовка листа (`redraw.attempt`,
    свой потолок денег) → стены по ПРОВЕРЕННОМУ чистому листу, подписи — те же `G` с чтения оригинала (VLM чистый лист не
    видит; кэш VLM — по sha оригинала) → `redraw.decide`. Итог: принят — разбор чистого + `redraw_used`; нет —
    разбор оригинала + `redraw_rejected:<причина>`. Сбой перерисовки задание не роняет. Шаг страницы не меняется
    (закрытый список стадий: остаётся `export`). Подробности — `<workdir>/redraw/{redraw,decision}.json`."""
    import redraw
    import bench
    import cv2
    why = redraw.alarm(res, log)
    if rmode == 'on' and not why:
        return res
    t0 = time.time()
    rdir = workdir / 'redraw'
    a = redraw.attempt(image, vlm_dir, plan, rdir, draw=draw, cap=redraw.cap_usd(), cache_only=cache_only)
    usd = float(a.get('usd') or 0.0)
    total = round(float(vlm_usd) + usd, 6)
    if spent and usd:
        spent(total)
    dec = {'alarm': why, 'mode': rmode, 'redraw': {k: a.get(k) for k in ('why', 'usd', 'cached', 'clean')}}
    pick, flag = res, None
    if not a.get('clean'):
        flag = f"redraw_rejected:{a.get('why') or 'none'}"
    else:
        clean = Path(a['clean'])
        out_c = rdir / 'bench'
        out_c.mkdir(parents=True, exist_ok=True)
        G_c = dict(G, image=str(clean.resolve()))           # те же подписи; лист для стен — чистый
        try:
            C_c = bench.auto_cfg(cv2.imread(str(clean), cv2.IMREAD_COLOR))
            log_c, meta_c = walls(plan, clean, out_c, G_c, C_c, lambda s: None, slot, job)
            res_c = to_result(log_c, out_c, plan, G_c, source, total, T, fl, meta_c['guess_ppm'] is not None, area)
            (rdir / 'result-clean.json').write_text(json.dumps(res_c, ensure_ascii=False, separators=(',', ':')))
            d = redraw.decide(res, log, _models(out, plan), res_c, log_c, _models(out_c, plan))
        except TrialError as e:
            flag = f'redraw_rejected:parse_{e.code}'
            dec['parse_error'] = e.detail[:300]
        except Exception as e:  # noqa: BLE001 — сбой разбора чистого листа не роняет задание: итог — оригинал
            flag = 'redraw_rejected:parse_crash'
            dec['parse_error'] = f'{type(e).__name__}: {str(e)[:300]}'
        else:
            dec.update(d)
            if d['accept']:
                pick, flag = res_c, 'redraw_used'
            else:
                flag = f"redraw_rejected:{d['why']}"
    pick = dict(pick, timings=dict(res['timings'], redraw=round(time.time() - t0, 2)), costUsd=total)
    redraw.add_flag(pick, flag)
    dec['flag'] = flag
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / 'decision.json').write_text(json.dumps(dec, ensure_ascii=False, indent=1, default=float))
    return pick


# ── весь путь ──────────────────────────────────────────────────────────────────────────────────────────────────────

def run(image_path, listing_text, workdir, *, source: dict | None = None, vlm_dir=None, vlm_root=None, ask=None,
        cap_usd: float = CAP_USD, stage=None, slot: bool = True, an_cache=None, plan: str = PLAN, job: str = '-',
        timings: dict | None = None, flags: list | None = None, spent=None, cache_only: bool = False) -> dict:
    """Лист (PNG/JPEG) + текст объявления → `floorplanResult` (dict). VLM — из `vlm_dir` (или
    `vlm_root/<sha256 листа>`); нет ответа — платный вопрос с потолком `cap_usd` на задание.
    `cache_only` — перечитать план с новым текстом (Р2-текст): только кэш VLM, 0 $; кэша нет — `source_gone`."""
    import bench
    import cv2
    image, workdir = Path(image_path).resolve(), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    stage = stage or (lambda s: None)
    T = dict(timings or {})
    if source is None:
        h, w = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE).shape[:2]
        source = {'mime': 'image/png' if image.suffix.lower() == '.png' else 'image/jpeg', 'pages': 1, 'usedPages': 1,
                  'imageW': int(w), 'imageH': int(h)}
    t0 = time.time()
    stage('labels')
    if vlm_dir is None:
        root = Path(vlm_root or os.path.expanduser('~/remlab-logs/trial/vlm-cache'))
        vlm_dir = root / file_sha(image)[:32]
    vlm_dir = Path(vlm_dir)
    if cache_only and any(not (vlm_dir / f'raw-{plan}-{k}.txt').exists() for k in kinds(vlm_dir, plan)):
        raise TrialError('source_gone', False, 'vlm cache missing')
    try:
        v = ensure_vlm(image, vlm_dir, plan, ask, cap_usd)
    except TrialError as e:
        if spent:
            spent(getattr(e, 'usd', 0.0))
        raise
    if spent:
        spent(v['usd'])
    lst = None
    if listing_text and listing_text.strip():
        lst = workdir / 'listing.txt'
        lst.write_text(listing_text[:5000])
    out = workdir / 'bench'
    out.mkdir(parents=True, exist_ok=True)
    fl = list(flags or [])
    lk = kinds(vlm_dir, plan)[0]
    envkw = dict(FP_VLM=str(vlm_dir), FP_LABELS=lk, FP_VLM2=None, FP_CACHE=an_cache, FP_PPM=None, FP_DEBUG_ENV=None,
                 FP_DUMP=None)
    with _env(**envkw):
        import vlm
        raw = vlm.parse((vlm_dir / f'raw-{plan}-{lk}.txt').read_text()) or {}
        fl += truncated_flags(vlm_dir, plan)
        import listing
        area, afl = listing.pick_area(listing.total_area(listing_text or ''), listing.sheet_area(raw.get('areas')))
        fl += afl
        G = bench.blind_gold(plan, image, str(vlm_dir), str(lst) if lst else None)
        C = bench.auto_cfg(cv2.imread(str(image), cv2.IMREAD_COLOR))
        T['labels'] = time.time() - t0
        t1 = time.time()
        log, meta = walls(plan, image, out, G, C, stage, slot, job)
    T['slot_wait'] = meta['slot_wait']
    T['walls'] = time.time() - t1 - meta['slot_wait']
    t2 = time.time()
    stage('export')
    res = to_result(log, out, plan, G, source, v['usd'], T, fl, meta['guess_ppm'] is not None, area)
    res['timings']['export'] = round(time.time() - t2, 2)
    if os.environ.get('FP_REDRAW'):
        import redraw
        rmode = redraw.mode()
        if rmode != 'off':
            with _env(**envkw):
                res = redraw_stage(res, rmode, image=image, vlm_dir=vlm_dir, plan=plan, G=G, log=log, out=out,
                                   workdir=workdir, slot=slot, job=job, vlm_usd=v['usd'], T=T, fl=fl, area=area,
                                   source=source, spent=spent, cache_only=cache_only)
    (workdir / 'gold.json').write_text(json.dumps({k: x for k, x in G.items() if k != '_labels'}, ensure_ascii=False,
                                                  default=float))
    return res


def _atomic(path: Path, text: str) -> None:
    tmp = path.with_name('.' + path.name + '.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)


def job_main(a) -> int:
    """Режим воркера: всё тяжёлое и чужие разборщики — в этом процессе (воркер шлёт heartbeat и снимет его по таймауту)."""
    W = Path(a.workdir)
    W.mkdir(parents=True, exist_ok=True)

    def stage(s):
        _atomic(W / 'stage', s)

    def spent(usd):
        _atomic(W / 'spent', f'{float(usd):.6f}')
    try:
        t0 = time.time()
        stage('raster')
        sheet, source, flags = prepare(Path(a.input), a.mime, W)
        listing = Path(a.listing_file).read_text(errors='replace') if a.listing_file else ''
        res = run(sheet, listing, W, source=source, vlm_root=a.vlm_root, cap_usd=a.cap_usd, stage=stage,
                  slot=not a.no_slot, an_cache=a.an_cache, job=a.job_id, timings={'raster': time.time() - t0},
                  flags=flags, spent=spent, cache_only=a.cache_only)
        _atomic(W / 'result.json', json.dumps(res, separators=(',', ':')))
        return 0
    except TrialError as e:
        _atomic(W / 'error.json', json.dumps({'code': e.code, 'retryable': e.retryable, 'detail': e.detail}))
        return 3
    except Exception as e:  # noqa: BLE001 — сбой кода стенда: повтор не поможет, причина — в деталях
        import traceback
        _atomic(W / 'error.json', json.dumps({'code': 'pipeline_error', 'retryable': False,
                                              'detail': f'{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}'}))
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    r = sp.add_parser('run')
    r.add_argument('image')
    r.add_argument('out')
    r.add_argument('--listing')
    r.add_argument('--vlm-dir')
    r.add_argument('--vlm-root')
    r.add_argument('--plan', default=PLAN)
    r.add_argument('--no-slot', action='store_true')
    r.add_argument('--an-cache')
    j = sp.add_parser('job')
    j.add_argument('--input', required=True)
    j.add_argument('--mime', required=True)
    j.add_argument('--workdir', required=True)
    j.add_argument('--listing-file')
    j.add_argument('--vlm-root')
    j.add_argument('--job-id', default='-')
    j.add_argument('--cap-usd', type=float, default=CAP_USD)
    j.add_argument('--an-cache')
    j.add_argument('--no-slot', action='store_true')
    j.add_argument('--cache-only', action='store_true', help='только кэш VLM (0 $); нет — код source_gone')
    a = ap.parse_args(argv)
    if a.cmd == 'job':
        return job_main(a)
    t0 = time.time()
    lt = Path(a.listing).read_text(errors='replace') if a.listing else ''
    res = run(a.image, lt, a.out, vlm_dir=a.vlm_dir, vlm_root=a.vlm_root, plan=a.plan, slot=not a.no_slot,
              an_cache=a.an_cache, stage=lambda s: print('stage', s, round(time.time() - t0, 1), flush=True))
    Path(a.out, 'result.json').write_text(json.dumps(res, separators=(',', ':')))
    print(json.dumps({'scale': res['scale'], 'flags': res['flags'], 'timings': res['timings'], 'costUsd': res['costUsd'],
                      'panels': [(p['title'], len(p['rooms'])) for p in res['panels']],
                      'bytes': len(json.dumps(res, separators=(',', ':')))}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
