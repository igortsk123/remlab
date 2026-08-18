#!/usr/bin/env python3
"""Q7 свода №13: СЛЕПАЯ ОЦЕНКА раунд 2 — пары «текущий ключ выбора (v1) vs новый (v2)».

Берём сцены, где новый ключ выбрал бы ДРУГОЙ план (`_beam.v2_would_choose != chosen`),
перегоняем сцену с LAYOUT_PLAN_KEY=v2 → две картинки A/B без подписей (порядок случайный,
детерминированный от имени сцены). Ключ ответов — `blind2-key.json`, НЕ публикуется.
Выборка стратифицирована по площади (малые/средние/просторные/XL по кругу), партиями по 20
(владелец: «лучше меньше 20»).

  blind_pairs_v2.py [N=20] [--batch K]     # K-я партия (1-based), без повторов
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/scout-scenes/blind2')
PY = sys.executable


def _scene_args(sc: dict) -> tuple:
    env = dict(os.environ, LAYOUT_ENGINE='zoned', LAYOUT_PLAN_KEY='v2',
               LAYOUT_SUFFIX="-blind2-v2-" + sc['id'])
    args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
    if sc.get('kind') == 'contour':
        xs = [p[0] for p in sc['contour']]
        ys = [p[1] for p in sc['contour']]
        env['SCENE_CONTOUR'] = json.dumps(sc['contour'])
        args += [str(max(xs)), str(max(ys))]
    elif 'w' in sc:
        args += [str(sc['w']), str(sc['d'])]
    if sc.get('openings'):
        env['SCENE_OPENINGS'] = json.dumps(sc['openings'])
    return args, env


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 20
    batch = int(sys.argv[sys.argv.index('--batch') + 1]) if '--batch' in sys.argv else 1
    scenes = {s['id']: s for s in json.load(open(os.path.join(HERE, 'acceptance-scenes.json'), encoding='utf-8'))}
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    diverge = []
    for f in sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json'))):
        art = json.load(open(f, encoding='utf-8'))
        bm = art.get('_beam') or {}
        w, c = bm.get('v2_would_choose'), bm.get('chosen')
        if w and c and w != c:
            sid = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
            if sid in scenes:
                diverge.append(sid)

    def band(sid):
        m2 = sets[scenes[sid]['set'] - 1]['m2']
        return 'small' if m2 < 20 else ('trans' if m2 < 25 else ('large' if m2 < 40 else 'xl'))

    by = {}
    for sid in sorted(diverge, key=lambda s: hashlib.md5(s.encode()).hexdigest()):
        by.setdefault(band(sid), []).append(sid)
    order = []
    while any(by.values()):
        for b in ('small', 'trans', 'large', 'xl'):
            if by.get(b):
                order.append(by[b].pop(0))
    picked = order[(batch - 1) * n: batch * n]
    if not picked:
        print('партия %d пуста (расхождений всего %d)' % (batch, len(diverge)))
        return
    os.makedirs(OUT, exist_ok=True)
    key, cards = [], []
    for i, sid in enumerate(picked, 1 + (batch - 1) * n):
        sc = scenes[sid]
        args, env = _scene_args(sc)
        subprocess.run(args, capture_output=True, text=True, timeout=1800, env=env)
        v2_png = os.path.join(HERE, "v3set%s-layout-blind2-v2-%s.png" % (sc['set'], sid))
        v1_png = os.path.join(HERE, "v3set%s-layout-acc-zoned-%s.png" % (sc['set'], sid))
        if not (os.path.exists(v1_png) and os.path.exists(v2_png)):
            print('  пропуск %s: нет картинки' % sid)
            continue
        flip = int(hashlib.md5(('flip2' + sid).encode()).hexdigest(), 16) % 2 == 1
        a_src, b_src = (v2_png, v1_png) if flip else (v1_png, v2_png)
        shutil.copy(a_src, os.path.join(OUT, 'pair%02d-A.png' % i))
        shutil.copy(b_src, os.path.join(OUT, 'pair%02d-B.png' % i))
        key.append({'pair': i, 'scene': sid, 'm2': sets[sc['set'] - 1]['m2'],
                    'A': 'v2' if flip else 'v1', 'B': 'v1' if flip else 'v2'})
        cards.append(
            "<section><h2>Пара %d</h2>"
            "<div class='row'><figure><img src='pair%02d-A.png' alt='A'><figcaption>A</figcaption></figure>"
            "<figure><img src='pair%02d-B.png' alt='B'><figcaption>B</figcaption></figure></div>"
            "<p class='ask'>Что лучше — <b>A</b>, <b>B</b> или <b>оба плохи</b>? Одной строкой: «%d: A — почему».</p></section>"
            % (i, i, i, i))
    style = ("body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui}"
             ".wrap{max-width:1100px;margin:0 auto;padding:20px 14px 60px}h1{font-size:22px}"
             "section{border-top:1px solid #E4E6E2;padding:16px 0}h2{font-size:18px;margin:0 0 8px}"
             ".row{display:flex;gap:14px;flex-wrap:wrap}figure{margin:0;flex:1 1 460px}"
             "img{width:100%;border:1px solid #ECEEEA;border-radius:4px}"
             "figcaption{font-weight:600;padding:4px 0}.ask{color:#3A423C;font-size:16px}"
             ".head{margin:10px 0;padding:10px 12px;border-left:3px solid #3B76A2;background:#F4F7FA;font-size:15.5px}")
    head = ("<div class='head'>На каждой паре — ОДНА И ТА ЖЕ комната и один и тот же набор мебели, "
            "но два разных решения движка. Что за чем стоит — не подписано специально. Скажите, какой "
            "вариант лучше как жильё: <b>A</b>, <b>B</b> или <b>оба плохи</b>, и коротко почему. "
            "Ответы — одной строкой на пару, например «3: B — диван не смотрит в окно».</div>")
    page = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='robots' content='noindex'><meta http-equiv='cache-control' content='no-store'>"
            "<title>Слепая оценка — раунд 2</title><style>%s</style></head><body><div class='wrap'>"
            "<h1>Слепая оценка планов — раунд 2 (партия %d)</h1>%s%s</div></body></html>"
            % (style, batch, head, ''.join(cards)))
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    kp = os.path.join(HERE, 'blind2-key.json')
    prev = json.load(open(kp, encoding='utf-8')) if os.path.exists(kp) else []
    json.dump(prev + key, open(kp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('партия %d: пар %d → %s (ключ %s; расхождений всего %d)'
          % (batch, len(key), OUT, os.path.basename(kp), len(diverge)))


if __name__ == '__main__':
    main()
