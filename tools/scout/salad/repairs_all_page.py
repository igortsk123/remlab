#!/usr/bin/env python3
"""Страница /test/mesh-repairs-all/ — ВСЁ, что автоматика вылечила сама. АРХИВ.

ВНИМАНИЕ: по этой самой странице владелец 01.09 отменил ремонт целиком (ADR-0143) —
«не лечишь, а калечишь». Копии `model.repaired.glb` убраны из дерева в
`~/scout-scenes/mesh-repairs-parked/`, так что скрипт больше ничего не найдёт и
перезапускать его не надо: опубликованная страница осталась как свидетельство отменённого.


Владелец 01.09: «таких пар 158 — покажи их все; интересно, что ты сам на автомате лечил».
На странице пара «до/после» для каждой модели с `model.repaired.glb`: слева оригинал от
генератора, справа результат цепочки ремонта (срез плиты, обрезка по паспорту, закраска
кромки, despeckle, цвет к фото — `apply_repairs.py`), плюс фото товара для сверки.
Рендер параллельный, с кэшем по mtime: повторный запуск дорисовывает только новое.
"""
import glob
import html
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/mesh-repairs-all')
CHECKER = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAHUlEQVQoz2P8'
           'z8DAwMDAxMDAwMDAwPD//38GBgYGBgYAJRcDJcOB/xkAAAAASUVORK5CYII=')


def _job(args):
    """Рендер одной стороны пары (отдельный процесс — GIL не мешает)."""
    glb, png = args
    from topview_render import render_front
    render_front(glb, 0.0, png)
    return png


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    items, todo = [], []
    for rp in sorted(glob.glob(os.path.join(SRC, '*/*/repair.json'))):
        d = os.path.dirname(rp)
        rep = os.path.join(d, 'model.repaired.glb')
        orig = os.path.join(d, 'model.glb')
        if not (os.path.exists(rep) and os.path.exists(orig)):
            continue
        sku = os.path.basename(os.path.dirname(d))
        job = os.path.basename(d)
        try:
            r = json.load(open(rp, encoding='utf-8'))
        except Exception:  # noqa: BLE001
            r = {}
        man = {}
        mp = os.path.join(d, 'manifest.json')
        if os.path.exists(mp):
            try:
                man = json.load(open(mp, encoding='utf-8'))
            except Exception:  # noqa: BLE001
                man = {}
        a_png = os.path.join(OUT, f'{sku}.{job}.orig.png')
        b_png = os.path.join(OUT, f'{sku}.{job}.fixed.png')
        for g, p in ((orig, a_png), (rep, b_png)):
            if not os.path.exists(p) or os.path.getmtime(p) < os.path.getmtime(g):
                todo.append((g, p))
        cut = os.path.join(d, 'cutout.png')
        c_png = ''
        if os.path.exists(cut):
            c_png = f'{sku}.{job}.photo.png'
            shutil.copy(cut, os.path.join(OUT, c_png))
        items.append({'sku': sku, 'job': job, 'role': man.get('role') or '?',
                      'seed': man.get('seed'), 'changed': bool(r.get('changed')),
                      'b_orig': r.get('bytes_orig'), 'b_rep': r.get('bytes_repaired'),
                      'a': os.path.basename(a_png), 'b': os.path.basename(b_png), 'c': c_png})
    if todo:
        workers = int(os.environ.get('REPAIRS_WORKERS', 0)) or max(1, (os.cpu_count() or 4) // 2)
        print(f'рендер {len(todo)} картинок на {workers} процессах', flush=True)
        import concurrent.futures as cf
        done = 0
        with cf.ProcessPoolExecutor(max_workers=workers) as ex:
            for f in cf.as_completed([ex.submit(_job, t) for t in todo]):
                try:
                    f.result()
                    done += 1
                    if done % 25 == 0:
                        print(f'  ...{done}/{len(todo)}', flush=True)
                except Exception as e:  # noqa: BLE001 — битая модель не валит страницу
                    print(f'  сбой: {str(e)[:70]}', flush=True)
    cards = []
    for it in sorted(items, key=lambda x: (x['role'], x['sku'])):
        delta = ''
        if it['b_orig'] and it['b_rep']:
            d_kb = (it['b_rep'] - it['b_orig']) / 1024
            delta = f'{d_kb:+.0f} КБ'
        seed = f" · перегон #{it['seed']}" if it.get('seed') else ''
        cards.append(f"""
<div class="card">
 <h3>{html.escape(it['role'])} <span class="sku">{it['sku']}</span>{seed}
  <span class="d">{delta}</span></h3>
 <div class="row">
  <div><div class="lbl">как сгенерировал генератор</div>
   <img src="{it['a']}" loading="lazy"></div>
  <div><div class="lbl">после автоматического ремонта</div>
   <img src="{it['b']}" loading="lazy"></div>
  <div><div class="lbl">фото товара</div>
   {f'<img src="{it["c"]}" loading="lazy">' if it['c'] else '<i>нет</i>'}</div>
 </div>
</div>""")
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Что автоматика вылечила сама</title><style>
body{{font:15px/1.5 system-ui;margin:20px;background:#fafaf8;color:#1c1c1a}}
h1{{font-size:20px}} .sub{{color:#666;max-width:820px}}
.card{{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:12px;margin:10px 0;max-width:1000px}}
h3{{font-size:15px;margin:0 0 8px}} .sku{{font-size:11px;color:#999;font-weight:400}}
.d{{font-size:11px;color:#888;font-weight:400;margin-left:8px}}
.lbl{{font-size:12px;color:#666;margin-bottom:4px}}
.row{{display:flex;gap:14px;flex-wrap:wrap}}
.row img{{max-width:290px;max-height:250px;border-radius:6px;background:url('{CHECKER}') repeat}}
</style></head><body>
<h1>Что автоматика вылечила сама — {len(items)} моделей</h1>
<p class="sub">Слева — как модель вышла из генератора, справа — после цепочки ремонта:
срез плиты под дном, обрезка выхода за паспортные габариты, закраска открывшейся кромки,
удаление мелких обломков и подгонка цвета к фото. Оригинал не удаляется: в любой момент
можно вернуться к исходной версии.</p>
{''.join(cards)}
</body></html>"""
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'карточек: {len(items)} → {OUT}', flush=True)


if __name__ == '__main__':
    main()
