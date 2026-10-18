import sys, os
OUT = sys.argv[1]
ROOMS = '''<div class="rooms">
  <article class="room big" id="r-living">
    <div class="ph"><img src="https://remont-lab.online/test/share/frames/improve-221545-C1.jpg" alt="Гостиная в стиле сканди" width="2048" height="1446">
      %(OV)s<button class="heart" aria-label="В избранном">♥</button>
      <div class="ttl">Гостиная <small>· 14,4 м²</small></div></div>
    <div class="rb"><div class="sum"><b>168 128 ₽</b><small>10 шт. · ♥ Гостиная #1</small></div>
      <button class="ico" aria-label="Поделиться">⇪</button><button class="btn cta">Открыть</button></div>
  </article>
  <div class="room stub" id="r-kitchen"><b>Кухня <small>· 13,2 м²</small></b><span>появится следующим шагом</span></div>
  <div class="room stub"><b>Спальня 1 <small>· 17,5 м²</small></b><span>появится следующим шагом</span></div>
  <div class="room stub"><b>Спальня 2 <small>· 9,7 м²</small></b><span>появится следующим шагом</span></div>
  <div class="room stub"><b>Санузел <small>· 4,4 м²</small></b><span>появится следующим шагом</span></div>
  <div class="room stub"><b>Прихожая <small>· 9,3 м²</small></b><span>появится следующим шагом</span></div>
</div>'''
TABS = '''<nav class="tabs" role="tablist" aria-label="Стили">
  <button class="tab on" role="tab" aria-selected="true">Сканди</button><button class="tab" role="tab">Современный</button><button class="tab" role="tab">Минимализм</button><button class="tab" role="tab">Лофт</button><button class="tab" role="tab">Джапанди</button>
</nav>'''
HINT = '<p class="hint">Подобрали вашу квартиру в разных стилях. Можете менять мебель, отделку и встраиваемое.</p>'
CERT = '<div class="cert%(CLS)s"><div class="t"><span>Сертификат<span class="d"> на мебель и технику</span> <b>470 000 ₽</b></span><span>остаток <b>301 872 ₽</b></span></div><div class="bar"><i></i></div></div>'
FAV = '<button class="fav" aria-label="Избранное: 1">♡<b>1</b></button>'
PRICE = '<button class="price" aria-label="Цена, подробнее">9 578 200 ₽ <span class="ih">i</span></button>'
META = 'ЖК «Ольховый квартал» · сдача 4 кв. 2026 · эт. 6/17'
ACTS = '<div class="acts"><button class="btn">Ипотека, рассрочка</button><button class="btn cta">Консультация</button></div>'
SCROLL = "<script>/* ?s=1 — состояние «после прокрутки» для витрины */if(/[?&]s=1/.test(location.search))addEventListener('load',()=>scrollTo(0,220))</script>"


def page(title, cls, head, ov=''):
    return f'''<!doctype html>
<!-- Сгенерировано gen.py (макет demo-16): правка — там, не здесь. -->
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="home.css"></head>
<body class="{cls}"><div class="wrap">
{head}
{TABS}
{ROOMS % {'OV': ov}}
</div>{SCROLL}</body></html>
'''


A = page('Главная · вариант A', 'vA', f'''<header class="hd1"><div class="fk">3-комн · 73,7 м²</div>{PRICE}{FAV}</header>
<div class="top-d"><div class="hd2">{META}</div>{ACTS}</div>
{CERT % {'CLS': ''}}
{HINT}''')
B = page('Главная · вариант B', 'vB', f'''<header class="hd1"><div class="fk">3-комн · 73,7 м²</div>{PRICE}{FAV}
  <div class="pc"><span class="c">сертификат <b>470 000 ₽</b> · остаток <b>301 872 ₽</b></span><div class="bar"><i></i></div></div></header>
<div class="row2"><div class="m"><span>ЖК «Ольховый квартал»</span><span>сдача 4 кв. 2026 · эт. 6/17</span></div><button class="btn">Ипотека</button><button class="btn cta">Консультация</button></div>
{HINT}''')
C = page('Главная · вариант C', 'vC', f'''<header class="hd1"><div class="fk">3-комн · 73,7 м²</div>{PRICE}{FAV}</header>
<p class="hint" style="margin-top:0">Ваша квартира в разных стилях — меняйте мебель и отделку.</p>''', ov=CERT % {'CLS': ' cert-ov'})
for n, s in (('a', A), ('b', B), ('c', C)):
    open(os.path.join(OUT, n + '.html'), 'w').write(s)
