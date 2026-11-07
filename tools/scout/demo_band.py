#!/usr/bin/env python3
"""НЕДОБОР ЛЕНТЫ ЗАМЕН ПО ПОЛОСЕ РАЗМЕРА — одно место для правила владельца 22.10 (TG 793/797, план demo-20 часть В).

ПРАВИЛО. У каждого места опубликованного варианта (роль × стиль варианта) в листе замены — не меньше `mesh_target` (10)
АЛЬТЕРНАТИВ: моделей (карточек листа; цвета одной модели — одна карточка, ведущий 22.10) кроме текущей, в полосе размера
комнаты (0.8–1.1 идеала слота, `slot_rules.slot_band`), годных по всем правилам ленты (стиль, живое фото, наличие, габариты) и
после экранных фильтров (диван — той же формы, что место: `sameShape` страницы и `lib/configurator/demo-feeds.ts`). Роль ленты
без места в варианте стиля — 10 моделей без исключений.

ТРИ МНОЖЕСТВА МОДЕЛЕЙ (Codex 22.10): `eligible` — годные в полосе с мешем и без; `ready` — меш готов; `published` — модель в
свежем индексе прода (`flat215_demo._mesh_index`). Лента берёт published, публикация — ready − published, очередь мешей — eligible
− ready. Модель, которая уже на сервере, но не в ленте, лента отвергла своими проверками (цвет модели, фото, годность) или
возьмёт при следующей сборке — действий нет, в счёт не идёт.

ДОБОР — ПО ПОКРЫТИЮ, БЕЗ ДВОЙНОГО СЧЁТА: одна модель годится в несколько стилей и мест (`cover[msid]` — какие места она
закрывает), поэтому жадно берём модель, закрывающую больше всего недобора; при равенстве — сперва готовую (выложить
бесплатно), потом порядок ленты. Очередь мешей — не больше `mesh_queue_max` за раз.

«Есть» — вчерашняя лента (`demo-data.json → feeds`), полоса и места — оттуда же, то есть ровно то, что видит страница. Стили —
опубликованных вариантов (новый подхватится сам, со сдвигом на сутки).

КОМНАТЫ КРОМЕ ГОСТИНОЙ (T-20261106-82/2, владелец 06.11 TG 215/218: «в каждом стиле, в каждой комнате 30 товаров с мешами… меши —
конвейером»). Места — (комната × стиль) банка комнаты, доли ролей — `rules/demo-swap.json → rooms.<комната>.roles` (сумма 30),
полосы — слоты записей банка (−20…+10 %); кандидаты, «есть» (привязка ready) и добор — `room_mesh_demand.room_quota`. Задания
комнат идут в ТОТ ЖЕ профиль demo (`mesh_priority.demo_rank`, ярус 3 — после недобора ленты гостиной и кандидата банка), под
общий потолок `mesh_queue_max` и остаток денег трека комнат (`room_mesh_demand.ledger`, цена `PRICE_RUB`). Гостиная считается
как прежде; сбой комнаты — строка WARN, гостиную не останавливает. Недобор каталога — строкой «не хватает каталога», не ошибкой.

  ~/venvs/scout/bin/python demo_band.py --report          # таблица пар → ~/scout-scenes/demo-band.json (шаг ночной цепочки)
  ~/venvs/scout/bin/python demo_band.py --report --dry    # то же без записи файла
  python3 demo_band.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import demo_swap_pool as DSP  # noqa: E402
from slot_rules import in_band  # noqa: E402

RULES = json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))
TARGET = int(RULES['mesh_target'])
QUEUE_MAX = int(RULES['mesh_queue_max'])
DEMO_DATA = os.path.expanduser(os.environ.get('DEMO_DATA', '~/scout-scenes/flat215-demo/demo-data.json'))
REPORT = os.path.expanduser(os.environ.get('DEMO_BAND_REPORT', '~/scout-scenes/demo-band.json'))
ROOMS = {k: v for k, v in (RULES.get('rooms') or {}).items() if not k.startswith('_')}
RMD_UNIT_RU = {'sku': 'товары (SKU, цвета отдельно)', 'family': 'модели (семейства)'}   # = room_mesh_demand.UNIT_RU
GEN_STATUS = ('none', 'stale')   # меш делать можно: нет его или фото сменилось; брак владельца и карантин — не наше решение
SOFA = 'диван'


def base_role(slot: str) -> str:
    """«стул 2» → «стул»; «стол обеденный» не резать."""
    parts = slot.split(' ')
    return ' '.join(parts[:-1]) if parts[-1].isdigit() else slot


def same_shape(p: dict, place: dict | None) -> bool:
    """Форма дивана — как `sameShape` страницы: угловой ↔ угловой; сторона — если названа у товара (ключ есть, даже пустой)."""
    if place is None:
        return True
    if bool(p.get('corner')) != bool(place.get('corner')):
        return False
    return not place.get('corner') or 'corner_left' not in p or p['corner_left'] == bool(place.get('corner_left'))


def styles_of(demo: dict) -> list[str]:
    return sorted({v['style'] for v in demo.get('variants') or [] if v.get('style')})


def places(demo: dict, roles=DSP.ROLES) -> list[dict]:
    """Места, у которых меряем лист: {'pair': (роль, стиль), 'model': текущая модель, 'place': форма для дивана}. Роль без места
    в варианте этого стиля — одно «место» без текущей модели."""
    out, seen = [], set()
    styles = styles_of(demo)
    for v in demo.get('variants') or []:
        for it in v.get('items') or []:
            role = base_role(it.get('role') or '')
            if role in roles and v.get('style') in styles:
                out.append({'pair': (role, v['style']), 'model': (it.get('sku') or {}).get('msid'),
                            'place': {'corner': it.get('corner'), 'corner_left': it.get('corner_left')} if role == SOFA else None})
                seen.add((role, v['style']))
    out += [{'pair': (r, s), 'model': None, 'place': None} for r in roles for s in styles if (r, s) not in seen]
    return out


def feed_models(demo: dict, roles=DSP.ROLES) -> dict:
    """(роль, стиль) → {модель: товар ленты} в полосе — карточки листа (товар нужен для формы дивана)."""
    band = (demo.get('rules') or {}).get('slot_band_cm') or {}
    out: dict = {}
    for role, lst in (demo.get('feeds') or {}).items():
        if role not in roles:
            continue
        for p in lst:
            if p.get('msid') and in_band(p, band.get(role)):
                for st in p.get('styles') or [p.get('style')]:
                    out.setdefault((role, st), {}).setdefault(p['msid'], p)
    return out


def alternatives(u: dict, models: dict) -> int:
    return sum(1 for m, p in models.items() if m != u['model'] and same_shape(p, u['place']))


def plan(demo: dict, cands: list, published: set, ready: set, gen_ok, target: int = TARGET, qmax: int = QUEUE_MAX) -> dict:
    """Чистое ядро (без базы и сети). `cands` — годные в полосе по порядку ленты: {'msid', 'role', 'style', 'corner'…};
    `published` — модели на сервере; `ready` — меш готов; `gen_ok(msid)` — можно ставить в генерацию.
    → {'pairs': {pair: {...}}, 'publish': [...], 'generate': [...], 'cut': n, 'target', 'queue_max'}"""
    feed = feed_models(demo)
    us = places(demo)
    need = [max(0, target - alternatives(u, feed.get(u['pair'], {}))) for u in us]
    have = list(need)
    rank: dict = {}
    cover: dict = {}
    by_pair: dict = {}
    for k, u in enumerate(us):
        by_pair.setdefault(u['pair'], []).append(k)
    for c in cands:
        m = c['msid']
        if m in published or not (m in ready or gen_ok(m)):
            continue
        rank.setdefault(m, len(rank))
        for k in by_pair.get((c['role'], c['style']), []):
            u = us[k]
            if m != u['model'] and m not in feed.get(u['pair'], {}) and same_shape(c, u['place']):
                cover.setdefault(m, set()).add(k)
    picked: list = []
    took: dict = {}                                   # модель → места, которые она закрыла (строка отчёта, откат по потолку)
    while True:
        best, key = None, None
        for m, ks in cover.items():
            gain = sum(1 for k in ks if need[k] > 0)
            if gain:
                kk = (-gain, 0 if m in ready else 1, rank[m])
                if key is None or kk < key:
                    best, key = m, kk
        if best is None:
            break
        picked.append(best)
        took[best] = {k for k in cover.pop(best) if need[k] > 0}
        for k in took[best]:
            need[k] -= 1
    publish = [m for m in picked if m in ready]
    generate = [m for m in picked if m not in ready]
    cut = max(0, len(generate) - qmax)
    gone = set(generate[qmax:])
    generate = generate[:qmax]
    for m in gone:                                    # срезанное потолком не закрывает: недобор возвращается
        for k in took.pop(m):
            need[k] += 1
    rows: dict = {}
    for pair, ks in by_pair.items():
        mods = {m for m, kk in took.items() if kk & set(ks)}
        rows[pair] = {'have': target - max(have[k] for k in ks), 'short': max(need[k] for k in ks),
                      'publish': sorted(m for m in mods if m in ready), 'generate': sorted(m for m in mods if m not in ready)}
        rows[pair]['after'] = target - rows[pair]['short']
    return {'pairs': rows, 'publish': publish, 'generate': generate, 'cut': cut, 'target': target, 'queue_max': qmax}


def load() -> dict:
    """Факты для `plan`: вчерашняя лента, места и полоса; годные в полосе из базы (ворота ленты, но и без меша) с формой
    дивана (`sofa_shape` — как у ленты); модели на сервере (`flat215_demo._mesh_index`); готовность мешей по базе."""
    from mesh_queue import db
    import flat215_demo as F
    import sofa_shape as SS
    demo = json.load(open(DEMO_DATA, encoding='utf-8'))
    band = (demo.get('rules') or {}).get('slot_band_cm') or {}
    styles = set(styles_of(demo))
    cands = []
    for p in map(DSP._row, db(DSP.pool_sql(any_mesh=True))):
        if p and p['style'] in styles and DSP.fits(p) and in_band(p, band.get(p['role'])):
            if p['role'] == SOFA:
                p.update(SS.shape(p.get('name'), p.get('d')))
            cands.append(p)
    st: dict = {}
    for r in db("select shop_mid||'_'||external_id, coalesce(mesh_status,'none'), (mesh_uri is not null)::text, "
                "coalesce(mesh_required, false)::text from products where cat_role in (" + DSP._lit(DSP.ROLES) + ")"):
        if len(r) == 4:
            st[r[0]] = (r[1], r[2] == 'true', r[3] == 'true')
    return {'demo': demo, 'cands': cands, 'published': set(F._mesh_index()),
            'ready': {k for k, (s, uri, _q) in st.items() if s == 'ready' and uri},
            'eligible': {p['msid'] for p in cands},
            'gen_ok': lambda m: m in st and st[m][0] in GEN_STATUS and st[m][2]}


def compute() -> dict:
    f = load()
    res = plan(f['demo'], f['cands'], f['published'], f['ready'], f['gen_ok'])
    el = f['eligible']
    res['sets'] = {'eligible': len(el), 'ready': len(el & f['ready']), 'published': len(el & f['published'])}
    return res


def _sku(msid: str) -> str:
    return msid.replace('_', ':', 1)


def publish_skus() -> set:
    """Модели (`mid:eid` представителя) выложить под недобор ленты — для `mesh_publish`."""
    return {_sku(m) for m in compute()['publish']}


def queue_skus() -> list:
    """Представители семейств (`mid:eid`) под генерацию — профиль demo очереди мешей (`mesh_priority.demo_rank`), по порядку."""
    return [_sku(m) for m in compute()['generate']]


# ---------------------------------------------------------------- комнаты кроме гостиной (T-20261106-82/2)
def room_bank(room: str, cfg: dict, env=None) -> str | None:
    """Банк комнаты: `DEMO_BAND_BANK_<КОМНАТА>` (проба, worktree), иначе первый существующий из `rooms.<комната>.bank`
    (пути от tools/scout: живой, затем кандидат). Нет ни одного — None (места комнаты не считаем, строка в отчёт)."""
    env = os.environ if env is None else env
    p = env.get(f'DEMO_BAND_BANK_{room.upper()}')
    paths = [p] if p else [x if os.path.isabs(x) else os.path.join(HERE, x) for x in cfg.get('bank') or []]
    return next((x for x in paths if x and os.path.exists(x)), None)


def rooms_merge(per_room: list, qmax_left: int, money_jobs: int) -> dict:
    """Чистое ядро: задания комнат по порядку комнат в правилах, без повторов SKU (меш один на все комнаты), срез потолком
    очереди (остаток после гостиной) и деньгами трека комнат. → {'jobs', 'cut_queue', 'cut_money'}."""
    jobs, seen = [], set()
    for _room, js in per_room:
        for j in js:
            if j['sku'] not in seen:
                seen.add(j['sku'])
                jobs.append(j)
    lim_q, lim_m = max(0, qmax_left), max(0, money_jobs)
    keep = jobs[:min(lim_q, lim_m)]
    return {'jobs': keep, 'cut_queue': max(0, len(jobs) - lim_q),
            'cut_money': max(0, min(len(jobs), lim_q) - lim_m)}


def rooms_compute(living_generate: int) -> dict:
    """Квоты комнат из правил → задания под общий профиль demo. Ошибка одной комнаты — в `notes`, остальные считаются."""
    import math
    import room_mesh_demand as RMD
    out = {'rooms': {}, 'notes': [], 'jobs': [], 'cut_queue': 0, 'cut_money': 0, 'left_rub': None}
    per_room = []
    for room, cfg in ROOMS.items():
        if not cfg.get('enabled'):
            out['notes'].append(f'{room}: выключено (rules/demo-swap.json rooms.{room}.enabled)')
            continue
        bank = room_bank(room, cfg)
        if not bank:
            out['notes'].append(f"{room}: банка нет ({', '.join(cfg.get('bank') or []) or 'пути не заданы'}) — места не считаю")
            continue
        try:
            Q = RMD.room_quota(room, bank, cfg['roles'], share=cfg.get('share'))
        except Exception as e:  # noqa: BLE001 — сбой комнаты не останавливает гостиную и другие комнаты
            out['notes'].append(f'WARN:demo_band: комната {room}: {type(e).__name__}: {e}')
            continue
        out['rooms'][room] = Q
        per_room.append((room, Q['jobs']))
    if per_room:
        try:
            L = RMD.ledger()
        except Exception as e:  # noqa: BLE001 — денег не знаем — заданий комнат нет (деньги важнее)
            out['notes'].append(f'WARN:demo_band: остаток денег комнат не читается ({type(e).__name__}: {e}) — задания комнат не ставлю')
            return out
        out['left_rub'] = L['left']
        M = rooms_merge(per_room, QUEUE_MAX - living_generate, int(math.floor(L['left'] / RMD.PRICE_RUB + 1e-9)))
        out.update(M)
    return out


def room_jobs(living_generate: int) -> list:
    """Задания мешей комнат (формат `room_mesh_jobs.job_of`) — для профиля demo (`mesh_priority.demo_rank`), по порядку."""
    R = rooms_compute(living_generate)
    for n in R['notes']:
        print(n if n.startswith('WARN:') else f'[demo_band] {n}', flush=True)
    return R['jobs']


def rooms_report(R: dict) -> tuple:
    """Строки отчёта по комнатам и запись для demo-band.json → (строки, {комната: {...}})."""
    lines, rec = [], {}
    taken = {j['sku'] for j in R['jobs']}
    for room, Q in R['rooms'].items():
        agg: dict = {}
        for r in Q['table']:
            a = agg.setdefault(f"{r['room_id']}/{r['style']}", {'have': 0, 'target': 0, 'after': 0, 'short': 0})
            a['have'] += r['covered']
            a['target'] += r['target']
            a['after'] += r['after']
            a['short'] += r['short']
        mine = [j['sku'] for j in Q['jobs'] if j['sku'] in taken]
        short = {k: a['short'] for k, a in sorted(agg.items()) if a['short']}
        lines.append(f"[demo_band] комната {room}: квота {sum(Q['split'].values())} на (комната × стиль), счёт — "
                     f"{RMD_UNIT_RU.get(Q.get('unit'), Q.get('unit'))}, в очередь мешей {len(mine)}"
                     f" (банк {os.path.basename(Q['bank'])})")
        for k, a in sorted(agg.items()):
            lines.append(f"  {room} {k}: готово {a['have']} → {a['after']} из {a['target']}"
                         + (f"; не хватает каталога {a['short']}" if a['short'] else ''))
        if short:
            lines.append(f"DIGEST:меши {room}: не хватает каталога — " + ', '.join(f'{k} {v}' for k, v in short.items()))
        rec[room] = {'bank': Q['bank'], 'split': Q['split'], 'unit': Q.get('unit'), 'generate': mine, 'short': short, 'places': agg}
    for n in R['notes']:
        lines.append(n if n.startswith('WARN:') else f'[demo_band] {n}')
    if R['cut_queue']:
        lines.append(f"WARN:demo_band: задания комнат упёрлись в потолок очереди {QUEUE_MAX} — {R['cut_queue']} ждут следующего раза")
    if R['cut_money']:
        lines.append(f"WARN:demo_band: остаток денег комнат {R['left_rub']:g} ₽ — {R['cut_money']} заданий комнат не влезли")
    return lines, rec


def report(dry: bool = False) -> int:
    res = compute()
    print(f"[demo_band] цель — {res['target']} альтернатив на место «роль × стиль» в полосе; потолок очереди {res['queue_max']}; "
          f"годных моделей в полосе {res['sets']['eligible']}: с готовым мешем {res['sets']['ready']}, на сервере {res['sets']['published']}")
    short = []
    for (role, st), r in sorted(res['pairs'].items()):
        if r['have'] >= res['target']:
            continue
        line = f"  {role}/{st}: в ленте {r['have']} → {r['after']}"
        if r['publish']:
            line += f"; выложить {len(r['publish'])}"
        if r['generate']:
            line += f"; сгенерить {len(r['generate'])}"
        if r['short']:
            line += f"; каталога не хватает {r['short']}"
            short.append(f'{role}/{st}')
        print(line)
    print(f"[demo_band] выложить {len(res['publish'])} моделей, в очередь мешей demo {len(res['generate'])}"
          + (f" (срезано потолком {res['cut']})" if res['cut'] else '') + f"; пар без 10 и всем каталогом: {len(short)}")
    if res['cut']:
        print(f"WARN:demo_band: очередь мешей demo упёрлась в потолок {res['queue_max']} — {res['cut']} моделей ждут следующего раза")
    # нехватка каталога — известное состояние, а не поломка: тревога только на НОВЫЕ такие пары (иначе строка каждую ночь,
    # и её перестают читать — урок 470)
    try:
        old = set(json.load(open(REPORT, encoding='utf-8')).get('short') or [])
    except Exception:  # noqa: BLE001 — первого отчёта ещё нет
        old = None
    new = sorted(set(short) - old) if old is not None else []
    if new:
        print(f"WARN:demo_band: новые пары без 10 моделей и всем каталогом: {', '.join(new)}")
    rooms_rec = None
    if ROOMS:
        R = rooms_compute(len(res['generate']))
        lines, rooms_rec = rooms_report(R)
        print('\n'.join(lines))
        print(f"[demo_band] комнаты: в очередь мешей demo {len(R['jobs'])}"
              + (f", остаток денег трека комнат {R['left_rub']:g} ₽" if R['left_rub'] is not None else ''))
    if not dry:
        out = {'target': res['target'], 'queue_max': res['queue_max'], 'cut': res['cut'], 'sets': res['sets'], 'short': short,
               'publish': res['publish'], 'generate': res['generate'],
               'pairs': {f'{r}/{s}': v for (r, s), v in sorted(res['pairs'].items())}}
        if rooms_rec is not None:
            out['rooms'] = rooms_rec
        tmp = REPORT + '.tmp'
        json.dump(out, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.replace(tmp, REPORT)
        print(f'[demo_band] отчёт → {REPORT}')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra='') -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1

    demo = {'rules': {'slot_band_cm': {'столик': {'lo': 88, 'hi': 121, 'side': 'w'}}},
            'variants': [{'style': 'сканди', 'items': [{'role': 'столик', 'sku': {'msid': 'a'}},
                                                       {'role': 'диван', 'corner': True, 'corner_left': True, 'sku': {'msid': 'S0'}}]},
                         {'style': 'лофт', 'items': [{'role': 'стул 2', 'sku': {'msid': 'z'}}]}],
            'feeds': {'столик': [{'msid': 'a', 'w': 100, 'styles': ['сканди', 'лофт']},
                                 {'msid': 'a', 'w': 100, 'styles': ['сканди']},          # цвет той же модели
                                 {'msid': 'b', 'w': 60, 'styles': ['сканди']},           # вне полосы
                                 {'msid': 'c', 'w': 110, 'styles': ['сканди']}],
                      'диван': [{'msid': 'S1', 'corner': True, 'corner_left': True, 'styles': ['сканди']},
                                {'msid': 'S2', 'corner': False, 'styles': ['сканди']},     # прямой на угловое место — нет
                                {'msid': 'S3', 'corner': True, 'styles': ['сканди']}],     # сторона не названа — годится
                      'ковёр': [{'msid': 'r', 'w': 230, 'styles': ['сканди']}]}}
    ok('стили — опубликованных вариантов', styles_of(demo) == ['лофт', 'сканди'])
    us = places(demo)
    ok('места: «стул 2» → стул, роль без места — одно место без текущей',
       {'pair': ('стул', 'лофт'), 'model': 'z', 'place': None} in us and {'pair': ('пуф', 'лофт'), 'model': None, 'place': None} in us)
    fm = feed_models(demo)
    ok('карточки — модели в полосе: цвета одной модели — одна, вне полосы не считается, роли без меша не берём',
       set(fm[('столик', 'сканди')]) == {'a', 'c'} and ('ковёр', 'сканди') not in fm, fm.get(('столик', 'сканди')))
    u_t = next(u for u in us if u['pair'] == ('столик', 'сканди'))
    u_s = next(u for u in us if u['pair'] == ('диван', 'сканди'))
    ok('альтернативы — без текущей модели', alternatives(u_t, fm[('столик', 'сканди')]) == 1)
    ok('диван: на угловое левое — угловой левый и угловой без стороны, прямой — нет', alternatives(u_s, fm[('диван', 'сканди')]) == 2)
    C = lambda m, st='сканди', **kw: {'msid': m, 'role': 'столик', 'style': st, **kw}  # noqa: E731
    cands = [C('a'), C('s1'), C('p1'), C('x1'), C('g1'), C('g2'), C('g3'), C('g1', 'лофт'), C('g4', 'лофт'),
             {'msid': 'P', 'role': 'диван', 'style': 'сканди', 'corner': False}]
    res = plan(demo, cands, published={'a', 'c', 's1'}, ready={'p1', 'P'}, gen_ok=lambda m: m != 'x1', target=4, qmax=10)
    sk, lo = res['pairs'][('столик', 'сканди')], res['pairs'][('столик', 'лофт')]
    ok('модель на сервере вне ленты — не действие (лента её отвергла)', 's1' not in res['publish'] + res['generate'])
    ok('прямой готовый диван на угловое место не выкладываем — не закрывает', 'P' not in res['publish'], res['publish'])
    ok('брак/карантин (gen_ok=нет) — пропуск', 'x1' not in res['generate'])
    ok('модель, годная в два стиля, — первой и одним заданием (g1 закрывает сканди и лофт)',
       res['generate'][:1] == ['g1'] and res['generate'].count('g1') == 1, res['generate'])
    ok('готовую — раньше генерации при равном вкладе', res['publish'] == ['p1'], res['publish'])
    ok('добор до цели и не больше: сканди 1 альтернатива → 4 (p1, g1, g2), g3 не взят',
       sk['have'] == 1 and sk['after'] == 4 and 'g3' not in res['generate'], sk)
    ok('нехватка каталога видна числом: лофт 1 → 3 (g1, g4), не хватает 1',
       lo['have'] == 1 and lo['after'] == 3 and lo['short'] == 1 and lo['generate'] == ['g1', 'g4'], lo)
    cut = plan(demo, cands, {'a', 'c', 's1'}, {'p1'}, lambda m: m != 'x1', target=4, qmax=1)
    ok('потолок очереди: первые по вкладу, остаток срезан и недобор за ним вернулся',
       cut['generate'] == ['g1'] and cut['cut'] == 2 and cut['pairs'][('столик', 'лофт')]['after'] == 2, cut['pairs'][('столик', 'лофт')])
    ok('правило — из rules/demo-swap.json', TARGET == int(RULES['mesh_target']) and QUEUE_MAX == int(RULES['mesh_queue_max']))
    # КОМНАТЫ (T-20261106-82/2)
    J = lambda *ss: [{'sku': x} for x in ss]  # noqa: E731
    m = rooms_merge([('bedroom', J('a', 'b', 'c')), ('hall', J('b', 'd'))], qmax_left=10, money_jobs=10)
    ok('комнаты: меш один на обе комнаты — SKU без повторов, порядок комнат из правил',
       [j['sku'] for j in m['jobs']] == ['a', 'b', 'c', 'd'] and m['cut_queue'] == m['cut_money'] == 0, m)
    m = rooms_merge([('bedroom', J('a', 'b', 'c')), ('hall', J('d'))], qmax_left=3, money_jobs=2)
    ok('комнаты: срез — остатком потолка очереди после гостиной и деньгами трека комнат, оба числа видны',
       [j['sku'] for j in m['jobs']] == ['a', 'b'] and m['cut_queue'] == 1 and m['cut_money'] == 1, m)
    ok('комнаты: потолок очереди уже выбран гостиной — заданий комнат нет', rooms_merge([('x', J('a'))], 0, 5)['jobs'] == [])
    ok('комнаты: банк из env пробы, иначе первый существующий из правил, иначе None',
       room_bank('bedroom', {'bank': ['/nope.json', __file__]}, env={}) == __file__
       and room_bank('bedroom', {'bank': [__file__]}, env={'DEMO_BAND_BANK_BEDROOM': '/nope'}) is None
       and room_bank('hall', {'bank': ['/nope.json']}, env={}) is None)
    ok('комнаты: доли ролей в правилах — сумма 30 на (комната × стиль)',
       all(sum(v['roles'].values()) == 30 for v in ROOMS.values()), {k: sum(v['roles'].values()) for k, v in ROOMS.items()})
    # T-20261107-10/2: распашной «шкаф» прихожей — член доли шкафа-купе; T-20261107-18/2: и модуль «прихожая» (купе 11),
    # сумма долей остаётся 30
    import room_mesh_demand as RMD
    ok('комнаты: общие доли (share) проходят проверку quota_share; прихожая — «шкаф» и модуль в доле «шкаф-купе», своей доли нет',
       all(RMD.quota_share(v['roles'], v.get('share')) is not None for v in ROOMS.values())
       and ROOMS['hall'].get('share') == {'шкаф': 'шкаф-купе', 'прихожая': 'шкаф-купе'}
       and not ({'шкаф', 'прихожая'} & set(ROOMS['hall']['roles'])) and ROOMS['hall']['roles']['шкаф-купе'] == 11)
    print(f'demo_band selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--report' in sys.argv:
        sys.exit(report('--dry' in sys.argv))
    print(__doc__)
