#!/usr/bin/env python3
"""Глубина по роли и ФОРМЕ — там, где фид её не присылает вовсе (ярус 3 плана dims-round-objects).

ЗАЧЕМ. Два крупных магазина (114667, 114082) не присылают глубину НИ В КАКОМ поле: у них только
«Высота» и «Ширина» (у 114667 ещё «Ширина спального места» и чертёж картинкой). Это ~900 диванов,
которым меш сделать можно, а честно расставить нельзя: солвер ставит предмет к стене и считает
вылет в комнату. Правило осей тут не поможет — нечего отображать, данных нет.

ПОЧЕМУ НЕ ИЗ МЕША. Гипотеза владельца (03.09, `mesh_dims.py`) геометрически верна, но калибровка
дала `verdict: false`: на 38 прямых диванах с известной глубиной в пределах 10 % попали лишь 36,8 %,
грубых промахов >20 % — 31,6 %. Причина физическая: каталожное фото фронтальное, и глубина — ровно
та ось, которую с него не видно; меш её достраивает догадкой. Поэтому меш оставлен как есть, а
здесь — другой источник.

ИДЕЯ. Глубина мебели определяется НЕ моделью, а типом предмета: комод 40–50, тумба 40–50,
стеллаж 31–40, кресло 75–100. Диван — исключение: 72–179, потому что в одну роль свалены прямые и
угловые. Но форма написана в названии, и тогда разброс схлопывается:
    прямой  86 / 98 / 115 (p10/медиана/p90), n=568
    угловой 146 / 160 / 178,                 n=271
    без пометки 40 / 110 / 272 — СЮДА НЕ ЛЕЗЕМ (две разные вещи в одной группе).

ЧЕСТНОСТЬ. Считаем по товарам, у которых глубина ПРИШЛА ИЗ ФИДА (не от приора и не из меша) —
это 5 883 наблюдения, а не 38. Группа применяется только если прошла гейт: n ≥ MIN_N и
относительный разброс (p90−p10)/медиана ≤ SPREAD_MAX. Берём p75, а не медиану: недооценить
глубину опаснее, чем переоценить — заниженная ставит диван в проход, завышенная лишь не даст
встать там, где он и так еле влезал.

БЕРЁМ МЕДИАНУ, А НЕ p75 — ЭТО ЗАМЕР, НЕ РАССУЖДЕНИЕ. Сперва я выбрал p75 из логики «недооценить
глубину опаснее». Сравнение на ТЕХ ЖЕ 38 диванах, на которых провалилась калибровка меша:
    меш           медиана ошибки 12,9 %, в пределах 10 % — 37 %, промахов >20 % — 32 %
    приор p75     10,2 %, 47 %, 11 %
    приор медиана  8,9 %, 71 %,  8 %   ← берём это
То есть приор по роли и форме ВДВОЕ точнее меша и даёт в четыре раза меньше грубых промахов, а
медиана заметно точнее p75. p90 остаётся в провенансе: потребителю, которому нужен запас на
коллизии, есть откуда его взять, не портя саму оценку.

Провенанс — `dims_evidence.d = {source:'role_prior', role, shape, p10, median, p75, p90, n,
spread, confidence}`. Пишем ТОЛЬКО там, где `d_cm is null`; измеренное сильнее инференса
(authority по оси), поэтому `load3` выведенную глубину не затирает, пока фид не даст свою.

  dim_prior.py --calibrate   # замер по ролям×формам, вердикт по каждой группе → dim-priors.json
  dim_prior.py --apply       # записать глубину прошедшим гейт (только где её нет)
  dim_prior.py --report
  dim_prior.py --selftest
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'dim-priors.json')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-v', 'ON_ERROR_STOP=1', '-q', '-t', '-A', '-F', '\t']
MIN_N = int(os.environ.get('DIM_PRIOR_MIN_N', '30'))
# 0.45, а не 0.35: шкаф даёт 0.40 (40/50/60) и это физично — шкафы действительно 40–60 см глубиной.
# Порог 0.45 пропускает прямой диван (0.30), угловой (0.20), кресло (0.29), комод (0.23),
# тумбу (0.24), стеллаж (0.26), шкаф (0.40) и отвергает пуф (1.12), столик (1.02) и диван без
# пометки формы (2.11) — то есть ровно те группы, где в одну роль свалены разные предметы.
SPREAD_MAX = float(os.environ.get('DIM_PRIOR_SPREAD_MAX', '0.45'))
# Форма пишется в названии. Порядок проверки ВАЖЕН: «п-образный» содержит «образн», а угловой
# модуль часто зовётся и «угловой», и «с оттоманкой» — сначала самое специфичное.
SHAPES = (
    ('П-образный', re.compile(r'п-?образн', re.I)),
    ('угловой', re.compile(r'углов|оттоманк|шезлонг', re.I)),
    ('прямой', re.compile(r'прям', re.I)),
)
# Роли, у которых форма расщепляет группу. Остальным хватает самой роли.
SHAPED_ROLES = frozenset({'диван'})


def db(sql: str) -> list[list[str]]:
    try:
        r = subprocess.run(PSQL, input=sql, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'база не опрошена: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(2)
    if r.returncode != 0:
        print(r.stderr[:400], file=sys.stderr)
        sys.exit(2)
    return [ln.split('\t') for ln in r.stdout.strip().split('\n') if ln]


def shape_of(role: str, name: str) -> str:
    """Форма предмета из названия. Для ролей без расщепления — пустая строка."""
    if role not in SHAPED_ROLES:
        return ''
    for tag, rx in SHAPES:
        if rx.search(name or ''):
            return tag
    return ''          # без пометки — отдельная группа, её гейт не пропустит


def gate(n: int, p10: float, p75: float, p90: float, med: float) -> tuple[bool, float, str]:
    """Можно ли применять группу. Возвращает (можно, разброс, причина отказа)."""
    if n < MIN_N:
        return (False, 0.0, f'мало наблюдений ({n} < {MIN_N})')
    if not med:
        return (False, 0.0, 'медиана нулевая')
    spread = (p90 - p10) / med
    if spread > SPREAD_MAX:
        return (False, spread, f'разброс {spread:.2f} > {SPREAD_MAX} — в группе разные предметы')
    return (True, spread, '')


def calibrate() -> dict:
    """Замер по (роль, форма) на товарах, чья глубина ПРИШЛА ИЗ ФИДА."""
    # НАЗВАНИЕ — ПОСЛЕДНЕЙ КОЛОНКОЙ (11.10): в названиях товаров встречается табуляция, а вывод
    # psql разбирается по табам. Стояло бы `name` в середине — сдвинулась бы сама глубина, и
    # калибровка соврала бы молча (поймано падением на распаковке).
    rows = db("""
      select coalesce(cat_role,''), d_cm, replace(name, chr(9), ' ')
        from products
       where in_stock and d_cm is not null and cat_role is not null
         and coalesce(dims_evidence->'d'->>'source','feed') not in ('role_prior','mesh_ratio')
    """)
    groups: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        if len(r) < 3:
            continue
        role, d, name = r[0], r[1], ' '.join(r[2:])
        try:
            val = float(d)
        except ValueError:
            continue
        groups.setdefault((role, shape_of(role, name)), []).append(val)

    def pct(xs: list[float], q: float) -> float:
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(q * len(xs)))]

    out = {}
    for (role, shape), xs in sorted(groups.items()):
        n = len(xs)
        p10, med, p75, p90 = pct(xs, 0.10), pct(xs, 0.50), pct(xs, 0.75), pct(xs, 0.90)
        ok, spread, why = gate(n, p10, p75, p90, med)
        out[f'{role}|{shape}'] = {'role': role, 'shape': shape, 'n': n, 'p10': p10,
                                  'median': med, 'p75': p75, 'p90': p90,
                                  'spread': round(spread, 3), 'apply': ok, 'why': why}
    return out


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    if '--calibrate' in sys.argv:
        cal = calibrate()
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'min_n': MIN_N, 'spread_max': SPREAD_MAX, 'groups': cal}, f,
                      ensure_ascii=False, indent=1)
        print(f'{"роль / форма":28}{"n":>6}{"p10":>6}{"мед":>6}{"p75":>6}{"p90":>6}{"разброс":>9}  вердикт')
        for k, g in sorted(cal.items(), key=lambda kv: -kv[1]['n']):
            print(f'{k[:28]:28}{g["n"]:>6}{g["p10"]:>6.0f}{g["median"]:>6.0f}{g["p75"]:>6.0f}'
                  f'{g["p90"]:>6.0f}{g["spread"]:>9.2f}  '
                  + ('ПРИМЕНЯЕМ' if g['apply'] else 'нет: ' + g['why']))
        print(f'\nкалибровка записана: {OUT}')
        return 0
    if not os.path.exists(OUT):
        print(f'нет {OUT} — сперва --calibrate')
        return 1
    cal = json.load(open(OUT, encoding='utf-8'))['groups']
    if '--report' in sys.argv:
        r = db("select count(*) filter (where dims_evidence->'d'->>'source'='role_prior'), "
               "count(*) filter (where in_stock and d_cm is null and cat_role is not null) "
               "from products")[0]
        print(f'глубин из приора в каталоге: {r[0]}; товаров in_stock без глубины: {r[1]}')
        return 0
    if '--apply' not in sys.argv:
        print(__doc__.strip().splitlines()[-4])
        return 1

    rows = db("""
      select shop_mid, external_id, coalesce(cat_role,''), replace(name, chr(9), ' ')
        from products
       where in_stock and d_cm is null and cat_role is not null and image_url is not null
    """)
    done, skip = 0, {}
    for r in rows:
        if len(r) < 4:
            continue
        mid, eid, role, name = r[0], r[1], r[2], ' '.join(r[3:])
        g = cal.get(f'{role}|{shape_of(role, name)}')
        if not g or not g['apply']:
            key = 'группа не прошла гейт' if g else 'группы нет в калибровке'
            skip[key] = skip.get(key, 0) + 1
            continue
        ev = {'raw': g['median'], 'unit': 'cm', 'source': 'role_prior', 'role': role,
              'shape': g['shape'], 'p10': g['p10'], 'median': g['median'], 'p75': g['p75'],
              'p90': g['p90'], 'n': g['n'], 'spread': g['spread'],
              'confidence': 'medium' if g['spread'] <= 0.3 else 'low'}
        payload = json.dumps(ev, ensure_ascii=False).replace("'", "''")
        db(f"""update products set d_cm = {g['median']},
                 dims_evidence = coalesce(dims_evidence,'{{}}'::jsonb)
                                 || jsonb_build_object('d', '{payload}'::jsonb),
                 dims_source = coalesce(dims_source,'') || ' prior:1'
               where shop_mid={int(mid)} and external_id='{eid.replace("'", "''")}'
                 and d_cm is null""")
        done += 1
    print(f'записано глубин по приору: {done}; пропущено: '
          + (', '.join(f'{k} — {v}' for k, v in skip.items()) or '0'))
    return 0


def _selftest() -> int:
    bad = 0
    for role, name, want in (('диван', 'П-образный диван Босс', 'П-образный'),
                             ('диван', 'Угловой диван левый Твин', 'угловой'),
                             ('диван', 'Диван с оттоманкой Рио', 'угловой'),
                             ('диван', 'Прямой диван Тренд', 'прямой'),
                             ('диван', 'Диван Босс Шенилл', ''),
                             ('комод', 'Комод угловой Рио', '')):   # роль без расщепления
        got = shape_of(role, name)
        if got != want:
            bad += 1
            print(f'  FAIL форма «{name}»: {got!r}, ждали {want!r}')
    # Гейт: узкая группа проходит, широкая и малая — нет. Числа — реальные замеры 11.10.
    for n, p10, p75, p90, med, want in ((568, 86, 105, 115, 98, True),     # прямой диван
                                        (271, 146, 170, 178, 160, True),   # угловой
                                        (607, 40, 150, 272, 110, False),   # без пометки
                                        (740, 40, 55, 60, 50, True),       # шкаф, разброс 0.40
                                        (10, 40, 45, 50, 44, False)):      # мало наблюдений
        ok, _, _ = gate(n, p10, p75, p90, med)
        if ok != want:
            bad += 1
            print(f'  FAIL гейт n={n} {p10}/{med}/{p90}: {ok}, ждали {want}')
    print('самопроверка dim_prior: ' + ('ОК' if not bad else f'ПРОВАЛОВ {bad}'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
