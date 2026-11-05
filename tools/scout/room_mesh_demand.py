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
Сумма > потолка (500 ₽, владелец 05.11) — хвост по приоритету отрезается, в отчёте — что не влезло.

  ~/venvs/scout/bin/python room_mesh_demand.py --room bedroom --bank <sets-bedroom.next.json> --out FILE [--k 3]
        [--budget 500] [--price 1.4] [--report-out DIR]
  python3 room_mesh_demand.py --selftest      # правила на подставных данных, без базы
Env: `BEDROOM_STYLE_SCORES` — как у `compose_bedroom.py` (в worktree — путь основной копии).
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))

K_DEFAULT = 3
BUDGET_RUB = 500.0          # потолок владельца на меши комнат (план room-pipeline-01 § Деньги)
PRICE_RUB = 1.4             # верх замера T-11 (13,8 ₽ / 10); волна 45 моделей — 1,08 ₽
ROOMS = ('bedroom',)        # комнаты со сборщиком наборов и банком; прихожая — когда появится банк (T-48)


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
    return (it.get('styles') or {}).get(c['style'], 0) >= thr


# ---------------------------------------------------------------- состояние товара
def state_of(sku: str, f: dict, bind: dict | None, defect: bool) -> str:
    """covered | blocked | defect | job | photo_pending | photo_bad | has_mesh | not_job.
    f — факты БД (has_mesh, rep_has_mesh, verdict). Товар из products — на общих правах (T-49/2)."""
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


# ---------------------------------------------------------------- отчёт
STATE_RU = {'covered': 'меш готов (ready)', 'blocked': 'меш есть, ждёт разблокировки (blocked)', 'defect': 'брак меша',
            'job': 'годен в генерацию', 'photo_pending': 'фото не оценено (ждёт вырезки)', 'photo_bad': 'фото негодно (коллаж/мелко/брак)',
            'has_mesh': 'меш есть (свой или у представителя), привязки нет',
            'not_job': 'не годен к заданию (room_mesh_jobs)'}


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


def write_snapshot(D: dict, out: str) -> None:
    """Формат `room_mesh_jobs.build` (его читает `mesh_wave_start.sh` → `MESH_QUEUE_FILE`)."""
    snap = {'source': f"room_mesh_demand:{D['room']}", 'room': D['room'], 'policy_version': 2, 'rework': [],
            'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'demand': {'k': D['k'], 'bank': D['bank'], 'binding_snapshot': D['snapshot'], 'price_rub': D['price_rub'],
                       'budget_rub': D['budget_rub'], 'over_budget': [s for s, _, _ in D['over_budget']]},
            'jobs': D['jobs']}
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
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
    try:
        demand('bedroom', '/нет/банка.json', 3, 500, 1.4)
        ok('нет файла банка — явная ошибка', False)
    except DemandError:
        ok('нет файла банка — явная ошибка', True)
    print(f'итог: {"OK" if not bad else f"FAIL {bad}"}')
    return 1 if bad else 0


def main(a: list) -> int:
    if '--selftest' in a:
        return _selftest()
    arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    room = arg('--room', 'bedroom')
    if '--out' not in a:
        print(__doc__)
        return 64
    try:
        D = demand(room, arg('--bank'), int(arg('--k', K_DEFAULT)), float(arg('--budget', BUDGET_RUB)),
                   float(arg('--price', PRICE_RUB)))
    except DemandError as e:
        print(f'ОТКАЗ: {e}', flush=True)
        return 2
    out = arg('--out')
    write_snapshot(D, out)
    S = report(D)
    rep = arg('--report-out') or os.path.dirname(os.path.abspath(out))
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
    print(f'снимок {out}: заданий {len(D["jobs"])}; отчёт {base}.md / .json / -picked.tsv', flush=True)
    return 0 if D['jobs'] else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
