"""Тень гостиной (room-pipeline-01 Б-1, T-20261105-39): адаптер `catalog_items.items('living')` против того, что сегодня
читает подбор гостиной `compose2.py`. Гостиная на адаптер не переведена — сначала доказываем паритет (цель — 0 расхождений).

Запрос гостиной берётся ИЗ ИСХОДНИКА compose2.py (`raw=rows(\"\"\"…\"\"\")`, разбор ast, без импорта: импорт compose2 запускает
полную сборку), с тем же условием `dimless.exclude_sql('p')` и тем же разбором вывода, что у `compose2.rows`. Поменялся
запрос в compose2 так, что разбор его не понимает, — отказ (тень устарела), а не молчаливый «паритет».
Адаптер берёт роли из профиля (T-20261105-43), а запрос compose2 — весь фид; первым шагом разбора compose2 отбрасывает
роли вне своего ROLES (`if role not in ROLES: continue`) — тень делает то же по ROLES из его исходника (`by_roles`), счёт
отброшенного — в отчёте `outside_roles`; шаг в compose2 изменился — отказ (`check_role_step`).

Сверяем: множество offer_id (только там / только тут, дубли), порядок выдачи и поля, которые compose2 берёт из строки:
роль, название, Ш/Г/длина/диаметр/В, цена, магазин, фото, прямая ссылка, текст «материал назначение тип», высота-улика
(источник, см, регулируемая, вылет подвеса). После чтения compose2 ещё отсекает протухшие фиды (feed-freshness.json) — это
уже отбор сборки, не чтение каталога; в отчёте — справкой.

    python catalog_items_shadow.py --room living [--out DIR]   # код 0 — расхождений нет, 1 — есть
    python catalog_items_shadow.py --selftest                  # без базы
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPOSE2 = os.path.join(HERE, 'compose2.py')
ROOMS = ('living',)   # тень есть только у гостиной: остальные комнаты читают адаптер напрямую
FIELDS = ('role', 'name', 'w', 'd', 'len', 'dia', 'h', 'price', 'shop', 'image', 'url', 'params', 'h_src', 'h_cm', 'h_adj',
          'h_drop')
NUMERIC = {'w', 'd', 'len', 'dia', 'h', 'price'}


def legacy_sql(src: str, exclude_sql=None) -> str:
    """SQL подбора гостиной из исходника compose2.py: присваивание `raw = rows(<строки> + _DL.exclude_sql('p') + …)`."""
    hits = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'raw' and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name) and n.value.func.id == 'rows']
    if len(hits) != 1:
        raise SystemExit(f'тень устарела: в compose2.py {len(hits)} присваиваний raw=rows(...), ждали 1')
    if exclude_sql is None:
        import dimless
        exclude_sql = dimless.exclude_sql

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return ev(n.left) + ev(n.right)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'exclude_sql'
                and isinstance(n.func.value, ast.Name) and n.func.value.id == '_DL'
                and all(isinstance(a, ast.Constant) for a in n.args) and not n.keywords):
            return exclude_sql(*[a.value for a in n.args])
        raise SystemExit(f'тень устарела: в запросе compose2 непонятный кусок {ast.dump(n)[:120]} (строка {n.lineno})')
    args = hits[0].value.args
    if len(args) != 1 or hits[0].value.keywords:
        raise SystemExit('тень устарела: rows(...) в compose2.py не с одним аргументом-запросом')
    return ev(args[0])


def legacy_rows(sql: str) -> list:
    """Как `compose2.rows`: psql с полем \\x1f, вывод strip() и split('\\n')."""
    psql = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
            '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
    r = subprocess.run(psql, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'запрос compose2 упал: {r.stderr[:400]}')
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


ROLE_STEP = re.compile(r'\nfor r in raw:\n\s+role=r\[0\]\n\s+if role not in ROLES: continue\n')


def check_role_step(src: str) -> None:
    """Тень отбрасывает роли вне ROLES до сверки, потому что compose2 делает это первым шагом разбора. Шаг изменился —
    отказ (тень устарела), а не молчаливый «паритет»."""
    if not ROLE_STEP.search(src):
        raise SystemExit('тень устарела: в compose2.py нет первого шага разбора «for r in raw: role=r[0]; '
                         'if role not in ROLES: continue»')


def by_roles(raw: list, roles=None) -> tuple:
    """Как первый шаг разбора compose2 (`if role not in ROLES: continue`): (строки с ролью из его ROLES, {роль: отброшено}).
    ROLES — из ИСХОДНИКА compose2 (`room_profile.compose2_roles`), не из профиля: тень сверяет с живым compose2."""
    if roles is None:
        import room_profile as RP
        roles = RP.compose2_roles()
    roles = set(roles)
    kept, dropped = [], {}
    for r in raw:
        if r and r[0] in roles:
            kept.append(r)
        else:
            k = r[0] if r else ''
            dropped[k] = dropped.get(k, 0) + 1
    return kept, dropped


def _n(v):
    return None if v in (None, '') else float(v)


def from_legacy(r: list) -> tuple:
    """Строка compose2 → (offer_id, поля); пустая строка psql = NULL. Короче 18 полей — как читает compose2: хвост с 14-го
    `r[i] if len(r) > i else ''` (у последней строки `strip()` съедает пустые хвостовые поля: \x1f для Python — пробел);
    короче 14 — строка порвана (перевод строки в значении), это расхождение."""
    if len(r) < 14 or len(r) > 18:
        return f'{r[1] if len(r) > 1 else "?"}:{r[2] if len(r) > 2 else "?"}', {'_broken': f'полей {len(r)}'}
    r = r + [''] * (18 - len(r))
    v = dict(role=r[0], name=r[3], w=r[4], d=r[5], len=r[6], dia=r[7], h=r[8], price=r[9], shop=r[10], image=r[11], url=r[12],
             params=r[13], h_src=r[14], h_cm=r[15], h_adj=r[16], h_drop=r[17])
    return f'{r[1]}:{r[2]}', {k: (_n(x) if k in NUMERIC else (x or '')) for k, x in v.items()}


def from_item(c) -> list:
    """CatalogItem → [(offer_id, поля)] по роли — в форме строки compose2 (NULL текста — '')."""
    p, e, d = c.params, c.dims['h_evidence'], c.dims
    out = []
    for role in c.roles:
        v = dict(role=role, name=c.name, w=d['w'], d=d['d'], len=d['len'], dia=d['dia'], h=d['h'], price=c.price, shop=c.shop,
                 image=c.photo['url'], url=c.url_direct,
                 params=f"{p.get('Материал') or ''} {p.get('Назначение') or ''} {p.get('Тип') or ''}",
                 h_src=e['source'], h_cm=e['cm'], h_adj=p.get('Регулируемая высота'), h_drop=e['drop_min'])
        out.append((c.offer_id, {k: (x if k in NUMERIC else (x or '')) for k, x in v.items()}))
    return out


def compare(legacy: list, adapter: list, sample: int = 20) -> dict:
    """legacy, adapter — [(offer_id, поля)] в порядке выдачи."""
    def index(seq):
        m, dup = {}, []
        for k, v in seq:
            (dup.append(k) if k in m else m.__setitem__(k, v))
        return m, dup
    L, ldup = index(legacy)
    A, adup = index(adapter)
    only_l = [k for k in L if k not in A]
    only_a = [k for k in A if k not in L]
    fields: dict = {}
    for k in L:
        if k in A and L[k] != A[k]:
            for f in sorted(set(L[k]) | set(A[k])):
                if L[k].get(f) != A[k].get(f):
                    fields.setdefault(f, []).append({'offer': k, 'compose2': L[k].get(f), 'adapter': A[k].get(f)})
    ol = [k for k, _ in legacy if k in A]
    oa = [k for k, _ in adapter if k in L]
    order_first = next((i for i, (x, y) in enumerate(zip(ol, oa)) if x != y), None)
    n_diff = len(only_l) + len(only_a) + len(ldup) + len(adup) + sum(len(v) for v in fields.values()) + (order_first is not None)
    return {'compose2': len(legacy), 'adapter': len(adapter), 'diff': n_diff,
            'only_compose2': {'n': len(only_l), 'sample': only_l[:sample]},
            'only_adapter': {'n': len(only_a), 'sample': only_a[:sample]},
            'dup_compose2': ldup[:sample], 'dup_adapter': adup[:sample],
            'fields': {f: {'n': len(v), 'sample': v[:sample]} for f, v in fields.items()},
            'order_first_mismatch': order_first}


def stale_info(legacy: list) -> dict:
    """Справка: сколько офферов compose2 отсечёт после чтения как протухший фид (то же правило, что в compose2)."""
    try:
        fresh = json.load(open(os.path.join(HERE, 'feed-freshness.json')))
        mids = {int(m) for rec in fresh.values() if rec.get('state') in ('stale', 'broken') for m in rec.get('mids', [])}
    except Exception as e:  # noqa: BLE001 — справка, не сверка
        return {'error': str(e)[:200]}
    return {'stale_mids': sorted(mids), 'offers': sum(1 for k, _ in legacy if int(k.split(':')[0]) in mids)}


def run(room: str, out_dir: str) -> int:
    if room not in ROOMS:
        raise SystemExit(f'тень есть только у {ROOMS}, не {room!r}')
    import catalog_items as CI
    t = time.time()
    src = open(COMPOSE2, encoding='utf-8').read()
    check_role_step(src)
    raw = legacy_rows(legacy_sql(src))
    kept, dropped = by_roles(raw)
    legacy = [from_legacy(r) for r in kept]
    adapter = [x for c in CI.items(room) for x in from_item(c)]
    rep = compare(legacy, adapter)
    rep.update(room=room, short_tail_rows=sum(1 for r in raw if 14 <= len(r) < 18), stale_after_read=stale_info(legacy),
               outside_roles={'n': sum(dropped.values()), 'by_role': dropped,
                              '_why': 'строки запроса compose2 с ролью вне его ROLES — он их отбрасывает первым же шагом, адаптер '
                                      '(роли профиля) их не читает'},
               seconds=round(time.time() - t, 1),
               at=time.strftime('%Y-%m-%d %H:%M:%S'))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'catalog-shadow-{room}.json')
    json.dump(rep, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"тень {room}: compose2 {rep['compose2']}, адаптер {rep['adapter']}, расхождений {rep['diff']} "
          f"(только compose2 {rep['only_compose2']['n']}, только адаптер {rep['only_adapter']['n']}, "
          f"поля {sum(v['n'] for v in rep['fields'].values())}, порядок {'ок' if rep['order_first_mismatch'] is None else 'нет'})")
    print(f'отчёт: {path}')
    return 0 if rep['diff'] == 0 else 1


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    src = 'x=1\nraw=rows("""select a from p where """+_DL.exclude_sql(\'p\')+""" order by 1""")\n'
    ok('запрос из исходника + условие dimless', legacy_sql(src, lambda a: f'X({a})') == 'select a from p where X(p) order by 1')
    for bad_src, why in (('raw=rows("a"+f(x))', 'чужой вызов'), ('y=1', 'нет raw'), ('raw=rows("a")\nraw=rows("b")', 'два raw')):
        try:
            legacy_sql(bad_src, lambda a: '')
            ok(f'устаревшая тень — отказ ({why})', False)
        except SystemExit:
            ok(f'устаревшая тень — отказ ({why})', True)
    real = legacy_sql(open(COMPOSE2, encoding='utf-8').read(), lambda a: 'true')
    ok('запрос живого compose2.py разбирается', real.startswith('select p.cat_role, p.shop_mid') and 'from products p' in real)
    row = ['лампа', '1', 'a', 'Лампа', '20', '', '', '', '45', '4990', 'М', 'http://i', 'http://d', 'хлопок  ', '', '', '', '']
    k, v = from_legacy(row)
    ok('строка compose2: числа, NULL', k == '1:a' and v['w'] == 20.0 and v['d'] is None and v['params'] == 'хлопок  ')
    ok('последняя строка без пустого хвоста — как у compose2', from_legacy(row[:14]) == (k, v)
       and '_broken' in from_legacy(row[:12])[1])
    import catalog_items as CI
    prow = ['лампа', '1', 'a', 'Лампа', 'М', None, '4990', 't', '20', None, '45', None, None, None, None, None, None,
            'http://i', None, 't', 'http://u', 'http://d', 'хлопок', None, None, None, None, None, None]
    c = CI.product_item(prow, 'living', [])
    ok('адаптер в форме compose2 — равно', from_item(c) == [(k, v)])
    r = compare([(k, v), ('2:b', v)], [('2:b', v), (k, dict(v, w=21.0)), ('3:c', v)])
    ok('сверка: только там/тут, поле, порядок', r['only_compose2']['n'] == 0 and r['only_adapter']['n'] == 1
       and r['fields']['w']['n'] == 1 and r['order_first_mismatch'] == 0 and r['diff'] == 3)
    ok('сверка: равные — 0', compare([(k, v)], [(k, dict(v))])['diff'] == 0)
    kept, dropped = by_roles([row, ['шкаф'] + row[1:], ['шкаф'] + row[1:]], ['лампа'])
    ok('роли вне ROLES compose2 отброшены, со счётом', kept == [row] and dropped == {'шкаф': 2})
    check_role_step(open(COMPOSE2, encoding='utf-8').read())
    ok('живой compose2.py: первый шаг разбора — роль из ROLES', True)
    try:
        check_role_step('for r in raw:\n    role=r[0]\n    pass\n')
        ok('шаг ролей изменился — отказ', False)
    except SystemExit:
        ok('шаг ролей изменился — отказ', True)
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    room = argv[argv.index('--room') + 1] if '--room' in argv else 'living'
    out = argv[argv.index('--out') + 1] if '--out' in argv else os.path.expanduser(
        f'~/remlab-logs/catalog-shadow-{time.strftime("%m%d-%H%M")}')
    return run(room, out)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
