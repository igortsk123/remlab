#!/usr/bin/env python3
"""T-180/4 · сводка и страницы прогона покраски — числа и кадры автоматом, не руками (владелец TG 1251, 1258; поправки директора по приёмке отчёта 1).

ЗАЧЕМ: одно и то же число («сколько остановилось, сколько покрашено, сколько показано») считали по памяти и ошиблись; теперь его считает код
из тех же решений этапов, что воронка (`paint_funnel.analyse`), и сам проверяет, что сумма сходится. Страницы — для владельца: названия товаров и этапов
словами, причины одной строкой («код причины → фраза» в `tools/scout/rules/paint-reasons.json`), числа — в свёрнутом «подробно».

ЧТО ДЕЛАЕТ (только чтение готового прогона; платного и нейросети нет):
  ① сводка — вошло N · не дошли до готовой модели (по этапам, с причиной каждого товара) · покрашено (есть итоговая модель `08-material/material.glb`;
     из них итог этапа 9) · карточек на странице. `summary.md` + `summary.json`.
     Самопроверка (`verify`): N совпало с числом папок товаров на диске; не дошли + покрашено = N; сумма по этапам = не дошедшим; у каждого не дошедшего есть причина;
     кадров «фото | наш 3D» = покрашено; карточек = N. Не сошлось — ненулевой код возврата и строка «ОШИБКА СВОДКИ».
  ② страница прогона `index.html` — сверху сводка и ссылки на этапы; карточки ВСЕХ товаров: покрашенные «фото | наш 3D» (как `tex_visible`: итоговая текстура
     этапа 8 по растру камеры этапа 4, без света), не дошедшие «фото | последний кадр, который есть» с подписью «встал на: …». Без скриптов и кода доступа,
     телефон 375 и ПК, картинки JPEG ≤1600 px (PNG 1536² Телеграм не берёт).
  ②б страницы этапов `<этап>/index.html` — по КАЖДОМУ этапу все товары набора: «фото | результат этапа» (`<товар>/<этап>/frame.png`), подпись «этап NN · название ·
     готовность этапа N %», вошло/прошло/встало, ссылки на соседние этапы. Готовность и названия этапов — `tools/scout/rules/paint-readiness.json` (нет файла или ключа — «не задана»).
  Публикация — только `--publish` (rsync на `/opt/remlab/test/paint-<прогон>/`); по умолчанию всё лежит локально в `--out`.

«Покрашено» = у товара есть итоговая модель этапа 8 (решение директора 22.11): именно её можно показать. Остальные — «не дошли»: этап — первый отказ (при отказе и «нет check.json»
берётся отказ), причина — слова самого конвейера (`paint_check`). ID товаров в код не попадают.

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

MODEL = os.path.join('08-material', 'material.glb')
MAX_SIDE = 1600
JPEG_Q = 88
REMOTE = 'root@89.167.127.0'
REMOTE_ROOT = '/opt/remlab/test'
URL_ROOT = 'https://remont-lab.online/test'
READINESS = os.path.join('tools', 'scout', 'rules', 'paint-readiness.json')
REASONS = os.path.join('tools', 'scout', 'rules', 'paint-reasons.json')
VERDICT = {'ok': 'прошёл проверку', 'soft': 'прошёл с замечаниями', 'refused': 'не прошёл', 'missing': 'проверка не запускалась'}
STAGE_VERDICT = {'ok': 'прошёл', 'soft': 'прошёл с замечаниями', 'refused': 'встал', 'missing': 'не дошёл'}


def slug(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return 'paint-' + (s or 'run')


# ---------- слова для владельца: названия этапов и фразы причин — из json рядом с правилами, не из кода ----------

def _load(repo: str, rel: str) -> dict:
    try:
        d = json.load(open(os.path.join(repo, rel), encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def load_words(repo: str) -> dict:
    """{'stages': {папка этапа: {name, pct}}, 'updated': …, 'phrases': [{has, say}]}. Нет файла — пусто: этап называется кодом, причина — своим текстом."""
    r = _load(repo, READINESS)
    return {'stages': r.get('stages') or {}, 'updated': r.get('updated'), 'phrases': (_load(repo, REASONS).get('phrases') or [])}


def stage_name(W: dict, code: str) -> str:
    return ((W.get('stages') or {}).get(code) or {}).get('name') or code


def stage_pct(W: dict, code: str):
    v = ((W.get('stages') or {}).get(code) or {}).get('pct')
    return v if isinstance(v, (int, float)) else None


def say(W: dict, reason: str) -> str:
    """Причина одной строкой словами: фразы всех подошедших строк таблицы (без повторов, по порядку таблицы). Ни одна не подошла — сам текст причины, укороченный."""
    out = []
    for p in W.get('phrases') or []:
        if p.get('has') and p['has'] in (reason or '') and p.get('say') and p['say'] not in out:
            out.append(p['say'])
    if out:
        return '; '.join(out)
    r = (reason or '').strip()
    return r if len(r) <= 120 else r[:117] + '…'


def stop_of(rows: list) -> tuple[str, str]:
    """Где остановился товар без крашеной модели: первый ОТКАЗ (пустой check.json раньше отказа — не причина, этап мог просто не писать его), иначе первый «нет check.json»."""
    for want in ('refused', 'missing'):
        for r in rows:
            if r['status'] == want:
                return r['stage'], (r.get('reason') or '').strip() or 'причина не записана'
    return rows[-1]['stage'] if rows else '—', 'все этапы прошли, но итоговой модели (08-material/material.glb) нет'


def summarise(per: dict, painted: set, label: str, n_dirs: int | None = None, frames: int | None = None, names: dict | None = None, cards: int | None = None) -> dict:
    """Сводка по `per` ({sku: [решения этапов]}) и множеству `painted` (sku с итоговой моделью). Чистая функция — считает и ничего не читает с диска."""
    names = names or {}
    stopped: dict = {}
    for sku in sorted(per):
        if sku in painted:
            continue
        st, why = stop_of(per[sku])
        stopped.setdefault(st, []).append({'sku': sku, 'name': names.get(sku) or sku, 'reason': why})
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
        prow.append({'sku': sku, 'name': names.get(sku) or sku, 'final': last['status'], 'strict': is_strict, 'reason': last.get('reason') or ''})
    s = {'label': label, 'n': len(per), 'n_dirs': n_dirs, 'stopped': sum(x['count'] for x in stages), 'stopped_by_stage': stages,
         'painted': len(painted & set(per)), 'painted_final': fin, 'painted_strict': strict, 'painted_items': prow, 'frames': frames, 'cards': cards}
    s['errors'] = verify(s)
    return s


def verify(s: dict) -> list:
    """Самопроверка сводки: каждое число считается двумя путями. Пустой список — сошлось."""
    e = []
    if s['n_dirs'] is not None and s['n'] != s['n_dirs']:
        e.append(f"вошло {s['n']} ≠ папок товаров на диске {s['n_dirs']}")
    if s['stopped'] + s['painted'] != s['n']:
        e.append(f"не дошли {s['stopped']} + покрашено {s['painted']} ≠ вошло {s['n']}")
    if sum(x['count'] for x in s['stopped_by_stage']) != s['stopped'] or sum(len(x['items']) for x in s['stopped_by_stage']) != s['stopped']:
        e.append('сумма по этапам остановки ≠ числу не дошедших')
    if any(not i['reason'] for x in s['stopped_by_stage'] for i in x['items']):
        e.append('у не дошедшего товара нет причины')
    if sum(s['painted_final'].values()) != s['painted'] or len(s['painted_items']) != s['painted']:
        e.append('итоги этапа 9 по покрашенным не сходятся с числом покрашенных')
    if s['frames'] is not None and s['frames'] != s['painted']:
        e.append(f"кадров «фото | наш 3D» {s['frames']} ≠ покрашено {s['painted']}")
    if s.get('cards') is not None and s['cards'] != s['n']:
        e.append(f"карточек на странице {s['cards']} ≠ вошло {s['n']}")
    return e


def render_md(s: dict, W: dict | None = None) -> str:
    W = W or {}
    f = s['painted_final']
    out = [f"# Прогон покраски `{s['label']}` — сводка (автоматом, `paint_run_report.py`)", '',
           f"- **Вошло: {s['n']}**",
           f"- **Не дошли до готовой модели: {s['stopped']}**" + ('' if s['stopped'] else ' — нет')]
    for x in s['stopped_by_stage']:
        out.append(f"  - {stage_name(W, x['stage'])} (`{x['stage']}`) — {x['count']}: " + '; '.join(f"{i.get('name') or i['sku']} (`{i['sku']}`) — {say(W, i['reason'])}" for i in x['items']))
    out.append(f"- **Покрашено (есть итоговая модель этапа 8): {s['painted']}** — итог проверки: прошли {f['ok']} · с замечаниями {f['soft']} · не прошли {f['refused']}"
               + (f" · проверка не запускалась {f['missing']}" if f.get('missing') else '') + f"; без замечаний ни на одном этапе: {s['painted_strict']}")
    out.append(f"- **Кадров «фото | наш 3D»: {'не строились' if s['frames'] is None else s['frames']}** · карточек на странице: {'—' if s.get('cards') is None else s['cards']}")
    out.append('')
    if s['errors']:
        out += ['**ОШИБКА СВОДКИ:**'] + [f'- {x}' for x in s['errors']]
    else:
        out.append('Самопроверка сошлась: вошло = не дошли + покрашено; сумма по этапам = не дошедшим' + ('; кадров = покрашено; карточек = вошло.' if s['frames'] is not None else '.'))
    return '\n'.join(out) + '\n'


def painted_set(per: dict, runof: dict) -> set:
    return {sku for sku in per if os.path.exists(os.path.join(runof[sku], sku, MODEL))}


def product_meta(run: str, sku: str) -> dict:
    try:
        return json.load(open(os.path.join(run, sku, 'work', 'product.json'), encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return {}


def load_catalog(path: str | None) -> dict:
    """Выгрузка каталога (JSON-список записей с `sid` или `id`, `name`, `role`) → {товар: запись}. Нужна для названий тех товаров, что остановились раньше этапа 8: `work/product.json` там ещё не написан."""
    if not path:
        return {}
    d = json.load(open(os.path.expanduser(path), encoding='utf-8'))
    if isinstance(d, dict) and isinstance(d.get('items'), list):          # набор в виде {items: [...]} (например `set40.json` р.2)
        d = d['items']
    return {(r.get('sid') or r.get('id')): r for r in (d if isinstance(d, list) else [d]) if isinstance(r, dict) and (r.get('sid') or r.get('id'))}


NAMES_RU = os.path.join('tools', 'scout', 'data', 'names-en.json')


def load_names_ru(repo: str) -> dict:
    """Русские названия витрины из репозитория (`names-en.json`: ключ — sid, `ru` — название): запасной источник, когда нет ни `product.json`, ни выгрузки `--catalog`."""
    d = _load(repo, NAMES_RU)
    return {k: v['ru'] for k, v in d.items() if isinstance(v, dict) and v.get('ru')}


def photo_paths(per: dict, runof: dict) -> dict:
    """Фото товара: манифест этапа 5, а у остановившихся раньше — аргумент `--photo` из `run_all.json` (его пишет сам запуск прогона)."""
    out = {}
    for sku in per:
        base = os.path.join(runof[sku], sku)
        p = None
        try:
            p = json.load(open(os.path.join(base, 'work', 'manifest05.json'), encoding='utf-8'))[0]['path']
        except Exception:  # noqa: BLE001
            try:
                m = re.search(r'"--photo",\s*"([^"]+)"', open(os.path.join(base, 'run_all.json'), encoding='utf-8').read())
                p = m.group(1) if m else None
            except Exception:  # noqa: BLE001
                p = None
        out[sku] = p if p and os.path.exists(p) else None
    return out


def _jpeg(src: str, dst: str) -> None:
    from PIL import Image
    im = Image.open(src)
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bgim = Image.new('RGB', im.size, (232, 232, 232))
        bgim.paste(im, mask=im.split()[-1])
        im = bgim
    else:
        im = im.convert('RGB')
    if max(im.size) > MAX_SIDE:
        k = MAX_SIDE / max(im.size)
        im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
    im.save(dst, 'JPEG', quality=JPEG_Q, optimize=True)


def build_frames(repo: str, runof: dict, skus: list, out: str) -> dict:
    """Кадры «фото | наш 3D» (как `tex_visible`: фото карточки в кадре камеры этапа 4 и итоговая текстура этапа 8 по растру той же камеры, без света) — JPEG ≤1600 px.
    Возвращает {'ok': {sku: {'foto': путь, 'view3d': путь}}, 'errors': {sku: текст}}; сбой одного товара не рушит остальных (сводка ловит нехватку)."""
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


def stopped_frames(runof: dict, per: dict, stopped: list, photos: dict, out: str) -> dict:
    """Для не дошедших: фото + последний кадр, который есть (от этапа остановки назад). {sku: {'foto','frame','frame_stage'}}; нет кадра — None (карточка всё равно будет)."""
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    res = {}
    for sku, stage in stopped:
        c = {'foto': None, 'frame': None, 'frame_stage': None}
        try:
            if photos.get(sku):
                _jpeg(photos[sku], os.path.join(out, 'img', f'{sku}_1-foto.jpg'))
                c['foto'] = f'img/{sku}_1-foto.jpg'
        except Exception:  # noqa: BLE001
            pass
        order = [r['stage'] for r in per[sku]]
        cand = order[:order.index(stage) + 1][::-1] if stage in order else order[::-1]
        for st in cand:
            fr = os.path.join(runof[sku], sku, st, 'frame.png')
            if os.path.exists(fr):
                try:
                    _jpeg(fr, os.path.join(out, 'img', f'{sku}_2-stop.jpg'))
                    c['frame'], c['frame_stage'] = f'img/{sku}_2-stop.jpg', st
                    break
                except Exception:  # noqa: BLE001
                    continue
        res[sku] = c
    return res


CSS = """
:root{--bg:#fff;--fg:#1c1c1c;--mut:#666;--card:#f4f4f2;--line:#ddd;--ok:#1d7a3c;--soft:#9a6b00;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--card:#222;--line:#444;--ok:#5fcf86;--soft:#e6b34a;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,sans-serif;max-width:1400px;margin-inline:auto}
h1{font-size:1.25rem;margin:0 0 8px}h2{font-size:1.05rem;margin:20px 0 8px}.sum{background:var(--card);border-radius:10px;padding:12px 14px;margin-bottom:16px}
.sum b{font-weight:650}.sum ul{margin:6px 0 0;padding-left:18px}.sum li{margin:3px 0;font-size:.92rem;word-break:break-word}.sum a{color:inherit}
.card{border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:16px}.card h3{font-size:1rem;margin:0}.id,.meta,small{color:var(--mut);font-size:.78rem;opacity:.85}.meta{font-size:.85rem;opacity:1}
.badge{display:inline-block;font-size:.8rem;border-radius:99px;padding:1px 9px;border:1px solid currentColor;margin-left:6px;white-space:nowrap}.ok{color:var(--ok)}.soft{color:var(--soft)}.refused,.missing{color:var(--bad)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.pair figure{margin:0}.pair img{width:100%;height:auto;display:block;border-radius:6px;background:#e8e8e8}
.pair figcaption{font-size:.8rem;color:var(--mut);text-align:center;margin-top:2px}.why{font-size:.9rem;margin-top:6px}details{margin-top:4px;font-size:.8rem;color:var(--mut)}details summary{cursor:pointer}
.nofr{display:flex;align-items:center;justify-content:center;min-height:120px;border:1px dashed var(--line);border-radius:6px;color:var(--mut);font-size:.85rem}nav{margin:6px 0 12px;font-size:.95rem}nav a{padding:0 2px}
@media (max-width:640px){.pair{grid-template-columns:1fr}}
"""


def _head(title: str, body: str) -> str:
    e = html.escape
    return (f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body>{body}</body></html>")


def _card(c: dict, badge_class: str, badge: str, W: dict, caption: str, cap1: str, cap2: str, why: str = '', detail: str = '') -> str:
    e = html.escape
    ph = f"<figure><img src='{e(c['foto'])}' loading='lazy' alt='фото'><figcaption>{e(cap1)}</figcaption></figure>" if c.get('foto') else "<figure><div class='nofr'>фото нет</div></figure>"
    key = 'view3d' if c.get('view3d') else 'frame'
    fr = (f"<figure><img src='{e(c[key])}' loading='lazy' alt='результат'><figcaption>{e(cap2)}</figcaption></figure>" if c.get(key) else "<figure><div class='nofr'>кадра нет</div></figure>")
    return (f"<div class='card'><h3>{e(c['name'])}<span class='badge {e(badge_class)}'>{e(badge)}</span></h3><div class='id'>{e(c['sku'])}</div>"
            + (f"<div class='meta'>{e(caption)}</div>" if caption else '') + f"<div class='pair'>{ph}{fr}</div>"
            + (f"<div class='why'>{e(why)}</div>" if why else '') + (f"<details><summary>подробно</summary>{e(detail)}</details>" if detail else '') + '</div>')


def render_page(s: dict, cards: list, stopped_cards: list, title: str, W: dict | None = None, stage_links: dict | None = None) -> str:
    W = W or {}
    e = html.escape
    f = s['painted_final']
    li = ''.join(f"<li><b>{e(stage_name(W, x['stage']))}</b> <small>({e(x['stage'])})</small> — {x['count']}: "
                 + '; '.join(f"{e(i.get('name') or i['sku'])} — {e(say(W, i['reason']))}" for i in x['items']) + '</li>' for x in s['stopped_by_stage'])
    summ = (f"<div class='sum'><div><b>Вошло {s['n']}</b> · <b>не дошли до готовой модели {s['stopped']}</b> · <b>покрашено {s['painted']}</b> · <b>карточек на странице {len(cards) + len(stopped_cards)}</b></div>"
            f"<div>у покрашенных: прошли проверку {f['ok']} · с замечаниями {f['soft']} · не прошли {f['refused']}" + (f" · проверка не запускалась {f['missing']}" if f.get('missing') else '') + '</div>'
            + (f'<ul>{li}</ul>' if li else '') + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(s['errors']))}</div>" if s['errors'] else '') + '</div>')
    nav = ''
    if stage_links:
        nav = ("<div class='sum'><b>По этапам</b> (весь набор на каждом):<ul>" + ''.join(
            f"<li><a href='{e(k)}/'>{e(stage_name(W, k))}</a> <small>({e(k)})</small> — вошло {v['reached']}, встало {v['refused']}</li>" for k, v in stage_links.items()) + '</ul></div>')
    body = []
    for c in cards:
        verdict = VERDICT.get(c['final'], c['final'])
        body.append(_card(c, c['final'], verdict, W, '', 'фото товара', 'наш 3D (без света)', say(W, c['reason']) if c['final'] != 'ok' and c['reason'] else '', c['reason'] if c['final'] != 'ok' else ''))
    stop = []
    for c in stopped_cards:
        st = c['stop_stage']
        cap = f"встал на: {stage_name(W, st)} ({st})"
        fs = c.get('frame_stage')
        cap2 = f"последний кадр: {stage_name(W, fs)} ({fs})" if fs else 'кадра нет'
        stop.append(_card(c, 'refused', 'не дошёл до готовой модели', W, cap, 'фото товара', cap2, say(W, c['reason']), c['reason']))
    return _head(title, f"<h1>{e(title)}</h1>{summ}{nav}<h2>Покрашенные: фото | наш 3D</h2>{''.join(body)}"
                 + (f"<h2>Не дошли до готовой модели: фото | последний кадр</h2>{''.join(stop)}" if stop else ''))


# ---------- страницы по этапам (T-180/4 доп., владелец TG 1258): после КАЖДОГО этапа — «фото | результат этапа» по всем товарам набора ----------

def stage_summary(per: dict, stage: str) -> dict:
    """Сводка одного этапа по `per`: вошло (этап запускался: есть check.json) · прошло (ok) · с замечаниями · встало (refused) · не дошло. Самопроверка: вошло = прошло+с замечаниями+встало; вошло+не дошло = N."""
    c = {'ok': 0, 'soft': 0, 'refused': 0, 'missing': 0}
    items = {}
    for sku, rows in per.items():
        r = next((x for x in rows if x['stage'] == stage), None)
        st = r['status'] if r else 'missing'
        c[st] = c.get(st, 0) + 1
        items[sku] = {'status': st, 'reason': ((r or {}).get('reason') or '').strip()}
    reached = c['ok'] + c['soft'] + c['refused']
    s = {'stage': stage, 'n': len(per), 'reached': reached, 'ok': c['ok'], 'soft': c['soft'], 'refused': c['refused'], 'not_reached': c['missing'], 'no_frame': 0, 'items': items, 'errors': []}
    if reached + c['missing'] != len(per):
        s['errors'].append(f'{stage}: вошло {reached} + не дошло {c["missing"]} ≠ N {len(per)}')
    return s


def stage_cards(runof: dict, per: dict, stage: str, out: str, photos: dict, names: dict) -> tuple:
    """Карточки одного этапа: фото и `<товар>/<этап>/frame.png`. Возвращает (карточки, ошибки обработки файлов). Нет кадра — карточка с пометкой «кадра нет» (считается в `no_frame`)."""
    d = os.path.join(out, stage, 'img')
    os.makedirs(d, exist_ok=True)
    cards, errs = [], []
    for sku in sorted(per):
        r = next((x for x in per[sku] if x['stage'] == stage), None)
        st = r['status'] if r else 'missing'
        c = {'sku': sku, 'name': names.get(sku) or sku, 'status': st, 'reason': ((r or {}).get('reason') or '').strip(), 'foto': None, 'frame': None}
        try:
            if photos.get(sku):
                _jpeg(photos[sku], os.path.join(d, f'{sku}_1-foto.jpg'))
                c['foto'] = f'img/{sku}_1-foto.jpg'
        except Exception as ex:  # noqa: BLE001
            errs.append(f'{stage}: фото {sku}: {type(ex).__name__}: {ex}')
        fr = os.path.join(runof[sku], sku, stage, 'frame.png')
        if os.path.exists(fr):
            try:
                _jpeg(fr, os.path.join(d, f'{sku}_2-{stage[:2]}.jpg'))
                c['frame'] = f'img/{sku}_2-{stage[:2]}.jpg'
            except Exception as ex:  # noqa: BLE001
                errs.append(f'{stage}: кадр {sku}: {type(ex).__name__}: {ex}')
        cards.append(c)
    return cards, errs


def render_stage_page(s: dict, cards: list, stages: list, label: str, W: dict) -> str:
    e = html.escape
    st = s['stage']
    pct = stage_pct(W, st)
    cap = f"этап {st[:2]} · {stage_name(W, st)} · готовность этапа " + (f'{pct} %' if pct is not None else 'не задана')
    nav = f"<a href='../'>весь прогон</a> · " + ' · '.join((f"<b>{e(x[:2])}</b>" if x == st else f"<a href='../{e(x)}/' title='{e(stage_name(W, x))}'>{e(x[:2])}</a>") for x in stages)
    summ = (f"<div class='sum'><div><b>вошло {s['reached']}</b> · <b>прошло {s['ok']}</b> · с замечаниями {s['soft']} · <b>встало {s['refused']}</b> · не дошло {s['not_reached']} (из {s['n']})"
            + (f" · без кадра этапа {s['no_frame']}" if s['no_frame'] else '') + '</div>'
            + (f"<div class='why'><b>ОШИБКА СВОДКИ:</b> {e('; '.join(s['errors']))}</div>" if s['errors'] else '') + f"<div class='meta'>готовность обновлена: {e(str(W.get('updated') or '—'))}</div></div>")
    body = []
    for c in cards:
        body.append(_card(c, c['status'], STAGE_VERDICT.get(c['status'], c['status']), W, cap, 'фото товара', f'после этапа {st[:2]}',
                          say(W, c['reason']) if c['status'] in ('refused', 'soft') and c['reason'] else '', c['reason'] if c['status'] in ('refused', 'soft') else ''))
    return _head(f'{label}: {cap}', f"<h1>{e(cap)}</h1><nav>{nav}</nav>{summ}{''.join(body)}")


def stage_pages(per: dict, runof: dict, out: str, W: dict, label: str, names: dict, photos: dict) -> tuple:
    """Страницы всех этапов набора в `<out>/<этап>/index.html`. Возвращает ({этап: сводка}, ошибки)."""
    stages = sorted({r['stage'] for rows in per.values() for r in rows})
    sums, errs = {}, []
    for st in stages:
        s = stage_summary(per, st)
        cards, e = stage_cards(runof, per, st, out, photos, names)
        s['errors'] += e
        s['no_frame'] = sum(1 for c in cards if c['status'] != 'missing' and not c['frame'])
        errs += s['errors']
        os.makedirs(os.path.join(out, st), exist_ok=True)
        open(os.path.join(out, st, 'index.html'), 'w', encoding='utf-8').write(render_stage_page(s, cards, stages, label, W))
        sums[st] = {k: v for k, v in s.items() if k != 'items'}
    json.dump(sums, open(os.path.join(out, 'stages.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return sums, errs


def publish(out: str, name: str) -> str:
    remote = f'{REMOTE_ROOT}/{name}'
    sh = lambda *c: subprocess.run(c, check=True)  # noqa: E731
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'mkdir -p {remote}')
    sh('rsync', '-a', '--size-only', '-e', 'ssh -o BatchMode=yes', '--exclude', '*.png', '--exclude', 'page_*', out + '/', f'{REMOTE}:{remote}/')
    sh('ssh', '-o', 'BatchMode=yes', REMOTE, f'chmod -R a+rX {remote}')
    return f'{URL_ROOT}/{name}/'


def report(runs: list, per_by_label: dict, out: str, repo: str, name: str | None = None, do_publish: bool = False, frames_fn=None, with_stages: bool = True, catalog: str | None = None) -> int:
    """Сводка + страницы для набора прогонов. `per_by_label` — {метка прогона: {sku: решения}} в порядке `runs`; повтор sku — из первого прогона. Возвращает код возврата."""
    labels = list(per_by_label)
    per, runof = {}, {}
    seen = set()
    for r, lab in zip(runs, labels):
        for sku in pf.products(r):
            seen.add(sku)
        for sku, rows in per_by_label[lab].items():
            if sku not in per:
                per[sku], runof[sku] = rows, r
    n_dirs = len(seen)
    label = name or '+'.join(labels)
    W = load_words(repo)
    cat = load_catalog(catalog)
    ru = load_names_ru(repo)
    names = {sku: product_meta(runof[sku], sku).get('name') or (cat.get(sku) or {}).get('name') or ru.get(sku) or sku for sku in per}
    painted = painted_set(per, runof)
    os.makedirs(out, exist_ok=True)
    photos = photo_paths(per, runof)
    built = (frames_fn or build_frames)(repo, runof, sorted(painted), out)
    stop_list = [(sku, stop_of(rows)[0]) for sku, rows in sorted(per.items()) if sku not in painted]
    sf = stopped_frames(runof, per, stop_list, photos, out)
    s = summarise(per, painted, label, n_dirs, len(built['ok']), names, None)
    extra = [f'кадр не построен: {sku}: {er}' for sku, er in sorted(built['errors'].items())]
    cards = []
    for it in s['painted_items']:
        if it['sku'] in built['ok']:
            cards.append({**it, **built['ok'][it['sku']]})
    stopped_cards = []
    reasons = {i['sku']: i['reason'] for x in s['stopped_by_stage'] for i in x['items']}
    for sku, stg in stop_list:
        stopped_cards.append({'sku': sku, 'name': names[sku], 'stop_stage': stg, 'reason': reasons.get(sku, ''), **sf[sku]})
    s['cards'] = len(cards) + len(stopped_cards)
    s['errors'] = verify(s) + extra
    stage_sums = {}
    if with_stages:                                                    # страницы по этапам: `<out>/<этап>/index.html` — фото | результат этапа по всем товарам набора
        stage_sums, serrs = stage_pages(per, runof, out, W, label, names, photos)
        s['errors'] += serrs
    open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8').write(render_md(s, W))
    json.dump(s, open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(render_page(s, cards, stopped_cards, f'Прогон покраски {label}', W, stage_sums))
    print(render_md(s, W))
    print(f'страница: {os.path.join(out, "index.html")}')
    if do_publish and not s['errors']:
        print('выложено:', publish(out, slug(label)))
    elif do_publish:
        print('НЕ выложено: сводка не сошлась')
    return 1 if s['errors'] else 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description='сводка и страницы прогона покраски (самопроверка: сумма сходится, кадров = покрашено, карточек = вошло)')
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--out')
    ap.add_argument('--name')
    ap.add_argument('--repo')
    ap.add_argument('--catalog', help='выгрузка каталога (JSON-список {sid|id, name, role}) — названия товаров, остановившихся до этапа 8')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args(argv)
    runs = [os.path.expanduser(r).rstrip('/') for r in a.runs]
    PC, PS, rules, repo = pf.load_pc(a.repo)
    per_by = {}
    for r in runs:
        _stages, per = pf.analyse(PC, PS, rules, r)
        per_by[os.path.basename(r)] = per
    out = a.out or os.path.join(runs[0], '_report')
    return report(runs, per_by, out, repo, a.name, a.publish, catalog=a.catalog)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
