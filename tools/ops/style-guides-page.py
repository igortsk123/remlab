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
RU = {   # что просим — простым языком, 5–7 строк (сам текст в модель идёт по-английски, план demo-13)
    'сканди': ['Стены — тёплый белый с кремовым или светло-бежевым оттенком, одна стена может быть чуть темнее', 'Пол — светлый матовый дуб или ясень',
               'Плинтус и двери — простые белые', 'Свет — светлый, мягкий, чуть золотистый дневной', 'Люстра — широкий плоский северный плафон, матовый белый с деталью светлого дуба, у потолка, выключена', 'Шторы — длинный лён кремового цвета на тонком карнизе',
               'Картины — одна-две графики в чёрных рамках, одно растение', 'Нельзя: глянец, золото, узоры, холодный серый, лишние вещи'],
    'современный': ['Стены — гладкие тёплые серо-бежевые; за диваном или ТВ можно одну стену глубже (графит, олива, глина)', 'Пол — широкая доска тёплого среднего тона',
                    'Плинтус тонкий, двери гладкие с чёрной ручкой', 'Свет — ровный дневной, чёткие мягкие тени', 'Люстра — низкое скульптурное кольцо в тонкой чёрной раме с молочным рассеивателем, у потолка, выключена', 'Шторы — простые льняные от потолка или рулонная штора',
                    'Картина — одна большая абстракция с единственным акцентным цветом, одно скульптурное растение', 'Нельзя: лепнина, «деревенское», хром, пастель, обои с узором'],
    'минимализм': ['Стены — одна светлая тёплая гамма, гладко или тонкая штукатурка, без акцентной стены', 'Пол — бесшовный светлый, дерево или микроцемент',
                   'Плинтус почти невидимый, дверь в цвет стены', 'Свет — мягкий рассеянный, почти без теней', 'Люстра — широкий ультратонкий диск тёплого белого цвета, почти вровень с потолком, выключена', 'Окно — сплошной лёгкий тюль от потолка до пола',
                   'Картина — одна крупная спокойная или ни одной; пустые поверхности — так задумано', 'Нельзя: узоры, яркие акценты, глянец, мелочи'],
    'лофт': ['Стена за диваном или ТВ — открытый кирпич, остальные — тёплый «бетон» или графит', 'Пол — тёмная доска или серый бетон',
             'Плинтус и двери — тёмные, прямые линии', 'Свет — тёплый дневной вдоль кирпича, чуть контрастнее, мебель хорошо видна', 'Люстра — широкий плоский фабричный плафон из матовой чёрной стали на очень коротком подвесе, выключена',
             'Шторы — тяжёлый лён графит или ржавчина на чёрной трубе, или без штор', 'Картина — большой ч/б постер в тонкой чёрной раме, высокое растение', 'Нельзя: глянец, золото, лепнина, пастель, цветочки'],
    'неоклассика': ['Стены — кремовые, тёплые бежевые или пыльно-голубые с тонкими белыми молдингами симметрично', 'Пол — дубовая ёлочка светло-медового тона',
                    'Потолок с простым карнизом, высокий профильный плинтус, филёнчатая белая дверь с латунной ручкой', 'Свет — тёплый золотистый, мягкие блики на молдингах', 'Люстра — небольшая плоская симметричная с тонкими рожками под состаренную латунь и прозрачным стеклом, скромная розетка, короткий подвес, выключена',
                    'Шторы — тяжёлые в пол с мягкими складками и белый тюль', 'Картина — классическая живопись или пара гравюр, или зеркало; белая орхидея', 'Нельзя: колонны, барокко, много золота, глянцевые потолки, «дворец»'],
    'джапанди': ['Стены — известковая или фактурная штукатурка: песок, глина, «грибной» тон', 'Пол — светлый матовый ясень или дуб; тёмное дерево — только в дверях и отделке',
                 'Плинтус низкий, дверь — дуб или орех с маленькой чёрной ручкой', 'Свет — мягкий тёплый, как через бумажные ширмы', 'Люстра — широкий приплюснутый бумажный фонарь на тонком каркасе из светлого дерева или бамбука, у потолка, выключена', 'Шторы — сырой лён или бамбуковая штора',
                 'Картина — тушь или ботаника в тонкой деревянной раме, чуть не по центру; растение в керамике ручной работы', 'Нельзя: глянец, золото, яркие цвета, нарочитая симметрия, пластик'],
}


def main() -> int:
    db = json.load(open(os.path.join(ROOT, 'tools/scout/styles.json'), encoding='utf-8'))
    # пробные фото гайдов (demo-13): `tools/ops/style-trials.mjs` пишет их вне общего реестра — карточки вариантов до приёмки не меняются
    trials = {}
    tp = os.path.expanduser(os.environ.get('STYLE_TRIALS', '~/scout-scenes/style-trials.json'))
    if os.path.exists(tp):
        trials = json.load(open(tp, encoding='utf-8'))
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
        ph = trials.get(st) or last.get(st)
        imgs = ''.join(f'<a href="{html.escape(s["url"])}" target="_blank"><img src="{html.escape(s.get("thumb") or s["url"])}" '
                       f'alt="{html.escape(st)} {html.escape(s.get("camera") or "")}" loading="lazy"></a>' for s in (ph or {}).get('shots', []))
        cards.append(f'<section><h2>{html.escape(st)}</h2><ul class="ru">{"".join(f"<li>{html.escape(x)}</li>" for x in RU.get(st, []))}</ul>'
                     f'<div class="ph">{imgs or "<span class=no>фото — после пересъёмки этого стиля</span>"}</div>'
                     f'<details><summary>текст для модели (как уходит)</summary><p class="en">{html.escape(g)}</p></details></section>')
    page = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Гайды стилей</title><style>:root{--ink:#2b2622;--muted:#6f665e;--line:#e6dfd6;--bg:#faf7f2;--card:#fff;--acc:#a8613f}'
            '@media(prefers-color-scheme:dark){:root{--ink:#eee7df;--muted:#b3a99e;--line:#3a332d;--bg:#1d1a17;--card:#26221e}}'
            'body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:980px;margin:0 auto;padding:20px 16px 60px}'
            'h1{font-size:24px;margin:0 0 6px}.lead{color:var(--muted);margin:0 0 20px}section{background:var(--card);border:1px solid var(--line);'
            'border-radius:14px;padding:16px;margin:0 0 16px}h2{margin:0 0 4px;font-size:20px;text-transform:capitalize}.ru{margin:0 0 10px}'
            '.ru{margin:0 0 10px;padding-left:20px}.ph{display:flex;gap:10px;flex-wrap:wrap}.ph img{width:min(460px,100%);border-radius:10px;display:block}.no{color:var(--muted)}'
            'details{margin-top:10px}summary{cursor:pointer;color:var(--acc)}.en{color:var(--muted);font-size:14px}</style></head><body><main>'
            '<h1>Гайды стилей для фото нейросети</h1><p class="lead">Модель gpt-image-2.5-sunburst, качество medium, промпт improve-v3.2 '
            '(гайды стилей v2.1, demo-13; люстра стиля — demo-20 Г4). Под каждым стилем — что просим простым языком, пробное фото этим гайдом (обе точки) и текст для модели.</p>'
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
