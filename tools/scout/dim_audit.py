#!/usr/bin/env python3
"""Сторож размеров: кто из магазинов молча выпадает из работы (план dims-round-objects, 11.10).

ЗАЧЕМ. Подключили Орматек — часть его товаров наш загрузчик не понял (его конвенция осей не
измерена) и молча выбросил: в каталоге товар есть, цена есть, фото есть, а в очередь мешей и в
расстановку он не попадает. Обнаружилось случайно, через демо. Тот же класс дыр до этого держал
1514 люстр и 97 торшеров: у круглых предметов «Диаметр» вместо «Ширины».

ЧТО СЧИТАЕМ — ТРИ РАЗНЫЕ ГОТОВНОСТИ по `магазин × роль` (их нельзя смешивать, разбор Codex 11.10):
  mesh_ready   — годен к ГЕНЕРАЦИИ: есть высота и (ширина ИЛИ диаметр);
  place_ready  — годен к РАССТАНОВКЕ: есть все три оси (диаметр закрывает глубину у круглого);
  unresolved   — размерные поля в `params` ЕСТЬ, а осей нет: именно это и есть молчаливая потеря.

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
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-t', '-A', '-F', '\t']
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
  count(*) filter (where (p.w_cm is null or p.h_cm is null)
                     and exists (select 1 from jsonb_each_text(coalesce(p.params,'{}'::jsonb)) kv
                                  where kv.key like any (array[%s]))) as unresolved
from products p
where p.in_stock and p.image_url is not null and p.cat_role is not null
group by 1,2 order by 1,2;
"""


def rows() -> list[list[str]]:
    like = ', '.join("'%" + f + "%'" for f in DIM_FIELDS)
    r = subprocess.run(PSQL, input=SQL % like, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(r.stderr[:400], file=sys.stderr)
        sys.exit(1)
    return [ln.split('\t') for ln in r.stdout.strip().split('\n') if ln]


def verdict(n: int, unresolved: int) -> tuple[str, float]:
    """Статус группы и доля нерешённых. Отдельная чистая функция — её и проверяет селфтест."""
    share = (unresolved / n) if n else 0.0
    if n < MIN_N:
        return ('insufficient_sample', share)
    if share > MAX_UNRESOLVED:
        return ('ТРЕВОГА', share)
    return ('ok', share)


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    only = None
    if '--mid' in sys.argv:
        only = sys.argv[sys.argv.index('--mid') + 1]
    out, alarms = [], []
    for r in rows():
        if len(r) < 6:
            continue
        mid, role, n, mesh, place, unres = r[0], r[1], int(r[2]), int(r[3]), int(r[4]), int(r[5])
        if only and mid != only:
            continue
        st, share = verdict(n, unres)
        row = {'mid': mid, 'role': role, 'n': n, 'mesh_ready': mesh, 'place_ready': place,
               'unresolved': unres, 'share': round(share, 3), 'status': st}
        out.append(row)
        if st == 'ТРЕВОГА':
            alarms.append(row)
    print(f'{"магазин":>8} {"роль":16} {"всего":>6} {"меш":>6} {"расст.":>7} {"потеряно":>9} статус')
    for r in sorted(out, key=lambda x: -x['unresolved'])[:40]:
        print(f'{r["mid"]:>8} {r["role"][:16]:16} {r["n"]:>6} {r["mesh_ready"]:>6} '
              f'{r["place_ready"]:>7} {r["unresolved"]:>9} {r["status"]}'
              + (f' ({r["share"]:.0%})' if r['status'] == 'ТРЕВОГА' else ''))
    if '--json' in sys.argv:
        p = sys.argv[sys.argv.index('--json') + 1]
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'min_n': MIN_N, 'max_unresolved': MAX_UNRESOLVED, 'rows': out}, f,
                      ensure_ascii=False, indent=1)
        print(f'отчёт: {p}')
    if alarms:
        tot = sum(a['unresolved'] for a in alarms)
        print(f'\nТРЕВОГ {len(alarms)}: размеры в фиде есть, а в базу не доехали у {tot} товаров.'
              f' Это молчаливая потеря — измерь конвенцию осей магазина (dim_resolver.SHOP_DIM_KEYS).')
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
    for n, unres, want in cases:
        got, _ = verdict(n, unres)
        if got != want:
            bad += 1
            print(f'  FAIL n={n} unresolved={unres}: {got}, ждали {want}')
    print('самопроверка dim_audit: ' + ('ОК' if not bad else f'ПРОВАЛОВ {bad}'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
