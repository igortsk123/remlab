#!/usr/bin/env python3
"""Интеграционный тест конвейера на ОДНОРАЗОВОЙ базе (план conv-06, «стыки на временной БД»).

Селфтесты проверяют правила по отдельности; поломки же случались НА СТЫКАХ: роль не доезжала до подбора (тв-тумбы,
11.10), размеры есть в фиде, но не в базе, повторная загрузка помечала всё «устаревшим» (13.10). Здесь мини-фид
(`tests/fixtures/feed-mini.xml.zip`, 14 офферов с разметкой случаев в `feed-mini.manifest.json`) проходит ТЕМ ЖЕ
путём, что ночью: схема (`bootstrap.sql` + реестр мешей `mesh_queue.SCHEMA` + миграции по порядку) → `load3.py` (разбор, роли, размеры, отпечатки,
наличие) → представление подбора `lr_roles` → метрики стыков `pipeline_map.collect()`. База `remlab_chaintest_<pid>`
создаётся в том же контейнере `remlab-devdb` и удаляется в `finally` — боевую базу тест не трогает.

  ~/venvs/scout/bin/python tests/pipeline_chain_dbtest.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.dirname(HERE)
FIX = os.path.join(HERE, 'fixtures')
DBNAME = f'remlab_chaintest_{os.getpid()}'
ADMIN = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'postgres', '-q', '-v', 'ON_ERROR_STOP=1', '-tA']
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', DBNAME, '-q', '-v', 'ON_ERROR_STOP=1', '-tA']
FAILS: list[str] = []


def sql(q: str, base: list | None = None) -> str:
    r = subprocess.run(base or PSQL, input=q, capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[:600])
    return r.stdout.strip()


def n(q: str) -> int:
    return int(sql(q) or 0)


def check(cond: bool, what: str) -> None:
    print(('  ok   ' if cond else '  FAIL ') + what, flush=True)
    if not cond:
        FAILS.append(what)


def load(feeds: str) -> str:
    env = {**os.environ, 'SCOUT_FEEDS_DIR': feeds, 'SCOUT_PSQL_CMD': ' '.join(PSQL[:-1]),   # без -tA: load3 читает свой вывод
           'SCOUT_ROLES_PATH': os.path.join(FIX, 'category-roles-mini.json'),
           'SCOUT_PRIORS_PATH': os.path.join(FIX, 'unit-priors-mini.json')}
    r = subprocess.run([sys.executable, os.path.join(SCOUT, 'load3.py')], env=env, capture_output=True, text=True,
                       timeout=600, cwd=SCOUT)
    if r.returncode:
        raise RuntimeError('load3: ' + (r.stdout[-800:] + r.stderr[-800:]))
    return r.stdout


def main() -> int:
    sql(f'create database {DBNAME}', ADMIN)
    feeds = tempfile.mkdtemp(prefix='chaintest-feeds-', dir=os.path.expanduser('~/.cache'))
    try:
        sql(open(os.path.join(SCOUT, 'bootstrap.sql'), encoding='utf-8').read())
        # реестр мешей создаёт сам конвейер (`mesh_queue.SCHEMA`) — миграции 006+ его дополняют
        os.environ['REMLAB_DEVDB_NAME'] = DBNAME
        sys.path.insert(0, SCOUT)
        import mesh_queue
        mesh_queue.db(mesh_queue.SCHEMA)
        for f in sorted(glob.glob(os.path.join(SCOUT, '[0-9][0-9][0-9]-*.sql'))):
            sql(open(f, encoding='utf-8').read())
        print('схема: bootstrap + миграции применены', flush=True)
        man = json.load(open(os.path.join(FIX, 'feed-mini.manifest.json'), encoding='utf-8'))
        shutil.copy(os.path.join(FIX, 'feed-mini.xml.zip'), feeds)

        out1 = load(feeds)
        got = n('select count(*) from products')
        # ожидание — тем же разбором, что у загрузчика (одна реализация): принятые офферы без дублей ключа
        import load3 as L3
        catrole, known = L3.load_roles(os.path.join(FIX, 'category-roles-mini.json'))
        offers, _raw = L3.parse_feed(os.path.join(FIX, 'feed-mini.xml.zip'), catrole, known)
        want = len({(o['mid'], o['eid']) for o in offers if o['accepted']})
        check(got == want and want < len(man), f'загрузка: товаров {got} = принятых разбором {want} (из {len(man)} офферов; '
              f'не гостиная и фурнитура отсеяны)')
        roles = n('select count(*) from products where cat_role is not null')
        check(roles > 0, f'роли из карты категорий доехали до товаров ({roles})')
        lr = n('select count(*) from lr_roles where role is not null')
        check(lr == roles, f'подбор видит те же роли: lr_roles {lr} = cat_role {roles} (стык «роль → подбор»)')
        dims = n('select count(*) from products where w_cm is not null and d_cm is not null')
        check(dims > 0, f'размеры разобраны ({dims})')
        hd = n('select count(*) from products where image_url_hd is not null')
        check(hd > 0, f'крупное фото из фида записано ({hd})')
        stale1 = n("select count(*) from product_enrichment where enrichment_status='stale'")

        out2 = load(feeds)                                           # та же выгрузка второй раз — ничего не меняется
        check(n('select count(*) from products') == got, 'повторная загрузка: число товаров то же')
        stale2 = n("select count(*) from product_enrichment where enrichment_status='stale'")
        check(stale2 == stale1, f'повторная загрузка не плодит «устаревшие» ({stale1} → {stale2})')

        import pipeline_map as PM
        m = PM.collect()
        for k in ('catalog_active', 'role_share', 'dims_share'):
            check(m.get(k) is not None and m[k] > 0, f'стык {k} считается на этой базе: {m.get(k)}')
        print('хвост загрузки:', (out1.strip().splitlines() or [''])[-1][:140], '|', (out2.strip().splitlines() or [''])[-1][:140])
    finally:
        shutil.rmtree(feeds, ignore_errors=True)
        sql(f'drop database if exists {DBNAME} with (force)', ADMIN)
    print('ИТОГ:', 'всё зелёное' if not FAILS else f'провалов {len(FAILS)}', flush=True)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
