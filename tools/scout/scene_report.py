#!/usr/bin/env python3
"""Полный отчёт по сцене комплекта: что ОТПРАВЛЯЕМ в модель и что ПОЛУЧАЕМ.

Владелец проверяет визуально и хочет видеть весь набор по ссылке, а не по кускам в чате:
план → карта глубины (ровно та, что ушла) → маски объектов → clay → промпт и параметры запроса →
результат → результат с наложенным планом (сетка пола и следы предметов).

  ~/venvs/scout/bin/python scene_report.py 21              # все посчитанные виды
  ~/venvs/scout/bin/python scene_report.py 21 --views P,A
"""
import base64
import html
import io
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
VIEW_TITLE = {'A': 'Вид A — от ТВ на зону отдыха', 'B': 'Вид B — от дивана на ТВ-зону',
              'P': 'Панорама от двери — осмотреться', 'T': 'Вид сверху'}


def uri(path, maxpx=1800, q=85):
    if not os.path.exists(path):
        return ''
    im = Image.open(path).convert('RGB')
    im.thumbnail((maxpx, maxpx))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=q, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def depth_preview(prefix):
    """Карта глубины В ТОМ ВИДЕ, В КАКОМ ОНА УХОДИТ В МОДЕЛЬ (инвертированная)."""
    src = f'{prefix}-depth16.png'
    if not os.path.exists(src):
        return ''
    d = np.asarray(Image.open(src)).astype(np.float32)
    d = (d - d.min()) / max(d.max() - d.min(), 1e-6)
    img = Image.fromarray((((1.0 - d) ** 0.7) * 255).astype(np.uint8)).convert('RGB')
    img.thumbnail((1800, 1800))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def fig(src, title, text):
    if not src:
        return ''
    return (f'<figure><img src="{src}" alt="{html.escape(title)}" loading="lazy">'
            f'<figcaption><b>{html.escape(title)}</b><span>{text}</span></figcaption></figure>')


def view_block(n, view):
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{view}')
    meta_p = f'{prefix}-frame.json'
    if not os.path.exists(meta_p):
        return ''
    meta = json.load(open(meta_p))
    cam = meta['camera']
    req = json.load(open(f'{prefix}-request.json')) if os.path.exists(f'{prefix}-request.json') else {}
    visible = ', '.join(meta['visible']) or '—'
    behind = ', '.join(meta['behind']) or '—'
    params = {k: v for k, v in req.items()
              if k not in ('prompt', 'negative_prompt', 'controls', 'view')}
    rows = ''.join(f'<tr><td>{html.escape(str(k))}</td><td>{html.escape(json.dumps(v, ensure_ascii=False))}</td></tr>'
                   for k, v in params.items())
    prompt_txt = html.escape(req.get('prompt', '— (кадр ещё не генерировали)'))
    neg_txt = html.escape(req.get('negative_prompt', '—'))
    eye = ', '.join(f'{v:.0f}' for v in cam['eye'])
    return f'''
<h2>{html.escape(VIEW_TITLE.get(view, view))}</h2>
<p class="lead">Камера в точке ({eye}) см, объектив {cam['fov']:.0f}°, кадр
{cam['size'][0]}×{cam['size'][1]}. В кадре: <b>{html.escape(visible)}</b>.
Вне кадра: {html.escape(behind)}.</p>
{fig(depth_preview(prefix), 'Отправляем: карта глубины', 'Ровно этот файл уходит в модель как управляющий сигнал. Светлое ближе, тёмное дальше.')}
{fig(uri(f'{prefix}-instances.png'), 'Отправляем (пока не используем): маски объектов', 'У каждого предмета свой цвет-идентификатор. На Ф2 по этим маскам врисовываются конкретные товары.')}
{fig(uri(f'{prefix}-clay.png'), 'Наш собственный рендер сцены', 'Геометрия без генерации: стены, проёмы, объёмы предметов.')}
<details open><summary>Отправляем: текст запроса и параметры</summary>
<pre class="prompt">{prompt_txt}</pre>
<p class="sub2">Запрещаем (negative prompt):</p><pre class="prompt neg">{neg_txt}</pre>
<table>{rows}</table></details>
{fig(uri(f'{prefix}-base-sdxl.jpg'), 'Получаем: кадр', 'Результат генерации по карте глубины.')}
{''.join(fig(uri(f'{prefix}-{name}.jpg'), f'Три кадра из ЭТОЙ ЖЕ генерации — взгляд {ru}', 'Не отдельная генерация: обычный перспективный кадр вырезан из панорамы, поэтому свет и материалы совпадают с остальными видами по построению.') for name, ru in (('left', 'налево'), ('center', 'прямо'), ('right', 'направо')))}
{fig(uri(f'{prefix}-check.jpg'), 'Проверка: план поверх результата', 'Зелёные контуры — следы предметов по плану, белая сетка — метры пола, жёлтые точки — расстояние от камеры. Мебель на своих следах = масштаб верный.')}
'''


def main():
    n = int(sys.argv[1])
    views = (sys.argv[sys.argv.index('--views') + 1].split(',')
             if '--views' in sys.argv else ['P', 'A', 'B', 'T'])
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]
    plan = uri(os.path.join(SCENE_DIR, f'scene{n}-plan.png'), 1500)
    blocks = ''.join(view_block(n, v) for v in views)
    out = os.path.join(SCENE_DIR, f'scene{n}-report.html')
    open(out, 'w').write(f'''<meta charset="utf-8"><title>Комплект {n} — что отправляем и что получаем</title>
<style>
:root {{ --bg:#F5F6F4; --panel:#fff; --ink:#171C18; --soft:#5C655E; --line:#DFE3DC; --accent:#3F6B57; }}
@media (prefers-color-scheme:dark) {{ :root {{ --bg:#101410; --panel:#191E18; --ink:#E8ECE6;
  --soft:#9AA598; --line:#2A312A; --accent:#8FBFA3; }} }}
:root[data-theme="dark"] {{ --bg:#101410; --panel:#191E18; --ink:#E8ECE6; --soft:#9AA598;
  --line:#2A312A; --accent:#8FBFA3; }}
:root[data-theme="light"] {{ --bg:#F5F6F4; --panel:#fff; --ink:#171C18; --soft:#5C655E;
  --line:#DFE3DC; --accent:#3F6B57; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.w {{ max-width:1080px; margin:0 auto; padding:42px 20px 72px; }}
h1 {{ font-family:"Iowan Old Style",Georgia,serif; font-size:clamp(25px,4vw,36px); margin:0 0 6px;
  line-height:1.15; text-wrap:balance; }}
h2 {{ font-family:"Iowan Old Style",Georgia,serif; font-size:22px; margin:44px 0 4px; }}
.sub {{ color:var(--soft); margin-bottom:20px; }}
.sub2 {{ color:var(--soft); margin:12px 0 4px; font-size:14px; }}
.lead {{ color:var(--soft); margin:0 0 14px; }}
figure {{ margin:0 0 20px; background:var(--panel); border:1px solid var(--line);
  border-radius:14px; overflow:hidden; }}
figure img {{ display:block; width:100%; height:auto; }}
figcaption {{ padding:12px 15px; border-top:1px solid var(--line); font-size:14.5px; }}
figcaption b {{ display:block; margin-bottom:3px; }}
figcaption span {{ color:var(--soft); }}
details {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:14px 16px; margin-bottom:20px; }}
summary {{ cursor:pointer; font-weight:600; }}
pre.prompt {{ white-space:pre-wrap; background:transparent; border-left:3px solid var(--accent);
  padding:8px 12px; margin:10px 0 0; font:13.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }}
pre.neg {{ border-left-color:#A2493B; }}
table {{ border-collapse:collapse; width:100%; margin-top:12px; font-size:13.5px;
  font-variant-numeric:tabular-nums; }}
td {{ border-top:1px solid var(--line); padding:5px 8px; vertical-align:top; }}
td:first-child {{ color:var(--soft); width:32%; }}
</style>
<div class="w">
<h1>Комплект {n} — что отправляем в модель и что получаем</h1>
<div class="sub">Гостиная {s.get('band', '')} м² · стиль {s.get('style', '')} ·
комната 400 × 460 см · всё ниже посчитано из одного файла раскладки</div>
{fig(plan, 'План расстановки — источник для всего остального',
     'Красные точки — камеры и их сектор обзора. Синяя линия — окно, жёлтая — дверь.')}
{blocks}
</div>''')
    print(out)


if __name__ == '__main__':
    main()
