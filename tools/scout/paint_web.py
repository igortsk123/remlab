#!/usr/bin/env python3
"""Этап 10 «сайт» нового пути покраски (план paint-photo-fill-01; T-20261121-171/1; P-040 ≤5 МБ, P-059 на сайт — только после «принято» владельца).
Крашеная модель этапа 9 → лёгкая копия `web.glb` для сайта + проверка «на глаз не отличить». НА САЙТ НЕ ВЫКЛАДЫВАЕТ (выкладка — `tools/assets/publish_rt.sh`, отдельным шагом).

Лёгкая копия собирается ТЕМ ЖЕ кодом, что копии сайта: `tools/assets/runtime_mesh.py:build_light` (лестница веса из `rules/rt-weight.json`: текстура 1024 → 512 → упрощение граней,
gltfpack: meshopt + KTX2). Порог ВЕСА — только в rt-weight.json; пороги ПОХОЖЕСТИ — только в `rules/paint-web.json`; в коде порогов и ID товаров нет.
Пишет `<run>/<sku>/10-web/`: `web.glb`, `check.json` (через paint_stage), `frame.png` («полная | лёгкая», ракурс `max_diff_view`), `web-real.glb` и кадры `<full|web>-<вид>.png`.

ПОХОЖЕСТЬ: кадры «лёгкой» снимаются с НАСТОЯЩЕГО `web.glb`: его KTX2-картинку раскодирует утилита `ktx` (KTX-Software ≥4.4, переменная KTX или PATH) в PNG, и PNG встаёт на место KTX2
(копия `web-real.glb`: геометрия meshopt, UV и материал — те же, что поедут на сайт; Blender KTX2 не читает, поэтому подмена). Потеря на KTX2 попадает в кадры и в мерки; отдельно в check.json
`extra.ktx2_tex` — ΔE00 самой текстуры (раскодированная против карты цвета полной); `ktx2_measured=true`. Нет утилиты `ktx` — этап НЕ проходит (причина словами), молча к JPEG-двойнику не возвращается.
Кадры — Cycles на ЦП (Workbench/Eevee тут не стартуют: нет libEGL), излучающие материалы = плоский свет, камеры `views` одинаковые у полной и лёгкой.
Мерки по маске товара (непрозрачные пиксели обоих кадров): ΔE00 среднее и 95-й процентиль, SSIM на сером фоне, IoU силуэта; худший из ракурсов.

  paint_web.py run <run> <sku> <glb>             один товар
  paint_web.py batch <run> <папка-с-GLB> [--force] [--limit N]   все `*<sku_suffix>.glb` папки (суффикс — в правиле); таблица → <run>/summary-10-web.md
  paint_web.py table <run>                      только таблица по готовым check.json
  paint_web.py --selftest
Окружение: `PAINT_STAGE_DIR` — папка с paint_stage.py (пока он не в main), `BLENDER` — бинарь Blender, `KTX` — бинарь ktx (KTX-Software).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules')
STAGE = '10-web'
BLENDER = os.environ.get('BLENDER') or os.path.expanduser('~/opt/blender-5.3.0-linux-x64/blender')

if os.environ.get('PAINT_STAGE_DIR'):
    sys.path.insert(0, os.environ['PAINT_STAGE_DIR'])
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'assets'))
import paint_stage as PS  # noqa: E402  (общий писатель check.json)
import runtime_mesh as RM  # noqa: E402  (лестница веса и сборка лёгкой копии — те же, что у сайта)


def pick_light(src: bytes, dst: str, rule: dict, weight: dict, fallback: bool = True) -> tuple[dict, str]:
    """Лёгкая копия «лучшее, что влезает»: `candidates` из правила по порядку убывания качества (размер текстуры, ключи gltfpack), первый влезший в вес — победитель.
    Ни один не влез — запасная обычная лестница сайта (rt-weight.json: размер ↓, упрощение граней), её отказ и есть причина (fallback=False — без неё: `ok` False). → (res со `steps`, метка)."""
    one, steps = {**weight, 'ladder': []}, []
    res, label = {}, ''
    for c in rule['candidates']:
        label = str(c['size']) + (' ' + ' '.join(c['tex_flags']) if c['tex_flags'] else '')
        res = RM.build_light(src, dst, int(c['size']), int(rule['quality']), 0.0, True, one, tuple(c['tex_flags']))
        t = res['tried'][-1] if res['tried'] else {}
        steps.append([label, t.get('bytes'), t.get('skip') or t.get('problems')])
        if res['ok']:
            return {**res, 'steps': steps}, label
    if not fallback:
        return {**res, 'steps': steps}, label
    res = RM.build_light(src, dst, int(rule['candidates'][0]['size']), int(rule['quality']), 0.0, True, weight)
    steps += [[t['step'], t.get('bytes'), t.get('skip') or t.get('problems')] for t in res['tried']]
    return {**res, 'steps': steps}, ('лестница сайта: ' + res['tried'][-1]['step'] if res['tried'] else 'лестница сайта')


def load_rule(path: str | None = None) -> dict:
    """Правило похожести; пороги проверены: у каждого op из paint_stage и число."""
    r = json.load(open(path or os.path.join(RULES, 'paint-web.json'), encoding='utf-8'))
    cs = r.get('candidates')
    if not cs or any(not isinstance(c.get('size'), int) or not isinstance(c.get('tex_flags'), list) for c in cs):
        raise ValueError('paint-web.json: candidates — список {size: число, tex_flags: список}, по убыванию качества')
    for k, t in r['thresholds'].items():
        if t.get('op') not in PS.OPS or not isinstance(t.get('value'), (int, float)):
            raise ValueError(f'paint-web.json: порог {k}: нужен op из {sorted(PS.OPS)} и число')
    return r


# ── цвет и сходство ───────────────────────────────────────────────────────────────────────────────────────────────

def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..1 (N×3) → Lab (D65)."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], -1)


def ciede2000(l1: np.ndarray, l2: np.ndarray) -> np.ndarray:
    """ΔE2000 (Sharma 2005), векторно: N×3 Lab и N×3 Lab → N."""
    L1, a1, b1 = l1[:, 0], l1[:, 1], l1[:, 2]
    L2, a2, b2 = l2[:, 0], l2[:, 1], l2[:, 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0.0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hbp = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = 1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp)) + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63))
    dth = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def _box(x: np.ndarray, k: int = 7) -> np.ndarray:
    p = k // 2
    c = np.cumsum(np.cumsum(np.pad(np.asarray(x, np.float64), p, mode='edge'), 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ssim_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Карта SSIM двух серых картинок 0..1, окно 7×7."""
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)          # float32 в накопительных суммах терял разряды: SSIM выходил >1
    ma, mb = _box(a), _box(b)
    va, vb, cov = _box(a * a) - ma * ma, _box(b * b) - mb * mb, _box(a * b) - ma * mb
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))


def _load_rgba(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert('RGBA'), np.float32) / 255.0


def _on_grey(img: np.ndarray) -> np.ndarray:
    a = img[..., 3:4]
    return img[..., :3] * a + 0.5 * (1 - a)


def compare_images(full: np.ndarray, web: np.ndarray) -> dict:
    """Мерки двух RGBA-кадров (0..1) одной камеры. ΔE00 — по пикселям, где оба кадра непрозрачны (кромку сглаживания не считаем).
    SSIM — на сером фоне, по внутренней части товара."""
    af, aw = full[..., 3], web[..., 3]
    inner = (af > 0.99) & (aw > 0.99)
    inter, union = ((af > 0.5) & (aw > 0.5)).sum(), ((af > 0.5) | (aw > 0.5)).sum()
    out = {'silhouette_iou': float(inter / union) if union else 0.0, 'px': int(inner.sum())}
    if inner.sum() == 0:
        return {**out, 'de00_mean': None, 'de00_p95': None, 'ssim': None}
    de = ciede2000(srgb_to_lab(full[..., :3][inner]), srgb_to_lab(web[..., :3][inner]))
    gf, gw = _on_grey(full), _on_grey(web)
    lum = np.array([0.2126, 0.7152, 0.0722], np.float32)
    s = ssim_map(gf @ lum, gw @ lum)
    # SSIM — по ВНУТРЕННЕЙ части товара (отступ 4 px от кромки): форму и кромку проверяет силуэт IoU, а окно 7×7 на кромке цепляет серый фон
    core = _box(inner.astype(np.float32), 9) > 0.999
    mask = core if core.sum() else inner
    if not mask.sum():
        return {**out, 'de00_mean': float(de.mean()), 'de00_p95': float(np.percentile(de, 95)), 'ssim': None}
    return {**out, 'de00_mean': float(de.mean()), 'de00_p95': float(np.percentile(de, 95)), 'ssim': float(s[mask].mean())}


# ── сборка и проверка ─────────────────────────────────────────────────────────────────────────────────────────────

def _atlas_px(src: bytes) -> int:
    """Наибольшая сторона картинки под картой цвета исходной модели (px)."""
    js, bin_chunk = RM.parse_glb(src)
    best = 0
    for im in js.get('images', []):
        raw = RM.image_bytes(im, js, bin_chunk)
        if raw:
            best = max(best, max(Image.open(io.BytesIO(raw)).size))
    return best


def _render(cfg: dict, timeout: int) -> tuple[bool, str, dict]:
    """Blender рисует кадры полной и лёгкой одной камерой. → (ок, сообщение, {путь GLB: {'tris': n, 'img': [w, h]}})."""
    cmd = ['nice', '-n', '19', BLENDER, '-b', '-P', os.path.join(HERE, 'paint_web_render.py'), '--', json.dumps(cfg)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f'Blender не уложился в {timeout} с', {}
    info: dict = {}
    for line in p.stdout.splitlines():
        parts = line.split()
        if parts[:1] == ['TRIS'] and len(parts) == 3:
            info.setdefault(parts[1], {})['tris'] = int(parts[2])
        elif parts[:1] == ['IMG'] and len(parts) == 4:
            info.setdefault(parts[1], {}).setdefault('img', [int(parts[2]), int(parts[3])])
    if 'RENDER_DONE' not in p.stdout:
        tail = (p.stderr or p.stdout).strip().splitlines()
        return False, 'Blender не дорисовал: ' + (tail[-1][:160] if tail else f'код {p.returncode}'), info
    return True, '', info


def run_one(run: str, sku: str, glb: str, rule: dict | None = None, weight: dict | None = None, force: bool = False) -> dict:
    """Этап 10 для одного товара → check.json (словарь). Не выкладывает.
    Кандидаты правила пробуются по убыванию качества: победитель — первый, что и влез в вес, и прошёл мерки (по тем же порогам). «Влез» ≠ «прошёл»:
    у одних товаров выигрывает меньший размер без урезания кодека, у других — больший с урезанием, наперёд не угадать. Ни один не прошёл — в check.json лучший
    из влезших (первый по порядку), с причиной; ни один не влез — запасная лестница сайта."""
    rule = rule or load_rule()
    weight = weight or RM.weight_rule()
    t0 = time.time()
    d = PS.stage_dir(run, sku, STAGE)
    src = open(glb, 'rb').read()
    sha = hashlib.sha256(src).hexdigest()[:16]
    prev = PS.read_check(d)
    if prev and not force and prev.get('extra', {}).get('glb_sha') == sha and prev.get('extra', {}).get('rule') == _rule_fp(rule, weight) and not prev['extra'].get('no_tool'):
        return prev
    ktx = ktx_bin(rule)
    if not ktx:        # до всякой сборки: без утилиты проверку по настоящей текстуре не сделать — честный отказ словами (кэш такого отказа не берётся: поставили утилиту — пересчитается)
        return PS.write_check(d, STAGE, sku, passed=False, metric={'name': 'ktx_tool', 'value': 0, 'threshold': 1, 'op': '>='}, seconds=time.time() - t0, outputs=[],
                              reason='нет утилиты ktx (KTX-Software): поставить tools/ops/install-ktx.sh или задать переменную KTX — потеря на KTX2 не измерена',
                              glb_sha=sha, rule=_rule_fp(rule, weight), ktx2_measured=False, no_tool=True, bytes_before=len(src))
    earlier, first_fit = [], None
    for c in rule['candidates']:
        ck = _attempt(run, sku, glb, dict(rule, candidates=[c]), weight, ktx, t0, earlier, False, _rule_fp(rule, weight))
        if ck['passed']:
            return ck
        if ck['extra'].get('fits'):
            first_fit = first_fit or c
        earlier.append([ck['extra'].get('texture_step') or str(c['size']), ck.get('reason', '')[:100]])
    if first_fit is None:      # ни один не влез — запасная лестница сайта
        return _attempt(run, sku, glb, rule, weight, ktx, t0, earlier, True, _rule_fp(rule, weight))
    return _attempt(run, sku, glb, dict(rule, candidates=[first_fit]), weight, ktx, t0, earlier, False, _rule_fp(rule, weight))   # ни один не прошёл: файлы и кадры — лучшего из влезших


def _attempt(run: str, sku: str, glb: str, rule: dict, weight: dict, ktx: str, t0: float, earlier: list, fallback: bool, fp: str) -> dict:
    """Одна попытка этапа 10 с кандидатами `rule['candidates']` (обычно один): сборка → раскодирование KTX2 → кадры → мерки → check.json (extra.fits — влез ли в вес)."""
    d = PS.stage_dir(run, sku, STAGE)
    src = open(glb, 'rb').read()
    sha = hashlib.sha256(src).hexdigest()[:16]
    web, real = os.path.join(d, 'web.glb'), os.path.join(d, 'web-real.glb')
    res, label = pick_light(src, web, rule, weight, fallback)
    steps = res['steps']
    base = {'glb_sha': sha, 'rule': fp, 'steps': steps, 'tried_before': earlier, 'fits': bool(res['ok']), 'ktx2_measured': False, 'texture_pack': res.get('how', ''),
            'bytes_before': len(src), 'atlas_px_before': _atlas_px(src)}
    size_metric = {'name': 'bytes', 'value': res.get('bytes', 0), 'threshold': weight['max_bytes'], 'op': '<='}
    if not res['ok']:
        why = 'текстура упаковалась битой: ' + '; '.join(res['probs'])[:120] if res['kind'] == 'texture' else \
            f"тяжелее {weight['max_bytes'] / 1048576:.1f} МБ даже после лестницы ({label}: {res['bytes'] / 1048576:.2f} МБ)"
        return PS.write_check(d, STAGE, sku, passed=False, metric=size_metric, reason=why, seconds=time.time() - t0, outputs=[], **base)
    # кадры — с НАСТОЯЩЕГО web.glb: его KTX2-картинку раскодирует утилита ktx (KTX-Software), PNG встаёт на место KTX2 (геометрия и UV те же, что поедут на сайт)
    ok, why, tinfo = decode_web(web, real, ktx, d)
    if not ok:
        return PS.write_check(d, STAGE, sku, passed=False, metric=size_metric, reason=why, seconds=time.time() - t0, outputs=['web.glb'], bytes=res['bytes'],
                              texture_step=label, **base)
    base.update(ktx2_measured=True, ktx2_tool=tinfo['tool'], ktx2_tex=_tex_loss(src, tinfo['png']))
    cfg = {'views': rule['views'], 'res': rule['res'], 'margin': rule['ortho_margin'],
           'items': [{'glb': glb, 'out': os.path.join(d, 'full')}, {'glb': real, 'out': os.path.join(d, 'web')}]}
    ok, why, info = _render(cfg, int(rule.get('blender_timeout', 900)))
    base.update(bytes=res['bytes'], atlas_px_after=max(tinfo['size']), faces_before=info.get(glb, {}).get('tris'), faces_after=info.get(real, {}).get('tris'),
                texture_step=label)
    if not ok:
        return PS.write_check(d, STAGE, sku, passed=False, metric=size_metric, reason=why, seconds=time.time() - t0, outputs=['web.glb', 'web-real.glb'], **base)
    views = {v['name']: compare_images(_load_rgba(os.path.join(d, f"full-{v['name']}.png")), _load_rgba(os.path.join(d, f"web-{v['name']}.png")) ) for v in rule['views']}
    metrics = {}
    for k, t in rule['thresholds'].items():       # худший из ракурсов: для «≤» наибольшее, для «≥» наименьшее; нет измерения хоть в одном — мерка не прошла
        xs = [m.get(k) for m in views.values()]
        worst = None if any(x is None for x in xs) else (max(xs) if t['op'] in ('<=', '<') else min(xs))
        metrics[k] = {'value': None if worst is None else round(worst, 4), 'threshold': t['value'], 'op': t['op']}
    metrics['bytes'] = size_metric
    frame = _frame(d, rule['max_diff_view'])
    return PS.write_check(d, STAGE, sku, passed=None, metric={'name': 'de00_mean', **metrics.pop('de00_mean')}, metrics=metrics, seconds=time.time() - t0,
                          outputs=['web.glb', 'web-real.glb'], frame=frame, views=views, **base)


CODE_V = 2   # версия способа проверки (1 — JPEG-двойник, 2 — раскодированный KTX2): меняется — кэш прежних check.json не берётся


def _rule_fp(rule: dict, weight: dict) -> str:
    return hashlib.sha256(json.dumps([rule, weight.get('fingerprint'), CODE_V], sort_keys=True).encode()).hexdigest()[:8]


def ktx_bin(rule: dict | None = None) -> str | None:
    """Утилита ktx (KTX-Software ≥4.4): переменная KTX → PATH → путь из правила (`ktx_bin` в paint-web.json; ставит tools/ops/install-ktx.sh). Нет — None."""
    for p in (os.environ.get('KTX'), shutil.which('ktx'), os.path.expanduser((rule or {}).get('ktx_bin') or '')):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def decode_web(web_glb: str, out_glb: str, ktx: str, workdir: str) -> tuple[bool, str, dict]:
    """KTX2-картинки web.glb → PNG утилитой `ktx extract --transcode rgba8` и подмена в копии GLB (`out_glb`): геометрия, UV и материал — прежние, текстура — та,
    что реально раскодирует KTX2. → (ок, причина, {'png': путь PNG первой текстуры, 'size': [w, h], 'tool': версия})."""
    js, b = RM.parse_glb(open(web_glb, 'rb').read())
    b = bytearray(b)
    first: dict = {}
    for i, im in enumerate(js.get('images', [])):
        if im.get('mimeType') != 'image/ktx2':
            continue
        k, p = os.path.join(workdir, f'.tex{i}.ktx2'), os.path.join(workdir, f'tex{i}-ktx2.png')
        open(k, 'wb').write(RM.image_bytes(im, js, bytes(b)) or b'')
        try:
            r = subprocess.run([ktx, 'extract', '--transcode', 'rgba8', k, p], capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return False, 'ktx не раскодировал текстуру за 300 с', {}
        finally:
            if os.path.exists(k):
                os.remove(k)
        if r.returncode != 0 or not os.path.exists(p):
            return False, 'ktx не раскодировал текстуру: ' + ((r.stderr or r.stdout).strip().splitlines() or ['код ' + str(r.returncode)])[-1][:140], {}
        png = open(p, 'rb').read()
        while len(b) % 4:
            b.append(0)
        js['bufferViews'].append({'buffer': 0, 'byteOffset': len(b), 'byteLength': len(png)})
        b += png
        im.clear()
        im.update({'bufferView': len(js['bufferViews']) - 1, 'mimeType': 'image/png'})
        for t in js.get('textures', []):
            e = (t.get('extensions') or {}).get('KHR_texture_basisu')
            if e and e.get('source') == i:
                t['source'] = i
                del t['extensions']['KHR_texture_basisu']
                if not t['extensions']:
                    del t['extensions']
        first = first or {'png': p, 'size': list(Image.open(p).size)}
    if not first:
        return False, 'в web.glb нет KTX2-картинок (копия собрана без KTX2)', {}
    for key in ('extensionsUsed', 'extensionsRequired'):
        if key in js:
            js[key] = [e for e in js[key] if e != 'KHR_texture_basisu']
            if not js[key]:
                del js[key]
    js['buffers'][0]['byteLength'] = len(b)
    open(out_glb, 'wb').write(RM.write_glb(js, bytes(b)))
    ver = subprocess.run([ktx, '--version'], capture_output=True, text=True).stdout.strip().splitlines()
    return True, '', {**first, 'tool': (ver[0] if ver else 'ktx')[:60]}


def _base_color_png(src: bytes) -> Image.Image | None:
    """Картинка карты цвета (baseColorTexture первого материала) исходной модели."""
    js, b = RM.parse_glb(src)
    try:
        t = js['textures'][js['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index']]
        raw = RM.image_bytes(js['images'][t['source']], js, b)
        return Image.open(io.BytesIO(raw)).convert('RGB')
    except (KeyError, IndexError, TypeError):
        return None


def _tex_loss(src: bytes, png_path: str) -> dict:
    """Потеря самой текстуры: раскодированный из KTX2 PNG против карты цвета полной модели (приведённой к тому же размеру), ΔE00 по каждому 3-му пикселю."""
    ref = _base_color_png(src)
    if ref is None:
        return {'de00_mean': None, 'why': 'у полной модели нет карты цвета'}
    got = Image.open(png_path).convert('RGB')
    if ref.size != got.size:
        ref = ref.resize(got.size, Image.LANCZOS)
    a = np.asarray(ref, np.float64)[::3, ::3].reshape(-1, 3) / 255.0
    c = np.asarray(got, np.float64)[::3, ::3].reshape(-1, 3) / 255.0
    de = ciede2000(srgb_to_lab(a), srgb_to_lab(c))
    return {'de00_mean': round(float(de.mean()), 4), 'de00_p95': round(float(np.percentile(de, 95)), 4), 'size': list(got.size)}


def _frame(d: str, view: str) -> str:
    """frame.png — «полная | лёгкая» рядом, один ракурс, на сером."""
    a = _on_grey(_load_rgba(os.path.join(d, f'full-{view}.png')))
    b = _on_grey(_load_rgba(os.path.join(d, f'web-{view}.png')))
    sep = np.full((a.shape[0], 6, 3), 0.15, np.float32)
    Image.fromarray((np.concatenate([a, sep, b], 1) * 255).astype(np.uint8)).save(os.path.join(d, PS.FRAME))
    return PS.FRAME


# ── таблица и пакет ───────────────────────────────────────────────────────────────────────────────────────────────

def table(run: str) -> str:
    rows = ['| товар | МБ до → после | граней до → после | атлас до → после | ΔE00 среднее / p95 | SSIM | силуэт | ΔE текстуры после KTX2 | passed |', '|---|---|---|---|---|---|---|---|---|']
    for sku in sorted(os.listdir(run)) if os.path.isdir(run) else []:
        c = PS.read_check(os.path.join(run, sku, STAGE))
        if not c:
            continue
        e, m, ms = c['extra'], c.get('metric') or {}, c.get('metrics') or {}
        if m.get('name') != 'de00_mean':          # этап упал до сравнения: в главной мерке — вес, не ΔE
            m = {}
        mb = lambda x: '—' if x is None else f'{x / 1048576:.2f}'
        f = lambda x: '—' if x is None else f'{x:.2f}' if abs(x) >= 1 else f'{x:.3f}'
        rows.append(f"| {sku} | {mb(e.get('bytes_before'))} → {mb(e.get('bytes'))} | {e.get('faces_before', '—')} → {e.get('faces_after', '—')} | "
                    f"{e.get('atlas_px_before', '—')} → {e.get('atlas_px_after', '—')} | {f(m.get('value'))} / {f((ms.get('de00_p95') or {}).get('value'))} | "
                    f"{f((ms.get('ssim') or {}).get('value'))} | {f((ms.get('silhouette_iou') or {}).get('value'))} | {f((e.get('ktx2_tex') or {}).get('de00_mean'))} | "
                    f"{'✓' if c['passed'] else '✗ ' + (c.get('reason') or '')[:70]} |")
    return '\n'.join(rows)


def batch(run: str, folder: str, force: bool = False, limit: int | None = None) -> int:
    rule, weight = load_rule(), RM.weight_rule()
    suf = rule['sku_suffix']
    files = sorted(f for f in os.listdir(folder) if f.endswith(suf + '.glb'))
    if limit:
        files = files[:limit]
    bad = 0
    for i, f in enumerate(files, 1):
        sku = f[:-len(suf + '.glb')]
        try:
            c = run_one(run, sku, os.path.join(folder, f), rule, weight, force)
        except Exception as e:  # noqa: BLE001 — товар упал: называем причину, идём дальше (не молчим)
            c = PS.write_check(PS.stage_dir(run, sku, STAGE), STAGE, sku, passed=False, reason=f'этап упал: {type(e).__name__}: {str(e)[:120]}')
        bad += 0 if c['passed'] else 1
        print(f"[{i}/{len(files)}] {sku} passed={c['passed']} {c.get('reason', '')[:100]}", flush=True)
    t = table(run)
    open(os.path.join(run, 'summary-10-web.md'), 'w', encoding='utf-8').write(t + '\n')
    print(t)
    print(f'ИТОГО: {len(files)} товаров, не прошли {bad}')
    return 0 if bad == 0 else 1


# ── самопроверка ──────────────────────────────────────────────────────────────────────────────────────────────────

def selftest() -> int:
    import tempfile
    import remlab_tmp
    remlab_tmp.use('paint_web_selftest')
    # ΔE00: пары из таблицы Sharma 2005
    pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425), ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615), ((50, 2.5, 0), (50, 0, -2.5), 4.3065),
             ((50, 2.5, 0), (73, 25, -18), 27.1492), ((50, 2.5, 0), (50, 3.1736, 0.5854), 1.0000)]
    de = ciede2000(np.array([p[0] for p in pairs], float), np.array([p[1] for p in pairs], float))
    for got, p in zip(de, pairs):
        assert abs(got - p[2]) < 1e-3, (got, p)
    rng = np.random.default_rng(1)
    a = rng.random((64, 64))
    assert abs(ssim_map(a, a).mean() - 1) < 1e-9
    assert ssim_map(a, rng.random((64, 64))).mean() < 0.3
    # compare_images: одинаковые → 0 / 1; сдвинутый цвет → ΔE > 0; пустой кадр → None
    img = np.zeros((40, 40, 4), np.float32)
    img[8:32, 8:32] = [0.8, 0.4, 0.3, 1]
    same = compare_images(img, img.copy())
    assert same['de00_mean'] == 0 and same['silhouette_iou'] == 1 and abs(same['ssim'] - 1) < 1e-9
    other = img.copy()
    other[8:32, 8:32, :3] = [0.7, 0.4, 0.3]
    assert compare_images(img, other)['de00_mean'] > 3
    assert compare_images(np.zeros((8, 8, 4), np.float32), np.zeros((8, 8, 4), np.float32))['de00_mean'] is None
    # правило читается; порог без op — ошибка; в коде порогов нет (проверка по тексту этого файла: числа порогов — только в json)
    r = load_rule()
    assert set(r['thresholds']) >= {'de00_mean', 'de00_p95', 'ssim', 'silhouette_iou'} and r['views']
    with tempfile.TemporaryDirectory() as t:
        bad = os.path.join(t, 'r.json')
        json.dump({**r, 'thresholds': {'ssim': {'value': 1}}}, open(bad, 'w'))
        try:
            load_rule(bad)
            raise AssertionError('порог без op должен падать')
        except ValueError:
            pass
        # таблица и check.json на пустом пакете
        d = PS.stage_dir(t, 'x', STAGE)
        PS.write_check(d, STAGE, 'x', passed=False, metric={'name': 'bytes', 'value': 6000000, 'threshold': 5242880, 'op': '<='}, reason='тяжелее', bytes_before=9000000, bytes=6000000)
        assert 'тяжелее' in table(t)
    print('selftest ok')
    return 0


def main(argv: list[str]) -> int:
    if '--selftest' in argv:
        return selftest()
    if len(argv) >= 4 and argv[0] == 'run':
        c = run_one(argv[1], argv[2], argv[3], force='--force' in argv)
        print(json.dumps({k: c[k] for k in ('passed', 'reason', 'metric', 'metrics')}, ensure_ascii=False, indent=1))
        return 0 if c['passed'] else 1
    if len(argv) >= 3 and argv[0] == 'batch':
        lim = int(argv[argv.index('--limit') + 1]) if '--limit' in argv else None
        return batch(argv[1], argv[2], '--force' in argv, lim)
    if len(argv) == 2 and argv[0] == 'table':
        print(table(argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
