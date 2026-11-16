"""T-20261116-60: сверка площади каждого разобранного этажа с площадью, напечатанной на листе (этап 1, «тень»).

Только ПРОВЕРКА, не опора масштаба: подгонка масштаба этажа под его площадь обнуляет саму проверку, а пропуск комнаты
превращает в раздувание остальных (план `trial-floor-area-check-01`, разбор Codex 16.11). Результат — список `areaChecks`
результата разбора (`contracts/trial.ts`); на показ, флаги комнат и `awaiting_check` он не влияет.

Три решения, общие для всех листов (RU/UK), без ID листов и туров:
• МЕРА — как напечатано: `gia` (британская GIA / «floor area») ↔ `gia_m2` панели (при масштабе по площади — × k²: модели уже
  умножены, `gia_m2` нет); `rooms` (русская «общая площадь», «площадь этажа») ↔ сумма ГЕОМЕТРИЧЕСКИХ площадей комнат модели
  (не `areaM2` результата: её заменяет напечатанная площадь комнаты `area_shown` — сверка стала бы круговой); NIA, жилая,
  полезная, «restricted head height» и прочее — `unknown`, число не сверяется.
• ПРИВЯЗКА площади к панели — только при высокой уверенности: точное совпадение нормализованного заголовка с уникальным
  заголовком панели (`title`); заголовок панели внутри подписи площади (`title_in_label`); единственная нетотальная площадь
  при единственном логическом рисунке (`single`). Иначе — `inconclusive`. Не по порядку, не по ближайшей рамке, не по
  расстоянию правки; «House»/«Outbuildings» — группы рисунков, к этажу не привязываются (`group`).
• ПОРОГ — `|√(получено / напечатано) − 1| > 5 %` И `|разница| > 3 м²` (5 % линейно ≈ 10 % площади: эталон B, +8,3 %, проходит;
  пропущенная комната ловится). «Примерно» (approx) — мягче: 7,5 % и 5 м².
Там, где вероятнее ошибка привязки (панели поделены по догадке, заголовки слиплись, контуры VLM и заголовки разошлись, прочитаны
не все страницы PDF, один рисунок разбит на куски), статус не выше `inconclusive`. Слияние двух комнат площадью не ловится
(GIA не меняется) — для него остаются флаг `merged` и покрытие подписей.
"""
from __future__ import annotations

import math
import re

MISMATCH_REL, MISMATCH_M2 = 0.05, 3.0          # линейная мера (√ отношения площадей) и разница м²
APPROX_REL, APPROX_M2 = 0.075, 5.0             # у «примерно»
BLOCKERS = ('panel_title_guess', 'panel_titles_merged', 'vlm_panels_disagree', 'area_pages_skipped')

_CYR = re.compile(r'[а-яё]', re.I)
_APPROX = re.compile(r'approx|приблиз|около|~|≈', re.I)
# мера не GIA и не «общая»: другая методика — число не сверяем
_UNKNOWN = re.compile(r'\bnia\b|net\s+internal|saleable|salable|usable|living\s+area|habitable|жил\w*|полезн\w*|head\s*height|headroom|'
                      r'restricted|eaves|1[.,]5\s*m\b|приведен\w*|понижающ\w*', re.I)
_RU_ROOMS = re.compile(r'общ\w*|площад\w*\s+этаж\w*|этаж\w*|итого', re.I)
# группа рисунков, а не этаж: «House 611», «Outbuildings 184» — к этажу не привязываем
GROUPS = {'house', 'main house', 'outbuildings', 'outbuilding', 'annexe', 'annex', 'dwelling', 'property'}
_NOISE = {'total', 'gia', 'gross', 'internal', 'area', 'approx', 'approximate', 'm2', 'sq', 'ft', 'of', 'the', 'inc', 'incl', 'excl'}


def norm(s) -> str:
    """Заголовок/подпись для точного сравнения: нижний регистр, без знаков, один пробел."""
    return ' '.join(re.sub(r'[^\w]+', ' ', str(s or '').lower()).split())


def is_excluded(names, excl) -> bool:
    """Комната вне площади: балкон/терраса и то, что подпись исключает («excl. garage»)."""
    import listing
    s = ' '.join(names or []).lower()
    return any(r in s for r in tuple(listing.OPEN_AIR) + tuple(excl or ()))


def measure_of(label: str) -> str:
    """Мера напечатанной площади: gia | rooms | unknown (по формулировке подписи)."""
    if _UNKNOWN.search(label or ''):
        return 'unknown'
    if _CYR.search(label or ''):
        return 'rooms' if _RU_ROOMS.search(label) else 'unknown'
    return 'gia'


def is_group(label: str) -> bool:
    core = ' '.join(t for t in norm(label).split() if t not in _NOISE)
    return core in GROUPS


def is_total(label: str) -> bool:
    import listing
    return bool(listing.TOTAL_KEY.search(label or ''))


def compare(printed: float, got: float, approx: bool = False) -> tuple[str, float]:
    """Напечатанная против полученной площади → (ok | mismatch, масштабное расхождение √(got/printed) − 1).
    mismatch — только когда расходятся ОБА условия: линейно дальше порога И по метрам дальше порога."""
    rel, absm = (APPROX_REL, APPROX_M2) if approx else (MISMATCH_REL, MISMATCH_M2)
    delta = math.sqrt(max(got, 0.0) / printed) - 1
    bad = round(abs(delta), 6) > rel and round(abs(got - printed), 6) > absm
    return ('mismatch' if bad else 'ok'), delta


def reconstructed_m2(P: dict, measure: str, models: dict | None, k2: float, excl) -> float | None:
    """Площадь панели в мере печати, м²: `gia` — gia_m2 × k² (модели уже × k, gia_m2 — нет), `rooms` — сумма площадей
    комнат модели (уже × k²); без исключённого. Нет данных — None."""
    m = (models or {}).get(tuple(P['bbox_px'])) if models is not None else None
    rooms = (m or {}).get('rooms') or []
    ex = sum(float(r.get('area_m2') or 0) for r in rooms if is_excluded(r.get('names'), excl))
    if measure == 'gia':
        g = P.get('gia_m2')
        if g is None:
            return None
        return max(0.0, float(g) * k2 - ex)
    if measure == 'rooms':
        if m is None:
            return None
        return max(0.0, sum(float(r.get('area_m2') or 0) for r in rooms) - ex)
    return None


def _contains(label_t: list, title_t: list) -> bool:
    n = len(title_t)
    return n > 0 and any(label_t[i:i + n] == title_t for i in range(len(label_t) - n + 1))


def _assoc(row: dict, pans: list) -> tuple[str, dict | None]:
    """Площадь → панель по заголовкам. → (способ, панель | None); способ: title | title_in_label | group | total | none."""
    lab = row['label']
    if is_group(lab):
        return 'group', None
    ln = norm(lab)
    uniq = [p for p in pans if p['tn'] and sum(1 for q in pans if q['tn'] == p['tn']) == 1]
    ex = [p for p in uniq if p['tn'] == ln]
    if len(ex) == 1:
        return 'title', ex[0]
    lt = ln.split()
    inn = [p for p in uniq if _contains(lt, p['tn'].split())]
    # заголовок, лежащий внутри другого найденного («Floor» в «First Floor»), не считается: берётся самый полный
    inn = [p for p in inn if not any(q is not p and q['tn'] != p['tn'] and _contains(q['tn'].split(), p['tn'].split()) for q in inn)]
    if len(inn) == 1:
        return 'title_in_label', inn[0]
    if is_total(lab):
        return 'total', None
    return 'none', None


def _rows(areas) -> list:
    out = []
    for a in areas or []:
        try:
            v = float(a.get('m2'))
        except (TypeError, ValueError, AttributeError):
            continue
        if v > 0 and math.isfinite(v):
            out.append({'label': ' '.join(str(a.get('label') or '').split()), 'm2': v})
    return out


def floor_area_checks(areas, panels, *, models: dict | None = None, k: dict | None = None, scale_status: str = '',
                      blockers=(), panels_src: str | None = None, titles: dict | None = None, nd: int = 2) -> list:
    """Площади листа (`areas` VLM: [{label, m2}], как есть, до свёртки в одно число) × панели журнала (`log['panels']`) →
    `areaChecks`. Строка без привязки к панели — запись `inconclusive` (group / sheet); «общая» многоэтажного листа — не здесь
    (её сверка — `pipeline.scale_of`, агрегатная).
    `models` — модели панелей по рамке (после `_scale_model`); без них мера `rooms` недоступна. `k` — множитель метров по рамке
    (масштаб по площади). `blockers` — флаги листа; из BLOCKERS ограничивают статус до inconclusive. `panels_src` — как поделён
    лист (`titles` | `vlm` | `pieces`): куски без заголовков — один рисунок разбит, проверять отдельный кусок нельзя.
    `titles` — {индекс панели: заголовок} вместо `vlm_title` (стенд: заголовок из золота)."""
    rows = _rows(areas)
    if not rows:
        return []
    k = k or {}
    pans = []
    for i, P in enumerate(panels):
        if models is not None and tuple(P['bbox_px']) not in models:
            continue                                            # как `to_result`: панель без модели в результат не идёт
        t = (titles or {}).get(i, P.get('vlm_title'))
        pans.append({'i': i, 'id': f'p{i}', 'P': P, 'tn': norm(t)})
    if not pans:
        return []
    block = [f for f in BLOCKERS if f in set(blockers or ())]
    pieces = panels_src == 'pieces' and len(pans) > 1
    for r in rows:
        r['how'], r['pan'] = _assoc(r, pans)
    # единственный логический рисунок: единственная нетотальная площадь (или единственная строка вообще, хоть «Total»)
    nontot = [r for r in rows if r['how'] != 'total']
    if len(pans) == 1 and not pieces:
        one = None
        if len(nontot) == 1 and nontot[0]['how'] == 'none':
            one = nontot[0]
        elif not nontot and len(rows) == 1:
            one = rows[0]
        if one is not None:
            one['how'], one['pan'] = 'single', pans[0]
    out, by_pan = [], {}
    for r in rows:
        if r['pan'] is not None:
            by_pan.setdefault(r['pan']['id'], []).append(r)
    for r in rows:
        meas = measure_of(r['label'])
        base = {'label': r['label'][:120], 'printedM2': round(r['m2'], nd), 'measure': meas}
        if r['how'] == 'total':
            continue                                            # агрегат листа — `scale_of`
        if r['pan'] is None:
            out.append(dict(base, scope='group' if r['how'] == 'group' else 'sheet', panelIds=[], status='inconclusive',
                            association='group' if r['how'] == 'group' else 'none',
                            note='group_not_floor' if r['how'] == 'group' else 'no_panel_match'))
            continue
        pan, note = r['pan'], None
        same = by_pan[pan['id']]
        if len({round(x['m2'], 1) for x in same}) > 1:
            note = 'ambiguous_rows'                             # две разные площади на один рисунок — какая его, не знаем
        entry = dict(base, scope='panel', panelIds=[pan['id']], association=r['how'])
        approx = bool(_APPROX.search(r['label']))
        got = None
        if meas != 'unknown':
            import listing
            excl = listing._excl(r['label'])
            bb = tuple(pan['P']['bbox_px'])
            got = reconstructed_m2(pan['P'], meas, models, float(k.get(bb, 1.0)) ** 2, excl)
        if got is not None and got > 0:
            status, delta = compare(r['m2'], got, approx)
            entry['reconstructedM2'] = round(got, nd)
            entry['scaleDelta'] = round(delta, 4)
        else:
            status = 'inconclusive'
            note = note or ('measure_unknown' if meas == 'unknown' else 'no_geometry')
        if status != 'inconclusive':
            if note:
                status = 'inconclusive'
            elif block:
                status, note = 'inconclusive', f'blocked:{block[0]}'
            elif pieces:
                status, note = 'inconclusive', 'pieces'
            elif scale_status == 'area' and len(pans) == 1:
                status, note = 'inconclusive', 'circular_area_scale'     # масштаб один, подогнан под эту же площадь
        entry['status'] = status
        if note:
            entry['note'] = note
        out.append(entry)
    return out
