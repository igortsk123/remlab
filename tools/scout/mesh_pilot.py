#!/usr/bin/env python3
"""Пилот 3D-мешей: выборка 500 товаров, постановка заданий, добор по Wilson, отчёт.

Почему не «первые 500» и не пропорционально пулу. Пилот должен ответить, для каких РОЛЕЙ
меш годится, а не просто «сколько процентов сгенерировалось». Пропорциональная выборка даёт
~30 позиций на роль — доверительный интервал ±18 п.п., на таком решение «включать ли люстры»
не принимается. Поэтому вес смещён к ролям с тонкой геометрией (люстры, бра, стулья,
торшеры, стеллажи, витрины), а простые корпуса (комод, пуф) представлены минимально: у них
исход предсказуем и тратить на них выборку незачем.

Вторая ось стратификации — СЛОЖНОСТЬ ВХОДА. 80 удобных люстр на белом фоне ничего не скажут
о 3 732 люстрах пула, поэтому внутри роли позиции разбираются по ячейкам
«материал × известны ли габариты × ракурс карточки» и берутся по кругу из всех ячеек.

Третье — стохастичность: 25 товаров прогоняются на трёх seed. Иначе неизвестно, меряем мы
способность модели или удачу одного прогона.

  ~/venvs/scout/bin/python mesh_pilot.py --sample          # собрать выборку 350 + резерв 150
  ~/venvs/scout/bin/python mesh_pilot.py --report          # состав выборки по стратам
  ~/venvs/scout/bin/python mesh_pilot.py --topup verdicts.json   # добор резерва по Wilson
"""
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, 'candidates-index.json')
SAMPLE = os.path.join(HERE, 'mesh-pilot-sample.json')

SEED = 'mesh-pilot-2026-08-28'      # фиксированный: выборка обязана быть воспроизводимой
PILOT_TOTAL = 500
STAGE1 = 350                        # заранее стратифицированная часть
RESERVE = PILOT_TOTAL - STAGE1      # добор в роли, где интервал упирается в порог решения
REPEAT_SKUS = 25                    # товаров с повтором на трёх seed
REPEAT_SEEDS = [0, 1, 2]

# Роли с тонкой/прозрачной геометрией — там исход неизвестен, туда и вес выборки.
# Люстры и бра включены по решению владельца (28.08): прежнее «подвесное не моделим» было
# ограничением Trellis, а не свойством задачи — проверяем измерением.
FOCUS_QUOTA = {'люстра': 80, 'бра': 50, 'стул': 50, 'торшер': 35, 'стеллаж': 35, 'витрина': 25}

# Остальные напольные роли — 75 мест пропорционально их реальному использованию в сетах
# (замер по sets3.json, 126 сетов: уникальных SKU на роль). Роль без спроса не нужна в пилоте.
REST_WEIGHTS = {'диван': 70, 'тв-тумба': 36, 'комод': 35, 'столик': 34, 'кресло': 30,
                'пуф': 16, 'стол обеденный': 13, 'камин': 11, 'кашпо': 10, 'стенка': 1}
REST_QUOTA = STAGE1 - sum(FOCUS_QUOTA.values())          # = 75

# Ковёр в пилот НЕ входит: это плоскость с текстурой, 3D-реконструкция ему не нужна.
# Шкаф не входит: 165 товаров есть в пуле, но `compose2.ROLES` их не запрашивает — сначала
# чинится подбор (follow-up плана), потом уже тратим на них генерации.
EXCLUDED = {'ковёр', 'ковер', 'шкаф', 'другое', 'растение', 'статуэтка', 'ваза', 'лампа',
            'плед', 'подушка', 'шторы', 'зеркало', 'полка', 'часы'}

GLASS = ('стекло', 'хрусталь', 'акрил', 'поликарбонат')
METAL = ('металл', 'сталь', 'латунь', 'алюминий', 'хром', 'железо', 'чугун')
TEXTILE = ('ткань', 'велюр', 'рогожка', 'шенилл', 'бархат', 'экокожа', 'кожа', 'жаккард')


def _rank(key: str) -> str:
    """Стабильный порядок вместо random: тот же вход — та же выборка, без состояния ГПСЧ."""
    return hashlib.sha256((SEED + '|' + key).encode()).hexdigest()


def material_class(materials: list) -> str:
    """Класс материала — главный предиктор сложности: стекло и тонкий металл ломаются чаще."""
    low = ' '.join(materials or []).lower()
    if any(g in low for g in GLASS):
        return 'стекло'
    if any(m in low for m in METAL):
        return 'металл'
    if any(t in low for t in TEXTILE):
        return 'текстиль'
    return 'корпус'


def dims_known(it: dict) -> bool:
    """Без габаритов меш нечем нормировать — и приёмка не может сверить пропорции."""
    return bool((it.get('w') or it.get('dia')) and it.get('h'))


def yaw_bucket(mid: int, eid: str) -> str:
    """Ракурс карточки: по замеру 5 420 товаров 53% сняты в три четверти, и это влияет на то,
    сколько модель вынуждена додумывать. Нет обогащения по фото — отдельная ячейка."""
    try:
        from enrich_bridge import photo_yaw
        y = photo_yaw(mid, eid)
    except Exception:  # noqa: BLE001 — нет данных: не догадываемся, помечаем честно
        y = None
    if y is None:
        return 'ракурс неизвестен'
    return 'фронт' if abs(y) < 20 else 'три четверти'


def cell(it: dict) -> str:
    return (f"{material_class(it.get('materials'))}|"
            f"{'габариты есть' if dims_known(it) else 'без габаритов'}|"
            f"{yaw_bucket(it['mid'], it['eid'])}")


def largest_remainder(weights: dict, total: int) -> dict:
    """Раздача целых мест по весам без потери суммы (метод наибольших остатков)."""
    s = sum(weights.values()) or 1
    exact = {k: v * total / s for k, v in weights.items()}
    out = {k: int(v) for k, v in exact.items()}
    left = total - sum(out.values())
    for k, _ in sorted(exact.items(), key=lambda kv: -(kv[1] - int(kv[1])))[:left]:
        out[k] += 1
    return out


def pick(pool: list, quota: int) -> list:
    """Берём по кругу из ячеек сложности, внутри ячейки — по стабильному рангу.

    Круговой обход важнее равномерности по ячейкам: если просто отсортировать, вся квота
    уйдёт в самую населённую ячейку (у люстр это «металл+стекло, габариты есть»), и про
    тканевые или безразмерные позиции пилот не скажет ничего.
    """
    cells: dict[str, list] = {}
    for it in pool:
        cells.setdefault(cell(it), []).append(it)
    for c in cells:
        cells[c].sort(key=lambda i: _rank(f"{i['mid']}:{i['eid']}"))
    order = sorted(cells, key=lambda c: (-len(cells[c]), c))
    out, i = [], 0
    while len(out) < quota and any(cells[c] for c in order):
        c = order[i % len(order)]
        if cells[c]:
            out.append(cells[c].pop(0))
        i += 1
    return out


def wilson(ok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Интервал Вильсона: на малых n и долях у края он честнее нормального приближения."""
    if n == 0:
        return 0.0, 1.0
    p = ok / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def build_sample() -> dict:
    idx = json.load(open(INDEX, encoding='utf-8'))
    items = [dict(v, key=k) for k, v in idx['items'].items()]
    by_role: dict[str, list] = {}
    for it in items:
        r = it.get('role')
        if r and r not in EXCLUDED:
            by_role.setdefault(r, []).append(it)

    quota = dict(FOCUS_QUOTA)
    rest = {r: w for r, w in REST_WEIGHTS.items() if by_role.get(r)}
    quota.update(largest_remainder(rest, REST_QUOTA))

    chosen, short = [], {}
    for role, q in quota.items():
        pool = by_role.get(role, [])
        got = pick(pool, q)
        if len(got) < q:
            short[role] = {'нужно': q, 'есть в пуле': len(pool)}
        chosen += got

    # Повторы на трёх seed — по кругу ролей, чтобы стохастичность мерялась не на одних диванах
    chosen.sort(key=lambda i: _rank(f"repeat|{i['mid']}:{i['eid']}"))
    seen_roles: dict[str, int] = {}
    repeats = []
    for it in chosen:
        if len(repeats) >= REPEAT_SKUS:
            break
        r = it['role']
        if seen_roles.get(r, 0) < 2:      # не более двух повторов на роль
            seen_roles[r] = seen_roles.get(r, 0) + 1
            repeats.append(f"{it['mid']}:{it['eid']}")
    rep = set(repeats)

    jobs = []
    for it in chosen:
        pid = f"{it['mid']}:{it['eid']}"
        jobs.append({
            'sku': pid, 'mid': it['mid'], 'eid': it['eid'], 'role': it['role'],
            'subtype': it.get('subtype'), 'name': it['name'], 'shop': it['shop'],
            'image_url': it['img'], 'product_url': it['url'],
            'dims_cm': {'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'),
                        'dia': it.get('dia')},
            'strata': {'role': it['role'], 'material': material_class(it.get('materials')),
                       'dims_known': dims_known(it), 'yaw': yaw_bucket(it['mid'], it['eid'])},
            'seeds': REPEAT_SEEDS if pid in rep else [0],
        })

    out = {'seed': SEED, 'stage1': len(jobs), 'reserve': RESERVE,
           'generations': sum(len(j['seeds']) for j in jobs),
           'quota': quota, 'short': short, 'repeat_skus': sorted(rep), 'jobs': jobs}
    json.dump(out, open(SAMPLE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out


def report(s: dict) -> None:
    print(f"выборка: {s['stage1']} товаров, {s['generations']} генераций "
          f"(из них {len(s['repeat_skus'])} SKU × 3 seed); резерв {s['reserve']}")
    if s['short']:
        print(f"НЕ ХВАТИЛО В ПУЛЕ: {s['short']}")
    print(f"\n{'роль':16s} {'квота':>5s}  ячейки сложности")
    for role in sorted(s['quota'], key=lambda r: -s['quota'][r]):
        js = [j for j in s['jobs'] if j['role'] == role]
        cells: dict[str, int] = {}
        for j in js:
            k = f"{j['strata']['material']}/{'габ' if j['strata']['dims_known'] else 'без габ'}"
            cells[k] = cells.get(k, 0) + 1
        line = ', '.join(f'{k} {v}' for k, v in sorted(cells.items(), key=lambda kv: -kv[1]))
        print(f'{role:16s} {len(js):5d}  {line}')


def topup(verdicts_path: str) -> None:
    """Резерв 150 — в роли, где интервал Вильсона ПЕРЕСЕКАЕТ порог решения.

    Порог 0.60: ниже — роль в массовый прогон не берём. Пока интервал накрывает порог, мы не
    знаем, по какую он сторону, и добор именно туда, а не размазывание по простым ролям.
    """
    THRESHOLD = 0.60
    v = json.load(open(verdicts_path, encoding='utf-8'))
    s = json.load(open(SAMPLE, encoding='utf-8'))
    stat: dict[str, list] = {}
    for job in s['jobs']:
        r = job['role']
        st = stat.setdefault(r, [0, 0])
        res = v.get(job['sku'])
        if res is None:
            continue
        st[1] += 1
        st[0] += 1 if res == 'web_ready' else 0
    need = {}
    for role, (ok, n) in stat.items():
        lo, hi = wilson(ok, n)
        crosses = lo <= THRESHOLD <= hi
        print(f'{role:16s} {ok:3d}/{n:3d} = {ok / max(n, 1):.0%}  CI [{lo:.0%}, {hi:.0%}]'
              f'{"  ← неопределённо, добираем" if crosses else ""}')
        if crosses:
            need[role] = hi - lo                  # шире интервал — больше добор
    if not need:
        print(f'\nвсе роли определены относительно порога {THRESHOLD:.0%} — резерв не нужен')
        return
    add = largest_remainder(need, s['reserve'])
    print(f'\nдобор резерва {s["reserve"]}: {add}')


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
