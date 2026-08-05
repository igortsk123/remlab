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


def main() -> None:
    if '--index' in sys.argv:
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
