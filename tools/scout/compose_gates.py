#!/usr/bin/env python3
"""Ворота фото и меша первичной сборки `compose2` — fail-closed (план conv-13 п.2).

ЗАЧЕМ. Сборщик проверял фото (`img_alive`, `slot_contract.photo_ok`) и меш (`slot_contract.mesh_ok`) внутри
`try/except: pass`: упала проверка — товар проходил. Ночной валидатор `sets_incremental --contracts` при сбое того же
предиката товар НЕ пускает, поэтому свежая сборка уходила в банк с позициями, которые валидатор потом массово менял.
Теперь сбой проверки = товар не берём, а сколько раз и какая проверка падала — строка в журнале сборки (`summary`).

ЖИВОСТЬ ФОТО — ТОТ ЖЕ ПРЕДИКАТ, ЧТО У КОНТРАКТА (`sets_incremental._slot_ok` → `img_alive.alive_now`; T-20261021-09).
Сборка спрашивала мягкий `alive`: непроверенное фото — «живое». Пересборка 21.10 взяла комод с мёртвым фото (в кэше
записи не было) в 7 сетов, а сухой контракт тут же его снимал. Теперь непроверенное проверяется сразу и ложится в кэш.

  python3 compose_gates.py --selftest
"""
import collections
import sys

FAILS: collections.Counter = collections.Counter()   # {«какая проверка: класс ошибки»: сколько раз}
UNFIT: collections.Counter = collections.Counter()   # {причина «не мешепригоден»: сколько отказов} — строка журнала сборки


BLOCKED: dict | None = None   # sku → причина «меш не заказать / чёрный список кандидата»; None — ещё не загружен
MESHF = None                  # лёгкие факты мешевой пригодности (каталог одним запросом); None — ещё не загружены


def _mesh_facts():
    """Каталог одним запросом (`bank_ready.load_prod`: роль, представитель семейства, `mesh_required`, габариты, трансформер),
    готовые меши, стратегия ролей, квадратные роли, журнал решений по мешам и failed_terminal — то же, на чём `bank_ready.classify`
    судит мешевую позицию (как `bank_ready.load_facts`). Без медиа и живости фото (их проверяют ворота ниже). Один раз на сборку."""
    global MESHF
    if MESHF is None:
        import types
        import bank_ready as BR
        import render_strategy as RS
        from mesh_ready import mesh_ready_raw
        import bank_pending as BP
        import mesh_bind as MB
        import mesh_decisions as MD
        from mesh_queue import db
        failed = {r[0] for r in db("select distinct sku from mesh_jobs where status = 'failed_terminal'") if r and r[0]}
        MESHF = types.SimpleNamespace(prod=BR.load_prod(), mesh_ok=mesh_ready_raw(), strategy=RS.strategy,
                                      square=RS.square_roles(), rules=BP.rules(),
                                      decisions=MD.load(), failed=failed, awaiting=MB.awaiting_enrichment())
    return MESHF


def _blocked() -> dict:
    """ДО СБОРКИ (conv-14 шаг 2, `bank_pending.blocklist`): блоки политики из ТЕКУЩИХ фактов — журнал решений по мешам
    (`replace_needed`/`reject`) и failed_terminal, с раскрытием на всё семейство по `mesh_family_rep` (`bank_pending.policy_blocks`:
    `bank_ready.classify` наследует решение представителя всем цветам модели — T-20261023-08, Codex 23.10 «чёрный список до
    compose, не из вчерашнего pending»), плюс прочие записи состояния (ушёл, нет в каталоге) и, по ключу, мешевая роль без высоты.
    Ключи `rules/bank-candidate.json`: `compose_reject_blacklist` (блоки политики), `compose_no_height` (нет высоты, выключен).
    Загружается один раз на сборку."""
    global BLOCKED
    if BLOCKED is None:
        import bank_pending as BP
        r = BP.rules()
        nh, rj = bool(r.get('compose_no_height')), bool(r.get('compose_reject_blacklist'))
        M = _mesh_facts()
        BLOCKED = BP.blocklist(M.prod, M.strategy, BP.load_state(), no_height=nh, reject=rj, decisions=M.decisions,
                               failed=M.failed, mesh_ok=M.mesh_ok)
    return BLOCKED


def mesh_unfit(sku: str, role: str | None) -> str | None:
    """МЕШЕВАЯ РОЛЬ — ТОЛЬКО МЕШЕПРИГОДНОЕ (T-20261023-08, ночь 23.10: 27 необогащённых товаров divan.ru держали 31 ячейку в
    wait_catalog). Тот же суд, что у `bank_ready.classify` для мешевой позиции: гейт геометрии (высота, горизонталь, глубина,
    доказанный трансформер), затем «меш готов у товара или представителя» ИЛИ «представитель мешепригоден» (`mesh_required` —
    выход `mesh_bind.mark_required`: наличие, фото, обогащение со стилями, габариты, категория не без размеров). Иначе ячейка
    с этим товаром не станет готовой никогда — не берём. НЕ ХВАТАЕТ ТОЛЬКО ОБОГАЩЕНИЯ (`mesh_bind.awaiting_enrichment`: каталожная
    часть предиката пройдена) — берём: ночная порция обогащения берёт сперва товары кандидата (`enrich.py`), и следующей ночью
    товар мешепригоден; отрежь его здесь — он не попал бы в кандидата и не обогатился бы никогда (проба 23.10: без этого в больших
    комнатах эконома прямые диваны divan.ru сменились модульными до 271×176 и ковёр 300 перестал подходить — 7 новых дыр).
    Роль не мешевая или ключ `compose_mesh_eligible` выключен — None."""
    if not role:
        return None
    M = _mesh_facts()
    if not M.rules.get('compose_mesh_eligible', True):
        return None
    import bank_ready as BR
    b = BR.base_role(role)
    if M.strategy(b) != 'mesh':
        return None
    p = M.prod.get(sku)
    if not p:
        return 'нет в каталоге'
    geo = BR.geometry(b, p, M.square)
    if geo:
        return geo
    rep = p.get('rep') or sku
    if sku in M.mesh_ok or rep in M.mesh_ok:
        return None
    if (M.prod.get(rep) or p).get('eligible') or rep in M.awaiting:
        return None                 # ждёт только обогащения — его даст ночная порция (товары кандидата — первыми)
    return 'не мешепригоден (mesh_required=false)'


def admit(sku: str, img: str | None, role: str | None = None) -> str | None:
    """None — товар годен по фото и мешу; иначе причина отказа. Сбой проверки — отказ и счёт в `FAILS`.
    `role` — слот сборки: для мешевой роли ещё и мешепригодность (`mesh_unfit`)."""
    try:
        why = _blocked().get(sku)
    except Exception as e:  # noqa: BLE001 — fail-closed, как прочие ворота
        FAILS[f'чёрный список: {type(e).__name__}'] += 1
        return 'сбой проверки чёрного списка'
    if why:
        return why
    try:
        why = mesh_unfit(sku, role)
    except Exception as e:  # noqa: BLE001 — fail-closed
        FAILS[f'мешепригодность: {type(e).__name__}'] += 1
        return 'сбой проверки мешепригодности'
    if why:
        UNFIT[why] += 1
        return why
    if not img:
        return 'нет фото'
    try:
        from img_alive import alive_now
        if not alive_now(img):
            return 'фото мёртвое'
    except Exception as e:  # noqa: BLE001 — fail-closed, считаем
        FAILS[f'живость фото: {type(e).__name__}'] += 1
        return 'сбой проверки фото'
    try:
        from slot_contract import photo_ok
        if not photo_ok(sku, context='new'):
            return 'фото негодное'
    except Exception as e:  # noqa: BLE001
        FAILS[f'пригодность фото: {type(e).__name__}'] += 1
        return 'сбой проверки фото'
    try:
        # Готовность представления (Codex P0-4): без неё MESH_GATE_PHASE=hard_new не действовал в ПЕРВИЧНОЙ сборке
        from slot_contract import mesh_ok
        if not mesh_ok(sku):
            return 'нет меша'
    except Exception as e:  # noqa: BLE001
        FAILS[f'меш: {type(e).__name__}'] += 1
        return 'сбой проверки меша'
    return None


# ВЫЛЕТ ПОДВЕСА (catalog-holes-bank Н2в; разбор Codex 23.10). Под люстрой нужен проход 210 см (СП 59.13330.2020;
# ADA §307.4 — 203 см): подвес не длиннее «потолок − 210». Потолок — параметр (`ceiling_cm`): у квартиры с известной высотой —
# её, иначе базовые 270 (→ 60 см). Банк комплектов общий для квартир — собирается и лечится на базовом потолке.
# Этап 2 (23.10, без миграции): поля вылета в `dims_evidence.h` (`dim_resolver.pendant_drop`) — гейт берёт `drop_min`
# (минимальную подвеску: регулируемый подвес укорачивают); нет полей — как в этапе 1 (высота = вылет).
CEILING_CM, CLEARANCE_CM = 270, 210
DROP_MAX_CM = CEILING_CM - CLEARANCE_CM
_NO = {'', 'нет', 'no', '0', '-', 'false'}


def drop_limit(ceiling_cm: float | None = None) -> float:
    """Самый длинный допустимый вылет при этом потолке, см."""
    return float(ceiling_cm or CEILING_CM) - CLEARANCE_CM


def pendant_out(h: float | None, h_source: str | None, h_cm: str | float | None, adjustable: str | None,
                drop_min: str | float | None = None, ceiling_cm: float | None = None) -> str | None:
    """None — люстра годна для слота по вылету; иначе причина. Без высоты и без признаков подвеса — как раньше (ждёт каталог)."""
    lim, ceil = drop_limit(ceiling_cm), float(ceiling_cm or CEILING_CM)
    norm = f'{lim:g} (проход {CLEARANCE_CM} при потолке {ceil:g})'
    try:
        dmin = float(drop_min) if drop_min not in (None, '') else None
    except (TypeError, ValueError):
        dmin = None
    if dmin is not None:
        return f"{'вылет' if h is not None else 'подвес'} {dmin:g} см > {norm}" if dmin > lim else None
    if h is not None:
        return f'вылет {h:g} см > {norm}' if h > lim else None
    if (h_source or '').endswith('-suspension'):
        try:
            return f'подвес {float(h_cm):g} см > {norm}'
        except (TypeError, ValueError):
            return 'подвес длиннее нормы, число не разобрано'
    if (adjustable or '').strip().lower() not in _NO:
        return 'регулируемый подвес без высоты — вылет неизвестен'
    return None


def pendant_out_media(m: dict | None, ceiling_cm: float | None = None) -> str | None:
    """`pendant_out` по записи `catalog_media.media` — для лечения банка (замена люстры проходит ту же норму, что сборка)."""
    m = m or {}
    return pendant_out(m.get('h'), m.get('h_src'), m.get('h_cm'), m.get('adj'), m.get('drop_min'), ceiling_cm)


def summary() -> str:
    n = sum(FAILS.values())
    unfit = ('; мешевой роли не мешепригодных отказов: ' + ', '.join(f'{k} ×{v}' for k, v in UNFIT.most_common())) \
        if UNFIT else ''
    if not n:
        return 'ворота фото/меша: сбоев проверки 0' + unfit
    return (f'WARN:compose_gate_fail: сбоев проверки {n} — эти товары НЕ взяты: '
            + ', '.join(f'{k} ×{v}' for k, v in FAILS.most_common()) + unfit)


def _selftest() -> int:
    import types
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def boom(*a, **k):
        raise RuntimeError('нет базы')

    saved = {m: sys.modules.get(m) for m in ('img_alive', 'slot_contract')}

    P = lambda **k: {'role': 'диван', 'status': 'none', 'eligible': True, 'rep': None, 'w': 200, 'd': 90, 'h': 80,  # noqa: E731
                     'dia': None, 'has_h': True, 'tr': False, 'proven': False, **k}
    prod = {'1:ok': P(), '1:ne': P(eligible=False), '1:noh': P(h=None, has_h=False, eligible=False),
            '1:mesh': P(eligible=False), '1:var': P(eligible=False, rep='1:ok'), '1:var2': P(eligible=False, rep='1:ne'),
            '1:bed': P(tr=True), '1:pil': P(role='подушка', eligible=False, h=None), '1:wait': P(eligible=False)}

    def fake(alive=lambda u: True, photo=lambda s, context=None: True, mesh=lambda s: True, blocked=None, rules=None):
        global BLOCKED, MESHF
        sys.modules['img_alive'] = types.SimpleNamespace(alive_now=alive, alive=lambda u, unknown=True: True)
        sys.modules['slot_contract'] = types.SimpleNamespace(photo_ok=photo, mesh_ok=mesh)
        BLOCKED = {} if blocked is None else blocked
        MESHF = types.SimpleNamespace(prod=prod, mesh_ok={'1:mesh'}, square=set(), rules=rules or {}, awaiting={'1:wait'},
                                      strategy=lambda r: 'cutout' if r == 'подушка' else 'mesh')
        FAILS.clear()
        UNFIT.clear()

    try:
        fake()
        ok('всё годно — товар берём', admit('1:a', '//img') is None and summary().endswith('0'))
        ok('нет фото — отказ', admit('1:a', None) == 'нет фото')
        fake(alive=lambda u: False)
        ok('мёртвое фото по строгой проверке (как у контракта `_slot_ok`) — отказ, даже если мягкий `alive` «жив»',
           admit('1:a', '//img') == 'фото мёртвое' and not FAILS)
        fake(alive=boom)
        ok('сбой проверки живости — отказ и счёт', admit('1:a', '//img') == 'сбой проверки фото'
           and FAILS['живость фото: RuntimeError'] == 1)
        fake(photo=boom)
        ok('сбой photo_ok — отказ и счёт', admit('1:a', '//img') == 'сбой проверки фото' and sum(FAILS.values()) == 1)
        fake(mesh=boom)
        r = admit('1:a', '//img'), admit('1:b', '//img')
        ok('сбой mesh_ok — отказ, счёт по каждому товару, громкая строка журнала',
           r == ('сбой проверки меша',) * 2 and FAILS['меш: RuntimeError'] == 2 and summary().startswith('WARN:'))
        fake(mesh=lambda s: False)
        ok('нет меша — отказ без счёта сбоя', admit('1:a', '//img') == 'нет меша' and not FAILS)
        fake(blocked={'1:k': 'нет высоты (h_cm) — меш не заказать'})
        ok('мешевая роль без высоты / чёрный список кандидата — отказ до сборки с причиной, прочие — как раньше',
           admit('1:k', '//img') == 'нет высоты (h_cm) — меш не заказать' and admit('1:a', '//img') is None)
        fake()
        ok('мешевая роль: мешепригодный — берём; без обогащения (mesh_required=false) — отказ со счётом в журнале',
           admit('1:ok', '//img', 'диван') is None and 'не мешепригоден' in (admit('1:ne', '//img', 'диван 2') or '')
           and 'мешевой роли не мешепригодных отказов' in summary())
        ok('без высоты — отказ по геометрии (как classify: wait_catalog навсегда); трансформер без доказанных размеров — отказ',
           admit('1:noh', '//img', 'диван') == 'нет высоты (h_cm)' and 'трансформер' in (admit('1:bed', '//img', 'диван') or ''))
        ok('меш готов у товара или у представителя, мешепригоден представитель — берём; представитель не годен — отказ',
           admit('1:mesh', '//img', 'диван') is None and admit('1:var', '//img', 'диван') is None
           and admit('1:var2', '//img', 'диван') is not None)
        ok('не хватает только обогащения (каталожная часть предиката пройдена) — берём: обогащение возьмёт товар кандидата первым',
           admit('1:wait', '//img', 'диван') is None)
        ok('не мешевая роль (подушка) и вызов без роли — мешепригодность не спрашиваем',
           admit('1:pil', '//img', 'подушка') is None and admit('1:ne', '//img') is None)
        fake(rules={'compose_mesh_eligible': False})
        ok('ключ compose_mesh_eligible=false — ворота выключены', admit('1:ne', '//img', 'диван') is None)
        fake()
        MESHF.prod = None                                             # сломанные факты — отказ и счёт, не пропуск
        ok('сбой проверки мешепригодности — отказ и счёт (fail-closed)',
           admit('1:ok', '//img', 'диван') == 'сбой проверки мешепригодности'
           and FAILS['мешепригодность: AttributeError'] == 1)
        ok('вылет: 60 см — годен, 61 — вне слота с причиной', pendant_out(60, 'param', None, 'Да') is None
           and 'вылет 61 см > 60' in (pendant_out(61, 'param', None, '') or ''))
        ok('плоская и обычная люстра — годна', pendant_out(2.5, 'param', None, 'Нет') is None)
        ok('длинный подвес без h (резолвер: suspension) — вне слота, число в причине',
           'подвес 230 см' in (pendant_out(None, 'param-suspension', '230.0', '') or ''))
        ok('регулируемый без высоты — вне слота; «нет»/пусто без высоты — как раньше (ждёт каталог)',
           pendant_out(None, None, None, 'да') and pendant_out(None, None, None, 'нет') is None
           and pendant_out(None, 'param-insane', None, None) is None)
        # этап 2: потолок — параметр; поля вылета — минимальная подвеска решает
        ok('потолок 300 → норма 90: вылет 80 годен, при базовом 270 — нет; 250 → норма 40',
           pendant_out(80, 'param', None, '', ceiling_cm=300) is None and pendant_out(80, 'param', None, '')
           and 'вылет 45 см > 40 (проход 210 при потолке 250)' in (pendant_out(45, 'param', None, '', ceiling_cm=250) or ''))
        ok('диапазон 36/136: минимум 36 — годен при 270; подвес 230 с регулировкой — по минимуму 230, вне слота',
           pendant_out(36, 'prior', None, 'да', drop_min='36.0') is None
           and 'подвес 230 см' in (pendant_out(None, 'param-suspension', '230.0', 'да', drop_min=230) or ''))
        ok('лечение: запись медиа с drop_min и потолком',
           pendant_out_media({'h': 36, 'drop_min': '70'}) and pendant_out_media({'h': 36, 'drop_min': '70'}, ceiling_cm=300) is None)
        sys.modules['slot_contract'] = types.SimpleNamespace()     # модуль без функций — ImportError
        FAILS.clear()
        ok('нет функции проверки — отказ (а не пропуск)', admit('1:a', '//img') == 'сбой проверки фото')
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
        FAILS.clear()
        UNFIT.clear()
        globals()['BLOCKED'] = None
        globals()['MESHF'] = None
    print(f'compose_gates selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
