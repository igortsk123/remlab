#!/usr/bin/env python3
"""Страница разбора застрявших товаров: фото, вырезка и то, что вышло — рядом.

ЗАЧЕМ (владелец 01.09): «покажи что сгенерилось и фото рядом, сравню и скажу, всё ли там
ок». Гейт формы отбраковал несколько позиций демо дважды подряд, вырезка одного товара
упала — решение «чинить, менять фото или менять товар» принимает владелец, и для этого ему
нужно видеть вход и выход, а не вердикт словами.

Показываем ЧЕСТНО: не только итог, но и промежуточное — вырезку, которая уходит в генератор.
Именно она и есть вход (ADR-0133), а не исходное фото.

  ~/venvs/scout/bin/python blocked_page.py --skus 99272:123,112923:456
  ~/venvs/scout/bin/python blocked_page.py --pinned      # все закреплённые владельцем
"""
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))

MESH = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/mesh-blocked')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def render_shape(glb: str, out: str, yaw: float) -> bool:
    """Рендер того, что выдал генератор. Без текстуры — у забракованных её и нет."""
    try:
        import mesh_render as MR
        from PIL import Image
        img = MR.render(MR.load_parts(glb), yaw_deg=yaw, pitch_deg=12.0, size=(560, 560))
        import numpy as np
        a = np.asarray(img)
        ys, xs = np.where(a[..., 3] > 8)
        if len(ys):
            img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        w, h = img.size
        k = 300 / max(w, h)
        img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS).save(out)
        return True
    except Exception:  # noqa: BLE001 — один битый меш не должен ронять страницу
        print(f'  рендер не удался: {traceback.format_exc(limit=1)[:120]}')
        return False


# Веса модели вырезки лежат ВНУТРИ образа нод (/opt/weights/birefnet) — на дев-машине их
# нет. Значит вырезку здесь воспроизвести нельзя, и говорить «вырезка не получилась» у
# каждого товара было бы враньём: это ограничение стенда, а не свойство фото.
ENV_MARK = 'Repo id must be in the form'


def cutout_of(url: str, role: str, out: str) -> tuple[bool, str]:
    """Прогоняем ТУ ЖЕ вырезку, что уходит в генератор. Отличаем отказ ПО ТОВАРУ от
    невозможности посчитать её здесь вообще."""
    try:
        import preprocess as PRE
        _shape, cut_rgba, _paint, _sha, _info = PRE.prepare(url, role)
        cut_rgba.save(out)
        return True, ''
    except Exception as e:  # noqa: BLE001
        msg = f'{type(e).__name__}: {str(e)[:200]}'
        return False, ('ENV' if ENV_MARK in str(e) else msg)


def main() -> None:
    if '--pinned' in sys.argv:
        pin = json.load(open(os.path.join(HERE, '..', 'rules', 'mesh-pinned.json'),
                             encoding='utf-8'))
        skus = [s for g in pin['pinned'] for s in g['skus']]
    else:
        skus = sys.argv[sys.argv.index('--skus') + 1].split(',')
    os.makedirs(OUT, exist_ok=True)

    info = {}
    rows = db("select shop_mid||':'||external_id, coalesce(name,''), coalesce(cat_role,''), "
              "coalesce(image_url_hd, image_url), coalesce(w_cm,0), coalesce(d_cm,0), "
              "coalesce(h_cm,0), coalesce(mesh_status,'none'), coalesce(url,'') from products "
              "where shop_mid||':'||external_id in (" +
              ','.join("'" + s + "'" for s in skus) + ");")
    for sku, name, role, img, w, d, h, st, link in rows:
        info[sku] = {'name': name, 'role': role, 'img': img, 'w': w, 'd': d, 'h': h,
                     'status': st, 'link': link}

    cards = []
    for sku in skus:
        p = info.get(sku)
        if not p:
            continue
        slug = sku.replace(':', '_')
        card = {'sku': sku, **p, 'shapes': [], 'reasons': [], 'cut': None, 'cut_err': ''}
        d = os.path.join(MESH, slug)
        if os.path.isdir(d):
            for j in sorted(os.listdir(d)):
                man = os.path.join(d, j, 'manifest.json')
                glb = os.path.join(d, j, 'shape.glb')
                if os.path.exists(man):
                    m = json.load(open(man, encoding='utf-8'))
                    card['reasons'].append(m.get('gate_reason') or '—')
                if os.path.exists(glb):
                    for yaw, tag in ((0, 'front'), (60, 'side')):
                        f = f'{slug}-{j[:8]}-{tag}.png'
                        if render_shape(glb, os.path.join(OUT, f), yaw):
                            card['shapes'].append(f)
        if not card['reasons']:
            # Нет манифеста — значит отказ случился ДО публикации комплекта (например
            # вырезка). Вердикт ноды тогда есть только в журнале прогона.
            try:
                for ln in open(os.path.join(HERE, '..', 'mesh-run-progress.jsonl'),
                               encoding='utf-8'):
                    ln = ln.strip()
                    if not ln:
                        continue
                    r = json.loads(ln)
                    if r.get('sku') == sku and r.get('status') not in ('ok', 'cached'):
                        card['reasons'] = [f"{r['status']}: {str(r.get('error') or '')[:200]}"]
            except FileNotFoundError:
                pass
        f = f'{slug}-cut.png'
        ok, err = cutout_of(p['img'], p['role'], os.path.join(OUT, f))
        card['cut'] = f if ok else None
        card['cut_err'] = err
        cards.append(card)
        print(f'  {sku} {p["role"]}: форм {len(card["shapes"]) // 2}, вырезка '
              + ('ок' if ok else 'ОТКАЗ'))

    html = ['<!doctype html><meta charset="utf-8"><title>Застрявшие товары</title>',
            '<style>body{font:14px/1.5 system-ui;margin:24px;background:#faf9f7;color:#1a1a1a}'
            'h1{font-size:20px}.card{background:#fff;border:1px solid #e5e2dc;border-radius:10px;'
            'padding:16px;margin:0 0 18px}.row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}'
            '.row figure{margin:0;text-align:center}.row img{max-height:300px;border:1px solid #eee;'
            'border-radius:6px;background:#fff}figcaption{font-size:12px;color:#666;margin-top:4px}'
            '.why{background:#fff4f0;border-left:3px solid #d9714e;padding:8px 12px;margin:10px 0;'
            'font-size:13px}.dim{color:#666;font-size:13px}a{color:#1a56b8}</style>',
            f'<h1>Застрявшие товары — что ушло в генератор и что вышло ({len(cards)})</h1>',
            '<p class="dim">Слева фото товара, дальше то, что генератор выдал, с двух '
            'ракурсов. Вырезку (реальный вход генератора) на этой машине посчитать нельзя — '
            'веса модели живут внутри образа нод, — поэтому её здесь нет; там, где вырезка '
            'и была причиной отказа, вердикт ноды показан текстом.</p>']
    for c in cards:
        html.append('<div class="card">')
        html.append(f'<b>{c["name"] or c["sku"]}</b> <span class="dim">— {c["role"]}, '
                    f'паспорт {c["w"]}×{c["d"] or "?"}×{c["h"]} см, статус {c["status"]}</span>')
        if c['link']:
            html.append(f' · <a href="{c["link"]}" target="_blank">карточка магазина</a>')
        for r in dict.fromkeys(c['reasons']):
            html.append(f'<div class="why">вердикт гейта: {r}</div>')
        if c['cut_err'] and c['cut_err'] != 'ENV':
            html.append(f'<div class="why">вырезка не получилась: {c["cut_err"]}</div>')
        html.append('<div class="row">')
        html.append(f'<figure><img src="{c["img"]}"><figcaption>фото товара</figcaption></figure>')
        if c['cut']:
            html.append(f'<figure><img src="{c["cut"]}"><figcaption>вырезка — ВХОД генератора'
                        '</figcaption></figure>')
        for i, f in enumerate(c['shapes']):
            html.append(f'<figure><img src="{f}"><figcaption>выход, попытка {i // 2 + 1}, '
                        f'{"вид спереди" if i % 2 == 0 else "вид сбоку"}</figcaption></figure>')
        html.append('</div></div>')
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write('\n'.join(html))
    print(f'страница: {OUT}/index.html')


if __name__ == '__main__':
    main()
