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


def load_pool() -> list[dict]:
    """Пул кандидатов: объёмные — `demo_swap_pool.pool_top()` (прежний отбор 30, demo-18), ковры — плоский запрос."""
    from demo_swap_pool import pool_top
    out = []
    for p in pool_top():
        mid, eid = p['sid'].split('_', 1)
        out.append({**p, 'mid': mid, 'eid': eid})
    from mesh_queue import db
    for r in db(RUG_SQL):
        if len(r) != 9:
            continue
        sku, name, shop, img, url, price, w, d, style = r
        mid, eid = sku.split(':', 1)
        out.append({'mid': mid, 'eid': eid, 'role': 'ковёр', 'style': style, 'name': name, 'shop': shop,
                    'img': img, 'url': url, 'price': int(float(price)) if price else None,
                    'w': float(w), 'd': float(d), 'h': 1.0})
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
        repl = spare = None
        own_c = own_spares(s, role, media, used) if own and base_role(role) in CORE else []
        # уже взятый в другой вариант запасной — после пула (разнообразие между стилями, как у `candidates`), но до дыры
        k = lambda c: f"{c['mid']}:{c['eid']}" in (avoid or ())  # noqa: E731
        for c in ([c for c in own_c if not k(c)] + candidates(role, old, s.get('style'), pool, used, env, avoid)
                  + [c for c in own_c if k(c)]):
            if ok(role, c, s, {r: v for r, v in items.items() if r != role}):
                repl, spare = card(c, old or {}), c.get('spare')
                break
        sku = lambda it: f"{it.get('mid')}:{it.get('eid')}" if it else None  # noqa: E731
        journal.append({'role': role, 'from': (old or {}).get('name'), 'from_sku': sku(old),
                        'to': (repl or {}).get('name'), 'to_sku': sku(repl), 'reason': why,
                        **({'source': 'запасной набора'} if spare else {})})
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
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
