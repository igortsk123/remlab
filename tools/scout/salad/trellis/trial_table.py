#!/usr/bin/env python3
"""ТАБЛИЦА ПРОБЫ ГЕНЕРАТОРОВ МЕШЕЙ: товар × модель → CSV + markdown (план mesh-models-trial-01, шаг 3 «Числа»; T-20261118-91/4).

ЗАЧЕМ. KPI владельца (TG 2108) — цена ОДНОЙ модели, принятой автоматически без ручной правки. Скрипт общий для всех кандидатов
(trellis2, hunyuan, pixal3d, localmesh, гибриды): на вход — папка GLB каждой модели, на выход — строка на товар × модель и итог по модели:
доля принятых и «$ за одну принятую» = ВСЕ траты на модель / число принятых.

КОЛОНКИ (по товару × модели):
  готов / отказ + причина · время, с и $ из журналов драйвера (`summary-*.json` рядом с GLB; у боевого Hunyuan — `complete.json`) ·
  треугольники · МБ сырого GLB и МБ лёгкой копии нашей обычной веб-конвертацией (`tools/assets/runtime_mesh.py`: текстура 1024 → gltfpack) ·
  IoU силуэта спереди к вырезке (метод боевого `mesh_make.mesh_trusted`: обрезка по рамке, 256², лучшее по ракурсам) ·
  ΔE00 и ΔL по рендеру БЕЗ света (`mesh_render.py`, `UNLIT=1`: чистый baseColor против цвета вырезки, медианы Lab) ·
  `pattern_grad_ncc` — `tools/scout/pattern_metric.py` рабочего 4 (медиана по переднему кадру; СПРАВОЧНАЯ колонка, в автоприёмку не входит; своя — `--pattern-fn`) ·
  АВТОПРИЁМКА — вердикты БОЕВЫХ сторожей по итоговому GLB; «принят», только если все чистые:
     серый верх  — `mesh_grey_top.analyze` (ok/na чисто; candidate/reject — нет);
     пустой вид  — идея `salad/view_guard.py` по рендеру итогового GLB: вид сзади и сверху, внутри силуэта почти всё цвета пустого вида сети (128±TOL);
     цвет        — `mesh_color_check`: цвет поверхности модели против цвета вырезки (`surface_colour`/`photo_colour`/`diff`/`verdict`, пороги `rules/mesh-color-guard.json`).

ИТОГОВЫЙ GLB. Есть `*.clean.glb` (очистка `mesh_clean.py`: плита под предметом убрана) — судим его, иначе сырой. Вход вырезки — `inputs30/<ключ>.rgba.png` (одна и та же вырезка
для всех моделей; её хэш — в строке). Платного нет: только чтение и рендер на процессоре. Сторожа берём ФУНКЦИЯМИ (`analyze`, `surface_colour`, …), а не прогоном модуля.

РАСКЛАДКИ ПАПКИ МОДЕЛИ (`--model имя=папка`; без `=` папка — `<корень>/<имя>`):
  плоская   `<ключ>-1024-42-0.glb` (+ `.clean.glb`, `.audit.glb`, `.metrics.json`)   — TRELLIS.2 пробы;
  по папкам `<ключ>/model.glb` (+ `model.clean.glb`) или `<ключ>/<метка>/model.glb` + `complete.json` — боевое хранилище Hunyuan
            (`~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2`; берётся новейший прогон).
  Ключ товара = `sku` из набора с `:` → `_`.

  ~/venvs/scout/bin/python trial_table.py --set <корень>/trellis/set30.json --out ДИР \
      --model trellis2=<корень>/trellis --model hunyuan=~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2 [--workers 2] [--no-lite]
  `--model` понимает приписку: `имя=папка?suffix=-1024-42-0&sum=hunyuan21&variant=&kpi=trellis2-r30&pilot=-s0` — точное имя файла после ключа, сводки только этой модели, задания
  без/с вариантом, траты для KPI — по группам (регулярка имени группы), пилоты «встать» отдельной колонкой (в $ за принятую не входят).
  ОБЩАЯ ПАПКА ВЫВОДА: драйверы моделей пишут `<ключ>-1024-42-0.glb` в одну папку и перезаписывают друг друга; с `sum=` файл признаётся своим, только если его размер
  (сырой; `size_mb` журнала — МиБ) и число треугольников (`.clean.glb`, по `*.metrics.json`) совпадают с журналом задания этой модели (`owned`); иначе строка «нет: перезаписан».
  python3 trial_table.py --selftest        # без trimesh/рендера: ΔE00, IoU, раскладки, расчёт итогов и автоприёмки
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
REPO = os.path.normpath(os.path.join(SCOUT, '..', '..'))
ROOT = os.path.expanduser('~/remlab-logs/mesh-models-1118')
RULES_GROUPS = os.path.join(SCOUT, 'rules', 'salad-groups.json')
VERSION = 'tt-2'                      # версия расчёта: меняется формула/ракурсы/пороги — старые кэши строк не берём

IOU_SIZE = (256, 256)
IOU_ALPHA = 90                        # как в `mesh_make.mesh_trusted`
THIN_R = 3                            # радиус «открытия» маски (px при 256²): ножки/спицы тоньше ~6 px исчезают из обеих масок


def _battle_min_iou() -> float:
    """Порог силуэта — БОЕВОЙ: значение `min_iou` по умолчанию у `mesh_make.mesh_trusted` (читаем из исходника: импорт модуля тянет fal/viz_*;
    все боевые вызовы — `viz_build`, `viz_paste` — зовут без своего порога). Своего числа тут нет: поменяют боевое — поменяется и тут."""
    m = re.search(r'def mesh_trusted\([^)]*min_iou:\s*float\s*=\s*([0-9.]+)', open(os.path.join(SCOUT, 'mesh_make.py'), encoding='utf-8').read())
    if not m:
        raise RuntimeError('mesh_make.mesh_trusted: порог min_iou не найден — сверить trial_table')
    return float(m.group(1))


IOU_OK = _battle_min_iou()
RENDER = (500, 500)
PITCH = 12.0
IOU_YAWS_QUICK = (0.0, -20.0, 20.0)   # быстрый режим: три ракурса при наклоне 12°; `--iou-grid full` — 3×3 как в боевом
GPU_CLASS = {'RTX 4090 Laptop': 'RTX 4090 Laptop (16 GB)', 'RTX A5000': 'RTX A5000 (24 GB)', 'RTX 4090': 'RTX 4090 (24 GB)', 'RTX 3090 Ti': 'RTX 3090 Ti (24 GB)', 'RTX 3090': 'RTX 3090 (24 GB)',
             'RTX 4060 Ti': 'RTX 4060 Ti (16 GB)', 'RTX 4070 Ti': 'RTX 4070 Ti (12 GB)'}

COLS = ['model', 'sku', 'role', 'status', 'reason', 't_s', 'usd', 'tris', 'mb_raw', 'mb_lite', 'iou_front', 'iou_open', 'iou_turn',
        'de00', 'dL', 'pattern_grad_ncc', 'grey_top', 'view_empty', 'colour_guard', 'accepted', 'why_not', 'final', 'input_sha8']


# ---------------------------------------------------------------- чистые функции (без trimesh) ----------------
def de2000(lab1, lab2) -> float:
    """CIEDE2000 между двумя цветами Lab (Sharma, Wu, Dalal 2005; kL=kC=kH=1)."""
    L1, a1, b1 = (float(x) for x in lab1)
    L2, a2, b2 = (float(x) for x in lab2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0.0
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        dhp += -360 if dhp > 180 else (360 if dhp < -180 else 0)
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dth = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dth)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def iou_masks(a, b) -> float:
    """IoU двух булевых масок одного размера (numpy)."""
    union = float((a | b).sum())
    return float((a & b).sum()) / union if union else 0.0


def key_of(sku: str) -> str:
    return sku.replace(':', '_')


def locate(model_dir: str, key: str, suffix: str | None = None) -> dict | None:
    """Файлы товара в папке модели → {'raw','clean','dir','complete'} или None. Раскладки — в шапке файла. `suffix` — точное имя после ключа
    (`-1024-42-0`, `-paint-noremesh-42`): в общей папке несколько моделей/вариантов, шаблон `<ключ>-*` взял бы чужой файл."""
    if suffix:
        raw = os.path.join(model_dir, key + suffix + '.glb')
        if not os.path.exists(raw):
            return None
        clean = raw[:-4] + '.clean.glb'
        return {'raw': raw, 'clean': clean if os.path.exists(clean) else None, 'dir': model_dir, 'complete': None}
    flat_raw = sorted(p for p in glob.glob(os.path.join(model_dir, key + '-*.glb'))
                      if not p.endswith(('.clean.glb', '.audit.glb')))
    if flat_raw:
        raw = flat_raw[-1]
        clean = raw[:-4] + '.clean.glb'
        return {'raw': raw, 'clean': clean if os.path.exists(clean) else None, 'dir': model_dir, 'complete': None}
    d = os.path.join(model_dir, key)
    if not os.path.isdir(d):
        return None
    runs = sorted(glob.glob(os.path.join(d, '*', 'model.glb')), key=lambda p: os.path.getmtime(os.path.dirname(p) + '/complete.json')
                  if os.path.exists(os.path.dirname(p) + '/complete.json') else os.path.getmtime(p))
    if runs:
        base = os.path.dirname(runs[-1])
    elif os.path.exists(os.path.join(d, 'model.glb')):
        base = d
    else:
        return None
    clean = os.path.join(base, 'model.clean.glb')
    cj = os.path.join(base, 'complete.json')
    return {'raw': os.path.join(base, 'model.glb'), 'clean': clean if os.path.exists(clean) else None, 'dir': base,
            'complete': cj if os.path.exists(cj) else None}


def price_usd_h(gpu_name: str | None, tier: str, groups: dict | None = None) -> float | None:
    """Цена карты по классу из `rules/salad-groups.json`; нет класса/цены — None (деньги без цены не считаем)."""
    if not gpu_name:
        return None
    groups = groups if groups is not None else json.load(open(RULES_GROUPS, encoding='utf-8'))
    name = gpu_name.replace('NVIDIA GeForce ', '').replace('NVIDIA ', '')
    for short, cls in GPU_CLASS.items():
        if name.startswith(short):
            try:
                return float(groups['prices_by_class_usd_h'][cls][tier])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def load_summaries(model_dir: str, sum_model: str | None = None, variant: str | None = None) -> dict:
    """Сводки драйвера `summary-*.json` в папке → {'jobs': {job_id: последнее задание}, 'spend': сумма cost_usd_est, 'groups': N}.
    `sum_model` — только сводки этой модели (поле `model`: в общей папке лежат сводки и TRELLIS.2, и Hunyuan, и других); `variant` — `''` только задания без
    варианта, иначе только с таким `variant` (гибриды «форма + покраска»). Последнее по времени задание на номер побеждает: упавшее, потом сделанное — «готов»."""
    jobs: dict[str, dict] = {}
    spend, groups = 0.0, 0
    by_group: dict[str, float] = {}
    for p in sorted(glob.glob(os.path.join(model_dir, 'summary-*.json')), key=os.path.getmtime):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if sum_model and d.get('model') != sum_model:
            continue
        if variant is not None and d.get('jobs') and not any((j.get('variant') or '') == variant for j in d['jobs']):
            continue                                            # группа гибридов/контроля чужого варианта: её траты не наши (группы без заданий — считаем, траты холодных стартов)
        groups += 1
        spend += float(d.get('cost_usd_est') or 0.0)
        by_group[str(d.get('group'))] = float(d.get('cost_usd_est') or 0.0)
        for j in d.get('jobs') or []:
            if variant is not None and (j.get('variant') or '') != variant:
                continue
            j = dict(j)
            j['price_usd_h'] = d.get('price_usd_h')
            j['gpu'] = ((d.get('info') or {}).get('gpu') or {}).get('name')
            j['_group'] = d.get('group')
            jk = j.get('job_id') or j.get('sku')
            prev = jobs.get(jk)                                  # повтор того же задания (тот же номер, другой прогон): GLB предыдущих «готов» — тоже наши
            alts = list((prev or {}).get('_alt_glbs') or [])
            if prev and prev.get('status') == 'done' and ((prev.get('metrics') or {}).get('glb')):
                alts.append(prev['metrics']['glb'])
            j['_alt_glbs'] = alts
            jobs[jk] = j
    return {'jobs': jobs, 'spend': round(spend, 4), 'groups': groups, 'by_group': by_group}


def owned(path: str, job: dict | None, kind: str = 'raw', tol_mb: float = 0.06) -> bool | None:
    """ПРИНАДЛЕЖНОСТЬ файла модели по журналу её драйвера (общая папка вывода: драйверы разных моделей пишут `<ключ>-1024-42-0.glb` в одно место и
    перезаписывают друг друга — найдено 19.11). Сырой GLB — размер совпадает с `metrics.glb.size_mb` задания (±tol_mb); `.clean.glb` — число треугольников
    исходника в `*.metrics.json` рядом (±1 %) совпадает с `metrics.glb.triangles` задания. None — в журнале нет размера/треугольников, судить нечем (файл берём)."""
    gs = [((job or {}).get('metrics') or {}).get('glb') or {}] + list((job or {}).get('_alt_glbs') or [])   # последний прогон и прежние того же номера (комод гонялся 3 раза)
    if kind == 'raw':
        if all(g.get('size_mb') is None for g in gs):
            return None
        return any(g.get('size_mb') is not None and abs(os.path.getsize(path) / 1048576 - float(g['size_mb'])) <= tol_mb for g in gs)  # `size_mb` — МиБ
    mp = path[:-len('.clean.glb')] + '.metrics.json'
    if all(g.get('triangles') is None for g in gs) or not os.path.exists(mp):
        return None
    try:
        t = float(json.load(open(mp, encoding='utf-8')).get('tris_total'))
    except (OSError, ValueError, TypeError):
        return None
    return any(g.get('triangles') is not None and abs(t - float(g['triangles'])) <= max(2.0, 0.01 * float(g['triangles'])) for g in gs)


def split_spend(by_group: dict, kpi: str | None, pilot: str | None) -> tuple[float, float | None]:
    """Траты модели: (для KPI, пилоты «встать»). `kpi` — регулярка по имени группы Salad (рабочие прогоны: `trellis2-r30` берёт r30, r30t, r30d), `pilot` — по пилотам
    (проверка, что модель встаёт и сколько стоит: s0b…s0f). Группы вне обеих — в KPI не входят и в пилоты тоже (их видно в сводках драйвера). Без `kpi` — все группы."""
    if not kpi:
        return round(sum(by_group.values()), 4), None
    k = sum(c for g, c in by_group.items() if re.search(kpi, g))
    pl = sum(c for g, c in by_group.items() if pilot and re.search(pilot, g)) if pilot else None
    return round(k, 4), (None if pl is None else round(pl, 4))


def accept(grey: str | None, view_empty: bool | None, colour: str | None, iou: float | None = None, iou_open: float | None = None,
           min_iou: float | None = None) -> tuple[bool, list[str]]:
    """Автоприёмка: «принят», только если ВСЕ условия чисты. Серый верх: ok/na чисто. Пустой вид: None (не судим) — чисто.
    Цвет: только ok (unknown — нет замера — не принимаем). Силуэт спереди — БОЕВОЙ порог `mesh_trusted` (`IOU_OK`): ниже — не принят; если без тонких частей
    (открытие масок) порог берётся — причина «силуэт: тонкие части» (ножки/спицы, а не чужая форма), всё равно не принят: решение о таких — за ведущим."""
    min_iou = IOU_OK if min_iou is None else min_iou
    why = []
    if iou is None:
        why.append('силуэт: нет замера')
    elif iou < min_iou:
        why.append('силуэт: тонкие части' if (iou_open or 0) >= min_iou else f'силуэт: IoU {iou:.2f} < {min_iou:g}')
    if grey not in ('ok', 'na'):
        why.append(f'серый верх: {grey}')
    if view_empty:
        why.append('пустой вид (зад/верх)')
    if colour != 'ok':
        why.append(f'цвет: {colour}')
    return (not why), why


def model_summary(rows: list[dict], spend_usd: float | None, setup_usd: float | None = None) -> dict:
    """Итог по модели. Доля принятых — от товаров, где модель ПРОБОВАЛИ (есть файл или запись об отказе); «нет» — не пробовали, в знаменатель не входит.
    $ за одну принятую = все траты / число принятых (нет принятых или нет трат — None)."""
    tried = [r for r in rows if r['status'] in ('готов', 'отказ')]
    acc = [r for r in tried if r.get('accepted') == 'да']
    out = {'products': len(rows), 'tried': len(tried), 'ready': sum(r['status'] == 'готов' for r in tried),
           'refused': sum(r['status'] == 'отказ' for r in tried), 'not_run': sum(r['status'] == 'нет' for r in rows),
           'accepted': len(acc), 'accepted_share': round(len(acc) / len(tried), 3) if tried else None,
           'thin_notes': sum('силуэт: тонкие части' in (r.get('why_not') or '') for r in tried), 'spend_usd': spend_usd, 'setup_usd': setup_usd, 'usd_per_accepted': None}
    if acc and spend_usd:
        out['usd_per_accepted'] = round(spend_usd / len(acc), 4)
    return out


# ---------------------------------------------------------------- измерение одной пары (тяжёлое; в процессе-работнике) ----------
def _sha8(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:8]


def _bbox_crop(rgba, thr: int):
    import numpy as np
    a = np.asarray(rgba)[..., 3] > thr
    if not a.any():
        return None
    ys, xs = np.where(a)
    return rgba.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def _mask256(rgba):
    """Обрезка по рамке силуэта → 256×256 → булева маска (как `mesh_trusted`)."""
    import numpy as np
    from PIL import Image
    c = _bbox_crop(rgba, IOU_ALPHA)
    if c is None:
        return np.zeros(IOU_SIZE[::-1], bool)
    return np.asarray(c.resize(IOU_SIZE, Image.LANCZOS))[..., 3] > IOU_ALPHA


def _opened(m):
    """Открытие маски (эрозия + наращивание, как `view_guard._morph`): тонкие части короче 2·THIN_R px пропадают."""
    from salad import view_guard as VG
    return VG._morph(VG._morph(m, THIN_R, grow=False), THIN_R, grow=True)


def measure_pair(task: dict) -> dict:
    """Все числа для одной пары товар × модель. Исключения — в `error` (счётчик отказов обязателен, молчать нельзя)."""
    import numpy as np
    from PIL import Image
    os.environ['UNLIT'] = '1'                                   # рендер без света: чистый baseColor (замер цвета)
    sys.path.insert(0, SCOUT)
    sys.path.insert(0, os.path.join(REPO, 'tools', 'assets'))
    import mesh_color_check as MC
    import mesh_grey_top as GT
    import mesh_render as MR
    from salad import view_guard as VG

    final, raw, cut = task['final'], task['raw'], task['cutout']
    out: dict = {'tris': None, 'mb_lite': None, 'iou_front': None, 'iou_open': None, 'iou_turn': None, 'de00': None, 'dL': None,
                 'pattern_grad_ncc': None, 'grey_top': None, 'view_empty': None, 'colour_guard': None, 'errors': []}

    def guard(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — сторож упал: не «чисто», а ошибка с именем
            out['errors'].append(f'{name}: {type(e).__name__}: {str(e)[:80]}')
            return None

    # --- части для рендера (лёгкие, если граница даёт ужать — сам итоговый GLB меряется отдельно, `count_tris`)
    parts = guard('загрузка', lambda: MR.lite_parts(final, 40000))
    cut_im = Image.open(cut).convert('RGBA') if cut and os.path.exists(cut) else None

    # --- рендеры: IoU (силуэт), цвет без света, пустой зад/верх
    cur = {'parts': parts}

    def shot(yaw, pitch):
        # упрощатель мог сломать индексы UV (пример: `IndexError: index 53766 … size 53765` на Hunyuan-GLB) — один раз пробуем полные части
        try:
            return MR.render(cur['parts'], yaw, pitch, size=RENDER)
        except IndexError:
            if cur['parts'] is not parts:
                raise
            cur['parts'] = MR.load_parts(final)
            out.setdefault('notes', []).append('упрощение частей ломало UV — рендер по полным частям')
            return MR.render(cur['parts'], yaw, pitch, size=RENDER)

    def render_block():
        cm = _mask256(cut_im)
        yaws = IOU_YAWS_QUICK if task['iou_grid'] == 'quick' else (0.0, -20.0, 20.0)
        pitches = (PITCH,) if task['iou_grid'] == 'quick' else (0.0, 12.0, 22.0)
        best, front_img, best_mask = 0.0, None, None
        for yw in yaws:
            for pt in pitches:
                im = shot(yw, pt)
                if yw == 0.0 and pt == PITCH:
                    front_img = im
                mk = _mask256(im)
                v = iou_masks(mk, cm)
                if best_mask is None or v > best:
                    best, best_mask = v, mk
        out['iou_front'] = round(best, 3)
        out['iou_open'] = round(iou_masks(_opened(best_mask), _opened(cm)), 3)      # без тонких частей: ножки, спицы, плафонные стойки
        if best < IOU_OK:                                       # не лицом? — подсказка «модель повёрнута», а не «плохая форма»
            out['iou_turn'] = round(max(iou_masks(_mask256(shot(yw, PITCH)), cm) for yw in (90.0, 180.0, 270.0)), 3)
        if front_img is not None:
            sa = np.asarray(front_img)
            px = sa[..., :3][sa[..., 3] > 128].astype(np.float64)
            pc = MC.photo_colour(cut)
            if len(px) > 50 and pc:
                mc = MC.summary(px)
                out['de00'] = round(de2000(mc['lab'], pc['lab']), 2)
                out['dL'] = round(float(mc['lab'][0]) - float(pc['lab'][0]), 1)
            if task.get('pattern_fn'):                          # своя функция вместо встроенной: f(рендер_RGBA, вырезка_RGBA) → число
                fn = _resolve(task['pattern_fn'])
                out['pattern_grad_ncc'] = guard('pattern_grad_ncc', lambda: fn(front_img, cut_im))
            elif task.get('pattern'):
                out['pattern_grad_ncc'] = guard('pattern_grad_ncc', lambda: pattern_value(front_img, cut_im))

    if parts is not None and cut_im is not None:
        guard('рендер (IoU/цвет)', render_block)

    # --- сторож 1: серый верх (боевая функция, не прогон модуля)
    g = guard('mesh_grey_top', lambda: GT.analyze(final))
    out['grey_top'] = (g or {}).get('verdict') if g is not None else 'ошибка'

    # --- сторож 2: пустой вид по рендеру итогового GLB (зад и верх; идея view_guard)
    def view_block():
        flags = []
        for yw, pt in ((180.0, PITCH), (0.0, 55.0)):
            im = shot(yw, pt)
            a = np.asarray(im)
            sil = a[..., 3] > 128
            inside = VG._morph(sil, VG.ERODE_PX, grow=False)
            if inside.sum() < VG.MIN_INSIDE_FRAC * sil.size:
                continue                                        # силуэт мал — не судим (как view_guard)
            rgb = a[..., :3].astype(np.int16)
            near = np.all(np.abs(rgb[inside] - np.array(VG.EMPTY_GREY)) <= VG.TOL, axis=-1)
            flags.append(float(near.mean()) >= VG.EMPTY_FRAC)
        out['view_empty'] = any(flags) if flags else None

    if parts is not None:
        guard('рендер (пустой вид)', view_block)

    # --- сторож 3: цвет модели против цвета вырезки (боевые функции и пороги)
    if cut:
        def colour():
            R = MC.rules()
            sc, pc = MC.surface_colour(final), MC.photo_colour(cut)
            return MC.verdict(MC.diff(sc, pc), R)
        out['colour_guard'] = guard('mesh_color_check', colour) or ('ошибка' if out['errors'] else 'unknown')

    # --- вес: сырой и лёгкая копия обычной веб-конвертацией
    if task.get('lite_dir'):
        out['mb_lite'] = guard('лёгкая копия', lambda: lite_copy(final, task['lite_dir'], key_of(task['sku'])))
    return out


def pattern_value(render_rgba, cut_rgba) -> float | None:
    """`pattern_metric.pattern_grad_ncc` (рабочий 4, T-20261119-04) по переднему кадру: рендер без света и вырезка режутся по рамке силуэта и
    приводятся к 256² (как для IoU), мерим там, где оба непрозрачны; в таблицу — медиана (больше — похожее). СПРАВОЧНАЯ колонка, в автоприёмку
    не входит: на комоде метрика не различила TRELLIS (0,034) и Hunyuan (0,044), совмещение к фото не сходится (cc < 0,5)."""
    import numpy as np
    from PIL import Image
    sys.path.insert(0, SCOUT)
    import pattern_metric as PM
    a, b = _bbox_crop(render_rgba, 128), _bbox_crop(cut_rgba, 128)
    if a is None or b is None:
        return None
    a, b = (np.asarray(x.resize(IOU_SIZE, Image.LANCZOS)) for x in (a, b))
    mask = (a[..., 3] > 128) & (b[..., 3] > 128)
    r = PM.pattern_grad_ncc(a[..., :3].copy(), b[..., :3].copy(), mask)
    m = r.get('median')
    return None if m is None else round(float(m), 3)


def count_tris(glb: str) -> int | None:
    """Треугольники ИТОГОВОГО GLB (не упрощённых частей рендера): сумма по всем геометриям сцены."""
    import trimesh
    sc = trimesh.load(glb, force='scene')
    return int(sum(len(g.faces) for g in sc.geometry.values())) if hasattr(sc, 'geometry') else None


def _resolve(spec: str):
    import importlib
    mod, fn = spec.split(':')
    return getattr(importlib.import_module(mod), fn)


def lite_copy(final_glb: str, out_dir: str, key: str) -> float | None:
    """Лёгкая копия — ровно нашей веб-конвертацией: `runtime_mesh.optimise` (текстура 1024, q82, без MR) → `build_copy` (gltfpack, KTX2). МБ или None."""
    sys.path.insert(0, os.path.join(REPO, 'tools', 'assets'))
    import runtime_mesh as RM
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, key + '.glb')
    data = open(final_glb, 'rb').read()
    out, stats = RM.optimise(data, 1024, 82)
    tmp = dst[:-4] + '.src.glb'
    with open(tmp, 'wb') as f:
        f.write(out)
    try:
        packed, how, probs = RM.build_copy(tmp, dst, 0.0, True, stats['images_out'] > 0)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if probs:
        raise RuntimeError('; '.join(probs)[:100])
    return round(os.path.getsize(dst) / 1e6, 2)


# ---------------------------------------------------------------- сборка таблицы ----------------------------------
def build_row(model: str, c: dict, spec: dict, meta: dict, cache_dir: str, a) -> dict:
    sku = c['sku']
    key = key_of(sku)
    row = {k: None for k in COLS}
    row.update(model=model, sku=sku, role=c.get('role'), accepted='нет', why_not='')
    suffix = spec.get('suffix')
    found = locate(spec['dir'], key, suffix)
    job = (meta['jobs'].get(key + suffix) if suffix else None) or meta['jobs'].get(key + '-1024-42-0') or meta['jobs'].get(sku) or {}
    if found and spec.get('sum_model') and job.get('status') != 'done':
        found = None                                                 # у этой модели задания «готов» нет: файл в общей папке — чужой
    if found and spec.get('sum_model') and job.get('status') == 'done':
        raw_own = owned(found['raw'], job, 'raw') is not False
        clean_own = bool(found['clean']) and owned(found['clean'], job, 'clean') is not False
        if not clean_own:
            found['clean'] = None                                    # очистка сделана из чужого GLB — не берём
        if not raw_own:                                              # сырой — другой модели (перезапись в общей папке)
            if not found['clean']:
                row.update(status='нет', reason='GLB перезаписан другой моделью (общая папка вывода) — исходный потерян', accepted='—')
                return row
            found['raw'] = None                                      # сырого нет, но своя очистка уцелела — судим её (итоговый GLB)
    if not found:
        if job.get('status') == 'failed':
            row.update(status='отказ', reason=(job.get('error') or 'failed')[:120], t_s=(job.get('metrics') or {}).get('total_s'))
        else:
            row.update(status='нет', reason='не запускали' if not job else job.get('status'))
        row['accepted'] = '—'
        return row
    final = found['clean'] or found['raw']
    row.update(status='готов', reason='' if found['raw'] else 'сырой GLB перезаписан чужой моделью, итоговый — своя очистка', final='clean' if found['clean'] else 'raw',
               mb_raw=round(os.path.getsize(found['raw']) / 1e6, 2) if found['raw'] else None)
    # время и деньги из журналов драйвера
    m = job.get('metrics') or {}
    if m.get('total_s') is not None:
        row['t_s'] = round(float(m['total_s']), 1)
        price = job.get('price_usd_h')
        if price:
            row['usd'] = round(float(m['total_s']) / 3600 * float(price), 4)
    elif found['complete']:
        cj = json.load(open(found['complete'], encoding='utf-8'))
        row['t_s'] = round(float((cj.get('timings_s') or {}).get('total') or 0), 1) or None
        price = price_usd_h((cj.get('gpu') or {}).get('name'), a.hy_tier)
        if row['t_s'] and price:
            row['usd'] = round(row['t_s'] / 3600 * price, 4)
    cut = os.path.join(a.inputs, key + '.rgba.png')
    row['input_sha8'] = _sha8(cut) if os.path.exists(cut) else None
    ck = hashlib.sha1(json.dumps([VERSION, final, os.path.getmtime(final), os.path.getsize(final), row['input_sha8'], a.iou_grid,
                                  a.pattern_fn, bool(a.no_lite), not a.no_pattern]).encode()).hexdigest()[:16]
    cp = os.path.join(cache_dir, f'{model}-{key}-{ck}.json')
    if os.path.exists(cp):
        meas = json.load(open(cp, encoding='utf-8'))
    else:
        meas = measure_pair({'final': final, 'raw': found['raw'] or final, 'cutout': cut if os.path.exists(cut) else None, 'sku': sku,
                             'iou_grid': a.iou_grid, 'pattern_fn': a.pattern_fn, 'pattern': not a.no_pattern,
                             'lite_dir': None if a.no_lite else os.path.join(a.out, 'lite', model)})
        json.dump(meas, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    try:
        row['tris'] = count_tris(final)
    except Exception as e:  # noqa: BLE001
        meas.setdefault('errors', []).append(f'треугольники: {str(e)[:60]}')
    for k in ('mb_lite', 'iou_front', 'iou_open', 'iou_turn', 'de00', 'dL', 'pattern_grad_ncc', 'grey_top', 'view_empty', 'colour_guard'):
        row[k] = meas.get(k)
    ok, why = accept(row['grey_top'], row['view_empty'], row['colour_guard'], row['iou_front'], row['iou_open'])
    if meas.get('errors'):
        ok, why = False, why + ['сторож упал: ' + '; '.join(meas['errors'])[:100]]
    row['accepted'] = 'да' if ok else 'нет'
    row['why_not'] = '; '.join(why)
    return row


def _w(worker_args):
    return build_row(*worker_args)


def fmt(v, nd=None):
    if v is None or v == '':
        return '—'
    if isinstance(v, bool):
        return 'да' if v else 'нет'
    return f'{v:.{nd}f}' if nd is not None and isinstance(v, float) else str(v)


def write_outputs(out_dir: str, rows: list[dict], sums: dict, notes: dict, set_name: str) -> tuple[str, str, str]:
    os.makedirs(out_dir, exist_ok=True)
    p_csv, p_sum, p_md = (os.path.join(out_dir, n) for n in ('trial-table.csv', 'trial-models.csv', 'trial-table.md'))
    with open(p_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in COLS})
    scols = ['model', 'products', 'tried', 'ready', 'refused', 'not_run', 'accepted', 'accepted_share', 'thin_notes', 'spend_usd', 'setup_usd', 'usd_per_accepted',
             'spend_note']
    with open(p_sum, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=scols)
        w.writeheader()
        for m, s in sums.items():
            w.writerow({'model': m, **{k: ('' if s.get(k) is None else s[k]) for k in scols[1:-1]}, 'spend_note': notes.get(m, '')})
    L = [f'# Проба генераторов мешей — таблица (набор `{set_name}`, расчёт `{VERSION}`)', '',
         '**Принят** = все три боевых сторожа чисты по итоговому GLB (серый верх · пустой вид зад/верх · цвет против вырезки). '
         '**$ за одну принятую** = все траты на модель / число принятых. Четвёртое условие — IoU силуэта спереди не ниже боевого порога `mesh_make.mesh_trusted` '
         f'({IOU_OK:g}, берётся из боевого кода); «тонкие части» — IoU без ножек и спиц достигает порога, не принят, пометка для решения ведущего.', '',
         '## Итог по моделям', '',
         '| модель | пробовали | готово | отказ | принято | доля принятых | траты (KPI), $ | пилоты «встать», $ | **$ за одну принятую** | из не принятых — «тонкие части» | чем считали траты |',
         '|---|---|---|---|---|---|---|---|---|---|---|']
    for m, s in sums.items():
        share = fmt(None if s['accepted_share'] is None else round(s['accepted_share'] * 100, 1))
        L.append(f"| {m} | {s['tried']} (не пробовали: {s['not_run']}) | {s['ready']} | {s['refused']} | {s['accepted']} | "
                 f"{share}{'' if share == '—' else ' %'} | {fmt(s['spend_usd'])} | {fmt(s['setup_usd'])} | **{fmt(s['usd_per_accepted'])}** | "
                 f"{s['thin_notes']} | {notes.get(m, '')} |")
    for m in sums:
        L += ['', f'## {m}', '',
              '| товар | роль | статус | с | $ | треуг. | МБ сырой | МБ лёгкая | IoU | ΔE00 | ΔL | pattern | серый верх | пуст. вид | цвет | принят | почему нет |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for r in (x for x in rows if x['model'] == m):
            st = r['status'] if not r['reason'] else (f"отказ: {r['reason']}" if r['status'] == 'отказ' else f"{r['status']} ({r['reason']})")
            iou = fmt(r['iou_front']) + ('' if r['iou_open'] is None else f" (без тонких {r['iou_open']})") + ('' if r['iou_turn'] is None else f" (повёрн. {r['iou_turn']})")
            L.append(f"| `{r['sku']}` | {r['role'] or ''} | {st} | {fmt(r['t_s'])} | {fmt(r['usd'])} | {fmt(r['tris'])} | {fmt(r['mb_raw'])} | "
                     f"{fmt(r['mb_lite'])} | {iou} | {fmt(r['de00'])} | {fmt(r['dL'])} | {fmt(r['pattern_grad_ncc'])} | {fmt(r['grey_top'])} | "
                     f"{fmt(r['view_empty'])} | {fmt(r['colour_guard'])} | {r['accepted']} | {r['why_not'] or ''} |")
    open(p_md, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return p_csv, p_sum, p_md


def main() -> int:
    ap = argparse.ArgumentParser(description='Таблица пробы генераторов мешей (товар × модель)')
    ap.add_argument('--set', default=os.path.join(ROOT, 'trellis', 'set30.json'))
    ap.add_argument('--inputs', default=os.path.join(ROOT, 'trellis', 'inputs30'), help='папка вырезок `<ключ>.rgba.png` (общая для всех моделей)')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--model', action='append', default=[], help='имя[=папка]; повторяется')
    ap.add_argument('--out', default=os.path.join(ROOT, 'table'))
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--no-lite', action='store_true', help='не собирать лёгкие копии (быстро; без МБ лёгкой)')
    ap.add_argument('--iou-grid', choices=('quick', 'full'), default='quick')
    ap.add_argument('--pattern-fn', default='', help='своя метрика узора вместо встроенной `pattern_metric.pattern_grad_ncc`: модуль:функция, f(рендер_RGBA, вырезка_RGBA) → число')
    ap.add_argument('--no-pattern', action='store_true', help='не считать pattern_grad_ncc (справочная колонка)')
    ap.add_argument('--hy-tier', default='high', help='тариф Salad для оценки $ боевого Hunyuan (по complete.json); группы боевых прогонов были разные')
    ap.add_argument('--spend', action='append', default=[], help='модель=USD — траты, если сводок драйвера нет/неполны (идущий прогон)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.model:
        ap.error('нужен хотя бы один --model')
    specs = {}
    for m in a.model:
        name, _, path = m.partition('=')
        path, _, q = path.partition('?')                         # name=папка?suffix=-1024-42-0&sum=hunyuan21&variant=noremesh
        opts = dict(kv.split('=', 1) for kv in q.split('&') if '=' in kv)
        specs[name] = {'dir': os.path.expanduser(path or os.path.join(a.root, name)), 'suffix': opts.get('suffix'),
                       'sum_model': opts.get('sum'), 'variant': opts.get('variant'), 'kpi': opts.get('kpi'), 'pilot': opts.get('pilot')}
    override = {k: float(v) for k, v in (s.split('=') for s in a.spend)}
    items = json.load(open(a.set, encoding='utf-8'))
    set_name = os.path.basename(a.set)
    cache_dir = os.path.join(a.out, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    rows, sums, notes = [], {}, {}
    for name, spec in specs.items():
        setup = None
        meta = load_summaries(spec['dir'], spec.get('sum_model'), spec.get('variant'))
        tasks = [(name, c, spec, meta, cache_dir, a) for c in items]
        if a.workers > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=a.workers) as ex:
                mrows = list(ex.map(_w, tasks))
        else:
            mrows = [_w(t) for t in tasks]
        rows += mrows
        if name in override:
            spend, notes[name] = override[name], 'задано вручную (--spend)'
        elif meta['groups'] and spec.get('kpi'):
            spend, setup = split_spend(meta['by_group'], spec['kpi'], spec.get('pilot'))
            notes[name] = f"группы /{spec['kpi']}/ (с холодными стартами); пилоты «встать» — отдельно, в KPI не входят"
        elif meta['groups']:
            spend, notes[name] = meta['spend'], f"{meta['groups']} сводок драйвера (все группы, с холодными стартами)"
        else:
            est = [r['usd'] for r in mrows if r['usd'] is not None]
            spend = round(sum(est), 4) if est else None
            notes[name] = 'оценка: время генерации × тариф, без холодных стартов' if est else 'трат нет в журналах'
        sums[name] = model_summary(mrows, spend, setup)
        print(f'{name}: пробовали {sums[name]["tried"]}, принято {sums[name]["accepted"]}, $/принятую {sums[name]["usd_per_accepted"]}', flush=True)
    paths = write_outputs(a.out, rows, sums, notes, set_name)
    print('\n'.join(paths))
    return 0


# ---------------------------------------------------------------- самопроверка ----------------------------------
def selftest() -> int:
    sys.path.insert(0, SCOUT)
    import remlab_tmp                                           # временные файлы теста — под гигиену `test_tmp_hygiene`
    remlab_tmp.use('trial_table')
    import tempfile
    bad = 0

    def check(name, cond):
        nonlocal bad
        print(('ok   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    # ΔE00 по эталонным парам Sharma et al. 2005
    check('ΔE00 Sharma #1 = 2.0425', abs(de2000((50, 2.6772, -79.7751), (50, 0, -82.7485)) - 2.0425) < 1e-3)
    check('ΔE00 Sharma #7 = 4.3065', abs(de2000((50, 2.5, 0), (50, 0, -2.5)) - 4.3065) < 1e-3)
    check('ΔE00 одинаковых = 0', de2000((60, 10, -10), (60, 10, -10)) == 0)
    try:
        import numpy as np
        a = np.zeros((10, 10), bool)
        a[2:8, 2:8] = True
        b = a.copy()
        check('IoU одинаковых = 1', iou_masks(a, b) == 1.0)
        b[2:8, 5:] = False
        check('IoU половины = 0,5', abs(iou_masks(a, b) - 0.5) < 1e-9)
    except ImportError:
        print('skip IoU (нет numpy)')
    # раскладки
    with tempfile.TemporaryDirectory() as t:
        flat, tree = os.path.join(t, 'flat'), os.path.join(t, 'tree')
        os.makedirs(flat)
        os.makedirs(os.path.join(tree, '1_2', 'run1'))
        os.makedirs(os.path.join(tree, '3_4', 'run1'))
        os.makedirs(os.path.join(tree, '3_4', 'run2'))
        for n in ('1_2-1024-42-0.glb', '1_2-1024-42-0.clean.glb', '1_2-1024-42-0.audit.glb', '5_6-1024-42-0.glb'):
            open(os.path.join(flat, n), 'wb').write(b'x')
        for p in ('1_2/run1/model.glb', '3_4/run1/model.glb', '3_4/run2/model.glb', '3_4/run2/model.clean.glb'):
            open(os.path.join(tree, p), 'wb').write(b'x')
        os.utime(os.path.join(tree, '3_4', 'run1', 'model.glb'), (1, 1))
        f1, f2, f3, f4 = locate(flat, '1_2'), locate(flat, '5_6'), locate(tree, '3_4'), locate(tree, '9_9')
        check('плоская: сырой/clean найдены, audit не берётся', bool(f1 and f1['raw'].endswith('1_2-1024-42-0.glb') and f1['clean'].endswith('.clean.glb')))
        check('плоская без clean → clean None', bool(f2 and f2['clean'] is None))
        check('по папкам: берётся новейший прогон и его clean', bool(f3 and '/run2/' in f3['raw'] and f3['clean']))
        check('нет товара → None', f4 is None and locate(flat, '7_7') is None)
        # сводки драйвера: последнее задание побеждает, траты — сумма по группам
        json.dump({'group': 'g1', 'cost_usd_est': 0.1, 'price_usd_h': 0.33,
                   'jobs': [{'sku': 'a:1', 'status': 'failed', 'error': 'boom'}]}, open(os.path.join(flat, 'summary-g1.json'), 'w'))
        os.utime(os.path.join(flat, 'summary-g1.json'), (10, 10))
        json.dump({'group': 'g2', 'cost_usd_est': 0.25, 'price_usd_h': 0.33, 'info': {'gpu': {'name': 'NVIDIA GeForce RTX 4090'}},
                   'jobs': [{'sku': 'a:1', 'status': 'done', 'metrics': {'total_s': 136.4}}]}, open(os.path.join(flat, 'summary-g2.json'), 'w'))
        s = load_summaries(flat)
        check('сводки: траты 0,35, 2 группы', abs(s['spend'] - 0.35) < 1e-9 and s['groups'] == 2)
        check('сводки: упавшее, затем сделанное → done', s['jobs']['a:1']['status'] == 'done' and s['jobs']['a:1']['price_usd_h'] == 0.33)
    bg = {'trial-trellis2-s0b': 0.226, 'trial-trellis2-s0f': 0.056, 'trial-trellis2-r30': 0.996, 'trial-trellis2-r30t': 0.1, 'trial-trellis2-r30d': 0.4}
    check('траты: KPI = r30+r30t+r30d, пилоты отдельно', split_spend(bg, 'trellis2-r30', '-s0') == (1.496, 0.282))
    check('траты: без kpi — все группы, пилотов нет', split_spend(bg, None, None) == (round(sum(bg.values()), 4), None))
    # общая папка: точное имя, принадлежность файла по журналу, фильтр сводок по модели
    with tempfile.TemporaryDirectory() as t:
        for n, size in (('7_8-1024-42-0.glb', 5_000_000), ('7_8-paint-x-42.glb', 1000)):
            open(os.path.join(t, n), 'wb').write(b'x' * size)
        check('suffix: берётся именно свой файл', locate(t, '7_8', '-paint-x-42')['raw'].endswith('paint-x-42.glb') and locate(t, '7_8', '-nope-42') is None)
        raw = os.path.join(t, '7_8-1024-42-0.glb')
        check('owned: размер совпал → свой', owned(raw, {'metrics': {'glb': {'size_mb': 4.77}}}) is True)
        check('owned: размер другой (перезаписан чужой моделью) → не свой', owned(raw, {'metrics': {'glb': {'size_mb': 20.7}}}) is False)
        check('owned: в журнале нет размера → судить нечем (None)', owned(raw, {'metrics': {}}) is None)
        cl = os.path.join(t, '7_8-1024-42-0.clean.glb')
        open(cl, 'wb').write(b'x')
        json.dump({'tris_total': 490132}, open(os.path.join(t, '7_8-1024-42-0.metrics.json'), 'w'))
        check('owned clean: треугольники исходника совпали → свой', owned(cl, {'metrics': {'glb': {'triangles': 490000}}}, 'clean') is True)
        check('owned clean: у чужой модели 40000 → не свой', owned(cl, {'metrics': {'glb': {'triangles': 40000}}}, 'clean') is False)
        for g, m, v in (('a', 'trellis2', None), ('b', 'hunyuan21', None), ('c', 'hunyuan21', 'noremesh')):
            json.dump({'group': g, 'model': m, 'cost_usd_est': 1.0, 'jobs': [{'job_id': 'j-' + g, 'sku': 'x:1', 'status': 'done', **({'variant': v} if v else {})}]},
                      open(os.path.join(t, f'summary-{g}.json'), 'w'))
        sa = load_summaries(t, 'hunyuan21', '')
        check('сводки: только своя модель и без вариантов', sorted(sa['jobs']) == ['j-b'] and sa['spend'] == 1.0 and sa['groups'] == 1)
        check('сводки: вариант отдельно', sorted(load_summaries(t, 'hunyuan21', 'noremesh')['jobs']) == ['j-c'])
    g = {'prices_by_class_usd_h': {'RTX 3090 (24 GB)': {'high': 0.17}, 'RTX 4090 (24 GB)': {'high': 0.33}}}
    check('цена по классу карты', price_usd_h('NVIDIA GeForce RTX 3090', 'high', g) == 0.17 and price_usd_h('RTX 4090', 'high', g) == 0.33)
    check('неизвестная карта → None, не 0', price_usd_h('Tesla T4', 'high', g) is None and price_usd_h(None, 'high', g) is None)
    # автоприёмка: все чисты → принят; любой грязный → нет
    check('порог силуэта — боевой (0,6 из mesh_trusted)', IOU_OK == 0.6)
    check('приёмка: ok/ok/ok/силуэт 0,9 → принят', accept('ok', False, 'ok', 0.9, 0.95) == (True, []))
    check('приёмка: na и вид не судим → принят', accept('na', None, 'ok', 0.7, 0.7)[0])
    check('приёмка: силуэт ровно на пороге → принят', accept('ok', False, 'ok', IOU_OK, IOU_OK)[0])
    check('приёмка: силуэт ниже порога → нет, причина с числом', accept('ok', False, 'ok', 0.4, 0.45)[1] == ['силуэт: IoU 0.40 < 0.6'])
    check('приёмка: ниже порога, но без тонких частей достигает → пометка «тонкие части», не принят', accept('ok', False, 'ok', 0.4, 0.7) == (False, ['силуэт: тонкие части']))
    check('приёмка: нет замера силуэта → нет', accept('ok', False, 'ok') == (False, ['силуэт: нет замера']))
    check('приёмка: серый верх reject → нет', not accept('reject', False, 'ok', 0.9, 0.9)[0])
    check('приёмка: candidate (на ручную) → нет', not accept('candidate', False, 'ok', 0.9, 0.9)[0])
    check('приёмка: пустой вид → нет', not accept('ok', True, 'ok', 0.9, 0.9)[0])
    check('приёмка: цвет mismatch/unknown → нет', not accept('ok', False, 'mismatch', 0.9, 0.9)[0] and not accept('ok', False, 'unknown', 0.9, 0.9)[0])
    check('приёмка: три нарушения — три причины', len(accept('reject', True, 'mismatch', 0.9, 0.9)[1]) == 3)
    # итог по модели: $ за принятую = все траты / принятые; «нет» в знаменатель не входит
    rows = [{'status': 'готов', 'accepted': 'да'}, {'status': 'готов', 'accepted': 'нет'}, {'status': 'отказ', 'accepted': 'нет'},
            {'status': 'нет', 'accepted': '—'}, {'status': 'готов', 'accepted': 'да'}]
    sm = model_summary(rows, 1.0)
    check('итог: пробовали 4 из 5, принято 2, доля 0,5', sm['tried'] == 4 and sm['accepted'] == 2 and sm['accepted_share'] == 0.5 and sm['not_run'] == 1)
    check('итог: $ за принятую = 1,0 / 2 = 0,5', sm['usd_per_accepted'] == 0.5)
    check('цена: 4090 Laptop и A5000 находятся (не 4090)', price_usd_h('NVIDIA GeForce RTX 4090 Laptop GPU', 'high', {'prices_by_class_usd_h': {'RTX 4090 Laptop (16 GB)': {'high': 0.2}, 'RTX 4090 (24 GB)': {'high': 0.33}}}) == 0.2
          and price_usd_h('NVIDIA RTX A5000', 'high', {'prices_by_class_usd_h': {'RTX A5000 (24 GB)': {'high': 0.15}}}) == 0.15)
    check('итог: нет принятых → $ за принятую None', model_summary([{'status': 'готов', 'accepted': 'нет'}], 1.0)['usd_per_accepted'] is None)
    check('итог: нет трат → None, не деление на ноль', model_summary(rows, None)['usd_per_accepted'] is None)
    print('ИТОГ:', 'FAIL ×%d' % bad if bad else 'всё ok')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
