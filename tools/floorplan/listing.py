"""Текст объявления рядом с картинкой планировки (T-20261109-04): `<имя>-listing.txt` — строки риелтора с размерами
комнат. Разбор — чистые функции: строка → (имя, A×B м, заметки «max/into bay»); сопоставление с подписями плана по имени
(One↔1, регистр, «/», «&»). Имя в тексте есть, а на плане нет (или наоборот), повтор имени — флаг, не угадываем.

Форматы: `Lounge L:3.77m W:4.20m`, `Lounge 3.77m x 4.20m`, `Lounge 3.77 x 4.20`, `Kitchen 12'3" x 6'9"`,
`Bedroom One 4.10m (13'5") x 3.20m (10'6") max`, имя отдельной строкой над размерами.

Русский текст агента (T-20261109-33, «размеры своими словами»): «гостиная 4,2 на 3,8», «спальня 3×3» (целые — только в строке
с кириллицей), «кухня 10 м²» (площадь комнаты — поле `area_m2`, стороны не выдумываем), «Комната 1», «вторая спальня»; единицы
«м/метра», разделители «на / x / × / х». Имена RU↔EN сопоставляются по ВИДУ комнаты и номеру (`room_kind`: «гостиная» ↔ Lounge /
Living Room, «спальня 1» ↔ Bedroom 1) — только если одна из сторон по-русски и пара однозначна с обеих сторон; английское ↔
английское — как раньше, по точному ключу имени.

Общая площадь (T-20261109-26): `total_area` (текст: «Total area 72.5 m²», «780 sq ft», «GIA», «общая площадь 54,3 м²»),
`sheet_area` (напечатано на листе — ответ VLM `labels2.areas`), `pick_area` (обе есть и разошлись — флаг, не угадываем);
масштаб из неё — `pipeline.area_scale`.
"""
from __future__ import annotations

import re

NUM_WORDS = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
             'nine': '9', 'ten': '10', 'eleven': '11', 'twelve': '12', 'first': '1', 'second': '2', 'third': '3',
             'fourth': '4', 'fifth': '5', 'sixth': '6', 'seventh': '7', 'eighth': '8', 'ninth': '9', 'tenth': '10'}
NUM_WORDS_RU = {'один': '1', 'одна': '1', 'первая': '1', 'первый': '1', 'два': '2', 'две': '2', 'вторая': '2', 'второй': '2',
                'три': '3', 'третья': '3', 'третий': '3', 'четыре': '4', 'четвертая': '4', 'четвертый': '4', 'пять': '5',
                'пятая': '5', 'пятый': '5', 'шесть': '6', 'шестая': '6'}
STOP = {'and', 'the', 'of', 'и', 'я', 'й', 'ая', 'ой'}

_M = r'(\d{1,2}(?:[.,]\d{1,3})?)\s*(?:m|metres|meters|mtrs?|м|метр(?:а|ов)?)\b'      # «м» перед «²/2» — не метр (\b)
_FT = r"(\d{1,2})\s*(?:'|’|′|ft|feet)\s*(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|”|″|''|in|inches)?)?"
_SEP = r'\s*(?:x|×|х|by|на|\*)\s*'                                               # «х» — кириллица
_BARE = r'(\d{1,2}[.,]\d{1,3})' + _SEP + r'(\d{1,2}[.,]\d{1,3})(?!\s*(?:\'|’|′|ft))'
_BARE_INT = r'(?<![\d.,])(\d{1,2}(?:[.,]\d{1,3})?)' + _SEP + r'(\d{1,2}(?:[.,]\d{1,3})?)(?![\d\'’′]|\s*(?:ft|м²|м2|m²|m2))'
_ROOM_AREA = r'(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:м²|м2\b|кв\.?\s*м\b|m²|m2\b|sq\.?\s*m\b|sqm\b)'
CYR = re.compile(r'[а-яё]', re.I)
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
    if not bare and CYR.search(low):                       # «спальня 3×3», «3 на 4 м» — целые только у русского текста
        bare = [(m.start(), (_f(m.group(1)), _f(m.group(2)))) for m in re.finditer(_BARE_INT, low)]
    dims, unit, start = None, None, None
    if len(met) >= 2:
        dims, unit, start = (met[0][1], met[1][1]), 'm', met[0][0]
    elif bare:
        dims, unit, start = bare[0][1], 'm', bare[0][0]
    elif len(ft) >= 2:
        dims, unit, start = (ft[0][1], ft[1][1]), 'ft', ft[0][0]
    if dims is None:
        return _area_row(s, low)
    if not all(0.3 <= v <= 40 for v in dims):
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


def _area_row(s: str, low: str) -> dict | None:
    """Строка без двух сторон, но с площадью КОМНАТЫ («кухня 10 м²», «Bedroom 2 9.8 m²») → {'name', 'dims_m': None, 'area_m2'}.
    Общая площадь («Общая площадь 54 м²», «GIA …») и площадь без названия комнаты — не строка комнаты (это `total_area`)."""
    m = re.search(_ROOM_AREA, low)
    if not m or TOTAL_KEY.search(low) or not ROOM_WORD.search(low[:m.start()]):
        return None
    v = _f(m.group(1))
    if not 1.0 <= v <= 200.0:
        return None
    name = re.sub(r'[\s:;,\-–—(=]+$', '', s[:m.start()]).strip()
    name = re.sub(r'^[\s\-–—•*·]+', '', name)
    if not name:
        return None
    return {'name': name, 'dims_m': None, 'area_m2': round(v, 2), 'unit': 'm2', 'notes': [], 'raw': s}


def parse_listing(text: str) -> list[dict]:
    """Весь текст → строки с размерами; строка без имени берёт ближайшую строку выше без размеров. Строка с одной площадью
    комнаты (`area_m2`, без сторон) той же комнаты, что строка со сторонами, — не вторая строка, а поле той (иначе повтор имени)."""
    rows, prev = [], None
    for line in text.splitlines():
        r = parse_line(line)
        if r is None:
            t = ' '.join(line.split()).strip(' :-–—•*')
            if t and len(t) <= 60 and re.search(r'[A-Za-zА-Яа-яЁё]', t):
                prev = t
            continue
        if r['name'] is None:
            if prev is None:
                continue
            r['name'] = prev
        prev = None
        rows.append(r)
    sized = {norm_name(r['name']): r for r in rows if r.get('dims_m')}
    out = []
    for r in rows:
        twin = sized.get(norm_name(r['name'])) if not r.get('dims_m') else None
        if twin is not None:
            twin.setdefault('area_m2', r['area_m2'])
            continue
        out.append(r)
    return out


def norm_name(name: str) -> str:
    """Ключ сопоставления: регистр, «/» «&» «-» → пробел, слова-числа → цифры (One↔1, «вторая»↔2), «and/the» убраны,
    ведущие нули чисел — нет, «ё» = «е». «Bedroom One» = «bedroom 1» = «BEDROOM 1»; «Kitchen/Diner» = «Kitchen & Diner»;
    «Спальня 1» = «спальня первая»."""
    s = name.lower().replace('ё', 'е').replace('&', ' ').replace('/', ' ').replace('+', ' ')
    s = re.sub(r'[^a-z0-9а-я ]+', ' ', s)
    toks = []
    for w in s.split():
        w = NUM_WORDS.get(w, NUM_WORDS_RU.get(w, w))
        if w in STOP:
            continue
        if w.isdigit():
            w = str(int(w))
        toks.append(w)
    return ' '.join(toks)


# вид комнаты для сопоставления RU↔EN: первый узнанный корень слова (порядок важен: «кухня-гостиная» — кухня)
KIND_ROOTS = [('kitchen', ('kitchen', 'кухн')), ('living', ('lounge', 'living', 'sitting', 'reception', 'drawing', 'гостин', 'зал')),
              ('bedroom', ('bedroom', 'bed', 'master', 'спальн', 'детск')), ('dining', ('dining', 'diner', 'столов')),
              ('bathroom', ('bathroom', 'bath', 'shower', 'ensuite', 'ванн', 'душ', 'санузел')),
              ('wc', ('wc', 'toilet', 'cloakroom', 'cloaks', 'туалет', 'уборн')),
              ('hall', ('hallway', 'hall', 'entrance', 'lobby', 'прихож', 'коридор', 'холл')),
              ('study', ('study', 'office', 'кабинет')), ('utility', ('utility', 'laundry', 'постироч')),
              ('store', ('storage', 'store', 'cupboard', 'closet', 'pantry', 'кладов', 'гардероб')),
              ('balcony', ('balcony', 'terrace', 'балкон', 'лоджи', 'террас')), ('garage', ('garage', 'гараж')),
              ('room', ('room', 'комнат', 'жил'))]


def room_kind(name: str) -> tuple[str | None, str | None]:
    """Имя → (вид, номер) для сопоставления RU↔EN: «Гостиная» → ('living', None), «Bedroom Two» → ('bedroom', '2'),
    «вторая спальня» → ('bedroom', '2'), «Комната 1» → ('room', '1'). Вид не узнан — (None, номер)."""
    toks = norm_name(name).split()
    num = next((t for t in toks if t.isdigit()), None)
    for t in toks:
        for kind, roots in KIND_ROOTS:
            if any(t == r or (len(r) >= 3 and t.startswith(r)) for r in roots):
                return kind, num
    return None, num


def dims_agree(a, b, tol_abs: float = 0.05, tol_rel: float = 0.02) -> bool:
    """Две пары размеров совпадают (порядок сторон не важен) в max(5 см, 2 %)."""
    def ok(x, y):
        return abs(x - y) <= max(tol_abs, tol_rel * max(x, y))
    return (ok(a[0], b[0]) and ok(a[1], b[1])) or (ok(a[0], b[1]) and ok(a[1], b[0]))


def match(plan_labels: list[dict], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """plan_labels: [{'name', 'dims'|None, ...}] (подписи плана, прочитанные VLM) ← строки текста.
    → (подписи с полями 'dims' (итог), 'dims_src' plan|text|both, 'text_flags'), строки текста без пары (с причиной).
    Пара — только по совпадению ключа имени и только один-к-одному: повтор ключа на любой стороне — флаг, размер
    из текста не берём. Есть и на плане, и в тексте: совпали → both; разошлись → флаг, остаётся размер плана.
    Имя по-русски хотя бы с одной стороны и точного ключа нет — пара по виду комнаты и номеру (`room_kind`), тоже один-к-одному
    (`text_match: kind`); текст без номера («спальня») — к единственной комнате этого вида на плане. Строка с одной площадью
    (`area_m2`, без сторон) — поле `text_area_m2` у подписи, размер не подменяет."""
    from collections import Counter
    pkey = [norm_name(l['name']) for l in plan_labels]
    tkey = [norm_name(r['name']) for r in rows]
    pk, tk = Counter(pkey), Counter(tkey)
    pair, how = {}, {}                                   # индекс подписи → индекс строки текста; как сопоставили
    for i, k in enumerate(pkey):
        if pk[k] == 1 and tk.get(k, 0) == 1:
            pair[i], how[i] = tkey.index(k), 'name'
    # RU↔EN: подписи без строки с тем же ключом и строки без подписи с тем же ключом — по виду и номеру, однозначно
    free_p = [i for i, k in enumerate(pkey) if tk.get(k, 0) == 0]
    free_t = [j for j, k in enumerate(tkey) if pk.get(k, 0) == 0]
    pkind = {i: room_kind(plan_labels[i]['name']) for i in free_p}
    tkind = {j: room_kind(rows[j]['name']) for j in free_t}
    unsure = set()
    for j in free_t:
        kind, num = tkind[j]
        if kind is None:
            continue
        cyr_t = bool(CYR.search(rows[j]['name']))
        cand = [i for i in free_p if i not in pair and pkind[i][0] == kind and (cyr_t or CYR.search(plan_labels[i]['name']))
                and (num is None or pkind[i][1] == num)]
        rivals = [x for x in free_t if x != j and tkind[x][0] == kind and (num is None or tkind[x][1] in (None, num))]
        if len(cand) == 1 and not rivals:
            pair[cand[0]], how[cand[0]] = j, 'kind'
        elif cand:
            unsure.add(j)
    used = set(pair.values())
    out = []
    for i, l in enumerate(plan_labels):
        l = dict(l)
        k = pkey[i]
        fl = list(l.get('text_flags', []))
        src = 'plan' if l.get('dims') else None
        if i not in pair:
            if tk.get(k, 0) > 1 or (tk.get(k, 0) and pk[k] > 1):
                fl.append('повтор имени — текст не взят')
            elif rows:
                fl.append('нет в тексте')
        else:
            r = rows[pair[i]]
            if r.get('conflict'):
                fl.append('текст: ' + r['conflict'])
            if r['notes']:
                fl.append('текст: ' + '/'.join(r['notes']))
            if r.get('area_m2'):
                l['text_area_m2'] = r['area_m2']
            if not r.get('dims_m'):
                pass                                     # одна площадь — сторон не выдумываем
            elif l.get('dims'):
                if dims_agree(l['dims'], r['dims_m']):
                    src = 'both'
                else:
                    fl.append(f'текст {r["dims_m"][0]}×{r["dims_m"][1]} ≠ план')
            else:
                l['dims'] = tuple(r['dims_m'])
                src = 'text'
            l['text_row'] = r['raw']
            l['text_match'] = how[i]
        l['dims_src'] = src
        l['text_flags'] = fl
        out.append(l)
    orphans = []
    for j, r in enumerate(rows):
        if j in used:
            continue
        k = tkey[j]
        why = ('повтор имени' if pk.get(k, 0) > 1 or tk[k] > 1 else
               'неясно, какая комната на плане' if j in unsure else 'в тексте есть, на плане не найдено')
        orphans.append(dict(r, why=why))
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
