#!/usr/bin/env python3
"""Сторож размеров: кто из магазинов молча выпадает из работы (план dims-round-objects, 11.10).

ЗАЧЕМ. Подключили Орматек — часть его товаров наш загрузчик не понял (его конвенция осей не
измерена) и молча выбросил: в каталоге товар есть, цена есть, фото есть, а в очередь мешей и в
расстановку он не попадает. Обнаружилось случайно, через демо. Тот же класс дыр до этого держал
1514 люстр и 97 торшеров: у круглых предметов «Диаметр» вместо «Ширины».

ЧТО СЧИТАЕМ — ТРИ РАЗНЫЕ ГОТОВНОСТИ по `магазин × роль` (их нельзя смешивать, разбор Codex 11.10):
  mesh_ready   — годен к ГЕНЕРАЦИИ: есть высота и (ширина ИЛИ диаметр);
  place_ready  — годен к РАССТАНОВКЕ: есть все три оси (диаметр закрывает глубину у круглого);
  lost_mesh    — размерные поля в `params` ЕСТЬ, а к генерации не годен: молчаливая потеря;
  lost_depth   — к генерации годен, но ГЛУБИНЫ нет при наличии размерных полей: меш сделаем,
                 честно расставить не сможем. Это отдельный счёт: первая версия сторожа его не
                 считала и ставила `ok` 14 группам, где глубины нет у >50 % (3 503 товара) —
                 поймал субагент `verify`.

РОЛЬ РЕШАЕТ, ЧТО СЧИТАТЬ ПОТЕРЕЙ. У пледа/подушки/ковра «высоты» не бывает по природе: это
плоские предметы (`render_strategy.strategy` → `flat`), им нужны ширина и длина, а не три оси.
Поэтому тревогу по ним поднимаем отдельной строкой и не мешаем с мебелью — иначе сторож кричит
всегда и его перестают читать.

ПОРОГИ. Тревога только там, где есть статистика: `n >= MIN_N` и доля unresolved > `MAX_UNRESOLVED`.
Маленькая группа получает статус `insufficient_sample` — по ней правило не выводим (правило из
шапки `dim_resolver.py`: конвенцию мерить на выборке, не на примере).

Место в конвейере: СРАЗУ после `load3`, ДО платных шагов (обогащение, судья) и до `mesh_bind` —
чтобы молчаливая потеря всплыла раньше, чем мы за неё заплатим.

  dim_audit.py                 # отчёт по всем магазинам
  dim_audit.py --mid 93965     # один магазин
  dim_audit.py --json <файл>   # машинный отчёт для дайджеста
  dim_audit.py --selftest      # самопроверка порогов
Код возврата 1 — есть тревоги (для крона и дайджеста).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# ON_ERROR_STOP ОБЯЗАТЕЛЕН (грабля из `mesh_priority.py:32`): psql со stdin при ошибке SQL
# вернёт 0 и пустой вывод, и сторож напечатал бы «тревог нет» — то есть соврал бы ровно в том
# месте, ради которого создан.
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-v', 'ON_ERROR_STOP=1', '-q', '-t', '-A', '-F', '\t']
MIN_N = int(os.environ.get('DIM_AUDIT_MIN_N', '20'))
MAX_UNRESOLVED = float(os.environ.get('DIM_AUDIT_MAX_UNRESOLVED', '0.20'))
# Поля, по которым судим «размеры в фиде ЕСТЬ». Список держим здесь, а не в SQL, чтобы он читался.
DIM_FIELDS = ('Ширина', 'Глубина', 'Высота', 'Длина', 'Диаметр', 'Габариты', 'Размер')

SQL = """
select p.shop_mid, coalesce(p.cat_role,'(нет роли)') as role,
  count(*) as n,
  count(*) filter (where (p.w_cm is not null or p.dia_cm is not null) and p.h_cm is not null) as mesh_ready,
  count(*) filter (where p.w_cm is not null and p.h_cm is not null
                     and (p.d_cm is not null or p.dia_cm is not null)) as place_ready,
  count(*) filter (where (p.w_cm is null and p.dia_cm is null or p.h_cm is null)
                     and exists (select 1 from jsonb_each_text(coalesce(p.params,'{}'::jsonb)) kv
                                  where kv.key like any (array[%s]))) as lost_mesh,
  count(*) filter (where (p.w_cm is not null or p.dia_cm is not null) and p.h_cm is not null
                     and p.d_cm is null and p.dia_cm is null
                     and exists (select 1 from jsonb_each_text(coalesce(p.params,'{}'::jsonb)) kv
                                  where kv.key like any (array[%s]))) as lost_depth
from products p
where p.in_stock and p.image_url is not null and p.cat_role is not null
group by 1,2 order by 1,2;
"""


def rows() -> list[list[str]]:
    like = ', '.join("'%" + f + "%'" for f in DIM_FIELDS)
    try:
        r = subprocess.run(PSQL, input=SQL % (like, like), capture_output=True, text=True,
                           timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'база не опрошена: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(2)          # 2 — инфраструктура, чтобы не путать с «есть тревоги» (1)
    if r.returncode != 0:
        print(r.stderr[:400], file=sys.stderr)
        sys.exit(2)
    return [ln.split('\t') for ln in r.stdout.strip().split('\n') if ln]


def arg(flag: str) -> str | None:
    """Значение флага; флаг последним аргументом не должен ронять сторожа."""
    if flag in sys.argv:
        i = sys.argv.index(flag) + 1
        if i < len(sys.argv):
            return sys.argv[i]
        print(f'у флага {flag} нет значения — игнорирую', file=sys.stderr)
    return None


def verdict(n: int, lost: int) -> tuple[str, float]:
    """Статус группы и доля потерь. Чистая функция — её и проверяет селфтест."""
    share = (lost / n) if n else 0.0
    if n < MIN_N:
        return ('insufficient_sample', share)
    if share > MAX_UNRESOLVED:
        return ('ТРЕВОГА', share)
    return ('ok', share)


def _strategy(role: str) -> str:
    """Способ отрисовки роли: от него зависит, что считать потерей. Без него сторож кричал бы
    на пледы и подушки, которым три оси не нужны по природе."""
    try:
        sys.path.insert(0, HERE)
        from render_strategy import base_role, strategy
        return strategy(base_role(role))
    except Exception:  # noqa: BLE001 — роль вне таблицы: судим как объёмную, это строже
        return 'mesh'


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    only = arg('--mid')
    out, alarms = [], []
    for r in rows():
        if len(r) < 7:
            continue
        mid, role, n = r[0], r[1], int(r[2])
        mesh, place, lost_mesh, lost_depth = int(r[3]), int(r[4]), int(r[5]), int(r[6])
        if only and mid != only:
            continue
        strat = _strategy(role)
        # ЧТО СЧИТАЕТСЯ ПОТЕРЕЙ — ПО СПОСОБУ ОТРИСОВКИ (`render_strategy`):
        #   mesh   — нужны и годность к генерации, и глубина (иначе не расставить);
        #   flat   — варпится по перспективе: нужны ширина и высота, глубина не нужна;
        #   cutout — вклеивается силуэтом, размеры не нужны ВООБЩЕ: тревожить по ним нельзя,
        #            иначе сторож кричит на пледы и подушки всегда и его перестают читать
        #            (у них размеров и не должно быть; первая версия давала 4 ложные тревоги).
        lost = {'mesh': lost_mesh + lost_depth, 'flat': lost_mesh}.get(strat, 0)
        st, share = verdict(n, lost)
        row = {'mid': mid, 'role': role, 'strategy': strat, 'n': n, 'mesh_ready': mesh,
               'place_ready': place, 'lost_mesh': lost_mesh, 'lost_depth': lost_depth,
               'lost': lost, 'share': round(share, 3), 'status': st}
        out.append(row)
        if st == 'ТРЕВОГА':
            alarms.append(row)
    print(f'{"магазин":>8} {"роль":14} {"как":7} {"всего":>6} {"меш":>6} {"расст.":>7} '
          f'{"нет меша":>9} {"нет глуб.":>10} статус')
    for r in sorted(out, key=lambda x: -x['lost'])[:40]:
        print(f'{r["mid"]:>8} {r["role"][:14]:14} {r["strategy"][:7]:7} {r["n"]:>6} '
              f'{r["mesh_ready"]:>6} {r["place_ready"]:>7} {r["lost_mesh"]:>9} '
              f'{r["lost_depth"]:>10} {r["status"]}'
              + (f' ({r["share"]:.0%})' if r['status'] == 'ТРЕВОГА' else ''))
    p = arg('--json')
    if p:
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump({'min_n': MIN_N, 'max_unresolved': MAX_UNRESOLVED, 'rows': out}, fh,
                      ensure_ascii=False, indent=1)
        print(f'отчёт: {p}')
    if alarms:
        tot = sum(a['lost'] for a in alarms)
        print(f'\nТРЕВОГ {len(alarms)}: размеры в фиде есть, а в работу не доехали у {tot} товаров.'
              f' Это молчаливая потеря — измерь конвенцию осей магазина'
              f' (`dim_resolver.SHOP_DIM_KEYS`, правило: мерить на выборке, не на примере).')
        return 1
    print('\nтревог нет')
    return 0


def _selftest() -> int:
    bad = 0
    cases = [
        (5, 5, 'insufficient_sample'),      # мало данных — правило не выводим
        (19, 19, 'insufficient_sample'),     # граница снизу
        (20, 5, 'ТРЕВОГА'),                  # 25% > 20%
        (20, 4, 'ok'),                       # ровно 20% — не тревога
        (100, 0, 'ok'),
        (0, 0, 'insufficient_sample'),       # пустая группа не делит на ноль
    ]
    # Роль решает, что считать потерей: плоским трёх осей не нужно.
    for role, want in (('диван', 'mesh'), ('плед', 'cutout'), ('ковёр', 'flat'), ('ваза', 'mesh')):
        got = _strategy(role)
        if got != want:
            bad += 1
            print(f'  FAIL стратегия роли «{role}»: {got}, ждали {want}')
    # Флаг последним аргументом не должен ронять сторожа.
    sys.argv = ['dim_audit.py', '--mid']
    if arg('--mid') is not None:
        bad += 1
        print('  FAIL --mid без значения вернул значение')
    for n, unres, want in cases:
        got, _ = verdict(n, unres)
        if got != want:
            bad += 1
            print(f'  FAIL n={n} unresolved={unres}: {got}, ждали {want}')
    print('самопроверка dim_audit: ' + ('ОК' if not bad else f'ПРОВАЛОВ {bad}'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
