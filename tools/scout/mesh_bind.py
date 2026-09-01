#!/usr/bin/env python3
"""ПОМЕТКА «ТРЕБУЕТСЯ МЕШ» И ЖЁСТКАЯ ССЫЛКА НА ГОТОВЫЙ МЕШ В КАРТОЧКЕ ТОВАРА.

Решение владельца 01.09: «в структуру как хранятся товары туда и надо пометку типа
требуется меш, и все туда смотрят. Как меш готов — там ссылка на меш и дата изготовления».

Что делает (идемпотентно, безопасно повторять):
  1. `products.mesh_required` — из канона ролей `rules/asset-strategies.json` (политика v2:
     свет и вазы требуют мешей, ковры/пледы/шторы/зеркала/картины — нет). Пишется ВСЕМ
     активным товарам, чтобы «все смотрели туда», а не пересчитывали правило у себя.
  2. `products.mesh_uri / mesh_at / mesh_revision_key / mesh_status` — по факту готовых
     моделей на диске: ссылка на модель, дата изготовления (mtime файла), ключ ревизии.
     История ревизий и брак остаются в `asset_revisions` — здесь только указатель
     на текущий рабочий меш.

Запуск:
  ~/venvs/scout/bin/python mesh_bind.py            # пометить + привязать
  ~/venvs/scout/bin/python mesh_bind.py --report   # только показать состояние
"""
import datetime
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))
MESH_DIR = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
MESH_HTTP = os.environ.get('MESH_HTTP', 'https://remont-lab.online/test/mesh-pilot10')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '|']


def sql(q: str) -> list[str]:
    r = subprocess.run(PSQL + ['-c', q], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return [x for x in r.stdout.strip().splitlines() if x]


def sql_stdin(script: str) -> None:
    r = subprocess.run(PSQL, input=script, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])


def mark_required() -> tuple[int, int]:
    """Пометка «нужен ли меш» по канону ролей — одной транзакцией, без построчных вызовов."""
    import asset_strategy as AS
    roles = [r for r in sql("select distinct cat_role from products where cat_role is not null")]
    need = [r for r in roles if AS.strategy(r) == 'hunyuan3d']
    skip = [r for r in roles if AS.strategy(r) != 'hunyuan3d']

    def lit(xs):
        return ','.join("'" + x.replace("'", "''") + "'" for x in xs) or "''"
    ver = AS.policy_version()
    # СПОСОБ ПОПАДАНИЯ В СЦЕНУ пишем ВСЕМ (владелец 01.09: «ковры и пледы надо пометить
    # в базе, что они идут вклейкой вместо меша») — чтобы это было видно в карточке,
    # а не выводилось каждым потребителем заново.
    by_strategy = {}
    for r in roles:
        by_strategy.setdefault(AS.strategy(r), []).append(r)
    upd = '\n'.join(
        f"update products set asset_strategy = '{st}' where cat_role in ({lit(rs)}) "
        f"and asset_strategy is distinct from '{st}';"
        for st, rs in by_strategy.items())
    sql_stdin('begin;\n' + upd + '\ncommit;')
    # ГЕЙТЫ КАНОНИЧЕСКОГО ПОРЯДКА обязательны (владелец 01.09, дважды): меш нужен только
    # тому, кто в наличии, с фото, ПРОШЁЛ обогащение и стили и имеет габариты. Пометка
    # только по роли завышала число (17 379 против настоящих 12 092).
    GATES = ("p.in_stock and p.image_url is not null and p.w_cm is not null "
             "and p.h_cm is not null and e.enriched_at is not null "
             "and e.payload->'model'->'styles' is not null")
    JOIN = ("from products p join product_enrichment e "
            "on e.shop_mid = p.shop_mid and e.external_id = p.external_id")
    sql_stdin(f"""begin;
-- сначала снимаем пометку со всех, потом ставим прошедшим цепочку: так снятие товара с
-- продажи или пропавшие габариты сами гасят требование
update products set mesh_required = false, mesh_policy_version = {ver}
 where mesh_required is distinct from false;
update products p set mesh_required = true, mesh_policy_version = {ver}
  from product_enrichment e
 where e.shop_mid = p.shop_mid and e.external_id = p.external_id
   and p.cat_role in ({lit(need)})
   and p.in_stock and p.image_url is not null and p.w_cm is not null and p.h_cm is not null
   and e.enriched_at is not null and e.payload->'model'->'styles' is not null;
commit;""")
    return len(need), len(skip)


def bind_ready() -> int:
    """Привязка готовых моделей: ссылка + дата изготовления в карточке товара."""
    rows = []
    for sku_dir in sorted(glob.glob(os.path.join(MESH_DIR, '*'))):
        sku = os.path.basename(sku_dir).replace('_', ':', 1)
        # берём САМУЮ СВЕЖУЮ модель товара (последний перегон)
        models = sorted(glob.glob(os.path.join(sku_dir, '*', 'model.glb')),
                        key=os.path.getmtime)
        if not models:
            continue
        glb = models[-1]
        job = os.path.basename(os.path.dirname(glb))
        at = datetime.datetime.fromtimestamp(os.path.getmtime(glb),
                                             datetime.timezone.utc).isoformat()
        uri = f'{MESH_HTTP}/{os.path.basename(sku_dir)}/model.glb'
        rows.append((sku, uri, at, f'{sku}|{job}'))
    if not rows:
        return 0
    vals = ','.join("('" + s.replace("'", "''") + "','" + u + "','" + a + "','"
                    + k.replace("'", "''") + "')" for s, u, a, k in rows)
    sql_stdin(f"""begin;
create temp table _bind(sku text, uri text, at timestamptz, rk text) on commit drop;
insert into _bind values {vals};
update products p set mesh_uri = b.uri, mesh_at = b.at, mesh_revision_key = b.rk,
                      mesh_status = 'ready'
  from _bind b
 where p.shop_mid || ':' || p.external_id = b.sku
   and (p.mesh_uri is distinct from b.uri or p.mesh_at is distinct from b.at);
commit;""")
    return len(rows)


def report() -> None:
    r = sql("""select
      count(*) filter (where mesh_required) as нужен,
      count(*) filter (where mesh_required and mesh_status='ready') as готов,
      count(*) filter (where mesh_required and coalesce(mesh_status,'none')='none') as ждут,
      count(*) filter (where mesh_required is false) as не_нужен
      from products where in_stock""")
    need, ready, wait, no = (r[0].split('|') + ['0'] * 4)[:4]
    print(f'требуется меш ....... {need}')
    print(f'  готов (есть ссылка) {ready}')
    print(f'  ждут генерации .... {wait}')
    print(f'меш не требуется .... {no}')
    ex = sql("""select mesh_uri, to_char(mesh_at,'YYYY-MM-DD HH24:MI')
                from products where mesh_status='ready' order by mesh_at desc limit 2""")
    for e in ex:
        u, a = e.rsplit('|', 1)
        print(f'  пример: {a}  {u}')


def main() -> None:
    if '--report' not in sys.argv:
        n_need, n_skip = mark_required()
        n_bind = bind_ready()
        print(f'пометка по канону: ролей требующих меша {n_need}, не требующих {n_skip}')
        print(f'привязано моделей: {n_bind}')
    report()


if __name__ == '__main__':
    main()
