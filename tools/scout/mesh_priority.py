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
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'mesh-priority.json')
SETS = os.path.join(HERE, 'sets3.json')
SAMPLE = os.path.join(HERE, 'mesh-pilot-sample.json')
# ON_ERROR_STOP ОБЯЗАТЕЛЕН: без него psql при ошибке SQL отдаёт код 0 и пустой вывод,
# и «неверная колонка» выглядит как «в базе ничего нет» (поймано на себе 01.09).
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

TIER_IDS = ('demo_flat215', 'set_closure', 'furniture', 'light_decor')


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

    Вход генератора берём как ADR-0136: HD-фото, иначе обычное. Габариты обязательны —
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
        if sku in demo:
            tier, why = 'demo_flat215', 'показывается на /test/flat215-demo'
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


def main() -> None:
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
        prod = products()
        jobs = []
        for x in todo:
            p = prod[x['sku']]
            mid, eid = x['sku'].split(':', 1)
            jobs.append({'sku': x['sku'], 'mid': int(mid), 'eid': eid, 'role': x['role'],
                         'name': '', 'image_url': p['image_url'], 'dims_cm': p['dims_cm'],
                         'strata': {'tier': x['tier'], 'reason': x['reason']}, 'seeds': [0]})
        json.dump({'source': 'mesh_priority', 'policy_version': todo[0]['policy_version'],
                   'built_at': __import__('time').strftime('%Y-%m-%dT%H:%M:%S'),
                   'jobs': jobs}, open(path, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'очередь собрана: {len(jobs)} заданий в порядке приоритета → {path}')
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
