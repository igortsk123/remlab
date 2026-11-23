#!/usr/bin/env python3
"""Четыре состояния решения этапа 9: pass / fail / uncertain / not_applicable (T-20261123-19/1, П1.154; сверка директора с Codex 23.11).
ЗАЧЕМ. Старый флаг `passed` этапов 06/07 и «ready» этапа 9 считают «прошло», когда мерка ПУСТА или не подключена (аудит 23.11: front_on_back_corr = null → «прошло» у 35 из 300;
tex_coverage пропускает пустые значения; paint_check берёт passed=true этапа без проверки полноты). Здесь «pass» — только если все обязательные применимые мерки посчитаны и в пороге.

Правила одной мерки (реестр `rules/paint-decisions.json`, чисел порогов там нет — порог читает сам этап, мы берём его `ok`/`threshold`):
  • нет check.json этапа / нет значения (пусто, None) → uncertain (кроме `na_when_absent`: известное «мерки нет» — not_applicable с записанной причиной);
  • мерка помечена `na` самим сторожем (верх не виден на фото) → not_applicable с его причиной;
  • `calibrated: false` → uncertain «порог не откалиброван» (сырой итог пишем в `raw`, чтобы видеть «было бы pass/fail»);
  • иначе pass / fail по `ok` (или по value/threshold/op, если `ok` нет).
Итог товара: `state` — только по hard/soft (текущий состав), `state_with_shadow` — плюс новые решения в тени. fail — любое hard fail; иначе uncertain — любое hard/soft uncertain;
иначе pass (soft fail → пометка в `notes`, как «готов с пометкой»). info в итог не входит. Старый флаг НЕ меняется — это отдельный ключ рядом.
Модуль без numpy: json + чистая логика (его зовёт paint_check.py и таблица «старое → новое»). ID товаров в коде нет."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'paint-decisions.json')
OPS = {'<=': lambda v, t: v <= t, '>=': lambda v, t: v >= t, '<': lambda v, t: v < t, '>': lambda v, t: v > t}
STATES = ('pass', 'fail', 'uncertain', 'not_applicable')


def load(path: str = RULES) -> dict:
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    ids = [d['id'] for d in r['decisions']]
    if len(ids) != len(set(ids)):
        raise ValueError('paint-decisions.json: повторяется id решения')
    for d in r['decisions']:
        if d['severity'] not in r['severity']:
            raise ValueError(f"paint-decisions.json: {d['id']}: строгость {d['severity']!r} не из списка")
        for k in ('stage', 'owner', 'applies', 'threshold_ref', 'calibrated', 'requires'):
            if k not in d:
                raise ValueError(f"paint-decisions.json: {d['id']}: нет поля {k}")
    return r


def _ok_of(m: dict) -> bool | None:
    """Мерка в пороге? `ok` этапа главнее; нет — по value/threshold/op; нечего сравнить — None."""
    if isinstance(m.get('ok'), bool):
        return m['ok']
    v, t, op = m.get('value'), m.get('threshold'), m.get('op')
    if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(t, (int, float)) and op in OPS:
        return bool(OPS[op](v, t))
    return None


def decide_one(d: dict, stages: dict, extra: dict) -> dict:
    """Состояние одного решения. stages: имя этапа → результат classify_stage (или status-словарь сторожа); extra — словарь сторожей 09 (coverage/palette/surface)."""
    out = {'id': d['id'], 'severity': d['severity'], 'state': 'uncertain', 'why': ''}
    st = (extra if d['stage'] in extra else stages).get(d['stage'])
    if st is None:
        out['why'] = f"нет входа: {d['requires'][0]}"
        return out
    if 'status_of' in d:                                                        # сторож 09: статус ok|soft|refused|missing
        s = st.get('status')
        if s == 'missing':
            out['why'] = st.get('reason') or 'сторож не запускался'
        elif s in ('ok', 'soft', 'refused'):
            out['state'] = 'fail' if s == 'refused' else 'pass'
            out['note'] = st.get('reason') if s == 'soft' else ''
        else:
            out['why'] = f'неизвестный статус {s!r}'
        return _calibration(d, out)
    if st.get('status') == 'missing' and not st.get('metrics'):
        out['why'] = st.get('reason') or 'нет check.json этапа'
        return out
    m = (st.get('metrics') or {}).get(d['metric'])
    if m is None:
        if d.get('na_when_absent'):
            return dict(out, state='not_applicable', why=d['na_when_absent'])
        out['why'] = 'мерка не посчитана (нет в check.json этапа)'
        return out
    if m.get('na'):                                                             # сторож сам сказал «не применимо» и почему
        return dict(out, state='not_applicable', why=str(m['na']))
    if m.get('error'):
        out['why'] = f"мерка не измерена: {m['error']}"
        return out
    if m.get('value') is None:
        if d.get('na_when_absent'):
            return dict(out, state='not_applicable', why=d['na_when_absent'])
        out['why'] = 'значение пустое (раньше это считалось «прошло»)'
        return out
    ok = _ok_of(m)
    if ok is None:
        out['why'] = 'нечем сравнить с порогом (нет порога/ok)'
        return out
    out.update(state='pass' if ok else 'fail', value=m.get('value'))
    return _calibration(d, out)


def _calibration(d: dict, out: dict) -> dict:
    if not d.get('calibrated', True) and out['state'] in ('pass', 'fail'):
        out.update(raw=out['state'], state='uncertain', why='порог не откалиброван' + (f": {d['why_uncalibrated']}" if d.get('why_uncalibrated') else ''))
    return out


def decide_product(stages: list, extra: dict | None = None, reg: dict | None = None) -> dict:
    """Итог товара по реестру. stages — список classify_stage; extra — {'coverage': …, 'palette': …, 'surface': …}."""
    reg = reg or load()
    by = {s['stage']: s for s in stages}
    items = [decide_one(d, by, extra or {}) for d in reg['decisions']]

    def agg(sev: tuple) -> str:
        use = [i for i in items if i['severity'] in sev]
        if any(i['state'] == 'fail' and i['severity'] in ('hard', 'shadow') for i in use):
            return 'fail'
        if any(i['state'] == 'uncertain' for i in use):
            return 'uncertain'
        return 'pass' if any(i['state'] == 'pass' for i in use) else 'uncertain'

    soft_fail = [i['id'] for i in items if i['severity'] == 'soft' and i['state'] == 'fail']
    return {
        'registry': reg['version'], 'state': agg(('hard', 'soft')), 'state_with_shadow': agg(('hard', 'soft', 'shadow')),
        'items': {i['id']: {k: v for k, v in i.items() if k != 'id' and v not in ('', None)} for i in items},
        'fail': [i['id'] for i in items if i['state'] == 'fail' and i['severity'] in ('hard', 'shadow')],
        'uncertain': [i['id'] for i in items if i['state'] == 'uncertain' and i['severity'] != 'info'],
        'notes': soft_fail, 'not_applicable': [i['id'] for i in items if i['state'] == 'not_applicable'],
    }
