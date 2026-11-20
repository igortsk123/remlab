#!/usr/bin/env python3
"""Страница-просмотр «30 товаров: исходное фото ↔ вырезка последней версии на фиолетовом» (T-20261119-104/4, владелец TG 2262).

Набор — ровно `set30.json`; SKU, которого нет среди вырезанных (`products.json` прогона), заменяется товаром ТОЙ ЖЕ роли, выбор детерминированный
(первый по sha1(sku) среди ещё не взятых; подпись «замена»). Платно ничего не режет: берёт готовые `cut/<sha>.png` прогона. Конвейер не меняет.

  python tools/scout/cutout_page30.py --run 1119-a [--set ~/remlab-logs/mesh-models-1118/trellis/set30.json] [--notes notes30.json] [--out DIR]

Пишет в DIR: `index.html`, `img/NN-photo.webp`, `img/NN-cut.webp` (вырезка на фиолетовом, тот же масштаб, что у фото), `data.json` (номера, остатки, замены).
Остатки: связные компоненты маски (alpha>127, 8-связность) кроме главной, площадью ≥ 0,05 % кадра; доля — от площади всего товара."""
import argparse
import hashlib
import html
import json
import os
import statistics
import time

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = os.path.expanduser('~/remlab-logs/t104-1119')
PURPLE = (138, 43, 226)
MAXW = 1600
MIN_SHARE = 0.0005   # 0,05 % кадра
VERDICT_RU = {'ok': 'ok', 'photo_too_small': 'мелкое фото', 'collage': 'коллаж'}


def residues(alpha: np.ndarray, frame_px: float) -> dict:
    fg = alpha > 127
    lab, n = ndi.label(fg, structure=np.ones((3, 3), int))
    if n == 0:
        return {'pieces': 0, 'share': 0.0, 'total': 0}
    sizes = ndi.sum(fg, lab, index=range(1, n + 1))
    main = int(np.argmax(sizes))
    rest = [s for i, s in enumerate(sizes) if i != main and s >= MIN_SHARE * frame_px]
    total = float(sizes.sum())
    return {'pieces': len(rest), 'share': round(100.0 * float(sum(rest)) / max(1.0, total), 2), 'total': int(total)}


def fit(im: Image.Image) -> Image.Image:
    if im.width > MAXW:
        im = im.resize((MAXW, max(1, round(im.height * MAXW / im.width))), Image.LANCZOS)
    return im


def pick(set30: list, rows: dict, last: dict) -> list:
    used = {x['sku'] for x in set30 if x['sku'] in rows and x['sku'] in last}
    used_sha = {last[s]['sha'] for s in used}
    out = []
    for x in set30:
        sku = x['sku']
        if sku in rows and sku in last:
            out.append({**x, 'use': sku, 'replaced': False})
            continue
        cands = sorted((s for s, r in rows.items() if r['role'] == x['role'] and s in last and last[s].get('status') == 'ok' and s not in used
                        and last[s]['sha'] not in used_sha), key=lambda s: hashlib.sha1(s.encode()).hexdigest())
        if not cands:
            raise SystemExit(f'нет замены для {sku} ({x["role"]})')
        s = cands[0]
        used.add(s)
        used_sha.add(last[s]['sha'])
        out.append({**x, 'use': s, 'replaced': True})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--set', default=os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis/set30.json'))
    ap.add_argument('--notes', default='')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    d = os.path.join(ROOT, a.run)
    out = a.out or os.path.expanduser('~/remlab-logs/t104-1120/page30-' + time.strftime('%H%M') + '/site')
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    rows = {r['sku']: r for r in json.load(open(os.path.join(d, 'products.json'), encoding='utf-8'))}
    last = {}
    for line in open(os.path.join(d, 'chain.jsonl'), encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        last[r['sku']] = r
    notes = json.load(open(a.notes, encoding='utf-8')) if a.notes else {}
    items = pick(json.load(open(a.set, encoding='utf-8')), rows, last)
    data = []
    for i, it in enumerate(items, 1):
        sku = it['use']
        r, c = rows[sku], last[sku]
        sha = c['sha']
        photo = Image.open(os.path.join(d, 'photos', sha + '.img')).convert('RGB')
        cut = Image.open(os.path.join(d, 'cut', sha + '.png')).convert('RGBA')
        cv = Image.new('RGB', photo.size, PURPLE)
        cv.paste(cut, ((photo.width - cut.width) // 2, (photo.height - cut.height) // 2), cut)
        fit(photo).save(os.path.join(out, 'img', f'{i:02d}-photo.webp'), quality=88)
        fit(cv).save(os.path.join(out, 'img', f'{i:02d}-cut.webp'), quality=88)
        res = residues(np.asarray(cut)[..., 3], photo.width * photo.height)
        data.append({'n': i, 'sku': sku, 'role': r['role'], 'name': r['name'], 'replaced': it['replaced'], 'orig_sku': it['sku'], 'sha': sha,
                     'verdict': VERDICT_RU.get(c.get('verdict') or c.get('mask_verdict') or '', c.get('verdict') or '?'), 'wh': list(photo.size), **res,
                     'grade': (notes.get(str(i)) or {}).get('g', ''), 'note': (notes.get(str(i)) or {}).get('t', '')})
    pcs = [x['pieces'] for x in data]
    zero = sum(p == 0 for p in pcs)
    worst = sorted(data, key=lambda x: (-x['pieces'], -x['share']))[:3]
    json.dump(data, open(os.path.join(out, '..', 'data.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    e = html.escape
    cards = []
    for x in data:
        rep = f' · <b class="rep">замена (в наборе был {e(x["orig_sku"])})</b>' if x['replaced'] else ''
        cards.append(f'''<section class="row" id="n{x["n"]}">
<div class="pair"><figure><img loading="lazy" src="img/{x["n"]:02d}-photo.webp" alt=""><figcaption>исходное фото · {x["wh"][0]}×{x["wh"][1]} px</figcaption></figure>
<figure><img loading="lazy" src="img/{x["n"]:02d}-cut.webp" alt=""><figcaption>вырезка (последняя версия)</figcaption></figure></div>
<p class="cap"><b>№{x["n"]} · {e(x["role"])}</b> · {e(x["name"])}<br><span class="sku">{e(x["sku"])}</span>{rep}<br>вердикт вырезки: <b>{e(x["verdict"])}</b> · остатки: <b>{x["pieces"]}</b> куск. · {x["share"]} % площади<br><span class="note">на глаз: <b>{e(x["grade"] or "—")}</b> — {e(x["note"])}</span></p></section>''')
    gr = {g: sum(x['grade'] == g for x in data) for g in ('чисто', 'края', 'дефект')}
    worst_txt = ', '.join(f'№{x["n"]} {e(x["role"])} — {x["pieces"]} куск., {x["share"]} %' for x in worst)
    page = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Вырезка: 30 товаров</title><style>
:root{{--bg:#fff;--fg:#1b1b1f;--mut:#6b6b73;--line:#e2e2e8;--acc:#8a2be2}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#ececf1;--mut:#a0a0ab;--line:#2c2c34}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:12px 16px 40px}}h1{{font-size:20px;margin:8px 0}}
.sum{{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0 18px}}
.row{{border-top:1px solid var(--line);padding:14px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
figure{{margin:0;min-width:0}}img{{width:100%;height:auto;display:block;border-radius:6px;background:#ddd}}
figcaption{{font-size:12px;color:var(--mut);padding-top:3px}}.cap{{margin:8px 0 0;overflow-wrap:anywhere}}
.sku{{color:var(--mut);font-size:12px}}.rep{{color:var(--acc)}}.note{{color:var(--mut)}}
</style></head><body><main>
<h1>Вырезка новым алгоритмом: 30 произвольных товаров</h1>
<div class="sum"><b>Сводка.</b> Без остатков (0 кусков вне главного тела): <b>{zero} из {len(data)}</b>. Медиана числа остатков: <b>{statistics.median(pcs)}</b>. Худшие три: {worst_txt}.<br>
<b>На глаз</b> (листы по 330 px, до показа): чисто — <b>{gr['чисто']}</b>, мелкие дефекты краёв — <b>{gr['края']}</b>, заметный дефект — <b>{gr['дефект']}</b>. «Остатки» по кускам у всех 0, потому что цепочка и так выбрасывает отдельные куски; то, что прилипло к телу (белые чёрточки, кайма, хвост тени), счётчик не видит — оно в подписях.<br>
<span class="sku">Остатки = отдельные связные куски маски вне главного тела площадью ≥ 0,05 % кадра; доля — от площади всего товара. Замен из-за отсутствия в прогоне: {sum(x["replaced"] for x in data)} из {len(data)}. Слева — исходное фото, справа — вырезка на фиолетовом в том же масштабе (по центру кадра).</span></div>
{''.join(cards)}
</main></body></html>'''
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'готово: {out} · без остатков {zero}/{len(data)} · медиана {statistics.median(pcs)} · замен {sum(x["replaced"] for x in data)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
