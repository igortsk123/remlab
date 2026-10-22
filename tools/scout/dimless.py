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
Малые категории (n < MIN_N) решения не получают — их 11 у mdm (23 товара); правило для них — в отчёте плана.

  dimless.py --warn       # строки WARN:category_dimless для дайджеста (refresh_daily)
  dimless.py --report     # таблица категорий в карантине
  dimless.py --selftest
Env: REMLAB_DEVDB_NAME — одноразовая база (как у mesh_queue/mesh_bind).
"""
import os
import subprocess
import sys

MIN_N = int(os.environ.get('DIMLESS_MIN_N', '5'))
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


def categories_sql() -> str:
    """SELECT категорий в карантине: shop_mid, category_id, n, путь, магазин. Одно место правила для всех потребителей."""
    return f"""select shop_mid, category_id, count(*) n, min(category_path) path, min(shop) shop
  from products
 where status = 'active' and cat_role = any({_roles_sql()}) and category_id is not null
 group by shop_mid, category_id
having count(*) >= {MIN_N}
   and count(*) filter (where w_cm is not null and h_cm is not null
         and coalesce(dims_evidence->'w'->>'source','') !~ '{INFERRED_RX}'
         and coalesce(dims_evidence->'h'->>'source','') !~ '{INFERRED_RX}') = 0"""


def exclude_sql(alias: str = 'p') -> str:
    """Условие WHERE «товар НЕ из категории без размеров» — для dim_prior, mesh_bind, compose2."""
    return (f"not exists (select 1 from ({categories_sql()}) dimless_c "
            f"where dimless_c.shop_mid = {alias}.shop_mid and dimless_c.category_id = {alias}.category_id)")


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def categories() -> list[dict]:
    out = []
    for r in db(categories_sql() + ' order by n desc'):
        if len(r) >= 5:
            out.append({'mid': int(r[0]), 'cid': r[1], 'n': int(r[2]), 'path': r[3], 'shop': r[4]})
    return out


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
    sql = categories_sql()
    ok('выведенные размеры не считаются измеренными', all(s in INFERRED_RX for s in ('role_prior', 'mesh_ratio', 'shape_rule')))
    ok('текстиль вне правила (у подушки высоты нет по природе)', not {'подушка', 'плед', 'ковёр', 'шторы'} & set(ROLES))
    ok('роли мебели и света внутри', {'шкаф', 'стеллаж', 'стенка', 'люстра', 'ваза'} <= set(ROLES))
    ok('SQL — только активные и по категории', "status = 'active'" in sql and 'group by shop_mid, category_id' in sql)
    ok('условие исключения ссылается на алиас', 'dimless_c.shop_mid = p.shop_mid' in exclude_sql('p'))
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
        print(f'категорий без размеров (n ≥ {MIN_N}): {len(cats)}, товаров {sum(c["n"] for c in cats)}')
        for c in cats:
            print(f"  {c['n']:5}  {c['shop']:16} {c['mid']}:{c['cid']}  {c['path']}")
        return 0
    print(__doc__.strip().splitlines()[-5])
    return 1


if __name__ == '__main__':
    sys.exit(main())
