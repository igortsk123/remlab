#!/usr/bin/env python3
"""Прозрачность солвера (владелец 10.08: «на стороне солвера всё прозрачно,
без споров; судья — только GPT»): авто-страница ВСЕХ правил движка.

Генерится напрямую из файлов правил (occupancy/severity/weights/zones) и
docs/kb-rules-classification.json — единый источник, ручных текстов нет,
разойтись с движком не может. Публикация: /opt/remlab/test/rules/.

  ~/venvs/scout/bin/python rules_page.py [--publish]
"""
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules')
CLASSIF = os.path.join(HERE, '..', '..', 'docs', 'kb-rules-classification.json')
OUT = os.path.expanduser('~/scout-scenes/rules-page')

occ = json.load(open(os.path.join(RULES, 'occupancy.json')))
sev = json.load(open(os.path.join(RULES, 'severity.json')))['codes']
zones = json.load(open(os.path.join(RULES, 'zones.json')))
classif = {}
if os.path.exists(CLASSIF):
    classif = {r['param']: r for r in json.load(open(CLASSIF))['rows']}

d = occ['distances_cm']
rows = []
for k in sorted(d):
    if k.startswith('_'):
        continue
    note = d.get(f'_note_{k}', '')
    cl = classif.get(k)
    src = 'книга (пруф в классификации)' if cl and cl['verdict'] == 'SUPPORTED' \
        else (cl['verdict'] if cl else '')
    rows.append(f"<tr><td><code>{html.escape(k)}</code></td>"
                f"<td class='num'>{html.escape(json.dumps(d[k]))}</td>"
                f"<td>{html.escape(src)}</td>"
                f"<td>{html.escape(str(note)[:220])}</td></tr>")

sev_rows = []
for code in sorted(sev):
    sev_rows.append(f"<tr><td><code>{html.escape(code)}</code></td>"
                    f"<td>{html.escape(sev[code])}</td></tr>")

grp_rows = []
for g in zones.get('seating_groups', []):
    req = ', '.join(g['roles'].get('required', []))
    grp_rows.append(f"<tr><td><code>{html.escape(g['id'])}</code></td>"
                    f"<td class='num'>{g.get('footprint_m2')}</td>"
                    f"<td class='num'>{g.get('seats')}</td>"
                    f"<td>{html.escape(req)}</td></tr>")

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Правила солвера RemLab — прозрачный свод</title>
<style>
body{{margin:0;background:#fff;color:#1A1F1C;font:15px/1.5 system-ui,sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:22px 14px 60px}}
h1{{font-size:21px;margin:0 0 4px}} .sub{{color:#5C655E;font-size:13.5px;margin:0 0 18px}}
h2{{font-size:17px;margin:26px 0 8px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
td,th{{border-bottom:1px solid #EDEFEC;padding:5px 8px;text-align:left;vertical-align:top}}
th{{color:#5C655E}} td.num{{white-space:nowrap;font-variant-numeric:tabular-nums}}
.note{{margin:14px 0;padding:10px 12px;border-left:3px solid #3B76A2;background:#F4F7FA;
font-size:13.5px;color:#3A423C}}
</style></head><body><div class="wrap">
<h1>Правила солвера — прозрачный свод</h1>
<p class="sub">Автогенерация из файлов правил движка (единый источник; ручных текстов нет).
Решения на стороне солвера — только детерминированные: жёсткие проверки → мягкие штрафы →
лексикографический отбор. Единственный судья — GPT (terra-vision), он предлагает ходы,
солвер перепроверяет и принимает только при улучшении.</p>
<div class="note">Любая правка этих файлов проходит: тест совместимости пар правил →
полную приёмку 252 сцены («ни одна не хуже») → при регрессе — автоматический бисект
виновника. Классы сил: правки hard-слоя может предлагать только кодовое свидетельство
(класс-гейт), рекомендации живут в preferred.</div>

<h2>Числовые нормы (см) — distances_cm ({len(rows)})</h2>
<table><tr><th>Параметр</th><th>Значение</th><th>Сверка с книгой</th><th>Комментарий/пруф</th></tr>
{''.join(rows)}</table>

<h2>Коды проверок и классы ({len(sev_rows)})</h2>
<p class="sub">H0 — физика (брак), H1 — обязательное, S1/S2 — мягкие штрафы.</p>
<table><tr><th>Код</th><th>Класс</th></tr>{''.join(sev_rows)}</table>

<h2>Посадочные группы ({len(grp_rows)})</h2>
<table><tr><th>Группа</th><th>м²</th><th>мест</th><th>Обязательные роли</th></tr>
{''.join(grp_rows)}</table>
</div></body></html>"""

os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, 'index.html'), 'w').write(page)
print(f'OK → {OUT}/index.html ({len(rows)} чисел, {len(sev_rows)} кодов)')
if '--publish' in sys.argv:
    subprocess.run(['scp', '-q', os.path.join(OUT, 'index.html'),
                    'root@89.167.127.0:/tmp/rules-index.html'], check=True)
    subprocess.run(['ssh', 'root@89.167.127.0',
                    'mkdir -p /opt/remlab/test/rules && '
                    'mv /tmp/rules-index.html /opt/remlab/test/rules/index.html'],
                   check=True)
    print('опубликовано: /test/rules/')
