#!/usr/bin/env python3
"""Воронка конвейера: сколько товаров помечено на каждом этапе — одним экраном.

ЗАЧЕМ. Владелец принимает решение «переключать ли на прод» по соотношениям между этапами,
а не по одному числу. Каждая строка — этап канона (`core/pipeline-order.md`), каждое число —
живой запрос к базе, не кэш и не память. Если соотношение выглядит странно, это повод не
верить этапу и разбираться, а не повод верить воронке.

  ~/venvs/scout/bin/python pipeline_funnel.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# ПОРЯДОК ВАЖЕН: `asset_strategy.py` существует в ДВУХ копиях — здесь и в `salad/` (вторая
# нужна внутри docker-образа воркера). Если salad идёт первым, канон берётся из копии образа.
sys.path.insert(0, os.path.join(HERE, 'salad'))
sys.path.insert(0, HERE)

from asset_strategy import non_mesh_roles  # noqa: E402
from mesh_queue import db, q  # noqa: E402
from preprocess import ASSESSOR_VERSION     # noqa: E402

POOL = ("from products p join product_enrichment e using (shop_mid, external_id) "
        "where p.cat_role is not null and p.status='active' and p.in_stock "
        "and p.image_url is not null and p.price_rub is not null "
        "and e.status='active' and e.payload is not null and e.quality>=0.65")
EX = ','.join(q(r) for r in sorted(non_mesh_roles()))


def n(sql: str) -> int:
    r = db(sql)
    return int(r[0][0]) if r and r[0] and r[0][0] else 0


def main() -> None:
    rows = []

    def stage(name, val, base=None, note=''):
        share = f'{100 * val / base:5.1f}%' if base else '      '
        rows.append((name, val, share, note))

    total = n('select count(*) from products')
    stage('1  каталог (фиды+API)', total)
    role = n("select count(*) from products where cat_role is not null")
    stage('   с ролью', role, total)
    instock = n("select count(*) from products where cat_role is not null "
                "and status='active' and in_stock")
    stage('2  активен и в наличии', instock, role)
    photo = n("select count(*) from products where cat_role is not null and status='active' "
              "and in_stock and image_url is not null and price_rub is not null")
    stage('   с фото и ценой', photo, instock)
    hd = n("select count(*) from products where cat_role is not null and status='active' "
           "and in_stock and image_url_hd is not null")
    stage('   из них с HD-фото (API)', hd, photo, '800×600 против 450')
    enr = n(f'select count(*) {POOL}')
    stage('3  ОТБОР: обогащение+quality≥0.65', enr, photo)
    hashed = n("select count(*) from product_photo_current c "
               "join products p on p.shop_mid||':'||p.external_id = c.sku "
               f"{POOL.split('where')[0].replace('from products p','').strip()} "
               .replace('join product_enrichment', 'join product_enrichment')
               if False else
               "select count(*) from product_photo_current")
    stage('4  ОБРЕЗКА: хеш фото посчитан', hashed, enr)
    assessed = n("select count(distinct c.sku) from product_photo_current c "
                 "join photo_assessment a on a.source_sha = c.source_sha "
                 f"and a.assessor_version = {q(ASSESSOR_VERSION)}")
    stage('   вырезано и оценено', assessed, hashed)
    for verdict, label in (('ok', 'годных (ok)'), ('collage', 'коллажей'),
                           ('bad_cutout', 'брак маски'), ('tiny_object', 'товар мелкий')):
        v = n("select count(distinct c.sku) from product_photo_current c "
              "join photo_assessment a on a.source_sha = c.source_sha "
              f"and a.assessor_version = {q(ASSESSOR_VERSION)} "
              f"where a.verdict = {q(verdict)}")
        if v or verdict == 'ok':
            stage(f'     · {label}', v, assessed)
    meshable = n("select count(distinct c.sku) from product_photo_current c "
                 "join products p on p.shop_mid||':'||p.external_id = c.sku "
                 "join photo_assessment a on a.source_sha = c.source_sha "
                 f"and a.assessor_version = {q(ASSESSOR_VERSION)} "
                 f"where a.verdict='ok' and p.cat_role not in ({EX}) "
                 "and p.in_stock and p.status='active'")
    stage('5  ОЧЕРЕДЬ МЕШЕЙ: годных объёмных', meshable, assessed, 'минус мягкий декор')
    demand = n("select count(*) from mesh_demand where status='wanted'")
    stage('   спрос учтён (mesh_demand)', demand)
    jobs = n("select count(*) from mesh_jobs where status in ('queued','submitted','running')")
    stage('6  ГЕНЕРАЦИЯ: дневная партия', jobs, None, 'планировщик, предел '
          + os.environ.get('MESH_DAILY_BATCH', '10'))
    accepted = n("select count(distinct sku) from asset_revisions where status='accepted'")
    stage('   мешей принято', accepted)
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    stage('7  СЕТЫ: комплектов', len(sets))
    try:
        from render_strategy import asset_ready, base_role
        full = sum(1 for s in sets
                   if all(asset_ready(f"{it['mid']}:{it['eid']}", base_role(sl))
                          for sl, it in (s.get('items') or {}).items()
                          if it and it.get('mid')))
        stage('   полностью готовых к показу', full, len(sets), 'asset_ready по стратегии')
    except Exception as e:  # noqa: BLE001
        rows.append(('   готовность не посчиталась', 0, '', str(e)[:50]))

    w = max(len(r[0]) for r in rows) + 2
    print(f"{'этап':{w}}{'товаров':>9}{'доля':>8}  примечание")
    print('-' * (w + 30))
    for name, val, share, note in rows:
        print(f'{name:{w}}{val:>9}{share:>8}  {note}')


if __name__ == '__main__':
    main()
