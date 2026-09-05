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
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'salad'))
sys.path.insert(0, HERE)   # корень побеждает salad/ (см. render_strategy.py)
# Источник привязки — реестр поколений `mesh_generations` (05.09), не обход диска: диск читает
# `salad/ingest_registry.py` шагом раньше, и «текущее поколение» решается в одном месте.
MESH_HTTP = os.environ.get('MESH_HTTP', 'https://remont-lab.online/test/mesh-pilot10')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab',
        '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),   # одноразовая база для --dbtest
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '|']


def sql(q: str) -> list[str]:
    r = subprocess.run(PSQL + ['-c', q], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return [x for x in r.stdout.strip().splitlines() if x]


def sql_stdin(script: str) -> list[str]:
    r = subprocess.run(PSQL, input=script, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return [x for x in r.stdout.strip().splitlines() if x]


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


def current_generations() -> list[tuple[str, str, str, str, str]]:
    """(sku, generation_key, job_id, generated_at, owner_verdict) — ТЕКУЩЕЕ поколение каждого
    товара из реестра `mesh_generations` (его заполняет `salad/ingest_registry.py` шагом раньше).
    «Текущее» — то же правило, что у реестра: позднее по времени, при равенстве — большее по ключу."""
    # Разделитель — \x1f, а не «|»: ключ поколения сам состоит из «|».
    r = subprocess.run(PSQL[:-1] + ['\x1f', '-c',
                       "select sku, generation_key, job_id, generated_at, coalesce(owner_verdict,'') "
                       "from (select distinct on (sku) sku, generation_key, job_id, generated_at, owner_verdict "
                       "        from mesh_generations order by sku, generated_at desc, generation_key desc) t"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    out = []
    for ln in r.stdout.splitlines():
        parts = ln.split('\x1f')
        if len(parts) == 5 and parts[0]:
            out.append(tuple(parts))
    return out


def bind_ready() -> tuple[int, int]:
    """Привязка ТЕКУЩЕГО поколения к карточке товара; отвергнутое владельцем — явная отвязка.

    Раньше бралась «самая свежая model.glb на диске» без оглядки на решение человека, а
    отвязки не было вовсе: отсутствие строки ничего не снимало (разбор Codex 05.09). Теперь
    источник — реестр поколений, и правило одно: текущее поколение отвергнуто → товар БЕЗ меша
    (`mesh_status='rejected'`, ссылка пуста) до следующего перегона. Старые попытки НЕ
    воскрешаются — от них система уже отказалась (приёмка завернула, был перегон).
    Возвращает (привязано, отвязано)."""
    rows = current_generations()
    if not rows:
        print('реестр поколений пуст — привязку не трогаю (сначала ingest_registry.py)', flush=True)
        return 0, 0
    vals = ','.join(
        "(" + ','.join(("'" + str(x).replace("'", "''") + "'") for x in
                       (sku, f'{MESH_HTTP}/{sku.replace(":", "_", 1)}/model.glb', at, f'{sku}|{job}', gk))
        + f", {'true' if verdict else 'false'})"
        for sku, gk, job, at, verdict in rows)
    out = sql_stdin(f"""begin;
create temp table _bind(sku text, uri text, at timestamptz, rk text, gk text, rejected boolean) on commit drop;
insert into _bind values {vals};
update products p set mesh_uri = b.uri, mesh_at = b.at, mesh_revision_key = b.rk,
                      mesh_generation_key = b.gk, mesh_status = 'ready'
  from _bind b
 where p.shop_mid || ':' || p.external_id = b.sku and not b.rejected
   and (p.mesh_uri is distinct from b.uri or p.mesh_at is distinct from b.at
        or p.mesh_generation_key is distinct from b.gk);
select 'bound '||count(*) from _bind where not rejected;
update products p set mesh_uri = null, mesh_at = null, mesh_revision_key = null,
                      mesh_generation_key = null, mesh_status = 'rejected'
  from _bind b
 where p.shop_mid || ':' || p.external_id = b.sku and b.rejected
   and (p.mesh_uri is not null or p.mesh_status is distinct from 'rejected');
select 'unbound '||count(*) from _bind where rejected;
commit;""")
    nums = {x.split()[0]: int(x.split()[1]) for x in out if x.startswith(('bound ', 'unbound '))}
    return nums.get('bound', 0), nums.get('unbound', 0)


def enforce_ready_invariant() -> tuple[int, int]:
    """Инвариант (Codex 03.09, план catalog-load-hardening П2): `mesh_status='ready'` допустим ТОЛЬКО
    когда у товара есть не-legacy ревизия (accepted|generated) по ТЕКУЩЕМУ фото — хеш фото в ключе
    ревизии (16 знаков) совпадает с `product_photo_current.source_sha`. Иначе — `stale`: модель есть,
    но сделана по старой картинке (или фото ещё не захешировано). Раньше `bind_ready()` ставил ready
    по «самому свежему model.glb на диске», и `mesh_ready()` с `products.mesh_status` спорили.
    → (стало stale, вернулось в ready)."""
    out = sql("""begin;
create temp table _inv on commit drop as
select p.shop_mid, p.external_id,
       exists (select 1 from asset_revisions r
                 join product_photo_current c on c.sku = r.sku
                where r.sku = p.shop_mid||':'||p.external_id
                  and r.status in ('accepted','generated') and r.origin <> 'legacy-local'
                  and c.source_sha like split_part(r.revision_key,'|',2)||'%') as ok
  from products p where p.mesh_uri is not null;
update products p set mesh_status = 'stale' from _inv i
 where p.shop_mid = i.shop_mid and p.external_id = i.external_id and not i.ok and p.mesh_status = 'ready';
select 'stale '||count(*) from _inv where not ok;
update products p set mesh_status = 'ready' from _inv i
 where p.shop_mid = i.shop_mid and p.external_id = i.external_id and i.ok and p.mesh_status is distinct from 'ready';
select 'ready '||count(*) from _inv where ok;
commit;""")
    nums = [int(x.split()[1]) for x in out if x.startswith(('stale ', 'ready '))]
    return (nums + [0, 0])[:2]


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
        n_bind, n_unbind = bind_ready()
        n_stale, n_ready = enforce_ready_invariant()
        print(f'пометка по канону: ролей требующих меша {n_need}, не требующих {n_skip}')
        print(f'привязано моделей: {n_bind}, отвязано по отказу владельца: {n_unbind}; '
              f'инвариант «ready = ревизия по текущему фото»: ready {n_ready}, stale {n_stale}')
    report()


if __name__ == '__main__':
    main()
