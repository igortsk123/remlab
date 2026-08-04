#!/usr/bin/env python3
"""Страница «весь процесс по шагам»: что отправили, в какую модель, что получили.

Владелец: «хочу весь процесс видеть в каждом кейсе по ссылке — шаг 1 отправил то-то, шаг 2 модель
сделала то-то». Журнал пишет `steps.py` во время прогона; здесь он разворачивается в страницу.

  ~/venvs/scout/bin/python process_report.py 21 --cams C1,C2
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


def uri(path, maxpx=900, q=84):
    try:
        im = Image.open(path).convert('RGB')
    except OSError:
        return ''
    im.thumbnail((maxpx, maxpx))
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=q, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()


def thumbs(paths, cls):
    out = []
    for p in paths[:9]:
        u = uri(p)
        if u:
            out.append(f'<figure class="{cls}"><img src="{u}" loading="lazy" alt="">'
                       f'<figcaption>{html.escape(os.path.basename(p))}</figcaption></figure>')
    return ''.join(out)


def step_block(st):
    par = ''.join(
        f'<tr><td>{html.escape(str(k))}</td>'
        f'<td>{html.escape(json.dumps(v, ensure_ascii=False)[:220])}</td></tr>'
        for k, v in st['params'].items())
    prompt = (f'<p class="lbl">Текст запроса</p><pre>{html.escape(st["prompt"])}</pre>'
              if st['prompt'] else '')
    return f'''<section class="step">
  <h3><span class="num">Шаг {st['n']}</span> {html.escape(st['title'])}</h3>
  <p class="model">Исполнитель: <b>{html.escape(st['model'])}</b> · {html.escape(st['ts'])}</p>
  {f'<p class="note">{html.escape(st["note"])}</p>' if st['note'] else ''}
  <div class="io">
    <div><p class="lbl">Отправляем</p><div class="row">{thumbs(st['inputs'], 'in')}</div></div>
    <div><p class="lbl">Получаем</p><div class="row">{thumbs(st['outputs'], 'out')}</div></div>
  </div>
  {prompt}
  {f'<table>{par}</table>' if par else ''}
</section>'''


def main():
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]
    parts = []
    for cam in cams:
        prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
        path = f'{prefix}-steps.json'
        if not os.path.exists(path):
            continue
        steps = json.load(open(path))
        blocks = ''.join(step_block(st) for st in steps)
        # Итог — выход ПОСЛЕДНЕГО шага журнала, а не файл с «правильным» именем: иначе на
        # странице висит артефакт прошлого прогона (владелец поймал серый куб вместо пуфа).
        final = ''
        for st in reversed(steps):
            outs = [o for o in st['outputs'] if o.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if outs:
                final = (f'<figure class="big"><img src="{uri(outs[0], 1500)}" alt="итог">'
                         f'<figcaption>Итог этого вида — шаг {st["n"]}: '
                         f'{html.escape(st["title"])}</figcaption></figure>')
                break
        parts.append(f'<h2>Вид {html.escape(cam)}</h2>{final}{blocks}')

    out = os.path.join(SCENE_DIR, f'scene{n}-process.html')
    open(out, 'w').write(f'''<meta charset="utf-8"><title>Комплект {n} — весь процесс по шагам</title>
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
.w {{ max-width:1120px; margin:0 auto; padding:42px 20px 76px; }}
h1 {{ font-family:"Iowan Old Style",Georgia,serif; font-size:clamp(25px,4vw,36px); margin:0 0 6px; }}
h2 {{ font-family:"Iowan Old Style",Georgia,serif; font-size:23px; margin:46px 0 12px; }}
h3 {{ font-size:17px; margin:0 0 4px; }}
.sub {{ color:var(--soft); margin-bottom:22px; }}
.step {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:16px 18px; margin-bottom:16px; }}
.num {{ display:inline-block; background:var(--accent); color:#fff; border-radius:999px;
  padding:2px 10px; font-size:13px; margin-right:8px; vertical-align:middle; }}
.model {{ color:var(--soft); font-size:14px; margin:0 0 8px; }}
.note {{ color:var(--soft); font-size:14.5px; margin:0 0 10px; }}
.lbl {{ font-size:12px; letter-spacing:.09em; text-transform:uppercase; color:var(--accent);
  margin:10px 0 6px; }}
.io {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:720px) {{ .io {{ grid-template-columns:1fr; }} }}
.row {{ display:flex; flex-wrap:wrap; gap:10px; }}
figure {{ margin:0; background:var(--bg); border:1px solid var(--line); border-radius:10px;
  overflow:hidden; max-width:210px; }}
figure img {{ display:block; width:100%; height:auto; }}
figure figcaption {{ font-size:11px; color:var(--soft); padding:5px 7px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
figure.big {{ max-width:100%; margin-bottom:14px; }}
pre {{ white-space:pre-wrap; background:var(--bg); border-left:3px solid var(--accent);
  padding:9px 12px; margin:6px 0 0; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }}
table {{ border-collapse:collapse; width:100%; margin-top:10px; font-size:13px; }}
td {{ border-top:1px solid var(--line); padding:4px 8px; vertical-align:top; }}
td:first-child {{ color:var(--soft); width:32%; }}
</style>
<div class="w">
<h1>Комплект {n} — весь процесс по шагам</h1>
<div class="sub">Гостиная {s.get('band', '')} м² · стиль {s.get('style', '')} ·
каждый шаг: что отправили, кто исполнитель, что получили</div>
{''.join(parts) or '<p>Журнал пуст — прогоните сцену заново.</p>'}
</div>''')
    print(out)


if __name__ == '__main__':
    main()
