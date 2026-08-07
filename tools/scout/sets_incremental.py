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
        for role, it in list(s['items'].items()):
            k = key(it['mid'], it['eid'])
            if k not in dead:
                continue
            spares = [a for a in ((s.get('alternates') or {}).get(role) or [])
                      if key(a['mid'], a['eid']) in alive]
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
    if '--heal' in sys.argv:
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
