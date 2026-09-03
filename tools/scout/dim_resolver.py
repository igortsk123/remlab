#!/usr/bin/env python3
"""Резолвер габаритов из фида — T1 мастер-плана truth-first (P0 аудита рефери).

Чем плоха была эвристика `>400 → /10` в load3 (пруф 08.08 по живым фидам):
  - П-образные диваны 440–442 СМ (mnogomebeli/divanboss) превращались в «диваны 44 см»
    (46 офферов); при этом tvoydom/gipfel реально шлют ММ (высота люстры 780, диаметр 490),
    а атрибута unit= Гдеслон не передаёт вовсе (0 вхождений во всех 10 фидах).
  - «350 мм» порог не делил (350 ≤ 400) — узкая тумба 35 см жила как 350 см.

Единица определяется НЕСКОЛЬКИМИ свидетельствами, по убыванию доверия (per-item сильнее приора):
  1. `param_name` — единица в ИМЕНИ параметра: «Ширина, мм» / «Ширина (см)».
  2. `title` — кросс-чек с «Ш×Г×В» из названия товара: значение или значение/10 совпало
     с числом из названия (названию верим как см — так пишут карточки RU-магазинов).
  3. `prior` — выученный приор (mid × роль × параметр) из unit-priors.json (--learn):
     доля значений >400 в группе ≥ LEARN_MM_SHARE → группа шлёт мм (и тогда делятся ВСЕ
     значения группы, включая ≤400 — случай «350 мм»).
  4. `plaus` — правдоподобие по роли: ≤ ROLE_MAX_CM → см; >порога, но /10 попадает → мм.
  5. Не разрешилось — значение НЕ пишется (лучше дыра, чем ложь), сырьё остаётся в
     params/evidence, товар получает флаг `unresolved`.

Provenance: на товар пишется dims_source (сводка, напр. "param:2 prior-mm:1") и
dims_evidence jsonb {dim: {raw, unit, source}}. Ручные/скрейпленные размеры
(dims_source scrape|manual) фид НЕ затирает (authority сильнее свежести — правка рефери).

Запуск:  --learn (построить unit-priors.json по фидам)  ·  --selftest  ·  --check <mid>
"""
import glob
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRIORS_PATH = os.environ.get('SCOUT_PRIORS_PATH') or os.path.join(HERE, 'unit-priors.json')  # env — для селфтестов в CI без данных вне git
LEARN_MM_SHARE = 0.30   # доля значений >400 в группе, после которой группа считается мм-группой
LEARN_MIN_N = 8         # меньше наблюдений — приор не строим (шум)

# Ключи фида по осям (как в load3) + алиасы divan.ru (открыто T1: у divan.ru 5 283 товара
# лежали в БД БЕЗ размеров — параметры зовутся «Размеры: Длина габаритная» и т.д.; их оси:
# Длина = фронт (наша w), Ширина = глубина (наша d) — проверено на комодах/тумбах 08.08).
DIM_KEYS = {
    'w': ['Ширина', 'Ширина, см', 'Ширина, мм', 'Размеры: Длина габаритная'],
    'd': ['Глубина', 'Глубина, см', 'Глубина, мм', 'Размеры: Ширина габаритная'],
    'h': ['Высота', 'Высота, см', 'Высота, мм', 'Размеры: Высота габаритная'],
    'len': ['Длина', 'Длина, см', 'Длина, мм'],
    'dia': ['Диаметр', 'Диаметр, см', 'Диаметр, мм'],
}
# Максимальный правдоподобный размер в см по роли — И для fallback-ступени, И для обучения
# приоров. Дефолт 400 (крупная мебель); шире — только роли с реальными >400 см (модульные
# диваны); УЖЕ — декор и свет: ваза «200» при потолке 60 читается как 200 мм, а не 2 метра
# (найдено кросс-чеком T1: gipfel шлёт весь декор в мм, и значения ≤400 приор считал см).
ROLE_MAX_CM = {
    'диван': 470, 'стенка': 430, 'ковёр': 500,
    'ваза': 60, 'статуэтка': 70, 'часы': 100, 'кашпо': 90,
    'лампа': 70, 'бра': 70, 'люстра': 150, 'подушка': 100, 'плед': 260,
}
# Потолок правдоподобной ВЫСОТЫ, см (для остального — 330, выше потолка мебель не бывает)
ROLE_MAX_H_CM = {'ваза': 120, 'статуэтка': 110, 'лампа': 100, 'бра': 80,
                 'люстра': 150, 'часы': 120, 'кашпо': 120, 'подушка': 80, 'плед': 260}
MIN_CM = 5.0    # меньше 5 см любая ось мебели/декора неправдоподобна

_num = re.compile(r'\d+(?:[.,]\d+)?')
_title_triple = re.compile(r'(\d{2,4})\s*[x×х*]\s*(\d{2,4})(?:\s*[x×х*]\s*(\d{2,4}))?')

_PRIORS: dict | None = None


def _priors() -> dict:
    global _PRIORS
    if _PRIORS is None:
        try:
            _PRIORS = json.load(open(PRIORS_PATH))
        except (OSError, json.JSONDecodeError):
            _PRIORS = {}
    return _PRIORS


def _numval(s: str) -> float | None:
    m = _num.search(s or '')
    if not m:
        return None
    try:
        return float(m.group(0).replace(',', '.'))
    except ValueError:
        return None


def title_numbers(name: str) -> set[float]:
    """Числа из «Ш×Г×В» в названии — считаем сантиметрами (конвенция RU-карточек)."""
    out: set[float] = set()
    for m in _title_triple.finditer(name or ''):
        for g in m.groups():
            if g:
                out.add(float(g))
    return out


def role_max(role: str | None, dim: str) -> float:
    if dim == 'h':
        return ROLE_MAX_H_CM.get(role or '', 330.0)
    return ROLE_MAX_CM.get(role or '', 400.0)


def resolve(mid: int, name: str, params: dict, role: str | None):
    """→ (dims {w,d,h,len,dia → см|None}, evidence {dim: {raw,unit,source}}, source_summary)."""
    tnums = title_numbers(name)
    priors = _priors()
    dims: dict[str, float | None] = {}
    evidence: dict[str, dict] = {}
    counts: dict[str, int] = {}

    for dim, keys in DIM_KEYS.items():
        raw, key_used, val_str = None, None, ''
        for k in keys:
            v = params.get(k)
            if v:
                raw, key_used, val_str = _numval(v), k, v
                if raw is not None:
                    break
        if raw is None:
            dims[dim] = None
            continue

        unit, source = None, None
        # 1. Явная единица в ЗНАЧЕНИИ («47см», «470 мм») или в ИМЕНИ параметра («Ширина, мм»)
        low = val_str.lower()
        if 'мм' in low or 'mm' in low:
            unit, source = 'mm', 'param'
        elif 'см' in low or 'cm' in low:
            unit, source = 'cm', 'param'
        elif key_used and 'мм' in key_used:
            unit, source = 'mm', 'param'
        elif key_used and 'см' in key_used:
            unit, source = 'cm', 'param'
        # 2. Кросс-чек с названием. Асимметрия: «param/10 совпал с названием» доказывает мм
        # всегда (название при этом в см); «param совпал с названием» доказывает см только
        # для правдоподобных значений — название «1200x300x1800» само в мм, и точное
        # совпадение 1200==1200 единицу НЕ раскрывает (уйдёт на ступени 3–4).
        if unit is None and tnums:
            if round(raw / 10, 1) in tnums or raw / 10 in tnums:
                unit, source = 'mm', 'title'
            elif raw in tnums and raw <= role_max(role, dim):
                unit, source = 'cm', 'title'
        # 3. Выученный приор группы (mid × роль × ось). Приор — групповое знание и НЕ
        # перебивает неправдоподобие конкретного значения: cm-приор применим, только если
        # значение правдоподобно как см (иначе это per-item мм-выброс смешанного магазина —
        # люстра «780» в cm-группе tvoydom), мм-приор — только если /10 даёт ≥ MIN_CM.
        if unit is None:
            pr = priors.get(f'{mid}:{role or "?"}:{dim}')
            if pr and pr['n'] >= LEARN_MIN_N:
                if pr['unit'] == 'mm' and raw / 10 >= MIN_CM:
                    unit, source = 'mm', 'prior'
                elif pr['unit'] == 'cm' and MIN_CM <= raw <= role_max(role, dim):
                    unit, source = 'cm', 'prior'
        # 4. Правдоподобие по роли
        if unit is None:
            mx = role_max(role, dim)
            if MIN_CM <= raw <= mx:
                unit, source = 'cm', 'plaus'
            elif raw > mx and MIN_CM <= raw / 10 <= mx:
                unit, source = 'mm', 'plaus'

        if unit is None:
            dims[dim] = None
            evidence[dim] = {'raw': raw, 'unit': None, 'source': 'unresolved'}
            counts['unresolved'] = counts.get('unresolved', 0) + 1
            continue
        val = round(raw / 10, 1) if unit == 'mm' else raw
        # Ролевой sanity-clamp итога: даже правильно разрешённая единица не спасает от
        # мусорного сырья (объём/артикул в размерном поле) — ваза «190 см» невозможна
        if not (MIN_CM <= val <= role_max(role, dim) * 1.15):
            dims[dim] = None
            evidence[dim] = {'raw': raw, 'unit': unit, 'source': f'{source}-insane'}
            counts['unresolved'] = counts.get('unresolved', 0) + 1
            continue
        dims[dim] = val
        evidence[dim] = {'raw': raw, 'unit': unit, 'source': source}
        tag = source if unit == 'cm' else f'{source}-mm'
        counts[tag] = counts.get(tag, 0) + 1

    summary = ' '.join(f'{k}:{v}' for k, v in sorted(counts.items())) or None
    return dims, evidence, summary


# ---------------------------------------------------------------- learn / check / selftest

def learn() -> None:
    """Построить unit-priors.json: (mid × роль × ось) → инференс единицы по доле >400.
    Логика: реальные >400 см в мебели — редкость (только модульные диваны/стенки), поэтому
    доля >400 ≥ LEARN_MM_SHARE в группе означает «группа шлёт мм» — и делить надо ВСЕ её
    значения (включая ≤400, случай «350 мм»). Evidence ledger — по правке рефери §15."""
    sys.path.insert(0, HERE)
    catrole = {}
    try:
        cr = json.load(open(os.path.join(HERE, 'category-roles.json')))
        for rec in cr.values():          # ключ «mid:cid», значение {mid,id,role,...}
            if rec.get('role'):
                catrole[(int(rec['mid']), str(rec['id']))] = rec['role']
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        print('category-roles.json не читается — приоры без ролей не строим', file=sys.stderr)
        sys.exit(1)
    import xml.etree.ElementTree as ET
    groups: dict[str, list[float]] = {}
    for zp in sorted(glob.glob(os.path.join(HERE, 'feeds2', '*.xml.zip'))):
        with zipfile.ZipFile(zp) as z:
            for nm in z.namelist():
                with z.open(nm) as f:
                    for _, el in ET.iterparse(f):
                        if el.tag != 'offer':
                            continue
                        url = el.findtext('url') or ''
                        m = re.search(r'mid=(\d+)|mid%3D(\d+)', url)
                        if not m:
                            el.clear(); continue
                        mid = int(m.group(1) or m.group(2))
                        cid = el.findtext('categoryId')
                        role = catrole.get((mid, str(cid)))
                        if not role:
                            el.clear(); continue
                        params = {p.get('name'): (p.text or '') for p in el.findall('param')}
                        for dim, keys in DIM_KEYS.items():
                            for k in keys:
                                if 'мм' in k or 'см' in k:
                                    continue      # явная единица — не сырьё для приора
                                v = _numval(params.get(k, ''))
                                if v is not None:
                                    groups.setdefault(f'{mid}:{role}:{dim}', []).append(v)
                                    break
                        el.clear()
    priors = {}
    for key, vals in groups.items():
        n = len(vals)
        if n < LEARN_MIN_N:
            continue
        _, role, dim = key.split(':')
        mx = role_max(role, dim)     # ролезависимый порог: ваза >60 «см» уже неправдоподобна
        share = sum(1 for v in vals if v > mx) / n
        unit = 'mm' if share >= LEARN_MM_SHARE else 'cm'
        priors[key] = {'unit': unit, 'n': n, 'share_implaus_cm': round(share, 3),
                       'role_max_cm': mx, 'version': 'v2',
                       'generated_by': 'dim_resolver --learn'}
    json.dump(priors, open(PRIORS_PATH, 'w'), ensure_ascii=False, indent=1)
    mm = [k for k, p in priors.items() if p['unit'] == 'mm']
    print(f'групп: {len(priors)}, мм-групп: {len(mm)}')
    for k in sorted(mm)[:20]:
        print('  mm:', k, priors[k])


def selftest() -> None:
    cases = [
        # (mid, name, params, role, ось, ожидание_см, ожид_source)
        (114667, 'П-образный диван Босс Софт', {'Ширина': '440', 'Высота': '88'},
         'диван', 'w', 440.0, 'prior'),   # реальные см НЕ делятся (cm-приор группы диванов)
        (99272, 'Люстра подвесная', {'Высота': '780'}, 'люстра', 'h', 78.0, 'plaus'),
        (99272, 'Тумба узкая', {'Ширина, мм': '350'}, 'тв-тумба', 'w', 35.0, 'param'),
        (116933, 'Диван Тунне 145x82x86', {'Ширина': '145'}, 'диван', 'w', 145.0, 'title'),
        # название само в мм: точное совпадение 1200==1200 единицу не раскрывает → plaus
        (116933, 'Стеллаж 1200x300x1800', {'Ширина': '1200'}, 'стеллаж', 'w', 120.0, 'plaus'),
        (99272, 'Ваза', {'Высота': '4'}, 'ваза', 'h', None, None),   # < 5 см — не пишем
        # divan.ru: свои имена параметров, единица в значении, Длина габаритная = наш фронт w
        (112923, 'Комод Монблан 185x76', {'Размеры: Длина габаритная': '185см',
         'Размеры: Ширина габаритная': '50см', 'Размеры: Высота габаритная': '76см'},
         'комод', 'w', 185.0, 'param'),
    ]
    bad = 0
    for mid, name, params, role, dim, want, want_src in cases:
        dims, ev, _ = resolve(mid, name, params, role)
        got, src = dims.get(dim), (ev.get(dim) or {}).get('source')
        ok = (got == want) and (want is None or src == want_src)
        bad += 0 if ok else 1
        print(f'{"ok " if ok else "FAIL"} {name[:32]:34} {dim}={got} (src={src}, ждали {want}/{want_src})')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    if '--learn' in sys.argv:
        learn()
    elif '--selftest' in sys.argv:
        selftest()
    else:
        print(__doc__)
