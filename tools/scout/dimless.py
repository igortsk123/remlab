#!/usr/bin/env python3
"""КАТЕГОРИЯ БЕЗ РАЗМЕРОВ — КАРАНТИН ПРИГОДНОСТИ, НЕ СНЯТИЕ РОЛИ (план catalog-holes-bank Н1, разбор Codex 23.10).

ЗАЧЕМ. Магазин 96431 (mdm-complect) — поставщик фурнитуры: рельсы, корзины, ролики. Карта категорий отдаёт их в
«шкаф»/«стеллаж» по родителю пути («Шкафы. Гардеробные. Двери», `category_map.classify` — откат с листа на полный путь),
и 821 товар живёт в ролях мебели: на него ложится приор глубины (шкаф 50 см), он попадает в пул и в счёт «без высоты».
Словари слов не сходятся (теряют настоящие шкафы Орматек «…(профиль)», «Вешалка»), а СТАТИСТИКА категории — сходится:
из 87 мебельных категорий у 31 (n ≥ 5) нет ни одного товара с измеренными Ш и В, и промежуточных (1–29 %) нет вовсе.

ПОЧЕМУ НЕ СНИМАЕМ РОЛЬ. Роль = допуск оффера в загрузку (`load3.assign`: `accepted = bool(role)`, три пропуска → архив).
Сняв роль, потеряли бы «Модульные гостиные» divan.ru (24 настоящих предмета, просто без размеров). Поэтому роль остаётся,
а категория уходит в карантин: не получает приор глубины (`dim_prior`), не требует меша (`mesh_bind`), не идёт в пул
автоподбора (`compose2`), а ночной дайджест пишет строку `WARN:` — новый магазин без размеров не пропадёт молча.

ЧТО СЧИТАЕТСЯ ИЗМЕРЕННЫМ. Ш и В есть и пришли НЕ из вывода (`role_prior`, `mesh_ratio`, `shape_rule:*` — их источник в
`dims_evidence`). Статистика — по текущим данным загрузки (`products`), а не по карте категорий: карта ночью не пересобирается.
МАЛЫЕ КАТЕГОРИИ (n < MIN_N, ни одного измеренного; T-20261022-26/2): своей статистики не хватает — решает ближайший предок
пути (`category-roles.json`, путь «A / B / C»), у поддерева которого уже n ≥ MIN_N: 0 измеренных в поддереве — карантин
(«ветка»), есть измеренные — нет. Предка с n ≥ MIN_N нет — решает магазин: ≥ SHOP_SHARE его товаров в ролях уже в карантине
(mdm 97 %) — карантин («магазин»); у divan.ru 0,7 % — нет. Замер 23.10: ветка закрывает 20 из 23 малых товаров mdm, магазин — 3.

  dimless.py --warn       # строки WARN:category_dimless для дайджеста (refresh_daily)
  dimless.py --report     # таблица категорий в карантине
  dimless.py --selftest
Env: REMLAB_DEVDB_NAME — одноразовая база (как у mesh_queue/mesh_bind).
"""
import json
import os
import subprocess
import sys

MIN_N = int(os.environ.get('DIMLESS_MIN_N', '5'))
SHOP_SHARE = float(os.environ.get('DIMLESS_SHOP_SHARE', '0.9'))
HERE = os.path.dirname(os.path.abspath(__file__))
ROLES_PATH = os.environ.get('SCOUT_ROLES_PATH') or os.path.join(HERE, 'category-roles.json')
# Роли, которым размер нужен для расстановки и меша (мебель, свет, декор на полу/полке). Текстиль (подушка, плед,
# ковёр, шторы) не входит: у него высоты нет по природе, и его категории «без В» — норма, а не дыра.
ROLES = ('диван', 'кресло', 'стул', 'стол', 'стол обеденный', 'столик', 'тумба', 'тв-тумба', 'комод', 'стеллаж', 'шкаф',
         'стенка', 'пуф', 'банкетка', 'витрина', 'полка', 'камин', 'кашпо', 'ваза', 'торшер', 'растение', 'лампа',
         'статуэтка', 'люстра', 'бра', 'зеркало', 'часы')
# Источники ВЫВЕДЕННОГО размера (не измерение): приор роли, пропорция меша, правило формы
INFERRED_RX = '^(role_prior|mesh_ratio|shape_rule)'
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']


def is_dimless(n: int, measured: int) -> bool:
    """Решение по одной категории: достаточно товаров и ни одного измеренного."""
    return n >= MIN_N and measured == 0


def _roles_sql() -> str:
    return 'array[' + ','.join("'" + r + "'" for r in ROLES) + ']'


MEASURED_SQL = (f"w_cm is not null and h_cm is not null "
                f"and coalesce(dims_evidence->'w'->>'source','') !~ '{INFERRED_RX}' "
                f"and coalesce(dims_evidence->'h'->>'source','') !~ '{INFERRED_RX}'")


def stats_sql() -> str:
    """Статистика по ВСЕМ категориям ролей: shop_mid, category_id, n, измеренных, лист пути, магазин."""
    return f"""select shop_mid, category_id, count(*) n, count(*) filter (where {MEASURED_SQL}) m,
       min(category_path) path, min(shop) shop
  from products
 where status = 'active' and cat_role = any({_roles_sql()}) and category_id is not null
 group by shop_mid, category_id"""


def decide(stats: dict, paths: dict) -> dict:
    """{(mid, cid): (n, измеренных)} + {(mid, cid): полный путь} → {(mid, cid): причина} категорий в карантине.
    Чистая функция — одно место правила (selftest без БД)."""
    out = {}
    for k, (n, m) in stats.items():
        if is_dimless(n, m):
            out[k] = 'категория'
    tot, quar = {}, {}
    for (mid, cid), (n, _) in stats.items():
        tot[mid] = tot.get(mid, 0) + n
        if (mid, cid) in out:
            quar[mid] = quar.get(mid, 0) + n
    shop_dimless = {mid for mid in tot if tot[mid] and quar.get(mid, 0) / tot[mid] >= SHOP_SHARE}
    for (mid, cid), (n, m) in stats.items():
        if n >= MIN_N or m:
            continue
        parts = (paths.get((mid, cid)) or '').split(' / ')
        verdict = None
        for i in range(len(parts) - 1, 0, -1):          # ближайший предок, чьё поддерево набрало MIN_N
            anc = ' / '.join(parts[:i])
            sub = [st for k2, st in stats.items() if k2[0] == mid and
                   ((paths.get(k2) or '') == anc or (paths.get(k2) or '').startswith(anc + ' / '))]
            if sum(x[0] for x in sub) >= MIN_N:
                verdict = 'ветка' if sum(x[1] for x in sub) == 0 else 'есть измеренные'
                break
        if verdict == 'ветка':
            out[(mid, cid)] = 'ветка'
        elif verdict is None and mid in shop_dimless:
            out[(mid, cid)] = 'магазин'
    return out


def _paths() -> dict:
    try:
        cr = json.load(open(ROLES_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        print(f'WARN:category_dimless_paths: {ROLES_PATH} не читается — малые категории решаются только долей магазина',
              flush=True)
        return {}
    return {(int(r['mid']), str(r['id'])): r.get('path') or '' for r in cr.values() if r.get('mid') is not None}


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


_CATS: list | None = None


def categories() -> list[dict]:
    """Категории в карантине (кэш на процесс): mid, cid, n, path (лист), shop, why."""
    global _CATS
    if _CATS is None:
        rows = [r for r in db(stats_sql()) if len(r) >= 6]
        stats = {(int(r[0]), r[1]): (int(r[2]), int(r[3])) for r in rows}
        meta = {(int(r[0]), r[1]): (r[4], r[5]) for r in rows}
        dec = decide(stats, _paths())
        _CATS = sorted(({'mid': k[0], 'cid': k[1], 'n': stats[k][0], 'path': meta[k][0], 'shop': meta[k][1], 'why': why}
                        for k, why in dec.items()), key=lambda c: -c['n'])
    return _CATS


def exclude_sql(alias: str = 'p', keys: list | None = None) -> str:
    """Условие WHERE «товар НЕ из категории без размеров» — для dim_prior, mesh_bind, compose2. Список категорий решён в
    Python (`decide`: путь категории живёт в `category-roles.json`, не в базе) и вписан литералом; пусто — `true`."""
    ks = keys if keys is not None else [f"{c['mid']}:{c['cid']}" for c in categories()]
    if not ks:
        return 'true'
    lit = ','.join("'" + k.replace("'", "''") + "'" for k in ks)
    # coalesce: товар без категории иначе дал бы NULL — и молча выпал бы из пула/приоров/мешей (`and NULL` = ложь)
    return f"({alias}.shop_mid::text || ':' || coalesce({alias}.category_id::text, '')) <> all(array[{lit}]::text[])"


def warn_lines(cats: list[dict]) -> list[str]:
    """Строки дайджеста: по магазину — сколько категорий и товаров вне подбора, плюс крупнейшие категории."""
    by: dict[tuple[int, str], list[dict]] = {}
    for c in cats:
        by.setdefault((c['mid'], c['shop']), []).append(c)
    lines = []
    for (mid, shop), cs in sorted(by.items(), key=lambda kv: -sum(c['n'] for c in kv[1])):
        top = ', '.join(f"«{c['path']}» {c['n']}" for c in cs[:3])
        lines.append(f"WARN:category_dimless: магазин {shop} ({mid}) — {len(cs)} категорий, {sum(c['n'] for c in cs)} "
                     f"товаров без размеров: вне подбора, приоров и мешей ({top}{'…' if len(cs) > 3 else ''})")
    return lines


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1
    ok('n ≥ 5 и 0 измеренных — карантин', is_dimless(5, 0) and is_dimless(257, 0))
    ok('малая категория (n < 5) — решения нет', not is_dimless(4, 0))
    ok('хоть один измеренный — не карантин', not is_dimless(100, 1))
    sql = stats_sql()
    ok('выведенные размеры не считаются измеренными', all(s in INFERRED_RX for s in ('role_prior', 'mesh_ratio', 'shape_rule')))
    ok('текстиль вне правила (у подушки высоты нет по природе)', not {'подушка', 'плед', 'ковёр', 'шторы'} & set(ROLES))
    ok('роли мебели и света внутри', {'шкаф', 'стеллаж', 'стенка', 'люстра', 'ваза'} <= set(ROLES))
    ok('SQL — только активные и по категории', "status = 'active'" in sql and 'group by shop_mid, category_id' in sql)
    ex = exclude_sql('p', ['96431:1478', "1:o'k"])
    ok('условие исключения: алиас, ключ «магазин:категория», кавычки экранированы; пусто — true',
       ex.startswith("(p.shop_mid::text || ':' || coalesce(p.category_id::text, '')) <> all(") and "'96431:1478'" in ex
       and "'1:o''k'" in ex and exclude_sql('q', []) == 'true')
    # МАЛЫЕ КАТЕГОРИИ: модель mdm (почти весь магазин без размеров) и divan.ru (размеры есть почти везде)
    S = {(96431, 'big'): (249, 0), (96431, 'duko'): (2, 0), (96431, 'ghost'): (1, 0), (96431, 'ghost_br'): (60, 0),
         (96431, 'rot'): (3, 0), (96431, 'meas_small'): (2, 0), (96431, 'meas_sib'): (6, 3),
         (112923, 'mod'): (24, 0), (112923, 'sofa'): (5000, 4800), (112923, 'tiny'): (2, 0), (112923, 'tiny_m'): (3, 1)}
    P = {(96431, 'big'): 'Шкафы / Раздвижные', (96431, 'duko'): 'Шкафы / Раздвижные / ДУКО',
         (96431, 'ghost'): 'Шкафы / Двери / GHOST', (96431, 'ghost_br'): 'Шкафы / Двери',
         (96431, 'rot'): 'Трансформация / Поворотные', (96431, 'meas_small'): 'Кухни / Мойки',
         (96431, 'meas_sib'): 'Кухни / Столешницы',
         (112923, 'mod'): 'Гостиные / Модульные', (112923, 'sofa'): 'Диваны / Прямые', (112923, 'tiny'): 'Диваны / Пледы',
         (112923, 'tiny_m'): 'Гостиные / Пуфы'}
    D = decide(S, P)
    ok('большая категория без измеренных — «категория» (как раньше)', D.get((96431, 'big')) == 'категория'
       and D.get((112923, 'mod')) == 'категория')
    ok('малая под веткой без измеренных — «ветка»', D.get((96431, 'duko')) == 'ветка' and D.get((96431, 'ghost')) == 'ветка')
    ok('малая без предка n ≥ 5 у магазина ≥ 90 % в карантине — «магазин»', D.get((96431, 'rot')) == 'магазин')
    ok('малая под веткой с измеренными — не карантин, даже у магазина ≥ 90 %', (96431, 'meas_small') not in D)
    ok('divan.ru (0,7 % в карантине): малая без предка — не карантин; с измеренными — не карантин; настоящие диваны — нет',
       (112923, 'tiny') not in D and (112923, 'tiny_m') not in D and (112923, 'sofa') not in D)
    lines = warn_lines([{'mid': 96431, 'shop': 'mdm-complect.ru', 'cid': '1478', 'n': 257, 'path': 'Системы хранения'},
                        {'mid': 96431, 'shop': 'mdm-complect.ru', 'cid': '1477', 'n': 75, 'path': 'Штанги'},
                        {'mid': 112923, 'shop': 'divan.ru', 'cid': '24', 'n': 24, 'path': 'Модульные гостиные'}])
    ok('дайджест: строка на магазин, с префиксом WARN:', len(lines) == 2 and all(x.startswith('WARN:category_dimless:') for x in lines)
       and '332 товаров' in lines[0] and 'divan.ru' in lines[1])
    print('самопроверка dimless: ' + ('ОК' if not bad else f'ПРОВАЛОВ {bad}'))
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    cats = categories()
    if '--warn' in sys.argv:
        for ln in warn_lines(cats):
            print(ln)
        return 0
    if '--report' in sys.argv:
        by = {}
        for c in cats:
            by[c['why']] = by.get(c['why'], 0) + 1
        print(f'категорий без размеров: {len(cats)}, товаров {sum(c["n"] for c in cats)} (по причине: '
              + ', '.join(f'{k} {v}' for k, v in sorted(by.items())) + ')')
        for c in cats:
            print(f"  {c['n']:5}  {c['shop']:16} {c['mid']}:{c['cid']}  {c['why']:9}  {c['path']}")
        return 0
    print(__doc__.strip().splitlines()[-5])
    return 1


if __name__ == '__main__':
    sys.exit(main())
