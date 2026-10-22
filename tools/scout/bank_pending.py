#!/usr/bin/env python3
"""ОЖИДАНИЕ ГОТОВНОСТИ КАНДИДАТА БАНКА И СПРОС МЕШЕЙ `bank_candidate` (conv-14 шаг 2, владелец 22.10 TG 895, разбор Codex § 3).

ЗАЧЕМ. Ночью собирается кандидат банка (`sets3.next.json`); ячейка `(band, style, tier)` подменяет живую, только когда
каждый ПОКАЗЫВАЕМЫЙ товар готов к показу (`bank_ready.classify`, шаг 2.1: доступен, текущая ссылка, живое фото; мягкому —
больше ничего, ковру — обе стороны, мешу — гейт геометрии и готовый меш; глобальный `render_strategy.asset_ready` не трогаем).
Неготовая ячейка ждёт, а её товары встают в очередь мешей. Ни `demo_band` (дефицит вчерашнего демо), ни `mesh_scheduler`
(живой `sets3.json`) кандидата не видят — отсюда отдельный источник спроса.

СОСТОЯНИЕ (`~/scout-scenes/bank-pending.json`, env `BANK_PENDING`; запись атомарная, переживает перезапуск). По ячейке:
`set_id` (1:1 с ячейкой, `set_identity`), `candidate_hash` (полный состав: позиции и запасные — SKU, ссылка, фото, цена,
габариты, количество — плюс capsule/group/pair), `since` (с какого времени ждёт ЭТОТ кандидат), `missing` (чего не хватает, тип
ожидания и с какого времени), `status` — `ready` или худший тип позиции (`bank_ready.TYPES`). Кандидат сменился
(другой hash) — запись заменяется, спрос прежнего кандидата снимается сам: спрос считается только из текущих записей. Иначе
каждая новая сборка меняла бы цель до готовности, и деньги уходили бы на меши брошенных вариантов (Codex).

ТИПЫ ОЖИДАНИЯ (Codex 22.10 § 4, шаг 2.1) вместо одного `invalid`: `wait_asset` (ждём меш — спрос; карантин — ждёт решения),
`wait_catalog` (дыра каталога: высота, глубина, трансформер, обогащение, фото, ссылка — не брак), `redo` (переделка владельца —
своя очередь), `blocked_policy` (товар заменить: ушёл, `replace_needed`/`reject` журнала `mesh_decisions`, failed_terminal) →
чёрный список и пересборка ячейки, `legacy_unknown` (`rejected` без происхождения — не продвигать, не тратить, триаж).
ЧЁРНЫЙ СПИСОК ОЧИЩАЕТСЯ: каждую ночь его товары переоцениваются, перестал быть `blocked_policy` (исправили данные, перегон
удался, решение снято) — снимается. ЯЧЕЙКА С БЛОКОМ В СПРОСЕ ОСТАЁТСЯ: её прочие меши всё равно понадобятся пересобранной.
До сборки (`blocklist` → `compose_gates.admit`) отсеивается чёрный список (`compose_reject_blacklist`); отсев мешевых ролей
без высоты (`compose_no_height`) — отдельным ключом, выключен: 2740 таких товаров — вероятно, дыра в данных о высоте.

СПРОС. Порядок ячеек: замена живого `gone` → меньше недостающего → ячейка в вариантах демо → дольше ждёт. В ячейке — по
порядку ролей, без повторов по представителю семейства меша (`mesh_family_rep`: один меш на модель). Потолок очереди demo
(`rules/demo-swap.json:mesh_queue_max`, 150) — ОБЩИЙ с `demo_band` после дедупликации (`combine`); денежный предел — `wave_guard`
как есть. Включение — `rules/bank-candidate.json:enabled` (по умолчанию выключено, шаги 3–4 плана — селектор и подмена).

  ~/venvs/scout/bin/python bank_pending.py --dry [--candidate sets3.next.json]   # что попало бы в спрос, без записи
  ~/venvs/scout/bin/python bank_pending.py --update                               # обновить состояние (ночной шаг, позже)
  python3 bank_pending.py --selftest
"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bank_ready as BR  # noqa: E402
import set_identity as SID  # noqa: E402

RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')
STATE = os.path.expanduser(os.environ.get('BANK_PENDING', '~/scout-scenes/bank-pending.json'))
CANDIDATE = os.path.join(HERE, 'sets3.next.json')
LIVE = os.path.join(HERE, 'sets3.json')
DEMO_DATA = os.path.expanduser(os.environ.get('DEMO_DATA', '~/scout-scenes/flat215-demo/demo-data.json'))


def rules() -> dict:
    try:
        return json.load(open(RULES_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def enabled() -> bool:
    return bool(rules().get('enabled'))


def sku_of(it: dict | None) -> str | None:
    return f"{it.get('mid')}:{it.get('eid')}" if it and it.get('eid') else None


def key(s: dict) -> str:
    return '|'.join(str(x) for x in SID.cell(s))


def shown(s: dict) -> list[tuple[str, str]]:
    """Показываемые позиции ячейки (роль, sku) в порядке банка — то, что обязано быть готово к подмене."""
    return [(role, sku_of(it)) for role, it in (s.get('items') or {}).items() if sku_of(it)]


HASH_FIELDS = ('mid', 'eid', 'url', 'img', 'price', 'w', 'd', 'h', 'dia', 'qty')


def _pos(it) -> dict | None:
    return {k: it.get(k) for k in HASH_FIELDS} if isinstance(it, dict) else None


def candidate_hash(s: dict) -> str:
    """Отпечаток ПОЛНОГО состава ячейки (Codex § 4): позиции и запасные (SKU, ссылка, фото, цена, габариты, количество), capsule,
    group, pair. Сменилось что-то из этого — это другой кандидат, ожидание считается заново."""
    body = {'items': {r: _pos(it) for r, it in sorted((s.get('items') or {}).items())},
            'alternates': {r: [_pos(a) for a in (lst or [])] for r, lst in sorted((s.get('alternates') or {}).items())}
            if isinstance(s.get('alternates'), dict) else s.get('alternates'),
            'capsule': s.get('capsule'), 'group': s.get('group'), 'pair': s.get('pair')}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


base_role = BR.base_role
Facts = BR.Facts


def classify(role: str, sku: str, F: Facts, item: dict | None = None) -> tuple[str, str | None, str | None]:
    """→ (тип, причина, need) — `bank_ready.classify`: 'ready' или тип ожидания; need='mesh' — в спрос мешей."""
    return BR.classify(role, sku, item, F)


def cell_status(missing: dict) -> str:
    return max((m['type'] for m in missing.values()), key=BR.SEVERITY.get, default='ready')


def update(state: dict, cand: list, F: Facts, now: float | None = None) -> tuple[dict, dict]:
    """Чистое ядро: новое состояние по кандидату и факты. → (state, diff{'new','replaced','kept','dropped'})."""
    now = round(time.time() if now is None else now)
    old = state.get('cells') or {}
    cells, diff = {}, {'new': 0, 'replaced': 0, 'kept': 0, 'dropped': 0, 'cleared': 0}
    black = {}
    for s in cand:
        k, h = key(s), candidate_hash(s)
        prev = old.get(k)
        same = bool(prev) and prev.get('candidate_hash') == h
        diff['kept' if same else 'replaced' if prev else 'new'] += 1
        was = ((prev or {}).get('missing') or {}) if same else {}
        missing = {}
        for role, sku in shown(s):
            t, why, need = classify(role, sku, F, (s.get('items') or {}).get(role))
            if t == 'ready':
                continue
            missing[sku] = {'role': role, 'type': t, 'why': why, 'need': need, 'rep': F.rep(sku),
                            'since': (was.get(sku) or {}).get('since', now)}
            if t == 'blocked_policy':
                b = black.setdefault(sku, {'role': role, 'why': why, 'at': ((state.get('blacklist') or {}).get(sku) or {})
                                           .get('at', now), 'cells': []})
                b['cells'].append(k)
        cells[k] = {'set_id': s.get('set_id'), 'candidate_hash': h, 'since': prev['since'] if same else now,
                    'status': cell_status(missing), 'total': len(shown(s)), 'missing': missing,
                    'mesh_missing': sum(1 for m in missing.values() if m['need'] == 'mesh')}
    # ОЧИЩАЕМЫЙ ЧЁРНЫЙ СПИСОК: прежние записи вне кандидата переоцениваем; перестал быть блоком — снимаем
    for sku, b in (state.get('blacklist') or {}).items():
        if sku in black:
            continue
        t, why, _ = classify(b.get('role') or '', sku, F, None)
        if t == 'blocked_policy':
            black[sku] = {**b, 'why': why, 'cells': []}
        else:
            diff['cleared'] += 1
    diff['dropped'] = sum(1 for k in old if k not in cells)
    return {'version': 2, 'updated_at': now, 'cells': cells, 'blacklist': black}, diff


def demand(state: dict, gone_cells: set, demo_cells: set) -> list[dict]:
    """Спрос мешей по состоянию: недостающие меши (`need == mesh`) ВСЕХ неготовых ячеек — с блоком тоже (Codex § 4: прочие меши
    пересобранной ячейке понадобятся); порядок — gone → меньше недостающего (всего, не только мешей: ячейка с блоком уходит
    дальше) → демо → дольше ждёт; в ячейке — по порядку ролей; без повторов по представителю семейства."""
    order = sorted(((k, c) for k, c in (state.get('cells') or {}).items() if c.get('mesh_missing')),
                   key=lambda kc: (kc[0] not in gone_cells, len(kc[1]['missing']), kc[0] not in demo_cells, kc[1]['since'], kc[0]))
    out, seen = [], set()
    for k, c in order:
        why = 'замена ушедшего' if k in gone_cells else 'ячейка демо' if k in demo_cells else 'кандидат банка'
        for sku, m in c['missing'].items():
            if m.get('need') == 'mesh' and m['rep'] not in seen:
                seen.add(m['rep'])
                out.append({'sku': m['rep'], 'cell': k, 'why': f"{why}: недостаёт {c['mesh_missing']}"})
    return out


def combine(band: list, bank: list, cap: int, reserve: int = 0) -> tuple[list, list]:
    """Общий потолок очереди demo для `demo_band` и `bank_candidate` ПОСЛЕ дедупликации по представителю: повтор в спросе
    банка места не занимает. `reserve` — сколько мест держать за банком (0 — сперва лента, как было до шага 2). → (лента, банк)."""
    bank_u = [s for s in dict.fromkeys(bank) if s not in set(band)]
    keep_bank = min(len(bank_u), max(0, reserve), cap)
    band_n = min(len(band), cap - keep_bank)
    band_k = band[:band_n]
    return band_k, bank_u[:cap - band_n]


def blocklist(prod: dict, strategy, state: dict | None = None, no_height: bool = False, reject: bool = True) -> dict:
    """Не пускать в сборку кандидата (ДО сборки, `compose_gates.admit`). `reject` — чёрный список состояния (меш брак/
    карантин/failed_terminal); `no_height` — мешевая роль без высоты (меш не заказать). → {sku: причина}.
    «Нет высоты» по умолчанию ВЫКЛЮЧЕНО (ведущий 22.10): по каталогу это 2740 товаров — похоже на дыру в данных о высоте,
    а не на свойство товаров; резать по ней каталог нельзя, пока она не разобрана."""
    out = {}
    if no_height:
        out = {s: 'нет высоты (h_cm) — меш не заказать' for s, p in prod.items()
               if not p.get('has_h') and p.get('role') and strategy(p['role']) == 'mesh'}
    if reject:
        for s, b in ((state or {}).get('blacklist') or {}).items():
            out.setdefault(s, b.get('why') or 'чёрный список кандидата')
    return out


# ——— ввод-вывод (база, файлы) ———

def load_facts() -> Facts:
    return BR.load_facts()


def load_state() -> dict:
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # битое состояние — не «всё ждёт с нуля молча»: громко, и начинаем заново (ожидание считается с этой ночи)
        print(f'WARN:bank_pending: {STATE} не читается ({type(e).__name__}) — состояние с нуля', flush=True)
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)


def live_context(live: list) -> tuple[set, set]:
    """(ячейки живого банка с ушедшим товаром, ячейки вариантов опубликованного демо `setN`)."""
    gone = {key(s) for s in live if any((it or {}).get('_gone') for it in (s.get('items') or {}).values())}
    demo = set()
    try:
        for v in json.load(open(DEMO_DATA, encoding='utf-8')).get('variants') or []:
            n = int(str(v.get('id', '')).removeprefix('set') or 0)
            if 1 <= n <= len(live):
                demo.add(key(live[n - 1]))
    except (OSError, ValueError) as e:
        print(f'WARN:bank_pending: демо не прочитано ({type(e).__name__}) — без яруса «ячейка демо»', flush=True)
    return gone, demo


def queue_skus() -> list:
    """Спрос `bank_candidate` для профиля demo (`mesh_priority.demo_rank`) — по СОХРАНЁННОМУ состоянию; выключен — пусто."""
    if not enabled():
        return []
    gone, demo = live_context(json.load(open(LIVE, encoding='utf-8')))
    return [d['sku'] for d in demand(load_state(), gone, demo)]


def run(cand_path: str, write: bool) -> int:
    import collections
    cand = json.load(open(cand_path, encoding='utf-8'))
    live = json.load(open(LIVE, encoding='utf-8'))
    F = load_facts()
    state, diff = update(load_state(), cand, F)
    gone, demo = live_context(live)
    dem = demand(state, gone, demo)
    cells = list(state['cells'].values())
    st = collections.Counter(c['status'] for c in cells)
    items = [(r, s) for c in cand for r, s in shown(c)]
    uniq = {s for _, s in items}
    pos = [m for c in cells for m in c['missing'].values()]
    by_type = collections.Counter(m['type'] for m in pos)
    sku_type = {}
    for m_c in cells:
        for sku, m in m_c['missing'].items():
            sku_type.setdefault(sku, m['type'])
    print(f'[bank_pending] кандидат {os.path.basename(cand_path)}: ячеек {len(cand)} — '
          + ', '.join(f'{t} {st[t]}' for t in ('ready',) + BR.TYPES) + f'; смена кандидатов: {diff}')
    print(f'  показываемых позиций {len(items)}, разных товаров {len(uniq)}, из них не готовы {len(sku_type)}; '
          f'неготовых позиций по типам: {dict(by_type)}; разных товаров по типам: {dict(collections.Counter(sku_type.values()))}')
    for t in BR.TYPES:
        why = collections.Counter(f"{m['why']} [{base_role(m['role'])}]" for m in pos if m['type'] == t)
        if why:
            print(f'    {t}: ' + '; '.join(f'{w} — {n}' for w, n in why.most_common(8)))
    fam = {d['sku'] for d in dem}
    print(f'  спрос мешей bank_candidate: {len(dem)} заданий = {len(fam)} семейств (представителей); по причинам: '
          f'{dict(collections.Counter(d["why"].split(":")[0] for d in dem))}; чёрный список {len(state["blacklist"])}')
    print(f'  включён в очередь demo: {"да" if enabled() else "нет (rules/bank-candidate.json:enabled=false)"}')
    if write:
        save_state(state)
        print(f'[bank_pending] состояние → {STATE}')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra='') -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    def S(band, style, items, sid='set-x', tier='эконом', **extra):
        return {'band': band, 'style': style, 'tier': tier, 'set_id': sid,
                'items': {r: {'mid': 1, 'eid': e, 'url': f'u/1:{e}'} for r, e in items.items()}, **extra}

    def P(role, **k):
        return {'role': role, 'status': 'none', 'eligible': True, 'rep': None, 'w': 100, 'd': 60, 'h': 80, 'dia': None,
                'has_h': k.get('h', 80) is not None, 'tr': False, 'proven': False, **k}
    prod = {f'1:{e}': P(r) for e, r in (('d1', 'диван'), ('d2', 'диван'), ('k1', 'кресло'), ('t1', 'столик'),
                                        ('t2', 'столик'), ('p1', 'подушка'), ('v1', 'диван'), ('v2', 'диван'))}
    prod['1:k2'] = P('кресло', h=None)                             # кресло без высоты (как 93965) — дыра каталога, не брак
    prod['1:v2']['rep'] = '1:v1'                                   # цвет той же модели — один меш
    media = {s: {'state': 'available', 'url': f'u/{s}', 'img': f'i/{s}'} for s in prod}
    strat = lambda role: 'cutout' if role == 'подушка' else 'mesh'  # noqa: E731
    dec = {'1:t2': {'decision': 'replace_needed'}}
    F = Facts(prod, failed=set(), strategy=strat, media=media.get, mesh_ok={'1:d1', '1:t1'}, decisions=dec)
    A = S('14-16', 'сканди', {'диван': 'd1', 'столик': 't1'}, 'set-a')                 # всё готово
    B = S('14-16', 'лофт', {'диван': 'd2', 'столик': 't1', 'подушка': 'p1'}, 'set-b')  # 1 меш; подушка готова без маски
    C = S('17-20', 'лофт', {'диван': 'v1', 'кресло': 'd2', 'столик': 't1'}, 'set-c')   # 2 меша, d2 общий с B
    D = S('17-20', 'сканди', {'диван': 'd1', 'кресло': 'k2'}, 'set-d')                 # кресло без высоты
    E = S('21-25', 'сканди', {'диван': 'v2', 'столик': 't2'}, 'set-e')                 # столик — заменить (журнал)
    st, diff = update({}, [A, B, C, D, E], F, now=100)
    c = st['cells']
    ok('готовая ячейка — ready; ждущая меш — wait_asset с недостающим и временем', c['14-16|сканди|эконом']['status'] == 'ready'
       and c['14-16|лофт|эконом']['status'] == 'wait_asset' and c['14-16|лофт|эконом']['missing']['1:d2']['since'] == 100)
    ok('подушка с живым фото и текущей ссылкой — готова без маски (не держит ячейку)',
       '1:p1' not in c['14-16|лофт|эконом']['missing'] and c['14-16|лофт|эконом']['mesh_missing'] == 1)
    ok('нет высоты — wait_catalog и НЕ в чёрном списке; replace_needed — blocked_policy и в чёрном списке',
       c['17-20|сканди|эконом']['status'] == 'wait_catalog' and c['21-25|сканди|эконом']['status'] == 'blocked_policy'
       and set(st['blacklist']) == {'1:t2'}, st['blacklist'])
    ok('смена кандидатов: все новые', diff == {'new': 5, 'replaced': 0, 'kept': 0, 'dropped': 0, 'cleared': 0}, diff)
    got = [d['sku'] for d in demand(st, set(), set())]
    ok('ячейка с блоком в спросе остаётся: меш дивана v1 (через цвет v2) просим', '1:v1' in got, got)
    # перезапуск: тот же кандидат — время ожидания сохраняется; сменился состав — запись заменена, спрос прежнего снят
    B2 = S('14-16', 'лофт', {'диван': 'k1', 'столик': 't1'}, 'set-b')
    st2, diff2 = update(json.loads(json.dumps(st)), [A, B2, C, D, E], F, now=200)
    ok('тот же кандидат после перезапуска — since прежний', st2['cells']['17-20|лофт|эконом']['since'] == 100
       and st2['cells']['17-20|лофт|эконом']['missing']['1:v1']['since'] == 100)
    ok('кандидат сменился (другой hash) — запись заменена, ожидание с новой ночи, d2 из спроса ячейки ушёл',
       st2['cells']['14-16|лофт|эконом']['since'] == 200 and '1:d2' not in st2['cells']['14-16|лофт|эконом']['missing']
       and diff2['replaced'] == 1 and diff2['kept'] == 4, diff2)
    # полный отпечаток: запасные, цена, ссылка, capsule — тоже состав
    h0 = candidate_hash(A)
    A_alt = {**A, 'alternates': {'диван': [{'mid': 1, 'eid': 'd2'}]}}
    A_price = json.loads(json.dumps(A))
    A_price['items']['диван']['price'] = 999
    ok('отпечаток: сменились запасные / цена / capsule — другой кандидат; тот же состав — тот же отпечаток',
       len({h0, candidate_hash(A_alt), candidate_hash(A_price), candidate_hash({**A, 'capsule': {'wood': 'дуб'}})}) == 4
       and candidate_hash(json.loads(json.dumps(A))) == h0)
    # очищаемый чёрный список: ячейку пересобрали без t2; пока решение действует — держим, сняли решение — снимаем
    E2 = S('21-25', 'сканди', {'диван': 'v2', 'столик': 't1'}, 'set-e')
    st3, d3 = update(json.loads(json.dumps(st)), [A, B, C, D, E2], F, now=300)
    ok('вне кандидата, решение действует — товар остаётся в чёрном списке', '1:t2' in st3['blacklist'] and d3['cleared'] == 0)
    F.decisions = {}
    st4, d4 = update(json.loads(json.dumps(st3)), [A, B, C, D, E2], F, now=400)
    ok('решение сняли (исправили данные / перегон) — запись чёрного списка снята', st4['blacklist'] == {} and d4['cleared'] == 1,
       (st4['blacklist'], d4))
    # приоритет: gone → меньше недостающего → демо → дольше ждёт; дедуп по представителю семейства
    M = lambda rep, need='mesh', t='wait_asset': {'need': need, 'rep': rep, 'type': t}  # noqa: E731
    st5 = {'cells': {
        'g|1|1': {'mesh_missing': 3, 'since': 50, 'missing': {'1:x1': M('1:x1'), '1:x2': M('1:x2'), '1:x3': M('1:x3')}},
        'm|1|1': {'mesh_missing': 1, 'since': 90, 'missing': {'1:y1': M('1:y1')}},
        'd|1|1': {'mesh_missing': 2, 'since': 80, 'missing': {'1:z1': M('1:z1'), '1:x2v': M('1:x2')}},
        'o|1|1': {'mesh_missing': 1, 'since': 10, 'missing': {'1:w1': M('1:w1'), '1:w2': M('1:w2', None, 'wait_catalog')}},
        'b|1|1': {'mesh_missing': 1, 'since': 1, 'missing': {'1:q': M('1:q'), '1:bb': M('1:bb', None, 'blocked_policy'),
                                                             '1:bc': M('1:bc', None, 'redo')}}}}
    got = [d['sku'] for d in demand(st5, gone_cells={'g|1|1'}, demo_cells={'d|1|1'})]
    ok('порядок: gone → меньше недостающего → демо → дольше ждёт; ячейка с блоком — последней, но в спросе; не-меш — нет',
       got == ['1:x1', '1:x2', '1:x3', '1:y1', '1:z1', '1:w1', '1:q'], got)
    # общий потолок 150 с demo_band после дедупликации
    band = [f'b{i}' for i in range(140)]
    bank = ['b3', 'b5'] + [f'k{i}' for i in range(30)]
    b, k = combine(band, bank, 150)
    ok('общий потолок: лента 140 + банк 10 = 150; повторы ленты в банке места не занимают',
       len(b) == 140 and len(k) == 10 and k[0] == 'k0' and len(b) + len(k) == 150, (len(b), k[:3]))
    b, k = combine([f'b{i}' for i in range(200)], bank, 150, reserve=40)
    ok('резерв за банком 40, а у банка 30 — банку 30, ленте 120', len(k) == 30 and len(b) == 120, (len(b), len(k)))
    b, k = combine([f'b{i}' for i in range(200)], [], 150, reserve=40)
    ok('резерв не простаивает: банку нечего — лента берёт все 150', len(b) == 150 and k == [])
    b, k = combine([f'b{i}' for i in range(200)], bank, 150, reserve=0)
    b2, k2 = combine([f'b{i}' for i in range(200)], bank, 150, reserve=int(rules().get('reserve') or 0))
    ok('голодание: при reserve=0 полная лента забирает все 150 — банку 0; резерв правил (> 0) банку места оставляет',
       len(k) == 0 and len(k2) > 0 and len(b2) + len(k2) == 150, (len(k), len(k2)))
    bl = blocklist(prod, strat, st, no_height=True)
    ok('до сборки не пускаем (оба ключа): мешевая роль без высоты и чёрный список; вырезке высота не нужна',
       set(bl) == {'1:k2', '1:t2'}, bl)
    ok('по умолчанию — только чёрный список состояния (blocked_policy), «нет высоты» выключено',
       set(blocklist(prod, strat, st)) == {'1:t2'} and set(blocklist(prod, strat, {})) == set())
    ok('чёрный список выключен — пусто', blocklist(prod, strat, st, reject=False) == {})
    print(f'bank_pending selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--dry' in sys.argv or '--update' in sys.argv:
        cp = sys.argv[sys.argv.index('--candidate') + 1] if '--candidate' in sys.argv else CANDIDATE
        sys.exit(run(cp, '--update' in sys.argv))
    print(__doc__)
