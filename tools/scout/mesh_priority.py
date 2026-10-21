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
import re
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
_STOP_COLOR = re.compile(
    r'\b(беж\w*|сер\w*|син\w*|зел[её]н\w*|коричн\w*|ч[её]рн\w*|бел\w*|графит\w*|латте|мокко|'
    r'изумруд\w*|горчичн\w*|пудр\w*|роз\w*|голуб\w*|фиолет\w*|бордо\w*|венге|дуб\s?\w*|орех\w*|'
    r'ясень|сонома|капучино|шоколад\w*|молочн\w*|крем\w*|песочн\w*|терракот\w*|оливк\w*|мятн\w*|'
    r'лаванд\w*|карбон|антрацит|жемчужн\w*|сливов\w*|вельвет\w*|велюр\w*|шенилл\w*|рогожк\w*|'
    r'экокож\w*|микровелюр\w*|правый|левый|угол|бархат\w*|т[её]мн\w*|светл\w*|глосс|люкс|найс|'
    r'плюш\w*)\b', re.I)


def _model_key(name: str) -> str:
    """Ключ модели — как у стиль-скоринга (`style_score.py:34-37`): цвета вычеркнуты, 6 слов."""
    n = _STOP_COLOR.sub(' ', (name or '').lower())
    n = re.sub(r'[^а-яa-z0-9 ]', ' ', n)
    return ' '.join(re.sub(r'\s+', ' ', n).strip().split()[:6])


def style_lookup():
    """Оценка стиля по товару. ПОРЯДОК КАК У СБОРЩИКА СЕТОВ, иначе очередь и сеты выберут разных.

    Канон (`core/styles.md`, сверено 11.10): источник №1 — база (`enrich_bridge.style_scores`),
    `style-scores.json` — фолбэк, именно так их берёт `compose2.py:538`. В JSON ключ — МОДЕЛЬ, а
    не артикул: скоринг схлопывает цвета по первым 6 словам названия и кэширует под ПЕРВЫМ
    артикулом модели, который не обязан совпадать с представителем семейства мешей. Чтение по
    артикулу в лоб теряет 21% пула (замер 11.10: 277 из 1306).
    """
    try:
        import enrich_bridge as EB
    except Exception:  # noqa: BLE001 — без базы остаётся только JSON
        EB = None
    jpath = os.path.join(HERE, 'style-scores.json')
    raw = {}
    if os.path.exists(jpath):
        with open(jpath, encoding='utf-8') as fh:
            raw = json.load(fh)
    # Карта «(магазин, модель) → оценка» строится ОДИН раз: линейный поиск по 17 тыс. ключей на
    # каждый товар давал бы десятки миллионов операций с регексом на сборку одной очереди.
    by_model: dict[tuple[str, str], dict] = {}
    for k, v in raw.items():
        km, _, ke = k.partition('-')
        by_model.setdefault((km, _model_key(ke)), v)

    def get(sku: str, name: str) -> dict | None:
        mid, _, eid = sku.partition(':')
        if EB is not None:
            try:
                sc = EB.style_scores(int(mid), eid)
                if sc:
                    return sc
            except Exception:  # noqa: BLE001 — мост не должен ронять сборку очереди
                pass
        direct = raw.get(f'{mid}-{eid}')
        if direct:
            return direct
        return by_model.get((mid, _model_key(name)))
    return get


def demo_rank() -> list[dict]:
    """Очередь под демо: топ-N на каждый тип в КАЖДОМ стиле, без повторов и без готовых.

    Один товар, годный в несколько стилей, встаёт в очередь ОДИН раз: меш у него один
    (ADR-0196), и платить дважды незачем. Ярус = номер стиля, поэтому первым добивается первый
    стиль списка — порядок стилей задаётся профилем.
    """
    prof = json.load(open(DEMO_PROFILE, encoding='utf-8'))
    top_n, styles, roles = prof['top_n'], prof['styles'], set(prof['roles'])
    pen = float(prof.get('universal_penalty') or 0)
    prod = products()
    names = {r[0]: r[1] for r in db("select shop_mid||':'||external_id, "
                                    "replace(coalesce(name,''), chr(9), ' ') from products "
                                    "where mesh_required")}
    get = style_lookup()
    scored = []
    for sku, p in prod.items():
        if p['role'] not in roles:
            continue
        sc = get(sku, names.get(sku, ''))
        if not sc:
            continue
        scored.append((sku, p, sc))

    return demo_pick(scored, styles, roles, top_n, pen,
                     f"demo-v{prof.get('policy_version', 1)}",
                     pinned=tuple(pinned_skus()), prod=prod)


def demo_pick(scored: list, styles: list, roles: set, top_n: int, pen: float,
              ver: str, pinned: tuple = (), prod: dict | None = None) -> list[dict]:
    """Чистый отбор: топ-N на тип в каждом стиле, без повторов, без готовых. Без базы и сети.

    Один товар, годный в несколько стилей, встаёт ОДИН раз: меш у него один (ADR-0196), платить
    дважды незачем. Ярус = номер стиля, поэтому первым добивается первый стиль списка.

    ЗАКРЕПЛЁННЫЕ ВЛАДЕЛЬЦЕМ ИДУТ ПЕРЕД ВСЕМИ СТИЛЯМИ (12.10). Ярус `pinned` жил только в боевом
    ранжире `rank()`, а профиль считает очередь здесь — и список `rules/mesh-pinned.json` на него
    не влиял вовсе. Цена ошибки измерена: волна 12.10 сделала 986 мешей за 709 ₽, но из 12
    закреплённых позиций, которыми закрывались все шесть сцен демо, попали только 2 — деньги
    ушли «вширь», по 30 вариантов на тип. Закреплённый берётся НЕЗАВИСИМО от того, попала ли его
    роль в профиль и есть ли у него оценка стиля: это прямое указание человека, а не отбор.
    """
    rows, seen = [], set()
    for sku in (pinned or ()):
        p = (prod or {}).get(sku)
        if not p or sku in seen:
            continue
        seen.add(sku)
        rows.append({'tier': 0, 'sku': sku, 'role': p['role'], 'status': p['status'],
                     'key': f'00|{len(rows):06d}|{sku}',
                     'reason': 'закреплено владельцем (rules/mesh-pinned.json)',
                     'policy_version': ver})
    for si, style in enumerate(styles, 1):
        def key(x, _st=style):
            v = float(x[2].get(_st) or 0)
            if pen and x[2].get('universal'):
                v -= pen          # универсальный не вытесняет характерный при равном балле
            return (-v, x[0])     # tie-break по sku: снимок не должен дрожать между прогонами
        taken: dict[str, int] = {}
        for sku, p, sc in sorted(scored, key=key):
            if sku in seen or taken.get(p['role'], 0) >= top_n:
                continue
            if p['role'] not in roles:
                continue
            # ГОТОВЫЙ МЕШ ЗАНИМАЕТ СЛОТ, А НЕ ОСВОБОЖДАЕТ ЕГО (11.10). Он И ЕСТЬ один из 30
            # вариантов стиля — просто делать его не надо. Пропускать готовых ПРИ ОТБОРЕ значит
            # отдавать их места следующим кандидатам и раздувать генерацию: замер показал
            # 585 → 684 задания. Поэтому ряд создаётся, а отбрасывает готовых уже `main()`,
            # тем же фильтром, что и у боевой очереди.
            seen.add(sku)
            taken[p['role']] = taken.get(p['role'], 0) + 1
            # Форма ряда — ТА ЖЕ, что у боевого ранжира: `build_queue` читает `key` и
            # `policy_version`, профиль обязан соблюдать их контракт, а не свой.
            rows.append({'tier': si, 'sku': sku, 'role': p['role'], 'status': p['status'],
                         'key': f'{si:02d}|{len(rows):06d}|{sku}',
                         'reason': f'демо: стиль «{style}», балл {float(sc.get(style) or 0):.1f}',
                         'policy_version': ver})
    rows.sort(key=lambda x: x['key'])
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
    # --- ПРОФИЛЬ ДЕМО: топ-N на тип в каждом стиле ---
    bad_demo = 0
    def _p(role, status='none'):
        return {'role': role, 'status': status}
    sc = lambda a, b, u=False: {'сканди': a, 'лофт': b, 'universal': u}  # noqa: E731
    scored = [
        ('m:1', _p('диван'), sc(9, 1)), ('m:2', _p('диван'), sc(8, 2)),
        ('m:3', _p('диван'), sc(1, 9)), ('m:4', _p('кресло'), sc(9, 9)),
        ('m:5', _p('диван', 'ready'), sc(10, 10)),       # готовый не повторяем
        ('m:6', _p('ковёр'), sc(10, 10)),                # роль вне профиля
        ('m:7', _p('кресло'), sc(9, 9, True)),           # универсальный — со штрафом
    ]
    rows = demo_pick(scored, ['сканди', 'лофт'], {'диван', 'кресло'}, 2, 0.5, 'test')
    got = [r['sku'] for r in rows]
    # Готовый ЗАНИМАЕТ слот (он и есть один из вариантов), но в генерацию не идёт — его
    # отбрасывает `main()` тем же фильтром, что у боевой очереди. Проверяем оба утверждения.
    if 'm:5' not in got:
        bad_demo += 1; print('  FAIL готовый меш не занял слот — места уйдут лишним кандидатам')
    if 'm:5' in [r['sku'] for r in rows if r['status'] != 'ready']:
        bad_demo += 1; print('  FAIL готовый меш попал бы в генерацию')
    if 'm:6' in got:
        bad_demo += 1; print('  FAIL профиль взял роль вне списка')
    if len(got) != len(set(got)):
        bad_demo += 1; print(f'  FAIL товар попал в очередь дважды: {got}')
    # ЗАКРЕПЛЁННЫЕ — ПЕРВЫМИ И НЕЗАВИСИМО ОТ ПРОФИЛЯ (12.10). `m:6` роль вне профиля, `m:8`
    # вовсе без оценок стиля: оба закреплены человеком и обязаны попасть в начало очереди.
    prod = {sku: p for sku, p, _ in scored} | {'m:8': _p('тв-тумба')}
    rows_p = demo_pick(scored, ['сканди', 'лофт'], {'диван', 'кресло'}, 2, 0.5, 'test',
                       pinned=('m:6', 'm:8'), prod=prod)
    got_p = [r['sku'] for r in rows_p]
    if got_p[:2] != ['m:6', 'm:8']:
        bad_demo += 1; print(f'  FAIL закреплённые не встали первыми: {got_p[:4]}')
    if len(got_p) != len(set(got_p)):
        bad_demo += 1; print(f'  FAIL закреплённый продублировался отбором: {got_p}')
    if any(r['tier'] != 0 for r in rows_p[:2]):
        bad_demo += 1; print('  FAIL у закреплённых не нулевой ярус — порядок снимка собьётся')
    # В «сканди» топ-2 диванов — по баллу: m:5 (10, уже готов — слот занят) и m:1 (9).
    # m:3 (балл 1 в сканди) не берём: отбор именно по соответствию стилю, а не по порядку sku.
    sk = [r['sku'] for r in rows if r['tier'] == 1 and r['role'] == 'диван']
    if sk != ['m:5', 'm:1']:
        bad_demo += 1; print(f'  FAIL топ-2 диванов в «сканди»: {sk}, ждали [m:5, m:1]')
    # …а в генерацию из этой пары идёт только неготовый
    gen = [r['sku'] for r in rows if r['tier'] == 1 and r['role'] == 'диван'
           and r['status'] != 'ready']
    if gen != ['m:1']:
        bad_demo += 1; print(f'  FAIL в генерацию по «сканди» идут {gen}, ждали [m:1]')
    # лимит на ТИП внутри стиля, а не на стиль целиком
    if any(sum(1 for r in rows if r['tier'] == t and r['role'] == ro) > 2
           for t in (1, 2) for ro in ('диван', 'кресло')):
        bad_demo += 1; print('  FAIL лимит top_n на тип нарушен')
    # штраф за универсальность: при равном балле характерный (m:4) идёт раньше
    cr = [r['sku'] for r in rows if r['role'] == 'кресло']
    if cr and cr[0] != 'm:4':
        bad_demo += 1; print(f'  FAIL универсальный вытеснил характерный: {cr}')
    # Ключ модели обязан СОВПАДАТЬ с ключом стиль-скоринга (`style_score.py:34-37`) — иначе
    # оценка не найдётся. Поэтому список вычёркиваемых слов копируется дословно, а не улучшается.
    if _model_key('Диван divan.ru Риббл-1 Велюр Молочный') != _model_key(
            'Диван divan.ru Риббл-1 Шенилл Графитовый'):
        bad_demo += 1; print('  FAIL ключ модели не схлопывает варианты ткани и цвета')
    # ИЗВЕСТНАЯ ДЫРА ОБЩЕГО СПИСКА (найдена этим стендом 11.10): «букле» в нём нет, поэтому
    # вариант на букле получает ОТДЕЛЬНУЮ оценку стиля. Для поиска не страшно (ищем по своему
    # ключу и по артикулу), но скоринг платит за лишние карточки. Чинить — в `style_score.py`,
    # это область сессии каталога; здесь фиксируем контрактом, чтобы не забылось.
    if _model_key('Диван Риббл-1 Букле Молочный') == _model_key('Диван Риббл-1 Велюр Молочный'):
        bad_demo += 1; print('  FAIL «букле» вдруг стало вычёркиваться — обнови заметку о дыре')
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
    print(f'mesh_priority selftest: случаев 6, ошибок {bad}')
    return 1 if bad else 0


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
