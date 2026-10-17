#!/usr/bin/env python3
"""Проход 2 сравнения моделей (17.10): Google-модели в полном разрешении (providerOptions.google.imageConfig 2K, 2:3)
и FLUX 3 Image («пиксельные правки») через /v1/images/edits JSON. Тот же лист и промпт, что у боевого режима.
ПЛАТНО. Запуск: ~/venvs/scout/bin/python tools/ops/bench-realistic2.py <payload.json> <out_dir> [model ...]
"""
import base64
import io
import json
import os
import sys
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..', 'scout')
sys.path.insert(0, SCOUT)
os.chdir(SCOUT)
import draft_render as DR  # noqa: E402
from PIL import Image  # noqa: E402

DEFAULT = ['google/gemini-nano-banana-2.1', 'google/gemini-3-pro-image', 'google/gemini-3.1-flash-image', 'bfl/flux-3-image']
EDITS = 'https://ai-gateway.vercel.sh/v1/images/edits'
LAST = {}


def _data_url(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.convert('RGB').save(buf, 'JPEG', quality=92)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + DR.gw_key(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=DR._GW_TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        txt = e.read().decode('utf-8', 'replace')[:500]
        raise RuntimeError(f'HTTP {e.code}: {txt}') from None


def edit_any(images, prompt, size='2048x3072', quality='medium', model='', mask=None):
    """Замена DR.gpt_edit на время бенча: Google — chat с providerOptions (2K, 2:3), при отказе — /images/edits JSON;
    BFL — /images/edits JSON с несколькими картинками."""
    t0 = time.time()
    if model.startswith('openai/'):
        return DR.gpt_edit.__wrapped__(images, prompt, size=size, quality=quality, model=model, mask=mask)
    po = {'google': {'imageConfig': {'imageSize': '2K', 'aspectRatio': '2:3'}}} if model.startswith('google/') else \
         {'blackForestLabs': {'outputFormat': 'jpeg'}}
    im = None
    if model.startswith('google/'):
        parts = [{'type': 'text', 'text': prompt}] + [{'type': 'image_url', 'image_url': {'url': _data_url(x)}} for x in images]
        body = {'model': model, 'messages': [{'role': 'user', 'content': parts}], 'modalities': ['image', 'text'],
                'providerOptions': po}
        try:
            j = _post(DR.CHAT_URL, body)
            msg = (j.get('choices') or [{}])[0].get('message') or {}
            for x in (msg.get('images') or []):
                u = (x.get('image_url') or {}).get('url', '') if isinstance(x, dict) else ''
                if u.startswith('data:'):
                    im = Image.open(io.BytesIO(base64.b64decode(u.split(',', 1)[1]))).convert('RGB')
                    LAST['path'] = 'chat+providerOptions'
                    break
            if im is None:
                raise RuntimeError('chat без картинки: ' + json.dumps(j)[:200])
        except Exception as e:  # noqa: BLE001
            print('chat-путь не вышел:', str(e)[:200], '→ пробую /images/edits', flush=True)
    if im is None:
        body = {'model': model, 'prompt': prompt, 'images': [{'image_url': _data_url(x)} for x in images],
                'response_format': 'b64_json', 'providerOptions': po}
        if model.startswith('google/'):
            body['providerOptions'] = {'google': {'imageConfig': {'imageSize': '2K', 'aspectRatio': '2:3'}}}
        j = _post(EDITS, body)
        d = (j.get('data') or [{}])[0]
        if d.get('b64_json'):
            im = Image.open(io.BytesIO(base64.b64decode(d['b64_json']))).convert('RGB')
        elif d.get('url'):
            with urllib.request.urlopen(d['url'], timeout=120) as r:
                im = Image.open(io.BytesIO(r.read())).convert('RGB')
        else:
            raise RuntimeError('edits без картинки: ' + json.dumps(j)[:300])
        LAST['path'] = 'images/edits'
    LAST['model_s'] = round(time.time() - t0, 1)
    LAST['sheet'] = im.size
    print(f'модель {model}: {LAST["model_s"]} с, лист {im.size}, путь {LAST["path"]}', flush=True)
    return im


def main():
    payload = json.load(open(sys.argv[1], encoding='utf-8'))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    models = sys.argv[3:] or DEFAULT
    orig = DR.gpt_edit
    edit_any.__wrapped__ = orig  # noqa
    orig.__wrapped__ = orig
    DR.gpt_edit = edit_any
    rows = []
    for m in models:
        DR.REALISTIC_MODEL = m
        LAST.clear()
        bal0 = DR.gw_credits(max_age_s=0)
        t0 = time.time()
        row = {'model': m, 'pass': 2, 'balance_before': bal0}
        try:
            res = DR.render(layout=payload, quality='realistic', save_prefix=os.path.join(out, m.replace('/', '_')))
            row.update({'ok': True, 'total_s': round(time.time() - t0, 1), 'shots': [s.get('url') for s in res.get('shots', [])]})
        except BaseException as e:  # noqa: BLE001
            row.update({'ok': False, 'total_s': round(time.time() - t0, 1), 'error': str(e)[:300]})
            traceback.print_exc()
        row.update(LAST)
        time.sleep(20)                      # баланс шлюза отстаёт
        bal1 = DR.gw_credits(max_age_s=0)
        row['balance_after'] = bal1
        row['cost_usd'] = round(bal0 - bal1, 4) if isinstance(bal0, (int, float)) and isinstance(bal1, (int, float)) else None
        rows.append(row)
        print('РЕЗУЛЬТАТ', json.dumps(row, ensure_ascii=False), flush=True)
        json.dump(rows, open(os.path.join(out, 'bench2.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
