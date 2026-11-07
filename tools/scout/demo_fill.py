#!/usr/bin/env python3
"""Дозаполнение вариантов демо ДО расстановки (план conv-09).

ЗАЧЕМ. Ночное лечение банка комплектов с конца сентября стоит на предохранителе («затронуло бы
N из 126, предел 25 %»), поэтому снятые с продажи товары из банка не уходят. Сборка демо их просто
выбрасывала (`drop_unavailable`): 545–567 позиций за прогон, варианты по 2–7 предметов, ковра нет
ни в одном. Хуже того, расстановку считал `solver_run.py` по банку НА ДИСКЕ — место под снятый
товар в комнате оставалось, а самого товара на странице не было.

ЧТО ДЕЛАЕМ. Для выбранных вариантов — и только для них, банк не переписываем: каждую роль ядра и
каждую расставляемую роль, где товара нет, он снят или у него нет модели, заменяем из ТОГО ЖЕ пула,
что лента замен на странице (`demo_swap_pool`: в наличии, есть модель и все габариты, стиль
«высокая/средняя»), ковёр — из плоского пула (модель ему не нужна). Каждая кандидатура проходит
те же ворота, что лечение (`sets_incremental._slot_ok`: живое фото, наличие, футпринт, конверт
слота, контракт ковра). Журнал замен едет в demo-data.json.

СВОЙ ЗАПАСНОЙ — ПЕРВЫМ (T-20261023-10, лофт 23.10). Роль ЯДРА ушла — сперва запасные самого набора (`alternates` банка:
их подобрала сборка под этот стиль, метраж и бюджет), потом пул. Ворота те же: в продаже, живое фото, модель готова и
подходит по цвету, конверт комнаты, пропорции. Без этого диван «Этен Мини» лофта ушёл, в ленте замен «диван/лофт» пусто,
и стиль выпал из демо, хотя в наборе лежал свой «Викс» в продаже и с моделью.

  ~/venvs/scout/bin/python demo_fill.py --selftest
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Ядро гостиной: без любого из них вариант не публикуется (план conv-09 п.3). Свет на полу — торшер:
# люстра на плане не стоит.
CORE = ('диван', 'столик', 'тв-тумба', 'ковёр', 'торшер')
# Роли, которые демо ставит на пол и которые есть смысл заменять.
FILL_ROLES = set(CORE) | {'кресло', 'стеллаж', 'комод', 'пуф', 'кашпо', 'витрина', 'банкетка',
                          'стол обеденный', 'стул'}
NOMESH = {'ковёр', 'ковер'}
# HARD-контракт зонного ковра (ADR-0120): короткая сторона не меньше, длинная — не короче дивана. Одно правило для дозаполнения
# вариантов (`make_gate`) и ленты замен ковра (`flat215_demo.swap_rug_ok`, demo-18 п.2)
RUG_SHORT_MIN = 140


def rug_fits(w: float, d: float, sofa: float = 0) -> bool:
    """Ковёр годен зоне дивана: короткая ≥ `RUG_SHORT_MIN`, длинная ≥ ширины дивана (дивана нет — без второго условия)."""
    return min(w, d) >= RUG_SHORT_MIN and not (sofa and max(w, d) < sofa)

# СТИЛЬ КОВРА ДОЗАПОЛНЕНИЯ — СТУПЕНЬ ОБОГАЩЕНИЯ, у ленты (`demo_swap_pool.rug_sql`) — БАЛЛ ≥ порога: несовпадение известно,
# решит ведущий отдельно (T-20261107-11/2); запасной нейтральный — `demo_swap_pool.universal_rugs`, общий для обоих
RUG_SQL = """
select p.shop_mid||':'||p.external_id, coalesce(p.name,''), coalesce(p.shop,''),
       coalesce(p.image_url_hd, p.image_url), p.url, coalesce(coalesce(p.price_shown_rub, p.price_rub)::text,''), p.w_cm, p.d_cm, s.style
  from products p
  join product_enrichment e using (shop_mid, external_id)
  cross join lateral (select unnest(array['лофт','сканди','джапанди','минимализм','неоклассика','современный']) as style) s
 where p.cat_role = 'ковёр' and p.in_stock and p.status = 'active'
   and p.w_cm is not null and p.d_cm is not null and coalesce(p.image_url_hd, p.image_url) is not null
   and e.payload->'model'->'styles'->>s.style in ('высокая','средняя')
 order by coalesce(e.quality,0) desc, 1"""


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role)


# ЦВЕТ ЗАМЕНЫ НЕОБЯЗАТЕЛЬНОГО (T-20261107-11/3): дозаполнение подставляло стулья «Glasar Совы желтый» в неоклассику на место
# снятого кресла, а лента мягкого — подушку «Саона Велюр Оранжевый/Синий». Оценщик цвета один на все сборщики
# (`compose_common.color_eval`, правила `rules/style-color-policy.json`): у второстепенных сидений и мягкого текстиля ЯРКИЙ
# цвет с ярусом discouraged/forbidden — замену не берём. Только яркий (ведущий: «не брать vivid»): приглушённый discouraged
# (оливковые стулья джапанди) отсевом сменил бы опубликованный стиль — это решение политики, не этой правки. Роль
# необязательная: лучше на стул меньше, чем чужой цвет; ядро так не режем (дыра в ядре снимает вариант). Названия ролей
# демо → роли политики: «подушка» у демо, «подушки» у правил.
COLOR_GROUPS = ('secondary_seating', 'soft_textile')
COLOR_ROLE = {'подушка': 'подушки', 'покрывало': 'плед', 'ковер': 'ковёр'}


def color_refused(role: str, c: dict, style: str | None) -> str | None:
    """Причина не брать кандидата по цвету (ярус discouraged/forbidden в группах `COLOR_GROUPS`); None — годен. Роли вне
    групп и стиль без правил — None (как было)."""
    import compose_common as CC
    b = base_role(role or '')
    e = CC.color_eval(c, COLOR_ROLE.get(b, b), style or '')
    if e['group'] in COLOR_GROUPS and e['cat'] == 'vivid' and e['tier'] in ('discouraged', 'forbidden'):
        return e['why']
    return None


def load_pool() -> list[dict]:
    """Пул кандидатов: объёмные — `demo_swap_pool.pool_top()` (прежний отбор 30, demo-18), ковры — плоский запрос."""
    from demo_swap_pool import pool_top
    out = []
    for p in pool_top():
        mid, eid = p['sid'].split('_', 1)
        out.append({**p, 'mid': mid, 'eid': eid})
    from mesh_queue import db
    have = set()
    for r in db(RUG_SQL):
        if len(r) != 9:
            continue
        sku, name, shop, img, url, price, w, d, style = r
        mid, eid = sku.split(':', 1)
        have.add(style)
        out.append({'mid': mid, 'eid': eid, 'role': 'ковёр', 'style': style, 'name': name, 'shop': shop,
                    'img': img, 'url': url, 'price': int(float(price)) if price else None,
                    'w': float(w), 'd': float(d), 'h': 1.0})
    # стилю без единого своего ковра — запасной нейтральный (общая функция с лентой, T-20261107-11/2); у кого свои есть — как было
    from demo_swap_pool import universal_rugs
    for p in universal_rugs(have):
        mid, eid = p['sid'].split('_', 1)
        out.append({'mid': mid, 'eid': eid, 'role': 'ковёр', 'style': p['style'], 'name': p['name'], 'shop': p['shop'],
                    'img': p['img'], 'url': p['url'], 'price': p['price'], 'w': p['w'], 'd': p['d'], 'h': 1.0,
                    'rug_universal': True})
    return out


def need_reason(role: str, it: dict | None, media, has_mesh) -> str | None:
    """Почему позицию надо заменить; None — позиция годна."""
    if not it or not it.get('mid'):
        return 'нет товара'
    if base_role(role) == 'ковёр':
        try:
            import rug_kids
            if any(rug_kids.is_kids_rug(it.get(k)) for k in ('img_hd', 'img')):
                return 'детский ковёр (по картинке)'   # demo-05, 17.10: уже стоящий в варианте ковёр тоже перепроверяется
        except Exception:  # noqa: BLE001 — без кэша решения ковёр не трогаем
            pass
    from catalog_rules import availability
    if availability(media(it.get('mid'), it.get('eid'))) == 'unavailable':
        return 'снят с продажи'               # `unknown` (фид не приехал) — товар не трогаем
    if base_role(role) not in NOMESH and not has_mesh(it):
        return 'нет модели'
    return None


def own_spares(s: dict, role: str, media, exclude: set) -> list[dict]:
    """Свои запасные набора для роли (`s['alternates'][роль]`) в порядке сборки, карточкой кандидата из каталога (в запасных
    банка только артикул, имя и цена). Уже стоящие в наборе (`exclude`) пропускаем."""
    out = []
    for a in (s.get('alternates') or {}).get(base_role(role)) or []:
        mid, eid = str((a or {}).get('mid') or ''), str((a or {}).get('eid') or '')
        if not mid or not eid or f'{mid}:{eid}' in exclude:
            continue
        m = media(mid, eid) or {}
        out.append({'mid': mid, 'eid': eid, 'role': base_role(role), 'style': s.get('style'),
                    'name': m.get('name') or a.get('name'), 'shop': m.get('shop'), 'img': m.get('img'), 'url': m.get('url'),
                    'price': m.get('price') or a.get('price'), 'w': m.get('w'), 'd': m.get('d'), 'h': m.get('h'),
                    'dia': m.get('dia'), 'spare': True})
    return out


def candidates(role: str, old: dict | None, style: str | None, pool: list[dict], exclude: set,
               env: dict | None = None, avoid: set | None = None) -> list[dict]:
    """Кандидаты той же роли и стиля. Близость к ЦЕЛИ по ширине (прежний товар, а если роли не было —
    середина конверта слота комнаты), шагом 10 см; внутри шага — порядок пула (качество обогащения), при
    замене — ближе по цене. Раньше для отсутствующей роли побеждал самый дешёвый (Codex 13.10)."""
    b = base_role(role)
    out = [p for p in pool if p['role'] == b and p.get('style') == style
           and f"{p['mid']}:{p['eid']}" not in exclude]
    lo, hi = (env or {}).get(b, (0, 0))
    target = (old or {}).get('w') or ((lo + hi) / 2 if hi else 0)
    op = (old or {}).get('price') or 0
    side = (lambda p: max(p['w'], p['d'])) if b == 'ковёр' else (lambda p: p['w'])
    # РАЗНООБРАЗИЕ (13.10): один и тот же ковёр в четырёх стилях из пяти — не «как от дизайнера». Товар,
    # уже взятый в другой вариант, идёт после неиспользованных; ворота всё равно проверяют посадку.
    avoid = avoid or set()
    out.sort(key=lambda p: (f"{p['mid']}:{p['eid']}" in avoid,
                            int(abs(side(p) - target) // 10) if target else 0,
                            abs((p.get('price') or 0) - op) if op else 0))
    return out


NB_TIERS = ('preferred', 'allowed')


def neighbour_fill(role: str, old: dict | None, s: dict, pool: list[dict], used: set, env, avoid, ok, card, items: dict,
                   neighbours=None) -> tuple:
    """РОЛЬ ЯДРА У СОСЕДНЕГО СТИЛЯ (T-20261107-11/6, ведущий: общее правило вместо «для одной ситуации»). В своём стиле годного
    товара роли ядра нет (неоклассика 07.11: единственный столик в конверте — Gatwick, его модель в карантине) — дыра снимала
    вариант целиком (`incomplete_styles`). Берём товар роли у соседа по `style-axes.json:confusable_pairs`
    (`demo_room.neighbour_styles`, порядок пар; у неоклассики — современный): те же ворота комнаты (`ok`) и порядок кандидатов
    (`candidates`), плюс цвет ДЛЯ СТИЛЯ-ПОЛУЧАТЕЛЯ (`compose_common.color_eval`) — только preferred/allowed: чужой товар не
    должен спорить со стилем ещё и цветом. Зовётся только при дыре в ядре — у стилей с полным ядром ничего не меняется.
    → (карточка | None, имя соседа | None)"""
    import compose_common as CC
    style = s.get('style') or ''
    if neighbours is None:
        import demo_room
        neighbours = demo_room.neighbour_styles
    b = base_role(role)
    rest = {r: v for r, v in items.items() if r != role}
    for nb in neighbours(style):
        for c in candidates(role, old, nb, pool, used, env, avoid):
            if CC.color_eval(c, COLOR_ROLE.get(b, b), style)['tier'] not in NB_TIERS:
                continue
            if ok(role, c, s, rest):
                repl = card(c, old or {})
                repl['style_from'] = nb
                return repl, nb
    return None, None


def fill_set(s: dict, pool: list[dict], ok, card, media, has_mesh, env: dict | None = None,
             avoid: set | None = None, own: bool = True) -> list[dict]:
    """Заменить негодные и добавить недостающие роли ядра. Меняет `s['items']`; → журнал замен.
    `own=False` — без своих запасных набора, только пул (прежнее дозаполнение: запасной вариант, если со своим запасным
    набор не расставился — `flat215_demo.fill_banks`)."""
    items = s.setdefault('items', {})
    journal = []
    used = {f"{it.get('mid')}:{it.get('eid')}" for it in items.values() if it}
    roles = [r for r in items if base_role(r) in FILL_ROLES] + [r for r in CORE if r not in items]
    # диван первым: от его ширины зависит контракт ковра
    roles.sort(key=lambda r: (base_role(r) != 'диван', base_role(r) == 'ковёр'))
    for role in roles:
        old = items.get(role)
        why = need_reason(role, old, media, has_mesh)
        if not why:
            continue
        repl = spare = uni = None
        own_c = own_spares(s, role, media, used) if own and base_role(role) in CORE else []
        # уже взятый в другой вариант запасной — после пула (разнообразие между стилями, как у `candidates`), но до дыры
        k = lambda c: f"{c['mid']}:{c['eid']}" in (avoid or ())  # noqa: E731
        core = base_role(role) in CORE
        for c in ([c for c in own_c if not k(c)] + candidates(role, old, s.get('style'), pool, used, env, avoid)
                  + [c for c in own_c if k(c)]):
            if not core and color_refused(role, c, s.get('style')):
                continue                 # необязательное яркое не в стиле — не берём (T-20261107-11/3)
            if ok(role, c, s, {r: v for r, v in items.items() if r != role}):
                repl, spare, uni = card(c, old or {}), c.get('spare'), c.get('rug_universal')
                if uni:                  # запасной нейтральный ковёр стиля (`demo_swap_pool.universal_rugs`) — с отметкой
                    repl['rug_universal'] = True
                break
        nb = None
        if repl is None and core:
            repl, nb = neighbour_fill(role, old, s, pool, used, env, avoid, ok, card, items)
        sku = lambda it: f"{it.get('mid')}:{it.get('eid')}" if it else None  # noqa: E731
        journal.append({'role': role, 'from': (old or {}).get('name'), 'from_sku': sku(old),
                        'to': (repl or {}).get('name'), 'to_sku': sku(repl), 'reason': why,
                        **({'source': 'запасной набора'} if spare else {}),
                        **({'source': f'соседний стиль: {nb}'} if nb else {}),
                        **({'rug_universal': True} if uni else {})})
        if repl:
            items[role] = repl
            used.add(f"{repl.get('mid')}:{repl.get('eid')}")
        elif old is not None:
            items.pop(role)          # заменить нечем — честно нет, а не мёртвый товар
    return journal


def make_gate(env: dict, media, alive_img, footprint_known, proportions=None, subtype=None):
    """Ворота кандидата ДЛЯ КОМНАТЫ ДЕМО — те же правила, что у лечения банка (`sets_incremental._slot_ok`),
    но без импорта `compose2`: тот при загрузке пересобирает все комплекты и пишет файл (ловушка 13.10).
    Конверт — под реальную комнату демо (`flat215_demo.DEMO_ENV`), а не под метраж комплекта."""
    def gate(role: str, c: dict, s: dict, chosen: dict) -> bool:
        b = base_role(role)
        from catalog_rules import availability
        m = media(c.get('mid'), c.get('eid'))
        if availability(m) != 'available':     # новую замену при «не знаю» не берём
            return False
        if not alive_img(c.get('img')):
            return False
        if not footprint_known(m):
            return False
        w, d = c.get('w') or 0, c.get('d') or 0
        side = max(w, d) if b == 'ковёр' else w
        lo, hi = env.get(b, (0, 10 ** 6))
        if not (lo <= side <= hi):
            return False
        if b == 'ковёр':
            if not rug_fits(w, d, (chosen.get('диван') or {}).get('w') or 0):
                return False
        # ПРОПОРЦИИ К УЖЕ ВЫБРАННОМУ (столик к дивану и т. п.): те же жёсткие правила, что у сборки и
        # лечения (`proportions.check`); без них замена могла поставить столик шире дивана (Codex 13.10)
        if proportions is not None:
            ctx = {'chosen': chosen, 'wall': None,
                   'corner_sofa': 'углов' in str((chosen.get('диван') or {}).get('name', '')).lower()}
            ok, _bonus, _notes = proportions(b, c, ctx, subtype(b, c) if subtype else None)
            if not ok:
                return False
        return True
    return gate


def core_missing(s: dict) -> list[str]:
    items = s.get('items') or {}
    return [r for r in CORE if not items.get(r)]


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    alive = {('1', 'sofa'), ('1', 'tv'), ('2', 'rug'), ('2', 'table'), ('3', 'lamp')}
    media = lambda mid, eid: {'state': 'available' if (mid, eid) in alive else 'gone'}  # noqa: E731
    has_mesh = lambda it: it.get('eid') != 'nomesh'  # noqa: E731
    gate = lambda role, c, s, chosen: c['w'] < 300  # noqa: E731
    card = lambda c, old: {'mid': c['mid'], 'eid': c['eid'], 'name': c['name'], 'w': c['w'], 'd': c.get('d'), 'price': c.get('price')}  # noqa: E731
    pool = [
        {'mid': '2', 'eid': 'table', 'role': 'столик', 'style': 'лофт', 'name': 'Столик Б', 'w': 90, 'd': 50, 'price': 9000},
        {'mid': '2', 'eid': 'rug', 'role': 'ковёр', 'style': 'лофт', 'name': 'Ковёр 200×160', 'w': 200, 'd': 160, 'price': 12000},
        {'mid': '9', 'eid': 'huge', 'role': 'ковёр', 'style': 'лофт', 'name': 'Ковёр 400×300', 'w': 400, 'd': 300, 'price': 30000},
        {'mid': '3', 'eid': 'lamp', 'role': 'торшер', 'style': 'сканди', 'name': 'Торшер чужого стиля', 'w': 40, 'd': 40, 'price': 5000},
    ]
    s = {'style': 'лофт', 'items': {
        'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван', 'w': 200},
        'тв-тумба': {'mid': '1', 'eid': 'tv', 'name': 'Тумба', 'w': 150},
        'столик': {'mid': '7', 'eid': 'dead', 'name': 'Снятый столик', 'w': 100, 'price': 8000}}}
    j = fill_set(s, pool, gate, card, media, has_mesh)
    ok('снятый столик заменён живым того же стиля', s['items']['столик']['name'] == 'Столик Б')
    ok('недостающий ковёр добавлен, огромный отсеян воротами', s['items'].get('ковёр', {}).get('name') == 'Ковёр 200×160')
    ok('торшер чужого стиля не подставлен — ядро честно неполное', core_missing(s) == ['торшер'])
    ok('журнал пишет причину', any(x['role'] == 'столик' and x['reason'] == 'снят с продажи' for x in j))
    ok('годный диван не тронут', s['items']['диван']['name'] == 'Диван')
    # свой запасной набора — первым для роли ядра; негодный (снят / не проходит ворота) пропускается, тогда — пул
    alive |= {('5', 'spare2'), ('2', 'sofa9')}
    cat = {('5', 'spare1'): {'name': 'Запасной снятый', 'w': 190, 'd': 90, 'img': '//a'},
           ('5', 'spare2'): {'name': 'Запасной живой', 'w': 198, 'd': 90, 'h': 83, 'img': '//b', 'price': 25990},
           ('5', 'huge'): {'name': 'Запасной огромный', 'w': 400, 'd': 90, 'img': '//c'}}
    media2 = lambda mid, eid: {**cat.get((mid, eid), {}), 'state': 'available' if (mid, eid) in alive else 'gone'}  # noqa: E731
    pool2 = pool + [{'mid': '2', 'eid': 'sofa9', 'role': 'диван', 'style': 'лофт', 'name': 'Диван из пула', 'w': 200, 'd': 95}]
    gate2 = lambda role, c, s, chosen: c['w'] < 300 and media2(c['mid'], c['eid'])['state'] == 'available'  # noqa: E731
    mk = lambda alts: {'style': 'лофт', 'alternates': {'диван': alts}, 'items': {  # noqa: E731
        'диван': {'mid': '7', 'eid': 'gone', 'name': 'Этен Мини', 'w': 180}, 'тв-тумба': {'mid': '1', 'eid': 'tv', 'name': 'Тумба'}}}
    s2 = mk([{'mid': 5, 'eid': 'spare1'}, {'mid': 5, 'eid': 'huge'}, {'mid': 5, 'eid': 'spare2'}])
    j2 = fill_set(s2, pool2, gate2, card, media2, has_mesh)
    x = next(x for x in j2 if x['role'] == 'диван')
    ok('ушёл диван: свой запасной набора раньше пула (снятый и огромный пропущены), журнал помечает источник',
       s2['items']['диван']['name'] == 'Запасной живой' and x['to_sku'] == '5:spare2' and x.get('source') == 'запасной набора')
    s3 = mk([{'mid': 5, 'eid': 'spare1'}])
    j3 = fill_set(s3, pool2, gate2, card, media2, has_mesh)
    ok('свои запасные негодны — замена из пула, без пометки источника',
       s3['items']['диван']['name'] == 'Диван из пула' and 'source' not in next(x for x in j3 if x['role'] == 'диван'))
    s5 = mk([{'mid': 5, 'eid': 'spare2'}])
    fill_set(s5, pool2, gate2, card, media2, has_mesh, avoid={'5:spare2'})
    ok('запасной уже взят другим стилем — сперва пул (разнообразие), сам запасной — только если пул пуст',
       s5['items']['диван']['name'] == 'Диван из пула')
    s6 = mk([{'mid': 5, 'eid': 'spare2'}])
    fill_set(s6, pool, gate2, card, media2, has_mesh, avoid={'5:spare2'})
    ok('…пул пуст — повтор запасного лучше дыры в ядре', s6['items']['диван']['name'] == 'Запасной живой')
    s7 = mk([{'mid': 5, 'eid': 'spare2'}])
    j7 = fill_set(s7, pool2, gate2, card, media2, has_mesh, own=False)
    ok('own=False — прежнее дозаполнение: только пул, свои запасные не смотрим',
       s7['items']['диван']['name'] == 'Диван из пула' and not any(x.get('source') for x in j7))
    s4 = {'style': 'лофт', 'alternates': {'кресло': [{'mid': 5, 'eid': 'spare2'}]}, 'items': {
        'кресло': {'mid': '7', 'eid': 'gone', 'name': 'Кресло снятое', 'w': 80}}}
    fill_set(s4, pool2, gate2, card, media2, has_mesh)
    ok('не ядро (кресло) — свои запасные не берём, как прежде (заменить нечем — снято)', 'кресло' not in s4['items'])
    ok('ковёр зоны дивана: 160×230 под диван 198 — да, 120×180 и 140×190 под 198 — нет, без дивана 140×190 — да',
       [rug_fits(230, 160, 198), rug_fits(180, 120, 198), rug_fits(190, 140, 198), rug_fits(140, 190)] == [True, False, False, True])
    # запасной нейтральный ковёр (T-20261107-11/2): отметка — в журнале и у ковра набора; свой ковёр стиля — без отметки
    uni_pool = [{'mid': '2', 'eid': 'uni', 'role': 'ковёр', 'style': 'неоклассика', 'name': 'Ковёр Серый 300×200', 'w': 300,
                 'd': 200, 'price': 5000, 'rug_universal': True}]
    alive.add(('2', 'uni'))
    gate_u = lambda role, c, s, chosen: c['w'] <= 300  # noqa: E731
    s8 = {'style': 'неоклассика', 'items': {'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван', 'w': 200}}}
    j8 = fill_set(s8, uni_pool, gate_u, card, media, has_mesh)
    x8 = next(x for x in j8 if x['role'] == 'ковёр')
    ok('запасной нейтральный: отметка rug_universal в журнале и у ковра',
       s8['items']['ковёр'].get('rug_universal') is True and x8.get('rug_universal') is True)
    s9 = {'style': 'лофт', 'items': {'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван', 'w': 200}}}
    j9 = fill_set(s9, pool, gate, card, media, has_mesh)
    ok('свой ковёр стиля — ключа rug_universal нет нигде (5 стилей побайтно)',
       'rug_universal' not in s9['items']['ковёр'] and not any('rug_universal' in x for x in j9))
    # цвет необязательного (T-20261107-11/3): яркий стул неоклассике не берём, нейтральный — да; современному яркий можно;
    # ядро (диван) по цвету не режем; подушка демо = «подушки» правил
    alive |= {('4', 'chy'), ('4', 'chb')}
    chairs = [{'mid': '4', 'eid': 'chy', 'role': 'стул', 'style': 'неоклассика', 'name': 'Стул Glasar Совы желтый', 'w': 45, 'd': 50},
              {'mid': '4', 'eid': 'chb', 'role': 'стул', 'style': 'неоклассика', 'name': 'Стул Венский бежевый', 'w': 45, 'd': 50}]
    s10 = {'style': 'неоклассика', 'items': {'стул': {'mid': '7', 'eid': 'gone', 'name': 'Стул снятый', 'w': 45}}}
    fill_set(s10, chairs, gate, card, media, has_mesh)
    ok('неоклассика: яркий жёлтый стул пропущен, взят бежевый', s10['items'].get('стул', {}).get('name') == 'Стул Венский бежевый')
    s11 = {'style': 'неоклассика', 'items': {'стул': {'mid': '7', 'eid': 'gone', 'name': 'Стул снятый', 'w': 45}}}
    fill_set(s11, chairs[:1], gate, card, media, has_mesh)
    ok('…только яркий — стул снят, а не жёлтый', 'стул' not in s11['items'])
    ok('современный: яркий стул допустим', color_refused('стул', chairs[0], 'современный') is None)
    ok('подушка демо — группа мягкого: оранжевая неоклассике нет, синяя бархатная да',
       bool(color_refused('подушка', {'name': 'Подушка Саона Велюр Оранжевый/Синий'}, 'неоклассика'))
       and color_refused('подушка', {'name': 'Подушка Бархат синий'}, 'неоклассика') is None)
    ok('приглушённый discouraged (оливковый стул джапанди) — не отсев, только яркий',
       color_refused('стул', {'name': 'Стул Марти-2 Велюр Оливковый/Натуральный'}, 'джапанди') is None)
    ok('ядро по цвету не режем: жёлтый диван — не причина', color_refused('диван', {'name': 'Диван желтый'}, 'неоклассика') is None)
    # роль ядра у соседнего стиля (T-20261107-11/6): своего столика нет — берём у соседа (неоклассика → современный), цвет —
    # по правилам получателя; у полного ядра и у стиля без соседа с товаром — как было
    alive |= {('6', 'tyel'), ('6', 'tnut'), ('6', 'tloft')}
    tables = [{'mid': '6', 'eid': 'tyel', 'role': 'столик', 'style': 'современный', 'name': 'Столик жёлтый', 'w': 90, 'd': 60},
              {'mid': '6', 'eid': 'tnut', 'role': 'столик', 'style': 'современный', 'name': 'Столик орех', 'w': 95, 'd': 60},
              {'mid': '6', 'eid': 'tloft', 'role': 'столик', 'style': 'лофт', 'name': 'Столик серый лофт', 'w': 90, 'd': 60}]
    neo = lambda: {'style': 'неоклассика', 'items': {'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван', 'w': 200}}}  # noqa: E731
    s12 = neo()
    j12 = fill_set(s12, tables, gate, card, media, has_mesh)
    t12 = s12['items'].get('столик') or {}
    x12 = next((x for x in j12 if x['role'] == 'столик'), {})
    ok('нет своего столика — у соседа (современный), жёлтый пропущен цветом получателя, взят орех; отметки в журнале и у товара',
       t12.get('name') == 'Столик орех' and t12.get('style_from') == 'современный' and x12.get('source') == 'соседний стиль: современный')
    s13 = neo()
    fill_set(s13, tables[:1] + tables[2:], gate, card, media, has_mesh)
    ok('у соседа только яркий, лофт не сосед неоклассики — дыра честная', 'столик' not in s13['items'])
    s14 = {'style': 'неоклассика', 'items': {'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван', 'w': 200},
                                             'столик': {'mid': '2', 'eid': 'table', 'name': 'Свой столик', 'w': 90}}}
    j14 = fill_set(s14, tables, gate, card, media, has_mesh)
    ok('свой годный столик есть — соседа не зовём, ключей style_from/«соседний» нет',
       s14['items']['столик']['name'] == 'Свой столик' and 'style_from' not in s14['items']['столик']
       and not any('соседний' in str(x.get('source', '')) for x in j14))
    got = neighbour_fill('столик', None, {'style': 'x'}, tables, set(), None, None, gate, card, {}, neighbours=lambda st: [])
    ok('у стиля нет соседей — (None, None)', got == (None, None))
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
