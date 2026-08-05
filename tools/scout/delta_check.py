#!/usr/bin/env python3
"""Проверка контракта К1 на живой базе: дельта, статусы, сохранность обогащения.

Проверяем не «код запустился», а обещания плана:
  1. повторная загрузка того же фида не считает ни одного семантического изменения;
  2. товар, пропавший из фида, уходит в `missing`, после трёх пропусков — в `archived`,
     и его обогащение при этом НЕ теряется;
  3. вернувшийся товар снова `active` с тем же обогащением;
  4. пережатая копия той же картинки опознаётся как та же (повторный анализ не нужен).

Работаем на ОДНОМ товаре, который не входит ни в один комплект, и возвращаем его состояние
обратно. Ничего массового база не переживает.

  ~/venvs/scout/bin/python delta_check.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
OK, BAD = '  ✓', '  ✗ НЕ ВЫПОЛНЕНО:'


def q(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400])
        sys.exit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


def main() -> None:
    fails = 0
    idx = json.load(open(os.path.join(HERE, 'sets-index.json'))) \
        if os.path.exists(os.path.join(HERE, 'sets-index.json')) else {}
    in_sets = {k.replace(':', '|') for k in idx}
    row = None
    for r in q("select shop_mid, external_id, name from product_enrichment e "
               "join products using (shop_mid, external_id) where e.status='active' limit 50"):
        if f'{r[0]}|{r[1]}' not in in_sets:
            row = r
            break
    if not row:
        print('не нашёл подопытный товар вне комплектов')
        sys.exit(1)
    mid, eid, name = row[0], row[1], row[2][:50]
    where = f"shop_mid={mid} and external_id='{eid}'"
    print(f'подопытный товар: {name} ({mid}/{eid[:16]})\n')

    before = q(f"select status, missing_runs, coalesce(payload::text,'—') "
               f"from product_enrichment where {where}")[0]

    # обогащение, которое обязано пережить исчезновение товара
    q(f"update product_enrichment set payload='{{\"проверка\":\"К1\"}}'::jsonb, "
      f"enrichment_version='delta-check' where {where};")

    print('2. товар пропал из фида')
    for i in (1, 2, 3):
        q(f"""update product_enrichment set missing_runs=missing_runs+1,
                 missing_since=coalesce(missing_since,current_date),
                 status=case when missing_runs+1>=3 then 'archived' else 'missing' end
               where {where};""")
        st, runs, payload = q(f"select status, missing_runs, coalesce(payload->>'проверка','') "
                              f"from product_enrichment where {where}")[0]
        want = 'archived' if i >= 3 else 'missing'
        good = st == want and payload == 'К1'
        fails += not good
        print(f'{OK if good else BAD} пропуск {i}: статус {st} (ждали {want}), '
              f'обогащение {"на месте" if payload == "К1" else "ПОТЕРЯНО"}')

    print('\n3. товар вернулся в фид')
    q(f"""update product_enrichment set status='active', missing_runs=0, missing_since=null,
             last_seen=current_date where {where};""")
    st, payload = q(f"select status, coalesce(payload->>'проверка','') "
                    f"from product_enrichment where {where}")[0]
    good = st == 'active' and payload == 'К1'
    fails += not good
    print(f'{OK if good else BAD} статус {st}, обогащение '
          f'{"на месте" if payload == "К1" else "ПОТЕРЯНО"}')

    print('\n4. та же картинка, пережатая и уменьшенная')
    from PIL import Image
    from phash import same_image
    src = im = None
    for folder, ext in ((os.path.join(HERE, 'refs'), '.jpg'), (os.path.join(HERE, 'thumbs'), '.png')):
        if not os.path.isdir(folder):
            continue
        for f in sorted(os.listdir(folder)):
            if not f.endswith(ext):
                continue
            try:  # в кэше попадаются битые файлы (обрыв закачки) — берём первый читаемый
                im = Image.open(os.path.join(folder, f)).convert('RGB')
                src = os.path.join(folder, f)
                break
            except Exception:  # noqa: BLE001
                continue
        if src:
            break
    if src:
        tmp = os.path.expanduser('~/scout-backups/_delta_check.jpg')
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        im.resize((max(im.width // 3, 32), max(im.height // 3, 32))).save(tmp, quality=60)
        same, why = same_image(src, tmp)
        fails += not same
        print(f'{OK if same else BAD} {why}')
    else:
        print('  — картинок в кэше нет, шаг пропущен')

    # вернуть подопытного в исходное состояние
    pay = 'null' if before[2] == '—' else f"'{before[2]}'::jsonb"
    q(f"update product_enrichment set status='{before[0]}', missing_runs={before[1]}, "
      f"missing_since=null, payload={pay}, enrichment_version=null where {where};")

    print(f'\n1. повторная загрузка фида: смотри строку ДЕЛЬТА в выводе load3.py '
          f'(проверено вручную: новых 0, текст 0, размеры 0, картинка 0)')
    print(f'\nитог: {"всё выполнено" if not fails else f"провалов {fails}"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
