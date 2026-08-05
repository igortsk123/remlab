#!/usr/bin/env python3
"""Золотая выборка: несколько сотен товаров, на которых меряют модели.

Смысл — не «взять случайные 300», а покрыть трудные места: спорные роли (пуф, столик, комод),
карточки без описания, товары с дырами в размерах, все три ценовые ступени. Модель, которая
хорошо работает на диванах с полным описанием, может разваливаться ровно там, где нам больно.

Выборка детерминированная: сортировка по идентификатору и равномерный шаг, без случайности —
иначе повторный прогон даёт другой набор и метрики нельзя сравнивать между собой.

  ~/venvs/scout/bin/python golden_build.py            # собрать golden.json
  ~/venvs/scout/bin/python golden_build.py --show     # показать распределение
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'golden.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

# роль → сколько берём. Спорные роли (подтип решает правила размеров) — с запасом.
QUOTA = {'пуф': 30, 'столик': 30, 'комод': 25, 'диван': 20, 'кресло': 18, 'стеллаж': 18,
         'тв-тумба': 15, 'торшер': 15, 'ковёр': 12, 'кашпо': 15, 'лампа': 15, 'люстра': 15,
         'ваза': 12, 'плед': 10, 'подушка': 10}
TIERS = ('эконом', 'комфорт', 'премиум')


def rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def fetch(role: str) -> list[dict]:
    """Все живые кандидаты роли с полями, которые получит модель."""
    q = f"""
    select l.shop_mid, l.external_id, l.name, coalesce(p.description,''), l.category_path,
           coalesce(l.price_rub,0), coalesce(l.w_cm,0), coalesce(l.d_cm,0), coalesce(l.h_cm,0),
           coalesce(l.dia_cm,0), coalesce(p.params::text,'{{}}'), l.shop, coalesce(l.image_url,'')
      from lr_roles l join products p using (shop_mid, external_id)
     where l.role = '{role}' and p.in_stock and l.price_rub is not null
     order by l.shop_mid, l.external_id
    """
    out = []
    for r in rows(q):
        out.append(dict(mid=int(r[0]), eid=r[1], name=r[2], desc=r[3][:900], cat=r[4],
                        price=int(r[5]), w=float(r[6]) or None, d=float(r[7]) or None,
                        h=float(r[8]) or None, dia=float(r[9]) or None,
                        params=json.loads(r[10]), shop=r[11], img=r[12], role_feed=role))
    return out


def strata(items: list[dict]) -> dict:
    """Ценовая ступень по перцентилям своей роли — та же логика, что и в сборщике комплектов."""
    ps = sorted(x['price'] for x in items)

    def pc(p):
        return ps[max(0, min(len(ps) - 1, int(p * len(ps))))]
    lo, hi = pc(0.33), pc(0.75)
    out = {t: [] for t in TIERS}
    for it in items:
        t = 'эконом' if it['price'] < lo else ('комфорт' if it['price'] < hi else 'премиум')
        it['tier'] = t
        it['hard'] = (not it['desc']) or not (it['w'] and it['h'])   # трудная карточка
        out[t].append(it)
    return out


def pick(items: list[dict], n: int) -> list[dict]:
    """Равномерный шаг по отсортированному списку: детерминированно и без перекоса по магазину."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def main() -> None:
    if '--show' in sys.argv and os.path.exists(OUT):
        g = json.load(open(OUT))
        by_role: dict = {}
        for it in g:
            b = by_role.setdefault(it['role_feed'], {'всего': 0, 'трудных': 0, **{t: 0 for t in TIERS}})
            b['всего'] += 1
            b['трудных'] += bool(it['hard'])
            b[it['tier']] += 1
        print(f'{"роль":10s} {"всего":>6} {"трудных":>8} {"эконом":>7} {"комфорт":>8} {"премиум":>8}')
        for role, b in sorted(by_role.items(), key=lambda kv: -kv[1]['всего']):
            print(f'{role:10s} {b["всего"]:>6} {b["трудных"]:>8} {b["эконом"]:>7} '
                  f'{b["комфорт"]:>8} {b["премиум"]:>8}')
        print(f'\nвсего в выборке: {len(g)}')
        return

    golden = []
    for role, quota in QUOTA.items():
        items = fetch(role)
        if not items:
            print(f'{role}: в каталоге нет — пропуск')
            continue
        st = strata(items)
        # половину квоты отдаём трудным карточкам, остальное делим по ступеням
        hard = [x for x in items if x['hard']]
        easy = [x for x in items if not x['hard']]
        take = pick(hard, quota // 2) + pick(easy, quota - quota // 2)
        seen = set()
        uniq = []
        for it in take:
            k = (it['mid'], it['eid'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(it)
        golden.extend(uniq)
        print(f'{role}: кандидатов {len(items)}, взято {len(uniq)} '
              f'(трудных {sum(1 for x in uniq if x["hard"])})')
    json.dump(golden, open(OUT, 'w'), ensure_ascii=False)
    print(f'\nзолотая выборка: {len(golden)} товаров → {OUT}')


if __name__ == '__main__':
    main()
