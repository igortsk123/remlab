#!/usr/bin/env python3
"""Сравнение банков «было / стало» и инварианты кандидата (план conv-13 п.3, критерии приёмки).

ЗАЧЕМ. Новый банк собирается рядом (`sets3.next.json`, `bank_paths`) и подменяет живой только после ⚑ владельца.
До показа нужны числа, а не «на глаз»: та же карта сетов, ни одного ушедшего товара, пары и контракты чисты,
ссылки партнёрские и текущие, ключевые роли на месте. Скрипт ничего не пишет — только читает оба банка и каталог.

Критерии (каждый — число; `ok` = выполнен):
  identity       — 126 уникальных ячеек (band, style, tier), set_id у каждого и без повторов, карта «номер массива →
                   set_id» та же, что у прежнего банка или у снимка `sets-id-map.json` (conv-14 шаг 1, `set_identity.verify`);
  map            — 126 сетов, та же карта (band, style, tier, set_id) по номерам;
  gone           — позиций, которых нет в каталоге (`catalog_media.media` → None / state gone), = 0;
  pair_mismatch  — экземпляр пары ≠ основному (`sets_incremental.sync_pairs`, сухо), = 0;
  contracts      — позиций вне контракта слота (`sets_incremental._slot_ok` — те же ворота, что у ночного шага), = 0;
  role_mismatch  — позиций, чья текущая роль каталога несовместима со слотом (`slot_catalog_compatible`: сиденья;
                   «кресло 2» — по базовой роли; «банкетка» — из пуф/диван), = 0; запасной такой — `alt_bad` «не той роли каталога»;
  url_stale      — ссылка позиции ≠ текущей партнёрской из каталога (или пустая), = 0; сетью НЕ проверяем —
                   стучаться ботом в партнёрскую ссылку нельзя (накрутка кликов, `catalog_media`);
  alt_bad        — запасные (`alternates`): без SKU, ушедшие из каталога, равные выбранному, повтор в роли, не той роли
                   (`item_function.fits_role` по имени и размерам каталога), = 0; разбивка — `alt_why`;
  core_missing   — сетов без дивана / столика / носителя ТВ (тв-тумба или стенка) / обязательной пары
                   (≥25 м² с диваном и креслом — кресло 2 или qty≥2, как `test_bank_coverage`), по каждой = 0.
Дельта: сколько слотов сменило SKU, по стилям; роли, которые появились или пропали.

  ~/venvs/scout/bin/python bank_invariants.py --old sets3.json --new ~/remlab-logs/t21-09/sets3.next.json [--json out.json]
  ~/venvs/scout/bin/python bank_invariants.py                     # один живой банк против снимка номеров sets-id-map.json
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BEARERS = ('тв-тумба', 'стенка')


def sku(it: dict | None) -> str | None:
    return f"{it.get('mid')}:{it.get('eid')}" if it and it.get('eid') else None


def core_missing(s: dict) -> list[str]:
    it = s.get('items') or {}
    out = [r for r in ('диван', 'столик') if r not in it]
    if not any(b in it for b in BEARERS):
        out.append('носитель ТВ')
    if (s.get('m2') or 0) >= 25 and 'диван' in it and 'кресло' in it \
            and 'кресло 2' not in it and int(it['кресло'].get('qty') or 1) < 2:
        out.append('пара кресел')
    return out


# ВЫБОР НАБОРА — ПО ОБЯЗАТЕЛЬНОМУ ЯДРУ, А НЕ ПО ЧИСЛУ ПРЕДМЕТОВ (T-20261112-122, Codex 12.11 `_intake/codex/2026-11-12-dresser-small-living-answer.md`
# § 5). Прежний ключ туров и /demo награждал набор за лишний предмет («больше расставляемых»): набор без столика, но с комодом выигрывал
# у набора со столиком, геометрия тура теряла столик, и гостиная выходила пустой (MEDIA_MISSING). Теперь: сперва полное ядро (диван,
# столик, носитель ТВ — `core_missing`), затем годные модели ЯДРА, затем годные модели прочего, затем дыры состава. Лишний предмет
# (комод, пуф) ключ не двигает: встанет ли он — решает расстановка. Один ключ на туры (`trial_demo._style_ranking`) и /demo
# (`flat215_demo.pick_banks`, `fill_banks`).
CORE_ROLES = ('диван', 'столик') + BEARERS


def selection_key(s: dict, no_mesh_core: int = 0, no_mesh: int = 0) -> tuple:
    """Ключ выбора набора стиля (меньше — лучше): (нет ролей ядра, ядро без годной модели, прочее без годной модели, дыры состава).
    Число предметов в ключ не входит. Номер набора (стабильный порядок) добавляет вызывающий."""
    return (len(core_missing(s)), int(no_mesh_core), int(no_mesh), len(s.get('gaps') or []))


# АТОМ «КОМОД + ЛАМПА» (T-20261112-122, паспорт `living.json` light.dresser_lamp): комод — необязательный предмет и показывается
# только с лампой на нём. Одно правило на туры (`trial_demo.place`) и /demo (`flat215_demo` после `lamp_decor`); банк держит то же
# при сборке (`compose2`: комод без лампы из состава вон).
def dresser_atom_drop(roles, lamp_placed: bool) -> list[str]:
    """Роли комода, которые снять, раз лампа на комоде не встала (нет в наборе, не влезла, без модели). Лампа есть — ничего."""
    if lamp_placed:
        return []
    return [r for r in roles if re.sub(r'\s+\d+$', '', r or '') == 'комод']


# КОМОД УСТУПАЕТ ЯДРУ (владелец 13.11, TG 1406: «комод уступает ТВ и столику»; T-20261113-12). Ядро считаем ПО ФАКТУ: роли ядра,
# что есть в наборе, против предметов, что встали в комнату (не по списку `absent_roles`: роль, срезанную геометрией тура, он не
# видит). Ядро неполное — комода (с лампой) в варианте нет. Одно правило на туры (`trial_demo.place`, `retry_next`, `rescue`) и
# /demo (`flat215_demo` после атома); решатель держит то же ярусом `core_missing` ключа `plan_key` v1.
def _role_base(r: str) -> str:
    return re.sub(r'\s+\d+$', '', r or '')


def core_lost(want_roles, got_roles) -> list[str]:
    """Роли ядра, которые в наборе есть, а в комнату не встали: «диван», «столик», «носитель ТВ» (тумба или стенка)."""
    want = {_role_base(r) for r in want_roles or []}
    got = {_role_base(r) for r in got_roles or []}
    out = [r for r in ('диван', 'столик') if r in want and r not in got]
    if want & set(BEARERS) and not got & set(BEARERS):
        out.append('носитель ТВ')
    return out


# ЯДРО ВАРИАНТА ГОСТИНОЙ — ОДНО НА ВСЕ МЕСТА (T-20261113-23): подбор тура (`trial_demo.core_gone`: вариант без ядра скрыт) и сторож
# перечитки (`tools/floorplan/regress.page_rooms`: «стиль с мебелью» гостиной = стиль с полным ядром). Требуем независимо от состава набора.
LIVING_CORE = ('диван', 'столик', 'тв-тумба')


def living_core_gone(placed_roles) -> list[str]:
    """Роли ядра гостиной, которых нет среди вставших предметов: «диван», «столик», «носитель ТВ» (тумба или стенка)."""
    return core_lost(LIVING_CORE, placed_roles)


def dresser_yield_drop(want_roles, got_roles) -> list[str]:
    """Роли комода, которые снять, раз ядро потеряно (`core_lost`). Ядро полное — ничего."""
    if not core_lost(want_roles, got_roles):
        return []
    return [r for r in got_roles or [] if _role_base(r) == 'комод']


# ПРИЗНАК СТОЛОВОЙ — ОДИН НА ДВА МЕСТА (T-20261112-100): сторож доли столовой ночного экзамена
# (`services/planner-solver/tests/test_contour_features.py:test_dining_share_watchdog`) и экзамен продвижения ячейки
# (`bank_promote.exam_verdict`: у живого банка столовая встала, у смешанного — нет → провал). Второе определение не заводить.
def has_dining_table(s: dict) -> bool:
    """В сете есть обеденный стол (слот «стол обеденный…»): без него столовой в сцене быть не может."""
    it = s.get('items') or {}
    roles = list(it) if isinstance(it, dict) else [i.get('role') or '' for i in it]
    return any((r or '').startswith('стол обеден') for r in roles)


def dining_placed(row: dict | None) -> bool:
    """Столовая встала в сцене экзамена: тег `+din` в `templates` строки отчёта `acceptance-report-*.json[l]`."""
    return '+din' in ((row or {}).get('templates') or '')


# СЛОТ ↔ РОЛЬ КАТАЛОГА (T-20261105-53/2, Codex 05.11): товар держит слот, только пока его текущая `products.cat_role`
# совместима со слотом. Иначе после смены роли в каталоге («Босс пуф» был креслом → стал пуфом) удержание прошлого
# кандидата (`compose2._keep_check`), инварианты и строгий promote (`bank_promote.strict`) его не замечали: сборка выбирает
# по роли, а удержание и проверки роль не читали. Одна функция на все три места. Нумерованный слот («кресло 2») — по базовой
# роли. Планировочный слот «банкетка» (не роль каталога) берёт пуф/диван (`compose2.py` Q6a, `capabilities.py`).
# Сторожим только роли сидений: их трогает правило по названию (`category_map.seat_role`); у прочих слотов законные
# расхождения есть (подушка без роли, витрина из стеллажа — замер живого банка 05.11), их сюда не включать без таблицы.
SEAT_SLOT_ROLES = frozenset({'диван', 'кресло', 'пуф', 'стул'})
PLANNING_SLOT_SOURCES = {'банкетка': frozenset({'пуф', 'диван'})}


def slot_catalog_compatible(slot: str, cat_role: str | None) -> bool:
    """Совместима ли роль каталога товара `cat_role` (None — без роли) со слотом банка `slot`."""
    base = re.sub(r'\s+\d+$', '', slot or '')
    if base in PLANNING_SLOT_SOURCES:
        return cat_role in PLANNING_SLOT_SOURCES[base]
    if base not in SEAT_SLOT_ROLES:
        return True
    return cat_role == base


def catalog_role_bad(slot: str, m: dict | None) -> str | None:
    """Причина «не той роли каталога» по записи `catalog_media.media` (без поля роли — не судим), иначе None."""
    if not m or 'cat_role' not in m or slot_catalog_compatible(slot, m['cat_role']):
        return None
    return f"роль каталога «{m['cat_role'] or 'нет'}»"


def _probe(m: dict | None) -> dict | None:
    return {k: m.get(k) for k in ('name', 'w', 'd', 'h', 'dia')} if m else None


def _alt_reason(role: str, a: dict, chosen: dict | None, m: dict | None, seen: set, fits, chosen_m: dict | None = None) -> str | None:
    """Почему запасной негоден: нет SKU, ушёл из каталога, равен выбранному, повтор в роли, не той роли.
    «Не той роли» — ОТНОСИТЕЛЬНО выбранного: функцию роли (`fits_role`) проходит выбранный товар, а запасной — нет.
    Абсолютная проверка врёт там, где у роли нет правила подтипа (тв-тумба: правило не задано — `generic` не входит
    в разрешённые, и негодным выходит каждый товар, включая выбранный, — замер на живом банке 22.10)."""
    if not a.get('eid'):
        return 'нет SKU'
    if not m or m.get('state') == 'gone':
        return 'ушёл'
    if catalog_role_bad(role, m):
        return 'не той роли каталога'
    if sku(a) == sku(chosen):
        return 'равен выбранному'
    if sku(a) in seen:
        return 'повтор'
    base = re.sub(r'\s+\d+$', '', role)
    if fits is not None and chosen_m is not None and fits(base, _probe(chosen_m))[0] and not fits(base, _probe(m))[0]:
        return 'не той роли'
    return None


def check(sets: list, ref: list | None, media, slot_ok, sync_pairs, fits=None, id_map: dict | None = None,
          cells: int = 126) -> dict:
    """Инварианты банка `sets` (`ref` — прежний банк для карты; `id_map` — снимок «номер → set_id» живого банка,
    `sets-id-map.json`, если прежнего банка нет). Чистая относительно файлов: каталог и ворота — аргументы."""
    import set_identity as SID
    r = {'sets': len(sets)}
    # ИДЕНТИЧНОСТЬ (conv-14 шаг 1): 126 уникальных ячеек (band, style, tier), set_id у каждого и без повторов,
    # карта «номер массива → set_id» та же, что у живого банка
    ident = SID.verify(sets, ref, cells=cells)
    if ref is not None:
        key4 = lambda s: (s.get('band'), s.get('style'), s.get('tier'), s.get('set_id'))  # noqa: E731
        diff, n_ref = [i + 1 for i, (a, b) in enumerate(zip(ref, sets)) if key4(a) != key4(b)], len(ref)
    elif id_map:
        diff, n_ref = [n for n, sid in id_map.items() if n > len(sets) or sets[n - 1].get('set_id') != sid], len(id_map)
        if diff or n_ref != len(sets):
            ident.append(f'карта «номер → set_id» разошлась со снимком: номера {diff[:5]}'
                         + (f', в снимке {n_ref} против {len(sets)}' if n_ref != len(sets) else ''))
    r['identity'] = ident
    r['identity_ok'] = not ident
    if ref is not None or id_map:
        r['map_diff'] = diff[:20] + (['…'] if len(diff) > 20 else [])
        r['map_ok'] = not diff and len(sets) == n_ref == cells
    gone, url_stale, contracts, alt_bad, role_bad = [], [], [], [], []
    for n, s in enumerate(sets, 1):
        items = s.get('items') or {}
        for role, it in items.items():
            if not it or not it.get('eid'):
                continue
            m = media(it.get('mid'), it.get('eid'))
            if not m or m.get('state') == 'gone':
                gone.append((n, role, sku(it)))
            elif not it.get('url') or it.get('url') != m.get('url'):
                url_stale.append((n, role, sku(it)))
            why = catalog_role_bad(role, m)
            if why:
                role_bad.append((n, role, sku(it), why))
            if not slot_ok(role, it, s):
                contracts.append((n, role, sku(it)))
        for role, alts in (s.get('alternates') or {}).items():
            seen: set = set()
            ch = items.get(role)
            ch_m = media(ch.get('mid'), ch.get('eid')) if ch and ch.get('eid') else None
            for a in alts or []:
                m = media(a.get('mid'), a.get('eid')) if a.get('eid') else None
                why = _alt_reason(role, a, ch, m, seen, fits, ch_m)
                if why:
                    alt_bad.append((n, role, sku(a), why))
                seen.add(sku(a))
    pairs = sync_pairs(json.loads(json.dumps(sets)), apply=False)
    miss = collections.Counter(x for s in sets for x in core_missing(s))
    r.update(gone=len(gone), gone_rows=gone[:30], url_stale=len(url_stale), url_rows=url_stale[:30],
             contracts=len(contracts), contracts_rows=contracts[:30], role_mismatch=len(role_bad), role_rows=role_bad[:30],
             pair_mismatch=len(pairs), pair_rows=pairs[:30],
             alt_bad=len(alt_bad), alt_why=dict(collections.Counter(x[3] for x in alt_bad)), alt_rows=alt_bad[:30],
             core_missing=dict(miss),
             gaps_declared=dict(collections.Counter(str(g).split(' — ')[0] for s in sets for g in (s.get('gaps') or []))))
    r['ok'] = (not ident and r.get('map_ok', True) and not gone and not url_stale and not contracts and not role_bad
               and not pairs and not alt_bad and not miss)
    return r


def delta(old: list, new: list) -> dict:
    """Сколько слотов сменило SKU — по стилям; роли, которые появились/пропали (по set_id, не по номеру)."""
    by_id = {s.get('set_id'): s for s in old}
    st = collections.defaultdict(lambda: collections.Counter())
    for s in new:
        o = by_id.get(s.get('set_id'))
        c = st[s.get('style')]
        if o is None:
            c['сет новый'] += 1
            continue
        a, b = o.get('items') or {}, s.get('items') or {}
        for role in set(a) | set(b):
            if role not in a:
                c['роль появилась'] += 1
            elif role not in b:
                c['роль пропала'] += 1
            elif sku(a[role]) != sku(b[role]):
                c['SKU сменился'] += 1
            else:
                c['без изменений'] += 1
    return {k: dict(v) for k, v in sorted(st.items(), key=lambda kv: str(kv[0]))}


def _line(side: str, r: dict) -> str:
    return (f"[{side}] сетов {r['sets']}"
            + (f", карта {'та же' if r['map_ok'] else 'РАЗНАЯ ' + str(r['map_diff'])}" if 'map_ok' in r else '')
            + f"; идентичность {'цела' if r['identity_ok'] else 'НАРУШЕНА: ' + '; '.join(r['identity'])}"
            + f"; ушедших {r['gone']}, ссылок не текущих {r['url_stale']}, вне контракта {r['contracts']}, "
              f"не той роли каталога {r['role_mismatch']}, "
              f"пар разошлось {r['pair_mismatch']}, запасных негодных {r['alt_bad']} {r['alt_why'] or ''}; "
              f"без ключевых ролей {r['core_missing'] or 0}; итог {'OK' if r['ok'] else 'НЕ ГОДЕН'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default=os.path.join(HERE, 'sets3.json'))
    ap.add_argument('--new', default=None, help='кандидат; без него — проверка одного --old по снимку номеров --map')
    ap.add_argument('--map', default=os.path.join(HERE, 'sets-id-map.json'))
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    import sets_incremental as SI
    from catalog_media import media
    from item_function import fits_role
    old = json.load(open(a.old, encoding='utf-8'))
    id_map = ({int(k): v for k, v in json.load(open(a.map, encoding='utf-8')).items()}
              if a.map and os.path.exists(a.map) else None)
    rep = {'old': check(old, None, media, SI._slot_ok, SI.sync_pairs, fits_role, id_map=id_map)}
    if a.new:
        new = json.load(open(a.new, encoding='utf-8'))
        rep['new'] = check(new, old, media, SI._slot_ok, SI.sync_pairs, fits_role)
        rep['delta'] = delta(old, new)
    for side in ('old', 'new'):
        if side in rep:
            print(_line(side, rep[side]))
    for style, c in (rep.get('delta') or {}).items():
        print(f'  дельта {style}: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())))
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    return 0 if rep['new' if a.new else 'old']['ok'] else 1


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def mk(sid, items, m2=15, style='сканди', alts=None, band='14-16', tier='эконом'):
        return {'band': band, 'style': style, 'tier': tier, 'set_id': sid, 'm2': m2, 'items': items,
                'alternates': alts or {}}
    it = lambda e, **k: dict(mid=1, eid=e, url=f'u{e}', **k)  # noqa: E731
    cat = {('1', 'a'): {'state': 'available', 'url': 'ua', 'name': 'Диван'}, ('1', 'b'): {'state': 'available', 'url': 'ub'},
           ('1', 'c'): {'state': 'available', 'url': 'uc'}, ('1', 'g'): {'state': 'gone', 'url': 'ug'},
           ('1', 't'): {'state': 'available', 'url': 'ut', 'name': 'Табурет'}}
    media = lambda mid, eid: cat.get((str(mid), str(eid)))  # noqa: E731
    core = {'диван': it('a'), 'столик': it('b'), 'тв-тумба': it('c')}
    bank = [mk(f's{n}', core, band=b, style=st, tier=t, alts={'диван': [it('b')]}) for n, (b, st, t) in enumerate(
        ((b, st, t) for b in ('14-16', '17-20', '21-25', '26-30', '31-40', '41-50', '50+')
         for st in ('сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди')
         for t in ('эконом', 'комфорт', 'премиум')), 1)]
    pairs0 = lambda sets, apply=False: []  # noqa: E731
    yes = lambda *x: True  # noqa: E731
    r = check(bank, bank, media, yes, pairs0)
    ok('чистый банк 126 ячеек — ok, карта та же, идентичность цела', r['ok'] and r['map_ok'] and r['identity_ok'])
    badset = mk('s1', {'диван': it('g'), 'столик': dict(it('b'), url='old'), 'тв-тумба': it('c')},
                alts={'диван': [it('g'), it('g')], 'столик': [it('b')]})
    r = check([badset], None, media, lambda role, i, s: role != 'тв-тумба', lambda sets, apply=False: [(1,)], cells=1)
    ok('ушедший, старая ссылка, вне контракта, пара, запасные (ушедший ×2 и равный выбранному) — каждый счётчик',
       (r['gone'], r['url_stale'], r['contracts'], r['pair_mismatch'], r['alt_bad']) == (1, 1, 1, 1, 3) and not r['ok'])
    fits = lambda role, p: (role != 'диван' or 'Диван' in (p.get('name') or ''), '')  # noqa: E731
    alts = mk('s1', core, alts={'диван': [it('b'), it('t'), it('t')]})
    r = check([alts], None, media, yes, pairs0, fits=fits, cells=1)
    ok('запасной не той роли (табурет у дивана) и повтор в роли — негодны, с причиной',
       r['alt_why'] == {'не той роли': 2, 'повтор': 1})
    tv = mk('s1', {'диван': it('b'), 'столик': it('b'), 'тв-тумба': it('c')}, alts={'диван': [it('t')]})
    r = check([tv], None, media, yes, pairs0, fits=fits, cells=1)
    ok('выбранный сам не проходит функцию роли (нет правила подтипа) — запасного «не той ролью» не судим', r['alt_bad'] == 0)
    r = check([mk('s1', {'столик': it('b')}, m2=26), mk('s2', {'диван': it('a'), 'кресло': it('b'), 'стенка': it('c'),
                                                               'столик': it('b')}, m2=26, style='лофт')], None, media,
              yes, pairs0, cells=2)
    ok('ключевые роли: диван, носитель ТВ, пара кресел ≥25 м² — по отдельности',
       r['core_missing'] == {'диван': 1, 'носитель ТВ': 1, 'пара кресел': 1})
    r = check(bank[:125], bank, media, yes, pairs0)
    ok('125 сетов против 126 — карта не та, идентичность нарушена', not r['map_ok'] and not r['identity_ok'] and not r['ok'])
    dup = bank[:125] + [dict(bank[0])]
    r = check(dup, None, media, yes, pairs0)
    ok('дубль ячейки и set_id — идентичность нарушена', not r['identity_ok'] and not r['ok'])
    shifted = [bank[1], bank[0]] + bank[2:]
    r = check(shifted, None, media, yes, pairs0, id_map={n: s['set_id'] for n, s in enumerate(bank, 1)})
    ok('сдвиг порядка против снимка номеров — карта не та', not r['map_ok'] and not r['identity_ok'] and r['map_diff'] == [1, 2])
    nid = [dict(s) for s in bank]
    nid[5].pop('set_id')
    ok('сет без set_id — идентичность нарушена', not check(nid, None, media, yes, pairs0)['identity_ok'])
    # слот ↔ роль каталога (T-53/2): «Босс пуф» в кресле после смены роли; банкетка из пуфа — законно; без поля — не судим
    sc = slot_catalog_compatible
    ok('совместимость: кресло 2←кресло, банкетка←пуф/диван, подушка←нет роли — да; кресло←пуф, диван←нет роли, '
       'банкетка←кресло — нет',
       sc('кресло 2', 'кресло') and sc('банкетка', 'пуф') and sc('банкетка', 'диван') and sc('подушка', None)
       and sc('витрина', 'стеллаж') and not sc('кресло', 'пуф') and not sc('кресло 2', 'пуф') and not sc('диван', None)
       and not sc('банкетка', 'кресло') and not sc('стул', 'пуф'))
    cat.update({('1', 'p'): {'state': 'available', 'url': 'up', 'name': 'Босс пуф', 'cat_role': 'пуф'},
                ('1', 'k'): {'state': 'available', 'url': 'uk', 'name': 'Кресло', 'cat_role': 'кресло'}})
    boss = mk('s1', dict(core, **{'кресло': it('p'), 'кресло 2': it('k'), 'банкетка': it('p')}),
              alts={'кресло': [it('k'), it('p')]})
    r = check([boss], None, media, yes, pairs0, cells=1)
    ok('пуф в слоте «кресло» — не той роли каталога (и запасной тоже); кресло 2 и банкетка — чисты',
       r['role_mismatch'] == 1 and r['role_rows'][0][1] == 'кресло' and r['alt_why'] == {'не той роли каталога': 1}
       and not r['ok'])
    d = delta([mk('s1', core), mk('s2', {'диван': it('a')}, style='лофт')],
              [mk('s1', {'диван': it('b'), 'столик': it('b'), 'ковёр': it('c')}), mk('s3', {}, style='лофт')])
    ok('дельта: SKU сменился, роль появилась/пропала, новый сет — по стилю',
       d == {'сканди': {'SKU сменился': 1, 'без изменений': 1, 'роль появилась': 1, 'роль пропала': 1},
             'лофт': {'сет новый': 1}})
    print(f'bank_invariants selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
