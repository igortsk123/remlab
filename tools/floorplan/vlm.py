#!/usr/bin/env python3
"""VLM-путь стенда планировок (T-20261109-02): та же модель и шлюз, что `tools/scout/drawing_dims.py:ask`
(Vercel AI Gateway, `google/gemini-3.8-flash`, только шлюз). Два вопроса на план: подписи комнат с точкой и «стены JSON-ом».
Оценка — теми же мерками, что OpenCV-путь (комнаты по эталону, LOO размеров), стены VLM растрируются в маску.

  ask:  python tools/floorplan/vlm.py ask <A|B|C> <labels|walls> <out-папка>   (ключ — из окружения запуска)
  eval: python tools/floorplan/vlm.py eval <out-папка>                         (без сети)

Деньги: остаток шлюза до/после (GET /v1/credits) + токены из ответа; потолок стенда $0,50 — проверяется перед вызовом.
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
INPUTS = Path('/home/pakar/remlab-logs/floorplan-bench/inputs')
MODEL = os.environ.get('FLOORPLAN_VLM_MODEL', 'google/gemini-3.8-flash')
CAP_USD = 0.50
CREDITS_URL = 'https://ai-gateway.vercel.sh/v1/credits'

PROMPTS = {
    'labels': (
        "This is an architectural floor plan image, {w}x{h} pixels. List EVERY room label printed on it. "
        "For each room give: the room name as printed; the metric dimensions as printed (two numbers in metres, in the "
        "printed order; null if not printed); and the pixel coordinates [x, y] of the centre of the room-name text in "
        "THIS image (origin top-left, x to the right, y down). Also list any printed floor-area totals. "
        "Answer with JSON only: {{\"rooms\": [{{\"name\": str, \"dims_m\": [a, b] | null, \"pt\": [x, y]}}], "
        "\"areas\": [{{\"label\": str, \"m2\": number}}]}}"),
    'walls': (
        "This is an architectural floor plan image, {w}x{h} pixels. Trace ALL walls (exterior and interior) as straight "
        "centre-line segments in pixel coordinates of THIS image (origin top-left, x right, y down). Draw walls as "
        "CONTINUOUS through door and window openings (do not break them), and list the openings separately. Include "
        "the wall thickness in pixels. Use as many segments as needed; diagonal walls are allowed. "
        "Answer with JSON only: {{\"walls\": [{{\"x1\": n, \"y1\": n, \"x2\": n, \"y2\": n, \"t\": n}}], "
        "\"openings\": [{{\"type\": \"door\"|\"window\", \"x\": n, \"y\": n, \"width\": n}}]}}"),
    'wallspro': (
        "This is an architectural floor plan image. Use a normalized coordinate grid 0-1000 on both axes (x: 0 = left "
        "edge, 1000 = right edge; y: 0 = top edge, 1000 = bottom edge). Trace ALL walls (exterior and interior) as "
        "straight centre-line segments in that 0-1000 grid. Draw walls as CONTINUOUS through door and window openings "
        "(do not break them), and list the openings separately. Include the wall thickness in the same grid units. "
        "Use as many segments as needed; diagonal walls are allowed. "
        "Answer with JSON only: {{\"walls\": [{{\"x1\": n, \"y1\": n, \"x2\": n, \"y2\": n, \"t\": n}}], "
        "\"openings\": [{{\"type\": \"door\"|\"window\", \"x\": n, \"y\": n, \"width\": n}}]}}"),
    'panels': (
        "This is a real-estate floor plan sheet. Use a normalized coordinate grid 0-1000 on both axes (x: 0 = left "
        "edge, 1000 = right edge; y: 0 = top edge, 1000 = bottom edge). The sheet may hold several separate drawings: "
        "floors of the house and separate buildings (outbuildings, garage, stables, pool house, cellar). List EACH "
        "separate building drawing as its own panel, with the printed title that belongs to it (e.g. 'Ground Floor', "
        "'First Floor', 'Outbuildings', 'Cellar'). If an outbuilding is drawn touching the house, it is still its own "
        "panel. For each panel give an outline polygon (4-12 vertices, clockwise) that follows that building's outer "
        "walls tightly and contains no other building, and the names of the rooms inside it. Ignore compass, scale bar, "
        "legend and text blocks. Answer with JSON only: {\"panels\": [{\"title\": str, \"poly\": [[x, y], ...], "
        "\"rooms\": [str]}]}"),
}
# $ за 1 токен (вход, выход) — из /v1/models шлюза 09.11; для потолка «худшего случая» перед вызовом
PRICE = {'google/gemini-3.8-flash': (0.75e-6, 3.75e-6), 'google/gemini-3.1-pro-preview': (2e-6, 12e-6)}


def credits():
    key = os.environ.get('VERCEL_AI_GATEWAY_KEY')
    if not key:
        return None
    req = urllib.request.Request(CREDITS_URL, headers={'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        return float(d.get('balance'))
    except Exception as e:  # noqa: BLE001 — остаток не обязателен, но сбой пишем
        print('credits: сбой', type(e).__name__, str(e)[:120], file=sys.stderr)
        return None


def jpeg(path):
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    im = im.convert('RGB')
    w, h = im.size                       # листы стенда ≤ 2048 — не ужимаем, координаты = пиксели исходника
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=92)
    return buf.getvalue(), w, h


def spent(out):
    p = Path(out) / 'calls.jsonl'
    if not p.exists():
        return 0.0, 0
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return sum(r.get('usd') or 0.0 for r in rows), len(rows)


def ask(plan, kind, out):
    sys.path.insert(0, str(HERE.parent / 'scout'))
    import llm_gateway  # noqa: E402 — только шлюз, без тяжёлых модулей scout
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    usd0, n0 = spent(out)
    if usd0 >= CAP_USD:
        raise SystemExit(f'потолок ${CAP_USD} исчерпан: ${usd0:.4f} за {n0} вызовов')
    pin, pout = PRICE.get(MODEL, (2e-6, 12e-6))
    max_tok = min(16000, int((CAP_USD - usd0 - 3000 * pin) / pout))   # худший случай не выходит за потолок
    if max_tok < 4000:
        raise SystemExit(f'остаток ${CAP_USD - usd0:.3f} мал для вызова {MODEL}')
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    img, w, h = jpeg(INPUTS / gold['image'])
    msg = [{'role': 'user', 'content': [
        {'type': 'text', 'text': PROMPTS[kind] if kind == 'panels' else PROMPTS[kind].format(w=w, h=h)},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(img).decode()}}]}]
    b0 = credits()
    t0 = time.time()
    resp = llm_gateway.chat(MODEL, msg, timeout=180, tries=3, direct_fallback=False, temperature=0, max_tokens=max_tok)
    sec = time.time() - t0
    time.sleep(3)
    b1 = credits()
    ch = resp['choices'][0]
    raw = ch['message']['content'] or ''
    usage = resp.get('usage') or {}
    usd = None
    for k in ('cost', 'total_cost'):
        if isinstance(usage.get(k), (int, float)):
            usd = float(usage[k])
    if usd is None and b0 is not None and b1 is not None:
        usd = round(b0 - b1, 6)
    rec = {'plan': plan, 'kind': kind, 'model': MODEL, 'sec': round(sec, 1), 'finish': ch.get('finish_reason'),
           'usage': usage, 'balance_before': b0, 'balance_after': b1, 'usd': usd, 'at': time.strftime('%H:%M:%S')}
    with open(out / 'calls.jsonl', 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    (out / f'raw-{plan}-{kind}.txt').write_text(raw)
    rec['max_tokens'] = max_tok
    print(json.dumps(rec, ensure_ascii=False))


def _pairs(pairs):
    """Сильная модель путает ключи («y» вместо «y1/y2», «y1» дважды) — дубли в JSON теряются. Чиним по порядку:
    x-значения → x1, x2; y-значения → y1, y2. Остальные ключи как есть (оговорка в отчёте)."""
    d = {}
    xs = [v for k, v in pairs if k in ('x', 'x1', 'x2')]
    ys = [v for k, v in pairs if k in ('y', 'y1', 'y2')]
    for k, v in pairs:
        if k not in ('x', 'x1', 'x2', 'y', 'y1', 'y2'):
            d[k] = v
    if len(xs) == 2 and len(ys) == 2:
        d.update(x1=xs[0], x2=xs[1], y1=ys[0], y2=ys[1])
        if [k for k, _ in pairs if k[0] in 'xy'] != ['x1', 'y1', 'x2', 'y2']:
            d['_fixed_keys'] = True
    elif len(xs) == 1 and len(ys) == 1:
        d.update(x=xs[0], y=ys[0])
    else:
        for k, v in pairs:
            d.setdefault(k, v)
    return d


def _loads(t):
    return json.loads(t, object_pairs_hook=_pairs)


def parse(raw):
    m = re.search(r'\{.*\}', raw, re.S)
    if not m:
        return None
    try:
        return _loads(m.group(0))
    except json.JSONDecodeError:
        pass
    # ответ оборван лимитом токенов (finish=length): берём всё до последнего целого объекта и закрываем массив
    txt = raw[raw.index('{'):]
    for cut in range(txt.rfind('}'), 0, -1):
        if txt[cut] != '}':
            continue
        for tail in (']}', ']}]}'):
            try:
                d = _loads(txt[:cut + 1] + tail)
                d['_truncated'] = True
                return d
            except json.JSONDecodeError:
                continue
    return None


def img_size(plan):
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    h, w = cv2.imread(str(INPUTS / gold['image'])).shape[:2]
    return w, h


def eval_labels(plan, data):
    """Подписи: найдено эталонных комнат с точным размером; ошибка точки. Gemini отдаёт координаты и в пикселях,
    и в своей сетке 0–1000 — считаем оба прочтения, берём лучшее и пишем, какое."""
    w, h = img_size(plan)
    best = None
    for name, kx, ky in (('px', 1.0, 1.0), ('norm1000', w / 1000, h / 1000)):
        d = json.loads(json.dumps(data))
        for r in d.get('rooms', []):
            if r.get('pt'):
                r['pt'] = [r['pt'][0] * kx, r['pt'][1] * ky]
        e = _eval_labels(plan, d)
        e['coords'] = name
        if best is None or (e['pt_err_px_median'] or 1e9) < (best['pt_err_px_median'] or 1e9):
            best = e
    return best


def _eval_labels(plan, data):
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    req = [g for g in gold['rooms'] if 'dims_m' in g]
    got = [r for r in (data or {}).get('rooms', []) if r.get('dims_m')]
    used, hits, dists = set(), 0, []
    for g in req:
        best, bd = None, 1e9
        for i, r in enumerate(got):
            if i in used:
                continue
            try:
                a, b = map(float, r['dims_m'][:2])
            except (TypeError, ValueError):
                continue
            if sorted([round(a, 2), round(b, 2)]) != sorted([round(x, 2) for x in g['dims_m']]):
                continue
            d = float(np.hypot(r['pt'][0] - g['pt'][0], r['pt'][1] - g['pt'][1])) if r.get('pt') else 1e6
            if d < bd:
                best, bd = i, d
        if best is not None:
            used.add(best)
            hits += 1
            dists.append(bd)
    return {'gold': len(req), 'dims_exact': hits, 'got': len(got), 'pt_err_px_median': float(np.median(dists)) if dists else None,
            'pt_err_px_max': float(max(dists)) if dists else None}


def eval_walls(plan, data, out, kind='walls'):
    """Стены VLM → маска → комнаты → метрики; два прочтения координат (px / 0–1000), лучшее — по числу найденных комнат."""
    w, h = img_size(plan)
    best = None
    for name, kx, ky in (('px', 1.0, 1.0), ('norm1000', w / 1000, h / 1000)):
        d = json.loads(json.dumps(data))
        for s_ in d.get('walls', []):
            for k in ('x1', 'x2'):
                if isinstance(s_.get(k), (int, float)):
                    s_[k] *= kx
            for k in ('y1', 'y2'):
                if isinstance(s_.get(k), (int, float)):
                    s_[k] *= ky
            if isinstance(s_.get('t'), (int, float)):
                s_['t'] *= (kx + ky) / 2
        e = _eval_walls(plan, d, out, f'{kind}-{name}')
        e['coords'] = name
        if best is None or e['topology']['found'] > best['topology']['found']:
            best = e
    return best


def _eval_walls(plan, data, out, tag):
    import bench
    import fpcore as fc
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    img = cv2.imread(str(INPUTS / gold['image']), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    wall = np.zeros((H, W), np.uint8)
    walls = (data or {}).get('walls', [])
    for s in walls:
        try:
            p1 = (int(round(s['x1'])), int(round(s['y1'])))
            p2 = (int(round(s['x2'])), int(round(s['y2'])))
            t = max(2, int(round(float(s.get('t') or 6))))
        except (KeyError, TypeError, ValueError):
            continue
        cv2.line(wall, p1, p2, 1, t)
    n, lab, outside = fc.free_components(wall)
    areas = np.bincount(lab.ravel(), minlength=n)
    rooms = [i for i in range(1, n) if areas[i] >= 200 and not outside[lab == i].any()]
    res = {'lab': lab, 'rooms': rooms, 'areas': areas, 'ppm': 6}
    groom = [dict(g) for g in gold['rooms']]
    fams = fc.angle_families(wall) if wall.any() else [0.0, 90.0]
    hit, obs = bench.match_gold(res, groom, fams)
    fit = fc.fit_scale(obs) if obs else None
    ppm = 1.0 / fit['s'] if fit else 50.0
    topo = bench.topology(res, groom, hit, ppm)
    loo = fc.loo_summary(fc.leave_one_out(obs)) if len(obs) >= 3 else None
    ov = (img.astype(float) * 0.35 + 255 * 0.65).astype(np.uint8)
    rng = np.random.default_rng(7)
    for rid in rooms:
        ov[lab == rid] = (ov[lab == rid] * 0.4 + rng.integers(120, 240, 3) * 0.6).astype(np.uint8)
    ov[wall > 0] = (60, 60, 60)
    for g in groom:
        cv2.circle(ov, tuple(map(int, g['pt'])), 6, (0, 120, 255) if g.get('_room') is not None else (0, 0, 255), -1)
    cv2.imwrite(str(Path(out) / f'vlm-walls-{plan}-{tag}.png'), ov)
    return {'segments': len(walls), 'fixed_keys': sum(1 for w_ in walls if w_.get('_fixed_keys')), 'openings': len((data or {}).get('openings', [])), 'topology': topo, 'loo': loo,
            'ppm': round(ppm, 2)}


def evaluate(out):
    out = Path(out)
    rep = {}
    for p in sorted(out.glob('raw-*-*.txt')):
        _, plan, kind = p.stem.split('-')
        data = parse(p.read_text())
        if data is None:
            rep[f'{plan}-{kind}'] = {'parse': 'fail'}
            continue
        rep[f'{plan}-{kind}'] = eval_labels(plan, data) if kind == 'labels' else eval_walls(plan, data, out, kind)
        if data.get('_truncated'):
            rep[f'{plan}-{kind}']['truncated'] = True
    usd, n = spent(out)
    rep['_money'] = {'calls': n, 'usd': round(usd, 4)}
    (out / 'vlm-eval.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float))
    print(json.dumps(rep, ensure_ascii=False, default=float))


if __name__ == '__main__':
    if sys.argv[1] == 'ask':
        ask(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        evaluate(sys.argv[2])
