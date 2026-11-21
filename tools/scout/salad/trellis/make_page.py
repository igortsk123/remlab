#!/usr/bin/env python3
"""СТРАНИЦА ПРОБЫ ГЕНЕРАТОРОВ МЕШЕЙ (T-20261118-91, владелец TG 2082): `/test/mesh-models-1118/` — статический сайт из папки кадров.

ЧТО ПОКАЗЫВАЕТ. Для каждого товара набора: фото товара и вырезка-вход, а под ними — кадры меша КАЖДОЙ модели (по 20: 10 ракурсов × текстура/глина),
подпись модели открыто (анонимность снята владельцем). Кадры — отдельными картинками, не сеткой: в странице миниатюра, по клику — полный размер
(стрелки/Esc, свайп не нужен). Страницу дополняем по мере готовности моделей: прогнал снова — добавилось.

ВХОД (папка кадров `--frames`, по умолчанию ~/remlab-logs/mesh-models-1118/frames):
  <frames>/<модель>/<sku с «_» вместо «:»>/*.png|jpg|webp   — кадры по возрастанию имени (имя без расширения — подпись кадра)
  <frames>/<модель>/results.json                              — необязательно: {sku: {"status","reason","total_s","triangles","size_mb","cost_usd","note"}}
  <frames>/models.json                                        — необязательно: порядок и подписи моделей {"trellis2": {"title": "...", "note": "..."}}
Набор товаров — `--set` (set30.json), фото и вырезки — `--inputs` (inputs30: `inputs.json` с image_url, `<sku>.cut-preview.png`).

ВЫХОД (`--out`): index.html (сводка товар × модель, ссылки), p/<sku>.html (товар целиком), img/<модель>/<sku>/NN.webp (≤1600 px) и NN.t.webp (миниатюра 480),
photos/<sku>.jpg. Вес картинок ограничен (диск сайта: свободно ~8,5 ГБ, приём мешей закрывается ниже 7): печатается итог в МБ, превышение `--max-mb` — отказ.
Выкладка на сервер — отдельным шагом и только по слову директора; сам генератор ничего не выкладывает.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.request

FULL_PX, THUMB_PX = 1600, 480
EXT = ('.png', '.jpg', '.jpeg', '.webp')
DEFAULT_MODELS = {
    'trellis2': {'title': 'TRELLIS.2', 'note': 'Microsoft, 4B, MIT; вход — наша вырезка'},
    'hunyuan21': {'title': 'Hunyuan3D-2.1 (боевой)', 'note': 'контроль: боевой генератор, та же видеокарта RTX 4090'},
    'pixal3d': {'title': 'Pixal3D', 'note': ''},
}
CSS = """
:root{--bg:#fafaf8;--fg:#1c1c1a;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--acc:#2f5d50;--bad:#a33}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--mut:#9a9992;--card:#20201e;--line:#34332f;--acc:#8fc5b4;--bad:#e08a8a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.4em 0 .3em}h3{font-size:1rem;margin:1.2em 0 .2em}
a{color:var(--acc)}.mut{color:var(--mut);font-size:.9rem}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.top{display:flex;gap:12px;flex-wrap:wrap}.top figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px}
.top img{display:block;max-height:260px;max-width:100%;border-radius:4px}figcaption{font-size:.8rem;color:var(--mut);padding:4px 2px 0}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.frames a{display:block;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:3px;text-decoration:none}
.frames img{display:block;width:100%;height:auto;border-radius:3px}.frames span{display:block;font-size:.72rem;color:var(--mut);padding:2px}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;justify-content:center;z-index:9}#lb.on{display:flex}
#lb img{max-width:96vw;max-height:92vh}#lb p{position:fixed;bottom:6px;left:0;right:0;text-align:center;color:#ddd;margin:0;font-size:.85rem}
nav a{margin-right:12px}
"""
JS = """
(function(){var lb=document.getElementById('lb'),im=lb.querySelector('img'),cap=lb.querySelector('p'),list=[],i=0;
function show(k){i=(k+list.length)%list.length;im.src=list[i].href;cap.textContent=list[i].title+'  ('+(i+1)+'/'+list.length+')'}
document.querySelectorAll('.frames').forEach(function(g){g.querySelectorAll('a').forEach(function(a,k,all){a.addEventListener('click',function(e){e.preventDefault();list=Array.prototype.slice.call(all);show(k);lb.classList.add('on')})})});
lb.addEventListener('click',function(e){if(e.target===lb||e.target===im)lb.classList.remove('on')});
document.addEventListener('keydown',function(e){if(!lb.classList.contains('on'))return;if(e.key==='Escape')lb.classList.remove('on');if(e.key==='ArrowRight')show(i+1);if(e.key==='ArrowLeft')show(i-1)})})();
"""


def fname(sku: str) -> str:
    return sku.replace(':', '_')


def to_webp(src: str, dst: str, px: int, q: int) -> int:
    """Картинка → webp не больше px по большей стороне; уже сделанное и свежее не трогает. Возвращает размер файла, байт."""
    from PIL import Image
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return os.path.getsize(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im = Image.open(src)
    im.load()
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
    if max(im.size) > px:
        k = px / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    im.save(dst, 'WEBP', quality=q, method=6)
    return os.path.getsize(dst)


def fetch_photo(url: str, dst: str) -> bool:
    """Фото товара из магазина (одно на товар, кэш в out/photos). Нет сети/адреса — False: покажем только вырезку."""
    if os.path.exists(dst):
        return True
    if not url:
        return False
    if url.startswith('//'):
        url = 'https:' + url
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (mesh-models-page)'})
        data = urllib.request.urlopen(req, timeout=30).read()
    except (OSError, ValueError):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst + '.src', 'wb').write(data)
    try:
        to_webp(dst + '.src', dst, FULL_PX, 85)
    except Exception:  # noqa: BLE001 — битая картинка магазина не роняет страницу
        os.remove(dst + '.src')
        return False
    os.remove(dst + '.src')
    return True


def list_frames(d: str) -> list[str]:
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d) if n.lower().endswith(EXT))


def load_json(p: str, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def meta_line(r: dict) -> str:
    bits = []
    if r.get('total_s') is not None:
        bits.append(f'{r["total_s"]} с')
    if r.get('triangles') is not None:
        bits.append(f'{int(r["triangles"]):,} треуг.'.replace(',', ' '))
    if r.get('size_mb') is not None:
        bits.append(f'{r["size_mb"]} МБ')
    if r.get('cost_usd') is not None:
        bits.append(f'${r["cost_usd"]}')
    if r.get('note'):
        bits.append(r['note'])
    return ' · '.join(esc(b) for b in bits)


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body><main>{body}</main>'
            f'<div id="lb"><img alt=""><p></p></div><script>{JS}</script></body></html>')


def build(frames: str, set_path: str, inputs_dir: str, out: str, max_mb: float, fetch=fetch_photo) -> dict:
    products = load_json(set_path, [])
    inputs = load_json(os.path.join(inputs_dir, 'inputs.json'), {})
    cfg = {**DEFAULT_MODELS, **load_json(os.path.join(frames, 'models.json'), {})}
    present = [m for m in cfg if os.path.isdir(os.path.join(frames, m))]
    results = {m: load_json(os.path.join(frames, m, 'results.json'), {}) for m in present}
    total = 0
    n_frames = 0
    index_rows = []
    os.makedirs(os.path.join(out, 'p'), exist_ok=True)
    for pr in products:
        sku = pr['sku']
        fn = fname(sku)
        inp = inputs.get(sku, {})
        top = []
        photo = os.path.join(out, 'photos', fn + '.jpg.webp')
        if fetch(inp.get('image_url') or pr.get('image_url') or '', photo):
            total += os.path.getsize(photo)
            top.append(f'<figure><a href="../photos/{esc(fn)}.jpg.webp"><img src="../photos/{esc(fn)}.jpg.webp" alt="фото товара"></a><figcaption>фото товара (магазин)</figcaption></figure>')
        cut = os.path.join(inputs_dir, fn + '.cut-preview.png')
        if os.path.exists(cut):
            dst = os.path.join(out, 'photos', fn + '.cut.webp')
            total += to_webp(cut, dst, 900, 85)
            top.append(f'<figure><img src="../photos/{esc(fn)}.cut.webp" alt="вход"><figcaption>вход для моделей: вырезка</figcaption></figure>')
        sec = []
        cells = []
        for m in present:
            t = cfg[m].get('title', m)
            files = list_frames(os.path.join(frames, m, fn))
            r = results[m].get(sku, {})
            if not files:
                reason = r.get('reason') or ('нет меша' if r.get('status') in ('failed', 'no_mesh') else 'ещё не сделано')
                sec.append(f'<h3>{esc(t)}</h3><p class="mut {"bad" if r.get("status") in ("failed", "no_mesh") else ""}">{esc(reason)}</p>')
                cells.append(f'<td class="{"bad" if r.get("status") in ("failed", "no_mesh") else "mut"}">{esc(reason)}</td>')
                continue
            links = []
            for k, fp in enumerate(files):
                stem = os.path.splitext(os.path.basename(fp))[0]
                full = os.path.join(out, 'img', m, fn, f'{k:02d}.webp')
                thumb = os.path.join(out, 'img', m, fn, f'{k:02d}.t.webp')
                total += to_webp(fp, full, FULL_PX, 82) + to_webp(fp, thumb, THUMB_PX, 72)
                n_frames += 1
                rel = f'../img/{esc(m)}/{esc(fn)}/{k:02d}'
                links.append(f'<a href="{rel}.webp" title="{esc(t)} · {esc(stem)}"><img src="{rel}.t.webp" loading="lazy" alt="{esc(stem)}"><span>{esc(stem)}</span></a>')
            ml = meta_line(r)
            sec.append(f'<h3>{esc(t)}</h3><p class="mut">{esc(cfg[m].get("note", ""))}{" · " if ml and cfg[m].get("note") else ""}{ml}</p><div class="frames">{"".join(links)}</div>')
            cells.append(f'<td>{len(files)} кадров{("<br><span class=mut>" + ml + "</span>") if ml else ""}</td>')
        hard = ', '.join(pr.get('hard') or [])
        dims = '×'.join(f'{x:g}' for x in pr.get('dims_cm') or [])
        head = (f'<nav><a href="../index.html">← все товары</a></nav><h1>{esc(pr.get("name", sku))}</h1>'
                f'<p class="mut">{esc(pr.get("role", ""))} · {esc(dims)} см · {esc(sku)}{" · трудное: " + esc(hard) if hard else ""}</p>')
        open(os.path.join(out, 'p', fn + '.html'), 'w', encoding='utf-8').write(page(pr.get('name', sku), head + f'<div class="top">{"".join(top)}</div>' + ''.join(sec)))
        index_rows.append(f'<tr><td><a href="p/{esc(fn)}.html">{esc(pr.get("name", sku))}</a><br><span class="mut">{esc(pr.get("role", ""))}{" · " + esc(hard) if hard else ""}</span></td>{"".join(cells)}</tr>')
    th = ''.join(f'<th>{esc(cfg[m].get("title", m))}</th>' for m in present)
    body = (f'<h1>Пробная сверка генераторов 3D-мешей</h1><p class="mut">{len(products)} товаров; модели подписаны открыто. Нажми на товар — кадры каждой модели, '
            f'по клику на кадр — крупно (стрелки ← → листают, Esc закрывает).</p>'
            f'<table><tr><th>Товар</th>{th}</tr>{"".join(index_rows)}</table>')
    open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(page('Сверка генераторов мешей', body))
    mb = total / 2 ** 20
    if mb > max_mb:
        raise SystemExit(f'картинки {mb:.0f} МБ > предела {max_mb:.0f} МБ — уменьшить качество или число кадров (диск сайта)')
    return {'products': len(products), 'models': present, 'frames': n_frames, 'mb': round(mb, 1)}


def main() -> None:
    base = os.path.expanduser('~/remlab-logs/mesh-models-1118')
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', default=os.path.join(base, 'frames'))
    ap.add_argument('--set', default=os.path.join(base, 'trellis', 'set30.json'))
    ap.add_argument('--inputs', default=os.path.join(base, 'trellis', 'inputs30'))
    ap.add_argument('--out', default=os.path.join(base, 'site'))
    ap.add_argument('--max-mb', type=float, default=1500.0, help='предел веса картинок страницы, МБ (диск сайта)')
    a = ap.parse_args()
    r = build(a.frames, a.set, a.inputs, a.out, a.max_mb)
    print(json.dumps(r, ensure_ascii=False), '→', a.out)


if __name__ == '__main__':
    sys.exit(main())
