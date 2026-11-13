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
# ВХОДЫ СБОРКИ НА ХОДУ (T-20261112-121/2): какие файлы правил открыл этот процесс — до первого импорта (модули читают правила
# при загрузке); в конце — строка «прочитано K из N входов» и WARN за правило вне `build_stamp.DEMO_INPUTS` (метка его не видит)
if __name__ == '__main__':
    import build_stamp as _BSW  # noqa: E402
    _BSW.watch_rules()
import bank_paths as _BP  # noqa: E402
import atomic_io as _AIO  # noqa: E402 — выходные json сборки пишутся подменой, не обрезкой (T-20261105-59)
import room_bindings as _RB  # noqa: E402 — привязка, индекс прода и правило годности модели (одно с банком, T-20261106-70)
BANK = _BP.demo_plan(os.environ, OUT)
# ОДНА РАССТАНОВКА НА ВСЕ СТИЛИ (demo-31, `demo_one_layout.py`): включено — солвер берёт только гипотезы опорной подписи
# (`rules/demo-layout.json`), раскладки — со своим суффиксом `-one` (общие `v3set{n}-layout.json` пересчитывают другие прогоны)
import demo_one_layout as _ONE  # noqa: E402
ONE_LAYOUT = _ONE.enabled()
# ВАРИАНТЫ РАССТАНОВКИ и КОМПЛЕКТЫ ТОВАРОВ — РАЗНЫЕ СУЩНОСТИ (владелец 26.08):
# «шаблоны не называть стилями, а просто варианты; далее под любой из шаблонов показываем наши
# сеты; люди могут смешать разные товары из разных стилей». Поэтому: вариант = геометрия
# расстановки, комплект = набор товаров, который на неё накладывается; отдельный предмет можно
# заменить товаром из любого комплекта.
# СЕТЫ ДЛЯ ДЕМО ВЫБИРАЮТСЯ ПО СОСТАВУ, А НЕ ПО НОМЕРУ (26.08). Жёсткий список [1,4,7,…] сломался,
# как только контракт снял из банков позиции закрывшегося магазина: два сета остались без дивана,
# и движок честно вернул пустую комнату. Берём банки нужного метража с полным ядром (T-20261112-122:
# число предметов не награждается — лишний комод не обгоняет набор с полным ядром).
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
    без меша (серая коробка в кадре хуже, чем набор поскромнее). Замер 13.10: по этому правилу
    шести сценам не хватало 12 мешей против 26 у прежнего отбора «кто богаче». T-20261112-122:
    сперва полное обязательное ядро и его модели (`bank_invariants.selection_key`, общий с турами),
    число предметов больше не награждается.
    """
    import bank_invariants as BI
    idx = _mesh_index()
    order = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
    best: dict = {}
    for i, st in enumerate(sets, 1):
        if st.get('band') != band or 'диван' not in (st.get('items') or {}) or hidden(st):
            continue
        items = st.get('items') or {}
        nm = [r for r, it in items.items()
              if r.split(' ')[0] in PLACEABLE and it and it.get('mid') and _msid(f"{it['mid']}_{it['eid']}") not in idx]
        # T-20261112-122: ключ — общий с турами (`bank_invariants.selection_key`): ядро, его модели, прочие модели; число предметов
        # не награждается (лишний предмет не делает набор «лучше»)
        key = BI.selection_key(st, sum(1 for r in nm if r.split(' ')[0] in BI.CORE_ROLES), len(nm)) + (i,)
        style = st.get('style') or ''
        if style not in best or key < best[style][0]:
            best[style] = (key, i)
    picked = [best[s][1] for s in order if s in best]
    picked += [v[1] for k, v in sorted(best.items()) if k not in order]
    for style in order:
        if style in best:
            k = best[style][0]
            print(f'  вариант стиля «{style}»: набор {best[style][1]}, '
                  f'нет ядра {k[0]}, без меша {k[2]}', flush=True)
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
            # запасной нейтральный ковёр стиля без своих (`demo_swap_pool.universal_rugs`) — только когда он; иначе ключа нет
            **({'rug_universal': True} if it.get('rug_universal') else {}),
            # глубина «для сцены» у стульев К2 (`scene_dims`, T-25/9): d — по мешу, d_catalog — каталог для подписи
            **scene_dims(f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else None, _cat_dims(it))}


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
    if _MESH_IDX is None:     # чтение — общее с банком спальни (`room_bindings.prod_index`, T-20261106-70)
        _MESH_IDX = _RB.prod_index(lambda: _demo_msids(os.path.join(OUT, 'demo-data.json')))
    return _MESH_IDX


def _demo_msids(path: str) -> set:
    """Модели опубликованного демо (ленты и предметы вариантов) — запасная истина «на сервере», когда прод не ответил.
    Общее с банком спальни (`room_bindings.demo_msids`, T-20261106-70)."""
    return _RB.demo_msids(path)


_MESH_REP: dict | None = None


def _mesh_rep() -> dict:
    """Артикул товара → артикул его МОДЕЛИ (представителя семейства, ADR-0196).

    Один меш на модель: цветовые варианты своего меша не имеют и берут модель «родителя».
    Раньше демо искало GLB по артикулу самого товара — и рисовало серую коробку, хотя модель
    формы давно готова. Ключ каталога мешей отдаём отдельным полем `msid`, а `sid` остаётся
    артикулом самого товара (карточка, ссылка в магазин).
    """
    global _MESH_REP
    if _MESH_REP is None:     # общее с банком спальни (`room_bindings.mesh_rep`, T-20261106-70)
        _MESH_REP = _RB.mesh_rep()
    return _MESH_REP


_BIND_ROWS: dict | None = None


def _bind_rows() -> dict:
    """Строки привязки `offer_asset_binding` (артикул через `:` → строка), один раз на сборку. Не читается — {} и WARN: сцена
    берёт представителя семьи, как до T-20261106-77/5 (не серые коробки)."""
    global _BIND_ROWS
    if _BIND_ROWS is None:
        try:
            import catalog_items as CI
            rows, why = _RB.load_db(CI.fetch)
        except Exception as e:  # noqa: BLE001
            rows, why = {}, repr(e)[:160]
        if why:
            print(f'WARN:scene_msid: привязка не читается ({why}) — модели сцены по представителю семьи', flush=True)
        _BIND_ROWS = rows or {}
    return _BIND_ROWS


def _msid(sid: str | None) -> str | None:
    """Какую модель грузит сцена — ОДНО ПРАВИЛО ДЛЯ ВСЕХ КОМНАТ (`room_bindings.scene_msid`, T-20261106-77/5 шаг 3): модель
    привязки (`mesh_id` строки, ту, что проверила привязка); представитель семьи — только явной привязкой (`via_family`), иначе
    None — модели нет, штатная замена (T-20261107-25/5). Привязка не читается вовсе (WARN выше) — по-старому представитель
    семьи, чтобы сбой таблицы не снял модели со всей гостиной."""
    if not sid:
        return None
    rows = _bind_rows()
    if not rows:
        return _mesh_rep().get(sid, sid)
    return _RB.scene_msid(rows.get(sid.replace('_', ':', 1)), sid, _mesh_rep())


def scene_family_digest(data: dict, rows: dict) -> str:
    """Сторож правила B (T-20261107-25/5) по собранному демо: товаров, у которых сцена грузит ЧУЖУЮ модель (msid ≠ sid) без явной
    привязки к представителю (`via_family`), — должно быть 0. Не 0 — WARN (правило `scene_msid` обойдено); привязка не читается —
    тоже WARN (тогда сцена по-старому берёт представителя)."""
    if not rows:
        return 'WARN:scene_family: привязка не читается — модели сцены по представителю семьи без проверки'
    seen = {}
    for lst in (data.get('feeds') or {}).values():
        for p in lst:
            seen[p.get('sid')] = p.get('msid')
    for v in data.get('variants') or []:
        for i in v.get('items') or []:
            s = i.get('sku') or {}
            seen[s.get('sid')] = s.get('msid')
    bad = sorted(sid for sid, m in seen.items() if sid and m and m != sid
                 and not (rows.get(sid.replace('_', ':', 1)) or {}).get('via_family'))
    if bad:
        return f'WARN:scene_family: сцена грузит чужую модель без явной привязки у {len(bad)}: {", ".join(bad[:5])}'
    n = sum(1 for sid, m in seen.items() if sid and m and m != sid)
    return f'DIGEST:модели сцены: чужая модель без явной привязки 0 (представитель семьи явно — {n})'


def colour_flagged(sid: str | None) -> bool:
    """Сторож «меш не того цвета» (T-20261107-14/2): привязка варианта семьи отмечена `mesh_color_mismatch` — видимый цвет
    модели представителя (даже с подкраской) далеко от фото товара (оранжевый «Аронт» вместо серого). Такой товар не идёт ни в
    ленту замен, ни в вариант; правило и порог — `room_bindings.measured_colour`, замер — `mesh_color_check`."""
    return bool(sid) and _RB.colour_flagged(_bind_rows().get(sid.replace('_', ':', 1)))


_EFF_POL: dict | None = None


def scene_dims(sid: str | None, dims: dict) -> dict:
    """ГЛУБИНА «ДЛЯ СЦЕНЫ» (T-20261107-25/9, план dims-effective-01, Codex 07.11 п.5). У стульев К2 глубина каталога — копия
    ширины (ложный квадрат); привязка подтвердила глубину паспорта мешем (`passport.effective_dims`). Сцена — солвер, след,
    3D (`meshes.ts:placeMesh` тянет модель до w,d,h) и фото — берёт её; каталожная остаётся рядом в `d_catalog` (подпись
    товара покупателю), отбор и фильтры по-прежнему на каталоге. Условия — `room_bindings.effective_d`; откат — политика
    `passport.d_by_mesh.effective: false` или `FLAT215_EFFECTIVE_DIMS=0`. Нет основания — `dims` как есть (тот же объект)."""
    global _EFF_POL
    if not sid or not dims or os.environ.get('FLAT215_EFFECTIVE_DIMS', '1') == '0':
        return dims
    rows = _bind_rows()
    if not rows:
        return dims
    if _EFF_POL is None:
        try:
            _EFF_POL = _RB.policy()
        except Exception as e:  # noqa: BLE001 — политика не читается: сцена на каталоге
            print(f'WARN:scene_dims: политика привязки не читается ({repr(e)[:120]}) — глубина сцены из каталога', flush=True)
            _EFF_POL = {}
    d = _RB.effective_d(rows.get(sid.replace('_', ':', 1)), _msid(sid), dims.get('w'), dims.get('d'), _EFF_POL)
    if d is None:
        return dims
    return dict(dims, d=d, d_catalog=dims.get('d'), dims_by='паспорт по мешу')


def _scene_sets(sets: list) -> list:
    """Копия банка демо для солвера с глубиной «для сцены» (`scene_dims`); сам банк и `sets` в памяти не трогаем (Р1: банк =
    каталог, `catalog_media.sync_sets`)."""
    out = []
    for s in sets:
        items = (s or {}).get('items') if isinstance(s, dict) else None
        if not items:
            out.append(s)
            continue
        new = {}
        for role, it in items.items():
            if it and it.get('mid') and it.get('eid'):
                sd = scene_dims(f"{it['mid']}_{it['eid']}", it)
                if sd is not it:
                    it = {k: v for k, v in sd.items() if k not in ('d_catalog', 'dims_by')}
            new[role] = it
        out.append(dict(s, items=new))
    return out


DECOR_ROLES = {'ваза', 'статуэтка', 'свеча', 'книги', 'поднос', 'шкатулка', 'часы'}


def soft_roles() -> list:
    """Мягкое без места в 3D (demo-24): `asset_strategy.soft_roles` — стратегия `cutout` канона `rules/asset-strategies.json`
    (подушка, шторы, плед, покрывало), кроме настольного декора. Меш им не положен по канону; в варианте они идут строками
    списка и в запрос «Улучшить фото» (`improve_mode.soft_items`), а сцена и план их не рисуют."""
    import asset_strategy as _AS
    return sorted(_AS.soft_roles() - DECOR_ROLES)


def soft_role(role: str | None) -> bool:
    return feed_base(role or '') in soft_roles()


def decor_model(it: dict) -> tuple:
    """Годная модель декора паспорта (люстра, лампа): на сервере, цвета как на фото → (габариты меша, None) или (None, причина)."""
    sid = f"{it['mid']}_{it['eid']}"
    m = _msid(sid)
    if not m or m not in _mesh_index():
        return None, 'нет модели на сервере'
    if not color_ok(m, it.get('name') or '') or colour_flagged(sid):
        return None, 'модель не того цвета'
    ext = _mesh_extents(m)
    return (ext, None) if ext else (None, 'меш не читается')


def lamp_decor(sets: list, idx: int, tag: str, objs: list, room_wd: tuple) -> dict | None:
    """ЛАМПА НАБОРА НА КОМОДЕ → строка декора варианта (T-20261112-101; правила — `dependent_decor.py`): место — решатель паспорта
    (`light.lamp` на `light.dresser`), сцена пересчитывает его от текущего комода. Лампы в наборе нет или комода в варианте нет —
    строки нет (как было); лампа без модели или не влезает — следующая того же стиля; ни одной — громко, строки нет."""
    import dependent_decor as DD
    own = [it for r, it in ((sets[idx] or {}).get('items') or {}).items() if DD.is_lamp(r) and it]
    if not own or not DD.carrier_objs(objs, DD.LAMP_CARRIERS):
        return None
    it, pl, why = DD.lamp_pick(sets, idx, objs, room_wd, decor_model)
    if not it:
        print(f"WARN:lamp: {tag} — лампы на комоде нет ни в цене, ни в 3D: {'; '.join(why) or 'нет кандидатов'}", flush=True)
        return None
    sk = _sku({DD.LAMP_ROLE: it}, DD.LAMP_ROLE)
    row = DD.lamp_row(pl, objs, sk)
    swap = '' if it.get('eid') == own[0].get('eid') else f" (вместо «{own[0].get('name')}»: {'; '.join(why)})"
    print(f"  лампа {tag}: «{it.get('name')}» на {pl.parent_slot_instance_id}, низ {row['place']['bottom_cm']:g} см{swap}", flush=True)
    return row


def chandelier_decor(sets: list, idx: int, tag: str, objs: list, room_wd: tuple) -> dict | None:
    """ЛЮСТРА НАБОРА → строка декора варианта гостиной (T-20261112-66; правила — `chandelier.py`): товар с моделью на сервере,
    цветом как на фото, габарит сцены — по мешу (высота каталога у подвесных без шнура, сцена сплющила бы модель). МЕСТО —
    решатель паспорта (`dependents.resolve`, место `ceiling.chandelier`) на носителях этого варианта `objs` (ковёр, столик,
    диваны — `CH.carriers_from_variant`): в данных `place` {x, y, bottom_cm, slot_instance_id}, сцена рисует там и сама не
    считает. Корпус не влезает — следующая люстра стиля; нет ни одной или решатель отказал — строки нет вовсе."""
    import chandelier as CH
    own = [it for r, it in ((sets[idx] or {}).get('items') or {}).items() if CH.is_role(r) and it]
    ceil = float(demo_ceiling() or CH.DEFAULT_CEILING_CM)
    it, dims, pl, why = CH.pick(sets, idx, objs, room_wd, ceil, decor_model)
    if not own and not it:
        return None
    if not it:
        print(f"WARN:chandelier: {tag} — люстры нет ни в цене, ни в 3D: {'; '.join(why) or 'нет кандидатов'}", flush=True)
        return None
    sk = _sku({CH.ROLE: it}, CH.ROLE)
    # в карточке покупателю (бирка в 3D, строка списка) — каталог: Ш = Г = диаметр, В — корпус; Ш×Г×В сцены по мешу (подвес со
    # шнуром) — отдельно, `sku.hang` (`fromDemo.ts:isCeilingDecor`), иначе бирка показала бы «В 98 см» у корпуса 32 см
    dia = CH.diameter(it)
    sk.update(w=dia, d=dia, h=CH.body_h(it, dims), dia=dia, hang=dims)
    swap = '' if it is (own[0] if own else None) else f" (вместо «{(own[0] if own else {}).get('name')}»: {'; '.join(why)})"
    place = {'x': pl.x, 'y': pl.y, 'bottom_cm': pl.elev_cm, 'slot_instance_id': pl.slot_instance_id}
    print(f"  люстра {tag}: «{it.get('name')}» {dims['w']:g}×{dims['d']:g}×{dims['h']:g} см по мешу, место "
          f"{place['x']:g},{place['y']:g} над {pl.parent_slot_instance_id}, низ {place['bottom_cm']:g} см при потолке {ceil:g}"
          f"{swap}", flush=True)
    return {'role': CH.ROLE, 'strategy': CH.STRATEGY, 'place': place, 'sku': sk}


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
    src = sku.get('dims_by') or 'каталог'          # 'паспорт по мешу' — глубина сцены К2 (`scene_dims`, T-25/9)
    if sku.get('dia') and not (w and d):
        w, d, src = sku['dia'], sku['dia'], 'диаметр'
    import footprint as _fp
    known = _fp.footprint_known({'w': w, 'd': d})
    out = {'w': w, 'd': d, 'h': h, 'dims_src': src if known else 'неизвестно', 'dims_unknown': not known}
    if known and sku.get('dims_by') and sku.get('d_catalog') is not None:
        out['d_catalog'] = sku['d_catalog']        # подпись «Ш×Г×В» покупателю — каталог (`fromDemo.ts`)
    return out


BANKS: list = []          # заполняется в build(): выбранные банки демо


def solve_layouts(flat: dict, only: list | None = None) -> None:
    """РАСКЛАДКИ СЧИТАЕМ ПОД ЭТУ КОМНАТУ (26.08). Артефакт `v3set{n}-layout.json` по умолчанию
    считается для условного прямоугольника из метража сета (например 360×415) — если взять
    такой артефакт для комнаты 439×325, мебель окажется за стеной. Поэтому демо само вызывает
    солвер с реальными габаритами и проёмами квартиры, а не надеется на ранее посчитанный файл."""
    liv = flat['rooms'][0]
    sfx = BANK['layout_sfx'] + ('-one' if ONE_LAYOUT else '')
    env = dict(os.environ, SETS_SNAPSHOT=DEMO_SETS, **({'LAYOUT_SUFFIX': sfx} if sfx else {}),
               **({'LAYOUT_SIGNATURE_FILE': _ONE.RULES_PATH} if ONE_LAYOUT else {}),
               SCENE_OPENINGS=json.dumps([{k: v for k, v in o.items() if not k.startswith('_')}
                                          for o in liv['openings']], ensure_ascii=False),
               SCENE_RADIATORS=json.dumps([{k: v for k, v in r.items() if not k.startswith('_')}
                                           for r in (liv.get('radiators') or [])], ensure_ascii=False),
               # T-20261112-98/2: тип/название комнаты → сценарий решателя (кухня-гостиная — стол обязателен)
               SCENE_ROOM_KIND=str(liv.get('kind') or ''), SCENE_ROOM_TITLE=str(liv.get('title') or ''))
    py = os.path.expanduser('~/venvs/scout/bin/python')
    for n in (only if only is not None else BANKS):
        art = layout_path(n)
        fresh = (os.path.exists(art)
                 and (json.load(open(art, encoding='utf-8')).get('_room') or {}).get('w') == liv['w']
                 and os.path.getmtime(art) > os.path.getmtime(DEMO_SETS)
                 # подпись правила сменилась или расстановка не та — пересчитать
                 and (not ONE_LAYOUT or (os.path.getmtime(art) > os.path.getmtime(_ONE.RULES_PATH)
                                         and _ONE.signature(json.load(open(art, encoding='utf-8')))
                                         == _ONE.rules()['signature'])))
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
    Тот же рубеж у тура загруженного плана: банки гостиной и спальни (`trial_demo.build`, `trial_bedroom.default_ctx`, T-20261112-96).
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


def room_flags(apt: dict) -> dict:
    """ФЛАГИ НОВЫХ КОМНАТ И ОПРОСА (ADR-0330 п.5, onb-12): из реестра квартиры (`apartments[].rooms[].enabled`,
    `apartments[].quiz.enabled`, по умолчанию выключены) — в `demo-data.json` полями `rooms_enabled` (id включённых комнат в порядке
    плана) и `quiz_enabled`. Всё выключено — пусто: данные демо байт в байт прежние, страница читает «нет поля» как «выключено».
    Включается только настоящее `true` (не строка «true»: опечатку ловит схема `contracts/partner.ts` в тестах)."""
    rooms = [r['id'] for r in apt.get('rooms') or [] if r.get('enabled') is True]
    quiz = (apt.get('quiz') or {}).get('enabled') is True
    return {**({'rooms_enabled': rooms} if rooms else {}), **({'quiz_enabled': True} if quiz else {})}


ROOMS_ENV = 'FLAT215_ROOMS_ENABLED'


def rooms_on(apt: dict, env=None, out: str | None = None) -> dict:
    """Флаги комнат и опроса для этой сборки (onb-07 Т3): реестр (`room_flags`) + проверочное включение `FLAT215_ROOMS_ENABLED=
    bedroom-1,…` — ТОЛЬКО у сборки рядом (`FLAT215_DEMO_OUT`, /test/): главная демо включается реестром и приёмкой ведущего,
    переменной её не включить (отказ сборки). Комнаты — в порядке плана квартиры, неизвестный id — отказ (опечатка)."""
    env = os.environ if env is None else env
    flags = room_flags(apt)
    want = [x.strip() for x in str(env.get(ROOMS_ENV) or '').split(',') if x.strip()]
    if not want:
        return flags
    if _BP.same(out or OUT, _BP.DEMO_OUT_DEFAULT):
        raise SystemExit(f'{ROOMS_ENV} у сборки в папку витрины: главная демо включает комнату только реестром — сборка рядом '
                         f'(FLAT215_DEMO_OUT) для /test/')
    order = [r['id'] for r in apt.get('rooms') or []]
    bad = [x for x in want if x not in order]
    if bad:
        raise SystemExit(f'{ROOMS_ENV}: комнат {bad} нет в реестре квартиры')
    on = set(flags.get('rooms_enabled') or []) | set(want)
    return {**flags, 'rooms_enabled': [r for r in order if r in on]}


def living_room_id() -> str:
    """Комната, которую обставляют варианты витрины: первая гостиная квартиры из реестра; реестра нет — `living`."""
    return next((r['id'] for r in demo_apartment().get('rooms') or [] if r.get('kind') == 'living'), 'living')


# доли цветовых семейств стиля — функцией страницы (`quizStyleColours`, блок QUIZPICK): одна копия правила на страницу, опрос и сборку
QUIZ_COLOURS_NODE = r'''
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const m = src.match(/QUIZPICK START[^\n]*\n([\s\S]*?)\n[^\n]*QUIZPICK END/);
if (!m) { console.log('{}'); process.exit(0); }
const quizStyleColours = new Function(m[1] + '\nreturn quizStyleColours;')();
const inp = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = {};
for (const [s, v] of Object.entries(inp.variants)) out[s] = quizStyleColours(v, inp.pal);
console.log(JSON.stringify(out));
'''


def quiz_colours(variants: list, pal: dict | None, root: str) -> dict:
    """{стиль: доли цвета} — по варианту гостиной стиля (нет — первому его варианту), как опрос страницы. Нет палитры, node или
    блока QUIZPICK — пусто (карта замен тогда решает равенство порядком вкладок), строка WARN."""
    if not pal:
        return {}
    pick = {}
    for v in variants:
        s = v.get('style')
        if s and (s not in pick or ((v.get('room_id') or 'living') == living_room_id()
                                    and (pick[s].get('room_id') or 'living') != living_room_id())):
            pick[s] = v
    try:
        r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node -e "$0" "$1"', QUIZ_COLOURS_NODE,
                            os.path.join(HERE, 'flat215-demo', 'index.html')],
                           input=json.dumps({'pal': pal, 'variants': pick}, ensure_ascii=False), capture_output=True, text=True,
                           timeout=120)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip()[-160:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001 — без палитры карта всё равно строится
        print(f'WARN:style_fallback_colours: доли цвета стилей не посчитались ({repr(e)[:120]}) — равенство соседей решит порядок вкладок',
              flush=True)
        return {}


def room_style_fallback(data: dict, root: str) -> dict:
    """КАРТА ЗАМЕН КОМНАТ (план style-fallback-01, владелец 07.11 TG 309: «молчаливая подмена, вариант А»): `D.room_style_fallback` =
    {комната: {id стиля вкладки, которого в комнате нет: [id стилей комнаты по порядку замены]}} — правило `demo_room.style_fallback`.
    Страница (`drawHome`/`homeLayout`, окно «Выбрать другой» `mixApply`, ссылка `?style=&room=`) берёт первый стиль, чей вариант у неё есть, и рисует обычную
    карточку без пометки. Все комнаты со всеми стилями — пусто (поле не пишется: данные прежние байт в байт)."""
    import demo_room as R
    vs = [v for v in data.get('variants') or [] if not v.get('mine') and not v.get('cid') and v.get('style')]
    tabs = list(dict.fromkeys(v['style'] for v in vs))
    rooms = {}
    for v in vs:
        rooms.setdefault(v.get('room_id') or 'living', []).append(v['style'])
    if all(set(tabs) <= set(have) for have in rooms.values()):
        return {}
    fb = R.style_fallback(rooms, tabs, colours=quiz_colours(vs, (data.get('quiz') or {}).get('palettes'), root))
    out = {room: {style_id(w): [style_id(s) for s in order if style_id(s)] for w, order in m.items() if style_id(w)}
           for room, m in fb.items()}
    for room, m in out.items():
        print(f'карта замен: {room} — ' + ', '.join(f'{w} → {order[0]}' for w, order in m.items() if order), flush=True)
    return {room: m for room, m in out.items() if m}


def rooms_geo(living: dict, extra: dict | None = None) -> dict:
    """Геометрия комнат витрины `{room_id: комната}` (onb-07 основа). Гостиная — ТОТ ЖЕ объект, что `data['room']` (псевдоним
    для старых читателей: `demo-cams.mjs`, /flat, прогрев); `extra` — другие комнаты (спальни — onb-07 Т2), гостиную не подменяют."""
    out = {living_room_id(): living}
    for rid, geo in (extra or {}).items():
        if rid not in out and isinstance(geo, dict) and geo.get('w') and geo.get('d'):
            out[rid] = geo
    return out


def unique_rooms(data: dict) -> list:
    """Каждая геометрия комнаты витрины один раз (гостиная в `room` и `rooms_geo` — один объект): проёмы кадра, отделка и
    плинтусы считаются по всем комнатам, но по гостиной — один раз, как до onb-07."""
    out = []
    for geo in [data.get('room')] + list((data.get('rooms_geo') or {}).values()):
        if isinstance(geo, dict) and not any(geo is g for g in out):
            out.append(geo)
    return out


def rooms_check(data: dict) -> list:
    """Сторож «вариант → комната» (onb-07 основа): номер варианта один на всю витрину (ссылка `#v=` не знает комнаты), комната
    варианта есть в `rooms_geo`. Возвращает строки WARN; повтор номера — остановка сборки (ссылки открыли бы чужую комнату)."""
    ids = [v.get('id') for v in data.get('variants') or []]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise SystemExit(f'FAIL:rooms: номер варианта повторяется в разных комнатах — {", ".join(map(str, dup))}')
    geo = data.get('rooms_geo') or {}
    return [f'WARN:rooms: вариант {v.get("id")} — комнаты {v.get("room_id")} нет в rooms_geo, главная его не покажет'
            for v in data.get('variants') or [] if geo and (v.get('room_id') or 'living') not in geo]


DEMO_SETS = BANK['demo_sets']     # банк, по которому считается расстановка демо (`HERE/demo-sets.json`; у копии — в OUT)


def layout_path(n: int) -> str:
    """Раскладка набора `n` в комнате демо: `v3set{n}-layout.json`, у копии банка — со своим суффиксом, у одной
    расстановки на все стили — ещё `-one`."""
    return os.path.join(HERE, f"v3set{n}-layout{BANK['layout_sfx']}{'-one' if ONE_LAYOUT else ''}.json")
# Конверт слотов ЭТОЙ комнаты (гостиная 439×325): для ленты замен и для дозаполнения вариантов.
# Правило — `rules/demo-swap.json → room_fit_envelope_cm` (conv-03, ADR-0271): «что физически встаёт в комнату»,
# шире идеала слота сборки (`slot_rules`), иначе ленты сократились бы в разы.
_SWAP_RULES = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))
DEMO_ENV = {k: tuple(v) for k, v in _SWAP_RULES['room_fit_envelope_cm'].items() if not k.startswith('_')}


def fill_banks(sets: list, band: str = '14-16', per_style: int = 5) -> tuple[list, dict, list]:
    """Выбор набора стиля ПОСЛЕ дозаполнения (план conv-09 п.2/п.5) → (BANKS, журнал, неполные стили).

    На стиль берём `per_style` лучших по ключу ядра (`bank_invariants.selection_key`), каждый дозаполняем (`demo_fill.fill_set`) в
    копии и выбираем того, у кого полнее ядро и меньше без модели; число предметов не награждается (T-20261112-122). Банк на диске
    не трогаем — его лечит ночной конвейер."""
    import copy
    import bank_invariants as BI
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
                                                           _msid(f"{it.get('mid')}_{it.get('eid')}")) is None
                           and not colour_flagged(f"{it.get('mid')}_{it.get('eid')}"))
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
        # T-20261112-122: очередь наборов стиля — по ядру (`bank_invariants.selection_key`), не по числу предметов
        by_style.setdefault(st.get('style') or '', []).append(BI.selection_key(st) + (i,))
    if n_hidden:
        print(f'скрыты банком (bank_status hidden) — не варианты: {n_hidden} наборов полосы {band}', flush=True)
    order = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
    ranked: dict = {}
    taken: set = set()          # товары, уже подставленные в другие стили: разнообразие между вариантами
    for style in order + sorted(k for k in by_style if k not in order):
        cands = []

        def filled(i: int, own: bool, colour: bool = True) -> tuple:
            s = copy.deepcopy(sets[i - 1])
            j = DF.fill_set(s, pool, gate, _card, _media, has_mesh, DEMO_ENV, taken, own=own, colour_swap=colour)
            nook = drop_lonely_nook(s, benches)
            if nook:
                j.append(nook)
            items = s.get('items') or {}
            no_mesh = sum(1 for r, it in items.items() if DF.base_role(r) in PLACEABLE
                          and DF.base_role(r) not in NOMESH_ROLES and it and not has_mesh(it))
            # T-20261112-122: без награды за число предметов — лишний предмет набор «лучше» не делает (встанет ли — решает расстановка,
            # не встало обязательное — `choose_banks` берёт следующий)
            return ((len(DF.core_missing(s)), no_mesh, i, 0 if own else 1, 0 if colour else 1), i, s, j)
        for _k in sorted(by_style.get(style, []))[:per_style]:
            c = filled(_k[-1], True)
            cands.append(c)
            # ЗАМЕНА ПО ЦВЕТУ НЕ ВЫБИВАЕТ ВЕЩЬ ИЗ РАССТАНОВКИ (T-25/2): тот же набор без замен по цвету — сразу следом (ключ на
            # единицу хуже); `choose_banks` возьмёт его, если заменённая по цвету вещь не встала на пол
            if any(DF.is_colour_swap(x) for x in c[3]):
                cands.append(filled(_k[-1], True, False))
            # СВОЙ ЗАПАСНОЙ НЕ ДЕЛАЕТ ХУЖЕ ПРЕЖНЕГО (T-20261023-10): ворота он проходит, но расстановку может не дать (23.10
            # «современный»: свой столик 120×58 вытеснил торшер). Брали свой запасной — тот же набор с прежним дозаполнением
            # из пула идёт сразу следом (ключ на единицу хуже), и `choose_banks` попробует его раньше следующего набора
            if any(x.get('source') for x in c[3]):
                cands.append(filled(_k[-1], False))
        if cands:
            ranked[style] = sorted(cands, key=lambda c: c[0])
            # запасной нейтральный ковёр (`demo_swap_pool.universal_rugs`) — не «занят»: стиль на запасном не отнимает его у
            # стилей, для которых он свой (T-20261107-11/2: неоклассика взяла «Котри Серый» — джапанди сменил бы свой ковёр)
            taken |= {x['to_sku'] for x in ranked[style][0][3] if x.get('to_sku') and not x.get('rug_universal')}
    return ranked


def swap_ok(p: dict) -> bool:
    """Товар пула показуем в ленте замен — те же проверки, что лента применяет к товарам сетов: живое фото, модель семейства
    лежит на сервере (не карантин) и подходит товару по цвету, предмет годится для гостиной (`unfit.py`). Пул ленты зовёт её
    ДО отбора 30 в группе (`demo_swap_pool.pick`, demo-18 п.1); ширину комнаты пул проверяет сам по `rules/demo-swap.json`.
    Дозаполнение вариантов берёт прежний пул (`pool_top`): показываемые варианты в этой задаче не меняются.
    МОДЕЛЬ — ПРАВИЛОМ ПРИВЯЗКИ (`_msid`, T-20261107-25/5): запрос пула даёт представителя семьи (`mesh_family_rep`) — по нему пул
    только группирует «одна модель в группе»; проверяем ту модель, которую сцена реально загрузит (своя или явная семья)."""
    from img_alive import alive_now
    from unfit import unfit
    m = _msid(p.get('sid')) if p.get('sid') else p.get('msid')
    return (bool(m) and m in _mesh_index() and not unfit(p.get('role'), p.get('name'), None, p.get('h'), d=p.get('d'))
            and color_ok(m, p.get('name')) and alive_now(p.get('img')))


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
    if base not in NOMESH_ROLES and (not _msd or _msd not in _mesh_index() or not color_ok(_msd, it.get('name'))
                                     or colour_flagged(_sid)):
        return None          # нет модели или модель семейства другого цвета (demo-05: бежевый товар — чёрный меш; замер T-14)
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
    # глубина «для сцены» (`scene_dims`, T-25/9): отбор выше — по каталогу, место и модель в сцене — по мешу
    _sd = scene_dims(_sid, {'w': _w, 'd': _d}) if base != 'ковёр' else {}
    _dc = {'d_catalog': _d} if _sd.get('dims_by') else {}
    _d = _sd.get('d', _d) if _dc else _d
    return {'name': it.get('name'), 'w': _w, 'd': _d, **_dc, 'h': _h,
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


def soft_pool_ok(p: dict) -> bool:
    """Мягкое из каталога (`demo_swap_pool.soft_pool`) годно в ленту стиля: живое фото и цвет не яркий-чужой
    (`demo_fill.color_refused`, тот же отсев, что у замены мягкого)."""
    import demo_fill as _DF
    if _DF.color_refused(p.get('role') or '', p, p.get('style')):
        return False
    try:
        from img_alive import alive_now as _alive
        return bool(_alive(p.get('img')))
    except Exception:  # noqa: BLE001
        return True


def wall_art_step(data: dict) -> None:
    """КАРТИНЫ НАД МЕБЕЛЬЮ (viz-decor-01 шаг 3, T-20261112-26): товары каталога роли «картина» стиля варианта — в декор гостиной
    и спальни и в ленты замен (`wall_art.annotate`); место в 3D считает сцена от текущей опоры (`lib/configurator/wall-art.ts`).
    Строки — формой ленты мягкого (`glue_soft`: цена с датой, основание наличия). Сбой — громко, витрина без картин."""
    try:
        import demo_swap_pool
        import wall_art as WA
        r = WA.rules()
        if not WA.enabled(r):
            print('картины: выключены (wall-art.json enabled=false или DEMO_WALL_ART=0)')
            return
        pool: dict = {}
        glue_soft(demo_swap_pool.soft_pool(r['role'], soft_pool_ok), pool, {})
        got = WA.annotate(data, pool.get(r['role'], []), r, demo_ceiling())
        print(f"картины: пул {len(pool.get(r['role'], []))}, повешены в {sum(1 for g in got if g[2])} из {len(got)} вариантов с опорой")
        for vid, sup, names in got:
            print(f"  картины {vid} над «{sup}»: " + ('; '.join(names) if names else 'нет товара по размеру и стилю'))
    except Exception as e:  # noqa: BLE001
        print(f'WARN:wall_art: картины в витрину не попали: {repr(e)[:160]}')


def glue_soft(rows: list, target: dict, have: dict) -> int:
    """Мягкое пула → в ленты `target` строкой мягкого (как `soft_feed_row`: без меша и конверта); товар уже в ленте — только
    стиль ему дописываем. → сколько добавлено."""
    n = 0
    for p in rows:
        base = p['role']
        old = have.get((base, p['sid']))
        if old is not None:
            if p['style'] not in old.setdefault('styles', [old['style']] if old.get('style') else []):
                old['styles'].append(p['style'])
            continue
        mid, eid = p['sid'].split('_', 1)
        it = {'mid': mid, 'eid': eid, 'price': p['price']}
        row = {'name': p['name'], 'w': p['w'] or None, 'd': p['d'] or None, 'h': p['h'] or None,
               'price': _price(it)[0], 'price_at': _price(it)[1], 'img': p['img'], 'url': p['url'], 'shop': p.get('shop'),
               'style': p['style'], 'styles': [p['style']], 'sid': p['sid'], 'msid': None, 'sub': base, 'src': 'pool',
               'soft': True, 'basis': _basis(mid, eid), 'pack': _pack_of(mid, eid, p['name'])}
        have[(base, p['sid'])] = row
        target.setdefault(base, []).append(row)
        n += 1
    return n


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
    if base not in NOMESH_ROLES and colour_flagged(p.get('sid')):
        return 'mesh_colour'  # видимый цвет модели семьи далеко от фото товара (сторож T-20261107-14) — кандидат на свой меш
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
                _AIO.write_json(path, cache)
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
    atexit.register(lambda: dirty[0] and _AIO.write_json(path, cache))
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


ONE_INFO: dict = {}     # подпись и ось одной расстановки — в данные (`one_layout`), если ворота прошли


def one_layout(arts: dict) -> dict:
    """Ворота и выравнивание одной расстановки (demo-31): подпись каждого варианта = опорной, затем центры дивана/столика/
    ТВ/ковра — на общую ось (`demo_one_layout.align`). Не сошлось — варианты как были, громко `WARN:one_layout` (сборка не
    падает: показать разные расстановки лучше, чем пустую страницу)."""
    ref = _ONE.rules()['signature']
    off = {f'set{n}': _ONE.signature(a) for n, a in arts.items() if _ONE.signature(a) != ref}
    if off:
        print(f'WARN:one_layout: подпись не {ref}: {off} — выравнивание не делаю', flush=True)
        return arts
    out, rep = _ONE.align(arts)
    if not rep['ok']:
        print(f'WARN:one_layout: ось не нашлась без новых жёстких нарушений: {json.dumps(rep, ensure_ascii=False)}', flush=True)
        return arts
    ONE_INFO.update(signature=ref, axis={rep['dim']: rep['axis']}, max_shift_cm=rep['max_shift_cm'])
    print(f"one_layout: OK — вариантов {len(arts)}, подпись {ref}, ось {rep['dim']}={rep['axis']}, "
          f"наибольший сдвиг {rep['max_shift_cm']} см", flush=True)
    return out


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
            # замена по цвету не должна выбить вещь из расстановки (T-25/2: «Амберсон» 118 см не встал на место стеллажа 75 см
            # под окном — стеллаж пропал): следом в списке тот же набор без замен по цвету (`fill_banks`)
            cs = sorted({DF.base_role(x['role']) for x in j if DF.is_colour_swap(x)})
            if cs and not layout_ok(i, tuple(cs)):
                print(f'  стиль «{style}»: набор {i} — замена по цвету ({", ".join(cs)}) не встала в расстановку — '
                      f'беру набор без неё', flush=True)
                sets[i - 1] = orig
                why = why or {'style': style, 'missing': ['замена по цвету не встала в расстановку']}
                continue
            print(f'  вариант стиля «{style}»: набор {i}, ядро полное, без модели {key[1]}, '
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
    """Банк для солвера; переписываем только при изменении — раскладки не пересчитываются зря. Глубина — «для сцены»
    (`_scene_sets`, T-25/9): солвер ставит стул К2 по глубине меша, а не по квадрату каталога."""
    blob = json.dumps(_scene_sets(sets), ensure_ascii=False)
    if not os.path.exists(DEMO_SETS) or open(DEMO_SETS, encoding='utf-8').read() != blob:
        _AIO.write_text(DEMO_SETS, blob)


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
        _AIO.write_json(os.path.join(OUT, 'demo-fill-report.json'), rep, ensure_ascii=False, indent=1)
    return rep


def showcase(room_type: str):
    """Адаптер витрины типа комнаты — модуль шага `demo` реестра возможностей (`room_profile.CAPABILITIES`: `demo_bedroom`,
    `demo_hall`); у него `SPEC` (ядро `demo_room.Showcase`), `GEO_FILE`, `BANK_LIVE`, подписи и `GATE_OFF_MAIN`. Шага нет — None."""
    import importlib
    import room_profile as RP
    m = RP.capability(room_type, 'demo')
    return importlib.import_module(m) if m else None


def room_env(room_type: str, what: str) -> str:
    """Имя переключателя сборки комнаты: `BEDROOM_SETS`, `HALL_MESH_GATE`, … (тип комнаты заглавными + что)."""
    return f'{room_type.upper()}_{what}'


def catalog_key(room_type: str) -> str:
    """Ключ фото-каталога комнаты в `demo-data.json`: `bedroom_catalog`, `hall_catalog` (страница — блок ROOMCAT)."""
    return f'{room_type}_catalog'


def room_catalogs(data: dict) -> list:
    """Фото-каталоги комнат в данных витрины (`<тип>_catalog` типов с шагом demo реестра), что есть."""
    import room_profile as RP
    return [data[k] for k in map(catalog_key, RP.rooms_with('demo')) if isinstance(data.get(k), dict)]


def bedroom_catalog() -> dict:
    """Фото-каталог спальни для вкладки «Спальня 1» (план b2b-10 этап 2, v1; ADR-0279) из `room_catalog` — `room_photo_catalog`."""
    return room_photo_catalog('bedroom')


def room_photo_catalog(room_type: str) -> dict:
    """Фото-каталог комнаты (спальня — b2b-10 этап 2, ADR-0279; прихожая — hall-demo-01 этап 4) из `room_catalog`.

    Выборка на роль — по одной модели из семейства (без десяти цветов одной кровати) и ровно по цене: от дешёвых
    к дорогим через равные шаги, чтобы видно было весь диапазон (сколько на роль — `CATALOG_SHOW` адаптера). Показываем только с
    ценой, фото и из свежего фида (`shown_where` модуля каталога комнаты, `catalog_items._rc`). Кровати — с честным габаритом
    впереди. Нет таблицы/базы — пусто, вкладка «скоро»."""
    A = showcase(room_type)
    try:
        import catalog_items as CI
        import room_catalog as RC
        from mesh_queue import db as _db
        M = CI._rc(room_type)
        R = M.rules()
        rows = _db("select role, shop_mid||':'||external_id, name, shop, url, coalesce(image_url_hd, image_url), price_rub, "
                   "w_cm, d_cm, h_cm, sleep_w_cm, sleep_l_cm, coalesce(footprint_ok,false), "
                   "to_char(max(last_seen) over (), 'YYYY-MM-DD') from room_catalog where " + M.shown_where(R) +
                   # только включённые роли (флаг `roles_enabled`, onb-04 / ADR-0330): новые роли лежат в таблице,
                   # но демо их не берёт, пока ведущий не включит — выключено → данные байт в байт прежние
                   ' and ' + RC.enabled_sql(R) + RC.kids_where(R))
        # детские шкаф/комод/тумба лежат в общих ролях с назначением только child:* — спальне пары они не нужны
        # (по названию здесь, по детской категории — «and not kids» выше, когда столбец есть: kids_store после 015)
        rows = [r for r in rows if not RC.child_only(r[0], r[2], R)]
    except Exception as e:  # noqa: BLE001 — каталога комнаты нет: вкладка остаётся «скоро»
        print(f'каталог {A.TITLE_OF}: недоступен ({str(e)[:80]})')
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
        k = A.CATALOG_SHOW.get(role, 8)
        pick = reps if len(reps) <= k else [reps[round(i * (len(reps) - 1) / (k - 1))] for i in range(k)]
        out[role] = pick
    print(f'каталог {A.TITLE_OF}: ' + ', '.join(f'{r} {len(v)} (моделей {len(by[r])})' for r, v in out.items()))
    return {'roles': out, 'updated': updated}


BEDROOM_SETS_ENV = room_env('bedroom', 'SETS')
FEED_ANY_MESH_ENV = 'FLAT215_FEED_ANY_MESH'


def bedroom_bank_path(env, out: str) -> str:
    return room_bank_path('bedroom', env, out)


def room_bank_path(room_type: str, env, out: str) -> str:
    """Банк комнаты для сборки (T-20261105-32/2): `<ТИП>_SETS` (`BEDROOM_SETS`, `HALL_SETS`) → живой `sets-<тип>.json`, если
    есть → у сборки рядом — кандидат сборщика `sets-<тип>.next.json` (`bank_paths.room_bank_output`), чтобы не задавать путь руками.
    Витрина без живого банка — живой путь (пусто → комната «скоро»): кандидат в публикуемую папку не идёт, подмена — onb-12."""
    A = showcase(room_type)
    if env.get(room_env(room_type, 'SETS')):
        return env[room_env(room_type, 'SETS')]
    if os.path.exists(A.BANK_LIVE) or _BP.same(out, _BP.DEMO_OUT_DEFAULT):
        return A.BANK_LIVE
    return _BP.room_bank_output({}, room_type)


def bedroom_one_layout(recs: list, styles: list) -> dict:
    return room_one_layout('bedroom', recs, styles)


def room_one_layout(room_type: str, recs: list, styles: list) -> dict:
    """Одна расстановка комнаты на все стили (T-20261105-32/4, `demo_room.one_layout`): по комнате — готовые расстановки банка
    выравниваются по опорному стилю → {(комната, стиль): расстановка}. Правило выключено (`rules/demo-layout.json` → тип комнаты;
    у прихожей записи нет) или у записи нет готовой расстановки — пусто (вариант берёт свою расстановку банка, как раньше). Что
    переставилось и что не встало — в журнал сборки."""
    import demo_room as R
    spec = showcase(room_type).SPEC
    if not R.one_rule(spec).get('enabled'):
        return {}
    out: dict = {}
    for rid in dict.fromkeys(r['room_id'] for r in recs):
        rs = [r for r in recs if r['room_id'] == rid and isinstance((r.get('layout') or {}).get('_room'), dict)]
        arts, rep = R.one_layout(spec, {r['style']: r['layout'] for r in rs}, styles, {r['style']: r.get('purpose') for r in rs})
        out.update({(rid, s): a for s, a in arts.items()})
        mv = '; '.join(f"{m['style']} «{m['role']}» {m['from'][3]}→{m['to'][3]} ({m['to'][0]}, {m['to'][1]}, {m['to'][2]}°)"
                       for m in rep['moved']) or 'ничего'
        print(f"{room_type}_one_layout: {rid} — опорный стиль «{rep['ref']}», переставлено: {mv}", flush=True)
        for k in rep['kept']:
            print(f"WARN:{room_type}_one_layout: {rid} {k['style']} «{k['role']}» не встаёт на место опорного "
                  f"({', '.join(k['why']) if isinstance(k['why'], list) else k['why']}) — своя позиция банка", flush=True)
    return out


BEDROOM_MESH_GATE_ENV = room_env('bedroom', 'MESH_GATE')   # orient (по умолчанию) | strict | 0 — сторож модели (T-20261105-51)
BEDROOM_MESH_GATE_MODES = _RB.MESH_GATE_MODES + ('0',)
orient_only = _RB.orient_only        # правило одно с банком спальни (`room_bindings`, T-20261106-70)


def bedroom_mesh_gate(rows=None, why: str = '', mode: str | None = None):
    return room_mesh_gate('bedroom', rows, why, mode)


def room_mesh_gate(room_type: str, rows=None, why: str = '', mode: str | None = None):
    """Сторож модели предмета варианта комнаты (`demo_room.gate_items`): sku → '' (годен) или причина. Основа — та же
    проверка, что у выдачи каталога (`catalog_items.bound_asset` поверх `room_bindings.load_db`). Режимы (`<ТИП>_MESH_GATE`:
    `BEDROOM_MESH_GATE`, `HALL_MESH_GATE`):
      strict — привязка `ready` и модель выложена привязкой (`published`);
      orient (по умолчанию, решение ведущего T-51/3) — `ready` ИЛИ `blocked` только по развороту (`orientation_*`): брака у
               модели нет, не решён лишь фронт; такой предмет годен, а `note(sku)` даёт причину — сборка пишет его строкой
               `WARN:<тип>_orient_unresolved` и счётчиком (видно, что не решено, когда комнату включат на главной);
      0 — выключен (откат спальни; у прихожей — только сборка рядом, `GATE_OFF_MAIN` адаптера: у папки витрины отказ).
    В обоих режимах: сцена грузит именно модель привязки (`msid` = `mesh_id` — иначе в кадре меш представителя, которого
    привязка не проверяла) и она в индексе прода (`_mesh_index`, без карантина) — иначе серая коробка.
    Привязка не читается — все предметы «unbound» с причиной (вариант честно пустеет, а не показывает заглушки).
    Само правило — `room_bindings.usable` (одно с готовностью банка спальни `room_ready`, T-20261106-70); здесь — режим 0,
    чтение привязки и индекса прода."""
    A = showcase(room_type)
    env = room_env(room_type, 'MESH_GATE')
    mode = mode or os.environ.get(env) or 'orient'
    if mode not in BEDROOM_MESH_GATE_MODES:
        raise SystemExit(f'{env}={mode!r}? можно {", ".join(BEDROOM_MESH_GATE_MODES)}')
    if mode == '0':
        if not A.GATE_OFF_MAIN and _BP.same(OUT, _BP.DEMO_OUT_DEFAULT):
            raise SystemExit(f'{env}=0 у сборки в папку витрины — только сборка рядом (FLAT215_DEMO_OUT): на главной предмета '
                             f'без модели не бывает')
        print(f'WARN:{room_type}_mesh_gate: выключен ({env}=0) — предметы {A.TITLE_OF} без проверки модели', flush=True)
        return None
    import catalog_items as CI
    if rows is None:
        rows, why = _RB.load_db(CI.fetch)
        if why:
            print(f'WARN:{room_type}_mesh_gate: привязка не читается ({why}) — у предметов {A.TITLE_OF} моделей нет', flush=True)
    idx = _mesh_index()

    def bound(s: dict) -> dict:
        return CI.bound_asset({}, (rows or {}).get(str(s.get('sid') or '').replace('_', ':', 1)), why)

    def ok(s: dict) -> str:
        return _RB.usable(bound(s), s.get('msid'), idx, mode)[0] if s.get('sid') else 'нет артикула'
    ok.note = lambda s: _RB.orient_note(bound(s), mode)
    ok.mode = mode
    # МОДЕЛЬ СЦЕНЫ СПАЛЬНИ = МОДЕЛЬ ПРИВЯЗКИ (T-20261106-77/4, вариант А): `msid` предметов и ленты спальни — `mesh_id` той же
    # строки привязки, которую проверяет сторож; представитель семьи — только если записи нет (`room_bindings.scene_msid`)
    ok.msid = lambda sid: _RB.scene_msid((rows or {}).get(str(sid).replace('_', ':', 1)), sid, _mesh_rep()) if sid else None
    return ok


def room_showcases(apt: dict, flags: dict, variants: list, feeds: dict, incomplete: list, room: dict) -> tuple[dict, dict, dict]:
    """ВИТРИНЫ КОМНАТ — ПО РЕЕСТРУ (`room_profile.CAPABILITIES`, шаг demo; hall-demo-01 этап 4): тип за типом в порядке реестра
    (спальни, потом прихожая) → (геометрии `rooms_geo`, полосы `slot_band_cm`, фото-каталоги `{<тип>_catalog: …}`). Каталог типа —
    всегда у типа с `CATALOG_ALWAYS` адаптера (спальня — данные b2b-10, как было), у остальных — только когда комната типа
    включена: выключено — ни ключа, ни варианта, данные витрины прежние (`tests/test_demo_room_build.py`)."""
    import room_profile as RP
    extra_geo, rules_extra, cats = {}, {}, {}
    for rt in RP.rooms_with('demo'):
        A = showcase(rt)
        try:
            on = RP.enabled_rooms('demo', flags.get('rooms_enabled') or [], apt.get('rooms') or [], RP.capability(rt, 'demo'))
        except ValueError as e:
            raise SystemExit(f'витрина: {e}') from None
        if not (on or A.CATALOG_ALWAYS):
            continue
        cats[catalog_key(rt)] = room_photo_catalog(rt)
        g, b = room_variants(rt, apt, flags, variants, feeds, incomplete, room, cats[catalog_key(rt)])
        extra_geo.update(g)
        rules_extra.update(b)
    return extra_geo, rules_extra, cats


def bedroom_variants(apt: dict, flags: dict, variants: list, feeds: dict, incomplete: list, room: dict,
                     bcat: dict) -> tuple[dict, dict]:
    return room_variants('bedroom', apt, flags, variants, feeds, incomplete, room, bcat)


def room_variants(room_type: str, apt: dict, flags: dict, variants: list, feeds: dict, incomplete: list, room: dict,
                  cat: dict) -> tuple[dict, dict]:
    """КОМНАТЫ ТИПА В ВИТРИНЕ (спальни — onb-07 Т2; прихожая — hall-demo-01 этап 4): варианты включённых комнат типа из банка
    (адаптер `showcase(тип)` поверх ядра `demo_room`) — в конец `variants`, ленты ролей — в `feeds` под ключом «<тип>:<роль>»,
    неполные — в `incomplete`; → (геометрии для `rooms_geo`, полосы размера для `rules.slot_band_cm` под ключом «<комната>:<роль>»;
    ключи — `demo_room.room_key`).
    Ни одна комната типа не включена — ничего не трогаем (данные гостиной байт в байт прежние). Банк — `room_bank_path`
    (живой `sets-<тип>.json`; у сборки рядом — `<ТИП>_SETS` или кандидат `.next`); там же `FLAT215_FEED_ANY_MESH=1` пускает в ленту
    товары без модели (проверка ленты, пока меши не выложены, onb-10) — у папки витрины это отказ.
    Сторож выключен (`<ТИП>_MESH_GATE=0`) или лента без проверки — предмет варианта и строка ленты без годной модели несут метку
    `no_mesh` (причина того же сторожа, режим orient): следующий шаг (спрос мешей) её видит, а не теряет (ведущий 07.11, T-05/1)."""
    import demo_room as R
    import room_profile as RP
    A = showcase(room_type)
    # комнаты, чья витрина — адаптер типа: по реестру возможностей (`room_profile.CAPABILITIES`, T-20261106-72), не по префиксу
    # id; включённая комната без строки реестра (тип неизвестен) — отказ сборки, а не молча мимо
    try:
        on = [rid for rid, _k in RP.enabled_rooms('demo', flags.get('rooms_enabled') or [], apt.get('rooms') or [],
                                                  RP.capability(room_type, 'demo'))]
    except ValueError as e:
        raise SystemExit(f'витрина: {e}') from None
    if not on:
        return {}, {}
    test_env = [k for k in (room_env(room_type, 'SETS'), FEED_ANY_MESH_ENV) if os.environ.get(k)]
    if test_env and _BP.same(OUT, _BP.DEMO_OUT_DEFAULT):
        raise SystemExit(f'{", ".join(test_env)} у сборки в папку витрины — только сборка рядом (FLAT215_DEMO_OUT)')
    spec = A.SPEC
    bank = R.load_bank(room_bank_path(room_type, os.environ, OUT))
    reg = {r['id']: r for r in apt.get('rooms') or []}
    shared = {k: room[k] for k in ('window_view', 'height_cm') if k in room}
    # геометрия — комната готовой расстановки банка (`layout._room`), иначе чертёж адаптера (`GEO_FILE`)
    geos = {rid: g for rid in on if (g := R.room_geo(spec, rid, A.GEO_FILE, reg.get(rid), shared, R.bank_room(bank, rid)))}
    styles = [v.get('style') for v in variants if (v.get('room_id') or 'living') == living_room_id()]
    made = 0
    recs = R.pick_records(spec, bank, list(geos), styles)
    lays = room_one_layout(room_type, recs, styles)
    # СВОЯ РАССТАНОВКА У КАЖДОГО СТИЛЯ — СВОЯ ПАРА РАКУРСОВ (T-20261107-05/4): правила «одна расстановка на все стили» у типа нет
    # (прихожая: `rules/demo-layout.json`) или комната его не получила — подбор одной пары на все стили (`demo-cams.mjs`, demo-31)
    # искал точку, годную при пяти разных расстановках, и находил только поперёк коридора: в стену или в дверцу шкафа. Метка
    # геометрии `cams_own` — сборщик ракурсов подбирает пару по мебели своего стиля. Спальни (расстановка общая) — без метки
    for rid in geos:
        if not any(k[0] == rid for k in lays):
            geos[rid]['cams_own'] = True
    gate = room_mesh_gate(room_type)
    # сторож выключен — та же проверка только для метки «нет модели» (`no_mesh`), предметы не снимаются
    mark = gate or room_mesh_gate(room_type, mode='orient')
    lead = R.lead_roles(room_type)
    unresolved = 0
    # модель сцены — модель привязки, то же правило, что `_msid` гостиной (`room_bindings.scene_msid`); у сторожа — строки
    # той привязки, которую он проверяет
    bed_msid = getattr(mark, 'msid', None) or _msid
    # РАЗМЕР ПРЕДМЕТА КОМНАТЫ — ИЗ КАТАЛОГА КОМНАТЫ (T-20261107-05): у роли с источником `room_catalog` (профиль комнаты) габарит —
    # тот, что сборщик банка взял из `room_catalog` (с толщиной плоских — зеркало 3 см, `hall_catalog.flat_dims`), а не из каталога
    # гостиной (`products` через `_cat_dims`): там у настенного зеркала глубины нет (предмет выпадал в `dims_unknown`), а «диаметр»
    # круглого зеркала давал коробку 60×60 на полу (OUT_OF_ROOM). Нет габарита в записи — прежний путь
    own_dims = {r for r, p in RP.load(room_type)['roles'].items() if p.get('source') == 'room_catalog'}

    def bed_sku(items: dict, role: str) -> dict | None:
        s = _sku(items, role)
        it = items.get(role) or items.get(R.base_role(role)) or {}
        if s and R.base_role(role) in own_dims and it.get('w') and it.get('d'):
            s = dict(s, w=it['w'], d=it['d'], h=it.get('h'), dia=it.get('dia'))
        return dict(s, msid=bed_msid(s['sid'])) if s and s.get('sid') else s

    def no_mesh(role: str, s: dict) -> str:
        return mark(s) if mark and R.needs_mesh(R.base_role(role)) and s else ''
    # РАЗНЫЕ ТОВАРЫ В КОМНАТАХ ТИПА (bedroom-distinct-01, владелец 07.11 TG 348): по стилю — sid товаров уже собранных комнат;
    # следующая комната того же стиля их не повторяет (`demo_room.distinct_items`). Порядок комнат — порядок РЕЕСТРА квартиры
    # (спальня 1 первой), не порядок флага `rooms_enabled`: ночные пересборки и правка флага их местами не меняют
    used_by_style: dict = {}
    dups = 0
    for rec in R.by_registry(recs, apt.get('rooms')):
        # предмет без модели (T-20261106-77; с /4 — любая роль солвера, не только ведущая): запас из других записей банка — свой
        # стиль, потом соседний
        used = used_by_style.setdefault(rec.get('style') or '', set())
        v, why = R.build_variant(spec, rec, geos[rec['room_id']], bed_sku, _dims_of, style_id, hung=_hung,
                                 decor_role=lambda r: r.split(' ')[0] in DECOR_ROLES or soft_role(r),
                                 layout=lays.get((rec['room_id'], rec.get('style'))), mesh_ok=gate, lead=lead,
                                 spares=R.role_spares(spec, bank, rec) if gate else None, used=used,
                                 distinct_spares=R.role_spares(spec, bank, rec, roles=[k for k in rec.get('items') or {}
                                                                                        if R.base_role(k) == k],
                                                               neighbours=lambda s: []) if used else None)
        for e in (v or {}).pop('distinct_swaps', None) or []:
            print(f"{room_type}_distinct: {rec['room_id']} «{rec.get('style')}» {e['role']}: {e['was'][1]} (уже в другой комнате) → "
                  f"{e['now'][1]}", flush=True)
        for e in (v or {}).pop('dup', None) or []:
            dups += 1
            print(f"WARN:demo_room_dup: {rec['room_id']} «{rec.get('style')}» {e['role']} {e['sid']} «{e['name']}» — тот же товар, "
                  f"что в другой комнате этого стиля: {e['why']}", flush=True)
        if v:
            used |= R.variant_sids(v)
        for e in (v or {}).get('mesh_swaps') or []:
            print(f"{room_type}_mesh_gate: {rec['room_id']} «{rec.get('style')}» {e['role']}: {e['was'][1]} ({e['why']}) → "
                  f"{e['now'][1]}" + (f" (соседний стиль «{e['style']}»)" if e.get('style') else ''), flush=True)
        for e in ((v or {}).get('missing_item') or []) + ((why or {}).get('mesh') or []):
            print(f"WARN:{room_type}_mesh_gate: {rec['room_id']} «{rec.get('style')}» {e['role']} пустая — {e['why']}", flush=True)
        for e in (v or {}).pop('orient_unresolved', None) or []:
            unresolved += 1
            print(f"WARN:{room_type}_orient_unresolved: {rec['room_id']} «{rec.get('style')}» {e['role']} {e['msid']} — {e['why']}",
                  flush=True)
        for r in (v or {}).pop('unpaired', None) or []:   # сторож пары (T-20261107-05): место «… 2» без `pair` в профиле
            print(f"WARN:{room_type}_unpaired: {rec['room_id']} «{rec.get('style')}» место «{r}» не поставлено — у роли "
                  f"«{R.base_role(r)}» нет pair в профиле (tools/scout/rules/profiles/{room_type}.json)", flush=True)
        if why:
            print(f'WARN:demo_style_dropped: {why["room_id"]} «{why["style"]}» без {", ".join(map(str, why["missing"]))} — '
                  'не публикуем', flush=True)
            incomplete.append(why)
            continue
        if not gate:
            for it in v['items']:
                if (w := no_mesh(it['role'], it.get('sku'))):
                    it['no_mesh'] = w
                    print(f"WARN:{room_type}_no_mesh: {rec['room_id']} «{rec.get('style')}» {it['role']} "
                          f"{(it.get('sku') or {}).get('sid')} — {w} (сторож выключен, предмет в варианте)", flush=True)
        variants.append(v)
        made += 1
    any_mesh = os.environ.get(FEED_ANY_MESH_ENV) == '1'
    # ЛЕНТА — ТЕМ ЖЕ СТОРОЖЕМ, ЧТО ВАРИАНТ (T-20261106-77 Д1): замена на товар без годной модели ставила на место кровати коробку
    # (/test/t32f). Сторож выключен (`<ТИП>_MESH_GATE=0`) — прежняя проверка индекса прода
    feed_gate = ((lambda s: '' if s.get('msid') else 'нет модели') if any_mesh
                 else gate or (lambda s: '' if s.get('msid') in _mesh_index() else 'нет в индексе прода'))
    # фото живое — поле базы (`room_catalog.photo_alive` / `products.photo_alive`, писатель `img_alive.py`), не «живо по
    # умолчанию»: мёртвая ссылка CDN давала пустую карточку в ленте замен (T-20261106-84)
    from img_alive import dead_room_photos
    dead = dead_room_photos()
    bf = R.feeds(spec, bank, cat, bed_msid, feed_gate, alive=lambda u: u not in dead)
    marked = 0
    if any_mesh or not gate:
        for role, rows in bf.items():
            for row in rows:
                if (w := no_mesh(role, row)):
                    row['no_mesh'] = w
                    marked += 1
    # КЛЮЧ «ТИП КОМНАТЫ + РОЛЬ» (T-20261106-77, Codex): прежний `setdefault(role, rows)` отдавал общей роли (ковёр) ленту гостиной,
    # а спальня свою теряла. Ленты гостиной не трогаем — у неё голая роль (`demo_room.room_key`)
    R.merge_room_feeds(feeds, room_type, bf)
    print(f'{A.TITLE}: включены {on}, банк {len(bank)} записей, вариантов {made}; ленты '
          + (', '.join(f'{r} {len(x)}' for r, x in sorted(bf.items())) or 'пусто')
          + (' (без проверки моделей — сборка рядом)' if any_mesh else '')
          + (f', без модели (метка no_mesh) {marked}' if marked else '')
          + (f', повторов товара между комнатами (demo_room_dup) {dups}' if dups else '')
          + (f"; сторож {gate.mode}, разворот не решён у {unresolved} предметов вариантов" if gate else ''), flush=True)
    return geos, R.room_bands(spec, bank, geos)


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
    arts = {n: json.load(open(layout_path(n), encoding='utf-8')) for n in BANKS if os.path.exists(layout_path(n))}
    if ONE_LAYOUT:
        arts = one_layout(arts)
    variants = []
    for k, n in enumerate(BANKS, 1):
        # ПОДПИСЬ — СТИЛЬ, А НЕ НОМЕР (13.10). «Вариант 1…6» ничего не говорит, и два набора
        # одного стиля выглядели как дубль. Номер остаётся только запасным именем.
        style = (sets[n - 1].get('style') or f'Вариант {k}').capitalize()
        art = arts.get(n)
        if not art:
            continue
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
                         **({'d_catalog': _dims['d_catalog']} if 'd_catalog' in _dims else {}),
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
        # ЛЮСТРА — В ЦЕНУ И НА ПОТОЛОК (T-20261112-66): раньше роль не выгружалась вовсе, в 3D висел условный плафон
        ch = chandelier_decor(sets, n - 1, f'set{n}', objs, (liv['w'], liv['d']))
        if ch:
            decor.append(ch)
        # ЛАМПА НА КОМОДЕ — В ЦЕНУ И НА КОМОД (T-20261112-101): раньше роль выпадала из декора молча — ни в списке, ни в 3D
        lp = lamp_decor(sets, n - 1, f'set{n}', objs, (liv['w'], liv['d']))
        if lp:
            decor.append(lp)
        # АТОМ «КОМОД + ЛАМПА» (T-20261112-122, одно правило с турами — `bank_invariants.dresser_atom_drop`): лампа не встала — комода нет
        import bank_invariants as BI
        lone = BI.dresser_atom_drop([o['role'] for o in objs], bool(lp))
        if lone:
            print(f"  атом комод+лампа set{n}: лампы на комоде нет — {', '.join(lone)} не показываем", flush=True)
            objs[:] = [o for o in objs if o['role'] not in lone]
        # ШТОРЫ И ПЛЕД — УСЛОВНО, ЦВЕТОМ ТОВАРА (T-20261112-74, владелец TG 953): место — решатель паспорта на носителях варианта,
        # цвет — по названию (`textile_abstract.look_of`); отказ — строка только в списке, как было
        import textile_abstract as _TX
        _TX.annotate(decor, objs, liv, f'set{n}', demo_ceiling())
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
            if base not in NOMESH_ROLES:   # модель сцены — правилом привязки (`_msid`), не представитель из запроса пула (T-25/5)
                p = dict(p, msid=_msid(p['sid']))
            # ОДИН ТОВАР — ОДНА КАРТОЧКА, СТИЛЕЙ У НЕЁ МОЖЕТ БЫТЬ НЕСКОЛЬКО (08.09). Пул
            # перечисляет товар в каждом стиле, которому тот подходит; если складывать это в
            # ленту как разные строки — получаются дубли, а если брать только первый стиль —
            # товар пропадает из остальных (так из 1186 подходящих в ленту попадали 340).
            old = have.get((base, p['sid']))
            if old is not None:
                if p['style'] not in old['styles']:
                    old['styles'].append(p['style'])
                    if p.get('rug_universal'):   # запасной нейтральный этому стилю (`universal_rugs`) — список таких стилей
                        old.setdefault('rug_universal', []).append(p['style'])
                continue
            why = pool_feed_check(p)
            if why == 'off_env':
                n[1] += 1
            if why:
                continue
            mid, eid = p['sid'].split('_', 1)
            # глубина «для сцены» (`scene_dims`, T-25/9): проверки ленты выше — по каталогу, место и модель — по мешу
            _sd = scene_dims(p['sid'], {'w': p['w'], 'd': p['d']}) if base not in NOMESH_ROLES else {}
            _dc = {'d_catalog': p['d']} if _sd.get('dims_by') else {}
            it = {'name': p['name'], 'w': p['w'], 'd': _sd['d'] if _dc else p['d'], **_dc, 'h': p['h'], 'price': p['price'],
                  'img': p['img'], 'url': p['url'], 'shop': p.get('shop'),
                  'style': p['style'], 'styles': [p['style']],
                  'sid': p['sid'], 'msid': p['msid'], 'sub': p['sub'], 'src': 'pool',
                  'basis': _basis(mid, eid), 'hung': _hung(p['name']),
                  'pack': _pack_of(mid, eid, p['name']),
                  **({'rug_universal': [p['style']]} if p.get('rug_universal') else {})}
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
    # ШТОРЫ — ИЗ КАТАЛОГА (style-color-01 шаг 2б, T-20261107-25/3): лента штор была только из наборов — у сканди одна
    # (бирюзовая), у джапанди ни одной, и заменить шторы не в цвет было нечем. Свой запрос (`demo_swap_pool.soft_pool`), в обе
    # ленты: замен (что видит человек) и сборки (замена мягкого варианта по цвету ниже). Сбой — громко, шторы остаются из наборов.
    # Подушки — тем же путём (T-20261107-25/4): у неоклассики лента подушек из наборов была пустой
    try:
        import demo_swap_pool
        n_soft = {}
        for srole in demo_swap_pool.SOFT_FEED_ROLES:
            rows = demo_swap_pool.soft_pool(srole, soft_pool_ok)
            n_soft[srole] = (len(rows), glue_soft(rows, feeds, have),
                             glue_soft(rows, dec_feeds, {(r, p.get('sid')): p for r, lst in dec_feeds.items() for p in lst}))
        print('мягкое ленты из каталога: ' + ', '.join(f'{r} — из пула {a}, в ленту замен +{b}, в ленту сборки +{c}'
                                                       for r, (a, b, c) in n_soft.items()))
    except Exception as e:  # noqa: BLE001
        print(f'WARN:soft_pool: мягкое из каталога в ленту не попало: {repr(e)[:160]}')
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
    import demo_fill as DF
    soft_fixed, soft_dropped, soft_kept, soft_used = [], [], [], set()
    # ВАРИАНТ НА ЗАПАСНОМ — ПОСЛЕДНИМ В РАЗНООБРАЗИИ (T-20261107-11/2): стиль, собранный с запасным нейтральным ковром, берёт
    # мягкое после остальных — разнообразие только переставляет выбор (взятое другим берётся, если больше нечего), поэтому
    # полноты он не теряет, а у стилей со своими ничего не меняется. Порядок вариантов в данных — прежний (сортировка устойчивая)
    for v in sorted(variants, key=lambda v: any(x.get('rug_universal') for x in v.get('fill') or [])):
        st = v.get('style') or ''
        keep = []
        for d in (v.get('decor') or []):
            sk = d.get('sku') or {}
            why = None
            colour = False
            if soft_role(d.get('role')):
                why = ('роль снята каталогом' if (sk.get('sid') or '').replace('_', ':', 1) in _SOFT_LOST
                       else None if _alive(sk.get('img')) else 'фото не открывается')
                if not why:          # цвет не в стиле (шаг 2б, `demo_fill.soft_color_need`) — замена, но только ярусом лучше
                    why = DF.soft_color_need(d.get('role'), sk, st)
                    colour = bool(why)
            if not why:
                keep.append(d)
                continue
            base = re.sub(r'\s+\d+$', '', d.get('role') or '')
            taken = {(x.get('sku') or {}).get('sid') for x in v.get('decor') or []}
            cand = [p for p in dec_feeds.get(base, []) if p.get('soft') and p.get('sid') not in taken]
            # цвет — общим оценщиком (`demo_fill.color_refused`, T-20261107-11/3): яркое не в стиле не берём; нечем — снимаем
            cand = [p for p in cand if not DF.color_refused(base, p, st)]
            if colour:               # замена по цвету — только preferred/allowed этого стиля; нечем — вещь остаётся
                cand = [p for p in cand if not DF.soft_color_need(base, p, st)]
                if not cand:
                    soft_kept.append((v.get('id'), d.get('role'), sk.get('name'), why))
                    keep.append(d)
                    continue
            if not cand:
                soft_dropped.append((v.get('id'), d.get('role'), sk.get('name'), why))
                continue
            # ЯРУС ЦВЕТА — ПЕРВЫЙ КЛЮЧ В ЛЮБОЙ ЗАМЕНЕ МЯГКОГО (сухой прогон T-25/3: снятая каталогом подушка минимализма заменилась
            # первой по цене — синей «Линкс Велюр», discouraged); годные (preferred) раньше, внутри яруса порядок прежний.
            # ТОВАР НАБОРОВ — РАНЬШЕ КАТАЛОЖНОГО того же яруса и стиля (T-20261107-25/4): каталог в ленте — выбор человеку; в вариант
            # он идёт, только когда в наборах годного нет (шторы сканди и джапанди). Сухой прогон без этого ключа: подушки сменились
            # в 5 вариантах из 6, у сканди встала фигурная «Тут Рядом Красавчик», у минимализма — снимок комнаты вместо подушки
            best = min(cand, key=lambda p: (DF.color_eval_role(base, p, st)['rank'],
                                            not (st and (p.get('style') == st or st in (p.get('styles') or []))),
                                            p.get('src') == 'pool',
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
    for vid, role, old, why in soft_kept:
        print(f'  мягкое {vid} {role}: «{old}» ({why}) — замены ярусом лучше нет, оставлено', flush=True)
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
    room = {'w': liv['w'], 'd': liv['d'], 'title': liv['title'],
            'openings': liv['openings'], 'radiators': liv.get('radiators') or [],
            # вид из окна — из карточки квартиры застройщика (demo-04 п.5); нет — страница и кадр берут вид по умолчанию
            **({'window_view': demo_apartment()['windowView']} if demo_apartment().get('windowView') else {}),
            # высота потолка квартиры (реестр) — 3D-комната и камера страницы (`room.height_cm ?? 270`)
            **({'height_cm': demo_ceiling()} if demo_ceiling() else {})}
    flags = rooms_on(apt)
    extra_geo, rules_extra, cats = room_showcases(apt, flags, variants, feeds, incomplete, room)
    return {'room': room,
            # ГЕОМЕТРИЯ КАЖДОЙ КОМНАТЫ ВИТРИНЫ (onb-07 основа, ADR-0330 п.3): вариант обставляет `rooms_geo[v.room_id]`; `room` —
            # псевдоним гостиной для старых читателей (тот же объект: проёмы кадра и отделка ниже дописываются один раз)
            'rooms_geo': rooms_geo(room, extra_geo),
            'apartment_id': demo_apartment_id(), 'plan': plan,
            # ПОМЕЩЕНИЯ КВАРТИРЫ ИЗ РЕЕСТРА (demo-16): порядок плана и площади — `data/partners/*.json`; страница берёт их
            # карточкой `/api/apartments`, а это — запасной путь, пока карточка не пришла (`rooms` выше — схема плана целиком)
            'apartment_rooms': apt.get('rooms') or [],
            # ФЛАГИ НОВЫХ КОМНАТ И ОПРОСА (ADR-0330 п.5): всё выключено — полей нет вовсе (данные гостиной прежние)
            **flags,
            'variants': variants, 'sets': product_sets, 'sofa_feed': feed, 'feeds': feeds,
            # ПОЛОСА «ПОДХОДЯЩИХ ПО РАЗМЕРУ» ленты замен (решение владельца 22.10, demo-20 А4; частично отменяет ADR-0271): ширина
            # 0.8–1.1 идеала слота этой комнаты — одно правило со сборкой комплектов (`slot_rules.slot_band`); лента в данных
            # остаётся широкой (`DEMO_ENV`), страница фильтрует по полосе, пока включён чип «Подходящие по размеру»
            'rules': {**_rules(), 'slot_band_cm': {**_slot_band(liv), **rules_extra}, 'soft_roles': soft_roles()},
            **cats,
            # ОПРОС-ЗНАКОМСТВО (onb-03 Т1, ADR-0330): правило и тексты вопросов — `rules/quiz.json` целиком (страница: `D.quiz`, подбор —
            # блок QUIZPICK). Показ решает флаг квартиры в карточке `/api/apartments` (`quiz.enabled`) или `?quiz=1`, не наличие правила
            'quiz': json.load(open(os.path.join(HERE, 'rules', 'quiz.json'), encoding='utf-8')),
            # стили, где после дозаполнения нет ядра: вариант не публикуется, страница честно пишет почему
            'incomplete_styles': incomplete,
            # ОДНА РАССТАНОВКА НА ВСЕ СТИЛИ (demo-31): есть — `demo-cams.mjs` подбирает одну пару точек на все варианты
            **({'one_layout': ONE_INFO} if ONE_INFO else {}),
            # КВАРТИРА, ЖК, ЦЕНА И СЕРТИФИКАТ — В РЕЕСТРЕ ЗАСТРОЙЩИКОВ (`data/partners/*.json`,
            # план b2b-06): страница берёт их карточкой `/api/apartments/<apartment_id>`. Сумму
            # сертификата здесь не пишем — её считает сервер одной формулой для демо, 3D и отчёта.
            '_note': flat.get('_scale_note')}


def _hung(name: str | None) -> bool:
    """Подвесная (навесная) тумба по НАЗВАНИЮ товара (владелец 02.09; высота признаком не является) — `sku_scene.hung`,
    общее с туром загруженного плана (T-20261112-96)."""
    import sku_scene as _SS
    return _SS.hung(name)


# ПОДХВАТ ФОТО С ОПУБЛИКОВАННОЙ ГЛАВНОЙ (T-20261106-65): магазин режет массовое скачивание (403 «через раз»; пустая папка
# T-59/2 — 14 из 936 не скачались, 5 из них — предметы комнат, на главной у всех фото есть). Имя файла — хеш адреса фида,
# у главной тот же, поэтому не скачалось → берём её копию. Пустая строка в переменной — подхват выключен.
IMG_FALLBACK = os.environ.get('FLAT215_IMG_FALLBACK', 'https://remont-lab.online/demo/')


def _http_get(url: str):
    """(код, тип, тело) или (0, '', b'') при сетевой ошибке; 4xx/5xx — тоже код, а не исключение."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (remlab demo build)'})
    try:
        with urllib.request.urlopen(req, timeout=15) as f:
            return f.status, f.headers.get('Content-Type') or '', f.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type') or '' if e.headers else '', b''
    except Exception:
        return 0, '', b''


def published_img(name: str, dst: str, big: str, base: str = None, fetch=None) -> bool:
    """Взять плитку `img/<name>` (и, если есть, крупную `-l.jpg`) с опубликованной главной. Только ответ 200 с типом
    `image/*`, не меньше 500 байт и открывающийся как картинка — страницу ошибки или HTML не берём. Плитка записана → True."""
    import io
    from PIL import Image
    base = IMG_FALLBACK if base is None else base
    if not base:
        return False
    fetch = fetch or _http_get

    def one(url: str, path: str, side: int) -> bool:
        code, ctype, raw = fetch(url)
        if code != 200 or not ctype.lower().startswith('image/') or len(raw) < 500:
            return False
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
            im = im.convert('RGB')
        except Exception:
            return False
        if min(im.size) < 32:
            return False
        im.thumbnail((side, side))
        tmp = path + '.tmp'
        im.save(tmp, 'JPEG', quality=82)
        os.replace(tmp, path)
        return True

    root = base.rstrip('/') + '/img/'
    if not (os.path.exists(dst) or one(root + name, dst, 400)):
        return False
    if not os.path.exists(big):
        one(root + name[:-4] + '-l.jpg', big, 1200)   # крупной нет — карточка покажет плитку
    return True


def img_name(u: str) -> str:
    """Имя плитки витрины по адресу фото фида: `<md5 адреса>[:16].jpg` (крупная копия — `<то же>-l.jpg`)."""
    import hashlib
    return hashlib.md5(u.encode()).hexdigest()[:16] + '.jpg'


def img_fail_reason(e: BaseException) -> str:
    """Причина, по которой фото не скачалось, — для счётчика отказов в журнале (не молчим)."""
    import urllib.error
    from PIL import UnidentifiedImageError
    if isinstance(e, urllib.error.HTTPError):
        return f'http {e.code}'
    if isinstance(e, UnidentifiedImageError):          # (подкласс OSError — проверяем раньше сети)
        return 'не картинка'
    if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, OSError)):
        return 'сеть'
    return type(e).__name__


def fetch_images(urls, imgdir: str | None = None) -> dict:
    """СКАЧИВАНИЕ ФОТО В ПАПКУ ВИТРИНЫ — один код для витрины (`cache_images`) и товаров банков пробы агента
    (`trial_bundle.cache_bank_images`, T-20261110-25/2): плитка 400 px `img/<md5>.jpg` и крупная `-l.jpg` до 1200 px; уже
    лежащие не перекачиваются; три попытки, затем повтор по одному после паузы, затем копия опубликованной главной.
    Итог: {'got': {адрес: 'img/<имя>' | None}, 'retried', 'rescued', 'fail': {причина: сколько адресов}} — причина последней
    попытки у каждого так и не скачавшегося (`img_fail_reason`)."""
    from concurrent.futures import ThreadPoolExecutor
    import io
    import urllib.request
    from PIL import Image
    imgdir = imgdir or os.path.join(OUT, 'img')
    os.makedirs(imgdir, exist_ok=True)
    why: dict = {}

    # КРУПНАЯ КОПИЯ ДЛЯ КАРТОЧКИ ТОВАРА (demo-26 Д, владелец 23.10): рядом с плиткой 400 px — `<id>-l.jpg` до 1200 px из того же
    # исходника (в выборке уже `coalesce(image_url_hd, image_url)` — HD магазина, где есть). Замер 23.10 на 25 товарах: исходники
    # 700–2560 px, копия 1200 px — в среднем 36 КБ (на ~850 фото ~30 МБ). Страница берёт её по имени и только при `_img_large`
    def grab(u: str):
        name = img_name(u)
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
                why.pop(u, None)
                return u, 'img/' + name
            except Exception as e:  # noqa: BLE001 — причина идёт в счётчик отказов (`fail`), не молча
                why[u] = img_fail_reason(e)
                if k < 2:
                    time.sleep(1.5)
        # крупная не скачалась, плитка есть — товар остаётся с плиткой (карточка покажет её)
        return u, ('img/' + name) if os.path.exists(dst) else None

    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(grab, sorted(urls)))
    # T-65: не скачавшиеся — ещё раз по одному после паузы (магазин режет поток), затем копия опубликованной главной
    miss = sorted(u for u, v in got.items() if not v)
    retried = rescued = 0
    if miss:
        time.sleep(5)
        for u in miss:
            got[u] = grab(u)[1]
            retried += bool(got[u])
        for u in (u for u in miss if not got[u]):
            name = img_name(u)
            dst = os.path.join(imgdir, name)
            if published_img(name, dst, dst[:-4] + '-l.jpg'):
                got[u] = 'img/' + name
                rescued += 1
    fail: dict = {}
    for u, v in got.items():
        if not v:
            r = why.get(u) or 'нет на главной'
            fail[r] = fail.get(r, 0) + 1
    return {'got': got, 'retried': retried, 'rescued': rescued, 'fail': fail}


def fail_text(fail: dict) -> str:
    """«не скачались: 5 (http 404 — 3, сеть — 2)» — для строки журнала."""
    n = sum(fail.values())
    return f'не скачались: {n}' + (' (' + ', '.join(f'{k} — {v}' for k, v in sorted(fail.items(), key=lambda x: -x[1])) + ')'
                                   if n else '')


def cache_images(data: dict) -> dict:
    """ФОТО КЛАДЁМ К СЕБЕ (владелец 26.08: «фотки не все прогружаются»). Причина — в фиде
    протокол-относительные ссылки на CDN Гдеслона, и примерно половина отдаёт 404: карточки
    приходили пустыми. Качаем один раз, ужимаем до 400 px и раздаём со своего домена; у товара
    с мёртвой ссылкой `img=null` — карточка честно показывает «фото недоступно», а сам товар
    (габариты, цена, ссылка в магазин) остаётся рабочим. Скачивание — `fetch_images`."""
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
    for lst in [x for c in room_catalogs(data) for x in (c.get('roles') or {}).values()]:
        for p in lst:
            if p.get('img'):
                urls.add(p['img'])

    res = fetch_images(urls)
    got, retried, rescued = res['got'], res['retried'], res['rescued']
    ok = sum(1 for v in got.values() if v)
    print(f'фото: скачано {ok} из {len(urls)} (остальные — битые ссылки фида); со второй попытки: {retried}; '
          f'подхвачено с прода: {rescued}; {fail_text(res["fail"])}')

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
    no_photo = []
    for v in data.get('variants') or []:
        for it in v['items']:
            fix(it.get('sku'))
            # предмет комнаты без фото остаётся (он расставлен, у него меш, размеры, цена и ссылка): страница рисует плашку
            # «нет фото» (T-65); замена другим товаром сдвинула бы расстановку и 3D
            sk = it.get('sku') or {}
            if sk and not sk.get('img'):
                no_photo.append(f"{v.get('id')} {it.get('role')}: {sk.get('name')}")
        for x in v.get('decor') or []:              # не скачалось — остаётся адрес магазина: строка декора из списка не пропадает
            sk = x.get('sku') or {}
            if sk.get('img'):
                sk['img'] = got.get(sk['img']) or sk['img']
    for bc in [c.get('roles') or {} for c in room_catalogs(data)]:
        for role in list(bc):                   # каталог комнаты: товар без живого фото не показываем
            for p in bc[role]:
                fix(p)
            bc[role] = [p for p in bc[role] if p.get('img')]
    # ТОВАР БЕЗ ФОТО В ВЫБОРКЕ НЕ УЧАСТВУЕТ (владелец 26.08): выборку пересчитываем ПОСЛЕ
    # проверки картинок, иначе половина ленты — пустые карточки.
    dropped = capped = color_cut = color_low = 0
    import demo_fill as _DFC
    cur_items = {(v.get('style'), (x.get('sku') or {}).get('sid')) for v in data.get('variants') or []
                 if (v.get('room_id') or 'living') == 'living' for x in (v.get('items') or []) + (v.get('decor') or [])}
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
        # ЦВЕТ ЛЕНТЫ ГОСТИНОЙ (style-color-01 шаг 2а, T-20261107-25/2): forbidden — стиль снимается с товара, discouraged — в конец
        # ленты этого стиля (`color_low`, страница `feedFor`); товары вариантов не трогаем. Ленты других комнат (`bedroom:…`) — как были
        if ':' not in role:
            keep, _cut, _low = _DFC.lane_color(role, keep, cur_items)
            color_cut += _cut
            color_low += _low
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
    print(f'ленты гостиной по цвету: снято стилей у товаров (forbidden) {color_cut}, в конец ленты стиля (discouraged) {color_low}')
    print(f'предметов комнат без фото (плашка «нет фото»): {len(no_photo)}'
          + (' — ' + '; '.join(no_photo) if no_photo else ''))
    data['_img_cached'] = {'ok': ok, 'total': len(urls), 'dropped_no_photo': dropped,
                           'capped': capped, 'retried': retried, 'from_published': rescued,
                           'variant_items_no_photo': len(no_photo)}
    large = sum(1 for v in got.values() if v and os.path.exists(os.path.join(OUT, v[:-4] + '-l.jpg')))
    print(f'крупных копий для карточки товара: {large} из {ok}')
    data['_img_large'] = large > 0                 # страница пробует `<id>-l.jpg` только при этом флаге (нет файла — остаётся плитка)
    return data


def annotate_yaw(data: dict) -> int:
    """Разворот фронта модели — в каждый предмет вариантов (`sku.yaw`), чтобы 3D по кнопке из демо
    (`lib/configurator/fromDemo.ts`) ставил модель так же, как 3D-сцена самого демо (`orient.json` прода) и базовая
    квартира (ручные поправки `data/flat3d/front-overrides.json` — сильнее). Раньше 3D по ссылке из демо брал 0 у всех
    (разбор Codex 14.10). Нет сети — разворотов нет, как раньше.
    ЛЕНТЫ И ДЕКОР ТОЖЕ (demo-01, 14.10): живая сцена ставит модель заменённого предмета прямо из ленты.
    Тело — `sku_scene.yaw`: тот же шаг делает тур загруженного плана (`trial_bundle.scene_fields`, T-20261112-96)."""
    import sku_scene as _SS
    return _SS.yaw(_SS.skus_of(data))


def annotate_strategy(data: dict) -> int:
    """СТРАТЕГИЯ 3D-АССЕТА — В ПРЕДМЕТ ВАРИАНТА (T-20261107-05/3; контракт `lib/configurator/fromDemo.ts` поле `strategy`, T-73).
    Мост рисует зеркало и картину плоскостью на стене только по этому полю (`isWallPlane`): канон ролей лежит в `tools/`, которых
    нет в образе приложения, поэтому решение идёт ДАННЫМИ. Без поля зеркало прихожей шло коробкой и искало модель (404).
    Тело — `sku_scene.strategy` (общее с туром, T-20261112-96)."""
    import sku_scene as _SS
    return _SS.strategy([it for v in data.get('variants') or [] for it in v.get('items') or []])


def _tone(path: str):
    """Средний цвет товара по фото без белого фона — `sku_scene.tone` (= `mesh_color_check.tone`, одно правило со сторожем)."""
    import sku_scene as _SS
    return _SS.tone(path)


def _rep_tones(msids: set) -> dict:
    """Тон фото ПРЕДСТАВИТЕЛЯ, которого нет среди товаров демо (T-20261107-14/2) — `sku_scene.rep_tones`."""
    import sku_scene as _SS
    return _SS.rep_tones(msids)


def annotate_tint(data: dict, out_dir: str = OUT) -> int:
    """ЦВЕТ ВАРИАНТА НА МОДЕЛИ СЕМЕЙСТВА (demo-02 приёмка 16.10 п.11б): `sku.tint` у вариантов, декора и лент. Тело —
    `sku_scene.tint` (строка ночного замера сторожа, T-20261112-89, или тоны двух фото); тот же шаг делает тур загруженного
    плана (`trial_bundle.scene_fields`, T-20261112-96). `_rep_tones` — здесь, чтобы проверки могли подменить базу."""
    import sku_scene as _SS
    return _SS.tint(_SS.skus_of(data), out_dir, rep=lambda need: _rep_tones(need))


def _swatch_tone(path: str):
    """ТОН ОБРАЗЦА — цвет ткани, а не среднее по фото (ведущий 23.10: «Молочный» кружок заметно темнее дивана). Среднее `_tone`
    серит светлое трижды: отбрасывает самые светлые пиксели ткани (порог фона), берёт тени и тёмные ножки. Здесь: фон — почти белое,
    связанное с краем кадра (белая обивка внутри предмета остаётся); пиксели предмета — в 4 группы по цвету, берётся самая большая
    (ткань, а не ножки и тень на полу) и в ней освещённая часть — яркость от медианы до 95-го процентиля. Доли 0..1; без scipy или
    на мелком предмете — прежнее среднее. Подкраска 3D (`annotate_tint`) остаётся на `_tone`: там важно отношение тонов, не тон."""
    try:
        import numpy as _np
        from PIL import Image as _Im
        from scipy import ndimage as _nd
        from scipy.cluster.vq import kmeans2 as _km
        a = _np.asarray(_Im.open(path).convert('RGB').resize((128, 96)), _np.float32)
        white = a.min(axis=2) >= 244
        lab, _n = _nd.label(white)
        edge = set(_np.unique(_np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]).tolist())) - {0}
        obj = ~_np.isin(lab, list(edge))
        # просветы тонкого предмета (стол на ножках, открытые полки, кашпо на подставке) — тоже фон: замкнутого почти белого 15–60 %
        # предмета → не берём (T-20261112-29: чёрный стол и графитовая тумба давали белый образец); меньше — белая вставка обивки,
        # больше — белый предмет. Замер на 325 товарах тура: меняются только такие случаи
        encl = float((obj & white).sum()) / max(1, int(obj.sum()))
        px = a[obj & ~white] if 0.15 <= encl < 0.6 else a[obj]
        if len(px) < 200:
            return _tone(path)
        _c, lb = _km(px, 4, seed=_np.random.default_rng(0), minit='++')
        s = px[lb == _np.bincount(lb, minlength=4).argmax()]
        lum = s @ _np.array([0.299, 0.587, 0.114], _np.float32)
        lo, hi = _np.percentile(lum, [50, 95])
        s = s[(lum >= lo) & (lum <= hi)]
        return [float(x) / 255.0 for x in s.mean(axis=0)] if len(s) else _tone(path)
    except Exception:  # noqa: BLE001 — нет фото/scipy: прежнее среднее (или без образца)
        return _tone(path)


def swatch_hex(img, out_dir: str = OUT, cache: dict | None = None) -> str | None:
    """Цвет товара '#rrggbb' по его плитке витрины (`img/<md5>.jpg` в `out_dir`) — `_swatch_tone`. Адрес http(s), нет файла — None."""
    if not img or str(img).startswith(('http:', 'https:', '//')):
        return None
    if cache is not None and img in cache:
        return cache[img]
    p = os.path.join(out_dir, str(img))
    t = _swatch_tone(p) if os.path.isfile(p) else None
    h = '#%02x%02x%02x' % tuple(max(0, min(255, round(x * 255))) for x in t) if t else None
    if cache is not None:
        cache[img] = h
    return h


def annotate_swatch(data: dict, out_dir: str = OUT) -> int:
    """ОБРАЗЕЦ ЦВЕТА (demo-28, владелец 23.10): у КАЖДОГО товара с фото — `sku.swatch` = '#rrggbb', цвет ткани по фото (`_swatch_tone`:
    главная группа цвета без фона, её освещённая часть). Это кружки цвета в строке списка и в карточке товара (они — только у модели
    хотя бы в двух цветах, `index.html:colourFam`) и ЦВЕТ ПРЕДМЕТА НА ПЛАНЕ (T-20261112-29, владелец: «на схеме диван фиолетовый, а в 3D
    бежевый» — схема рисовала условной палитрой по роли, `index.html:shape`). Нет фото — без образца: кружок из самого фото, на плане —
    нейтральный цвет роли.
    СЕМЬЯ ЦВЕТОВ — по представителю семьи (`_mesh_rep`), а не по модели сцены (T-20261106-77/5): с правилом привязки у цвета бывает
    своя 3D-модель (`scene_msid`), и группировка по `msid` разбивала семью — кружки пропадали у 34 товаров лент. Где семья
    отличается от `msid`, она пишется в `sku.fam` — по ней же страница собирает «Цвета этой модели» (`famKey`)."""
    skus = [it.get('sku') or {} for v in data.get('variants') or [] for it in (v.get('items') or []) + (v.get('decor') or [])]
    skus += [f for lst in (data.get('feeds') or {}).values() for f in lst if isinstance(f, dict)]
    import sku_scene as _SS
    _SS.family(skus, _mesh_rep())                         # то же правило — у тура загруженного плана (T-20261112-96)
    tone: dict = {}
    n = 0
    for sk in skus:
        sk.pop('swatch', None)
        h = swatch_hex(sk.get('img'), out_dir, tone)
        if h:
            sk['swatch'] = h
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


def room_ir(room: dict, root: str, tag: str = '') -> None:
    """Проёмы кадра, паспорт отделки и плинтусы комнаты — на месте, в `room` (было — только `data['room']`, до onb-07).
    `tag` — подпись комнаты в журнале; у гостиной пусто, строки журнала прежние."""
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(room, tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}"'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        room['openings_ir'] = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        room['openings_ir'] = None
    if not room['openings_ir']:
        room.pop('openings_ir', None)
        print(f'WARN:opening_ir: {tag}описание проёмов не посчиталось (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    else:
        print(f"{tag}проёмы кадра: {len(room['openings_ir'])} из общего описания")
    # ПАСПОРТ ОТДЕЛКИ (demo-04): карточка квартиры (`finish`) поверх набора по умолчанию — готовым, им красят и страница, и кадр
    if demo_apartment().get('finish'):
        room['finish'] = demo_apartment()['finish']
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(room, tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}" --finish'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        room['finish'] = json.loads(r.stdout) if r.returncode == 0 else room.get('finish')
    except ValueError:
        print(f'WARN:finish: {tag}паспорт отделки не посчитался (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')
    # плинтус, карниз, светильник — тем же генератором (demo-04 п.6, `lib/viewer3d/fixtures-ir.ts`)
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
        json.dump(room, tf, ensure_ascii=False)
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/opening-ir.mjs" "{tf.name}" --fixtures'],
                       capture_output=True, text=True, timeout=120)
    os.unlink(tf.name)
    try:
        fx = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        fx = None
    if fx:
        room['fixtures_ir'] = fx
    else:
        print(f'WARN:fixtures_ir: {tag}плинтус/карниз/светильник не посчитались (rc={r.returncode}): {(r.stderr or "").strip()[-200:]}')


def rt_table_side() -> str:
    """ТАБЛИЦА ЛЁГКИХ КОПИЙ У СБОРКИ РЯДОМ (T-20261107-05/2). `rt-meshes.json` кладёт в папку витрины не эта сборка, а публикация
    копий (`tools/assets/publish_rt.sh`). У сборки для /test/ её не было — страница (`rtMeshes`) получала 404, сцена брала тяжёлые
    исходники галереи `/test/mesh-pilot10/<id>/model.glb` вместо `/rt/`, а у товаров без модели — ещё и 404 на каждый. Копия таблицы
    витрины — только когда своей нет; папку витрины не трогает. Что сделано — строкой (для журнала)."""
    if _BP.same(OUT, _BP.DEMO_OUT_DEFAULT):
        return ''
    dst, src = os.path.join(OUT, 'rt-meshes.json'), os.path.join(_BP.DEMO_OUT_DEFAULT, 'rt-meshes.json')
    if os.path.exists(dst):
        return 'своя'
    if not os.path.exists(src):
        print(f'WARN:rt_table: у витрины нет {src} — сцена /test/ возьмёт исходники галереи', flush=True)
        return 'нет'
    _AIO.write_text(dst, open(src, encoding='utf-8').read())
    print(f'таблица лёгких копий: копия витрины → {dst}', flush=True)
    return 'копия'


DEMO_CAMS_TIMEOUT = 300


def demo_cams(root: str, path: str, timeout: float = DEMO_CAMS_TIMEOUT, run=subprocess.run) -> str:
    """Ракурсы окна в данные (`tools/flat3d/demo-cams.mjs` → `v.cams`) → строка лога сборки. НЕ ВАЛИТ СБОРКУ (T-20261107-47):
    таймаут был без перехвата — `TimeoutExpired` ронял весь `flat215_demo`, и ночь оставалась без публикации витрины (07.11 после
    видов спальни с двух концов подбор шёл 259 с при пороге 300, под нагрузкой — дольше). Таймаут и код ≠ 0 — строка
    WARN:demo_cams, файл данных остаётся как записан до ракурсов (скрипт пишет подменой — оборванный не портит), сборка идёт дальше:
    страница считает ракурсы сама, /flat показывает прежний вид. `exec` — таймаут убивает сам node, а не только bash: иначе
    осиротевший node дописал бы файл позже, посреди публикации. Его временный файл подмены (`<файл>.cams-<pid>.tmp`) после
    таймаута убираем, чтобы он не уехал на прод с папкой витрины."""
    try:
        r = run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && exec node "{root}/tools/flat3d/demo-cams.mjs" "{path}"'],
                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        for t in glob.glob(glob.escape(path) + '.cams-*.tmp'):
            try:
                os.remove(t)
            except OSError:
                pass
        out = e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return (f'WARN:demo_cams: ракурсы окна в данные не записались (таймаут {timeout:.0f} с) — ракурсы считает '
                f'страница, сборка идёт дальше; последнее в выводе: {out.strip()[-200:]}')
    if r.returncode == 0:
        return (r.stdout or '').strip()[-300:]
    return f'WARN:demo_cams: ракурсы окна в данные не записались (rc={r.returncode}): {(r.stderr or r.stdout or "").strip()[-200:]}'


def page_step(root: str, src: str) -> None:
    """СТРАНИЦА В ВИТРИНУ — СЖАТОЙ (T-20261112-90, план tour-page-split-01 А): `tools/scout/page_build.mjs` убирает комментарии и
    пробелы каждого блока (имена не трогает) и кладёт блок ракурсов файлом `lib/camfit.<хеш>.js` (имя — в `lib/scene.json`, поэтому
    шаг идёт ПОСЛЕ сборки движка, которая этот манифест переписывает). Исходник в репо не меняется. node не запустился — копия как
    есть (как было до T-90) и громкий WARN: страница работает, только тяжелее, а запасной подбор ракурсов — в главном потоке."""
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/scout/page_build.mjs" "$0" "$1"',
                        src, OUT], capture_output=True, text=True, timeout=180)
    if r.returncode == 0:
        print((r.stdout or '').strip()[-400:], flush=True)
        return
    _AIO.write_text(os.path.join(OUT, 'index.html'), open(src, encoding='utf-8').read())
    print(f'WARN:page_build: страница не собралась (rc={r.returncode}) — в витрину исходник как есть: '
          f'{(r.stderr or r.stdout or "").strip()[-200:]}', flush=True)


def main() -> None:
    if '--publish' in sys.argv and not _BP.same(OUT, _BP.DEMO_OUT_DEFAULT):
        # publish_demo.sh публикует ПАПКУ ВИТРИНЫ, а не OUT: сборка рядом (копия банка, проверка) на прод не едет
        raise SystemExit(f'--publish со сборкой в {OUT}: публикуется только папка витрины — копия банка идёт в /test/')
    os.makedirs(OUT, exist_ok=True)
    # ИСХОДНИК СТРАНИЦЫ ЖИВЁТ В РЕПО (26.08): до этого index.html лежал только в ~/scout-scenes и
    # не попадал в git — демо было невоспроизводимо и терялось при чистке. Копия — подменой (T-20261105-59)
    src = os.path.join(HERE, 'flat215-demo', 'index.html')
    rt_table_side()
    # ДВИЖОК ЖИВОЙ СЦЕНЫ (demo-01): тот же исходник, что /flat (`lib/viewer3d`), собирается рядом со страницей
    # (`lib/scene.<версия>.js` + `lib/scene.json`). Не собрался — остаётся вчерашний файл, страница работает с ним
    # или уходит на серверный эскиз; громко, а не молча.
    root = os.path.abspath(os.path.join(HERE, '..', '..'))
    r = subprocess.run(['bash', '-c', f'. "{root}/tools/ops/node-env.sh" && node "{root}/tools/flat3d/build-scene-bundle.mjs" '
                        f'--out "{os.path.join(OUT, "lib")}"'], capture_output=True, text=True, timeout=300)
    print((r.stdout or '').strip()[-300:] if r.returncode == 0 else
          f'WARN:scene_bundle: движок живой сцены не собрался (rc={r.returncode}): {(r.stderr or r.stdout or "").strip()[-200:]}')
    if os.path.exists(src):
        page_step(root, src)
    data = build()
    wall_art_step(data)
    data = cache_images(data)
    print(f'разворот фронта в предметах вариантов: {annotate_yaw(data)}')
    print(f'стратегия плоскости (зеркало, картина, ковёр) в предметах вариантов: {annotate_strategy(data)}')
    try:
        import wall_art as _WA
        print('картины: фото без белого поля — {} из {}'.format(*_WA.annotate_crop(data, OUT)))
    except Exception as e:  # noqa: BLE001 — без обрезки полотно — фото товара как есть
        print(f'WARN:wall_art_crop: {repr(e)[:160]}')
    print(f'подкраска цветовых вариантов семейства: {annotate_tint(data)}')
    print(f'образцы цвета у товаров с цветами: {annotate_swatch(data)}')
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
    # КАЖДАЯ КОМНАТА ВИТРИНЫ (onb-07 основа): те же шаги по всем геометриям `rooms_geo`; гостиная (`room`) — один раз, как прежде
    for geo in unique_rooms(data):
        room_ir(geo, root, '' if geo is data['room'] else f"{geo.get('title') or '?'}: ")
    for line in rooms_check(data):
        print(line, flush=True)
    try:
        prev = json.load(open(os.path.join(OUT, 'demo-data.json'), encoding='utf-8'))
    except (OSError, ValueError):
        prev = None
    data['variant_aliases'] = merge_aliases(prev, data['variants'])
    fallback = room_style_fallback(data, root)
    if fallback:
        data['room_style_fallback'] = fallback
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
    print(scene_family_digest(data, _bind_rows()), flush=True)
    # АНГЛИЙСКИЕ НАЗВАНИЯ (план demo-31, владелец 30.10): `name_en`/`colour_en` каждому товару — для английского демо.
    # Без кириллицы и магазина по построению (нет перевода — нейтральное по роли, строка WARN); публикацию не останавливает
    try:
        import names_en as _NE
        for line in _NE.report_lines(_NE.annotate(data)):
            print(line, flush=True)
    except Exception as e:  # noqa: BLE001 — сломанный перевод не валит русскую витрину, но громко
        print(f'WARN:names_en_error: английские названия не записались: {repr(e)[:160]}', flush=True)
    # АТОМАРНО (T-20261105-59): раньше файл обрезался и писался заново — упавшая посреди записи сборка оставляла
    # обрывок, и публикация увозила его на прод. Теперь временный файл рядом + os.replace (`atomic_io.py`)
    import build_stamp as _BS                       # метка правил сборщика — проверка «демо = туры» (T-20261112-92)
    data['build'] = _BS.stamp()
    _AIO.write_json(os.path.join(OUT, 'demo-data.json'), data, ensure_ascii=False, indent=1)
    # РАКУРСЫ ОКНА — В ДАННЫЕ (demo-05 п.8): тот же блок CAMFIT страницы считает пару ракурсов каждого варианта
    # (`tools/flat3d/demo-cams.mjs` → `v.cams`), ими снимает «Фото» в /flat. Не посчиталось — /flat покажет прежний вид
    print(demo_cams(root, os.path.join(OUT, 'demo-data.json')), flush=True)
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
    for line in _BS.watch_report():
        print(line, flush=True)
    if '--publish' in sys.argv:
        # ПУБЛИКУЕТ ОДИН СКРИПТ (08.09). Здесь раньше стояла своя копия команд, и она сносила
        # каталог целиком (`rm -rf /opt/remlab/demo && mv`) — а он примонтирован в контейнер
        # Caddy: новый каталог получает новый inode, и `/demo` начинает отдавать 404 до
        # пересоздания контейнера. `publish_demo.sh` обновляет содержимое НА МЕСТЕ (урок 430).
        subprocess.run([os.path.join(HERE, 'publish_demo.sh')], check=True)


if __name__ == '__main__':
    main()
