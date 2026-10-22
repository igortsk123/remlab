#!/usr/bin/env python3
"""ОЖИДАНИЕ ГОТОВНОСТИ КАНДИДАТА БАНКА И СПРОС МЕШЕЙ `bank_candidate` (conv-14 шаг 2, владелец 22.10 TG 895, разбор Codex § 3).

ЗАЧЕМ. Ночью собирается кандидат банка (`sets3.next.json`); ячейка `(band, style, tier)` подменяет живую, только когда у
каждого ПОКАЗЫВАЕМОГО товара готово представление по своей стратегии (`render_strategy.asset_ready`: меш, вырезка, плоское).
Неготовая ячейка ждёт, а её товары встают в очередь мешей. Ни `demo_band` (дефицит вчерашнего демо), ни `mesh_scheduler`
(живой `sets3.json`) кандидата не видят — отсюда отдельный источник спроса.

СОСТОЯНИЕ (`~/scout-scenes/bank-pending.json`, env `BANK_PENDING`; запись атомарная, переживает перезапуск). По ячейке:
`set_id` (1:1 с ячейкой, `set_identity`), `candidate_hash` (состав показываемых товаров), `since` (с какого времени ждёт ЭТОТ
кандидат), `missing` (чего не хватает и с какого времени), `status` ready|wait|invalid, `invalid` (почему). Кандидат сменился
(другой hash) — запись заменяется, спрос прежнего кандидата снимается сам: спрос считается только из текущих записей. Иначе
каждая новая сборка меняла бы цель до готовности, и деньги уходили бы на меши брошенных вариантов (Codex).

НЕ ЖДАТЬ БЕСКОНЕЧНО: меш `rejected`/`quarantine`, задание `failed_terminal`, нет высоты (`h_cm`), не мешепригоден
(`mesh_required=false`) → ячейка `invalid`, товар — в чёрный список (`blacklist`) для пересборки ячейки. Карантин — не готовность.
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

import set_identity as SID  # noqa: E402

RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')
STATE = os.path.expanduser(os.environ.get('BANK_PENDING', '~/scout-scenes/bank-pending.json'))
CANDIDATE = os.path.join(HERE, 'sets3.next.json')
LIVE = os.path.join(HERE, 'sets3.json')
DEMO_DATA = os.path.expanduser(os.environ.get('DEMO_DATA', '~/scout-scenes/flat215-demo/demo-data.json'))
DEAD_MESH = ('rejected', 'quarantine')


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


def candidate_hash(s: dict) -> str:
    return hashlib.sha256(json.dumps(sorted(shown(s)), ensure_ascii=False).encode()).hexdigest()[:12]


def base_role(slot: str) -> str:
    parts = slot.split(' ')
    return ' '.join(parts[:-1]) if parts[-1].isdigit() else slot


class Facts:
    """Факты о товарах (каталог, меши, стратегии) — подменяемые в тестах. `prod[sku]` = {'role', 'status', 'eligible',
    'has_h', 'rep'}; `failed` — представители с заданием failed_terminal; `ready(sku)` и `strategy(role)` — функции."""

    def __init__(self, prod: dict, failed: set, ready, strategy):
        self.prod, self.failed, self.ready, self.strategy = prod, failed, ready, strategy

    def rep(self, sku: str) -> str:
        return (self.prod.get(sku) or {}).get('rep') or sku


def classify(role: str, sku: str, F: Facts) -> tuple[str, str | None]:
    """→ ('ready'|'wait'|'wait_other'|'invalid', причина). `wait` — нужен меш (спрос); `wait_other` — вырезка/плоское ещё не
    готовы, мешей не просим (их готовит свой конвейер)."""
    if F.ready(sku) or F.ready(F.rep(sku)):
        return 'ready', None
    if F.strategy(base_role(role)) != 'mesh':
        return 'wait_other', None
    p = F.prod.get(sku)
    if not p:
        return 'invalid', 'нет в каталоге'
    if not p.get('has_h'):
        return 'invalid', 'нет высоты (h_cm) — меш не заказать'
    rep = F.prod.get(F.rep(sku)) or p
    if rep.get('status') in DEAD_MESH:
        return 'invalid', f"меш {rep['status']}"
    if F.rep(sku) in F.failed:
        return 'invalid', 'генерация failed_terminal'
    if not rep.get('eligible'):
        return 'invalid', 'не мешепригоден (mesh_required=false)'
    return 'wait', None


def update(state: dict, cand: list, F: Facts, now: float | None = None) -> tuple[dict, dict]:
    """Чистое ядро: новое состояние по кандидату и факты. → (state, diff{'new','replaced','kept','dropped'})."""
    now = round(time.time() if now is None else now)
    old = state.get('cells') or {}
    cells, diff = {}, {'new': 0, 'replaced': 0, 'kept': 0, 'dropped': 0}
    black = dict(state.get('blacklist') or {})
    for s in cand:
        k, h = key(s), candidate_hash(s)
        prev = old.get(k)
        same = bool(prev) and prev.get('candidate_hash') == h
        diff['kept' if same else 'replaced' if prev else 'new'] += 1
        was = ((prev or {}).get('missing') or {}) if same else {}
        missing, invalid, waits = {}, [], 0
        for role, sku in shown(s):
            st, why = classify(role, sku, F)
            if st == 'ready':
                continue
            if st == 'invalid':
                invalid.append({'role': role, 'sku': sku, 'why': why})
                b = black.setdefault(sku, {'why': why, 'at': now, 'cells': []})
                if k not in b['cells']:
                    b['cells'].append(k)
                continue
            missing[sku] = {'role': role, 'need': st, 'rep': F.rep(sku), 'since': (was.get(sku) or {}).get('since', now)}
            waits += st == 'wait'
        cells[k] = {'set_id': s.get('set_id'), 'candidate_hash': h, 'since': prev['since'] if same else now,
                    'status': 'invalid' if invalid else 'wait' if missing else 'ready', 'total': len(shown(s)),
                    'missing': missing, 'mesh_missing': waits, 'invalid': invalid}
    diff['dropped'] = sum(1 for k in old if k not in cells)
    return {'version': 1, 'updated_at': now, 'cells': cells, 'blacklist': black}, diff


def demand(state: dict, gone_cells: set, demo_cells: set) -> list[dict]:
    """Спрос мешей по состоянию: ячейки `wait` с недостающими мешами, порядок — gone → меньше недостающего → демо → дольше
    ждёт; в ячейке — по порядку ролей; без повторов по представителю семейства. → [{'sku': представитель, 'cell', 'why'}]."""
    order = sorted(((k, c) for k, c in (state.get('cells') or {}).items() if c.get('status') == 'wait' and c.get('mesh_missing')),
                   key=lambda kc: (kc[0] not in gone_cells, kc[1]['mesh_missing'], kc[0] not in demo_cells, kc[1]['since'], kc[0]))
    out, seen = [], set()
    for k, c in order:
        why = 'замена ушедшего' if k in gone_cells else 'ячейка демо' if k in demo_cells else 'кандидат банка'
        for sku, m in c['missing'].items():
            if m.get('need') == 'wait' and m['rep'] not in seen:
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
    from mesh_queue import db
    import render_strategy as RS
    prod = {}
    for r in db("select shop_mid||':'||external_id, coalesce(cat_role,''), coalesce(mesh_status,'none'), "
                "coalesce(mesh_required,false)::text, (h_cm is not null)::text, "
                "coalesce(mesh_family_rep, shop_mid||':'||external_id) from products"):
        if len(r) == 6:
            prod[r[0]] = {'role': r[1], 'status': r[2], 'eligible': r[3] == 'true', 'has_h': r[4] == 'true', 'rep': r[5]}
    failed = {r[0] for r in db("select distinct sku from mesh_jobs where status = 'failed_terminal'") if r and r[0]}
    return Facts(prod, failed, RS.asset_ready, RS.strategy)


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
    cells = state['cells'].values()
    st = collections.Counter(c['status'] for c in cells)
    items = [(r, s) for c in cand for r, s in shown(c)]
    uniq = {s for _, s in items}
    ready_u = {s for s in uniq if F.ready(s) or F.ready(F.rep(s))}
    need = collections.Counter(m['need'] for c in cells for m in c['missing'].values())
    why = collections.Counter(i['why'] for c in cells for i in c['invalid'])
    print(f'[bank_pending] кандидат {os.path.basename(cand_path)}: ячеек {len(cand)} — готовы {st["ready"]}, ждут {st["wait"]}, '
          f'недействительны {st["invalid"]}; смена кандидатов: {diff}')
    print(f'  показываемых позиций {len(items)}, разных товаров {len(uniq)}, из них готовы {len(ready_u)}; ждут меш {need["wait"]}, '
          f'ждут вырезку/плоское {need["wait_other"]}; причины недействительности: {dict(why) or "нет"}')
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

    def S(band, style, items, sid='set-x', tier='эконом'):
        return {'band': band, 'style': style, 'tier': tier, 'set_id': sid,
                'items': {r: {'mid': 1, 'eid': e} for r, e in items.items()}}
    prod = {f'1:{e}': {'role': r, 'status': 'none', 'eligible': True, 'has_h': True, 'rep': f'1:{e}'}
            for e, r in (('d1', 'диван'), ('d2', 'диван'), ('k1', 'кресло'), ('k2', 'кресло'), ('t1', 'столик'),
                         ('t2', 'столик'), ('p1', 'подушка'), ('v1', 'диван'), ('v2', 'диван'))}
    prod['1:v2']['rep'] = '1:v1'                                   # цвет той же модели — один меш
    prod['1:k2']['has_h'] = False                                  # кресло без высоты (как 93965)
    prod['1:t2']['status'] = 'quarantine'
    ready = {'1:d1', '1:t1'}
    strat = lambda role: 'cutout' if role == 'подушка' else 'mesh'  # noqa: E731
    F = Facts(prod, failed=set(), ready=lambda s: s in ready, strategy=strat)
    A = S('14-16', 'сканди', {'диван': 'd1', 'столик': 't1'}, 'set-a')                 # всё готово
    B = S('14-16', 'лофт', {'диван': 'd2', 'столик': 't1', 'подушка': 'p1'}, 'set-b')  # 1 меш + вырезка
    C = S('17-20', 'лофт', {'диван': 'v1', 'кресло': 'd2', 'столик': 't1'}, 'set-c')   # 2 меша, d2 общий с B
    D = S('17-20', 'сканди', {'диван': 'd1', 'кресло': 'k2'}, 'set-d')                 # кресло без высоты
    E = S('21-25', 'сканди', {'диван': 'v2', 'столик': 't2'}, 'set-e')                 # столик в карантине
    st, diff = update({}, [A, B, C, D, E], F, now=100)
    c = st['cells']
    ok('готовая ячейка — ready; ждущая — wait с недостающим и временем', c['14-16|сканди|эконом']['status'] == 'ready'
       and c['14-16|лофт|эконом']['status'] == 'wait' and c['14-16|лофт|эконом']['missing']['1:d2']['since'] == 100)
    ok('вырезка не готова — ждёт, но мешей не просит', c['14-16|лофт|эконом']['missing']['1:p1']['need'] == 'wait_other'
       and c['14-16|лофт|эконом']['mesh_missing'] == 1)
    ok('нет высоты и карантин — ячейка invalid, товары в чёрном списке',
       c['17-20|сканди|эконом']['status'] == 'invalid' and c['21-25|сканди|эконом']['status'] == 'invalid'
       and set(st['blacklist']) == {'1:k2', '1:t2'} and 'высоты' in st['blacklist']['1:k2']['why'], st['blacklist'])
    ok('смена кандидатов: все новые', diff == {'new': 5, 'replaced': 0, 'kept': 0, 'dropped': 0}, diff)
    # перезапуск: тот же кандидат — время ожидания сохраняется; сменился состав — запись заменена, спрос прежнего снят
    B2 = S('14-16', 'лофт', {'диван': 'k1', 'столик': 't1'}, 'set-b')
    st2, diff2 = update(json.loads(json.dumps(st)), [A, B2, C, D, E], F, now=200)
    ok('тот же кандидат после перезапуска — since прежний', st2['cells']['17-20|лофт|эконом']['since'] == 100
       and st2['cells']['17-20|лофт|эконом']['missing']['1:v1']['since'] == 100)
    ok('кандидат сменился (другой hash) — запись заменена, ожидание с новой ночи, d2 из спроса ячейки ушёл',
       st2['cells']['14-16|лофт|эконом']['since'] == 200 and '1:d2' not in st2['cells']['14-16|лофт|эконом']['missing']
       and diff2['replaced'] == 1 and diff2['kept'] == 4, diff2)
    # приоритет: gone → меньше недостающего → демо → дольше ждёт; дедуп по представителю семейства
    st3 = {'cells': {
        'g|1|1': {'status': 'wait', 'mesh_missing': 3, 'since': 50, 'missing': {
            '1:x1': {'need': 'wait', 'rep': '1:x1'}, '1:x2': {'need': 'wait', 'rep': '1:x2'}, '1:x3': {'need': 'wait', 'rep': '1:x3'}}},
        'm|1|1': {'status': 'wait', 'mesh_missing': 1, 'since': 90, 'missing': {'1:y1': {'need': 'wait', 'rep': '1:y1'}}},
        'd|1|1': {'status': 'wait', 'mesh_missing': 2, 'since': 80, 'missing': {
            '1:z1': {'need': 'wait', 'rep': '1:z1'}, '1:x2v': {'need': 'wait', 'rep': '1:x2'}}},
        'o|1|1': {'status': 'wait', 'mesh_missing': 2, 'since': 10, 'missing': {
            '1:w1': {'need': 'wait', 'rep': '1:w1'}, '1:w2': {'need': 'wait_other', 'rep': '1:w2'}}},
        'i|1|1': {'status': 'invalid', 'mesh_missing': 1, 'since': 1, 'missing': {'1:q': {'need': 'wait', 'rep': '1:q'}}}}}
    got = [d['sku'] for d in demand(st3, gone_cells={'g|1|1'}, demo_cells={'d|1|1'})]
    ok('порядок: замена gone → меньше недостающего → демо → дольше ждёт; invalid и вырезка — не в спросе; семейство один раз',
       got == ['1:x1', '1:x2', '1:x3', '1:y1', '1:z1', '1:w1'], got)
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
    bl = blocklist(prod, strat, st, no_height=True)
    ok('до сборки не пускаем (оба ключа): мешевая роль без высоты и чёрный список; вырезке высота не нужна',
       set(bl) == {'1:k2', '1:t2'}, bl)
    ok('по умолчанию — только чёрный список состояния, «нет высоты» выключено',
       set(blocklist(prod, strat, st)) == {'1:k2', '1:t2'} and set(blocklist(prod, strat, {})) == set())
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
