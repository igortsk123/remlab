#!/usr/bin/env python3
"""СПРОС НА МЕШИ КОМНАТ ПО СЛОТАМ (room-pipeline-01 волна В, T-20261105-49) — какие товары отдать в генерацию, чтобы у каждого
стиля × роли × слота комнаты было ≥ K годных 3D-кандидатов. Только расчёт: БД и диск читаются, пишется один файл-снимок
в формате `room_mesh_jobs.py` (его подают в `mesh_wave_start.sh` ключом `MESH_QUEUE_FILE`) + отчёт. Генерацию запускает
другой шаг после слова ведущего; денег здесь нет.

ЯЧЕЙКА СПРОСА = (стиль, роль, слот). Слоты — из профиля комнаты (`rules/profiles/<комната>.json` → назначения состава),
только назначения, которые есть в банке; одинаковые слоты разных назначений (тумба, шкаф, комод) — одна ячейка, кровать — своя
на назначение (своя вилка спального места). Кандидат ячейки — ровно то, что взял бы сборщик набора: `compose_bedroom.gate`
(Ш×Г×В, полоса −20…+10 % идеала по сторонам `band`, у кровати — честный габарит и спальное место в вилке) и балл стиля
≥ `in_style_min`. Тир цены не делим: меш нужен модели, а не ценовой ступени.

КТО ПОКРЫВАЕТ ЯЧЕЙКУ. Товар с привязкой `ready` (`offer_asset_binding`, T-45) — покрыл; брак меша по названию (`mesh_defect`
правил) — не покрыл. Счёт — по семействам моделей (`fam`): три размера одной кровати — одна модель, не три кандидата.
Товар с привязкой `blocked` в генерацию НЕ идёт (меш есть, держит разворот/размер) — отдельной строкой «ждёт разблокировки».

КОГО ОТДАЁМ В МЕШ (сначала банк, потом добор):
  1. товары наборов банка в ролях с мешем, у которых привязки нет («сам товар набора»);
  2. добор до K: жадно — товар, закрывающий больше всего дефицитных ячеек (балл стиля, цена, SKU — ничья), одно семейство
     на ячейку. Вариант семьи мешей (`products.mesh_family_rep`) — через представителя, один раз.
Годен к генерации: фото текущей ревизии оценено и `ok` (`photo_assessment`, оценщик `preprocess.ASSESSOR_VERSION`:
вырезка годна, не коллаж — оценка скачала фото, значит, оно живое), меша нет ни у товара, ни у представителя семьи, все
условия `room_mesh_jobs.job_of`. Товар из `products` (шкафы, комоды спальни) — на тех же правах, если он кандидат слота
(T-20261105-49/2: привязка ключуется товаром без комнаты, меш в карточке гостиной ничего не ломает). Не оценённое фото — не в очередь,
а в отчёт («ждёт оценки фото»: досчитает вырезка, пересчитать).

ДЕНЬГИ. Цена модели — по замеру T-11 (проба 10 = 13,8 ₽ → 1,4 ₽; волна 45 = 48,5 ₽ → 1,1 ₽): считаем по верхней 1,4 ₽.
ОБЩИЙ ОСТАТОК (T-20261106-75, критика Codex к hall-demo-01: «бюджет не общий»): потолок владельца 1000 ₽ (до 12.11 — 500) — один на ВСЕ
комнаты и ВСЕ запуски, а не на каждый запуск. Каждый запуск считает остаток = потолок − факт волн комнат − удержание открытых − резерв
снимков, ещё не ушедших в волну (`ledger`). Факт денег по заданиям в БД не пишется (`mesh_generations` без цены), поэтому
источник — журнал ручных волн `salad/wave_cap.py` (`~/scout-scenes/wave-manual.json`: `spent_rub` закрытой волны — по книге
сторожа денег, открытая держит свой `rub_cap`); волна комнаты — снимок с `room` ≠ гостиной, нечитаемый снимок — считаем
(деньги важнее). Записанный снимок (`--out`) резервирует свою сумму в `~/scout-scenes/room-mesh-reserve.jsonl` под замком —
второй запуск подряд видит остаток за вычетом первого; резерв гаснет, когда снимок ушёл в волну (тот же отпечаток заданий —
дальше считается факт волны), или по `--release`. Учёт — с `BUDGET_SINCE` (начало трека комнат: деньги — в сторону осторожности); не влезло — хвост по
приоритету отрезается, в отчёте — что не влезло.

СПРОС ПО ВАРИАНТАМ ВИТРИНЫ (ADR-0314, `--want`): не весь каталог, а предметы показанных вариантов — пустые роли (файл
`rules/room-mesh-want.json`: из отчёта сторожа спальни), перегенерация брака ДРУГИМ фото и (за флагом `--hall-bank`) товары без
меша из банка `compose_hall`. По каждому — годно ли вырезанное фото (`photo_assessment` ok); нет — «ждёт вырезки» с причиной.

  ~/venvs/scout/bin/python room_mesh_demand.py --room bedroom --bank <sets-bedroom.next.json> (--out FILE | --dry) [--k 3]
        [--budget 1000] [--price 1.4] [--report-out DIR]                                  # спрос по слотам (весь каталог)
  ~/venvs/scout/bin/python room_mesh_demand.py --room bedroom --want rules/room-mesh-want.json (--out FILE | --dry) [--report-out DIR]
  ~/venvs/scout/bin/python room_mesh_demand.py --room hall --hall-bank <sets-hall.next.json> (--out FILE | --dry)
  ~/venvs/scout/bin/python room_mesh_demand.py --ledger            # остаток денег мешей комнат
  ~/venvs/scout/bin/python room_mesh_demand.py --release FILE      # снять резерв снимка, который не пойдёт в волну
  python3 room_mesh_demand.py --selftest      # правила на подставных данных, без базы
`--budget` — общий потолок (1000), не потолок запуска. Env: `BEDROOM_STYLE_SCORES` — как у `compose_bedroom.py` (в worktree —
путь основной копии); `MESH_WAVE_MANUAL`, `ROOM_MESH_RESERVE` — пути журнала волн и резерва (тесты).
"""
import datetime
import fcntl
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))
import room_profile as _RP  # noqa: E402

K_DEFAULT = 3
BUDGET_RUB = 1000.0         # ОБЩИЙ потолок владельца на меши всех комнат (план room-pipeline-01 § Деньги) — см. ledger;
#                             500 → 1000 ₽ 12.11 (владелец TG 1163; T-20261112-47/3: остаток 6,41 ₽ не давал волну спальни)
BUDGET_SINCE = '2026-11-05T00:00:00+00:00'   # учёт с начала трека комнат (onb-10 создан 05.11; волны T-11 13,8 + 48,5 ₽ — в счёт, решение ведущего T-75/1)
PRICE_RUB = 1.4             # верх замера T-11 (13,8 ₽ / 10); волна 45 моделей — 1,08 ₽
PRICE_LOW_RUB = 1.1
# РЕЕСТР ВОЗМОЖНОСТЕЙ КОМНАТЫ (room_profile.CAPABILITIES, T-72): у кого шаг «спрос мешей» — этот модуль. По вариантам витрины
# (`--want` / `--hall-bank`) — все они; по слотам (`demand`) — только комнаты со сборщиком compose_bedroom: `demand` читает его правила
WANT_ROOMS = _RP.rooms_with('mesh_demand', 'room_mesh_demand')
ROOMS = tuple(t for t in WANT_ROOMS if _RP.capability(t, 'bank') == 'compose_bedroom')
WAVES_FILE = os.environ.get('MESH_WAVE_MANUAL') or os.path.expanduser('~/scout-scenes/wave-manual.json')   # = salad/wave_cap.PATH
RESERVE_FILE = os.environ.get('ROOM_MESH_RESERVE') or os.path.expanduser('~/scout-scenes/room-mesh-reserve.jsonl')
LEASE_FILE = os.environ.get('ROOM_MESH_LEASE') or os.path.expanduser('~/scout-scenes/wave-lease.json')   # = salad/wave_guard.LEASE
WANT_FILE = os.path.join(HERE, 'rules', 'room-mesh-want.json')
LIVING = ('living', 'living_room', 'гостиная')
# ПРЕДУПРЕЖДЕНИЕ НА 80 % (владелец 12.11, TG 1167): факт + удержание открытых волн (как `ledger`, без резерва снимков) ≥ доли
# потолка → строка `WARN:room_mesh_budget:` (дайджест ночи, шаг `room_mesh_budget` в refresh_daily.sh) и тревога `alert.sh`
# не чаще раза в сутки (метка с датой UTC). 100 % — как раньше: снимок режется до остатка (`cut_budget`), волна не стартует.
WARN_SHARE = 0.8
WARN_STAMP = os.environ.get('ROOM_MESH_WARN_STAMP') or os.path.expanduser('~/scout-scenes/room-mesh-budget-warn.json')


class DemandError(Exception):
    pass


# ---------------------------------------------------------------- ячейки
def cells_of(purposes: dict, used: list, roles: list, styles: list) -> dict:
    """{cell_key: {style, role, slot, purposes[]}}. slot — {ideal, band, sleep_w?}; одинаковые слоты назначений — одна ячейка."""
    out: dict = {}
    for p in used:
        for s in (purposes.get(p) or {}).get('slots') or []:
            if s['role'] not in roles:
                continue
            sig = json.dumps({'ideal': s.get('ideal'), 'band': s.get('band'), 'sleep_w': s.get('sleep_w')}, sort_keys=True)
            for st in styles:
                k = (st, s['role'], sig)
                c = out.setdefault(k, {'style': st, 'role': s['role'], 'slot': s, 'purposes': []})
                if p not in c['purposes']:
                    c['purposes'].append(p)
    return out


def cell_name(c: dict) -> str:
    return f"{c['style']} × {c['role']} × {'/'.join(c['purposes'])}"


def fits(it: dict, c: dict, tol: tuple, thr: float, gate, band_of) -> bool:
    """Кандидат ячейки — как у сборщика: размеры по полосе слота и стиль ≥ порога."""
    if it['role'] != c['role']:
        return False
    if gate(it, c['slot'], band_of(c['slot'], tol)) is not None:
        return False
    return _RP.in_style(it.get('styles'), c['style'], thr)


# ---------------------------------------------------------------- состояние товара
def colour_own(bind: dict | None) -> bool:
    """Вариант семьи, отмеченный сторожем цвета (`mesh_color_mismatch`, T-20261107-14/2): меш представителя ему не годится
    по виду (оранжевый «Аронт» вместо серого) — он НЕ «готов» и не «ждёт разблокировки», а кандидат на СВОЙ меш, на общих правах."""
    import room_bindings as RB
    return bool(bind) and bool(bind.get('via_family')) and RB.colour_flagged(bind)


def own_facts(f: dict, bind: dict | None) -> dict:
    """Факты товара для спроса: у отмеченного сторожем цвета варианта семьи представителя нет (свой меш), иначе как есть."""
    return dict(f, rep=None, rep_has_mesh=False, colour_own=True) if colour_own(bind) else f


def state_of(sku: str, f: dict, bind: dict | None, defect: bool) -> str:
    """covered | blocked | defect | job | photo_pending | photo_bad | has_mesh | not_job.
    f — факты БД (has_mesh, rep_has_mesh, verdict). Товар из products — на общих правах (T-49/2). Вариант семьи с отметкой
    сторожа цвета — как товар без привязки и без представителя (`colour_own`)."""
    if colour_own(bind):
        bind, f = None, own_facts(f, bind)
    if bind is not None:
        if bind.get('status') == 'ready':
            return 'defect' if defect else 'covered'
        return 'blocked'
    if f.get('has_mesh') or f.get('rep_has_mesh'):
        return 'has_mesh'           # меш есть (свой или у представителя семьи), привязки нет — генерация не по этому правилу
    v = f.get('verdict')
    if v is None:
        return 'photo_pending'
    if v != 'ok':
        return 'photo_bad'
    return 'job'


def job_row(it: dict, f: dict) -> dict:
    """Строка для `room_mesh_jobs.job_of` из товара сборщика и фактов БД (фото оценено ok → скачивается)."""
    return {'shop_mid': int(it['mid']), 'external_id': str(it['eid']), 'role': it['role'], 'name': it.get('name') or '',
            'image_url': f.get('image_url') or it.get('img'), 'w_cm': it.get('w'), 'd_cm': it.get('d'), 'h_cm': it.get('h'),
            'footprint_ok': bool(f.get('footprint_ok')), 'shown': True, 'in_products': bool(f.get('in_products')),
            'has_mesh': bool(f.get('has_mesh')), 'rep': f.get('rep'), 'rep_has_mesh': bool(f.get('rep_has_mesh')),
            'slot_candidate': bool(it.get('slot_candidate')), 'photo_alive': True if f.get('verdict') == 'ok' else None}


# ---------------------------------------------------------------- выбор
def choose(cells: dict, items: list, states: dict, bank_skus: list, k: int, member) -> tuple:
    """→ (выбор [(sku, приоритет, [ячейки])], покрытие до {cell: n}, покрытие после {cell: n}).
    items — кандидаты с ключами sku/fam/role/styles/price; states — sku → состояние; member(it, cell) → bool.
    Покрытие — число разных семейств (fam) с готовым или выбранным мешем."""
    cells_of_item = [[ck for ck, c in cells.items() if member(it, c)] for it in items]   # индекс товара → его ячейки
    have = {ck: set() for ck in cells}
    for i, it in enumerate(items):
        if states[it['sku']] == 'covered':
            for ck in cells_of_item[i]:
                have[ck].add(it['fam'])
    before = {ck: len(v) for ck, v in have.items()}
    picked: list = []
    taken: set = set()                      # sku: товар двух ролей генерируется один раз

    def take(i, why):
        it = items[i]
        taken.add(it['sku'])
        cs = [ck for j, x in enumerate(items) if x['sku'] == it['sku'] for ck in cells_of_item[j]]
        for ck in cs:
            have[ck].add(it['fam'])
        picked.append((it['sku'], why, [cell_name(cells[ck]) for ck in cs]))

    first = {}
    for i, it in enumerate(items):
        first.setdefault(it['sku'], i)
    for s in bank_skus:                     # 1. сам товар набора
        if s in first and s not in taken and states[s] == 'job':
            take(first[s], 'bank')
    pool = [i for i, it in enumerate(items) if states[it['sku']] == 'job' and cells_of_item[i]]
    while True:                             # 2. добор до K — жадно по числу закрываемых дефицитных ячеек
        best, best_key = None, None
        for i in pool:
            it = items[i]
            if it['sku'] in taken:
                continue
            gain = [ck for ck in cells_of_item[i] if len(have[ck]) < k and it['fam'] not in have[ck]]
            if not gain:
                continue
            sc = max((it.get('styles') or {}).get(cells[ck]['style'], 0) for ck in gain)
            key = (-len(gain), -sc, it.get('price') or 0, it['sku'])
            if best_key is None or key < best_key:
                best, best_key = i, key
        if best is None:
            break
        take(best, 'topup')
    return picked, before, {ck: len(v) for ck, v in have.items()}


def cut_budget(picked: list, budget: float, price: float) -> tuple:
    """(в бюджет, не влезло) по порядку приоритета."""
    n = int(math.floor(budget / price + 1e-9)) if price > 0 else len(picked)
    return picked[:n], picked[n:]


# ---------------------------------------------------------------- чтение БД (только SELECT)
def facts(skus: list, fetch) -> dict:
    """sku → {in_products, rep, has_mesh, rep_has_mesh, verdict, image_url, footprint_ok}. Один SELECT."""
    import preprocess as PRE
    if not skus:
        return {}
    arr = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
    rows = fetch(f"""select s.sku, (p.external_id is not null), p.mesh_family_rep,
        exists(select 1 from mesh_generations g where g.sku = s.sku), a.verdict, pc.image_url,
        (select bool_or(coalesce(r.footprint_ok, false)) from room_catalog r where r.shop_mid || ':' || r.external_id = s.sku),
        (select coalesce(r.image_url_hd, r.image_url) from room_catalog r where r.shop_mid || ':' || r.external_id = s.sku
           order by r.room limit 1),
        exists(select 1 from mesh_generations g where g.sku = p.mesh_family_rep)
      from unnest(array[{arr}]::text[]) s(sku)
      left join products p on p.shop_mid || ':' || p.external_id = s.sku
      left join product_photo_current pc on pc.sku = s.sku
      left join photo_assessment a on a.source_sha = pc.source_sha and a.assessor_version = '{PRE.ASSESSOR_VERSION}'""")
    t = lambda v: v in (True, 't')  # noqa: E731
    return {r[0]: {'in_products': t(r[1]), 'rep': r[2] or None, 'has_mesh': t(r[3]), 'verdict': r[4] or None,
                   'image_url': r[7] or r[5], 'footprint_ok': t(r[6]), 'rep_has_mesh': t(r[8])} for r in rows}


def bank_items(bank: list, roles: list) -> list:
    """SKU товаров наборов (items, не альтернативы) в ролях с мешем — по порядку банка, без повторов."""
    out = []
    for s in bank:
        for role, it in (s.get('items') or {}).items():
            if role in roles and isinstance(it, dict) and it.get('mid') is not None:
                sku = f"{it['mid']}:{it['eid']}"
                if sku not in out:
                    out.append(sku)
    return out


# ---------------------------------------------------------------- расчёт комнаты
def demand(room: str, bank_path: str, k: int, budget: float, price: float) -> dict:
    if room not in ROOMS:
        raise DemandError(f'комната {room}: сборщика наборов и банка нет — спрос не считаю (есть: {", ".join(ROOMS)})')
    if not bank_path or not os.path.exists(bank_path):
        raise DemandError(f'банк {room} не найден: {bank_path!r} — без банка спрос не считаю')
    import asset_strategy as AS
    import catalog_items as CI
    import compose_bedroom as CB
    import re
    import room_bindings as RB
    import room_mesh_jobs as RMJ
    R = CB.rules()
    tol, thr = CB.tolerance(), float(CB.PROFILE['style']['in_style_min'])
    roles = [r for r in CB.MAJOR if AS.strategy(r) == 'hunyuan3d']
    bank = json.load(open(bank_path, encoding='utf-8'))
    used = sorted({s.get('purpose') for s in bank if s.get('purpose')})
    cells = cells_of(R['purposes'], used, roles, list(R['styles']))
    cat, _ = CB.load_items(R)
    rows, why = RB.load_db(CI.fetch)
    if rows is None:
        raise DemandError(f'привязка не читается ({why}) — без неё не знаю, у кого меш уже есть')
    md = (R.get('mesh_defect') or {}).get('names')
    defect_re = re.compile(md, re.I) if md else None
    items_all = [dict(it, sku=f"{it['mid']}:{it['eid']}") for it in cat if it['role'] in roles]
    F = facts(sorted({it['sku'] for it in items_all}), CI.fetch)
    # Вариант семьи мешей (products.mesh_family_rep) → представитель: один меш на семью. Кандидатство слота — по варианту
    # (его размеры в полосе), задание — по собственной карточке представителя (его размеры и фото: паспорт меша — его).
    member = lambda it, c: fits(it, c, tol, thr, CB.gate, CB.band_of)  # noqa: E731
    own = {}
    for it in items_all:
        own.setdefault((it['sku'], it['role']), it)
    states, items, seen = {}, [], set()
    for it in items_all:
        f = F.get(it['sku'], {})
        rep = f.get('rep')
        if rep and rep != it['sku'] and it['sku'] not in rows:
            it = dict(it, sku=rep, via=it['sku'])
            f = F.get(rep) or facts([rep], CI.fetch).get(rep, {})
            F[rep] = f
        elif colour_own(rows.get(it['sku'])):      # отметка сторожа цвета — свой меш варианту (задание по его фото)
            f = F[it['sku']] = own_facts(f, rows.get(it['sku']))
        key = (it['sku'], it['role'], it.get('via'))
        if key in seen:
            continue
        seen.add(key)
        it['from_products'] = bool(f.get('in_products'))
        if it['sku'] not in states:
            states[it['sku']] = state_of(it['sku'], f, rows.get(it['sku']),
                                         bool(defect_re and defect_re.search(it.get('name') or '')))
        items.append(it)
    cand = {it['sku'] for it in items if any(member(it, c) for c in cells.values())}
    # годность к заданию — правилом room_mesh_jobs (одно место); отказ → состояние not_job
    jobs_of = {}
    for it in items:
        if states[it['sku']] == 'job' and it['sku'] not in jobs_of:
            base = own.get((it['sku'], it['role']))
            if base is None:
                states[it['sku']] = 'not_job'
                it['not_job'] = 'представителя семьи нет в каталоге комнаты в этой роли'
                continue
            j, w = RMJ.job_of(job_row(dict(base, slot_candidate=it['sku'] in cand), F[it['sku']]), room)
            if j is None:
                states[it['sku']] = 'not_job'
                it['not_job'] = w
            else:
                jobs_of[it['sku']] = j
    bank_skus = bank_items(bank, roles)
    picked, before, after = choose(cells, items, states, bank_skus, k, member)
    fit_b, over = cut_budget(picked, budget, price)
    fam_of = {it['sku']: it['fam'] for it in items}
    # после бюджета — покрытие по тому, что влезло
    in_budget = {s for s, _, _ in fit_b}
    have_final = {}
    for ck, c in cells.items():
        fams = {it['fam'] for it in items if member(it, c)
                and (states[it['sku']] == 'covered' or it['sku'] in in_budget)}
        have_final[ck] = len(fams)
    jobs = []
    for s, pr, cs in fit_b:
        j = dict(jobs_of[s])
        j['strata'] = {'tier': 'room', 'reason': f"комната {room}: спрос по слотам ({'набор банка' if pr == 'bank' else 'добор до K'}; "
                                                f"{len(cs)} яч.) T-20261105-49", 'priority': pr, 'cells': cs}
        jobs.append(j)
    return {'room': room, 'bank': bank_path, 'purposes': used, 'k': k, 'budget_rub': budget, 'price_rub': price,
            'roles': roles, 'cells': cells, 'items': items, 'states': states, 'member': member,
            'bank_skus': bank_skus, 'picked': picked, 'in_budget': fit_b, 'over_budget': over, 'before': before,
            'after': after, 'final': have_final, 'jobs': jobs, 'fam_of': fam_of,
            'snapshot': next(iter({r['snapshot_id'][:16] for r in rows.values()}), None)}


# ---------------------------------------------------------------- общий остаток денег (T-20261106-75)
def _ts(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso).timestamp()


def fingerprint(jobs: list) -> str:
    """Отпечаток снимка по заданиям (sku + seeds): `mesh_wave_start.sh` копирует снимок дословно — у волны тот же."""
    keys = sorted(f"{j.get('sku')}#{','.join(str(s) for s in j.get('seeds') or [])}" for j in jobs)
    return hashlib.sha1('\n'.join(keys).encode()).hexdigest()[:16]


def snap_info(path: str) -> dict | None:
    """Снимок волны → {room, fp, n}; нет файла / битый — None."""
    try:
        s = json.load(open(path, encoding='utf-8'))
        return {'room': s.get('room'), 'source': s.get('source') or '', 'fp': fingerprint(s.get('jobs') or []),
                'n': len(s.get('jobs') or [])}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _read_waves(path: str) -> list:
    try:
        d = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        return []
    except ValueError as e:
        raise DemandError(f'журнал волн {path} битый ({e}) — без него остаток не знаю, снимок не пишу')
    return list((d or {}).get('waves') or [])


def _read_reserve(path: str) -> list:
    out = []
    try:
        for ln in open(path, encoding='utf-8'):
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    except FileNotFoundError:
        pass
    return out


def _read_lease(path: str) -> list:
    try:
        d = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        return []
    except ValueError as e:
        raise DemandError(f'разрешение {path} битое ({e}) — без него остаток не знаю')
    return list((d or {}).get('waves') or [])


def _usd_rub() -> float:
    import salad_groups as SG
    return float(SG.usd_rub())


def ledger(total: float = BUDGET_RUB, since: str = BUDGET_SINCE, waves_path: str = WAVES_FILE,
           reserve_path: str = RESERVE_FILE, load=snap_info, lease_path: str | None = None, usd_rub=None) -> dict:
    """Остаток денег мешей комнат = total − факт закрытых волн комнат − потолок открытых − резерв снимков вне волны.
    Волны гостиной (снимок без `room` или `room` гостиной) не в счёт; нечитаемый снимок — в счёт (деньги важнее).
    ВОЛНЫ АВТОЗАПУСКА (`wave_guard`, разрешение `wave-lease.json`; T-20261106-82/2): с комнатами в профиле demo волна
    смешанная (гостиная + комнаты), снимок у неё общий — поэтому ВСЕ волны разрешения с начала учёта идут в счёт трека
    комнат целиком (в сторону осторожности: доля гостиной — единицы мешей): закрытая — `spent_usd` × курс, открытая —
    потолок `usd_cap` × курс. Отпечаток снимка волны (если записан) гасит резерв, как у ручной волны."""
    t0 = _ts(since)
    rows, spent, held, reserved, fps = [], 0.0, 0.0, 0.0, set()
    lw = [w for w in _read_lease(LEASE_FILE if lease_path is None else lease_path) if float(w.get('started') or 0) >= t0]
    if lw:
        rate = float(usd_rub if usd_rub is not None else _usd_rub())
        for w in lw:
            if w.get('snapshot'):
                info = load(w['snapshot'])
                if info:
                    fps.add(info['fp'])
            if w.get('closed'):
                rub, kind = float(w.get('spent_usd') or 0) * rate, 'факт автоволны (разрешение)'
                spent += rub
            else:
                rub, kind = float(w.get('usd_cap') or 0) * rate, 'открытая автоволна — держим потолок'
                held += rub
            rows.append({'kind': kind, 'room': 'общая', 'rub': round(rub, 2), 'snapshot': w.get('snapshot'),
                         'at': w.get('at')})
    for w in _read_waves(waves_path):
        info = load(w.get('snapshot') or '')
        room = (info or {}).get('room')
        if info is not None and (room is None or room in LIVING):
            continue                                    # гостиная — свой бюджет
        if float(w.get('started') or 0) < t0:
            rows.append({'kind': 'до начала учёта', 'room': room or '?', 'rub': float(w.get('spent_rub') or 0),
                         'snapshot': w.get('snapshot'), 'at': w.get('at')})
            continue
        if info:
            fps.add(info['fp'])
        if w.get('closed'):
            rub, kind = float(w.get('spent_rub') or 0), 'факт волны'
            spent += rub
        else:
            rub, kind = float(w.get('rub_cap') or 0), 'открытая волна — держим потолок'
            held += rub
        rows.append({'kind': kind if info else kind + ' (снимок не читается — считаем)', 'room': room or '?', 'rub': rub,
                     'snapshot': w.get('snapshot'), 'at': w.get('at')})
    R = _read_reserve(reserve_path)
    released = {e['release'] for e in R if e.get('release')}
    for e in R:
        if e.get('release') or float(e.get('at') or 0) < t0:
            continue
        if e.get('snapshot') in released or e.get('fp') in fps:
            continue                                    # снят или ушёл в волну (дальше — факт волны)
        reserved += float(e.get('rub') or 0)
        rows.append({'kind': 'резерв снимка (ещё не в волне)', 'room': e.get('room'), 'rub': float(e.get('rub') or 0),
                     'snapshot': e.get('snapshot'), 'at': e.get('at')})
    left = max(0.0, total - spent - held - reserved)
    return {'total': total, 'since': since, 'spent': round(spent, 2), 'held': round(held, 2), 'reserved': round(reserved, 2),
            'left': round(left, 2), 'rows': rows}


def ledger_text(L: dict) -> str:
    s = (f"Деньги мешей комнат (общий потолок {L['total']:g} ₽ с {L['since'][:16]}): факт волн {L['spent']:g} ₽, "
         f"открытые {L['held']:g} ₽, резерв снимков {L['reserved']:g} ₽ → остаток **{L['left']:g} ₽**.")
    pre = [r for r in L['rows'] if r['kind'] == 'до начала учёта']
    if pre:
        s += f" До начала учёта (не в счёт): {len(pre)} волн, {sum(r['rub'] for r in pre):g} ₽."
    return s


def _alert_sh(text: str) -> int:
    import subprocess
    return subprocess.run(['bash', os.path.join(HERE, 'alert.sh'), text], check=False).returncode


def budget_warn(L: dict, stamp_path: str | None = None, alert=None, today: str | None = None) -> str | None:
    """Потрачено + удержано (`ledger`: spent + held) ≥ WARN_SHARE потолка → печатает строку WARN (её берёт дайджест) и, если
    сегодня (UTC) тревоги ещё не было, шлёт `alert.sh` и пишет метку {date, used, total, rc}. Код alert.sh ≠ 0 (TG не ответил
    или не настроен) — второй строкой WARN, метку всё равно пишем: «не чаще раза в сутки» важнее повторов. → строка WARN или None."""
    used, total = round(L['spent'] + L['held'], 2), float(L['total'])
    if total <= 0 or used < WARN_SHARE * total:
        return None
    pct = round(100 * used / total)
    line = (f"WARN:room_mesh_budget: меши комнат — потрачено и удержано {used:g} из {total:g} ₽ ({pct} %), остаток "
            f"{L['left']:g} ₽; на 100 % снимки режутся до остатка и волны встают")
    print(line, flush=True)
    stamp_path = stamp_path or WARN_STAMP
    day = today or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    try:
        last = json.load(open(stamp_path, encoding='utf-8')).get('date')
    except FileNotFoundError:
        last = None
    except ValueError as e:                             # битая метка — тревогу шлём (громче лучше тишины), метку перепишем
        print(f'WARN:room_mesh_budget_stamp: метка {stamp_path} битая ({e}) — пишу заново', flush=True)
        last = None
    if last == day:
        return line
    rc = (alert or _alert_sh)(f"remlab: деньги мешей комнат — {pct} % потолка ({used:g} из {total:g} ₽), остаток {L['left']:g} ₽. "
                              f"На 100 % волны комнат встанут: поднять потолок или ждать.")
    if rc != 0:
        print(f'WARN:room_mesh_budget_alert: alert.sh вернул {rc} (1 — TG не ответил, 2 — не настроен)', flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(stamp_path)), exist_ok=True)
    tmp = stamp_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'date': day, 'used': used, 'total': total, 'pct': pct, 'rc': rc}, f, ensure_ascii=False)
    os.replace(tmp, stamp_path)
    return line


def commit_snapshot(jobs: list, out: str, room: str, price: float, meta: dict, total: float = BUDGET_RUB,
                    since: str = BUDGET_SINCE, waves_path: str = WAVES_FILE, reserve_path: str = RESERVE_FILE,
                    now: float | None = None) -> tuple:
    """Под замком: пересчитать остаток → отрезать хвост, что не влезает → записать снимок → резерв его суммы.
    Замок — чтобы два запуска одновременно не увидели один и тот же остаток. → (в снимке, не влезло, остаток до)."""
    os.makedirs(os.path.dirname(os.path.abspath(reserve_path)), exist_ok=True)
    with open(reserve_path + '.lock', 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        L = ledger(total, since, waves_path, reserve_path)
        fit, over = cut_budget(jobs, L['left'], price)
        snap = dict(meta, room=room, policy_version=2, rework=[], jobs=fit,
                    built_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
        snap.setdefault('demand', {})
        snap['demand'] = dict(snap['demand'], budget_total_rub=total, budget_left_rub=L['left'], price_rub=price,
                              over_budget=[j['sku'] for j in over])
        tmp = out + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)
        if fit:
            with open(reserve_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'at': now or __import__('time').time(), 'snapshot': os.path.abspath(out),
                                    'fp': fingerprint(fit), 'room': room, 'n': len(fit),
                                    'rub': round(len(fit) * price, 2)}, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
    return fit, over, L


def release(snapshot: str, reserve_path: str = RESERVE_FILE) -> None:
    """Снять резерв снимка, который не пойдёт в волну (журнал только дописывается)."""
    with open(reserve_path + '.lock', 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        with open(reserve_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': __import__('time').time(), 'release': os.path.abspath(snapshot)}) + '\n')


# ---------------------------------------------------------------- спрос по вариантам витрины (T-20261106-75)
WANT_ORDER = {'empty': 0, 'regen': 1, 'hall': 2}     # приоритет под потолок: пустая роль показанного варианта → брак → прихожая
WANT_RU = {'job': 'годно — в очередь', 'regen_job': 'перегенерация: у товара новое фото',
           'regen_sibling': 'перегенерация: фото варианта семьи (меш на вариант)', 'wait_cut': 'ждёт вырезки',
           'photo_bad': 'фото негодно', 'no_alt': 'другого годного фото нет', 'has_mesh': 'меш уже есть — не генерация',
           'not_job': 'не годен к заданию', 'not_in_room': 'нет в каталоге комнаты'}


def hall_want(bank: list, strategy, styles=None) -> list:
    """Банк `compose_hall` → товары без меша (`mesh_need`) в ролях с мешем (зеркало — плоскость, не меш), с вариантами.
    styles — стили состава прихожей (`compose_hall.rules()['styles']`): набор снятого стиля (неоклассика, T-20261107-18) из
    старого банка в спрос не идёт. None — все наборы."""
    out: dict = {}
    for s in bank:
        if styles and s.get('style') not in styles:
            continue
        role_of = {f"{it['mid']}:{it['eid']}": r for r, it in (s.get('items') or {}).items() if isinstance(it, dict)}
        for sku in s.get('mesh_need') or []:
            r = role_of.get(sku)
            if not r or strategy(r) != 'hunyuan3d':
                continue
            e = out.setdefault(sku, {'room': 'hall', 'sku': sku, 'role': r, 'why': 'hall', 'variants': []})
            v = f"{s.get('style')} {s.get('tier')}"
            if v not in e['variants']:
                e['variants'].append(v)
    return list(out.values())


def merge_want(entries: list) -> list:
    """(комната, sku) — одна строка: перегенерация сильнее «пустой роли», варианты объединяются; порядок — приоритет."""
    out: dict = {}
    for e in entries:
        k = (e['room'], e['sku'])
        if k in out:
            o = out[k]
            rank = {'regen': 0, 'empty': 1, 'hall': 2}
            if rank[e['why']] < rank[o['why']]:
                o['why'] = e['why']
            o['variants'] = o.get('variants', []) + [v for v in e.get('variants') or [] if v not in o.get('variants', [])]
            o['note'] = '; '.join(x for x in (o.get('note'), e.get('note')) if x)
            o['shown'] = o.get('shown', []) + [x for x in e.get('shown') or [] if x not in o.get('shown', [])]
        else:
            out[k] = dict(e, variants=list(e.get('variants') or []))
    return sorted(out.values(), key=lambda e: (WANT_ORDER[e['why']], -len(e['variants']), e['sku']))


def want_rows(skus: list, room: str, fetch, missing_after: int = 1, assessor: str | None = None) -> dict:
    """sku → факты для решения: карточка комнаты, фото текущей ревизии и его вердикт, фото уже сделанных мешей. SELECT.
    assessor — версия оценщика вырезки; по умолчанию `preprocess.ASSESSOR_VERSION` (импорт тянет torch — селфтест передаёт
    свою строку, в CI scout-orient torch нет)."""
    if not skus:
        return {}
    if assessor is None:
        import preprocess as PRE
        assessor = PRE.ASSESSOR_VERSION
    arr = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
    rows = fetch(f"""select s.sku, r.role, r.name, r.w_cm, r.d_cm, r.h_cm, coalesce(r.footprint_ok, false),
        (r.price_rub is not null and coalesce(r.image_url_hd, r.image_url) is not null and r.missing_runs < {int(missing_after)}),
        (p.external_id is not null), p.mesh_family_rep, pc.source_sha, coalesce(pc.image_url, r.image_url_hd, r.image_url),
        a.verdict, (select string_agg(distinct g.source_sha, ',') from mesh_generations g where g.sku = s.sku),
        (select max(g.seed) from mesh_generations g where g.sku = s.sku), r.external_id is not null, '.'
      from unnest(array[{arr}]::text[]) s(sku)
      left join room_catalog r on r.room = '{room}' and r.shop_mid || ':' || r.external_id = s.sku
      left join products p on p.shop_mid || ':' || p.external_id = s.sku
      left join product_photo_current pc on pc.sku = s.sku
      left join photo_assessment a on a.source_sha = pc.source_sha and a.assessor_version = '{assessor}'""")
    t = lambda v: v in (True, 't')  # noqa: E731
    f = lambda v: float(v) if v not in (None, '') else None  # noqa: E731
    out = {}
    for r in rows:
        if len(r) != 17 or r[16] != '.':
            raise DemandError(f'want_rows: строка не той ширины ({len(r)}): {r[:2]}')
        out[r[0]] = {'sku': r[0], 'role': r[1], 'name': r[2] or '', 'w': f(r[3]), 'd': f(r[4]), 'h': f(r[5]),
                     'footprint_ok': t(r[6]), 'shown': t(r[7]), 'in_products': t(r[8]), 'rep': r[9] or None,
                     'sha': r[10] or None, 'image_url': r[11], 'verdict': r[12] or None,
                     'used': sorted((r[13] or '').split(',')) if r[13] else [], 'max_seed': int(r[14]) if r[14] else None,
                     'in_room': t(r[15])}
    return out


def siblings_of(reps: list, fetch) -> dict:
    """Представитель семьи мешей → варианты семьи (другие цвета той же модели) из `products`."""
    if not reps:
        return {}
    arr = ','.join("'" + s.replace("'", "''") + "'" for s in reps)
    out: dict = {}
    for rep, sku in fetch(f"""select p.mesh_family_rep, p.shop_mid || ':' || p.external_id from products p
            where p.mesh_family_rep in ({arr}) and p.shop_mid || ':' || p.external_id <> p.mesh_family_rep order by 2"""):
        out.setdefault(rep, []).append(sku)
    return out


def _job(F: dict, room: str, seeds: list, job_of) -> tuple:
    """Задание по карточке — правилом `room_mesh_jobs.job_of` (одно место); фото — та ревизия, что оценена."""
    mid, eid = F['sku'].split(':', 1)
    row = {'shop_mid': int(mid), 'external_id': eid, 'role': F['role'], 'name': F['name'], 'image_url': F['image_url'],
           'w_cm': F['w'], 'd_cm': F['d'], 'h_cm': F['h'], 'footprint_ok': F['footprint_ok'], 'shown': F['shown'],
           'in_products': F['in_products'], 'has_mesh': False, 'rep': None, 'rep_has_mesh': False, 'slot_candidate': True,
           'photo_alive': True}
    j, w = job_of(row, room)
    if j is not None:
        j['seeds'] = seeds
    return j, w


def evaluate(e: dict, F: dict, sibs: list, room: str, job_of, own: bool = False) -> dict:
    """Строка спроса → {state, reason, job?, photo}. F — want_rows по sku и его вариантам семьи; sibs — варианты семьи.
    own — вариант семьи, отмеченный сторожем цвета (`colour_own`, как в `state_of`): меш представителя ему не годится, он
    кандидат на СВОЙ меш — «меш у семьи есть» и «меш делается представителю» к нему не относятся (T-20261112-47/3)."""
    me = F.get(e['sku'])
    if own and me:
        me = dict(me, rep=None)
    res = {'state': None, 'reason': '', 'job': None, 'photo': None, 'job_sku': None}
    if not me or not me['in_room']:
        return dict(res, state='not_in_room', reason=f'нет в room_catalog ({room})')
    res['photo'] = (me['sha'] or '')[:10] or None
    k16 = lambda v: (v or '')[:16]  # noqa: E731 — mesh_generations.source_sha хранит 16 знаков, product_photo_current — полный
    used = {k16(v) for v in me['used']}         # фото уже сделанных мешей товара и его семьи
    for s in sibs:
        used |= {k16(v) for v in (F.get(s) or {}).get('used') or []}
    pre = ''
    if e['why'] == 'regen' and not used:
        pre = 'в списке брака, но меша у семьи нет — первая генерация; '
    if e['why'] != 'regen' or not used:
        if me['used']:
            return dict(res, state='has_mesh', reason='меш уже есть — пусто не из-за меша (привязка/индекс), генерация не поможет')
        if me['rep'] and me['rep'] != me['sku']:
            return dict(res, state='not_job', reason=f'вариант семьи — меш делается представителю {me["rep"]}')
        if me['verdict'] is None:
            return dict(res, state='wait_cut', reason=pre + 'фото не оценено — ждёт вырезки' + ('' if me['sha'] else ' (нет хеша фото)'))
        if me['verdict'] != 'ok':
            return dict(res, state='photo_bad', reason=pre + f'вырезка: {me["verdict"]}')
        j, w = _job(me, room, [0], job_of)
        return dict(res, state='job' if j else 'not_job', reason=pre + (w or 'фото ok'), job=j, job_sku=j and j['sku'])
    # перегенерация брака ДРУГИМ фото: фото меша не повторяем (ни своё, ни уже взятое у семьи)
    if me['sha'] and k16(me['sha']) not in used:
        if me['verdict'] == 'ok':
            j, w = _job(me, room, [(me['max_seed'] or 0) + 1], job_of)
            if j:
                return dict(res, state='regen_job', reason='фото товара сменилось после меша, вырезка ok', job=j, job_sku=j['sku'])
        elif me['verdict'] is None:
            return dict(res, state='wait_cut', reason='у товара новое фото — ждёт вырезки')
    waiting = []
    shown = [s for s in e.get('shown') or [] if s in sibs]      # цвет, который стоит в показанном варианте, — первым
    for s in shown + [s for s in sibs if s not in shown]:
        x = F.get(s)
        if not x or not x['in_room'] or not x['sha'] or k16(x['sha']) in used or x['used']:
            continue
        if x['verdict'] is None:
            if s in shown:      # пустую роль показанного варианта закрывает его цвет — ждём его вырезку, не берём чужой
                return dict(res, state='wait_cut', reason=f'фото показанного варианта «{x["name"]}» ждёт вырезки')
            waiting.append(x['name'])
            continue
        if x['verdict'] != 'ok':
            continue
        j, w = _job(x, room, [0], job_of)
        if j:
            return dict(res, state='regen_sibling', reason=f'фото варианта «{x["name"]}», вырезка ok', job=j, job_sku=j['sku'],
                        photo=x['sha'][:10])
    if waiting:
        return dict(res, state='wait_cut', reason=f'другое фото — у варианта семьи «{waiting[0]}», ждёт вырезки'
                    + (f' (+{len(waiting) - 1})' if len(waiting) > 1 else ''))
    return dict(res, state='no_alt', reason='другого годного фото нет: в фиде у товара одно фото (оно дало брак), у вариантов '
                                            'семьи — нет в каталоге комнаты, негодно или уже с мешем')


def want_demand(room: str, entries: list, price: float, fetch=None, binds: dict | None = None,
                assessor: str | None = None) -> dict:
    """Спрос по вариантам витрины: строки → решения → задания по приоритету (без потолка — его режет commit/dry).
    binds — привязка {sku: строка} (`room_bindings.load_db`); по ней вариант, отмеченный сторожем цвета, остаётся СОБОЙ
    (`colour_own`, как в спросе по слотам), а не уходит к представителю с мешем другого цвета. assessor — в `want_rows`
    (None — боевая версия оценщика из `preprocess`)."""
    import room_catalog as RC
    import room_mesh_jobs as RMJ
    fetch = fetch or __import__('catalog_items').fetch
    if room not in WANT_ROOMS:
        raise DemandError(f'комната {room}: шага «спрос мешей» в реестре нет (есть: {", ".join(WANT_ROOMS)})')
    mh = int(RC.rules().get('missing_hide_after', 1))
    E0 = [e for e in entries if e['room'] == room]
    if not E0:
        raise DemandError(f'спрос по вариантам: для комнаты {room} строк нет')
    if binds is None:
        import room_bindings as RB
        binds, why = RB.load_db(fetch)
        if binds is None:
            raise DemandError(f'привязка не читается ({why}) — без неё не знаю, чей меш не годится по цвету')
    own = {e['sku'] for e in E0 if colour_own(binds.get(e['sku']))}
    # вариант семьи мешей (другой цвет) → представитель: меш один на семью (как в спросе по слотам); отмеченный сторожем
    # цвета — нет: ему нужен свой меш
    r0 = want_rows(sorted({e['sku'] for e in E0}), room, fetch, mh, assessor)
    E1 = []
    for e in E0:
        rep = (r0.get(e['sku']) or {}).get('rep')
        if rep and rep != e['sku'] and e['sku'] not in own:
            e = dict(e, sku=rep, shown=list(e.get('shown') or []) + [e['sku']],
                     note='; '.join(x for x in (e.get('note'), f"показан вариант {e['sku']} → представитель") if x))
        E1.append(e)
    E = merge_want(E1)
    regen = [e['sku'] for e in E if e['why'] == 'regen']
    base = want_rows([e['sku'] for e in E], room, fetch, mh, assessor)
    reps = sorted({(base.get(s) or {}).get('rep') or s for s in regen})
    S = siblings_of(reps, fetch)
    sib_all = sorted({x for v in S.values() for x in v} | set(reps))
    F = dict(base, **{k: v for k, v in want_rows(sib_all, room, fetch, mh, assessor).items() if k not in base})
    out, jobs, taken = [], [], set()
    for e in E:
        rep = (F.get(e['sku']) or {}).get('rep') or e['sku']
        sibs = [x for x in S.get(rep, []) + ([rep] if rep != e['sku'] else []) if x != e['sku']]
        r = evaluate(e, F, sibs, room, RMJ.job_of, own=e['sku'] in own)
        if r['job'] and r['job_sku'] in taken:
            r = dict(r, state='not_job', reason=f'задание на {r["job_sku"]} уже есть в этом снимке', job=None)
        if r['job']:
            taken.add(r['job_sku'])
            r['job']['strata'] = {'tier': 'room', 'reason': f"комната {room}: спрос по вариантам витрины ({e['why']}) T-20261106-75",
                                  'priority': e['why'], 'variants': e['variants']}
            jobs.append(r['job'])
        out.append(dict(e, name=(F.get(e['sku']) or {}).get('name', ''), **r))
    return {'room': room, 'rows': out, 'jobs': jobs, 'price_rub': price}


def want_md(W: dict, fit: list, L: dict, dry: bool) -> str:
    fs = {j['sku'] for j in fit}
    st: dict = {}
    for r in W['rows']:
        st[r['state']] = st.get(r['state'], 0) + 1
    n = len(fit)
    L_ = [f"# Спрос на меши по вариантам витрины: {W['room']}{' (сухой расчёт)' if dry else ''}", '', ledger_text(L), '',
          f"Предметов: {len(W['rows'])}; заданий: **{len(W['jobs'])}**, в остаток влезло {n} ≈ {n * PRICE_LOW_RUB:.1f}–"
          f"{n * W['price_rub']:.1f} ₽ (по {W['price_rub']:g} ₽ за модель); ждёт вырезки: {st.get('wait_cut', 0)}.", '',
          '| зачем | роль | sku | товар | вариантов | решение | причина | задание | в остатке |', '|---|---|---|---|---|---|---|---|---|']
    for r in W['rows']:
        L_.append(f"| {r['why']} | {r['role']} | {r['sku']} | {r['name'][:42]} | {len(r['variants'])} | {WANT_RU[r['state']]} | "
                  f"{r['reason']} | {r['job_sku'] or '—'} | {'да' if r['job_sku'] in fs else '—'} |")
    return '\n'.join(L_) + '\n'


# ---------------------------------------------------------------- отчёт
STATE_RU = {'covered': 'меш готов (ready)', 'blocked': 'меш есть, ждёт разблокировки (blocked)', 'defect': 'брак меша',
            'job': 'годен в генерацию', 'photo_pending': 'фото не оценено (ждёт вырезки)', 'photo_bad': 'фото негодно (коллаж/мелко/брак)',
            'has_mesh': 'меш есть (свой или у представителя), привязки нет',
            'not_job': 'не годен к заданию (room_mesh_jobs)'}


# ---------------------------------------------------------------- квота мешей комнаты (T-20261106-82/2)
# ВЛАДЕЛЕЦ 06.11 (TG 215/218): «в каждом стиле в каждой комнате 30 товаров с мешами… только влезающие (−20…+10 % к месту на
# плане); меш один на все расстановки; меши — конвейером». Место квоты = (комната × стиль); доли ролей — `rules/demo-swap.json →
# rooms.<комната>.roles` (ведущий 06.11: спальня 10/7/8/5, прихожая 8/3/4/6/5/4). Кандидат — тот же отбор, что у сборщика
# комнаты (`compose_*.gate` по полосе слота записи банка, у кровати — спальное место; балл стиля ≥ `in_style_min`), фото
# текущей ревизии оценено ok, задание проходит `room_mesh_jobs.job_of`. «Есть» — привязка `ready` (`offer_asset_binding`).
# Добор — сперва товары наборов и альтернатив банка («в ленте»), потом по баллу стиля; один SKU засчитывается всем местам,
# где он кандидат. Считает это `demo_band` (общий профиль очереди demo) — ручных снимков ночью нет.

def quota_slots(bank: list, purposes: dict, band_of, tol: tuple, mesh_role, sizes_of=None) -> dict:
    """{room_id: {роль: [слот{role, band, sleep_w?, need_dims?}]}} — все различные полосы комнаты из записей банка (ниши шкафа
    bedroom-2 — свои), плюс роли профиля, которых нет в записи (у прихожей — модуль «прихожая», хранение второго выбора).
    `mesh_role(role)` — роль строится мешем. `sizes_of(слот)` — типоразмеры слота (`compose_common.slot_sizes`)."""
    if sizes_of is None:
        from compose_common import slot_sizes as sizes_of
    out: dict = {}
    for s in bank:
        prof = {x['role']: x for x in (purposes.get(s.get('purpose')) or {}).get('slots') or []}
        rid = s.get('room_id')
        for role, sl in (s.get('slots') or {}).items():
            if not sl.get('mesh') or not mesh_role(role):
                continue
            slot = {'role': role, 'band': {k: list(v) for k, v in (sl.get('band') or {}).items()}}
            for k in ('sleep_w', 'need_dims'):
                if (prof.get(role) or {}).get(k):
                    slot[k] = prof[role][k]
            lst = out.setdefault(rid, {}).setdefault(role, [])
            if slot not in lst:
                lst.append(slot)
        for role, p in prof.items():
            # роль не в записи — полосы всех её типоразмеров; в записи — добавочно только типоразмеры правил (`sizes`, T-90):
            # каждый проверен солвером flat215, «место на плане» — любой из них (у спальни `sizes` нет — как было)
            if not mesh_role(role) or (role in (s.get('slots') or {}) and not p.get('sizes')):
                continue
            for sz in sizes_of(p):
                slot = {'role': role, 'band': band_of(sz, tol) if sz.get('band') else {}}
                for k in ('sleep_w', 'need_dims'):
                    if p.get(k):
                        slot[k] = p[k]
                lst = out.setdefault(rid, {}).setdefault(role, [])
                if slot not in lst:
                    lst.append(slot)
    return out


def bank_shown(bank: list) -> set:
    """SKU наборов и альтернатив банка — «в ленте» (приоритет добора)."""
    got = set()
    for s in bank:
        for it in (s.get('items') or {}).values():
            if isinstance(it, dict) and it.get('mid') is not None:
                got.add(f"{it['mid']}:{it['eid']}")
        for alts in (s.get('alternates') or {}).values():
            for x in alts or []:
                if isinstance(x, dict) and x.get('mid') is not None:
                    got.add(f"{x['mid']}:{x['eid']}")
    return got


COUNT_UNITS = ('sku', 'family')
UNIT_RU = {'sku': 'товары (SKU, цвета отдельно)', 'family': 'модели (семейства)'}


def room_count_unit(room: str, rules: dict | None = None) -> str:
    """Единица счёта квоты комнаты из правил: `rules/demo-swap.json → rooms.<комната>.count_unit`, иначе общее
    `room_count_unit`, иначе sku (решение владельца 06.11). Чужое значение — отказ, а не тихий счёт по умолчанию."""
    R = rules if rules is not None else json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))
    u = ((R.get('rooms') or {}).get(room) or {}).get('count_unit') or R.get('room_count_unit') or 'sku'
    if u not in COUNT_UNITS:
        raise DemandError(f'rules/demo-swap.json: единица счёта {room} {u!r} — только {"|".join(COUNT_UNITS)}')
    return u


def unit_of(it: dict, unit: str) -> str:
    """Единица счёта квоты (T-20261106-90, владелец 06.11: «пока считай цвета одной модели отдельными товарами»):
    sku — сам товар каталога (вариант, заменённый представителем семьи мешей, считается своим артикулом `via`);
    family — модель (`fam`: магазин + название без размера и цвета)."""
    return it['fam'] if unit == 'family' else (it.get('via') or it['sku'])


def quota_table(slots: dict, styles: list, items: list, states: dict, shown: set, gate, thr: float,
                unit: str = 'sku', color=None) -> list:
    """Строка на (room_id × стиль × роль): единиц влезает / кандидатов (фото ok) / готово / можно в меш (по порядку добора).
    Единица — `unit_of` (`rules/demo-swap.json → room_count_unit`, по умолчанию sku). Меш один на семейство мешей (ADR-0196):
    задание ставится на представителя (`sku` после замены), и он закрывает ВСЕ единицы строки, что на него указывают
    (`weights`: цвета одной модели — один меш, несколько единиц). family: у модели в очередь идёт лучший по порядку меш, модель
    с готовым мешом в очередь не идёт. sku: каждый меш-представитель свой; порядок — в ленте → больше единиц на меш (дешевле)
    → балл стиля → цена → SKU. В стиле — `room_profile.in_style` (одно правило со сборщиками и отчётом скорера).
    color(товар, роль, стиль) → ярус (str) или `compose_common.color_eval` ({tier, rank}; ранг стиля по группе) — тот же
    оценщик, что у сборщиков (style-color-01):
    forbidden — не единица квоты (сборщик его не возьмёт; счёт — `color_forbidden`), остальное — в порядке добора ПЕРВЫМ
    ключом, раньше «в ленте» (ведущий T-20261107-12/2): ранг яруса из политики (`color_rank`). None — цвет не учитывается
    (ранг у всех одинаковый — порядок как до style-color-01)."""
    import compose_common as CC
    if unit not in COUNT_UNITS:
        raise DemandError(f'единица счёта квоты {unit!r}: только {"|".join(COUNT_UNITS)}')
    table = []
    for rid in sorted(slots):
        for st in styles:
            for role, sl in slots[rid].items():
                c: dict = {}
                best: dict = {}
                per_mesh: dict = {}
                for it in items:
                    if it['role'] != role or not _RP.in_style(it.get('styles'), st, thr):
                        continue
                    if not any(gate(it, x, x['band']) is None for x in sl):
                        continue
                    e = color(it, role, st) if color else None        # ярус (str) или color_eval → {tier, rank}
                    ct, cr = (e, CC.color_rank(e)) if isinstance(e, str) else ((e['tier'], e['rank']) if e else (None, 1))
                    if ct == 'forbidden':
                        c.setdefault('color_forbidden', set()).add(unit_of(it, unit))
                        continue
                    s, u = states[it['sku']], unit_of(it, unit)
                    c.setdefault('fit', set()).add(u)
                    if s in ('photo_pending', 'photo_bad'):
                        c.setdefault('photo', set()).add(u)
                        continue
                    c.setdefault('cand', set()).add(u)
                    c.setdefault(s, set()).add(u)
                    if s == 'job':
                        per_mesh.setdefault(it['sku'], set()).add(u)
                        key = (0 if (it['sku'] in shown or it.get('via') in shown) else 1, cr,
                               -(it.get('styles') or {}).get(st, 0), it.get('price') or 0, it['sku'])
                        bk = u if unit == 'family' else it['sku']
                        if bk not in best or key < best[bk][0]:
                            best[bk] = (key, it['sku'])
                if unit == 'family':      # модель уже с готовым мешом — второй меш её не добавит
                    best = {f: v for f, v in best.items() if f not in (c.get('covered') or ())}
                    weights = {v[1]: 1 for v in best.values()}
                else:
                    weights = {sku: len(us) for sku, us in per_mesh.items()}
                # ярус цвета → в ленте → единиц на меш → стиль → цена → SKU (v[0] = (в ленте, ярус, −стиль, цена, SKU))
                rk = lambda v: (v[0][1], v[0][0], -weights[v[1]]) + v[0][2:]  # noqa: E731
                order = sorted(best.values(), key=rk)
                n = lambda k: len(c.get(k) or ())  # noqa: E731
                table.append({'room_id': rid, 'style': st, 'role': role, 'unit': unit, 'fit': n('fit'), 'cand': n('cand'),
                              'covered': n('covered'), 'job': n('job'), 'photo_wait': n('photo'),
                              'mesh_other': n('has_mesh') + n('blocked') + n('defect'), 'not_job': n('not_job'),
                              'color_forbidden': n('color_forbidden'),
                              'shown_jobs': sum(1 for v in best.values() if v[0][0] == 0),
                              'ranked': [v[1] for v in order], 'weights': weights,
                              # ключ порядка — для общей ленты доли нескольких ролей (`quota_plan`, share)
                              'rank_keys': {v[1]: list(rk(v)) for v in order}})
    return table


def quota_share(split: dict, share: dict | None) -> dict:
    """Общие доли ролей (`rules/demo-swap.json → rooms.<комната>.share`, T-20261107-10/2): {роль-член: роль-лидер} —
    член своей доли не имеет, его единицы идут в долю лидера (распашной «шкаф» → «шкаф-купе»: «купе + распашной» = 8).
    Проверка: лидер — в долях, у члена своей ненулевой доли нет, без цепочек (лидер сам не член) и без «роль → себе».
    Ошибка — отказ, а не тихий счёт 8 + 8. → share (пустой словарь, если не задан)."""
    share = dict(share or {})
    for m, lead in share.items():
        if m == lead or lead not in split:
            raise DemandError(f'доля {m!r} → {lead!r}: лидер должен быть другой ролью из долей ({sorted(split)})')
        if int(split.get(m) or 0):
            raise DemandError(f'доля {m!r} → {lead!r}: у члена своя доля {split[m]} — либо общая, либо своя')
        if lead in share:
            raise DemandError(f'доля {m!r} → {lead!r} → {share[lead]!r}: цепочки долей не поддерживаются')
    return share


def quota_plan(table: list, split: dict, share: dict | None = None) -> list:
    """Добор до доли роли в каждом (room_id × стиль). Чистая функция. → выбранные SKU по порядку; в строки дописывает
    target / after / short. Один SKU засчитывается всем строкам, где он в `ranked` (меш один на все расстановки), — столько
    единиц, сколько у него в `weights` строки (нет `weights` — 1: счёт по семействам).

    ОБЩАЯ ДОЛЯ (`share`, `quota_share`; T-20261107-10/2): строки лидера и членов одного (room_id × стиль) — одна группа с
    целью доли лидера. Готовое у любой роли группы (меши распашных со спальни) уменьшает добор; добор — ОБЩЕЙ лентой группы
    по ключу `quota_table` (в ленте → единиц на меш → балл стиля → цена → SKU; роль — не первый признак, Codex 07.11), без
    ключей — лента лидера, потом членов. Цель и недобор пишутся в строку лидера (нет её — в первую строку группы), у членов
    target = short = 0, after — у каждой строки свой: суммы по (room_id × стиль) в `quota_md` и `demo_band.rooms_report`
    не задваиваются. Без share — как было: группа = строка."""
    share = quota_share(split, share)
    where: dict = {}
    for i, r in enumerate(table):
        for s in r['ranked']:
            where.setdefault(s, []).append(i)
    w = lambda i, s: int((table[i].get('weights') or {}).get(s, 1))  # noqa: E731
    order = list(split)
    lead_of = lambda role: share.get(role, role)  # noqa: E731
    groups: dict = {}
    for i, r in enumerate(table):
        groups.setdefault((r['room_id'], r['style'], lead_of(r['role'])), []).append(i)
    for g in groups.values():          # лидер — первым в группе, члены — по порядку таблицы
        g.sort(key=lambda i: (table[i]['role'] != lead_of(table[i]['role']), i))
    picked: list = []
    took: set = set()
    head: dict = {}
    for key in sorted(groups, key=lambda k: (k[0], k[1], order.index(k[2]) if k[2] in order else 99)):
        rows = groups[key]
        target = int(split.get(key[2], 0))
        for i in rows:
            table[i]['target'] = 0
        head[key] = rows[0]
        table[rows[0]]['target'] = target
        gain = lambda s: sum(w(i, s) for i in rows if i in where.get(s, ()))  # noqa: E731
        have = sum(table[i]['covered'] for i in rows) + sum(gain(s) for s in took)
        need = max(0, target - have)
        if len(rows) > 1 and all('rank_keys' in table[i] for i in rows):
            cand = [s for _k, s in sorted((tuple(table[i]['rank_keys'][s]), s) for i in rows for s in table[i]['ranked'])]
        else:
            cand = [s for i in rows for s in table[i]['ranked']]
        for s in cand:
            if need <= 0:
                break
            if s not in took:
                took.add(s)
                picked.append(s)
                need -= gain(s)
    for i, r in enumerate(table):
        r['after'] = r['covered'] + sum(w(i, s) for s in took if i in where[s])
        r['short'] = 0
    for key, rows in groups.items():
        table[head[key]]['short'] = max(0, table[head[key]]['target'] - sum(table[i]['after'] for i in rows))
    return picked


def _room_adapter(room: str):
    """(сборщик, правила, каталог, gate, порог стиля, допуск) комнаты — по реестру возможностей (`room_profile`, T-72)."""
    import importlib
    mod = importlib.import_module(_RP.capability(room, 'bank'))
    R = mod.rules()
    cat = mod.load_items(R)[0] if mod.__name__ == 'compose_bedroom' else mod.load_items()
    return mod, R, cat, mod.gate, float(mod.PROFILE['style']['in_style_min']), tuple(mod.tolerance())


def room_states(room: str, cat: list, R: dict, rows: dict, fetch) -> tuple:
    """Как `demand`: вариант семьи → представитель, состояние товара, годность задания (`room_mesh_jobs.job_of`).
    → (items, states, jobs_of)."""
    import asset_strategy as AS
    import re
    import room_mesh_jobs as RMJ
    md = (R.get('mesh_defect') or {}).get('names')
    defect_re = re.compile(md, re.I) if md else None
    items_all = [dict(it, sku=f"{it['mid']}:{it['eid']}") for it in cat if AS.strategy(it['role']) == 'hunyuan3d']
    F = facts(sorted({it['sku'] for it in items_all}), fetch)
    reps = sorted({f['rep'] for f in F.values() if f.get('rep') and f['rep'] not in F})
    F.update(facts(reps, fetch))
    own = {}
    for it in items_all:
        own.setdefault((it['sku'], it['role']), it)
    states, items, seen, jobs_of = {}, [], set(), {}
    for it in items_all:
        f = F.get(it['sku'], {})
        rep = f.get('rep')
        if rep and rep != it['sku'] and it['sku'] not in rows:
            it = dict(it, sku=rep, via=it['sku'])
            f = F.get(rep, {})
        elif colour_own(rows.get(it['sku'])):      # отметка сторожа цвета — свой меш варианту (T-20261107-14/2)
            f = own_facts(f, rows.get(it['sku']))
        key = (it['sku'], it['role'], it.get('via'))
        if key in seen:
            continue
        seen.add(key)
        if it['sku'] not in states:
            st = state_of(it['sku'], f, rows.get(it['sku']), bool(defect_re and defect_re.search(it.get('name') or '')))
            if st == 'job':
                base = own.get((it['sku'], it['role']))
                j, w = (None, 'представителя семьи нет в каталоге комнаты в этой роли') if base is None else \
                    RMJ.job_of(job_row(dict(base, slot_candidate=True), f), room)
                if j is None:
                    st, it['not_job'] = 'not_job', w
                else:
                    jobs_of[it['sku']] = j
            states[it['sku']] = st
        items.append(it)
    return items, states, jobs_of


def room_quota(room: str, bank_path: str, split: dict, fetch=None, rows=None, unit: str | None = None,
               share: dict | None = None) -> dict:
    """Квота мешей комнаты: таблица мест, выбранные задания по порядку, итоги. Только чтение БД и банка. unit — единица
    счёта (sku | family); None — из правил (`room_count_unit`). share — общие доли ролей ({член: лидер}, `quota_share`);
    передаётся явно (`demo_band.rooms_compute` — из rooms.<комната>.share)."""
    share = quota_share(split, share)
    import asset_strategy as AS
    import catalog_items as CI
    import room_bindings as RB
    fetch = fetch or CI.fetch
    if not bank_path or not os.path.exists(bank_path):
        raise DemandError(f'банк {room} не найден: {bank_path!r}')
    bank = json.load(open(bank_path, encoding='utf-8'))
    mod, R, cat, gate, thr, tol = _room_adapter(room)
    if rows is None:
        rows, why = RB.load_db(fetch)
        if rows is None:
            raise DemandError(f'привязка не читается ({why}) — без неё не знаю, у кого меш уже есть')
    items, states, jobs_of = room_states(room, cat, R, rows, fetch)
    slots = quota_slots(bank, R['purposes'], mod.band_of, tol, lambda r: AS.strategy(r) == 'hunyuan3d')
    styles = room_styles(bank, R)
    unit = unit or room_count_unit(room)
    import compose_common as CC        # цвет по фото (кэш thumbs/) + тот же оценщик, что у сборщика (style-color-01)
    CC.palette(items)
    table = quota_table(slots, styles, items, states, bank_shown(bank), gate, thr, unit,
                        color=lambda it, role, st: CC.color_eval(it, role, st))
    picked = quota_plan(table, split, share)
    jobs = []
    for s in picked:
        j = dict(jobs_of[s])
        cells = [f"{r['room_id']} × {r['style']} × {r['role']}" for r in table if s in r['ranked']]
        j['strata'] = {'tier': 'room', 'reason': f'комната {room}: квота 30 на (комната × стиль), T-20261106-82',
                       'cells': cells}
        jobs.append(j)
    return {'room': room, 'bank': bank_path, 'split': split, 'share': share, 'table': table, 'jobs': jobs, 'styles': styles,
            'unit': unit}


def room_styles(bank: list, R: dict) -> list:
    """Стили мест квоты: стили записей банка, но только из состава комнаты (`composer.rules.styles`; T-20261107-18 — неоклассика
    ушла из прихожей): старый банк со снятым стилем денег на него не тратит до штатной пересборки. Нет списка в правилах — все
    стили банка (как было)."""
    allowed = R.get('styles')
    return sorted({s['style'] for s in bank if s.get('style') and (not allowed or s['style'] in allowed)})


def quota_md(Q: dict) -> str:
    """Короткая сводка квоты для отчёта: строка на (room_id × стиль) + задания; недобор — «не хватает каталога»."""
    agg: dict = {}
    for r in Q['table']:
        a = agg.setdefault((r['room_id'], r['style']), {'covered': 0, 'cand': 0, 'target': 0, 'after': 0, 'short': 0})
        for k in a:
            a[k] += r[k]
    L = [f"Квота мешей {Q['room']} (банк {os.path.basename(Q['bank'])}, счёт — {UNIT_RU[Q.get('unit', 'family')]}): "
         f"в очередь {len(Q['jobs'])}", '',
         '| комната | стиль | готово | кандидатов | цель | после | не хватает каталога |', '|---|---|---|---|---|---|---|']
    for (rid, st), a in sorted(agg.items()):
        L.append(f"| {rid} | {st} | {a['covered']} | {a['cand']} | {a['target']} | {a['after']} | {a['short']} |")
    return '\n'.join(L)


def report(D: dict) -> dict:
    """Сводка по ролям: каталог роли → в полосе и стиле хоть одной ячейки → состояния → нужно → в очереди → цена."""
    roles = {}
    for role in D['roles']:
        rcells = {ck: c for ck, c in D['cells'].items() if c['role'] == role}
        # счёт — по мешам (sku после замены варианта представителем), не по строкам каталога
        its = {it['sku'] for it in D['items'] if it['role'] == role}
        cand_it = [it for it in D['items'] if it['role'] == role and any(D['member'](it, c) for c in rcells.values())]
        cand = {it['sku'] for it in cand_it}
        st = {}
        for s in cand:
            st[D['states'][s]] = st.get(D['states'][s], 0) + 1
        from_products = len({it['sku'] for it in cand_it if it.get('from_products')})
        need = sum(max(0, D['k'] - D['before'][ck]) for ck in rcells)
        q = [p for p in D['in_budget'] if any(D['cells'][ck]['role'] == role for ck in D['cells']
                                                 if cell_name(D['cells'][ck]) in p[2])]
        short = sorted(cell_name(c) for ck, c in rcells.items() if D['final'][ck] < D['k'])
        roles[role] = {'catalog': len(its), 'out_of_slots': len(its) - len(cand), 'candidates': len(cand), 'from_products': from_products, 'states': st,
                       'cells': len(rcells), 'need_before': need, 'queued': len(q),
                       'queued_bank': sum(1 for p in q if p[1] == 'bank'), 'short_cells': short}
    return {'room': D['room'], 'bank': os.path.basename(D['bank']), 'purposes': D['purposes'], 'k': D['k'],
            'binding_snapshot': D['snapshot'], 'cells': len(D['cells']),
            'cells_full_before': sum(1 for v in D['before'].values() if v >= D['k']),
            'cells_full_after': sum(1 for v in D['final'].values() if v >= D['k']),
            'picked': len(D['picked']), 'queued': len(D['in_budget']), 'over_budget': len(D['over_budget']),
            'queued_bank': sum(1 for p in D['in_budget'] if p[1] == 'bank'),
            'cost_rub': round(len(D['in_budget']) * D['price_rub'], 1), 'cost_low_rub': round(len(D['in_budget']) * 1.1, 1),
            'budget_rub': D['budget_rub'], 'price_rub': D['price_rub'], 'roles': roles}


def report_md(S: dict) -> str:
    L = [f"# Спрос на меши: {S['room']} (банк {S['bank']}, назначения {', '.join(S['purposes'])}, K={S['k']})", '',
         f"Привязка {S['binding_snapshot']}. Ячеек стиль×роль×слот: {S['cells']}; полных (≥K моделей с мешем) до: "
         f"{S['cells_full_before']}, после очереди: {S['cells_full_after']}.",
         f"В очередь: **{S['queued']}** (из набора банка {S['queued_bank']}, добор {S['queued'] - S['queued_bank']}) ≈ "
         f"{S['cost_low_rub']}–{S['cost_rub']} ₽ (потолок {S['budget_rub']:g} ₽)"
         + (f"; не влезло в потолок: {S['over_budget']}" if S['over_budget'] else '') + '.', '',
         '| роль | в каталоге | вне полос/стиля | кандидатов (из products) | готово | ждёт разблок. | фото не оценено | фото негодно | меш без привязки | годно | нужно до K | в очереди | ячеек < K |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r, v in S['roles'].items():
        s = v['states']
        L.append(f"| {r} | {v['catalog']} | {v['out_of_slots']} | {v['candidates']} ({v['from_products']}) | {s.get('covered', 0)} | "
                 f"{s.get('blocked', 0)} | {s.get('photo_pending', 0)} | {s.get('photo_bad', 0)} | {s.get('has_mesh', 0)} | {s.get('job', 0)} | "
                 f"{v['need_before']} | {v['queued']} | {len(v['short_cells'])} |")
    L += ['', 'Счёт — по мешам (вариант семьи — представителем) в полосе и стиле хоть одной ячейки; покрытие ячеек — по семействам моделей (размеры одной '
          'модели — одна).', '']
    for r, v in S['roles'].items():
        if v['short_cells']:
            L.append(f"- {r}: меньше K после очереди — " + '; '.join(v['short_cells']))
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('room_mesh_demand-selftest')
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    purposes = {'couple': {'slots': [{'role': 'кровать', 'ideal': {'w': 175, 'd': 215}, 'band': ['w', 'd'], 'sleep_w': [160, 180]},
                                     {'role': 'тумба', 'ideal': {'w': 45}, 'band': ['w']}]},
                'single': {'slots': [{'role': 'кровать', 'ideal': {'w': 135, 'd': 215}, 'band': ['w', 'd'], 'sleep_w': [90, 140]},
                                     {'role': 'тумба', 'ideal': {'w': 45}, 'band': ['w']}]},
                'office': {'empty': 'x'}}
    C = cells_of(purposes, ['couple', 'single', 'office'], ['кровать', 'тумба'], ['a', 'b'])
    ok('одинаковый слот назначений — одна ячейка, кровать — своя на назначение (2 стиля × (2 кровати + 1 тумба) = 6)',
       len(C) == 6 and sorted(len(c['purposes']) for c in C.values() if c['role'] == 'тумба') == [2, 2])
    ok('назначение не из банка — ячеек нет', len(cells_of(purposes, ['couple'], ['кровать', 'тумба'], ['a'])) == 2)

    def gate(it, slot, band):
        return None if all(lo <= it.get(k, 0) <= hi for k, (lo, hi) in band.items()) else 'вне'

    def band_of(slot, tol):
        return {k: [slot['ideal'][k] * tol[0], slot['ideal'][k] * tol[1]] for k in slot.get('band', [])}
    tum = next(c for c in C.values() if c['role'] == 'тумба' and c['style'] == 'a')
    ok('кандидат: полоса −20…+10 % и стиль ≥ порога',
       fits({'role': 'тумба', 'w': 49, 'styles': {'a': 7}}, tum, (0.8, 1.1), 6.6, gate, band_of)
       and not fits({'role': 'тумба', 'w': 50, 'styles': {'a': 7}}, tum, (0.8, 1.1), 6.6, gate, band_of)
       and not fits({'role': 'тумба', 'w': 35.9, 'styles': {'a': 7}}, tum, (0.8, 1.1), 6.6, gate, band_of)
       and fits({'role': 'тумба', 'w': 36.1, 'styles': {'a': 7}}, tum, (0.8, 1.1), 6.6, gate, band_of)
       and not fits({'role': 'тумба', 'w': 45, 'styles': {'a': 6.5}}, tum, (0.8, 1.1), 6.6, gate, band_of))

    base = {'in_products': False, 'has_mesh': False, 'verdict': 'ok'}
    ok('ready-привязка — покрыл; ready с браком — не покрыл; blocked — не в генерацию',
       state_of('s', base, {'status': 'ready'}, False) == 'covered' and state_of('s', base, {'status': 'ready'}, True) == 'defect'
       and state_of('s', base, {'status': 'blocked'}, False) == 'blocked')
    ok('без привязки: фото ok → job; не оценено → ждёт; коллаж → негодно; в products → job (T-49/2); меш свой/у представителя → нет',
       state_of('s', base, None, False) == 'job' and state_of('s', {**base, 'verdict': None}, None, False) == 'photo_pending'
       and state_of('s', {**base, 'verdict': 'collage'}, None, False) == 'photo_bad'
       and state_of('s', {**base, 'in_products': True}, None, False) == 'job'
       and state_of('s', {**base, 'rep_has_mesh': True}, None, False) == 'has_mesh'
       and state_of('s', {**base, 'has_mesh': True}, None, False) == 'has_mesh')
    # сторож цвета (T-20261107-14/2): вариант семьи с отметкой — кандидат на свой меш, не «готов» и не «ждёт разблокировки»
    cb = {'status': 'blocked', 'via_family': True, 'reasons': ['mesh_color_mismatch:dL-39,dab72']}
    ok('вариант семьи с отметкой цвета: не covered/blocked — job (своё фото ok), представитель не мешает',
       state_of('s', {**base, 'rep': 'r', 'rep_has_mesh': True}, cb, False) == 'job'
       and state_of('s', {**base, 'rep': 'r', 'rep_has_mesh': True, 'verdict': None}, cb, False) == 'photo_pending'
       and state_of('s', {**base, 'has_mesh': True}, cb, False) == 'has_mesh'
       and own_facts({'rep': 'r', 'rep_has_mesh': True}, cb) == {'rep': None, 'rep_has_mesh': False, 'colour_own': True})
    ok('свой меш с предупреждением цвета и blocked без отметки — как прежде',
       state_of('s', base, {'status': 'ready', 'via_family': False, 'reasons': [], 'warnings': ['mesh_color_mismatch']}, False) == 'covered'
       and state_of('s', base, {'status': 'blocked', 'via_family': True, 'reasons': ['rep:orientation_pending']}, False) == 'blocked')

    # выбор: одна ячейка, K=2; семейство считается один раз; сначала банк
    cell = {('a', 'тумба', 'x'): {'style': 'a', 'role': 'тумба', 'slot': {}, 'purposes': ['couple']}}
    it = lambda sku, fam, sc=7, pr=100: {'sku': sku, 'fam': fam, 'role': 'тумба', 'styles': {'a': sc}, 'price': pr}  # noqa: E731
    items = [it('r1', 'F1'), it('r2', 'F1'), it('j1', 'F1'), it('j2', 'F2', 8), it('j3', 'F3', 9), it('j4', 'F4', 6.7)]
    states = {'r1': 'covered', 'r2': 'covered', 'j1': 'job', 'j2': 'job', 'j3': 'job', 'j4': 'job'}
    member = lambda i, c: True  # noqa: E731
    P, before, after = choose(cell, items, states, [], 2, member)
    ok('покрытие — по семействам: два готовых одного семейства = 1; добор берёт лучший стиль другого семейства',
       before[('a', 'тумба', 'x')] == 1 and [p[0] for p in P] == ['j3'] and after[('a', 'тумба', 'x')] == 2)
    P, _, _ = choose(cell, items, states, ['j4', 'r1'], 2, member)
    ok('товар набора банка — первым, даже если не лучший; потом добор только до K',
       [p[0] for p in P] == ['j4'] and P[0][1] == 'bank')
    P, _, _ = choose(cell, items, states, ['j1'], 3, member)
    ok('товар банка того же семейства, что готовый, всё равно идёт (сам товар набора)', P[0][0] == 'j1' and P[0][1] == 'bank')
    two = {('a', 'тумба', 'x'): cell[('a', 'тумба', 'x')],
           ('b', 'тумба', 'x'): {'style': 'b', 'role': 'тумба', 'slot': {}, 'purposes': ['couple']}}
    items2 = [dict(it('m1', 'M1', 9), styles={'a': 9}), dict(it('m2', 'M2', 7), styles={'a': 7, 'b': 7})]
    mem2 = lambda i, c: (i['styles'].get(c['style'], 0) >= 6.6)  # noqa: E731
    P, _, _ = choose(two, items2, {'m1': 'job', 'm2': 'job'}, [], 1, mem2)
    ok('жадно: товар, закрывающий две ячейки, раньше лучшего по стилю в одной', [p[0] for p in P] == ['m2'])
    P, _, _ = choose(cell, items, {**states, 'j2': 'photo_pending', 'j3': 'blocked', 'j4': 'has_mesh'}, [], 3, member)
    ok('в генерацию — только job (не оценено/blocked/меш есть — нет)', [p[0] for p in P] == [])

    picked = [(f's{i}', 'bank' if i < 2 else 'topup', []) for i in range(10)]
    a, b = cut_budget(picked, 5.0, 1.4)
    ok('потолок: 5 ₽ / 1,4 ₽ = 3 модели, хвост — по приоритету', [p[0] for p in a] == ['s0', 's1', 's2'] and len(b) == 7)
    ok('потолок с запасом не режет', len(cut_budget(picked, 500, 1.4)[0]) == 10)

    row = job_row({'mid': 1, 'eid': '2', 'role': 'тумба прикроватная', 'name': 'Т', 'w': 45.0, 'd': 40.0, 'h': 55.0, 'img': 'u0'},
                  {'verdict': 'ok', 'footprint_ok': True, 'image_url': 'u1'})
    import room_mesh_jobs as RMJ
    j, w = RMJ.job_of(row, 'bedroom')
    ok('строка задания проходит room_mesh_jobs.job_of (формат снимка тот же)', j is not None and j['sku'] == '1:2'
       and j['image_url'] == 'u1' and j['seeds'] == [0])
    ok('без честного габарита — job_of отказывает', RMJ.job_of(dict(row, footprint_ok=False), 'bedroom')[0] is None)
    shk = {'mid': 1, 'eid': '3', 'role': 'шкаф', 'name': 'Ш', 'w': 150.0, 'd': 60.0, 'h': 220.0, 'img': 'u0'}
    fp = {'verdict': 'ok', 'footprint_ok': True, 'in_products': True, 'rep': '1:3'}
    ok('шкаф из products — кандидат слота, меша нет → задание (T-49/2)',
       RMJ.job_of(job_row(dict(shk, slot_candidate=True), fp), 'bedroom')[0] is not None)
    ok('шкаф из products не кандидат слота → нет; меш у представителя → нет',
       RMJ.job_of(job_row(shk, fp), 'bedroom')[0] is None
       and RMJ.job_of(job_row(dict(shk, slot_candidate=True), {**fp, 'rep': '1:4', 'rep_has_mesh': True}), 'bedroom')[0] is None)
    ok('банк: только items в ролях с мешем, без повторов',
       bank_items([{'items': {'кровать': {'mid': 1, 'eid': 'a'}, 'ковёр': {'mid': 1, 'eid': 'b'}}},
                   {'items': {'кровать': {'mid': 1, 'eid': 'a'}}, 'alternates': {'кровать': [{'mid': 1, 'eid': 'c'}]}}],
                  ['кровать']) == ['1:a'])
    try:
        demand('hall', '/нет', 3, 500, 1.4)
        ok('комната без банка/сборщика — явная ошибка', False)
    except DemandError:
        ok('комната без банка/сборщика — явная ошибка', True)
    wref = []
    for t in ('living', 'kitchen'):          # спрос по вариантам — тоже по реестру: отказ до чтения каталога
        try:
            want_demand(t, [{'room': t, 'sku': '1:x', 'role': 'диван', 'why': 'empty'}], 1.4, fetch=lambda *_: [])
        except DemandError as e:
            wref.append('реестре нет' in str(e))
    ok('спрос по вариантам: living и kitchen — отказ по реестру, прихожая и спальня — в реестре',
       wref == [True, True] and WANT_ROOMS == ('bedroom', 'hall'))
    refused = []
    for t in ('living', 'kitchen'):          # реестр возможностей (T-20261106-72): адаптер спальни для них не запускается
        try:
            demand(t, __file__, 3, 500, 1.4)
        except DemandError:
            refused.append(t)
    ok('living и kitchen — отказ до сборщика спальни (реестр возможностей)', refused == ['living', 'kitchen']
       and 'compose_bedroom' not in sys.modules)
    try:
        demand('bedroom', '/нет/банка.json', 3, 500, 1.4)
        ok('нет файла банка — явная ошибка', False)
    except DemandError:
        ok('нет файла банка — явная ошибка', True)

    # ---- общий остаток денег (T-20261106-75): журнал волн + резерв снимков, два запуска подряд ≤ потолка
    import shutil
    import tempfile
    import time as _t
    tmpd = tempfile.mkdtemp(prefix='rmd-selftest-')
    since = '2026-11-05T18:56:00+00:00'
    t0 = _ts(since)
    lease_keep = LEASE_FILE
    globals()['LEASE_FILE'] = os.path.join(tmpd, 'нет-разрешения.json')   # герметично: живое разрешение машины не читаем

    def snapf(name, room, jobs):
        p = os.path.join(tmpd, name)
        d = {'jobs': jobs} if room is None else {'room': room, 'jobs': jobs}
        json.dump(d, open(p, 'w', encoding='utf-8'))
        return p
    wj = [{'sku': '9:1', 'seeds': [0]}]
    waves = [{'started': t0 - 3600, 'closed': t0 - 60, 'spent_rub': 62.3, 'snapshot': snapf('w0.json', 'bedroom', wj)},
             {'started': t0 + 60, 'closed': t0 + 99, 'spent_rub': 100.0, 'snapshot': snapf('w1.json', 'bedroom', wj)},
             {'started': t0 + 120, 'rub_cap': 50.0, 'snapshot': snapf('w2.json', 'hall', wj)},
             {'started': t0 + 130, 'closed': t0 + 140, 'spent_rub': 999.0, 'snapshot': snapf('w3.json', None, wj)},
             {'started': t0 + 150, 'closed': t0 + 160, 'spent_rub': 10.0, 'snapshot': os.path.join(tmpd, 'нет.json')}]
    wp, rp = os.path.join(tmpd, 'wave-manual.json'), os.path.join(tmpd, 'reserve.jsonl')
    json.dump({'waves': waves}, open(wp, 'w', encoding='utf-8'))
    L0 = ledger(500.0, since, wp, rp)
    ok('остаток: до слова владельца не в счёт, гостиная не в счёт, открытая держит потолок, нечитаемый снимок — в счёт '
       '(500 − 100 − 10 − 50 = 340)', L0['left'] == 340.0 and L0['spent'] == 110.0 and L0['held'] == 50.0)
    J = lambda tag, n: [{'sku': f'{tag}:{i}', 'seeds': [0]} for i in range(n)]  # noqa: E731
    o1, o2, o3 = (os.path.join(tmpd, f'run{i}.json') for i in (1, 2, 3))
    f1, v1, _ = commit_snapshot(J('a', 200), o1, 'bedroom', 1.0, {'source': 't'}, 500.0, since, wp, rp, now=t0 + 200)
    f2, v2, _ = commit_snapshot(J('b', 200), o2, 'hall', 1.0, {'source': 't'}, 500.0, since, wp, rp, now=t0 + 201)
    f3, v3, _ = commit_snapshot(J('c', 50), o3, 'bedroom', 1.0, {'source': 't'}, 500.0, since, wp, rp, now=t0 + 202)
    L1 = ledger(500.0, since, wp, rp)
    ok('два запуска подряд (разные комнаты): первый берёт 200, второй — только остаток 140, вместе с фактом ≤ 500 ₽',
       len(f1) == 200 and len(f2) == 140 and len(v2) == 60 and L1['spent'] + L1['held'] + L1['reserved'] <= 500.0)
    ok('третий запуск при нулевом остатке: снимок пустой, резерва не пишет',
       len(f3) == 0 and L1['left'] == 0 and len(_read_reserve(rp)) == 2 and json.load(open(o3))['jobs'] == [])
    s1 = json.load(open(o1))
    ok('снимок — формат MESH_QUEUE_FILE (room, jobs с sku/seeds) + остаток и потолок в demand',
       s1['room'] == 'bedroom' and len(s1['jobs']) == 200 and s1['demand']['budget_left_rub'] == 340.0)
    launched = os.path.join(tmpd, 'mesh-queue-x.json')     # mesh_wave_start копирует снимок дословно под имя волны
    shutil.copy(o1, launched)
    waves.append({'started': t0 + 300, 'closed': t0 + 400, 'spent_rub': 150.0, 'snapshot': launched})
    json.dump({'waves': waves}, open(wp, 'w', encoding='utf-8'))
    L2 = ledger(500.0, since, wp, rp)
    ok('снимок ушёл в волну: резерв гаснет, считается факт волны (500 − 260 − 50 − 140 = 50)', L2['left'] == 50.0)
    release(o2, rp)
    ok('снятый резерв (снимок не пойдёт в волну) возвращает деньги в остаток', ledger(500.0, since, wp, rp)['left'] == 190.0)
    f4, _, _ = commit_snapshot(J('d', 500), os.path.join(tmpd, 'run4.json'), 'bedroom', 1.4, {'source': 't'}, 500.0, since, wp, rp,
                               now=_t.time())
    L4 = ledger(500.0, since, wp, rp)
    ok('по цене 1,4 ₽ остаток 190 → 135 моделей, общий счёт ≤ 500 ₽',
       len(f4) == 135 and L4['spent'] + L4['held'] + L4['reserved'] <= 500.0)
    open(wp, 'w').write('{битый')
    try:
        ledger(500.0, since, wp, rp)
        ok('битый журнал волн — отказ, а не «остаток 500»', False)
    except DemandError:
        ok('битый журнал волн — отказ, а не «остаток 500»', True)
    # волны автозапуска (разрешение wave_guard, T-20261106-82/2): все с начала учёта — в счёт комнат
    lp, wp2, rp2 = (os.path.join(tmpd, n) for n in ('lease.json', 'wm2.json', 'res2.jsonl'))
    json.dump({'waves': [{'started': t0 - 60, 'closed': t0 - 10, 'spent_usd': 9.0},
                         {'started': t0 + 10, 'closed': t0 + 20, 'spent_usd': 0.5},
                         {'started': t0 + 30, 'usd_cap': 0.2}]}, open(lp, 'w', encoding='utf-8'))
    L5 = ledger(500.0, since, wp2, rp2, lease_path=lp, usd_rub=100.0)
    ok('автоволны: до начала учёта не в счёт, закрытая — факт $ × курс, открытая держит потолок (500 − 50 − 20 = 430)',
       L5['spent'] == 50.0 and L5['held'] == 20.0 and L5['left'] == 430.0)
    ok('нет файла разрешения — автоволн нет (остаток 500)', ledger(500.0, since, wp2, rp2)['left'] == 500.0)
    open(lp, 'w').write('{битый')
    try:
        ledger(500.0, since, wp2, rp2, lease_path=lp, usd_rub=100.0)
        ok('битое разрешение — отказ, а не «остаток 500»', False)
    except DemandError:
        ok('битое разрешение — отказ, а не «остаток 500»', True)
    globals()['LEASE_FILE'] = lease_keep
    # ---- предупреждение на 80 % (владелец TG 1167): заглушка тревоги, метка во временной папке, настоящий TG не трогаем
    sent, stamp = [], os.path.join(tmpd, 'warn.json')
    fake = lambda text: sent.append(text) or 0  # noqa: E731
    Lw = lambda used: {'total': 1000.0, 'spent': used - 100.0, 'held': 100.0, 'left': 1000.0 - used}  # noqa: E731
    ok('799 из 1000 ₽ — тихо: ни WARN, ни тревоги, ни метки',
       budget_warn(Lw(799.0), stamp, fake, '2026-11-12') is None and not sent and not os.path.exists(stamp))
    w1 = budget_warn(Lw(800.0), stamp, fake, '2026-11-12')
    ok('800 из 1000 ₽ (факт + удержание) — WARN и одна тревога, метка с датой',
       bool(w1) and w1.startswith('WARN:room_mesh_budget:') and len(sent) == 1 and '80 %' in sent[0]
       and json.load(open(stamp, encoding='utf-8'))['date'] == '2026-11-12')
    w2 = budget_warn(Lw(850.0), stamp, fake, '2026-11-12')
    ok('повтор в тот же день — WARN есть, тревоги нет', bool(w2) and len(sent) == 1)
    budget_warn(Lw(850.0), stamp, fake, '2026-11-13')
    ok('на следующий день — тревога снова (одна)', len(sent) == 2)
    ok('резерв снимков в 80 % не входит (только факт + удержание)',
       budget_warn({'total': 1000.0, 'spent': 500.0, 'held': 200.0, 'reserved': 300.0, 'left': 0.0}, stamp, fake, '2026-11-14') is None)
    bad_rc = []
    budget_warn(Lw(900.0), os.path.join(tmpd, 'warn2.json'), lambda t: bad_rc.append(t) or 1, '2026-11-12')
    ok('alert.sh вернул 1 — метка всё равно записана (не чаще раза в сутки)',
       json.load(open(os.path.join(tmpd, 'warn2.json'), encoding='utf-8'))['rc'] == 1 and len(bad_rc) == 1)
    shutil.rmtree(tmpd, ignore_errors=True)

    # ---- квота 30 на (комната × стиль) с долями ролей (T-20261106-82/2): один меш — всем строкам, где он кандидат
    T = [{'room_id': 'b1', 'style': 'лофт', 'role': 'кровать', 'covered': 1, 'ranked': ['x', 'y', 'z']},
         {'room_id': 'b1', 'style': 'лофт', 'role': 'тумба', 'covered': 0, 'ranked': ['x']},
         {'room_id': 'b1', 'style': 'сканди', 'role': 'кровать', 'covered': 0, 'ranked': ['y']},
         {'room_id': 'b1', 'style': 'сканди', 'role': 'шкаф', 'covered': 5, 'ranked': ['w']}]
    P = quota_plan(T, {'кровать': 3, 'тумба': 1})
    ok('квота: добор по доле роли, SKU одной строки засчитан и другим (x закрыл тумбу, y — сканди), без доли — 0',
       P == ['x', 'y'] and [r['after'] for r in T] == [3, 1, 1, 5] and [r['short'] for r in T] == [0, 0, 2, 0]
       and T[3]['target'] == 0)

    # ---- общая доля (T-20261107-10/2): распашной «шкаф» в доле «шкаф-купе» — 8 на двоих, не 8 + 8
    def qrow(role, covered, ranked, keys=None, rid='h1', st='лофт'):
        r = {'room_id': rid, 'style': st, 'role': role, 'covered': covered, 'ranked': ranked}
        if keys is not None:
            r['rank_keys'] = keys
        return r
    sp, sh_ = {'шкаф-купе': 3, 'обувница': 1}, {'шкаф': 'шкаф-купе'}
    K = lambda shown, sc, sku: [shown, -1, -sc, 100, sku]  # noqa: E731
    Tq = [qrow('шкаф-купе', 0, ['k1', 'k2', 'k3'], {'k1': K(1, 8.0, 'k1'), 'k2': K(1, 7.0, 'k2'), 'k3': K(1, 6.9, 'k3')}),
          qrow('шкаф', 1, ['s1', 's2'], {'s1': K(0, 6.7, 's1'), 's2': K(1, 7.5, 's2')}),
          qrow('обувница', 0, ['o1'], {'o1': K(1, 7, 'o1')})]
    Pq = quota_plan(Tq, sp, sh_)
    ok('общая доля: готовый меш распашного (со спальни) засчитан купе — добор 2, а не 3',
       sum(r['after'] for r in Tq[:2]) == 3 and len([s for s in Pq if s != 'o1']) == 2)
    ok('общая доля: добор общей лентой по ключу (в ленте s1 → балл k1 8,0 → s2 7,5), не «сперва все купе»',
       Pq == ['s1', 'k1', 'o1'])
    ok('общая доля: цель и недобор — в строке лидера, у члена 0 (суммы quota_md не задваиваются)',
       [r['target'] for r in Tq] == [3, 0, 1] and [r['short'] for r in Tq] == [0, 0, 0]
       and sum(r['target'] for r in Tq) == 4)
    Tq2 = [qrow('шкаф-купе', 0, ['k1']), qrow('шкаф', 0, ['s1'])]
    Pq2 = quota_plan(Tq2, {'шкаф-купе': 3}, sh_)
    ok('общая доля: каталога на двоих 2 из 3 — недобор 1 у лидера; без ключей — лента лидера, потом члена',
       Pq2 == ['k1', 's1'] and Tq2[0]['short'] == 1 and Tq2[1]['short'] == 0 and [r['after'] for r in Tq2] == [1, 1])
    Tq3 = [qrow('шкаф', 2, ['s1'])]
    quota_plan(Tq3, {'шкаф-купе': 3}, sh_)
    ok('общая доля: строки лидера нет (купе не влезает) — цель в строке члена', Tq3[0]['target'] == 3 and Tq3[0]['short'] == 0)
    Tq4 = [qrow('шкаф-купе', 0, ['k1']), qrow('шкаф', 0, ['s1'])]
    P4 = quota_plan(Tq4, {'шкаф-купе': 1})
    ok('без share — как было: распашной без доли, купе берёт своё', P4 == ['k1'] and Tq4[1]['target'] == 0)
    for bad_share, why in (({'шкаф': 'нет'}, 'лидер не в долях'), ({'шкаф-купе': 'шкаф-купе'}, 'роль → себе'),
                           ({'обувница': 'шкаф-купе'}, 'у члена своя доля'),
                           ({'шкаф': 'шкаф-купе', 'шкаф-купе': 'обувница'}, 'цепочка')):
        try:
            quota_share({'шкаф-купе': 3, 'обувница': 1}, bad_share)
            ok(f'share: {why} — отказ', False)
        except DemandError:
            ok(f'share: {why} — отказ', True)
    # T-20261107-18/2: модуль «прихожая» — в доле шкафа-купе (ведущий 07.11): живые правила и счёт группы из трёх ролей
    H = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))['rooms']['hall']
    hs = quota_share(H['roles'], H.get('share'))
    ok('прихожая в правилах: сумма долей на стиль 30, купе 11, модуль и распашной — члены доли купе без своей доли',
       sum(H['roles'].values()) == 30 and H['roles']['шкаф-купе'] == 11 and 'прихожая' not in H['roles']
       and hs == {'шкаф': 'шкаф-купе', 'прихожая': 'шкаф-купе'})
    Th = [qrow('шкаф-купе', 2, ['k1', 'k2', 'k3']), qrow('шкаф', 1, ['s1']),
          qrow('прихожая', 1, ['n1', 'n2', 'n3'])]                 # Неста: 1 меш готов + 3 цвета в ленте
    Ph = quota_plan(Th, H['roles'], hs)
    ok('прихожая: Неста засчитана в 11 — готовый меш модуля и добор его лентой, цель и недобор только у купе',
       sum(r['after'] for r in Th) == 11 and {'n1', 'n2', 'n3'} <= set(Ph) and len(Ph) == 7
       and [r['target'] for r in Th] == [11, 0, 0] and [r['short'] for r in Th] == [0, 0, 0])

    # ---- типоразмеры слота в квоте (T-20261106-90): запись банка несёт полосу своего типоразмера, остальные — из правил
    def bo(slot, tol):
        return {k: [slot['ideal'][k] * tol[0], slot['ideal'][k] * tol[1]] for k in slot.get('band', [])}
    prof = {'hall': {'slots': [{'role': 'консоль', 'ideal': {'w': 90}, 'band': ['w'], 'sizes': [{'id': '120', 'ideal': {'w': 120}}]},
                               {'role': 'тумба', 'ideal': {'w': 40}, 'band': ['w']}]}}
    bank_ = [{'room_id': 'h', 'purpose': 'hall', 'slots': {'консоль': {'mesh': True, 'band': {'w': [96.0, 132.0]}},
                                                         'тумба': {'mesh': True, 'band': {'w': [30.0, 50.0]}}}}]
    QS = quota_slots(bank_, prof, bo, (0.8, 1.1), lambda r: True)
    ok('квота: у роли с типоразмерами — полосы всех (запись 120 + основной 90), без типоразмеров — только полоса записи',
       sorted(x['band']['w'][0] for x in QS['h']['консоль']) == [72.0, 96.0] and len(QS['h']['тумба']) == 1)

    # ---- единица счёта (T-20261106-90): sku | family; меш один на семейство мешей, цвета — через представителя (via)
    sl = {'h1': {'обувница': [{'role': 'обувница', 'band': {'w': [48, 66]}}]}}
    g = lambda it, slot, band: None if all(lo <= it.get(k, 0) <= hi for k, (lo, hi) in band.items()) else 'вне'  # noqa: E731
    sh = lambda sku, fam, w=60, sc=7.0, via=None: dict({'sku': sku, 'fam': fam, 'role': 'обувница', 'w': w, 'styles': {'лофт': sc},  # noqa: E731
                                                        'price': 100}, **({'via': via} if via else {}))
    its = [sh('1:a', 'A'), sh('1:a', 'A', via='1:a2'), sh('1:a', 'A', via='1:a3'),    # модель A: 3 цвета, меш у представителя 1:a
           sh('1:b', 'A', w=64),                                                       # модель A другого размера — свой меш
           sh('1:c', 'C'), sh('1:d', 'D', sc=6.5), sh('1:e', 'E', w=90)]               # D — ниже порога, E — вне полосы
    stt = {'1:a': 'job', '1:b': 'job', '1:c': 'job', '1:d': 'job', '1:e': 'job'}
    Ts = quota_table(sl, ['лофт'], its, stt, set(), g, 6.6, 'sku')
    Tf = quota_table(sl, ['лофт'], its, stt, set(), g, 6.6, 'family')
    ok('sku: 4 артикула в полосе и стиле (3 цвета A + размер A), C; меш 1:a закрывает 3 единицы и идёт первым',
       Ts[0]['fit'] == 5 and Ts[0]['ranked'] == ['1:a', '1:b', '1:c'] and Ts[0]['weights'] == {'1:a': 3, '1:b': 1, '1:c': 1})
    ok('family: моделей 2 (A, C), по мешу на модель', Tf[0]['fit'] == 2 and len(Tf[0]['ranked']) == 2
       and set(Tf[0]['weights'].values()) == {1})
    Ps, Pf = quota_plan(Ts, {'обувница': 4}), quota_plan(Tf, {'обувница': 4})
    ok('доля 4: sku — 2 меша (1:a = 3 цвета + 1:b), family — 2 меша и недобор 2 (моделей нет)',
       Ps == ['1:a', '1:b'] and Ts[0]['after'] == 4 and Ts[0]['short'] == 0 and len(Pf) == 2 and Tf[0]['short'] == 2)
    stc = dict(stt, **{'1:a': 'covered'})
    Tc = quota_table(sl, ['лофт'], its, stc, set(), g, 6.6, 'family')
    ok('family: модель с готовым мешом второй меш не получает (размер 1:b той же модели не в очереди)',
       Tc[0]['covered'] == 1 and Tc[0]['ranked'] == ['1:c'])
    Tcs = quota_table(sl, ['лофт'], its, stc, set(), g, 6.6, 'sku')
    ok('sku: готовый меш представителя засчитан всем трём цветам', Tcs[0]['covered'] == 3 and Tcs[0]['ranked'][0] in ('1:b', '1:c'))
    ok('правила: room_count_unit по умолчанию sku, своё у комнаты, чужое — отказ',
       room_count_unit('hall', {}) == 'sku' and room_count_unit('hall', {'room_count_unit': 'family'}) == 'family'
       and room_count_unit('hall', {'room_count_unit': 'family', 'rooms': {'hall': {'count_unit': 'sku'}}}) == 'sku'
       and room_count_unit('hall') in COUNT_UNITS)
    try:
        room_count_unit('hall', {'room_count_unit': 'штуки'})
        ok('неизвестная единица — отказ', False)
    except DemandError:
        ok('неизвестная единица — отказ', True)

    # ---- спрос по вариантам витрины
    import asset_strategy as AS
    hb = [{'style': 'сканди', 'tier': 'комфорт', 'mesh_need': ['1:a', '1:z', '1:m'],
           'items': {'вешалка': {'mid': 1, 'eid': 'a'}, 'зеркало': {'mid': 1, 'eid': 'z'}, 'обувница': {'mid': 1, 'eid': 'm'}}},
          {'style': 'лофт', 'tier': 'комфорт', 'mesh_need': ['1:a'], 'items': {'вешалка': {'mid': 1, 'eid': 'a'}}}]
    H = hall_want(hb, AS.strategy)
    ok('прихожая из банка: без меша и в ролях с мешем (зеркало — плоскость), товар двух вариантов — одна строка',
       sorted(h['sku'] for h in H) == ['1:a', '1:m'] and next(h for h in H if h['sku'] == '1:a')['variants'] == ['сканди комфорт', 'лофт комфорт'])
    # T-20261107-18: неоклассика ушла из прихожей — набор снятого стиля в старом банке денег не тратит до пересборки
    hb_neo = hb + [{'style': 'неоклассика', 'tier': 'комфорт', 'mesh_need': ['1:n'], 'items': {'банкетка': {'mid': 1, 'eid': 'n'}}}]
    ok('прихожая из банка: набор стиля не из состава комнаты — не в спрос',
       sorted(h['sku'] for h in hall_want(hb_neo, AS.strategy, ['сканди', 'лофт'])) == ['1:a', '1:m']
       and '1:n' in {h['sku'] for h in hall_want(hb_neo, AS.strategy)})
    ok('квота: стили мест — из банка, но только из состава комнаты; без списка в правилах — все стили банка',
       room_styles(hb_neo, {'styles': ['сканди', 'лофт', 'минимализм']}) == ['лофт', 'сканди']
       and room_styles(hb_neo, {}) == ['лофт', 'неоклассика', 'сканди'])
    M = merge_want([{'room': 'bedroom', 'sku': '1:t', 'role': 'комод', 'why': 'empty', 'variants': ['v1']},
                    {'room': 'bedroom', 'sku': '1:t', 'role': 'комод', 'why': 'regen', 'variants': ['v2']},
                    {'room': 'bedroom', 'sku': '1:h', 'role': 'вешалка', 'why': 'hall', 'variants': []},
                    {'room': 'bedroom', 'sku': '1:e', 'role': 'шкаф', 'why': 'empty', 'variants': ['v1']}])
    ok('слияние: перегенерация сильнее пустой роли, варианты объединены; порядок — пустые → брак → прихожая',
       [m['sku'] for m in M] == ['1:e', '1:t', '1:h'] and M[1]['why'] == 'regen' and M[1]['variants'] == ['v1', 'v2'])
    import room_mesh_jobs as RMJ

    def card(sku, **kw):
        c = {'sku': sku, 'role': 'шкаф', 'name': 'Шкаф ' + sku, 'w': 120.0, 'd': 60.0, 'h': 220.0, 'footprint_ok': True,
             'shown': True, 'in_products': True, 'rep': None, 'sha': 'sha-' + sku, 'image_url': 'u-' + sku, 'verdict': 'ok',
             'used': [], 'max_seed': None, 'in_room': True}
        c.update(kw)
        return c
    ev = lambda why, F, sibs=(), sku='1:x': evaluate({'sku': sku, 'why': why}, F, list(sibs), 'bedroom', RMJ.job_of)  # noqa: E731
    r = ev('empty', {'1:x': card('1:x')})
    ok('пустая роль, фото ok → задание seed 0 на sku', r['state'] == 'job' and r['job']['sku'] == '1:x' and r['job']['seeds'] == [0])
    ok('пустая роль, фото не оценено → «ждёт вырезки»', ev('empty', {'1:x': card('1:x', verdict=None)})['state'] == 'wait_cut')
    ok('пустая роль, вырезка collage → фото негодно', ev('empty', {'1:x': card('1:x', verdict='collage')})['state'] == 'photo_bad')
    ok('пустая роль, меш уже есть → не генерация (держит привязка/индекс)',
       ev('empty', {'1:x': card('1:x', used=['sha-1:x'])})['state'] == 'has_mesh')
    ok('нет карточки в комнате → not_in_room', ev('empty', {})['state'] == 'not_in_room')
    F = {'1:x': card('1:x', used=['sha-1:x'], max_seed=2), '1:s1': card('1:s1', verdict=None), '1:s2': card('1:s2')}
    r = ev('regen', F, ['1:s1', '1:s2'])
    ok('брак: своё фото = фото меша → берём оценённое фото варианта семьи (меш на вариант, seed 0)',
       r['state'] == 'regen_sibling' and r['job_sku'] == '1:s2' and r['job']['seeds'] == [0])
    r = ev('regen', {**F, '1:s2': card('1:s2', verdict='tiny_object')}, ['1:s1', '1:s2'])
    ok('брак: у варианта фото есть, но не оценено → «ждёт вырезки» с именем варианта', r['state'] == 'wait_cut' and '1:s1' in r['reason'])
    ok('брак: других фото нет → no_alt', ev('regen', {'1:x': F['1:x']})['state'] == 'no_alt')
    r = ev('regen', {'1:x': card('1:x', used=['old'], max_seed=2, sha='new')})
    ok('брак: фото товара сменилось после меша, ok → перегенерация своим фото, следующий seed',
       r['state'] == 'regen_job' and r['job']['seeds'] == [3])
    ok('брак: вариант семьи с мешем фото не даёт (его фото уже в меше)',
       ev('regen', {'1:x': F['1:x'], '1:s2': card('1:s2', used=['sha-1:s2'])}, ['1:s2'])['state'] == 'no_alt')
    F3 = {'1:x': card('1:x', used=['sha-1:x']), '1:s1': card('1:s1'), '1:s2': card('1:s2'), '1:s3': card('1:s3', verdict=None)}
    r = evaluate({'sku': '1:x', 'why': 'regen', 'shown': ['1:s2']}, F3, ['1:s1', '1:s2'], 'bedroom', RMJ.job_of)
    ok('брак: цвет показанного варианта — первым (не первый по коду)', r['state'] == 'regen_sibling' and r['job_sku'] == '1:s2')
    r = evaluate({'sku': '1:x', 'why': 'regen', 'shown': ['1:s3']}, F3, ['1:s1', '1:s3'], 'bedroom', RMJ.job_of)
    ok('брак: фото показанного варианта не оценено → ждём его, чужой цвет не берём', r['state'] == 'wait_cut' and '1:s3' in r['reason'])
    M2 = merge_want([{'room': 'b', 'sku': '1:x', 'why': 'empty', 'shown': ['1:s2']}, {'room': 'b', 'sku': '1:x', 'why': 'regen'}])
    ok('слияние сохраняет показанные варианты', M2[0]['why'] == 'regen' and M2[0]['shown'] == ['1:s2'])
    full = 'f' * 64
    ok('брак: фото меша (16 знаков в mesh_generations) = полный хеш текущего фото → не «новое фото»',
       ev('regen', {'1:x': card('1:x', sha=full, used=[full[:16]])})['state'] == 'no_alt')
    r = ev('regen', {'1:x': card('1:x', verdict=None)})
    ok('в списке брака, но меша у семьи нет → первая генерация (ждёт вырезки, с пометкой)',
       r['state'] == 'wait_cut' and 'первая генерация' in r['reason'])
    # T-20261112-47/3: оливковый вариант семьи при светлом меше представителя (сторож цвета) — кандидат на СВОЙ меш
    fv = {'1:v': card('1:v', rep='1:r')}
    r = evaluate({'sku': '1:v', 'why': 'empty'}, fv, [], 'bedroom', RMJ.job_of, own=True)
    ok('вариант с отметкой сторожа цвета → задание на свой sku, не «меш делается представителю»',
       r['state'] == 'job' and r['job_sku'] == '1:v'
       and evaluate({'sku': '1:v', 'why': 'empty'}, fv, [], 'bedroom', RMJ.job_of)['state'] == 'not_job')

    def fake_fetch(sql):
        if 'mesh_family_rep in' in sql:
            return []
        rows = {'1:v': ('1:v', 'комод', 'Комод Оливковый', 93, 45, 87, 't', 't', 't', '1:r', 'sha-v', 'u-v', 'ok', None, None, 't', '.'),
                '1:r': ('1:r', 'комод', 'Комод Светлый', 93, 45, 87, 't', 't', 't', '1:r', 'sha-r', 'u-r', 'ok', 'sha-r', 0, 't', '.')}
        return [v for k, v in rows.items() if f"'{k}'" in sql]
    olive = [{'room': 'bedroom', 'sku': '1:v', 'role': 'комод', 'why': 'empty', 'variants': ['v']}]
    flag = {'1:v': {'status': 'blocked', 'via_family': True,
                    'reasons': ['family_colour_mismatch:зелёный→светлый', 'mesh_color_mismatch:dL+6,dab8']}}
    Wf = want_demand('bedroom', olive, 1.4, fetch=fake_fetch, binds=flag, assessor='selftest')
    Wn = want_demand('bedroom', olive, 1.4, fetch=fake_fetch, binds={}, assessor='selftest')
    ok('спрос по вариантам: оливковый товар при светлом меше семьи → свой меш (job на 1:v), без отметки → «меш есть» у представителя',
       [j['sku'] for j in Wf['jobs']] == ['1:v'] and Wf['rows'][0]['state'] == 'job'
       and not Wn['jobs'] and Wn['rows'][0]['sku'] == '1:r' and Wn['rows'][0]['state'] == 'has_mesh')
    print(f'итог: {"OK" if not bad else f"FAIL {bad}"}')
    return 1 if bad else 0


def main(a: list) -> int:
    if '--selftest' in a:
        return _selftest()
    arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    room = arg('--room', 'bedroom')
    total, since, price = float(arg('--budget', BUDGET_RUB)), arg('--since', BUDGET_SINCE), float(arg('--price', PRICE_RUB))
    if '--release' in a:
        release(arg('--release'))
        print(f'резерв снят: {arg("--release")}')
        L = ledger(total, since)
        print(ledger_text(L))
        budget_warn(L)
        return 0
    if '--ledger' in a:
        try:
            L = ledger(total, since)
        except DemandError as e:
            print(f'ОТКАЗ: {e}', flush=True)
            return 2
        print(ledger_text(L))
        budget_warn(L)
        for r in L['rows']:
            at = r['at'] if isinstance(r['at'], str) else __import__('time').strftime('%Y-%m-%d %H:%M', __import__('time').gmtime(r['at']))
            print(f"  {at:<16}  {r['kind']:<34} {r['room'] or '?':<8} {r['rub']:>7.1f} ₽  {r['snapshot']}")
        return 0
    dry = '--dry' in a
    if '--out' not in a and not dry:
        print(__doc__)
        return 64
    out = arg('--out')
    if '--want' in a or '--hall-bank' in a:
        return main_want(a, arg, room, total, since, price, out, dry)
    try:
        L = ledger(total, since)
        D = demand(room, arg('--bank'), int(arg('--k', K_DEFAULT)), L['left'], price)
    except DemandError as e:
        print(f'ОТКАЗ: {e}', flush=True)
        return 2
    print(ledger_text(L))
    budget_warn(L)
    if not dry:
        fit, over, L = commit_snapshot(D['jobs'], out, room, price, {
            'source': f"room_mesh_demand:{room}", 'demand': {'k': D['k'], 'bank': D['bank'], 'binding_snapshot': D['snapshot']}},
            total, since)
        if len(fit) < len(D['jobs']):
            print(f'остаток сменился за расчёт: в снимке {len(fit)} из {len(D["jobs"])}', flush=True)
        D['jobs'] = fit
    S = report(D)
    rep = arg('--report-out') or os.path.dirname(os.path.abspath(out or '.'))
    os.makedirs(rep, exist_ok=True)
    base = os.path.join(rep, f'demand-{room}')
    json.dump(S, open(base + '.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(base + '.md', 'w', encoding='utf-8').write(report_md(S))
    with open(base + '-picked.tsv', 'w', encoding='utf-8') as f:
        f.write('sku\tприоритет\tв_потолке\tроль\tсемейство\tячейки\n')
        role_of = {it['sku']: it['role'] for it in D['items']}
        fb = {s for s, _, _ in D['in_budget']}
        for s, pr, cs in D['picked']:
            f.write(f"{s}\t{pr}\t{'да' if s in fb else 'нет'}\t{role_of.get(s)}\t{D['fam_of'].get(s)}\t{'; '.join(cs)}\n")
    print(report_md(S))
    print(f'{"сухой расчёт" if dry else "снимок " + out}: заданий {len(D["jobs"])}; отчёт {base}.md / .json / -picked.tsv', flush=True)
    return 0 if D['jobs'] else 3


def main_want(a: list, arg, room: str, total: float, since: str, price: float, out: str | None, dry: bool) -> int:
    """Спрос по вариантам витрины: `--want` (файл строк) и/или `--hall-bank` (банк compose_hall, флаг до реестра T-72)."""
    import asset_strategy as AS
    entries = []
    try:
        if '--want' in a:
            p = arg('--want')
            if not p or p.startswith('--'):     # `--want` без пути — файл по умолчанию, следующий ключ не съедаем
                p = WANT_FILE
            entries += json.load(open(p, encoding='utf-8'))['items']
        if '--hall-bank' in a:
            hb = arg('--hall-bank')
            if not hb or not os.path.exists(hb):
                raise DemandError(f'банк прихожей не найден: {hb!r}')
            import compose_hall as CH
            entries += hall_want(json.load(open(hb, encoding='utf-8')), AS.strategy, CH.rules().get('styles'))
        L = ledger(total, since)
        W = want_demand(room, entries, price)
    except (DemandError, OSError, KeyError, ValueError) as e:
        print(f'ОТКАЗ: {e}', flush=True)
        return 2
    budget_warn(L)
    if dry:
        fit, over = cut_budget(W['jobs'], L['left'], price)
    else:
        fit, over, L = commit_snapshot(W['jobs'], out, room, price, {'source': f'room_mesh_demand:want:{room}'}, total, since)
    md = want_md(W, fit, L, dry)
    rep = arg('--report-out') or os.path.dirname(os.path.abspath(out or '.'))
    os.makedirs(rep, exist_ok=True)
    base = os.path.join(rep, f'want-{room}')
    open(base + '.md', 'w', encoding='utf-8').write(md)
    json.dump({'room': room, 'ledger': L, 'rows': [{k: v for k, v in r.items() if k != 'job'} for r in W['rows']],
               'jobs': fit, 'over_budget': [j['sku'] for j in over]},
              open(base + '.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(md)
    print(f'{"сухой расчёт — снимок не пишу, резерва нет" if dry else "снимок " + out}: заданий {len(fit)}'
          f'{f", не влезло {len(over)}" if over else ""}; отчёт {base}.md / .json', flush=True)
    return 0 if fit else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
