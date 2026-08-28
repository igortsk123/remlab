"""Прогон вырезальщиков по набору товаров. Один вариант = одна папка с RGBA-PNG.

Счётчик отказов обязателен, молчаливый except запрещён (правило владельца).
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SCOUT = '/home/pakar/igor/remlab/tools/scout'

VARIANTS = {
    # как сейчас в проде: birefnet/v2 с дефолтами == локальный BiRefNet в образе Salad
    'A-now':      ('fal-ai/birefnet/v2', {}),
    'B-heavy2k':  ('fal-ai/birefnet/v2', {'model': 'General Use (Heavy)',
                                          'operating_resolution': '2048x2048',
                                          'refine_foreground': True}),
    'C-matte2k':  ('fal-ai/birefnet/v2', {'model': 'Matting',
                                          'operating_resolution': '2048x2048',
                                          'refine_foreground': True}),
    'D-bria2':    ('fal-ai/bria/background/remove', {}),
}


def fal_key():
    for line in open(os.path.join(SCOUT, '.env')):
        m = re.match(r'FAL_KEY=(.+)', line.strip())
        if m:
            return m.group(1)
    raise SystemExit('нет FAL_KEY')


KEY = fal_key()


def data_uri(path):
    with open(path, 'rb') as f:
        return 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode()


def fal_run(model, payload, timeout=300):
    req = urllib.request.Request(
        f'https://queue.fal.run/{model}', method='POST',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Key {KEY}', 'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    status_url, resp_url = r['status_url'], r['response_url']
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        s = json.loads(urllib.request.urlopen(urllib.request.Request(
            status_url, headers={'Authorization': f'Key {KEY}'}), timeout=60).read())
        if s.get('status') == 'COMPLETED':
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                resp_url, headers={'Authorization': f'Key {KEY}'}), timeout=120).read())
        if s.get('status') in ('FAILED', 'ERROR'):
            raise RuntimeError(f'fal {s.get("status")}: {str(s)[:200]}')
    raise TimeoutError('fal не ответил за %ss' % timeout)


def one(variant, item):
    model, extra = VARIANTS[variant]
    dst = os.path.join(ROOT, variant, item['id'] + '.png')
    if os.path.exists(dst):
        return 'cached'
    src = os.path.join(ROOT, 'src', item['id'] + '.jpg')
    res = fal_run(model, {'image_url': data_uri(src), **extra})
    url = ((res.get('image') or {}).get('url')
           or (res.get('images') or [{}])[0].get('url'))
    if not url:
        raise RuntimeError('в ответе нет картинки: ' + str(res)[:200])
    raw = urllib.request.urlopen(url, timeout=180).read()
    img = Image.open(io.BytesIO(raw)).convert('RGBA')
    src_im = Image.open(src)
    if img.size != src_im.size:                 # у части моделей выход отмасштабирован
        img = img.resize(src_im.size, Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    img.save(dst)
    return 'ok'


def main():
    variants = sys.argv[1].split(',')
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    items = json.load(open(os.path.join(ROOT, 'set.json')))
    if limit:
        items = items[:limit]
    for v in variants:
        stat = {'ok': 0, 'cached': 0, 'fail': 0}
        errs = []

        def work(it):
            try:
                return one(v, it), None
            except Exception as e:                      # noqa: BLE001 — считаем и печатаем
                return 'fail', f'{it["id"]}: {type(e).__name__}: {str(e)[:120]}'

        with ThreadPoolExecutor(max_workers=4) as ex:
            for st, err in ex.map(work, items):
                stat[st] += 1
                if err:
                    errs.append(err)
        print(f'{v}: ok={stat["ok"]} cached={stat["cached"]} fail={stat["fail"]}')
        for e in errs[:10]:
            print('   ✗', e)


if __name__ == '__main__':
    main()
