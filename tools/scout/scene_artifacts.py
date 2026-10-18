#!/usr/bin/env python3
"""НОЧНОЙ ОТЧЁТ ОБ АРТЕФАКТАХ СЦЕНЫ ПО ОПУБЛИКОВАННЫМ ВАРИАНТАМ ДЕМО (план demo-05, п.1 — только отчёт, публикацию не держит).

Ворота публикации — `scene_checks.py` (наезд, тёмная модель; их зовёт `flat215_demo.py`). Здесь — таблица для человека
и хаба /test/ по тем же данным витрины (`~/scout-scenes/flat215-demo/demo-data.json` = `/demo/demo-data.json`):
  (а) наезды — `scene_checks.overlap_pairs`: ОДИН Г-след с воротами (`planner/geometry.py:footprint`), порог 2 см.
      Сторона оттоманки — флаг `corner_left`: живая сцена и серверный кадр зеркалят модель под него
      (`lib/viewer3d/viewer.ts` → `meshes.ts:chaiseSide`, `draft_render.py` → `scene_mesh.chaise_side`). Если сторону по
      модели узнать нельзя (нет исходника на диске или мера молчит) — модель рисуется как есть, след по флагу может
      не совпасть с картинкой: это отдельная заметка.
  (в) текстуры — у каждой модели варианта и декора (кроме ковра — он фото на полу) в лёгких копиях `/rt/` (полная
      и `-lite`) есть картинка под картой цвета материала, не пустая и разбирается (JPEG/PNG/WebP — PIL; KTX2 —
      заголовок и уровни по спецификации Khronos, PIL KTX2 не читает). Иначе «без текстуры». Читается только сама
      лёгкая копия (0,1–0,4 МБ), геометрия не декодируется.
  (ж) ковёр и декор в данных варианта: ковёр с фото и ценой, ваза с ценой и моделью.
Не покрыто (нужен браузер/движок): (б) чёрные пиксели в кадре, (г) первая точка обзора, (д) камера прогулки; (е) пины в
кадре — живой тест в браузере (`e2e/live/demo-scenarios.live.ts`, «пины в кадре»), не здесь.

  ~/venvs/scout/bin/python tools/scout/scene_artifacts.py [--data PATH|URL] [--rt DIR] [--out DIR] [--date YYYY-MM-DD]
Выход: таблица в stdout, `<out>/<дата>.json` и `<out>/index.html` (страница для хаба /test/; публикация — не здесь).
Последняя строка — вердикт для ночного журнала (`verdict`): `WARN:scene_artifacts: …` с названиями красных вариантов
(уходит в дайджест) или `scene_artifacts: OK — …` с числами. Ночью (`refresh_daily.sh`, шаг `scene_artifacts`) данные
берутся с прода (`--data https://remont-lab.online/demo/demo-data.json`), фото ковра — HEAD по адресу страницы.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import os
import struct
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scene_checks as SC  # noqa: E402

DATA = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
RT = os.path.expanduser('~/scout-scenes/flat3d-rt')          # то, что `publish_rt.sh` выкладывает на /rt/
OUT = os.path.expanduser('~/scout-scenes/scene-checks')
# исходники моделей — только с диска (кэш `runtime_mesh.fetch_source` и галерея), ничего не качаем
SRC_DIRS = (os.path.expanduser('~/scout-scenes/flat3d-src/{}.glb'),
            os.path.expanduser('~/scout-scenes/mesh-pilot-gallery/{}/model.glb'))
NOT_COVERED = [
    ('б', 'чёрный предмет — доля тёмных пикселей по маске объекта в кадре', 'нужен рендер сцены'),
    ('г', 'первая точка обзора 3D видит ≥ 3 предмета ядра', 'нужен движок сцены/браузер'),
    ('д', 'камера прогулки не входит в след предмета', 'нужен движок прогулки (walk.ts)'),
    ('е', 'пины цен в пределах кадра', 'живой тест в браузере — e2e/live/demo-scenarios.live.ts'),
]


def load_data(src: str) -> tuple[dict, str]:
    if src.startswith('http'):
        with urllib.request.urlopen(src, timeout=60) as r:  # noqa: S310 — свой прод
            raw = r.read()
    else:
        raw = open(os.path.expanduser(src), 'rb').read()
    return json.loads(raw), hashlib.sha1(raw).hexdigest()[:12]


def model_id(sku: dict | None) -> str:
    sku = sku or {}
    m = sku.get('msid') or sku.get('sid') or ''
    return '' if ':' in m else m              # заглушки вида `tv:…` — не модели


# ——— (а) сторона оттоманки у Г-дивана ——————————————————————————————————————————

def model_chaise_side(mid: str, yaw: float) -> tuple[str | None, str]:
    """Сторона оттоманки у модели — мерой `scene_mesh.chaise_side` по исходнику с диска; (None, почему) — не узнать."""
    path = next((p.format(mid) for p in SRC_DIRS if os.path.exists(p.format(mid))), None)
    if not path:
        return None, 'нет исходника модели на диске'
    try:
        import trimesh
        import scene_mesh as SM
        sc = trimesh.load(path, force='scene', process=False)
        parts = [g for g in sc.dump() if hasattr(g, 'vertices') and len(g.vertices)]
        side = SM.chaise_side(parts, yaw)
        return side, '' if side else 'мера не видит оттоманку'
    except Exception as e:  # noqa: BLE001 — одна модель не валит отчёт, причина — в заметке
        return None, f'модель не разобрана: {str(e)[:60]}'


def chaise_notes(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if not it.get('corner'):
            continue
        sku = it.get('sku') or {}
        side, why = model_chaise_side(model_id(sku), float(sku.get('yaw') or 0))
        want = 'left' if it.get('corner_left') else 'right'
        if side is None:
            out.append({'item': it['role'], 'problem': 'сторона оттоманки по модели не определена — модель рисуется '
                        'без зеркала, след по флагу может не совпасть', 'value': why})
        elif side != want:
            out.append({'item': it['role'], 'problem': 'оттоманка модели с другой стороны — сцена зеркалит её под флаг',
                        'value': f'модель {side}, флаг {want}'})
    return out


# ——— (в) текстуры в лёгких копиях ————————————————————————————————————————————

KTX2_ID = b'\xabKTX 20\xbb\r\n\x1a\n'


def check_ktx2(b: bytes) -> str:
    """'' — KTX2 цел; иначе причина. Спецификация KTX 2.0: заголовок, индекс, уровни внутри файла и не пустые."""
    if len(b) < 80 or b[:12] != KTX2_ID:
        return 'не KTX2 (нет подписи)'
    (_fmt, _ts, w, h, _dep, _lay, _faces, levels, scheme) = struct.unpack_from('<9I', b, 12)
    _dfo, _dfl, _kvo, _kvl, sgo, sgl = struct.unpack_from('<4I2Q', b, 48)
    if w == 0 or h == 0:
        return f'размер {w}×{h}'
    n = max(levels, 1)
    if 80 + 24 * n > len(b):
        return 'обрезан индекс уровней'
    for k in range(n):
        off, ln, _ = struct.unpack_from('<3Q', b, 80 + 24 * k)
        if ln == 0 or off + ln > len(b):
            return f'уровень {k} пуст или за концом файла'
    if scheme == 1 and (sgl == 0 or sgo + sgl > len(b)):     # BasisLZ: без глобальных данных не декодируется
        return 'BasisLZ без глобальных данных'
    return ''


def check_image(b: bytes, mime: str) -> str:
    if not b:
        return 'пустая картинка (0 байт)'
    if mime == 'image/ktx2' or b[:12] == KTX2_ID:
        return check_ktx2(b)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(b)) as im:
            im.verify()
        return ''
    except Exception as e:  # noqa: BLE001
        return f'не открывается: {str(e)[:50]}'


def parse_glb(b: bytes) -> tuple[dict, bytes]:
    magic, _ver, _ln = struct.unpack_from('<III', b, 0)
    if magic != 0x46546C67:
        raise ValueError('не GLB')
    jl, _jt = struct.unpack_from('<II', b, 12)
    j = json.loads(b[20:20 + jl])
    off, binb = 20 + jl, b''
    if off + 8 <= len(b):
        bl, _bt = struct.unpack_from('<II', b, off)
        binb = b[off + 8: off + 8 + bl]
    return j, binb


def glb_textures(b: bytes) -> tuple[int, list[str]]:
    """(сколько годных картинок под картой цвета материалов, проблемы). 0 годных — «без текстуры»."""
    j, binb = parse_glb(b)
    imgs, texs, bvs = j.get('images') or [], j.get('textures') or [], j.get('bufferViews') or []
    used = {((m.get('pbrMetallicRoughness') or {}).get('baseColorTexture') or {}).get('index')
            for m in j.get('materials') or []} - {None}
    probs, good = [], 0
    for ti in sorted(used):
        t = texs[ti] if ti < len(texs) else {}
        src = (t.get('extensions') or {}).get('KHR_texture_basisu', {}).get('source', t.get('source'))
        if src is None or src >= len(imgs):
            probs.append(f'текстура {ti} без картинки')
            continue
        im = imgs[src]
        if 'bufferView' not in im:
            probs.append(f'картинка {src} снаружи файла ({str(im.get("uri", ""))[:30]})')
            continue
        bv = bvs[im['bufferView']]
        s, ln = int(bv.get('byteOffset') or 0), int(bv.get('byteLength') or 0)
        why = check_image(binb[s:s + ln] if s + ln <= len(binb) else b'', im.get('mimeType', ''))
        if why:
            probs.append(f'картинка {src}: {why}')
        else:
            good += 1
    return good, probs


def check_textures(mid: str, rt_dir: str) -> list[dict]:
    out = []
    for suf in ('', '-lite'):
        p = os.path.join(rt_dir, f'{mid}{suf}.glb')
        copy = suf or 'полная'
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            out.append({'copy': copy, 'problem': 'нет лёгкой копии', 'value': os.path.basename(p)})
            continue
        try:
            good, probs = glb_textures(open(p, 'rb').read())
        except Exception as e:  # noqa: BLE001
            out.append({'copy': copy, 'problem': 'копия не разбирается', 'value': str(e)[:60]})
            continue
        if not good:
            out.append({'copy': copy, 'problem': 'без текстуры', 'value': '; '.join(probs) or 'материал без карты цвета'})
        elif probs:
            out.append({'copy': copy, 'problem': 'часть текстур битая', 'value': '; '.join(probs)})
    return out


# ——— (ж) ковёр и декор в данных —————————————————————————————————————————————

def photo_exists(data_dir: str, img: str) -> bool:
    """Фото рядом с данными: на диске — файл; данные с прода — HEAD по тому же адресу, что берёт страница."""
    if not data_dir.startswith('http'):
        return os.path.exists(os.path.join(data_dir, img))
    try:
        req = urllib.request.Request(urllib.parse.urljoin(data_dir, img), method='HEAD')
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 — свой прод
            return r.status == 200
    except Exception:  # noqa: BLE001 — 404 и отказ сети одинаково «фото не видно»
        return False


def check_rug_decor(v: dict, data_dir: str) -> list[dict]:
    out = []
    rugs = [it for it in v.get('items') or [] if SC._base(it['role']) == 'ковёр']
    if not rugs:
        out.append({'item': 'ковёр', 'problem': 'нет ковра в варианте', 'value': ''})
    for it in rugs:
        sku = it.get('sku') or {}
        img = str(sku.get('img') or '')
        if not img:
            out.append({'item': it['role'], 'problem': 'ковёр без фото', 'value': sku.get('name', '')})
        elif data_dir and not img.startswith(('http', '//')) and not photo_exists(data_dir, img):
            out.append({'item': it['role'], 'problem': 'фото ковра нет в выкладке', 'value': img})
        if not (sku.get('price') or 0) > 0:
            out.append({'item': it['role'], 'problem': 'ковёр без цены', 'value': sku.get('name', '')})
    vases = [x for x in v.get('decor') or [] if SC._base(x.get('role', '')) == 'ваза']
    if not vases:
        out.append({'item': 'ваза', 'problem': 'нет вазы в декоре', 'value': ''})
    for x in vases:
        sku = x.get('sku') or {}
        if not (sku.get('price') or 0) > 0:
            out.append({'item': x['role'], 'problem': 'ваза без цены', 'value': sku.get('name', '')})
        if not model_id(sku):
            out.append({'item': x['role'], 'problem': 'ваза без модели', 'value': sku.get('name', '')})
    return out


# ——— сборка отчёта ————————————————————————————————————————————————————————————

def run(data: dict, rt_dir: str, data_dir: str, thr: float = SC.OVERLAP_CM) -> dict:
    rows, summary = [], []
    for v in data.get('variants') or []:
        vid, style, items = v.get('id'), v.get('style'), v.get('items') or []
        base = {'variant': vid, 'style': style}
        ovs, notes = SC.overlap_pairs(items, thr), chaise_notes(items)
        for o in ovs:
            rows.append({**base, 'check': 'а', 'item': f"{o['a']} × {o['b']}", 'problem': 'наезд',
                         'value': f"{o['depth_cm']:g} см (полоса {o['len_cm']:g} см)", 'depth_cm': o['depth_cm']})
        rows += [{**base, 'check': 'а', **n} for n in notes]
        models: dict[str, str] = {}
        for it in list(items) + list(v.get('decor') or []):
            m = model_id(it.get('sku'))
            if m and SC._base(it.get('role', '')) != 'ковёр':
                models.setdefault(m, it['role'])
        no_tex = set()
        for m, role in models.items():
            for t in check_textures(m, rt_dir):
                no_tex.add(m)
                rows.append({**base, 'check': 'в', 'item': f'{role} ({m})', 'problem': f"{t['problem']} [{t['copy']}]",
                             'value': t['value']})
        rd = check_rug_decor(v, data_dir)
        rows += [{**base, 'check': 'ж', **r} for r in rd]
        summary.append({**base, 'title': v.get('title') or style, 'overlaps_gt_thr': len(ovs), 'max_overlap_cm': max([o['depth_cm'] for o in ovs], default=0.0),
                        'models': len(models), 'models_without_texture': len(no_tex), 'chaise_notes': len(notes),
                        'rug_decor_problems': len(rd)})
    return {'rows': rows, 'summary': summary}


def verdict(rep: dict) -> list[str]:
    """Строки для ночного журнала и дайджеста. Красное — ОДНА строка `WARN:scene_artifacts:` с названиями всех красных
    вариантов (дайджест берёт первую WARN-строку шага, до 200 знаков); зелёное — одна строка OK с числами, чтобы по журналу
    было видно, что шаг прошёл. Красное: наезд глубже порога, модель без текстуры (или без лёгкой копии), ковёр/ваза (ж).
    Заметки об оттоманке — не красное."""
    sm, thr = rep['summary'], f"{rep['threshold_cm']:g}"
    if not sm:
        return ['WARN:scene_artifacts: в опубликованных данных нет вариантов']
    red = []
    for s in sm:
        why = []
        if s['overlaps_gt_thr']:
            why.append(f"наезд {s['max_overlap_cm']:g} см")
        if s['models_without_texture']:
            why.append(f"без текстуры {s['models_without_texture']}")
        why += list(dict.fromkeys(r['problem'] for r in rep['rows'] if r['variant'] == s['variant'] and r['check'] == 'ж'))
        if why:
            red.append(f"{s.get('title') or s['style']} ({s['variant']}): {', '.join(why)}")
    if red:
        return [f'WARN:scene_artifacts: красных {len(red)} из {len(sm)} — ' + '; '.join(red)]
    return [f"scene_artifacts: OK — вариантов {len(sm)}, наездов > {thr} см 0, моделей {sum(s['models'] for s in sm)} — "
            f"все с текстурой, ковёр и ваза у всех, заметок об оттоманке {sum(s['chaise_notes'] for s in sm)}"]


def table(rows: list[dict]) -> str:
    head = ('вариант', 'предмет', 'проблема', 'величина')
    body = [(f"{r['variant']} {r['style']}", r['item'], f"({r['check']}) {r['problem']}", str(r.get('value', '')))
            for r in rows]
    if not body:
        return 'находок нет'
    wd = [min(max(len(x[i]) for x in [head] + body), 60) for i in range(3)]
    fmt = lambda x: '  '.join(x[i][:60].ljust(wd[i]) for i in range(3)) + '  ' + x[3]  # noqa: E731
    return '\n'.join([fmt(head)] + [fmt(x) for x in body])


def page(rep: dict) -> str:
    e = html.escape
    thr = f"{rep['threshold_cm']:g}"
    srows = ''.join(
        f"<tr><td>{e(s['variant'])} · {e(s['style'])}</td><td class=n>{s['overlaps_gt_thr']}</td>"
        f"<td class=n>{s['max_overlap_cm']:g}</td><td class=n>{s['models_without_texture']} из {s['models']}</td>"
        f"<td class=n>{s['rug_decor_problems']}</td><td class=n>{s['chaise_notes']}</td></tr>" for s in rep['summary'])
    frows = ''.join(
        f"<tr><td>{e(r['variant'])} · {e(r['style'])}</td><td>{e(r['item'])}</td><td>({e(r['check'])}) {e(r['problem'])}"
        f"</td><td>{e(str(r.get('value', '')))}</td></tr>" for r in rep['rows']) \
        or '<tr><td colspan=4>Находок нет</td></tr>'
    nc = ''.join(f"<li>({e(k)}) {e(t)} — <i>{e(w)}</i></li>" for k, t, w in NOT_COVERED)
    return f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Проверка сцен демо</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe6;--mut:#9a9993;--line:#2f2f2c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 8px}}
p.m{{color:var(--mut);margin:0 0 12px}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mut);font-weight:500}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main>
<h1>Проверка сцен демо</h1>
<p class=m>{e(rep['date'])} · данные {e(rep['source'])} (sha {e(rep['data_sha'])}) · порог наезда {thr} см ·
только отчёт; ворота публикации — <code>scene_checks.py</code> (план demo-05 п.1)</p>
<h2>Сводка по вариантам</h2><div class=wrap><table><tr><th>Вариант</th><th>Наездов &gt; {thr} см</th>
<th>Макс., см</th><th>Без текстуры</th><th>Ковёр и ваза: проблем</th><th>Оттоманка: заметок</th></tr>{srows}</table></div>
<h2>Находки</h2><div class=wrap><table><tr><th>Вариант</th><th>Предмет</th><th>Проблема</th><th>Величина</th></tr>{frows}</table></div>
<h2>Не покрыто</h2><ul>{nc}</ul>
</main></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description='отчёт об артефактах сцены по опубликованным вариантам демо')
    ap.add_argument('--data', default=DATA, help='demo-data.json: путь или URL')
    ap.add_argument('--rt', default=RT, help='каталог лёгких копий (то, что выкладывается на /rt/)')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--threshold', type=float, default=SC.OVERLAP_CM)
    a = ap.parse_args()
    data, sha = load_data(a.data)
    data_dir = a.data if a.data.startswith('http') else os.path.dirname(os.path.expanduser(a.data))
    rep = {'date': a.date, 'source': a.data, 'data_sha': sha, 'rt_dir': a.rt, 'threshold_cm': a.threshold,
           **run(data, a.rt, data_dir, a.threshold),
           'not_covered': [{'check': k, 'what': t, 'why': w} for k, t, w in NOT_COVERED]}
    print(table(rep['rows']))
    print()
    for s in rep['summary']:
        print(f"{s['variant']} {s['style']}: наездов > {a.threshold:g} см — {s['overlaps_gt_thr']} (макс. "
              f"{s['max_overlap_cm']:g}), без текстуры — {s['models_without_texture']} из {s['models']}, ковёр/ваза — "
              f"{s['rug_decor_problems']}, оттоманка — {s['chaise_notes']}")
    print('не покрыто здесь: ' + ', '.join(f'({k})' for k, _, _ in NOT_COVERED))
    os.makedirs(a.out, exist_ok=True)
    jp = os.path.join(a.out, f'{a.date}.json')
    json.dump(rep, open(jp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(a.out, 'index.html'), 'w', encoding='utf-8').write(page(rep))
    print(f'отчёт: {jp} · страница: {os.path.join(a.out, "index.html")}')
    print('\n'.join(verdict(rep)), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
