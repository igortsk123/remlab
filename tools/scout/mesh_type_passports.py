#!/usr/bin/env python3
"""Единственный загрузчик реестра паспортов типов (rules/mesh-type-passports.json) — план mesh-type-passports-01, фаза 1 «реестр + тень».

ЧТО ЭТО. Паспорт типа — данные: путь роли (`route`, ссылка на `asset-strategies.json`), флаги цепочки вырезки (`chain_flags`, сверяются с
константами `components.py`/`hybrid_mask.py` тестом), сторожа (`guards[]`: К1 «потеря изголовья» у кровати, К3 «подушка однотонная» у подушки),
режим (`observe`/`enforce`), `provisional`. Фаза 1 НИЧЕГО не блокирует: сторожа только пишут вердикт в `passport_shadow`, гейты платных входов
работают в `observe` (всегда «пропустить», но считают «заблокировал бы»). Блокировка платного — фаза 2, отдельный план.

ЗАКОН РАМКИ: паспорт с `provisional: true` не может быть в режиме `enforce`, не имеет сторожей и не влияет на маршрут — схема такой паспорт отвергает.

`gate()` и `passport_preflight()` НИКОГДА не бросают: любой сбой реестра → «пропустить» + одна строка `WARN:passport_registry` за прогон
(платный путь не должен упасть из-за битого JSON). Схему проверяет CI (`--selftest`), а не ночь. Копии в `salad/` в фазе 1 нет (образ GPU не меняется).

  python tools/scout/mesh_type_passports.py --selftest
  python tools/scout/mesh_type_passports.py            # сводка реестра
"""
import collections
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import asset_strategy as AS  # noqa: E402 — канон стратегий: route паспорта обязан совпасть с AS.strategy(тип)

PATH = os.environ.get('PASSPORTS_PATH') or os.path.join(HERE, 'rules', 'mesh-type-passports.json')

# Закрытые списки схемы (неизвестное имя — ошибка, fail-closed).
STAGES = ('pre_mask', 'full_frame', 'cropped')
GUARD_NAMES = ('headboard_loss', 'pillow_plain')
CHAIN_FLAGS = ('grow', 'solid_silhouette', 'attached_prune', 'solid_body')
FAMILIES = ('мягкое', 'корпусное', 'каркасное', 'плоское', 'свет', 'вращательное', 'текстиль', 'смешанное', 'декор', 'настенное')
MODES = ('observe', 'enforce')
SUBTYPES_ALLOWED = ('hb_low',)
# Поля-селекторы товара запрещены (правила — по признакам, без ID): sku, id, url, sha, product*, *_id.
_BAD_KEY = re.compile(r'^(sku|id|url|sha|product.*|.*_id)$', re.I)
# Значения без идентификаторов: «№12», «#123», шаблон SKU «123:456», цепочки из ≥5 цифр.
_BAD_VAL = re.compile(r'(№\s*\d+|#\d+|\b\d+:\d+\b|\d{5,})')


class PassportError(RuntimeError):
    """Реестр не прошёл схему (список причин в тексте)."""


def policy_view(p: dict) -> dict:
    """Часть паспорта, которая и есть ПОЛИТИКА (идёт в digest): всё, кроме `sample` и ключей-пояснений `_*`."""
    return {k: v for k, v in p.items() if k != 'sample' and not k.startswith('_')}


def digest_of(p: dict) -> str:
    """sha256 канонического JSON политики одного паспорта (пороги, подтипы, guards[], режим, route…)."""
    return hashlib.sha256(json.dumps(policy_view(p), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _walk(node, path, errs):
    """Запрет селекторов и идентификаторов во всём реестре (ключи и значения; `_*`-пояснения не проверяются)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.startswith('_'):
                continue
            if _BAD_KEY.match(str(k)):
                errs.append(f'{path}.{k}: поле-селектор товара запрещено')
            _walk(v, f'{path}.{k}', errs)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f'{path}[{i}]', errs)
    elif isinstance(node, str) and _BAD_VAL.search(node):
        errs.append(f'{path}: значение похоже на идентификатор ({node[:40]!r})')


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(reg, strategies: set | None = None) -> list:
    """Список ошибок схемы (пустой — реестр годен). Чистая функция; `strategies` — допустимые route (по умолчанию из канона)."""
    errs: list = []
    if not isinstance(reg, dict) or not isinstance(reg.get('types'), dict) or not reg['types']:
        return ['нет объекта types']
    if strategies is None:
        strategies = set(AS._load().get('_strategies') or {})
    _walk(reg.get('types'), 'types', errs)
    seen: dict = {}
    for name, p in reg['types'].items():
        w = f'types[{name}]'
        if not isinstance(p, dict):
            errs.append(f'{w}: не объект')
            continue
        for a in [name] + list(p.get('aliases') or []):
            if not isinstance(a, str) or not a.strip() or a != a.strip():
                errs.append(f'{w}: пустое имя/алиас {a!r}')
            elif a in seen and seen[a] != name:
                errs.append(f'{w}: имя «{a}» уже у типа «{seen[a]}»')
            else:
                seen[a] = name
        if p.get('family') not in FAMILIES:
            errs.append(f'{w}.family={p.get("family")!r}: допустимо {FAMILIES}')
        if not isinstance(p.get('provisional'), bool):
            errs.append(f'{w}.provisional: нужен bool')
        if p.get('mode') not in MODES:
            errs.append(f'{w}.mode={p.get("mode")!r}: допустимо {MODES}')
        if p.get('route') not in strategies:
            errs.append(f'{w}.route={p.get("route")!r}: нет в стратегиях канона')
        if not isinstance(p.get('needs_3d'), bool):
            errs.append(f'{w}.needs_3d: нужен bool')
        cut = p.get('cutout')
        if not isinstance(cut, dict):
            errs.append(f'{w}.cutout: нужен объект')
            continue
        flags = cut.get('chain_flags')
        if not isinstance(flags, list) or any(f not in CHAIN_FLAGS for f in flags):
            errs.append(f'{w}.cutout.chain_flags={flags!r}: допустимо подмножество {CHAIN_FLAGS}')
        guards = cut.get('guards')
        if not isinstance(guards, list):
            errs.append(f'{w}.cutout.guards: нужен список')
            guards = []
        if p.get('provisional') is True:
            # ЗАКОН РАМКИ: provisional → только observe, без сторожей, без влияния на маршрут
            if p.get('mode') != 'observe':
                errs.append(f'{w}: provisional не может быть в режиме {p.get("mode")!r} (только observe)')
            if guards:
                errs.append(f'{w}: provisional не может иметь сторожей')
        for i, g in enumerate(guards):
            gw = f'{w}.cutout.guards[{i}]'
            if not isinstance(g, dict):
                errs.append(f'{gw}: не объект')
                continue
            if g.get('name') not in GUARD_NAMES:
                errs.append(f'{gw}.name={g.get("name")!r}: допустимо {GUARD_NAMES}')
            if g.get('stage') not in STAGES:
                errs.append(f'{gw}.stage={g.get("stage")!r}: допустимо {STAGES}')
            if not isinstance(g.get('measurement_version'), str) or not re.fullmatch(r'k\d+\.v\d+', g.get('measurement_version') or ''):
                errs.append(f'{gw}.measurement_version: вид k1.v1')
            for b in ('needs_source', 'blocking'):
                if not isinstance(g.get(b), bool):
                    errs.append(f'{gw}.{b}: нужен bool')
            th = g.get('thresholds')
            if not isinstance(th, dict) or not th or any(not _num(v) or v < 0 or v > 1000 for v in th.values()):
                errs.append(f'{gw}.thresholds: нужны числа 0…1000')
            elif not set(g.get('pixel_params') or ()) <= set(th):
                errs.append(f'{gw}.pixel_params: ключи вне thresholds')
        sub = p.get('subtypes')
        if sub is not None and (not isinstance(sub, list) or any(s not in SUBTYPES_ALLOWED for s in sub)):
            errs.append(f'{w}.subtypes: допустимо {SUBTYPES_ALLOWED}')
        if 'sample' in p and (not isinstance(p['sample'], dict) or set(p['sample']) - {'count', 'period', 'source'}):
            errs.append(f'{w}.sample: только агрегаты count/period/source')
    return errs


_REG = None


def load(path: str | None = None, force: bool = False) -> dict:
    """Реестр с проверкой схемы. Бросает PassportError (строгий путь: CI, самотест). Боевые вызовы идут через gate()."""
    global _REG
    if path is None and _REG is not None and not force:
        return _REG
    p = path or PATH
    try:
        reg = json.load(open(p, encoding='utf-8'))
    except FileNotFoundError:
        raise PassportError(f'реестр не найден: {p}')
    except ValueError as e:
        raise PassportError(f'реестр не JSON: {e}')
    errs = validate(reg)
    if errs:
        raise PassportError('схема реестра: ' + '; '.join(errs[:8]) + (f' …(+{len(errs) - 8})' if len(errs) > 8 else ''))
    if path is None:
        _REG = reg
    return reg


def _index(reg: dict) -> dict:
    out = {}
    for name, p in reg['types'].items():
        out[name] = name
        for a in p.get('aliases') or ():
            out[a] = name
    return out


def normalize(role: str | None, reg: dict | None = None) -> str | None:
    """Роль каталога → имя типа паспорта (по `base_role` канона + алиасы) или None."""
    reg = reg or load()
    return _index(reg).get(AS.base_role(role))


def get(role: str | None, reg: dict | None = None) -> dict | None:
    reg = reg or load()
    t = normalize(role, reg)
    return reg['types'][t] if t else None


def digest(role: str | None, reg: dict | None = None) -> str | None:
    p = get(role, reg)
    return digest_of(p) if p else None


def guard_for(role: str | None, name: str, reg: dict | None = None) -> dict | None:
    p = get(role, reg)
    for g in ((p or {}).get('cutout') or {}).get('guards') or ():
        if g.get('name') == name:
            return g
    return None


# ------------------------------------------------------------------ гейт (observe)

STATS: collections.Counter = collections.Counter()
NO_PASSPORT: collections.Counter = collections.Counter()   # роль без паспорта → число товаров
_WARNED: set = set()


def reset_stats() -> None:
    STATS.clear()
    NO_PASSPORT.clear()
    _WARNED.clear()


def warn_once(key: str, line: str) -> None:
    if key not in _WARNED:
        _WARNED.add(key)
        print(line, flush=True)


def gate(role: str | None, mode: str = 'observe', verdict: str | None = None, n: int = 1) -> tuple:
    """Ворота платного входа → (решение, причина). НИКОГДА не бросает: любой сбой → ('pass', 'registry_error') и одна WARN-строка.

    `observe` (фаза 1): решение ВСЕГДА 'pass'; причина `would_block:no_passport` (роли нет в реестре) или `would_block:<вердикт>` (вердикт тени
    из blocking_verdicts блокирующего сторожа неблокированного-provisional паспорта) — только счётчик. `enforce` в фазе 1 не подключён."""
    try:
        reg = load()
        t = normalize(role, reg)
        if t is None:
            STATS['would_block:no_passport'] += n
            NO_PASSPORT[AS.base_role(role) or '(пусто)'] += n
            return ('pass', 'would_block:no_passport') if mode == 'observe' else ('block', 'no_passport')
        p = reg['types'][t]
        if p['provisional']:
            STATS['pass:provisional'] += n
            return 'pass', 'provisional'
        if verdict:
            for g in p['cutout']['guards']:
                if g['blocking'] and verdict in g.get('blocking_verdicts', ()):
                    STATS[f'would_block:{verdict}'] += n
                    if mode == 'enforce' and p['mode'] == 'enforce':
                        return 'block', verdict
                    return 'pass', f'would_block:{verdict}'
        STATS['pass:ok'] += n
        return 'pass', 'ok'
    except Exception as e:  # noqa: BLE001 — гейт обязан не ронять платный путь
        STATS['pass:registry_error'] += n
        warn_once('registry', f'WARN:passport_registry: {type(e).__name__}: {str(e)[:160]} — гейт пропускает (observe), платный путь не меняется')
        return 'pass', 'registry_error'


def passport_preflight(role: str | None) -> tuple:
    """Пред-платная проверка покраски StableGen (`sg_salad.run`): то же, что gate, в `observe`. Не бросает."""
    return gate(role, 'observe')


def report_line() -> str:
    """Строка ночного отчёта по гейтам: сколько пропущено, «заблокировал бы», роли без паспорта."""
    try:
        wb = {k.split(':', 1)[1]: v for k, v in STATS.items() if k.startswith('would_block:')}
        return (f"гейты паспортов (observe): пропущено {sum(v for k, v in STATS.items() if k.startswith('pass:'))}, "
                f"заблокировал бы {sum(wb.values())} {dict(wb) if wb else ''}; ролей без паспорта {len(NO_PASSPORT)}, товаров {sum(NO_PASSPORT.values())}"
                + (f", сбоев реестра {STATS['pass:registry_error']}" if STATS.get('pass:registry_error') else ''))
    except Exception as e:  # noqa: BLE001
        return f'гейты паспортов: отчёт не собран ({type(e).__name__})'


# ------------------------------------------------------------------ самотест

def _selftest() -> int:
    import copy
    import remlab_tmp
    remlab_tmp.use('mesh_type_passports')
    import tempfile
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    reg = load(force=True)
    ok('реестр проходит схему', validate(reg) == [])
    ok('30 типов', len(reg['types']) == 30)
    prov = [n for n, p in reg['types'].items() if p['provisional']]
    ok('сторожа только у кровати и подушки, остальные 28 — provisional',
       sorted(set(reg['types']) - set(prov)) == ['кровать', 'подушка'] and len(prov) == 28)
    ok('все паспорта в режиме observe', all(p['mode'] == 'observe' for p in reg['types'].values()))
    # маршрут — по AS.strategy(тип), не по ключам roles (кровать и тумба прикроватная идут через _default)
    miss = [n for n, p in reg['types'].items() if p['route'] != AS.strategy(n)]
    ok('route == AS.strategy(тип) у всех: ' + (', '.join(miss) or 'расхождений нет'), not miss)
    alias_miss = [(a, n) for n, p in reg['types'].items() for a in p.get('aliases') or () if AS.strategy(a) != p['route']]
    ok('route совпадает со стратегией каждого алиаса', not alias_miss)
    ok('needs_3d согласован со стратегиями меша', all(p['needs_3d'] == (p['route'] in AS.mesh_strategies()) for p in reg['types'].values()))
    # покрытие ролей: каждая роль канона и фикстуры — паспорт или алиас
    roles = {r for r in AS._load()['roles'] if not r.startswith('_')}
    fx = os.path.join(HERE, 'tests', 'fixtures', 'category-roles-mini.json')
    if os.path.exists(fx):
        def _roles(n):
            if isinstance(n, dict):
                for k, v in n.items():
                    if k == 'role' and isinstance(v, str):
                        yield v
                    else:
                        yield from _roles(v)
            elif isinstance(n, list):
                for v in n:
                    yield from _roles(v)
        roles |= set(_roles(json.load(open(fx, encoding='utf-8'))))
    nop = sorted(r for r in roles if normalize(r, reg) is None)
    ok('каждая роль канона и фикстуры имеет паспорт или алиас' + (f' — нет у: {nop}' if nop else ''), not nop)
    ok('digest стабилен и меняется от порога',
       digest('кровать', reg) == digest('кровать', copy.deepcopy(reg))
       and digest_of({**reg['types']['кровать'], 'sample': {'count': 1}}) == digest('кровать', reg)
       and digest_of({**reg['types']['кровать'], 'route': 'cutout'}) != digest('кровать', reg))
    # ---- схема краснеет на нарушителях
    def mut(f):
        r = copy.deepcopy(reg)
        f(r['types'])
        return validate(r)
    ok('provisional + enforce → ошибка', bool(mut(lambda t: t['комод'].update(mode='enforce'))))
    ok('provisional + сторож → ошибка', bool(mut(lambda t: t['комод']['cutout']['guards'].append(copy.deepcopy(t['подушка']['cutout']['guards'][0])))))
    ok('неизвестный сторож / стадия / флаг цепочки → ошибка',
       bool(mut(lambda t: t['кровать']['cutout']['guards'][0].update(name='x_guard')))
       and bool(mut(lambda t: t['кровать']['cutout']['guards'][0].update(stage='late')))
       and bool(mut(lambda t: t['комод']['cutout'].update(chain_flags=['teleport']))))
    ok('поле-селектор товара (sku/url/sha/product_id) → ошибка',
       all(mut(lambda t, k=k: t['комод'].update({k: 'x'})) for k in ('sku', 'url', 'sha', 'product_name', 'mesh_id')))
    ok('значение-идентификатор (№12, #123, 12:345, 5+ цифр) → ошибка',
       all(mut(lambda t, v=v: t['комод'].setdefault('sample', {}).update(source=v)) for v in ('плитка №12', 'товар #123', '112:3456', 'x 4912345 y')))
    ok('route вне канона / дубль имени → ошибка',
       bool(mut(lambda t: t['комод'].update(route='teleport')))
       and bool(mut(lambda t: t['комод'].update(aliases=['стул']))))
    ok('порог не число / отрицательный → ошибка',
       bool(mut(lambda t: t['кровать']['cutout']['guards'][0]['thresholds'].update(loss_de='2.5')))
       and bool(mut(lambda t: t['кровать']['cutout']['guards'][0]['thresholds'].update(loss_de=-1))))
    # ---- гейт: никогда не бросает, observe всегда «пропустить»
    reset_stats()
    ok('observe: известная роль → pass', gate('диван')[0] == 'pass' and gate('кресло 3')[0] == 'pass')
    ok('observe: роль без паспорта → pass + would_block:no_passport + счёт ролей',
       gate('камин', n=4) == ('pass', 'would_block:no_passport') and NO_PASSPORT['камин'] == 4)
    ok('observe: вердикт К1 → pass + would_block:headboard_loss', gate('кровать', verdict='headboard_loss') == ('pass', 'would_block:headboard_loss'))
    ok('observe: мягкая метка К3 ничего не «блокирует»', gate('подушка', verdict='pattern') == ('pass', 'ok'))
    ok('в строке отчёта есть «заблокировал бы»', 'заблокировал бы' in report_line())
    # битый реестр: невалидный JSON, неверная схема, нет файла → pass + одна WARN-строка, исключения нет
    import io
    import contextlib
    global PATH, _REG
    saved_path, saved_reg = PATH, _REG
    try:
        with tempfile.TemporaryDirectory() as td:
            for label, body in (('невалидный JSON', '{not json'), ('неверная схема', '{"types": {"кровать": {"mode": "x"}}}'), ('нет файла', None)):
                pth = os.path.join(td, 'reg.json')
                if body is not None:
                    open(pth, 'w', encoding='utf-8').write(body)
                elif os.path.exists(pth):
                    os.unlink(pth)
                PATH, _REG = pth if body is not None else os.path.join(td, 'нет.json'), None
                reset_stats()
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        r1, r2, r3 = gate('кровать'), gate('диван'), passport_preflight('шкаф')
                    thrown = False
                except Exception:  # noqa: BLE001
                    thrown = True
                ok(f'битый реестр ({label}): гейт не бросил, всё pass/registry_error, WARN ровно одна',
                   not thrown and r1 == r2 == r3 == ('pass', 'registry_error') and buf.getvalue().count('WARN:passport_registry') == 1)
    finally:
        PATH, _REG = saved_path, saved_reg
        reset_stats()
    print(f'mesh_type_passports selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(_selftest())
    r = load()
    print(f'паспортов {len(r["types"])}, не provisional: {[n for n, p in r["types"].items() if not p["provisional"]]}')
