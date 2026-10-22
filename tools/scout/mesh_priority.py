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
    variants = 0
    for sku, role, status, img, w, d, h, dia, rep in db(
            "select shop_mid||':'||external_id, coalesce(cat_role,''), "
            "coalesce(mesh_status,'none'), coalesce(image_url_hd, image_url), "
            "coalesce(w_cm,0), coalesce(d_cm,0), coalesce(h_cm,0), coalesce(dia_cm,0), "
            "coalesce(mesh_family_rep, shop_mid||':'||external_id) "
            "from products where mesh_required;"):
        # ОДИН МЕШ НА МОДЕЛЬ (владелец 05.09, `mesh_family.py`): цветовой вариант в очередь не
        # встаёт — его меш и готовность приходят от представителя семейства.
        if rep != sku:
            variants += 1
            continue
        # ДИАМЕТР ПЕРЕДАЁМ КАК ЕСТЬ, НЕ ПОДСТАВЛЯЕМ (11.10, исправлено по разбору `verify`).
        # Пул пускает круглое по `(w или dia) и h` (mesh_bind), поэтому габарит обязан доехать до
        # ноды. Первая версия писала `w = d = dia` здесь — и ОБХОДИЛА знание потребителей: они уже
        # делают `w = w or dia` и приравнивают `d = w` ТОЛЬКО для `SQUARE_ROLES`
        # (`salad/apply_repairs.py:31`, `salad/pipeline.py:161`), то есть кашпо/вазе/торшеру — да,
        # а бра и статуэтке — нет (у бра диаметр это лицевая часть, глубина — вынос от стены).
        # Плюс подстановка стирала ключ `dia` из манифеста, который второй производитель очереди
        # (`mesh_pilot.py:161`) сохраняет. Ключ `dia` здесь — тот же контракт, что там.
        out[sku] = {'role': role, 'status': status, 'image_url': img,
                    'dims_cm': {'w': float(w) or None, 'd': float(d) or None,
                                'h': float(h) or None, 'dia': float(dia) or None}}
    if variants:
        print(f'вариантов семейств вне очереди: {variants}', flush=True)
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


DEMO_PROFILE = os.path.join(HERE, 'rules', 'mesh-queue-demo.json')


def demo_rank() -> list[dict]:
    """Очередь под демо (policy v2, план demo-20 В2, владелец 22.10 TG 793/797): закреплённые владельцем, затем недобор ленты
    замен по полосе размера — модели без меша, которые доводят места опубликованных вариантов до 10 альтернатив
    (`demo_band.queue_skus`: правило, порядок и потолок `mesh_queue_max` — там). Прежний «топ-30 по баллу стиля на тип»
    (v1, владелец 11.10) снят: он не смотрел на размер и на то, что уже есть в ленте."""
    prof = json.load(open(DEMO_PROFILE, encoding='utf-8'))
    if prof.get('rule') != 'demo_band':
        sys.exit(f'профиль demo: правило «{prof.get("rule")}» не реализовано (есть demo_band)')
    import demo_band
    prod = products()
    pinned = tuple(pinned_skus())
    if len(pinned) > demo_band.QUEUE_MAX:
        print(f'WARN:mesh_priority: закреплённых владельцем {len(pinned)} — больше потолка очереди demo '
              f'{demo_band.QUEUE_MAX}; закреплённые не режем, недобор ленты встанет после них', flush=True)
    band = demo_band.queue_skus()
    # КАНДИДАТ БАНКА (conv-14 шаг 2): спрос `bank_candidate` — за флагом `rules/bank-candidate.json:enabled` (выключен,
    # пустой список). Потолок `mesh_queue_max` — ОБЩИЙ с недобором ленты после дедупликации по представителю семейства
    import bank_pending
    bank = bank_pending.queue_skus()
    if bank:
        band, bank = bank_pending.combine(band, bank, demo_band.QUEUE_MAX, int(bank_pending.rules().get('reserve') or 0))
    return demo_pick(pinned, band, prod, f"demo-v{prof.get('policy_version', 2)}", bank)


def demo_pick(pinned: tuple, band: list, prod: dict, ver: str, bank: list | tuple = ()) -> list[dict]:
    """Чистый отбор: закреплённые (ярус 0), затем недобор ленты (ярус 1) по порядку `demo_band`, затем кандидат банка (ярус 2,
    `bank_pending`; общий потолок уже посчитан `bank_pending.combine`), без повторов; товар вне
    `products()` (нет пометки «требуется меш» или не представитель семейства) пропускается. Готовые отбрасывает `main()` тем же
    фильтром, что у боевой очереди. Потолок очереди считает `demo_band` по незавершённым — закреплённые его не съедают.

    ЗАКРЕПЛЁННЫЕ ВЛАДЕЛЬЦЕМ ИДУТ ПЕРВЫМИ (12.10): волна 12.10 сделала 986 мешей, а из 12 закреплённых позиций, которыми
    закрывались все шесть сцен демо, попали только 2 — деньги ушли «вширь». Закреплённый берётся независимо от роли и ленты:
    это прямое указание человека, а не отбор."""
    rows, seen = [], set()
    for tier, skus, why in ((0, pinned, 'закреплено владельцем (rules/mesh-pinned.json)'),
                            (1, band, 'демо: недобор ленты замен по полосе размера (demo_band)'),
                            (2, bank, 'демо: кандидат банка ждёт меш (bank_candidate, conv-14)')):
        for sku in skus:
            p = prod.get(sku)
            if not p or sku in seen:
                continue
            seen.add(sku)
            # Форма ряда — ТА ЖЕ, что у боевого ранжира: `build_queue` читает `key` и `policy_version`
            rows.append({'tier': tier, 'sku': sku, 'role': p['role'], 'status': p['status'],
                         'key': f'{tier:02d}|{len(rows):06d}|{sku}', 'reason': why, 'policy_version': ver})
    return rows


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
            tier, why = 'demo_flat215', 'показывается на /demo'
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


def take_top(jobs: list, queued: list, take: int) -> tuple[list, list]:
    """Первые `take` заданий снимка (он уже в порядке приоритета) — сколько оплачено разрешением владельца (`wave_guard`,
    `MESH_TAKE_JOBS`). Переделки владельца, не попавшие в волну, НЕ помечаются `queued`: иначе страница показывала бы
    «в очереди» то, чего в снимке нет. Чистая функция — селфтест."""
    if not take or len(jobs) <= take:
        return jobs, queued
    kept = jobs[:take]
    ids = {j['strata']['rework']['request_id'] for j in kept if 'rework' in j.get('strata', {})}
    return kept, [q for q in queued if q[0] in ids]


def build_queue(path: str, todo: list, prod: dict) -> None:
    """Снимок очереди: недоделанное в порядке регламента + переделки владельца на их же местах
    (товар с `mesh_status='rejected'` попадает в `todo` сам — обгона нет). Файл пишется
    АТОМАРНО (tmp → fsync → rename): `ssh_run` читает его целиком и не должен увидеть половину.
    Запрос переделки становится `queued` только ПОСЛЕ успешной записи — до этого страница
    честно показывает «принято, ждёт сборки очереди»."""
    import time
    rework = pending_rework()
    used = used_seeds(set(rework), os.path.join(HERE, 'mesh-reseed.json'), active_snapshots())
    photo, gen0 = stale_facts(todo)
    # Причины — по представителям семейства: варианты в `todo` не попадают (`products`).
    no_hash = sum(1 for x in todo if x['status'] == 'stale' and x['sku'] not in photo)
    suppressed = 0
    jobs, queued, seen = [], [], set()
    for x in todo:
        p = prod[x['sku']]
        mid, eid = x['sku'].split(':', 1)
        seeds, strata = [0], {'tier': x['tier'], 'reason': x['reason']}
        rq = rework.get(x['sku'])
        if suppress_seed0(x['status'], bool(rq), x['sku'] in photo, x['sku'] in gen0):
            suppressed += 1
            continue
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
    # ВОЛНА ПО РАЗРЕШЕНИЮ БЕРЁТ ВЕРХ ОЧЕРЕДИ (15.10): автозапуск передавал «сколько моделей оплачено» в предохранитель ниже,
    # а тот на очереди 6240 > 2846 отказывался писать снимок — волна не стартовала. Сколько взять и предохранитель — разное
    total = len(jobs)
    jobs, queued = take_top(jobs, queued, int(os.environ.get('MESH_TAKE_JOBS', '0') or 0))
    if len(jobs) < total:
        print(f'волна по разрешению: беру первые {len(jobs)} из {total} заданий очереди', flush=True)
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
    print(f'stale_missing_photo_hash {no_hash}, suppressed_seed0 {suppressed}', flush=True)


def suppress_seed0(status: str, has_rework: bool, photo_known: bool, has_gen0: bool) -> bool:
    """Не ставить задание seed 0 (план mesh-13, правило сверено с Codex 21.10). Только для stale:
    - запрос переделки владельца → ставим (свой seed, `build_queue`);
    - хеш текущего фото известен → ставим seed 0: stale при известном фото значит «фото сменилось» — новый job_id;
    - хеша фото нет (`product_photo_current`), а поколение seed 0 уже есть → НЕ ставим: «не знаем фото» ≠
      «фото сменилось», а `mesh_bind.enforce_ready_invariant` ставит stale и в этом случае. Перегон дал бы тот же
      job_id, хеш фото генерация не создаёт — товар оставался stale, и каждая волна делала его заново (21.10:
      127 из 239 мешей ночи, 295 таких товаров);
    - поколения нет → ставим.
    quarantine и rejected — как было (вне плана). Чистая функция."""
    return status == 'stale' and not has_rework and not photo_known and has_gen0


def stale_facts(todo: list) -> tuple[set, set]:
    """Факты для `suppress_seed0` из базы по stale-товарам очереди: (хеш фото известен, есть поколение seed 0)."""
    stale = {x['sku'] for x in todo if x['status'] == 'stale'}
    if not stale:
        return set(), set()
    lit = ','.join("'" + s.replace("'", "''") + "'" for s in stale)
    photo = {r[0] for r in db(f"select sku from product_photo_current where coalesce(source_sha,'') <> '' "
                              f"and sku in ({lit})") if r}
    gen0 = {r[0] for r in db(f"select distinct sku from mesh_generations where seed = 0 and sku in ({lit})") if r}
    return photo, gen0


def _selftest() -> int:
    # --- ПРОФИЛЬ ДЕМО v2: закреплённые, затем недобор ленты (demo-20 В2) ---
    bad_demo = 0
    prod = {s_: {'role': 'столик', 'status': st_} for s_, st_ in
            (('m:1', 'none'), ('m:2', 'stale'), ('m:3', 'none'), ('m:5', 'ready'), ('m:8', 'none'))}
    rows = demo_pick(('m:8', 'm:5', 'm:9'), ['m:1', 'm:8', 'm:2', 'm:4', 'm:3'], prod, 'test')
    got = [r['sku'] for r in rows]
    if got[:2] != ['m:8', 'm:5'] or any(r['tier'] != 0 for r in rows[:2]):
        bad_demo += 1; print(f'  FAIL закреплённые не встали первыми с ярусом 0: {got}')
    if got[2:] != ['m:1', 'm:2', 'm:3']:
        bad_demo += 1; print(f'  FAIL недобор ленты — по порядку demo_band, без повторов и без товаров вне products: {got}')
    if 'm:5' in [r['sku'] for r in rows if r['status'] != 'ready']:
        bad_demo += 1; print('  FAIL готовый меш попал бы в генерацию')
    if [r['key'][:2] for r in rows] != ['00', '00', '01', '01', '01'] or rows != sorted(rows, key=lambda r: r['key']):
        bad_demo += 1; print(f'  FAIL ключи ряда — ярус и порядок, снимок не должен перемешаться: {[r["key"] for r in rows]}')
    # кандидат банка (conv-14 шаг 2) — ярус 2 после ленты, без повторов с закреплёнными и лентой
    rows = demo_pick(('m:8',), ['m:1'], prod, 'test', ['m:1', 'm:2', 'm:8', 'm:4'])
    if [(r['sku'], r['tier']) for r in rows] != [('m:8', 0), ('m:1', 1), ('m:2', 2)] or 'bank_candidate' not in rows[-1]['reason']:
        bad_demo += 1; print(f'  FAIL кандидат банка — ярус 2 после ленты, без повторов: {[(r["sku"], r["tier"]) for r in rows]}')
    print('профиль демо: ' + ('ОК' if not bad_demo else f'ПРОВАЛОВ {bad_demo}'))

    bad = 0
    if next_seed(set()) != 1 or next_seed({0}) != 1 or next_seed({0, 1}) != 2 or next_seed({0, 3}) != 4:
        bad += 1; print('  FAIL next_seed')
    import contextlib
    import io
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
    # --- ВЕРХ ОЧЕРЕДИ ПО РАЗРЕШЕНИЮ: переделка за чертой не помечается queued ---
    js = [{'sku': f'm:{i}', 'strata': ({'rework': {'request_id': 100 + i}} if i in (1, 4) else {})} for i in range(5)]
    q = [(101, 7), (104, 9)]
    kj, kq = take_top(js, q, 3)
    if [j['sku'] for j in kj] != ['m:0', 'm:1', 'm:2'] or kq != [(101, 7)]:
        bad += 1
        print('  FAIL take_top: верх очереди или переделки за чертой', kj, kq)
    if take_top(js, q, 0) != (js, q) or take_top(js, q, 10) != (js, q):
        bad += 1
        print('  FAIL take_top: без лимита или лимит больше очереди должен вернуть всё')
    # --- STALE БЕЗ ХЕША ФОТО (план mesh-13): не знаем фото ≠ фото сменилось ---
    if (suppress_seed0('stale', True, False, True) or not suppress_seed0('stale', False, False, True)
            or suppress_seed0('stale', False, True, True) or suppress_seed0('stale', False, False, False)
            or suppress_seed0('quarantine', False, False, True)):
        bad += 1
        print('  FAIL suppress_seed0: подавлять только stale без хеша, с поколением seed 0 и без переделки')
    g = globals()
    keep = {k: g[k] for k in ('pending_rework', 'used_seeds', 'active_snapshots', 'stale_facts', 'db')}
    with tempfile.TemporaryDirectory() as td:
        try:
            g['pending_rework'] = lambda: {'9:1': {'id': 7, 'attempt': 2, 'next_seed': None, 'status': 'requested'}}
            g['used_seeds'] = lambda skus, rp, sn: {s_: {0} for s_ in skus}
            g['active_snapshots'] = lambda: []
            g['stale_facts'] = lambda todo: ({'9:3'}, {'9:1', '9:2', '9:3', '9:5'})
            g['db'] = lambda sql: []
            st = {1: 'stale', 2: 'stale', 3: 'stale', 4: 'stale', 5: 'quarantine'}
            todo = [{'sku': f'9:{i}', 'role': 'кресло', 'tier': 1, 'reason': 'т', 'status': st[i],
                     'policy_version': 't'} for i in st]
            prod = {x['sku']: {'image_url': 'u', 'dims_cm': {}} for x in todo}
            out = os.path.join(td, 'q.json')
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                build_queue(out, todo, prod)
            got = {j['sku']: j['seeds'] for j in json.load(open(out, encoding='utf-8'))['jobs']}
        finally:
            g.update(keep)
    want = {'9:1': [1], '9:3': [0], '9:4': [0], '9:5': [0]}
    if got != want or 'stale_missing_photo_hash 3, suppressed_seed0 1' not in buf.getvalue():
        bad += 1
        print('  FAIL build_queue: переделка без хеша ставится, без переделки подавлена, другой хеш — seed 0',
              got, buf.getvalue()[-120:])
    print(f'mesh_priority selftest: случаев 6 + профиль демо 4, ошибок {bad + bad_demo}')
    return 1 if bad or bad_demo else 0


def main() -> None:
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    # ПРОФИЛЬ — ОТДЕЛЬНАЯ ОЧЕРЕДЬ, НЕ ПОДМЕНА БОЕВОЙ (владелец 11.10: «выдели очередь отдельно,
    # чтоб её логику можно было быстро менять»). Боевой регламент `rules/mesh-priority.json` и
    # его ярусы не затрагиваются; принцип демо живёт в `rules/mesh-queue-demo.json` и меняется
    # правкой JSON. Снимок собирается тем же атомарным путём, старт волны не меняется.
    if '--profile' in sys.argv:
        name = sys.argv[sys.argv.index('--profile') + 1] \
            if sys.argv.index('--profile') + 1 < len(sys.argv) else ''
        if name != 'demo':
            sys.exit(f'неизвестный профиль «{name}»: есть только demo')
        rows = demo_rank()
    else:
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
        print(f'  {x["sku"]:40s} {x["role"]:12s} {str(x["tier"]):13s} {x["reason"]}')


if __name__ == '__main__':
    main()
