#!/usr/bin/env python3
"""НАЛИЧИЕ ТОВАРА — единственный вычислитель (31.08.2026, ADR «наличие ≠ есть в фиде»).

  in_stock = фид активен  И  программа магазина жива  И  карточка не признана мёртвой

До этого наличие писали пятеро (`load3`, `health`, `linkcheck`, `gdeslon_api`, `resurrect`),
и последний писавший побеждал: `load3` каждое утро ставил `in_stock=true` всем, кто есть в фиде,
и стирал вердикты вечерних проверок. Теперь источники хранятся раздельно
(`product_enrichment.status`, `shop_status.program_state`, `product_page_status.state`),
а `products.in_stock` — производное, которое материализует ТОЛЬКО `reconcile()` отсюда.

СНИМАЕМ С ПЕРВОГО ОТКАЗА (ADR-0148), цена ошибки ограничена быстрым воскрешением (6 ч). Защита от
массового ложного снятия — не второй голос, а: якорь домена и карантин магазина в `stock_check`
(наблюдения карантина помечаются `disposition='quarantined'` и в свёртку больше не попадают), негатив
действует только по ТЕКУЩЕЙ ссылке карточки (`products.direct_url_hash`), гейт считает долю по
РЕШАЮЩИМ ответам с абсолютным пределом при малой выборке (план stock-and-dims-honesty, Н1).

  stock_truth.py --reconcile        # пересчитать in_stock из трёх источников
  stock_truth.py --audit            # сторож: расхождений формулы и in_stock должно быть 0
  stock_truth.py --selftest         # свёртка наблюдений и гейты на таблице случаев
"""
import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

CONFIRM_GAP_MIN = int(os.environ.get('STOCK_CONFIRM_GAP_MIN', '15'))   # минут между
# наблюдениями, чтобы второе считалось независимым голосом, а не эхом первого
# СНИМАЕМ С ПЕРВОГО ОТКАЗА (ADR-0148, решение владельца 01.09). Было 2 голоса с разрывом
# 15 минут. Замер: 347 повторных заходов из 347 подтвердили первый и не отменили НИ ОДНОГО.
# Владелец принял риск: «это редкость, и один товар из 1000 — нормально, можно пренебречь».
# Настоящую опасность повтор всё равно не ловил: закрывшийся от нас магазин отдаёт тот же
# ответ и через 15 минут (лечится порядком проверок в `page_alive.classify`), а ошибка в самой
# ссылке даёт стабильный 404 оба раза. Цена ошибки ограничена не повтором, а быстрым
# воскрешением: снятого перепроверяем через 6 часов (`TTL_GONE_FRESH_HOURS`).
CONFIRM_NEEDED = 1
NEGATIVE = ('gone', 'oos')

# Гейты применения (staging → гейт → применение). Пороги — на МАГАЗИН, а не на весь прогон:
# 100% ложных 404 у маленького магазина растворились бы в общей статистике 3500 запросов.
GATE_MIN_N = 30           # меньше выборка — гейт не судит, вердикты применяются
GATE_NOISE_FLOOR = 0.10   # ниже этой доли не судим вовсе: 0.1% → 0.5% это шум, а не поломка
GATE_HIST_FACTOR = 3.0    # во сколько раз выше исторического уровня — уже подозрительно
# ПЕРВЫЙ ПРОХОД ПО МАГАЗИНУ СУДИТСЯ ИНАЧЕ. У divanboss реально мертвы 39% проверенных ссылок —
# это накопленный за месяцы долг, а не сбой. С порогом 20% магазин попадал бы в карантин вечно
# и ни одна проверка никогда не применилась бы. Пока истории нет, срабатывает только аварийный
# порог: массовая поломка (сменилась схема ссылок, магазин лёг, нас забанили) даёт почти 100%,
# а не 39%. Как только история накопится, работает обычный порог и множитель к норме.
GATE_SHARE_FIRST_RUN = 0.60


def gate_limit(hist):
    """Потолок доли отрицательных для магазина.

    Судим по ОТКЛОНЕНИЮ ОТ НОРМЫ этого магазина, а не по общей константе: у одного 2% мёртвых
    ссылок — норма жизни, у другого 39% — накопленный долг, который и надо вычистить. Поэтому
    порог = норма×3, но не ниже шум-пола (мелкие колебания) и не выше аварийного (там уже
    очевидная поломка, а не ассортимент). Истории нет — работает только аварийный.
    """
    if hist is None:
        return GATE_SHARE_FIRST_RUN
    return min(max(hist * GATE_HIST_FACTOR, GATE_NOISE_FLOOR), GATE_SHARE_FIRST_RUN)


def db(sql: str) -> list:
    """psql → список полей. ВАЖНО: обрезаем только переводы строк.

    `str.strip()` здесь — мина: `'\\x1f'.isspace()` в Python равно True, поэтому обычный strip()
    съедает ПУСТЫЕ последние поля последней строки, и она молча приезжает короче остальных
    (поймано 31.08 на товаре без записи в page_status: 4 поля вместо 7).
    """
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:500])
    return [ln.split('\x1f') for ln in r.stdout.strip('\n').split('\n') if ln]


def q(v) -> str:
    """Литерал для SQL: None → NULL, строка → экранированная."""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


# --- свёртка наблюдений: чистая функция, поэтому её можно проверить селфтестом ----------------
def fold(observations, gap_min: int = CONFIRM_GAP_MIN):
    """История наблюдений по товару → (state, negatives, reason).

    Правила (каждое оплачено граблями, см. `core/lessons.md`):
    - учитываем только наблюдения по ТЕКУЩЕЙ ссылке: починили ссылку — старый 404 не в счёт;
    - `unknown` не подтверждает и не отменяет: антибот не должен ни спасать, ни убивать товар;
    - `alive` обрывает серию отрицательных немедленно;
    - два отрицательных ближе `gap_min` друг к другу считаются ОДНИМ: так повторный запуск
      reducer'а или гонка двух проверок не «подтверждают» смерть сами себе.

    Вход: список (verdict, url_hash, observed_at: datetime, reason), по возрастанию времени.
    """
    obs = [o for o in observations if o[0] in ('alive', 'oos', 'gone', 'unknown')]
    if not obs:
        return 'unknown', 0, 'наблюдений нет'
    cur_hash = obs[-1][1]
    obs = [o for o in obs if o[1] == cur_hash]
    negs, last_neg_at, last_reason, last_verdict = 0, None, None, None
    for verdict, _h, at, reason in reversed(obs):
        if verdict == 'unknown':
            continue
        if verdict == 'alive':
            if negs == 0:
                return 'alive', 0, reason
            break
        # отрицательное
        if last_neg_at is not None and abs((last_neg_at - at).total_seconds()) < gap_min * 60:
            continue                      # то же самое наблюдение по сути — не второй голос
        negs += 1
        last_neg_at, last_reason, last_verdict = at, reason, verdict
    if negs >= CONFIRM_NEEDED:
        return last_verdict, negs, last_reason
    return 'unknown', 0, obs[-1][3]


GATE_SMALL_MAX_NEG = 5    # малая выборка (< GATE_MIN_N решающих) не судится долей, но абсолютный
                          # предел негативов есть: 2 gone среди 998 blocked — норма, 6 gone из 8 решающих — нет


def gate(per_shop: dict, history: dict):
    """Какие магазины в карантине (их вердикты не применяются) → (карантин, причины).

    per_shop: mid → (attempted, decisive, negative) — сколько пытались, сколько ответов РЕШАЮЩИХ
    (alive/oos/gone; `unknown` в долю не входит — иначе 40 % неизвестных у tvoydom делали порог вдвое
    мягче) и сколько отрицательных. Совместимость: пара (n, neg) читается как (n, n, neg).
    history: mid → историческая доля отрицательных среди решающих (explore + accepted + текущая версия).
    """
    quarantine, why = set(), {}
    norm = {}
    for mid, v in per_shop.items():
        att, dec, neg = (v if len(v) == 3 else (v[0], v[0], v[1]))
        norm[mid] = (att, dec, neg)
    total_dec = sum(d for _, d, _ in norm.values())
    total_neg = sum(neg for _, _, neg in norm.values())
    for mid, (att, dec, neg) in norm.items():
        if dec < GATE_MIN_N:
            if neg > GATE_SMALL_MAX_NEG:
                quarantine.add(mid)
                why[mid] = f'{neg} отрицательных при {dec} решающих из {att} — малая выборка, предел {GATE_SMALL_MAX_NEG}'
            continue
        share, hist = neg / dec, history.get(mid)
        limit = gate_limit(hist)
        if share > limit:
            quarantine.add(mid)
            why[mid] = (f'{neg}/{dec} отрицательных ({share:.0%} > {limit:.0%}' +
                        (f', история {hist:.0%})' if hist is not None else ', первый проход)'))
    # Второй уровень — на весь прогон: сбой, задевший несколько магазинов сразу (наша сеть,
    # общий антибот-провайдер, испорченное формирование ссылок).
    hist_all = [h for h in (history.get(m) for m in norm) if h is not None]
    limit_all = gate_limit(sum(hist_all) / len(hist_all) if hist_all else None)
    if total_dec >= GATE_MIN_N and total_neg / total_dec > limit_all:
        for mid in norm:
            quarantine.add(mid)
            why.setdefault(mid, f'глобально {total_neg}/{total_dec} отрицательных '
                                f'({total_neg / total_dec:.0%} > {limit_all:.0%})')
    return quarantine, why


# --- материализация наличия -------------------------------------------------------------------
TRUTH_SQL = """
select p.shop_mid, p.external_id,
       (coalesce(e.status, p.status) = 'active'
        and coalesce(s.program_state, 'active') <> 'retired'
        -- негатив действует только по ТЕКУЩЕЙ ссылке карточки: починили ссылку — старый 404 не в счёт
        and not (coalesce(ps.state, 'unknown') in ('gone', 'oos')
                 and (p.direct_url_hash is null or ps.url_hash is null or ps.url_hash = p.direct_url_hash))) as want,
       p.in_stock
  from products p
  left join product_enrichment e on e.shop_mid = p.shop_mid and e.external_id = p.external_id
  left join shop_status s on s.shop_mid = p.shop_mid
  left join product_page_status ps on ps.shop_mid = p.shop_mid and ps.external_id = p.external_id
"""


# Производные поля честной модели (Н2). Негатив/позитив карточки действует только по ТЕКУЩЕЙ ссылке;
# время свидетельства — последнее РЕШАЮЩЕЕ принятое наблюдение, а не checked_at (тот двигается и на
# неудачных попытках, см. Codex 03.09).
DERIVED_SQL = """
with cur as (
  select p.shop_mid, p.external_id,
         (coalesce(e.status, p.status) = 'active') as feed_active,
         (coalesce(s.program_state, 'active') <> 'retired') as program_ok,
         case when ps.state in ('alive','oos','gone') and (p.direct_url_hash is null or ps.url_hash is null
                                                         or ps.url_hash = p.direct_url_hash)
              then ps.state else 'unknown' end as page_verdict
    from products p
    left join product_enrichment e on e.shop_mid = p.shop_mid and e.external_id = p.external_id
    left join shop_status s on s.shop_mid = p.shop_mid
    left join product_page_status ps on ps.shop_mid = p.shop_mid and ps.external_id = p.external_id),
ev as (
  select o.shop_mid, o.external_id,
         max(o.observed_at) filter (where o.verdict in ('alive','oos','gone') and o.disposition = 'accepted') as evidence_at,
         max(o.observed_at) filter (where o.disposition in ('accepted','quarantined')) as probe_at
    from product_page_observation o group by 1, 2),
truth as (
  select c.shop_mid, c.external_id,
         (c.feed_active and c.program_ok and c.page_verdict not in ('gone','oos')) as want,
         case when c.page_verdict = 'alive' then 'in_stock'
              when c.page_verdict = 'oos' then 'out_of_stock'
              else 'unknown' end as availability_state,
         case when c.page_verdict in ('alive','oos') then 'alive'
              when c.page_verdict = 'gone' then 'gone' else 'unknown' end as page_state,
         case when c.page_verdict in ('alive','oos','gone') then 'page'
              when c.feed_active and c.program_ok then 'feed' else 'none' end as availability_basis,
         ev.evidence_at, ev.probe_at
    from cur c left join ev on ev.shop_mid = c.shop_mid and ev.external_id = c.external_id)
"""


def reconcile(verbose: bool = True) -> int:
    """Пересчитать `products.in_stock` и производные поля честной модели. → сколько строк изменилось."""
    out = db(f"""
    {DERIVED_SQL}
    update products p set in_stock = t.want, availability_state = t.availability_state,
           page_state = t.page_state, availability_basis = t.availability_basis,
           stock_evidence_at = t.evidence_at, stock_probe_at = t.probe_at
      from truth t
     where p.shop_mid = t.shop_mid and p.external_id = t.external_id
       and (p.in_stock is distinct from t.want or p.availability_state is distinct from t.availability_state
            or p.page_state is distinct from t.page_state or p.availability_basis is distinct from t.availability_basis
            or p.stock_evidence_at is distinct from t.evidence_at or p.stock_probe_at is distinct from t.probe_at)
    returning p.shop, t.want, (p.in_stock is distinct from t.want) as flipped;
    """)
    flips = [r for r in out if len(r) >= 3 and r[2] == 't']
    on = sum(1 for r in flips if r[1] == 't')
    off = len(flips) - on
    if verbose:
        print(f'наличие пересчитано: снято {off}, возвращено {on}; производных полей обновлено у {len(out)}')
        per = {}
        for r in flips:
            k = (r[0], 'вернулось' if r[1] == 't' else 'снято')
            per[k] = per.get(k, 0) + 1
        for (shop, what), n in sorted(per.items(), key=lambda x: -x[1])[:10]:
            print(f'  {shop}: {what} {n}')
    return len(flips)


def audit(verbose: bool = True) -> int:
    """Сторож: сколько товаров расходятся с формулой (in_stock И производные поля). После reconcile — 0."""
    rows = db(f"""
    {DERIVED_SQL}
    select count(*) from truth t join products p on p.shop_mid = t.shop_mid and p.external_id = t.external_id
     where p.in_stock is distinct from t.want or p.availability_state is distinct from t.availability_state
        or p.page_state is distinct from t.page_state or p.availability_basis is distinct from t.availability_basis;
    """)
    n = int(rows[0][0]) if rows else 0
    if verbose:
        print(f'сторож наличия: расхождений с формулой {n}' + (' — ЧИСТО' if n == 0 else ' — ПОЧИНИТЬ'))
    return n


def set_shop_state(mid: int, shop: str, state: str, note: str = '') -> None:
    """Состояние партнёрской программы магазина (пишет `gdeslon_api.py`)."""
    db(f"""insert into shop_status (shop_mid, shop, program_state, checked_at, note)
           values ({int(mid)}, {q(shop)}, {q(state)}, now(), {q(note or None)})
           on conflict (shop_mid) do update set shop = excluded.shop,
             program_state = excluded.program_state, checked_at = now(), note = excluded.note;""")


# --- селфтест ---------------------------------------------------------------------------------
def _selftest() -> int:
    T0 = dt.datetime(2026, 8, 31, 10, 0)
    def t(minutes):
        return T0 + dt.timedelta(minutes=minutes)
    H1, H2 = 'hash-A', 'hash-B'
    cases = [
        ('один 404 — снимаем сразу (ADR-0148); suspect не существует',
         [('gone', H1, t(0), 'http 404')], ('gone', 1)),
        ('два 404 с разрывом — снимаем',
         [('gone', H1, t(0), 'http 404'), ('gone', H1, t(30), 'http 404')], ('gone', 2)),
        ('два 404 подряд в одну минуту — считаем одним наблюдением, не двумя',
         [('gone', H1, t(0), 'http 404'), ('gone', H1, t(1), 'http 404')], ('gone', 1)),
        ('404 → капча → 404: капча не подтверждает, но и не спасает',
         [('gone', H1, t(0), 'http 404'), ('unknown', H1, t(20), 'антибот'),
          ('gone', H1, t(40), 'http 404')], ('gone', 2)),
        ('404 → товар снова продаётся',
         [('gone', H1, t(0), 'http 404'), ('gone', H1, t(30), 'http 404'),
          ('alive', H1, t(60), 'schema: в продаже')], ('alive', 0)),
        ('ссылку починили — счёт заново',
         [('gone', H1, t(0), 'http 404'), ('gone', H1, t(30), 'http 404'),
          ('gone', H2, t(60), 'http 404')], ('gone', 1)),
        ('только антибот — ничего не знаем',
         [('unknown', H1, t(0), 'антибот'), ('unknown', H1, t(30), 'антибот')], ('unknown', 0)),
        ('OOS дважды — снимаем как oos',
         [('oos', H1, t(0), 'schema'), ('oos', H1, t(30), 'schema')], ('oos', 2)),
        ('OOS один раз — тоже снимаем (ADR-0148)',
         [('oos', H1, t(0), 'schema')], ('oos', 1)),
        ('капча ПОСЛЕ отказа не воскрешает, но и не подтверждает',
         [('gone', H1, t(0), 'http 404'), ('unknown', H1, t(30), 'антибот')], ('gone', 1)),
        ('живой товар',
         [('alive', H1, t(0), 'schema: в продаже')], ('alive', 0)),
        ('наблюдений нет', [], ('unknown', 0)),
    ]
    bad = 0
    for title, obs, (want_state, want_neg) in cases:
        state, negs, _r = fold(obs)
        if (state, negs) != (want_state, want_neg):
            bad += 1
            print(f'  FAIL {title}: получили ({state}, {negs}), ждали ({want_state}, {want_neg})')
    # гейты
    gates = [
        ('всплеск у одного магазина не растворяется в общем объёме',
         {1: (100, 45), 2: (3000, 30)}, {1: 0.03, 2: 0.01}, {1}),
        ('маленькая выборка не судится долей, но 10 негативов из 10 — выше абсолютного предела',
         {1: (10, 10)}, {}, {1}),
        ('малая выборка с 3 негативами — применяем',
         {1: (10, 3)}, {}, set()),
        ('unknown не входят в долю: 2 gone среди 998 неизвестных — норма',
         {1: (1000, 2, 2)}, {}, set()),
        ('решающих мало, негативов много — карантин',
         {1: (1000, 8, 6)}, {}, {1}),
        ('рост втрое над историей — карантин',
         {1: (200, 30)}, {1: 0.02}, {1}),
        ('норма проходит', {1: (200, 4)}, {1: 0.02}, set()),
        ('магазин с исторически высоким долгом не карантинится на своей же норме',
         {1: (900, 320)}, {1: 0.36}, set()),
        ('он же при реальной поломке — карантин', {1: (900, 700)}, {1: 0.36}, {1}),
        ('глобальный всплеск гасит всех',
         {1: (100, 70), 2: (100, 65)}, {1: 0.02, 2: 0.02}, {1, 2}),
        # первый проход по магазину: 39% мёртвых ссылок — это накопленный долг, а не сбой,
        # вердикты применяем (иначе магазин в карантине навсегда и чистка не стартует)
        ('первый проход с большим долгом — применяем', {1: (900, 350)}, {}, set()),
        ('первый проход с массовой поломкой — карантин', {1: (900, 800)}, {}, {1}),
    ]
    for title, per, hist, want in gates:
        got, _why = gate(per, hist)
        if got != want:
            bad += 1
            print(f'  FAIL гейт «{title}»: карантин {got}, ждали {want}')
    print(f'stock_truth selftest: случаев {len(cases) + len(gates)}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    elif '--reconcile' in sys.argv:
        reconcile()
        sys.exit(1 if audit() else 0)
    elif '--audit' in sys.argv:
        sys.exit(1 if audit() else 0)
    else:
        print(__doc__)
