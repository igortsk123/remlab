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
ОБЩИЙ ОСТАТОК (T-20261106-75, критика Codex к hall-demo-01: «бюджет не общий»): потолок владельца 500 ₽ — один на ВСЕ комнаты
и ВСЕ запуски, а не на каждый запуск. Каждый запуск считает остаток = 500 − факт волн комнат − удержание открытых − резерв
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
        [--budget 500] [--price 1.4] [--report-out DIR]                                  # спрос по слотам (весь каталог)
  ~/venvs/scout/bin/python room_mesh_demand.py --room bedroom --want rules/room-mesh-want.json (--out FILE | --dry) [--report-out DIR]
  ~/venvs/scout/bin/python room_mesh_demand.py --room hall --hall-bank <sets-hall.next.json> (--out FILE | --dry)
  ~/venvs/scout/bin/python room_mesh_demand.py --ledger            # остаток денег мешей комнат
  ~/venvs/scout/bin/python room_mesh_demand.py --release FILE      # снять резерв снимка, который не пойдёт в волну
  python3 room_mesh_demand.py --selftest      # правила на подставных данных, без базы
`--budget` — общий потолок (500), не потолок запуска. Env: `BEDROOM_STYLE_SCORES` — как у `compose_bedroom.py` (в worktree —
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

K_DEFAULT = 3
BUDGET_RUB = 500.0          # ОБЩИЙ потолок владельца на меши всех комнат (план room-pipeline-01 § Деньги) — см. ledger
BUDGET_SINCE = '2026-11-05T00:00:00+00:00'   # учёт с начала трека комнат (onb-10 создан 05.11; волны T-11 13,8 + 48,5 ₽ — в счёт, решение ведущего T-75/1)
PRICE_RUB = 1.4             # верх замера T-11 (13,8 ₽ / 10); волна 45 моделей — 1,08 ₽
PRICE_LOW_RUB = 1.1
ROOMS = ('bedroom',)        # спрос по слотам: комнаты со сборщиком наборов и банком; прихожая — по `--hall-bank` (T-72 — реестр)
WAVES_FILE = os.environ.get('MESH_WAVE_MANUAL') or os.path.expanduser('~/scout-scenes/wave-manual.json')   # = salad/wave_cap.PATH
RESERVE_FILE = os.environ.get('ROOM_MESH_RESERVE') or os.path.expanduser('~/scout-scenes/room-mesh-reserve.jsonl')
WANT_FILE = os.path.join(HERE, 'rules', 'room-mesh-want.json')
LIVING = ('living', 'living_room', 'гостиная')


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


def ledger(total: float = BUDGET_RUB, since: str = BUDGET_SINCE, waves_path: str = WAVES_FILE,
           reserve_path: str = RESERVE_FILE, load=snap_info) -> dict:
    """Остаток денег мешей комнат = total − факт закрытых волн комнат − потолок открытых − резерв снимков вне волны.
    Волны гостиной (снимок без `room` или `room` гостиной) не в счёт; нечитаемый снимок — в счёт (деньги важнее)."""
    t0 = _ts(since)
    rows, spent, held, reserved, fps = [], 0.0, 0.0, 0.0, set()
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


def hall_want(bank: list, strategy) -> list:
    """Банк `compose_hall` → товары без меша (`mesh_need`) в ролях с мешем (зеркало — плоскость, не меш), с вариантами."""
    out: dict = {}
    for s in bank:
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


def want_rows(skus: list, room: str, fetch, missing_after: int = 1) -> dict:
    """sku → факты для решения: карточка комнаты, фото текущей ревизии и его вердикт, фото уже сделанных мешей. SELECT."""
    import preprocess as PRE
    if not skus:
        return {}
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
      left join photo_assessment a on a.source_sha = pc.source_sha and a.assessor_version = '{PRE.ASSESSOR_VERSION}'""")
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


def evaluate(e: dict, F: dict, sibs: list, room: str, job_of) -> dict:
    """Строка спроса → {state, reason, job?, photo}. F — want_rows по sku и его вариантам семьи; sibs — варианты семьи."""
    me = F.get(e['sku'])
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


def want_demand(room: str, entries: list, price: float, fetch=None) -> dict:
    """Спрос по вариантам витрины: строки → решения → задания по приоритету (без потолка — его режет commit/dry)."""
    import room_catalog as RC
    import room_mesh_jobs as RMJ
    fetch = fetch or __import__('catalog_items').fetch
    mh = int(RC.rules().get('missing_hide_after', 1))
    E0 = [e for e in entries if e['room'] == room]
    if not E0:
        raise DemandError(f'спрос по вариантам: для комнаты {room} строк нет')
    # вариант семьи мешей (другой цвет) → представитель: меш один на семью (как в спросе по слотам)
    r0 = want_rows(sorted({e['sku'] for e in E0}), room, fetch, mh)
    E1 = []
    for e in E0:
        rep = (r0.get(e['sku']) or {}).get('rep')
        if rep and rep != e['sku']:
            e = dict(e, sku=rep, shown=list(e.get('shown') or []) + [e['sku']],
                     note='; '.join(x for x in (e.get('note'), f"показан вариант {e['sku']} → представитель") if x))
        E1.append(e)
    E = merge_want(E1)
    regen = [e['sku'] for e in E if e['why'] == 'regen']
    base = want_rows([e['sku'] for e in E], room, fetch, mh)
    reps = sorted({(base.get(s) or {}).get('rep') or s for s in regen})
    S = siblings_of(reps, fetch)
    sib_all = sorted({x for v in S.values() for x in v} | set(reps))
    F = dict(base, **{k: v for k, v in want_rows(sib_all, room, fetch, mh).items() if k not in base})
    out, jobs, taken = [], [], set()
    for e in E:
        rep = (F.get(e['sku']) or {}).get('rep') or e['sku']
        sibs = [x for x in S.get(rep, []) + ([rep] if rep != e['sku'] else []) if x != e['sku']]
        r = evaluate(e, F, sibs, room, RMJ.job_of)
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

    # ---- общий остаток денег (T-20261106-75): журнал волн + резерв снимков, два запуска подряд ≤ потолка
    import shutil
    import tempfile
    import time as _t
    tmpd = tempfile.mkdtemp(prefix='rmd-selftest-')
    since = '2026-11-05T18:56:00+00:00'
    t0 = _ts(since)

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
    shutil.rmtree(tmpd, ignore_errors=True)

    # ---- спрос по вариантам витрины
    import asset_strategy as AS
    hb = [{'style': 'сканди', 'tier': 'комфорт', 'mesh_need': ['1:a', '1:z', '1:m'],
           'items': {'вешалка': {'mid': 1, 'eid': 'a'}, 'зеркало': {'mid': 1, 'eid': 'z'}, 'обувница': {'mid': 1, 'eid': 'm'}}},
          {'style': 'лофт', 'tier': 'комфорт', 'mesh_need': ['1:a'], 'items': {'вешалка': {'mid': 1, 'eid': 'a'}}}]
    H = hall_want(hb, AS.strategy)
    ok('прихожая из банка: без меша и в ролях с мешем (зеркало — плоскость), товар двух вариантов — одна строка',
       sorted(h['sku'] for h in H) == ['1:a', '1:m'] and next(h for h in H if h['sku'] == '1:a')['variants'] == ['сканди комфорт', 'лофт комфорт'])
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
        print(ledger_text(ledger(total, since)))
        return 0
    if '--ledger' in a:
        L = ledger(total, since)
        print(ledger_text(L))
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
            p = arg('--want') or WANT_FILE
            entries += json.load(open(p, encoding='utf-8'))['items']
        if '--hall-bank' in a:
            hb = arg('--hall-bank')
            if not hb or not os.path.exists(hb):
                raise DemandError(f'банк прихожей не найден: {hb!r}')
            entries += hall_want(json.load(open(hb, encoding='utf-8')), AS.strategy)
        L = ledger(total, since)
        W = want_demand(room, entries, price)
    except (DemandError, OSError, KeyError, ValueError) as e:
        print(f'ОТКАЗ: {e}', flush=True)
        return 2
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
