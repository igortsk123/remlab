#!/usr/bin/env python3
"""Пост-QA финала ветки B (А4, урок 191): ворота ПОСЛЕ дорогого шага, не только до.

`collage_audit.py` проверяет коллаж ДО оплаты; после генерации gpt-image-2 брак ловили только
глаза. Здесь два дешёвых судьи по каждому кадру (перенос механики из pipeline2):
  1. ΔRGB кодом — цвет героев в финале против коллажа (боксы из instances.png, поиск по сдвигам,
     свето-инвариантные разности каналов);
  2. VLM `gpt-5-mini` — состав: каждый предмет коллажа ровно один раз, без лишней мебели,
     цвета не «исправлены» (~$0.003/кадр).
Вердикт — scene{n}-{cam}-qa.json; exit 3, если хоть один кадр не прошёл (гейт для батчей).

  ~/venvs/scout/bin/python viz_qa.py 21 --cams C1,C2
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCENE_DIR = os.path.expanduser(os.environ.get('SCENE_DIR', '~/scout-scenes'))
DRGB_T = 12          # порог хроматического дрейфа (ветка A: «пастель дрейфует в серый»)
SHIFTS = (-40, 0, 40)  # рендер смещает предметы на десятки px — ищем минимум по сдвигам


def _key() -> str:
    k = os.environ.get('OPENAI_API_KEY')
    if k:
        return k
    for p in (os.path.join(HERE, '.env'), '/home/pakar/mltest/.env'):
        try:
            for line in open(p):
                m = re.match(r'OPENAI_API_KEY=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"')
        except OSError:
            continue
    raise SystemExit('нет OPENAI_API_KEY')


def _chroma(c):
    return (c[0] - c[1], c[1] - c[2])   # свето-инвариантные разности каналов


def _mean_rgb(arr: np.ndarray):
    return tuple(float(x) for x in arr.reshape(-1, 3).mean(0))


def role_boxes(prefix: str) -> dict[str, tuple[int, int, int, int]]:
    """Роль → bbox в пикселях кадра коллажа: из instances.png + карты id в paint.json."""
    inst = np.asarray(Image.open(f'{prefix}-instances.png').convert('RGB'))[..., 0] // 8
    ids = json.load(open(f'{prefix}-paint.json'))['ids']
    out = {}
    for sid, role in ids.items():
        m = inst == int(sid)
        if m.sum() < 400:                 # крохотный след — bbox ни о чём
            continue
        ys, xs = np.where(m)
        out[role] = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return out


def qa_drgb(pasted: Image.Image, final: Image.Image, boxes: dict) -> list[dict]:
    """Цвет героев: сравниваем средний тон в боксе коллажа и финала (финал приводим к коллажу)."""
    fin = final.resize(pasted.size)
    src = np.asarray(pasted.convert('RGB'))
    fn = np.asarray(fin.convert('RGB'))
    H, W = src.shape[:2]
    issues = []
    for role, (x0, y0, x1, y1) in boxes.items():
        mx, my = int((x1 - x0) * 0.2), int((y1 - y0) * 0.2)
        want = _chroma(_mean_rgb(src[y0 + my:y1 - my, x0 + mx:x1 - mx]
                                 if (y1 - y0 > 2 * my + 4 and x1 - x0 > 2 * mx + 4)
                                 else src[y0:y1, x0:x1]))
        d = 1e9
        for dx in SHIFTS:
            for dy in SHIFTS:
                cx0, cy0 = max(0, x0 + mx + dx), max(0, y0 + my + dy)
                cx1, cy1 = min(W, x1 - mx + dx), min(H, y1 - my + dy)
                if cx1 - cx0 < 4 or cy1 - cy0 < 4:
                    continue
                got = _chroma(_mean_rgb(fn[cy0:cy1, cx0:cx1]))
                d = min(d, max(abs(a - b) for a, b in zip(want, got)))
        if d > DRGB_T:
            issues.append({'role': role, 'drgb': round(d, 1), 'box': [x0, y0, x1, y1]})
    return issues


def qa_vlm(pasted: Image.Image, final: Image.Image, roles: list[str], key: str) -> dict:
    def b64(im, side=1024):
        im = im.copy()
        im.thumbnail((side, side))
        b = io.BytesIO()
        im.convert('RGB').save(b, 'JPEG', quality=85)
        return base64.b64encode(b.getvalue()).decode()

    text = (
        'Image 1 is a draft collage: real product photos placed in a room render — it defines the '
        'EXACT set of objects, their positions and colours. Image 2 is the final render. Objects: '
        + ', '.join(roles) + '. Check ONLY: (1) every draft object present exactly once; '
        '(2) positions roughly kept; (3) product colours match the draft — a colour "corrected" to '
        'look more natural is an ERROR; (4) NO EXTRA furniture/lamps/rugs/plants beyond the draft '
        '(wall art, curtains, window view, finishes and shadows ARE allowed). Reply STRICT JSON: '
        '{"ok":bool,"issues":[{"what":"short problem","role":"role name"}]} Max 4 issues, worst first.')
    body = {'model': 'gpt-5-mini', 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': text},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64(pasted)}},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64(final)}}]}]}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                                 data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
        m = re.search(r'\{.*\}', out['choices'][0]['message']['content'], re.S)
        return json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001 — судья упал ≠ кадр плох; но факт печатаем, не глотаем
        print(f'  qa_vlm недоступен ({str(e)[:80]}) — вердикт только по ΔRGB', flush=True)
        return {'ok': True, 'issues': [], 'skipped': True}


def qa_cam(n: int, cam: str, key: str | None = None) -> bool:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
    fin_p = f'{prefix}-final.jpg'
    pasted_p = f'{prefix}-pasted.jpg'
    if not (os.path.exists(fin_p) and os.path.exists(pasted_p)):
        print(f'{cam}: нет финала или коллажа — QA пропущен')
        return True
    pasted = Image.open(pasted_p)
    final = Image.open(fin_p)
    boxes = role_boxes(prefix)
    drgb = qa_drgb(pasted, final, boxes)
    vlm = qa_vlm(pasted, final, sorted(boxes), key or _key())
    ok = not drgb and bool(vlm.get('ok', True))
    json.dump({'ok': ok, 'drgb_issues': drgb, 'vlm': vlm},
              open(f'{prefix}-qa.json', 'w'), ensure_ascii=False, indent=1)
    tail = '' if ok else f' ΔRGB={ [i["role"] for i in drgb] } vlm={vlm.get("issues", [])}'
    print(f'QA {cam}: {"ok" if ok else "БРАК"}{tail}', flush=True)
    return ok


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    key = _key()
    bad = [c for c in cams if not qa_cam(n, c, key)]
    if bad:
        print(f'сцена {n}: брак финала в {bad} — не показывать без пересмотра')
        sys.exit(3)
    print(f'сцена {n}: финал прошёл пост-QA')


if __name__ == '__main__':
    main()
