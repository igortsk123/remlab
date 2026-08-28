#!/usr/bin/env python3
"""Страница «замены в комплектах» — утренний экран владельца.

ЧТО НА НЕЙ И ПОЧЕМУ ИМЕННО ЭТО. Первая версия показывала только журнал замен, и в день, когда
замен не было, открывалась пустой — то есть бесполезной. Но «сегодня ничего не менялось» — не
вся правда: важнее, ГОТОВА ли система менять, когда понадобится. Замена возможна только там,
где у слота есть запасной товар с уже сделанным мешом; где его нет — выбытие товара оставит дыру.

Поэтому три части, в порядке важности:
  1. готовность к замене — сколько занятых слотов имеют годную подмену (и сколько держатся
     на одном магазине: падение фида обнулит их резерв целиком);
  2. слоты без подмены — что сломается, если товар пропадёт именно там;
  3. журнал — что уже поменялось и почему.

Публикуется на единый хаб `/test/` (правило владельца 11.08).

  ~/venvs/scout/bin/python set_changes_page.py            # собрать локально
  ~/venvs/scout/bin/python set_changes_page.py --publish  # собрать и выложить
"""
import collections
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

REASON = {'out_of_stock': 'пропало наличие', 'dead_photo': 'умерло фото',
          'bad_photo': 'негодное фото', 'contract_fail': 'не прошёл контракт',
          'bad_mesh': 'брак меша'}


def _cards() -> dict:
    try:
        return json.load(open(CAND)).get('items', {})
    except Exception:  # noqa: BLE001
        return {}


def _journal():
    from heal_policy import db, init
    init()
    rows = db("select at::date, set_id, slot, coalesce(old_sku,''), coalesce(new_sku,''), reason "
              f"from set_changes where at > now() - interval '{DAYS} days' order by at desc")
    return [r for r in rows if len(r) >= 6]


def _coverage():
    import reserve
    return reserve.coverage()['rows']


def build() -> str:
    cards = _cards()
    sets = {s.get('set_id'): s for s in json.load(open(SETS))}
    errors = []
    try:
        rows = _journal()
    except Exception as e:  # noqa: BLE001 — честно скажем, а не покажем пустоту как факт
        rows, _ = [], errors.append(f'журнал недоступен: {type(e).__name__}: {e}')
    try:
        cov = _coverage()
    except Exception as e:  # noqa: BLE001
        cov, _ = [], errors.append(f'покрытие не посчитано: {type(e).__name__}: {e}')

    total = len(cov)
    ready = sum(1 for r in cov if r['ready'] >= r['target'])
    none_ready = [r for r in cov if r['ready'] == 0]
    one_shop = sum(1 for r in cov if r['ready'] >= r['target'] and r['shops'] < 2)
    pct = (100 * ready / total) if total else 0

    def title(sid):
        s = sets.get(sid) or {}
        return ' · '.join(x for x in (f"{s.get('band', '')} м²", s.get('tier'), s.get('style')) if x)

    def cell(sku):
        it = cards.get(sku) or {}
        img = it.get('img') or ''
        if img.startswith('//'):
            img = 'https:' + img
        name = html.escape(str(it.get('name') or sku or '—'))
        pic = (f'<img src="{html.escape(img)}" alt="" loading="lazy">' if img
               else '<div class="no"></div>')
        return f'<figure>{pic}<figcaption>{name}</figcaption></figure>'

    # ---- 1. готовность
    by_role = collections.defaultdict(lambda: [0, 0])
    for r in cov:
        b = by_role[r['role']]
        b[0] += 1
        b[1] += r['ready'] >= r['target']
    role_rows = ''.join(
        f'<tr><th scope="row">{html.escape(role)}</th><td>{n}</td><td>{ok}</td>'
        f'<td class="bar"><span style="width:{100 * ok / max(n, 1):.0f}%"></span></td></tr>'
        for role, (n, ok) in sorted(by_role.items(), key=lambda kv: -kv[1][0])[:14])

    state = ('ready' if pct >= 80 else 'warn' if pct >= 30 else 'bad')
    hint = ('Замена сработает почти везде.' if pct >= 80 else
            'Замена сработает не везде — часть слотов останется с дырой.' if pct >= 30 else
            'Готовых подмен нет: пока меши не сгенерированы, автозамена ставит обычный товар '
            'из запаса, а слот без запаса просто пустеет.')

    # ---- 2. слоты без подмены
    risk = collections.Counter(r['role'] for r in none_ready)
    risk_rows = ''.join(
        f'<li><b>{html.escape(role)}</b> — {n} слот(ов)</li>'
        for role, n in risk.most_common(10)) or '<li>таких слотов нет</li>'

    # ---- 3. журнал
    journal = []
    for at, sid, slot, old, new, reason in rows:
        journal.append(
            f'<article><header><span class="d">{html.escape(at)}</span>'
            f'<b>{html.escape(slot)}</b> в комплекте <code>{html.escape(sid)}</code>'
            f'<span class="s">{html.escape(title(sid))}</span>'
            f'<span class="why">{html.escape(REASON.get(reason, reason))}</span></header>'
            f'<div class="pair">{cell(old)}<span class="arrow">→</span>{cell(new)}</div></article>')
    journal_html = '\n'.join(journal) or (
        f'<p class="empty">За последние {DAYS} дней автозамен не было — значит, из комплектов '
        f'ничего не выбывало. Это нормальное состояние, а не ошибка страницы.</p>')

    err_html = ''.join(f'<p class="err">{html.escape(e)}</p>' for e in errors)

    return (TEMPLATE
            .replace('{{ERR}}', err_html)
            .replace('{{STATE}}', state)
            .replace('{{PCT}}', f'{pct:.0f}')
            .replace('{{READY}}', str(ready))
            .replace('{{TOTAL}}', str(total))
            .replace('{{ONESHOP}}', str(one_shop))
            .replace('{{NONE}}', str(len(none_ready)))
            .replace('{{HINT}}', html.escape(hint))
            .replace('{{ROLES}}', role_rows)
            .replace('{{RISK}}', risk_rows)
            .replace('{{JOURNAL}}', journal_html)
            .replace('{{DAYS}}', str(DAYS)))


TEMPLATE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Замены в комплектах</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&display=swap">
<style>
:root{--paper:#f6f7f8;--card:#fff;--ink:#151d24;--ink2:#4a565f;--ink3:#7d8990;--line:#dfe4e7;
  --line2:#eef1f3;--accent:#276876;--good:#2f6b45;--warn:#a5591c;--bad:#a33b32}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#10161a;--card:#161d22;
  --ink:#e7ecee;--ink2:#a5b1b7;--ink3:#76848b;--line:#263037;--line2:#1d262b;--accent:#6fb6c4;
  --good:#6fbf90;--warn:#d99a55;--bad:#e08a80}}
:root[data-theme="dark"]{--paper:#10161a;--card:#161d22;--ink:#e7ecee;--ink2:#a5b1b7;--ink3:#76848b;
  --line:#263037;--line2:#1d262b;--accent:#6fb6c4;--good:#6fbf90;--warn:#d99a55;--bad:#e08a80}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:16px/1.62 "IBM Plex Sans",-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:940px;margin:0 auto;padding:56px 24px 90px}
h1{font:600 2.1rem/1.13 Spectral,Georgia,serif;margin:0 0 .5rem;letter-spacing:-.01em}
h2{font:600 1.35rem/1.2 Spectral,Georgia,serif;margin:44px 0 6px}
.lede{color:var(--ink2);max-width:62ch;margin:0 0 8px}
.sub{color:var(--ink3);font-size:.92rem;margin:0 0 28px}
.gauge{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:22px 24px;
  display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.big{font:600 3rem/1 "IBM Plex Sans",sans-serif;font-variant-numeric:tabular-nums}
.gauge.ready .big{color:var(--good)}.gauge.warn .big{color:var(--warn)}.gauge.bad .big{color:var(--bad)}
.gtext{flex:1;min-width:240px}
.gtext p{margin:0 0 4px}
.gtext .nums{color:var(--ink2);font-size:.92rem}
table{border-collapse:collapse;width:100%;margin-top:14px;font-size:.93rem}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2)}
thead th{font:400 .72rem/1 "IBM Plex Mono",monospace;letter-spacing:.09em;text-transform:uppercase;
  color:var(--ink3)}
tbody th{font-weight:500}
td{font-variant-numeric:tabular-nums;color:var(--ink2)}
td.bar{width:38%}
td.bar span{display:block;height:7px;background:var(--accent);border-radius:2px;min-width:2px}
ul{margin:10px 0 0;padding-left:20px;color:var(--ink2)}
article{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:16px 18px;
  margin-bottom:14px}
article header{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin-bottom:12px;
  font-size:.92rem}
.d{font-family:"IBM Plex Mono",monospace;color:var(--ink3);font-size:.82rem}
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
.empty{color:var(--ink2);background:var(--card);border:1px solid var(--line);border-radius:3px;
  padding:16px 18px;margin:0}
.err{color:var(--bad)}
</style></head><body><div class="wrap">
<h1>Замены в комплектах</h1>
<p class="lede">Автоматика меняет товар в комплекте, когда он выбыл: пропало наличие, умерло
или оказалось негодным фото. Меняет только на запасной товар, у которого уже есть готовый меш —
иначе в визуализации будет дыра вместо починки.</p>
<p class="sub">Обновляется ночным прогоном.</p>
{{ERR}}

<h2>Готовность к замене</h2>
<div class="gauge {{STATE}}">
  <div class="big">{{PCT}}%</div>
  <div class="gtext">
    <p>{{HINT}}</p>
    <p class="nums">Слотов с готовой подменой: {{READY}} из {{TOTAL}} ·
       без подмены вовсе: {{NONE}} · держатся на одном магазине: {{ONESHOP}}</p>
  </div>
</div>
<table><thead><tr><th>роль</th><th>слотов</th><th>с подменой</th><th></th></tr></thead>
<tbody>{{ROLES}}</tbody></table>

<h2>Где замена не сработает</h2>
<p class="lede">Если товар выбудет здесь, слот останется пустым — подменить не на что.</p>
<ul>{{RISK}}</ul>

<h2>Что менялось</h2>
{{JOURNAL}}
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
