#!/usr/bin/env python3
"""Страница «один запрос — один ответ»: что уходит в модель и что возвращается.

Владелец просил посмотреть живой обмен целиком: фото товара, точный текст запроса, схему ответа,
сырой JSON от модели и то, как из него собрался стиль — по шагам, с рангом каждого признака.

  ~/venvs/scout/bin/python one_request_page.py
"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser('~/scout-backups/one-request.json')
OUT = os.path.expanduser('~/scout-scenes/golden/one-request.html')
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
W = {'маркер': 3.0, 'поддержка': 1.5, 'фон': 0.6}

CSS = """
:root{--bg:#f6f5f2;--panel:#fff;--ink:#191817;--dim:#6b6862;--line:#e3dfd8;--acc:#3d6b52;
      --bad:#9c3b2e;--chip:#eeebe4;--code:#f2f0eb}
@media (prefers-color-scheme:dark){:root{--bg:#14140f;--panel:#1d1d18;--ink:#eeeae2;--dim:#a09b91;
      --line:#302e28;--acc:#7fb894;--bad:#e08b7c;--chip:#26241f;--code:#211f1b}}
:root[data-theme=dark]{--bg:#14140f;--panel:#1d1d18;--ink:#eeeae2;--dim:#a09b91;--line:#302e28;
      --acc:#7fb894;--bad:#e08b7c;--chip:#26241f;--code:#211f1b}
:root[data-theme=light]{--bg:#f6f5f2;--panel:#fff;--ink:#191817;--dim:#6b6862;--line:#e3dfd8;
      --acc:#3d6b52;--bad:#9c3b2e;--chip:#eeebe4;--code:#f2f0eb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 70px}
h1{font-size:27px;margin:0 0 6px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
   margin:32px 0 10px;font-weight:600}
.lede{color:var(--dim);max-width:70ch;margin:0 0 4px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
     overflow-x:auto}
.card{display:flex;gap:18px;align-items:flex-start}
.card img{width:230px;border-radius:10px;background:#fff}
.meta div{font-size:14px;color:var(--dim);margin-bottom:3px}
.meta b{color:var(--ink)}
pre{margin:0;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;
    color:var(--ink);background:var(--code);border-radius:8px;padding:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
   padding:9px 8px;border-bottom:1px solid var(--line);font-weight:600}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.m{background:color-mix(in srgb,var(--acc) 22%,transparent);border-radius:5px;padding:1px 7px;
   font-size:12.5px;white-space:nowrap}
.s{background:color-mix(in srgb,var(--acc) 11%,transparent);border-radius:5px;padding:1px 7px;
   font-size:12.5px;white-space:nowrap}
.f{background:var(--chip);border-radius:5px;padding:1px 7px;font-size:12.5px;white-space:nowrap}
.neg{background:color-mix(in srgb,var(--bad) 16%,transparent)}
.bars div{display:flex;align-items:center;gap:10px;margin:5px 0;font-variant-numeric:tabular-nums}
.bars span.n{width:120px;font-size:14px}
.bars span.b{height:16px;border-radius:4px;background:var(--acc);display:inline-block}
.bars span.v{font-size:14px;color:var(--dim)}
.note{color:var(--dim);font-size:13.5px;margin-top:8px}
"""


def main() -> None:
    d = json.load(open(SRC))
    it = d['item']
    img = it['img']
    img = 'https:' + img if img.startswith('//') else img
    dims = ' × '.join(str(int(v)) for v in (it.get('w'), it.get('d'), it.get('h')) if v)

    rows = []
    for attr, val, tiers, why in d['fired']:
        cells = []
        for st, t in tiers.items():
            w = W[t['tier']] * t.get('sign', 1)
            cls = {'маркер': 'm', 'поддержка': 's', 'фон': 'f'}[t['tier']]
            if w < 0:
                cls += ' neg'
            cells.append(f'<span class="{cls}">{html.escape(st)} {w:+.1f}</span>')
        rows.append(f'<tr><td><b>{html.escape(attr)}</b> = {html.escape(str(val))}</td>'
                    f'<td>{" ".join(cells)}</td></tr>')

    sc = d['scores']
    mx = max(sc.values()) or 1
    bars = ''.join(
        f'<div><span class="n">{html.escape(s)}</span>'
        f'<span class="b" style="width:{sc[s] / 10 * 320:.0f}px"></span>'
        f'<span class="v">{sc[s]}</span></div>'
        for s in sorted(STYLES, key=lambda x: -sc[x]))

    kind = d['kind']
    kinds = ', '.join(f'{s}: маркеров {kind[s].get("маркер", 0)}, поддержки {kind[s].get("поддержка", 0)}'
                      for s in sorted(STYLES, key=lambda x: -sc[x])[:3])

    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Один запрос и ответ — как определяется стиль</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Один запрос и один ответ</h1>
<p class="lede">Живой обмен с моделью по одному товару: что уходит, что возвращается и как из
ответа собирается стиль.</p>

<h2>1. Товар</h2>
<div class="box card">
  <img src="{html.escape(img)}" alt="">
  <div class="meta">
    <div><b>{html.escape(it['name'])}</b></div>
    <div>категория из фида: <b>{html.escape(it['role_feed'])}</b></div>
    <div>размеры: {html.escape(dims or '—')} см</div>
    <div>цена: {it['price']:,} ₽</div>
    <div>магазин: {html.escape(it.get('shop') or '')}</div>
  </div>
</div>

<h2>2. Что уходит в модель — общая часть</h2>
<div class="box"><pre>{html.escape(d['sys'])}</pre></div>

<h2>3. Что уходит в модель — этот товар</h2>
<div class="box"><pre>{html.escape(d['user'])}</pre>
<p class="note">Вместе с текстом уходит сама фотография (ужата до 448 px, режим низкой детализации)
и строгая схема ответа: модель обязана выбрать одно из перечисленных значений, свой вариант
написать не может.</p></div>

<h2>4. Что вернула модель</h2>
<div class="box"><pre>{html.escape(json.dumps(d['answer'], ensure_ascii=False, indent=2))}</pre></div>

<h2>5. Как из ответа собрался стиль</h2>
<div class="box"><table>
<thead><tr><th>признак</th><th>что даёт стилям</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="note">Ранг определяет балл: маркер ±3.0, поддержка ±1.5, фон ±0.6. Признаков разглядено
{d['seen']}, уверенность {d['conf']}. {html.escape(kinds)}.</p></div>

<h2>6. Итог</h2>
<div class="box bars">{bars}
<p class="note">Баллы стилей сравниваются между собой внутри товара и переводятся в шкалу 0–10.
Стиль без единого положительного маркера высоко уйти не может.</p></div>
</div></body></html>"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(page)
    print(f'страница: {OUT}')


if __name__ == '__main__':
    main()
