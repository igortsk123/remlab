#!/usr/bin/env python3
"""ДЕМО «интерактив» по квартире 215 (гостиная): экспорт данных для страницы.

Архитектура — по решению владельца 26.08: НИЧЕГО не считаем на лету. Здесь офлайн собираем
`demo-data.json` (комната + предпосчитанные варианты + лента диванов из каталога + числа правил),
а страница только показывает и даёт двигать. Правила для советчика берутся из ТЕХ ЖЕ файлов,
что читает движок, чтобы подсказки не разошлись с каноном.

  ~/venvs/scout/bin/python flat215_demo.py [--publish]      # → /test/flat215-demo/
"""
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules')
OUT = os.path.expanduser('~/scout-scenes/flat215-demo')
# ВАРИАНТЫ РАССТАНОВКИ и КОМПЛЕКТЫ ТОВАРОВ — РАЗНЫЕ СУЩНОСТИ (владелец 26.08):
# «шаблоны не называть стилями, а просто варианты; далее под любой из шаблонов показываем наши
# сеты; люди могут смешать разные товары из разных стилей». Поэтому: вариант = геометрия
# расстановки, комплект = набор товаров, который на неё накладывается; отдельный предмет можно
# заменить товаром из любого комплекта.
# СЕТЫ ДЛЯ ДЕМО ВЫБИРАЮТСЯ ПО СОСТАВУ, А НЕ ПО НОМЕРУ (26.08). Жёсткий список [1,4,7,…] сломался,
# как только контракт снял из банков позиции закрывшегося магазина: два сета остались без дивана,
# и движок честно вернул пустую комнату. Берём банки нужного метража, где есть диван и больше
# всего расставляемых ролей.
PLACEABLE = {'диван', 'кресло', 'столик', 'ковёр', 'тв-тумба', 'стеллаж', 'комод', 'витрина',
             'торшер', 'пуф', 'кашпо', 'стул', 'банкетка', 'стол обеденный', 'камин', 'стенка'}


def pick_banks(sets: list, band: str = '14-16', n: int = 6) -> list:
    rated = []
    for i, st in enumerate(sets, 1):
        if st.get('band') != band or 'диван' not in (st.get('items') or {}):
            continue
        rated.append((sum(1 for r in st['items'] if r.split(' ')[0] in PLACEABLE),
                      -len(st.get('gaps') or []), i))
    rated.sort(reverse=True)
    return [i for _, _, i in rated[:n]]
SHOW_ROLES = ('диван', 'диван 2', 'кресло', 'кресло 2', 'столик', 'ковёр', 'тв-тумба', 'стенка',
              'торшер', 'пуф', 'стеллаж', 'комод', 'витрина', 'кашпо', 'камин', 'банкетка',
              'стол обеденный', 'стул', 'стул 2', 'приставной')


def _rules() -> dict:
    occ = json.load(open(os.path.join(RULES, 'occupancy.json'), encoding='utf-8'))
    zn = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    d = occ.get('distances_cm') or {}
    dyn = occ.get('dynamic') or {}
    return {
        'main_route': zn.get('main_route') or {'quality_min_cm': 75, 'acceptance_floor_cm': 70,
                                               'target_cm': 91},
        'sofa_table_hard': d.get('sofa_coffee_table_hard') or [32, 50],
        'sofa_table_pref': d.get('sofa_coffee_table') or [36, 46],
        'sofa_tv_cm': d.get('sofa_tv_cm') or [180, 300],
        'corner_sofa_tv_min_cm': 150,          # угловой смотрит по диагонали — ближе допустимо
        'corner_sofa_table_min_cm': 0,         # столик внутри «Г» стоит вплотную к плечу
        '_corner_why': 'исключения для Г-дивана — те же, что в движке (solver_run: lo_eff=150; '
                       'validate: нижней границы столика у углового нет)',
        'passage_secondary_cm': d.get('sofa_to_wall_passage') or 76,
        'rug_front_legs_cm': (dyn.get('rug_rules') or {}).get('front_legs_on_rug_cm') or 25,
        'radiator_min_cm': ((dyn.get('radiator') or {}).get('hard_min_clearance_cm') or [15, 20])[0],
        '_provenance': 'services/planner-solver/rules/{occupancy,zones}.json — те же файлы, что у движка',
    }


_PACK_RE = re.compile(r'(\d+)\s*шт', re.I)


def _pack_of(mid, eid, name: str | None) -> int:
    """Штук в одной покупке. Каталожная разметка сильнее названия: у 906 стульев число в
    названии нашлось лишь у 16, остальное размечено по фото офлайн (`pack_qty.py`)."""
    try:
        from pack_qty import pack_of
        return pack_of(mid, eid, name)
    except Exception:  # noqa: BLE001 — нет таблицы/модуля: остаётся разбор названия
        return pack_size(name)


def pack_size(name: str | None) -> int:
    """Сколько штук в ОДНОЙ покупке — из названия товара («Стул АСТИ 2 шт.» → 2).

    Владелец 01.09: «мы моделим стул один, а их обычно больше в группе, 2 или 4 бывает часто».
    Магазины продают стулья комплектами, и это написано только в названии: отдельного поля в
    фиде нет. Без разбора названия одна покупка выглядела как один предмет — и в комнате стоял
    один стул там, где куплено два, а смета считала два комплекта вместо одного.
    """
    m = _PACK_RE.search(name or '')
    n = int(m.group(1)) if m else 1
    return n if 1 <= n <= 12 else 1        # «100 шт» в названии — это не комплект мебели


def _sku(items: dict, role: str) -> dict | None:
    """Товар слота. Пронумерованный экземпляр («стул 2») берёт товар БАЗОВОЙ роли.

    Слоты вида «стул 2» создаёт раскладка, а в банке товар лежит один — под «стул». Раньше
    такой слот приезжал пустым: на плане и в кадре он оставался серой заглушкой рядом с честно
    отрисованным первым стулом. Берём тот же товар, но не молча: `pack` говорит, сколько штук
    даёт одна покупка, и по нему страница считает, сколько покупок нужно на все слоты.
    """
    it = items.get(role)
    if not it:
        base = re.sub(r'\s+\d+$', '', role)
        if base != role:
            it = items.get(base)
    if not it:
        return None
    return {'name': it.get('name'), 'price': it.get('price'), 'img': it.get('img'),
            'url': it.get('url'), 'shop': it.get('shop'),
            # sid — ключ каталога мешей (/test/mesh-pilot10/<sid>/model.glb): 3D-сцена демо
            'sid': (f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else None),
            # штук в покупке: сперва разметка каталога (`product_pack`, размечает pack_qty.py
            # по названию/описанию/фото), и только если её нет — разбор названия
            'pack': _pack_of(it.get('mid'), it.get('eid'), it.get('name')),
            'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h')}


BANKS: list = []          # заполняется в build(): выбранные банки демо


def solve_layouts(flat: dict) -> None:
    """РАСКЛАДКИ СЧИТАЕМ ПОД ЭТУ КОМНАТУ (26.08). Артефакт `v3set{n}-layout.json` по умолчанию
    считается для условного прямоугольника из метража сета (например 360×415) — если взять
    такой артефакт для комнаты 439×325, мебель окажется за стеной. Поэтому демо само вызывает
    солвер с реальными габаритами и проёмами квартиры, а не надеется на ранее посчитанный файл."""
    liv = flat['rooms'][0]
    env = dict(os.environ,
               SCENE_OPENINGS=json.dumps([{k: v for k, v in o.items() if not k.startswith('_')}
                                          for o in liv['openings']], ensure_ascii=False),
               SCENE_RADIATORS=json.dumps([{k: v for k, v in r.items() if not k.startswith('_')}
                                           for r in (liv.get('radiators') or [])], ensure_ascii=False))
    py = os.path.expanduser('~/venvs/scout/bin/python')
    for n in BANKS:
        art = os.path.join(HERE, f'v3set{n}-layout.json')
        fresh = (os.path.exists(art)
                 and (json.load(open(art, encoding='utf-8')).get('_room') or {}).get('w') == liv['w']
                 and os.path.getmtime(art) > os.path.getmtime(os.path.join(HERE, 'sets3.json')))
        if fresh:
            continue
        r = subprocess.run([py, 'solver_run.py', str(n), '--v3', str(liv['w']), str(liv['d'])],
                           cwd=HERE, env=env, capture_output=True, text=True)
        print(f'  раскладка сета {n}: ' + ('пересчитана' if r.returncode == 0 else f'ОШИБКА\n{r.stderr[-400:]}'))


def drop_unavailable(sets: list) -> int:
    """Снять из банка позиции, которых уже нет в продаже. → сколько снято.

    ВТОРОЙ РУБЕЖ, А НЕ ДУБЛИРОВАНИЕ (01.09). Наличие лечит конвейер (`sets_incremental --heal`),
    но между «наличие снято» и «банк вылечен» проходит до суток, и всё это время страница честно
    показывает партнёру мёртвый товар — ровно это и нашёл владелец 01.09 (диван с карточкой 404).
    Страница не считает наличие сама: спрашивает каталог, единственный источник (ADR-0141).
    `unknown` (фид магазина не приехал) НЕ снимаем — «не знаю про фид» это не «товара нет».
    """
    from catalog_media import media as _media
    n = 0
    for st in sets:
        items = st.get('items') or {}
        for role, it in list(items.items()):
            if not it or not it.get('mid'):
                continue
            m = _media(it.get('mid'), it.get('eid'))
            if m is None or m.get('state') == 'gone':
                items.pop(role)
                n += 1
    return n


def build() -> dict:
    flat = json.load(open(os.path.join(HERE, 'flat215.json'), encoding='utf-8'))
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    gone = drop_unavailable(sets)
    print(f'снято позиций не в продаже: {gone}')
    global BANKS
    BANKS = pick_banks(sets)
    print('банки демо:', BANKS)
    solve_layouts(flat)                 # раскладки — под реальную комнату, а не под метраж сета
    liv = flat['rooms'][0]
    variants = []
    for k, n in enumerate(BANKS, 1):
        style = f'Вариант {k}'
        fs = glob.glob(os.path.join(HERE, f'v3set{n}-layout.json'))
        if not fs:
            continue
        art = json.load(open(fs[0], encoding='utf-8'))
        items = sets[n - 1].get('items') or {}
        objs = []
        for role, v in art.items():
            if role.startswith('_') or not isinstance(v, dict) or 'x' not in v:
                continue
            if role.split(' ')[0] not in [r.split(' ')[0] for r in SHOW_ROLES]:
                continue
            objs.append({'role': role, 'x': round(v['x'], 1), 'y': round(v['z'], 1),
                         'rot': int(v.get('rot') or 0), 'w': v.get('w'), 'd': v.get('d'),
                         'h': v.get('h'), 'sku': _sku(items, role),
                         # Г-диван: у него ДРУГИЕ пороги (столик может стоять вплотную внутри «Г»,
                         # ТВ ближе — 150 см), иначе советчик выдаёт ложные предупреждения на
                         # плане, который движок считает валидным (26.08)
                         'corner': bool(v.get('corner')),
                         'corner_left': bool(v.get('corner_left')),
                         'section': v.get('section') or v.get('corner_section_cm')})
        # СТИЛЬ ВАРИАНТА (владелец 26.08: «каждый вариант надо добавлять какой это стиль и в
        # промпт стиля добавляй»): берём стиль банка, из которого собран этот вариант.
        variants.append({'id': f'set{n}', 'title': style, 'style': sets[n - 1].get('style'),
                         'fill_pct': art.get('_fill_pct'), 'items': objs})
    # ЛЕНТЫ ТОВАРОВ ПО РОЛЯМ (владелец 26.08: «чтоб фотки можно было назначать»): для каждой роли
    # собираем живые SKU с фото; границы — конверт слота той же комнаты, чтобы примерка не
    # предлагала заведомо негодный габарит (диван 260 см в 14 м²).
    ENV = {'диван': (144, 198), 'кресло': (60, 100), 'столик': (70, 132), 'ковёр': (180, 300),
           'тв-тумба': (90, 176), 'стеллаж': (60, 110), 'комод': (80, 140), 'торшер': (20, 60),
           'пуф': (35, 90), 'кашпо': (20, 60), 'витрина': (50, 100), 'банкетка': (90, 150),
           'стол обеденный': (70, 160), 'стул': (35, 60), 'приставной': (30, 70)}
    feeds, seen = {}, set()
    for s in sets:
        for role, it in (s.get('items') or {}).items():
            base = role.split(' ')[0]
            if base not in ENV or not it or not it.get('img'):
                continue
            key = (base, it.get('mid'), it.get('eid'))
            if key in seen:
                continue
            lo, hi = ENV[base]
            # без ОБОИХ габаритов товар примерять нечестно: объект пришлось бы «додумать»
            if not (it.get('w') and it.get('d')):
                continue
            side = max(it.get('w') or 0, it.get('d') or 0) if base == 'ковёр' else (it.get('w') or 0)
            if not (lo <= side <= hi):
                continue
            try:
                from img_alive import alive_now as _alive
                if not _alive(it.get('img')):
                    continue          # фото мертво — товар в выборку не попадает вовсе
            except Exception:
                pass
            seen.add(key)
            feeds.setdefault(base, []).append(
                {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                 'price': it.get('price'), 'img': it.get('img'), 'url': it.get('url'),
                 'shop': it.get('shop'), 'style': s.get('style')})
    # кап ставим ПОСЛЕ проверки фото (владелец 26.08: «нет фото — товар не участвует в выборке»)
    for k in feeds:
        feeds[k].sort(key=lambda x: x['price'] or 0)
        feeds[k] = feeds[k][:60]
    feed = feeds.get('диван', [])
    # КОМПЛЕКТЫ: набор товаров по ролям, который накладывается на ЛЮБОЙ вариант расстановки
    product_sets = []
    for n in BANKS:
        items = (sets[n - 1].get('items') or {})
        roles = {}
        for role, it in items.items():
            base = role.split(' ')[0]
            if base not in ENV or not it or not it.get('img'):
                continue
            roles[role] = {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'),
                           'h': it.get('h'), 'price': it.get('price'), 'img': it.get('img'),
                           'url': it.get('url'), 'shop': it.get('shop')}
        if roles:
            product_sets.append({'id': f'kit{n}', 'title': f'Комплект {BANKS.index(n) + 1}',
                                 'roles': roles,
                                 'sum': sum((v.get('price') or 0) for v in roles.values())})
    # СПИСОК КОМНАТ КВАРТИРЫ (26.08) — для вкладки «План квартиры». Геометрии всей квартиры у нас
    # нет (с чертежа сняты только габариты гостиной), поэтому отдаём честный состав: название,
    # площадь и признак заглушки. Схему страница рисует из площадей и подписывает как схему.
    rooms = []
    for r in flat['rooms']:
        title = r.get('title') or r.get('id')
        m2 = None
        m = re.search(r'([\d.,]+)\s*(?:\([\d.,]+\)\s*)?м²', title)   # «Лоджия 1.3 (2.6) м²» тоже
        if m:
            m2 = float(m.group(1).replace(',', '.'))
        rooms.append({'id': r.get('id'), 'title': re.sub(r'\s*[\d.,()\s]+м²', '', title).strip(),
                      'm2': m2, 'ready': not r.get('stub')})
    plan = flat.get('plan_example') or {}
    return {'room': {'w': liv['w'], 'd': liv['d'], 'title': liv['title'],
                     'openings': liv['openings'], 'radiators': liv.get('radiators') or []},
            'rooms': rooms, 'flat_title': 'Квартира №215 · 73,7 м²', 'plan': plan,
            'variants': variants, 'sets': product_sets, 'sofa_feed': feed, 'feeds': feeds,
            'rules': _rules(),
            '_note': flat.get('_scale_note')}


def cache_images(data: dict) -> dict:
    """ФОТО КЛАДЁМ К СЕБЕ (владелец 26.08: «фотки не все прогружаются»). Причина — в фиде
    протокол-относительные ссылки на CDN Гдеслона, и примерно половина отдаёт 404: карточки
    приходили пустыми. Качаем один раз, ужимаем до 400 px и раздаём со своего домена; у товара
    с мёртвой ссылкой `img=null` — карточка честно показывает «фото недоступно», а сам товар
    (габариты, цена, ссылка в магазин) остаётся рабочим."""
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import io
    import urllib.request
    from PIL import Image
    imgdir = os.path.join(OUT, 'img')
    os.makedirs(imgdir, exist_ok=True)
    urls = set()
    for lst in (data.get('feeds') or {}).values():
        for p in lst:
            if p.get('img'):
                urls.add(p['img'])
    for kit in (data.get('sets') or []):
        for p in kit['roles'].values():
            if p.get('img'):
                urls.add(p['img'])
    for v in data.get('variants') or []:
        for it in v['items']:
            if (it.get('sku') or {}).get('img'):
                urls.add(it['sku']['img'])

    def grab(u: str):
        name = hashlib.md5(u.encode()).hexdigest()[:16] + '.jpg'
        dst = os.path.join(imgdir, name)
        if os.path.exists(dst):
            return u, 'img/' + name
        full = ('https:' + u) if u.startswith('//') else u
        try:
            req = urllib.request.Request(full, headers={'User-Agent': 'Mozilla/5.0',
                                                        'Referer': 'https://remont-lab.online/'})
            with urllib.request.urlopen(req, timeout=15) as f:
                raw = f.read()
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            im.thumbnail((400, 400))
            im.save(dst, 'JPEG', quality=82)
            return u, 'img/' + name
        except Exception:
            return u, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(grab, sorted(urls)))
    ok = sum(1 for v in got.values() if v)
    print(f'фото: скачано {ok} из {len(urls)} (остальные — битые ссылки фида)')

    def fix(p):
        if p and p.get('img'):
            p['img'] = got.get(p['img'])
    for lst in (data.get('feeds') or {}).values():
        for p in lst:
            fix(p)
    data['sofa_feed'] = data.get('feeds', {}).get('диван', [])
    for kit in (data.get('sets') or []):
        for p in kit['roles'].values():
            fix(p)
    for v in data.get('variants') or []:
        for it in v['items']:
            fix(it.get('sku'))
    # ТОВАР БЕЗ ФОТО В ВЫБОРКЕ НЕ УЧАСТВУЕТ (владелец 26.08): выборку пересчитываем ПОСЛЕ
    # проверки картинок, иначе половина ленты — пустые карточки.
    dropped = 0
    for role, lst in list((data.get('feeds') or {}).items()):
        live = [p for p in lst if p.get('img')]
        dropped += len(lst) - len(live)
        data['feeds'][role] = live[:24]
        if not data['feeds'][role]:
            data['feeds'].pop(role)
    data['sofa_feed'] = data.get('feeds', {}).get('диван', [])
    swapped = 0
    for kit in (data.get('sets') or []):
        fixed = {}
        for r, p in kit['roles'].items():
            if p.get('img'):
                fixed[r] = p
                continue
            pool = (data.get('feeds') or {}).get(r.split(' ')[0]) or []
            side = p.get('w') or 0
            best = min(pool, key=lambda c: abs((c.get('w') or 0) - side)) if pool else None
            if best:                       # роль сохраняем, товар подменяем ближайшим по размеру
                fixed[r] = dict(best)
                swapped += 1
        kit['roles'] = fixed
        kit['sum'] = sum((p.get('price') or 0) for p in kit['roles'].values())
    data['sets'] = [k for k in (data.get('sets') or []) if k['roles']]
    if swapped:
        print(f'в комплектах заменено товаров без фото: {swapped}')
    print(f'из выборки убрано без фото: {dropped}; осталось по ролям: '
          + ', '.join(f"{k} {len(v)}" for k, v in sorted(data['feeds'].items())))
    data['_img_cached'] = {'ok': ok, 'total': len(urls), 'dropped_no_photo': dropped}
    return data


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    # ИСХОДНИК СТРАНИЦЫ ЖИВЁТ В РЕПО (26.08): до этого index.html лежал только в ~/scout-scenes и
    # не попадал в git — демо было невоспроизводимо и терялось при чистке
    import shutil
    src = os.path.join(HERE, 'flat215-demo', 'index.html')
    if os.path.exists(src):
        shutil.copy(src, os.path.join(OUT, 'index.html'))
    data = cache_images(build())
    json.dump(data, open(os.path.join(OUT, 'demo-data.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"OK: вариантов {len(data['variants'])}; ленты: "
          + ', '.join(f"{k} {len(v)}" for k, v in sorted(data['feeds'].items()))
          + f"; комплектов {len(data['sets'])}")
    if '--publish' in sys.argv:
        subprocess.run(f"cd {os.path.dirname(OUT)} && tar czf /tmp/f215demo.tgz flat215-demo && "
                       "scp -q -P 22222 /tmp/f215demo.tgz root@89.167.127.0:/tmp/ && "
                       "ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf flat215-demo && "
                       "tar xzf f215demo.tgz && rm -rf /opt/remlab/test/flat215-demo && "
                       "mv flat215-demo /opt/remlab/test/flat215-demo && rm f215demo.tgz' && "
                       "rm -f /tmp/f215demo.tgz", shell=True, check=True)
        print('опубликовано: /test/flat215-demo/')


if __name__ == '__main__':
    main()
