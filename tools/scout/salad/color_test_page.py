#!/usr/bin/env python3
"""Страница проверки цвета: фото → фото после подготовки → модель, с оценкой владельца.

Владелец 01.09: «по всем что темнее/светлее/переделать сделай страницу: фото было, фото
после обработки, что стало; потом туда же третьим столбцом модель и кнопку ок/нет».

Список товаров берём из файла отметок (то, что владелец скопировал с галереи кнопкой).
Формат — как отдаёт панель галереи:
    светлее (12):
    112923:5177956365797043847
    ...
Пустой список = взять всё, что есть.

  ~/venvs/scout/bin/python color_test_page.py [marks.txt]
"""
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/mesh-color')
MARK_NAMES = {'светлее': 'light', 'темнее': 'dark', 'переделать': 'redo'}


def read_marks(path: str | None) -> dict:
    """Текст из панели галереи → {sku: пометка}. Порядок групп значения не имеет."""
    if not path or not os.path.exists(path):
        return {}
    cur, out = None, {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        m = re.match(r'^(светлее|темнее|переделать)\s*\(', line)
        if m:
            cur = MARK_NAMES[m.group(1)]
            continue
        if line and ':' in line and not line.endswith(':') and cur:
            out[line.split()[0]] = cur
    return out


def newest_dirs() -> dict:
    """sku → каталог самой свежей генерации с моделью."""
    best = {}
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json')),
                     key=lambda p: -os.path.getmtime(p)):
        d = os.path.dirname(mp)
        man = json.load(open(mp, encoding='utf-8'))
        if man['sku'] in best or not os.path.exists(os.path.join(d, 'model.glb')):
            continue
        best[man['sku']] = (d, man)
    return best


def main() -> None:
    import photo_color
    from PIL import Image
    marks = read_marks(sys.argv[1] if len(sys.argv) > 1 else None)
    ev_p = os.path.join(HERE, 'exposure_plan.json')
    EV = json.load(open(ev_p, encoding='utf-8')) if os.path.exists(ev_p) else {}
    os.makedirs(OUT, exist_ok=True)
    best = newest_dirs()
    order = {'redo': 0, 'dark': 1, 'light': 2, '': 3}
    redo = [s for s, v in marks.items() if v == 'redo']
    items = [(s, v) for s, v in best.items()
             if (not marks or s in marks) and marks.get(s) != 'redo']
    items.sort(key=lambda x: (order[marks.get(x[0], '')], x[1][1].get('role') or ''))
    cards, reports = [], {}
    for sku, (d, man) in items:
        cut_p = os.path.join(d, 'cutout.png')
        if not os.path.exists(cut_p):
            continue
        key = sku.replace(':', '_')
        plan = EV.get(sku) or {}
        stops = float(plan.get('stops') or 0.0)
        shifted, rep = photo_color.shift_exposure(Image.open(cut_p), stops)
        rep.update({k: plan.get(k) for k in ('stops_raw', 'y_photo', 'y_model', 'note')})
        reports[sku] = rep
        Image.open(cut_p).save(os.path.join(OUT, f'{key}.was.png'))
        shifted.save(os.path.join(OUT, f'{key}.now.png'))
        glb_src = os.path.join(d, 'model.glb')
        glb = f'{key}.glb'
        if not os.path.exists(os.path.join(OUT, glb)) or \
                os.path.getmtime(os.path.join(OUT, glb)) < os.path.getmtime(glb_src):
            open(os.path.join(OUT, glb), 'wb').write(open(glb_src, 'rb').read())
        ver = int(os.path.getmtime(glb_src))
        mark = marks.get(sku, '')
        badge = {'light': 'вы отметили: светлее', 'dark': 'вы отметили: темнее',
                 'redo': 'вы отметили: переделать'}.get(mark, '')
        note = (f"замер: покраска промахнулась на {plan.get('stops_raw')} ступени "
                f"(яркость фото {plan.get('y_photo')} против модели {plan.get('y_model')}); "
                f"входу даём {stops:+.2f} — дальше упирается в засветы"
                if plan else 'замер не сделан')
        cards.append(f"""
<div class="card" data-sku="{html.escape(sku)}">
 <h3>{html.escape(man.get('role') or '?')} <span class="sku">{key}</span>
  <span class="badge">{badge}</span></h3>
 <div class="row">
  <div><div class="lbl">фото как есть</div><img src="{key}.was.png" loading="lazy"></div>
  <div><div class="lbl">фото со сдвинутой экспозицией: {stops:+.2f} ступени
   (треть от замера, не больше 0.45)</div>
   <img src="{key}.now.png" loading="lazy"></div>
  <div><div class="lbl">модель (пока со старого фото)</div>
   <model-viewer src="{glb}?v={ver}" camera-controls auto-rotate shadow-intensity="1"
     loading="lazy" style="width:290px;height:250px;background:#f4f4f2;border-radius:6px"></model-viewer>
  </div>
 </div>
 <div class="marks">
   <button class="mk" data-m="ok">ок, помогло</button>
   <button class="mk" data-m="no">нет, не помогло</button>
 </div>
 <div class="tech">{html.escape(note)}</div>
</div>""")
    json.dump(reports, open(os.path.join(OUT, 'reports.json'), 'w'), ensure_ascii=False, indent=1)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проверка цвета — было / после подготовки / модель</title>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
 body{{font:15px/1.5 system-ui;margin:22px;background:#fafaf8;color:#1c1c1a}}
 h1{{font-size:20px}} .sub{{color:#555;max-width:900px}}
 .card{{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:14px;margin:12px 0;max-width:1000px}}
 h3{{font-size:15px;margin:0 0 8px}} .sku{{font-size:11px;color:#999;font-weight:400}}
 .badge{{font-size:11px;color:#8a6d00;background:#fdf3d5;border-radius:4px;padding:2px 6px;font-weight:400}}
 .lbl{{font-size:12px;color:#666;margin-bottom:4px}}
 .row{{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start}}
 .row img{{max-width:290px;max-height:250px;border-radius:6px;background:#fff;border:1px solid #eee}}
 .marks{{display:flex;gap:8px;margin-top:10px;max-width:600px}}
 .mk{{flex:1;padding:8px;font:13px system-ui;cursor:pointer;border:1px solid #d5d5cf;
   border-radius:6px;background:#fff}}
 .mk.on{{border-color:#1c1c1a;background:#1c1c1a;color:#fff;font-weight:600}}
 .card[data-mark="ok"]{{box-shadow:0 0 0 2px #3d8a4e}} .card[data-mark="no"]{{box-shadow:0 0 0 2px #c04a3e}}
 .tech{{font-size:11px;color:#999;margin-top:6px}}
{MARKS_PANEL_CSS}
</style></head><body>
<h1>Экспозиция входа — проверка на {len(cards)} товарах</h1>
<p class="sub">Отмеченные «переделать» ({len(redo)} шт.) сюда НЕ попали: там брак формы —
приросшая плита, а не цвет. Они идут отдельной очередью на перегенерацию.</p>
<p class="sub">Слева фото, как оно уходит в генератор сейчас. В середине — то же фото со
сдвинутой экспозицией: это то, что мы предлагаем подать на перепокраску. Справа — сегодняшняя
модель, сделанная со старого фото, для сравнения.</p>
<p class="sub"><b>Второе фото намеренно НЕ выглядит правильным.</b> Это не улучшение картинки,
а компенсация: покраска систематически промахивается по светлоте, и мы двигаем экспозицию входа
в обратную сторону ровно на столько ступеней, на сколько она промахнулась. Судить это фото надо
не по красоте, а по тому, не сломалось ли оно: нет ли выжженных белых пятен, не уехал ли оттенок,
видна ли ещё фактура. Величина сдвига и замер — серой строкой под карточкой.</p>
<p class="sub">Сдвиг считается по рендеру модели БЕЗ света (только собственный цвет покраски)
против фото, в линейной яркости, разница в ступенях. В тёмную сторону предел мягкий, в светлую —
ровно до появления засветов, поэтому у части товаров сдвиг меньше нужного.</p>
{''.join(cards)}
{MARKS_PANEL_HTML}
<script>{MARKS_PANEL_JS}</script>
</body></html>"""
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'карточек: {len(cards)} → {OUT}/index.html')


MARKS_PANEL_CSS = """
 #panel{position:fixed;right:14px;bottom:14px;z-index:9;background:#fff;border:1px solid #d5d5cf;
   border-radius:10px;padding:10px 12px;font:13px system-ui;box-shadow:0 3px 14px #0002;max-width:330px}
 #panel button{font:12px system-ui;padding:5px 8px;margin:6px 4px 0 0;border:1px solid #d5d5cf;
   border-radius:6px;background:#fff;cursor:pointer}
 #out{display:none;width:305px;height:140px;margin-top:8px;font:11px/1.35 monospace}
"""

MARKS_PANEL_HTML = """
<div id="panel">
  <div><b>Оценка цвета</b></div>
  <div id="cnt">ок 0 · нет 0</div>
  <button id="copy">скопировать оценки</button><button id="clr">стереть всё</button>
  <textarea id="out" readonly></textarea>
</div>
"""

MARKS_PANEL_JS = """
(function(){
  var KEY='colorMarks', NAMES={ok:'ок',no:'нет'};
  function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
  function save(m){try{localStorage.setItem(KEY,JSON.stringify(m))}catch(e){alert('Браузер не даёт сохранить оценки')}}
  function paint(){
    var m=load(), cnt={ok:0,no:0};
    for(var k in m){if(cnt[m[k]]!==undefined)cnt[m[k]]++;}
    document.querySelectorAll('.card').forEach(function(c){
      var v=m[c.dataset.sku]||'';
      if(v){c.dataset.mark=v;}else{c.removeAttribute('data-mark');}
      c.querySelectorAll('.mk').forEach(function(b){b.classList.toggle('on',b.dataset.m===v);});
    });
    document.getElementById('cnt').textContent='ок '+cnt.ok+' · нет '+cnt.no;
  }
  function text(){
    var m=load(), by={ok:[],no:[]};
    for(var k in m){if(by[m[k]])by[m[k]].push(k);}
    var s='';
    ['ok','no'].forEach(function(t){s+=NAMES[t]+' ('+by[t].length+'):\\n'+(by[t].join('\\n')||'—')+'\\n\\n';});
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
      if(navigator.clipboard){navigator.clipboard.writeText(t);}else{document.execCommand('copy');}
      e.target.textContent='скопировано';
      setTimeout(function(){e.target.textContent='скопировать оценки';},1500);
    }
    if(e.target.id==='clr'&&confirm('Стереть все оценки?')){save({});paint();}
  });
  document.addEventListener('DOMContentLoaded',paint);
})();
"""

if __name__ == '__main__':
    main()
