#!/usr/bin/env python3
"""Q6a свода №13 (MASTER-zones-v7): capability-проекция каталога — таблица `product_capabilities`.

Что это: детерминированная проекция params фида + габаритов + (актуального) обогащения через
правила `rules/capabilities.json` в способности SKU ПОВЕРХ `cat_role` (роль не меняется):
seat_* (отдельно от overall_*), wall_seat_capable (банкетка/кушетка — планировочный слот
«банкетка»), dining_seat_capable, nominal/guaranteed_seats, shallow_storage_capable /
behind_sofa_console_capable (Q6e), extension_mechanism_present (sleeping).

Каждый атрибут — с evidence {value, state, source, path, raw, confidence, rule_id};
state ∈ known|inferred|unknown|conflict; false = ДОКАЗАННОЕ несоответствие, «нет данных» = unknown
(Codex 17.08: fail-closed — capability не выводится из одних габаритов; категория/подтип обязательны).

Хранение: PK (shop_mid, external_id), schema_version, rules_hash, input_hash; computed_at меняется
только при изменившемся результате (дельта). Пересчёт: после load3 и в enrich_wait после забора
батча (обогащение асинхронно); payload с enrichment_version IS NULL не читаем (сброшен load3).

Запуск: `capabilities.py --build` (пересчёт), `--report` (unknown-rate по магазинам, счётчики),
`--export` (capabilities-index.json для композитора: planning_role → SKU + caps_used).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, 'rules', 'capabilities.json')
INDEX_OUT = os.path.join(HERE, 'capabilities-index.json')
SCHEMA_VERSION = 1
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

DDL = """
create table if not exists product_capabilities (
  shop_mid int not null, external_id text not null,
  source_role text, planning_roles jsonb not null default '[]'::jsonb,
  caps jsonb not null, evidence jsonb not null,
  schema_version int not null, rules_version text not null, rules_hash text not null,
  input_hash text not null, computed_at timestamptz not null default now(),
  primary key (shop_mid, external_id));
create index if not exists pc_planning_roles_gin on product_capabilities using gin (planning_roles);
create index if not exists pc_wall_seat on product_capabilities ((caps->'wall_seat_capable'->>'value'))
  where (caps->'wall_seat_capable'->>'value')='true';
create index if not exists pc_shallow on product_capabilities ((caps->'shallow_storage_capable'->>'value'))
  where (caps->'shallow_storage_capable'->>'value')='true';
"""


def rules() -> dict:
    return json.load(open(RULES_PATH, encoding='utf-8'))


def _rules_hash() -> str:
    return hashlib.sha1(open(RULES_PATH, 'rb').read()).hexdigest()[:12]


def _rows(q: str, inp: str | None = None) -> list[list[str]]:
    r = subprocess.run(PSQL, input=(inp if inp is not None else q), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:600], file=sys.stderr)
        raise SystemExit(1)
    return [l.split('\x1f') for l in r.stdout.strip().split('\n') if l]


# ---------------------------------------------------------------- evidence helpers
def ev(value, state: str, source: str, rule_id: str, path: str | None = None, raw=None,
       confidence: str = 'high', depends_on: list[str] | None = None, reason: str | None = None) -> dict:
    d = {'value': value, 'state': state, 'source': source, 'rule_id': rule_id, 'confidence': confidence}
    if path:
        d['path'] = path
    if raw is not None:
        d['raw'] = raw
    if depends_on:
        d['depends_on'] = depends_on
    if reason:
        d['reason'] = reason
    return d


UNKNOWN = lambda rule_id, reason='no_data': ev(None, 'unknown', 'none', rule_id, confidence='low', reason=reason)

_NUM = re.compile(r'(\d+(?:[.,]\d+)?)')


def _param_num(params: dict, keys: list[str]) -> tuple[float | None, str | None, str | None]:
    for k in keys:
        if k in params and params[k] not in (None, ''):
            m = _NUM.search(str(params[k]))
            if m:
                return float(m.group(1).replace(',', '.')), k, str(params[k])
    return None, None, None


def _param_text(params: dict, keys: list[str]) -> tuple[str | None, str | None]:
    for k in keys:
        if k in params and params[k] not in (None, ''):
            return str(params[k]), k
    return None, None


# ---------------------------------------------------------------- core projection
def project(row: dict, R: dict) -> tuple[dict, dict, list[str]]:
    """row: {shop_mid, external_id, cat_role, category_path, name, w, d, h, params(dict), enr(dict|None)}
    → (caps, evidence, planning_roles). caps[k] = evidence-dict (value внутри)."""
    P = row.get('params') or {}
    E = row.get('enr') or {}
    spec = (E.get('specific') or {}) if isinstance(E, dict) else {}
    name = (row.get('name') or '').lower()
    cat = (row.get('category_path') or '')
    role = row.get('cat_role') or ''
    w, d, h = row.get('w'), row.get('d'), row.get('h')
    caps: dict = {}
    PK = R['params_keys']

    # overall_* — как есть (footprint), не эргономика
    caps['overall_w_cm'] = ev(w, 'known' if w else 'unknown', 'products.w_cm', 'overall-v1')
    caps['overall_d_cm'] = ev(d, 'known' if d else 'unknown', 'products.d_cm', 'overall-v1')
    caps['overall_h_cm'] = ev(h, 'known' if h else 'unknown', 'products.h_cm', 'overall-v1')

    # seat_* — ТОЛЬКО точные params; для backless (банкетка) — inferred от габаритов (medium)
    for key in ('seat_length_cm', 'seat_depth_cm', 'seat_height_cm'):
        v, k, raw = _param_num(P, PK[key])
        caps[key] = ev(v, 'known', 'params', f'{key.split("_")[1]}-param-v1', path=f'params.{k}', raw=raw) \
            if v is not None else UNKNOWN(f'{key.split("_")[1]}-param-v1')
    if isinstance(spec.get('seat_height'), str):
        caps['seat_height_class'] = ev(spec['seat_height'], 'known', 'enrichment', 'seat-height-class-v1',
                                       path='payload.specific.seat_height', confidence='medium')

    # has_arms / back — params доказывают и наличие, и отсутствие; enrichment — только наличие
    at, ak = _param_text(P, PK['has_arms'])
    if at:
        caps['has_arms'] = ev(not at.lower().startswith('без'), 'known', 'params', 'arms-param-v1', path=f'params.{ak}', raw=at)
    elif isinstance(spec.get('arms'), str):
        caps['has_arms'] = ev(spec['arms'] not in ('нет', 'без', 'не_видно'), 'inferred', 'enrichment', 'arms-enrich-v1',
                              path='payload.specific.arms', raw=spec['arms'], confidence='medium')
    else:
        caps['has_arms'] = UNKNOWN('arms-param-v1')
    bt, bk = _param_text(P, PK['back'])
    if bt:
        caps['has_back'] = ev(not bt.lower().startswith('без') and bt.lower() != 'нет', 'known', 'params', 'back-param-v1', path=f'params.{bk}', raw=bt)
    elif isinstance(spec.get('back'), str) and spec['back'] not in ('не_видно',):
        # enrichment.specific.back доказывает НАЛИЧИЕ (виды спинки), не отсутствие (Codex)
        caps['has_back'] = ev(True, 'inferred', 'enrichment', 'back-enrich-v1', path='payload.specific.back', raw=spec['back'], confidence='medium')
    else:
        caps['has_back'] = UNKNOWN('back-param-v1')

    # ---- bench / daybed → wall_seat_capable, usable_seat_length, seats
    B, D = R['bench'], R['daybed']
    is_bench = any(c.lower() in cat.lower() for c in B['source_categories']) and re.search(B['name_regex'], name) is not None
    is_daybed = any(c.lower() in cat.lower() for c in D['source_categories']) and re.search(D['name_regex'], name) is not None
    caps['subtype'] = ev('банкетка' if is_bench else ('кушетка' if is_daybed else None),
                         'known' if (is_bench or is_daybed) else 'unknown', 'category+name', 'subtype-v1',
                         raw=cat if (is_bench or is_daybed) else None, reason=None if (is_bench or is_daybed) else 'not_bench_or_daybed')
    if is_bench:
        # backless: сиденье ≈ габарит; высота сиденья ≈ общая h (medium)
        if caps['seat_length_cm']['state'] == 'unknown' and w:
            caps['seat_length_cm'] = ev(float(w), 'inferred', 'products.w_cm', 'seat-length-backless-v1', confidence='medium', reason='backless_bench: seat≈overall')
        if caps['seat_height_cm']['state'] == 'unknown' and h:
            caps['seat_height_cm'] = ev(float(h), 'inferred', 'products.h_cm', 'seat-height-backless-v1', confidence='medium', reason='backless_bench: h≈seat_height')
        if caps['has_back']['state'] == 'unknown':
            caps['has_back'] = ev(False, 'inferred', 'category', 'back-bench-v1', confidence='medium', reason='банкетка — без спинки по типу')
    planning_roles: list[str] = []
    usable = caps['seat_length_cm']['value']
    if is_bench or is_daybed:
        lim = B if is_bench else D
        d_ok = (d is not None and d <= lim['d_max_cm'])
        l_ok = (usable is not None and usable >= lim['usable_seat_length_min_cm'])
        if d is None or usable is None:
            caps['wall_seat_capable'] = ev(None, 'unknown', 'derived', 'wall-seat-v1',
                                           depends_on=['overall_d_cm', 'seat_length_cm'], reason='missing_d_or_seat_length', confidence='low')
        else:
            caps['wall_seat_capable'] = ev(bool(d_ok and l_ok), 'known' if caps['seat_length_cm']['state'] == 'known' else 'inferred',
                                           'derived', 'wall-seat-v1', depends_on=['subtype', 'overall_d_cm', 'seat_length_cm'],
                                           confidence='high' if caps['seat_length_cm']['state'] == 'known' else 'medium',
                                           reason=None if (d_ok and l_ok) else ('d>' + str(lim['d_max_cm']) if not d_ok else 'seat_length<' + str(lim['usable_seat_length_min_cm'])))
        if caps['wall_seat_capable']['value'] is True:
            planning_roles.append('банкетка')
        S = R['seats']
        if usable:
            caps['nominal_seats'] = ev(int(usable // S['nominal_per_cm']), caps['seat_length_cm']['state'], 'derived', 'seats-nominal-v1', depends_on=['seat_length_cm'], confidence='medium')
            caps['guaranteed_seats'] = ev(int(usable // S['guaranteed_per_cm']), caps['seat_length_cm']['state'], 'derived', 'seats-guaranteed-v1', depends_on=['seat_length_cm'],
                                          confidence=caps['seat_length_cm']['confidence'])
        # dining: только ТОЧНАЯ высота сиденья
        DS = R['dining_seat']
        sh = caps['seat_height_cm']
        if sh['state'] == 'known' and sh['value'] is not None:
            lo, hi = DS['seat_height_hard_cm']
            plo, phi = DS['seat_height_pref_cm']
            okh = lo <= sh['value'] <= hi
            caps['dining_seat_capable'] = ev(bool(okh and caps['wall_seat_capable']['value'] is True), 'known', 'derived', 'dining-seat-v1',
                                             depends_on=['seat_height_cm', 'wall_seat_capable'],
                                             confidence='high' if plo <= sh['value'] <= phi else 'medium',
                                             reason=None if okh else f'seat_height {sh["value"]} вне {lo}–{hi}')
        else:
            caps['dining_seat_capable'] = ev(None, 'unknown', 'derived', 'dining-seat-v1', depends_on=['seat_height_cm'],
                                             reason='seat_height inferred/unknown — только candidate', confidence='low')
        caps['requires_wall_back_support'] = ev(caps['has_back']['value'] is False if caps['has_back']['state'] != 'unknown' else None,
                                                caps['has_back']['state'], 'derived', 'wall-back-v1', depends_on=['has_back'], confidence=caps['has_back']['confidence'])
    else:
        caps['wall_seat_capable'] = ev(False, 'known', 'category', 'wall-seat-v1', reason='not_bench_or_daybed')

    # ---- shallow storage / console (Q6e)
    SS = R['shallow_storage']
    if role in SS['cat_roles']:
        if d is None or h is None:
            caps['shallow_storage_capable'] = ev(None, 'unknown', 'derived', 'shallow-v1', reason='missing_dims', confidence='low')
        else:
            ok = d <= SS['d_max_cm'] and h <= SS['h_max_cm']
            caps['shallow_storage_capable'] = ev(bool(ok), 'known', 'derived', 'shallow-v1', depends_on=['overall_d_cm', 'overall_h_cm'],
                                                 reason=None if ok else ('d>' + str(SS['d_max_cm']) if d > SS['d_max_cm'] else 'h>' + str(SS['h_max_cm'])))
        fak = {'комод': 'drawers', 'тв-тумба': 'hinged', 'стеллаж': 'open'}[role]
        if role == 'тв-тумба' and re.search(r'открыт|полк', name):
            fak = 'open'
        caps['front_access_kind'] = ev(fak, 'inferred', 'role+name', 'front-access-v1', confidence='medium')
        wh = re.search(SS['wall_hung_regex'], name) is not None
        caps['mounting_mode'] = ev('wall_hung' if wh else 'freestanding', 'known' if wh else 'inferred', 'name', 'mounting-v1',
                                   confidence='high' if wh else 'medium', reason=None if wh else 'по умолчанию напольный (в имени нет «подвесн»)')
        modes = []
        if caps['shallow_storage_capable']['value'] is True:
            modes.append('wall_console')
            if not wh:
                modes.append('behind_sofa_candidate')   # задняя отделка неизвестна → кандидат, не сертификат
        caps['placement_modes'] = ev(modes, 'inferred', 'derived', 'placement-modes-v1', depends_on=['shallow_storage_capable', 'mounting_mode'], confidence='medium')
        caps['behind_sofa_console_capable'] = ev(None, 'unknown', 'derived', 'behind-sofa-v1',
                                                 reason='нужна задняя отделка + сверка с диваном (h ≤ спинка+5, w ≥ ⅔) — при расстановке', confidence='low')

    # ---- extension mechanism (sleeping)
    EM = R['extension_mechanism']
    if role in EM['cat_roles']:
        mt, mk = _param_text(P, PK['mechanism'])
        by_name = re.search(EM['name_regex'], name) is not None
        if mt:
            caps['extension_mechanism_present'] = ev(not mt.lower().startswith('без'), 'known', 'params', 'ext-mech-param-v1', path=f'params.{mk}', raw=mt)
        elif by_name:
            caps['extension_mechanism_present'] = ev(True, 'inferred', 'name', 'ext-mech-name-v1', confidence='medium', raw=name[:60])
        else:
            caps['extension_mechanism_present'] = UNKNOWN('ext-mech-param-v1')
        caps['extension_mechanism_present']['status'] = EM['status']   # sleeping: геометрия closed/open неизвестна

    evidence = {k: {kk: vv for kk, vv in v.items() if kk != 'value'} for k, v in caps.items()}
    return caps, evidence, planning_roles


# ---------------------------------------------------------------- build
def _fetch_rows() -> list[dict]:
    q = """select p.shop_mid, p.external_id, coalesce(p.cat_role,''), coalesce(p.category_path,''), coalesce(p.name,''),
                  coalesce(p.w_cm::text,''), coalesce(p.d_cm::text,''), coalesce(p.h_cm::text,''),
                  coalesce(p.params::text,'{}'),
                  case when e.enrichment_version is not null and e.status='active' then coalesce(e.payload::text,'') else '' end
           from products p left join product_enrichment e using (shop_mid, external_id)
           where p.in_stock and p.cat_role in ('пуф','диван','комод','тв-тумба','стеллаж','стол обеденный')"""
    out = []
    for r in _rows(q):
        if len(r) < 10:
            continue
        try:
            params = json.loads(r[8]) if r[8] else {}
        except Exception:
            params = {}
        try:
            enr = json.loads(r[9]) if r[9] else None
        except Exception:
            enr = None
        out.append({'shop_mid': int(r[0]), 'external_id': r[1], 'cat_role': r[2], 'category_path': r[3], 'name': r[4],
                    'w': float(r[5]) if r[5] else None, 'd': float(r[6]) if r[6] else None, 'h': float(r[7]) if r[7] else None,
                    'params': params if isinstance(params, dict) else {}, 'enr': enr})
    return out


def _input_hash(row: dict) -> str:
    src = json.dumps({k: row[k] for k in ('cat_role', 'category_path', 'name', 'w', 'd', 'h', 'params', 'enr')},
                     ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(src.encode()).hexdigest()[:16]


def _copy_upsert(lines: list[str]) -> None:
    sql_head = """create temp table pc_in (shop_mid int, external_id text, source_role text, planning_roles jsonb, caps jsonb, evidence jsonb,
 schema_version int, rules_version text, rules_hash text, input_hash text);
copy pc_in from stdin;
"""
    sql_tail = """\\.
insert into product_capabilities as t (shop_mid, external_id, source_role, planning_roles, caps, evidence, schema_version, rules_version, rules_hash, input_hash, computed_at)
select shop_mid, external_id, source_role, planning_roles, caps, evidence, schema_version, rules_version, rules_hash, input_hash, now() from pc_in
on conflict (shop_mid, external_id) do update set source_role=excluded.source_role, planning_roles=excluded.planning_roles,
  caps=excluded.caps, evidence=excluded.evidence, schema_version=excluded.schema_version, rules_version=excluded.rules_version,
  rules_hash=excluded.rules_hash, input_hash=excluded.input_hash, computed_at=now();
"""
    _rows('', inp=sql_head + '\n'.join(lines) + '\n' + sql_tail)


def report() -> None:
    q = """select p.shop, count(*),
        sum(case when (c.caps->'wall_seat_capable'->>'value')='true' then 1 else 0 end),
        sum(case when (c.caps->'dining_seat_capable'->>'value')='true' then 1 else 0 end),
        sum(case when (c.caps->'shallow_storage_capable'->>'value')='true' then 1 else 0 end),
        sum(case when (c.caps->'extension_mechanism_present'->>'value')='true' then 1 else 0 end),
        sum(case when (c.caps->'seat_height_cm'->>'state')='unknown' and c.source_role in ('диван','пуф') then 1 else 0 end)
        from product_capabilities c join products p using (shop_mid, external_id) group by 1 order by 2 desc"""
    print('shop\tn\twall_seat\tdining_seat\tshallow\text_mech\tseat_h_unknown(диван/пуф)')
    for r in _rows(q):
        print('\t'.join(r))
    print('planning_roles:', _rows("select planning_roles::text, count(*) from product_capabilities group by 1 order by 2 desc"))


def export() -> None:
    q = """select c.shop_mid, c.external_id, c.source_role, c.planning_roles::text, c.caps::text, c.rules_version, p.name, p.price_rub, p.shop
           from product_capabilities c join products p using (shop_mid, external_id)
           where p.in_stock and (jsonb_array_length(c.planning_roles) > 0 or (c.caps->'shallow_storage_capable'->>'value')='true')"""
    idx: dict[str, list] = {}
    for r in _rows(q):
        caps = json.loads(r[4]); pr = json.loads(r[3])
        used = {k: caps[k].get('value') for k in ('seat_length_cm', 'seat_height_cm', 'guaranteed_seats', 'nominal_seats', 'wall_seat_capable',
                                                   'dining_seat_capable', 'requires_wall_back_support', 'shallow_storage_capable',
                                                   'front_access_kind', 'mounting_mode', 'placement_modes') if k in caps}
        rec = {'mid': int(r[0]), 'eid': r[1], 'source_role': r[2], 'name': r[6], 'price': int(r[7]) if r[7] else None, 'shop': r[8],
               'caps_used': used, 'cap_rules_version': r[5]}
        for role in pr:
            idx.setdefault(role, []).append(dict(rec, planning_role=role))
        if used.get('shallow_storage_capable') is True:
            idx.setdefault('_shallow_storage', []).append(rec)
    json.dump({'schema_version': SCHEMA_VERSION, 'roles': idx}, open(INDEX_OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('export:', {k: len(v) for k, v in idx.items()}, '→', os.path.basename(INDEX_OUT))


def main() -> None:
    if '--build' in sys.argv:
        R = rules(); rh = _rules_hash()
        _rows(DDL)
        rows = _fetch_rows()
        prev = {(int(a), b): (c, d_) for a, b, c, d_ in _rows("select shop_mid, external_id, input_hash, rules_hash from product_capabilities")}
        lines = []; same = 0
        for row in rows:
            ih = _input_hash(row)
            if prev.get((row['shop_mid'], row['external_id'])) == (ih, rh):
                same += 1; continue
            caps, evidence, pr = project(row, R)
            rec = [str(row['shop_mid']), row['external_id'], row['cat_role'], json.dumps(pr, ensure_ascii=False),
                   json.dumps(caps, ensure_ascii=False), json.dumps(evidence, ensure_ascii=False),
                   str(SCHEMA_VERSION), R['_meta']['version'], rh, ih]
            lines.append('\t'.join(x.replace('\\', '\\\\').replace('\t', ' ').replace('\n', ' ') for x in rec))
        for i in range(0, len(lines), 5000):
            _copy_upsert(lines[i:i + 5000])
        # снятые с in_stock / вне ролей — не трогаем (снапшот истории; heal читает products)
        print(f'capabilities: строк {len(rows)}, пересчитано {len(lines)}, без изменений {same}, rules {R["_meta"]["version"]}/{rh}')
    if '--report' in sys.argv:
        report()
    if '--export' in sys.argv:
        export()
    if len(sys.argv) == 1:
        print(__doc__)


if __name__ == '__main__':
    main()
