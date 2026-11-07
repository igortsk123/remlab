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

ЧТО ЧИНИТСЯ НАШИМ КОДОМ, А ЧТО НЕТ (T-20261107-22, 07.11). Тревога висела каждую ночь (716–1703 товара), и больше
половины суммы загрузчик не вернёт никогда: в фиде только «Высота» (растения, вазы tvoydom — 268), глубину диванов
mnogomebeli/divanboss знает только чертёж (`drawing_dims`, 127), у ковра требовали высоту (48 — у них есть Ш и Г).
Поэтому причина потери считается ПО ТОВАРУ (`reason`), и тревога (WARN) — только на `fix`; остальное — строкой
DIGEST без тревоги:
  height_only — у товара нет ни одного горизонтального размерного поля, только «Высота…»;
  no_height   — высота нужна и пуста, а вертикали в фиде нет вовсе (ни «Высоты…», ни составного «Габариты»/«Размеры»):
                свет и кашпо tvoydom с одним «Диаметром» или «Длиной/Шириной» — 400+ товаров, первая версия звала их «fix»;
  one_horizontal — нет только глубины, а горизонталь в фиде одна (её уже взяли в ширину);
  drawing     — диван/кресло магазина с чертежом (`drawing_dims.SHOPS`), нет только глубины, поля «Глубина…» нет;
  fix         — размерное поле есть и его не поняли: это и есть молчаливая потеря.
Габариты УПАКОВКИ и «брутто» — не размер товара: «размеры в фиде есть» по ним не считаем.
Ковёр лежит на полу: ему нужны ширина и глубина (или диаметр), а не высота (`FLOOR_FLAT`).

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
import re
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

# Не размер товара: габариты упаковки и вес брутто (T-22). Иначе «Высота упаковки 1 (см)» у искусственного цветка
# без единого горизонтального поля считалась «размеры в фиде есть» — и тревожила.
NOT_ITEM = ('упаковк', 'брутто')
# Плоское на полу: Ш×Г (или диаметр), высоты у ковра нет по природе. Плоское на стене (картина, зеркало) — Ш×В.
FLOOR_FLAT = frozenset({'ковёр', 'ковер'})
DRAWING_ROLES = frozenset({'диван', 'кресло'})
REASONS = ('fix', 'height_only', 'no_height', 'one_horizontal', 'drawing')
# Откуда загрузчик может взять ВЫСОТУ: поле «Высота…» или составное поле с вертикалью («Габариты (Д*Ш*В)», «Размеры» 60x80,
# «Размер, см», «Размер штор») — `dim_resolver.COMPOSITE_KEYS`. «Размеры: Длина/Ширина/Глубина габаритная» — горизонтали.
VERT_COMPOSITE = re.compile(r'^(Габариты|Размеры?(,| штор|$))')

# ПО ТОВАРУ, а не суммой (T-22): причина потери считается в `reason` на каждом товаре. Ключи — размерные поля
# товара с числом в значении (без упаковки); фильтр по имени — тот же LIKE, что и раньше.
SQL = """
select p.shop_mid, p.cat_role, p.w_cm is not null, p.d_cm is not null, p.h_cm is not null, p.dia_cm is not null,
  coalesce((select string_agg(kv.key, chr(31)) from jsonb_each_text(coalesce(p.params,'{}'::jsonb)) kv(key, val)
             where kv.key like any (array[%s]) and kv.val ~ '[0-9]'
               and kv.key not ilike '%%упаковк%%' and kv.key not ilike '%%брутто%%'), '')
from products p
where p.in_stock and p.image_url is not null and p.cat_role is not null;
"""


def drawing_shops() -> frozenset:
    """Магазины, где глубину дивана знает только чертёж — `drawing_dims.SHOPS` (один список; нет модуля — пусто, строже)."""
    try:
        sys.path.insert(0, HERE)
        from drawing_dims import SHOPS
        return frozenset(SHOPS)
    except Exception:  # noqa: BLE001 — без модуля чертежей диваны судим как все: это строже, не мягче
        return frozenset()


def rows() -> list[list[str]]:
    like = ', '.join("'%" + f + "%'" for f in DIM_FIELDS)
    return db_rows(SQL % like)


def db_rows(sql: str) -> list[list[str]]:
    try:
        r = subprocess.run(PSQL, input=sql, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'база не опрошена: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(2)
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


def classify(mid: int, role: str, strat: str, w: bool, d: bool, h: bool, dia: bool, keys: list[str],
             drawing: frozenset = frozenset()) -> str | None:
    """Причина потери размеров у ОДНОГО товара: None — не потеря (годен или размерных полей нет), иначе одна из REASONS.
    Чистая функция — её проверяет селфтест (правило на случай)."""
    if strat == 'cutout' or not keys:
        return None
    horiz = w or dia
    need_h = not (strat == 'flat' and role in FLOOR_FLAT)
    if strat == 'flat':
        ok, depth_only = (horiz and (d or dia), False) if role in FLOOR_FLAT else (horiz and h, False)
    else:
        mesh_ok = horiz and h
        ok, depth_only = mesh_ok and (d or dia), mesh_ok and not (d or dia)
    if ok:
        return None
    hz = [k for k in keys if 'Высота' not in k]          # «Размеры: Высота габаритная», «Высота ворса» — тоже вертикаль
    if not hz:
        return 'height_only'
    if need_h and not h and not any('Высота' in k or VERT_COMPOSITE.match(k) for k in keys):
        return 'no_height'                                # высоту взять неоткуда — остальные оси её не заменят
    if depth_only and role in DRAWING_ROLES and mid in drawing and not any('Глубин' in k for k in keys):
        return 'drawing'
    if depth_only and len([k for k in hz if 'спальн' not in k]) <= 1:
        return 'one_horizontal'
    return 'fix'


def _strategy(role: str) -> str:
    """Способ отрисовки роли: от него зависит, что считать потерей. Без него сторож кричал бы
    на пледы и подушки, которым три оси не нужны по природе."""
    try:
        sys.path.insert(0, HERE)
        from render_strategy import base_role, strategy
        return strategy(base_role(role))
    except Exception:  # noqa: BLE001 — роль вне таблицы: судим как объёмную, это строже
        return 'mesh'


PROPOSE_SQL = """
select p.shop_mid, coalesce(p.cat_role,'(нет роли)'), kv.key, count(*)
  from products p, jsonb_each_text(coalesce(p.params,'{}'::jsonb)) kv(key, val)
 where p.in_stock and p.image_url is not null and p.cat_role is not null
   and (p.d_cm is null and p.dia_cm is null or p.w_cm is null and p.dia_cm is null
        or p.h_cm is null)
   and kv.key like any (array[%s])
   and kv.val ~ '[0-9]'
   -- ГАБАРИТЫ УПАКОВКИ — НЕ ГАБАРИТЫ ТОВАРА. В подсказке их быть не должно: разметишь
   -- «Длина упаковки 1 (см)» как глубину — и диван станет коробкой.
   and kv.key not ilike '%упаковк%' and kv.key not ilike '%брутто%'
 group by 1,2,3 having count(*) >= 20
 order by 1,2,4 desc;
"""


def propose() -> None:
    """Какие размерные поля ЕСТЬ у товаров с потерей — то есть кандидаты на разметку осей.

    Это и есть ответ на «какое поле куда отображать» для нового магазина: сторож показывает, что
    в фиде лежит заполненным, пока оси пустуют. Решение всё равно за человеком — конвенцию мерить
    на выборке (правило из шапки `dim_resolver.py`), но искать её больше не надо.
    """
    like = ', '.join("'%" + f + "%'" for f in DIM_FIELDS)
    cur, seen = None, 0
    print('\nЧТО ЛЕЖИТ В ФИДЕ У ТОВАРОВ С ПОТЕРЕЙ (кандидаты на разметку осей):')
    for r in db_rows(PROPOSE_SQL % like):
        if len(r) < 4:
            continue
        key = (r[0], r[1])
        if key != cur:
            cur, seen = key, 0
            print(f'  магазин {r[0]}, роль «{r[1]}»:')
        if seen < 6:
            print(f'      {r[2]:34} {r[3]:>6} товаров')
            seen += 1
    print('  Разметка живёт в `dim_resolver.SHOP_DIM_KEYS` — список групп «роли → оси» на магазин.')


def aggregate(items: list[list], only: str | None = None, drawing: frozenset = frozenset()) -> list[dict]:
    """Товары (mid, роль, w, d, h, dia, ключи через \\x1f) → строки «магазин × роль» со счётом причин и статусом.
    ЧТО СЧИТАЕТСЯ ПОТЕРЕЙ — ПО СПОСОБУ ОТРИСОВКИ (`render_strategy`), см. `classify`:
      mesh   — нужны и годность к генерации, и глубина (иначе не расставить);
      flat   — варпится по перспективе: на стене Ш×В, на полу (ковёр) Ш×Г;
      cutout — вклеивается силуэтом, размеры не нужны ВООБЩЕ (пледы, подушки — первая версия давала 4 ложные тревоги).
    Статус (`verdict`) — только по `fix`: тревога на то, что чинится нашим кодом."""
    t = lambda x: x in (True, 't', 'true')
    groups: dict[tuple, dict] = {}
    strat_of: dict[str, str] = {}
    for r in items:
        if len(r) < 7 or (only and str(r[0]) != str(only)):
            continue
        mid, role = str(r[0]), r[1]
        w, d, h, dia = t(r[2]), t(r[3]), t(r[4]), t(r[5])
        keys = [k for k in (r[6] or '').split('\x1f') if k]
        strat = strat_of.setdefault(role, _strategy(role))
        g = groups.setdefault((mid, role), {'mid': mid, 'role': role, 'strategy': strat, 'n': 0, 'mesh_ready': 0,
                                            'place_ready': 0, 'lost_mesh': 0, 'lost_depth': 0,
                                            **{k: 0 for k in REASONS}})
        g['n'] += 1
        mesh_ok = (w or dia) and h
        g['mesh_ready'] += bool(mesh_ok)
        g['place_ready'] += bool(w and h and (d or dia))
        why = classify(int(mid), role, strat, w, d, h, dia, keys, drawing)
        if why is None:
            continue
        g[why] += 1
        g['lost_depth' if strat != 'flat' and mesh_ok else 'lost_mesh'] += 1
    out = []
    for g in sorted(groups.values(), key=lambda x: (x['mid'], x['role'])):
        g['lost'] = g['fix']
        st, share = verdict(g['n'], g['lost'])
        g['share'], g['status'] = round(share, 3), st
        out.append(g)
    return out


def digest_lines(out: list[dict]) -> list[str]:
    """Строки DIGEST без тревоги — то, что загрузчик не вернёт: в фиде нет поля, или глубину знает только чертёж."""
    def top(key):
        rs = sorted((r for r in out if r[key]), key=lambda r: -r[key])
        return sum(r[key] for r in rs), ', '.join(f'{r["mid"]} «{r["role"]}» {r[key]}' for r in rs[:3])
    lines = []
    ho, ho_top = top('height_only')
    nh, nh_top = top('no_height')
    oh, oh_top = top('one_horizontal')
    if ho or nh or oh:
        parts = ([f'только высота — {ho} ({ho_top})'] if ho else []) + ([f'нет высоты — {nh} ({nh_top})'] if nh else []) \
            + ([f'одна горизонталь — {oh} ({oh_top})'] if oh else [])
        lines.append('DIGEST:размеры: в фиде не хватает поля, загрузчиком не вернуть — ' + '; '.join(parts))
    dr, dr_top = top('drawing')
    if dr:
        lines.append(f'DIGEST:размеры: глубина дивана — только с чертежа (drawing_dims), ждут {dr} ({dr_top})')
    return lines


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    only = arg('--mid')
    out = aggregate(rows(), only, drawing_shops())
    alarms = [r for r in out if r['status'] == 'ТРЕВОГА']
    print(f'{"магазин":>8} {"роль":14} {"как":7} {"всего":>6} {"меш":>6} {"расст.":>7} '
          f'{"нет меша":>9} {"нет глуб.":>10} {"чинится":>8} {"фид":>5} статус')
    for r in sorted(out, key=lambda x: -(x['lost_mesh'] + x['lost_depth']))[:40]:
        feed = r['height_only'] + r['no_height'] + r['one_horizontal'] + r['drawing']
        print(f'{r["mid"]:>8} {r["role"][:14]:14} {r["strategy"][:7]:7} {r["n"]:>6} '
              f'{r["mesh_ready"]:>6} {r["place_ready"]:>7} {r["lost_mesh"]:>9} '
              f'{r["lost_depth"]:>10} {r["lost"]:>8} {feed:>5} {r["status"]}'
              + (f' ({r["share"]:.0%})' if r['status'] == 'ТРЕВОГА' else ''))
    for line in digest_lines(out):
        print(line)
    p = arg('--json')
    if p:
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump({'min_n': MIN_N, 'max_unresolved': MAX_UNRESOLVED, 'rows': out}, fh,
                      ensure_ascii=False, indent=1)
        print(f'отчёт: {p}')
    if '--propose' in sys.argv:
        propose()
    if alarms:
        tot = sum(a['lost'] for a in alarms)
        msg = (f'ТРЕВОГ {len(alarms)}: размеры в фиде есть, а в работу не доехали у {tot} товаров.'
               f' Это молчаливая потеря — измерь конвенцию осей магазина'
               f' (`dim_resolver.SHOP_DIM_KEYS`, правило: мерить на выборке, не на примере).')
        # В ДНЕВНОМ ЦИКЛЕ ЭТО ПРЕДУПРЕЖДЕНИЕ, А НЕ СБОЙ. Контракт `refresh_daily.sh`: шаг со
        # строкой `WARN:<код>: текст` и кодом 0 попадает в дайджест предупреждением. Без `--warn`
        # сторож каждый день рисовал бы «СБОЙ» на известной проблеме, и отчёт перестали бы читать
        # (ровно то, от чего правило «успех уборки — это цифра» в lessons/mesh-salad-pool 427).
        if '--warn' in sys.argv:
            print(f'WARN:dims_lost: {msg}')
            return 0
        print('\n' + msg)
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
    # Причина по товару (T-22): правило на случай. (mid, роль, как, w, d, h, dia, ключи) → причина.
    DR = frozenset({114082})
    for args, want, why in (
        ((112923, 'ковёр', 'flat', True, True, False, False, ['Размеры: Длина габаритная', 'Размеры: Ширина габаритная']),
         None, 'ковёр Ш×Г без высоты — не потеря (лежит на полу)'),
        ((112923, 'ковёр', 'flat', True, False, False, False, ['Размеры: Длина габаритная', 'Размеры']), 'fix',
         'ковёр без глубины при поле «Размеры» — чинится'),
        ((112923, 'картина', 'flat', False, False, False, False, ['Размеры']), 'fix', 'картина «Размеры 60x80» — чинится'),
        ((112923, 'зеркало', 'flat', True, False, True, False, ['Размеры']), None, 'зеркало Ш×В без глубины — не потеря'),
        ((99272, 'растение', 'mesh', False, False, True, False, ['Высота']), 'height_only', 'только «Высота» — фид'),
        ((99272, 'растение', 'mesh', False, False, True, False, []), None, 'упаковка вычтена в SQL: ключей нет — не потеря'),
        ((99272, 'растение', 'mesh', False, True, True, False, ['Высота', 'Ширина']), 'fix',
         'одна горизонталь ушла в глубину, ширины нет — чинится'),
        ((99272, 'ваза', 'mesh', True, False, True, False, ['Высота', 'Ширина']), 'one_horizontal',
         'ширина есть, глубины нет, горизонталь одна — фид'),
        ((112098, 'ваза', 'mesh', True, False, True, False, ['Высота', 'Длина', 'Ширина']), 'fix',
         'две горизонтали, глубины нет (gipfel) — чинится'),
        ((114082, 'диван', 'mesh', True, False, True, False, ['Высота', 'Ширина', 'Ширина спального места']), 'drawing',
         'диван магазина с чертежом без «Глубины» — путь чертежа'),
        ((114082, 'диван', 'mesh', True, False, True, False, ['Высота', 'Ширина', 'Глубина']), 'fix',
         'поле «Глубина» есть — это не чертёж, чинится'),
        ((112923, 'диван', 'mesh', True, False, True, False, ['Высота', 'Ширина', 'Ширина спального места']),
         'one_horizontal', 'магазин без чертежа: спальное место не вторая горизонталь — фид'),
        ((114082, 'диван', 'mesh', True, False, False, False, ['Ширина', 'Высота']), 'fix',
         'высота в фиде есть и не понята — не «только глубина», чертёж не спасёт — чинится'),
        ((114082, 'диван', 'mesh', True, False, False, False, ['Ширина']), 'no_height',
         'нет высоты и поля под неё — фид'),
        ((99272, 'люстра', 'mesh', False, False, False, True, ['Диаметр', 'Длина цепи']), 'no_height',
         'люстра с одним «Диаметром»: высоты в фиде нет — фид'),
        ((99272, 'бра', 'mesh', True, False, False, False, ['Габариты (Д*Ш*В)', 'Ширина']), 'fix',
         'вертикаль в составном «Габариты» есть — чинится'),
        ((112923, 'картина', 'flat', False, False, False, False, ['Размеры: Длина габаритная']), 'no_height',
         '«Размеры: Длина габаритная» — горизонталь, не составное поле'),
        ((112923, 'ковёр', 'flat', True, False, False, False, ['Размеры: Длина габаритная', 'Ширина']), 'fix',
         'ковру высота не нужна — «нет высоты» к нему не применяется'),
        ((112923, 'зеркало', 'flat', False, False, False, False, ['Размеры: Высота габаритная']), 'height_only',
         '«Размеры: Высота габаритная» — тоже вертикаль'),
        ((93965, 'плед', 'cutout', False, False, False, False, ['Ширина']), None, 'вклейка — размеры не нужны'),
        ((99272, 'диван', 'mesh', True, True, True, False, ['Ширина']), None, 'все оси есть — не потеря'),
    ):
        got = classify(*args, drawing=DR)
        if got != want:
            bad += 1
            print(f'  FAIL {why}: {got}, ждали {want}')
    # Статус группы — только по «чинится»: 30 цветов «только высота» тревоги не дают, DIGEST — даёт.
    X = '\x1f'
    items = [[99272, 'растение', 'f', 'f', 't', 'f', 'Высота']] * 30 + [[99272, 'растение', 'f', 't', 't', 'f', f'Высота{X}Ширина']] * 2
    items += [[112923, 'картина', 'f', 'f', 'f', 'f', 'Размеры']] * 25
    items += [[114082, 'диван', 't', 'f', 't', 'f', f'Высота{X}Ширина']] * 21
    items += [[99272, 'люстра', 'f', 'f', 'f', 't', 'Диаметр']] * 7
    _strategy_cache = {'растение': 'mesh', 'картина': 'flat', 'диван': 'mesh'}
    real = globals()['_strategy']
    globals()['_strategy'] = lambda role: _strategy_cache.get(role, 'mesh')
    try:
        out = {(r['mid'], r['role']): r for r in aggregate(items, drawing=DR)}
    finally:
        globals()['_strategy'] = real
    pl, pic, sofa = out[('99272', 'растение')], out[('112923', 'картина')], out[('114082', 'диван')]
    for cond, why in (
        (pl['height_only'] == 30 and pl['fix'] == 2 and pl['status'] == 'ok', 'цветы: 30 фид + 2 чинится → ok (2/32 < 20 %)'),
        (pic['fix'] == 25 and pic['status'] == 'ТРЕВОГА' and pic['lost_mesh'] == 25, 'картины 25/25 → ТРЕВОГА, «нет меша»'),
        (sofa['drawing'] == 21 and sofa['status'] == 'ok' and sofa['lost_depth'] == 21, 'диваны 21 → чертёж, не тревога'),
        (aggregate(items, only='112923', drawing=DR)[0]['role'] == 'картина' and len(aggregate(items, only='112923')) == 1,
         '--mid оставляет один магазин'),
    ):
        if not cond:
            bad += 1
            print(f'  FAIL {why}')
    globals()['_strategy'] = lambda role: _strategy_cache.get(role, 'mesh')
    try:
        dl = digest_lines(aggregate(items, drawing=DR))
    finally:
        globals()['_strategy'] = real
    if not (len(dl) == 2 and all(x.startswith('DIGEST:') for x in dl) and 'только высота — 30' in dl[0]
            and 'нет высоты — 7' in dl[0] and 'ждут 21' in dl[1] and not any('WARN' in x for x in dl)):
        bad += 1
        print(f'  FAIL строки DIGEST: {dl}')
    if digest_lines(aggregate([[112923, 'картина', 'f', 'f', 'f', 'f', 'Размеры']] * 25)) != []:
        bad += 1
        print('  FAIL нечего сказать — DIGEST не печатаем')
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
