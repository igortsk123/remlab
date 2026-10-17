#!/usr/bin/env python3
"""СТРАНИЦА ГАЙДОВ СТИЛЕЙ ДЛЯ ВЛАДЕЛЬЦА (план demo-11 п.3): шесть текстов `render_guide` из канона (`tools/scout/styles.json`) —
то, что уходит в модель «реалистично» как описание ремонта, — и по стилю последнее фото нейросети новой модели из реестра кадров.
Пишет одну страницу и кладёт её на прод в `/test/share/style-guides/`.

    python3 tools/ops/style-guides-page.py            # собрать и выложить
    python3 tools/ops/style-guides-page.py --local    # только собрать в /tmp/style-guides.html
"""
import html
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
MODEL = os.environ.get('EXPECT_MODEL', 'improve/openai/gpt-image-2.5-sunburst')
# что просим у модели — коротко по-русски (сам текст в модель идёт по-английски)
RU = {
    'сканди': 'тёплые белые стены с кремовым оттенком, светлый дуб, предзакатный тёплый свет 3500 K, льняные шторы, 1–2 постера, растение',
    'современный': 'тёплый грейж или тауп, одна стена глубже (глина, олива), дуб среднего тона, тёплый свет 3700 K, льняные шторы, одна картина',
    'минимализм': 'одна светлая тёплая гамма стен, бесшовный светлый пол, мягкий рассеянный свет 4000 K, лёгкий тюль, максимум одна картина',
    'лофт': 'стена из тёплого кирпича, остальные — тёплый «бетон», тёмный пол, тёмный потолок, тёплый свет 3500 K, тёмные шторы',
    'неоклассика': 'кремовые стены, сдержанные молдинги, карниз, ёлочка из дуба, золотистый свет 3300 K, кремовые шторы до пола',
    'джапанди': 'стены — тёплый песок/глина под известь, светлый ясень, мягкий тёплый свет 3500 K, льняные шторы, ветка в керамике',
}


def main() -> int:
    db = json.load(open(os.path.join(ROOT, 'tools/scout/styles.json'), encoding='utf-8'))
    try:
        reg = json.loads(urllib.request.urlopen('https://remont-lab.online/test/share/shots.json', timeout=30).read().decode())
    except Exception:  # noqa: BLE001 — без реестра страница всё равно нужна: тексты
        reg = []
    last = {}
    for r in reg:
        if r.get('quality') == 'realistic' and r.get('model') == MODEL and r.get('shots'):
            if r.get('ts', 0) >= last.get(r.get('style'), {}).get('ts', 0):
                last[r.get('style')] = r
    cards = []
    for st, rec in db['styles'].items():
        g = rec.get('render_guide') or ''
        ph = last.get(st)
        imgs = ''.join(f'<a href="{html.escape(s["url"])}" target="_blank"><img src="{html.escape(s.get("thumb") or s["url"])}" '
                       f'alt="{html.escape(st)} {html.escape(s.get("camera") or "")}" loading="lazy"></a>' for s in (ph or {}).get('shots', []))
        cards.append(f'<section><h2>{html.escape(st)}</h2><p class="ru">{html.escape(RU.get(st, ""))}</p>'
                     f'<div class="ph">{imgs or "<span class=no>фото — после пересъёмки этого стиля</span>"}</div>'
                     f'<details><summary>текст для модели (как уходит)</summary><p class="en">{html.escape(g)}</p></details></section>')
    page = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Гайды стилей</title><style>:root{--ink:#2b2622;--muted:#6f665e;--line:#e6dfd6;--bg:#faf7f2;--card:#fff;--acc:#a8613f}'
            '@media(prefers-color-scheme:dark){:root{--ink:#eee7df;--muted:#b3a99e;--line:#3a332d;--bg:#1d1a17;--card:#26221e}}'
            'body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:980px;margin:0 auto;padding:20px 16px 60px}'
            'h1{font-size:24px;margin:0 0 6px}.lead{color:var(--muted);margin:0 0 20px}section{background:var(--card);border:1px solid var(--line);'
            'border-radius:14px;padding:16px;margin:0 0 16px}h2{margin:0 0 4px;font-size:20px;text-transform:capitalize}.ru{margin:0 0 10px}'
            '.ph{display:flex;gap:10px;flex-wrap:wrap}.ph img{width:min(460px,100%);border-radius:10px;display:block}.no{color:var(--muted)}'
            'details{margin-top:10px}summary{cursor:pointer;color:var(--acc)}.en{color:var(--muted);font-size:14px}</style></head><body><main>'
            '<h1>Гайды стилей для фото нейросети</h1><p class="lead">Модель gpt-image-2.5-sunburst, качество medium, промпт improve-v2 '
            '(«фотографический вид» и правило каталожной формы). Под каждым стилем — что просим коротко и последнее фото этой моделью.</p>'
            + ''.join(cards) + '</main></body></html>')
    out = '/tmp/style-guides.html'
    open(out, 'w', encoding='utf-8').write(page)
    if '--local' in sys.argv:
        print(out)
        return 0
    subprocess.run(['ssh', '-o', 'BatchMode=yes', 'root@89.167.127.0', 'mkdir -p /opt/remlab/test/share/style-guides'], check=True)
    subprocess.run(['scp', '-q', out, 'root@89.167.127.0:/opt/remlab/test/share/style-guides/index.html'], check=True)
    print('выложено: https://remont-lab.online/test/share/style-guides/ · фото есть у', ', '.join(sorted(last)) or 'никого')
    return 0


if __name__ == '__main__':
    sys.exit(main())
