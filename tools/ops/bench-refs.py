#!/usr/bin/env python3
"""A/B РЕФЕРЕНСОВ ТОВАРОВ В «СДЕЛАТЬ РЕАЛИСТИЧНЕЕ» (план demo-14, протокол Codex 17.10): один лист Сканди из кадров браузера,
baseline (ровно то, что ушло в модель на проде) + пять вариантов, каждый меняет РОВНО одно:
  locator  — второй лист: те же виды с контурами и «#N роль» на мебели, без заливки (карта соответствий)
  photos   — отдельная картинка на товар (фото магазина без фона, 1024×1024, подпись полосой) вместо коллажа
  hires    — тот же коллаж, но из крупных фото без фона (не уменьшенных до 480×380)
  json     — в промпте список товаров: номер, роль, название, материал, цвет словами, измеренный тон и уверенность
  matrix   — начало промпта: короткая матрица источников и приоритетов (что берётся откуда)
Верность цвета — `tools/scout/refs_check.py` (ΔE00 по карте предметов позы). Страница — `/test/share/refs-check/`.

    ~/venvs/scout/bin/python tools/ops/bench-refs.py --src improve-210440 --shot improve-210510           # сухой: собрать входы, замерить baseline
    ~/venvs/scout/bin/python tools/ops/bench-refs.py --src improve-210440 --shot improve-210510 --go      # + 5 платных прогонов (~5.5 ¢ каждый)
    ~/venvs/scout/bin/python tools/ops/bench-refs.py --page                                               # собрать и выложить страницу
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
SCOUT = os.path.join(ROOT, 'tools', 'scout')
sys.path.insert(0, SCOUT)
import refs_check as RC  # noqa: E402

OUT = os.path.expanduser('~/scout-scenes/bench-refs')
SRC_DIR = os.path.expanduser('~/scout-scenes/src')
DEMO = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
BASE = 'https://remont-lab.online'
MODEL = 'openai/gpt-image-2.5-sunburst'
VARIANTS = ['baseline', 'locator', 'photos', 'hires', 'json', 'matrix', 'json2', 'combo', 'v4base', 'neutral', 'neutral2']
# json2 — повтор победителя (шум), combo — json + фото + locator; v4base/neutral/neutral2 — A/B «нейтральные серые не утеплять» поверх v4
NEUTRAL_RULE = ('Keep neutral and cool product colours neutral: grey, blue-grey and white upholstery, rugs and finishes must stay the same hue '
                'as in their references; warm daylight may warm highlights and walls, but must not tint products beige or brown.')
MATERIALS = [('рогожк', 'woven matting fabric'), ('шенилл', 'chenille'), ('велюр', 'velour'), ('букле', 'bouclé'), ('вельвет', 'corduroy'),
             ('экокож', 'faux leather'), ('кож', 'leather'), ('лён', 'linen'), ('шерст', 'wool'), ('хлоп', 'cotton'), ('дуб', 'oak'),
             ('орех', 'walnut'), ('ясень', 'ash'), ('сосн', 'pine'), ('древесн', 'wood'), ('дерев', 'wood'), ('металл', 'metal'),
             ('стекл', 'glass'), ('мрамор', 'marble'), ('ротанг', 'rattan'), ('лдсп', 'laminated board'), ('мдф', 'MDF')]


def db(sql: str) -> list:
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-At', '-F', '\x1f', '-q'],
                       capture_output=True, text=True, input=sql)
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def shot_record(shot: str) -> dict:
    reg = json.loads(urllib.request.urlopen(f'{BASE}/test/share/shots.json?v={int(time.time())}', timeout=30).read())
    return next(x for x in reg if any(shot in s.get('url', '') for s in x.get('shots', [])))


def variant_items(style: str) -> tuple:
    D = json.load(open(DEMO, encoding='utf-8'))
    v = next(x for x in D['variants'] if x['style'] == style)
    items = []
    for it in v['items']:
        sku = it.get('sku') or {}
        sid = sku.get('sid') or ''
        url = None
        if '_' in sid:
            mid, eid = sid.split('_', 1)
            r = db(f"select coalesce(image_url_hd, image_url) from products where shop_mid={int(mid)} and external_id='{eid}'")
            url = r[0][0] if r and r[0] else None
        items.append({**it, 'x': +it['x'], 'y': +it['y'], 'w': +it['w'], 'd': +it['d'], 'rot': +it.get('rot') or 0,
                      'sku_name': sku.get('name') or '', 'img_url': url})
    return D['room'], items


def cutout_square(im: Image.Image, side: int = 1024, margin: float = 0.07) -> Image.Image:
    """Фото товара без фона, вписанное в квадрат на белом с полем (Codex п.3: не резать до 640, фон — прочь)."""
    m = RC.fg_mask(im)
    ys, xs = np.where(m)
    if len(xs):
        im = im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        mk = Image.fromarray((m[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1] * 255).astype(np.uint8))
    else:
        mk = Image.new('L', im.size, 255)
    inner = int(side * (1 - 2 * margin))
    k = min(inner / im.width, inner / im.height)
    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    mk = mk.resize(im.size, Image.LANCZOS)
    sq = Image.new('RGB', (side, side), (255, 255, 255))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), mk)
    return sq


def caption(im: Image.Image, text: str) -> Image.Image:
    """Узкая белая полоса с подписью «#N роль» под фото (Codex: подпись не поверх товара)."""
    import draft_render as DR
    out = Image.new('RGB', (im.width, im.height + 64), (255, 255, 255))
    out.paste(im, (0, 0))
    ImageDraw.Draw(out).text((24, im.height + 12), text, fill=(20, 20, 20), font=DR._font(36))
    return out


def products(items: list) -> list:
    """Уникальные товары (комплект из двух одинаковых стульев — одна позиция с двумя номерами), ковёр и всё с фото."""
    out, seen = [], {}
    for i, it in enumerate(items):
        key = it['sku_name'] or it['role']
        if key in seen:
            seen[key]['nums'].append(i + 1)
            continue
        p = {'nums': [i + 1], 'role': RC.base_role(it['role']), 'name': it['sku_name'], 'img_url': it.get('img_url')}
        seen[key] = p
        out.append(p)
    return out


def material_of(name: str) -> str | None:
    low = (name or '').lower()
    return next((en for ru, en in MATERIALS if ru in low), None)


def locator(sheet: Image.Image, views: list, masks: np.ndarray, items: list) -> Image.Image:
    """Тот же лист с контурами предметов и крупными «#N роль» — без заливки (Codex п.1: карта соответствий, не новая картинка)."""
    import cv2
    import draft_render as DR
    out = sheet.copy()
    d = ImageDraw.Draw(out)
    f = DR._font(44)
    for k, (_, box) in enumerate(views):
        x0, y0, x1, y1 = box
        mk = cv2.resize(masks[k].astype(np.int16), (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
        for i, it in enumerate(items):
            m = (mk == i).astype(np.uint8)
            if m.sum() < 400:
                continue
            cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                pts = [(int(p[0][0]) + x0, int(p[0][1]) + y0) for p in c]
                if len(pts) > 2:
                    d.line(pts + [pts[0]], fill=(0, 0, 0), width=7)
                    d.line(pts + [pts[0]], fill=(255, 255, 0), width=3)
            ys, xs = np.where(m)
            cx, cy = int(np.median(xs)) + x0, int(np.median(ys)) + y0
            lab = f'#{i + 1} {RC.base_role(it["role"])}'
            tw = d.textlength(lab, font=f)
            d.rectangle([cx - tw / 2 - 10, cy - 30, cx + tw / 2 + 10, cy + 30], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
            d.text((cx, cy), lab, fill=(0, 0, 0), font=f, anchor='mm')
    return out


def hires_collage(prods: list, photos: dict) -> Image.Image:
    """Коллаж той же раскладки (3 колонки), но из крупных фото без фона — меняется ТОЛЬКО качество эталона."""
    import draft_render as DR
    cols, cw = 3, 700
    rows = (len(prods) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cw, rows * (cw + 90)), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(prods):
        x, y = (i % cols) * cw, (i // cols) * (cw + 90)
        im = photos.get(p['name'])
        if im is not None:
            sheet.paste(cutout_square(im, cw - 20), (x + 10, y + 10))
        d.text((x + 20, y + cw + 10), (', '.join(f'#{n}' for n in p['nums']) + f' {p["role"]}')[:40], fill=(20, 20, 20), font=DR._font(34))
    return sheet


def product_json(prods: list, refs: dict) -> list:
    import draft_render as DR
    out = []
    for p in prods:
        r = refs.get(p['name']) or {}
        out.append({'id': p['nums'], 'role': p['role'], 'name': p['name'], 'material': material_of(p['name']),
                    'colour_name': DR._colour_from_name(p['name']), 'colour_hex': r.get('hex'), 'confidence': r.get('confidence')})
    return out


def prompt_variant(base: str, kind: str, prods: list, refs: dict, n_photo_imgs: int = 0) -> str:
    p = base
    if kind == 'locator':
        p = p.replace('You are given TWO images:', 'You are given THREE images:', 1)
        p = p.replace('* IMAGE 2: catalogue references for all real products already placed in the room.',
                      '* IMAGE 2: LOCATOR — the same two views with a numbered outline "#N role" on each product. Use it ONLY to learn which '
                      'number sits on which object; never draw the numbers, outlines or labels.\n'
                      '* IMAGE 3: catalogue references for all real products already placed in the room, labelled with the same numbers.', 1)
        p = p.replace('IMAGE 2 controls only the COLOUR', 'IMAGE 3 controls only the COLOUR', 1).replace('from IMAGE 2.', 'from IMAGE 3.')
    elif kind == 'photos':
        lines = []
        for j, pr in enumerate(prods):
            lines.append(f'* IMAGE {j + 2}: product {", ".join("#" + str(n) for n in pr["nums"])} ({pr["role"]}, "{pr["name"]}") — '
                         'its exact colour, fabric weave and finish.')
        p = p.replace('You are given TWO images:', f'You are given {1 + len(prods)} images:', 1)
        p = p.replace('* IMAGE 2: catalogue references for all real products already placed in the room.', '\n'.join(lines), 1)
        p = p.replace('IMAGE 2 controls only the COLOUR', f'IMAGES 2–{1 + len(prods)} control only the COLOUR', 1).replace('from IMAGE 2.', 'from its product image.')
    elif kind == 'json':
        js = json.dumps(product_json(prods, refs), ensure_ascii=False)
        p = p.replace('Ignore catalogue backgrounds, text, logos and watermarks.',
                      'Ignore catalogue backgrounds, text, logos and watermarks.\n\nPRODUCT LIST (numbers as on IMAGE 2; colour_hex is the base tone '
                      'measured on the product photo, not an exact RGB under any light):\n' + js, 1)
    elif kind == 'matrix':
        head = ('SOURCES AND PRIORITIES (read first):\n'
                '* Geometry, cameras, positions, sizes, silhouettes, counts, openings and the magenta band — ONLY from IMAGE 1.\n'
                '* Colour, material, fabric and finish of every product — from its catalogue reference on IMAGE 2; if IMAGE 1 shows a '
                'product with a wrong tint, texture or artefacts, trust IMAGE 2 and repaint that product\'s surface to match it exactly '
                '(hue, saturation, weave, wood grain), keeping the IMAGE 1 silhouette and position.\n'
                '* Finishes of walls, floor and ceiling — from the STYLE GUIDE below.\n\n')
        p = head + p
    return p


def neutral_prompt(p: str) -> str:
    """Правило «нейтральные серые не утеплять» — сразу после PHOTOGRAPHIC LOOK (меняется ровно одно относительно v4)."""
    i = p.index('no oversaturation.') + len('no oversaturation.')
    return p[:i] + ' ' + NEUTRAL_RULE + p[i:]


def combo_prompt(base: str, prods: list, refs: dict) -> str:
    """Сочетание лучших по одному: locator (IMAGE 2) + отдельные фото товаров (IMAGE 3…) + список товаров JSON."""
    lines = [f'* IMAGE {j + 3}: product {", ".join("#" + str(n) for n in pr["nums"])} ({pr["role"]}, "{pr["name"]}") — its exact colour, fabric '
             'weave and finish.' for j, pr in enumerate(prods)]
    p = base.replace('You are given TWO images:', f'You are given {2 + len(prods)} images:', 1)
    p = p.replace('* IMAGE 2: catalogue references for all real products already placed in the room.',
                  '* IMAGE 2: LOCATOR — the same two views with a numbered outline "#N role" on each product. Use it ONLY to learn which number '
                  'sits on which object; never draw the numbers, outlines or labels.\n' + '\n'.join(lines), 1)
    p = p.replace('IMAGE 2 controls only the COLOUR', f'IMAGES 3–{2 + len(prods)} control only the COLOUR', 1).replace('from IMAGE 2.', 'from its product image.')
    js = json.dumps(product_json(prods, refs), ensure_ascii=False)
    return p.replace('Ignore catalogue backgrounds, text, logos and watermarks.',
                     'Ignore catalogue backgrounds, text, logos and watermarks.\n\nPRODUCT LIST (numbers as on IMAGE 2; colour_hex is the base tone '
                     'measured on the product photo, not an exact RGB under any light):\n' + js, 1)


def build(src: str, shot: str) -> dict:
    """Входы всех вариантов + baseline-замер (по уже снятому фото того же листа) — бесплатно."""
    os.makedirs(OUT, exist_ok=True)
    rec = shot_record(shot)
    style = rec.get('style')
    room, items = variant_items(style)
    sdir = os.path.join(SRC_DIR, src)
    sheet = Image.open(os.path.join(sdir, '1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg')).convert('RGB')
    collage = Image.open(os.path.join(sdir, '2-ОТПРАВЛЯЕМ-эталоны-товаров.jpg')).convert('RGB')
    base_prompt = open(os.path.join(sdir, 'prompt.txt'), encoding='utf-8').read()
    views = RC.split_sheet(sheet)
    vw = views[0][1][2] - views[0][1][0]
    vh = views[0][1][3] - views[0][1][1]
    cams = rec['cams']
    masks, solo = RC.item_masks(room, items, cams, vw, vh)
    prods = products(items)
    photos, refs = {}, {}
    for p in prods:
        if p.get('img_url'):
            try:
                photos[p['name']] = RC.fetch(p['img_url'])
            except Exception as e:  # noqa: BLE001
                print(f'  фото не скачалось: {p["name"][:40]} — {str(e)[:60]}')
                continue
            refs[p['name']] = RC.ref_colour(photos[p['name']])
    for it in items:
        it['ref_key'] = it['sku_name']
    loc = locator(sheet, views, masks, items)
    hc = hires_collage(prods, photos)
    singles = [caption(cutout_square(photos[p['name']]), f'{", ".join("#" + str(n) for n in p["nums"])} {p["role"]}')
               for p in prods if p['name'] in photos]
    inputs = {
        'baseline': ([sheet, collage], base_prompt),
        'locator': ([sheet, loc, collage], prompt_variant(base_prompt, 'locator', prods, refs)),
        'photos': ([sheet] + singles, prompt_variant(base_prompt, 'photos', [p for p in prods if p['name'] in photos], refs)),
        'hires': ([sheet, hc], base_prompt),
        'json': ([sheet, collage], prompt_variant(base_prompt, 'json', prods, refs)),
        'matrix': ([sheet, collage], prompt_variant(base_prompt, 'matrix', prods, refs)),
        'json2': ([sheet, collage], prompt_variant(base_prompt, 'json', prods, refs)),
        'combo': ([sheet, loc] + singles, combo_prompt(base_prompt, [p for p in prods if p['name'] in photos], refs)),
        'v4base': ([sheet, collage], prompt_variant(base_prompt, 'json', prods, refs)),
        'neutral': ([sheet, collage], neutral_prompt(prompt_variant(base_prompt, 'json', prods, refs))),
        'neutral2': ([sheet, collage], neutral_prompt(prompt_variant(base_prompt, 'json', prods, refs))),
    }
    for k, (imgs, pr) in inputs.items():
        d = os.path.join(OUT, k)
        os.makedirs(d, exist_ok=True)
        for j, im in enumerate(imgs):
            im.save(os.path.join(d, f'in-{j + 1}.jpg'), quality=90)
        open(os.path.join(d, 'prompt.txt'), 'w', encoding='utf-8').write(pr)
    # baseline — фото, уже снятое на проде из этих же входов (кадры C1/C2)
    base_views = [RC.fetch(s['url']) for s in rec['shots'][:2]]
    for j, v in enumerate(base_views):
        v.save(os.path.join(OUT, 'baseline', f'out-C{j + 1}.jpg'), quality=90)
    np.save(os.path.join(OUT, 'masks.npy'), masks)
    json.dump(solo, open(os.path.join(OUT, 'solo.json'), 'w'))
    prev = json.load(open(os.path.join(OUT, 'state.json'), encoding='utf-8')).get('runs', {}) if os.path.exists(os.path.join(OUT, 'state.json')) else {}
    state = {'src': src, 'shot': shot, 'style': style, 'cams': cams, 'items': [{k: it[k] for k in ('role', 'sku_name')} for it in items],
             'refs': {k: {'hex': v.get('hex'), 'confidence': v.get('confidence')} for k, v in refs.items()},
             'products': [{k: p[k] for k in ('nums', 'role', 'name')} for p in prods], 'runs': {}}
    rows = RC.measure(base_views, masks, items, refs, solo)
    state['runs'] = {k: v for k, v in prev.items() if k != 'baseline'}
    state['runs']['baseline'] = {'rows': rows, 'summary': RC.summary(rows), 'out': shot, 'paid': False}
    json.dump(state, open(os.path.join(OUT, 'state.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'входы собраны: {OUT}; товаров с фото {len(photos)} из {len(prods)}; baseline: {RC.summary(rows)}')
    return {'state': state, 'inputs': inputs, 'masks': masks, 'solo': solo, 'items': items, 'refs': refs}


def run(built: dict, only: list) -> None:
    import draft_render as DR
    st, masks, items, refs = built['state'], built['masks'], built['items'], built['refs']
    for k in [x for x in VARIANTS if x != 'baseline' and (not only or x in only)]:
        imgs, pr = built['inputs'][k]
        t0 = time.time()
        try:
            out = DR.gpt_edit(imgs, pr, size='2048x3072', quality='medium', model=MODEL)
        except Exception as e:  # noqa: BLE001 — один вариант не валит остальные, но громко
            print(f'  {k}: ОШИБКА {str(e)[:160]}', flush=True)
            st['runs'][k] = {'error': str(e)[:300], 'paid': True}
            continue
        sec = round(time.time() - t0, 1)
        out.save(os.path.join(OUT, k, 'out-sheet.jpg'), quality=90)
        vs = RC.views_of(out)
        for j, v in enumerate(vs):
            v.save(os.path.join(OUT, k, f'out-C{j + 1}.jpg'), quality=90)
        rows = RC.measure(vs, masks, items, refs, built['solo'])
        st['runs'][k] = {'rows': rows, 'summary': RC.summary(rows), 'sec': sec, 'paid': True, 'inputs': len(imgs)}
        json.dump(st, open(os.path.join(OUT, 'state.json'), 'w'), ensure_ascii=False, indent=1)
        print(f'  {k}: {sec} с, входов {len(imgs)} · {RC.summary(rows)}', flush=True)


def page() -> int:
    import html as H
    st = json.load(open(os.path.join(OUT, 'state.json'), encoding='utf-8'))
    names = {p['name']: p for p in st['products']}
    head = ''.join(f'<th>{H.escape(k)}</th>' for k in VARIANTS)
    # таблица ΔE по товару: лучший из двух видов
    body = ''
    for p in st['products']:
        cells = ''
        for k in VARIANTS:
            rows = [r for r in (st['runs'].get(k) or {}).get('rows') or [] if r['n'] in p['nums']]
            if not rows:
                cells += '<td class=na>—</td>'
                continue
            r = min(rows, key=lambda x: x['de'])
            cells += (f'<td class={r["verdict"]}><b>{r["de"]}</b><br><span class=sw style="background:{r["out_hex"]}"></span>'
                      f'<span class=sw style="background:{r["ref_hex"]}"></span></td>')
        body += f'<tr><td>{", ".join("#" + str(n) for n in p["nums"])} {H.escape(p["role"])}<br><small>{H.escape(p["name"][:46])}</small></td>{cells}</tr>'
    summ = ''.join(f'<td>{(st["runs"].get(k) or {}).get("summary", {}).get("mean_de", "—")}<br><small>ок {(st["runs"].get(k) or {}).get("summary", {}).get("ok", "—")}'
                   f' из {(st["runs"].get(k) or {}).get("summary", {}).get("items", "—")}</small></td>' for k in VARIANTS)
    secs = ''.join(f'<td>{(st["runs"].get(k) or {}).get("sec", "—")}</td>' for k in VARIANTS)
    gal = ''
    for k in VARIANTS:
        d = os.path.join(OUT, k)
        outs = sorted(f for f in os.listdir(d) if f.startswith('out-C')) if os.path.isdir(d) else []
        ins = sorted(f for f in os.listdir(d) if f.startswith('in-')) if os.path.isdir(d) else []
        gal += (f'<section><h3>{k}</h3><div class=row>' + ''.join(f'<a href="{k}/{f}" target=_blank><img src="{k}/{f}" loading=lazy></a>' for f in outs)
                + '</div><details><summary>что ушло в модель</summary><div class=row>'
                + ''.join(f'<a href="{k}/{f}" target=_blank><img class=in src="{k}/{f}" loading=lazy></a>' for f in ins)
                + f'</div><p><a href="{k}/prompt.txt" target=_blank>промпт</a></p></details></section>')
    out = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Верность цвета товаров</title><style>:root{--ink:#2b2622;--muted:#6f665e;--line:#e6dfd6;--bg:#faf7f2;--card:#fff}'
           '@media(prefers-color-scheme:dark){:root{--ink:#eee7df;--muted:#b3a99e;--line:#3a332d;--bg:#1d1a17;--card:#26221e}}'
           'body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}'
           '.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card)}td,th{border:1px solid var(--line);padding:6px 8px;text-align:center;vertical-align:top}'
           'td:first-child{text-align:left}.ok{background:#e3f4e1}.warn{background:#fdf1d6}.fail{background:#f9dcdc}.na{color:var(--muted)}'
           '@media(prefers-color-scheme:dark){.ok{background:#1f3a22}.warn{background:#3d3418}.fail{background:#3f1f1f}}'
           '.sw{display:inline-block;width:18px;height:12px;border:1px solid #0003;margin:2px}.row{display:flex;gap:8px;flex-wrap:wrap}'
           '.row img{width:min(360px,100%);border-radius:8px}.row img.in{width:min(220px,46%)}section{margin:18px 0}small{color:var(--muted)}</style></head><body><main>'
           f'<h1>Верность цвета товаров на фото нейросети</h1><p>Лист {H.escape(st["style"])} (кадры браузера, исходник {H.escape(st["src"])}). '
           'В ячейке — ΔE00 (меньше — ближе к фото магазина; ≤ 8 зелёный, ≤ 12 жёлтый), лучший из двух видов; квадратики — цвет на фото нейросети и '
           'основной тон фото товара. Каждый вариант меняет ровно одно относительно baseline.</p>'
           f'<div class=tw><table><tr><th>товар</th>{head}</tr>{body}<tr><td><b>средний ΔE00</b></td>{summ}</tr><tr><td>время модели, с</td>{secs}</tr></table></div>'
           + gal + '</main></body></html>')
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(out)
    subprocess.run(['ssh', '-o', 'BatchMode=yes', 'root@89.167.127.0', 'mkdir -p /opt/remlab/test/share/refs-check'], check=True)
    subprocess.run(['bash', '-c', f'cd "{OUT}" && tar cf - index.html */*.jpg */*.txt | ssh -o BatchMode=yes root@89.167.127.0 "tar xf - -C /opt/remlab/test/share/refs-check"'], check=True)
    print('выложено: https://remont-lab.online/test/share/refs-check/')
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--page' in a:
        sys.exit(page())
    src = a[a.index('--src') + 1]
    shot = a[a.index('--shot') + 1]
    b = build(src, shot)
    if '--go' in a:
        only = a[a.index('--only') + 1].split(',') if '--only' in a else []
        run(b, only)
