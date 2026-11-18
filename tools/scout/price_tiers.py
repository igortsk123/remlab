"""Ценовые ступени роли (эконом / комфорт / премиум = `lo` / `mid` / `hi`) — ОДНО место правила границ
(владелец TG 1975, 18.11; план `plans/price-segments-01.md`, критика Codex `_intake/codex/2026-11-18-price-segments-answer.md`).

Ступени НЕ пересекаются: терцили цены СЕМЕЙСТВА роли (цвета/ткань — одна модель, разный типоразмер — разные; цена семейства —
медиана показываемых цен его вариантов), граница стоит на разрыве между разными ценами (одна цена — в одной ступени), хвосты не
режутся, верх премиума открыт. Границы — файл `rules/price-segments.json`, его строит ОТДЕЛЬНАЯ команда
(`price_segments_build.py --build`), потребители сами квантили не считают: лента «Заменить» (`demo_swap_pool.pick`), фото-каталог
комнат (`flat215_demo._catalog_pick`), `demo-data.json` (поле `price_segment` и диапазоны роли для чипов страницы).
Этот модуль — только чтение правила + ключ семейства + популяция каталога; DB и PIL не нужны до вызова `family_prices`.

БАНК НАБОРОВ (T-20261118-61/6, план шаг 3): `tier_band(роль, ступень, цены, квантили)` — ЕДИНСТВЕННЫЙ источник диапазона цены ступени для
`candidates`/`compose`/`compose2`/`compose_bedroom`/`compose_hall`/`bank_keep` (раньше у каждого свой перекрывающийся перцентиль
p05–45/35–80/70–97 и у спальни пересчёт внутри стиля). Режим — `bank_segments_on()`: env `BANK_PRICE_SEGMENTS=1|0`, иначе поле
`bank_use_segments` в `rules/price-segments-config.json` (по умолчанию ВЫКЛ — ночная сборка кандидата как раньше, пока директор
не включит по отчёту тени). Выкл — прежние квантили (`quantile_band`, одна копия); вкл — границы роли из правила, ступени не
пересекаются; у роли без границ — запасной путь прежними квантилями (отчёт тени их называет).

  python3 price_tiers.py --selftest
"""
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, 'rules', 'price-segments.json')
KEYS = ('lo', 'mid', 'hi')
LABELS = {'ru': {'lo': 'эконом', 'mid': 'комфорт', 'hi': 'премиум'}, 'en': {'lo': 'economy', 'mid': 'comfort', 'hi': 'premium'}}
_CACHE: dict = {}


def load(path: str | None = None) -> dict:
    """Правило ступеней (кэш по пути); файла нет — пусто (ступеней нет: все потребители работают без них, как до правила)."""
    path = path or RULES_PATH
    if path not in _CACHE:
        try:
            _CACHE[path] = json.load(open(path, encoding='utf-8'))
        except OSError:
            _CACHE[path] = {}
    return _CACHE[path]


def bounds_of(role: str, rules: dict | None = None):
    """[B1, B2] роли в рублях (B1 — первая цена «комфорта», B2 — первая цена «премиума») или None (границ нет: <7 семейств и
    нет ручного правила)."""
    r = ((rules if rules is not None else load()).get('roles') or {}).get(role) or {}
    b = r.get('boundaries_rub')
    return [float(b[0]), float(b[1])] if b else None


def tier_of(role: str, price, rules: dict | None = None, bounds: dict | None = None):
    """Ступень по цене СЕМЕЙСТВА: ниже B1 — `lo`, от B1 до B2 — `mid`, от B2 и выше — `hi`. Границ роли нет (или цены нет) — None.
    `bounds` — {роль: [B1, B2]} поверх правила (тесты, ручной прогон)."""
    b = (bounds or {}).get(role) or bounds_of(role, rules)
    x = float(price or 0)
    if not b or x <= 0:
        return None
    return KEYS[0] if x < b[0] else KEYS[1] if x < b[1] else KEYS[2]


def ranges(rules: dict | None = None) -> dict:
    """Что отдаём странице (`demo-data.json` → `price_segments`): версия, подписи RU/EN и по роли границы/число семейств/метод —
    для чипов «Комфорт · 56 000–95 999 ₽» (премиум — «от …», максимум не показываем)."""
    R = rules if rules is not None else load()
    if not R:
        return {}
    return {'version': R.get('version'), 'labels': LABELS,
            'roles': {k: {'boundaries_rub': v.get('boundaries_rub'), 'families': v.get('families'), 'method': v.get('method')}
                      for k, v in (R.get('roles') or {}).items()}}


# ---------- банк наборов: один resolver диапазона ступени ----------
BANK_TIERS = {'эконом': 'lo', 'комфорт': 'mid', 'премиум': 'hi'}                          # имена ступеней банка → ключи правила
LEGACY_Q = {'эконом': (0.05, 0.45), 'комфорт': (0.35, 0.80), 'премиум': (0.70, 0.97)}    # прежние перцентили (перекрывались) — только запасной путь
_CONFIG = os.path.join(HERE, 'rules', 'price-segments-config.json')


def bank_segments_on() -> bool:
    """Банк берёт ступени из правила границ? env `BANK_PRICE_SEGMENTS` (1/0) главнее файла; без него — `bank_use_segments` конфига."""
    e = os.environ.get('BANK_PRICE_SEGMENTS')
    if e in ('0', '1'):
        return e == '1'
    return bool(load(_CONFIG).get('bank_use_segments', False))


def base_role(role: str) -> str:
    """«кресло 2» → «кресло» (второе место той же роли — те же границы; как на странице)."""
    return re.sub(r'\s+\d+$', '', role or '')


def quantile_band(prices, q) -> tuple:
    """Прежние квантили цены (запасной путь): q = (низ, верх) доли; пусто — без ограничения."""
    ps = sorted(prices)
    if not ps:
        return (0, 10 ** 9)

    def pc(p):
        return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
    return (pc(q[0]), pc(q[1]))


def tier_band(role: str, tier: str, prices=(), q=None, rules: dict | None = None, segments: bool | None = None) -> tuple:
    """(низ, верх) цены ступени `tier` (эконом/комфорт/премиум) роли, обе границы ВКЛЮЧИТЕЛЬНО. Режим «ступени из правила»: эконом —
    ниже B1, комфорт — от B1 до B2 (не включая), премиум — от B2 и выше; ступени не пересекаются. Иначе или у роли без границ —
    прежние квантили `q` (по умолчанию `LEGACY_Q[tier]`) по `prices` (цены годных роли). `segments` — принудительный режим (тест)."""
    on = bank_segments_on() if segments is None else segments
    b = bounds_of(base_role(role), rules) if on else None
    k = BANK_TIERS.get(tier)
    if b and k:
        return {'lo': (0, math.nextafter(b[0], 0.0)), 'mid': (b[0], math.nextafter(b[1], 0.0)), 'hi': (b[1], 10 ** 9)}[k]
    return quantile_band(prices, q or LEGACY_Q[tier])


def band_source(role: str, rules: dict | None = None) -> str:
    """Откуда диапазон роли при включённом режиме: `segments` (границы правила) или `legacy` (запасные квантили) — для отчёта тени."""
    return 'segments' if bounds_of(base_role(role), rules) else 'legacy'


# ---------- семейство ----------
def family_key(shop_mid, name: str, w, rep: str = '') -> str:
    """Коммерческое семейство товара (переходное правило Codex): представитель mesh-семьи (`mesh_family_rep`; его ключ уже включает
    размеры) → иначе магазин + модель по названию (без цвета/ткани/размера, `room_catalog.family`) + ширина с округлением до 10 см
    (разный типоразмер — разная модель). Одна функция для построителя границ, пула ленты и каталога комнат."""
    if rep:
        return 'm:' + str(rep).replace(':', '_', 1)   # «магазин_артикул» (так же пишет пул ленты: `msid`)
    try:
        import room_catalog as _RC
        fam = _RC.family(name or '')
    except Exception:  # noqa: BLE001 — без модуля: название до первой цифры
        import re
        fam = re.sub(r'\s\S*\d.*$', '', (name or '').lower()).strip()
    wb = int(round(float(w) / 10.0)) * 10 if w else 0
    return f'n:{shop_mid}|{fam}|{wb}'


def median_price(prices) -> float:
    ps = [float(x) for x in prices if x]
    return float(statistics.median(ps)) if ps else 0.0


def population_sql(roles=None, rooms: bool = False) -> str:
    """Популяция роли для границ: роль по ВСЕМ стилям; активен, в наличии, цена > 0 (`price_shown_rub`, правдивая цена), живое фото.
    НЕ влияют готовность меша, габариты, стиль, конверт и комната (это ворота выдачи, не рынок роли). `rooms` — плюс каталог комнат
    (`room_catalog`: спальня и прихожая — свежий фид, живое фото; роли только у них — кровать, шкаф-купе, …). Товар каталога комнаты,
    уже взятый из `products` ТОЙ ЖЕ ролью, второй раз не считаем; тот же артикул под другой ролью (банкетка прихожей — в `products`
    пуф/диван) — считаем: у планировочной роли своя шкала цен (Codex: «банкетка» — отдельная явная популяция)."""
    lit = lambda xs: ','.join("'" + str(x).replace("'", "''") + "'" for x in xs)  # noqa: E731
    where_role = f"and p.cat_role in ({lit(roles)})" if roles else "and p.cat_role is not null"
    sql = f"""
select p.cat_role, p.shop_mid, p.external_id, coalesce(p.mesh_family_rep, ''), coalesce(p.name, ''), coalesce(p.w_cm, p.dia_cm, 0),
       coalesce(p.price_shown_rub, p.price_rub)
  from products p
 where p.in_stock and p.status = 'active' and coalesce(p.price_shown_rub, p.price_rub) > 0
   and coalesce(p.image_url_hd, p.image_url) is not null and coalesce(p.photo_alive, true) {where_role}"""
    if rooms:
        sql += """
union
select c.role, c.shop_mid, c.external_id, '', coalesce(c.name, ''), coalesce(c.w_cm, 0), c.price_rub
  from room_catalog c
 where c.room in ('bedroom', 'hall') and c.price_rub > 0 and coalesce(c.image_url_hd, c.image_url) is not null
   and coalesce(c.photo_alive, true) and c.missing_runs < 1
   and not exists (select 1 from products q where q.shop_mid = c.shop_mid and q.external_id = c.external_id and q.cat_role = c.role
                    and q.in_stock and q.status = 'active' and coalesce(q.price_shown_rub, q.price_rub) > 0)"""
    return sql


def families_from(rows) -> dict:
    """Строки популяции → {роль: {семейство: цена семейства (медиана цен вариантов)}}. Строка: роль, shop_mid, external_id, rep, имя, ширина, цена."""
    by: dict = {}
    for role, mid, _eid, rep, name, w, price in rows:
        by.setdefault(role, {}).setdefault(family_key(mid, name, float(w or 0), rep), []).append(float(price))
    return {role: {f: median_price(ps) for f, ps in fm.items()} for role, fm in by.items()}


def population_rows(roles=None, rooms: bool = False) -> list:
    """Строки популяции по живой БД (`mesh_queue.db`): роль, shop_mid, external_id, rep, имя, ширина, цена — до аудита выбросов."""
    from mesh_queue import db
    return [(r[0], r[1], r[2], r[3], r[4], float(r[5] or 0), float(r[6])) for r in db(population_sql(roles, rooms))]


def family_prices(roles=None, rooms: bool = False) -> dict:
    """{роль: {семейство: цена семейства}} по живой БД. Всё популяция, без исключений аудита: ступень товара в ленте считается по
    границам роли, а в границы (`price_segments_build`) комплектующие не входят — для них аудит `price_outliers`."""
    return families_from(population_rows(roles, rooms))


_FP: dict = {}


def family_prices_cached(roles=None, rooms: bool = True) -> dict:
    """То же, один раз на процесс сборки (ключ — набор ролей): пул ленты, каталог комнат и штамп `price_segment` читают одну выборку."""
    k = (tuple(sorted(roles)) if roles else None, rooms)
    if k not in _FP:
        _FP[k] = family_prices(roles, rooms)
    return _FP[k]


def segment_of(role: str, fkey: str, own_price, fam_price: dict | None = None, rules: dict | None = None, bounds: dict | None = None):
    """Ступень товара = ступень ЕГО СЕМЕЙСТВА: цена семейства из `fam_price` ({роль: {семейство: цена}}), нет в нём — цена самого товара."""
    price = ((fam_price or {}).get(role) or {}).get(fkey) or own_price
    return tier_of(role, price, rules, bounds)


def _selftest() -> int:
    bad = 0
    R = {'version': 't', 'roles': {'диван': {'boundaries_rub': [50000, 90000], 'families': 100, 'method': 'local'},
                                   'мало': {'boundaries_rub': None, 'families': 3, 'method': 'none'}}}
    got = [tier_of('диван', x, R) for x in (1, 49999.9, 50000, 89999, 90000, 5_000_000)]
    if got != ['lo', 'lo', 'mid', 'mid', 'hi', 'hi']:
        bad += 1
        print('  FAIL: ступень по границам (B1, B2 — первая цена верхней группы)', got)
    if tier_of('мало', 70000, R) is not None or tier_of('нет такой', 70000, R) is not None or tier_of('диван', 0, R) is not None:
        bad += 1
        print('  FAIL: нет границ или цены → ступени нет')
    if tier_of('диван', 60000, R, bounds={'диван': [70000, 80000]}) != 'lo':
        bad += 1
        print('  FAIL: bounds поверх правила')
    if family_key('1', 'Диван Алекс Серый 200', 200, 'a_b') != 'm:a_b' or family_key('1', 'x', 1, 'a:b_c') != 'm:a_b_c':
        bad += 1
        print('  FAIL: ключ семьи по представителю mesh-семьи')
    k1, k2, k3 = (family_key('9', n, w) for n, w in (('Диван Алекс Серый 200 см', 200), ('Диван Алекс Бежевый 200 см', 203), ('Диван Алекс Серый 240 см', 240)))
    if not (k1 == k2 and k1 != k3):
        bad += 1
        print('  FAIL: цвет — одна семья, другой типоразмер — другая', k1, k2, k3)
    fp = families_from([('диван', '9', 'a', '', 'Диван Алекс Серый 200 см', 200, 10), ('диван', '9', 'b', '', 'Диван Алекс Бежевый 200 см', 200, 30),
                        ('диван', '9', 'c', '', 'Диван Алекс Синий 200 см', 200, 20)])
    if list(fp['диван'].values()) != [20.0]:
        bad += 1
        print('  FAIL: цена семьи — медиана цен вариантов', fp)
    if 'q.cat_role = c.role' not in population_sql(rooms=True):
        bad += 1
        print('  FAIL: артикул каталога комнаты под другой ролью — не дубль (банкетка прихожей = пуф в products)')
    if 'в наличии' in population_sql() or 'mesh_status' in population_sql() or 'product_style_scores' in population_sql() or 'h_cm' in population_sql():
        bad += 1
        print('  FAIL: в популяции границ нет меша/габаритов/стиля')
    if set(LABELS['ru']) != set(KEYS) or set(LABELS['en']) != set(KEYS):
        bad += 1
        print('  FAIL: подписи RU/EN — пара на каждый ключ')
    if ranges({}) != {} or ranges(R)['roles']['диван']['boundaries_rub'] != [50000, 90000]:
        bad += 1
        print('  FAIL: диапазоны для страницы')
    if segment_of('диван', 'f1', 10, {'диван': {'f1': 60000}}, R) != 'mid' or segment_of('диван', 'zz', 95000, {'диван': {}}, R) != 'hi':
        bad += 1
        print('  FAIL: ступень товара — по цене семейства, нет семейства — по своей цене')
    # банк: один resolver диапазона ступени
    if quantile_band(list(range(100)), (0.05, 0.45)) != (5, 45) or quantile_band([], (0.1, 0.9)) != (0, 10 ** 9):
        bad += 1
        print('  FAIL: прежние квантили (запасной путь) — как compose2.tier_band')
    on = {t: tier_band('диван', t, [1, 2, 3], rules=R, segments=True) for t in BANK_TIERS}
    pr = [49999, 50000, 89999, 90000]
    hit = [[t for t, (lo, hi) in on.items() if lo <= x <= hi] for x in pr]
    if hit != [['эконом'], ['комфорт'], ['комфорт'], ['премиум']] or tier_band('диван 2', 'эконом', rules=R, segments=True) != on['эконом']:
        bad += 1
        print('  FAIL: ступени банка не пересекаются: одна цена — одна ступень, «диван 2» — границы «дивана»', hit)
    if tier_band('мало', 'комфорт', [10, 20, 30, 40], rules=R, segments=True) != quantile_band([10, 20, 30, 40], LEGACY_Q['комфорт']) or band_source('мало', R) != 'legacy':
        bad += 1
        print('  FAIL: роль без границ — запасной путь прежними квантилями')
    if tier_band('диван', 'комфорт', [1, 2, 3], rules=R, segments=False) != quantile_band([1, 2, 3], LEGACY_Q['комфорт']):
        bad += 1
        print('  FAIL: режим выключен — прежние квантили')
    print(f'price_tiers selftest: случаев 15, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
