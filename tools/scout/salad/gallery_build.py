#!/usr/bin/env python3
"""Галерея пилота мешей: исходник → вырезка → вертящаяся 3D-модель. Публикуется на /test/.

Зачем страница, а не файлы. Владелец оценивает ДВЕ вещи, и обе — глазами: качественно ли
режется фото (просьба 29.08: «проверь фотки, что качественно режутся») и похож ли меш на
товар со всех сторон. Рендеры с фиксированных углов прячут спину и бока — поэтому модель
вертится в браузере (<model-viewer>, GLB как есть); вырезка — на клетчатом фоне, где виден
каждый съеденный пиксель и каждый прилипший кусок фона.

  ~/venvs/scout/bin/python gallery_build.py           # собрать в ~/scout-scenes/mesh-pilot-gallery
  python3 gallery_build.py --selftest                 # выбор файла (mtime / привязка) на подставных данных

КАКОЙ ФАЙЛ НА SKU (T-20261105-50/2). По умолчанию — как всегда: папка поколения с самым свежим `manifest.json`.
`GALLERY_FROM_BINDING=1` — файл привязки товар→меш (`offer_asset_binding`, T-45: текущая попытка ревизии ТЕКУЩЕГО фото),
если он есть, цел и его полный sha совпал с привязкой; иначе — прежнее правило (товары не в наличии привязки не имеют).
Зачем флагом: ночная сборка не должна поменяться, пока ведущий не посмотрит результат на /test/. В `mesh-index.json` у
каждой модели — `glb_sha` (первые 16 знаков sha256 файла): демо ставит `?v=`, чтобы смена байтов под тем же адресом дошла
до браузера. `GALLERY_OUT` — другая папка вывода (стенд и доказательства; по умолчанию прежняя).
"""
import base64
import glob
import hashlib
import html
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

SRC = os.environ.get('GALLERY_SRC', os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2'))
OUT = os.environ.get('GALLERY_OUT') or os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
SHA_CACHE = os.path.expanduser('~/scout-scenes/catalog-assets/v1/glb-sha-cache.json')   # кэш room_bindings: только читаем


def drop_strays() -> None:
    """В ЭТОЙ ПАПКЕ НЕ ДОЛЖНО БЫТЬ ЧУЖИХ РЕЕСТРОВ (01.09). Папка публикуется на прод целиком,
    и завалявшийся здесь `orient.json` уехал поверх серверного: 185 записей ориентации
    схлопнулись до 12. Реестры публикуются ТОЛЬКО слиянием (`publish_merge.py`).
    (Было на уровне модуля — срабатывало и при импорте/селфтесте; теперь — в начале сборки, T-50/2.)"""
    for _stray in ('orient.json',):
        _p = os.path.join(OUT, _stray)
        if os.path.exists(_p):
            os.remove(_p)
            print(f'убран чужой реестр из папки публикации: {_stray}', flush=True)


def select(entries: list, only: set | None, bound: dict, from_binding: bool) -> tuple:
    """Какую папку поколения показывать на SKU. entries — папки в порядке обхода сборки (свежий manifest первым):
    {dir, sku, owner_reject, role_mesh, has_glb}. Прежнее правило: первая папка SKU без брака владельца, из списка отбора,
    с ролью-мешем и model.glb (папка без model.glb SKU не занимает). bound — sku → папка файла привязки (уже проверенного:
    цел, sha совпал); с from_binding у такого SKU берётся ТОЛЬКО эта папка, если она проходит те же условия, иначе —
    прежнее правило. → ({sku: dir}, {sku: 'binding'|'mtime'})."""
    ok = lambda e: not e['owner_reject'] and (only is None or e['sku'] in only) and e['role_mesh'] and e['has_glb']  # noqa: E731
    want = {}
    if from_binding:
        dirs = {os.path.normpath(e['dir']): e for e in entries}
        for sku, d in bound.items():
            e = dirs.get(os.path.normpath(d))
            if e is not None and e['sku'] == sku and ok(e):
                want[sku] = os.path.normpath(d)
    chosen, how = {}, {}
    for e in entries:
        s = e['sku']
        if s in chosen or not ok(e):
            continue
        if s in want:
            if os.path.normpath(e['dir']) != want[s]:
                continue
            how[s] = 'binding'
        else:
            how[s] = 'mtime'
        chosen[s] = e['dir']
    return chosen, how


def _load_binding() -> tuple:
    import catalog_items as CI
    import room_bindings as RB
    return RB.load_db(CI.fetch)


def binding_dirs(only: set | None = None, load=_load_binding) -> tuple:
    """sku → папка файла привязки, у которого файл цел и полный sha = asset_id привязки (only — только эти sku).
    → (dirs, счётчики отказов). Привязка не читается — ({}, {причина}): сборка идёт прежним правилом, громко."""
    try:
        rows, why = load()
    except Exception as e:  # noqa: BLE001
        rows, why = None, repr(e)[:120]
    if rows is None:
        print(f'WARN:gallery_build: привязка не читается ({why}) — выбор файла прежний (mtime)', flush=True)
        return {}, {'binding_unreadable': 1}
    out, bad = {}, {}
    for sku, r in rows.items():
        if only is not None and sku not in only:
            continue
        if not r.get('asset_id') or not r.get('local_path'):
            bad['no_file'] = bad.get('no_file', 0) + 1
            continue
        sha = glb_sha(r['local_path'])
        if sha is None or 'sha256:' + sha != r['asset_id']:
            bad['sha_mismatch'] = bad.get('sha_mismatch', 0) + 1
            continue
        out[sku] = os.path.dirname(r['local_path'])
    return out, bad


_SHA: dict | None = None


def glb_sha(path: str) -> str | None:
    """Полный sha256 файла; кэш room_bindings (путь → [размер, mtime, sha]) только читаем, промах — считаем сами."""
    global _SHA
    if _SHA is None:
        try:
            _SHA = json.load(open(SHA_CACHE, encoding='utf-8'))
        except Exception:  # noqa: BLE001
            _SHA = {}
    try:
        st = os.stat(path)
    except OSError:
        return None
    hit = _SHA.get(path)
    if hit and hit[0] == st.st_size and abs(hit[1] - st.st_mtime) < 1e-6:
        return hit[2]
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    _SHA[path] = [st.st_size, st.st_mtime, h.hexdigest()]
    return _SHA[path][2]

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


COLOR_RE = (r'(латте|графитов\w*|бел\w+|терракотов\w*|оливков\w*|бежев\w*|молочн\w*|син\w+|'
            r'сер\w+|серо-\w+|чёрн\w+|черн\w+|шоколад\w*|агат|антик|золотист\w*|золотой|хром|'
            r'дуб \w+|аквамарин|монстера|зелен\w*|тёмно-\w+|темно-\w+|светло-\w+|коричнев\w*|'
            r'розов\w*|голуб\w*|крем\w*|песочн\w*|капучино|орех|венге|сонома|мокко|табак)')
FABRIC_RE = (r'(велюр|рогожка|экокожа|букле|ткань|шенилл|микровельвет|монолит|мальмо|роял|'
             r'плюш|лофти|аляска|савана)')


def _product_names(skus: list[str]) -> dict:
    """sku → название товара из БД. Недоступна — вернём пусто, галерея соберётся как есть."""
    import re
    import subprocess
    try:
        pairs = [s.split(':') for s in skus if ':' in s]
        if not pairs:
            return {}
        vals = ','.join(f"({m},'{re.sub(chr(39), '', e)}')" for m, e in pairs)
        q = (f'select shop_mid||\':\'||external_id, name from products '
             f'where (shop_mid,external_id) in ({vals})')
        r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab',
                            '-d', 'remlab', '-q', '-t', '-A', '-F', '\x1f'],
                           input=q, capture_output=True, text=True, timeout=60)
        return {l.split('\x1f')[0]: l.split('\x1f')[1]
                for l in r.stdout.strip().split('\n') if '\x1f' in l}
    except Exception as e:  # noqa: BLE001
        print(f'  имена товаров недоступны ({str(e)[:60]}) — группировка вариантов пропущена')
        return {}


def collapse_variants(rows: list) -> list:
    """Одна карточка на МОДЕЛЬ товара, а не на SKU (владелец 01.09).

    Он поймал повтор, который не ловится ни по SKU, ни по файлу фото: два стула tvoydom
    (1002717604 и 1002739220) — одна и та же модель в разной обивке, разные SKU и разные
    снимки. Так же ведут себя серии divan.ru: стеллаж «Кейн» приезжал в галерею 10 раз в
    десяти цветах. Ключ группировки — название товара без цвета, ткани и размеров;
    остаётся имя модели («стеллаж divan ru кейн»). Показываем самую свежую генерацию
    группы, рядом пишем, сколько вариантов свёрнуто. Сами SKU из каталога не пропадают —
    свёрнут только ПОКАЗ.
    """
    import re
    names = _product_names([r['man']['sku'] for r in rows])
    if not names:
        return rows
    seen, out, extra = {}, [], {}
    for r in rows:
        n = names.get(r['man']['sku'])
        if not n:
            out.append(r)
            continue
        s = n.lower()
        s = re.sub(r'\d+[.,]?\d*\s*[xх]\s*\d+[.,]?\d*', ' ', s)
        s = re.sub(r'\b\d+\b', ' ', s)
        s = re.sub(FABRIC_RE, ' ', s)
        s = re.sub(COLOR_RE, ' ', s)
        key = (r['man'].get('role'), re.sub(r'\s+', ' ', re.sub(r'[«»"“”,./\\|()-]', ' ', s)).strip())
        if key in seen:
            extra[seen[key]] = extra.get(seen[key], 0) + 1
            continue
        seen[key] = len(out)
        r['name'] = n
        out.append(r)
    for i, k in extra.items():
        out[i]['variants'] = k
    print(f'  свёрнуто вариантов одного товара: {sum(extra.values())} '
          f'(карточек {len(rows)} → {len(out)})')
    return out


def build() -> str:
    rows = []
    # СПИСОК ОТБОРА (13.10). Без него галерея копирует ВЕСЬ склад мешей: 4 222 модели ≈ 25 ГБ, и
    # выложить это на прод нельзя — там свободно 17 ГБ. Демо показывает только то, что есть в
    # комплектах (372 товара на все 126 наборов), поэтому публикуем ровно их. Формат файла —
    # по одному SKU в строке, `mid:eid` или `mid_eid`.
    only = None
    only_p = os.environ.get('GALLERY_ONLY')
    if only_p and os.path.exists(only_p):
        only = {l.strip().replace('_', ':', 1) for l in open(only_p, encoding='utf-8') if l.strip()}
        print(f'[галерея] отбор по списку: {len(only)} SKU', flush=True)
    drop_strays()
    import asset_strategy as AS
    # На SKU показываем ОДИН меш — самый свежий (перегон затирает брак): обход от свежего manifest к старому,
    # забракованное владельцем (owner_reject.json — ждёт перегона) и не-меши пропускаем. Показ — ТОЛЬКО оригинал
    # генератора (владелец 01.09 — «ремонт калечит, оставляй оригинальные модели»): model.repaired.glb не читается.
    # Папка без model.glb (suspect-комплект, одна диагностика) SKU не занимает — показывается предыдущая версия.
    entries, mans = [], {}
    for d in sorted(glob.glob(os.path.join(SRC, '*/*/')), key=lambda p: -os.path.getmtime(os.path.join(p,'manifest.json')) if os.path.exists(os.path.join(p,'manifest.json')) else 0):
        man_p = os.path.join(d, 'manifest.json')
        if not os.path.exists(man_p):
            continue
        man = json.load(open(man_p, encoding='utf-8'))
        mans[d] = man
        entries.append({'dir': d, 'sku': man['sku'], 'owner_reject': os.path.exists(os.path.join(d, 'owner_reject.json')),
                        'role_mesh': AS.strategy(man.get('role')) == 'hunyuan3d',
                        'has_glb': os.path.exists(os.path.join(d, 'model.glb'))})
    from_binding = os.environ.get('GALLERY_FROM_BINDING') == '1'
    # ПРИВЯЗКА ТОЛЬКО ДЛЯ СПИСКА (T-20261106-77/6): `mesh_publish` даёт модели гостиной, чей файл везёт привязка
    # (`living_bound`), — остальной отбор по свежести, как прежде. Нет файла списка — привязка для всего отбора.
    bind_only = None
    bo_p = os.environ.get('GALLERY_BIND_ONLY')
    if from_binding and bo_p and os.path.exists(bo_p):
        bind_only = {l.strip().replace('_', ':', 1) for l in open(bo_p, encoding='utf-8') if l.strip()}
        bind_only = bind_only & only if only is not None else bind_only
        print(f'[галерея] файл по привязке — только для списка: {len(bind_only)} SKU', flush=True)
    bound, bad = binding_dirs(bind_only if bind_only is not None else only) if from_binding else ({}, {})
    chosen, how = select(entries, only, bound, from_binding)
    if from_binding:
        n_b = sum(1 for v in how.values() if v == 'binding')
        none = len(only - set(chosen)) if only is not None else 0
        no_row = sum(1 for s, v in how.items() if v == 'mtime' and s not in bound)
        print(f'[галерея] выбор файла: по привязке {n_b} / по mtime {len(how) - n_b} / нет ничего {none} '
              f'(по mtime: нет строки привязки {no_row}, файл привязки не годен для показа {len(how) - n_b - no_row}; '
              f'отказы привязки {bad or "—"})', flush=True)
    for d in [e['dir'] for e in entries if chosen.get(e['sku']) == e['dir']]:
        man = mans[d]
        model_src = os.path.join(d, 'model.glb')
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
                     'ver': int(os.path.getmtime(model_src)), 'glb_sha': (glb_sha(model_src) or '')[:16] or None})

    rows = collapse_variants(rows)
    cards = []
    for r in rows:
        m = r['man']
        seed = int(m.get('seed') or 0)
        gen = f'<span class="seed">перегон #{seed}</span>' if seed else ''
        if r.get('variants'):
            gen += (f'<span class="seed"> · свёрнуто ещё {r["variants"]} '
                    f'вариант(ов) этого товара — другой цвет или размер</span>')
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
    # glb_sha (T-50/2) — 16 знаков sha256 показанного файла: демо ставит ?v=, чтобы новые байты под тем же адресом
    # не залипали в кэше браузера (ver — mtime, при смене выбора файла может уйти назад).
    json.dump({r['sku']: {'ver': r['ver'], 'glb_sha': r['glb_sha']} for r in rows},
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


def _selftest() -> int:
    """Выбор файла на SKU без базы и сети: флаг выкл / вкл / нет файла привязки, sha и отказ чтения привязки."""
    import tempfile
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    E = lambda d, s, **k: {'dir': d, 'sku': s, 'owner_reject': False, 'role_mesh': True, 'has_glb': True, **k}  # noqa: E731
    ents = [E('/g/a/new/', 'm:a'), E('/g/a/old/', 'm:a'), E('/g/b/new/', 'm:b', has_glb=False), E('/g/b/old/', 'm:b'),
            E('/g/c/new/', 'm:c', owner_reject=True), E('/g/c/old/', 'm:c'), E('/g/d/x/', 'm:d', role_mesh=False)]
    off, how_off = select(ents, None, {'m:a': '/g/a/old'}, False)
    ok('флаг выкл: свежий manifest, папка без glb и брак владельца пропущены, не-меш не показан, привязка не читается',
       off == {'m:a': '/g/a/new/', 'm:b': '/g/b/old/', 'm:c': '/g/c/old/'} and set(how_off.values()) == {'mtime'})
    on, how = select(ents, None, {'m:a': '/g/a/old', 'm:c': '/g/c/new'}, True)
    ok('флаг вкл: у SKU с привязкой — файл привязки, хоть он и старше',
       on['m:a'] == '/g/a/old/' and how['m:a'] == 'binding')
    ok('флаг вкл: файл привязки забракован владельцем — прежнее правило',
       on['m:c'] == '/g/c/old/' and how['m:c'] == 'mtime')
    ok('флаг вкл: нет строки привязки (нет в наличии) — прежнее правило', on['m:b'] == '/g/b/old/' and how['m:b'] == 'mtime')
    on2, how2 = select(ents, None, {'m:a': '/g/a/gone'}, True)
    ok('флаг вкл: нет файла привязки среди папок — прежнее правило', on2['m:a'] == '/g/a/new/' and how2['m:a'] == 'mtime')
    on3, _ = select(ents, None, {'m:a': '/g/b/old'}, True)
    ok('флаг вкл: папка привязки чужого SKU — не берём', on3['m:a'] == '/g/a/new/')
    on4, _ = select(ents, {'m:b'}, {'m:a': '/g/a/old'}, True)
    ok('список отбора действует и с привязкой', set(on4) == {'m:b'})
    with tempfile.TemporaryDirectory() as t:
        good, wrong = os.path.join(t, 'g1'), os.path.join(t, 'g2')
        for p in (good, wrong):
            os.makedirs(p)
            open(os.path.join(p, 'model.glb'), 'wb').write(b'glTF' + p.encode())
        sha = hashlib.sha256(b'glTF' + good.encode()).hexdigest()
        ok('glb_sha — полный sha256 файла', glb_sha(os.path.join(good, 'model.glb')) == sha)
        rows = {'m:a': {'asset_id': 'sha256:' + sha, 'local_path': os.path.join(good, 'model.glb')},
                'm:b': {'asset_id': 'sha256:' + sha, 'local_path': os.path.join(wrong, 'model.glb')},
                'm:c': {'asset_id': 'sha256:' + sha, 'local_path': os.path.join(t, 'нет', 'model.glb')},
                'm:d': {'asset_id': None, 'local_path': None}}
        dirs, why = binding_dirs(None, lambda: (rows, None))
        ok('привязка: берём только файл, чей sha совпал с asset_id; битый/пропавший/без файла — отказ со счётом',
           dirs == {'m:a': good} and why == {'sha_mismatch': 2, 'no_file': 1})
        ok('привязка по списку отбора', binding_dirs({'m:b'}, lambda: (rows, None))[0] == {})

    def boom():
        raise RuntimeError('нет базы')
    ok('привязка не читается — пусто, сборка идёт прежним правилом', binding_dirs(None, boom) == ({}, {'binding_unreadable': 1})
       and binding_dirs(None, lambda: (None, 'snapshot_mismatch'))[0] == {})
    print(f'итог: {"OK" if not bad else f"FAIL {bad}"}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv[1:]:
        sys.exit(_selftest())
    build()
