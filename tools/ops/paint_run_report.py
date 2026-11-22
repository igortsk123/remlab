#!/usr/bin/env python3
"""T-180/4 · сводка и страница прогона покраски — числа и кадры автоматом, не руками (владелец TG 1251).

ЗАЧЕМ: одно и то же число («сколько остановилось, сколько покрашено, сколько показано») считали по памяти и ошиблись; теперь его считает код
из тех же решений этапов, что воронка (`paint_funnel.analyse`), и сам проверяет, что сумма сходится.

ЧТО ДЕЛАЕТ (только чтение готового прогона; платного и нейросети нет):
  ① сводка — вошло N · остановились без крашеной модели (по этапам, с причиной каждого товара) · покрашено (есть итоговая модель `08-material/material.glb`;
     из них итог этапа 9: прошёл / мягко / не готов; строго — без «мягко») · кадров на странице. `summary.md` + `summary.json`.
     Самопроверка (`verify`): N совпало с числом папок товаров на диске; остановившиеся + покрашенные = N; сумма по этапам = остановившимся;
     у каждого остановившегося есть причина; кадров = покрашенным. Хоть одно не сошлось — ненулевой код возврата и строка «ОШИБКА СВОДКИ».
  ② страница — по ВСЕМ покрашенным «фото | наш 3D» (как `tex_visible`: итоговая текстура этапа 8 по растру камеры этапа 4, без света) + сводка сверху;
     один `index.html` без скриптов и кода доступа (телефон 375 и ПК), картинки JPEG ≤1600 px (кадр этапа 1536×1536 PNG Телеграм не берёт).
  Публикация — только `--publish` (rsync на `/opt/remlab/test/paint-<прогон>/`); по умолчанию страница лежит локально в `--out`.

«Покрашено» = у товара есть итоговая модель этапа 8: именно её можно показать. Остальные — «остановились»: этап — первый отказ (при отказе и «нет check.json» берётся отказ),
причина — слова самого конвейера (`paint_check`). ID товаров в код не попадают.

Запуск (обычно — само, в конце `paint_funnel.py`; отдельно так):
  python3 paint_run_report.py <прогон> [<прогон> …] [--out <папка>] [--name <имя>] [--publish]     # несколько прогонов — один набор (повтор sku берётся из первого)
Код возврата 0 — всё сошлось; 1 — самопроверка нашла расхождение или кадр не построился."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paint_funnel as pf  # noqa: E402

HOME = os.path.expanduser('~')
MODEL = os.path.join('08-material', 'material.glb')
MAX_SIDE = 1600
JPEG_Q = 88
REMOTE = 'root@89.167.127.0'
REMOTE_ROOT = '/opt/remlab/test'
URL_ROOT = 'https://remont-lab.online/test'
FINAL_WORDS = {'ok': 'прошёл', 'soft': 'мягко', 'refused': 'не готов', 'missing': 'этап 9 не запускался'}


def slug(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return 'paint-' + (s or 'run')


def stop_of(rows: list) -> tuple[str, str]:
    """Где остановился товар без крашеной модели: первый ОТКАЗ (пустой check.json раньше отказа — не причина, этап мог просто не писать его), иначе первый «нет check.json»."""
    for want in ('refused', 'missing'):
        for r in rows:
            if r['status'] == want:
                return r['stage'], (r.get('reason') or '').strip() or 'причина не записана'
    return rows[-1]['stage'] if rows else '—', 'все этапы прошли, но итоговой модели (08-material/material.glb) нет'


def summarise(per: dict, painted: set, label: str, n_dirs: int | None = None, frames: int | None = None) -> dict:
    """Сводка по `per` ({sku: [решения этапов]}) и множеству `painted` (sku с итоговой моделью). Чистая функция — считает и ничего не читает с диска."""
    stopped: dict = {}
    for sku in sorted(per):
        if sku in painted:
            continue
        st, why = stop_of(per[sku])
        stopped.setdefault(st, []).append({'sku': sku, 'reason': why})
    stages = [{'stage': st, 'count': len(v), 'items': v} for st, v in sorted(stopped.items())]
    fin = {'ok': 0, 'soft': 0, 'refused': 0, 'missing': 0}
    strict = 0
    prow = []
    for sku in sorted(per):
        if sku not in painted:
            continue
        rows = per[sku]
        last = next((r for r in rows if r['stage'] == pf.NINE), rows[-1])
        fin[last['status']] = fin.get(last['status'], 0) + 1
        is_strict = pf.passed_all(rows, True)
        strict += is_strict
        prow.append({'sku': sku, 'final': last['status'], 'strict': is_strict, 'reason': last.get('reason') or ''})
    s = {'label': label, 'n': len(per), 'n_dirs': n_dirs, 'stopped': sum(x['count'] for x in stages), 'stopped_by_stage': stages,
         'painted': len(painted & set(per)), 'painted_final': fin, 'painted_strict': strict, 'painted_items': prow, 'frames': frames}
    s['errors'] = verify(s)
    return s


def verify(s: dict) -> list:
    """Самопроверка сводки: каждое число считается двумя путями. Пустой список — сошлось."""
    e = []
    if s['n_dirs'] is not None and s['n'] != s['n_dirs']:
        e.append(f"вошло {s['n']} ≠ папок товаров на диске {s['n_dirs']}")
    if s['stopped'] + s['painted'] != s['n']:
        e.append(f"остановились {s['stopped']} + покрашено {s['painted']} ≠ вошло {s['n']}")
    if sum(x['count'] for x in s['stopped_by_stage']) != s['stopped'] or sum(len(x['items']) for x in s['stopped_by_stage']) != s['stopped']:
        e.append('сумма по этапам остановки ≠ числу остановившихся')
    if any(not i['reason'] for x in s['stopped_by_stage'] for i in x['items']):
        e.append('у остановившегося товара нет причины')
    if sum(s['painted_final'].values()) != s['painted'] or len(s['painted_items']) != s['painted']:
        e.append('итоги этапа 9 по покрашенным не сходятся с числом покрашенных')
    if s['frames'] is not None and s['frames'] != s['painted']:
        e.append(f"кадров на странице {s['frames']} ≠ покрашено {s['painted']}")
    return e


def render_md(s: dict) -> str:
    f = s['painted_final']
    out = [f"# Прогон покраски `{s['label']}` — сводка (автоматом, `paint_run_report.py`)", '',
           f"- **Вошло: {s['n']}**",
           f"- **Остановились, крашеной модели нет: {s['stopped']}**" + ('' if s['stopped'] else ' — нет')]
    for x in s['stopped_by_stage']:
        out.append(f"  - этап `{x['stage']}` — {x['count']}: " + '; '.join(f"`{i['sku']}` — {i['reason']}" for i in x['items']))
    out.append(f"- **Покрашено (есть итоговая модель этапа 8): {s['painted']}** — итог этапа 9: прошёл {f['ok']} · мягко {f['soft']} · не готов {f['refused']}"
               + (f" · этап 9 не запускался {f['missing']}" if f.get('missing') else '') + f"; строго (без «мягко»): {s['painted_strict']}")
    out.append(f"- **Кадров на странице: {'не строились' if s['frames'] is None else s['frames']}**")
    out.append('')
    if s['errors']:
        out += ['**ОШИБКА СВОДКИ:**'] + [f'- {x}' for x in s['errors']]
    else:
        out.append('Самопроверка сошлась: вошло = остановились + покрашено; сумма по этапам = остановившимся' + ('; кадров = покрашено.' if s['frames'] is not None else '.'))
    return '\n'.join(out) + '\n'


def painted_set(per: dict, runof: dict) -> set:
    return {sku for sku in per if os.path.exists(os.path.join(runof[sku], sku, MODEL))}


def product_meta(run: str, sku: str) -> dict:
    try:
        return json.load(open(os.path.join(run, sku, 'work', 'product.json'), encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def build_frames(repo: str, runof: dict, skus: list, out: str) -> dict:
    """Кадры «фото | наш 3D» (как `tex_visible`: фото карточки в кадре камеры этапа 4 и итоговая текстура этапа 8 по растру той же камеры, без света) — JPEG ≤1600 px.
    Возвращает {sku: {'foto': путь, 'view3d': путь}} только по построенным; сбой одного товара не рушит остальных (сводка ловит нехватку)."""
    import numpy as np
    from PIL import Image
    sys.path[:0] = [os.path.join(repo, 'tools', 'scout', 'salad', 'trellis'), os.path.join(repo, 'tools', 'scout')]
    import tex_visible as TV  # noqa: E402
    bg = 232
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    res, errs = {}, {}
    for sku in skus:
        try:
            base = os.path.join(runof[sku], sku)
            photo = json.load(open(os.path.join(base, 'work', 'manifest05.json'), encoding='utf-8'))[0]['path']
            st = TV.load_stage(base)
            geoms = TV.load_shape(os.path.join(base, MODEL))
            P = np.asarray(Image.open(photo).convert('RGBA'))
            prgb, pmask = TV.photo_to_frame(P, st['P'], st['px'])
            after = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
            f1 = np.full(prgb.shape, bg, np.uint8)
            f1[pmask] = prgb[pmask]
            f2 = np.full(after.shape, bg, np.uint8)
            f2[st['mask']] = after[st['mask']]
            paths = {}
            for key, arr in (('foto', f1), ('view3d', f2)):
                im = Image.fromarray(arr[..., :3]).convert('RGB')
                if max(im.size) > MAX_SIDE:
                    k = MAX_SIDE / max(im.size)
                    im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
                p = os.path.join('img', f'{sku}_{"1-foto" if key == "foto" else "2-3d"}.jpg')
                im.save(os.path.join(out, p), 'JPEG', quality=JPEG_Q, optimize=True)
                paths[key] = p
            res[sku] = paths
        except Exception as ex:  # noqa: BLE001 — один товар не должен ронять страницу; нехватку поймает самопроверка
            errs[sku] = f'{type(ex).__name__}: {ex}'
    return {'ok': res, 'errors': errs}


CSS = """
:root{--bg:#fff;--fg:#1c1c1c;--mut:#666;--card:#f4f4f2;--line:#ddd;--ok:#1d7a3c;--soft:#9a6b00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--card:#222;--line:#444;--ok:#5fcf86;--soft:#e6b34a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,sans-serif;max-width:1400px;margin-inline:auto}
h1{font-size:1.25rem;margin:0 0 8px}h2{font-size:1.05rem;margin:20px 0 8px}.sum{background:var(--card);border-radius:10px;padding:12px 14px;margin-bottom:16px}
.sum b{font-weight:650}.sum ul{margin:6px 0 0;padding-left:18px}.sum li{margin:2px 0;font-size:.92rem;color:var(--mut);word-break:break-word}
.card{border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:16px}.card h3{font-size:1rem;margin:0}.meta{color:var(--mut);font-size:.85rem;word-break:break-all}
.badge{display:inline-block;font-size:.8rem;border-radius:99px;padding:1px 9px;border:1px solid currentColor;margin-left:6px}.ok{color:var(--ok)}.soft{color:var(--soft)}.refused,.missing{color:var(--bad)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.pair figure{margin:0}.pair img{width:100%;height:auto;display:block;border-radius:6px;background:#e8e8e8}
.pair figcaption{font-size:.8rem;color:var(--mut);text-align:center;margin-top:2px}.why{font-size:.85rem;color:var(--mut);margin-top:6px}
@media (max-width:640px){.pair{grid-template-columns:1fr}}
"""


def render_page(s: dict, cards: list, title: str) -> str:
    e = html.escape
    f = s['painted_final']
    short = lambda t: t if len(t) <= 110 else t[:107] + '…'          # полный текст причины — в summary.md/json
    li = ''.join(f"<li><b>{e(x['stage'])}</b> — {x['count']}: " + '; '.join(f"{e(i['sku'])}: {e(short(i['reason']))}" for i in x['items']) + '</li>' for x in s['stopped_by_stage'])
    summ = (f"<div class='sum'><div><b>Вошло {s['n']}</b> · <b>остановились (крашеной модели нет) {s['stopped']}</b> · <b>покрашено {s['painted']}</b> · <b>кадров на странице {len(cards)}</b></div>"
            f"<div>итог этапа 9 у покрашенных: прошёл {f['ok']} · мягко {f['soft']} · не готов {f['refused']}" + (f" · не запускался {f['missing']}" if f.get('missing') else '')
            + f"; строго (без «мягко»): {s['painted_strict']}</div>"
            + (f'<ul>{li}</ul>' if li else '') + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(s['errors']))}</div>" if s['errors'] else '') + '</div>')
    body = []
    for c in cards:
        badge = FINAL_WORDS.get(c['final'], c['final']) + (' · строго' if c['strict'] else '')
        body.append(f"<div class='card'><h3>{e(c['name'])}<span class='badge {e(c['final'])}'>{e(badge)}</span></h3><div class='meta'>{e(c['role'])} · {e(c['sku'])}</div>"
                    f"<div class='pair'><figure><img src='{e(c['foto'])}' loading='lazy' alt='фото'><figcaption>фото товара</figcaption></figure>"
                    f"<figure><img src='{e(c['view3d'])}' loading='lazy' alt='наш 3D'><figcaption>наш 3D (без света)</figcaption></figure></div>"
                    + (f"<div class='why'>{e(c['reason'])}</div>" if c['reason'] and c['final'] != 'ok' else '') + '</div>')
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body><h1>{e(title)}</h1>{summ}<h2>Покрашенные: фото | наш 3D</h2>{''.join(body)}</body></html>")


def publish(out: str, name: str) -> str:
    remote = f'{REMOTE_ROOT}/{name}'
    sh = lambda *c: subprocess.run(c, check=True)  # noqa: E731
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'mkdir -p {remote}/img')
    sh('rsync', '-a', '--size-only', '-e', 'ssh -o BatchMode=yes', out + '/img/', f'{REMOTE}:{remote}/img/')
    sh('rsync', '-a', '-e', 'ssh -o BatchMode=yes', out + '/index.html', out + '/summary.json', out + '/summary.md', f'{REMOTE}:{remote}/')
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'chmod -R a+rX {remote}')
    return f'{URL_ROOT}/{name}/'


def report(runs: list, per_by_label: dict, out: str, repo: str, name: str | None = None, do_publish: bool = False, frames_fn=None) -> int:
    """Сводка + страница для набора прогонов. `per_by_label` — {метка прогона: {sku: решения}} в порядке `runs`; повтор sku — из первого прогона. Возвращает код возврата."""
    labels = list(per_by_label)
    per, runof = {}, {}
    n_dirs = 0
    seen = set()
    for r, lab in zip(runs, labels):
        for sku in pf.products(r):
            if sku not in seen:
                seen.add(sku)
                n_dirs += 1
        for sku, rows in per_by_label[lab].items():
            if sku not in per:
                per[sku], runof[sku] = rows, r
    label = name or '+'.join(labels)
    painted = painted_set(per, runof)
    os.makedirs(out, exist_ok=True)
    built = (frames_fn or build_frames)(repo, runof, sorted(painted), out)
    s = summarise(per, painted, label, n_dirs, len(built['ok']))
    for sku, er in sorted(built['errors'].items()):
        s['errors'].append(f'кадр не построен: {sku}: {er}')
    cards = []
    for it in s['painted_items']:
        if it['sku'] not in built['ok']:
            continue
        meta = product_meta(runof[it['sku']], it['sku'])
        cards.append({**it, **built['ok'][it['sku']], 'name': meta.get('name') or it['sku'], 'role': meta.get('role') or ''})
    open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8').write(render_md(s))
    json.dump(s, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(render_page(s, cards, f'Прогон покраски {label}'))
    print(render_md(s))
    print(f'страница: {os.path.join(out, "index.html")}')
    if do_publish and not s['errors']:
        print('выложено:', publish(out, slug(label)))
    elif do_publish:
        print('НЕ выложено: сводка не сошлась')
    return 1 if s['errors'] else 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description='сводка и страница прогона покраски (самопроверка: сумма сходится, кадров = покрашено)')
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--repo')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    runs = [os.path.expanduser(r).rstrip('/') for r in a.runs]
    PC, PS, rules, repo = pf.load_pc(a.repo)
    per_by = {}
    for r in runs:
        _stages, per = pf.analyse(PC, PS, rules, r)
        per_by[os.path.basename(r)] = per
    out = a.out or os.path.join(runs[0], '_report')
    return report(runs, per_by, out, repo, a.name, a.publish)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
