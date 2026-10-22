#!/usr/bin/env python3
"""ЖУРНАЛ РЕШЕНИЙ ПО МЕШАМ `mesh_asset_decisions` (conv-14 шаг 2.1, разбор Codex 22.10 § 2).

ЗАЧЕМ. `products.mesh_status='rejected'` склеивает три разных смысла: `redo` (модель плохая — переделать), `replace_needed`
(товар заменить, переделывать бесполезно) и `reject` (ручной брак карантина). Ожидание банка (`bank_pending`) обязано их
различать: переделку ждут, замену и брак пересобирают без товара. Плюс у 33 из 62 `rejected` на DEV нет НИ ОДНОЙ записи о
поколении (следы мешей v1, папку вычистили 02.10): угадывать «меша не было — закажем заново» нельзя — Tubo тому пример,
отказ владельца записан только в `rules/mesh-pinned.json`. Такие — `legacy_unknown`: не продвигать, не тратить, разовая
триаж-очередь (`--triage`).

ИСТОЧНИКИ (новая таблица БД — миграция, её нет; журнал — файлы):
  1. `rules/mesh-asset-decisions.json` — перенесённые вручную решения прошлого (в git, с источником и датой);
  2. `~/scout-scenes/mesh-asset-decisions.jsonl` (env `MESH_DECISIONS`) — новые решения, ТОЛЬКО дописываются (`record`);
     снять решение — дописать `cleared` (исправили данные, перегон удался), прошлое не правится;
  3. DEV как есть: вердикт владельца ТЕКУЩЕГО поколения (`mesh_generations.owner_verdict`, адресован поколению —
     `mesh_audit_sync.py:95`) и решение карантина `reject` (`mesh_quarantine.decision`).
Последнее по времени решение по SKU побеждает; решение с `generation_key` действует, пока это поколение текущее.

  python3 mesh_decisions.py --selftest
  ~/venvs/scout/bin/python mesh_decisions.py --triage           # legacy_unknown: rejected без происхождения
  ~/venvs/scout/bin/python mesh_decisions.py --record SKU replace_needed "владелец: …"   # дописать решение
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, 'rules', 'mesh-asset-decisions.json')
LOG = os.path.expanduser(os.environ.get('MESH_DECISIONS', '~/scout-scenes/mesh-asset-decisions.jsonl'))
DECISIONS = ('redo', 'replace_needed', 'reject', 'cleared')


def latest(records: list, current_gen: dict | None = None) -> dict:
    """Чистое ядро: записи → {sku: последнее действующее решение}. Решение, адресованное поколению, которое уже не текущее
    (`current_gen[sku]` другое), не действует — меш заменён, решение было про прежнюю модель. `cleared` снимает решение."""
    out = {}
    for r in sorted(records, key=lambda r: (str(r.get('at') or ''), r.get('_n', 0))):
        sku, d = r.get('sku'), r.get('decision')
        if not sku or d not in DECISIONS:
            continue
        gk = r.get('generation_key')
        if gk and current_gen is not None and current_gen.get(sku) not in (None, gk):
            continue
        if d == 'cleared':
            out.pop(sku, None)
        else:
            out[sku] = {k: r.get(k) for k in ('decision', 'source', 'at', 'generation_key')}
    return out


def _seed() -> list:
    try:
        return list(json.load(open(SEED, encoding='utf-8')).get('decisions') or [])
    except FileNotFoundError:
        return []


def _log() -> list:
    out = []
    try:
        with open(LOG, encoding='utf-8') as f:
            for n, line in enumerate(f):
                line = line.strip()
                if line:
                    try:
                        out.append({**json.loads(line), '_n': n})
                    except ValueError:
                        print(f'WARN:mesh_decisions: строка {n + 1} журнала {LOG} не читается — пропущена', flush=True)
    except FileNotFoundError:
        pass
    return out


def _db_records() -> tuple[list, dict]:
    """Решения DEV: вердикт владельца текущего поколения и `reject` карантина. → (записи, {sku: текущее поколение})."""
    from mesh_queue import db
    recs, cur = [], {}
    # «текущее» поколение — правило реестра и `mesh_bind.current_generations`: позднее по времени, при равенстве — больший ключ
    for sku, gk, verdict, at in db(
            "select sku, generation_key, coalesce(owner_verdict,''), coalesce(owner_verdict_at, updated)::date::text "
            "from (select distinct on (sku) sku, generation_key, owner_verdict, owner_verdict_at, updated "
            "      from mesh_generations order by sku, generated_at desc, generation_key desc) t"):
        cur[sku] = gk
        if verdict:
            recs.append({'sku': sku, 'generation_key': gk, 'at': at, 'source': 'mesh_generations.owner_verdict',
                         'decision': 'redo' if verdict == 'redo' else 'replace_needed'})
    for sku, at in db("select sku, max(coalesce(decided_at, created))::date::text from mesh_quarantine "
                      "where decision = 'reject' group by sku"):
        recs.append({'sku': sku, 'at': at, 'source': 'mesh_quarantine.decision=reject', 'decision': 'reject'})
    return recs, cur


def load(with_db: bool = True) -> dict:
    """{sku: решение} по всем источникам."""
    recs, cur = (_db_records() if with_db else ([], None))
    return latest(_seed() + recs + _log(), cur)


def record(sku: str, decision: str, source: str, generation_key: str | None = None, note: str = '') -> dict:
    """Дописать решение (append-only; файл создаётся, прошлое не правится)."""
    if decision not in DECISIONS:
        raise ValueError(f'решение {decision!r} — не из {DECISIONS}')
    if not source:
        raise ValueError('у решения обязателен источник')
    rec = {'sku': sku, 'decision': decision, 'source': source, 'generation_key': generation_key,
           'at': time.strftime('%Y-%m-%dT%H:%M:%S'), **({'note': note} if note else {})}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())
    return rec


def legacy_unknown(rejected: set, decisions: dict, with_generation: set) -> set:
    """`rejected` без происхождения: нет решения в журнале и нет ни одного поколения на DEV."""
    return {s for s in rejected if s not in decisions and s not in with_generation}


def triage() -> int:
    from mesh_queue import db
    dec = load()
    rej = {r[0]: r[1:] for r in db("select shop_mid||':'||external_id, coalesce(cat_role,''), left(name,60) "
                                   "from products where mesh_status = 'rejected'") if len(r) == 3}
    gens = {r[0] for r in db("select distinct sku from mesh_generations") if r and r[0]}
    unk = sorted(legacy_unknown(set(rej), dec, gens))
    print(f'[mesh_decisions] rejected {len(rej)}: с решением {sum(1 for s in rej if s in dec)}, '
          f'с поколением без решения {sum(1 for s in rej if s not in dec and s in gens)}, без происхождения {len(unk)}')
    for s in unk:
        print(f'  legacy_unknown  {s}  {rej[s][0]:<12} {rej[s][1]}')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    recs = [{'sku': 'a', 'decision': 'redo', 'at': '2026-10-01', 'generation_key': 'g1', 'source': 's'},
            {'sku': 'a', 'decision': 'replace_needed', 'at': '2026-10-05', 'generation_key': 'g1', 'source': 's'},
            {'sku': 'b', 'decision': 'replace_needed', 'at': '2026-10-02', 'source': 'seed'},
            {'sku': 'b', 'decision': 'cleared', 'at': '2026-10-09', 'source': 'исправили данные'},
            {'sku': 'c', 'decision': 'redo', 'at': '2026-10-03', 'generation_key': 'old', 'source': 's'},
            {'sku': 'd', 'decision': 'перекрасить', 'at': '2026-10-03', 'source': 's'}]
    got = latest(recs, {'a': 'g1', 'c': 'new'})
    ok('последнее решение побеждает (redo → replace_needed)', got.get('a', {}).get('decision') == 'replace_needed', got)
    ok('cleared снимает решение', 'b' not in got)
    ok('решение о прежнем поколении не действует на новое', 'c' not in got)
    ok('незнакомое решение — пропущено', 'd' not in got)
    ok('без сведений о поколениях (только журнал) — решение о поколении действует',
       latest(recs[4:5], None).get('c', {}).get('decision') == 'redo')
    ok('legacy_unknown: rejected без решения и без поколения',
       legacy_unknown({'x', 'y', 'z'}, {'x': {}}, {'y'}) == {'z'})
    import tempfile
    global LOG
    keep = LOG
    with tempfile.TemporaryDirectory() as td:
        LOG = os.path.join(td, 'd.jsonl')
        record('q', 'reject', 'тест')
        record('q', 'cleared', 'тест')
        lines = open(LOG, encoding='utf-8').read().splitlines()
        ok('запись только дописывается: обе строки на месте, итог — снято', len(lines) == 2 and 'q' not in latest(_log()))
        try:
            record('q', 'reject', '')
            ok('без источника — отказ', False)
        except ValueError:
            ok('без источника — отказ', True)
    LOG = keep
    seed = latest(_seed())
    ok('Tubo — явный replace_needed из журнала (отказ владельца, rules/mesh-pinned.json)',
       seed.get('99272:2147763667486905198', {}).get('decision') == 'replace_needed', seed)
    print(f'mesh_decisions selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--triage' in sys.argv:
        sys.exit(triage())
    if '--record' in sys.argv:
        i = sys.argv.index('--record')
        print(json.dumps(record(sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]), ensure_ascii=False))
        sys.exit(0)
    print(__doc__)
