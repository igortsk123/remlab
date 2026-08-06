#!/usr/bin/env python3
"""Пересчёт стилевой машины по ВСЕМУ каталогу — после полного прогона обогащения.

До сих пор частоты признаков и статистика считались по тестовым выборкам (671 карточка). Когда
обогащение проходит по всем 25 тысячам, всё это надо пересчитать на реальных данных: частота
признака внутри категории определяет, что считать маркером, а от неё зависят все ранги.

Порядок: частоты по категориям → пересборка таблицы → распределение стилей по каталогу.

  ~/venvs/scout/bin/python style_recalc.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def freq_by_category() -> dict:
    """Частота каждого признака ВНУТРИ категории — по всему обогащённому каталогу."""
    r = subprocess.run(PSQL, capture_output=True, text=True, input="""
        select p.cat_role, e.payload->'model'->>'photo', e.payload->'model'->>'specific',
               e.payload->'model'->>'materials', e.payload->'model'->>'primary_color'
          from product_enrichment e join products p using (shop_mid, external_id)
         where e.payload is not null and p.cat_role is not null
    """)
    cnt: dict[str, int] = {}
    tot: dict[str, int] = {}
    for line in r.stdout.split('\n'):
        f = line.split('\x1f')
        if len(f) < 5 or not f[0]:
            continue
        role = f[0]
        tot[role] = tot.get(role, 0) + 1
        obs = {}
        for raw in (f[1], f[2]):
            try:
                obs.update(json.loads(raw) if raw else {})
            except json.JSONDecodeError:
                pass
        if f[4]:
            obs['primary_color'] = f[4]
        for a, v in obs.items():
            if v in ('не_видно', 'неясно', 'не_применимо', 'не_определён', None):
                continue
            cnt[f'{role}|{a}={v}'] = cnt.get(f'{role}|{a}={v}', 0) + 1
        try:
            for m in json.loads(f[3] or '[]'):
                cnt[f'{role}|materials={m}'] = cnt.get(f'{role}|materials={m}', 0) + 1
        except json.JSONDecodeError:
            pass
    out = {k: round(n / max(tot[k.split('|')[0]], 1), 4) for k, n in cnt.items()}
    out['_totals'] = tot
    json.dump(out, open(os.path.join(HERE, 'attr-freq-cat.json'), 'w'), ensure_ascii=False)
    print(f'частоты пересчитаны: {sum(tot.values())} товаров, {len(tot)} категорий')
    return out


def distribution() -> None:
    """Как распределились стили по всему каталогу — и сколько нейтральных."""
    import style_attrs as SA
    cache = SA.EB.load()
    tops: dict[str, int] = {}
    neu = 0
    total = 0
    byrole: dict[str, dict] = {}
    for key in cache:
        sc = SA.scores(*key.split(':', 1))
        if not sc:
            continue
        total += 1
        role = (cache[key].get('role') or '—')
        r = byrole.setdefault(role, {'n': 0, 'neu': 0, 'top': {}})
        r['n'] += 1
        if sc.get('neutral'):
            neu += 1
            r['neu'] += 1
            continue
        vals = {s: sc[s] for s in SA.STYLES}
        t = max(vals, key=vals.get)
        tops[t] = tops.get(t, 0) + 1
        r['top'][t] = r['top'].get(t, 0) + 1
    print(f'\nтоваров с оценкой: {total}; нейтральных {neu} ({neu / max(total, 1) * 100:.0f}%)')
    s = sum(tops.values()) or 1
    print('стили среди остальных: ' + ', '.join(
        f'{k} {v} ({v / s * 100:.0f}%)' for k, v in sorted(tops.items(), key=lambda kv: -kv[1])))
    print(f'\n{"категория":16s} {"всего":>7} {"нейтр":>7}  преобладает')
    for role, r in sorted(byrole.items(), key=lambda kv: -kv[1]['n']):
        top = ', '.join(f'{k} {v}' for k, v in sorted(r['top'].items(), key=lambda kv: -kv[1])[:2])
        print(f'{role:16s} {r["n"]:>7} {r["neu"]:>7}  {top or "—"}')


def main() -> None:
    freq_by_category()
    subprocess.run([sys.executable, os.path.join(HERE, 'matrix_build.py'), '--build'],
                   capture_output=True, text=True)
    print('таблица «категория × признак» пересобрана на реальных частотах')
    distribution()


if __name__ == '__main__':
    main()
