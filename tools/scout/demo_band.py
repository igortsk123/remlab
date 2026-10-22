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
    if not dry:
        out = {'target': res['target'], 'queue_max': res['queue_max'], 'cut': res['cut'], 'sets': res['sets'], 'short': short,
               'publish': res['publish'], 'generate': res['generate'],
               'pairs': {f'{r}/{s}': v for (r, s), v in sorted(res['pairs'].items())}}
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
    print(f'demo_band selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--report' in sys.argv:
        sys.exit(report('--dry' in sys.argv))
    print(__doc__)
