#!/usr/bin/env python3
"""Замер РАКУРСА съёмки в каталоге магазина: под каким углом снят товар.

Идея владельца: карточки одного поставщика обычно сняты одинаково — «в три четверти». Если угол
постоянный, его можно заложить в конвейер: вырезку ставить не строго лицом к камере, а с этим
разворотом, и она перестанет выглядеть плоской.

Угол оценивает vision-модель по фотографии: 0° — строго фас, положительные значения — виден
правый бок товара, отрицательные — левый.

  ~/venvs/scout/bin/python measure_angle.py --shop mnogomebeli.com --limit 10
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get('ANGLE_MODEL', 'gpt-5-mini')


def key(name: str) -> str:
    return ''


def photo_of(it: dict) -> str:
    k = re.sub(r'[^A-Za-z0-9]', '_', str(it['eid']))[:40]
    for p in (os.path.join(HERE, 'refs', f"{it['mid']}-{k}.jpg"),
              os.path.join(HERE, 'thumbs', f"{it['mid']}-{k}.png")):
        if os.path.exists(p):
            return p
    return ''


def ask_angle(path: str, oai: str) -> dict:
    im = Image.open(path).convert('RGB')
    im.thumbnail((512, 512))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {
        'model': MODEL,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text':
                 'This is a furniture catalogue photo. Estimate the camera yaw relative to the '
                 'front of the item: 0 = strictly frontal (only the front face visible), positive '
                 'degrees = the item is turned so its RIGHT side is visible, negative = LEFT side '
                 'visible. Also estimate the camera pitch (0 = eye level, positive = looking down). '
                 'Answer strictly as JSON: {"yaw_deg": <int>, "pitch_deg": <int>, '
                 '"front_visible": true|false}'},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
            ],
        }],
    }
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                                 data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {oai}',
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        txt = json.loads(r.read())['choices'][0]['message']['content']
    m = re.search(r'\{.*\}', txt, re.S)
    return json.loads(m.group(0)) if m else {}


def main() -> None:
    shop = sys.argv[sys.argv.index('--shop') + 1] if '--shop' in sys.argv else None
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 10
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    by_shop = defaultdict(list)
    seen = set()
    for s in sets:
        for role, it in s['items'].items():
            k = (it.get('mid'), it.get('eid'))
            if k in seen:
                continue
            seen.add(k)
            by_shop[it.get('shop', '?')].append((role, it))
    if not shop:
        for sh, items in sorted(by_shop.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f'{sh:24s} позиций {len(items)}')
        return

    oai = os.environ.get('OPENAI_API_KEY') or ''
    if not oai:
        for p in ('/home/pakar/mltest/.env', os.path.join(HERE, '../../.env')):
            try:
                for line in open(p):
                    m = re.match(r'OPENAI_API_KEY=(.+)', line.strip())
                    if m:
                        oai = m.group(1).strip().strip('"')
            except OSError:
                pass
    got, angles = 0, []
    for role, it in by_shop.get(shop, []):
        if got >= limit:
            break
        p = photo_of(it)
        if not p or 'thumbs' in p:
            continue
        try:
            res = ask_angle(p, oai)
        except Exception as e:  # noqa: BLE001 — интересует статистика, а не единичный сбой
            print(f'  {role}: ошибка {str(e)[:60]}')
            continue
        got += 1
        angles.append(res.get('yaw_deg', 0))
        print(f'  {role:12s} yaw {res.get("yaw_deg")}°  pitch {res.get("pitch_deg")}°  '
              f'{(it.get("name") or "")[:44]}')
    if angles:
        srt = sorted(angles)
        med = srt[len(srt) // 2]
        print(f'\n{shop}: замерено {len(angles)} фото · медиана yaw {med}° · '
              f'разброс {min(angles)}…{max(angles)}°')


if __name__ == '__main__':
    main()
