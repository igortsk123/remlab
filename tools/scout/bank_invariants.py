#!/usr/bin/env python3
"""Сравнение банков «было / стало» и инварианты кандидата (план conv-13 п.3, критерии приёмки).

ЗАЧЕМ. Новый банк собирается рядом (`sets3.next.json`, `bank_paths`) и подменяет живой только после ⚑ владельца.
До показа нужны числа, а не «на глаз»: та же карта сетов, ни одного ушедшего товара, пары и контракты чисты,
ссылки партнёрские и текущие, ключевые роли на месте. Скрипт ничего не пишет — только читает оба банка и каталог.

Критерии (каждый — число; `ok` = выполнен):
  map            — 126 сетов, та же карта (band, style, tier, set_id) по номерам;
  gone           — позиций, которых нет в каталоге (`catalog_media.media` → None / state gone), = 0;
  pair_mismatch  — экземпляр пары ≠ основному (`sets_incremental.sync_pairs`, сухо), = 0;
  contracts      — позиций вне контракта слота (`sets_incremental._slot_ok` — те же ворота, что у ночного шага), = 0;
  url_stale      — ссылка позиции ≠ текущей партнёрской из каталога (или пустая), = 0; сетью НЕ проверяем —
                   стучаться ботом в партнёрскую ссылку нельзя (накрутка кликов, `catalog_media`);
  alt_bad        — запасные (`alternates`) без SKU, ушедшие из каталога или равные выбранному, = 0;
  core_missing   — сетов без дивана / столика / носителя ТВ (тв-тумба или стенка) / обязательной пары
                   (≥25 м² с диваном и креслом — кресло 2 или qty≥2, как `test_bank_coverage`), по каждой = 0.
Дельта: сколько слотов сменило SKU, по стилям; роли, которые появились или пропали.

  ~/venvs/scout/bin/python bank_invariants.py --old sets3.json --new ~/remlab-logs/t21-09/sets3.next.json [--json out.json]
"""
import argparse
import collections
import json
import os
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


def check(sets: list, ref: list | None, media, slot_ok, sync_pairs) -> dict:
    """Инварианты банка `sets` (`ref` — прежний банк для карты). Чистая относительно файлов: каталог и ворота — аргументы."""
    r = {'sets': len(sets)}
    key4 = lambda s: (s.get('band'), s.get('style'), s.get('tier'), s.get('set_id'))  # noqa: E731
    if ref is not None:
        diff = [i + 1 for i, (a, b) in enumerate(zip(ref, sets)) if key4(a) != key4(b)]
        r['map_diff'] = diff[:20] + (['…'] if len(diff) > 20 else [])
        r['map_ok'] = len(sets) == len(ref) == 126 and not diff
    gone, url_stale, contracts, alt_bad = [], [], [], []
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
            if not slot_ok(role, it, s):
                contracts.append((n, role, sku(it)))
        for role, alts in (s.get('alternates') or {}).items():
            for a in alts or []:
                m = media(a.get('mid'), a.get('eid')) if a.get('eid') else None
                if not a.get('eid') or not m or m.get('state') == 'gone' or sku(a) == sku(items.get(role)):
                    alt_bad.append((n, role, sku(a)))
    pairs = sync_pairs(json.loads(json.dumps(sets)), apply=False)
    miss = collections.Counter(x for s in sets for x in core_missing(s))
    r.update(gone=len(gone), gone_rows=gone[:30], url_stale=len(url_stale), url_rows=url_stale[:30],
             contracts=len(contracts), contracts_rows=contracts[:30], pair_mismatch=len(pairs), pair_rows=pairs[:30],
             alt_bad=len(alt_bad), alt_rows=alt_bad[:30], core_missing=dict(miss),
             gaps_declared=dict(collections.Counter(str(g).split(' — ')[0] for s in sets for g in (s.get('gaps') or []))))
    r['ok'] = (r.get('map_ok', True) and not gone and not url_stale and not contracts and not pairs
               and not alt_bad and not miss)
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default=os.path.join(HERE, 'sets3.json'))
    ap.add_argument('--new', required=True)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    import sets_incremental as SI
    from catalog_media import media
    old = json.load(open(a.old, encoding='utf-8'))
    new = json.load(open(a.new, encoding='utf-8'))
    rep = {'old': check(old, None, media, SI._slot_ok, SI.sync_pairs),
           'new': check(new, old, media, SI._slot_ok, SI.sync_pairs),
           'delta': delta(old, new)}
    for side in ('old', 'new'):
        r = rep[side]
        print(f"[{side}] сетов {r['sets']}" + (f", карта {'та же' if r['map_ok'] else 'РАЗНАЯ ' + str(r['map_diff'])}"
                                                if 'map_ok' in r else '')
              + f"; ушедших {r['gone']}, ссылок не текущих {r['url_stale']}, вне контракта {r['contracts']}, "
                f"пар разошлось {r['pair_mismatch']}, запасных негодных {r['alt_bad']}; "
                f"без ключевых ролей {r['core_missing'] or 0}; итог {'OK' if r['ok'] else 'НЕ ГОДЕН'}")
    print('дельта по стилям:')
    for style, c in rep['delta'].items():
        print(f'  {style}: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())))
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    return 0 if rep['new']['ok'] else 1


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def mk(sid, items, m2=15, style='сканди', alts=None):
        return {'band': '14-16', 'style': style, 'tier': 'эконом', 'set_id': sid, 'm2': m2, 'items': items,
                'alternates': alts or {}}
    it = lambda e, **k: dict(mid=1, eid=e, url=f'u{e}', **k)  # noqa: E731
    cat = {('1', 'a'): {'state': 'available', 'url': 'ua'}, ('1', 'b'): {'state': 'available', 'url': 'ub'},
           ('1', 'c'): {'state': 'available', 'url': 'uc'}, ('1', 'g'): {'state': 'gone', 'url': 'ug'}}
    media = lambda mid, eid: cat.get((str(mid), str(eid)))  # noqa: E731
    good = mk('s1', {'диван': it('a'), 'столик': it('b'), 'тв-тумба': it('c')}, alts={'диван': [it('b')]})
    pairs0 = lambda sets, apply=False: []  # noqa: E731
    r = check([good] * 126, [good] * 126, media, lambda *x: True, pairs0)
    ok('чистый банк — ok, карта та же', r['ok'] and r['map_ok'])
    badset = mk('s1', {'диван': it('g'), 'столик': dict(it('b'), url='old'), 'тв-тумба': it('c')},
                alts={'диван': [it('g'), it('g')], 'столик': [it('b')]})
    r = check([badset], None, media, lambda role, i, s: role != 'тв-тумба', lambda sets, apply=False: [(1,)])
    ok('ушедший, старая ссылка, вне контракта, пара, запасные (ушедший ×2 и равный выбранному) — каждый счётчик',
       (r['gone'], r['url_stale'], r['contracts'], r['pair_mismatch'], r['alt_bad']) == (1, 1, 1, 1, 3) and not r['ok'])
    r = check([mk('s1', {'столик': it('b')}, m2=26), mk('s2', {'диван': it('a'), 'кресло': it('b'), 'стенка': it('c'),
                                                               'столик': it('b')}, m2=26)], None, media,
              lambda *x: True, pairs0)
    ok('ключевые роли: диван, носитель ТВ, пара кресел ≥25 м² — по отдельности',
       r['core_missing'] == {'диван': 1, 'носитель ТВ': 1, 'пара кресел': 1})
    r = check([good] * 125, [good] * 126, media, lambda *x: True, pairs0)
    ok('125 сетов против 126 — карта не та', not r['map_ok'] and not r['ok'])
    d = delta([good, mk('s2', {'диван': it('a')}, style='лофт')],
              [mk('s1', {'диван': it('b'), 'столик': it('b'), 'ковёр': it('c')}), mk('s3', {}, style='лофт')])
    ok('дельта: SKU сменился, роль появилась/пропала, новый сет — по стилю',
       d == {'сканди': {'SKU сменился': 1, 'без изменений': 1, 'роль появилась': 1, 'роль пропала': 1},
             'лофт': {'сет новый': 1}})
    print(f'bank_invariants selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())
