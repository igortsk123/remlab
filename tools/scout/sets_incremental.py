#!/usr/bin/env python3
"""Обратный индекс «товар → комплекты»: что пересобирать, когда товар изменился.

Сейчас связь односторонняя: комплект знает свои товары, а товар о комплектах — нет. Поэтому любое
изменение каталога означает «пересобрать все 126 комплектов». Индекс делает связь двусторонней:
ушёл товар — видно ровно те комплекты, которых это касается.

Сама пересборка — этап К4 мастер-плана; здесь индекс, диагноз и готовая замена из `alternates`.

  ~/venvs/scout/bin/python sets_incremental.py --index     # построить sets-index.json
  ~/venvs/scout/bin/python sets_incremental.py --check     # какие комплекты задеты сейчас
  ~/venvs/scout/bin/python sets_incremental.py --why 116933 3036041517751486277
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = os.path.join(HERE, 'sets3.json')
INDEX = os.path.join(HERE, 'sets-index.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def key(mid, eid) -> str:
    return f'{mid}:{eid}'


def build() -> dict:
    """Индекс: ключ товара → в каких комплектах и в какой роли он стоит (плюс где он в запасе)."""
    sets = json.load(open(SETS))
    idx: dict[str, dict] = {}
    for n, s in enumerate(sets, 1):
        for role, it in s['items'].items():
            rec = idx.setdefault(key(it['mid'], it['eid']),
                                 {'name': it['name'], 'used': [], 'spare': []})
            rec['used'].append({'set': n, 'role': role, 'price': it['price']})
        for role, alts in (s.get('alternates') or {}).items():
            for a in alts:
                rec = idx.setdefault(key(a['mid'], a['eid']),
                                     {'name': a.get('name', ''), 'used': [], 'spare': []})
                rec['spare'].append({'set': n, 'role': role})
    json.dump(idx, open(INDEX, 'w'), ensure_ascii=False)
    used = sum(1 for v in idx.values() if v['used'])
    print(f'товаров в индексе: {len(idx)} (в комплектах {used}, только в запасе {len(idx) - used})')
    print(f'комплектов: {len(sets)}; записей «товар в комплекте»: '
          f'{sum(len(v["used"]) for v in idx.values())}')
    return idx


def _load() -> dict:
    if not os.path.exists(INDEX):
        return build()
    return json.load(open(INDEX))


def _rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def check() -> None:
    """Какие комплекты сейчас задеты: товар не `active` или сменил семантику."""
    idx = _load()
    ids = [k.split(':') for k in idx if idx[k]['used']]
    if not ids:
        print('в индексе нет товаров комплектов')
        return
    vals = ','.join(f"({m},'{e}')" for m, e in ids)
    rows = _rows(f"""
      select e.shop_mid, e.external_id, e.status, coalesce(e.missing_runs,0)
        from product_enrichment e join (values {vals}) v(mid,eid)
          on e.shop_mid=v.mid and e.external_id=v.eid
       where e.status <> 'active'
    """)
    if not rows:
        print('все товары комплектов в наличии — пересобирать нечего')
        return
    hit: dict[int, list] = {}
    for mid, eid, status, runs in rows:
        rec = idx[key(mid, eid)]
        for u in rec['used']:
            hit.setdefault(u['set'], []).append((u['role'], rec['name'], status, runs))
    print(f'задето комплектов: {len(hit)} из-за {len(rows)} товаров\n')
    sets = json.load(open(SETS))
    for n in sorted(hit):
        s = sets[n - 1]
        print(f'комплект {n} ({s["style"]}, {s["band"]} м², {s["tier"]}):')
        for role, name, status, runs in hit[n]:
            spare = (s.get('alternates') or {}).get(role) or []
            fix = f'замена в запасе: {spare[0]["name"][:40]}' if spare else 'ЗАПАСА НЕТ — роль повиснет'
            print(f'  {role}: {name[:44]} → {status} (пропусков {runs}); {fix}')


def why(mid: str, eid: str) -> None:
    rec = _load().get(key(mid, eid))
    if not rec:
        print('этого товара нет ни в одном комплекте')
        return
    print(f'{rec["name"]}\n  в комплектах: '
          + (', '.join(f'{u["set"]}({u["role"]})' for u in rec['used']) or '—'))
    print('  в запасе у: ' + (', '.join(f'{s["set"]}({s["role"]})' for s in rec['spare']) or '—'))


_CAND_CACHE: dict = {}


def _live_candidates(role: str, cur: dict, style: str | None, alive: set,
                     exclude: set, limit: int = 10) -> list[dict]:
    """Кандидаты из живого candidates-index.json: роль та же, в наличии, ±30% цены,
    сортировка по ступени стиля сета и близости цены (В3)."""
    if not _CAND_CACHE:
        p = os.path.join(HERE, 'candidates-index.json')
        if not os.path.exists(p):
            return []
        _CAND_CACHE.update(json.load(open(p)))
    steps = {'нет': 0, 'низкая': 1, 'средняя': 2, 'высокая': 3}
    out = []
    for k, item in _CAND_CACHE.get('items', {}).items():
        if item.get('role') != role or k in exclude or k not in alive:
            continue
        pr = item.get('price') or 0
        if not (0.7 * cur['price'] <= pr <= 1.3 * cur['price']):
            continue
        st = steps.get(str((item.get('styles') or {}).get(style or '', 'нет')), 0)
        out.append((st, abs(pr - cur['price']), {'mid': item['mid'], 'eid': item['eid'],
                                                 'name': item['name'], 'price': pr,
                                                 'w': item.get('w'), 'd': item.get('d'),
                                                 'h': item.get('h'), 'dia': item.get('dia'),
                                                 'shop': item.get('shop'), 'subtype': item.get('subtype')}))
    out.sort(key=lambda t: (-t[0], t[1]))
    return [x[2] for x in out[:limit]]


def refresh(apply: bool = False, max_swaps_per_set: int = 2) -> None:
    """Еженедельное ТОЧЕЧНОЕ освежение (В3/К4, владелец 07.08): новинка ЗАМЕТНО лучше
    стоящего в сете по силе стиля (ступень строго выше, цель «высокая») и в ±30% цены —
    точечная замена с воротами пропорций. Состав не «прыгает»: ≤2 замен на сет за прогон."""
    import shutil
    from proportions import check as prop_check
    from item_function import subtype as _sub
    steps = {'нет': 0, 'низкая': 1, 'средняя': 2, 'высокая': 3}
    sets = json.load(open(SETS))
    alive = {key(r[0], r[1]) for r in _rows(
        "select e.shop_mid, e.external_id from product_enrichment e "
        "join products p using (shop_mid, external_id) "
        "where e.status='active' and p.in_stock") if len(r) >= 2}
    if not _CAND_CACHE:
        p = os.path.join(HERE, 'candidates-index.json')
        if os.path.exists(p):
            _CAND_CACHE.update(json.load(open(p)))
    items_idx = _CAND_CACHE.get('items', {})
    major = ('диван', 'кресло', 'столик', 'тв-тумба', 'стеллаж', 'комод', 'стол обеденный')
    from testmode import skip as _tm_skip
    swapped = 0
    for n, s in enumerate(sets, 1):
        if _tm_skip(n):
            continue                     # тест-режим: освежаем только выбранные (heal — всегда все)
        style = s.get('style')
        if not style:
            continue
        done = 0
        for role in major:
            if done >= max_swaps_per_set:
                break
            it = s['items'].get(role)
            if not it:
                continue
            cur_rec = items_idx.get(key(it['mid'], it['eid'])) or {}
            cur_step = steps.get(str((cur_rec.get('styles') or {}).get(style, 'нет')), 0)
            if cur_step >= 3:
                continue                     # уже «высокая» — менять незачем
            for cand in _live_candidates(role, it, style, alive,
                                         exclude={key(it['mid'], it['eid'])}, limit=5):
                cst = steps.get(str((items_idx.get(key(cand['mid'], cand['eid']), {})
                                     .get('styles') or {}).get(style, 'нет')), 0)
                if cst < 3 or cst <= cur_step:
                    continue                 # замена только на СТРОГО лучшую, до «высокой»
                trial = dict(it)
                trial.update({k2: cand[k2] for k2 in ('mid', 'eid', 'name', 'price') if k2 in cand})
                ctx = {'chosen': {r: v for r, v in s['items'].items() if r != role}, 'wall': None,
                       'corner_sofa': 'углов' in str((s['items'].get('диван') or {}).get('name', '')).lower()}
                ok, _b, _no = prop_check(role, trial, ctx, _sub(role, trial))
                if not ok:
                    continue
                print(f'  сет {n} [{style}]: {role} «{it["name"][:30]}» (ступень {cur_step}) '
                      f'→ «{cand["name"][:30]}» (высокая)')
                if apply:
                    s['items'][role] = trial
                swapped += 1
                done += 1
                break
    print(f'освежено позиций: {swapped}' + ('' if apply else ' (показ; применить — --apply)'))
    if apply and swapped:
        shutil.copy(SETS, SETS + '.bak')
        json.dump(sets, open(SETS, 'w'), ensure_ascii=False)
        print('sets3.json обновлён (бэкап .bak)')


_POD_BANNED: set | None = None


def _pod_banned_mids() -> set:
    """Магазины со сломанным/протухшим фидом (+ отложенный карантин) — в pod не берём (fail-closed,
    как в compose2)."""
    global _POD_BANNED
    if _POD_BANNED is None:
        _POD_BANNED = set()
        try:
            fr = json.load(open(os.path.join(HERE, 'feed-freshness.json')))
            for rec in fr.values():
                if rec.get('state') in ('stale', 'broken'):
                    _POD_BANNED |= {int(m) for m in list(rec.get('mids', [])) + list(rec.get('mids_quarantine_pending', []))}
        except Exception:
            pass
    return _POD_BANNED


def _heal_pod(s: dict, members: list[str], dead: dict, alive: set, apply: bool = False) -> dict | None:
    """Замена умерших членов pod-комплекта живыми аналогами (правила pod_kit из zones.json seating_pods).
    Возвращает {роль: новое имя} или None (замены нет — снять весь pod)."""
    import re as _re
    try:
        zr = json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules', 'zones.json'), encoding='utf-8'))
        cfg = (zr.get('seating_pods') or {}).get('pod_kit') or {}
    except Exception:
        cfg = {}
    hard = tuple(cfg.get('armchair_hard_wd_cm', [100, 105]))
    bad = _re.compile(cfg.get('armchair_exclude_regex', 'реклайнер|recliner|кресло-кроват|раскладн|качалк|мешок|подвесн'), _re.I)
    smax = float(cfg.get('surface_side_max_cm', 70)); sdia = tuple(cfg.get('surface_dia_cm', [35, 70]))
    banned = _pod_banned_mids()
    items = s['items']
    out = {}
    dead_roles = [r for r in members if key(items[r]['mid'], items[r]['eid']) in dead]
    if any(r in ('кресло 3', 'кресло 4') for r in dead_roles):
        cur = items.get('кресло 3') or items.get('кресло 4')
        main_key = key(items['кресло']['mid'], items['кресло']['eid']) if 'кресло' in items else None
        pick = None
        for c in _live_candidates('кресло', cur, s.get('style'), alive, exclude=set(), limit=40):
            if int(c['mid']) in banned or key(c['mid'], c['eid']) == main_key:
                continue
            if (c.get('w') or 999) > hard[0] or (c.get('d') or 999) > hard[1] or bad.search(c.get('name') or ''):
                continue
            if 'пуф' in (c.get('name') or '').lower() or str(c.get('subtype') or '').startswith('пуф'):
                continue                                   # роль «кресло» с именем «пуф» — не кресло pod
            pick = c; break
        if pick is None:
            return None
        pk = key(pick['mid'], pick['eid'])
        if apply:
            for r in ('кресло 3', 'кресло 4'):
                base = dict(items[r]); base.update(pick); base['pair_key'] = pk
                items[r] = base
        out['кресло 3/4'] = pick['name'][:36]
    if 'столик 2' in dead_roles:
        cur = items['столик 2']
        main_key = key(items['столик']['mid'], items['столик']['eid']) if 'столик' in items else None
        pick = None
        for c in _live_candidates('столик', cur, s.get('style'), alive, exclude=set(), limit=60):
            if int(c['mid']) in banned or key(c['mid'], c['eid']) == main_key:
                continue
            w, d = c.get('w') or 0, c.get('d') or 0
            if not (0 < w <= smax and 0 < d <= smax) and not (w == d and sdia[0] <= w <= sdia[1]):
                continue
            pick = c; break
        if pick is None:
            return None
        if apply:
            base = dict(cur); base.update(pick); base['surface_key'] = key(pick['mid'], pick['eid'])
            items['столик 2'] = base
        out['столик 2'] = pick['name'][:36]
    # общий pod_key пересобрать
    if apply and out and all(r in items for r in ('кресло 3', 'столик 2')):
        pk = f"{items['кресло 3']['mid']}:{items['кресло 3']['eid']}|{items['столик 2']['mid']}:{items['столик 2']['eid']}"
        for r in members:
            if r in items:
                items[r]['pod_key'] = pk
    return out or None


def heal(apply: bool = False) -> None:
    """Лечение комплектов: выбывший товар меняем на запасной той же роли.

    Замена обязана пройти те же ворота, что и оригинал: быть в наличии, попадать в ценовую вилку
    (±30%) и не ломать пропорции относительно остальных предметов комплекта. Иначе «починка» тихо
    портит комплект — а это хуже, чем честно показать дырку.
    """
    import shutil
    from proportions import check as prop_check
    from item_function import subtype as _sub

    idx = _load()
    sets = json.load(open(SETS))
    ids = [k.split(':') for k in idx if idx[k]['used']]
    vals = ','.join(f"({m},'{e}')" for m, e in ids)
    # выбыл = пропал из фида (status) ИЛИ карточка мертва (health.py гасит in_stock поверх фида)
    dead = {}
    for row in _rows(f"""select e.shop_mid, e.external_id,
                    case when e.status <> 'active' then e.status else 'карточка мертва' end
             from product_enrichment e
             join products p on p.shop_mid=e.shop_mid and p.external_id=e.external_id
             join (values {vals}) v(mid,eid) on e.shop_mid=v.mid and e.external_id=v.eid
            where e.status <> 'active' or not p.in_stock"""):
        if len(row) >= 3:
            dead[key(row[0], row[1])] = row[2]
    if not dead:
        print('выбывших товаров в комплектах нет — лечить нечего')
        return
    alive = {key(r[0], r[1]) for r in _rows(
        "select e.shop_mid, e.external_id from product_enrichment e "
        "join products p using (shop_mid, external_id) "
        "where e.status='active' and p.in_stock") if len(r) >= 2}

    healed, hopeless = 0, []
    for n, s in enumerate(sets, 1):
        # Q5 свода №13 (Codex): pod-комплект (pod_key: кресло 3/4 одного SKU + столик 2) лечится
        # ЦЕЛИКОМ — независимая замена роли рвёт exact-SKU пару. Выбыл любой член → весь pod
        # снимается (alt-роли, вне total/fill; вернёт следующая полная сборка compose2)
        _dead_pods = {it.get('pod_key') for role, it in s['items'].items()
                      if it.get('pod_key') and key(it['mid'], it['eid']) in dead}
        for _pk in _dead_pods:
            _members = [r for r, it in s['items'].items() if it.get('pod_key') == _pk]
            # 17.08 (урок: утренний heal снял 55/72 pod из-за одного умершего столика 2): член pod
            # ЗАМЕНЯЕТСЯ живым аналогом с теми же pod-воротами (пара 3/4 — один компактный SKU на
            # обоих, столик 2 — малая поверхность), только из живых фидов; нет замены — pod снимается
            _repl = _heal_pod(s, _members, dead, alive, apply)
            if _repl:
                print(f'  комплект {n}: pod {_pk} — член выбыл, заменён: {_repl}')
                healed += 1
                continue
            print(f'  комплект {n}: pod {_pk} — выбыл член, замены нет, снимаем целиком: {_members}')
            healed += 1
            if apply:
                for r in _members:
                    s['items'].pop(r, None)
                # СНЯЛИ КОМПЛЕКТ — ОБЯЗАНЫ ЗАПИСАТЬ ПРОБЕЛ (20.08): контракт банка требует либо
                # pod-комплект с 25 м², либо ЯВНЫЙ gap. Молча снятый pod выглядел как «в сете
                # просто нет второй зоны», и сторож банка падал (сеты 66/83/84/101/102/119/120)
                _g = s.setdefault('gaps', [])
                _msg = 'coverage_gap: pod-комплект (кресло 3/4 + столик 2) — член выбыл, замены нет'
                if _msg not in _g:
                    _g.append(_msg)
        for role, it in list(s['items'].items()):
            k = key(it['mid'], it['eid'])
            if k not in dead:
                continue
            # Q5-КОНТРАКТ ПАРЫ (20.08): «кресло 2» — ВТОРОЙ ЭКЗЕМПЛЯР основного кресла, а не
            # самостоятельный SKU. Общее лечение подбирало ему замену по роли и ломало контракт
            # (сеты 59/63/65/69/70/73/78 после ночной пересборки: mid у кресла и кресла 2 разные).
            # Живое основное кресло — берём его копию; основное тоже мертво — снимаем экземпляр.
            if role == 'кресло 2':
                _main = s['items'].get('кресло')
                if _main and key(_main['mid'], _main['eid']) in alive:
                    _cl = dict(_main, qty=1, alt=True,
                               pair_key=key(_main['mid'], _main['eid']), pair_provenance='exact_sku')
                    healed += 1
                    print(f'  комплект {n}: кресло 2 → экземпляр основного «{_main["name"][:32]}» (контракт пары)')
                    if apply:
                        s['items'][role] = _cl
                else:
                    hopeless.append((n, role, it['name'][:38], 'основное кресло тоже мертво'))
                    if apply:
                        s['items'].pop(role, None)
                continue
            spares = [a for a in ((s.get('alternates') or {}).get(role) or [])
                      if key(a['mid'], a['eid']) in alive]
            # В3 (владелец 07.08): снапшот запасных не видит новинок — добираем из ЖИВОГО
            # индекса кандидатов той же роли, лучшие по силе стиля сета и близости цены
            spares = spares + _live_candidates(role, it, s.get('style'), alive,
                                               exclude={key(a['mid'], a['eid']) for a in spares})
            picked = None
            for a in spares:
                if not (0.7 * it['price'] <= a.get('price', 0) <= 1.3 * it['price']):
                    continue
                cand = dict(it)
                cand.update({kk: a[kk] for kk in ('mid', 'eid', 'name', 'price') if kk in a})
                ctx = {'chosen': {r: v for r, v in s['items'].items() if r != role},
                       'wall': None,
                       'corner_sofa': 'углов' in str((s['items'].get('диван') or {}).get('name', '')).lower()}
                ok, _b, _no = prop_check(role, cand, ctx, _sub(role, cand))
                if ok:
                    picked = cand
                    break
            if picked:
                healed += 1
                print(f'  комплект {n}: {role} «{it["name"][:32]}» ({dead[k]}) → «{picked["name"][:32]}»')
                if apply:
                    s['items'][role] = picked
            else:
                hopeless.append((n, role, it['name'][:38], dead[k]))
    print(f'\nвылечено ролей: {healed}; без замены: {len(hopeless)}')
    for n, role, name, st in hopeless[:10]:
        print(f'  комплект {n}: {role} «{name}» — {st}, запаса нет → комплект скрывается')
    if apply and healed:
        shutil.copy(SETS, SETS + '.bak')
        json.dump(sets, open(SETS, 'w'), ensure_ascii=False)
        print('\nsets3.json обновлён (бэкап рядом, .bak)')
    elif not apply:
        print('\nэто был показ без изменений; применить — ключом --apply')


def main() -> None:
    if '--refresh' in sys.argv:
        refresh('--apply' in sys.argv)
    elif '--heal' in sys.argv:
        heal('--apply' in sys.argv)
    elif '--index' in sys.argv:
        build()
    elif '--check' in sys.argv:
        check()
    elif '--why' in sys.argv:
        i = sys.argv.index('--why')
        why(sys.argv[i + 1], sys.argv[i + 2])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
