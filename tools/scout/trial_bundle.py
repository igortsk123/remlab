#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ДАННЫЕ СТРАНИЦЫ /demo ПОД ЗАГРУЖЕННЫЙ ПЛАН (план agent-trial-08-demo-as-template, задачи А и З; T-20261109-21).

Итог пробы открывается ТЕМ ЖЕ `index.html`, что и `/demo`, поэтому у каждого задания свой `demo-data.json` по контракту
`flat215_demo.py:build`: `room`, `rooms_geo`, `apartment_rooms`, `variants`, `feeds` (и `v.cams`, `rules`, `quiz`). Вход:
`contracts/trial.ts:floorplanResult`, сцена гостиной `trial_demo.py` (`~/scout-scenes/trial/<id>/scene.json`), когда готова, и куски
других стадий (`parts`: спальни — `trial_bedroom.bundle_parts`), когда готовы.

ИСХОД МЕБЕЛИ ПО КОМНАТЕ (`apartment_rooms[].furniture_state`, Codex 09.11 третья проверка, владелец 09.11):
  `pending` — мебель подбирается (вариант `items: []`, `pending: true`: пустая комната с крутилкой);
  `ready` — обставлена (варианты с предметами);
  `refused` — честный отказ: комната остаётся ПУСТОЙ в 3D (вариант `items: []`, `furniture_state: failed`), текст покупателю
             `furniture_text`/`furniture_text_en`; нет подходящих товаров — «Нет подходящих товаров согласно действующим шаблонам»;
  `not_furnished` — комнату не обставляем по типу (кухня, санузел, прихожая, прочее): не цель, завершённости не мешает.
Цели — гостиные и спальни (`TARGET_KINDS`); `trial.complete` — ни одной цели в `pending` (дирижёр ставит `done` только при нём).

ОЧИСТКА (общий разрешённый список для ВСЕХ комнат): предмет — только `ITEM_KEYS`, его `sku` — только `SKU_KEYS` (нейтральное имя
по роли, ключ модели, размеры), ленты — `FEED_KEYS`; ни названий товаров и магазинов, ни ссылок, ни цен. `assert_public` проверяет
ВЕСЬ собранный JSON; нашлось — отказ `shop_leak`, а не публикация.

ОПРОС: `quiz` — правило `rules/quiz.json` целиком, как в живом `/demo`: без `D.quiz.questions` ссылка покупателя `?quiz=1` опрос не откроет.

Комната — прямоугольное ядро как `trial_room.adapt`, проёмы — по стенам. Отличие от `adapt` одно: геометрия НЕ отказывает
из-за мебели (нет окна, диван не влезает, нет входа, масштаб не проверен) — это причины отказа мебели, а пустая
комната и в них честно показывается («сбой гостиной — 3D остаётся»). Неоднозначные данные — отказ, не угадывание:
`opening_ambiguous`, `contour_distorted`, `no_core`, `opening_cut_by_core`. Радиаторов в контракте нет — `radiators: []`,
не выдумываем. Этажи — `storey` у комнаты, только если подпись панели его подтверждает; `floor`/`floorsTotal` (этаж дома)
не трогаем. Папки и версии — на проде (`lib/trial/repo-bundle.ts`): здесь только сборка JSON.

  ~/venvs/scout/bin/python trial_bundle.py <job_id> <floorplanResult.json> [--scene scene.json] [--parts parts.json] [--out demo-data.json]
Код выхода: 0 — собрано, 2 — честный отказ (причина JSON-строкой в stdout).
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import trial_room as TR  # noqa: E402  (кладёт солвер в sys.path)

LIVING = 'living'
BEDROOM = 'bedroom'
TARGET_KINDS = (LIVING, BEDROOM)          # завершённость задания — по ним; прочие комнаты — «не обставляется»
# как `flat215_demo.STYLE_IDS` и `STYLE_IDS` страницы (сверка — тестом): страница узнаёт стиль по этому ключу
STYLE_IDS = {'сканди': 'scandi', 'современный': 'modern', 'минимализм': 'minimal', 'лофт': 'loft', 'неоклассика': 'neoclassic',
             'джапанди': 'japandi'}
PENDING_STYLE = 'сканди'                 # стиль пустой комнаты: валидный, сменится с приходом вариантов
# причины ядра, которые решают судьбу МЕБЕЛИ, а не геометрии (см. шапку)
FURNITURE_ONLY_REASONS = {'living_core_small', 'no_entry'}
TITLES = {'living': ('Гостиная', 'Living room'), 'bedroom': ('Спальня', 'Bedroom'), 'kitchen': ('Кухня', 'Kitchen'),
          'bathroom': ('Санузел', 'Bathroom'), 'hall': ('Прихожая', 'Hall'), 'other': ('Помещение', 'Room')}
SCENE_FURNITURE = {'ok': 'ready', 'partial': 'partial', 'refused': 'failed', 'failed': 'failed'}
SCENE_READY = ('ok', 'partial')

# ───────────────────────── исход по комнате: код для страницы и тексты (ru, en) ─────────────────────────
# `furniture_state` — машина состояний (дирижёр), `furniture_outcome` — код для страницы (выбор надписи на любом языке),
# `furniture_code` — точная причина стадии (диагностика). Тексты — готовые на обоих языках, страница может взять свои по коду.
ROOM_STATES = ('pending', 'ready', 'refused', 'not_furnished')
OUTCOME_TEXT = {
    'no_products': ('Нет подходящих товаров согласно действующим шаблонам.', 'No suitable products under the current templates.'),
    'not_readable': ('Не удалось надёжно построить эту комнату по плану, поэтому мебель не расставлена.',
                     'This room could not be read reliably from the plan, so furniture was not placed.'),
    'scale_unverified': ('Размеры комнаты по плану не подтверждены, поэтому мебель не расставлена.',
                         'Room dimensions could not be confirmed from this plan, so furniture was not placed.'),
    'no_window': ('В гостиной на плане нет окна, поэтому мебель гостиной не расставлена.',
                  'The living room has no window on the plan, so living-room furniture was not placed.'),
    'largest_living_only': ('Мебель подбираем только для самой большой гостиной.', 'Furniture is selected only for the largest living room.'),
    'not_furnished': ('Эту комнату не обставляем.', 'We do not furnish rooms of this type.'),
    'failed': ('Не удалось подобрать мебель для этой комнаты.', 'Furniture could not be placed in this room.'),
}
CODE_OUTCOME = {
    **{c: 'no_products' for c in ('no_products', 'bed_no_fit', 'room_too_small', 'living_core_small', 'layout_failed', 'style_rejected',
                                  'furniture_failed')},
    **{c: 'not_readable' for c in ('contour_distorted', 'no_core', 'opening_cut_by_core', 'opening_ambiguous', 'no_entry')},
    'scale_unverified': 'scale_unverified', 'living_no_window': 'no_window', 'one_living_furnished': 'largest_living_only',
    'room_kind_not_furnished': 'not_furnished',
}
APPROX_SHARE = 0.92                       # ядро-прямоугольник меньше этой доли контура — комната «приближённая» (`rooms_geo[].approx`)

# ───────────────────────── подписи комнат (ru ↔ en) ─────────────────────────
# Распознанное имя переводится ЗДЕСЬ (Codex 09.11 lang п.2.1): страница выбирает `titleRu/titleEn`, а не лечит подписи словарём DOM.
# Составные («Kitchen/Diner», «Кухня-гостиная») — по частям; номер сохраняется; неизвестное слово — тип комнаты + номер.
ROOM_EN_RU = {
    'living room': 'гостиная', 'lounge': 'гостиная', 'reception room': 'гостиная', 'reception': 'гостиная', 'sitting room': 'гостиная',
    'family room': 'семейная комната', 'bedroom': 'спальня', 'master bedroom': 'главная спальня', 'kitchen': 'кухня', 'diner': 'столовая',
    'dining room': 'столовая', 'dining': 'столовая', 'kitchen-living room': 'кухня-гостиная', 'bathroom': 'ванная',
    'shower room': 'душевая', 'en-suite': 'санузел при спальне', 'ensuite': 'санузел при спальне', 'wc': 'туалет', 'toilet': 'туалет',
    'cloakroom': 'туалет', 'hall': 'прихожая', 'hallway': 'прихожая', 'entrance hall': 'прихожая', 'landing': 'лестничная площадка',
    'corridor': 'коридор', 'study': 'кабинет', 'office': 'кабинет', 'utility': 'подсобная', 'utility room': 'подсобная',
    'store': 'кладовая', 'storage': 'кладовая', 'dressing room': 'гардеробная', 'balcony': 'балкон', 'loggia': 'лоджия',
    'garage': 'гараж', 'workshop': 'мастерская', 'conservatory': 'зимний сад', 'nursery': 'детская', 'terrace': 'терраса',
    'en suite': 'санузел при спальне', 'pantry': 'кладовая', 'vestibule': 'тамбур', 'porch': 'тамбур', 'linen room': 'бельевая',
    'linen rm.': 'бельевая', 'linen': 'бельевая', 'laundry': 'прачечная', 'laundry room': 'прачечная', 'room': 'комната',
    'snug': 'малая гостиная', 'boot room': 'прихожая', 'playroom': 'игровая', 'gym': 'спортзал', 'kitchen/diner': 'кухня-столовая',
    'kitchen diner': 'кухня-столовая', 'open plan kitchen': 'кухня-гостиная',
}
ROOM_RU_EN = {
    'гостиная': 'living room', 'зал': 'living room', 'спальня': 'bedroom', 'кухня': 'kitchen', 'столовая': 'dining room',
    'кухня-гостиная': 'kitchen-living room', 'кухня-столовая': 'kitchen-diner', 'ванная': 'bathroom', 'ванная комната': 'bathroom',
    'санузел': 'bathroom', 'с/у': 'bathroom', 'туалет': 'WC', 'уборная': 'WC', 'душевая': 'shower room', 'прихожая': 'hall',
    'холл': 'hall', 'коридор': 'corridor', 'кабинет': 'study', 'детская': 'nursery', 'гардеробная': 'dressing room',
    'гардероб': 'dressing room', 'кладовая': 'storage', 'кладовка': 'storage', 'постирочная': 'utility room', 'балкон': 'balcony',
    'лоджия': 'loggia', 'терраса': 'terrace', 'гараж': 'garage', 'мастерская': 'workshop',
}
_CYR = re.compile(r'[Ѐ-ԯ]')
_SEP_MAIN = re.compile(r'(\s*[/&+,]\s*|\s+-\s+|\s+(?:and|и)\s+)', re.I)
_SEP_DASH = re.compile(r'((?<=[^\W\d])-(?=[^\W\d]))')
_ROOM_NUM = re.compile(r'^(.*?)[\s.#№(]*(\d{1,2})\)?$')


def _tr_whole(text: str, table: dict) -> str | None:
    m = _ROOM_NUM.match(text.strip())
    words, num = (m.group(1), m.group(2)) if m and m.group(1).strip() else (text, None)
    hit = table.get(re.sub(r'\s+', ' ', words.strip().lower()))
    return None if hit is None else hit + (f' {num}' if num else '')


def _tr_room(text: str, table: dict, and_word: str) -> str | None:
    """Подпись целиком по словарю; иначе по частям (сперва `/ & + , and`, затем дефис между словами). Хоть одна часть не знакома — None."""
    whole = _tr_whole(text, table)
    if whole is not None:
        return whole
    for sep in (_SEP_MAIN, _SEP_DASH):
        bits = sep.split(text)
        if len(bits) < 2:
            continue
        out = []
        for i, b in enumerate(bits):
            if i % 2:
                out.append(f' {and_word} ' if b.strip().lower() in ('and', 'и') else b)
                continue
            t = _tr_room(b, table, and_word) if b.strip() else None
            if t is None:
                return None
            out.append(t)
        return ''.join(out)
    return None


def room_titles(name: str | None, kind: str) -> tuple[str, str]:
    """Распознанная подпись комнаты → (по-русски, по-английски). Язык подписи сохраняется как есть, другой — перевод словарём;
    перевода нет — тип комнаты с тем же номером («Bedroom 3» → «Спальня 3», «Кладовка у лестницы» → «Room»). Кириллица в EN — никогда."""
    base_ru, base_en = TITLES.get(kind, TITLES['other'])
    src = re.sub(r'\s+', ' ', str(name or '').strip())
    if not src:
        return base_ru, base_en
    if src.isupper():                                       # «BEDROOM 1» с плана — «Bedroom 1»; сокращения («WC») — как есть
        src = ' '.join(w if len(w) <= 3 else w[:1] + w[1:].lower() for w in src.split(' '))
    m = _ROOM_NUM.match(src)
    num = m.group(2) if m and m.group(1).strip() else None

    def fb(base):
        return f'{base} {num}' if num else base

    def cap(s):
        return s[:1].upper() + s[1:]
    if _CYR.search(src):
        en = _tr_room(src, ROOM_RU_EN, 'and')
        return src, (cap(en) if en and not _CYR.search(en) else fb(base_en))
    ru = _tr_room(src, ROOM_EN_RU, 'и')
    return (cap(ru) if ru else fb(base_ru)), src

# ───────────────────────── общий разрешённый список полей товара (все комнаты) ─────────────────────────
ITEM_KEYS = {'role', 'x', 'y', 'rot', 'w', 'd', 'h', 'dims_src', 'sku', 'corner', 'corner_left', 'section', 'elev'}
SKU_KEYS = {'name', 'name_en', 'colour_en', 'msid', 'w', 'd', 'h', 'sleep_w'}
FEED_KEYS = SKU_KEYS | {'style', 'styles', 'src', 'corner'}
BANNED_KEYS = {'url', 'url_direct', 'shop', 'img', 'img_hd', 'price', 'brand'}
SHOP_LINKS = re.compile(r'(https?:|//[a-z0-9.-]+\.[a-z]{2,}|gdeslon|\berid=)', re.I)
TOKEN_MIN = 6                             # короче — слишком общее слово (роль «пуф»), ловило бы само себя
# имя товара на странице — нейтральное по роли: по-русски (`name`) и по-английски (`name_en`, словарь ролей живой витрины
# `data/names-en-dict.json` → `names_en.neutral`); цвет — `colour_en` (хвост цвета/материала из названия, без модели и магазина)
NEUTRAL_RU = {'тв-тумба': 'ТВ-тумба', 'стол обеденный': 'Обеденный стол', 'тумба прикроватная': 'Прикроватная тумба',
              'стол рабочий': 'Рабочий стол', 'стул рабочий': 'Рабочий стул', 'кровать детская': 'Детская кровать',
              'стол детский': 'Детский стол', 'стул детский': 'Детский стул'}


class BundleRefused(Exception):
    """Честный отказ собрать данные: страницу без вариантов открыть нельзя (`load()` упадёт), выдумывать комнату — тоже."""

    def __init__(self, code: str, detail: str = ''):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail = code, detail


def quiz_rule() -> dict:
    """Правило опроса живого демо (`flat215_demo.build` кладёт его же в `D.quiz`)."""
    return json.load(open(os.path.join(HERE, 'rules', 'quiz.json'), encoding='utf-8'))


def default_ctx() -> dict:
    """Что берётся у живого демо: числа правил страницы, модель товара, правило опроса. Импорт `flat215_demo` тяжёлый — только здесь."""
    import flat215_demo as FD
    return {'rules': {**FD._rules(), 'soft_roles': FD.soft_roles()}, 'msid_of': FD._msid, 'slot_band': FD._slot_band, 'quiz': quiz_rule()}


# ───────────────────────── этажи ─────────────────────────

_STOREY_WORDS = (
    (r'\b(basement|cellar|цокол\w*|подвал\w*)\b', -1), (r'\bground\b', 0), (r'\b(first|1st)\s+(floor|level|storey)\b', 1),
    (r'\b(second|2nd)\s+(floor|level|storey)\b', 2), (r'\b(third|3rd)\s+(floor|level|storey)\b', 3),
    (r'\b(fourth|4th)\s+(floor|level|storey)\b', 4), (r'\bпервый\s+этаж\b', 1), (r'\bвторой\s+этаж\b', 2), (r'\bтретий\s+этаж\b', 3),
)
_STOREY_NUM = (r'\b(?:floor|level|storey)\s*(\d{1,2})\b', r'\b(\d{1,2})(?:-?(?:й|ой))?\s+этаж\b', r'\bэтаж\s*(\d{1,2})\b')


def storey_of(title: str | None) -> int | None:
    """Этаж по подписи панели; нет слова об этаже или подпись называет два разных (`Ground and First Floor`) — неизвестно."""
    s = re.sub(r'lower[\s-]*ground', 'basement', str(title or '').lower())
    found = {v for pat, v in _STOREY_WORDS if re.search(pat, s)}
    found |= {int(m) for pat in _STOREY_NUM for m in re.findall(pat, s)}
    return found.pop() if len(found) == 1 else None


def storeys(panels: list) -> tuple[dict, list]:
    """Индекс панели → этаж. Этаж считается подтверждённым, только если подписаны ВСЕ панели и разными этажами."""
    vals = [storey_of(p.get('title')) for p in panels]
    if any(v is None for v in vals) or len(set(vals)) != len(vals):
        return {}, ['storey_unconfirmed'] if len(panels) > 1 else []
    return dict(enumerate(vals)), []


# ───────────────────────── геометрия комнаты ─────────────────────────

def _num(v: float) -> float | int:
    r = round(float(v), 1)
    return int(r) if r == int(r) else r


def _openings_for_page(ops: list) -> list:
    """Проёмы ядра → формат `room.openings` страницы: служебное (`_…`) снято; проход без полотна (`door` без дуги) — `opening`,
    как `trial_demo.core_room(render=True)`: дверь в проходе рисовать нечем."""
    out = []
    for o in ops:
        o = {k: v for k, v in o.items() if not k.startswith('_')}
        if o.get('kind') == 'door' and not o.get('swing_cm'):
            o = {k: v for k, v in o.items() if k != 'swing_cm'}
            o['kind'] = 'opening'
        out.append(o)
    return out


def core_geometry(panel: dict, room: dict, cfg: dict) -> dict:
    """Ядро комнаты и проёмы по её стенам (шаги `trial_room.adapt` без мебельных отказов) → w, d, openings. Отказ — `Refusal`."""
    from planner.geometry import largest_free_rectangles
    ours, amb = TR._openings_of(panel, room, cfg)
    if amb:
        raise TR.Refusal('opening_ambiguous', '; '.join(f"{o['kind']} {o['widthCm']:.0f} см в {o['_d']:.0f} см от стены" for o in amb))
    fr = TR.ortho_frame(room['contour'], cfg)
    ops = [TR._place_opening(fr['poly'], o, fr['T'], cfg) for o in ours]
    rects = [g.bounds for g in largest_free_rectangles(fr['poly'], min_side_cm=cfg['core_min_side_cm'], limit=24)]
    if not rects:
        raise TR.Refusal('no_core')
    cands = [TR.core_candidate(fr['poly'], r, ops, TR.need_group(), cfg) for r in rects[:int(cfg['core_candidates'])]]
    blocking = [[r for r in c['reasons'] if r.split(':')[0] not in FURNITURE_ONLY_REASONS] for c in cands]
    ok = [c for c, b in zip(cands, blocking) if not b]
    ok.sort(key=lambda c: (not c['light_on_core'], -c['area_m2']))
    if not ok:
        why = [r.split(':')[0] for b in blocking for r in b]
        code = 'opening_cut_by_core' if 'opening_cut_by_core' in why else 'no_core'
        raise TR.Refusal(code, '; '.join(f"ядро {c['w']:.0f}×{c['d']:.0f}: {', '.join(b)}" for c, b in zip(cands, blocking)))
    best = ok[0]
    return {'w': _num(best['w']), 'd': _num(best['d']), 'openings': _openings_for_page(TR.solver_openings(best, cfg))}


# ───────────────────────── очистка ─────────────────────────

def _base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


_NE: list = []


def _names_en():
    """(`names_en`, его словарь) — один раз на процесс."""
    if not _NE:
        import names_en
        _NE.extend([names_en, names_en.load_dict()])
    return _NE[0], _NE[1]


def neutral_names(role: str) -> tuple[str, str]:
    """Нейтральное имя предмета по роли: (по-русски, по-английски)."""
    base = _base_role(role)
    NE, D = _names_en()
    return NEUTRAL_RU.get(base, base[:1].upper() + base[1:]), NE.neutral(base, D)


def colour_en(name: str | None, role: str) -> str:
    """Цвет/материал товара по-английски из его названия (`names_en.translate`) — только слова словарей цвета, материала и рисунка:
    модель, бренд и магазин сюда не проходят (нашлось чужое слово — пусто)."""
    if not name:
        return ''
    NE, D = _names_en()
    c = (NE.translate(name, role, D).get('colour') or '').strip()
    vocab = {w for t in ('colours', 'materials', 'patterns') for v in (D.get(t) or {}).values() for w in re.findall(r'[a-z]+', str(v).lower())}
    words = re.findall(r'[^\s,/-]+', c.lower())
    return c if words and not NE.bad(c, D) and all(w in vocab or w in ('and', 'with') for w in words) else ''


def public_item(it: dict) -> dict:
    """Предмет варианта — только разрешённые поля: общий фильтр для гостиной, спален и любых будущих комнат."""
    out = {k: v for k, v in it.items() if k in ITEM_KEYS}
    if isinstance(out.get('sku'), dict):
        out['sku'] = {k: v for k, v in out['sku'].items() if k in SKU_KEYS}
    return out


def shop_tokens(scene: dict | None) -> list:
    """Что не должно попасть в вывод дословно: названия товаров и магазинов из входа (сцена гостиной)."""
    toks = set()

    def take(row):
        for k in ('name', 'shop', 'brand'):
            if isinstance(row.get(k), str):
                toks.add(row[k].strip().lower())
    for sv in (scene or {}).get('variants') or []:
        for row in sv.get('items') or []:
            take(row)
    # имена предметов кусков стадий сборка переписывает нейтральными (`_part_item`), поэтому в запрет не идут: стадия спален уже
    # выдаёт нейтральное («Bed 160 cm»), и оно совпало бы с нашим
    _, D = _names_en()
    names = {n.lower() for n in list(NEUTRAL_RU.values()) + list((D.get('roles') or {}).values())}
    return sorted(t for t in toks if len(t) >= TOKEN_MIN and t not in names)


def assert_public(obj, tokens: list) -> None:
    """Проверка очисткой ВЫВОДА: ни запрещённых полей, ни ссылок, ни названий товаров/магазинов во всём JSON → иначе `shop_leak`."""
    pats = [re.compile(r'(?<!\w)' + re.escape(t) + r'(?!\w)') for t in tokens]

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in BANNED_KEYS or (isinstance(k, str) and (k.endswith('_url') or k == 'href')):
                    raise BundleRefused('shop_leak', f'запрещённое поле {path}.{k}')
                walk(x, f'{path}.{k}')
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                walk(x, f'{path}[{i}]')
        elif isinstance(v, str):
            s = v.lower()
            if SHOP_LINKS.search(s) or any(p.search(s) for p in pats):
                raise BundleRefused('shop_leak', f'значение в {path}: {v[:80]}')
    walk(obj, '$')


# ───────────────────────── варианты ─────────────────────────

def _geo_titles(room: dict, geo: dict, kind: str) -> dict:
    """Подпись комнаты в 3D/плане: `title` (по-русски, как в живом `/demo`), `title_ru`, `title_en`, исходное имя — `name_src`."""
    area = room.get('areaM2') or geo['w'] * geo['d'] / 1e4
    ru, en = room_titles(room.get('name'), kind)
    return {'title': f'{ru} {area:.1f} м²', 'title_ru': f'{ru} {area:.1f} м²', 'title_en': f'{en} {area:.1f} m²', 'name_src': room.get('name') or ''}


def _approx(room: dict, geo: dict) -> bool:
    """Комната показана ядром-прямоугольником заметно меньше контура (Г-образная, скошенная) — `approx`: страница помечает видимо."""
    from shapely.geometry import Polygon
    try:
        area = Polygon(room['contour']).area
    except Exception:  # noqa: BLE001 — кривой контур: точно не «как на плане»
        return True
    return bool(area > 0 and geo['w'] * geo['d'] < APPROX_SHARE * area)


def _empty_variant(room_id: str, geo: dict, state: str, problem: dict | None = None) -> dict:
    out = {'id': f'trial-{room_id}', 'title': PENDING_STYLE.capitalize(), 'style': PENDING_STYLE, 'style_id': STYLE_IDS[PENDING_STYLE],
           'room_id': room_id, 'items': [], 'decor': [], 'dims_unknown': [], 'missing_item': [], 'fill': [], 'fill_pct': None,
           'cams': [], 'pending': state == 'pending', 'furniture_state': state, 'room_size': {'w': geo['w'], 'd': geo['d']}}
    if problem:
        out['furniture_problem'] = problem
    return out


def _outcome(state: str, code: str | None = None) -> dict:
    """Исход мебели по комнате: состояние (дирижёру), код для страницы `furniture_outcome` (`furnished` / `pending` / `no_products` /
    `not_readable` / `scale_unverified` / `no_window` / `largest_living_only` / `not_furnished` / `failed`), точная причина, тексты ru/en."""
    if state == 'ready':
        outcome = 'furnished'
    elif state == 'pending':
        outcome = 'pending'
    elif state == 'not_furnished':
        outcome = 'not_furnished'
    else:
        outcome = CODE_OUTCOME.get(code or '', 'failed')
        outcome = 'failed' if outcome == 'not_furnished' else outcome
    ru, en = OUTCOME_TEXT.get(outcome, (None, None))
    return {'furniture_state': state, 'furniture_outcome': outcome, 'furniture_code': code, 'furniture_text': ru, 'furniture_text_en': en}


def _item(row: dict, place: dict | None, msid_of) -> dict:
    """Строка сцены `trial_demo` → предмет варианта по разрешённому списку: имя — нейтральное по роли, модель — `msid`."""
    p = place or {}
    h = row.get('h') if row.get('h') is not None else p.get('h')
    ru, en = neutral_names(row['role'])
    sku = {'name': ru, 'name_en': en, 'colour_en': colour_en(row.get('name'), _base_role(row['role'])),
           'msid': msid_of(row.get('sid')) if row.get('sid') else None, 'w': row.get('w'), 'd': row.get('d'), 'h': h}
    return public_item({'role': row['role'], 'x': row['x'], 'y': row['y'], 'rot': int(row.get('rot') or 0), 'w': row.get('w'), 'd': row.get('d'),
                        'h': h, 'dims_src': 'каталог', 'sku': sku, 'corner': bool(row.get('corner')), 'corner_left': bool(p.get('corner_left')),
                        'section': p.get('section')})


def _scene_variant(sv: dict, room_id: str, geo: dict, msid_of) -> dict:
    style = sv.get('style') or PENDING_STYLE
    failed = bool(sv.get('failed'))
    state = 'failed' if failed else ('ready' if sv.get('post_ok') and not sv.get('hard') else 'partial')
    place = {p['role']: p for p in sv.get('placements_core') or []}
    out = {'id': f"set{sv['set_index']}", 'title': style.capitalize(), 'style': style, 'style_id': STYLE_IDS.get(style, ''),
           'room_id': room_id, 'items': [_item(r, place.get(r['role']), msid_of) for r in sv.get('items') or []], 'decor': [],
           'dims_unknown': [], 'missing_item': [{'role': r} for r in sv.get('absent_roles') or []], 'fill': [], 'fill_pct': None,
           'cams': [], 'pending': False, 'furniture_state': state, 'room_size': {'w': geo['w'], 'd': geo['d']}}
    if state != 'ready':
        out['furniture_problem'] = {'codes': sorted({p.get('code') for p in sv.get('problems') or []} | set(sv.get('hard') or []))}
    return out


def _feeds(variants: list) -> dict:
    """Ленты замен — только товары вариантов задания (других для этого плана не считалось), `диван` → строки как в живом `feeds`."""
    out: dict = {}
    seen: dict = {}
    for v in variants:
        for it in v['items']:
            sku, base = it.get('sku') or {}, _base_role(it['role'])
            key = (base, sku.get('msid') or sku.get('name'), sku.get('w'), sku.get('d'))
            if key in seen:
                if v['style'] not in seen[key]['styles']:
                    seen[key]['styles'].append(v['style'])
                continue
            row = {k: x for k, x in {**sku, 'style': v['style'], 'styles': [v['style']], 'src': 'set', 'corner': it.get('corner')}.items()
                   if k in FEED_KEYS}
            seen[key] = row
            out.setdefault(base, []).append(row)
    for lst in out.values():
        lst.sort(key=lambda p: (p.get('w') or 0, p.get('name') or ''))
    return out


# ───────────────────────── сборка ─────────────────────────

def _check_input(job_id: str, result: dict, scene: dict | None) -> None:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', job_id or ''):
        raise BundleRefused('bad_job_id', str(job_id))
    if result.get('version') != 1 or result.get('units') != 'cm' or not result.get('panels'):
        raise BundleRefused('bad_result', 'нужен floorplanResult v1 в сантиметрах')
    if scene is None:
        return
    if scene.get('trial_id') != job_id:
        raise BundleRefused('scene_mismatch', f"сцена другого задания: {scene.get('trial_id')}")
    if scene.get('status') not in SCENE_FURNITURE:
        raise BundleRefused('scene_mismatch', f"неизвестный статус сцены: {scene.get('status')}")
    if scene['status'] in SCENE_READY and not (scene.get('core') and scene.get('room') and scene.get('variants')):
        raise BundleRefused('scene_mismatch', 'сцена без ядра, комнаты или вариантов')


def _living_rooms(result: dict, cfg: dict) -> tuple[list, list]:
    """Комнаты типа «гостиная»: первая — та же, что выбирает `trial_room.pick_living` (её обставляет сцена), дальше по площади."""
    try:
        panel, main, flags = TR.pick_living(result, cfg)
    except TR.Refusal as e:
        raise BundleRefused(e.code, e.detail) from e
    from shapely.geometry import Polygon
    rest = [(p, r) for p in result['panels'] for r in p['rooms'] if r.get('kind') == LIVING and r is not main]
    rest.sort(key=lambda pr: -Polygon(pr[1]['contour']).area)
    return [(panel, main)] + rest, flags


def _map_parts(parts: list, panels: list, ids: dict, livings: set) -> dict:
    """Куски других стадий (спальни — `trial_bedroom.bundle_parts`) → {id комнаты задания: {entry, geo, variants}}.
    Комната кусков находится по (`panel`, `src_id`), если кусок их несёт, иначе по id; чужая, гостиная или повторная — `parts_mismatch`."""
    by_src = {(p['id'], r['id']): ids[id(r)] for p in panels for r in p['rooms']}
    ours = {ids[id(r)]: r for p in panels for r in p['rooms']}
    out: dict = {}
    for part in parts:
        remap = {}
        for e in part.get('apartment_rooms') or []:
            rid = by_src.get((e.get('panel'), e.get('src_id'))) if e.get('src_id') is not None else (e.get('id') if e.get('id') in ours else None)
            if rid is None or rid in out or id(ours[rid]) in livings or e.get('furniture_state') not in ROOM_STATES:
                raise BundleRefused('parts_mismatch', f"комната куска {e.get('id')} ({e.get('panel')}/{e.get('src_id')})")
            remap[e['id']] = rid
            out[rid] = {'entry': e, 'geo': (part.get('rooms_geo') or {}).get(e['id']), 'variants': []}
        for v in part.get('variants') or []:
            if v.get('room_id') not in remap:
                raise BundleRefused('parts_mismatch', f"вариант {v.get('id')} без комнаты куска")
            out[remap[v['room_id']]]['variants'].append({**v, 'room_id': remap[v['room_id']],
                                                         'items': [_part_item(it) for it in v.get('items') or []]})
    return out


def _part_item(it: dict) -> dict:
    """Предмет из куска стадии → разрешённые поля, имя — нейтральное по роли на обоих языках (кровать — с шириной спального места)."""
    out = public_item(it)
    sku = dict(out.get('sku') or {})
    ru, en = neutral_names(out.get('role') or '')
    sw = sku.get('sleep_w')
    if isinstance(sw, (int, float)) and sw > 0:
        ru, en = f'{ru} {round(sw)} см', f'{en} {round(sw)} cm'
    sku.update(name=ru, name_en=en)
    out['sku'] = sku
    return out


def build(job_id: str, result: dict, scene: dict | None = None, ctx: dict | None = None, parts: list | None = None) -> dict:
    """floorplanResult (+ сцена гостиной, + куски стадий) → `demo-data.json`. Нечего показать или утечка магазина — `BundleRefused`."""
    _check_input(job_id, result, scene)
    parts = list(parts or [])
    ctx = ctx or default_ctx()
    quiz = ctx.get('quiz') or quiz_rule()
    if not (isinstance(quiz, dict) and isinstance(quiz.get('questions'), list) and quiz['questions']):
        raise BundleRefused('quiz_missing', 'нет `questions` в правиле опроса: ссылка покупателя `?quiz=1` не откроет опрос')
    cfg = TR.rules()
    panels = result['panels']
    panel_of = {id(r): i for i, p in enumerate(panels) for r in p['rooms']}
    livings, flags = _living_rooms(result, cfg)
    main = livings[0][1]
    if scene is not None and scene.get('room') and (scene['room'].get('id') != main['id'] or
                                                     scene['room'].get('panel') != panels[panel_of[id(main)]]['id']):
        raise BundleRefused('scene_mismatch', f"сцена про комнату {scene['room'].get('id')}, а гостиная плана — {main['id']}")
    furnished = scene is not None and scene['status'] in SCENE_READY
    geos, refused = {}, []
    for panel, room in livings:
        try:
            if room is main and furnished:
                first = next(v for v in sorted(scene['variants'], key=lambda v: bool(v.get('failed'))))
                ops = scene['geometries'][first['geometry']]['openings_core'] or scene['openings_core']
                geos[id(room)] = {'w': _num(scene['core']['w']), 'd': _num(scene['core']['d']), 'openings': _openings_for_page(ops)}
            else:
                geos[id(room)] = core_geometry(panel, room, cfg)
        except TR.Refusal as e:
            refused.append({'room': room, 'code': e.code, 'detail': e.detail})
    if not geos:
        raise BundleRefused(refused[0]['code'], refused[0]['detail'])
    # id: первая собранная гостиная — `living` (страница и `HOME.room` опираются на него); уникальны и через панели
    ids: dict = {}
    n_living = 0
    for _, room in livings:
        if id(room) in geos:
            n_living += 1
            ids[id(room)] = LIVING if n_living == 1 else f'{LIVING}-{n_living}'
    for _, room in livings:
        if id(room) not in geos:
            n_living += 1
            ids[id(room)] = f'{LIVING}-{n_living}'
    counters: dict = {}
    for p in panels:
        for r in p['rooms']:
            if id(r) not in ids:
                counters[r['kind']] = counters.get(r['kind'], 0) + 1
                ids[id(r)] = f"{r['kind']}-{counters[r['kind']]}"
    pmap = _map_parts(parts, panels, ids, {id(r) for _, r in livings})
    storey_map, storey_flags = storeys(panels)
    rooms_geo, apartment_rooms, variants = {}, [], []
    outcomes = {ids[id(x['room'])]: _outcome('refused', x['code']) for x in refused}

    def put_geo(panel, room, rid, geo, kind):
        full = {'w': geo['w'], 'd': geo['d'], **_geo_titles(room, geo, kind), 'openings': geo['openings'], 'radiators': [],
                'approx': _approx(room, geo)}
        st = storey_map.get(panel_of[id(room)])
        if st is not None:
            full['storey'] = st
        rooms_geo[rid] = full

    for panel, room in livings:
        if id(room) not in geos:
            continue
        rid, geo = ids[id(room)], geos[id(room)]
        put_geo(panel, room, rid, geo, LIVING)
        if room is main and furnished:
            ready = [_scene_variant(sv, rid, geo, ctx['msid_of']) for sv in scene['variants']]
            shown = any(v['items'] and v['furniture_state'] != 'failed' for v in ready)
            if shown:
                variants += sorted(ready, key=lambda v: v['furniture_state'] == 'failed')
                outcomes[rid] = _outcome('ready')
            else:                                            # ни один стиль не встал — пустая комната с текстом, а не пустые «стили»
                variants.append(_empty_variant(rid, geo, 'failed', {'code': 'furniture_failed'}))
                outcomes[rid] = _outcome('refused', 'furniture_failed')
        elif room is main and scene is not None:
            why = scene.get('refusal') or {'code': (scene.get('problems') or [{}])[0].get('code') or scene['status']}
            variants.append(_empty_variant(rid, geo, 'failed', why))
            outcomes[rid] = _outcome('refused', why.get('code'))
        elif scene is not None:                              # `trial_demo` обставляет одну гостиную: эта уже не дождётся мебели
            variants.append(_empty_variant(rid, geo, 'failed', {'code': 'one_living_furnished'}))
            outcomes[rid] = _outcome('refused', 'one_living_furnished')
        else:
            variants.append(_empty_variant(rid, geo, 'pending'))
            outcomes[rid] = _outcome('pending')
    # спальни (и комнаты, которые стадия спален признала спальнями): своя стадия; нет её куска — подбирается
    living_ids = {id(r) for _, r in livings}
    kind_of = {}
    for p in panels:
        for r in p['rooms']:
            rid = ids[id(r)]
            if id(r) in living_ids or not (r.get('kind') == BEDROOM or rid in pmap):
                continue
            kind_of[rid] = BEDROOM
            got = pmap.get(rid)
            geo, gcode = (got or {}).get('geo'), None
            if not geo:
                try:
                    geo = core_geometry(p, r, cfg)
                except TR.Refusal as e:
                    gcode = e.code
            if geo:
                put_geo(p, r, rid, geo, BEDROOM)
            if got is None:
                if geo:
                    variants.append(_empty_variant(rid, geo, 'pending'))
                    outcomes[rid] = _outcome('pending')
                else:
                    outcomes[rid] = _outcome('refused', gcode)
                continue
            e = got['entry']
            full = [v for v in got['variants'] if v.get('items')]
            if e['furniture_state'] == 'ready' and full:
                variants += sorted(got['variants'], key=lambda v: not v.get('items'))
                outcomes[rid] = _outcome('ready', e.get('furniture_code'))
            elif e['furniture_state'] == 'pending':
                if geo:
                    variants.append(_empty_variant(rid, geo, 'pending'))
                outcomes[rid] = _outcome('pending')
            else:
                code = (e.get('furniture_code') if e['furniture_state'] == 'refused' else None) or 'furniture_failed'
                if geo:                                      # владелец 09.11: без подходящих товаров комната остаётся пустой, с текстом
                    variants.append(_empty_variant(rid, geo, 'failed', {'code': code}))
                outcomes[rid] = _outcome('refused', code)
    with_variant = {v['room_id'] for v in variants}
    order = [r for _, r in livings] + [r for p in panels for r in p['rooms'] if id(r) not in living_ids]
    for i, r in enumerate(order, 1):
        rid = ids[id(r)]
        kind = kind_of.get(rid, r['kind'])
        t_ru, t_en = room_titles(r.get('name'), kind)
        entry = {'id': rid, 'kind': kind, 'ordinal': i, 'titleRu': t_ru, 'titleEn': t_en, 'name_src': r.get('name') or '',
                 'areaM2': r.get('areaM2') or None, 'contentState': 'ready' if rid in with_variant else 'soon',
                 **(outcomes.get(rid) or _outcome('not_furnished', 'room_kind_not_furnished'))}
        st = storey_map.get(panel_of[id(r)])
        if st is not None:
            entry['storey'] = st
        apartment_rooms.append(entry)
    vids = [v['id'] for v in variants]
    if len(vids) != len(set(vids)):
        raise BundleRefused('parts_mismatch', 'id вариантов повторяются')
    rules = dict(ctx['rules'])
    if ctx.get('slot_band') and LIVING in rooms_geo:
        rules['slot_band_cm'] = ctx['slot_band'](rooms_geo[LIVING])
    feeds = _feeds(variants)
    trial = {'job_id': job_id, 'scale': result['scale']['status'], 'furniture': SCENE_FURNITURE[scene['status']] if scene else 'pending',
             'complete': all(r['furniture_state'] != 'pending' for r in apartment_rooms),
             'flags': sorted(set(result.get('flags') or []) | set(flags) | set(storey_flags) | set((scene or {}).get('flags') or [])),
             'refused_rooms': [{'room_id': ids[id(x['room'])], 'code': x['code'], 'detail': x['detail']} for x in refused],
             'panels': [{'id': p['id'], 'title': p['title'],
                         **({'storey': storey_map[i]} if i in storey_map else {}),
                         'rooms': [{'id': ids[id(r)], 'src_id': r['id'], 'name': r.get('name'), 'kind': r['kind'], 'areaM2': r.get('areaM2'),
                                    'bbox': r.get('bbox'), 'contour': r.get('contour'), 'flags': r.get('flags') or []} for r in p['rooms']],
                         'openings': p.get('openings') or [], 'walls': p.get('walls') or []} for i, p in enumerate(panels)]}
    room = rooms_geo.get(LIVING) or next(iter(rooms_geo.values()))
    out = {'room': room, 'rooms_geo': rooms_geo, 'apartment_id': '', 'plan': {}, 'apartment_rooms': apartment_rooms,
           'rooms_enabled': sorted(with_variant), 'variants': variants, 'sets': [], 'sofa_feed': feeds.get('диван', []), 'feeds': feeds,
           'rules': rules, 'incomplete_styles': [], 'quiz': quiz, 'trial': trial}
    assert_public(out, shop_tokens(scene))           # поймали — отказ, а не публикация
    return out


def write_atomic(path: str, data: dict) -> None:
    """Подменой: читатель (и сбой на полпути) не видит половину файла."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _arg(args: list, name: str) -> str | None:
    if name not in args:
        return None
    i = args.index(name)
    val = args[i + 1]
    del args[i:i + 2]
    return val


def main() -> int:
    args = sys.argv[1:]
    scene_path, parts_path, out = _arg(args, '--scene'), _arg(args, '--parts'), _arg(args, '--out')
    if len(args) != 2:
        print(__doc__)
        return 0
    job_id, result_path = args
    result = json.load(open(result_path, encoding='utf-8'))
    scene = json.load(open(scene_path, encoding='utf-8')) if scene_path else None
    parts = json.load(open(parts_path, encoding='utf-8')) if parts_path else []
    try:
        data = build(job_id, result, scene, parts=parts if isinstance(parts, list) else [parts])
    except BundleRefused as e:
        print(json.dumps({'refusal': e.code, 'detail': e.detail}, ensure_ascii=False))
        return 2
    if out:
        write_atomic(out, data)
        print(json.dumps({'ok': True, 'rooms': list(data['rooms_geo']), 'variants': len(data['variants'])}, ensure_ascii=False))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, separators=(',', ':'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
