#!/usr/bin/env python3
"""Страница владельцу: по каждому комплекту — аппликация, лист эталонов и карточки товаров.

Аппликация показывает, ЧТО и ГДЕ стоит; лист эталонов — как выглядят сами товары (то, что уходит
в модель как «внешний вид»); карточки — цена, магазин, размеры и ссылка. Плюс честная строка о
неполноте состава: какие роли остались пустыми и почему.

  ~/venvs/scout/bin/python page_sets10.py 2 5 8 11 14 17 20 23 26 29
"""
import html
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = os.path.expanduser('~/scout-scenes')
OUT = os.path.join(SCENES, 'page10')
PHOTOS = os.path.join(OUT, 'img')

# почему роль осталась пустой — по данным каталога, а не на глазок
GAP_WHY = {
    'ковёр': 'в каталоге всего 17 ковров, и почти все — коврики для ванной и придверные',
    'тв-тумба': 'телевизора в комплекте нет, тумбу под него не ставим',
}
GAP_WHY_DEFAULT = 'сборщик упёрся в правило разнообразия (см. примечание внизу)'

ROLE_ORDER = ['диван', 'кресло', 'пуф', 'столик', 'тв-тумба', 'комод', 'стеллаж', 'витрина',
              'стенка', 'ковёр', 'торшер', 'лампа', 'люстра', 'кашпо', 'ваза', 'плед',
              'подушка', 'подушка 2', 'подушка 3']


def photo(it: dict) -> str | None:
    """Фото товара из фида, уменьшенное до карточки. Кладём файлом — страница и так тяжёлая."""
    key = re.sub(r'[^A-Za-z0-9]', '_', str(it['eid']))[:40]
    name = f"{it['mid']}-{key[:36]}.jpg"
    p = os.path.join(PHOTOS, name)
    if not os.path.exists(p):
        url = it.get('img') or ''
        if url.startswith('//'):
            url = 'https:' + url
        im = None
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=25).read()))
        except Exception as e:  # noqa: BLE001 — мёртвая ссылка в фиде: карточка живёт по миниатюре
            th = os.path.join(HERE, 'thumbs', f"{it['mid']}-{key}.png")
            if os.path.exists(th):
                im = Image.open(th)
                print(f'  фото 404 — миниатюра: {it.get("name", "")[:40]}', flush=True)
            else:
                print(f'  фото не забрал ({str(e)[:40]}): {it.get("name", "")[:40]}', flush=True)
                return None
        im = im.convert('RGB')
        im.thumbnail((520, 520))
        im.save(p, 'JPEG', quality=86)
    return f'img/{name}'


def dims(it: dict) -> str:
    parts = [f'{int(v)}' for v in (it.get('w'), it.get('d'), it.get('h')) if v]
    if it.get('dia') and not it.get('w'):
        return f'⌀{int(it["dia"])} см'
    return '×'.join(parts) + ' см' if parts else 'размер не указан'


SHOWN_RANK = {'фото': 0, '3D-модель': 1, 'рисует нейросеть': 2, 'вне кадра': 3}


def how_shown(n: int) -> dict:
    """Как каждый товар попал в аппликацию — по журналу вклейки, а не на глазок.

    Фотография товара — основной путь; сильно развёрнутые напольные предметы идут 3D-моделью;
    мягкий декор (подушки, плед) и то, что не прошло, дорисовывает нейросеть по эталону.
    """
    out: dict[str, str] = {}
    for c in ('C1', 'C2'):
        p = os.path.join(SCENES, f'scene{n}-{c}-paint.json')
        if not os.path.exists(p):
            continue
        j = json.load(open(p))
        for role in j.get('ids', {}).values():
            state = ('3D-модель' if role in j.get('meshed', []) else
                     'фото' if role in j.get('pasted', []) else 'рисует нейросеть')
            if SHOWN_RANK[state] < SHOWN_RANK.get(out.get(role, 'вне кадра'), 3):
                out[role] = state
    return out


def card(role: str, it: dict, num: int | None, shown: str) -> str:
    src = photo(it)
    img = (f'<img src="{src}" alt="" loading="lazy">' if src
           else '<div class="noimg">фото недоступно</div>')
    mark = f'<span class="num">{num}</span>' if num else ''
    cls = {'фото': 'ok', '3D-модель': 'mesh', 'рисует нейросеть': 'ai'}.get(shown, 'off')
    return f"""<article class="card">
  <div class="ph">{img}{mark}</div>
  <div class="meta">
    <div class="role">{html.escape(role)} <span class="how {cls}">{shown}</span></div>
    <a class="name" href="{html.escape(it.get('url') or '#')}" target="_blank" rel="noopener">{html.escape(it['name'])}</a>
    <div class="line"><span class="dim">{dims(it)}</span><span class="price">{it['price']:,} ₽</span></div>
    <div class="shop">{html.escape(it.get('shop') or '')}</div>
  </div>
</article>""".replace(',', ' ')


def section(n: int, sets: list, nums: dict) -> str:
    s = sets[n - 1]
    items = s['items']
    order = sorted(items.items(),
                   key=lambda kv: ROLE_ORDER.index(kv[0]) if kv[0] in ROLE_ORDER else 99)
    shown = how_shown(n)
    cards = '\n'.join(card(r, it, nums.get(r), shown.get(r, 'вне кадра')) for r, it in order)
    tally = {}
    for r, _ in order:
        k = shown.get(r, 'вне кадра')
        tally[k] = tally.get(k, 0) + 1
    tally_s = ' · '.join(f'{k}: {v}' for k, v in sorted(tally.items(), key=lambda kv: SHOWN_RANK[kv[0]]))
    gaps = s.get('gaps') or []
    gap_html = ''
    if gaps:
        rows = ''.join(f'<li><b>{html.escape(g)}</b> — {GAP_WHY.get(g, GAP_WHY_DEFAULT)}</li>'
                       for g in gaps)
        gap_html = f'<div class="gaps"><div class="gh">не хватает в составе</div><ul>{rows}</ul></div>'
    vis = []
    for c in ('C1', 'C2'):
        p = f'{SCENES}/scene{n}-{c}-frame.json'
        vis.append(len(json.load(open(p))['visible']) if os.path.exists(p) else 0)
    return f"""<section class="set" id="set{n}">
  <header class="sh">
    <h2>Комплект {n}</h2>
    <div class="tags"><span>{html.escape(str(s['band']))} м²</span><span>{html.escape(str(s['style']))}</span>
      <span>{s['tier']}</span><span class="tot">{s['total']:,} ₽</span></div>
  </header>
  <p class="sub">Позиций в комплекте: <b>{len(items)}</b>. В кадре видно: вид 1 — {vis[0]},
     вид 2 — {vis[1]} (второй вид смотрит в пустой угол, там стоит меньше вещей).<br>
     На аппликации — {tally_s}.</p>
  {gap_html}
  <h3>Аппликация — два вида</h3>
  <a href="collage{n}.jpg" target="_blank"><img class="big" src="collage{n}.jpg" loading="lazy" alt=""></a>
  <h3>Эталоны внешнего вида — то, что уходит в модель</h3>
  <a href="ident{n}.jpg" target="_blank"><img class="big" src="ident{n}.jpg" loading="lazy" alt=""></a>
  <h3>Товары комплекта</h3>
  <div class="grid">{cards}</div>
</section>""".replace(',', ' ')


CSS = """
:root{--bg:#f7f6f4;--panel:#fff;--ink:#1b1a18;--dim:#6d6a64;--line:#e2ded7;--acc:#8a5b34;
      --chip:#efece6;}
@media (prefers-color-scheme:dark){:root{--bg:#15140f;--panel:#1e1c18;--ink:#efece6;--dim:#a29c92;
      --line:#332f28;--acc:#c99a63;--chip:#282520;}}
:root[data-theme=dark]{--bg:#15140f;--panel:#1e1c18;--ink:#efece6;--dim:#a29c92;--line:#332f28;
      --acc:#c99a63;--chip:#282520;}
:root[data-theme=light]{--bg:#f7f6f4;--panel:#fff;--ink:#1b1a18;--dim:#6d6a64;--line:#e2ded7;
      --acc:#8a5b34;--chip:#efece6;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.01em}
.lede{color:var(--dim);max-width:70ch;margin:0 0 22px}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:34px}
.toc a{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:5px 12px;
       text-decoration:none;color:var(--ink);font-size:14px}
.set{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;
     margin-bottom:30px}
.sh{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
h2{font-size:22px;margin:0}
h3{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
   margin:26px 0 10px;font-weight:600}
.tags{display:flex;gap:6px;flex-wrap:wrap}
.tags span{background:var(--chip);border-radius:6px;padding:2px 9px;font-size:13px;color:var(--dim)}
.tags .tot{color:var(--acc);font-weight:600;font-variant-numeric:tabular-nums}
.sub{color:var(--dim);font-size:14px;margin:8px 0 0}
.gaps{margin-top:14px;border-left:3px solid var(--acc);background:var(--chip);
      border-radius:0 8px 8px 0;padding:10px 14px}
.gh{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--acc);font-weight:600}
.gaps ul{margin:6px 0 0;padding-left:18px;font-size:14px;color:var(--dim)}
.big{width:100%;height:auto;border-radius:10px;border:1px solid var(--line);display:block}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.card{background:var(--bg);border:1px solid var(--line);border-radius:10px;overflow:hidden;
      display:flex;flex-direction:column}
.ph{position:relative;aspect-ratio:4/3;background:#fff;display:flex;align-items:center;
    justify-content:center;overflow:hidden}
.ph img{max-width:100%;max-height:100%;object-fit:contain}
.noimg{color:#999;font-size:12px}
.num{position:absolute;top:6px;left:6px;background:var(--acc);color:#fff;border-radius:50%;
     width:24px;height:24px;display:flex;align-items:center;justify-content:center;
     font-size:13px;font-weight:700}
.meta{padding:10px 11px 12px;display:flex;flex-direction:column;gap:4px}
.role{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
      display:flex;justify-content:space-between;gap:6px;align-items:center}
.how{text-transform:none;letter-spacing:0;font-size:10.5px;padding:1px 7px;border-radius:999px;
     border:1px solid var(--line);white-space:nowrap}
.how.ok{color:#2f7d4f;border-color:#2f7d4f55}
.how.mesh{color:#2d6ea8;border-color:#2d6ea855}
.how.ai{color:#9a6a1f;border-color:#9a6a1f55}
.how.off{color:var(--dim)}
.name{font-size:13.5px;line-height:1.35;color:var(--ink);text-decoration:none}
.name:hover{color:var(--acc);text-decoration:underline}
.line{display:flex;justify-content:space-between;gap:8px;font-size:13px;
      font-variant-numeric:tabular-nums;margin-top:2px}
.dim{color:var(--dim)}
.price{font-weight:600}
.shop{font-size:11.5px;color:var(--dim)}
.note{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;
      color:var(--dim);font-size:14.5px}
.note b{color:var(--ink)}
a:focus-visible,.toc a:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
"""


def main() -> None:
    ns = [int(x) for x in sys.argv[1:]] or [2, 5, 8, 11, 14, 17, 20, 23, 26, 29]
    os.makedirs(PHOTOS, exist_ok=True)
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    from viz_marks import numbering
    body = []
    for n in ns:
        try:
            nums = numbering(n, ('C1', 'C2'))
        except Exception:  # noqa: BLE001 — нумерация только украшает карточки
            nums = {}
        for src, dst in ((f'_collage{n}.jpg', f'collage{n}.jpg'), (f'_ident{n}.jpg', f'ident{n}.jpg')):
            s, d = os.path.join(SCENES, src), os.path.join(OUT, dst)
            if os.path.exists(s):
                with open(s, 'rb') as f, open(d, 'wb') as g:
                    g.write(f.read())
        body.append(section(n, sets, nums))
        print(f'сет {n} готов', flush=True)
    toc = ''.join(f'<a href="#set{n}">Комплект {n}</a>' for n in ns)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Комплекты уровня комфорт — аппликации, эталоны, товары</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Комплекты уровня «комфорт»</h1>
<p class="lede">По каждому комплекту: аппликация из двух видов (это проверочная картинка для вас —
в модель уходит схема с глубиной), лист эталонов внешнего вида на все позиции и карточки товаров
с ценой, размером и ссылкой в магазин.</p>
<div class="toc">{toc}</div>
{''.join(body)}
<div class="note"><b>Почему в трёх комплектах мало позиций.</b> Правило разнообразия не даёт двум
комплектам повторять друг друга. Сейчас оно считает пересечение целиком: как только набранный
комплект совпал с ранее собранным на 4 позиции при лимите 3, отсекается <em>любой</em> следующий
товар — даже тот, которого в том комплекте нет. Роли добираются по очереди, декор идёт последним,
поэтому у комплектов 17, 20 и 29 разом пропали торшер, люстра, подушки, плед и ваза. Это ошибка
проверки, а не нехватка каталога: люстр в каталоге 5 592, ваз 705, подушек 398.
Лечится одной строкой — считать пересечение только для тех товаров, которые в том комплекте
действительно есть. Пересборка комплектов бесплатная (платных вызовов нет).</div>
</div></body></html>"""
    with open(os.path.join(OUT, 'sets10.html'), 'w') as f:
        f.write(page)
    print(f'страница: {os.path.join(OUT, "sets10.html")}')


if __name__ == '__main__':
    main()
