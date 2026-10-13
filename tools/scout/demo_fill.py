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
    """Пул кандидатов: объёмные — `demo_swap_pool.pool()`, ковры — плоский запрос."""
    from demo_swap_pool import pool
    out = []
    for p in pool():
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
    from catalog_rules import availability
    if availability(media(it.get('mid'), it.get('eid'))) == 'unavailable':
        return 'снят с продажи'               # `unknown` (фид не приехал) — товар не трогаем
    if base_role(role) not in NOMESH and not has_mesh(it):
        return 'нет модели'
    return None


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
             avoid: set | None = None) -> list[dict]:
    """Заменить негодные и добавить недостающие роли ядра. Меняет `s['items']`; → журнал замен."""
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
        repl = None
        for c in candidates(role, old, s.get('style'), pool, used, env, avoid):
            if ok(role, c, s, {r: v for r, v in items.items() if r != role}):
                repl = card(c, old or {})
                break
        sku = lambda it: f"{it.get('mid')}:{it.get('eid')}" if it else None  # noqa: E731
        journal.append({'role': role, 'from': (old or {}).get('name'), 'from_sku': sku(old),
                        'to': (repl or {}).get('name'), 'to_sku': sku(repl), 'reason': why})
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
            sofa = (chosen.get('диван') or {}).get('w') or 0
            # HARD-контракт зонного ковра (ADR-0120): короткая ≥ 140, длинная ≥ ширины дивана
            if min(w, d) < 140 or (sofa and max(w, d) < sofa):
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
    return 1 if bad else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
