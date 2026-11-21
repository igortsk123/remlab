#!/usr/bin/env python3
"""Этап 05 «снять свет» нового пути покраски (план paint-photo-fill-01; T-20261121-160/3 — порт проб T-160/1–2).
Фото магазина (RGBA-вырезка) → то же фото со снятыми ПЛАВНЫМИ светом и тенью: `<run>/<sku>/05-delight/delight.rgba.png` (размер и альфа — как у фото; это вход этапа 6 «камера/проекция»),
`frame.png` («фото | снято», подписи DejaVu), `check.json` (через paint_stage), `albedo-iid-v11.png` (кэш модели).

СПОСОБ («мягкое», CPU, 0 $): albedo Marigold IID-Appearance v1.1 размывает мелочь и обесцвечивает, поэтому берём из него ТОЛЬКО низкие частоты света:
  результат = фото × g,  g = blur(Y_albedo) / blur(Y_фото),  σ = доля × длинная сторона, нормировано по медиане предмета, blur — только внутри маски.
Цвет, стёжка, ворс остаются с фото. Все пороги и параметры модели — в `rules/paint-delight.json` (в коде чисел порогов и ID товаров нет).

ЧЕСТНО О МЕРКЕ. `iid_shading_removed` = «результат/фото» по разбросу НИЗКОЧАСТОТНОЙ яркости внутри участка одного цвета (кластер хромы ФОТО; многотоновые участки по albedo не мерим).
Это «убрано то, что IID счёл светом», а НЕ «свет снят на самом деле»: если IID принял тень за цвет, мерка пройдёт. Независимая проверка по нормалям меша (R2) — позже:
в check.json стоит `independent_check: pending`. Света на фото мало (разброс < порога N/A) — мерка N/A, passed не краснеет. ΔL* к каталогу — НЕ здесь (шаг цвета).

  paint_delight.py run <run> <manifest.json> [--force]   manifest = [{"sku"[,"path"]}, …]; <run> — папка-прогон, где этап 04 уже положил `<sku>/04-camera/check.json`; повтор пропускает готовое
  paint_delight.py --selftest
ФОТО БЕРЁТСЯ ТОЛЬКО ОТ КАМЕРЫ (правило конвейера, директор 21.11): путь — из `<run>/<sku>/04-camera/check.json` → `extra.photo` (его же пишет pose_fit). Своё фото этап не выбирает:
нет check.json камеры / нет пути / файла нет / камера не прошла → отказ с причиной (check.json 05 passed=false, без картинки); `path` в манифесте, если задан, обязан совпасть с путём камеры — иначе «фото не то, что у камеры».
Зачем: этап 6 ставит снятое фото на ту форму и камеру, что посчитаны по фото камеры; другая вырезка → силуэт не сходится (IoU 0,19/0,00).
Окружение: SIGMA — доля вместо `sigma` правила; DELIGHT_RULES — другой файл правил; THREADS — потоки torch; HF_HOME — кэш модели; PAINT_STAGE_DIR — папка с paint_stage.py."""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('PAINT_STAGE_DIR'):
    sys.path.insert(0, os.environ['PAINT_STAGE_DIR'])
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402

import mesh_color_check as MC  # noqa: E402
import paint_stage as PS  # noqa: E402

STAGE = '05-delight'
RULES_PATH = os.environ.get('DELIGHT_RULES') or os.path.join(HERE, 'rules', 'paint-delight.json')
_PIPE = [None]


def load_rules(path: str | None = None) -> dict:
    """Пороги и параметры — только из файла; нет файла или ключа — падаем, умолчаний в коде не держим."""
    r = json.load(open(path or RULES_PATH, encoding='utf-8'))
    for k in ('sigma', 'light', 'hf_corr_min', 'hf_energy_min', 'model', 'bg_grey', 'metric_side', 'min_mask_px'):
        if k not in r:
            raise KeyError(f'rules/paint-delight.json: нет ключа {k!r}')
    for k in ('lf_sigma', 'clusters', 'min_cluster_share', 'stat_pct', 'na_spread_below', 'tone_split_max', 'ratio_max'):
        if k not in r['light']:
            raise KeyError(f'rules/paint-delight.json: light.{k} не задан')
    return r


# ---------- цвет и размытие ----------

def s2l(x):
    x = np.asarray(x, np.float64) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def l2s(x):
    x = np.clip(x, 0, 1)
    return np.clip(np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def lum(lin):
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def nblur(x, m, sigma):
    """Гауссиан только внутри маски (нормированная свёртка): фон не подмешивается."""
    mf = m.astype(np.float64)
    return ndi.gaussian_filter(x * mf, sigma) / np.maximum(ndi.gaussian_filter(mf, sigma), 1e-6)


def lab_full(rgb8):
    h, w = rgb8.shape[:2]
    return MC.lab(rgb8.reshape(-1, 3).astype(np.float64)).reshape(h, w, 3)


def lab_l(rgb8):
    return lab_full(rgb8)[..., 0]


def shrink(arr, side):
    h, w = arr.shape[:2]
    if max(h, w) <= side:
        return arr
    k = side / max(h, w)
    return np.asarray(Image.fromarray(arr).resize((round(w * k), round(h * k)), Image.LANCZOS))


# ---------- само снятие света ----------

def soft_transfer(photo8, alb8, mask, frac):
    """фото × (низкие частоты albedo / низкие частоты фото); вне маски — как на фото."""
    pl, al = s2l(photo8), s2l(alb8)
    sig = frac * max(photo8.shape[:2])
    g = nblur(lum(al), mask, sig) / np.maximum(nblur(lum(pl), mask, sig), 1e-4)
    g = g / max(np.median(g[mask]), 1e-6)
    res = l2s(pl * g[..., None])
    res[~mask] = photo8[~mask]
    return res


# ---------- мерки ----------

def light_spread(photo8, res8, alb8, mask, lr):
    """Разброс НИЗКОЧАСТОТНОЙ яркости внутри одного цветового участка: P90−P10 размытого L*, среднее по участкам с весом по площади.
    Участок = кластер ХРОМЫ ФОТО (a,b к свету почти не чувствительны), а не albedo: иначе результат внутри участков «плоский» по построению.
    albedo лишь выкидывает многотоновые участки (чёрное+белое в одном кластере хромы): разброс тона albedo в участке > tone_split_max → не мерим.
    → (фото, результат, число участков) или (None, None, 0), если мерить нечего."""
    from scipy.cluster.vq import kmeans2
    h, w = mask.shape
    sig = lr['lf_sigma'] * max(h, w)
    ab = lab_full(photo8)[..., 1:]
    core = ndi.binary_erosion(mask, iterations=3)
    pts = ab[core]
    if len(pts) < 500:
        return None, None, 0
    sub = pts[np.random.default_rng(0).choice(len(pts), min(len(pts), 20000), replace=False)]
    cent, _ = kmeans2(sub, lr['clusters'], minit='++', seed=0)
    lbl = np.argmin(((ab[..., None, :] - cent[None, None]) ** 2).sum(-1), axis=-1)
    lp, lq = nblur(lab_l(photo8), mask, sig), nblur(lab_l(res8), mask, sig)
    la = nblur(lab_l(alb8), mask, sig)
    p_lo, p_hi = lr['stat_pct']
    sp = sr = wsum = 0.0
    used = 0
    for k in range(len(cent)):
        m = core & (lbl == k)
        if m.sum() < lr['min_cluster_share'] * core.sum() or m.sum() < 300:
            continue
        if np.percentile(la[m], p_hi) - np.percentile(la[m], p_lo) > lr['tone_split_max']:
            continue
        sp += m.sum() * (np.percentile(lp[m], p_hi) - np.percentile(lp[m], p_lo))
        sr += m.sum() * (np.percentile(lq[m], p_hi) - np.percentile(lq[m], p_lo))
        wsum += m.sum()
        used += 1
    return (None, None, 0) if not wsum else (sp / wsum, sr / wsum, used)


def hf_metrics(photo8, res8, core):
    """Высокие частоты L* (L − gauss(L, 2 px)) внутри маски: корреляция фото↔результат (ловит «стёрло стёжку») и отношение энергий."""
    Lp, Lr = lab_l(photo8), lab_l(res8)
    hp, hr = Lp - ndi.gaussian_filter(Lp, 2.0), Lr - ndi.gaussian_filter(Lr, 2.0)
    return float(np.corrcoef(hp[core], hr[core])[0, 1]), float(hr[core].std() / max(hp[core].std(), 1e-6)), float(np.median(Lr[core]))


def evaluate(photo8, res8, alb8, a, rules):
    """Мерки на картинках не крупнее metric_side (числа сравнимы между товарами разного размера). → (фото, результат, словарь)."""
    side = rules['metric_side']
    pm, rm, bm = shrink(photo8, side), shrink(res8, side), shrink(alb8, side)
    am = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize(pm.shape[1::-1], Image.BILINEAR)) > 128
    corr, en, lmed = hf_metrics(pm, rm, ndi.binary_erosion(am, iterations=4))
    lp, lq, used = light_spread(pm, rm, bm, am, rules['light'])
    na = lp is None or lp < rules['light']['na_spread_below']        # света на фото мало (студийный рендер) — мерка N/A
    return pm, rm, {'hf_corr': corr, 'hf_energy_ratio': en, 'L_median': lmed, 'light_spread_photo': lp, 'light_spread_result': lq,
                    'light_clusters': used, 'light_ratio': None if lp is None or lp <= 0 else lq / lp, 'light_na': bool(na)}


# ---------- модель ----------

def marigold_albedo(small_img, rules):
    """albedo Marigold IID-Appearance v1.1 (диффузеры, fp32, ЦП) по картинке на сером фоне; нужны torch и diffusers (в CI не ставятся — там подмена)."""
    if _PIPE[0] is None:
        import diffusers
        import torch
        torch.set_num_threads(int(os.environ.get('THREADS', '3')))
        _PIPE[0] = diffusers.MarigoldIntrinsicsPipeline.from_pretrained(rules['model']['id'], variant='fp16', torch_dtype=torch.float32).to('cpu')
    pipe = _PIPE[0]
    res = pipe(small_img, num_inference_steps=rules['model']['steps'], ensemble_size=1, processing_resolution=rules['model']['res'], match_input_resolution=True)
    return pipe.image_processor.visualize_intrinsics(res.prediction, pipe.target_properties)[0]['albedo'].convert('RGB')


def albedo_for(d, bg_full, rules, model_fn=None):
    """albedo по фото на сером фоне; кэш в папке этапа; вход сжат до model.iid_side, результат растянут до размера фото."""
    cache = os.path.join(d, 'albedo-iid-v11.png')
    if os.path.exists(cache):
        return Image.open(cache).convert('RGB').resize(bg_full.size, Image.BICUBIC), 0.0
    t = time.time()
    k = min(1.0, rules['model']['iid_side'] / max(bg_full.size))
    small = bg_full if k >= 1 else bg_full.resize((round(bg_full.size[0] * k), round(bg_full.size[1] * k)), Image.LANCZOS)
    alb = (model_fn or marigold_albedo)(small, rules).resize(small.size)
    alb.save(cache)
    return alb.resize(bg_full.size, Image.BICUBIC), time.time() - t


# ---------- этап ----------

def _font():
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(p, 16)
        except OSError:
            continue
    return ImageFont.load_default()


def frame(photo8, res8, title_l, title_r, path):
    h, w = photo8.shape[:2]
    im = Image.new('RGB', (w * 2, h + 28), 'white')
    im.paste(Image.fromarray(photo8), (0, 28))
    im.paste(Image.fromarray(res8), (w, 28))
    d = ImageDraw.Draw(im)
    f = _font()
    d.text((8, 5), title_l, fill='black', font=f)
    d.text((w + 8, 5), title_r, fill='black', font=f)
    im.save(path)


CAMERA_STAGE = '04-camera'


class PhotoRefused(Exception):
    """Фото для этапа 05 нельзя взять от камеры (нет пути, камера не прошла, фото не то)."""


def camera_photo(run, sku, declared=None):
    """Путь фото — ТОЛЬКО из check.json этапа 04 в этом же прогоне (`extra.photo`). Нет пути / камера не прошла / `declared` не совпал → PhotoRefused с причиной."""
    cam = PS.read_check(os.path.join(run, PS.safe_name(sku), CAMERA_STAGE))
    if cam is None:
        raise PhotoRefused(f'нет {CAMERA_STAGE}/check.json в {run} — камера не посчитана, фото брать неоткуда')
    path = (cam.get('extra') or {}).get('photo')
    if not path:
        raise PhotoRefused(f'этап {CAMERA_STAGE} не записал путь к фото (extra.photo) — своё фото этап 05 не выбирает')
    if not os.path.isfile(path):
        raise PhotoRefused(f'фото камеры не найдено: {path}')
    if cam.get('passed') is False:
        raise PhotoRefused(f'камера не прошла ({cam.get("reason") or "passed=false"}) — снимать свет не на чем')
    if declared and os.path.realpath(declared) != os.path.realpath(path):
        raise PhotoRefused(f'фото не то, что у камеры: в манифесте {declared}, у камеры {path}')
    return path


def run_one(sku, run, rules, declared=None, sigma=None, force=False, model_fn=None):
    """Один товар → (check.json-словарь, пропущен_как_готовый). Фото — от камеры (`camera_photo`); отказ пишется в check.json 05 (passed=false, причина), исключения нет."""
    d = PS.stage_dir(run, sku, STAGE)
    try:
        path = camera_photo(run, sku, declared)
    except PhotoRefused as e:
        return PS.write_check(d, STAGE, sku, False, None, str(e), outputs=[], refused=True, independent_check='pending'), False
    old = PS.read_check(d)
    if old is not None and not force and not old['extra'].get('refused') and old['extra'].get('source_photo') == path \
            and os.path.exists(os.path.join(d, 'delight.rgba.png')):
        return old, True
    return _delight_file(sku, path, run, rules, sigma, model_fn)


def _delight_file(sku, path, run, rules, sigma=None, model_fn=None):
    """Снять свет с файла `path` (его даёт только `run_one` — от камеры)."""
    sigma = rules['sigma'] if sigma is None else sigma
    d = PS.stage_dir(run, sku, STAGE)
    t0 = time.time()
    im = Image.open(path).convert('RGBA')
    alpha = np.asarray(im)[..., 3]
    a = alpha > 128
    if a.sum() < rules['min_mask_px']:
        raise ValueError(f'маска предмета пуста ({int(a.sum())} px) — вырезка не годится')
    g = rules['bg_grey']
    bg = Image.new('RGB', im.size, (g, g, g))
    bg.paste(im, mask=im.split()[3])
    photo8 = np.asarray(bg)
    alb_img, sec_iid = albedo_for(d, bg, rules, model_fn)
    alb8 = np.array(alb_img)
    alb8[~a] = photo8[~a]
    res8 = soft_transfer(photo8, alb8, a, sigma)
    pm, rm, mm = evaluate(photo8, res8, alb8, a, rules)
    Image.fromarray(np.dstack([res8, alpha]), 'RGBA').save(os.path.join(d, 'delight.rgba.png'))
    frame(pm, rm, f'фото магазина — {sku}', f'снят свет (мягко, σ {sigma * 100:.1f} %) — этап 05', os.path.join(d, PS.FRAME))
    fmt = lambda v: None if v is None else round(float(v), 3)  # noqa: E731
    lr = rules['light']
    ratio, na = mm['light_ratio'], mm['light_na']
    doc = PS.write_check(
        d, STAGE, sku, None,
        {'name': 'iid_shading_removed', 'value': fmt(ratio), 'threshold': lr['ratio_max'], 'op': '<=', 'na': bool(na),
         'ok': None if na else PS.judge(ratio, '<=', lr['ratio_max']),
         'note': ('N/A: света на фото мало (разброс низкочастотной яркости внутри цветового участка < %s L*) — passed не краснеет' % lr['na_spread_below']) if na
         else 'результат/фото по разбросу низкочастотной яркости в участках цвета; это «убрано то, что IID счёл светом», не доказательство, что свет снят'},
        metrics={'hf_corr': {'value': fmt(mm['hf_corr']), 'threshold': rules['hf_corr_min'], 'op': '>='},
                 'hf_energy_ratio': {'value': fmt(mm['hf_energy_ratio']), 'threshold': rules['hf_energy_min'], 'op': '>='}},
        seconds=time.time() - t0, outputs=['delight.rgba.png', 'albedo-iid-v11.png'], frame=PS.FRAME,
        independent_check='pending', source_photo=path, size=list(im.size), sigma=sigma, sec_iid=round(sec_iid, 1), L_median=fmt(mm['L_median']),
        light_spread_photo=fmt(mm['light_spread_photo']), light_spread_result=fmt(mm['light_spread_result']), light_clusters=mm['light_clusters'], light_na=bool(na),
        rules=os.path.relpath(RULES_PATH, HERE) if rules is not None else None,
        method='albedo Marigold IID-Appearance v1.1 → только низкие частоты света: фото × blur(Y_albedo)/blur(Y_фото), норма по медиане; детали и цвет — с фото')
    return doc, False


def table(run, man):
    """Таблица по готовым check.json (по порядку манифеста) + кадры best/median/worst по товарам, где света достаточно. → число строк."""
    rows = []
    for it in man:
        doc = PS.read_check(os.path.join(run, PS.safe_name(it['sku']), STAGE))
        if not doc:
            continue
        ex, ms, m = doc['extra'], doc['metrics'], doc['metric'] or {}
        if ex.get('refused'):
            rows.append([it['sku'], '', None, '', None, None, None, None, None, 0, doc['reason']])
            continue
        rows.append([it['sku'], 'x'.join(map(str, ex['size'])), m['value'], 'N/A' if m.get('na') else '', ms['hf_corr']['value'], ms['hf_energy_ratio']['value'],
                     ex.get('light_spread_photo'), ex.get('light_spread_result'), ex.get('light_clusters'), int(doc['passed']), doc['reason']])
    with open(os.path.join(run, 'table-05-delight.tsv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, delimiter='\t')
        w.writerow(['sku', 'size', 'iid_shading_removed', 'na', 'hf_corr', 'hf_energy_ratio', 'light_spread_photo', 'light_spread_result', 'clusters', 'passed', 'reason'])
        w.writerows(rows)
    ranked = sorted([r for r in rows if r[2] is not None and r[3] != 'N/A'], key=lambda r: r[2])
    if ranked:
        pick = os.path.join(run, '_pick-05-delight')
        os.makedirs(pick, exist_ok=True)
        for tag, r in (('best', ranked[0]), ('median', ranked[len(ranked) // 2]), ('worst', ranked[-1])):
            shutil.copyfile(os.path.join(run, PS.safe_name(r[0]), STAGE, PS.FRAME), os.path.join(pick, f'{tag}-{PS.safe_name(r[0])}.png'))
    return len(rows)


def cmd_run(run, manifest, force=False):
    rules = load_rules()
    sigma = float(os.environ['SIGMA']) if os.environ.get('SIGMA') else None
    man = json.load(open(manifest, encoding='utf-8'))
    os.makedirs(run, exist_ok=True)
    fails, refused, t0, ok = [], [], time.time(), 0
    for n, it in enumerate(man, 1):
        try:
            doc, cached = run_one(it['sku'], run, rules, it.get('path'), sigma, force)
            if doc['extra'].get('refused'):
                refused.append((it['sku'], doc['reason']))
                print(f'[{n}/{len(man)}] {it["sku"]} ОТКАЗ: {doc["reason"]}', flush=True)
                continue
            ok += 1
            m = doc.get('metric') or {}
            print(f'[{n}/{len(man)}] {it["sku"]} {"(готово раньше)" if cached else ""} passed={doc["passed"]} iid_shading_removed={m.get("value")}{" N/A" if m.get("na") else ""} '
                  f'hf_corr={(doc["metrics"].get("hf_corr") or {}).get("value")} {doc.get("seconds")} с', flush=True)
        except Exception as e:  # noqa: BLE001 — сбой одного товара не валит остальные, но считается и печатается
            fails.append((it['sku'], f'{type(e).__name__}: {e}'))
            print(f'[{n}/{len(man)}] {it["sku"]} СБОЙ {type(e).__name__}: {e}', flush=True)
            traceback.print_exc()
    rows = table(run, man)
    print(f'готово: {ok}/{len(man)} товаров за {time.time() - t0:.0f} с, строк в таблице {rows}, отказов {len(refused)}: {refused}, сбоев {len(fails)}: {fails}', flush=True)
    return 1 if fails else 0


# ---------- самопроверка на синтетике (без модели) ----------

def _synthetic(size=288, ramp=0.6, seed=3):
    """Эллипс цвета base с «стёжкой» (шахматка ±) и плавным светом слева→справа (ramp: яркость 1−ramp/2 … 1+ramp/2). → (rgba фото, «идеальный albedo» = то же без света)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    mask = (((xx - size / 2) / (size * 0.42)) ** 2 + ((yy - size / 2) / (size * 0.32)) ** 2) <= 1
    stitch = 1 + 0.07 * np.sign(np.sin(xx / 6.0) * np.sin(yy / 6.0)) + rng.normal(0, 0.01, (size, size))
    base = np.array([150.0, 90.0, 70.0])
    flat = base[None, None] * stitch[..., None]
    light = (1 - ramp / 2) + ramp * (xx / size)
    photo = np.clip(flat * light[..., None], 0, 255)
    alb = np.clip(flat, 0, 255)
    rgba = np.dstack([photo, np.where(mask, 255, 0)]).astype(np.uint8)
    return rgba, alb.astype(np.uint8)


def selftest() -> int:
    import tempfile
    import remlab_tmp
    remlab_tmp.use('paint_delight_selftest')
    rules = load_rules()
    assert rules['light']['ratio_max'] > 0 and rules['sigma'] > 0
    bad = 0

    def ok(cond, what):
        nonlocal bad
        if not cond:
            bad += 1
            print('НЕТ:', what)
    with tempfile.TemporaryDirectory(prefix='delight-') as tmp:
        for tag, ramp in (('lit', 0.6), ('flat', 0.0)):
            rgba, alb = _synthetic(ramp=ramp)
            src = os.path.join(tmp, f'{tag}.png')
            Image.fromarray(rgba, 'RGBA').save(src)
            run = os.path.join(tmp, 'run')
            fake = (lambda small, r, alb=alb: Image.fromarray(alb).resize(small.size))      # подмена модели: «идеальный» albedo без света
            PS.write_check(PS.stage_dir(run, tag, CAMERA_STAGE), CAMERA_STAGE, tag, True, None, '', photo=src)      # «камера» записала путь фото
            doc, cached = run_one(tag, run, rules, model_fn=fake)
            d = PS.stage_dir(run, tag, STAGE)
            out = np.asarray(Image.open(os.path.join(d, 'delight.rgba.png')))
            ok(not cached and out.shape == rgba.shape, f'{tag}: размер сохранён')
            ok((out[..., 3] == rgba[..., 3]).all(), f'{tag}: альфа сохранена')
            ok(os.path.exists(os.path.join(d, PS.FRAME)) and doc['extra']['independent_check'] == 'pending', f'{tag}: кадр и independent_check=pending')
            ok(doc['metric']['name'] == 'iid_shading_removed' and 'light_spread_ratio' not in json.dumps(doc), f'{tag}: имя мерки')
            ok(doc['metrics']['hf_corr']['value'] >= rules['hf_corr_min'], f'{tag}: стёжка цела hf_corr={doc["metrics"]["hf_corr"]["value"]}')
            if tag == 'lit':
                ok(not doc['metric']['na'] and doc['metric']['value'] <= rules['light']['ratio_max'] and doc['passed'], f'lit: свет снят ratio={doc["metric"]["value"]}')
                a = rgba[..., 3] > 128
                lp, lq = lab_l(np.asarray(Image.fromarray(rgba[..., :3]))), lab_l(out[..., :3])
                ok(np.percentile(lq[a], 90) - np.percentile(lq[a], 10) < 0.5 * (np.percentile(lp[a], 90) - np.percentile(lp[a], 10)), 'lit: разброс яркости упал вдвое')
            else:
                ok(doc['metric']['na'] and doc['metric']['ok'] is None and doc['passed'], 'flat: света мало → N/A, passed не краснеет')
        # повтор — готовое не пересчитывается; кэш albedo берётся с диска
        doc2, cached2 = run_one('lit', run, rules, model_fn=lambda *a: (_ for _ in ()).throw(AssertionError('модель не нужна')))
        ok(cached2 and doc2['passed'], 'повтор пропущен как готовый')
        # пустая маска → ошибка словами
        empty = os.path.join(tmp, 'empty.png')
        Image.fromarray(np.zeros((64, 64, 4), np.uint8), 'RGBA').save(empty)
        PS.write_check(PS.stage_dir(run, 'empty', CAMERA_STAGE), CAMERA_STAGE, 'empty', True, None, '', photo=empty)
        try:
            run_one('empty', run, rules)
            ok(False, 'пустая маска должна падать')
        except ValueError:
            pass
        # фото — только от камеры: другой путь в манифесте / нет пути / нет камеры / камера не прошла → отказ с причиной, без картинки
        other = os.path.join(tmp, 'flat.png')
        PS.write_check(PS.stage_dir(run, 'nopath', CAMERA_STAGE), CAMERA_STAGE, 'nopath', True, None, '')                                  # камера не записала путь
        PS.write_check(PS.stage_dir(run, 'camfail', CAMERA_STAGE), CAMERA_STAGE, 'camfail', False, None, 'не легла', photo=other)        # камера не прошла
        no_model = lambda *a: (_ for _ in ()).throw(AssertionError('модель не нужна при отказе'))  # noqa: E731
        for what, sku, declared in (('в манифесте другое фото', 'lit', other), ('нет камеры', 'nocam', None), ('нет пути', 'nopath', None), ('камера не прошла', 'camfail', None)):
            doc3, _ = run_one(sku, run, rules, declared, force=True, model_fn=no_model)
            ok(doc3['passed'] is False and doc3['extra'].get('refused') and doc3['reason'] and not doc3['outputs'], f'отказ: {what} → {doc3["reason"][:60]}')
        ok('фото не то' in run_one('lit', run, rules, other, force=True, model_fn=no_model)[0]['reason'], 'отказ «фото не то, что у камеры»')
        ok(table(run, [{'sku': 'lit'}, {'sku': 'flat'}]) == 2, 'таблица по готовым check.json')
        # параметры чужого σ: больше σ — снято меньше
        rgba, alb = _synthetic()
        im = Image.fromarray(rgba, 'RGBA')
        bg = Image.new('RGB', im.size, (rules['bg_grey'],) * 3)
        bg.paste(im, mask=im.split()[3])
        p8, a = np.asarray(bg), rgba[..., 3] > 128
        al = alb.copy()
        al[~a] = p8[~a]
        ratios = []
        for sg in (rules['sigma'], 0.25):
            _, _, mm = evaluate(p8, soft_transfer(p8, al, a, sg), al, a, rules)
            ratios.append(mm['light_ratio'])
        ok(ratios[0] < ratios[1], f'больше σ — снято меньше {ratios}')
    print('paint_delight selftest:', 'OK' if not bad else f'{bad} сбоев')
    return 1 if bad else 0


def main(argv):
    if argv[:1] == ['--selftest']:
        return selftest()
    if argv[:1] == ['run'] and len(argv) >= 3:
        return cmd_run(argv[1], argv[2], '--force' in argv)
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
