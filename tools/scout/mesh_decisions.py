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
  ~/venvs/scout/bin/python mesh_decisions.py --comments [--since 7d] [--digest]   # комментарии владельца к браку

КОММЕНТАРИИ К БРАКУ (план mesh-audit-comments, владелец 23.10): решение с `/lab/mesh-audit` мост (`mesh_audit_sync.py`) дописывает
в журнал с источником `AUDIT_SOURCE` и полем `note` — «что не так». `--comments` раз в неделю: сколько, по магазину / роли /
источнику фото, с примерами — ищем ОБЩЕЕ решение (поставщик, тип фото, канал), а не правку одного товара; `--digest` — одна
строка `DIGEST:` для утренней сводки ночного прогона.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, 'rules', 'mesh-asset-decisions.json')
LOG = os.path.expanduser(os.environ.get('MESH_DECISIONS', '~/scout-scenes/mesh-asset-decisions.jsonl'))
DECISIONS = ('redo', 'replace_needed', 'reject', 'cleared')
AUDIT_SOURCE = 'владелец /lab/mesh-audit'


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


def summarize(records: list, info: dict, since: str) -> dict:
    """Чистое ядро `--comments`: комментарии владельца к браку не раньше `since` (ISO-дата). Отменённое (`cleared` того же
    поколения позже) не считается. `info[sku]` = {'shop','role','photo','name','url'}. → {'n', 'by_shop', 'by_role', 'by_photo',
    'items'} — счётчики убыванием и сами комментарии (новые сверху)."""
    live = {}
    for r in sorted(records, key=lambda r: (str(r.get('at') or ''), r.get('_n', 0))):
        if not str(r.get('source') or '').startswith(AUDIT_SOURCE):
            continue
        key = (r.get('sku'), r.get('generation_key'))
        if r.get('decision') == 'cleared':
            live.pop(key, None)
        elif r.get('note') and str(r.get('at') or '') >= since:
            live[key] = r
    items = []
    for (sku, gk), r in live.items():
        i = info.get(sku) or {}
        items.append({'sku': sku, 'generation_key': gk, 'at': r.get('at'), 'decision': r.get('decision'), 'note': r['note'],
                      **{k: i.get(k) or '?' for k in ('shop', 'role', 'photo', 'name', 'url')}})
    items.sort(key=lambda x: str(x['at']), reverse=True)

    def count(k):
        c = {}
        for x in items:
            c[x[k]] = c.get(x[k], 0) + 1
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    return {'n': len(items), 'by_shop': count('shop'), 'by_role': count('role'), 'by_photo': count('photo'), 'items': items}


def _since(arg: str | None) -> str:
    """'7d' → ISO-дата неделю назад (по умолчанию 7d)."""
    days = int((arg or '7d').rstrip('d') or 7)
    return time.strftime('%Y-%m-%d', time.localtime(time.time() - days * 86400))


def _info(skus: set) -> dict:
    """Магазин, роль, источник фото (хост HD-фото, иначе обычного), имя, ссылка — из каталога DEV."""
    if not skus:
        return {}
    from urllib.parse import urlparse
    from mesh_queue import db, q
    out = {}
    for sku, shop, role, img, hd, name, url in db(
            "select shop_mid||':'||external_id, coalesce(shop, shop_mid), coalesce(cat_role,''), coalesce(image_url,''), "
            "(image_url_hd is not null)::text, left(coalesce(name,''),80), coalesce(url,'') from products "
            f"where shop_mid||':'||external_id in ({','.join(q(s) for s in sorted(skus))})"):
        out[sku] = {'shop': shop, 'role': role, 'name': name, 'url': url,
                    'photo': (urlparse(img).hostname or '?') + (' (HD)' if hd == 'true' else '')}
    return out


def comments(since_arg: str | None, digest: bool) -> int:
    recs = [r for r in _seed() + _log() if str(r.get('source') or '').startswith(AUDIT_SOURCE)]
    since = _since(since_arg)
    skus = {r.get('sku') for r in recs if r.get('note')}
    s = summarize(recs, _info(skus), since)
    top = lambda kv: ', '.join(f'{k} {n}' for k, n in kv[:3])  # noqa: E731
    if digest:
        print(f"DIGEST:комментариев к браку мешей с {since}: {s['n']}"
              + (f" (магазины: {top(s['by_shop'])}; роли: {top(s['by_role'])}) — разбор: mesh_decisions.py --comments" if s['n'] else ''))
        return 0
    print(f"[mesh_decisions] комментариев владельца к браку с {since}: {s['n']}")
    for title, k in (('по магазину', 'by_shop'), ('по роли', 'by_role'), ('по источнику фото', 'by_photo')):
        if s[k]:
            print(f'  {title}: ' + ', '.join(f'{a} — {n}' for a, n in s[k]))
    for x in s['items']:
        print(f"  {str(x['at'])[:10]}  {x['decision']:<14} {x['role']:<10} {x['shop']:<10} «{x['note']}»  {x['name']}  {x['url']}")
    return 0


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
    aud = [{'sku': 'm:1', 'decision': 'redo', 'source': AUDIT_SOURCE + ', решение 5', 'generation_key': 'g1',
            'at': '2026-10-20T10:00:00', 'note': 'фото не дорезалось'},
           {'sku': 'm:2', 'decision': 'redo', 'source': AUDIT_SOURCE + ', решение 6', 'generation_key': 'g2',
            'at': '2026-10-21T10:00:00', 'note': 'ножки пропали'},
           {'sku': 'm:2', 'decision': 'cleared', 'source': AUDIT_SOURCE + ', отмена решения 6', 'generation_key': 'g2',
            'at': '2026-10-21T10:01:00'},
           {'sku': 'm:3', 'decision': 'redo', 'source': AUDIT_SOURCE + ', решение 7', 'generation_key': 'g3', 'at': '2026-10-22'},
           {'sku': 'm:4', 'decision': 'replace_needed', 'source': AUDIT_SOURCE + ', решение 8', 'generation_key': 'g4',
            'at': '2026-10-01T10:00:00', 'note': 'старое'},
           {'sku': 'm:5', 'decision': 'redo', 'source': 'руками', 'at': '2026-10-22', 'note': 'не с приёмки'}]
    sm = summarize(aud, {'m:1': {'shop': 'divan.ru', 'role': 'диван', 'photo': 'cdn (HD)'}}, '2026-10-16')
    ok('комментарии: отменённое и без текста не считаются, старое — вне окна, чужой источник — нет',
       sm['n'] == 1 and sm['items'][0]['note'] == 'фото не дорезалось', sm)
    ok('комментарии: сводка по магазину/роли/фото', sm['by_shop'] == [('divan.ru', 1)] and sm['by_photo'] == [('cdn (HD)', 1)], sm)
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
    if '--comments' in sys.argv:
        sys.exit(comments(sys.argv[sys.argv.index('--since') + 1] if '--since' in sys.argv else None, '--digest' in sys.argv))
    if '--record' in sys.argv:
        i = sys.argv.index('--record')
        print(json.dumps(record(sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]), ensure_ascii=False))
        sys.exit(0)
    print(__doc__)
