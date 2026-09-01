#!/usr/bin/env python3
"""СКОЛЬКО МЕШЕЙ НУЖНО — единый счётчик потребности (владелец 01.09).

Зачем. Число «сколько мешей надо» жило текстом в плане (11 631) и устаревало: в нём не были
вычтены роли, которым меш не нужен (ковры, пледы, подушки, шторы, зеркала, картины — их
ставим плоскостью или вырезкой из фото, `rules/asset-strategies.json`). Владелец: «конвейер
чётко должен работать, надо исключалось и помечалось верно». Теперь цифра НЕ хранится, а
считается по базе на каждый вызов.

Потребность = товар в наличии, с фотографией, с габаритами (без габаритов меш не масштабировать),
роль требует меша по политике стратегий. Разрезы: всего / в ролях слотов сетов / в очереди /
уже готово / осталось.

Запуск:
  ~/venvs/scout/bin/python mesh_demand.py            # человекочитаемо
  ~/venvs/scout/bin/python mesh_demand.py --json     # для конвейера и страниц
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
MESH_DIR = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
QUEUE = os.path.join(os.path.dirname(HERE), 'mesh-pilot-sample.json')
CACHE = os.path.expanduser('~/scout-scenes/meshes-hunyuan/demand.json')

# Роли слотов наборов мебели: то, что реально встаёт в комнату (методика ADR-0131).
SLOT_ROLES = {'диван', 'кресло', 'стул', 'табурет', 'пуф', 'банкетка', 'кровать',
              'стол', 'столик', 'тумба', 'тв-тумба', 'комод', 'стеллаж', 'шкаф',
              'витрина', 'стенка', 'камин', 'торшер', 'ваза', 'кашпо'}


def _db(q: str) -> list[str]:
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                        '-t', '-A', '-F', '|', '-c', q], capture_output=True, text=True)
    return [x for x in r.stdout.strip().splitlines() if '|' in x]


def funnel() -> list[tuple[str, int]]:
    """ВОРОНКА ПО ЭТАПАМ (владелец 01.09: «конвейер всегда должен знать, сколько на каждом
    этапе — каких фото, какие надо меши, какие нет»). Порядок канонический
    (`core/pipeline-order.md`): каталог → наличие → фото → обогащение → стиль → роль →
    габариты. Меш нужен только тому, кто прошёл ВСЮ цепочку: не прошёл обогащение или
    стиль — товар не попадёт в набор, и меш ему не нужен.
    """
    E = ("products p join product_enrichment e on e.shop_mid=p.shop_mid "
         "and e.external_id=p.external_id")
    q = f"""select
      (select count(*) from products) as v1,
      (select count(*) from products where in_stock) as v2,
      (select count(*) from products where in_stock and image_url is not null) as v3,
      (select count(*) from products where in_stock and image_url_hd is not null) as v4,
      (select count(*) from {E} where p.in_stock and p.image_url is not null
         and e.enriched_at is not null) as v5,
      (select count(*) from {E} where p.in_stock and p.image_url is not null
         and e.enriched_at is not null and e.payload->'model'->'styles' is not null) as v6,
      (select count(*) from {E} where p.in_stock and p.image_url is not null
         and e.enriched_at is not null and e.payload->'model'->'styles' is not null
         and p.w_cm is not null and p.h_cm is not null) as v7"""
    r = _db(q)
    v = [int(x) for x in r[0].split('|')] if r else [0] * 7
    return list(zip(['всего в каталоге', 'в наличии', 'с фото', '  из них с HD-фото',
                     'обогащены', 'со стилями', 'с габаритами (годны в работу)'], v))


def compute() -> dict:
    import asset_strategy as AS
    # ВАЖНО (владелец 01.09): потребность считается ПОСЛЕ обогащения и стилей — кто их не
    # прошёл, тот не попадёт в набор, и меш ему не нужен. Раньше здесь были только фото и
    # габариты, из-за чего цифра завышалась.
    E = ("products p join product_enrichment e on e.shop_mid=p.shop_mid "
         "and e.external_id=p.external_id")
    rows = _db(f"select coalesce(p.cat_role,''), "
               f"count(*) filter (where p.image_url is not null), "
               f"count(*) filter (where p.image_url is not null and p.w_cm is not null "
               f"                 and p.h_cm is not null) "
               f"from {E} where p.in_stock and e.enriched_at is not null "
               f"and e.payload->'model'->'styles' is not null group by 1")
    need = need_dims = slot = 0
    excluded = {}
    by_role = {}
    for r in rows:
        role, n_photo, n_dims = r.rsplit('|', 2)
        n_photo, n_dims = int(n_photo), int(n_dims)
        if not role:
            continue
        st = AS.strategy(role)
        if st != 'hunyuan3d':                       # ковры/пледы/шторы/зеркала/картины
            excluded[role] = excluded.get(role, 0) + n_photo
            continue
        need += n_photo
        need_dims += n_dims
        by_role[role] = n_dims
        if role.split()[0] in SLOT_ROLES:
            slot += n_dims
    have = set()
    for d in glob.glob(os.path.join(MESH_DIR, '*')):
        if glob.glob(os.path.join(d, '*', 'model.glb')):
            have.add(os.path.basename(d).replace('_', ':', 1))
    queued = set()
    if os.path.exists(QUEUE):
        try:
            queued = {j['sku'] for j in json.load(open(QUEUE, encoding='utf-8')).get('jobs', [])}
        except Exception:  # noqa: BLE001
            queued = set()
    return {
        'funnel': funnel(),
        'need_total': need,                       # роль требует меша, есть фото
        'need_with_dims': need_dims,              # + есть габариты (иначе не масштабировать)
        'need_slot_roles': slot,                  # только роли слотов наборов
        'excluded_total': sum(excluded.values()),
        'excluded_by_role': dict(sorted(excluded.items(), key=lambda kv: -kv[1])),
        'queued': len(queued),
        'have': len(have),
        'left_slot_roles': max(0, slot - len(have)),
        'top_roles': dict(sorted(by_role.items(), key=lambda kv: -kv[1])[:10]),
        'policy_version': AS.policy_version(),
    }


def main() -> None:
    d = compute()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(d, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if '--json' in sys.argv:
        print(json.dumps(d, ensure_ascii=False))
        return
    print('ВОРОНКА КАТАЛОГА (этапы до потребности в мешах)')
    for name, n in d.get('funnel', []):
        print(f'  {name:.<38} {n}')
    print()
    print('СКОЛЬКО МЕШЕЙ НУЖНО (после обогащения и стилей, политика ролей v%d)'
          % d['policy_version'])
    print(f"  роль требует меша, есть фото ........ {d['need_total']}")
    print(f"  из них с габаритами (годны в работу)  {d['need_with_dims']}")
    print(f"  в ролях слотов наборов (приоритет) .. {d['need_slot_roles']}")
    print(f"  ИСКЛЮЧЕНО (плоскость/вырезка) ....... {d['excluded_total']}"
          f"  {', '.join(f'{k} {v}' for k, v in list(d['excluded_by_role'].items())[:6])}")
    print(f"  в очереди сейчас .................... {d['queued']}")
    print(f"  готово моделей ...................... {d['have']}")
    print(f"  осталось по ролям слотов ............ {d['left_slot_roles']}")
    print('  топ ролей:', ', '.join(f'{k} {v}' for k, v in list(d['top_roles'].items())[:6]))


if __name__ == '__main__':
    main()
