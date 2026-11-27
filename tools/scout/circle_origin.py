#!/usr/bin/env python3
"""ПРОВЕРКА ВХОДА ПЕРЕД КРУГОМ ПОКРАСКИ — ПЯТЬ ВЕЩЕЙ (T-20261127-175/10; план Fable `plan-t175.md` § 3, ответ Fable 29 § 3, Fable 27 § 2).

ЗАЧЕМ. Три дорожки покраски (А/Б/В) гнали формы, вырезанные СТАРЫМ `make_hd_inputs` (T-93/1) вместо `chain_shape` (T-178): круг не знал, чем сделан его вход, и «хорошо/плохо» считалось на
устаревшем. Теперь старт круга сверяет вход с актуальным; расхождение — отказ строкой с причиной, круг не стартует. Код считает, не память директора.

ПЯТЬ ПУНКТОВ (каждый — своя строка отчёта: ✓ / · не применимо / ✗ ОТКАЗ / ⚠ ОБХОД):
 1. ВЫРЕЗКА ФОРМЫ — у готовой формы (`--prep-glb`/`--prep-dir`) есть запись происхождения (способ и версия цепочки вырезки, источник маски и версия весов, версия кода, хеш фото, дата) и версия
    цепочки в ней == актуальной («вход актуален»); ИЛИ есть запись «вход равнозначен: да» против АКТУАЛЬНОЙ версии (`cutout_equiv.py`: её пишет программа сравнения двух вырезок, проверка пересчитывает
    хеши и числа; сменилась версия — сравнение пересчитывается само; не сошлось/подделка — отказ) — в отчёте круга «вход равнозначен», не «актуален» (вердикт Fable по cut9). Форму, что строит этот
    же прогон текущим кодом, проверять нечего.
 2. ГЕНЕРАТОР И Ш0 — в записи назван генератор и ступень формы (генератор из разрешённых: TRELLIS.2; Hunyuan и прочие — отказ), и приёмка формы Ш0 ПРОЧИТАНА из записи `form_checks.json`
    рядом с формой (status == pass и список вызванных проверок `checks` непуст); нет записи, она битая/пустая/чужого товара, status не pass — отказ «Ш0 не пройдена». Ни `eye_accepted`, ни вложенный
    в запись происхождения `form_checks` не читаются: «пройдена» не подразумевается (директор 27.11: путь forms_render --accept молча сбоил с кодом 0).
 3. КАМЕРА 04 — этап 04 этого прогона прошёл (check.json ok/soft); ещё не считался и этот же прогон его посчитает — «не применимо» (гейты этапов не пустят 05+ без неё); не считался и не будет — отказ.
 4. КАРТОЧКА И ТИП — у товара есть запись каталога (иначе карточки нет, 07 идёт без роли — `no_type`, причина Avalon 27.11), в ней непустые название и роль и ≥ 1 параметра, роль даёт тип в паспортах
    (`paint_policy`: нет типа — правила типа не сработают); лежащая в прогоне `card.json` совпадает с карточкой из ТЕКУЩЕЙ записи каталога.
 5. НАБОР ПРАВИЛ — метка набора (sha реестра правил и паспортов + тип + digest паспорта типа, `rules_label`) пишется в журнал прогона; повторный старт в том же прогоне с ДРУГОЙ меткой — отказ
    («этапы посчитаны по одним правилам, продолжать по другим нельзя»); ожидаемая метка извне (`--rules-label`, замороженный набор экзамена) ≠ текущей — отказ. Поле и функцию метки у T-175/12
    (рабочий 4) согласовать: пока метка считается здесь же (`rules_label()`), смена — правка одной функции.
ОБХОД — только явным ключом `--allow-old-origin "причина ≥ 10 знаков"`: отказавшие пункты получают «обход», причина и список пишутся в `run_all.json` (`origin.bypass`) и печатаются итогом.

ГДЕ ФОРМАТ. Всё, что зависит от формата записи формы и Ш0, — в `rules/circle-origin.json` (пути записи, имена полей и синонимы, обязательные поля, разрешённые генераторы, откуда актуальная версия цепочки): формат
задаёт T-175/9 (рабочий 2, шаг 2) — подгонка = правка правил, не кода. Актуальная версия — `current.chain_version` либо константа в файле (`current.from`: «путь:ИМЯ», разбором, без импорта).
Нет актуальной версии (единый модуль вырезки не влит) — сверить НЕЧЕМ → отказ для готовой формы (честнее, чем «не знаю → пропустить»).

Библиотека: `check_start(...)` → {ok, items, origin, bypass}; CLI: `python3 tools/scout/circle_origin.py check --sku S [--prep-glb F] [--catalog C] [--card K] [--role R] [--run RUN] [--rules-label L] [--allow-old-origin ПРИЧИНА]`
(без камеры 04: её факт знает только paint_run_all — там зовётся с этапами). Код 0 — чисто/обход, 3 — отказ. Зовёт `paint_run_all.py run` до первого шага; `plan` печатает без отказа. Без сети, платного, секретов.
Тест: `python3 tools/scout/tests/test_circle_origin.py`."""
from __future__ import annotations

import argparse
import ast
import glob
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES = os.path.join(HERE, 'rules', 'circle-origin.json')
sys.path.insert(0, HERE)

OK, REFUSE, BYPASS, NA = 'ok', 'refuse', 'bypass', 'n/a'
I_CUT, I_GEN, I_CAM, I_CARD, I_RULES = 'вырезка формы', 'генератор и Ш0', 'камера 04', 'карточка и тип', 'набор правил'


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha256_obj(o) -> str:
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _load_json(path: str):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _dig(o, dotted: str):
    for k in [x for x in dotted.split('.') if x]:
        if not isinstance(o, dict) or k not in o:
            return None
        o = o[k]
    return o


def current_chain_version(rules: dict, root: str = ROOT) -> tuple:
    """(версия|None, откуда). `current.chain_version` — явное значение; иначе `current.from` «путь:ИМЯ» — константа в файле, читаем разбором (ast), модуль не импортируем."""
    cur = rules.get('current') or {}
    if cur.get('chain_version'):
        return str(cur['chain_version']), 'rules/circle-origin.json → current.chain_version'
    src = cur.get('from') or ''
    if ':' in src:
        rel, name = src.rsplit(':', 1)
        p = os.path.join(root, rel)
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except (OSError, SyntaxError):
            return None, f'{rel} не читается'
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
                try:
                    v = ast.literal_eval(n.value)
                except ValueError:
                    return None, f'{rel}:{name} — не константа'
                return (str(v) if v else None), f'{rel}:{name}'
        return None, f'{rel}: нет {name}'
    return None, 'актуальная версия цепочки не задана'


def sku_of(form: str) -> str:
    """id товара из имени формы: `<sku>-n1024.glb` / `<sku>.glb` / `<sku>.hd.rgba.png` → <sku> (суффиксы размера и вырезки отрезаются)."""
    b = os.path.basename(form)
    for suf in ('.glb', '.hd.rgba.png', '.rgba.png', '.png'):
        if b.endswith(suf):
            b = b[: -len(suf)]
            break
    return re.sub(r'-n\d+$', '', b)


def _paths(tpls: list, form: str, sku: str = '') -> list:
    """Подстановки: {form} {stem} {dir} {sku} (id из имени формы, если не задан) {sku_colon} (первое «_» → «:» — ключ в inputs.json: `112923:267…`)."""
    d, stem = os.path.dirname(form), os.path.splitext(form)[0]
    sku = sku or sku_of(form)
    colon = sku.replace('_', ':', 1)
    return [t.replace('{form}', form).replace('{stem}', stem).replace('{dir}', d).replace('{sku_colon}', colon).replace('{sku}', sku) for t in tpls]


def find_form_record(form: str, rules: dict) -> tuple:
    """(запись|None, где искали). Пути — `form.record_paths`; `путь#ключ.подключ` — запись внутри json."""
    tried = []
    for t in _paths((rules.get('form') or {}).get('record_paths') or [], form):
        path, _, key = t.partition('#')
        tried.append(t)
        data = _load_json(path)
        if data is None:
            continue
        rec = _dig(data, key) if key else data
        if isinstance(rec, dict) and rec:
            return rec, path + ('#' + key if key else '')
    return None, ', '.join(tried) or 'record_paths пуст'


def _field(rec: dict, name: str, rules: dict):
    for k in ((rules.get('form') or {}).get('fields') or {}).get(name) or [name]:
        v = _dig(rec, k) if '.' in k else rec.get(k)
        if v not in (None, '', [], {}):
            return v
    return None


def _item(item: str, status: str, reason: str, **kw) -> dict:
    return {'item': item, 'status': status, 'reason': reason, **kw}


def check_cutout(form: str | None, rules: dict, root: str = ROOT) -> dict:
    """Пункт 1: запись происхождения у готовой формы и версия цепочки вырезки == актуальной."""
    if not form:
        return _item(I_CUT, NA, 'готовой формы нет: форму строят этапы 01–02 этого же прогона текущим кодом')
    if not os.path.exists(form):
        return _item(I_CUT, REFUSE, f'файла формы нет: {form}')
    rec, where = find_form_record(form, rules)
    want, src = current_chain_version(rules, root)
    req = (rules.get('form') or {}).get('required') or ['chain_version']
    miss = [r for r in req if rec is not None and _field(rec, r, rules) is None]
    have = str(_field(rec, 'chain_version', rules)) if rec is not None and not miss else None
    if rec is not None and not miss and want and have == want:                         # версия вырезки актуальна — «вход актуален»
        return _item(I_CUT, OK, f'вход актуален: версия цепочки {have} = актуальной ({where})', record=where, chain_version=have, how='актуален')
    eq = check_equivalence(form, want, src, rules)                                     # иначе — запись «вход равнозначен» (её пишет программа сравнения, не рука)
    if eq is not None:
        return eq
    if rec is None:
        return _item(I_CUT, REFUSE, f'у формы нет записи происхождения (искал: {where}) и нет записи «вход равнозначен» — способ вырезки неизвестен; форма от старого `make_hd_inputs`/черновика не принимается')
    if miss:
        return _item(I_CUT, REFUSE, f'в записи происхождения ({where}) не хватает полей: {", ".join(miss)}')
    if not want:
        return _item(I_CUT, REFUSE, f'сверить нечем: актуальная версия цепочки не определена ({src}); единый модуль вырезки (T-175/9) не влит')
    return _item(I_CUT, REFUSE, f'вырезка формы старая: версия цепочки «{have}», актуальная «{want}» ({src}); способ «{_field(rec, "cutout_method", rules) or "?"}», дата «{_field(rec, "date", rules) or "?"}»; записи «вход равнозначен» нет')


def find_equiv_record(form: str, rules: dict) -> tuple:
    """(путь|None, запись|None): `<форма>.equiv.json` и т. п. — `form.equiv_paths`."""
    for p in _paths((rules.get('form') or {}).get('equiv_paths') or [], form):
        d = _load_json(p)
        if isinstance(d, dict) and d:
            return p, d
    return None, None


def check_equivalence(form: str, want: str | None, src: str, rules: dict) -> dict | None:
    """Запись «вход равнозначен» (cutout_equiv.py): нет записи — None (решает прежний путь); есть — пересчёт хешей и чисел; устарела (другая версия цепочки) — пересчёт сам (`equiv.recompute_cmd`),
    команды нет или не сошлось — отказ. Пройдена — «вход равнозначен» (не «актуален»)."""
    path, rec = find_equiv_record(form, rules)
    if rec is None:
        return None
    import cutout_equiv as CE
    E = rules.get('equiv') or {}
    th = E.get('thresholds')
    st, why, nums = CE.verify(rec, want, th)
    note = ''
    if st == 'stale' and want:
        new, why2 = CE.refresh(path, want, E.get('recompute_cmd'), th)
        if new is None:
            return _item(I_CUT, REFUSE, f'запись «вход равнозначен» ({path}) устарела: {why}; пересчёт не удался: {why2}')
        st, why, nums = CE.verify(new, want, th)
        note = ' (запись пересчитана сама: версия цепочки сменилась)'
    if st == 'equal':
        return _item(I_CUT, OK, f'вход равнозначен (не «актуален»): против версии цепочки {want}; несовпадение {nums.get("mismatch_pct")} %, пикселей дальше 2 px: {nums.get("far_px")} '
                     f'({nums.get("far_area_pct")} % площади), крупнейший кусок {nums.get("far_largest_px")} px{note}', record=path, chain_version=want, how='равнозначен', equiv=nums)
    return _item(I_CUT, REFUSE, {'forged': 'запись «вход равнозначен» не прошла проверку: ', 'not_equal': 'входы НЕ равнозначны: ', 'stale': 'запись устарела: ', 'unreadable': 'запись не читается: '}.get(st, '') + why)


def form_facts(form: str | None, rules: dict) -> dict | None:
    """Факты о форме для пункта 2: запись происхождения, дополненная блоком `form` записи «вход равнозначен» (только генератор и ступень — со слов того, кто писал запись)."""
    if not form or not os.path.exists(form):
        return None
    rec = find_form_record(form, rules)[0]
    _p, eq = find_equiv_record(form, rules)
    blk = (eq or {}).get('form')
    if isinstance(blk, dict) and blk:                                                # из блока — только генератор и ступень; Ш0 (eye_accepted, form_checks) в записи сравнения НЕ читается вовсе
        rec = {**{k: v for k, v in blk.items() if k not in ('eye_accepted', 'form_checks')}, **(rec or {})}
    for p in _paths((rules.get('form') or {}).get('meta_paths') or [], form):         # метка самой формы: генератор и ступень (запись вырезки их не несёт — её читает T-175/9)
        meta = _load_json(p)
        if isinstance(meta, dict):
            rec = {**{k: v for k, v in meta.items() if k in ('generator', 'stage', 'form_stage')}, **(rec or {})}
            break
    return rec


def read_verdict(form: str, sku: str, rules: dict) -> dict:
    """Вердикт Ш0 — ПРОЧИТАННЫЙ из записи `form_checks.json` рядом с формой (`form.verdict_paths`), не подразумеваемый (директор 27.11). → {status, flags, called, where, problem}.
    problem (None — запись годная): нет файла; файл не читается/не словарь/пуст; нет status или он не из известных; список `checks` (что вызвано) пуст или без обязательных проверок
    (`form.required_checks`); запись чужого товара (`sku` не совпал). Первая найденная запись решает — «поискать другую, где лучше» нет."""
    F = rules.get('form') or {}
    paths = _paths(F.get('verdict_paths') or [], form, sku)
    for p in paths:
        if not os.path.isfile(p):
            continue
        out = {'status': None, 'flags': None, 'called': [], 'where': p, 'problem': None}
        d = _load_json(p)
        if not isinstance(d, dict) or not d:
            out['problem'] = f'запись Ш0 {p} битая или пустая'
            return out
        st = d.get('status')
        out['status'], out['flags'] = (str(st) if st else None), d.get('flags')
        if not st or str(st) not in (F.get('known_status') or []):
            out['problem'] = f'в записи Ш0 {p} нет status или он неизвестный («{st}»; известны {F.get("known_status")})'
            return out
        checks = d.get('checks')
        called = [str(c.get('name')) for c in checks if isinstance(c, dict) and c.get('name')] if isinstance(checks, list) else []
        out['called'] = called
        if not called:
            out['problem'] = f'в записи Ш0 {p} не названо ни одной вызванной проверки (checks пуст) — вердикт ничем не подтверждён'
            return out
        miss = [n for n in F.get('required_checks') or [] if n not in called]
        if miss:
            out['problem'] = f'в записи Ш0 {p} не вызваны обязательные проверки: {miss}'
            return out
        if d.get('sku') not in (None, '', sku) and str(d.get('sku')).replace(':', '_') != sku.replace(':', '_'):
            out['problem'] = f'запись Ш0 {p} — другого товара («{d.get("sku")}», а круг по «{sku}»)'
            return out
        return out
    return {'status': None, 'flags': None, 'called': [], 'where': '', 'problem': 'нет записи form_checks.json (искал: ' + ', '.join(paths) + ')'}


def check_generator(form: str | None, sku: str, rec: dict | None, rules: dict) -> dict:
    """Пункт 2: генератор разрешён, ступень названа, Ш0 ПРОЧИТАНА из form_checks.json (status из разрешённых и список вызванных проверок). Ни `eye_accepted`, ни вложенного вердикта в записи происхождения нет."""
    if not form:
        return _item(I_GEN, NA, 'готовой формы нет: форма строится в этом прогоне')
    F = rules.get('form') or {}
    if rec is None:
        return _item(I_GEN, REFUSE, 'записи происхождения нет — генератор и ступень формы неизвестны (см. пункт «вырезка формы»)')
    gen, stage = _field(rec, 'generator', rules), _field(rec, 'form_stage', rules)
    if not gen or not stage:
        return _item(I_GEN, REFUSE, f'в записи не названы: {", ".join(n for n, v in (("generator", gen), ("stage", stage)) if not v)}')
    g = str(gen).lower()
    bad = [x for x in F.get('denied_generators') or [] if x in g]
    if bad or (F.get('allowed_generators') and not any(x in g for x in F['allowed_generators'])):
        return _item(I_GEN, REFUSE, f'генератор формы «{gen}» (ступень «{stage}») не разрешён: разрешены {F.get("allowed_generators")}, запрещены {F.get("denied_generators")}')
    v = read_verdict(form, sku, rules)
    if v['problem']:
        return _item(I_GEN, REFUSE, f'генератор «{gen}», ступень «{stage}»; Ш0 не пройдена: {v["problem"]}')
    if v['status'] not in (F.get('accept_status') or ['pass']):
        return _item(I_GEN, REFUSE, f'Ш0 не пройдена: status «{v["status"]}» (флаги: {v["flags"]}); допустимо {F.get("accept_status") or ["pass"]} ({v["where"]})')
    return _item(I_GEN, OK, f'генератор «{gen}», ступень «{stage}»; Ш0 {v["status"]}, вызвано проверок: {len(v["called"])} ({v["where"]})', generator=gen, stage=stage, sh0={'status': v['status'], 'called': v['called'], 'where': v['where']})


def check_camera(fact: dict | None) -> dict:
    """Пункт 3: `fact` {status: ok|soft|refused|missing, reason, will_run} — из check.json этапа 04 и плана прогона (знает paint_run_all). Нет факта — не применимо (CLI без прогона)."""
    if not fact:
        return _item(I_CAM, NA, 'прогон не передан — камеру 04 сверяет paint_run_all по check.json этапа')
    s = fact.get('status')
    if s in ('ok', 'soft'):
        return _item(I_CAM, OK, f'камера 04 пройдена ({s}): {fact.get("reason") or ""}'.rstrip(': '))
    if s == 'missing' and fact.get('will_run'):
        return _item(I_CAM, NA, 'камера 04 ещё не считалась, этот прогон посчитает её сам (этапы 05+ не стартуют без неё)')
    return _item(I_CAM, REFUSE, f'камера 04 не пройдена: {s} — {fact.get("reason") or "нет check.json этапа 04, и этот прогон его не посчитает"}')


def flat_card(record: dict | None) -> dict | None:
    """Карточка плоско — тем же правилом, что `$card_flat` в paint_run_all.resolve_files (name, role + params)."""
    if not record:
        return None
    return {'name': record.get('name'), 'role': record.get('role'), **(record.get('params') or {})}


def policy_of(role: str | None) -> dict:
    if not role:
        return {'type': None, 'digest': None, 'reason': 'no_role'}
    try:
        import mesh_type_passports as MTP
        return MTP.paint_policy(role)
    except Exception as e:  # noqa: BLE001 — нет реестра/модуля: тип не определён, не «обычная мебель»
        return {'type': None, 'digest': None, 'reason': f'registry_error:{type(e).__name__}'}


def check_card(record: dict | None, card_path: str | None, rules: dict | None = None) -> dict:
    """Пункт 4: карточка есть, непустая, роль даёт тип; card.json в прогоне = текущей записи каталога."""
    C = (rules or {}).get('card') or {}
    if not record:
        return _item(I_CARD, REFUSE, 'нет записи товара в каталоге (--catalog): карточки нет, шаг 07 пойдёт без роли и воздержится `no_type` (причина Avalon 27.11)')
    want = flat_card(record)
    empty = [k for k in C.get('required_fields') or ['name', 'role'] if not str(want.get(k) or '').strip()]
    if empty:
        return _item(I_CARD, REFUSE, f'карточка пустая: нет {", ".join(empty)}')
    n_params = len(record.get('params') or {})
    if n_params < int(C.get('min_params', 1)):
        return _item(I_CARD, REFUSE, f'в карточке {n_params} параметров (нужно ≥ {C.get("min_params", 1)}): зерну и размерам нечего брать')
    pol = policy_of(want['role'])
    if not pol.get('type'):
        return _item(I_CARD, REFUSE, f'роль «{want["role"]}» не даёт тип в паспортах ({pol.get("reason")}): правила типа не сработают — товар воздержится', card_sha=sha256_obj(want))
    if card_path and os.path.exists(card_path):
        have = _load_json(card_path)
        if have != want:
            diff = sorted(k for k in set(have or {}) | set(want) if (have or {}).get(k) != want.get(k))[:5] if isinstance(have, dict) else ['не json']
            return _item(I_CARD, REFUSE, f'карточка в прогоне ({card_path}) не совпадает с текущей записью каталога (поля: {", ".join(diff)}) — старая', card_sha=sha256_obj(want))
    return _item(I_CARD, OK, f'карточка непустая, роль «{want["role"]}» → тип «{pol["type"]}»' + ('; card.json = каталогу' if card_path and os.path.exists(card_path) else '; card.json запишется из каталога перед 07'),
                 card_sha=sha256_obj(want), type=pol['type'])


def rules_label(role: str | None, rules: dict, root: str = ROOT) -> dict:
    """Метка набора правил: sha файлов правил (`profile_files`) + тип роли + digest его паспорта. Одна функция — когда T-175/12 даст общую метку, меняется здесь."""
    files = {}
    for rel in rules.get('profile_files') or []:
        p = os.path.join(root, rel)
        files[rel] = sha256_file(p)[:16] if os.path.exists(p) else None
    pol = policy_of(role)
    lab = {'files': files, 'role': role, 'type': pol.get('type'), 'type_digest': pol.get('digest'), 'type_reason': pol.get('reason'), 'set': set_label(root)}
    lab['id'] = sha256_obj({k: lab[k] for k in ('files', 'type', 'type_digest')})[:16]
    return lab


def set_label(root: str = ROOT) -> str | None:
    """Метка ВСЕГО набора правил от T-175/12 (рабочий 4, `tools/scout/rules_label.py`: `field(root)['id']`, поле `rules_label`). ТОЛЬКО ЗАПИСЬ в журнал (`origin.rules_label.set`), в решение НЕ входит: менеджер 27.11 —
    метка №12 видит 4 переменные окружения из ~30 (правка rab-4, ветка feat/t175-12-env-polnyi); до неё отказы и «продолжать нельзя» судятся по метке круга (2 файла правил + тип + digest паспорта). Модуля нет/сбой — None."""
    try:
        import rules_label as RL
        i = (RL.field(root) or {}).get('id')
        return None if not i or i == 'нет' else str(i)
    except Exception:  # noqa: BLE001 — модуля нет/сбой: метка круга без него
        return None


def check_rules_set(role: str | None, rules: dict, prior: dict | None = None, expected: str | None = None, root: str = ROOT) -> dict:
    """Пункт 5: метка набора правил совпадает с меткой прежнего старта в этом прогоне и с ожидаемой извне."""
    lab = rules_label(role, rules, root)
    miss = [k for k, v in lab['files'].items() if v is None]
    if miss:
        return _item(I_RULES, REFUSE, f'файлов правил нет: {", ".join(miss)} — метку набора не посчитать', label=lab)
    if prior and prior.get('id') and prior['id'] != lab['id']:
        return _item(I_RULES, REFUSE, f'в этом прогоне этапы уже посчитаны по набору {prior["id"]}, сейчас {lab["id"]} — правила или паспорт типа изменились; новый прогон в новую папку', label=lab)
    if expected and expected != lab['id']:
        return _item(I_RULES, REFUSE, f'набор правил {lab["id"]} ≠ ожидаемому {expected} (замороженный набор): правила разошлись', label=lab)
    return _item(I_RULES, OK, f'метка набора {lab["id"]}' + (' = ожидаемой' if expected else '') + (' = прежней в этом прогоне' if prior and prior.get('id') else ''), label=lab)


def check_start(sku: str, *, form: str | None = None, record: dict | None = None, card: str | None = None, role: str | None = None, camera: dict | None = None,
                prior_origin: dict | None = None, expected_label: str | None = None, allow_old: str | None = None, rules: dict | None = None, root: str = ROOT,
                form_required: bool = False) -> dict:
    """→ {ok, items[5], origin{…для журнала}, bypass{reason, items, reasons}|None}. ok=False — круг не стартует."""
    rules = rules or load_rules()
    role = role or (record or {}).get('role') or None
    cut = _item(I_CUT, REFUSE, 'в строке входа нет формы (glb): стартер на пачке форму принимает входом, проверить вырезку нечем') if form_required and not form else check_cutout(form, rules, root)
    rec = form_facts(form, rules)
    items = [cut, check_generator(form, sku, rec, rules), check_camera(camera), check_card(record, card, rules),
             check_rules_set(role, rules, (prior_origin or {}).get('rules_label'), expected_label, root)]
    bad = [i for i in items if i['status'] == REFUSE]
    bypass = None
    if bad and allow_old is not None:
        if len((allow_old or '').strip()) < 10:
            items.append(_item('обход', REFUSE, '--allow-old-origin требует причину ≥ 10 знаков (она попадает в отчёт)'))
        else:
            for i in bad:
                i['status'] = BYPASS
            bypass = {'reason': allow_old.strip(), 'items': [i['item'] for i in bad], 'reasons': [i['reason'] for i in bad]}
    ok = not any(i['status'] == REFUSE for i in items)
    by = {i['item']: i for i in items}
    return {'ok': ok, 'sku': sku, 'items': items, 'bypass': bypass,
            'origin': {'form': by[I_CUT].get('record'), 'chain_version': by[I_CUT].get('chain_version'), 'cutout_basis': by[I_CUT].get('how'), 'equiv': by[I_CUT].get('equiv'), 'generator': by[I_GEN].get('generator'), 'sh0': by[I_GEN].get('sh0'), 'form_stage': by[I_GEN].get('stage'),
                       'card_sha': by[I_CARD].get('card_sha'), 'rules_label': by[I_RULES].get('label')}}


def catalog_record(catalog: str | None, sku: str) -> dict | None:
    """Запись товара из выгрузки каталога (список или одна запись {sid, name, role, params}) — как `paint_run_all.product_record`. Нет файла/товара → None."""
    if not catalog:
        return None
    data = _load_json(catalog)
    for r in data if isinstance(data, list) else ([data] if isinstance(data, dict) else []):
        if isinstance(r, dict) and r.get('sid') == sku:
            return {'sid': sku, 'name': r.get('name') or '', 'role': r.get('role') or '', 'params': r.get('params') or {}}
    return None


def camera_fact(pose_run: str | None) -> dict:
    """Факт камеры 04 по `<pose_run>/04-camera/check.json` — тем же классификатором (`paint_check.classify_stage`), что у paint_run_all. Нет папки/файла — missing (круг, который сам камеру не считает, отказывает)."""
    sys.path.insert(0, HERE)
    import paint_check as PC
    import paint_stage as PS
    chk = PS.read_check(os.path.join(pose_run, '04-camera')) if pose_run else None
    st = PC.classify_stage('04-camera', chk, PC.load_rules(), pose_run)
    return {'status': st['status'], 'reason': st['reason'], 'will_run': False}


def find_pose_run(sku: str, row: dict, pose_roots: list | tuple = ()) -> str | None:
    """Папка камеры этапа 4 товара: поле `pose_run` строки входа, иначе `<корень>/<товар>` и `<корень>/g*/<товар>` из `--pose-root`."""
    pr = (row or {}).get('pose_run')
    if pr:
        return pr
    for root in pose_roots:
        root = os.path.expanduser(root)
        for cand in [os.path.join(root, sku)] + sorted(glob.glob(os.path.join(root, '*', sku))):
            if os.path.isfile(os.path.join(cand, '04-camera', 'check.json')):
                return cand
    return None


def gate_rows(rows: dict, *, catalog: str | None = None, allow_old: str | None = None, pose_roots: list | tuple = (), expected_label: str | None = None,
              rules: dict | None = None, root: str = ROOT) -> dict:
    """Проверка входа на ПАЧКЕ товаров стартера круга (строки `{товар: {glb, photo, pose_run, extra_in{card.json}}}` — формат inputs.json у stage_trial/loop5): пять вещей по каждому товару тем же `check_start`.
    → {ok, n, refused: [sku…], results{sku: …}, bypass}. Строка без `glb` (форма не названа) — отказ пункта 1, не пропуск."""
    rules = rules or load_rules()
    results = {}
    for sku, row in rows.items():
        row = row or {}
        card = row.get('card') or (row.get('extra_in') or {}).get('card.json')
        results[sku] = check_start(sku, form=row.get('glb') or None, record=catalog_record(catalog, sku), card=card if card and os.path.isfile(card) else None,
                                   camera=camera_fact(find_pose_run(sku, row, pose_roots)), expected_label=expected_label, allow_old=allow_old, rules=rules, root=root, form_required=True)
    refused = [s for s, r in results.items() if not r['ok']]
    byp = {s: r['bypass'] for s, r in results.items() if r['bypass']}
    return {'ok': not refused, 'n': len(results), 'refused': refused, 'results': results, 'bypass': byp or None, 'allow_old': allow_old}


def render_rows(g: dict) -> str:
    out = [f"проверка входа круга: товаров {g['n']}, " + ('можно начинать' if g['ok'] else f"КРУГ НЕ СТАРТУЕТ — отказ у {len(g['refused'])}: {', '.join(g['refused'][:8])}{'…' if len(g['refused']) > 8 else ''}")]
    for sku, r in g['results'].items():
        bad = [i for i in r['items'] if i['status'] in (REFUSE, BYPASS)]
        if bad:
            out.append(f'  {sku}')
            out += [f"    {'✗ ОТКАЗ' if i['status'] == REFUSE else '⚠ ОБХОД'} {i['item']}: {i['reason']}" for i in bad]
    if g['bypass']:
        out.append(f"  ОБХОД ключом --allow-old-origin: «{g['allow_old']}» — у {len(g['bypass'])} товаров (попадёт в origin-check.json и в отчёт)")
    return '\n'.join(out)


def starter_gate(rows: dict, *, who: str, out_dir: str | None = None, dry: bool = False, allow_old: str | None = None, catalog: str | None = None, pose_roots: list | tuple = (),
                 expected_label: str | None = None, say=print, rules: dict | None = None) -> dict:
    """ЕДИНЫЕ ВОРОТА СТАРТЕРА КРУГА (T-175/10, условие директора): зовёт каждый стартер (loop5.py, stage_trial.py …) ДО первого платного шага. Печатает итог, пишет `<out_dir>/origin-check.json`
    (в нём обход и причина — в отчёт); при отказе без обхода — SystemExit(3). `dry` (разбор без запуска) отказ только печатает. Тест-сторож: `tests/test_circle_origin.py` («стартеры круга»)."""
    g = gate_rows(rows, catalog=catalog, allow_old=allow_old, pose_roots=pose_roots, expected_label=expected_label, rules=rules)
    say(f'[{who}] ' + render_rows(g))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, 'origin-check.json'), 'w', encoding='utf-8') as f:
            json.dump({'who': who, 'checked': time.strftime('%Y-%m-%d %H:%M:%S'), 'dry': dry, 'ok': g['ok'], 'refused': g['refused'], 'bypass': g['bypass'], 'allow_old': allow_old,
                       'products': {s: {'ok': r['ok'], 'origin': r['origin'], 'items': [{k: i[k] for k in ('item', 'status', 'reason')} for i in r['items']]} for s, r in g['results'].items()}},
                      f, ensure_ascii=False, indent=1)
    if not g['ok'] and not dry:
        raise SystemExit(3)
    return g


def _is_starter_file(path: str, M: dict) -> bool:
    """Запускает ли файл круг (признаки — rules/circle-origin.json → starters.markers). Python — по AST (комментарии и строки документации не в счёт), .sh — по строкам кода. Не разбирается → True (проверить нельзя — внести явно)."""
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return True
    if path.endswith('.sh'):
        return any(re.search(M['sh_re'], ln) for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith('#'))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return True
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(a.name.split('.')[0] in M['import_modules'] for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and n.module and n.module.split('.')[0] in M['import_modules']:
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in M['call_attrs']:
            return True
        if isinstance(n, ast.Name) and n.id in M['names']:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.search(M['script_re'], n.value):
            return True
    return False


def scan_starters(root: str = ROOT, rules: dict | None = None) -> list[str]:
    """Все файлы под `starters.scan_dirs`, что запускают круг (пути от корня репозитория)."""
    S = (rules or load_rules())['starters']
    found = []
    for base in S['scan_dirs']:
        for dp, dn, fn in os.walk(os.path.join(root, base)):
            dn[:] = sorted(d for d in dn if d not in S['scan_skip_dirs'])
            for f in sorted(fn):
                if f.endswith(('.py', '.sh')) and not f.startswith(tuple(S['scan_skip_prefixes'])) and _is_starter_file(os.path.join(dp, f), S['markers']):
                    found.append(os.path.relpath(os.path.join(dp, f), root))
    return found


def _dotted(node) -> str:
    """Имя вызываемого: `f` → «f», `CO.starter_gate` → «CO.starter_gate»; иное (вызов вызова, подписка) — пусто."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return '.'.join(reversed(parts))
    return ''


def _entry_calls(path: str, entry: str) -> list | None:
    """Вызовы в функции верхнего уровня `entry`: [(строка, столбец, имя, результат_присвоен)] по порядку в тексте. Только настоящие вызовы (AST): комментарии и строки не в счёт."""
    try:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return None
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == entry:
            assigned = {id(n.value) for n in ast.walk(fn) if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Call)}
            calls = [(n.lineno, n.col_offset, _dotted(n.func), id(n) in assigned) for n in ast.walk(fn) if isinstance(n, ast.Call)]
            return sorted(calls)
    return None


def starter_problems(root: str = ROOT, rules: dict | None = None) -> list[str]:
    """СТОРОЖ СТАРТЕРОВ КРУГА (условие директора к №10). Пусто — всё чисто. Иначе строки-причины: стартер не внесён в реестр (ни must_call, ни exempt с причиной); у must_call нет вызова ворот
    в точке входа; ворота стоят ПОСЛЕ первого запуска; реестр ссылается на несуществующее."""
    S = (rules or load_rules())['starters']
    listed = {m['file'] for m in S['must_call']} | {e['file'] for e in S['exempt']}
    probs = [f'{rel}: запускает круг, но не внесён в реестр стартеров (must_call — зовёт ворота; exempt — с причиной)' for rel in scan_starters(root, rules) if rel not in listed]
    for e in S['exempt']:
        if len((e.get('why') or '').strip()) < 20:
            probs.append(f"{e['file']}: исключение из ворот без причины (≥ 20 знаков)")
        if not os.path.isfile(os.path.join(root, e['file'])):
            probs.append(f"{e['file']}: внесён в исключения, но файла нет")
        elif e.get('wraps'):                                                       # обёртка: должна звать стартер из must_call, иначе исключение — дыра
            if e['wraps'] not in {m['file'] for m in S['must_call']}:
                probs.append(f"{e['file']}: обёртка над {e['wraps']}, а его нет среди must_call")
            with open(os.path.join(root, e['file']), encoding='utf-8') as f:
                if os.path.basename(e['wraps']) not in f.read():
                    probs.append(f"{e['file']}: обёртка больше не зовёт {os.path.basename(e['wraps'])}")
    for m in S['must_call']:
        p = os.path.join(root, m['file'])
        if not os.path.isfile(p):
            probs.append(f"{m['file']}: внесён как стартер, но файла нет")
            continue
        calls = _entry_calls(p, m['entry'])
        if calls is None:
            probs.append(f"{m['file']}: нет функции входа {m['entry']}()")
            continue
        gates = [c for c in calls if c[2] == m['gate'] and (c[3] or not m.get('gate_assigned'))]   # gate_assigned: результат ворот присвоен (в ветке `plan` тот же вызов без присваивания — не старт)
        if not gates:
            probs.append(f"{m['file']}: стартер круга без вызова проверки входа (`{m['gate']}(…)` нет в {m['entry']}())")
        for st in m['start']:
            starts = [c for c in calls if c[2] == st]
            if not starts:
                probs.append(f"{m['file']}: в {m['entry']}() нет запуска `{st}(…)` — реестр устарел")
            elif gates and starts[0][:2] < gates[0][:2]:
                probs.append(f"{m['file']}: проверка входа стоит ПОСЛЕ запуска `{st}(…)`")
    return probs


def render(res: dict) -> str:
    mark = {OK: '✓', REFUSE: '✗ ОТКАЗ', BYPASS: '⚠ ОБХОД', NA: '·'}
    out = [f"проверка входа круга {res['sku']}: " + ('можно начинать' if res['ok'] else 'КРУГ НЕ СТАРТУЕТ')]
    out += [f"  {n}. {mark[i['status']]:9} {i['item']}: {i['reason']}" for n, i in enumerate(res['items'], 1)]
    if res['bypass']:
        out.append(f"  ОБХОД ключом --allow-old-origin: «{res['bypass']['reason']}» — обойдено: {', '.join(res['bypass']['items'])} (попадёт в run_all.json и в отчёт)")
    return '\n'.join(out)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description='проверка входа перед кругом покраски: пять вещей (T-175/10)')
    ap.add_argument('cmd', choices=('check',))
    ap.add_argument('--sku', required=True)
    ap.add_argument('--prep-glb', default='')
    ap.add_argument('--catalog', default='', help='выгрузка каталога (JSON-список/запись {sid, name, role, params}) — как у paint_run_all')
    ap.add_argument('--card', default='', help='карточка в прогоне (card.json), если уже лежит')
    ap.add_argument('--role', default='')
    ap.add_argument('--run', default='', help='папка прогона: из <run>/<sku>/run_all.json берётся прежняя метка набора правил')
    ap.add_argument('--rules-label', default='', help='ожидаемая метка набора правил (замороженный набор экзамена)')
    ap.add_argument('--allow-old-origin', default=None, metavar='ПРИЧИНА')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    record = None
    if a.catalog:
        import paint_run_all as RA
        record = RA.product_record({'catalog': a.catalog}, a.sku)
    prior = None
    if a.run:
        import paint_stage as PS
        prior = (_load_json(os.path.join(a.run, PS.safe_name(a.sku), 'run_all.json')) or {}).get('origin')
    res = check_start(a.sku, form=a.prep_glb or None, record=record, card=a.card or None, role=a.role or None, prior_origin=prior, expected_label=a.rules_label or None, allow_old=a.allow_old_origin)
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render(res))
    return 0 if res['ok'] else 3


if __name__ == '__main__':
    sys.exit(main())
