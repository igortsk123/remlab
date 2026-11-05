#!/usr/bin/env python3
"""Задания мешей для товаров КОМНАТ КРОМЕ ГОСТИНОЙ — из `room_catalog`, отдельным снимком с меткой комнаты (план onb-10).

ЗАЧЕМ ОТДЕЛЬНО. Боевая очередь (`mesh_priority.py`, профили и закреплённые) читает только `products`; спальни там нет и
не будет до переноса (ADR-0279, ADR-0330 п.2). Снимок отсюда подаётся в законный старт волны ключом `MESH_QUEUE_FILE`
(`mesh_wave_start.sh`): подготовка, приёмник, потолок денег и сторожа — те же, меняется только источник списка.

ЧТО НЕ СМЕШИВАЕТСЯ С ГОСТИНОЙ. Товар, который есть в `products`, сюда не берём: его меш привязал бы `mesh_bind` к карточке
гостиной. Товар с уже сделанным мешем (`mesh_generations`) не берём: второй раз — деньги на ветер. Остальные пост-шаги
конвейера (`mesh_bind`, `mesh_family`, `mesh_ready`) читают `products` и спальню не видят; реестр поколений пишет её как
любой меш — по нему и считаем пробу.

  ~/venvs/scout/bin/python room_mesh_jobs.py --skus 112923:1,112923:2 --out FILE   # снимок по списку
  python3 room_mesh_jobs.py --selftest                                             # правила без базы и сети
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad'))
MAX_JOBS = 50   # предохранитель: этот путь — для проб и канареек, массовый прогон идёт своей очередью (onb-10)


def job_of(row: dict, room: str) -> tuple[dict | None, str]:
    """Строка каталога → (задание, '') или (None, причина). Чистая функция (селфтест)."""
    import asset_strategy as AS
    if row.get('in_products'):
        return None, 'есть в products — меш ушёл бы в гостиную'
    if row.get('has_mesh'):
        return None, 'меш уже есть'
    if not row.get('shown'):
        return None, 'не показывается (нет цены/фото или нет в свежем фиде)'
    if not row.get('footprint_ok'):
        return None, 'габарит не сверен (footprint_ok)'
    w, d, h = (row.get(k) for k in ('w_cm', 'd_cm', 'h_cm'))
    if not all(isinstance(v, (int, float)) and v > 0 for v in (w, d, h)):
        return None, 'нет габарита Ш×Г×В'
    if AS.strategy(row['role']) != 'hunyuan3d':
        return None, f'роль {row["role"]} — не меш'
    if row.get('photo_alive') is False:
        return None, 'фото не скачивается'
    sku = f'{row["shop_mid"]}:{row["external_id"]}'
    return {'sku': sku, 'mid': int(row['shop_mid']), 'eid': str(row['external_id']), 'role': row['role'],
            'name': row.get('name') or '', 'image_url': row['image_url'],
            'dims_cm': {'w': float(w), 'd': float(d), 'h': float(h), 'dia': None},
            'room': room, 'strata': {'tier': 'room', 'reason': f'комната {room}: room_catalog (onb-10)'},
            'seeds': [0]}, ''


def fetch(skus: list, room: str) -> list:
    import room_catalog as RC
    lit = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
    cols = ('shop_mid', 'external_id', 'role', 'name', 'image_url', 'w_cm', 'd_cm', 'h_cm', 'footprint_ok', 'shown',
            'in_products', 'has_mesh')
    rows = RC.sql(f"""select r.shop_mid, r.external_id, r.role, r.name, coalesce(r.image_url_hd, r.image_url),
        r.w_cm, r.d_cm, r.h_cm, coalesce(r.footprint_ok, false), ({RC.shown_where()}),
        exists(select 1 from products p where p.shop_mid = r.shop_mid and p.external_id = r.external_id),
        exists(select 1 from mesh_generations g where g.sku = r.shop_mid || ':' || r.external_id)
      from room_catalog r where r.room = '{room}' and r.shop_mid || ':' || r.external_id in ({lit})""")
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d['shop_mid'] = int(d['shop_mid'])
        for k in ('w_cm', 'd_cm', 'h_cm'):
            d[k] = float(d[k]) if d[k] else None
        for k in ('footprint_ok', 'shown', 'in_products', 'has_mesh'):
            d[k] = d[k] == 't'
        d['photo_alive'] = RC.photo_alive(d['image_url']) if d['image_url'] else False
        out.append(d)
    return out


def build(skus: list, room: str, out: str) -> int:
    if len(skus) > MAX_JOBS:
        print(f'ПРЕДОХРАНИТЕЛЬ: {len(skus)} > {MAX_JOBS} — этот путь для проб', flush=True)
        return 2
    rows = {f'{r["shop_mid"]}:{r["external_id"]}': r for r in fetch(skus, room)}
    jobs = []
    for s in skus:
        if s not in rows:
            print(f'  пропуск {s}: нет в room_catalog ({room})', flush=True)
            continue
        j, why = job_of(rows[s], room)
        if j is None:
            print(f'  пропуск {s}: {why}', flush=True)
            continue
        jobs.append(j)
    snap = {'source': f'room_catalog:{room}', 'room': room, 'policy_version': 2, 'rework': [],
            'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'jobs': jobs}
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)
    print(f'снимок {out}: {len(jobs)} заданий из {len(skus)} (комната {room})', flush=True)
    return 0 if jobs else 3


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    base = {'shop_mid': 112923, 'external_id': '1', 'role': 'кровать', 'name': 'Кровать', 'image_url': 'u',
            'w_cm': 151.0, 'd_cm': 212.0, 'h_cm': 126.0, 'footprint_ok': True, 'shown': True,
            'in_products': False, 'has_mesh': False, 'photo_alive': True}
    j, _ = job_of(base, 'bedroom')
    ok('годная кровать → задание с меткой комнаты и seed 0',
       j is not None and j['room'] == 'bedroom' and j['seeds'] == [0] and j['sku'] == '112923:1'
       and j['dims_cm'] == {'w': 151.0, 'd': 212.0, 'h': 126.0, 'dia': None})
    ok('есть в products — не берём', job_of({**base, 'in_products': True}, 'bedroom')[0] is None)
    ok('меш уже есть — не берём', job_of({**base, 'has_mesh': True}, 'bedroom')[0] is None)
    ok('не показывается — не берём', job_of({**base, 'shown': False}, 'bedroom')[0] is None)
    ok('габарит не сверен — не берём', job_of({**base, 'footprint_ok': False}, 'bedroom')[0] is None)
    ok('нет высоты — не берём', job_of({**base, 'h_cm': None}, 'bedroom')[0] is None)
    ok('мёртвое фото — не берём', job_of({**base, 'photo_alive': False}, 'bedroom')[0] is None)
    ok('«не смог проверить» фото — не приговор', job_of({**base, 'photo_alive': None}, 'bedroom')[0] is not None)
    ok('тумба прикроватная — меш', job_of({**base, 'role': 'тумба прикроватная'}, 'bedroom')[0] is not None)
    ok('ковёр — не меш', job_of({**base, 'role': 'ковёр'}, 'bedroom')[0] is None)
    print(f'итог: {"OK" if not bad else f"FAIL {bad}"}')
    return 1 if bad else 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--selftest' in a:
        sys.exit(_selftest())
    if '--skus' not in a or '--out' not in a:
        sys.exit(__doc__)
    room = a[a.index('--room') + 1] if '--room' in a else 'bedroom'
    sys.exit(build([s.strip() for s in a[a.index('--skus') + 1].split(',') if s.strip()], room, a[a.index('--out') + 1]))
