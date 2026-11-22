"""ЦЕНОВЫЕ СТУПЕНИ БАНКА НАБОРОВ — одно место (T-20261118-61/6 и /7, план `plans/price-segments-01.md` шаг 3; ответ Codex
`_intake/codex/2026-11-18-tier-fallback-answer.md`, решение директора 18.11).

`tier_band(роль, ступень, цены, квантили)` — ЕДИНСТВЕННЫЙ источник диапазона цены ступени для `candidates`/`compose`/`compose2`/
`compose_bedroom`/`compose_hall`/`bank_keep` (раньше у каждого свой перекрывающийся перцентиль p05–45/35–80/70–97 и у спальни пересчёт
внутри стиля). Границы — `rules/price-segments.json` (читает `price_tiers`); режим и КЛАСС РОЛИ — `rules/bank-price-tiers.json`
(этот файл читает только банк: витрина и туры его не читают, метка правил сборки не двигается).

РЕЖИМ — `bank_segments_on()`: env `BANK_PRICE_SEGMENTS=1|0`, иначе `bank_use_segments` файла (по умолчанию ВЫКЛ). Выкл — прежние
квантили (`quantile_band`, одна копия), наборы как в main; вкл — границы роли, ступени не пересекаются; у роли без границ — прежние квантили.

КЛАСС РОЛИ (`role_class`, данные `bank_role_policy`): `strict` — крупная мебель: своя ступень, `soft` цену НЕ снимает; `budgeted` — своя
ступень ±1 (эконом: эконом+комфорт, комфорт: любая, премиум: комфорт+премиум); `exempt` — мелкий декор, как до правила. Пустая ступень
у strict — не «соседняя ступень», а `gap` роли или недоступная ячейка (решает комната). `tier_violation` — то же правило как проверка
готовой позиции (валидатор `bank_invariants`, тень).

  python3 bank_tiers.py --selftest
"""
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import price_tiers as PT  # noqa: E402

BANK_TIERS = {'эконом': 'lo', 'комфорт': 'mid', 'премиум': 'hi'}                          # имена ступеней банка → ключи правила
LEGACY_Q = {'эконом': (0.05, 0.45), 'комфорт': (0.35, 0.80), 'премиум': (0.70, 0.97)}    # прежние перцентили (перекрывались) — запасной путь
CLASSES = ('strict', 'budgeted', 'exempt')
CONFIG_PATH = os.path.join(HERE, 'rules', 'bank-price-tiers.json')
_CACHE: dict = {}


def config(path: str | None = None) -> dict:
    """Настройки банка (кэш по пути); файла нет — пусто (режим выкл, классов нет)."""
    path = path or CONFIG_PATH
    if path not in _CACHE:
        try:
            _CACHE[path] = json.load(open(path, encoding='utf-8'))
        except OSError:
            _CACHE[path] = {}
    return _CACHE[path]


def bank_segments_on() -> bool:
    """Банк берёт ступени из правила границ? env `BANK_PRICE_SEGMENTS` (1/0) главнее файла; без него — `bank_use_segments`."""
    e = os.environ.get('BANK_PRICE_SEGMENTS')
    if e in ('0', '1'):
        return e == '1'
    return bool(config().get('bank_use_segments', False))


def base_role(role: str) -> str:
    """«кресло 2» → «кресло» (второе место той же роли — те же границы и класс; как на странице)."""
    return re.sub(r'\s+\d+$', '', role or '')


def role_class(role: str, cfg: dict | None = None):
    """Класс роли банка: 'strict' | 'budgeted' | 'exempt' или None (роль без класса — у роли без границ его и нет)."""
    pol = ((cfg if cfg is not None else config()).get('bank_role_policy') or {})
    b = base_role(role)
    for c in CLASSES:
        if b in (pol.get(c) or []):
            return c
    return None


def relax_allowed(role: str, cfg: dict | None = None) -> bool:
    """Можно ли роли взять товар вне ступени с записью `tier_relaxed`? Список — `tier_relaxed_allowed` файла (по умолчанию пуст)."""
    return base_role(role) in ((cfg if cfg is not None else config()).get('tier_relaxed_allowed') or [])


def quantile_band(prices, q) -> tuple:
    """Прежние квантили цены (запасной путь): q = (низ, верх) доли; пусто — без ограничения."""
    ps = sorted(prices)
    if not ps:
        return (0, 10 ** 9)

    def pc(p):
        return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
    return (pc(q[0]), pc(q[1]))


def tier_band(role: str, tier: str, prices=(), q=None, rules: dict | None = None, segments: bool | None = None,
              cfg: dict | None = None) -> tuple:
    """(низ, верх) цены ступени `tier` (эконом/комфорт/премиум) роли, обе границы ВКЛЮЧИТЕЛЬНО. Режим «ступени из правила»: эконом —
    ниже B1, комфорт — от B1 до B2 (не включая), премиум — от B2 и выше; ступени не пересекаются; роль класса `budgeted` — своя ступень ±1.
    Иначе или у роли без границ — прежние квантили `q` (по умолчанию `LEGACY_Q[tier]`) по `prices` (цены годных роли).
    `segments` — принудительный режим (тест)."""
    on = bank_segments_on() if segments is None else segments
    b = PT.bounds_of(base_role(role), rules) if on else None
    k = BANK_TIERS.get(tier)
    if b and k:
        lo, mid, hi = (0, math.nextafter(b[0], 0.0)), (b[0], math.nextafter(b[1], 0.0)), (b[1], 10 ** 9)
        if role_class(role, cfg) == 'budgeted':
            return {'lo': (0, mid[1]), 'mid': (0, 10 ** 9), 'hi': (mid[0], 10 ** 9)}[k]
        return {'lo': lo, 'mid': mid, 'hi': hi}[k]
    return quantile_band(prices, q or LEGACY_Q[tier])


def band_source(role: str, rules: dict | None = None) -> str:
    """Откуда диапазон роли при включённом режиме: `segments` (границы правила) или `legacy` (запасные квантили) — для отчёта тени."""
    return 'segments' if PT.bounds_of(base_role(role), rules) else 'legacy'


def soft_may_drop_price(role: str, segments: bool | None = None, cfg: dict | None = None) -> bool:
    """Может ли «мягкий» проход подбора (`pick2(..., soft=True)`) снять цену у роли? Выкл — да, как до правила; вкл — только у `exempt`
    и роли без класса: у strict и budgeted ступень держится и в мягком проходе."""
    on = bank_segments_on() if segments is None else segments
    return not (on and role_class(role, cfg) in ('strict', 'budgeted'))


def tier_violation(role: str, tier: str, price, rules: dict | None = None, cfg: dict | None = None):
    """Причина (строка), по которой позиция роли с ценой `price` не годится ячейке ступени `tier`, или None. strict — не своя ступень;
    budgeted — дальше соседней; exempt, роль без границ или цены — не проверяется. Режим не смотрит: проверка готового набора."""
    k = BANK_TIERS.get(tier)
    c = role_class(role, cfg)
    got = PT.tier_of(base_role(role), price, rules)
    if not k or got is None or c not in ('strict', 'budgeted'):
        return None
    d = abs(PT.KEYS.index(got) - PT.KEYS.index(k))
    if c == 'strict' and d:
        return f'{role}: {price} ₽ — ступень «{got}», ячейка «{k}» (strict)'
    if c == 'budgeted' and d > 1:
        return f'{role}: {price} ₽ — ступень «{got}», ячейка «{k}» (budgeted допускает ±1)'
    return None


def tier_problems(bank: list, rules: dict | None = None, cfg: dict | None = None, segments: bool | None = None) -> list:
    """ОБЩИЙ ВАЛИДАТОР ЦЕНЫ БАНКА (гостиная — `bank_invariants.check`, спальня и прихожая — их `check_bank`): позиция strict вне ступени
    своей ячейки (budgeted — дальше соседней) без записи `tier_relaxed` этой роли — нарушение. Запись принимается, только если роль
    есть в `tier_relaxed_allowed` (по умолчанию пусто). Режим выкл — проверки нет (прежний банк построен перекрывающимися квантилями).
    → список строк «<set_id или ячейка>: причина»."""
    if not (bank_segments_on() if segments is None else segments):
        return []
    out = []
    for s in bank:
        rel = s.get('tier_relaxed') or {}
        who = s.get('set_id') or '|'.join(str(s.get(k)) for k in ('band', 'style', 'tier'))
        for role, it in (s.get('items') or {}).items():
            if not it or it.get('alt'):
                continue
            why = tier_violation(role, s.get('tier'), it.get('price'), rules, cfg)
            if why and not (base_role(role) in rel and relax_allowed(role, cfg)):
                out.append(f'{who}: {why}')
    return out


def core_missing(room: str, roles, purpose: str | None = None, cfg: dict | None = None) -> list:
    """Группы ядра комнаты (`bank_core_roles`: ключ `комната` и `комната:назначение`), в которых нет ни одной из `roles` (названия
    позиций набора; «диван 2» = «диван»). Пусто — ядро на месте. Комнаты в файле нет — ядра нет."""
    have = {base_role(r) for r in roles}
    core = (cfg if cfg is not None else config()).get('bank_core_roles') or {}
    return [g for g in [*core.get(room, []), *(core.get(f'{room}:{purpose}', []) if purpose else [])] if not (have & set(g))]


def mode_stamp(rules: dict | None = None, cfg: dict | None = None) -> str:
    """Метка режима для состояния удержания (`bank_keep`): '' — прежние квантили (как до правила: метки в файле нет), иначе
    `segments:<хеш>` версии границ и политики ролей — смена режима, границ или классов даёт другую метку и ячейки пересобираются."""
    if not bank_segments_on():
        return ''
    R = rules if rules is not None else PT.load()
    body = json.dumps({'v': R.get('version'), 'b': {k: v.get('boundaries_rub') for k, v in sorted((R.get('roles') or {}).items())},
                       'p': (cfg if cfg is not None else config()).get('bank_role_policy'),
                       'x': (cfg if cfg is not None else config()).get('tier_relaxed_allowed')}, ensure_ascii=False, sort_keys=True)
    return 'segments:' + hashlib.sha256(body.encode()).hexdigest()[:12]


def _selftest() -> int:
    bad = 0
    R = {'version': 't', 'roles': {'диван': {'boundaries_rub': [50000, 90000], 'families': 100, 'method': 'local'},
                                   'лампа': {'boundaries_rub': [4000, 9000], 'families': 100, 'method': 'local'},
                                   'ваза': {'boundaries_rub': [3000, 6000], 'families': 100, 'method': 'local'},
                                   'мало': {'boundaries_rub': None, 'families': 3, 'method': 'none'}}}
    C = {'bank_role_policy': {'strict': ['диван'], 'budgeted': ['лампа'], 'exempt': ['ваза'], 'no_bounds': ['мало']}, 'tier_relaxed_allowed': []}
    if quantile_band(list(range(100)), (0.05, 0.45)) != (5, 45) or quantile_band([], (0.1, 0.9)) != (0, 10 ** 9):
        bad += 1
        print('  FAIL: прежние квантили (запасной путь) — как compose2.tier_band')
    on = {t: tier_band('диван', t, [1, 2, 3], rules=R, segments=True, cfg=C) for t in BANK_TIERS}
    hit = [[t for t, (lo, hi) in on.items() if lo <= x <= hi] for x in (49999, 50000, 89999, 90000)]
    if hit != [['эконом'], ['комфорт'], ['комфорт'], ['премиум']] or tier_band('диван 2', 'эконом', rules=R, segments=True, cfg=C) != on['эконом']:
        bad += 1
        print('  FAIL: ступени банка не пересекаются: одна цена — одна ступень, «диван 2» — границы «дивана»', hit)
    if tier_band('мало', 'комфорт', [10, 20, 30, 40], rules=R, segments=True, cfg=C) != quantile_band([10, 20, 30, 40], LEGACY_Q['комфорт']) \
            or band_source('мало', R) != 'legacy':
        bad += 1
        print('  FAIL: роль без границ — запасной путь прежними квантилями')
    if tier_band('диван', 'комфорт', [1, 2, 3], rules=R, segments=False, cfg=C) != quantile_band([1, 2, 3], LEGACY_Q['комфорт']):
        bad += 1
        print('  FAIL: режим выключен — прежние квантили')
    bl = {t: tier_band('лампа', t, rules=R, segments=True, cfg=C) for t in BANK_TIERS}
    ok_ = lambda t, x: bl[t][0] <= x <= bl[t][1]  # noqa: E731
    if not (ok_('эконом', 1000) and ok_('эконом', 5000) and not ok_('эконом', 9000) and ok_('комфорт', 1000) and ok_('комфорт', 99999)
            and not ok_('премиум', 3999) and ok_('премиум', 5000) and ok_('премиум', 99999)):
        bad += 1
        print('  FAIL: budgeted — своя ступень ±1', bl)
    tv = lambda r, t, p: tier_violation(r, t, p, R, C)  # noqa: E731
    if tv('диван', 'комфорт', 60000) or not tv('диван', 'комфорт', 40000) or not tv('диван', 'эконом', 60000) or tv('диван 2', 'премиум', 95000):
        bad += 1
        print('  FAIL: strict — только своя ступень')
    if tv('лампа', 'эконом', 5000) or not tv('лампа', 'эконом', 9500) or not tv('лампа', 'премиум', 1000) or tv('лампа', 'комфорт', 9500):
        bad += 1
        print('  FAIL: budgeted — дальше соседней ступени нельзя')
    if tv('ваза', 'эконом', 9000) or tv('мало', 'эконом', 9000) or tv('диван', 'эконом', 0) or tv('нет такой', 'эконом', 9000):
        bad += 1
        print('  FAIL: exempt, роль без границ или цены, роль без класса — не проверяются')
    s_on, s_off = soft_may_drop_price('диван', True, C), soft_may_drop_price('диван', False, C)
    if s_on or not s_off or soft_may_drop_price('лампа', True, C) or not soft_may_drop_price('ваза', True, C) or not soft_may_drop_price('мало', True, C):
        bad += 1
        print('  FAIL: soft снимает цену только у exempt/без класса; выкл — как раньше у всех')
    if role_class('диван 2', C) != 'strict' or role_class('нет такой', C) is not None or relax_allowed('диван', C):
        bad += 1
        print('  FAIL: класс роли, «диван 2» = «диван», tier_relaxed у strict по умолчанию запрещён')
    # политика файла: каждая роль правила границ — ровно в одном классе (новая роль без класса = FAIL)
    pol = (config().get('bank_role_policy') or {})
    roles = set((PT.load().get('roles') or {}))
    seen = [r for c in (*CLASSES, 'no_bounds') for r in (pol.get(c) or [])]
    dup = sorted({r for r in seen if seen.count(r) > 1})
    if dup or roles - set(seen) or set(seen) - roles:
        bad += 1
        print('  FAIL: политика ролей: дубли', dup, 'без класса', sorted(roles - set(seen)), 'лишние', sorted(set(seen) - roles))
    if any(PT.bounds_of(r) is not None for r in pol.get('no_bounds') or []) or any(PT.bounds_of(r) is None for c in CLASSES for r in pol.get(c) or []):
        bad += 1
        print('  FAIL: no_bounds — только роли без границ; у ролей классов границы есть')
    if not bank_segments_on() and mode_stamp(R, C) != '':
        bad += 1
        print('  FAIL: режим выкл — метки режима нет (файл удержания как до правила)')
    os.environ['BANK_PRICE_SEGMENTS'] = '1'
    try:
        m1 = mode_stamp(R, C)
        m2 = mode_stamp({**R, 'version': 'u'}, C)
        m3 = mode_stamp(R, {**C, 'bank_role_policy': {**C['bank_role_policy'], 'strict': []}})
    finally:
        del os.environ['BANK_PRICE_SEGMENTS']
    if not m1.startswith('segments:') or len({m1, m2, m3}) != 3:
        bad += 1
        print('  FAIL: метка режима меняется со версией границ и политикой ролей', m1, m2, m3)
    mkset = lambda tier, price, **kw: {'set_id': 'x', 'tier': tier, 'items': {'диван': {'price': price}, 'лампа': {'price': 5000}, 'ваза': {'price': 90000}}, **kw}  # noqa: E731
    tp = lambda bank, cfg=C, seg=True: tier_problems(bank, R, cfg, seg)  # noqa: E731
    if tp([mkset('комфорт', 60000)]) or len(tp([mkset('премиум', 60000)])) != 1 or len(tp([mkset('комфорт', 60000), mkset('эконом', 60000)])) != 1:
        bad += 1
        print('  FAIL: валидатор цены: strict вне ступени — нарушение, своя ступень — чисто, лампа ±1 и ваза не считаются')
    if tp([mkset('премиум', 60000)], seg=False):
        bad += 1
        print('  FAIL: режим выкл — валидатор цены молчит (прежний банк на квантилях)')
    rel = mkset('премиум', 60000, tier_relaxed={'диван': {'from': 'комфорт', 'to': 'премиум'}})
    if len(tp([rel])) != 1 or tp([rel], {**C, 'tier_relaxed_allowed': ['диван']}):
        bad += 1
        print('  FAIL: tier_relaxed принимается, только если роль есть в tier_relaxed_allowed (по умолчанию пусто — нарушение остаётся)')
    CC = {'bank_core_roles': {'living': [['диван'], ['тв-тумба', 'стенка']], 'bedroom:couple': [['тумба прикроватная']]}}
    if core_missing('living', ['диван', 'стенка'], None, CC) or core_missing('living', ['диван 2'], None, CC) != [['тв-тумба', 'стенка']] \
            or core_missing('bedroom', [], 'couple', CC) != [['тумба прикроватная']] or core_missing('bedroom', [], 'single', CC) or core_missing('нет', [], None, CC):
        bad += 1
        print('  FAIL: ядро комнаты — группы «хотя бы одна»; ключ комната:назначение; «диван 2» = «диван»')
    print(f'bank_tiers selftest: случаев 17, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
