#!/usr/bin/env python3
"""Показать, КАК обрезается товар — настоящей вырезкой, взятой с ноды.

ЗАЧЕМ (владелец 01.09): «надо чтоб понимать, есть ли косяк, видеть, как обрезается».
Вырезка и есть вход генератора (ADR-0133): если она кривая, кривой будет и модель, а по
одному лишь вердикту («фото-коллаж») судить нельзя — надо смотреть.

ПОЧЕМУ ЧЕРЕЗ НОДУ. Веса модели вырезки живут внутри образа воркера (`/opt/weights/birefnet`),
на дев-машине их нет. Считать здесь «похожей» вырезкой другой реализации — значит показать
владельцу не то, что реально уходит в генератор. Поэтому гоняем на ноде и приносим картинку.

  ~/venvs/scout/bin/python cutout_probe.py --sku 99272:12780789729488032325
  ~/venvs/scout/bin/python cutout_probe.py --sku a:1,b:2 --out ~/scout-scenes/cutouts
"""
import base64
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ssh_run as S  # noqa: E402

OUT = os.path.expanduser('~/scout-scenes/cutout-probe')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

# Скрипт исполняется НА НОДЕ. Возвращает вырезку (и «вид формы» — то, что реально уходит
# в генератор) в base64 между маркерами, либо причину отказа.
REMOTE = r'''python - <<'RLPY'
import base64, io, json, sys
sys.path.insert(0, '/app')
import preprocess as PRE
from PIL import Image
out = {'ok': False}
imgs = {}
try:
    shape_img, cut_rgba, paint_img, sha, info = PRE.prepare(%(url)r, %(role)r)
    out = {'ok': True, 'sha': sha, 'verdict': 'принято',
           'info': {k: v for k, v in (info or {}).items()
                    if isinstance(v, (int, float, str, bool))}}
    imgs = {'cut': cut_rgba, 'shape': shape_img}
except Exception as e:
    out = {'ok': False, 'verdict': f'{type(e).__name__}: {str(e)[:300]}'}
    try:
        raw = Image.open(io.BytesIO(PRE.fetch(%(url)r))).convert('RGB')
        cut = PRE.defringe(PRE.cutout(raw))
        imgs = {'cut': PRE.trim_alpha(cut)}
        try:
            out['mask'] = {k: (round(v, 3) if isinstance(v, float) else v)
                           for k, v in (PRE.mask_verdict(cut) or {}).items()
                           if isinstance(v, (int, float, str, bool))}
        except Exception:
            pass
    except Exception as e2:
        out['fetch_error'] = f'{type(e2).__name__}: {str(e2)[:200]}'
for name, im in imgs.items():
    b = io.BytesIO(); im.save(b, 'PNG')
    out[name] = base64.b64encode(b.getvalue()).decode()
print('RLBEG' + json.dumps(out) + 'RLEND')
RLPY
exit
'''


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def probe(port: int, url: str, role: str) -> dict:
    txt = S.ssh_text(port, REMOTE % {'url': url, 'role': role}, timeout=300)
    m = re.search(r'RLBEG(\{.*?\})RLEND', txt or '', re.S)
    if not m:
        return {'ok': False, 'error': 'нет ответа с ноды: ' + (txt or '')[-160:]}
    return json.loads(m.group(1))


def main() -> None:
    skus = sys.argv[sys.argv.index('--sku') + 1].split(',')
    out_dir = (sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else OUT)
    os.makedirs(out_dir, exist_ok=True)

    rows = db("select shop_mid||':'||external_id, coalesce(name,''), coalesce(cat_role,''), "
              "coalesce(image_url_hd, image_url) from products where "
              "shop_mid||':'||external_id in (" + ','.join("'" + s + "'" for s in skus) + ");")
    info = {r[0]: {'name': r[1], 'role': r[2], 'url': r[3]} for r in rows}

    ports = [i['port'] for i in S.instances()]
    if not ports:
        sys.exit('нет живых нод — вырезку посчитать негде')

    results = []
    for i, sku in enumerate(skus):
        p = info.get(sku)
        if not p:
            print(f'  {sku}: нет в каталоге')
            continue
        port = ports[i % len(ports)]
        r = probe(port, p['url'], p['role'])
        slug = sku.replace(':', '_')
        files = {}
        for name in ('cut', 'shape'):
            if r.get(name):
                f = f'{slug}-{name}.png'
                open(os.path.join(out_dir, f), 'wb').write(base64.b64decode(r[name]))
                files[name] = f
        if r.get('ok'):
            print(f'  {sku} ({p["role"]}): вырезка принята')
        else:
            print(f'  {sku} ({p["role"]}): вердикт — {r.get("verdict")}'
                  + (' (картинка получена)' if r.get('cut') else ' (картинки нет)'))
        results.append({**p, 'sku': sku, 'files': files, 'info': r.get('info') or {},
                        'verdict': r.get('verdict'), 'mask': r.get('mask') or {},
                        'error': r.get('fetch_error')})

    html = ['<!doctype html><meta charset="utf-8"><title>Как обрезается</title>',
            '<style>body{font:14px/1.5 system-ui;margin:24px;background:#faf9f7}'
            '.card{background:#fff;border:1px solid #e5e2dc;border-radius:10px;padding:16px;'
            'margin:0 0 18px}.row{display:flex;gap:14px;flex-wrap:wrap}.row figure{margin:0;'
            'text-align:center}.row img{max-height:340px;border:1px solid #eee;border-radius:6px;'
            'background:repeating-conic-gradient(#f4f4f4 0% 25%,#fff 0% 50%) 50%/16px 16px}'
            'figcaption{font-size:12px;color:#666;margin-top:4px}.why{background:#fff4f0;'
            'border-left:3px solid #d9714e;padding:8px 12px;margin:8px 0;font-size:13px}'
            '.dim{color:#666;font-size:13px}</style>',
            '<h1>Как обрезается товар</h1>',
            '<p class="dim">Вырезка посчитана НА НОДЕ той же моделью, что работает в бою. '
            'Второй кадр — то, что реально уходит в генератор формы. Клетка = прозрачный фон.</p>']
    for c in results:
        html.append('<div class="card">')
        html.append(f'<b>{c["name"] or c["sku"]}</b> <span class="dim">— {c["role"]}</span>')
        if c.get('verdict') and c['verdict'] != 'принято':
            html.append(f'<div class="why">вердикт приёмки фото: {c["verdict"]}</div>')
        if c.get('mask'):
            html.append('<div class="dim">замеры маски: '
                        + ', '.join(f'{k}={v}' for k, v in c['mask'].items()) + '</div>')
        if c.get('error'):
            html.append(f'<div class="why">картинку получить не удалось: {c["error"]}</div>')
        html.append('<div class="row">')
        html.append(f'<figure><img src="{c["url"]}"><figcaption>исходное фото</figcaption></figure>')
        for name, cap in (('cut', 'вырезка'), ('shape', 'вход генератора формы')):
            f = (c.get('files') or {}).get(name)
            if f:
                html.append(f'<figure><img src="{f}"><figcaption>{cap}</figcaption></figure>')
        html.append('</div></div>')
    open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8').write('\n'.join(html))
    print(f'страница: {out_dir}/index.html')


if __name__ == '__main__':
    main()
