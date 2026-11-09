"""Текст объявления рядом с картинкой планировки (T-20261109-04): `<имя>-listing.txt` — строки риелтора с размерами
комнат. Разбор — чистые функции: строка → (имя, A×B м, заметки «max/into bay»); сопоставление с подписями плана по имени
(One↔1, регистр, «/», «&»). Имя в тексте есть, а на плане нет (или наоборот), повтор имени — флаг, не угадываем.

Форматы: `Lounge L:3.77m W:4.20m`, `Lounge 3.77m x 4.20m`, `Lounge 3.77 x 4.20`, `Kitchen 12'3" x 6'9"`,
`Bedroom One 4.10m (13'5") x 3.20m (10'6") max`, имя отдельной строкой над размерами.

Общая площадь (T-20261109-26): `total_area` (текст: «Total area 72.5 m²», «780 sq ft», «GIA», «общая площадь 54,3 м²»),
`sheet_area` (напечатано на листе — ответ VLM `labels2.areas`), `pick_area` (обе есть и разошлись — флаг, не угадываем);
масштаб из неё — `pipeline.area_scale`.
"""
from __future__ import annotations

import re

NUM_WORDS = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
             'nine': '9', 'ten': '10', 'eleven': '11', 'twelve': '12', 'first': '1', 'second': '2', 'third': '3',
             'fourth': '4', 'fifth': '5', 'sixth': '6', 'seventh': '7', 'eighth': '8', 'ninth': '9', 'tenth': '10'}
STOP = {'and', 'the', 'of'}

_M = r'(\d{1,2}(?:[.,]\d{1,3})?)\s*(?:m|metres|meters|mtrs?)\b'
_FT = r"(\d{1,2})\s*(?:'|’|′|ft|feet)\s*(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|”|″|''|in|inches)?)?"
_BARE = r'(\d{1,2}[.,]\d{1,3})\s*(?:x|×|by|\*)\s*(\d{1,2}[.,]\d{1,3})(?!\s*(?:\'|’|′|ft))'
NOTE_PAT = [('into bay', r'into\s+(?:the\s+)?bay'), ('max', r'\bmax(?:imum)?\b'), ('min', r'\bmin(?:imum)?\b'),
            ('narrowing', r'narrowing'), ('overall', r'\boverall\b'), ('approx', r'\bapprox')]


def _f(s: str) -> float:
    return float(s.replace(',', '.'))


def ft_in_to_m(ft: str, inch: str | None) -> float:
    return round((int(ft) * 12 + (float(inch) if inch else 0.0)) * 0.0254, 3)


def parse_line(line: str) -> dict | None:
    """Одна строка → {'name', 'dims_m': (a, b), 'unit': 'm'|'ft', 'notes': [...], 'dims_ft_m'?, 'conflict'?} или None,
    если двух размеров нет. Имя — текст до первого числа (без «L:», «:», «-»); пустое имя — None (возьмёт строку выше)."""
    s = ' '.join(line.replace('\t', ' ').split())
    if not s:
        return None
    low = s.lower()
    met = [(m.start(), _f(m.group(1))) for m in re.finditer(_M, low)]
    ft = [(m.start(), ft_in_to_m(m.group(1), m.group(2))) for m in re.finditer(_FT, low)]
    bare = [(m.start(), (_f(m.group(1)), _f(m.group(2)))) for m in re.finditer(_BARE, low)]
    dims, unit, start = None, None, None
    if len(met) >= 2:
        dims, unit, start = (met[0][1], met[1][1]), 'm', met[0][0]
    elif bare:
        dims, unit, start = bare[0][1], 'm', bare[0][0]
    elif len(ft) >= 2:
        dims, unit, start = (ft[0][1], ft[1][1]), 'ft', ft[0][0]
    if dims is None or not all(0.3 <= v <= 40 for v in dims):
        return None
    if ft:
        start = min(start, ft[0][0])
    m_lw = re.search(r'\b[lw]\s*[:=]', low)
    if m_lw:
        start = min(start, m_lw.start())
    name = re.sub(r'[\s:;,\-–—(]+$', '', s[:start]).strip()
    name = re.sub(r'^[\s\-–—•*·]+', '', name)
    notes = [k for k, p in NOTE_PAT if re.search(p, low)]
    out = {'name': name or None, 'dims_m': tuple(round(v, 3) for v in dims), 'unit': unit, 'notes': notes, 'raw': s}
    if unit == 'm' and len(ft) >= 2:                       # футы рядом с метрами — сверка чтения
        fm = (ft[0][1], ft[1][1])
        out['dims_ft_m'] = fm
        if max(abs(fm[0] - dims[0]), abs(fm[1] - dims[1])) > 0.08:
            out['conflict'] = 'метры ≠ футы'
    return out


def parse_listing(text: str) -> list[dict]:
    """Весь текст → строки с размерами; строка без имени берёт ближайшую строку выше без размеров."""
    rows, prev = [], None
    for line in text.splitlines():
        r = parse_line(line)
        if r is None:
            t = ' '.join(line.split()).strip(' :-–—•*')
            if t and len(t) <= 60 and re.search(r'[A-Za-z]', t):
                prev = t
            continue
        if r['name'] is None:
            if prev is None:
                continue
            r['name'] = prev
        prev = None
        rows.append(r)
    return rows


def norm_name(name: str) -> str:
    """Ключ сопоставления: регистр, «/» «&» «-» → пробел, слова-числа → цифры (One↔1), «and/the» убраны,
    ведущие нули чисел — нет. «Bedroom One» = «bedroom 1» = «BEDROOM 1»; «Kitchen/Diner» = «Kitchen & Diner»."""
    s = name.lower().replace('&', ' ').replace('/', ' ').replace('+', ' ')
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    toks = []
    for w in s.split():
        w = NUM_WORDS.get(w, w)
        if w in STOP:
            continue
        if w.isdigit():
            w = str(int(w))
        toks.append(w)
    return ' '.join(toks)


def dims_agree(a, b, tol_abs: float = 0.05, tol_rel: float = 0.02) -> bool:
    """Две пары размеров совпадают (порядок сторон не важен) в max(5 см, 2 %)."""
    def ok(x, y):
        return abs(x - y) <= max(tol_abs, tol_rel * max(x, y))
    return (ok(a[0], b[0]) and ok(a[1], b[1])) or (ok(a[0], b[1]) and ok(a[1], b[0]))


def match(plan_labels: list[dict], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """plan_labels: [{'name', 'dims'|None, ...}] (подписи плана, прочитанные VLM) ← строки текста.
    → (подписи с полями 'dims' (итог), 'dims_src' plan|text|both, 'text_flags'), строки текста без пары (с причиной).
    Пара — только по совпадению ключа имени и только один-к-одному: повтор ключа на любой стороне — флаг, размер
    из текста не берём. Есть и на плане, и в тексте: совпали → both; разошлись → флаг, остаётся размер плана."""
    from collections import Counter
    pk = Counter(norm_name(l['name']) for l in plan_labels)
    tk = Counter(norm_name(r['name']) for r in rows)
    by_t = {}
    for r in rows:
        by_t.setdefault(norm_name(r['name']), []).append(r)
    out = []
    for l in plan_labels:
        l = dict(l)
        k = norm_name(l['name'])
        fl = list(l.get('text_flags', []))
        src = 'plan' if l.get('dims') else None
        if tk.get(k, 0) == 0:
            if rows:
                fl.append('нет в тексте')
        elif tk[k] > 1 or pk[k] > 1:
            fl.append('повтор имени — текст не взят')
        else:
            r = by_t[k][0]
            if r.get('conflict'):
                fl.append('текст: ' + r['conflict'])
            if r['notes']:
                fl.append('текст: ' + '/'.join(r['notes']))
            if l.get('dims'):
                if dims_agree(l['dims'], r['dims_m']):
                    src = 'both'
                else:
                    fl.append(f'текст {r["dims_m"][0]}×{r["dims_m"][1]} ≠ план')
            else:
                l['dims'] = tuple(r['dims_m'])
                src = 'text'
            l['text_row'] = r['raw']
        l['dims_src'] = src
        l['text_flags'] = fl
        out.append(l)
    orphans = []
    for r in rows:
        k = norm_name(r['name'])
        if pk.get(k, 0) == 0:
            orphans.append(dict(r, why='в тексте есть, на плане не найдено'))
        elif pk[k] > 1 or tk[k] > 1:
            orphans.append(dict(r, why='повтор имени'))
    return out, orphans


# ── общая площадь (T-20261109-26, задача С): «Total area 72.5 m²», «780 sq ft», «GIA», «общая площадь 54,3 м²» ──

SQFT_M2 = 0.09290304
AREA_MIN_M2, AREA_MAX_M2 = 10.0, 5000.0
_NUM = r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)'
_U_M2 = r'(?:m²|m2\b|sq\.?\s*m(?:trs?|etres?|eters?)?\b|sqm\b|square\s+met(?:re|er)s?\b|м²|м2|кв\.?\s*м\b)'
_U_FT = r'(?:sq\.?\s*ft\b|sqft\b|ft²|ft2\b|square\s+f(?:ee|oo)t\b)'
_AREA_RX = re.compile(_NUM + r'\s*(' + _U_M2 + '|' + _U_FT + ')', re.I)
TOTAL_KEY = re.compile(r'total|\bgia\b|gross\s+internal|internal\s+(?:floor\s+)?area|floor\s+area|overall\s+area|'
                       r'approx(?:imate|\.)?\s+(?:gross\s+)?(?:internal\s+)?(?:floor\s+)?area|общ\w*\s+площад|площад\w*\s+общ|'
                       r'\bs\s*общ|итого', re.I)
# что площадь НЕ включает: «excl. garage», «excluding balconies», «без балкона» → корни слов для сравнения с комнатами
EXCL_RX = re.compile(r'(?:excl(?:uding|udes|\.|\b)|not\s+including|without|без(?:\s+учёта|\s+учета)?)\s*:?\s*([^)\n;]{1,80})', re.I)
OPEN_AIR = ('balcon', 'terrace', 'patio', 'deck', 'veranda', 'loggia', 'roof garden', 'балкон', 'лоджи', 'террас', 'веранд')
EXCL_ROOTS = OPEN_AIR + ('garage', 'outbuilding', 'shed', 'store', 'loft', 'cellar', 'basement', 'annex', 'гараж', 'подвал',
                         'чердак', 'кладов')


def _num(s: str) -> float:
    """«1,347» (тысячи) / «54,3» (десятичная запятая) / «72.5»."""
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', s):
        return float(s.replace(',', ''))
    return float(s.replace(',', '.'))


def _figures(s: str) -> list[tuple[int, float, str]]:
    """Все площади в строке → [(позиция, м², 'm2'|'ft')]."""
    out = []
    for m in _AREA_RX.finditer(s):
        try:
            v = _num(m.group(1))
        except ValueError:
            continue
        ft = re.fullmatch(_U_FT, m.group(2), re.I) is not None
        out.append((m.start(), round(v * SQFT_M2, 2) if ft else v, 'ft' if ft else 'm2'))
    return out


def _excl(s: str) -> list[str]:
    roots = []
    for m in EXCL_RX.finditer(s):
        low = m.group(1).lower()
        roots += [r for r in EXCL_ROOTS if r in low]
    return list(dict.fromkeys(roots))


def _pair(figs: list) -> tuple[float, list]:
    """Площади одного утверждения (м² и/или фт² рядом) → (м², флаги); м² и фт² разошлись > 3 % — флаг, берём м²."""
    m2 = [v for _, v, u in figs if u == 'm2']
    ft = [v for _, v, u in figs if u == 'ft']
    fl = []
    if m2 and ft and abs(m2[0] - ft[0]) > 0.03 * max(m2[0], ft[0]):
        fl.append('area_m2_ne_sqft')
    return (m2 or ft)[0], fl


# площадь в строке с названием помещения — площадь этого помещения, не квартиры
ROOM_WORD = re.compile(r'bed|lounge|living|kitchen|dining|diner|bath|shower|w\.?c\b|hall|landing|study|office|utility|garage|'
                       r'store|reception|sitting|family|conservatory|спальн|гостин|кухн|ванн|санузел|прихож|коридор|кабинет|'
                       r'комнат|балкон|лоджи', re.I)


def total_area(text: str) -> dict | None:
    """Общая площадь из текста объявления → {'m2', 'src': 'text', 'approx', 'excl': [...], 'conv': 'gia'|'rooms', 'raw', 'flags'}
    или None. Сначала строка с ключом («Total area», «GIA», «общая площадь»); ключа нет — единственная площадь в тексте.
    Несколько разных площадей с ключом — None (неясно, какая общая, флаг не угадываем). `conv`: русская «общая площадь» —
    сумма помещений без стен (`rooms`), британская Total/GIA — по внутренней грани наружных стен с внутренними (`gia`)."""
    if not text or not text.strip():
        return None
    lines = [' '.join(ln.split()) for ln in text.splitlines()]
    keyed, loose = [], []
    for i, s in enumerate(lines):
        figs = _figures(s)
        if not figs:
            continue
        ctx = (lines[i - 1] + ' ' + s) if i and not _figures(lines[i - 1]) else s   # ключ строкой выше: «Total area» / «780 sq ft»
        v, fl = _pair(figs)
        rec = {'m2': round(v, 2), 'flags': fl, 'raw': s[:200], 'ctx': ctx}
        if TOTAL_KEY.search(ctx):
            keyed.append(rec)
        elif not ROOM_WORD.search(s[:figs[0][0]]):
            loose.append(rec)
    pick = keyed or loose
    vals = sorted({round(r['m2'], 1) for r in pick})
    if not vals or (len(vals) > 1 and vals[-1] - vals[0] > 0.02 * vals[-1]):
        return None
    r = pick[0]
    if not AREA_MIN_M2 <= r['m2'] <= AREA_MAX_M2:
        return None
    ctx = r['ctx']
    cyr = bool(re.search(r'[а-яё]', ctx, re.I))
    return {'m2': r['m2'], 'src': 'text', 'approx': bool(re.search(r'approx|приблиз|около|~|≈', ctx, re.I)), 'excl': _excl(ctx),
            'conv': 'rooms' if cyr else 'gia', 'raw': r['raw'], 'flags': r['flags'] + ([] if keyed else ['area_unlabeled'])}


def sheet_area(areas: list | None) -> dict | None:
    """Площади, напечатанные на листе (ответ VLM `labels2.areas`: [{'label', 'm2'}]) → общая площадь или None.
    Подпись с «total/GIA/…» — она (несколько — наибольшая: обычно «с гаражом», исключения — из её подписи);
    без такой подписи — сумма всех (этажи/корпуса по отдельности; флаг `area_sum_of_parts`)."""
    rows = []
    for a in areas or []:
        try:
            v = float(a.get('m2'))
        except (TypeError, ValueError, AttributeError):
            continue
        if v > 0:
            rows.append((str(a.get('label') or ''), v))
    if not rows:
        return None
    tot = [r for r in rows if TOTAL_KEY.search(r[0])]
    if tot:
        label, v = max(tot, key=lambda r: r[1])
        fl = []
    else:
        label, v, fl = ' + '.join(r[0] for r in rows)[:200], sum(r[1] for r in rows), (['area_sum_of_parts'] if len(rows) > 1 else [])
    if not AREA_MIN_M2 <= v <= AREA_MAX_M2:
        return None
    cyr = bool(re.search(r'[а-яё]', label, re.I))
    return {'m2': round(v, 2), 'src': 'sheet', 'approx': bool(re.search(r'approx|приблиз', label, re.I)), 'excl': _excl(label),
            'conv': 'rooms' if cyr else 'gia', 'raw': label[:200], 'flags': fl}


def pick_area(text_a: dict | None, sheet_a: dict | None, tol: float = 0.05) -> tuple[dict | None, list]:
    """Текст и лист → одна общая площадь и флаги. Обе есть и разошлись > tol — None + `area_conflict` (не угадываем)."""
    if text_a and sheet_a:
        if abs(text_a['m2'] - sheet_a['m2']) > tol * max(text_a['m2'], sheet_a['m2']):
            return None, ['area_conflict']
        return dict(text_a, src='both', excl=list(dict.fromkeys(text_a['excl'] + sheet_a['excl'])),
                    flags=text_a['flags'] + sheet_a['flags']), []
    a = text_a or sheet_a
    return a, []
