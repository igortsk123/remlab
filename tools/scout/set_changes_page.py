#!/usr/bin/env python3
"""Страница «что поменялось в комплектах» — то, ради чего журнал и заводился.

Владелец: «результат человек видит изменённый сет». Значит нужна не запись в БД, а страница,
на которой видно ЧТО поменялось, ПОЧЕМУ и КАК это выглядит: старый товар рядом с новым.

Публикуется на единый хаб `/test/` (правило владельца 11.08).

  ~/venvs/scout/bin/python set_changes_page.py            # собрать локально
  ~/venvs/scout/bin/python set_changes_page.py --publish  # собрать и выложить
"""
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SETS = os.path.join(HERE, 'sets3.json')
CAND = os.path.join(HERE, 'candidates-index.json')
OUT = os.path.expanduser('~/scout-scenes/set-changes')
DAYS = int(os.environ.get('CHANGES_DAYS', '14'))


def _cards() -> dict:
    try:
        return json.load(open(CAND)).get('items', {})
    except Exception:  # noqa: BLE001
        return {}


def _rows():
    from heal_policy import db, init
    init()
    return db("select at::date, set_id, slot, coalesce(old_sku,''), coalesce(new_sku,''), reason "
              f"from set_changes where at > now() - interval '{DAYS} days' order by at desc")


def build() -> str:
    cards = _cards()
    sets = {s.get('set_id'): s for s in json.load(open(SETS))}
    try:
        rows = [r for r in _rows() if len(r) >= 6]
    except Exception as e:  # noqa: BLE001 — без БД честно скажем, а не покажем пустую страницу
        rows = []
        err = f'{type(e).__name__}: {e}'
    else:
        err = None

    REASON = {'out_of_stock': 'пропало наличие', 'dead_photo': 'умерло фото',
              'bad_photo': 'негодное фото', 'contract_fail': 'не прошёл контракт',
              'bad_mesh': 'брак меша'}

    def cell(sku):
        it = cards.get(sku) or {}
        img = it.get('img') or ''
        if img.startswith('//'):
            img = 'https:' + img
        name = html.escape(str(it.get('name') or sku))
        pic = f'<img src="{html.escape(img)}" alt="" loading="lazy">' if img else '<div class="no"></div>'
        return f'<figure>{pic}<figcaption>{name}</figcaption></figure>'

    body = []
    for at, sid, slot, old, new, reason in rows:
        s = sets.get(sid) or {}
        title = f"{s.get('band', '?')} м² · {s.get('tier', '')} · {s.get('style', '')}".strip(' ·')
        body.append(
            f'<article><header><span class="d">{html.escape(at)}</span>'
            f'<b>{html.escape(slot)}</b> в комплекте <code>{html.escape(sid)}</code>'
            f'<span class="s">{html.escape(title)}</span>'
            f'<span class="why">{html.escape(REASON.get(reason, reason))}</span></header>'
            f'<div class="pair">{cell(old)}<span class="arrow">→</span>{cell(new)}</div></article>')

    note = ('<p class="err">Журнал недоступен: ' + html.escape(err) + '</p>') if err else ''
    empty = '<p class="empty">За последние %d дней автозамен не было.</p>' % DAYS
    return TEMPLATE.replace('{{BODY}}', '\n'.join(body) or (note or empty)) \
                   .replace('{{N}}', str(len(rows))).replace('{{DAYS}}', str(DAYS))


TEMPLATE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Замены в комплектах</title><style>
:root{--paper:#f6f7f8;--card:#fff;--ink:#151d24;--ink2:#4a565f;--line:#dfe4e7;--accent:#276876}
@media (prefers-color-scheme:dark){:root{--paper:#10161a;--card:#161d22;--ink:#e7ecee;
  --ink2:#a5b1b7;--line:#263037;--accent:#6fb6c4}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.6 "IBM Plex Sans",-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:48px 24px 80px}
h1{font:600 2rem/1.15 Georgia,serif;margin:0 0 .4rem}
.lede{color:var(--ink2);max-width:60ch;margin:0 0 32px}
article{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:16px 18px;
  margin-bottom:14px}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin-bottom:12px;font-size:.92rem}
.d{font-family:"IBM Plex Mono",monospace;color:var(--ink2);font-size:.82rem}
.s{color:var(--ink2)}
.why{margin-left:auto;color:var(--accent);font-weight:500}
code{font-family:"IBM Plex Mono",monospace;font-size:.85em;color:var(--ink2)}
.pair{display:flex;align-items:center;gap:18px}
figure{margin:0;flex:1;min-width:0;text-align:center}
figure img{width:100%;max-width:240px;height:170px;object-fit:contain;background:#fff;
  border:1px solid var(--line);border-radius:2px}
.no{height:170px;border:1px dashed var(--line);border-radius:2px}
figcaption{font-size:.84rem;color:var(--ink2);margin-top:6px;overflow-wrap:anywhere}
.arrow{font-size:1.6rem;color:var(--accent);flex:0 0 auto}
.empty,.err{color:var(--ink2)}
</style></head><body><div class="wrap">
<h1>Замены в комплектах</h1>
<p class="lede">Что автоматика поменяла за последние {{DAYS}} дней и почему. Слева — товар,
который выбыл, справа — тот, что встал на его место. Замена ставится только на товар с уже
готовым мешом, иначе слот честно остаётся пустым.</p>
<p class="lede">Записей: {{N}}</p>
{{BODY}}
</div></body></html>"""


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, 'index.html')
    open(dst, 'w', encoding='utf-8').write(build())
    print(f'OK → {dst}')
    if '--publish' in sys.argv:
        subprocess.run(['scp', '-q', '-P', '22222', dst,
                        'root@89.167.127.0:/tmp/set-changes.html'], check=True)
        subprocess.run(['ssh', '-p', '22222', 'root@89.167.127.0',
                        'mkdir -p /opt/remlab/test/set-changes && '
                        'mv /tmp/set-changes.html /opt/remlab/test/set-changes/index.html'],
                       check=True)
        print('опубликовано: /test/set-changes/')


if __name__ == '__main__':
    main()
