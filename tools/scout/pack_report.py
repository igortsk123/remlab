#!/usr/bin/env python3
"""Страница «весь пакет»: что ушло в модель, что вернулось, приёмка и товары комплекта.

Владелец смотрит результат только так: полный комплект входов и выходов на одной ссылке, плюс
товары в конце — чтобы видеть, из чего собрана комната и сколько она стоит.

  ~/venvs/scout/bin/python pack_report.py 21 --cams C1,C2
"""
import base64
import html
import io
import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from viz_objects import product  # noqa: E402

CSS = """
:root { --bg:#F5F6F4; --panel:#fff; --ink:#171C18; --soft:#5C655E; --line:#DFE3DC;
  --accent:#3F6B57; --bad:#A2412F; --badbg:#FBEEEA; }
@media (prefers-color-scheme:dark) { :root { --bg:#101410; --panel:#191E18; --ink:#E8ECE6;
  --soft:#9AA598; --line:#2A312A; --accent:#8FBFA3; --bad:#D98A76; --badbg:#251A17; } }
:root[data-theme="dark"] { --bg:#101410; --panel:#191E18; --ink:#E8ECE6; --soft:#9AA598;
  --line:#2A312A; --accent:#8FBFA3; --bad:#D98A76; --badbg:#251A17; }
:root[data-theme="light"] { --bg:#F5F6F4; --panel:#fff; --ink:#171C18; --soft:#5C655E;
  --line:#DFE3DC; --accent:#3F6B57; --bad:#A2412F; --badbg:#FBEEEA; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
.w { max-width:1120px; margin:0 auto; padding:44px 20px 80px; }
h1 { font-family:"Iowan Old Style",Georgia,serif; font-size:clamp(26px,4vw,38px);
  margin:0 0 8px; text-wrap:balance; }
h2 { font-family:"Iowan Old Style",Georgia,serif; font-size:22px; margin:0 0 8px; }
.sub { color:var(--soft); margin:0 0 26px; max-width:66ch; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:16px;
  padding:20px 22px; margin-bottom:18px; }
.card p { color:var(--soft); margin:0 0 12px; max-width:74ch; }
.shot { overflow-x:auto; background:#fff; border:1px solid var(--line); border-radius:10px;
  margin-bottom:12px; }
.shot img { display:block; width:100%; height:auto; min-width:520px; }
.score { display:flex; gap:20px; flex-wrap:wrap; margin:2px 0 14px; }
.score div { background:var(--bg); border:1px solid var(--line); border-radius:12px;
  padding:11px 17px; }
.score b { display:block; font-size:26px; font-variant-numeric:tabular-nums; }
.score span { color:var(--soft); font-size:13px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14.5px; min-width:520px; }
td,th { border-top:1px solid var(--line); padding:6px 10px; text-align:left; }
th { color:var(--soft); font-weight:600; font-size:12.5px; text-transform:uppercase;
  letter-spacing:.05em; }
td.n { font-variant-numeric:tabular-nums; }
tr.bad td { background:var(--badbg); color:var(--bad); }
pre { white-space:pre-wrap; background:var(--bg); border-left:3px solid var(--accent);
  padding:12px 14px; margin:0; font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;
  max-height:460px; overflow:auto; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:14px; }
figure.prod { margin:0; background:var(--bg); border:1px solid var(--line); border-radius:12px;
  overflow:hidden; }
figure.prod img { display:block; width:100%; height:150px; object-fit:contain; background:#fff; }
figure.prod figcaption { padding:8px 10px 11px; display:flex; flex-direction:column; gap:2px; }
figure.prod b { font-size:13.5px; }
figure.prod span { color:var(--soft); font-size:12px; }
figure.prod em { font-style:normal; font-weight:600; font-variant-numeric:tabular-nums;
  font-size:13.5px; }
figure.prod .shop { font-size:11.5px; }
"""


def uri(path, maxpx=1500, q=86):
    im = Image.open(path)
    if im.mode == 'RGBA':
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert('RGB')
    im.thumbnail((maxpx, maxpx))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=q, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def money(v) -> str:
    return f'{int(v):,}'.replace(',', ' ')


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    P = os.path.join(SCENE_DIR, f'scene{n}')
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]
    s_items = s['items']

    def load(name, default=None):
        try:
            return json.load(open(f'{P}-{name}.json'))
        except OSError:
            return default

    cost = load('pair-cost', {'cost_usd': 0, 'usage': {'input_tokens': 0}})
    build = load('build', {'mesh_roles': []})
    audit = load('audit', [])
    try:
        prompt = open(f'{P}-pair-prompt.txt').read()
    except OSError:
        prompt = ''

    steps = [
        ('Вход 1 — коллаж',
         'Фотографии товаров, поставленные по плану в наш рендер комнаты. Два вида на одном '
         'холсте 2048×2864, между ними маркерная полоса: чистая маджента, 94 px. Столик и кашпо '
         'здесь не фотографии, а 3D-модели товаров — камера видит их развёрнутыми на 58° и 87°, '
         'под таким углом карточка врёт.', f'{P}-pair-collage.jpg'),
        ('Вход 2 — тот же коллаж с номерами',
         'Служебная подсказка: у каждого предмета свой номер, сквозной по всему комплекту. К этим '
         'номерам в запросе привязан список — что за товар, габариты, как стоит. Рисовать номера '
         'в ответе запрещено.', f'{P}-pair-marked.jpg'),
        ('Вход 3 — план',
         'Комната сверху: размеры, площадь, дверь и окно, точки съёмки и секторы обзора обеих '
         'камер.', f'{P}-plan.png'),
        ('Вход 4 — эталоны внешнего вида',
         'Карточки тех товаров, что попали в кадр только частью. Модель берёт отсюда внешний вид, '
         'но не место и не размер.', f'{P}-pair-identity.jpg'),
        ('Выход — лист ответа',
         'Модель вернула оба кадра на одном холсте, полоса на месте. По ней ответ и режется.',
         f'{P}-pair-final.jpg'),
    ]
    blocks = ''
    for title, note, path in steps:
        if not os.path.exists(path):
            continue
        blocks += (f'<section class="card"><h2>{title}</h2><p>{note}</p>'
                   f'<div class="shot"><img src="{uri(path, 1700)}" alt=""></div></section>')

    frames = ''.join(f'<div class="shot"><img src="{uri(f"{P}-{c}-final.jpg", 1700)}" alt=""></div>'
                     for c in cams if os.path.exists(f'{P}-{c}-final.jpg'))

    tr, ok = '', 0
    for r in audit:
        if r.get('status') in ('рисует модель', 'частично закрыт'):
            continue
        bad = ', '.join(r.get('bad') or []) or '—'
        ok += bad == '—'
        how = '3D-модель' if r['role'] in build.get('mesh_roles', []) else 'фото'
        tr += (f'<tr{" class=\'bad\'" if bad != "—" else ""}><td>{r["cam"]}</td>'
               f'<td>{r["role"]}</td><td>{how}</td><td class="n">{r.get("width", "—")}</td>'
               f'<td class="n">{r.get("height", "—")}</td><td>{bad}</td></tr>')
    checked = len([r for r in audit if r.get('status') not in ('рисует модель', 'частично закрыт')])
    table = ('<div class="scroll"><table><tr><th>вид</th><th>предмет</th><th>чем показан</th>'
             f'<th>ширина</th><th>высота</th><th>замечания</th></tr>{tr}</table></div>')

    # Что вообще известно о товарах: показываем ВСЕ поля карточки, чтобы владелец видел, из чего
    # модель может читать материал и цвет, а чего в фиде просто нет.
    fields = ['name', 'w', 'd', 'h', 'price', 'shop', 'wood', 'metal', 'fabric', 'cls', 'rgb',
              'style']
    meta_head = ''.join(f'<th>{f}</th>' for f in fields)
    meta_rows = ''
    for role, it in s_items.items():
        tds = ''
        for f in fields:
            v = it.get(f)
            v = '—' if v in (None, 'None', '') else str(v)[:46]
            tds += f'<td>{html.escape(v)}</td>'
        meta_rows += f'<tr><td><b>{html.escape(role)}</b></td>{tds}</tr>'
    meta_table = ('<div class="scroll"><table><tr><th>роль</th>' + meta_head +
                  f'</tr>{meta_rows}</table></div>')

    cards, total = '', 0
    for role, it in s_items.items():
        try:
            thumb = f'<img src="{uri(product(n, role)[1], 320, 80)}" alt="">'
        except Exception:  # noqa: BLE001 — нет фото: карточка без картинки
            thumb = ''
        total += int(it.get('price') or 0)
        cards += (f'<figure class="prod">{thumb}<figcaption>'
                  f'<b>{html.escape(role)}</b>'
                  f'<span>{html.escape(str(it.get("name"))[:52])}</span>'
                  f'<em>{money(it.get("price") or 0)} ₽</em>'
                  f'<span class="shop">{html.escape(str(it.get("shop")))}</span>'
                  f'</figcaption></figure>')

    out = f'''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Комплект {n} — весь пакет: вход, выход, товары</title>
<style>{CSS}</style>
<div class="w">
<h1>Комплект {n} — весь пакет</h1>
<p class="sub">Гостиная {html.escape(str(s.get('band', '')))} м², стиль
{html.escape(str(s.get('style', '')))}. Ровно то, что ушло в модель, ровно то, что она вернула,
приёмка и товары комплекта.</p>

<section class="card"><h2>Счёт</h2>
<div class="score">
<div><b>${cost['cost_usd']}</b><span>за оба кадра</span></div>
<div><b>≈{cost['cost_usd'] * 80 / 2:.0f} ₽</b><span>за кадр</span></div>
<div><b>{cost['usage'].get('input_tokens', 0)}</b><span>токенов на входе</span></div>
<div><b>{len(build.get('mesh_roles', []))}</b><span>3D-моделей, ≈{len(build.get('mesh_roles', [])) * 1.6:.0f} ₽ разово</span></div>
</div>
<p>Один запрос на оба вида — свет и материалы совпадают по построению, а не по уговорам.
Модели товаров кэшируются по товару: в следующих комплектах эти же вещи бесплатны.</p>
</section>

{blocks}

<section class="card"><h2>Выход — два кадра после разреза</h2>{frames}</section>

<section class="card"><h2>Приёмка коллажа перед отправкой</h2>
<p>Конвейер сам сверил каждый предмет с его местом в кадре: {ok} из {checked} позиций без
замечаний. Не прошедшие отправлены по решению владельца.</p>
{table}</section>

<section class="card"><h2>Текст запроса</h2><pre>{html.escape(prompt)}</pre></section>

<section class="card"><h2>Что мы знаем о товарах — всё, что даёт фид</h2>
<p>Из этого модель читает материал и цвет. Прочерк — поля в фиде нет: у пуфа не пришли ни ткань,
ни дерево, поэтому цвет мы считаем сами по фотографии товара (<code>rgb</code>) и кладём в запрос.</p>
{meta_table}</section>

<section class="card"><h2>Товары комплекта — {len(s['items'])} позиций, {money(total)} ₽</h2>
<div class="grid">{cards}</div></section>
</div>'''
    dst = f'{P}-pack.html'
    open(dst, 'w').write(out)
    print(dst)


if __name__ == '__main__':
    main()
