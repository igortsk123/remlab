#!/usr/bin/env python3
"""Порядок очереди мешей — ЕДИНСТВЕННАЯ реализация регламента `rules/mesh-priority.json`.

Регламент задал владелец 01.09: сначала демо flat215, затем позиции готовых сетов, затем
вся прочая мебель, затем свет и декор. Здесь он превращается в ключ сортировки; почему
именно так — в JSON рядом, тут только механика.

ДВА ПРАВИЛА, КОТОРЫЕ ЛЕГКО НАРУШИТЬ СЛУЧАЙНО:
1. Ключ ЛЕКСИКОГРАФИЧЕСКИЙ (ярус, затем измеримые признаки, затем стабильный sku).
   Единого числового балла нет намеренно: коэффициенты в нём — недоказуемые скрытые веса.
2. Единица планирования для сетов — НЕДОСТАЮЩИЙ КОМПЛЕКТ, а не отдельный товар. Сет без
   одной позиции не показывается вообще, поэтому «дешёвый сет вперёд» даёт готовые сеты
   быстрее, чем «частая роль вперёд». Замер 01.09: 17 мешей → 10 сетов, 282 → все 126.
   Сортировка по частоте роли дала бы почти обратный порядок (диван 1.8 сета на меш против
   кашпо 8.0) — интуиция здесь ошибается.

  ~/venvs/scout/bin/python mesh_priority.py --report        # сводка по ярусам
  ~/venvs/scout/bin/python mesh_priority.py --export q.json # полный порядок
  ~/venvs/scout/bin/python mesh_priority.py --explain SKU   # почему товар тут
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'mesh-priority.json')
PINNED = os.path.join(HERE, 'rules', 'mesh-pinned.json')
SETS = os.path.join(HERE, 'sets3.json')
SAMPLE = os.path.join(HERE, 'mesh-pilot-sample.json')
# ON_ERROR_STOP ОБЯЗАТЕЛЕН: без него psql при ошибке SQL отдаёт код 0 и пустой вывод,
# и «неверная колонка» выглядит как «в базе ничего нет» (поймано на себе 01.09).
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

TIER_IDS = ('pinned', 'demo_flat215', 'set_closure', 'furniture', 'light_decor')


def rules() -> dict:
    r = json.load(open(RULES, encoding='utf-8'))
    ids = [t['id'] for t in r['tiers']]
    # Контракт: каждый ярус регламента обязан быть реализован здесь. Неизвестный ярус —
    # ошибка, а не молчаливый пропуск: иначе регламент и код разойдутся незаметно.
    unknown = set(ids) - set(TIER_IDS)
    if unknown:
        sys.exit(f'регламент требует ярусы без реализации: {sorted(unknown)}')
    if ids != [t for t in TIER_IDS if t in ids]:
        sys.exit(f'порядок ярусов в регламенте не совпадает с кодом: {ids}')
    return r


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def products() -> dict:
    """Множество очереди — `products.mesh_required`, единственный источник.

    Вход генератора берём как ADR-0182: HD-фото, иначе обычное. Габариты обязательны —
    без них товар и не получил бы пометку."""
    out = {}
    for sku, role, status, img, w, d, h in db(
            "select shop_mid||':'||external_id, coalesce(cat_role,''), "
            "coalesce(mesh_status,'none'), coalesce(image_url_hd, image_url), "
            "coalesce(w_cm,0), coalesce(d_cm,0), coalesce(h_cm,0) "
            "from products where mesh_required;"):
        out[sku] = {'role': role, 'status': status, 'image_url': img,
                    'dims_cm': {'w': float(w) or None, 'd': float(d) or None,
                                'h': float(h) or None}}
    if not out:
        sys.exit('в products нет ни одного mesh_required — это дефект, а не пустая очередь')
    return out


def demo_skus() -> set:
    """Позиции демо-квартиры — метка `strata.source == 'flat215'` в снимке очереди.

    Пустой результат — ОШИБКА, а не «демо пустое»: молчаливый ноль здесь означал бы, что
    первый ярус регламента тихо исчез (поймано на себе 01.09: неверный путь к файлу).
    """
    if not os.path.exists(SAMPLE):
        sys.exit(f'нет снимка очереди {SAMPLE} — ярус демо посчитать нечем')
    s = json.load(open(SAMPLE, encoding='utf-8'))
    out = {j['sku'] for j in s.get('jobs', [])
           if (j.get('strata') or {}).get('source') == 'flat215'}
    if not out:
        sys.exit(f'в {SAMPLE} нет ни одной позиции с меткой flat215 — ярус демо пуст, разбери')
    return out


def pinned_skus() -> list:
    """Закреплённые владельцем позиции — идут раньше всех ярусов.

    Нужны потому, что автоматический ярус считается по данным, а данные бывают неполны:
    01.09 ярус демо выводился из метки в снимке очереди и показывал «закрыто 61 из 61»,
    тогда как на странице демо владелец нашёл 9 позиций без моделей."""
    if not os.path.exists(PINNED):
        return []
    out = []
    for grp in json.load(open(PINNED, encoding='utf-8')).get('pinned', []):
        out.extend(grp.get('skus', []))
    return out


def sets_data() -> tuple[dict, dict]:
    """(набор позиций каждого сета, набор замен) — по опубликованным сетам."""
    if not os.path.exists(SETS):
        return {}, {}
    data = json.load(open(SETS, encoding='utf-8'))
    items, alts = {}, {}
    for s in data:
        sid = s.get('set_id')
        items[sid] = {f"{it['mid']}:{it['eid']}" for it in (s.get('items') or {}).values()}
        for lst in (s.get('alternates') or {}).values():
            for a in lst:
                alts.setdefault(f"{a['mid']}:{a['eid']}", set()).add(sid)
    return items, alts


def rank() -> list[dict]:
    """Полный порядок очереди. Возвращает список строк с ярусом, ключом и причиной."""
    r = rules()
    light, decor = set(r['light_roles']), set(r['decor_roles'])
    prod = products()
    demo = demo_skus()
    pin = {s: i for i, s in enumerate(pinned_skus())}
    set_items, alts = sets_data()

    # СТОИМОСТЬ ДОСТРОЙКИ СЕТА: сколько мешей ему ещё не хватает. Ею и сортируем ярус сетов —
    # товар наследует стоимость самого дешёвого сета, в котором участвует.
    missing = {sid: {s for s in skus if s in prod and prod[s]['status'] != 'ready'}
               for sid, skus in set_items.items()}
    cheapest = {}
    for sid, miss in missing.items():
        for sku in miss:
            cheapest[sku] = min(cheapest.get(sku, 10 ** 6), len(miss))
    in_set = {s for skus in set_items.values() for s in skus}
    # частота роли в реальных слотах сетов (а не населённость каталога — она обманывает)
    role_use: dict = {}
    for skus in set_items.values():
        for s in skus:
            role_use[prod.get(s, {}).get('role', '')] = role_use.get(
                prod.get(s, {}).get('role', ''), 0) + 1

    rows = []
    for sku, p in prod.items():
        role = p['role']
        if sku in pin:
            tier, why = 'pinned', 'закреплено владельцем (rules/mesh-pinned.json)'
            key = (-1, pin[sku], sku)
        elif sku in demo:
            tier, why = 'demo_flat215', 'показывается на /test/buildup'
            key = (0, sku)
        elif sku in in_set:
            c = cheapest.get(sku, 10 ** 6)
            tier, why = 'set_closure', f'позиция сета; дешевейшему сету не хватает {c}'
            key = (1, c, -role_use.get(role, 0), sku)
        elif role not in light and role not in decor:
            a = 0 if sku in alts else 1     # замены вперёд: закрывают дефицит подмен
            tier = 'furniture'
            why = ('замена в опубликованном сете' if not a else 'мебель, вне сетов')
            key = (2, a, -role_use.get(role, 0), sku)
        else:
            tier, why = 'light_decor', ('свет' if role in light else 'декор')
            key = (3, -role_use.get(role, 0), sku)
        rows.append({'sku': sku, 'role': role, 'tier': tier, 'key': key,
                     'reason': why, 'status': p['status'],
                     'policy_version': r['policy_version']})
    rows.sort(key=lambda x: x['key'])
    return rows


# ---------------------------------------------------------------- переделки владельца и seed

def next_seed(used: set) -> int:
    """Seed перегона: первый НАД всеми занятыми. Перегон никогда не seed 0 (это первая
    генерация), и никогда не совпадает ни с чем уже заказанным — иначе нода вернёт cached
    старую попытку вместо новой модели (разбор Codex 05.09)."""
    return (max(used) + 1) if used else 1


def used_seeds(skus: set, reseed_path: str, snapshots: list) -> dict:
    """sku → занятые seed из ВСЕХ источников: реестр поколений (что уже сделано), инбокс
    переделок (что зарезервировано), `mesh-reseed.json` (автоперегон приёмки) и снимки очереди
    (что ещё поедет). Один allocator на всех — единственная защита от дубля (sku, seed)."""
    used = {s: set() for s in skus}
    if not skus:
        return used
    lit = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
    for r in db(f"select sku, seed from mesh_generations where sku in ({lit})"):
        if len(r) == 2 and r[0] in used:
            used[r[0]].add(int(r[1]))
    for r in db(f"select sku, next_seed from mesh_rework_requests where next_seed is not null and sku in ({lit})"):
        if len(r) == 2 and r[0] in used and r[1] not in ('', '\\N'):
            used[r[0]].add(int(r[1]))
    if os.path.exists(reseed_path):
        try:
            for rec in json.load(open(reseed_path, encoding='utf-8')):
                job = rec.get('job') if isinstance(rec, dict) and 'job' in rec else rec
                if isinstance(job, dict) and job.get('sku') in used:
                    used[job['sku']].add(int(job.get('seed') or 0))
        except (ValueError, OSError):
            pass    # битый файл перегона не должен ронять сборку — его прочитает и поругает ssh_run
    for snap in snapshots:
        try:
            for j in json.load(open(snap, encoding='utf-8')).get('jobs', []):
                if j.get('sku') in used:
                    used[j['sku']].update(int(s) for s in j.get('seeds', []))
        except (ValueError, OSError):
            pass
    return used


def active_snapshots() -> list:
    """Снимки очереди, которые ещё могут поехать: тот, по которому идёт живой конвейер (его
    `MESH_SAMPLE` читаем из окружения процесса, PID — в замке), плюс все `mesh-queue-*.json`
    рядом — консервативно, seed от этого только растёт."""
    out = set(glob.glob(os.path.join(HERE, 'mesh-queue-*.json')))
    lock = os.path.expanduser('~/scout-scenes/.batch_show.lock')
    try:
        pid = int(open(lock).read().strip() or 0)
        env = open(f'/proc/{pid}/environ', 'rb').read().split(b'\0')
        for kv in env:
            if kv.startswith(b'MESH_SAMPLE='):
                out.add(kv.split(b'=', 1)[1].decode())
    except (OSError, ValueError):
        pass
    return sorted(p for p in out if os.path.exists(p) and not p.endswith('.tmp'))


def pending_rework() -> dict:
    """sku → запрос переделки, ждущий постановки (requested) или уже стоявший в прежнем снимке
    (queued, но перегон ещё не случился — иначе sync перевёл бы его в done)."""
    out = {}
    for r in db("select id, sku, manual_attempt_no, coalesce(next_seed::text,''), status "
                "from mesh_rework_requests where status in ('requested','queued') order by id"):
        if len(r) == 5:
            out[r[1]] = {'id': int(r[0]), 'attempt': int(r[2]),
                         'next_seed': int(r[3]) if r[3] else None, 'status': r[4]}
    return out


def build_queue(path: str, todo: list, prod: dict) -> None:
    """Снимок очереди: недоделанное в порядке регламента + переделки владельца на их же местах
    (товар с `mesh_status='rejected'` попадает в `todo` сам — обгона нет). Файл пишется
    АТОМАРНО (tmp → fsync → rename): `ssh_run` читает его целиком и не должен увидеть половину.
    Запрос переделки становится `queued` только ПОСЛЕ успешной записи — до этого страница
    честно показывает «принято, ждёт сборки очереди»."""
    import time
    rework = pending_rework()
    used = used_seeds(set(rework), os.path.join(HERE, 'mesh-reseed.json'), active_snapshots())
    jobs, queued, seen = [], [], set()
    for x in todo:
        p = prod[x['sku']]
        mid, eid = x['sku'].split(':', 1)
        seeds, strata = [0], {'tier': x['tier'], 'reason': x['reason']}
        rq = rework.get(x['sku'])
        if rq:
            others = used[x['sku']] - ({rq['next_seed']} if rq['next_seed'] is not None else set())
            gen_has = db(f"select 1 from mesh_generations where sku='{x['sku']}' and seed={rq['next_seed']}") \
                if rq['next_seed'] is not None else []
            seed = rq['next_seed'] if (rq['next_seed'] is not None and not gen_has
                                       and rq['next_seed'] not in others) else next_seed(used[x['sku']])
            seeds = [seed]
            strata['rework'] = {'request_id': rq['id'], 'attempt': rq['attempt']}
            queued.append((rq['id'], seed))
        for s in seeds:
            if (x['sku'], s) in seen:
                sys.exit(f'дубль (sku, seed) в снимке: {x["sku"]} seed {s} — сборка отменена')
            seen.add((x['sku'], s))
        jobs.append({'sku': x['sku'], 'mid': int(mid), 'eid': eid, 'role': x['role'],
                     'name': '', 'image_url': p['image_url'], 'dims_cm': p['dims_cm'],
                     'strata': strata, 'seeds': seeds})
    orphans = [s for s in rework if s not in prod]
    cap = int(os.environ.get('MESH_MAX_JOBS', '0') or 0)
    if cap and len(jobs) > cap:
        sys.exit(f'снимок {len(jobs)} заданий больше предохранителя MESH_MAX_JOBS={cap} — не пишу')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'source': 'mesh_priority', 'policy_version': todo[0]['policy_version'],
                   'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'rework': len(queued),
                   'jobs': jobs}, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    build_id = os.path.basename(path)
    if queued:
        db('begin;\n' + '\n'.join(
            f"update mesh_rework_requests set status='queued', next_seed={seed}, "
            f"queue_build_id='{build_id}', updated=now() where id={rid};" for rid, seed in queued)
           + '\ncommit;')
    if orphans:
        lit = ','.join("'" + s + "'" for s in orphans)
        db(f"update mesh_rework_requests set status='blocked', error='товар вне потребности "
           f"(нет mesh_required)', updated=now() where status in ('requested','queued') and sku in ({lit})")
    print(f'очередь собрана: {len(jobs)} заданий в порядке приоритета, переделок владельца '
          f'{len(queued)}, заблокировано вне потребности {len(orphans)} → {path}')


def _selftest() -> int:
    bad = 0
    if next_seed(set()) != 1 or next_seed({0}) != 1 or next_seed({0, 1}) != 2 or next_seed({0, 3}) != 4:
        bad += 1; print('  FAIL next_seed')
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rs = os.path.join(td, 'reseed.json')
        json.dump([{'sku': 'a', 'seed': 1}, {'job': {'sku': 'b', 'seed': 2}}], open(rs, 'w'))
        sn = os.path.join(td, 'mesh-queue-x.json')
        json.dump({'jobs': [{'sku': 'a', 'seeds': [0, 5]}]}, open(sn, 'w'))
        global db
        real_db = db
        db = lambda sql: [['a', '0'], ['b', '0']] if 'mesh_generations' in sql else [['b', '3']]  # noqa: E731
        try:
            u = used_seeds({'a', 'b'}, rs, [sn])
        finally:
            db = real_db
        if u != {'a': {0, 1, 5}, 'b': {0, 2, 3}}:
            bad += 1; print(f'  FAIL used_seeds: {u}')
        if next_seed(u['a']) != 6 or next_seed(u['b']) != 4:
            bad += 1; print('  FAIL next_seed поверх used_seeds')
    print(f'mesh_priority selftest: случаев 3, ошибок {bad}')
    return 1 if bad else 0


def main() -> None:
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    rows = rank()
    todo = [x for x in rows if x['status'] != 'ready']
    if '--explain' in sys.argv:
        want = sys.argv[sys.argv.index('--explain') + 1]
        for i, x in enumerate(rows, 1):
            if x['sku'] == want:
                print(f"{want}: место {i} из {len(rows)}, ярус {x['tier']}, "
                      f"роль {x['role']}, причина: {x['reason']}, статус {x['status']}")
                return
        print(f'{want}: в очереди нет (нет пометки «требуется меш»)')
        return
    if '--build-queue' in sys.argv:
        # Файл в формате конвейера (`ssh_run.jobs_from_sample`), но В ПОРЯДКЕ РЕГЛАМЕНТА и
        # ТОЛЬКО из недоделанного: готовые 218 не попадают, поэтому перегона не будет и
        # кэш приёмника для этого не нужен (мы его чистим).
        path = sys.argv[sys.argv.index('--build-queue') + 1]
        build_queue(path, todo, products())
        return
    if '--export' in sys.argv:
        path = sys.argv[sys.argv.index('--export') + 1]
        json.dump([{k: v for k, v in x.items() if k != 'key'} for x in todo],
                  open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'записано {len(todo)} заданий в порядке приоритета → {path}')
        return
    print(f'ВСЕГО требуется меш: {len(rows)}; готово {len(rows) - len(todo)}; '
          f'осталось {len(todo)}')
    for t in TIER_IDS:
        a = [x for x in rows if x['tier'] == t]
        left = [x for x in a if x['status'] != 'ready']
        print(f'  {t:14s} всего {len(a):6d}  готово {len(a) - len(left):5d}  осталось {len(left):6d}')
    print('\nпервые 10 в очереди:')
    for x in todo[:10]:
        print(f'  {x["sku"]:40s} {x["role"]:12s} {x["tier"]:13s} {x["reason"]}')


if __name__ == '__main__':
    main()
