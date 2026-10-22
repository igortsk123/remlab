#!/usr/bin/env python3
"""СЕЛЕКТОР ГОТОВЫХ ЯЧЕЕК, СМЕШАННЫЙ БАНК И ЭКЗАМЕН ПРОДВИГАЕМЫХ `bank_promote` (conv-14 шаг 3; разборы Codex 22.10:
`_intake/codex/conv-14-bank-auto-2026-10-22-answer.md` § 1–5, `conv-14-step3-readiness-2026-10-22-answer.md` § 4–5).

ЗАЧЕМ. Кандидат `sets3.next.json` (ночной `bank_prepare`) целиком живой банк заменить не может: часть ячеек ждёт мешей или
каталога. Подменять надо ячейку `(band, style, tier, set_id)` ЦЕЛИКОМ — как только она готова, — а итоговый СМЕШАННЫЙ банк
проверять целиком: повторы крупной мебели между сетами, порядок и номера, связи. ЭТОТ ШАГ ТОЛЬКО ОТЧИТЫВАЕТСЯ: строит
временный смешанный банк и manifest продвижения; `sets3.json` пишет лишь атомарный писатель шага 4.

ПОРЯДОК (за флагом `rules/bank-candidate.json:promote_enabled`, по умолчанию выключен — шаг `ok` со строкой «выключено»):
  1. идентичность кандидата против живого (`set_identity.verify`) — фатально: ничего не продвигаем;
  2. ячейка-претендент: состояние ожидания `bank_pending` = `ready` ПО ЭТОМУ ЖЕ кандидату (`candidate_hash`) и строгая чистота
     (`strict`): ушедших 0, ссылок не текущих 0, контракты слотов, пары, запасные живые той же роли, ключевые роли
     (`bank_invariants.core_missing`), зона столовой при свободном регионе (правило `compose2` Z4 — `dining_gap`), итог
     `total` = сумма позиций; совпадает с живой — продвигать нечего;
  3. порядок — `bank-candidate.json:priority` (замена ушедшего → ячейка демо → дольше ждёт); предел `max_promote_share`
     (env `BANK_MAX_PROMOTE_SHARE`, 25 % ячеек за ночь — свой, не `heal_policy`);
  4. вставка в смешанный банк по одной, на своё место (номер массива и set_id не меняются — демо публикует `setN`,
     `flat215_demo.py:1004-1010`): связка ≥2 одинаковых крупных предметов с любым другим сетом (`compose2.MAJOR_ROLES`,
     правило `overlap_ok`) и НОВОЕ нарушение ценового порядка тиров в (band, style) — ячейка не идёт; остановленные этим
     проходят повторно, когда сосед продвинут в ту же ночь (тиры сдвигаются вместе: прогон 22.10 — премиум → комфорт → эконом);
  5. экзамен: сцены продвигаемых сетов (`acceptance-scenes.json` → `ACC_MANIFEST`), старый банк против смешанного, движок
     из правил (zoned); новый hard / не размещено больше / TIMEOUT / сбой — ячейка не идёт, остальные идут; после отката
     провалившихся связки и тиры перепроверяются;
  6. нетронутые ячейки — «не хуже прежнего»: ровно как в живом банке, плюс явный `bank_status` у сетов с ушедшим товаром:
     `hidden` — ушёл товар ключевой роли (вариант без него не пройдёт рубеж публикации ядра), иначе `degraded`
     (демо снимет позицию и дозаполнит, `flat215_demo.drop_unavailable` / `demo_fill`);
  7. смешанный банк → `<рабочая папка>/hybrid.json` (`set_identity.write_bank`), manifest → `~/scout-scenes/bank-promote.json`
     (ячейка, set_id, candidate_hash, решение и причины, итог экзамена).

  ~/venvs/scout/bin/python bank_promote.py                      # ночной шаг (флаг из правил)
  ~/venvs/scout/bin/python bank_promote.py --force [--no-exam] [--force-ready 5,17,40]   # ручной прогон
  env BANK_CANDIDATE, BANK_PENDING, BANK_PROMOTE (manifest), BANK_PROMOTE_DIR (рабочая папка), BANK_MAX_PROMOTE_SHARE
  python3 bank_promote.py --selftest
"""
import ast
import copy
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bank_invariants as BI  # noqa: E402
import bank_pending as BP  # noqa: E402
import set_identity as SID  # noqa: E402

RULES_PATH = os.path.join(HERE, 'rules', 'bank-candidate.json')
LIVE = os.path.join(HERE, 'sets3.json')
CANDIDATE = os.path.abspath(os.environ.get('BANK_CANDIDATE') or os.path.join(HERE, 'sets3.next.json'))
MANIFEST = os.path.expanduser(os.environ.get('BANK_PROMOTE', '~/scout-scenes/bank-promote.json'))
WORK = os.path.expanduser(os.environ.get('BANK_PROMOTE_DIR', '~/scout-scenes/bank-promote'))
ZONES = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules', 'zones.json')
SCENES = os.path.join(HERE, 'acceptance-scenes.json')
TIERS = ('эконом', 'комфорт', 'премиум')


def rules() -> dict:
    try:
        return json.load(open(RULES_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _compose_const(name: str) -> set:
    """Константа сборщика разбором исходника: импорт `compose2` исполняет полную сборку (урок: import-ловушка scout)."""
    src = open(os.path.join(HERE, 'compose2.py'), encoding='utf-8').read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise KeyError(f'compose2.py: нет {name}')


def sku(it) -> str | None:
    return BI.sku(it)


def majors(s: dict, major: set) -> set:
    return {sku(it) for r, it in (s.get('items') or {}).items() if r in major and sku(it)}


def total_of(s: dict) -> int:
    """Итог сета так, как его считает сборщик: запасные позиции (`alt` — alt-кресло, банкетка) в сумму не входят
    (`compose2.py`: `total` считается до добавления alt; проверено на кандидате 22.10 — расхождений 0 из 126)."""
    return round(sum((it.get('price') or 0) * int(it.get('qty') or 1) for it in (s.get('items') or {}).values()
                     if it and not it.get('alt')))


def _seats(m2: float) -> str:
    # то же правило мест, что у сборщика (`compose2.py` Z4: «Свод №7 — регион по числу мест»)
    return '6' if m2 >= 40 else ('4' if m2 >= 22 else '2')


def dining_gap(s: dict, groups: dict, region: dict) -> str | None:
    """Зона столовой: регион свободен (usable − площадь посадочной группы ≥ региону по числу мест, `zones.json`) — значит
    сборщик обязан был поставить обеденный стол (`compose2.py` Z4); нет стола и нет объявленного пробела — дефект ячейки."""
    um, g = s.get('usable_m2'), groups.get(s.get('group'))
    if um is None or g is None or 'стол обеденный' in (s.get('items') or {}):
        return None
    need = float(region.get(_seats(float(s.get('m2') or 0)), 6.0))
    if float(um) - float(g.get('footprint_m2') or 0) < need:
        return None
    declared = any('стол обеденный' in str(x) for x in (s.get('gaps') or []))
    return f"нет обеденного стола при свободном регионе {float(um) - float(g['footprint_m2']):.1f} ≥ {need} м²" + \
        (' (пробел объявлен)' if declared else ' (пробел не объявлен)')


def strict(s: dict, media, slot_ok, sync_pairs, fits, groups: dict, region: dict, dining: bool = True) -> list[str]:
    """Строгая чистота продвигаемой ячейки → причины отказа (пусто — чиста)."""
    r = BI.check([s], None, media, slot_ok, sync_pairs, fits, cells=1)
    out = [f'{name} {r[k]}' for k, name in (('gone', 'ушедших'), ('url_stale', 'ссылок не текущих'),
                                            ('contracts', 'вне контракта'), ('pair_mismatch', 'пар разошлось'),
                                            ('alt_bad', 'запасных негодных')) if r.get(k)]
    if r.get('core_missing'):
        out.append('без ключевых ролей: ' + ', '.join(r['core_missing']))
    if s.get('total') is not None and abs(total_of(s) - float(s['total'])) > 1:
        out.append(f"итог {s['total']} ≠ сумме позиций {total_of(s)}")
    gap = dining_gap(s, groups, region) if dining else None
    if gap:
        out.append(gap)
    return out


def tier_bad(sets: list, n: int) -> set:
    """Нарушения ценового порядка тиров с участием сета №n (0-based): в той же (band, style) итог младшего тира > старшего."""
    s = sets[n]
    out = set()
    if s.get('tier') not in TIERS:
        return out
    for m, o in enumerate(sets):
        if m == n or (o.get('band'), o.get('style')) != (s.get('band'), s.get('style')) or o.get('tier') not in TIERS:
            continue
        lo, hi = sorted((s, o), key=lambda x: TIERS.index(x['tier']))
        if total_of(lo) > total_of(hi):
            out.add((lo['tier'], hi['tier']))
    return out


def links_bad(sets: list, n: int, major: set) -> list[str]:
    """Связка крупной мебели (≥2 одинаковых крупных SKU) сета №n с любым другим — правило разнообразия `compose2.overlap_ok`."""
    mine = majors(sets[n], major)
    return [f'связка с сетом {m + 1} ({len(mine & majors(o, major))} общих крупных)'
            for m, o in enumerate(sets) if m != n and len(mine & majors(o, major)) >= 2]


def gone_roles(s: dict, media) -> list[tuple]:
    out = []
    for role, it in (s.get('items') or {}).items():
        if it and it.get('eid'):
            m = media(it.get('mid'), it.get('eid'))
            if not m or m.get('state') == 'gone':
                out.append((role, sku(it)))
    return out


def live_status(s: dict, gone: list) -> dict | None:
    """Статус живого сета с ушедшим товаром. `hidden` — ушёл товар ключевой роли (без него вариант не пройдёт рубеж ядра
    публикации — смысла показывать нет), иначе `degraded` (демо снимет позицию и дозаполнит). Предложение правила — шаг 3."""
    if not gone:
        return None
    rest = {**s, 'items': {r: it for r, it in (s.get('items') or {}).items() if r not in {g[0] for g in gone}}}
    lost = sorted(set(BI.core_missing(rest)) - set(BI.core_missing(s)))
    return {'state': 'hidden' if lost else 'degraded', 'gone': [list(g) for g in gone], 'core_lost': lost}


def _strip(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != 'bank_status'}


def _fail_kinds(rec: dict) -> set:
    return {(re.match(r'FAIL\s*[:\-]?\s*(\S+)', f) or [None, f])[1] for f in (rec or {}).get('fails') or []}


def exam_verdict(old: dict, new: dict, ids: list) -> tuple[bool, list]:
    """Сцены сета: старый банк против смешанного. Новый hard-провал, TIMEOUT, сбой или больше неразмещённых — провал."""
    why = []
    if not ids:
        return False, ['нет сцен экзамена']
    for i in ids:
        o, nw = old.get(i) or {}, new.get(i)
        if nw is None:
            why.append(f'{i}: не посчитана')
            continue
        if nw.get('rc'):
            why.append(f"{i}: сбой солвера rc={nw['rc']}")
        add = _fail_kinds(nw) - _fail_kinds(o)
        if 'TIMEOUT' in add:
            why.append(f'{i}: TIMEOUT')
            add.discard('TIMEOUT')
        if add:
            why.append(f'{i}: новый hard {sorted(add)}')
        if len(nw.get('missing') or []) > len(o.get('missing') or []):
            why.append(f"{i}: не размещено {len(nw.get('missing') or [])} (было {len(o.get('missing') or [])})")
    return not why, why


def plan(live: list, cand: list, state: dict, R: dict, *, strict_fn, media, gone_cells: set, demo_cells: set,
         major: set, exam_fn=None, force_ready: set = frozenset()) -> dict:
    """Чистое ядро: → {'fatal', 'hybrid', 'rows', 'promoted', 'cap', 'status', 'exam'}. Живой банк не меняется."""
    ident = SID.verify(cand, live, cells=len(live))
    if ident:
        return {'fatal': 'идентичность кандидата против живого: ' + '; '.join(ident), 'hybrid': None, 'rows': [],
                'promoted': [], 'cap': 0, 'status': {}, 'exam': None}
    share = float(os.environ.get('BANK_MAX_PROMOTE_SHARE') or R.get('max_promote_share', 0.25))
    cap = math.floor(share * len(live))
    cells = (state or {}).get('cells') or {}
    rows, elig = {}, []
    for n, (L, C) in enumerate(zip(live, cand)):
        k, h = BP.key(C), BP.candidate_hash(C)
        st = cells.get(k) or {}
        row = rows[n] = {'n': n + 1, 'cell': k, 'set_id': C.get('set_id'), 'candidate_hash': h, 'decision': 'wait',
                         'reasons': [], 'since': st.get('since')}
        if _strip(C) == _strip(L):
            row.update(decision='same', reasons=['кандидат совпадает с живым'])
            continue
        if n + 1 in force_ready:
            row['forced_ready'] = True
        elif not st:
            row['reasons'].append('нет состояния ожидания')
        elif st.get('candidate_hash') != h:
            row['reasons'].append('ожидание посчитано по другому кандидату')
        elif st.get('status') != 'ready':
            row['reasons'].append(f"не готова: {st.get('status')} (не хватает {len(st.get('missing') or {})})")
        bad = strict_fn(C)
        if bad:
            row['decision'] = 'blocked'
            row['reasons'] += bad
        if not row['reasons']:
            elig.append(n)
    elig.sort(key=lambda n: (rows[n]['cell'] not in gone_cells, rows[n]['cell'] not in demo_cells,
                             rows[n]['since'] or 0, n))
    hybrid = copy.deepcopy(live)
    for s in hybrid:
        s.pop('bank_status', None)
    base = copy.deepcopy(hybrid)

    def admit(n: int) -> list[str]:
        trial = hybrid[:n] + [cand[n]] + hybrid[n + 1:]
        why = links_bad(trial, n, major)
        new_tier = tier_bad(trial, n) - tier_bad(base, n)
        if new_tier:
            why.append('ценовой порядок тиров: ' + ', '.join(f'{a} дороже {b}' for a, b in sorted(new_tier)))
        return why

    promoted, todo = [], list(elig)
    # ПОВТОРНЫЕ ПРОХОДЫ: ячейка, которую остановили связка или тиры с ЖИВЫМ соседом, проходит, когда сосед продвинут в эту
    # же ночь (тиры одной (band, style) часто сдвигаются вместе: премиум → комфорт → эконом) — иначе ушло бы три ночи
    first = True
    while todo:
        later = []
        for n in todo:
            if len(promoted) >= cap and not first:
                break                                  # повторный проход упёрся в предел — остаётся прежняя причина
            if len(promoted) >= cap:
                rows[n].update(decision='deferred', reasons=[f'предел {cap} ячеек за ночь ({share:.0%}) — следующей ночью'])
                continue
            why = admit(n)
            if why:
                rows[n].update(decision='blocked', reasons=why)
                later.append(n)
                continue
            hybrid[n] = copy.deepcopy(cand[n])
            promoted.append(n)
        todo, first = (later if len(later) < len(todo) else []), False
    exam = None
    if promoted and exam_fn is not None:
        exam = exam_fn(hybrid, promoted)
        if exam.get('error'):
            for n in promoted:
                rows[n].update(decision='blocked', reasons=[f"экзамен не прошёл целиком: {exam['error']}"])
                hybrid[n] = copy.deepcopy(base[n])
            promoted = []
        else:
            for n in list(promoted):
                v = exam['cells'].get(n + 1) or {'ok': False, 'why': ['нет итога экзамена']}
                rows[n]['exam'] = v
                if not v['ok']:
                    rows[n].update(decision='blocked', reasons=['экзамен: ' + '; '.join(v['why'][:6])])
                    hybrid[n] = copy.deepcopy(base[n])
                    promoted.remove(n)
            # откат провалившихся мог вернуть живые сеты, с которыми продвигаемый образует связку / нарушает тиры
            changed = True
            while changed:
                changed = False
                for n in list(promoted):
                    hybrid[n] = copy.deepcopy(base[n])
                    why = admit(n)
                    hybrid[n] = copy.deepcopy(cand[n])
                    if why:
                        rows[n].update(decision='blocked', reasons=['после отката соседа: ' + '; '.join(why)])
                        hybrid[n] = copy.deepcopy(base[n])
                        promoted.remove(n)
                        changed = True
    for n in promoted:
        rows[n]['decision'] = 'promote'
        rows[n]['reasons'] = ['готова, чиста, экзамен пройден' if exam_fn else 'готова и чиста (без экзамена)']
    status = {}
    for n, s in enumerate(hybrid):
        if n in promoted:
            continue
        st = live_status(s, gone_roles(s, media))
        if st:
            s['bank_status'] = st
            status[n + 1] = st
    fatal = None
    left = SID.verify(hybrid, live, cells=len(live))
    if left:
        fatal = 'смешанный банк: ' + '; '.join(left)
    worse = [n + 1 for n in range(len(live)) if n not in promoted and _strip(hybrid[n]) != _strip(base[n])]
    if worse:
        fatal = f'нетронутые ячейки изменились: {worse[:5]}'
    return {'fatal': fatal, 'hybrid': hybrid, 'rows': [rows[n] for n in sorted(rows)], 'promoted': [n + 1 for n in promoted],
            'cap': cap, 'status': status, 'exam': exam}


# ——— ввод-вывод ———

def _scene_ids(ns: list) -> dict:
    S = json.load(open(SCENES, encoding='utf-8'))
    return {n: [sc['id'] for sc in S if sc.get('set') == n] for n in ns}


def make_exam(live_path: str, R: dict, work: str):
    """Экзамен по сценам продвигаемых: два прогона `acceptance_run.py` (копия живого / смешанный) на одном подмножестве."""
    engine = R.get('promote_exam_engine') or 'zoned'
    timeout = int(R.get('promote_exam_timeout_min') or 90) * 60

    def exam(hybrid: list, promoted: list) -> dict:
        ns = [n + 1 for n in promoted]
        by = _scene_ids(ns)
        ids = [i for n in ns for i in by[n]]
        t0 = time.time()
        hpath = os.path.join(work, 'hybrid.exam.json')
        SID.write_bank(hybrid, hpath, LIVE)
        man = os.path.join(work, 'exam-scenes.json')
        json.dump(ids, open(man, 'w', encoding='utf-8'), ensure_ascii=False)
        recs = {}
        for side, bank in (('old', live_path), ('new', hpath)):
            sfx = f'-promote-{side}'
            jl = os.path.join(HERE, f'acceptance-report-{engine}{sfx}.jsonl')
            if os.path.exists(jl):
                os.replace(jl, jl + '.prev')    # иначе прошлые строки считались бы уже готовыми сценами
            env = {**os.environ, 'SETS_BANK': bank, 'ACC_MANIFEST': man, 'ACC_REPORT_SUFFIX': sfx}
            try:
                p = subprocess.run([sys.executable, os.path.join(HERE, 'acceptance_run.py'), engine], cwd=HERE, env=env,
                                   capture_output=True, text=True, timeout=max(60, timeout // 2))
            except subprocess.TimeoutExpired:
                return {'error': f'{side}: не уложился в {timeout // 120} мин', 'scenes': len(ids)}
            if p.returncode:
                return {'error': f'{side}: rc={p.returncode} {(p.stderr or "").strip()[-200:]}', 'scenes': len(ids)}
            rep = json.load(open(os.path.join(HERE, f'acceptance-report-{engine}{sfx}.json'), encoding='utf-8'))
            recs[side] = {r['scene']: r for r in rep}
        cells = {}
        for n in ns:
            ok, why = exam_verdict(recs['old'], recs['new'], by[n])
            cells[n] = {'ok': ok, 'why': why, 'scenes': by[n],
                        'new_ok': sum(1 for i in by[n] if (recs['new'].get(i) or {}).get('ok')),
                        'old_ok': sum(1 for i in by[n] if (recs['old'].get(i) or {}).get('ok'))}
        return {'engine': engine, 'scenes': len(ids), 'seconds': round(time.time() - t0), 'cells': cells}
    return exam


def _save(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def run(force: bool = False, no_exam: bool = False, force_ready: set = frozenset()) -> int:
    R = rules()
    if not (R.get('promote_enabled') or force):
        print('bank_promote: выключено (rules/bank-candidate.json:promote_enabled=false) — ячейки не судятся', flush=True)
        return 0
    if os.path.realpath(CANDIDATE) == os.path.realpath(LIVE):
        print('ERROR:bank_promote: кандидат — это живой банк', flush=True)
        return 2
    import collections
    import sets_incremental as SI
    from catalog_media import media
    from item_function import fits_role
    t0 = time.time()
    live = json.load(open(LIVE, encoding='utf-8'))
    try:
        cand = json.load(open(CANDIDATE, encoding='utf-8'))
    except FileNotFoundError:
        print(f'WARN:bank_promote: кандидата {CANDIDATE} нет — судить нечего (bank_prepare не собрал?)', flush=True)
        return 0
    z = json.load(open(ZONES, encoding='utf-8'))
    groups = {g['id']: g for g in z.get('seating_groups') or []}
    region = (z.get('dining_region_m2') or {}).get('by_seats') or {'2': 3.0, '4': 6.0, '6': 8.0}
    gone_cells, demo_cells = BP.live_context(live)
    gone_cells |= {BP.key(s) for s in live if gone_roles(s, media)}
    os.makedirs(WORK, exist_ok=True)
    live_copy = os.path.join(WORK, 'live.exam.json')
    _save(live_copy, live)
    exam = None if (no_exam or R.get('promote_exam') is False) else make_exam(live_copy, R, WORK)
    res = plan(live, cand, BP.load_state(), R, media=media, gone_cells=gone_cells, demo_cells=demo_cells,
               major=_compose_const('MAJOR_ROLES'), exam_fn=exam, force_ready=force_ready,
               strict_fn=lambda s: strict(s, media, SI._slot_ok, SI.sync_pairs, fits_role, groups, region,
                                          R.get('promote_dining_check', True)))
    dec = collections.Counter(r['decision'] for r in res['rows'])
    why = collections.Counter(re.sub(r'\d+', 'N', x.split(':')[0]) for r in res['rows'] if r['decision'] in ('wait', 'blocked')
                              for x in r['reasons'])
    stc = collections.Counter(s['state'] for s in res['status'].values())
    man = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'report_only': True, 'live': LIVE, 'candidate': CANDIDATE,
           'hybrid': None, 'cap': res['cap'], 'promoted': res['promoted'], 'decisions': dict(dec), 'fatal': res['fatal'],
           'exam': {k: v for k, v in (res['exam'] or {}).items() if k != 'cells'} or None,
           'live_status': res['status'], 'cells': res['rows'], 'forced_ready': sorted(force_ready)}
    rc = 0
    if res['fatal']:
        print(f"ERROR:bank_promote: {res['fatal']} — ничего не продвигаем", flush=True)
        rc = 1
    elif res['hybrid'] is not None:
        hp = os.path.join(WORK, 'hybrid.json')
        SID.write_bank(res['hybrid'], hp, LIVE)
        man['hybrid'] = hp
    if (res['exam'] or {}).get('error'):
        print(f"ERROR:bank_promote: экзамен — {res['exam']['error']}; продвигаемых нет (fail-closed)", flush=True)
        rc = 1
    man['seconds'] = round(time.time() - t0)
    _save(MANIFEST, man)
    print(f"bank_promote (только отчёт): ячеек {len(cand)} — продвигается {len(res['promoted'])} {res['promoted'][:12]} "
          f"(предел {res['cap']}), " + ', '.join(f'{k} {v}' for k, v in sorted(dec.items())), flush=True)
    print('  почему нет: ' + '; '.join(f'{w} — {n}' for w, n in why.most_common(8)), flush=True)
    print(f"  живые с ушедшим товаром: {dict(stc) or 0}; экзамен: "
          + (f"{res['exam'].get('scenes')} сцен за {res['exam'].get('seconds')} с" if res['exam'] and 'cells' in res['exam']
             else 'не запускался' if not res['exam'] else 'ошибка'), flush=True)
    print(f"[bank_promote] manifest → {MANIFEST}" + (f"; смешанный банк → {man['hybrid']}" if man['hybrid'] else ''), flush=True)
    return rc


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    MAJ = {'диван', 'кресло', 'столик', 'тв-тумба'}
    cat = {}

    def it(e, price=1000, **k):
        cat[('1', e)] = cat.get(('1', e)) or {'state': 'available', 'url': f'u{e}'}
        return {'mid': 1, 'eid': e, 'url': f'u{e}', 'price': price, 'qty': 1, **k}
    media = lambda mid, eid: cat.get((str(mid), str(eid)))  # noqa: E731

    def S(n, band, style, tier, items):
        s = {'band': band, 'style': style, 'tier': tier, 'set_id': f'id{n}', 'm2': 15, 'items': items, 'alternates': {}}
        s['total'] = total_of(s)
        return s
    styles = ('сканди', 'лофт', 'джапанди', 'минимализм')
    live = [S(i, b, st, t, {'диван': it(f'd{i}', 1000 * (ti + 1)), 'столик': it(f't{i}'), 'тв-тумба': it(f'v{i}')})
            for i, (b, st, (ti, t)) in enumerate(((b, st, tt) for b in ('14-16', '17-20') for st in styles
                                                   for tt in enumerate(TIERS)), 1)]
    N = len(live)   # 24
    cand = copy.deepcopy(live)
    for i in range(N):
        cand[i]['items']['диван'] = it(f'D{i}', 1000 * (TIERS.index(cand[i]['tier']) + 1))
        cand[i]['total'] = total_of(cand[i])
    state = {'cells': {BP.key(c): {'candidate_hash': BP.candidate_hash(c), 'status': 'ready', 'since': i, 'missing': {}}
                       for i, c in enumerate(cand)}}
    ok_strict = lambda s: []  # noqa: E731

    def go(c=None, st=None, R=None, exam=None, gone=frozenset(), demo=frozenset(), fr=frozenset(), lv=None):
        return plan(lv or live, c or cand, state if st is None else st, R or {'max_promote_share': 0.25}, strict_fn=ok_strict,
                    media=media, gone_cells=set(gone), demo_cells=set(demo), major=MAJ, exam_fn=exam, force_ready=set(fr))
    r = go()
    ok('предел доли: 25 % от 24 = 6 ячеек, остальные «следующей ночью»',
       len(r['promoted']) == 6 and sum(1 for x in r['rows'] if x['decision'] == 'deferred') == 18, (r['promoted'], r['cap']))
    ok('неизменность номеров и set_id в смешанном банке', [s['set_id'] for s in r['hybrid']] == [s['set_id'] for s in live]
       and [SID.cell(s) for s in r['hybrid']] == [SID.cell(s) for s in live] and r['fatal'] is None)
    ok('продвинутая ячейка — целиком из кандидата, нетронутая — как в живом',
       r['hybrid'][r['promoted'][0] - 1] == cand[r['promoted'][0] - 1] and r['hybrid'][N - 1] == live[N - 1])
    k5 = BP.key(cand[20])
    r = go(gone={k5})
    ok('приоритет: замена ушедшего первой', r['promoted'][0] == 21, r['promoted'])
    st2 = copy.deepcopy(state)
    st2['cells'][BP.key(cand[0])]['status'] = 'wait_asset'
    st2['cells'][BP.key(cand[1])]['candidate_hash'] = 'старый'
    r = go(st=st2)
    ok('не готова / ожидание по другому кандидату — не продвигается',
       r['rows'][0]['decision'] == 'wait' and 'не готова' in r['rows'][0]['reasons'][0]
       and 'другому кандидату' in r['rows'][1]['reasons'][0] and 1 not in r['promoted'] and 2 not in r['promoted'])
    r = go(st=st2, fr={1})
    ok('--force-ready снимает только ожидание (синтетика), строгая чистота остаётся', 1 in r['promoted'] and r['rows'][0].get('forced_ready'))
    c3 = copy.deepcopy(cand)
    c3[0]['items']['кресло'] = it('K', 1)
    c3[0]['items']['столик'] = live[5]['items']['столик']
    c3[5]['items']['кресло'] = it('K', 1)
    for c in (c3[0], c3[5]):
        c['total'] = total_of(c)
    st3 = {'cells': {BP.key(c): {'candidate_hash': BP.candidate_hash(c), 'status': 'ready', 'since': i}
                     for i, c in enumerate(c3)}}
    r = go(c=c3, st=st3)
    blk = [x for x in (r['rows'][0], r['rows'][5]) if x['decision'] == 'blocked' and 'связка' in x['reasons'][0]]
    ok('связка: 2 общих крупных с уже продвинутым сетом — вторая ячейка не идёт (повтор compose2), первая идёт',
       len(blk) == 1 and (1 in r['promoted']) != (6 in r['promoted']), (r['rows'][0], r['rows'][5]))
    c4 = copy.deepcopy(cand)
    c4[0]['items']['диван'] = it('DX', 99000)
    c4[0]['total'] = total_of(c4[0])
    st4 = {'cells': {BP.key(c): {'candidate_hash': BP.candidate_hash(c), 'status': 'ready', 'since': i}
                     for i, c in enumerate(c4)}}
    r = go(c=c4, st=st4)
    ok('ценовой порядок: эконом дороже комфорта — новое нарушение, не идёт',
       r['rows'][0]['decision'] == 'blocked' and 'тиров' in r['rows'][0]['reasons'][0], r['rows'][0])

    c6 = copy.deepcopy(cand)
    for i, price in ((0, 5000), (1, 6000), (2, 7000)):          # одна (band, style): все три тира дорожают вместе
        c6[i]['items']['диван'] = it(f'P{i}', price)
        c6[i]['total'] = total_of(c6[i])
    st6 = {'cells': {BP.key(c): {'candidate_hash': BP.candidate_hash(c), 'status': 'ready', 'since': i}
                     for i, c in enumerate(c6)}}
    r = go(c=c6, st=st6, R={'max_promote_share': 1.0})
    ok('тиры сдвигаются вместе: эконом и комфорт ждут премиум в ту же ночь, все три продвинуты',
       {1, 2, 3} <= set(r['promoted']), (r['promoted'], r['rows'][0]['reasons']))

    def exam_one_fails(hybrid, promoted):
        return {'cells': {n + 1: {'ok': n != promoted[1], 'why': [] if n != promoted[1] else ['s: новый hard [collision]']}
                          for n in promoted}, 'scenes': 3}
    r = go(exam=exam_one_fails)
    first = go()['promoted']
    ok('экзамен: провал одной ячейки — она не идёт, остальные идут, её место — живой сет',
       len(r['promoted']) == 5 and first[1] not in r['promoted'] and r['hybrid'][first[1] - 1] == live[first[1] - 1]
       and 'экзамен' in r['rows'][first[1] - 1]['reasons'][0], (r['promoted'], first))
    r = go(exam=lambda h, p: {'error': 'rc=1'})
    ok('экзамен упал целиком — fail-closed: ничего не продвигается', r['promoted'] == [] and r['hybrid'] == live)
    lv = copy.deepcopy(live)
    lv[10]['items']['столик'] = it('gone1')
    lv[11]['items']['торшер'] = it('gone2')
    lv[12]['bank_status'] = {'state': 'hidden'}     # прежний статус — пересчитывается каждую ночь
    cat[('1', 'gone1')] = {'state': 'gone'}
    cat[('1', 'gone2')] = None
    r = go(lv=lv, R={'max_promote_share': 0})
    ok('hybrid с прежними degraded: ушёл столик — hidden, ушёл торшер — degraded, остальные без статуса',
       r['status'].get(11, {}).get('state') == 'hidden' and r['status'].get(12, {}).get('state') == 'degraded'
       and 13 not in r['status'] and 'bank_status' not in r['hybrid'][12] and r['fatal'] is None, r['status'])
    c5 = copy.deepcopy(cand)
    c5[3]['set_id'] = 'чужой'
    ok('идентичность кандидата нарушена — фатально, ничего', go(c=c5)['fatal'] and go(c=c5)['promoted'] == [])
    same = copy.deepcopy(live)
    ok('кандидат = живой — «same», продвигать нечего', all(x['decision'] == 'same' for x in go(c=same)['rows']))
    ok('экзамен: новый hard / больше неразмещённых / TIMEOUT — провал; прежний провал — не хуже',
       not exam_verdict({'a': {'fails': []}}, {'a': {'fails': ['FAIL collision: x']}}, ['a'])[0]
       and not exam_verdict({'a': {'missing': []}}, {'a': {'missing': ['кресло'], 'fails': []}}, ['a'])[0]
       and not exam_verdict({}, {'a': {'fails': ['TIMEOUT']}}, ['a'])[0]
       and exam_verdict({'a': {'fails': ['FAIL wall: y']}}, {'a': {'fails': ['FAIL wall: z']}}, ['a'])[0]
       and not exam_verdict({}, {}, [])[0])
    g = {'sofa_armchair': {'footprint_m2': 8.4}}
    s = {'m2': 15, 'usable_m2': 12.9, 'group': 'sofa_armchair', 'items': {}, 'gaps': []}
    ok('итог без запасных (alt) — как у сборщика', total_of({'items': {'a': {'price': 10, 'qty': 2}, 'b': {'price': 5, 'alt': True}}}) == 20)
    ok('зона столовой: регион 4.5 ≥ 3 м² и нет стола — дефект; регион мал или стол есть — нет',
       dining_gap(s, g, {'2': 3.0}) and dining_gap({**s, 'usable_m2': 10}, g, {'2': 3.0}) is None
       and dining_gap({**s, 'items': {'стол обеденный': {}}}, g, {'2': 3.0}) is None)
    ok('константа сборщика разбором исходника: MAJOR_ROLES', 'диван' in _compose_const('MAJOR_ROLES'))
    print(f'bank_promote selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    fr = set()
    if '--force-ready' in sys.argv:
        fr = {int(x) for x in sys.argv[sys.argv.index('--force-ready') + 1].split(',') if x.strip()}
    sys.exit(run('--force' in sys.argv, '--no-exam' in sys.argv, fr))
