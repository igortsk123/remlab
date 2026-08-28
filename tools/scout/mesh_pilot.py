#!/usr/bin/env python3
"""Пилот 3D-мешей: выборка ПО НАШИМ СЕТАМ, постановка заданий, добор по Wilson, отчёт.

ПРИНЦИП ВЫБОРКИ (решение владельца 28.08): берём все товары из всех 126 сетов, чтобы каждый
сет был укомплектован ЦЕЛИКОМ. Тогда пилот отвечает на практический вопрос — соберётся ли
живая комната в 3D, — а не только на статистический «какой процент годных по ролям».

Прежний вариант (стратифицированная выборка со смещением к тонкой геометрии) отброшен
сознательно, и вот чем за это платим: сеты — это верхушка каталога, композитор берёт лучших
по скорингу. Значит измеренный процент годных будет ОПТИМИСТИЧНЕЕ, чем на всём пуле 11 631,
и переносить его на полный прогон напрямую нельзя. Зато половинчатых комнат не будет:
один непригодный меш ломает демонстрацию целого сета, и это надо видеть.

Что исключено из выборки и почему:
  * подушки, пледы, покрывала — мягкий декор снимают на белом фоне «в наборе», его рисует
    модель по фото (`viz_paste.SOFT`), 3D-реконструкция ему не нужна;
  * ковры — плоскость с текстурой, меш не нужен по существу.
Люстры и бра ВКЛЮЧЕНЫ (решение владельца): прежнее «подвесное не моделим» было ограничением
Trellis, проверяем измерением.

  ~/venvs/scout/bin/python mesh_pilot.py --sample          # собрать выборку из сетов
  ~/venvs/scout/bin/python mesh_pilot.py --report          # состав выборки
  ~/venvs/scout/bin/python mesh_pilot.py --topup verdicts.json   # добор по Wilson
"""
import hashlib
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, 'candidates-index.json')
SETS = os.path.join(HERE, 'sets3.json')
SAMPLE = os.path.join(HERE, 'mesh-pilot-sample.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

SEED = 'mesh-pilot-2026-08-28'
REPEAT_SKUS = 25                    # товаров с повтором на трёх seed — замер стохастичности
REPEAT_SEEDS = [0, 1, 2]

# Роли, которым 3D-реконструкция не нужна по существу (см. docstring)
SKIP_ROLES = {'подушка', 'плед', 'покрывало', 'ковёр', 'ковер'}

GLASS = ('стекло', 'хрусталь', 'акрил', 'поликарбонат')
METAL = ('металл', 'сталь', 'латунь', 'алюминий', 'хром', 'железо', 'чугун')
TEXTILE = ('ткань', 'велюр', 'рогожка', 'шенилл', 'бархат', 'экокожа', 'кожа', 'жаккард')


def _rank(key: str) -> str:
    """Стабильный порядок вместо random: тот же вход — та же выборка."""
    return hashlib.sha256((SEED + '|' + key).encode()).hexdigest()


def material_class(materials: list) -> str:
    low = ' '.join(materials or []).lower()
    if any(g in low for g in GLASS):
        return 'стекло'
    if any(m in low for m in METAL):
        return 'металл'
    if any(t in low for t in TEXTILE):
        return 'текстиль'
    return 'корпус'


def dims_known(it: dict) -> bool:
    return bool((it.get('w') or it.get('dia')) and it.get('h'))


def yaw_bucket(mid: int, eid: str) -> str:
    """Ракурс карточки — не ось отбора, а ДИАГНОСТИКА: по нему потом смотрим, где генератор
    ошибается чаще. По замеру 5 420 товаров 53% сняты в три четверти."""
    try:
        from enrich_bridge import photo_yaw
        y = photo_yaw(mid, eid)
    except Exception:  # noqa: BLE001 — нет обогащения: помечаем честно, не догадываемся
        y = None
    if y is None:
        return 'ракурс неизвестен'
    return 'фронт' if abs(y) < 20 else 'три четверти'


def from_db(pids: list[str]) -> dict:
    """Товары, которых нет в индексе кандидатов.

    Индекс пересобирается по расписанию, а сеты живут дольше: часть позиций из сетов успела
    выпасть из пула (кончился остаток, состарилось фото). Для ПИЛОТА это неважно — нам нужен
    меш товара, который стоит в сете, а не его текущая пригодность к подбору. Поэтому
    недостающие карточки берём напрямую из БД, а не выбрасываем позиции и не рвём сеты.
    """
    if not pids:
        return {}
    vals = ','.join(f"({p.split(':')[0]},'{p.split(':')[1]}')" for p in pids)
    q = f"""
      with want(mid, eid) as (values {vals})
      select p.shop_mid||':'||p.external_id, p.name, p.shop, p.image_url,
             coalesce(p.direct_url, p.url),
             coalesce(p.w_cm,0), coalesce(p.d_cm,0), coalesce(p.h_cm,0), coalesce(p.dia_cm,0),
             coalesce(e.payload->'model'->>'role',''),
             coalesce(e.payload->'model'->>'materials','[]')
        from products p join want w on w.mid=p.shop_mid and w.eid=p.external_id
        left join product_enrichment e
               on e.shop_mid=p.shop_mid and e.external_id=p.external_id
       where p.image_url is not null
    """
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'БД недоступна, {len(pids)} позиций возьмём без метаданных: {r.stderr[:200]}')
        return {}
    out = {}
    for line in r.stdout.strip().split('\n'):
        if not line:
            continue
        f = line.split('\x1f')
        w, d, h, dia = (float(x) for x in f[5:9])
        out[f[0]] = {'name': f[1], 'shop': f[2], 'img': f[3], 'url': f[4],
                     'w': w or None, 'd': d or None, 'h': h or None, 'dia': dia or None,
                     'role': f[9] or None,
                     'materials': json.loads(f[10]) if f[10] else []}
    return out


def build_sample() -> dict:
    sets = json.load(open(SETS, encoding='utf-8'))
    idx = json.load(open(INDEX, encoding='utf-8'))['items']

    order: list[str] = []                 # порядок первого появления — стабильный
    role_of: dict[str, str] = {}
    sets_map: list[dict] = []
    for n, s in enumerate(sets):
        ids = []
        for role, v in (s.get('items') or {}).items():
            if not isinstance(v, dict) or 'mid' not in v:
                continue
            base = role.split(' ')[0]     # «кресло 3» → «кресло»
            if base in SKIP_ROLES:
                continue
            pid = f"{v['mid']}:{v['eid']}"
            role_of.setdefault(pid, base)
            if pid not in role_of or pid not in order:
                order.append(pid)
            ids.append(pid)
        sets_map.append({'set': n, 'style': s.get('style'), 'm2': s.get('m2'),
                         'tier': s.get('tier'), 'skus': sorted(set(ids))})

    order = list(dict.fromkeys(order))
    extra = from_db([p for p in order if p not in idx])

    jobs, missing = [], []
    for pid in order:
        it = idx.get(pid) or extra.get(pid)
        if not it or not it.get('img'):
            missing.append(pid)           # без фото задание ставить не на что
            continue
        jobs.append({
            'sku': pid, 'mid': int(pid.split(':')[0]), 'eid': pid.split(':')[1],
            'role': role_of.get(pid) or it.get('role'), 'subtype': it.get('subtype'),
            'name': it.get('name'), 'shop': it.get('shop'),
            'image_url': it['img'], 'product_url': it.get('url'),
            'dims_cm': {'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                        'dia': it.get('dia')},
            'strata': {'role': role_of.get(pid), 'material': material_class(it.get('materials')),
                       'dims_known': dims_known(it),
                       'yaw': yaw_bucket(int(pid.split(':')[0]), pid.split(':')[1]),
                       'from_index': pid in idx},
            'seeds': [0],
        })

    # Повторы на трёх seed — по кругу ролей, чтобы стохастичность мерялась не на одних диванах
    have = {j['sku'] for j in jobs}
    pool = sorted(have, key=lambda p: _rank(f'repeat|{p}'))
    per_role: dict[str, int] = {}
    rep = []
    for pid in pool:
        if len(rep) >= REPEAT_SKUS:
            break
        r = role_of.get(pid, '?')
        if per_role.get(r, 0) < 2:
            per_role[r] = per_role.get(r, 0) + 1
            rep.append(pid)
    for j in jobs:
        if j['sku'] in set(rep):
            j['seeds'] = REPEAT_SEEDS

    # Полнота сетов — главный критерий этой выборки: сет считается покрытым, только если
    # ВСЕ его предметы под меш попали в задания. Половина комнаты бесполезна.
    full = sum(1 for s in sets_map if s['skus'] and all(p in have for p in s['skus']))

    out = {'seed': SEED, 'source': 'sets3.json', 'sets_total': len(sets_map),
           'sets_full': full, 'skus': len(jobs), 'missing': missing,
           'generations': sum(len(j['seeds']) for j in jobs),
           'repeat_skus': sorted(rep), 'sets': sets_map, 'jobs': jobs}
    json.dump(out, open(SAMPLE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


def report(s: dict) -> None:
    import collections
    print(f"источник: {s.get('source')} | товаров {s['skus']} | генераций {s['generations']} "
          f"(из них {len(s['repeat_skus'])} SKU × 3 seed)")
    print(f"сетов укомплектовано ПОЛНОСТЬЮ: {s['sets_full']} из {s['sets_total']}")
    if s['missing']:
        print(f"без фото, в задания не пошли: {len(s['missing'])} — сеты с ними будут неполными")
    print(f"\n{'роль':16s} {'шт':>4s}")
    for r, n in collections.Counter(j['role'] for j in s['jobs']).most_common():
        print(f'{r:16s} {n:4d}')
    print('\nдиагностика входа (не ось отбора — по ней потом смотрим, где генератор ошибается):')
    for k in ('material', 'yaw'):
        print(f"  {k}: {dict(collections.Counter(j['strata'][k] for j in s['jobs']))}")
    d = collections.Counter('габариты есть' if j['strata']['dims_known'] else 'без габаритов'
                            for j in s['jobs'])
    print(f'  {dict(d)}')
    ni = sum(1 for j in s['jobs'] if not j['strata']['from_index'])
    if ni:
        print(f'  добраны из БД (выпали из пула кандидатов, но стоят в сетах): {ni}')


def wilson(ok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Интервал Вильсона: на малых n и долях у края он честнее нормального приближения."""
    if n == 0:
        return 0.0, 1.0
    p = ok / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def topup(verdicts_path: str) -> None:
    """Что докупать после первого прогона.

    Два разных вопроса, и оба нужны:
      * какие СЕТЫ развалились — там достаточно перегенерировать конкретные позиции;
      * какие РОЛИ остались неопределёнными относительно порога 60% — там нужен добор,
        иначе решение о полном прогоне будет приниматься на интервале шириной в треть.
    """
    THRESHOLD = 0.60
    v = json.load(open(verdicts_path, encoding='utf-8'))
    s = json.load(open(SAMPLE, encoding='utf-8'))
    ok_skus = {k for k, r in v.items() if r == 'web_ready'}

    broken = [x for x in s['sets']
              if x['skus'] and not all(p in ok_skus for p in x['skus'])]
    print(f"сетов собирается целиком: {s['sets_total'] - len(broken)} из {s['sets_total']}")
    if broken:
        holes: dict[str, int] = {}
        for x in broken:
            for p in x['skus']:
                if p not in ok_skus:
                    role = next((j['role'] for j in s['jobs'] if j['sku'] == p), '?')
                    holes[role] = holes.get(role, 0) + 1
        print(f'  чем пробиты: {dict(sorted(holes.items(), key=lambda kv: -kv[1]))}')

    print('\nроли относительно порога годности 60%:')
    stat: dict[str, list] = {}
    for job in s['jobs']:
        st = stat.setdefault(job['role'], [0, 0])
        res = v.get(job['sku'])
        if res is None:
            continue
        st[1] += 1
        st[0] += 1 if res == 'web_ready' else 0
    need = {}
    for role, (ok, n) in sorted(stat.items(), key=lambda kv: -kv[1][1]):
        lo, hi = wilson(ok, n)
        crosses = lo <= THRESHOLD <= hi
        print(f'  {role:16s} {ok:3d}/{n:3d} = {ok / max(n, 1):.0%}  CI [{lo:.0%}, {hi:.0%}]'
              f'{"  ← неопределённо" if crosses else ""}')
        if crosses:
            need[role] = hi - lo
    if need:
        print(f'\nдобор нужен в: {dict(sorted(need.items(), key=lambda kv: -kv[1]))}')


def main() -> None:
    if '--sample' in sys.argv:
        report(build_sample())
    elif '--report' in sys.argv:
        report(json.load(open(SAMPLE, encoding='utf-8')))
    elif '--topup' in sys.argv:
        topup(sys.argv[sys.argv.index('--topup') + 1])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
