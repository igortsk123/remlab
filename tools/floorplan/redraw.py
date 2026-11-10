#!/usr/bin/env python3
"""Ступень «перерисовка шумного плана» в разборе /try (T-20261110-17; проба T-20261110-13 — `plan-mask-probe`).

За выключателем `FP_REDRAW` (по умолчанию выкл.; `1` — только при тревожном разборе оригинала, `force` — всегда, для оценки).
Зовёт `pipeline.run` ПОСЛЕ разбора оригинала; с выключателем выкл. этот модуль даже не импортируется.

Два листа — явно раздельно (критика Codex 10.11 п.1: кэш VLM не копировать под sha другого листа):
  • ЛИСТ ДЛЯ ПОДПИСЕЙ — оригинал. VLM читает только его (кэш — по его sha), подписи и их координаты — из этого чтения;
  • ПРОВЕРЕННЫЙ ЛИСТ ДЛЯ СТЕН — перерисовка, сведённая в пиксели оригинала найденной подгонкой (ECC: масштаб, поворот,
    сдвиг; потолки ниже). Подписи переносятся «обратным ходом»: чистый лист приводится к сетке оригинала, поэтому точки
    VLM (сетка 0–1000 оригинала) ложатся на него без пересчёта; подгонка — в `redraw.json`.

Ход: маска надписей (точки подписей VLM + строки текста — белым, стены в рамке сохраняются) → кусок листа по контурам
панелей VLM + белые поля под пропорцию модели → модель картинок (шлюз Vercel, `ENGINE`; свой потолок денег `CAP_USD`,
отдельно от VLM `pipeline.CAP_USD`; кэш ответа по sha отправленного) → обратно в пиксели оригинала + подгонка → честность
стен (`faithfulness`) → разбор чистого (в `pipeline`) → `decide`: двери, окна и связность комнат против разбора оригинала.

Выбор итога (`decide`) — только по проверяемым признакам: потеряна дверь/окно, сменилась связность (граф смежности комнат
через проходы), появилось окно/дверь между названными комнатами — итог = разбор оригинала (`redraw_rejected:<причина>`);
«чистый лучше» — меньше безымянных/слитых, больше подписей нашли комнату, ничего не хуже. Площадь из объявления — НЕ критерий.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCOUT = HERE.parent / 'scout'

ENGINE = 'google/gemini-3.1-flash-image'
PRICE_USD = {'google/gemini-3.1-flash-image': 0.10}  # $ за картинку (проба T-13: $0,1019 по балансу шлюза)
CAP_USD = 0.12                     # потолок перерисовки на задание (отдельно от VLM): одна картинка, повторов нет
IMAGE_SIZE = '2K'
GW_CHAT = 'https://ai-gateway.vercel.sh/v1/chat/completions'
GW_CREDITS = 'https://ai-gateway.vercel.sh/v1/credits'
GW_TIMEOUT = 240
SETTLE_S = 2.5                     # баланс шлюза обновляется не мгновенно (как `draft_render._PC_SETTLE_S`)
PHOTO_COST_LOG = os.environ.get('PHOTO_COST_LOG', os.path.expanduser('~/scout-scenes/photo-cost.jsonl'))
CACHE_ROOT = Path(os.path.expanduser('~/remlab-logs/trial/redraw-cache'))
GOOGLE_AR = {'1:1': 1.0, '2:3': 2 / 3, '3:2': 1.5, '3:4': 0.75, '4:3': 4 / 3, '4:5': 0.8, '5:4': 1.25, '9:16': 9 / 16,
             '16:9': 16 / 9, '21:9': 21 / 9}
SEND_SIDE = 1536                   # длинная сторона отправки (тонкие окна и проёмы не слипаются)
MARGIN_REL, MARGIN_MIN = 0.06, 24  # запас вокруг контуров панелей VLM
# подгонка: больше этого — модель нарисовала другой лист (SALI-FP 2026 у gpt-image-2: масштаб 0,93–0,98, сдвиг до 57 px)
ALIGN_MAX_SCALE, ALIGN_MAX_ROT_DEG, ALIGN_MAX_SHIFT_REL = 0.10, 2.0, 0.06
# честность стен (проба T-13 на Wynne: p_ink 0,997, r_wall 0,986, F 0,979, кусков 0/0, толщина ×1,0)
WALLS = {'p_ink': 0.97, 'r_wall': 0.95, 'f_wall': 0.97, 't_ratio': (0.7, 1.5), 'extra_blobs': 0, 'missing_blobs': 1}
SMALL_M2 = 1.5                     # безымянное меньше этого — обрезок шума (чулан без подписи — тоже сюда; см. `alarm`)
NARROW_CM = 50                     # дверь уже — подозрение на ложный проём
LOST_LABELS_MAX = 0.10             # доля подписей без комнаты (как `pipeline.AREA_MISSED_MAX`)
SCALE_RANK = {'verified': 3, 'listing': 2, 'area': 1, 'not_verified': 0}

PROMPT = """The image is a real-estate floor plan ({W}x{H} px). It may contain colour fills, shadows, furniture and \
bathroom fixtures, kitchen units, stairs, 3D-looking doors, room names, dimensions, logos and a semi-transparent agency \
watermark.

Redraw it as a clean black-and-white architectural line drawing of EXACTLY the same plan. Your output will be laid over \
the input pixel by pixel, so every element must stay at the same position and size.

KEEP, unchanged in position, length and thickness:
- every wall, as a solid black band of the same thickness as in the input (thick outer walls stay thick, thin partitions \
stay thin);
- every door: a white gap in the wall of the same width, with one thin black quarter-circle swing line;
- every open archway: a white gap in the wall, no swing line;
- every window: two thin parallel black lines inside the wall, same length as in the input;
- the walls around the staircase (but not the steps).

REMOVE completely: all colour and floor fills, shadows, furniture, beds, sofas, bath, shower, WC, basin, kitchen units, \
appliances, stair treads and arrows, all text, numbers, dimensions, compass, scale bar, logos and watermarks.

Rules:
- pure white background (#FFFFFF) and pure black lines (#000000), no grey, no colour;
- same canvas, same framing, same margins: no crop, no zoom, no rotation, no straightening;
- do not add, move, merge or split anything; do not invent doors or windows; when unsure whether a line is a wall, keep \
it exactly as drawn.
Return one image with exactly the proportions of the input.
"""
PROMPT_VERSION = 'v1-base'         # = `plan-clean-probe/prompts/v1-base.txt` (проба T-13, попытка 2)


class RedrawError(Exception):
    def __init__(self, msg: str, usd: float = 0.0):
        super().__init__(msg)
        self.usd = usd


def mode(env=None) -> str:
    """FP_REDRAW: пусто/0/off — выкл.; force — всегда (оценка); иначе — только при тревожном разборе оригинала."""
    v = str((os.environ if env is None else env).get('FP_REDRAW') or '').strip().lower()
    if v in ('', '0', 'off', 'no', 'false'):
        return 'off'
    return 'force' if v == 'force' else 'on'


def cap_usd(env=None) -> float:
    try:
        return float((os.environ if env is None else env).get('FP_REDRAW_CAP_USD') or CAP_USD)
    except ValueError:
        return CAP_USD


# ── когда звать ────────────────────────────────────────────────────────────────────────────────────────────────────

def stats(res: dict, log: dict) -> dict:
    """Проверяемые признаки разбора (одни и те же для оригинала и чистого)."""
    rooms = [r for p in res['panels'] for r in p['rooms']]
    labs = [q for P in log.get('panels', []) for q in P.get('label_report') or []]
    doors = [o for p in res['panels'] for o in p['openings'] if o['kind'] == 'door']
    return {'rooms': len(rooms),
            'unlabeled': sum(1 for r in rooms if 'unlabeled' in r['flags']),
            'small_unlabeled': sum(1 for r in rooms if 'unlabeled' in r['flags'] and r['areaM2'] < SMALL_M2),
            'merged': sum(1 for r in rooms if 'merged' in r['flags']),
            'labels': len(labs), 'labels_found': sum(1 for q in labs if q.get('room') is not None),
            'doors': len(doors), 'narrow_doors': sum(1 for o in doors if o['widthCm'] < NARROW_CM),
            'windows': sum(1 for p in res['panels'] for o in p['openings'] if o['kind'] == 'window'),
            'scale': res['scale']['status']}


def alarm(res: dict, log: dict) -> list:
    """Тревожный разбор оригинала — признаки шума листа (заливки, водяной знак, мебель режут комнаты на обрезки):
      small_unlabeled — безымянные комнаты < SMALL_M2 (обрезки; Wynne 3, Berrys 3);
      merged          — подписи двух комнат в одной (стена потерялась: Wynne T-13 «Kitchen/Diner + Hall»);
      labels_lost     — доля подписей без комнаты > LOST_LABELS_MAX (комната не замкнулась; `area_unusable:coverage`);
      narrow_doors    — дверь < NARROW_CM (ложный проём в разрыве штриховки).
    → список причин (пусто — оригинал спокойный, перерисовку не зовём)."""
    s = stats(res, log)
    why = []
    if s['small_unlabeled']:
        why.append(f"small_unlabeled:{s['small_unlabeled']}")
    if s['merged']:
        why.append(f"merged:{s['merged']}")
    if s['labels'] and (s['labels'] - s['labels_found']) / s['labels'] > LOST_LABELS_MAX:
        why.append(f"labels_lost:{s['labels'] - s['labels_found']}/{s['labels']}")
    if s['narrow_doors']:
        why.append(f"narrow_doors:{s['narrow_doors']}")
    return why


# ── маска надписей (проба T-13 `mask_probe.mask`) ──────────────────────────────────────────────────────────────────

INK = 110                          # темнее — «чернила» (текст и стены)
CH_MAX_H, CH_MAX_W = 22, 34        # знак на листе 1334 px по длинной стороне (Wynne); другие листы — пропорционально


def _comps(gray, k: float):
    import cv2
    import numpy as np
    n, _lab, st, cen = cv2.connectedComponentsWithStats((gray < INK).astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if h <= CH_MAX_H * k and w <= CH_MAX_W * k and a >= 3:
            out.append({'x': x, 'y': y, 'w': w, 'h': h, 'cx': float(cen[i][0]), 'cy': float(cen[i][1])})
    return out


def _grow_line(seed, cs, gap, dy):
    """От знака — строка влево/вправо: соседи по горизонтали с зазором ≤ gap и той же высотой центра."""
    line, x0, x1, cy = [seed], seed['x'], seed['x'] + seed['w'], seed['cy']
    changed = True
    while changed:
        changed = False
        for c in cs:
            if c in line or abs(c['cy'] - cy) > dy:
                continue
            if c['x'] <= x1 + gap and c['x'] + c['w'] >= x0 - gap:
                line.append(c)
                x0, x1 = min(x0, c['x']), max(x1, c['x'] + c['w'])
                changed = True
    return line


def _bbox(line, pad):
    return [min(c['x'] for c in line) - pad, min(c['y'] for c in line) - pad,
            max(c['x'] + c['w'] for c in line) + pad, max(c['y'] + c['h'] for c in line) + pad]


def mask_labels(sheet_rgb, vdir: Path, plan: str):
    """Надписи комнат (по точкам VLM) и строки над/под планом (заголовки этажей, подвал) — белым; пиксели стен в рамке
    подписи остаются. → (лист с маской, рамки)."""
    import cv2
    import numpy as np
    import vlm
    from PIL import Image
    W, H = sheet_rgb.size
    k = min(1.6, max(0.7, max(W, H) / 1334.0))
    g = cv2.cvtColor(np.array(sheet_rgb), cv2.COLOR_RGB2GRAY)
    cs = _comps(g, k)
    p = Path(vdir) / f'raw-{plan}-{vlm.label_kind(vdir, plan)}.txt'
    d = (vlm.parse(p.read_text()) or {}) if p.exists() else {}
    boxes = []
    for r in d.get('rooms', []):
        if not r.get('pt'):
            continue
        px, py = r['pt'][0] * W / 1000.0, r['pt'][1] * H / 1000.0
        near = [c for c in cs if abs(c['cx'] - px) <= 60 * k and abs(c['cy'] - py) <= 14 * k]
        if not near:
            continue
        seed = min(near, key=lambda c: (c['cx'] - px) ** 2 + 4 * (c['cy'] - py) ** 2)
        boxes.append({'src': 'vlm', 'box': _bbox(_grow_line(seed, cs, 9 * k, 6 * k), 3)})
    if boxes:
        y0 = min(b['box'][1] for b in boxes) - 160 * k
        y1 = max(b['box'][3] for b in boxes) + 60 * k
        used = set()
        for c in sorted(cs, key=lambda c: (c['cy'], c['cx'])):
            if (c['x'], c['y']) in used:
                continue
            if not (y0 - 20 * k < c['cy'] < y0 + 80 * k or y1 - 10 * k < c['cy'] < y1 + 110 * k):
                continue
            line = _grow_line(c, cs, 13 * k, 5 * k)
            used.update((q['x'], q['y']) for q in line)
            if len(line) >= 3:
                boxes.append({'src': 'line', 'box': _bbox(line, 2)})
    ink = (g < INK).astype(np.uint8)
    chars = np.zeros_like(ink)
    for c in cs:
        chars[c['y']:c['y'] + c['h'], c['x']:c['x'] + c['w']] = 1
    wall = cv2.dilate(ink & (1 - chars), np.ones((3, 3), np.uint8)).astype(bool)
    arr = np.array(sheet_rgb).copy()
    for b in boxes:
        x0, y0b, x1, y1b = (int(round(v)) for v in b['box'])
        x0, y0b = max(0, x0), max(0, y0b)
        reg = arr[y0b:y1b + 1, x0:x1 + 1]
        keep = wall[y0b:y1b + 1, x0:x1 + 1] if b['src'] == 'vlm' else np.zeros(reg.shape[:2], bool)
        reg[~keep] = 255
    return Image.fromarray(arr), boxes


# ── запрос: кусок листа + поля под пропорцию модели ───────────────────────────────────────────────────────────────

def crop_box(W: int, H: int, vdir: Path, plan: str) -> list:
    """Рамка запроса: объединение контуров панелей VLM (сетка 0–1000) + запас; нет панелей или ответ оборван лимитом
    (`_truncated`: выжили не все этажи — Nethercote ушёл на перерисовку одной левой частью, T-27) — весь лист."""
    import vlm
    p = Path(vdir) / f'raw-{plan}-panels.txt'
    pts = []
    d = (vlm.parse(p.read_text()) or {}) if p.exists() else {}
    if d.get('_truncated'):
        return [0, 0, W, H]
    for q in d.get('panels', []):
        pts += [(x * W / 1000.0, y * H / 1000.0) for x, y in q.get('poly', [])]
    if not pts:
        return [0, 0, W, H]
    xs, ys = [a for a, _ in pts], [b for _, b in pts]
    m = max(MARGIN_MIN, MARGIN_REL * max(max(xs) - min(xs), max(ys) - min(ys)))
    return [max(0, int(min(xs) - m)), max(0, int(min(ys) - m)), min(W, int(max(xs) + m)), min(H, int(max(ys) + m))]


def pad_to(img, aspect: float):
    """Белые поля до пропорции (только добавляем). → (картинка, поля l,t,r,b)."""
    from PIL import Image
    w, h = img.size
    W2, H2 = (round(h * aspect), h) if w / h < aspect else (w, round(w / aspect))
    l, t = (W2 - w) // 2, (H2 - h) // 2
    can = Image.new('RGB', (W2, H2), (255, 255, 255))
    can.paste(img, (l, t))
    return can, [l, t, W2 - w - l, H2 - h - t]


def _png(im) -> bytes:
    b = io.BytesIO()
    im.convert('RGB').save(b, 'PNG')          # PNG: JPEG мылит тонкие линии
    return b.getvalue()


# ── шлюз ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _key() -> str:
    sys.path.insert(0, str(SCOUT))
    import env_keys
    return env_keys.need('VERCEL_AI_GATEWAY_KEY')


def _balance(key: str):
    try:
        req = urllib.request.Request(GW_CREDITS, headers={'Authorization': 'Bearer ' + key})
        with urllib.request.urlopen(req, timeout=6) as r:
            return float(json.loads(r.read()).get('balance'))
    except Exception:  # noqa: BLE001 — баланс только для учёта цены
        return None


def _cost_log(rec: dict) -> None:
    try:
        Path(PHOTO_COST_LOG).parent.mkdir(parents=True, exist_ok=True)
        with open(PHOTO_COST_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
    except Exception as e:  # noqa: BLE001 — учёт не роняет задание
        print(f'ЦЕНА ПЕРЕРИСОВКИ: запись не сделана — {type(e).__name__}: {e}', flush=True)


def draw_gateway(sent, prompt: str, ar_name: str, engine: str = ENGINE, label: str = 'trial-redraw') -> tuple:
    """Один платный вызов модели картинок через шлюз (/chat/completions, Google). Цена — разница баланса ключа до/после
    (общий счёт: параллельные задания DEV могут влезть), строка — в `PHOTO_COST_LOG`. → (картинка, $)."""
    from PIL import Image
    key = _key()
    t0 = time.time()
    bal0 = _balance(key)
    rec = {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t0)), 'label': label, 'fn': 'redraw.draw_gateway',
           'model': engine, 'size': IMAGE_SIZE, 'aspect': ar_name, 'n_images': 1, 'prompt': PROMPT_VERSION,
           'pid': os.getpid(), 't_start': round(t0, 3), 'task': os.environ.get('PHOTO_COST_TASK')}
    body = {'model': engine, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(_png(sent)).decode()}}]}],
        'modalities': ['image', 'text'],
        'providerOptions': {'google': {'imageConfig': {'aspectRatio': ar_name, 'imageSize': IMAGE_SIZE}}}}
    req = urllib.request.Request(GW_CHAT, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    img, err = None, None
    try:
        with urllib.request.urlopen(req, timeout=GW_TIMEOUT) as r:
            j = json.loads(r.read())
        msg = (j.get('choices') or [{}])[0].get('message') or {}
        for x in msg.get('images') or []:
            u = (x.get('image_url') or {}).get('url', '') if isinstance(x, dict) else ''
            if u.startswith('data:'):
                img = Image.open(io.BytesIO(base64.b64decode(u.split(',', 1)[1]))).convert('RGB')
                break
        if img is None:
            err = 'no image: ' + json.dumps(j, ensure_ascii=False)[:300]
    except urllib.error.HTTPError as e:
        err = f'HTTP {e.code}: {e.read().decode("utf-8", "replace")[:300]}'
    except Exception as e:  # noqa: BLE001 — сеть/таймаут: перерисовки нет, задание идёт с оригиналом
        err = f'{type(e).__name__}: {str(e)[:300]}'
    time.sleep(SETTLE_S)
    bal1 = _balance(key)
    usd = round(bal0 - bal1, 6) if bal0 is not None and bal1 is not None and bal0 > bal1 else None
    rec.update(t_end=round(time.time(), 3), dur_s=round(time.time() - t0, 1), ok=img is not None, bal0=bal0, bal1=bal1)
    if usd is not None:
        rec.update(cost_usd=usd, cost_source='balance_delta')
    else:
        rec['cost_note'] = 'баланс не уменьшился или не узнан'
    if err:
        rec['error'] = err
    _cost_log(rec)
    # баланс не узнан, а картинка пришла — считаем по цене (учёт не занижаем); отказ без списания — 0
    usd = usd if usd is not None else (PRICE_USD.get(engine, 0.15) if img is not None else 0.0)
    if img is None:
        raise RedrawError(err or 'no image', usd)
    return img, usd


# ── обратно в пиксели оригинала ────────────────────────────────────────────────────────────────────────────────────

def back_to_crop(raw, padded_size, pad, crop_size):
    from PIL import Image
    im = raw.convert('RGB').resize(tuple(padded_size), Image.LANCZOS)
    l, t, r, b = pad
    im = im.crop((l, t, padded_size[0] - r, padded_size[1] - b))
    return im.resize(tuple(crop_size), Image.LANCZOS) if im.size != tuple(crop_size) else im


def align(orig_gray, clean_gray) -> dict:
    """ECC (аффинно, пирамида 1/4 → 1/2 → 1) по размытым «чернилам»; warp — координаты оригинала → координаты ответа
    (`warpAffine(..., WARP_INVERSE_MAP)`). Вне потолков или ECC не сошёлся — ok=False."""
    import cv2
    import numpy as np

    def ink(g):
        return cv2.GaussianBlur((g < 140).astype(np.float32), (0, 0), 2.5)
    a, b = ink(orig_gray), ink(clean_gray)
    H, W = a.shape
    warp = np.eye(2, 3, dtype=np.float32)
    cc = None
    try:
        for s in (0.25, 0.5, 1.0):
            A = cv2.resize(a, (max(8, int(W * s)), max(8, int(H * s))), interpolation=cv2.INTER_AREA)
            B = cv2.resize(b, (A.shape[1], A.shape[0]), interpolation=cv2.INTER_AREA)
            w = warp.copy()
            w[:, 2] *= s
            cc, w = cv2.findTransformECC(A, B, w, cv2.MOTION_AFFINE,
                                         (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
            w[:, 2] /= s
            warp = w
    except cv2.error as e:
        return {'ok': False, 'why': f'ecc: {str(e)[:120]}', 'warp': np.eye(2, 3).tolist()}
    sx, sy = float(math.hypot(warp[0, 0], warp[1, 0])), float(math.hypot(warp[0, 1], warp[1, 1]))
    rot = math.degrees(math.atan2(warp[1, 0], warp[0, 0]))
    dx, dy = float(warp[0, 2]), float(warp[1, 2])
    ok = (abs(sx - 1) <= ALIGN_MAX_SCALE and abs(sy - 1) <= ALIGN_MAX_SCALE and abs(rot) <= ALIGN_MAX_ROT_DEG
          and max(abs(dx), abs(dy)) <= ALIGN_MAX_SHIFT_REL * max(W, H))
    return {'ok': ok, 'why': None if ok else 'limits', 'scale': [round(sx, 4), round(sy, 4)], 'rot_deg': round(rot, 2),
            'shift_px': [round(dx, 1), round(dy, 1)], 'ecc': round(float(cc), 4) if cc is not None else None,
            'warp': warp.tolist()}


def apply_warp(img_rgb, warp, size):
    import cv2
    import numpy as np
    from PIL import Image
    a = cv2.warpAffine(np.array(img_rgb.convert('RGB')), np.array(warp, np.float32), tuple(size),
                       flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(255, 255, 255))
    return Image.fromarray(a)


# ── честность стен (пиксели, без разбора; проба T-13 `clean_probe.faithfulness`) ───────────────────────────────────

def faithfulness(orig_rgb, clean_rgb, box) -> tuple:
    """Стены оригинала и чистого — маской разбора (`bench.build_mask` + `auto_cfg`); «чернила» оригинала — темнее 160.
    Допуск — треть толщины стены оригинала (≥ 2 px). p_ink — доля стен чистого над линией оригинала (1 − p_ink = выдумано);
    p_wall — над стеной оригинала; r_wall — доля стен оригинала, сохранённых в чистом; куски — лишние/пропавшие пятна
    длиннее 3 толщин стены. → (метрики, картинка наложения)."""
    import cv2
    import numpy as np
    import bench
    import fpcore as fc
    from PIL import Image
    O = cv2.cvtColor(np.array(orig_rgb), cv2.COLOR_RGB2BGR)
    C = cv2.cvtColor(np.array(clean_rgb), cv2.COLOR_RGB2BGR)
    og, cg = cv2.cvtColor(O, cv2.COLOR_BGR2GRAY), cv2.cvtColor(C, cv2.COLOR_BGR2GRAY)
    ow, cw = bench.build_mask(O, bench.auto_cfg(O)) > 0, bench.build_mask(C, bench.auto_cfg(C)) > 0
    oink = (og < 160) | ow
    t_o, t_c = float(fc.stroke_thickness(ow.astype(np.uint8))), float(fc.stroke_thickness(cw.astype(np.uint8)))
    tol = max(2, int(round(t_o / 3)))
    kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * tol + 1, 2 * tol + 1))

    def dil(m):
        return cv2.dilate(m.astype(np.uint8), kk) > 0
    n_c, n_o = max(1, int(cw.sum())), max(1, int(ow.sum()))
    p_ink = float((cw & dil(oink)).sum()) / n_c
    p_wall = float((cw & dil(ow)).sum()) / n_c
    r_wall = float((ow & dil(cw)).sum()) / n_o
    extra, missing = cw & ~dil(oink), ow & ~dil(cw)

    def blobs(m):
        n, _lab, st, _c = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
        out = []
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in st[i])
            if max(w, h) >= 3 * max(t_o, 2) and a >= max(t_o, 2) ** 2:
                out.append({'x': x + box[0], 'y': y + box[1], 'w': w, 'h': h, 'px': a})
        return sorted(out, key=lambda b: -b['px'])
    eb, mb = blobs(extra), blobs(missing)
    m = {'tol_px': tol, 'thickness_px': {'orig': round(t_o, 2), 'clean': round(t_c, 2)},
         't_ratio': round(t_c / t_o, 3) if t_o > 0 else None,
         'p_ink': round(p_ink, 4), 'p_wall': round(p_wall, 4), 'r_wall': round(r_wall, 4),
         'f_wall': round(2 * p_wall * r_wall / (p_wall + r_wall), 4) if p_wall + r_wall > 0 else 0.0,
         'extra_px': int(extra.sum()), 'missing_px': int(missing.sum()),
         'extra_blobs': eb[:8], 'missing_blobs': mb[:8], 'n_extra_blobs': len(eb), 'n_missing_blobs': len(mb)}
    base = np.stack([255 - (255 - og) // 3] * 3, -1).astype(np.uint8)
    base[cw & dil(ow)] = (40, 170, 60)
    base[extra] = (220, 30, 30)
    base[missing] = (30, 80, 230)
    return m, Image.fromarray(base)


def walls_verdict(f: dict) -> list:
    why = []
    if f['p_ink'] < WALLS['p_ink']:
        why.append('invented')
    if f['r_wall'] < WALLS['r_wall']:
        why.append('lost')
    if f['f_wall'] < WALLS['f_wall']:
        why.append('f')
    lo, hi = WALLS['t_ratio']
    if f['t_ratio'] is None or not lo <= f['t_ratio'] <= hi:
        why.append('thickness')
    if f['n_extra_blobs'] > WALLS['extra_blobs']:
        why.append('extra_blobs')
    if f['n_missing_blobs'] > WALLS['missing_blobs']:
        why.append('missing_blobs')
    return why


def triptych(a, b, c):
    from PIL import Image, ImageDraw
    w, h = a.size
    s = 2 if max(w, h) < 900 else 1
    can = Image.new('RGB', (3 * w * s + 20, h * s + 28), (255, 255, 255))
    d = ImageDraw.Draw(can)
    for i, (im, cap) in enumerate(((a, 'original'), (b, 'redraw (aligned)'), (c, 'green=match  red=extra  blue=missing'))):
        can.paste(im.resize((w * s, h * s)), (i * (w * s + 10), 28))
        d.text((i * (w * s + 10) + 4, 6), cap, fill=(0, 0, 0))
    return can


# ── попытка перерисовки: лист → проверенный чистый лист в пикселях оригинала ──────────────────────────────────────

def attempt(image, vdir, plan: str, outdir, *, draw=None, cap: float | None = None, cache_root=None,
            cache_only: bool = False, engine: str = ENGINE) -> dict:
    """Перерисовка листа `image` (оригинал задания; подписи VLM — из `vdir`, кэша оригинала). Не бросает: любой сбой —
    `why`, задание идёт с оригиналом. `draw(sent, prompt, aspect, engine) → (картинка, $)` — для тестов (0 $).
    Ответ модели кэшируется по sha отправленного (повтор того же листа — 0 $; `cache_only` — только кэш).
    → {'clean': путь чистого листа | None, 'usd', 'why', 'align', 'walls', 'cached', 'request'}"""
    from PIL import Image
    import cv2
    import numpy as np
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = {'clean': None, 'usd': 0.0, 'why': None, 'align': None, 'walls': None, 'cached': False, 'engine': engine,
           'prompt': PROMPT_VERSION}
    try:
        S = Image.open(image).convert('RGB')
        masked, boxes = mask_labels(S, Path(vdir), plan)
        box = crop_box(S.width, S.height, Path(vdir), plan)
        crop, mcrop = S.crop(tuple(box)), masked.crop(tuple(box))
        ar_name, ar = min(GOOGLE_AR.items(), key=lambda kv: abs(math.log(kv[1] / (crop.width / crop.height))))
        padded, pad = pad_to(mcrop, ar)
        kz = SEND_SIDE / max(padded.size)
        sent = padded.resize((round(padded.width * kz), round(padded.height * kz)), Image.LANCZOS)
        sent.save(outdir / 'sent.png')
        prompt = PROMPT.format(W=sent.width, H=sent.height)
        key = hashlib.sha256(_png(sent) + prompt.encode() + f'|{engine}|{IMAGE_SIZE}'.encode()).hexdigest()[:32]
        out['request'] = {'sheet': str(image), 'size': [S.width, S.height], 'crop_box': box, 'aspect': ar_name,
                          'pad': pad, 'padded_size': list(padded.size), 'sent_size': list(sent.size),
                          'mask_boxes': len(boxes), 'cache_key': key}
        cdir = Path(cache_root or CACHE_ROOT) / key
        raw_p = cdir / 'raw.png'
        if raw_p.exists():
            raw, out['cached'] = Image.open(raw_p).convert('RGB'), True
        elif cache_only:
            out['why'] = 'cache_only'
            return out
        else:
            price, lim = PRICE_USD.get(engine, 0.15), (CAP_USD if cap is None else cap)
            if price > lim:
                out['why'] = 'budget'
                return out
            try:
                raw, usd = (draw or draw_gateway)(sent, prompt, ar_name, engine)
            except RedrawError as e:
                out['usd'], out['why'], out['error'] = round(float(e.usd), 6), 'model', str(e)[:300]
                return out
            out['usd'] = round(float(usd), 6)
            cdir.mkdir(parents=True, exist_ok=True)
            tmp = cdir / '.raw.png.tmp'
            raw.save(tmp, 'PNG')
            os.replace(tmp, raw_p)
        raw.save(outdir / 'raw.png')
        back = back_to_crop(raw, padded.size, pad, crop.size)
        al = align(cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY), cv2.cvtColor(np.array(back), cv2.COLOR_RGB2GRAY))
        out['align'] = {k: v for k, v in al.items() if k != 'warp'}
        out['align']['warp'] = al['warp']
        if not al['ok']:
            out['why'] = 'align'
            return out
        clean_crop = apply_warp(back, al['warp'], crop.size)
        full = Image.new('RGB', S.size, (255, 255, 255))
        full.paste(clean_crop, (box[0], box[1]))
        clean_p = outdir / 'clean-sheet.png'
        full.save(clean_p)
        f, ov = faithfulness(crop, clean_crop, box)
        triptych(crop, clean_crop, ov).save(outdir / 'compare.png')
        out['walls'] = f
        bad = walls_verdict(f)
        if bad:
            out['why'] = 'walls:' + '+'.join(bad)
            return out
        out['clean'] = str(clean_p)
        return out
    except Exception as e:  # noqa: BLE001 — сбой перерисовки не роняет задание: итог — оригинал
        out['why'] = f'error:{type(e).__name__}'
        out['error'] = str(e)[:300]
        return out
    finally:
        (outdir / 'redraw.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))


# ── двери, окна, связность: чистый против оригинала ───────────────────────────────────────────────────────────────

PASS_KINDS = ('door', 'opening')   # проход (дверь или арка): тип между разборами может смениться — сравниваем как проход


def topology(log: dict, models: dict) -> dict:
    """Комнаты и проёмы разбора в пикселях листа (px = м × ppm + угол bbox панели — оба разбора в сетке оригинала).
    Проход → до двух ближайших комнат, чей контур не дальше толщины стены от центра проёма; наружный — комната + OUT.
    → {'rooms': [{'names', 'rings'}], 'openings': [{'kind', 'x', 'y', 'tol', 'exterior', 'sides'}]}"""
    import cv2
    import numpy as np
    t = float(log.get('thickness_px') or 0.0)
    reach = 0.75 * max(t, 4.0) + 3.0
    rooms, opens = [], []
    for P in log.get('panels', []):
        m = models.get(tuple(P['bbox_px']))
        if m is None:
            continue
        ppm, (bx, by) = float(m['ppm']), m['bbox_px'][:2]
        names = {r['id']: list(r.get('names') or []) for r in m.get('rooms', [])}
        rings = {}
        for f in m.get('floors', []):
            if f.get('room') is None or len(f.get('outer') or []) < 3:
                continue
            rings.setdefault(f['room'], []).append(
                np.array([[x * ppm + bx, y * ppm + by] for x, y in f['outer']], np.float32).reshape(-1, 1, 2))
        base = len(rooms)
        idx = {}
        for rid, rr in rings.items():
            idx[rid] = len(rooms)
            rooms.append({'names': names.get(rid, []), 'rings': rr, 'panel': tuple(P['bbox_px'])})
        for o in m.get('openings', []):
            kind = o.get('kind') if o.get('kind') in ('door', 'window') else 'opening'
            opens.append({'kind': kind, 'x': float(o['c'][0]) * ppm + bx, 'y': float(o['c'][1]) * ppm + by,
                          'tol': max(8.0, 0.35 * ppm), 'exterior': bool(o.get('exterior')), 'sides': [],
                          'rooms_from': base, 'rooms_to': len(rooms)})
    for o in opens:
        if o['kind'] == 'window':
            continue
        d = []
        for i in range(o['rooms_from'], o['rooms_to']):
            dist = max(cv2.pointPolygonTest(r, (o['x'], o['y']), True) for r in rooms[i]['rings'])
            if dist >= -reach:
                d.append((-dist, i))
        d.sort()
        o['sides'] = [i for _, i in d[:2]]
    return {'rooms': rooms, 'openings': opens}


ABSORB_MIN = 0.5                   # безымянный кусок ≥ этой доли лежит в названной комнате другого разбора — он её часть


def absorb(ta: dict, tb: dict) -> None:
    """Безымянная комната разбора `ta`, которая большей частью (≥ ABSORB_MIN площади) лежит в НАЗВАННОЙ комнате разбора
    `tb`, получает её имена (`alias`): обрезок шума у лестницы в оригинале — часть «Hall» чистого, и связь
    «Lounge – обрезок – WC» сравнивается как «Lounge – Hall – WC», а не как потеря ребра. Оба разбора — в пикселях
    листа оригинала, поэтому площади сравнимы напрямую."""
    import cv2
    import numpy as np
    pts = [r for t in (ta, tb) for x in t['rooms'] for r in x['rings']]
    if not pts:
        return
    allp = np.concatenate([p.reshape(-1, 2) for p in pts])
    W, H = int(allp[:, 0].max()) + 2, int(allp[:, 1].max()) + 2

    def mask(r):
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [p.reshape(-1, 2).astype(np.int32) for p in r['rings']], 1)
        return m.astype(bool)
    named_b = [(r, mask(r)) for r in tb['rooms'] if r['names']]
    for r in ta['rooms']:
        if r['names'] or r.get('alias'):
            continue
        m = mask(r)
        a = int(m.sum())
        if not a or not named_b:
            continue
        best, ov = max(((rb, int((m & mb).sum())) for rb, mb in named_b), key=lambda x: x[1])
        if ov >= ABSORB_MIN * a:
            r['alias'] = list(best['names'])


def _named(topo, i) -> bool:
    return i == 'OUT' or bool(topo['rooms'][i]['names'] or topo['rooms'][i].get('alias'))


def _labels(topo, i) -> list:
    return ['OUT'] if i == 'OUT' else (topo['rooms'][i]['names'] or topo['rooms'][i].get('alias') or [])


def _ends(topo, o):
    """Концы прохода: две комнаты, или комната + OUT (наружный). Иначе — None (проход в никуда — в граф не входит)."""
    s = o['sides']
    if len(s) == 2:
        return s[0], s[1]
    if len(s) == 1 and o['exterior']:
        return s[0], 'OUT'
    return None


def groups(*topos) -> dict:
    """Имена, слитые в одну комнату хоть в одном разборе, — одна вершина графа (имя → метка группы). Иначе разрезанная
    перерисовкой слитая комната («Kitchen/Diner + Hall») «теряла» бы рёбра второго имени, хотя проход тот же."""
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            a = parent[a]
        return a
    for t in topos:
        for r in t['rooms']:
            ns = r['names']
            for n in ns[1:]:
                ra, rb = find(ns[0]), find(n)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    out = {}
    for n in list(parent):
        out.setdefault(find(n), []).append(n)
    return {n: '+'.join(sorted(ms)) for ms in out.values() if len(ms) > 1 for n in ms}


def links(topo: dict, only=None, group=None) -> set:
    """Граф смежности по ИМЕНАМ подписей (одни и те же у обоих разборов — подписи с оригинала): ребро a–b — проход между
    их комнатами, напрямую или через безымянные комнаты (обрезки шума прозрачны); имена одной слитой комнаты — тоже ребро.
    `only` — индексы проёмов, по которым строить (для «объяснённых» новых рёбер); `group` — имя → вершина (`groups`),
    петли внутри группы не считаются."""
    g = (lambda n: group.get(n, n)) if group else (lambda n: n)
    adj = {i: set() for i in range(len(topo['rooms']))}
    adj['OUT'] = set()
    for k, o in enumerate(topo['openings']):
        if o['kind'] not in PASS_KINDS or (only is not None and k not in only):
            continue
        e = _ends(topo, o)
        if e:
            adj[e[0]].add(e[1])
            adj[e[1]].add(e[0])
    E = set()
    for i in adj:
        if not _named(topo, i):
            continue
        ls = sorted({g(n) for n in _labels(topo, i)})
        for a in ls:
            for b in ls:
                if a < b:
                    E.add((a, b))
        seen, stack = {i}, list(adj[i])
        while stack:
            j = stack.pop()
            if j in seen:
                continue
            seen.add(j)
            if _named(topo, j):
                for a in ls:
                    for b in {g(n) for n in _labels(topo, j)}:
                        if a != b:
                            E.add(tuple(sorted((a, b))))
            else:
                stack.extend(adj[j])
    return E


def _connected(members: list, E: set) -> bool:
    ms = set(members)
    seen, stack = {members[0]}, [members[0]]
    while stack:
        a = stack.pop()
        for x, y in E:
            for p, q in ((x, y), (y, x)):
                if p == a and q in ms and q not in seen:
                    seen.add(q)
                    stack.append(q)
    return seen == ms


def match_openings(A: list, B: list) -> dict:
    """Проём A → ближайший проём B того же класса (окно / проход) в допуске. → {индекс A: индекс B}."""
    def cls(o):
        return 'window' if o['kind'] == 'window' else 'pass'
    pairs = sorted((math.hypot(q['x'] - o['x'], q['y'] - o['y']), i, j)
                   for i, o in enumerate(A) for j, q in enumerate(B)
                   if cls(o) == cls(q) and math.hypot(q['x'] - o['x'], q['y'] - o['y']) <= max(o['tol'], q['tol']))
    ua, ub, m = set(), set(), {}
    for _d, i, j in pairs:
        if i in ua or j in ub:
            continue
        ua.add(i)
        ub.add(j)
        m[i] = j
    return m


def _real(topo, o) -> bool:
    """Проход между названными комнатами (или названной и улицей) — настоящий; проход в обрезок шума — нет."""
    e = _ends(topo, o)
    return bool(e) and _named(topo, e[0]) and _named(topo, e[1])


def decide(res_o: dict, log_o: dict, models_o: dict, res_c: dict, log_c: dict, models_c: dict) -> dict:
    """Приёмка разбора чистого листа против разбора оригинала. Отказ (итог — оригинал), по порядку:
      door_lost      — настоящий проход оригинала (между названными комнатами / наружу) не найден в чистом;
      window_lost    — окно оригинала не найдено в чистом;
      link_lost      — пропало ребро графа смежности (имена комнат через проходы);
      window_new     — окно, которого нет в оригинале (выдумано);
      door_new       — новый проход между названными комнатами (выдуман или сдвинут дальше допуска);
      link_new       — новое ребро графа, не объяснённое проходами, найденными в обоих разборах;
      worse:<что>    — по проверяемым признакам хуже (подписей нашло комнату меньше, безымянных/слитых/узких дверей
                       больше, масштаб слабее);
      not_better     — ничего не лучше (перерисовка не нужна: дешевле и надёжнее оригинал).
    Площадь из объявления — не критерий (масштаб по ней подтверждается отдельно). → {'accept', 'why', ...подробности}."""
    to, tc = topology(log_o, models_o), topology(log_c, models_c)
    absorb(to, tc)
    absorb(tc, to)
    Ao, Ac = to['openings'], tc['openings']
    m = match_openings(Ao, Ac)
    hit_c = set(m.values())
    grp = groups(to, tc)

    def inner(topo, o):
        """Проход внутри слитой группы (разрез слитой комнаты) — не «новый» и не «потерянный» сам по себе."""
        e = _ends(topo, o)
        if not e or 'OUT' in e:
            return False
        ga = {grp.get(n, n) for n in _labels(topo, e[0])}
        gb = {grp.get(n, n) for n in _labels(topo, e[1])}
        return bool(ga & gb)
    lost_doors = [i for i, o in enumerate(Ao) if o['kind'] in PASS_KINDS and i not in m and _real(to, o)
                  and not inner(to, o)]
    lost_win = [i for i, o in enumerate(Ao) if o['kind'] == 'window' and i not in m]
    new_win = [j for j, o in enumerate(Ac) if o['kind'] == 'window' and j not in hit_c]
    new_doors = [j for j, o in enumerate(Ac) if o['kind'] in PASS_KINDS and j not in hit_c and _real(tc, o)
                 and not inner(tc, o)]
    Eo, Ec = links(to, group=grp), links(tc, group=grp)
    lost_links = sorted(Eo - Ec)
    # слитая в оригинале комната, разрезанная в чистом, — части обязаны сообщаться (проход или безымянный кусок)
    raw_c, seen_g = links(tc), set()
    for n, gname in grp.items():
        if gname in seen_g:
            continue
        seen_g.add(gname)
        members = [x for x in grp if grp[x] == gname]
        if not _connected(sorted(members), raw_c):
            lost_links.append(('split', gname))
    new_links = sorted((Ec - Eo) - links(tc, only=hit_c, group=grp))
    so, sc = stats(res_o, log_o), stats(res_c, log_c)
    worse = [k for k, bad in (('labels_found', sc['labels_found'] < so['labels_found']),
                              ('unlabeled', sc['unlabeled'] > so['unlabeled']),
                              ('small_unlabeled', sc['small_unlabeled'] > so['small_unlabeled']),
                              ('merged', sc['merged'] > so['merged']),
                              ('narrow_doors', sc['narrow_doors'] > so['narrow_doors']),
                              ('scale', SCALE_RANK.get(sc['scale'], 0) < SCALE_RANK.get(so['scale'], 0))) if bad]
    better = [k for k, ok in (('labels_found', sc['labels_found'] > so['labels_found']),
                              ('unlabeled', sc['unlabeled'] < so['unlabeled']),
                              ('small_unlabeled', sc['small_unlabeled'] < so['small_unlabeled']),
                              ('merged', sc['merged'] < so['merged']),
                              ('narrow_doors', sc['narrow_doors'] < so['narrow_doors'])) if ok]
    if lost_doors:
        why = 'door_lost'
    elif lost_win:
        why = 'window_lost'
    elif lost_links:
        why = 'link_lost'
    elif new_win:
        why = 'window_new'
    elif new_doors:
        why = 'door_new'
    elif new_links:
        why = 'link_new'
    elif worse:
        why = 'worse:' + '+'.join(worse)
    elif not better:
        why = 'not_better'
    else:
        why = None

    def xy(L, ii):
        return [[round(L[i]['x']), round(L[i]['y'])] for i in ii]

    def door_link(topo, o):
        e = _ends(topo, o)
        ga, gb = ({grp.get(n, n) for n in _labels(topo, x)} for x in e)
        return {tuple(sorted((a, b))) for a in ga for b in gb if a != b}
    # для разбора ведущим: потерянная дверь, чья связь в чистом цела другой дверью (дубль / ложный проём оригинала?)
    lost_dup = [i for i in lost_doors if door_link(to, Ao[i]) and door_link(to, Ao[i]) <= Ec]
    return {'accept': why is None, 'why': why, 'better': better, 'worse': worse, 'stats_orig': so, 'stats_clean': sc,
            'openings': {'orig': len(Ao), 'clean': len(Ac), 'matched': len(m)},
            'lost_doors_px': xy(Ao, lost_doors), 'lost_doors_link_kept_px': xy(Ao, lost_dup), 'lost_windows_px': xy(Ao, lost_win),
            'new_windows_px': xy(Ac, new_win), 'new_doors_px': xy(Ac, new_doors),
            'links_orig': len(Eo), 'links_clean': len(Ec),
            'lost_links': [list(e) for e in lost_links], 'new_links': [list(e) for e in new_links]}


def add_flag(res: dict, flag: str) -> None:
    """Флаг результата — первым (список ≤ 30 у контракта: хвост режется, этот — остаётся)."""
    res['flags'] = list(dict.fromkeys([flag[:60]] + list(res.get('flags') or [])))[:30]


if __name__ == '__main__':
    print(__doc__)
