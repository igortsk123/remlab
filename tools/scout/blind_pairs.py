#!/usr/bin/env python3
"""P6 свода №12: СЛЕПАЯ ОЦЕНКА владельцем — пары «greedy vs beam» на одной сцене.

Берём сцены, где beam выбрал не greedy-гипотезу (meta.beam.improved), перегоняем
сцену с LAYOUT_BEAM=0 (greedy) → две картинки A/B без подписи (порядок случайный, но
детерминированный от имени сцены), ключ ответов — отдельно (blind-key.json).
Выход: ~/scout-scenes/blind/ (index.html + пары), ключ НЕ публикуется на /test/.
Запуск: ~/venvs/scout/bin/python blind_pairs.py [N=20]
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/blind')
PY = sys.executable
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def main() -> None:
    scenes = {s['id']: s for s in json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))}
    improved = []
    for f in sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json'))):
        art = json.load(open(f, encoding='utf-8'))
        bm = art.get('_beam') or {}
        if bm.get('improved'):
            sid = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
            improved.append(sid)
    # детерминированная выборка: по хэшу имени, ровные страты по площади
    improved.sort(key=lambda s: hashlib.md5(s.encode()).hexdigest())
    picked = improved[:N]
    os.makedirs(OUT, exist_ok=True)
    key = []
    cards = []
    for i, sid in enumerate(picked, 1):
        sc = scenes[sid]
        env = dict(os.environ, LAYOUT_ENGINE='zoned', LAYOUT_BEAM='0',
                   LAYOUT_SUFFIX=f'-blind-greedy-{sid}')
        args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
        if sc.get('kind') == 'contour':
            xs = [p[0] for p in sc['contour']]; ys = [p[1] for p in sc['contour']]
            env['SCENE_CONTOUR'] = json.dumps(sc['contour']); args += [str(max(xs)), str(max(ys))]
        elif 'w' in sc:
            args += [str(sc['w']), str(sc['d'])]
        subprocess.run(args, capture_output=True, text=True, timeout=900, env=env)
        g_png = os.path.join(HERE, f"v3set{sc['set']}-layout-blind-greedy-{sid}.png")
        b_png = os.path.join(HERE, f"v3set{sc['set']}-layout-acc-zoned-{sid}.png")
        if not (os.path.exists(g_png) and os.path.exists(b_png)):
            continue
        flip = int(hashlib.md5(('flip' + sid).encode()).hexdigest(), 16) % 2 == 1
        a_src, b_src = (b_png, g_png) if flip else (g_png, b_png)
        shutil.copy(a_src, os.path.join(OUT, f'pair{i:02d}-A.png'))
        shutil.copy(b_src, os.path.join(OUT, f'pair{i:02d}-B.png'))
        key.append({'pair': i, 'scene': sid, 'A': 'beam' if flip else 'greedy',
                    'B': 'greedy' if flip else 'beam'})
        cards.append(
            f"<section><h2>Пара {i:02d} <small>({sc.get('w', '')}×{sc.get('d', '')} "
            f"{'контур' if sc.get('kind') == 'contour' else ''})</small></h2>"
            f"<div class='row'><figure><img src='pair{i:02d}-A.png'><figcaption>A</figcaption></figure>"
            f"<figure><img src='pair{i:02d}-B.png'><figcaption>B</figcaption></figure></div>"
            f"<p>Какой план лучше? <b>A</b> / <b>B</b> / одинаково — и почему (одно слово).</p></section>")
    html = ("<!doctype html><meta charset='utf-8'><title>Слепая оценка — свод №12</title>"
            "<style>body{font-family:sans-serif;max-width:1400px;margin:20px auto;padding:0 12px}"
            ".row{display:flex;gap:12px}figure{flex:1;margin:0}img{max-width:100%;border:1px solid #ccc}"
            "figcaption{text-align:center;font-weight:bold;font-size:22px}section{border-top:1px solid #ddd;padding:14px 0}</style>"
            "<h1>Слепая оценка: два плана одной комнаты</h1><p>Порядок A/B перемешан. Ответы: номер пары → A/B/=. "
            "Ключ (какой из них — новый движок) владельцу не показывается до подсчёта.</p>" + ''.join(cards))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(html)
    json.dump(key, open(os.path.join(HERE, 'blind-key.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'OK: {len(key)} пар → {OUT} (ключ: tools/scout/blind-key.json — НЕ публиковать)')


if __name__ == '__main__':
    main()
