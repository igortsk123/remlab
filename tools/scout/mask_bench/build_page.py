"""Сборка страницы сравнения: листы вшиваются в HTML как data-URI (внешние ссылки в артефакте
запрещены политикой безопасности)."""
import base64
import json
import os
import shutil
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = '/tmp/claude-1000/-home-pakar-igor-remlab/5651abb0-003c-46ff-abc6-fdb6db95fca6/scratchpad'
VARIANTS = ['A-now', 'B-heavy2k', 'C-matte2k', 'D-bria2', 'E-hybrid']
TITLES = {'A-now': 'A · Как сейчас', 'B-heavy2k': 'B · BiRefNet Heavy 2K',
          'C-matte2k': 'C · BiRefNet Matting 2K', 'D-bria2': 'D · BRIA RMBG 2.0',
          'E-hybrid': 'E · Наш гибрид'}
WHAT = {
    'A-now': 'То, что стоит в проде: BiRefNet General Light, 1024 px, дефолтные настройки. '
             'Ровно эта модель едет в нашем образе на Salad.',
    'B-heavy2k': 'Тот же BiRefNet, но «тяжёлая» модель на 2048 px с доводкой края. '
                 'Казалось очевидным улучшением.',
    'C-matte2k': 'BiRefNet в режиме матирования на 2048 px — вариант, заточенный под мягкий край.',
    'D-bria2': 'Другая сеть: BRIA RMBG 2.0. В нашем замере 04.08 проигрывала — но с тех пор '
               'её на fal подменили новой версией.',
    'E-hybrid': 'Не отдельная сеть, а наша надстройка над D: сеть решает, ЧТО товар, '
                'а на белой карточке мы возвращаем тонкие детали по цвету фона. Тень режется.',
}
HL = ['20-стеллаж-17194919', '14-комод-11733765', '09-столик-15220974', '16-комод-13729667']


def b64(p):
    return 'data:image/jpeg;base64,' + base64.b64encode(open(p, 'rb').read()).decode()


def main(site_dir=None):
    """site_dir задан → страница для нашего сайта: картинки отдельными файлами рядом,
    а не data-URI (иначе одна страница на 8 МБ грузится целиком до первого показа)."""
    rep = json.load(open(os.path.join(ROOT, 'report.json')))
    agg = {}
    for v in VARIANTS:
        tk, ls, iou, bad = [], [], [], 0
        for r in rep.values():
            m = r['v'][v]
            iou.append(m['iou_consensus'])
            if 'thin_keep' in m:
                tk.append(m['thin_keep'])
                ls.append(m['lost'])
                if m['lost'] > 8:
                    bad += 1
        agg[v] = {'thin': float(np.median(tk)), 'lost': float(np.median(ls)),
                  'iou': float(np.median(iou)), 'bad': bad}

    roles = sorted({r['meta']['role'] for r in rep.values()})
    if site_dir:
        os.makedirs(os.path.join(site_dir, 'sheets'), exist_ok=True)
    cards = []
    for iid, r in sorted(rep.items()):
        it = r['meta']
        img = os.path.join(ROOT, 'final', iid + '.jpg')
        if not os.path.exists(img):
            continue
        if site_dir:
            name = f'{len(cards):02d}.jpg'
            shutil.copyfile(img, os.path.join(site_dir, 'sheets', name))
            src = 'sheets/' + name
        else:
            src = b64(img)
        hard = ' data-hard="1"' if iid in HL else ''
        cards.append(
            f'<figure class="sheet" data-role="{it["role"]}"{hard}>'
            f'<img src="{src}" alt="{it["name"]}" loading="lazy">'
            f'</figure>')

    def row(v):
        a = agg[v]
        cls = ' class="win"' if v == 'E-hybrid' else (' class="bad"' if v == 'B-heavy2k' else '')
        return (f'<tr{cls}><th scope="row">{TITLES[v]}</th>'
                f'<td>{a["thin"]:.0f}%</td><td>{a["lost"]:.2f}%</td>'
                f'<td>{a["iou"]:.3f}</td><td>{a["bad"]}</td>'
                f'<td class="what">{WHAT[v]}</td></tr>')

    chips = ''.join(f'<button class="chip" data-f="{r}">{r}</button>' for r in roles)
    # str.format здесь непригоден: в CSS полно фигурных скобок
    html = TEMPLATE
    for k, v in (('{rows}', ''.join(row(x) for x in VARIANTS)),
                 ('{chips}', chips),
                 ('{cards}', '\n'.join(cards)),
                 ('{n}', str(len(cards))),
                 ('{uniform}', str(sum(1 for r in rep.values()
                                       if 'thin_keep' in r['v']['A-now'])))):
        html = html.replace(k, v)
    if site_dir:
        html = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta name="robots" content="noindex">' + html
                .replace('<header>', '</head><body><header>', 1) + '</body></html>')
        p = os.path.join(site_dir, 'index.html')
    else:
        os.makedirs(OUT, exist_ok=True)
        p = os.path.join(OUT, 'cutout-bench.html')
    open(p, 'w').write(html)
    print(p, round(os.path.getsize(p) / 1e6, 2), 'MB')


TEMPLATE = r"""<title>Пять вырезальщиков фона</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --paper:#f6f7f8; --card:#ffffff; --ink:#151d24; --ink-2:#4a565f; --ink-3:#7d8990;
  --line:#dfe4e7; --line-2:#eef1f3;
  --accent:#276876; --accent-soft:#e4eff1;
  --good:#2f6b45; --warn:#a5591c; --bad:#a33b32;
  --shadow:0 1px 2px rgba(21,29,36,.05), 0 8px 24px rgba(21,29,36,.05);
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#10161a; --card:#161d22; --ink:#e7ecee; --ink-2:#a5b1b7; --ink-3:#76848b;
  --line:#263037; --line-2:#1d262b;
  --accent:#6fb6c4; --accent-soft:#17262b;
  --good:#6fbf90; --warn:#d99a55; --bad:#e08a80;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.28);
}}
:root[data-theme="dark"]{
  --paper:#10161a; --card:#161d22; --ink:#e7ecee; --ink-2:#a5b1b7; --ink-3:#76848b;
  --line:#263037; --line-2:#1d262b;
  --accent:#6fb6c4; --accent-soft:#17262b;
  --good:#6fbf90; --warn:#d99a55; --bad:#e08a80;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.28);
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,Segoe UI,Roboto,sans-serif;
  font-size:16px;line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:1220px;margin:0 auto;padding:0 24px}
.narrow{max-width:680px}
h1,h2,h3{font-family:Spectral,Georgia,serif;font-weight:600;text-wrap:balance;margin:0}
h1{font-size:clamp(2rem,4.4vw,3rem);line-height:1.12;letter-spacing:-.015em}
h2{font-size:1.65rem;line-height:1.2;margin-bottom:.5rem}
h3{font-size:1.12rem;margin-bottom:.3rem}
p{margin:0 0 1rem}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:.735rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);margin:0 0 .9rem}
header{padding:72px 0 44px;border-bottom:1px solid var(--line)}
.lede{font-family:Spectral,Georgia,serif;font-size:1.24rem;line-height:1.55;color:var(--ink-2);
  max-width:60ch;margin-top:1.1rem}
section{padding:52px 0;border-bottom:1px solid var(--line-2)}
section:last-of-type{border-bottom:0}
.verdict{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  margin-top:26px}
.v{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:18px 20px;
  box-shadow:var(--shadow)}
.v .tag{font-family:"IBM Plex Mono",monospace;font-size:.7rem;letter-spacing:.1em;
  text-transform:uppercase;margin-bottom:.5rem}
.v.take .tag{color:var(--good)} .v.drop .tag{color:var(--bad)} .v.keep .tag{color:var(--warn)}
.v p{margin:0;font-size:.94rem;color:var(--ink-2)}
.v strong{color:var(--ink);font-weight:600}
.tbl{overflow-x:auto;margin-top:22px;border:1px solid var(--line);border-radius:3px;
  background:var(--card)}
table{border-collapse:collapse;width:100%;min-width:800px;font-size:.9rem}
th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line-2);vertical-align:top}
thead th{font-family:"IBM Plex Mono",monospace;font-size:.7rem;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-3);font-weight:500;background:var(--line-2)}
tbody th{font-weight:600;white-space:nowrap}
td{font-variant-numeric:tabular-nums;color:var(--ink-2)}
td.what{font-variant-numeric:normal;min-width:290px;font-size:.86rem;line-height:1.5}
tr.win th,tr.win td{background:var(--accent-soft)}
tr.win th{color:var(--accent)}
tr.bad th{color:var(--bad)}
.note{border-left:2px solid var(--accent);padding:2px 0 2px 18px;color:var(--ink-2);
  font-size:.94rem;margin:22px 0}
.note strong{color:var(--ink)}
.legend{display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
  margin-top:24px}
.legend div{font-size:.9rem;color:var(--ink-2)}
.legend b{display:block;color:var(--ink);font-weight:600;margin-bottom:.2rem}
.bar{margin-top:26px;display:flex;flex-wrap:wrap;gap:7px;align-items:center;
  position:sticky;top:0;background:var(--paper);padding:14px 0;z-index:5;
  border-bottom:1px solid var(--line-2)}
.chip{font:500 .82rem/1 "IBM Plex Sans",sans-serif;padding:7px 13px;border-radius:2px;
  border:1px solid var(--line);background:var(--card);color:var(--ink-2);cursor:pointer}
.chip:hover{border-color:var(--accent);color:var(--accent)}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
:root[data-theme="dark"] .chip[aria-pressed="true"],
:root:not([data-theme="light"]) .chip[aria-pressed="true"]{color:#0d1417}
.chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.sheets{margin-top:8px;display:flex;flex-direction:column;gap:16px}
.sheet{margin:0;background:var(--card);border:1px solid var(--line);border-radius:3px;
  overflow-x:auto;box-shadow:var(--shadow)}
.sheet img{display:block;width:100%;min-width:960px}
.sheet[hidden]{display:none}
footer{padding:46px 0 76px;color:var(--ink-3);font-size:.85rem}
code{font-family:"IBM Plex Mono",monospace;font-size:.87em;background:var(--line-2);
  padding:.1em .35em;border-radius:2px}
@media (prefers-reduced-motion:no-preference){.chip{transition:background .12s,color .12s,border-color .12s}}
</style>

<header>
  <div class="wrap">
    <p class="eyebrow">Замер · 36 товаров · 28 августа 2026</p>
    <h1>Пять вырезальщиков фона</h1>
    <p class="lede">Одни и те же 36 товаров — стулья, комоды, стеллажи, столики, торшеры —
    прогнаны через пять способов вырезки. Смотреть надо на нижний ряд каждого листа: это зум
    на самую тонкую деталь, и именно там варианты расходятся.</p>
  </div>
</header>

<section>
  <div class="wrap">
    <h2>Что выбрать</h2>
    <div class="verdict">
      <div class="v take"><p class="tag">Брать</p><p><strong>E · Наш гибрид.</strong>
        Держит тонкое лучше всех на всех 28 белых карточках. Денег не стоит — это надстройка
        над сетью, чистый расчёт по цвету фона.</p></div>
      <div class="v keep"><p class="tag">Запасной</p><p><strong>D · BRIA RMBG 2.0.</strong>
        Лучшая из чистых сетей и заметно лучше того, что стоит сейчас. Годится там, где фон
        не белый и аналитика не работает.</p></div>
      <div class="v drop"><p class="tag">Не брать</p><p><strong>B · BiRefNet Heavy 2K.</strong>
        Выглядел очевидным апгрейдом, а на деле стирает фасады комодов и теряет распорки.
        Провалов в 3–4 раза больше, чем у остальных.</p></div>
      <div class="v drop"><p class="tag">Не брать</p><p><strong>C · Matting 2K.</strong>
        Делает крупные светлые фасады полупрозрачными. На тонком не выигрывает.</p></div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>Цифры</h2>
    <p class="narrow" style="color:var(--ink-2)">Медиана по {uniform} карточкам с ровным фоном.
    «Тонкое» — какую долю деталей толщиной в 1–2 пикселя вариант сохранил. «Потери» — сколько
    видимого на фото товара исчезло. «Провалы» — сколько товаров из 36 потеряли больше 8%.</p>
    <div class="tbl">
      <table>
        <thead><tr><th scope="col">Вариант</th><th scope="col">Тонкое</th><th scope="col">Потери</th>
        <th scope="col">Согласие</th><th scope="col">Провалы</th><th scope="col">Что это</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <p class="note"><strong>Честная оговорка.</strong> Эталонной разметки «где на самом деле
    товар» у нас нет, поэтому «тонкое» и «потери» считаются по цвету фона — а гибрид E этим же
    цветом и пользуется. Его 95% частично засчитаны ему по построению. Сравнение
    A / B / C / D между собой от этого не страдает, но окончательное решение принимайте
    глазами по листам ниже, а не по таблице.</p>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>Как читать лист</h2>
    <div class="legend">
      <div><b>Верхний ряд</b>Вырезка целиком на шахматке. Шахматка обязательна: на белом фоне
      пропавшая белая ножка и оставшийся кусок фона выглядят одинаково.</div>
      <div><b>Нижний ряд</b>Зум на самое тонкое место товара, найденное автоматически.
      Основная разница между вариантами живёт здесь.</div>
      <div><b>Подпись «тонкое»</b>Доля сохранённых деталей толщиной 1–2 px именно у этого товара.</div>
      <div><b>Подпись «фон»</b>Сколько фона осталось внутри маски. Ноль почти везде — эту ошибку
      сегодня не делает никто.</div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <h2>Все {n} товаров</h2>
    <div class="bar">
      <button class="chip" data-f="all" aria-pressed="true">все</button>
      <button class="chip" data-f="hard">показательные</button>
      {chips}
    </div>
    <div class="sheets" id="sheets">
{cards}
    </div>
  </div>
</section>

<section>
  <div class="wrap narrow">
    <h2>Отдельная находка</h2>
    <p>Все фото в нашем каталоге — <strong>450 пикселей в ширину</strong>. Столько отдаёт фид
    Гдеслона, и другого размера на его картиночном сервере нет. На таком снимке проволочная
    ножка занимает один-два пикселя физически, и ни один вырезальщик не восстановит то, чего
    в файле нет.</p>
    <p>При этом у самих магазинов лежат оригиналы: у divan.ru — до 1920×1440, то есть вчетверо
    больше по стороне. Дотянуться до них можно, но не через фид, а со страницы товара, и для
    каждого магазина по-своему. Из проверенных: divan.ru отдаёт крупное, tvoydom.ru и
    mnogomebeli.com — нет. Это отдельная задача, но по влиянию на тонкие детали она,
    похоже, больше, чем выбор вырезальщика.</p>
  </div>
</section>

<footer>
  <div class="wrap">Замер: 36 товаров из <code>candidates-index.json</code>, роли отобраны с
  упором на тонкие детали. Варианты A–D посчитаны на fal, E — локально поверх D.
  Листы и метрики — <code>/home/pakar/igor/_bench-mask</code>.</div>
</footer>

<script>
(function(){
  var chips=[].slice.call(document.querySelectorAll('.chip'));
  var sheets=[].slice.call(document.querySelectorAll('.sheet'));
  function apply(f){
    chips.forEach(function(c){c.setAttribute('aria-pressed', String(c.dataset.f===f));});
    sheets.forEach(function(s){
      var show = f==='all' ? true : (f==='hard' ? s.dataset.hard==='1' : s.dataset.role===f);
      s.hidden = !show;
    });
    try{localStorage.setItem('cutbench.filter',f);}catch(e){}
  }
  chips.forEach(function(c){c.addEventListener('click',function(){apply(c.dataset.f);});});
  var saved='all';
  try{saved=localStorage.getItem('cutbench.filter')||'all';}catch(e){}
  if(!chips.some(function(c){return c.dataset.f===saved;})) saved='all';
  apply(saved);
})();
</script>
"""

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
