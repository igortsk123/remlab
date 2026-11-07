#!/usr/bin/env python3
"""НАСТОЯЩИЕ ШАГИ ЦЕПОЧКИ БАНКА КОМНАТЫ: подготовка и подмена (room-bank-01 этап Ж, T-20261107-04/3; ведущий 07.11 — вариант А).

ЗАЧЕМ. До этапа Ж `bank_prepare/bank_pending/bank_promote --room bedroom` были каркасом (`RoomBankSpec.skeleton`): ночь собирала
кандидата спальни и судила его всухую, а в живой банк ничего не шло — 12 ячеек шестого стиля (матрица профиля 72, живой 60)
не могли попасть в банк. Шаги гостиной для комнаты не годятся (пересборка `compose2`, медиа products, тиры и экзамен гостиной),
поэтому здесь — свои два шага, а `bank_pending` (ожидание и спрос) и `bank_refresh` (писатель) общие:

ПОДГОТОВКА `prepare` (`bank_prepare.py --room X`, флаг `rooms.<комната>.prepare_enabled`): кандидата НЕ пересобираем — его этой
  ночью уже собрал шаг `compose_<комната>` (атомарно) и судил `room_check_<комната>`. Здесь — проверка, что судить можно:
  кандидат читается, не старше `prepare_max_age_h` (12 ч), идентичность цела (`room_bootstrap.identity`: матрица профиля без
  стилей, пропущенных по правилу ядра, id от ячейки, происхождение), id живых ячеек = id тех же ячеек кандидата (иначе писатель
  упадёт на дрейфе); раскладка и состав (`check_bank`) — отчётом `WARN:`, ячейки судят сторожа. Затем паспорт кандидата
  (`bank_run.attest`) и отчёт с `pending_due` — как у гостиной; сбой — код 1, цепочка дальше не идёт.
ПОДМЕНА `promote` (`bank_promote.py --room X`, флаг `promote_enabled`): своя ночь (`bank_promote.chain`: отчёт prepare, паспорт,
  состояние `bank_pending` этой ночи по тем же байтам) → вердикт сторожей `room_guards.verdict` по ЭТИМ байтам (strict, модели,
  экзамен, связи, демо, доля ≤ 25 % живого; откаченный вручную тот же кандидат — `held`) → смешанный банк В ПОРЯДКЕ ЖИВОГО:
  прежние ячейки на своих номерах, новые (принятые сторожами) — в хвост в порядке матрицы (`room_guards.bank_order`);
  живые ячейки, которых нет в матрице профиля, — пометка `retired` (не удаляются; витрина их не берёт; `room_guards.retire_of`)
  → manifest в формате писателя (`room`, `run_id`, `live_sha`, `hybrid_sha`, `promoted`, `retired`, `cells[n, cell,
  candidate_hash, decision]`) → `bank_refresh --room X` пишет (вид журнала `add`, если есть новые).

  ~/venvs/scout/bin/python bank_prepare.py --room bedroom --run-id <номер> [--force]
  ~/venvs/scout/bin/python bank_promote.py --room bedroom --run-id <номер> [--force]
  python3 tests/test_room_bank_chain.py
"""
from __future__ import annotations

import collections
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bank_run as RUN  # noqa: E402
import room_bank_spec as RBS  # noqa: E402

MAX_AGE_H = 12
DECISION = {'promote': 'promote', 'waiting': 'wait', 'rejected': 'blocked', 'deferred': 'deferred', 'same': 'same'}


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


# ---------------------------------------------------------------- подготовка
def prepare(spec, run_id: str | None, force: bool = False, *, identity_fn=None, content_fn=None, attest=RUN.attest,
            save=None, now: float | None = None) -> int:
    """Шаг ночи «подготовка» комнаты. Зависимости подменяемые (тесты без базы). → код выхода."""
    import room_bootstrap as RBo
    R = spec.rules()
    run_id = run_id or RUN.new_run_id('manual')
    save = save or (lambda rep: RUN._atomic_json(spec.prepare_report, rep))
    out = spec.candidate
    print(f'bank_prepare: {spec.room}: run_id {run_id}', flush=True)
    rep = {'run_id': run_id, 'at': _now(), 'candidate': out, 'room': spec.room}
    if not (R.get('prepare_enabled') or force):
        print(f'bank_prepare: выключено (rules/bank-candidate.json:{spec.flag_ref("prepare_enabled")}=false) — кандидат не судится',
              flush=True)
        save({**rep, 'disabled': True})
        return 0

    def fail(msg: str, rc: int = 1) -> int:
        print(f'ERROR:bank_prepare: {spec.room}: {msg} — судить нельзя, цепочка дальше не идёт', flush=True)
        save({**rep, 'error': msg})
        return rc
    if os.path.realpath(out) == os.path.realpath(spec.live):
        return fail('кандидат — это живой банк', 2)
    try:
        raw = open(out, 'rb').read()
        cand = json.loads(raw)
    except (OSError, ValueError) as e:
        return fail(f'кандидат {out} не читается ({type(e).__name__}) — сборка compose_{spec.room} этой ночи не прошла?')
    age_h = ((time.time() if now is None else now) - os.path.getmtime(out)) / 3600
    lim = float(R.get('prepare_max_age_h') or MAX_AGE_H)
    if age_h > lim:
        return fail(f'кандидат собран {age_h:.0f} ч назад (предел {lim:.0f} ч) — не этой ночи')
    skipped = RBo.skipped_of(out)
    bad = (identity_fn or (lambda c: RBo.identity(spec.room, c, skipped)))(cand)
    if bad:
        rep['identity'] = bad[:10]
        return fail('идентичность кандидата: ' + '; '.join(bad[:3]))
    live = json.load(open(spec.live, encoding='utf-8')) if os.path.exists(spec.live) else []
    cid = {spec.key(s): s.get('set_id') for s in cand}
    drift = [spec.key(s) for s in live if spec.key(s) in cid and cid[spec.key(s)] != s.get('set_id')]
    if drift:
        rep['drift'] = drift[:10]
        return fail(f'id живых ячеек не равен id кандидата: {len(drift)} {drift[:3]}')
    content = (content_fn or (lambda c: _content(spec.room, c)))(cand)
    if content:
        print(f'WARN:bank_prepare: {spec.room}: кандидат целиком: {len(content)} замечаний ({"; ".join(content[:3])[:300]}) — '
              'это отчёт, ячейки судят сторожа (bank_promote)', flush=True)
    new = [k for k in cid if k not in {spec.key(s) for s in live}]
    try:
        rep['candidate_sha'] = attest(out, run_id)
    except OSError as e:
        return fail(f'паспорт кандидата не записан ({type(e).__name__}: {e})')
    rep.update(pending_due=True, cells=len(cand), live_cells=len(live), new_cells=len(new), skipped_styles=sorted(skipped),
               content=content[:20])
    save(rep)
    print(f'bank_prepare: {spec.room}: кандидат {len(cand)} ячеек (живой {len(live)}, новых {len(new)}) — паспорт ночи {run_id}; '
          'дальше ожидание (bank_pending) и подмена (bank_promote)', flush=True)
    print(f"DIGEST:кандидат банка {spec.room}: ячеек {len(cand)}, живой {len(live)}, новых {len(new)}"
          + (f", пропущены стили {', '.join(sorted(skipped))}" if skipped else '')
          + (f'; замечаний к целому {len(content)}' if content else ''), flush=True)
    return 0


def _content(room: str, cand: list) -> list[str]:
    import room_guards as RG
    M = RG.composer(room)
    return [p for p in M.check_bank(cand, M.rules(), M.tolerance()) if not str(p).startswith('~')]


# ---------------------------------------------------------------- подмена
def build(room: str, rep: dict, live: list, cand: list, want: set, cand_hash, pstate: dict | None = None) -> tuple[list, dict]:
    """Смешанный банк и тело manifest по вердикту сторожей. → (hybrid, поля manifest). Чистая функция.
    want — ключи ячеек матрицы профиля (`room_guards.cell_key`); cand_hash — `bank_pending.candidate_hash`."""
    import room_guards as RG
    take = list(rep.get('take') or [])
    hybrid = [copy.deepcopy(s) for s in RG.hybrid_of(live, cand, set(take), RG.bank_order(live, cand))]
    pos = {RG.cell_key(s): n for n, s in enumerate(hybrid, 1)}
    retire = [c for c in RG.retire_of(live, want) if c not in take]     # подменяемая ячейка — запись кандидата, не пометка
    for c in retire:
        hybrid[pos[c] - 1]['retired'] = True
    pc = (pstate or {}).get('cells') or {}
    cells, pending_new = [], []
    for r in rep.get('rows') or []:
        d = DECISION.get(r['decision'], r['decision'])
        if r['cell'] not in pos:
            pending_new.append({'cell': r['cell'], 'decision': d, 'reasons': r.get('reasons')})
            continue
        n = pos[r['cell']]
        src = hybrid[n - 1] if d == 'promote' else next((s for s in cand if RG.cell_key(s) == r['cell']), hybrid[n - 1])
        cells.append({'n': n, 'cell': r['cell'], 'set_id': r.get('set_id'), 'decision': d, 'kind': r.get('kind'),
                      'new': bool(r.get('new')), 'candidate_hash': cand_hash(src), 'reasons': r.get('reasons'),
                      'mesh_missing': (pc.get(r['cell']) or {}).get('mesh_missing')})
    promoted = sorted(pos[c] for c in take)
    fields = {'promoted': promoted, 'retired': sorted(pos[c] for c in retire),
              'new_cells': [n for n in promoted if n > len(live)], 'pending_new': pending_new, 'cap': rep.get('cap'),
              'decisions': dict(collections.Counter(c['decision'] for c in cells)), 'cells': cells}
    return hybrid, fields


def _hold(spec) -> dict:
    try:
        return {k: v['candidate_hash'] for k, v in
                (json.load(open(spec.refresh_paths()['hold'], encoding='utf-8')).get('cells') or {}).items()}
    except FileNotFoundError:
        return {}


def _atomic(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def promote(spec, run_id: str | None, force: bool = False, *, verdict_fn=None, want=None) -> int:
    """Шаг ночи «подмена» комнаты: вердикт сторожей → смешанный банк и manifest для `bank_refresh --room X`. Живой не пишет."""
    import bank_pending as BP
    import bank_promote as BPm
    import room_guards as RG
    import room_identity as RI
    import set_identity as SID
    R = spec.rules()
    if not (R.get('promote_enabled') or force):
        print(f'bank_promote: выключено (rules/bank-candidate.json:{spec.flag_ref("promote_enabled")}=false) — ячейки не судятся',
              flush=True)
        return 0
    if os.path.realpath(spec.candidate) == os.path.realpath(spec.live):
        print('ERROR:bank_promote: кандидат — это живой банк', flush=True)
        return 2
    RBS.bind(BP, spec, 'bank_pending')
    pstate = BP.load_state()
    try:
        got = BPm.chain(run_id, BP.PREPARE_REPORT, spec.candidate, pstate)
    except RUN.ChainError as e:
        return RUN.refuse('bank_promote', f'{spec.room}: {e} — ничего не сужу, manifest не пишу', e.rc)
    if got is None:
        print(f'WARN:bank_promote: {spec.room}: bank_prepare этой ночи выключен — не сужу', flush=True)
        return 0
    craw, csha = got
    if not os.path.exists(spec.live):
        print(f'WARN:bank_promote: {spec.room}: живого банка нет — поколение 0 кладёт room_bootstrap словом ведущего; не сужу',
              flush=True)
        return 0
    t0 = time.time()
    raw = open(spec.live, 'rb').read()
    live = json.loads(raw)
    hold = _hold(spec)

    def held(s):
        return hold.get(RG.cell_key(s)) is not None and hold.get(RG.cell_key(s)) == BP.candidate_hash(s)
    got = (verdict_fn or RG.verdict)(spec.room, spec.candidate, spec.live, cand_raw=craw, held_fn=held)
    if got is None:
        return RUN.refuse('bank_promote', f'{spec.room}: сторожа не судили (кандидат не читается)')
    rep, lines, cand, live_v = got
    for x in lines:
        print(x, flush=True)
    man = {'room': spec.room, 'at': _now(), 'run_id': run_id, 'candidate_sha': csha, 'live': spec.live,
           'candidate': spec.candidate, 'live_sha': RUN.sha(raw), 'hybrid': None, 'hybrid_sha': None,
           'fatal': rep.get('fatal') or None, 'guards': RG.summary(rep)}
    if live_v != live:
        man['fatal'] = ['живой банк сменился между чтением и вердиктом сторожей']
    rc = 0
    if man['fatal']:
        print(f"ERROR:bank_promote: {spec.room}: {'; '.join(man['fatal'])[:300]} — ничего не продвигаем", flush=True)
        rc = 1
    else:
        want = want if want is not None else {'|'.join(map(str, c)) for c in RI.expected(spec.room)}
        hybrid, fields = build(spec.room, rep, live, cand, want, BP.candidate_hash, pstate)
        man.update(fields)
        ident = SID.verify(hybrid, live, cells=None, key=spec.cell, grow=True)
        if ident:
            man['fatal'] = ['идентичность смешанного: ' + '; '.join(ident)]
            print(f"ERROR:bank_promote: {spec.room}: {man['fatal'][0][:300]} — ничего не продвигаем", flush=True)
            rc = 1
        else:
            hp = os.path.join(spec.promote_work, 'hybrid.json')
            data = json.dumps(hybrid, ensure_ascii=False, indent=1).encode('utf-8')
            _atomic(hp, data)
            man['hybrid'], man['hybrid_sha'] = hp, RUN.sha(data)
    man['seconds'] = round(time.time() - t0)
    _atomic(spec.promote_manifest, json.dumps(man, ensure_ascii=False, indent=1, default=str).encode('utf-8'))
    new_n, ret = man.get('new_cells') or [], man.get('retired') or []
    print(f"bank_promote {spec.room}: продвигается {len(man.get('promoted') or [])} {(man.get('promoted') or [])[:12]} "
          f"(предел {man.get('cap')}), из них новых ячеек {len(new_n)}; к снятию с витрины (retired) {len(ret)}; "
          f"новых, что ждут, {len(man.get('pending_new') or [])}; manifest → {spec.promote_manifest}", flush=True)
    print(f"DIGEST:банк {spec.room} (подмена): продвигается {len(man.get('promoted') or [])}, новых ячеек {len(new_n)}, "
          f"retired {len(ret)}, новых ждут {len(man.get('pending_new') or [])}" + ('; ОШИБКА — не продвигаем' if rc else ''),
          flush=True)
    return rc
