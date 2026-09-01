#!/usr/bin/env python3
"""Галерея пилота мешей: исходник → вырезка → вертящаяся 3D-модель. Публикуется на /test/.

Зачем страница, а не файлы. Владелец оценивает ДВЕ вещи, и обе — глазами: качественно ли
режется фото (просьба 29.08: «проверь фотки, что качественно режутся») и похож ли меш на
товар со всех сторон. Рендеры с фиксированных углов прячут спину и бока — поэтому модель
вертится в браузере (<model-viewer>, GLB как есть); вырезка — на клетчатом фоне, где виден
каждый съеденный пиксель и каждый прилипший кусок фона.

  ~/venvs/scout/bin/python gallery_build.py           # собрать в ~/scout-scenes/mesh-pilot-gallery
"""
import base64
import glob
import html
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

SRC = os.environ.get('GALLERY_SRC', os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
OUT = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')

CHECKER = ('data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000001000000010080200000090916836000000'
    '1d49444154289163fccfc0c0f09f818181f93f0323430323430323835d0d00a67b032500'
    'b7ac7e9c0000000049454e44ae426082')).decode()).replace('\n', '')


# Отметки владельца прямо на карточке (просьба 01.09): «светлее / темнее / переделать»,
# как табы — нажал/отжал, можно переключить, если промахнулся. Хранятся в браузере
# (localStorage, один ключ на весь сайт), поэтому переживают переход между страницами и
# пересборку галереи конвейером. Итог владелец копирует одной кнопкой и присылает.
# Обычные строки, НЕ f-строки: скобки CSS/JS не надо экранировать.
MARKS_CSS = """
 .marks{display:flex;gap:6px;margin-top:8px}
 .mk{flex:1;padding:7px 4px;font:13px system-ui;cursor:pointer;border:1px solid #d5d5cf;
   border-radius:6px;background:#fff;color:#333}
 .mk:hover{background:#f2f2ee}
 .mk.on{border-color:#1c1c1a;background:#1c1c1a;color:#fff;font-weight:600}
 .card[data-mark="light"]{box-shadow:0 0 0 2px #e0a53a}
 .card[data-mark="dark"]{box-shadow:0 0 0 2px #4a6fb5}
 .card[data-mark="redo"]{box-shadow:0 0 0 2px #c04a3e}
 .seed{font-size:11px;color:#888;font-weight:400}
 #panel{position:fixed;right:14px;bottom:14px;z-index:9;background:#fff;border:1px solid #d5d5cf;
   border-radius:10px;padding:10px 12px;font:13px system-ui;box-shadow:0 3px 14px #0002;max-width:330px}
 #panel button{font:12px system-ui;padding:5px 8px;margin:6px 4px 0 0;border:1px solid #d5d5cf;
   border-radius:6px;background:#fff;cursor:pointer}
 #out{display:none;width:305px;height:150px;margin-top:8px;font:11px/1.35 monospace}
"""

MARKS_JS = """
(function(){
  var KEY='meshMarks', NAMES={light:'светлее',dark:'темнее',redo:'переделать'};
  function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
  function save(m){try{localStorage.setItem(KEY,JSON.stringify(m))}catch(e){alert('Браузер не даёт сохранить отметки')}}
  function paint(){
    var m=load(), cnt={light:0,dark:0,redo:0};
    for(var k in m){if(cnt[m[k]]!==undefined)cnt[m[k]]++;}
    document.querySelectorAll('.card').forEach(function(c){
      var v=m[c.dataset.sku]||'';
      if(v){c.dataset.mark=v;}else{c.removeAttribute('data-mark');}
      c.querySelectorAll('.mk').forEach(function(b){b.classList.toggle('on',b.dataset.m===v);});
    });
    document.getElementById('cnt').textContent='светлее '+cnt.light+' · темнее '+cnt.dark+
      ' · переделать '+cnt.redo;
  }
  function text(){
    var m=load(), by={light:[],dark:[],redo:[]};
    for(var k in m){if(by[m[k]])by[m[k]].push(k);}
    var s='';
    ['light','dark','redo'].forEach(function(t){
      s+=NAMES[t]+' ('+by[t].length+'):\\n'+(by[t].join('\\n')||'—')+'\\n\\n';
    });
    return s.trim();
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest('.mk');
    if(b){var c=b.closest('.card'), s=c.dataset.sku, m=load();
      if(m[s]===b.dataset.m){delete m[s];}else{m[s]=b.dataset.m;}
      save(m); paint(); return;}
    if(e.target.id==='copy'){
      var t=text(), ta=document.getElementById('out');
      ta.style.display='block'; ta.value=t; ta.select();
      if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){
        document.getElementById('copy').textContent='скопировано';
        setTimeout(function(){document.getElementById('copy').textContent='скопировать отметки';},1500);
      });}else{document.execCommand('copy');}
    }
    if(e.target.id==='clr'){
      if(confirm('Стереть ВСЕ отметки?')){save({});paint();document.getElementById('out').style.display='none';}
    }
  });
  document.addEventListener('DOMContentLoaded',paint);
})();
"""

PANEL_HTML = """
<div id="panel">
  <div><b>Мои отметки</b></div>
  <div id="cnt">светлее 0 · темнее 0 · переделать 0</div>
  <button id="copy">скопировать отметки</button><button id="clr">стереть всё</button>
  <textarea id="out" readonly></textarea>
  <div style="color:#888;font-size:11px;margin-top:6px">Отметки живут в этом браузере и
   сохраняются при переходе между страницами.</div>
</div>
"""


def build() -> str:
    rows = []
    best = {}                     # на SKU показываем ОДИН меш — самый свежий (перегон затирает брак)
    for d in sorted(glob.glob(os.path.join(SRC, '*/*/')), key=lambda p: -os.path.getmtime(os.path.join(p,'manifest.json')) if os.path.exists(os.path.join(p,'manifest.json')) else 0):
        man_p = os.path.join(d, 'manifest.json')
        if not os.path.exists(man_p):
            continue
        man = json.load(open(man_p, encoding='utf-8'))
        if os.path.exists(os.path.join(d, 'owner_reject.json')):
            continue                  # забракован владельцем — не показываем, ждёт перегона
        if man['sku'] in best:
            continue
        import asset_strategy as AS
        if AS.strategy(man.get('role')) != 'hunyuan3d':
            continue
        # Показ: ТОЛЬКО оригинал генератора (владелец 01.09 — «ремонт калечит, оставляй
        # оригинальные модели»). Копии model.repaired.glb выведены из конвейера и не
        # читаются даже если лежат рядом.
        model_src = os.path.join(d, 'model.glb')
        if not os.path.exists(model_src):
            continue                  # suspect-комплект (одна диагностика): SKU не занимаем,
            # пусть показывается предыдущая версия с мешом
        best[man['sku']] = True
        sku = man['sku'].replace(':', '_')
        item_dir = os.path.join(OUT, sku)
        os.makedirs(item_dir, exist_ok=True)
        # Копируем только изменившееся: сборка галереи идёт КАЖДЫЙ цикл конвейера, а
        # перекладывать 200 неизменных GLB по 30 МБ — это минуты дискового ввода впустую.
        for f in ('model.glb', 'cutout.png', 'input.png'):
            s = os.path.join(d, f)
            if not os.path.exists(s):
                continue
            t = os.path.join(item_dir, f)
            if os.path.exists(t) and os.path.getmtime(t) >= os.path.getmtime(s) \
                    and os.path.getsize(t) == os.path.getsize(s):
                continue
            open(t, 'wb').write(open(s, 'rb').read())
        # Статус — из `verdict.json` шага приёмки, а НЕ пересчётом PBR-гейта здесь: гейт
        # грузит каждый GLB заново (~40 с на модель, 2+ часа на каталог), а на странице
        # не показывается вовсе — только в консольной сводке.
        try:
            v = json.load(open(os.path.join(d, 'verdict.json'), encoding='utf-8'))
            pbr = {'status': v.get('status') or '—', 'problems': []}
        except Exception:  # noqa: BLE001 — приёмки ещё не было: страница важнее статуса
            pbr = {'status': 'не принят', 'problems': []}
        rows.append({'sku': sku, 'man': man, 'pbr': pbr,
                     'ver': int(os.path.getmtime(model_src))})

    cards = []
    for r in rows:
        m = r['man']
        seed = int(m.get('seed') or 0)
        gen = f'<span class="seed">перегон #{seed}</span>' if seed else ''
        cards.append(f"""
<div class="card" data-sku="{html.escape(m['sku'])}">
  <h3>{html.escape(m.get('role') or '?')} <span class="sku">{r['sku']}</span> {gen}</h3>
  <model-viewer src="{r['sku']}/model.glb?v={r['ver']}" camera-controls auto-rotate shadow-intensity="1"
    loading="lazy" reveal="auto"
    style="width:100%;height:340px;background:#f4f4f2;border-radius:6px"></model-viewer>
  <div class="marks">
    <button class="mk" data-m="light">светлее</button>
    <button class="mk" data-m="dark">темнее</button>
    <button class="mk" data-m="redo">переделать</button>
  </div>
  <img class="cut" src="{r['sku']}/cutout.png?v={r['ver']}" loading="lazy"
    alt="вырезка, ушедшая в генератор">
</div>""")

    # Страницы по PER_PAGE карточек (владелец 30.08: «тяжёлые, грузятся 10 сек — размещай
    # по страницам»). Свежие всегда на первой; model-viewer грузит GLB лениво (loading=lazy).
    PER_PAGE = 10
    os.makedirs(OUT, exist_ok=True)
    # индекс опубликованных мешей — 3D-сцене демо (какие sid брать моделью, а не заглушкой)
    json.dump({r['sku']: {'ver': r['ver']} for r in rows},
              open(os.path.join(OUT, 'mesh-index.json'), 'w'), ensure_ascii=False)
    npages = max(1, (len(cards) + PER_PAGE - 1) // PER_PAGE)
    for pi in range(npages):
        chunk = cards[pi * PER_PAGE:(pi + 1) * PER_PAGE]
        nav = ' '.join(
            f'<b>{i + 1}</b>' if i == pi else
            f'<a href="{"index.html" if i == 0 else f"page{i + 1}.html"}">{i + 1}</a>'
            for i in range(npages))
        nav = f'<p class="nav">Страницы: {nav} <span class="sku">(свежие — на первой)</span></p>'
        page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Пилот мешей — стр. {pi + 1}/{npages}</title>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
 body{{font:15px/1.5 system-ui;margin:24px;background:#fafaf8;color:#1c1c1a}}
 h1{{font-size:22px}} .card{{background:#fff;border:1px solid #e5e5e0;border-radius:10px;
 padding:16px;margin:18px 0;max-width:1180px}}
 .card{{display:inline-block;width:360px;vertical-align:top;margin:9px}}
 .sku{{font-size:12px;color:#999;font-weight:400}} .meta{{font-size:13px;color:#444}}
 .nav{{font-size:15px}} .nav a{{margin:0 3px}} .nav b{{margin:0 3px}}
 .cut{{max-width:100%;max-height:170px;margin-top:8px;border-radius:6px;
   background:url('{CHECKER}') repeat;image-rendering:auto;display:block}}
 .probs{{font-size:13px;color:#a33;margin:4px 0 0 18px}}
 @media(max-width:900px){{.tri{{grid-template-columns:1fr}}}}
{MARKS_CSS}
</style></head><body>
<h1>Меши — {len(rows)} шт., по одной модели на товар (самая свежая версия)</h1>
{nav}
{''.join(chunk)}
{nav}
{PANEL_HTML}
<script>{MARKS_JS}</script>
</body></html>"""
        name = 'index.html' if pi == 0 else f'page{pi + 1}.html'
        open(os.path.join(OUT, name), 'w', encoding='utf-8').write(page)
    print(f'карточек: {len(rows)} на {npages} стр. → {OUT}/index.html')
    for r in rows:
        print(f"  {r['man'].get('role'):14s} приёмка={r['pbr']['status']:12s} "
              f"{(r['pbr']['problems'] or ['—'])[0][:60]}")
    return OUT


if __name__ == '__main__':
    build()
