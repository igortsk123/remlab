#!/usr/bin/env python3
"""Кого генерить СЕГОДНЯ. Между этапом «очередь» и этапом «генерация».

ЗАЧЕМ ОТДЕЛЬНЫЙ ШАГ (критика Codex 29.08). В очереди ~13 000 товаров, а карта делает десятки
в день. Если создавать задания на весь спрос и брать их по порядку SKU, то каждый прогон
одинаково бесполезен: меши появляются равномерно по каталогу и НИ ОДИН сет не становится
готовым целиком. Полезность измеряется не числом мешей, а числом сетов, которые благодаря им
можно показать.

Поэтому дневная партия набирается по приросту ГОТОВЫХ СЕТОВ, ярусами:
  1 — комплекты В ПОРЯДКЕ БЛИЗОСТИ К ГОТОВНОСТИ, каждый добивается целиком. Прежняя схема
      «сначала все предметы всех сетов подряд, потом отдельный ярус замыкания» была мертва
      по построению (Codex P2-10): первый ярус помечал всё как seen, и замыкание не получало
      ни одного товара — при партии 10 мы месяцами гнали бы первые сеты по порядку номеров;
  2 — дефицит готовых заменителей у занятых слотов: без него автозамена не работает;
  3 — проблемные роли по вердиктам обрезки: их надо проверить пилотом раньше планов;
  4 — хвост.

Задания (`mesh_jobs`) создаются ТОЛЬКО на выбранную партию. Всё остальное остаётся спросом.

  ~/venvs/scout/bin/python mesh_scheduler.py            # набрать партию и поставить задания
  ~/venvs/scout/bin/python mesh_scheduler.py --dry      # показать, кого бы взял
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mesh_queue import PIPELINE_VERSION, db, q, passport_observe, passport_report  # noqa: E402
from render_strategy import asset_ready, base_role, strategy  # noqa: E402
from mesh_ready import revision_current_sql  # noqa: E402

SETS = os.path.join(HERE, 'sets3.json')
DAILY = int(os.environ.get('MESH_DAILY_BATCH', '10'))


def _needs_mesh(sku: str, role: str) -> bool:
    """Нужен ли товару меш вообще. Мягкому декору — нет, и в партию он не попадает."""
    # `render_strategy.strategy()` уже переводит канон ролей: второй список исключений
    # здесь был бы третьей истиной — ровно из-за неё и сломались импорты.
    return strategy(role) == 'mesh' and not asset_ready(sku)


def _queue() -> dict[str, str]:
    """SKU → роль: спрос с посчитанным хешом фото, ещё без годной ревизии ТЕКУЩЕГО фото."""
    # Сверка по ХЕШУ ТЕКУЩЕГО ФОТО и версии конвейера, не по SKU (Codex P1-6): иначе меш от старого фото навсегда
    # закрывает дорогу новому — сменилась картинка, а SKU «уже готов». Условие — то же, что у готовности меша
    # (`mesh_ready.revision_current_sql`, T-20261118-04/22, Codex 18.11): accepted ИЛИ generated, не legacy, хеш фото в ключе ревизии (16 знаков)
    # — префикс полного `source_sha` спроса. Прежняя проверка сравнивала ключ с ПОЛНЫМ хешом и только `accepted`: ревизия 16-значного ключа
    # его не находила никогда, и меш, уже сделанный по текущему фото (ждёт ориентации), ставился в генерацию повторно.
    # Есть такая ревизия — генерацию не ставим: следующее действие — ориентация (`orient_worker`), не новый меш.
    rows = db(
        "select d.sku, d.role from mesh_demand d "
        " where d.status='wanted' and d.source_sha is not null "
        "   and not " + revision_current_sql('d.sku', 'd.source_sha', PIPELINE_VERSION) + " "
        "   and not exists (select 1 from mesh_jobs j "
        "        where j.job_key = d.sku||'|'||d.source_sha||'|'||" + q(PIPELINE_VERSION) + " "
        "          and j.status in ('queued','submitted','running'))")
    out = {r[0]: r[1] for r in rows if len(r) == 2}
    passport_observe(out)      # фаза 1 «тень»: гейт паспорта в observe — только счётчик, очередь не меняется
    return out


def _stamp_digest(job_key: str, sku: str) -> None:
    """Хеш паспорта типа — в колонку `mesh_jobs.passport_digest` ОТДЕЛЬНЫМ update (вставка и ключ задания не меняются; в `job_key` хеш не входит).
    Роль берём из спроса. Нет колонки (миграция 018 не применена)/сбой — одна WARN-строка и дальше: задание уже поставлено."""
    try:
        import mesh_type_passports as MTP
        role = db(f"select role from mesh_demand where sku={q(sku)}")
        dg = MTP.digest(role[0][0]) if role and role[0] else None
        if dg:
            db(f"update mesh_jobs set passport_digest={q(dg)} where job_key={q(job_key)}")
    except Exception as e:  # noqa: BLE001
        import mesh_type_passports as MTP
        MTP.warn_once('stamp', f'WARN:passport_shadow: хеш паспорта в задании не записан ({type(e).__name__}) — задание поставлено, миграция 018 применена?')


def tiers() -> list[tuple[int, str, str]]:
    """(ярус, sku, почему) — очередь в порядке полезности."""
    q_ = _queue()
    sets = json.load(open(SETS))
    out, seen = [], set()

    def take(tier, sku, why):
        if sku in q_ and sku not in seen:
            seen.add(sku)
            out.append((tier, sku, why))

    # 1 — комплекты в порядке близости к готовности, каждый добивается ЦЕЛИКОМ
    short = []
    for n, s in enumerate(sets, 1):
        need = [f"{it['mid']}:{it['eid']}"
                for slot, it in (s.get('items') or {}).items()
                if it and it.get('mid') and _needs_mesh(f"{it['mid']}:{it['eid']}", base_role(slot))]
        if need:
            short.append((len(need), n, need))
    for missing, n, need in sorted(short):
        for sku in need:
            take(1, sku, f'комплект №{n} (до готовности {missing})')

    # 2 — дефицит готовых заменителей
    try:
        import reserve
        for r in reserve.coverage()['rows']:
            if r['ready'] >= r['target']:
                continue
            for sku in r['missing'][:max(0, r['target'] - r['ready'])]:
                take(2, sku, f"запас слота «{r['slot']}»")
    except Exception as e:  # noqa: BLE001 — резерв не должен ронять планировщик
        print(f'резерв не посчитан: {type(e).__name__}: {str(e)[:80]}')

    # 3 — проблемные роли: где обрезка чаще бракует, там раньше нужен пилот
    bad = {r[0] for r in db(
        "select p.cat_role from photo_assessment a "
        "join product_photo_current c on c.source_sha=a.source_sha "
        "join products p on p.shop_mid||':'||p.external_id=c.sku "
        "where a.verdict <> 'ok' group by p.cat_role order by count(*) desc limit 6") if r}
    for sku, role in q_.items():
        if role in bad and _needs_mesh(sku, role):
            take(3, sku, f'проблемная роль «{role}»')

    # 4 — хвост
    for sku, role in sorted(q_.items()):
        if _needs_mesh(sku, role):
            take(4, sku, 'общая очередь')
    return out


def main() -> int:
    batch = tiers()[:DAILY]
    if not batch:
        print('партия пуста — всё нужное уже готово или в работе')
        return 0
    print(f'дневная партия: {len(batch)} (предел MESH_DAILY_BATCH={DAILY})')
    by = collections.Counter(t for t, _, _ in batch)
    print('  по ярусам: ' + ', '.join(f'{k}→{v}' for k, v in sorted(by.items())))
    for t, sku, why in batch:
        print(f'  [{t}] {sku:34} {why}')
    if '--dry' in sys.argv:
        print('это был показ; поставить задания — без --dry')
        return 0
    made = 0
    for _t, sku, _why in batch:
        r = db("insert into mesh_jobs (job_key, sku) "
               f"select d.sku||'|'||d.source_sha||'|'||{q(PIPELINE_VERSION)}, d.sku "
               f"  from mesh_demand d where d.sku={q(sku)} and d.source_sha is not null "
               "on conflict (job_key) do nothing returning job_key")
        new_keys = [x[0] for x in r if x and x[0]]
        made += len(new_keys)
        for jk in new_keys:
            _stamp_digest(jk, sku)
    print(f'поставлено заданий: {made}')
    passport_report()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
