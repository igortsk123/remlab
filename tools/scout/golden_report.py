#!/usr/bin/env python3
"""Страница владельцу: какая модель размечает каталог и во что это обойдётся.

Показываем не «мы выбрали модель», а на чём выбор основан: согласие с эталоном по каждому полю,
отдельно на трудных карточках, цена за тысячу товаров и позиции, где эталон сам под вопросом.

  ~/venvs/scout/bin/python golden_report.py
"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/golden')
POOL = 26114          # товаров в пуле гостиной (view lr_roles)

from golden_eval import PRICES, agree, styles_close, ci, FIELDS  # noqa: E402


def load(name: str) -> dict:
    return json.load(open(os.path.join(HERE, name)))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    golden = {f'{i["mid"]}:{i["eid"]}': i for i in load('golden.json')}
    ref = load('golden-ref.json')
    cands = [load(f) for f in sorted(os.listdir(HERE))
             if f.startswith('golden-') and f.endswith('.json')
             and f not in ('golden-ref.json', 'golden-probe.json', 'golden.json',
                           'golden-suspects.json')]

    rows = []
    for c in cands:
        common = [k for k in ref['labels'] if k in c['labels']]
        h = {f: [agree(ref['labels'][k], c['labels'][k], f) for k in common] for f in FIELDS}
        h['materials'] = [agree(ref['labels'][k], c['labels'][k], 'materials') for k in common]
        h['styles'] = [styles_close(ref['labels'][k], c['labels'][k]) for k in common]
        pin, pout = PRICES.get(c['model'], (0, 0))
        u = c['usage']
        per1000 = (u['in'] / len(common) * pin + u['out'] / len(common) * pout) / 1e6 * 1000
        hard = [x for k, x in zip(common, h['role']) if golden[k]['hard']]
        rows.append(dict(model=c['model'], h=h, common=common, per1000=per1000,
                         hard=sum(hard) / max(len(hard), 1), labels=c['labels']))
    rows.sort(key=lambda r: -sum(r['h']['role']) / len(r['common']))
    win = rows[0]

    def pct(v):
        return f'{v * 100:.0f}%'

    trs = []
    for r in rows:
        n = len(r['common'])
        p, lo, hi = ci(r['h']['role'])
        s, slo, shi = ci(r['h']['functional_subtype'])
        cls = ' class="win"' if r is win else ''
        trs.append(
            f'<tr{cls}><td class="m">{html.escape(r["model"])}</td>'
            f'<td>{pct(p)} <span class="ci">{lo*100:.0f}–{hi*100:.0f}</span></td>'
            f'<td>{pct(s)} <span class="ci">{slo*100:.0f}–{shi*100:.0f}</span></td>'
            f'<td>{pct(sum(r["h"]["primary_color"])/n)}</td>'
            f'<td>{pct(sum(r["h"]["materials"])/n)}</td>'
            f'<td>{pct(sum(r["h"]["styles"])/n)}</td>'
            f'<td>{pct(r["hard"])}</td>'
            f'<td class="cost">{r["per1000"]:.2f} $</td>'
            f'<td class="cost">{r["per1000"] * POOL / 1000:.0f} $</td></tr>')

    # где победитель ошибается чаще всего — по ролям фида
    by_role: dict[str, list] = {}
    for k, ok in zip(win['common'], win['h']['functional_subtype']):
        by_role.setdefault(golden[k]['role_feed'], []).append(ok)
    role_rows = ''.join(
        f'<tr><td>{html.escape(r)}</td><td>{len(v)}</td><td>{pct(sum(v)/len(v))}</td></tr>'
        for r, v in sorted(by_role.items(), key=lambda kv: sum(kv[1]) / len(kv[1])))

    sus = load('golden-suspects.json')['suspects'] if os.path.exists(
        os.path.join(HERE, 'golden-suspects.json')) else []
    sus_rows = ''.join(
        f'<tr><td>{html.escape(golden[s["key"]]["name"][:70])}</td>'
        f'<td>{html.escape(golden[s["key"]]["cat"][:40])}</td>'
        f'<td class="bad">{html.escape(s["ref"])}</td>'
        f'<td class="ok">{html.escape(s["cands"])}</td></tr>' for s in sus)

    css = """
:root{--bg:#f6f5f2;--panel:#fff;--ink:#191817;--dim:#6b6862;--line:#e3dfd8;--acc:#3d6b52;
      --bad:#9c3b2e;--chip:#eeebe4}
@media (prefers-color-scheme:dark){:root{--bg:#14140f;--panel:#1d1d18;--ink:#eeeae2;--dim:#a09b91;
      --line:#302e28;--acc:#7fb894;--bad:#e08b7c;--chip:#26241f}}
:root[data-theme=dark]{--bg:#14140f;--panel:#1d1d18;--ink:#eeeae2;--dim:#a09b91;--line:#302e28;
      --acc:#7fb894;--bad:#e08b7c;--chip:#26241f}
:root[data-theme=light]{--bg:#f6f5f2;--panel:#fff;--ink:#191817;--dim:#6b6862;--line:#e3dfd8;
      --acc:#3d6b52;--bad:#9c3b2e;--chip:#eeebe4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:34px 20px 70px}
h1{font-size:28px;margin:0 0 8px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
   margin:34px 0 12px;font-weight:600}
.lede{color:var(--dim);max-width:70ch;margin:0 0 6px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:4px 18px 14px;
     overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14.5px}
th{text-align:right;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;
   color:var(--dim);font-weight:600;padding:12px 8px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:right}
tr:last-child td{border-bottom:none}
.m{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13.5px}
.win td{background:color-mix(in srgb,var(--acc) 10%,transparent);font-weight:600}
.ci{color:var(--dim);font-size:12px;font-weight:400}
.cost{color:var(--acc)}
.bad{color:var(--bad)}
.ok{color:var(--acc)}
.note{color:var(--dim);font-size:14px;margin-top:10px}
b{color:var(--ink)}
"""
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Выбор модели для разметки каталога</title><style>{css}</style></head><body><div class="wrap">
<h1>Какая модель будет размечать каталог</h1>
<p class="lede">Выборка — {len(golden)} товаров: все роли, три ценовые ступени, половина
«трудных» (без описания или с дырами в размерах). Эталон размечен сильной моделью
<b>{html.escape(ref['model'])}</b>; кандидаты сравниваются с ним.</p>

<h2>Согласие с эталоном и цена</h2>
<div class="box"><table>
<thead><tr><th>модель</th><th>роль</th><th>функция</th><th>цвет</th><th>материал</th>
<th>стиль</th><th>роль на трудных</th><th>за 1000 тов.</th><th>весь пул 26 114</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
<p class="note">В скобках — доверительный интервал: на {len(golden)} товарах разница в пару
процентов ничего не значит. Цена по официальному прайсу на 05.08.2026; массовый прогон идёт
пакетом со скидкой 50%, то есть вдвое дешевле указанного.</p></div>

<h2>Где победитель ошибается — по ролям (совпадение функции)</h2>
<div class="box"><table>
<thead><tr><th>роль в фиде</th><th>товаров</th><th>совпало</th></tr></thead>
<tbody>{role_rows}</tbody></table>
<p class="note">Функция — это не категория: банкетка не пуф, тумба под телевизор не комод.
Именно она задаёт правила размеров, поэтому её точность важнее точности роли.</p></div>

<h2>Спорные позиции — тут, возможно, ошибается эталон</h2>
<div class="box"><table>
<thead><tr><th>товар</th><th>категория магазина</th><th>эталон</th><th>все кандидаты</th></tr></thead>
<tbody>{sus_rows or '<tr><td colspan="4">расхождений нет</td></tr>'}</tbody></table>
<p class="note">Все кандидаты сказали одно и то же, а эталон — другое. Скажите, кто прав, и я
поправлю эталон: он размечен моделью, а не человеком, и на этих позициях ему верить нельзя.</p></div>

<h2>Что это значит для следующего шага</h2>
<div class="box"><p class="note">Разметка всего пула гостиной ({POOL} товаров) моделью
<b>{html.escape(win['model'])}</b> обойдётся примерно
<b>{win['per1000'] * POOL / 1000 / 2:.0f} $</b> пакетом. Дальше платим только за изменения:
после К1 мы видим, что за прогон меняет семантику, а что — только цену.</p></div>
</div></body></html>"""
    p = os.path.join(OUT, 'golden.html')
    open(p, 'w').write(page)
    print(f'отчёт: {p}')


if __name__ == '__main__':
    main()
