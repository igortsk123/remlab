#!/usr/bin/env python3
"""Страница «комплекты и вырезки» — пересобирается ночью из кэша конвейера.

Читает ровно то, что видит генератор: вырезку из `~/scout-scenes/cutouts/<sha>.png` и вердикт
из `photo_assessment`. Поэтому страница не «снимок, который кто-то когда-то собрал», а текущее
состояние: сменилось фото — `cutout_sync` пересчитал маску, страница ночью показала новую.

Вырезки лежат на шахматке: на белом фоне пропавшая белая ножка и оставшийся кусок подложки
выглядят одинаково, то есть ровно та ошибка, которую мы ищем, становится невидимой.

  ~/venvs/scout/bin/python sets_preview_page.py            # собрать
  ~/venvs/scout/bin/python sets_preview_page.py --publish  # собрать и выложить на /test/
"""
import html
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))

SETS = os.path.join(HERE, 'sets3.json')
OUT = os.path.expanduser('~/scout-scenes/sets-preview')
THUMB = 240


def _state() -> dict:
    """SKU → (sha, вердикт, измерения). Из спроса и таблицы оценок, а не из файлов на диске."""
    import cutout_sync as CS
    import preprocess as PRE
    rows = CS.db(
        "select d.sku, d.source_sha, coalesce(a.verdict,'unknown'), coalesce(a.metrics::text,'{}') "
        "from mesh_demand d left join photo_assessment a "
        f"  on a.source_sha = d.source_sha and a.assessor_version = {CS.q(PRE.ASSESSOR_VERSION)} "
        "where d.source_sha is not null")
    out = {}
    for r in rows:
        if len(r) != 4:
            continue
        try:
            m = json.loads(r[3])
        except Exception:  # noqa: BLE001
            m = {}
        out[r[0]] = (r[1], r[2], m)
    return out


def checker(size, step=10):
    w, h = size
    y, x = np.mgrid[0:h, 0:w]
    c = np.where(((x // step + y // step) % 2) == 0, 238, 208).astype(np.uint8)
    return Image.fromarray(np.dstack([c, c, c]), 'RGB')


def thumb(cut_path, dst):
    im = Image.open(cut_path).convert('RGBA')
    im.thumbnail((THUMB, THUMB), Image.LANCZOS)
    bg = checker(im.size)
    bg.paste(im, (0, 0), im)
    canvas = Image.new('RGB', (THUMB, THUMB), (247, 248, 249))
    canvas.paste(bg, ((THUMB - bg.width) // 2, (THUMB - bg.height) // 2))
    canvas.save(dst, quality=84)


def build() -> tuple[int, int]:
    import cutout_sync as CS
    st = _state()
    sets = json.load(open(SETS))
    os.makedirs(os.path.join(OUT, 'i'), exist_ok=True)
    made = miss = 0
    cards = []
    for n, s in enumerate(sets, 1):
        items, flags = [], set()
        for slot, it in sorted((s.get('items') or {}).items()):
            if not it or not it.get('mid'):
                continue
            sku = f"{it['mid']}:{it['eid']}"
            sha, verdict, m = st.get(sku, (None, 'unknown', {}))
            cut = os.path.join(CS.CACHE, sha + '.png') if sha else None
            if cut and os.path.exists(cut):
                dst = os.path.join(OUT, 'i', sha + '.jpg')
                if not os.path.exists(dst):
                    thumb(cut, dst)
                pic = f'<img src="i/{sha}.jpg" alt="" loading="lazy">'
                made += 1
            else:
                pic = '<div class="no">вырезка ещё не посчитана</div>'
                miss += 1
            badge = ''
            if verdict == 'collage':
                badge, _ = '<span class="b bad">коллаж</span>', flags.add('коллаж')
            elif verdict == 'bad_cutout':
                badge, _ = '<span class="b bad">брак маски</span>', flags.add('брак маски')
            elif verdict == 'tiny_object':
                badge, _ = '<span class="b warn">товар мелкий</span>', flags.add('товар мелкий')
            elif m.get('verdict') == 'suspect':
                badge, _ = '<span class="b warn">подозрение</span>', flags.add('подозрение')
            rest = (m.get('restored_px') or 0)
            rest_html = f'<span class="b ok">+{rest} px</span>' if rest >= 300 else ''
            items.append(
                f'<figure>{pic}<figcaption><b>{html.escape(slot)}</b>{badge}{rest_html}<br>'
                f'{html.escape(str(it.get("name") or "")[:64])}</figcaption></figure>')
        head = ' · '.join(x for x in (f"{s.get('band', '')} м²", s.get('tier'), s.get('style'))
                          if x)
        fl = ''.join(f'<span class="b {"warn" if f in ("подозрение", "товар мелкий") else "bad"}">'
                     f'{f}</span>' for f in sorted(flags))
        cards.append(
            f'<section class="set" data-flag="{"1" if flags else "0"}">'
            f'<h2>№{n} <span class="sid">{html.escape(s.get("set_id", ""))}</span>'
            f'<span class="meta">{html.escape(head)}</span>{fl}</h2>'
            f'<div class="grid">{"".join(items)}</div></section>')
    page = (TEMPLATE.replace('{{SETS}}', '\n'.join(cards)).replace('{{N}}', str(len(sets)))
            .replace('{{ITEMS}}', str(made)).replace('{{MISS}}', str(miss)))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    return made, miss


TEMPLATE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Комплекты и вырезки</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap">
<style>
:root{--paper:#f6f7f8;--card:#fff;--ink:#151d24;--ink2:#4a565f;--ink3:#7d8990;--line:#dfe4e7;
  --line2:#eef1f3;--accent:#276876;--warn:#a5591c;--bad:#a33b32}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#10161a;--card:#161d22;
  --ink:#e7ecee;--ink2:#a5b1b7;--ink3:#76848b;--line:#263037;--line2:#1d262b;--accent:#6fb6c4;
  --warn:#d99a55;--bad:#e08a80}}
:root[data-theme="dark"]{--paper:#10161a;--card:#161d22;--ink:#e7ecee;--ink2:#a5b1b7;
  --ink3:#76848b;--line:#263037;--line2:#1d262b;--accent:#6fb6c4;--warn:#d99a55;--bad:#e08a80}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.6 "IBM Plex Sans",-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:52px 22px 90px}
h1{font:600 2.1rem/1.13 Spectral,Georgia,serif;margin:0 0 .5rem}
.lede{color:var(--ink2);max-width:64ch;margin:0 0 6px}
.sub{color:var(--ink3);font-size:.9rem;margin:0 0 22px}
.bar{position:sticky;top:0;z-index:5;background:var(--paper);padding:12px 0;
  border-bottom:1px solid var(--line2);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{font:500 .82rem/1 "IBM Plex Sans";padding:7px 13px;border:1px solid var(--line);
  background:var(--card);color:var(--ink2);border-radius:2px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
:root[data-theme="dark"] .chip[aria-pressed="true"]{color:#0d1417}
.chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.set{margin-top:26px}.set[hidden]{display:none}
h2{font:600 1.12rem/1.3 "IBM Plex Sans";margin:0 0 10px;display:flex;gap:10px;
  align-items:baseline;flex-wrap:wrap}
.sid{font-family:"IBM Plex Mono",monospace;font-size:.76rem;color:var(--ink3);font-weight:400}
.meta{font-weight:400;color:var(--ink2);font-size:.92rem}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(170px,1fr))}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:3px;
  padding:8px;text-align:center}
figure img{width:100%;height:auto;display:block;border-radius:2px}
.no{height:140px;display:flex;align-items:center;justify-content:center;color:var(--ink3);
  border:1px dashed var(--line);border-radius:2px;font-size:.8rem;padding:6px;text-align:center}
figcaption{font-size:.78rem;color:var(--ink2);margin-top:6px;line-height:1.4;
  overflow-wrap:anywhere}
figcaption b{color:var(--ink)}
.b{display:inline-block;font:500 .68rem/1 "IBM Plex Sans";padding:3px 6px;border-radius:2px;
  margin-left:5px;vertical-align:middle}
.b.bad{background:var(--bad);color:#fff}.b.warn{background:var(--warn);color:#fff}
.b.ok{background:var(--line2);color:var(--ink2)}
</style></head><body><div class="wrap">
<h1>Комплекты и вырезки</h1>
<p class="lede">Все {{N}} комплектов и то, чем каждый товар уйдёт в генератор мешей: вырезка
на шахматке. Шахматка не для красоты — на белом фоне пропавшая белая ножка и оставшийся кусок
подложки выглядят одинаково.</p>
<p class="sub">Вырезок: {{ITEMS}} · ещё не посчитано: {{MISS}}. Страница пересобирается ночью;
сменилось фото у товара — вырезка пересчитывается сама. Плашки: «коллаж» и «брак маски»
на генерацию не уходят, «+N px» — сколько тонких деталей вернул гибрид.</p>
<div class="bar">
  <button class="chip" data-f="all" aria-pressed="true">все комплекты</button>
  <button class="chip" data-f="flag">только с замечаниями</button>
</div>
{{SETS}}
</div>
<script>
(function(){
  var chips=[].slice.call(document.querySelectorAll('.chip'));
  var sets=[].slice.call(document.querySelectorAll('.set'));
  function apply(f){
    chips.forEach(function(c){c.setAttribute('aria-pressed',String(c.dataset.f===f));});
    sets.forEach(function(s){s.hidden=(f==='flag' && s.dataset.flag!=='1');});
    try{localStorage.setItem('setsprev.f',f);}catch(e){}
  }
  chips.forEach(function(c){c.addEventListener('click',function(){apply(c.dataset.f);});});
  var v='all'; try{v=localStorage.getItem('setsprev.f')||'all';}catch(e){}
  apply(chips.some(function(c){return c.dataset.f===v;})?v:'all');
})();
</script></body></html>"""


def main() -> None:
    made, miss = build()
    print(f'страница собрана: вырезок {made}, ещё не посчитано {miss}')
    if '--publish' in sys.argv:
        tgz = '/tmp/sets-preview.tgz'
        subprocess.run(['tar', 'czf', tgz, '-C', OUT, '.'], check=True)
        subprocess.run(['scp', '-q', '-P', '22222', tgz, 'root@89.167.127.0:/tmp/'], check=True)
        subprocess.run(
            ['ssh', '-p', '22222', 'root@89.167.127.0',
             'rm -rf /opt/remlab/test/sets-preview.new && '
             'mkdir -p /opt/remlab/test/sets-preview.new && '
             'tar xzf /tmp/sets-preview.tgz -C /opt/remlab/test/sets-preview.new && '
             'rm -rf /opt/remlab/test/sets-preview && '
             'mv /opt/remlab/test/sets-preview.new /opt/remlab/test/sets-preview && '
             'rm -f /tmp/sets-preview.tgz'], check=True)
        os.remove(tgz)
        print('опубликовано: /test/sets-preview/')


if __name__ == '__main__':
    main()
