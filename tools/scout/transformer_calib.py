#!/usr/bin/env python3
"""Подбор коэффициентов правила трансформера (`dim_resolver.TRANSFORMER_COEF`) — catalog-holes-bank Н3, 23.10.

Источник — доказанные трансформеры divan.ru (у них в фиде и спальное место, и собранные габариты). Классификация
типа и «как лежит место» — та же, что у правила (`dim_resolver.transformer_dims`), иначе коэффициенты не про то.
Коэффициент = квантиль 0,75 (ошибка — скорее в «больше»: у расстановки допуск +10/−20 %, главное — чтобы влезло).
Печатает таблицу коэффициентов, ошибку на той же выборке и расхождение с зашитыми в правило. БД только читает.

    ~/venvs/scout/bin/python tools/scout/transformer_calib.py          # REMLAB_DEVDB_NAME — другая база
"""
import os
import re
import subprocess
from collections import defaultdict

import dim_resolver as R

DIVAN = 112923
Q = 0.75
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
        '-v', 'ON_ERROR_STOP=1', '-q', '-t', '-A', '-F', '\t']
SQL = f"""set default_transaction_read_only = on;
select cat_role, coalesce(params->>'Механизм трансформации',''), params->>'Спальное место: Ширина спального места',
       params->>'Спальное место: Длина спального места', params->>'Размеры: Длина габаритная',
       coalesce(params->>'Размеры: Ширина габаритная', params->>'Размеры: Глубина габаритная'),
       params->>'Размеры: Высота габаритная', name
  from products where shop_mid={DIVAN} and status='active' and cat_role in ('диван','кресло')
   and params ? 'Спальное место: Ширина спального места'"""


def _num(v):
    return float(re.sub(r'[^\d.,]', '', v).replace(',', '.')) if v and re.search(r'\d', v) else None


def _q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def rows():
    out = subprocess.run(PSQL, input=SQL, capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        p = line.split('\t')
        if len(p) < 8:
            continue
        role, mech, *nums, name = p[0], p[1], *p[2:7], p[7]
        sw, sl, front, depth, h = map(_num, nums)
        if not (sw and sl and front and depth and h) or R.NOT_TRANSFORMER.match(mech):
            continue
        sw, sl = sorted((sw, sl))
        typ = 'кресло' if (role == 'кресло' or re.search(r'кресло', name, re.I)) else \
              'угловой' if R._CORNER.search(name) else 'прямой'
        orient = 'вперёд' if typ == 'кресло' or any(k in mech.lower() for k in R.FORWARD_MECH) else 'вдоль'
        yield typ, orient, sw, sl, front, depth, h


def main():
    data = list(rows())
    groups = defaultdict(list)
    for r in data:
        groups[r[:2]].append(r)
    print(f'divan.ru: трансформеров с местом и габаритами — {len(data)}; квантиль {Q}')
    print(f'{"тип/место":18} {"n":>4} | прибавка Г/сторона  В | зашито в правило | ошибка: недооценка >10 % / переоценка >20 % (Ш, Г, В)')
    for key in sorted(groups):
        g = groups[key]
        if len(g) < 5:
            continue
        add = _q([fr - (sl if key[1] == 'вдоль' else sw) for _, _, sw, sl, fr, _, _ in g], Q)
        d, h = _q([r[5] for r in g], Q), _q([r[6] for r in g], Q)
        errs = []
        for i, (est, true) in enumerate(((lambda r: (r[3] if key[1] == 'вдоль' else r[2]) + add, 4), (lambda r: d, 5),
                                         (lambda r: h, 6))):
            e = [(est(r) - r[true]) / r[true] for r in g]
            errs.append(f'{sum(x < -.1 for x in e) / len(e):.0%}/{sum(x > .2 for x in e) / len(e):.0%}')
        coded = R.TRANSFORMER_COEF.get(key)
        drift = '' if coded == (add, d, h) else '  ← расходится'
        print(f'{key[0] + "/" + key[1]:18} {len(g):4} | {add:6.0f} {d:6.0f} {h:4.0f} | {coded}{drift} | {"  ".join(errs)}')


if __name__ == '__main__':
    main()
