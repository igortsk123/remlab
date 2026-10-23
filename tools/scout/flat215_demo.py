#!/usr/bin/env python3
"""ДЕМО «интерактив» по квартире 215 (гостиная): экспорт данных для страницы.

Архитектура — по решению владельца 26.08: НИЧЕГО не считаем на лету. Здесь офлайн собираем
`demo-data.json` (комната + предпосчитанные варианты + лента диванов из каталога + числа правил),
а страница только показывает и даёт двигать. Правила для советчика берутся из ТЕХ ЖЕ файлов,
что читает движок, чтобы подсказки не разошлись с каноном.

  ~/venvs/scout/bin/python flat215_demo.py [--publish]      # → /demo/
"""
import functools
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules')
# папка витрины; FLAT215_DEMO_OUT — проверочная сборка рядом, не трогая публикуемую (T-20261019-02)
OUT = os.path.expanduser(os.environ.get('FLAT215_DEMO_OUT') or '~/scout-scenes/flat215-demo')
# ВХОДНОЙ БАНК — SETS_BANK (план conv-13 п.5): демо по копии банка (sets3.next.json) пишет СВОЙ demo-sets.json в OUT и
# раскладки со своим суффиксом — общие `demo-sets.json` и `v3set{n}-layout.json` живого демо не трогает
sys.path.insert(0, HERE)
import bank_paths as _BP  # noqa: E402
BANK = _BP.demo_plan(os.environ, OUT)
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


def hidden(s: dict) -> bool:
    """Сет скрыт банком (`bank_status.state == 'hidden'`, conv-14: ушёл товар ключевой роли — вариант без него не пройдёт
    рубеж ядра): не становится вариантом демо и не даёт товаров в ленты замен. `degraded` — как прежде, дозаполнение. Нет поля
    (старый банк) — не скрыт."""
    return ((s.get('bank_status') or {}).get('state')) == 'hidden'


def pick_banks(sets: list, band: str = '14-16', n: int = 6) -> list:
    """По ОДНОМУ набору на стиль, и это самый СОБИРАЕМЫЙ набор стиля.

    Было: шесть наборов с наибольшим числом предметов, стиль не учитывался вовсе. На странице
    13.10 из-за этого дважды стояла неоклассика, дважды джапанди, а лофта и современного не было
    совсем — владелец читал это как «два одинаковых варианта». Теперь стиль — первичный ключ:
    по одному варианту на каждый, порядок стилей фиксирован, чтобы страница не прыгала.

    Внутри стиля выигрывает тот набор, который МОЖНО ПОКАЗАТЬ ЦЕЛИКОМ: сперва меньше предметов
    без меша (серая коробка в кадре хуже, чем набор поскромнее), потом больше расставляемых
    предметов. Замер 13.10: по этому правилу шести сценам не хватало 12 мешей против 26 у
    прежнего отбора «кто богаче».
    """
    idx = _mesh_index()
    order = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
    best: dict = {}
    for i, st in enumerate(sets, 1):
        if st.get('band') != band or 'диван' not in (st.get('items') or {}) or hidden(st):
            continue
        items = st.get('items') or {}
        placeable = sum(1 for r in items if r.split(' ')[0] in PLACEABLE)
        no_mesh = sum(1 for r, it in items.items()
                      if r.split(' ')[0] in PLACEABLE and it and it.get('mid')
                      and _msid(f"{it['mid']}_{it['eid']}") not in idx)
        key = (no_mesh, -placeable, len(st.get('gaps') or []), i)
        style = st.get('style') or ''
        if style not in best or key < best[style][0]:
            best[style] = (key, i)
    picked = [best[s][1] for s in order if s in best]
    picked += [v[1] for k, v in sorted(best.items()) if k not in order]
    for style in order:
        if style in best:
            k = best[style][0]
            print(f'  вариант стиля «{style}»: набор {best[style][1]}, '
                  f'без меша {k[0]}, расставляемых {-k[1]}', flush=True)
    return picked[:n]
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
    # ЦЕНА — ТЕКУЩАЯ ПРАВДИВАЯ ИЗ КАТАЛОГА, А НЕ ЦЕНА МОМЕНТА СБОРКИ КОМПЛЕКТА (conv-10): фид или страница
    # магазина по правилу, с датой. Каталог товара не знает — остаётся цена банка без даты.
    _pm = {}
    try:
        from catalog_media import media as _media_p
        _pm = _media_p(it.get('mid'), it.get('eid')) or {}
    except Exception:  # noqa: BLE001
        _pm = {}
    return {'name': it.get('name'), 'price': _pm.get('price') or it.get('price'),
            'price_at': _pm.get('price_at'), 'price_basis': _pm.get('price_basis'), 'img': it.get('img'),
            'url': it.get('url'), 'shop': it.get('shop'),
            # ЧЕСТНОЕ НАЛИЧИЕ (Н2): на чём держится «в продаже» — наше свидетельство по карточке (page)
            # или только фид магазина (feed); витрина показывает пометку, а не молчит
            'basis': _basis(it.get('mid'), it.get('eid')),
            # sid — артикул товара; msid — ключ каталога мешей (/test/mesh-pilot10/<msid>/model.glb),
            # он же артикул представителя семейства: 3D-сцена демо грузит модель по нему
            'sid': (f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else None),
            'msid': _msid(f"{it.get('mid')}_{it.get('eid')}"
                          if it.get('mid') and it.get('eid') else None),
            # штук в покупке: сперва разметка каталога (`product_pack`, размечает pack_qty.py
            # по названию/описанию/фото), и только если её нет — разбор названия
            'pack': _pack_of(it.get('mid'), it.get('eid'), it.get('name')),
            **_cat_dims(it)}


def _cat_dims(it: dict) -> dict:
    """Габариты — ИЗ КАТАЛОГА, а не из замороженного банка (та же логика, что у фото и ссылок,
    ADR-0124).

    Протечка, найденная в разборе 01.09: в каталоге глубины у товара НЕТ, а в банке лежит
    посторонняя — она попала туда когда-то и переживала любую синхронизацию, потому что
    `catalog_media` обновляет известные оси и не стирает неизвестную. Пока банк был источником,
    «нет глубины» не наступало никогда, и вывод по мешу не включался ни разу. Теперь неизвестное
    остаётся неизвестным — и его честно достраивает меш.
    """
    try:
        from catalog_media import media as _media
        m = _media(it.get('mid'), it.get('eid')) or {}
    except Exception:  # noqa: BLE001 — каталога нет: остаётся банк
        m = {}
    if not m:
        return {'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'), 'dia': it.get('dia')}
    return {'w': m.get('w'), 'd': m.get('d'), 'h': m.get('h'), 'dia': m.get('dia')}



# РОЛИ С КРУГЛЫМ ИЛИ КВАДРАТНЫМ ОСНОВАНИЕМ: у них глубина равна ширине, и выдумывать её нельзя.
# Торшер Arte Lamp: в карточке магазина глубины НЕТ вовсе, а в банк приехало 30 при ширине 26 и
# диаметре 29 — число ниоткуда. Меш из-за этого растягивали по глубине втрое слабее, чем по
# ширине: круглое основание становилось овальным.
# ТОЛЬКО те роли, у которых основание круглое или квадратное ПО ПРИРОДЕ. Столы и пуфы отсюда
# убраны: они бывают прямоугольными, и приписывать им квадрат — та же выдумка, от которой
# уходим (замечание разбора 01.09).
# ЭТО ПРО ОТРИСОВКУ ВИДА СВЕРХУ, А НЕ ПРО ГЛУБИНУ (11.10). Вопрос «можно ли считать глубину
# равной ширине» решает канон `rules/asset-strategies.json:square_footprint_roles` —
# списки РАЗНЫЕ намеренно: тут важно, как нарисовать пятно на плане, и статуэтка с
# растением рисуются кругом, хотя их глубину из ширины выводить никто не просил.
ROUND_ON_PLAN = {'торшер', 'кашпо', 'ваза', 'лампа', 'растение', 'статуэтка'}
SQUARE_ROLES = ROUND_ON_PLAN   # прежнее имя: на него ссылается остальной файл
# Декор, который стоит НА мебели: в расстановку не идёт (у него нет места на полу), но товар
# куплен и должен появиться в кадре и в смете.
# Роли, которым меш не положен по канону (`asset-strategies.json`): их в ленте не режем.
NOMESH_ROLES = {'ковёр', 'ковер', 'картина', 'зеркало', 'плед', 'покрывало', 'шторы', 'подушка'}
_MESH_IDX = None


def _mesh_index() -> set:
    """SKU, у которых меш реально ЛЕЖИТ НА СЕРВЕРЕ (страница грузит GLB только оттуда).

    ИСТИНА — СВЕЖИЙ ИНДЕКС ПРОДА, без локальной галереи (план demo-20 В1, Codex 22.10): объединение с локальной пускало в
    демо модель, которую `rsync` в эту ночь не довёз, — в кадре она стала бы серой коробкой; а с выкладкой моделей «под
    ленту» (`demo_band` → `mesh_publish`) таких стало бы больше. `?v=` — мимо кэша. Прод не ответил — модели вчерашнего
    демо (они точно на сервере) и WARN: ленты не режем впустую, но и не обещаем непроверенного.
    """
    global _MESH_IDX
    if _MESH_IDX is None:
        idx = set()
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f'https://remont-lab.online/test/mesh-pilot10/mesh-index.json?v={int(time.time())}', timeout=60) as f:
                idx = set(json.load(f))
        except Exception as e:  # noqa: BLE001 — прод недоступен: вчерашнее демо
            idx = _demo_msids(os.path.join(OUT, 'demo-data.json'))
            print(f'WARN:mesh_index: каталог мешей прода недоступен ({repr(e)[:80]}) — беру модели вчерашнего демо: {len(idx)}')
        # КАРАНТИН (conv-04, ADR-0276): модель лежит на сервере, но кривая по осям — для демо её «нет»,
        # предмет дозаполнится заменой из ленты; вернётся после «принять» владельца
        try:
            from mesh_queue import db as _db
            quar = {r[0].replace(':', '_', 1) for r in _db(
                "select sku from mesh_quarantine where coalesce(decision,'cut') in ('cut','reject')") if r and r[0]}
            if quar & idx:
                print(f'карантин: моделей убрано из демо {len(quar & idx)}')
            idx -= quar
        except Exception as e:  # noqa: BLE001 — нет таблицы: карантина нет
            print('карантин не прочитан:', e)
        _MESH_IDX = idx
    return _MESH_IDX


def _demo_msids(path: str) -> set:
    """Модели опубликованного демо (ленты и предметы вариантов) — запасная истина «на сервере», когда прод не ответил."""
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception:  # noqa: BLE001 — демо ещё не собиралось
        return set()
    out = {p['msid'] for lst in (d.get('feeds') or {}).values() for p in lst if p.get('msid')}
    out |= {(i.get('sku') or {}).get('msid') for v in d.get('variants') or [] for i in v.get('items') or []}
    return {m for m in out if m}


_MESH_REP: dict | None = None


def _mesh_rep() -> dict:
    """Артикул товара → артикул его МОДЕЛИ (представителя семейства, ADR-0196).

    Один меш на модель: цветовые варианты своего меша не имеют и берут модель «родителя».
    Раньше демо искало GLB по артикулу самого товара — и рисовало серую коробку, хотя модель
    формы давно готова. Ключ каталога мешей отдаём отдельным полем `msid`, а `sid` остаётся
    артикулом самого товара (карточка, ссылка в магазин).
    """
    global _MESH_REP
    if _MESH_REP is None:
        _MESH_REP = {}
        try:
            from mesh_queue import db
            for r in db("select shop_mid||'_'||external_id, replace(mesh_family_rep,':','_') "
                        "from products where mesh_family_rep is not null"):
                if len(r) == 2 and r[1]:
                    _MESH_REP[r[0]] = r[1]
        except Exception:  # noqa: BLE001 — нет БД: считаем, что модель у каждого своя
            _MESH_REP = {}
    return _MESH_REP


def _msid(sid: str | None) -> str | None:
    return _mesh_rep().get(sid, sid) if sid else None


DECOR_ROLES = {'ваза', 'статуэтка', 'свеча', 'книги', 'поднос', 'шкатулка', 'часы'}


def soft_roles() -> list:
    """Мягкое без места в 3D (demo-24): `asset_strategy.soft_roles` — стратегия `cutout` канона `rules/asset-strategies.json`
    (подушка, шторы, плед, покрывало), кроме настольного декора. Меш им не положен по канону; в варианте они идут строками
    списка и в запрос «Улучшить фото» (`improve_mode.soft_items`), а сцена и план их не рисуют."""
    import asset_strategy as _AS
    return sorted(_AS.soft_roles() - DECOR_ROLES)


def soft_role(role: str | None) -> bool:
    return feed_base(role or '') in soft_roles()


_MESH_EXT_CACHE: dict = {}


def _mesh_extents(sid: str | None):
    """Габариты меша в канонической ориентации (Ш, В, Г) в его собственных единицах.

    Читаем из локальной галереи — тот же файл, что уедет на прод. Ориентация берётся из
    каталога: без неё «ширина» и «глубина» меша могут оказаться переставлены местами.
    """
    if not sid:
        return None
    if sid in _MESH_EXT_CACHE:
        return _MESH_EXT_CACHE[sid]
    path = os.path.expanduser(f'~/scout-scenes/mesh-pilot-gallery/{sid}/model.glb')
    ext = None
    if os.path.exists(path):
        try:
            import numpy as np
            import trimesh
            sys.path.insert(0, HERE)
            import scene_mesh as SM
            yaw = 0.0
            try:
                o = json.load(open(os.path.expanduser('~/scout-scenes/mesh-topview/topview.json'),
                                   encoding='utf-8')).get(sid) or {}
                yaw = float(o.get('yaw') or 0)
            except Exception:  # noqa: BLE001 — нет каталога ориентаций: считаем как есть
                pass
            m = trimesh.load(path, force='mesh')
            v3 = np.asarray(m.vertices, np.float32) @ SM.ry(-yaw).T
            e = v3.max(axis=0) - v3.min(axis=0)
            ext = (float(e[0]), float(e[1]), float(e[2]))
        except Exception:  # noqa: BLE001 — битый меш не должен ронять сборку демо
            ext = None
    _MESH_EXT_CACHE[sid] = ext
    return ext


def _dim_from_mesh(sid, w, d, h):
    """Недостающую ось выводим из ПРОПОРЦИЙ МЕША, опираясь на известные (владелец 01.09).

    Почему это лучше прежнего: раньше недостающая глубина либо выдумывалась числом из другой
    оси, либо бралась «типовая для роли». Меш сделан по фотографии ЭТОГО товара, поэтому его
    отношения сторон — самая близкая к нему оценка из доступных.

    Чем это НЕ является: измерением. Модель по одному фото невидимую глубину не меряет, а
    достраивает — поэтому значение помечается как выведенное (`dims_src`), и владелец смотрит
    такие меши глазами (его решение 01.09: «буду меши смотреть и если что браковать»).

    Масштаб берём как среднее по известным осям, а не по одной: если ширина и высота дают
    разные коэффициенты, одна из них уже врёт, и опираться только на неё нельзя.
    """
    ext = _mesh_extents(sid)
    if not ext or min(ext) <= 1e-6:
        return None
    ex, ey, ez = ext
    ks = []
    if w:
        ks.append(w / ex)
    if h:
        ks.append(h / ey)
    if d:
        ks.append(d / ez)
    if not ks:
        return None
    k = (max(ks) * min(ks)) ** 0.5          # геометрическое среднее известных коэффициентов
    return {'w': round(ex * k, 1), 'h': round(ey * k, 1), 'd': round(ez * k, 1)}


def _dims_of(v: dict, sku: dict | None, role: str = '') -> dict:
    """Габариты предмета — ТОЛЬКО ИЗ КАТАЛОГА (Р1, владелец 03.09: размер не придумывается).

    Что было и убрано: «квадратное основание» d=w для ролей (предположение), вывод оси из пропорций
    меша без калибровки (`_dim_from_mesh`, оставлен только для исследования Р2), подстановка размера
    из старой раскладки — ровно так чужая глубина переживала любую починку каталога (разбор 01.09).
    Единственное допустимое достраивание — диаметр: круглый предмет имеет w = d = dia по определению.
    Неизвестная ось остаётся None; напольный предмет без footprint в сцену не попадает, а страница
    честно пишет «размеры не указаны магазином».
    """
    sku = sku or {}
    w, d, h = sku.get('w'), sku.get('d'), sku.get('h')
    src = 'каталог'
    if sku.get('dia') and not (w and d):
        w, d, src = sku['dia'], sku['dia'], 'диаметр'
    import footprint as _fp
    known = _fp.footprint_known({'w': w, 'd': d})
    return {'w': w, 'd': d, 'h': h, 'dims_src': src if known else 'неизвестно', 'dims_unknown': not known}


BANKS: list = []          # заполняется в build(): выбранные банки демо


def solve_layouts(flat: dict, only: list | None = None) -> None:
    """РАСКЛАДКИ СЧИТАЕМ ПОД ЭТУ КОМНАТУ (26.08). Артефакт `v3set{n}-layout.json` по умолчанию
    считается для условного прямоугольника из метража сета (например 360×415) — если взять
    такой артефакт для комнаты 439×325, мебель окажется за стеной. Поэтому демо само вызывает
    солвер с реальными габаритами и проёмами квартиры, а не надеется на ранее посчитанный файл."""
    liv = flat['rooms'][0]
    env = dict(os.environ, SETS_SNAPSHOT=DEMO_SETS, **({'LAYOUT_SUFFIX': BANK['layout_sfx']} if not BANK['live'] else {}),
               SCENE_OPENINGS=json.dumps([{k: v for k, v in o.items() if not k.startswith('_')}
                                          for o in liv['openings']], ensure_ascii=False),
               SCENE_RADIATORS=json.dumps([{k: v for k, v in r.items() if not k.startswith('_')}
                                           for r in (liv.get('radiators') or [])], ensure_ascii=False))
    py = os.path.expanduser('~/venvs/scout/bin/python')
    for n in (only if only is not None else BANKS):
        art = layout_path(n)
        fresh = (os.path.exists(art)
                 and (json.load(open(art, encoding='utf-8')).get('_room') or {}).get('w') == liv['w']
                 and os.path.getmtime(art) > os.path.getmtime(DEMO_SETS))
        if fresh:
            continue
        r = subprocess.run([py, 'solver_run.py', str(n), '--v3', str(liv['w']), str(liv['d'])],
                           cwd=HERE, env=env, capture_output=True, text=True)
        print(f'  раскладка сета {n}: ' + ('пересчитана' if r.returncode == 0 else f'ОШИБКА\n{r.stderr[-400:]}'))


def _price(it: dict) -> tuple:
    """Правдивая цена товара из каталога (conv-10) и её дата; каталог товара не знает — цена банка."""
    try:
        from catalog_media import media as _m
        m = _m(it.get('mid'), it.get('eid')) or {}
    except Exception:  # noqa: BLE001
        m = {}
    return (m.get('price') or it.get('price'), m.get('price_at'))


def _basis(mid, eid) -> str:
    """page | feed | none — из каталога (catalog_media), см. stock_truth.DERIVED_SQL."""
    if not mid or not eid:
        return 'feed'
    from catalog_media import media as _media
    m = _media(mid, eid) or {}
    return m.get('basis') or 'feed'


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


def demo_apartment() -> dict:
    """Квартира реестра, чья витрина — этот demo-data.json (`sources.demoData`); нет — пустая."""
    root = os.path.join(HERE, '..', '..', 'data', 'partners')
    apts = [a for fn in sorted(glob.glob(os.path.join(root, '*.json')))
            for a in (json.load(open(fn, encoding='utf-8')).get('apartments') or [])]
    # британский двойник английского демо (`enTwin`, ADR-0298) делит ту же витрину — хозяин витрины не он
    twins = {a.get('enTwin') for a in apts if a.get('enTwin')}
    for a in apts:
        if (a.get('sources') or {}).get('demoData') == '/demo/demo-data.json' and a.get('id') not in twins:
            return a
    return {}


def demo_ceiling() -> float | None:
    """Потолок квартиры витрины, см (`apartmentRef.ceilingCm`, T-20261023-04/3); нет — None: 3D и гейт подвеса берут базовые 270."""
    return demo_apartment().get('ceilingCm')


def demo_apartment_id() -> str | None:
    return demo_apartment().get('id')


def apartment_area_check(apt: dict, plan: dict) -> None:
    """Сторожа площадей (T-20261022-04): комнаты реестра + лоджия = площадь квартиры (±0,2, как в `contracts/partner.ts`);
    у каждой комнаты схемы плана — комната реестра с тем же id (подпись и площадь берутся оттуда). Нарушено — сборка падает."""
    rooms = apt.get('rooms') or []
    if rooms:
        tot = sum(r['areaM2'] for r in rooms) + (apt.get('loggiaM2') or 0)
        if abs(tot - apt['areaM2']) > 0.2:
            raise SystemExit(f"FAIL:площади: комнаты {round(tot - (apt.get('loggiaM2') or 0), 2)} + лоджия {apt.get('loggiaM2') or 0} "
                             f"= {round(tot, 2)} м², а квартира {apt['areaM2']} м² (data/partners)")
    ids = {r['id'] for r in rooms}
    lost = [r.get('id') for r in plan.get('rooms') or [] if r.get('id') not in ids]
    if rooms and lost:
        raise SystemExit(f'FAIL:площади: комнат схемы плана нет в реестре квартиры: {lost}')


# id стиля для адреса главной (`?style=scandi`, demo-16): латиница, стабильная между пересборками
STYLE_IDS = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft',
             'неоклассика': 'neoclassic', 'джапанди': 'japandi'}


def style_id(style: str | None) -> str:
    """Латинский id стиля; неизвестный стиль — транслит не выдумываем, пусто (страница возьмёт свой словарь)."""
    return STYLE_IDS.get(str(style or '').strip().lower(), '')


def living_room_id() -> str:
    """Комната, которую обставляют варианты витрины: первая гостиная квартиры из реестра; реестра нет — `living`."""
    return next((r['id'] for r in demo_apartment().get('rooms') or [] if r.get('kind') == 'living'), 'living')


DEMO_SETS = BANK['demo_sets']     # банк, по которому считается расстановка демо (`HERE/demo-sets.json`; у копии — в OUT)


def layout_path(n: int) -> str:
    """Раскладка набора `n` в комнате демо: `v3set{n}-layout.json`, у копии банка — со своим суффиксом."""
    return os.path.join(HERE, f"v3set{n}-layout{BANK['layout_sfx']}.json")
# Конверт слотов ЭТОЙ комнаты (гостиная 439×325): для ленты замен и для дозаполнения вариантов.
# Правило — `rules/demo-swap.json → room_fit_envelope_cm` (conv-03, ADR-0271): «что физически встаёт в комнату»,
# шире идеала слота сборки (`slot_rules`), иначе ленты сократились бы в разы.
_SWAP_RULES = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))
DEMO_ENV = {k: tuple(v) for k, v in _SWAP_RULES['room_fit_envelope_cm'].items() if not k.startswith('_')}


def fill_banks(sets: list, band: str = '14-16', per_style: int = 5) -> tuple[list, dict, list]:
    """Выбор набора стиля ПОСЛЕ дозаполнения (план conv-09 п.2/п.5) → (BANKS, журнал, неполные стили).

    На стиль берём `per_style` лучших по прежнему ключу, каждый дозаполняем (`demo_fill.fill_set`) в
    копии и выбираем того, у кого полнее ядро, меньше без модели и больше расставляемых. Банк на диске
    не трогаем — его лечит ночной конвейер."""
    import copy
    import demo_fill as DF
    import footprint as _fp
    from catalog_media import media as _media
    from img_alive import alive_now as _alive
    from item_function import subtype as _sub
    from proportions import check as _prop
    from sets_incremental import _card            # лёгкий модуль; `_slot_ok` НЕ берём — он тянет compose2
    gate = DF.make_gate(DEMO_ENV, _media, _alive, _fp.footprint_known, _prop, _sub)
    idx = _mesh_index()
    # МОДЕЛЬ СЕМЕЙСТВА ДОЛЖНА ПОДХОДИТЬ ТОВАРУ ПО ЦВЕТУ (demo-05 п.3, 15.10): цветовой вариант берёт меш представителя
    # семейства (ADR-0196), и бежевый стул «Алекс» рисовался чёрной моделью графитового. Такая позиция — как «нет модели»:
    # лечение подставит другой товар, а ворота (`scene_checks.py`) поймают пропущенное
    # МОДЕЛЬ СЕМЕЙСТВА ДРУГОГО ЦВЕТА — тоже «нет модели» для предметов варианта (demo-05 п.2b, разбор Codex 16.10: у джапанди
    # серая «Брера» рисовалась разноцветной моделью представителя, у сканди голубой «Викс» — серой). Только для того, что видно
    # по умолчанию: в лентах таких вариантов семейства большинство (стулья 50 из 62) — там замер, лечение — перекраска (mesh_tint)
    import mesh_dark as _MDK
    has_mesh = lambda it: (_msid(f"{it.get('mid')}_{it.get('eid')}") in idx  # noqa: E731
                           and color_ok(_msid(f"{it.get('mid')}_{it.get('eid')}"), it.get('name') or '')
                           and _MDK.family_colour_mismatch(f"{it.get('mid')}_{it.get('eid')}",
                                                           _msid(f"{it.get('mid')}_{it.get('eid')}")) is None)
    _gate0 = gate
    # ПРИГОДНОСТЬ ДЛЯ ГОСТИНОЙ — то же правило, что у подбора наборов (`unfit.py`): 15.10 лечение подставило к обеденному
    # столу барный стул «Эрин»
    from unfit import unfit as _unfit
    gate = lambda role, c, s_, others: (_gate0(role, c, s_, others)  # noqa: E731
                                        and not _unfit(DF.base_role(role), c.get('name'), None, c.get('h'), d=c.get('d'))
                                        and (DF.base_role(role) in NOMESH_ROLES or has_mesh(c)))
    pool = DF.load_pool()
    print(f'пул дозаполнения: {len(pool)} товаров', flush=True)
    # «есть ли чем заменить банкетку» — по ленте замен стиля (demo-19 Г2); пул недоступен — считаем по наборам, громко
    try:
        import demo_swap_pool as _DSP
        benches = bench_pool(sets, _DSP.pool(swap_ok, roles=(BENCH,), ceiling_cm=demo_ceiling()))
    except Exception as e:  # noqa: BLE001
        print(f'WARN:bench_pool: банкетки пула не прочитаны ({repr(e)[:120]}) — считаю только по наборам', flush=True)
        benches = bench_pool(sets)
    print(f'банкетки в лентах стилей: {dict(sorted((k, len(v)) for k, v in benches.items()))}; '
          f'«уголок» — при ≥ {NOOK_MIN}', flush=True)
    by_style: dict = {}
    n_hidden = 0
    for i, st in enumerate(sets, 1):
        if st.get('band') != band:
            continue
        if hidden(st):
            n_hidden += 1
            continue
        items = st.get('items') or {}
        placeable = sum(1 for r in items if DF.base_role(r) in PLACEABLE)
        by_style.setdefault(st.get('style') or '', []).append((-placeable, len(st.get('gaps') or []), i))
    if n_hidden:
        print(f'скрыты банком (bank_status hidden) — не варианты: {n_hidden} наборов полосы {band}', flush=True)
    order = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
    ranked: dict = {}
    taken: set = set()          # товары, уже подставленные в другие стили: разнообразие между вариантами
    for style in order + sorted(k for k in by_style if k not in order):
        cands = []

        def filled(i: int, own: bool) -> tuple:
            s = copy.deepcopy(sets[i - 1])
            j = DF.fill_set(s, pool, gate, _card, _media, has_mesh, DEMO_ENV, taken, own=own)
            nook = drop_lonely_nook(s, benches)
            if nook:
                j.append(nook)
            items = s.get('items') or {}
            no_mesh = sum(1 for r, it in items.items() if DF.base_role(r) in PLACEABLE
                          and DF.base_role(r) not in NOMESH_ROLES and it and not has_mesh(it))
            placeable = sum(1 for r in items if DF.base_role(r) in PLACEABLE)
            return ((len(DF.core_missing(s)), no_mesh, -placeable, i, 0 if own else 1), i, s, j)
        for _k in sorted(by_style.get(style, []))[:per_style]:
            c = filled(_k[2], True)
            cands.append(c)
            # СВОЙ ЗАПАСНОЙ НЕ ДЕЛАЕТ ХУЖЕ ПРЕЖНЕГО (T-20261023-10): ворота он проходит, но расстановку может не дать (23.10
            # «современный»: свой столик 120×58 вытеснил торшер). Брали свой запасной — тот же набор с прежним дозаполнением
            # из пула идёт сразу следом (ключ на единицу хуже), и `choose_banks` попробует его раньше следующего набора
            if any(x.get('source') for x in c[3]):
                cands.append(filled(_k[2], False))
        if cands:
            ranked[style] = sorted(cands, key=lambda c: c[0])
            taken |= {x['to_sku'] for x in ranked[style][0][3] if x.get('to_sku')}
    return ranked


def swap_ok(p: dict) -> bool:
    """Товар пула показуем в ленте замен — те же проверки, что лента применяет к товарам сетов: живое фото, модель семейства
    лежит на сервере (не карантин) и подходит товару по цвету, предмет годится для гостиной (`unfit.py`). Пул ленты зовёт её
    ДО отбора 30 в группе (`demo_swap_pool.pick`, demo-18 п.1); ширину комнаты пул проверяет сам по `rules/demo-swap.json`.
    Дозаполнение вариантов берёт прежний пул (`pool_top`): показываемые варианты в этой задаче не меняются."""
    from img_alive import alive_now
    from unfit import unfit
    return (bool(p.get('msid')) and p['msid'] in _mesh_index() and not unfit(p.get('role'), p.get('name'), None, p.get('h'), d=p.get('d'))
            and color_ok(p['msid'], p.get('name')) and alive_now(p.get('img')))


@functools.lru_cache(maxsize=1)
def rug_ceiling() -> float:
    """Потолок длинной стороны ковра в гостиной демо: конверт ленты (`DEMO_ENV`) и проектный предел комнаты по площади
    (`zones.json` → `template_slot_envelopes.slots.ковёр`, ≤ 16 м² — 260: у стен остаётся полоса пола) — меньшее."""
    import slot_rules
    liv = json.load(open(os.path.join(HERE, 'flat215.json'), encoding='utf-8'))['rooms'][0]
    room = slot_rules.slot_ideal('ковёр', liv['w'] * liv['d'] / 10000)
    return min(DEMO_ENV['ковёр'][1], room or DEMO_ENV['ковёр'][1])


def _slot_band(liv: dict) -> dict:
    """Полоса ленты замен для гостиной демо (`slot_rules.slot_band` по площади комнаты из чертежа)."""
    import slot_rules
    return slot_rules.slot_band(liv['w'] * liv['d'] / 10000)


def swap_rug_ok(p: dict) -> bool:
    """Ковёр показуем в ленте замен (demo-18 п.2): есть артикул, цена и ссылка (без них корзина товар не признаёт —
    `lib/collections/prices.ts`), живое фото, не детский по картинке (`rug_kids.py`), годится для гостиной (`unfit.py`, резиновый
    и т. п.), размер — контракт зонного ковра (`demo_fill.rug_fits`: короткая ≥ 140) и потолок комнаты (`rug_ceiling`). «Не
    короче дивана» проверяет место (окно — `feedFor`, /flat — `demo-feeds.candidates`): диван можно заменить."""
    import demo_fill as DF
    import rug_kids
    from img_alive import alive_now
    from unfit import unfit
    w, d = p.get('w') or 0, p.get('d') or 0
    return (bool(p.get('sid')) and (p.get('price') or 0) > 0 and bool(p.get('url'))
            and DF.rug_fits(w, d) and max(w, d) <= rug_ceiling()
            and not unfit('ковёр', p.get('name'), None, p.get('h'), d=p.get('d')) and not rug_kids.is_kids_rug(p.get('img'))
            and alive_now(p.get('img')))


_COLOR_OK = []


def color_ok(msid, name) -> bool:
    """Общий экземпляр проверки «модель семейства подходит товару по цвету» (`_mesh_color_ok`) — сборка, ленты замен и пул."""
    if not _COLOR_OK:
        _COLOR_OK.append(_mesh_color_ok())
    return _COLOR_OK[0](msid, name or '')


def feed_base(role: str) -> str:
    """Ключ ленты замен — роль БЕЗ ХВОСТОВОГО НОМЕРА, а не «первое слово» (владелец 01.09: «стол косячный, просил заменить,
    а он до сих пор в модели»). `split(' ')[0]` резал «стол обеденный» до «стол», такого ключа в конверте нет — и обеденные
    столы не попадали в ленту замены ВООБЩЕ. Номер экземпляра («стул 2») по-прежнему отбрасываем."""
    return re.sub(r'\s+\d+$', '', role)


def feed_envs() -> tuple[dict, dict]:
    """Конверты лент замен → (мебель и декор, только декор), `rules/demo-swap.json`. НАСТОЛЬНЫЙ ДЕКОР — СВОЙ КОНВЕРТ (владелец
    08.09: «вазы настольные … добавлять в список товаров и считать сумму»): слота на полу у него нет, граница — «влезает на
    столешницу», поэтому меряем сам предмет, а не место в комнате."""
    dec = {k: tuple(v) for k, v in _SWAP_RULES['decor_envelope_cm'].items() if not k.startswith('_')}
    return {**DEMO_ENV, **dec}, dec


def set_feed_row(base: str, it: dict | None, style: str | None) -> dict | None:
    """Товар набора → строка ленты замен его роли, или None, если показать его заменой нельзя. Одна проверка для ленты
    (`build`) и для счёта «есть ли чем заменить» (`bench_pool`, demo-19 Г2)."""
    env_all, env_decor = feed_envs()
    if soft_role(base):
        return soft_feed_row(base, it, style)
    if base not in env_all or not it or not it.get('img'):
        return None
    lo, hi = env_all[base]
    # без ОБОИХ габаритов товар примерять нечестно: объект пришлось бы «додумать»
    if not (it.get('w') and it.get('d')):
        return None
    # У НАСТОЛЬНОГО ДЕКОРА ТРЕБУЕМ И ВЫСОТУ (08.09). Ваза встаёт на столешницу, и без высоты сцена её поставить не может —
    # предлагать в замену то, что не появится в кадре, нельзя (пул это условие держит с самого начала, лента — не держала).
    if base in env_decor and not it.get('h'):
        return None
    side = max(it.get('w') or 0, it.get('d') or 0) if base == 'ковёр' else (it.get('w') or 0)
    if not (lo <= side <= hi):
        return None
    try:
        from img_alive import alive_now as _alive
        if not _alive(it.get('img')):
            return None          # фото мертво — товар в выборку не попадает вовсе
    except Exception:  # noqa: BLE001
        pass
    # ТОЛЬКО ТО, ЧТО МЫ УМЕЕМ ПОКАЗАТЬ (владелец 01.09: «по кнопкам „заменить“ оставь только то, что есть в мешах и подходит
    # под соответствующий стиль»). Товар без меша, поставленный заменой, превращает предмет в серую заглушку — предлагать его
    # человеку значит обещать то, чего не будет в кадре. `sid` кладём рядом: страница по нему берёт модель.
    _sid = f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else None
    _msd = _msid(_sid)
    if base not in NOMESH_ROLES and (not _msd or _msd not in _mesh_index() or not color_ok(_msd, it.get('name'))):
        return None          # нет модели или модель семейства другого цвета (demo-05: бежевый товар — чёрный меш)
    from unfit import unfit as _unfit
    if _unfit(base, it.get('name'), None, it.get('h'), d=it.get('d')):
        return None          # барный/офисный стул, уличное, резиновый ковёр — не для гостиной (`unfit.py`)
    # КОВЁР — ТЕ ЖЕ ПРОВЕРКИ, ЧТО У ЛЕНТЫ КОВРОВ ИЗ ПУЛА (demo-18 п.2): потолок комнаты (ковёр 200×300 съедал проход у стен),
    # короткая ≥ 140, артикул и цена, не детский; длинная сторона — в `w`, как у пула
    if base == 'ковёр' and not swap_rug_ok({**it, 'sid': _sid, 'price': _price(it)[0]}):
        return None
    # ковёр — как строка пула (`demo_swap_pool.rug_sql`): длинная в `w`, плита 1 см, модель = товар
    _w, _d, _h = ((max(it['w'], it['d']), min(it['w'], it['d']), 1.0) if base == 'ковёр'
                  else (it.get('w'), it.get('d'), it.get('h')))
    _msd = _msd or (_sid if base == 'ковёр' else None)
    return {'name': it.get('name'), 'w': _w, 'd': _d, 'h': _h,
            'price': _price(it)[0], 'price_at': _price(it)[1], 'img': it.get('img'), 'url': it.get('url'),
            'shop': it.get('shop'), 'style': style, 'sid': _sid, 'msid': _msd,
            'src': 'set',
            'basis': _basis(it.get('mid'), it.get('eid')),
            'hung': _hung(it.get('name')),
            # ШТУК В ПОКУПКЕ — И В ЛЕНТЕ ЗАМЕНЫ ТОЖЕ (02.09). Без этого после замены товара «Стул 2 шт.» два слота считались
            # бы двумя покупками, хотя это одна.
            'pack': _pack_of(it.get('mid'), it.get('eid'), it.get('name'))}


_SOFT_LOST: set = set()


def soft_lost(sets: list) -> set:
    """Мягкое банка, у которого каталог СНЯЛ РОЛЬ — {'mid:eid'} (demo-24 правки). Ночное лечение банка стоит на предохранителе
    (`demo_fill.py`, шапка), и снятая загрузкой роль (детская линия — `category_map.soft_kids`, `load3.mark_soft_kids`) из банка
    сама не уходит: лягушка «Вигге» осталась бы подушкой в показе. Правило не дублируем — читаем его итог, `products.cat_role`.
    Нет базы — пусто (сбой пробы ≠ вердикт)."""
    keys = sorted({f"{it.get('mid')}:{it.get('eid')}" for s in sets for r, it in (s.get('items') or {}).items()
                   if it and it.get('mid') and it.get('eid') and soft_role(r)})
    if not keys:
        return set()
    try:
        from mesh_queue import db as _db
        lit = ','.join("'" + k.replace("'", "''") + "'" for k in keys)
        return {r[0] for r in _db(f"select shop_mid||':'||external_id from products where cat_role is null "
                                  f"and shop_mid||':'||external_id = any(array[{lit}])") if r and r[0]}
    except Exception as e:  # noqa: BLE001
        print(f'WARN:soft_lost: роль мягкого в каталоге не проверена: {repr(e)[:120]}', flush=True)
        return set()


def soft_feed_row(base: str, it: dict | None, style: str | None) -> dict | None:
    """Мягкое (demo-24) → строка ленты замен: места на полу и модели нет, поэтому ни конверта размера, ни меша не требуем —
    только то, без чего строку списка не показать честно: название, живое фото, цена и ссылка в магазин. Роль снята
    каталогом (детская линия) — не в ленту."""
    if not it or not it.get('name') or not it.get('img') or not it.get('url') or not _price(it)[0]:
        return None
    if f"{it.get('mid')}:{it.get('eid')}" in _SOFT_LOST:
        return None
    try:
        from img_alive import alive_now as _alive
        if not _alive(it.get('img')):
            return None
    except Exception:  # noqa: BLE001
        pass
    _sid = f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else None
    return {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
            'price': _price(it)[0], 'price_at': _price(it)[1], 'img': it.get('img'), 'url': it.get('url'),
            'shop': it.get('shop'), 'style': style, 'sid': _sid, 'msid': None, 'src': 'set', 'soft': True,
            'basis': _basis(it.get('mid'), it.get('eid')),
            'pack': _pack_of(it.get('mid'), it.get('eid'), it.get('name'))}


def pool_feed_check(p: dict) -> str:
    """Товар пула (`demo_swap_pool`) годится в ленту замен? → '' — да; иначе причина ('off_env' — габарит вне конверта роли).
    Те же проверки, что у товаров наборов (`set_feed_row`); одна функция для ленты (`build.glue`) и для счёта (`bench_pool`)."""
    base = p['role']
    env_all, _ = feed_envs()
    if base not in env_all:
        return 'role'
    if not p.get('img') or not (p.get('w') and p.get('d')):
        return 'dims'
    if base not in NOMESH_ROLES and (not p.get('msid') or p['msid'] not in _mesh_index() or not color_ok(p['msid'], p.get('name'))):
        return 'mesh'        # модели на сервере нет (серая коробка) или она другого цвета, чем товар; ковёр — плита с фото
    from unfit import unfit as _unfit
    if _unfit(base, p.get('name'), None, p.get('h'), d=p.get('d')):
        return 'unfit'       # не для гостиной (`unfit.py`): барный стул в ленте обеденных и т.п.
    lo, hi = env_all[base]
    if not (lo <= (p.get('w') or 0) <= hi):
        return 'off_env'     # габарит вне конверта слота этой комнаты
    return ''


BENCH = 'банкетка'
NOOK_MIN = int(_SWAP_RULES['nook_min_benches'])


def bench_pool(sets: list, pool_rows: list | None = None) -> dict[str, set]:
    """Банкетки, которые лента замен покажет стилю → {стиль: {sid}} — тем же отбором, что сама лента (`build`): товары наборов
    (`set_feed_row`, без снятых из продажи) и пул (`pool_feed_check`); товар набора, который пул отобрал и для другого стиля, —
    в обоих (`glue` дописывает ему стиль). `pool_rows` — банкетки пула (`demo_swap_pool.pool(swap_ok, roles=…)`)."""
    from catalog_media import media as _media
    out: dict = {}
    known: set = set()
    for s in sets:
        it = (s.get('items') or {}).get(BENCH)
        if not it or hidden(s):
            continue
        m = _media(it.get('mid'), it.get('eid'))
        if m is None or m.get('state') == 'gone':
            continue                # снят из продажи: ленту строят по банку без таких (`drop_unavailable`)
        row = set_feed_row(BENCH, it, s.get('style'))
        if row and row['sid']:
            known.add(row['sid'])
            out.setdefault(s.get('style') or '', set()).add(row['sid'])
    for p in pool_rows or []:
        if p.get('role') == BENCH and (p['sid'] in known or not pool_feed_check(p)):
            out.setdefault(p.get('style') or '', set()).add(p['sid'])
    return out


def drop_lonely_nook(s: dict, benches: dict) -> dict | None:
    """«УГОЛОК» С БАНКЕТКОЙ — ТОЛЬКО ЕСЛИ ЕЁ ЕСТЬ ЧЕМ ЗАМЕНИТЬ (владелец 20.10, demo-19 Г2). В ленте сканди банкетка была одна —
    сама эта: кнопка «заменить» открывала пустой выбор. Банкеток в ленте стиля меньше `NOOK_MIN` (`rules/demo-swap.json`) —
    банкетку из набора снимаем, и солвер расставляет обычную столовую со стульями, как в других стилях (без банкетки
    `template.place_edge_nook` не пробуется). Снимаем ДО расстановки и ДО выбора набора стиля: план рисует солвер по правилам,
    а выбор видит настоящий состав. → строка журнала дозаполнения или None."""
    items = s.get('items') or {}
    b = items.get(BENCH)
    if not b:
        return None
    n = len(benches.get(s.get('style') or '', set()))
    if n >= NOOK_MIN:
        return None
    items.pop(BENCH)
    return {'role': BENCH, 'from': b.get('name'), 'from_sku': f"{b.get('mid')}:{b.get('eid')}", 'to': None, 'to_sku': None,
            'reason': f'уголок: банкеток в ленте стиля {n} < {NOOK_MIN} — столовая со стульями'}


def _mesh_color_ok():
    """→ функция (msid, название товара) → годится ли модель по цвету — ТЕМ ЖЕ правилом, что ворота сцены
    (`scene_checks.dark_models` → `mesh_dark.measure`): яркость модели против названия И против фото, с которого модель
    сделана (`cutout.png` рядом с моделью). 15.10 сборка судила только по названию — «Алекс Замша Оливковый» (модель 11/255
    при фото в 5 раз светлее; «оливковый» не светлый цвет) прошёл в минимализм, и ворота скрыли весь стиль. Яркость
    поверхности модели и фото считаются один раз и кэшируются по файлу (`~/scout-scenes/mesh-luma-cache.json`)."""
    import mesh_dark as MDK
    # MESH_LUMA_CACHE — своя копия кэша у изолированных прогонов (проверки банка): кэш живого демо они не дописывают
    path = os.path.expanduser(os.environ.get('MESH_LUMA_CACHE') or '~/scout-scenes/mesh-luma-cache.json')
    try:
        cache = json.load(open(path))
    except (OSError, ValueError):
        cache = {}
    dirty = [False]

    def ok(msid: str | None, name: str) -> bool:
        glb = os.path.expanduser(f'~/scout-scenes/mesh-pilot-gallery/{msid}/model.glb') if msid else ''
        if not glb or not os.path.exists(glb):
            return True                       # нет файла — судить не о чем (есть ли модель, решает индекс)
        key = f'{msid}:{int(os.path.getmtime(glb))}'
        if key not in cache:
            try:
                import gc
                import trimesh
                _sc = trimesh.load(glb, force='scene')
                cache[key] = MDK.surface_luma(list(_sc.geometry.values()))
                del _sc
                gc.collect()            # моделей в лентах сотни: без сборки мусора на DEV снимал сторож памяти
            except Exception as e:  # noqa: BLE001 — не открылась: не браковать, но громко
                print(f'  яркость модели {msid}: не замерена ({str(e)[:60]})', flush=True)
                cache[key] = None
            dirty[0] = True
            if len(cache) % 25 == 0:
                json.dump(cache, open(path, 'w'))
        pkey = 'photo:' + key
        if pkey not in cache:
            try:
                cache[pkey] = MDK.photo_luma(os.path.join(os.path.dirname(glb), 'cutout.png'))
            except Exception as e:  # noqa: BLE001 — фото не открылось: судим по названию, но громко
                print(f'  яркость фото {msid}: не замерена ({str(e)[:60]})', flush=True)
                cache[pkey] = None
            dirty[0] = True
        return MDK.dark_flag(cache[key], name, cache[pkey]) is None

    import atexit
    atexit.register(lambda: dirty[0] and json.dump(cache, open(path, 'w')))
    return ok


def layout_ok(n: int, core: tuple = ()) -> bool:
    """Расстановка набора сошлась: нет отказа солвера и на полу стоят ВСЕ роли ядра (не «хоть что-то»)."""
    p = layout_path(n)
    try:
        art = json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return False
    placed = {re.sub(r'\s+\d+$', '', k) for k, v in art.items()
              if not k.startswith('_') and isinstance(v, dict) and 'x' in v}
    return bool(placed) and not art.get('_infeasible_reason') and all(c in placed for c in core)


def choose_banks(flat: dict, sets: list, ranked: dict) -> tuple[list, dict, list]:
    """По стилю — первый набор, у которого полное ядро И сошлась расстановка в ЭТОЙ комнате (conv-09).

    Отказ солвера — тоже повод взять следующий набор стиля, а не публиковать пустую комнату: 13.10 лофт с
    угловым диваном 186×151 и ковром 300×200 не дал зоны ТВ в 14 м² (MEDIA_MISSING) и приехал без мебели."""
    import demo_fill as DF
    banks, journal, incomplete = [], {}, []
    for style, cands in ranked.items():
        why = None
        for key, i, s, j in cands:
            miss = DF.core_missing(s)
            if miss:
                why = why or {'style': style, 'missing': miss}
                continue
            orig = sets[i - 1]
            sets[i - 1] = s
            _write_demo_sets(sets)
            # прежний файл расстановки удаляем: упал солвер — не должен подхватиться вчерашний результат
            try:
                os.remove(layout_path(i))
            except FileNotFoundError:
                pass
            solve_layouts(flat, only=[i])
            if not layout_ok(i, DF.CORE):
                print(f'  стиль «{style}»: набор {i} не расставился в комнате — беру следующий', flush=True)
                sets[i - 1] = orig
                why = why or {'style': style, 'missing': ['расстановка не сошлась']}
                continue
            print(f'  вариант стиля «{style}»: набор {i}, ядро полное, без модели {key[1]}, расставляемых {-key[2]}, '
                  f'замен {sum(1 for x in j if x["to"])}, снято без замены {sum(1 for x in j if not x["to"])}', flush=True)
            banks.append(i)
            journal[f'set{i}'] = j
            why = None
            break
        if why:
            # стиль пропал из демо — в дайджест (T-20261023-08: ночь 23.10 сняла лофт и неоклассику молча, живая 2.21 покраснела)
            print(f'WARN:demo_style_dropped: стиль «{style}»: полного варианта нет ({", ".join(why["missing"])}) — не публикуем',
                  flush=True)
            incomplete.append(why)
    _write_demo_sets(sets)
    return banks[:6], journal, incomplete


def _write_demo_sets(sets: list) -> None:
    """Банк для солвера; переписываем только при изменении — раскладки не пересчитываются зря."""
    blob = json.dumps(sets, ensure_ascii=False)
    if not os.path.exists(DEMO_SETS) or open(DEMO_SETS, encoding='utf-8').read() != blob:
        open(DEMO_SETS, 'w', encoding='utf-8').write(blob)


def fill_report(journal: dict, gone: int) -> dict:
    """«ЧТО ДЕМО ДОЗАПОЛНИЛО САМО» (план conv-13 п.5): демо перед показом чинит копию банка (`demo_fill.fill_set`), и
    полный на вид вариант не доказывает полноты банка. Строка в журнал всегда; у копии банка — ещё и файл в OUT.
    Для нового банка ожидание — 0 замен и 0 снятых."""
    rows = [dict(x, set=k) for k, j in journal.items() for x in j]
    rep = {'replaced': sum(1 for x in rows if x.get('to')), 'dropped': sum(1 for x in rows if not x.get('to')),
           'gone_outside_variants': gone, 'rows': rows}
    print(f"дозаполнено демо: замен {rep['replaced']}, снято без замены {rep['dropped']}, "
          f"не в продаже вне вариантов {gone}", flush=True)
    if not BANK['live']:
        os.makedirs(OUT, exist_ok=True)
        json.dump(rep, open(os.path.join(OUT, 'demo-fill-report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rep


BEDROOM_SHOW = {'кровать': 24, 'тумба прикроватная': 12, 'комод': 12, 'шкаф': 12, 'туалетный столик': 8}


def bedroom_catalog() -> dict:
    """Фото-каталог спальни для вкладки «Спальня 1» (план b2b-10 этап 2, v1; ADR-0279) из `room_catalog`.

    Выборка на роль — по одной модели из семейства (без десяти цветов одной кровати) и ровно по цене: от дешёвых
    к дорогим через равные шаги, чтобы видно было весь диапазон. Показываем только с ценой, фото и из свежего фида
    (`room_catalog.shown_where`). Кровати — с честным габаритом впереди. Нет таблицы/базы — пусто, вкладка «скоро»."""
    try:
        import room_catalog as RC
        from mesh_queue import db as _db
        rows = _db("select role, shop_mid||':'||external_id, name, shop, url, coalesce(image_url_hd, image_url), price_rub, "
                   "w_cm, d_cm, h_cm, sleep_w_cm, sleep_l_cm, coalesce(footprint_ok,false), "
                   "to_char(max(last_seen) over (), 'YYYY-MM-DD') from room_catalog where " + RC.shown_where())
    except Exception as e:  # noqa: BLE001 — каталога спальни нет: вкладка остаётся «скоро»
        print(f'каталог спальни: недоступен ({str(e)[:80]})')
        return {}
    by: dict = {}
    updated = ''
    for r in rows:
        role, sid, name, shop, url, img, price, w, d, h, sw, sl, ok, upd = r
        updated = upd or updated
        # семейство = название до первого слова с цифрой и без скобок цвета/материала: «Кейт 160 Букле Серый»,
        # «Торвалль 2-68x87», «Castello (Экокожа Слива) 140x190» → одна модель
        fam = re.sub(r'\s\S*\d.*$', '', re.sub(r'\s*\(.*$', '', name)).strip().lower()
        by.setdefault(role, {}).setdefault(fam, []).append({
            'sid': sid, 'name': re.sub(r'\s+', ' ', name).strip(), 'shop': shop, 'url': url, 'img': img, 'price': int(price),
            'w': w, 'd': d, 'h': h, 'sleep': [sw, sl] if sw and sl else None, 'fits': ok in (True, 't')})
    out = {}
    for role, fams in by.items():
        reps = []
        for items in fams.values():                      # представитель семейства: честный габарит, потом дешевле
            items.sort(key=lambda x: (not x['fits'], x['price']))
            reps.append(items[0])
        reps.sort(key=lambda x: x['price'])
        k = BEDROOM_SHOW.get(role, 8)
        pick = reps if len(reps) <= k else [reps[round(i * (len(reps) - 1) / (k - 1))] for i in range(k)]
        out[role] = pick
    print('каталог спальни: ' + ', '.join(f'{r} {len(v)} (моделей {len(by[r])})' for r, v in out.items()))
    return {'roles': out, 'updated': updated}


def build() -> dict:
    flat = json.load(open(os.path.join(HERE, 'flat215.json'), encoding='utf-8'))
    sets = json.load(open(BANK['bank'], encoding='utf-8'))
    _SOFT_LOST.clear()
    _SOFT_LOST.update(soft_lost(sets))      # мягкое без роли в каталоге — не в варианты и не в ленты (demo-24 правки)
    if _SOFT_LOST:
        print(f'мягкое банка без роли в каталоге (детские линии и т.п.): {len(_SOFT_LOST)} — заменяем из ленты', flush=True)
    if not BANK['live']:
        print(f"БАНК: {BANK['bank']} (копия; demo-sets и раскладки — свои, суффикс {BANK['layout_sfx']})", flush=True)
    global BANKS
    # расстановка считается по ДОЗАПОЛНЕННОМУ банку (`demo-sets.json`): иначе место под снятый товар в
    # комнате остаётся, а самого товара нет (conv-09)
    BANKS, fill_journal, incomplete = choose_banks(flat, sets, fill_banks(sets))
    gone = drop_unavailable(sets)       # у невыбранных наборов — для лент замен (выбранные уже чисты)
    print(f'снято позиций не в продаже (вне выбранных вариантов): {gone}')
    fill_report(fill_journal, gone)
    print('банки демо:', BANKS)
    liv = flat['rooms'][0]
    variants = []
    for k, n in enumerate(BANKS, 1):
        # ПОДПИСЬ — СТИЛЬ, А НЕ НОМЕР (13.10). «Вариант 1…6» ничего не говорит, и два набора
        # одного стиля выглядели как дубль. Номер остаётся только запасным именем.
        style = (sets[n - 1].get('style') or f'Вариант {k}').capitalize()
        fs = glob.glob(layout_path(n))
        if not fs:
            continue
        art = json.load(open(fs[0], encoding='utf-8'))
        items = sets[n - 1].get('items') or {}
        objs = []
        dims_unknown = []      # напольные без размера — не в сцене, а в честном списке (Р1)
        missing_item = []      # раскладка просит роль, а товара нет — это НЕ «размер не указан» (conv-09 п.4)
        for role, v in art.items():
            if role.startswith('_') or not isinstance(v, dict) or 'x' not in v:
                continue
            if role.split(' ')[0] not in [r.split(' ')[0] for r in SHOW_ROLES]:
                continue
            # ГАБАРИТЫ — ИЗ ТОВАРА, ЕСЛИ РАСКЛАДКА ИХ НЕ ДАЛА (01.09). Солвер считает план и
            # высоту предмета не проставляет, а страница и рендер берут габарит отсюда. Из-за
            # этого высота ТЕРЯЛАСЬ по дороге и подменялась значением «по умолчанию для роли»:
            # торшер 172 см приезжал как 160, меш тянули под чужой паспорт и он выходил кривым
            # (перекос 2.77 при пороге 2.6). Товар знает свой размер — берём у него.
            _sk = _sku(items, role)
            if not _sk:
                missing_item.append({'role': role})
                continue
            _dims = _dims_of(v, _sk, role)
            if _dims.get('dims_unknown'):
                # размер не указан магазином — предмет в сцену не ставим и ничего не додумываем (Р1)
                dims_unknown.append({'role': role, 'name': (_sk or {}).get('name')})
                continue
            # признак подвесной тумбы кладём В САМ ТОВАР: рендер не должен разбирать название
            if _sk and _hung(_sk.get('name')):
                _sk = dict(_sk); _sk['hung'] = True
            objs.append({'role': role, 'x': round(v['x'], 1), 'y': round(v['z'], 1),
                         'rot': int(v.get('rot') or 0), 'w': _dims['w'], 'd': _dims['d'],
                         'h': _dims['h'], 'dims_src': _dims.get('dims_src'), 'sku': _sk,
                         # Г-диван: у него ДРУГИЕ пороги (столик может стоять вплотную внутри «Г»,
                         # ТВ ближе — 150 см), иначе советчик выдаёт ложные предупреждения на
                         # плане, который движок считает валидным (26.08)
                         'corner': bool(v.get('corner')),
                         'corner_left': bool(v.get('corner_left')),
                         'section': v.get('section') or v.get('corner_section_cm')})
        # СТИЛЬ ВАРИАНТА (владелец 26.08: «каждый вариант надо добавлять какой это стиль и в
        # промпт стиля добавляй»): берём стиль банка, из которого собран этот вариант.
        # ДЕКОР НА МЕБЕЛИ (владелец 01.09). Вазы и статуэтки в банке ЕСТЬ, но на план не
        # попадают: они стоят не на полу, а на тумбе или столе, и у раскладки для них нет места.
        # Из-за этого купленный товар не доезжал ни до кадра, ни до сметы. Выгружаем отдельным
        # списком — модель ставит их на горизонтальные поверхности по третьему изображению.
        # МЯГКОЕ — ТЕМ ЖЕ СПИСКОМ, НО БЕЗ МЕСТА В 3D (demo-24, владелец 23.10: «должны быть в списке, но появляться на 3D-модели
        # не должны, а отправляться в GPT должны; нет смысла из них меши делать»). Подушки, шторы, плед — в списке, сумме и
        # «Улучшить фото»; сцена и план их не рисуют (`soft_role` по роли, на странице — `rules.soft_roles`). Модели у них нет: `msid` пуст
        decor = []
        for role, _it in (items or {}).items():
            soft = soft_role(role)
            if (role.split(' ')[0] in DECOR_ROLES or soft) and _it and _it.get('name'):
                sk = _sku(items, role)
                if sk:
                    if soft:
                        sk['msid'] = None
                    decor.append({'role': role, 'sku': sk})
        variants.append({'id': f'set{n}', 'title': style, 'style': sets[n - 1].get('style'),
                         # ключ главной «стиль → комната → вариант» (demo-16): латинский id стиля для адреса `?style=`
                         # и комната квартиры, которую обставляет вариант (пока все варианты — гостиная)
                         'style_id': style_id(sets[n - 1].get('style')), 'room_id': living_room_id(),
                         'fill_pct': art.get('_fill_pct'), 'items': objs, 'decor': decor,
                         'dims_unknown': dims_unknown, 'missing_item': missing_item,
                         'fill': fill_journal.get(f'set{n}', [])})
    # ПОСЛЕДНИЙ РУБЕЖ ПЕРЕД ПУБЛИКАЦИЕЙ (conv-09, Codex 13.10): ядро проверяется в САМОМ варианте, а не в
    # банке — солвер мог не поставить торшер или ковёр. Неполный вариант не публикуем; ни одного полного —
    # останавливаем сборку целиком: пусть останется вчерашнее демо, а не пустая страница.
    import demo_fill as _DF
    full = []
    for v in variants:
        roles = {re.sub(r'\s+\d+$', '', i['role']) for i in v['items']}
        miss = [c for c in _DF.CORE if c not in roles]
        if miss:
            print(f'WARN:demo_style_dropped: вариант «{v.get("style")}» без {", ".join(miss)} в расстановке — не публикуем',
                  flush=True)
            incomplete.append({'style': v.get('style'), 'missing': miss})
        else:
            full.append(v)
    if not full:
        raise SystemExit('ни одного полного варианта демо — публикация остановлена, остаётся прежнее демо')
    variants = full
    # ЛЕНТЫ ТОВАРОВ ПО РОЛЯМ (владелец 26.08: «чтоб фотки можно было назначать»): для каждой роли
    # собираем живые SKU с фото; границы — конверт слота той же комнаты, чтобы примерка не
    # предлагала заведомо негодный габарит (диван 260 см в 14 м²).
    ENV = DEMO_ENV
    ENV_ALL, _ = feed_envs()
    feeds, seen = {}, set()
    for s in sets:
        if hidden(s):
            continue                # скрытый банком сет — не источник ленты замен (conv-14); `bench_pool` — тем же правилом
        for role, it in (s.get('items') or {}).items():
            base = feed_base(role)
            if not it:
                continue
            key = (base, it.get('mid'), it.get('eid'))
            if key in seen:
                continue
            row = set_feed_row(base, it, s.get('style'))
            if row is None:
                continue
            seen.add(key)
            feeds.setdefault(base, []).append(row)
    for k in feeds:
        feeds[k].sort(key=lambda x: x['price'] or 0)
    # ПУЛ ЗАМЕНЫ — ЛЮБАЯ МЕБЕЛЬ СВОЕГО СТИЛЯ, У КОТОРОЙ ЕСТЬ МЕШ (владелец 08.09: «сделай так,
    # чтоб мебель можно было любую выбирать из тех, что есть меши и соответствует стилю»;
    # «изначальный набор в сете рекомендуемой мебели остаётся» — поэтому товары сетов идут
    # первыми и никогда не срезаются капом). Временное ограничение владельца — «по 30 вариантов
    # товаров каждой подкатегории в каждом стиле»: его держит сам пул (`demo_swap_pool.py`),
    # здесь мы только приклеиваем результат к лентам и не пускаем дубли.
    for lst in feeds.values():
        for p in lst:
            p['styles'] = [p['style']] if p.get('style') else []
    have: dict = {(r, p.get('sid')): p for r, lst in feeds.items() for p in lst}
    def glue(rows, target: dict, have: dict) -> list:
        """Товары пула → в ленты `target` (без дублей, с проверками ленты) → [добавлено, мимо конверта]."""
        n = [0, 0]
        for p in rows:
            base = p['role']
            if base not in ENV_ALL:
                continue
            # ОДИН ТОВАР — ОДНА КАРТОЧКА, СТИЛЕЙ У НЕЁ МОЖЕТ БЫТЬ НЕСКОЛЬКО (08.09). Пул
            # перечисляет товар в каждом стиле, которому тот подходит; если складывать это в
            # ленту как разные строки — получаются дубли, а если брать только первый стиль —
            # товар пропадает из остальных (так из 1186 подходящих в ленту попадали 340).
            old = have.get((base, p['sid']))
            if old is not None:
                if p['style'] not in old['styles']:
                    old['styles'].append(p['style'])
                continue
            why = pool_feed_check(p)
            if why == 'off_env':
                n[1] += 1
            if why:
                continue
            mid, eid = p['sid'].split('_', 1)
            it = {'name': p['name'], 'w': p['w'], 'd': p['d'], 'h': p['h'], 'price': p['price'],
                  'img': p['img'], 'url': p['url'], 'shop': p.get('shop'),
                  'style': p['style'], 'styles': [p['style']],
                  'sid': p['sid'], 'msid': p['msid'], 'sub': p['sub'], 'src': 'pool',
                  'basis': _basis(mid, eid), 'hung': _hung(p['name']),
                  'pack': _pack_of(mid, eid, p['name'])}
            have[(base, p['sid'])] = it
            n[0] += 1
            target.setdefault(base, []).append(it)
        return n
    # ДЕКОР ВАРИАНТА ПОДМЕНЯЕТСЯ ИЗ ЛЕНТЫ СБОРКИ, А НЕ ИЗ ЛЕНТЫ ЗАМЕН (demo-18, ведущий 18.10): подмена ниже — часть состава
    # варианта, и состав не должен меняться от расширения ленты замен (ваза set16). Лента сборки — те же товары сетов
    # (своя копия: пул дописывает им стили) плюс прежний пул `pool_top`
    dec_feeds = {r: [dict(p, styles=list(p['styles'])) for p in lst] for r, lst in feeds.items()}
    added, off_env = 0, 0
    try:
        import demo_swap_pool
        added, off_env = glue(demo_swap_pool.pool(swap_ok, band=_slot_band(liv), ceiling_cm=demo_ceiling()), feeds, have)   # в группе сперва в полосе (demo-20 В)
        glue(demo_swap_pool.pool_top(), dec_feeds, {(r, p.get('sid')): p for r, lst in dec_feeds.items() for p in lst})
    except Exception as e:  # noqa: BLE001 — нет БД/пула: ленты остаются набором сетов
        print('пул замены не подключён:', e)
    # КОВРЫ — СВОЙ ЗАПРОС (модель ковру не нужна), тот же отбор и та же лента (demo-18 п.2); в дозаполнение и подмену декора не
    # идут — показываемые варианты не меняются; сбой — громко, ковры остаются из наборов
    try:
        import demo_swap_pool
        rugs = demo_swap_pool.rug_pool(swap_rug_ok, band=_slot_band(liv))
        n_rug = glue(rugs, feeds, have)
        print(f'ковры ленты замен: из пула {len(rugs)}, добавлено {n_rug[0]} (потолок длинной стороны {rug_ceiling():g} см)')
    except Exception as e:  # noqa: BLE001
        print(f'WARN:rug_pool: ковры пула в ленту не попали: {repr(e)[:160]}')
    print(f'пул замены добавил в ленты: {added} товаров (мимо конверта комнаты: {off_env}); '
          'всего по ролям: '
          + ', '.join(f'{k} {len(v)}' for k, v in sorted(feeds.items())))
    # ФОРМА ДИВАНА — У КАЖДОГО ТОВАРА ЛЕНТЫ (demo-18 п.1): форму места сцена берёт из расстановки, не из товара
    # (`fromDemo.ts`), и прямой диван на месте углового рисовался бы углом. Окно и /flat предлагают замену той же формы и
    # стороны; правило — то же, что у расстановщика (`sofa_shape.py`)
    import sofa_shape as _SS
    for p in feeds.get('диван', []):
        p.update(_SS.shape(p.get('name'), p.get('d')))
    # ДЕКОР, КОТОРЫЙ МОЖНО ПОСТАВИТЬ НА СТОЛ (владелец 08.09: «вазы расставлять на журнальный
    # столик или на стол по центру сверху»). Ваза встаёт в кадр только если магазин указал ВСЕ
    # три габарита и есть модель: высоту мы не придумываем (Р1), а без модели это серая коробка.
    # У ваз из банка высота часто пустая («Ваза-шар Неман 260 мм» — размер только в названии), и
    # такая ваза осталась бы строкой в списке. Меняем её на ближайшую по ширине вазу того же
    # стиля из ленты сборки (`dec_feeds`) — то же место в наборе, но её видно в комнате. Не нашлось замены — оставляем
    # как есть: пусть лучше товар будет только в списке, чем подставим чужой стиль.
    dec_fixed, dec_left = 0, 0
    # МЯГКОЕ БЕЗ РОЛИ В КАТАЛОГЕ (demo-24 правки, детская линия): меняем на мягкое той же роли из ленты сборки — стиль варианта
    # первым, затем не взятое в другой вариант (разнообразие, как `demo_fill.candidates`), затем ближе по цене, без повтора внутри
    # варианта; модели и габариты мягкому не нужны. Нечем — строку снимаем: игрушка в списке хуже, чем подушкой меньше.
    # МЁРТВОЕ ФОТО — ТА ЖЕ ЗАМЕНА: лента мягкого требует живого фото (`soft_feed_row`), а товар варианта приходил из банка без
    # проверки — «Линкс Ваби» с фото 404 стоял битой картинкой в списке и на третьем листе «Улучшить» (прогон 23.10)
    try:
        from img_alive import alive_now as _alive
    except Exception:  # noqa: BLE001
        _alive = lambda u: True  # noqa: E731
    soft_fixed, soft_dropped, soft_used = [], [], set()
    for v in variants:
        st = v.get('style') or ''
        keep = []
        for d in (v.get('decor') or []):
            sk = d.get('sku') or {}
            why = None
            if soft_role(d.get('role')):
                why = ('роль снята каталогом' if (sk.get('sid') or '').replace('_', ':', 1) in _SOFT_LOST
                       else None if _alive(sk.get('img')) else 'фото не открывается')
            if not why:
                keep.append(d)
                continue
            base = re.sub(r'\s+\d+$', '', d.get('role') or '')
            taken = {(x.get('sku') or {}).get('sid') for x in v.get('decor') or []}
            cand = [p for p in dec_feeds.get(base, []) if p.get('soft') and p.get('sid') not in taken]
            if not cand:
                soft_dropped.append((v.get('id'), d.get('role'), sk.get('name'), why))
                continue
            best = min(cand, key=lambda p: (not (st and (p.get('style') == st or st in (p.get('styles') or []))),
                                            p.get('sid') in soft_used, abs((p.get('price') or 0) - (sk.get('price') or 0))))
            soft_used.add(best.get('sid'))
            d['sku'] = {k: best.get(k) for k in ('name', 'price', 'price_at', 'img', 'url', 'shop', 'basis', 'sid', 'msid',
                                                 'pack', 'w', 'd', 'h')}
            soft_fixed.append((v.get('id'), d.get('role'), sk.get('name'), best.get('name'), why))
            keep.append(d)
        v['decor'] = keep
    for vid, role, old, new, why in soft_fixed:
        print(f'  мягкое {vid} {role}: «{old}» ({why}) → «{new}»', flush=True)
    for vid, role, old, why in soft_dropped:
        print(f'  мягкое {vid} {role}: «{old}» ({why}) — замены нет, строка снята', flush=True)
    for v in variants:
        for d in (v.get('decor') or []):
            sk = d.get('sku') or {}
            if soft_role(d.get('role')):
                continue          # мягкому место в 3D не нужно — показуемой вазой его не меняем
            if sk.get('w') and sk.get('d') and sk.get('h') and sk.get('msid') in _mesh_index():
                continue
            base = re.sub(r'\s+\d+$', '', d.get('role') or '')
            st = v.get('style') or ''
            cand = [p for p in dec_feeds.get(base, [])
                    if p.get('w') and p.get('d') and p.get('h')
                    and p.get('msid') in _mesh_index()
                    and (not st or p.get('style') == st or st in (p.get('styles') or []))]
            if not cand:
                dec_left += 1
                continue
            best = min(cand, key=lambda p: abs((p.get('w') or 0) - (sk.get('w') or 0)))
            d['sku'] = {k: best.get(k) for k in ('name', 'price', 'img', 'url', 'shop', 'basis',
                                                 'sid', 'msid', 'pack', 'w', 'd', 'h')}
            dec_fixed += 1
    print(f'декор: заменено на показуемое {dec_fixed}, осталось только в списке {dec_left}')
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
                           'h': it.get('h'), 'price': _price(it)[0], 'img': it.get('img'),
                           'url': it.get('url'), 'shop': it.get('shop')}
        if roles:
            product_sets.append({'id': f'kit{n}', 'title': f'Комплект {BANKS.index(n) + 1}',
                                 'roles': roles,
                                 'sum': sum((v.get('price') or 0) for v in roles.values())})
    # КОМНАТЫ КВАРТИРЫ — ОДНО МЕСТО, РЕЕСТР (T-20261022-04): чертёж плана, главная и карточка `/api/apartments` берут состав и
    # площади из `data/partners/*.json`; прежний список с площадями в заголовках `flat215.json` (вторая копия, разошлась со схемой
    # плана №180) снят. Сторожа — `apartment_area_check`
    apt = demo_apartment()
    apartment_area_check(apt, flat.get('plan_example') or {})
    plan = flat.get('plan_example') or {}
    return {'room': {'w': liv['w'], 'd': liv['d'], 'title': liv['title'],
                     'openings': liv['openings'], 'radiators': liv.get('radiators') or [],
                     # вид из окна — из карточки квартиры застройщика (demo-04 п.5); нет — страница и кадр берут вид по умолчанию
                     **({'window_view': demo_apartment()['windowView']} if demo_apartment().get('windowView') else {}),
                     # высота потолка квартиры (реестр) — 3D-комната и камера страницы (`room.height_cm ?? 270`)
                     **({'height_cm': demo_ceiling()} if demo_ceiling() else {})},
            'apartment_id': demo_apartment_id(), 'plan': plan,
            # ПОМЕЩЕНИЯ КВАРТИРЫ ИЗ РЕЕСТРА (demo-16): порядок плана и площади — `data/partners/*.json`; страница берёт их
            # карточкой `/api/apartments`, а это — запасной путь, пока карточка не пришла (`rooms` выше — схема плана целиком)
            'apartment_rooms': apt.get('rooms') or [],
            'variants': variants, 'sets': product_sets, 'sofa_feed': feed, 'feeds': feeds,
            # ПОЛОСА «ПОДХОДЯЩИХ ПО РАЗМЕРУ» ленты замен (решение владельца 22.10, demo-20 А4; частично отменяет ADR-0271): ширина
            # 0.8–1.1 идеала слота этой комнаты — одно правило со сборкой комплектов (`slot_rules.slot_band`); лента в данных
            # остаётся широкой (`DEMO_ENV`), страница фильтрует по полосе, пока включён чип «Подходящие по размеру»
            'rules': {**_rules(), 'slot_band_cm': _slot_band(liv), 'soft_roles': soft_roles()},
            'bedroom_catalog': bedroom_catalog(),
            # стили, где после дозаполнения нет ядра: вариант не публикуется, страница честно пишет почему
            'incomplete_styles': incomplete,
            # КВАРТИРА, ЖК, ЦЕНА И СЕРТИФИКАТ — В РЕЕСТРЕ ЗАСТРОЙЩИКОВ (`data/partners/*.json`,
            # план b2b-06): страница берёт их карточкой `/api/apartments/<apartment_id>`. Сумму
            # сертификата здесь не пишем — её считает сервер одной формулой для демо, 3D и отчёта.
            '_note': flat.get('_scale_note')}


def _hung(name: str | None) -> bool:
    """Подвесная (навесная) тумба? Размечаем ПО НАЗВАНИЮ ТОВАРА, а не по высоте.

    Владелец 02.09: «посмотри все тв-тумбы на замену и размети навесные». Соблазн был считать
    низкие тумбы подвесными, но проверка карточки показала обратный пример: «Флавир 140x27» при
    высоте 27 см — НАПОЛЬНАЯ, на ножках («Расположение: напольное» в характеристиках). Высота
    признаком не является; название — является.

    Зачем признак: у подвесной тумбы её «высота» — толщина корпуса, а не уровень верхней
    плоскости, и телевизор на неё не ставят, а вешают над ней (`draft_render.tv_spec`).
    """
    n = (name or '').lower()
    return any(k in n for k in ('подвесн', 'навесн', 'настенн'))


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
        # и декор с мягким (demo-24): фото магазина отдаёт 403 через раз (`imgng.gdeslon.ru`) — строка списка оставалась без картинки
        for it in v['items'] + (v.get('decor') or []):
            if (it.get('sku') or {}).get('img'):
                urls.add(it['sku']['img'])
    for lst in ((data.get('bedroom_catalog') or {}).get('roles') or {}).values():
        for p in lst:
            if p.get('img'):
                urls.add(p['img'])

    # КРУПНАЯ КОПИЯ ДЛЯ КАРТОЧКИ ТОВАРА (demo-26 Д, владелец 23.10): рядом с плиткой 400 px — `<id>-l.jpg` до 1200 px из того же
    # исходника (в выборке уже `coalesce(image_url_hd, image_url)` — HD магазина, где есть). Замер 23.10 на 25 товарах: исходники
    # 700–2560 px, копия 1200 px — в среднем 36 КБ (на ~850 фото ~30 МБ). Страница берёт её по имени и только при `_img_large`
    def grab(u: str):
        name = hashlib.md5(u.encode()).hexdigest()[:16] + '.jpg'
        dst = os.path.join(imgdir, name)
        big = dst[:-4] + '-l.jpg'
        if os.path.exists(dst) and os.path.exists(big):
            return u, 'img/' + name
        full = ('https:' + u) if u.startswith('//') else u
        # ТРИ ПОПЫТКИ (demo-24): фото Гдеслона отвечает 403 через раз на тот же адрес (замер 23.10: 2 из 3 подушек — 403,
        # повтор — 200); с одной попыткой строка оставалась с адресом магазина, а он в браузере тоже 403 через раз
        for k in range(3):
            try:
                req = urllib.request.Request(full, headers={'User-Agent': 'Mozilla/5.0',
                                                            'Referer': 'https://remont-lab.online/'})
                with urllib.request.urlopen(req, timeout=15) as f:
                    raw = f.read()
                im = Image.open(io.BytesIO(raw)).convert('RGB')
                large = im.copy()
                large.thumbnail((1200, 1200))
                large.save(big, 'JPEG', quality=82)
                if not os.path.exists(dst):             # плитка уже лежит — не переписываем (докачали только крупную)
                    im.thumbnail((400, 400))
                    im.save(dst, 'JPEG', quality=82)
                return u, 'img/' + name
            except Exception:
                if k < 2:
                    time.sleep(1.5)
        # крупная не скачалась, плитка есть — товар остаётся с плиткой (карточка покажет её)
        return u, ('img/' + name) if os.path.exists(dst) else None

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
        for x in v.get('decor') or []:              # не скачалось — остаётся адрес магазина: строка декора из списка не пропадает
            sk = x.get('sku') or {}
            if sk.get('img'):
                sk['img'] = got.get(sk['img']) or sk['img']
    bc = (data.get('bedroom_catalog') or {}).get('roles') or {}
    for role in list(bc):                       # спальня: товар без живого фото не показываем
        for p in bc[role]:
            fix(p)
        bc[role] = [p for p in bc[role] if p.get('img')]
    # ТОВАР БЕЗ ФОТО В ВЫБОРКЕ НЕ УЧАСТВУЕТ (владелец 26.08): выборку пересчитываем ПОСЛЕ
    # проверки картинок, иначе половина ленты — пустые карточки.
    dropped = capped = 0
    for role, lst in list((data.get('feeds') or {}).items()):
        live = [p for p in lst if p.get('img')]
        dropped += len(lst) - len(live)
        # КАП — ПО СТИЛЮ И ПОДКАТЕГОРИИ, А НЕ ОДНИМ ЧИСЛОМ НА РОЛЬ (08.09). Прежний `[:24]`
        # оставлял на всю роль 24 товара — после подключения пула это срезало пять стилей из
        # шести, и «выбрать любую мебель своего стиля» превращалось в «выбрать из чужих».
        # Товары рекомендованного сета не срезаются никогда (условие владельца).
        keep, per = [], {}
        for p in live:
            if p.get('src') != 'pool':
                keep.append(p)
                continue
            # товар живёт в нескольких стилях сразу — место считаем в каждом, и оставляем,
            # пока хоть в одном стиле квота не выбрана (иначе редкий стиль остался бы пустым)
            ks = [(st, p.get('sub')) for st in (p.get('styles') or [p.get('style')])]
            if ks and all(per.get(k, 0) >= 30 for k in ks):
                continue
            for k in ks:
                per[k] = per.get(k, 0) + 1
            keep.append(p)
        capped += len(live) - len(keep)
        data['feeds'][role] = keep
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
    print(f'из выборки убрано без фото: {dropped}; срезано капом 30/подкатегорию×стиль: {capped}; '
          'осталось по ролям: '
          + ', '.join(f"{k} {len(v)}" for k, v in sorted(data['feeds'].items())))
    data['_img_cached'] = {'ok': ok, 'total': len(urls), 'dropped_no_photo': dropped,
                           'capped': capped}
    large = sum(1 for v in got.values() if v and os.path.exists(os.path.join(OUT, v[:-4] + '-l.jpg')))
    print(f'крупных копий для карточки товара: {large} из {ok}')
    data['_img_large'] = large > 0                 # страница пробует `<id>-l.jpg` только при этом флаге (нет файла — остаётся плитка)
    return data


def annotate_yaw(data: dict) -> int:
    """Разворот фронта модели — в каждый предмет вариантов (`sku.yaw`), чтобы 3D по кнопке из демо
    (`lib/configurator/fromDemo.ts`) ставил модель так же, как 3D-сцена самого демо (`orient.json` прода) и базовая
    квартира (ручные поправки `data/flat3d/front-overrides.json` — сильнее). Раньше 3D по ссылке из демо брал 0 у всех
    (разбор Codex 14.10). Нет сети — разворотов нет, как раньше."""
    import urllib.request
    try:
        orient = json.load(urllib.request.urlopen('https://remont-lab.online/test/mesh-pilot10/orient.json', timeout=30))
    except Exception:  # noqa: BLE001
        orient = {}
    try:
        over = json.load(open(os.path.join(HERE, '..', '..', 'data', 'flat3d', 'front-overrides.json'),
                              encoding='utf-8')).get('overrides') or {}
    except Exception:  # noqa: BLE001
        over = {}
    n = 0
    # ЛЕНТЫ И ДЕКОР ТОЖЕ (demo-01, 14.10): живая сцена демо ставит модель заменённого предмета прямо из ленты —
    # без разворота у кандидата заменённый диван встал бы боком (в лентах 0 из 478 имели `yaw`).
    skus = [it.get('sku') or {} for v in data.get('variants') or [] for it in (v.get('items') or []) + (v.get('decor') or [])]
    skus += [f for lst in (data.get('feeds') or {}).values() for f in lst if isinstance(f, dict)]
    for sk in skus:
        m = sk.get('msid')
        if not m:
            continue
        y = (over.get(m) or {}).get('yawDeg', (orient.get(m) or {}).get('yaw'))
        if y is not None:
            sk['yaw'] = float(y)
            n += 1
    return n


def _tone(path: str):
    """Средний цвет товара по фото без белого фона — то же правило, что у кадра (`draft_render._photo_hex`), в долях 0..1."""
    try:
        import numpy as _np
        from PIL import Image as _Im
        a = _np.asarray(_Im.open(path).convert('RGB').resize((64, 64)), _np.float32)
        m = a.sum(axis=2) < 720
        if m.sum() < 40:
            return None
        return [float(a[..., i][m].mean()) / 255.0 for i in range(3)]
    except Exception:  # noqa: BLE001 — нет фото: подкраски нет, модель остаётся своего цвета
        return None


def annotate_tint(data: dict, out_dir: str = OUT) -> int:
    """ЦВЕТ ВАРИАНТА НА МОДЕЛИ СЕМЕЙСТВА (demo-02 приёмка 16.10 п.11б). У цветового варианта своей 3D-модели нет: он показывается
    моделью представителя (`msid`), и замена «Серый → Графит» не меняла сцену ни на пиксель. Подкраска = средний тон фото
    варианта / тон фото представителя, по каналу (`sku.tint`, множитель цвета материала — `lib/viewer3d/meshes.ts`); простая
    заливка до полной перекраски (demo-05 п.11). Нет фото представителя или разница < 6 % — без подкраски."""
    skus = [it.get('sku') or {} for v in data.get('variants') or [] for it in (v.get('items') or []) + (v.get('decor') or [])]
    skus += [f for lst in (data.get('feeds') or {}).values() for f in lst if isinstance(f, dict)]
    tone: dict = {}
    for sk in skus:
        sid, img = sk.get('sid'), sk.get('img')
        if sid and sid not in tone and img and not str(img).startswith('http'):
            tone[sid] = _tone(os.path.join(out_dir, img))
    n = 0
    for sk in skus:
        sk.pop('tint', None)
        sid, msid = sk.get('sid'), sk.get('msid')
        a, b = tone.get(sid), tone.get(msid)
        if not sid or not msid or sid == msid or not a or not b:
            continue
        t = [round(min(2.5, max(0.35, x / max(y, 0.02))), 3) for x, y in zip(a, b)]
        if max(abs(x - 1) for x in t) >= 0.06:
            sk['tint'] = t
            n += 1
    return n


def merge_aliases(prev: dict | None, variants: list) -> dict:
    """ИСТОРИЯ НОМЕРОВ ВАРИАНТОВ → СТИЛЬ (план demo-05 п.10). Номер варианта (`set2`) — номер набора в сборке, и после
    пересборки он может исчезнуть: 14.10 `/flat?demo=set2` из живой ссылки менеджера дал 404. Сборка помнит, какому стилю
    принадлежал каждый когда-либо опубликованный номер (прошлая история + прошлые варианты + текущие, текущие главнее);
    по устаревшей ссылке `/flat` и окно демо открывают текущий вариант того же стиля с пометкой. Чистая функция."""
    out: dict = {}
    for src in ((prev or {}).get('variant_aliases') or {}, {v.get('id'): v.get('style') for v in (prev or {}).get('variants') or []},
                {v.get('id'): v.get('style') for v in variants}):
        out.update({k: st for k, st in src.items() if k and st})
    return out


def main() -> None:
    if '--publish' in sys.argv and not _BP.same(OUT, _BP.DEMO_OUT_DEFAULT):
        # publish_demo.sh публикует ПАПКУ ВИТРИНЫ, а не OUT: сборка рядом (копия банка, проверка) на прод не едет
        raise SystemExit(f'--publish со сборкой в {OUT}: публикуется только папка витрины — копия банка идёт в /test/')
    os.makedirs(OUT, exist_ok=True)
    # ИСХОДНИК СТРАНИЦЫ ЖИВЁТ В РЕПО (26.08): до этого index.html лежал только в ~/scout-scenes и
    # не попадал в git — демо было невоспроизводимо и терялось при чистке
    import shutil
    src = os.path.join(HERE, 'flat215-demo', 'index.html')
    if os.path.exists(src):
        shutil.copy(src, os.path.join(OUT, 'index.html'))
    # ДВИЖОК ЖИВОЙ СЦЕНЫ (demo-01): тот же исходник, что /flat (`lib/viewer3d`), собирается рядом со страницей
    # (`lib/scene.<версия>.js` + `lib/scene.json`). Не собрался — остаётся вчерашний файл, страница работает с ним
    # или уходит на серверный эскиз; громко, а не молча.
    root = os.path.abspath(os.path.join(HERE, '..', '..'))
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/build-scene-bundle.mjs" '
                        f'--out "{os.path.join(OUT, "lib")}"'], capture_output=True, text=True, timeout=300)
    print((r.stdout or '').strip()[-300:] if r.returncode == 0 else
          f'WARN:scene_bundle: движок живой сцены не собрался (rc={r.returncode}): {(r.stderr or r.stdout or "").strip()[-200:]}')
    data = cache_images(build())
    print(f'разворот фронта в предметах вариантов: {annotate_yaw(data)}')
    print(f'подкраска цветовых вариантов семейства: {annotate_tint(data)}')
    # ВОРОТА АРТЕФАКТОВ (demo-05 п.1): наезд глубже 2 см или модель намного темнее товара — вариант не публикуется. Если
    # красных больше половины — это скорее поломка проверки, чем данных: публикуем всё, тревога громче
    try:
        import scene_checks as SC
        red = SC.check(data)
        for vid, why in red.items():
            print(f'WARN:scene_checks: {vid} — ' + '; '.join(why), flush=True)
        if red and len(red) * 2 <= len(data['variants']):
            for v in [v for v in data['variants'] if v.get('id') in red]:
                data['incomplete_styles'].append({'style': v.get('style'), 'missing': [], 'artifacts': red[v['id']]})
            data['variants'] = [v for v in data['variants'] if v.get('id') not in red]
        elif red:
            print(f'WARN:scene_checks_many: красных {len(red)} из {len(data["variants"])} — публикуем всё, проверьте сами ворота', flush=True)
        else:  # на зелёном ворота молчали — по журналу не доказать, что они вообще шли
            print(f'scene_checks: OK — вариантов {len(data["variants"])}, наездов > {SC.OVERLAP_CM:g} см и тёмных моделей нет',
                  flush=True)
    except Exception as e:  # noqa: BLE001 — сломанные ворота не валят сборку, но громко
        print(f'WARN:scene_checks_error: {repr(e)[:160]}', flush=True)
    # ОКНА И ДВЕРИ СЕРВЕРНОГО КАДРА — ИЗ ТОГО ЖЕ ОПИСАНИЯ, ЧТО В ЖИВОЙ СЦЕНЕ (demo-04): генератор один
    # (`lib/viewer3d/opening-ir.ts`), страница шлёт `room.openings_ir` с запросом кадра. Не посчиталось — кадр строит
    # проёмы прежним путём, громко.
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(data['room'], tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}"'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        data['room']['openings_ir'] = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        data['room']['openings_ir'] = None
    if not data['room']['openings_ir']:
        data['room'].pop('openings_ir', None)
        print(f'WARN:opening_ir: описание проёмов не посчиталось (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    else:
        print(f"проёмы кадра: {len(data['room']['openings_ir'])} из общего описания")
    # ПАСПОРТ ОТДЕЛКИ (demo-04): карточка квартиры (`finish`) поверх набора по умолчанию — готовым, им красят и страница, и кадр
    if demo_apartment().get('finish'):
        data['room']['finish'] = demo_apartment()['finish']
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(data['room'], tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}" --finish'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        data['room']['finish'] = json.loads(r.stdout) if r.returncode == 0 else data['room'].get('finish')
    except ValueError:
        print(f'WARN:finish: паспорт отделки не посчитался (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    # плинтус, карниз, светильник — тем же генератором (demo-04 п.6, `lib/viewer3d/fixtures-ir.ts`)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(data['room'], tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}" --fixtures'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        fx = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        fx = None
    if fx:
        data['room']['fixtures_ir'] = fx
    else:
        print(f'WARN:fixtures_ir: плинтус/карниз/светильник не посчитались (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    try:
        prev = json.load(open(os.path.join(OUT, 'demo-data.json'), encoding='utf-8'))
    except (OSError, ValueError):
        prev = None
    data['variant_aliases'] = merge_aliases(prev, data['variants'])
    # ЗАМЕР «МОДЕЛЬ СЕМЕЙСТВА ДРУГОГО ЦВЕТА» В ЛЕНТАХ (demo-05 п.2b) — пока только счёт в журнал, без отсева: отсев обнулил бы
    # ленты стульев и пуфов; лечение — перекраска модели под фото товара
    try:
        import mesh_dark as _MDK
        bad = {r: sum(1 for p in f if _MDK.family_colour_mismatch(p.get('sid'), p.get('msid'))) for r, f in data['feeds'].items()}
        bad = {r: n for r, n in bad.items() if n}
        if bad:
            print('WARN:feed_family_colour: в лентах модели семейства другого цвета — ' + ', '.join(f'{r} {n}' for r, n in sorted(bad.items())), flush=True)
    except Exception as e:  # noqa: BLE001 — замер не валит сборку
        print(f'  замер цвета семейств в лентах не удался: {repr(e)[:100]}', flush=True)
    json.dump(data, open(os.path.join(OUT, 'demo-data.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    # РАКУРСЫ ОКНА — В ДАННЫЕ (demo-05 п.8): тот же блок CAMFIT страницы считает пару ракурсов каждого варианта
    # (`tools/flat3d/demo-cams.mjs` → `v.cams`), ими снимает «Фото» в /flat. Не посчиталось — /flat покажет прежний вид
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/demo-cams.mjs" '
                        f'"{os.path.join(OUT, "demo-data.json")}"'], capture_output=True, text=True, timeout=300)
    print((r.stdout or '').strip()[-300:] if r.returncode == 0 else
          f'WARN:demo_cams: ракурсы окна в данные не записались (rc={r.returncode}): {(r.stderr or r.stdout or "").strip()[-200:]}')
    # ОТЧЁТ ЛЕНТ ЗАМЕН ПО СТИЛЮ И РОЛИ (demo-18 п.1): eligible_sku / unique_msid / published_alternatives — правилом моста /flat
    # (`tools/flat3d/swap-report.mjs` → `lib/configurator/demo-feeds.ts`); меньше 5 — строка с «!»
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON '
                        f'"{root}/tools/flat3d/swap-report.mjs" "{os.path.join(OUT, "demo-data.json")}"'],
                       capture_output=True, text=True, timeout=120)
    print((r.stdout or '').strip() if r.returncode == 0 else
          f'WARN:swap_report: отчёт лент не посчитался (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    print(f"OK: вариантов {len(data['variants'])}; ленты: "
          + ', '.join(f"{k} {len(v)}" for k, v in sorted(data['feeds'].items()))
          + f"; комплектов {len(data['sets'])}")
    if '--publish' in sys.argv:
        # ПУБЛИКУЕТ ОДИН СКРИПТ (08.09). Здесь раньше стояла своя копия команд, и она сносила
        # каталог целиком (`rm -rf /opt/remlab/demo && mv`) — а он примонтирован в контейнер
        # Caddy: новый каталог получает новый inode, и `/demo` начинает отдавать 404 до
        # пересоздания контейнера. `publish_demo.sh` обновляет содержимое НА МЕСТЕ (урок 430).
        subprocess.run([os.path.join(HERE, 'publish_demo.sh')], check=True)


if __name__ == '__main__':
    main()
