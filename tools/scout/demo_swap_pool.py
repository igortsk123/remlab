#!/usr/bin/env python3
"""Пул замены для демо: «любая мебель, у которой есть меш и которая подходит стилю».

Владелец 08.09: «сделай так, чтобы мебель можно было выбирать любую из тех, что есть меши и
соответствуют стилю; изначальный набор в сете рекомендуемой мебели остаётся». И там же —
временное ограничение: «по 30 вариантов товаров каждой подкатегории в каждом стиле» (компромисс
по месту на сервере: без него под все стили нужно 8–11 ГБ моделей при 16 ГБ свободных).

Подкатегория — `functional_subtype` из обогащения (мягкая_мебель, тумба_под_тв, журнальный_стол…),
стиль — из `styles` того же обогащения со СИЛОЙ «высокая»/«средняя» (ключ есть у всех товаров,
поэтому фильтровать по наличию ключа бессмысленно). Внутри группы берём лучших по качеству
обогащения, при равенстве — стабильно по артикулу.

МОДЕЛЬ ОДНА НА СЕМЕЙСТВО (ADR-0196): цветовые варианты делят меш представителя, поэтому в пуле у
товара два артикула — свой (`sid`, для карточки и ссылки) и модельный (`msid`, по нему сцена
грузит GLB). Публикуем и держим на сервере только модели представителей.

30 — ПОСЛЕ ПРОВЕРОК СБОРКИ, РАЗНЫЕ МОДЕЛИ РАНЬШЕ ЦВЕТОВ (план demo-18 п.1, разбор T-20261018-13). Раньше SQL резал 30 лучших
до проверок витрины (модель на сервере, цвет модели, `unfit`, ширина комнаты), и у четырёх стилей из 13–130 подходящих диванов
в ленту доходили 1–3. Теперь запрос отдаёт всех кандидатов по порядку, а группа добирается до 30 прошедших: сперва по одному
лучшему товару на модель (`msid`), потом цвета тех же моделей. Проверку «модель на сервере и цвет» даёт сборка (`ok`), конверт
ширины — `rules/demo-swap.json` (один источник с `flat215_demo.DEMO_ENV`).

  ~/venvs/scout/bin/python demo_swap_pool.py            # сводка
  ~/venvs/scout/bin/python demo_swap_pool.py --json f   # выгрузить пул
  python3 demo_swap_pool.py --selftest
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RULES = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))   # conv-03: правила ленты
PER_GROUP = int(os.environ.get('DEMO_SWAP_PER_GROUP', RULES['per_group']))
IN_STYLE_MIN = float(RULES['in_style_min'])
STYLES = ('лофт', 'сканди', 'джапанди', 'минимализм', 'неоклассика', 'современный')
# роли, которые демо расставляет объёмными моделями (ковры и прочее плоское — вклейкой)
ROLES = ('диван', 'кресло', 'столик', 'тв-тумба', 'стеллаж', 'комод', 'торшер', 'пуф',
         'кашпо', 'витрина', 'банкетка', 'стол обеденный', 'стул',
         # НАСТОЛЬНЫЙ ДЕКОР (владелец 08.09: «вазы настольные и что там ещё есть, если есть меши
         # и стили, добавлять в список товаров и считать сумму»). Меши сегодня есть только у вазы
         # и кашпо; статуэтки/часы/картины пойдут сюда сами, когда их меши появятся.
         'ваза')
# ширина, которая встаёт в комнату демо (мебель) или на столешницу (декор) — те же числа читает `flat215_demo.DEMO_ENV`
ENVELOPE = {k: tuple(v) for blk in ('room_fit_envelope_cm', 'decor_envelope_cm')
            for k, v in RULES[blk].items() if not k.startswith('_')}


def _lit(xs) -> str:
    return ','.join("'" + str(x).replace("'", "''") + "'" for x in xs) or "''"


def pool_sql(in_style_min: float = IN_STYLE_MIN, top: int | None = None, any_mesh: bool = False) -> str:
    """Запрос пула — ВСЕ кандидаты по порядку группы (срез до `PER_GROUP` — в `pick` после проверок); `top` — прежний запрос
    (первые `top` группы до проверок, порядок выдачи базы) для дозаполнения вариантов; `any_mesh` — те же ворота и порядок, но
    и товары без готового меша (кого добирать в ленту, `demo_band`). Вынесен отдельно, чтобы `--selftest` проверял его форму
    без БД."""
    return f"""
with cand as (
  select p.shop_mid||':'||p.external_id as sku,
         coalesce(p.mesh_family_rep, p.shop_mid||':'||p.external_id) as rep,
         coalesce(e.payload->'model'->>'functional_subtype', p.cat_role) as sub,
         s.style, p.cat_role, coalesce(p.name,'') as name, coalesce(p.shop,'') as shop,
         coalesce(p.image_url_hd, p.image_url) as img, p.url, coalesce(p.price_shown_rub, p.price_rub) as price,
         coalesce(p.w_cm, p.dia_cm) as w_cm, coalesce(p.d_cm, p.dia_cm) as d_cm, p.h_cm, coalesce(e.quality, 0) as q,
         coalesce((ps.scores->>s.style)::numeric, 0) as st_score, coalesce(ps.universal, false) as uni
    from products p
    join product_enrichment e using (shop_mid, external_id)
    join product_style_scores ps using (shop_mid, external_id)
    cross join lateral (select unnest(array[{_lit(STYLES)}]) as style) s
   where p.cat_role in ({_lit(ROLES)})
     and {"" if any_mesh else "p.mesh_status = 'ready' and "}p.in_stock and p.status = 'active'
     -- круглое (столик, пуф, кашпо) — диаметр за обе стороны: общая норма размеров (verify 14.10, conv-03)
     and coalesce(p.w_cm, p.dia_cm) is not null and coalesce(p.d_cm, p.dia_cm) is not null and p.h_cm is not null
     and coalesce(p.image_url_hd, p.image_url) is not null and coalesce(p.photo_alive, true)  -- conv-05
     -- СТИЛЬ — БАЛЛ 0–10 ≥ порога (conv-03, ADR-0245/0271; rules/demo-swap.json), а не ступень обогащения;
     -- «универсальный» без исключения — тоже по баллу, но ниже в порядке
     and coalesce((ps.scores->>s.style)::numeric, 0) >= {in_style_min}),
ranked as (
  select *, row_number() over (partition by sub, style
                               order by uni asc, q desc, st_score desc, price asc nulls last, sku) as rn from cand)
select sku, rep, sub, style, cat_role, name, shop, img, url, coalesce(price::text,''),
       w_cm, d_cm, h_cm
  from ranked {f"where rn <= {top} order by cat_role, style, sku" if top else "order by sub, style, rn"}"""


RUG = 'ковёр'


def rug_sql(in_style_min: float = IN_STYLE_MIN) -> str:
    """ЛЕНТА ЗАМЕН КОВРА (план demo-18 п.2): ковру модель не нужна (он плита с фото), поэтому в `pool_sql` его нет. Отбор — запрос
    дозаполнения (`demo_fill.RUG_SQL`), но стиль — балл ≥ порога ленты, как у мебели, а порядок — тот же, что у пула. Та же форма
    строки, что у `pool_sql` (`_row`): модели семейства у ковров нет — модель = сам товар; `w` — длинная сторона, `d` — короткая
    (в фидах у ковров `w` бывает короткой — `zones.json` `measured_side`)."""
    return f"""
with cand as (
  select p.shop_mid||':'||p.external_id as sku, s.style, coalesce(p.name,'') as name, coalesce(p.shop,'') as shop,
         coalesce(p.image_url_hd, p.image_url) as img, p.url, coalesce(p.price_shown_rub, p.price_rub) as price,
         greatest(p.w_cm, p.d_cm) as w_cm, least(p.w_cm, p.d_cm) as d_cm, coalesce(e.quality, 0) as q,
         coalesce((ps.scores->>s.style)::numeric, 0) as st_score, coalesce(ps.universal, false) as uni
    from products p
    join product_enrichment e using (shop_mid, external_id)
    join product_style_scores ps using (shop_mid, external_id)
    cross join lateral (select unnest(array[{_lit(STYLES)}]) as style) s
   where p.cat_role = '{RUG}' and p.in_stock and p.status = 'active'
     and p.w_cm is not null and p.d_cm is not null
     and coalesce(p.image_url_hd, p.image_url) is not null and coalesce(p.photo_alive, true)
     and coalesce((ps.scores->>s.style)::numeric, 0) >= {in_style_min}),
ranked as (
  select *, row_number() over (partition by style order by uni asc, q desc, st_score desc, price asc nulls last, sku) as rn from cand)
select sku, sku, '{RUG}', style, '{RUG}', name, shop, img, url, coalesce(price::text,''), w_cm, d_cm, 1
  from ranked order by style, rn"""


UNI_RUG = RULES['rug_universal']


def universal_rug_sql() -> str:
    """Нейтральные «универсальные» ковры (`rules/demo-swap.json` `rug_universal`) — без стиля, форма строки `_row`, порядок —
    качество обогащения, артикул. Ворота наличия/фото — те же, что у `rug_sql`."""
    flag = 'and coalesce(ps.universal, false)' if UNI_RUG.get('universal_flag') else ''
    return f"""
select p.shop_mid||':'||p.external_id as sku, p.shop_mid||':'||p.external_id, '{RUG}', '', '{RUG}', coalesce(p.name,''),
       coalesce(p.shop,''), coalesce(p.image_url_hd, p.image_url), p.url,
       coalesce(coalesce(p.price_shown_rub, p.price_rub)::text,''), greatest(p.w_cm, p.d_cm), least(p.w_cm, p.d_cm), 1
  from products p
  join product_enrichment e using (shop_mid, external_id)
  join product_style_scores ps using (shop_mid, external_id)
 where p.cat_role = '{RUG}' and p.in_stock and p.status = 'active'
   and p.w_cm is not null and p.d_cm is not null
   and coalesce(p.image_url_hd, p.image_url) is not null and coalesce(p.photo_alive, true)
   and e.payload->'model'->>'primary_color' in ({_lit(UNI_RUG['colors'])})
   and e.payload->'model'->'specific'->>'rug_pattern' in ({_lit(UNI_RUG['patterns'])})
   {flag}
 order by coalesce(e.quality, 0) desc, 1"""


def universal_rugs(have: set, styles: tuple = STYLES, rows: list | None = None) -> list[dict]:
    """ЗАПАСНОЙ КОВЁР СТИЛЯ — ОБЩАЯ ФУНКЦИЯ ОБОИХ ЗАПРОСОВ (T-20261107-11/2): стилям из `styles`, у которых нет ни одного своего
    ковра (`have` — стили, которые свой запрос уже дал), — нейтральные универсальные ковры строками `_row` со стилем этого стиля
    и отметкой `rug_universal`. У кого свой ковёр есть — ничего (5 стилей гостиной не меняются). `rows` — строки
    `universal_rug_sql` (None — из базы, и только когда есть кому).

    НЕСОВПАДЕНИЕ «СТУПЕНЬ ↔ БАЛЛ» (решит ведущий отдельно): «свой ковёр» у дозаполнения вариантов — ступень обогащения
    (`demo_fill.RUG_SQL`: `payload.model.styles` «высокая»/«средняя»), у ленты — балл стиля ≥ `IN_STYLE_MIN` (`rug_sql`).
    Отбор ленты строже, и стиль может иметь свой ковёр в варианте, но не в ленте (или наоборот) — тогда запасной включится
    только в той, где своих нет. Критерии «в стиле» здесь не меняются."""
    miss = [s for s in styles if s not in have]
    if not miss:
        return []
    if rows is None:
        from mesh_queue import db
        rows = db(universal_rug_sql())
    base = [p for p in map(_row, rows) if p]
    return [dict(p, style=s, rug_universal=True) for s in miss for p in base]


def rug_pool(ok=None, band: dict | None = None) -> list[dict]:
    """Ковры ленты замен: тот же отбор `pick` (до `PER_GROUP` прошедших на стиль, конверт роли — `ENVELOPE['ковёр']` по длинной
    стороне, сперва — в полосе `band`), `ok` — проверки сборки ковра (`flat215_demo.swap_rug_ok`). Стилю без своих ковров —
    запасной нейтральный (`universal_rugs`)."""
    from mesh_queue import db
    rows = [p for p in map(_row, db(rug_sql())) if p]
    return pick(rows + universal_rugs({p['style'] for p in rows}), ok, band=band)


# Подушки (T-20261107-25/4): в ленту шли только подушки наборов — у неоклассики ни одной; из каталога тем же отбором, что шторы
SOFT_FEED_ROLES = ('шторы', 'подушка')


def soft_sql(role: str, in_style_min: float = IN_STYLE_MIN) -> str:
    """ЛЕНТА МЯГКОГО ИЗ КАТАЛОГА (style-color-01 шаг 2б, T-20261107-25/3): шторы приходили в ленту только из товаров наборов —
    у сканди одна (бирюзовая), у джапанди ни одной. Мягкому места на полу и модели не положено (`flat215_demo.soft_feed_row`),
    поэтому ни конверта, ни меша не требуем: в продаже, живое фото, ссылка и цена, балл стиля ≥ порога ленты, как у ковров.
    Порядок — как у ковров, но фото товара в интерьере или с другими товарами — после снимков товара (T-25/4: в ленте подушек
    плитка-комната вместо подушки; такое фото хуже и для «Улучшить фото»). Форма строки — как у `pool_sql` (`_row`); габариты,
    которых нет, — 0 (мягкое их не меряет)."""
    return f"""
with cand as (
  select p.shop_mid||':'||p.external_id as sku, s.style, coalesce(p.name,'') as name, coalesce(p.shop,'') as shop,
         coalesce(p.image_url_hd, p.image_url) as img, p.url, coalesce(p.price_shown_rub, p.price_rub) as price,
         coalesce(p.w_cm, 0) as w_cm, coalesce(p.d_cm, 0) as d_cm, coalesce(p.h_cm, 0) as h_cm, coalesce(e.quality, 0) as q,
         coalesce((ps.scores->>s.style)::numeric, 0) as st_score, coalesce(ps.universal, false) as uni,
         coalesce(e.payload->'model'->>'image_type', '') in ('товар_в_интерьере', 'несколько_товаров') as scene
    from products p
    left join product_enrichment e using (shop_mid, external_id)
    join product_style_scores ps using (shop_mid, external_id)
    cross join lateral (select unnest(array[{_lit(STYLES)}]) as style) s
   where p.cat_role = {_lit([role])} and p.in_stock and p.status = 'active'
     and p.url is not null and coalesce(p.price_shown_rub, p.price_rub) is not null
     and coalesce(p.image_url_hd, p.image_url) is not null and coalesce(p.photo_alive, true)
     and coalesce((ps.scores->>s.style)::numeric, 0) >= {in_style_min}),
ranked as (
  select *, row_number() over (partition by style order by uni asc, scene asc, q desc, st_score desc, price asc nulls last, sku) as rn
    from cand)
select sku, sku, {_lit([role])}, style, {_lit([role])}, name, shop, img, url, coalesce(price::text,''), w_cm, d_cm, h_cm
  from ranked order by style, rn"""


CURTAIN_DENY = re.compile(r'рулон|римск|кафе|для кухни|плисс|жалюзи', re.I)
SIZE_RE = re.compile(r'\s*\d+(?:[.,]\d+)?\s*[xхX×*]\s*\d+(?:[.,]\d+)?\s*(?:см)?', re.I)


def curtain_fits(p: dict) -> bool:
    """Штора гостиной закрывает окно: полотно до пола (h ≥ 250) и ткани ≥ 250 см (комплект «2 шт» — 2×w) — правило сборщика
    гостиной (`compose2.pick2`, ветка штор), рулонные/римские/кафе — нет (`rules/bedroom-composition.json` `шторы.deny`:
    рулонка 55 см на окно 240). Без высоты или ширины — нет: размер не додумываем (Р1)."""
    name = p.get('name') or ''
    if CURTAIN_DENY.search(name) or not (p.get('h') and p.get('w')):
        return False
    cloth = p['w'] * (2 if re.search(r'2\s*шт', name, re.I) else 1)
    return p['h'] >= 250 and cloth >= 250


def model_key(name: str) -> str:
    """Одна строка ленты на модель и цвет: размеры из названия («260x275 см») не различают товар для показа."""
    return re.sub(r'\s+', ' ', SIZE_RE.sub(' ', (name or '').lower())).strip()


def soft_pool(role: str, ok=None, per_group: int = PER_GROUP) -> list[dict]:
    """Мягкое ленты замен из каталога: по стилю — до `per_group` прошедших (шторы — `curtain_fits`; `ok(p)` — живое фото и цвет
    стиля, проверки сборки `flat215_demo.soft_pool_ok`), один размер на модель и цвет (`model_key`), порядок запроса. Модели
    нет: `msid` пуст."""
    from mesh_queue import db
    out, per, seen = [], {}, set()
    for p in map(_row, db(soft_sql(role))):
        if not p or per.get(p['style'], 0) >= per_group:
            continue
        p['msid'] = None
        if role == 'шторы' and not curtain_fits(p):
            continue
        k = (p['style'], model_key(p['name']))
        if k in seen or (ok is not None and not ok(p)):
            continue
        seen.add(k)
        per[p['style']] = per.get(p['style'], 0) + 1
        out.append(p)
    return out


def _row(r: list) -> dict | None:
    if len(r) != 13:
        return None
    sku, rep, sub, style, role, name, shop, img, url, price, w, d, h = r
    return {'sid': sku.replace(':', '_', 1), 'msid': rep.replace(':', '_', 1),
            'sub': sub, 'style': style, 'role': role, 'name': name, 'shop': shop,
            'img': img, 'url': url,
            'price': int(float(price)) if price else None,
            'w': float(w), 'd': float(d), 'h': float(h)}


def fits(p: dict, ceiling_cm: float | None = None) -> bool:
    """Фото, ширина и глубина есть, ширина — в конверте роли (`ENVELOPE`). `ceiling_cm` — потолок комнаты (нет — базовый)."""
    # ЛЮСТРЫ В ЛЕНТЕ НЕТ (на плане она не стоит, `demo_fill`). Появится роль — длинный подвес не пройдёт: та же норма
    # вылета, что у сборки и лечения (catalog-holes-bank Н2в, `compose_gates.pendant_out`; регулируемость здесь не видна)
    if p.get('role') == 'люстра':
        import compose_gates as _CG
        if _CG.pendant_out(p.get('h'), None, None, None, p.get('drop_min'), ceiling_cm):
            return False
    lo, hi = ENVELOPE.get(p.get('role'), (0, 0))
    return bool(p.get('img') and p.get('w') and p.get('d')) and lo <= p['w'] <= hi


def pick(rows: list[dict], ok=None, per_group: int = PER_GROUP, band: dict | None = None,
         ceiling_cm: float | None = None) -> list[dict]:
    """Группа «подкатегория × стиль» в порядке запроса → до `per_group` прошедших проверки: сперва по одному товару на модель
    (`msid`), потом цвета тех же моделей. `ok(p)` — проверки сборки (модель на сервере, цвет, `unfit`); зовётся лениво, пока
    группа не набрана, и один раз на товар (товар повторяется в каждом своём стиле).

    СПЕРВА — В ПОЛОСЕ РАЗМЕРА (`band` — `slot_rules.slot_band` комнаты демо; план demo-20 часть В, владелец 22.10 TG 793): лента
    по умолчанию показывает только подходящих по размеру, а 30 мест группы раньше занимали лучшие по качеству любого размера —
    тв-тумб «современный» в полосе с моделью на сервере 103, а в ленту доходило 19. Внутри «в полосе» и «вне» порядок прежний."""
    seen: dict = {}

    def good(p: dict) -> bool:
        if p['sid'] not in seen:
            seen[p['sid']] = fits(p, ceiling_cm) and (ok is None or bool(ok(p)))
        return seen[p['sid']]

    from slot_rules import in_band
    groups: dict = {}
    for p in rows:
        groups.setdefault((p['sub'], p['style']), []).append(p)
    out = []
    for grp in groups.values():
        if band:
            grp = sorted(grp, key=lambda p: not in_band(p, band.get(p['role'])))   # устойчивая: порядок внутри сохраняется
        took, models = [], set()
        for p in grp:                                   # сперва разные модели: лучший прошедший товар каждой
            if len(took) < per_group and p['msid'] not in models and good(p):
                took.append(p)
                models.add(p['msid'])
        taken = {p['sid'] for p in took}
        for p in grp:                                   # потом цвета уже взятых моделей
            if len(took) < per_group and p['sid'] not in taken and p['msid'] in models and good(p):
                took.append(p)
                taken.add(p['sid'])
        out.extend(took)
    return out


def pool(ok=None, roles: tuple | None = None, band: dict | None = None, ceiling_cm: float | None = None) -> list[dict]:
    """Пул ленты замен; `roles` — только эти роли (отбор тот же, проверки `ok` — только им: счёт банкеток стиля до расстановки,
    `flat215_demo.bench_pool`, demo-19 Г2); `band` — полоса размера комнаты (в группе сперва подходящие, `pick`); `ceiling_cm` —
    потолок квартиры (`flat215_demo.demo_ceiling`; нет — базовый) для гейта подвеса."""
    from mesh_queue import db
    return pick([p for p in map(_row, db(pool_sql())) if p and (roles is None or p['role'] in roles)], ok, band=band,
                ceiling_cm=ceiling_cm)


def pool_top() -> list[dict]:
    """Пул ДОЗАПОЛНЕНИЯ вариантов (`demo_fill.load_pool`) — прежний запрос (30 лучших до проверок, порядок базы). Под показываемые
    варианты стилей настроены камеры и сняты кадры (demo-18, ведущий 18.10): смена пула дозаполнения сменила бы варианты —
    это отдельное решение."""
    from mesh_queue import db
    return [p for p in map(_row, db(pool_sql(top=PER_GROUP))) if p]


def report(items: list[dict] | None = None) -> list[dict]:
    """Сводка пула для запуска без флагов (из fd87f948; при добавлении `pool_top` в 4bb8da72 выпала случайно). Без `ok` —
    до проверок сборки (модель на сервере, цвет): только конверт и габариты, т.е. верхняя граница того, что дойдёт до ленты."""
    items = items if items is not None else pool()
    models = {i['msid'] for i in items}
    groups: dict[tuple, int] = {}
    for i in items:
        groups[(i['sub'], i['style'])] = groups.get((i['sub'], i['style']), 0) + 1
    print(f'пул замены: товаров {len(items)}, моделей (уникальных мешей) {len(models)}, '
          f'групп «подкатегория×стиль» {len(groups)}, лимит на группу {PER_GROUP}')
    by_role: dict[str, int] = {}
    for i in items:
        by_role[i['role']] = by_role.get(i['role'], 0) + 1
    print('по ролям:', dict(sorted(by_role.items(), key=lambda kv: -kv[1])))
    print(f'вес моделей ≈ {len(models) * 7.6 / 1024:.1f} ГБ')
    return items


def _selftest() -> int:
    bad = 0
    q = pool_sql()
    # порог — из правил, не литерал (иначе смена in_style_min в JSON роняла бы селфтест)
    for must in ('functional_subtype', 'mesh_status', 'product_style_scores', f'>= {IN_STYLE_MIN}',
                 'mesh_family_rep', 'partition by sub, style', 'order by uni asc, q desc, st_score desc',
                 'order by sub, style, rn'):
        if must not in q:
            bad += 1
            print('  FAIL: в запросе нет', must)
    if 'rn <=' in q:
        bad += 1
        print('  FAIL: срез группы в запросе — до проверок сборки (demo-18 п.1)')
    if _lit(["a'b"]) != "'a''b'":
        bad += 1
        print('  FAIL: экранирование кавычек')
    if 'ковёр' in ROLES:
        bad += 1
        print('  FAIL: плоские роли (ковёр) в пул моделей не входят')
    if ENVELOPE.get('диван') != tuple(RULES['room_fit_envelope_cm']['диван']) or 'ваза' not in ENVELOPE:
        bad += 1
        print('  FAIL: конверт не из rules/demo-swap.json')
    # отбор: модель A — три цвета подряд (лучшие), B и C — по одному; C без модели на сервере; D шире комнаты
    row = lambda sid, msid, w=170: {'sid': sid, 'msid': msid, 'sub': 'диван', 'style': 'сканди', 'role': 'диван',  # noqa: E731
                                    'img': 'i', 'w': w, 'd': 90, 'h': 80, 'name': sid}
    rows = [row('a1', 'A'), row('a2', 'A'), row('a3', 'A'), row('c1', 'C'), row('d1', 'D', 260), row('b1', 'B')]
    calls: list = []
    ok = lambda p: calls.append(p['sid']) or p['msid'] != 'C'  # noqa: E731
    got = [p['sid'] for p in pick(rows + [dict(r, style='лофт') for r in rows], ok, per_group=3)]
    if got[:3] != ['a1', 'b1', 'a2']:
        bad += 1
        print('  FAIL: сперва разные модели, потом цвета, мимо непрошедших:', got[:3])
    if len(got) != 6 or len(calls) != len(set(calls)):
        bad += 1
        print('  FAIL: группа на стиль своя, проверка — один раз на товар:', got, calls)
    if 'd1' in calls:
        bad += 1
        print('  FAIL: шире конверта — отсев до дорогих проверок')
    if [p['sid'] for p in pick(rows, ok, per_group=30)] != ['a1', 'b1', 'a2', 'a3']:
        bad += 1
        print('  FAIL: добор до лимита — все прошедшие')
    if 'where rn <= 30 order by cat_role, style, sku' not in pool_sql(top=30):
        bad += 1
        print('  FAIL: пул дозаполнения — прежний запрос (срез группы до проверок, прежний порядок)')
    # ЛЮСТРА (catalog-holes-bank Н2в): в ленте её нет; если роль появится — подвес длиннее 60 см не проходит `fits`
    _env = ENVELOPE.pop('люстра', None)
    ENVELOPE['люстра'] = (0, 300)
    lu = lambda h: {'role': 'люстра', 'img': 'i', 'w': 60, 'd': 60, 'h': h}  # noqa: E731
    if not (fits(lu(50)) and fits(lu(60)) and not fits(lu(61)) and not fits(lu(230))):
        bad += 1
        print('  FAIL: длинная люстра (вылет > 60 см) не должна проходить в ленту замен')
    if not (fits(lu(80), ceiling_cm=300) and not fits(lu(80)) and not fits(lu(45), ceiling_cm=250)
            and [p['sid'] for p in pick([dict(lu(80), sid='L', msid='L', sub='s', style='x')], None, ceiling_cm=300)] == ['L']
            and not pick([dict(lu(80), sid='L', msid='L', sub='s', style='x')], None)):
        bad += 1
        print('  FAIL: потолок квартиры — норма вылета «потолок − 210» (300 → 80 годна, 270 → нет, 250 → 45 нет), и через pick')
    ENVELOPE.pop('люстра')
    if _env is not None:
        ENVELOPE['люстра'] = _env
    # ковры (demo-18 п.2): свой запрос — порог стиля ленты, длинная сторона в `w`, модель = товар; отбор — тот же `pick`
    rq = rug_sql()
    for must in (f">= {IN_STYLE_MIN}", "cat_role = 'ковёр'", 'greatest(p.w_cm, p.d_cm) as w_cm', 'least(p.w_cm, p.d_cm) as d_cm',
                 'photo_alive', 'order by uni asc, q desc, st_score desc', 'order by style, rn'):
        if must not in rq:
            bad += 1
            print('  FAIL: в запросе ковров нет', must)
    if 'mesh_status' in rq or 'rn <=' in rq:
        bad += 1
        print('  FAIL: ковру модель не нужна, срез — после проверок')
    rug = _row(['112923:7', '112923:7', 'ковёр', 'сканди', 'ковёр', 'Ковер 160x230', 'divan', 'i', 'u', '9990', '230', '160', '1'])
    if not rug or rug['msid'] != rug['sid'] or rug['w'] != 230 or rug['price'] != 9990:
        bad += 1
        print('  FAIL: строка ковра — модель = товар, длинная сторона в w:', rug)
    rugs = [dict(rug, sid=f'r{i}', msid=f'r{i}', w=w) for i, w in enumerate((230, 170, 290, 200))]
    if [p['sid'] for p in pick(rugs)] != ['r0', 'r2', 'r3']:
        bad += 1
        print('  FAIL: конверт ковра — по длинной стороне 180–300')
    # запасной нейтральный ковёр (T-20261107-11/2): только стилям без своих, с отметкой; есть свои у всех — пусто, база не нужна
    urow = ['112923:9', '112923:9', 'ковёр', '', 'ковёр', 'Ковер Серый 200x300', 'divan', 'i', 'u', '5000', '300', '200', '1']
    uni = universal_rugs({'лофт', 'сканди'}, styles=('лофт', 'сканди', 'неоклассика'), rows=[urow])
    if [(p['style'], p['sid'], p.get('rug_universal')) for p in uni] != [('неоклассика', '112923_9', True)]:
        bad += 1
        print('  FAIL: запасной ковёр — только стилю без своих, со стилем и отметкой:', uni)
    if universal_rugs(set(STYLES), rows=None) != []:
        bad += 1
        print('  FAIL: у всех стилей свои ковры — запасного нет (и запроса к базе нет)')
    uq = universal_rug_sql()
    for must in ("'серый'", "'однотонный'", 'ps.universal', "rug_pattern", 'photo_alive', "cat_role = 'ковёр'"):
        if must not in uq:
            bad += 1
            print('  FAIL: в запросе запасного ковра нет', must)
    own_r = dict(rug, sid='own', msid='own', style='сканди')
    mixed = pick([own_r] + uni)
    if [(p['style'], p['sid']) for p in mixed] != [('сканди', 'own'), ('неоклассика', '112923_9')]:
        bad += 1
        print('  FAIL: лента — свой ковёр стиля остаётся, запасной — своей группой стиля без своих:', mixed)
    # полоса (demo-20 В): в группе сперва подходящие по размеру, порядок внутри прежний; без полосы — как было
    bnd = {'диван': {'lo': 160, 'hi': 200, 'side': 'w'}}
    rows_b = [row('w1', 'W', 150), row('n1', 'N', 180), row('w2', 'X', 150), row('n2', 'Y', 190)]
    if [p['sid'] for p in pick(rows_b, per_group=3, band=bnd)] != ['n1', 'n2', 'w1']:
        bad += 1
        print('  FAIL: полоса — сперва в полосе по порядку, потом остальные:', [p['sid'] for p in pick(rows_b, per_group=3, band=bnd)])
    if [p['sid'] for p in pick(rows_b, per_group=3)] != ['w1', 'n1', 'w2']:
        bad += 1
        print('  FAIL: без полосы порядок прежний')
    q2 = pool_sql(any_mesh=True)
    if 'mesh_status' in q2 or 'photo_alive' not in q2 or f'>= {IN_STYLE_MIN}' not in q2:
        bad += 1
        print('  FAIL: запрос «и без меша» — те же ворота, кроме готовности меша')
    print(f'demo_swap_pool selftest: случаев 20, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    items = report()
    if '--json' in sys.argv:
        path = sys.argv[sys.argv.index('--json') + 1]
        json.dump(items, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('пул выгружен →', path)
