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


def compute() -> dict:
    import asset_strategy as AS
    rows = _db("select coalesce(cat_role,''), "
               "count(*) filter (where image_url is not null), "
               "count(*) filter (where image_url is not null and w_cm is not null "
               "                 and h_cm is not null) "
               "from products where in_stock group by 1")
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
    print('СКОЛЬКО МЕШЕЙ НУЖНО (считано по базе, политика ролей v%d)' % d['policy_version'])
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
