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

ОЧИСТКА (общий разрешённый список для ВСЕХ комнат): предмет — только `ITEM_KEYS`, его `sku` — только `SKU_KEYS` (имя, ключ модели,
размеры) и поля товара `/demo` (`PRODUCT_KEYS`), ленты — `FEED_KEYS`. `assert_public` проверяет ВЕСЬ собранный JSON; нашлось — отказ
`shop_leak`, а не публикация.

ТОВАР КАК В `/demo` (T-20261110-25, владелец 10.11 TG 744: «всё с товарами, как в России; на английской — без названия магазина и
цена с коэффициентом, ровно как на демо»): у предмета и строки ленты — название, цена, фото, ссылка «В магазин» и магазин, тем же
источником, что у витрины (`flat215_demo._sku`: название, фото, ссылка, магазин — товар банка по ключу `sid`, цена — текущая из
каталога `catalog_media`, нет её — банка; товара нет в банке — всё из каталога; фото — плитка витрины по адресу банка, нет его или
не скачался — по адресу каталога, плитки всех товаров банков докачивает ночь: `cache_bank_images`, T-20261110-25/2). Данные товара берутся ТОЛЬКО так по `sid`
(`catalog_goods`, `bank_index`), а не из входа стадий; `sid` в выход не идёт (`NEVER_KEYS`), поля товара — только на своих местах
(`variants[].items[].sku`, `feeds`, `sofa_feed`) и с проверенным видом (`_goods_ok`). Английскую цену (курс × наценка двойника /demo)
страница считает по `trial.money_en` (`uk_money` из `data/partners/demo-uk.json`), магазин и ссылку на английском прячет сама —
как у /demo (`index.html:MASK`). Товара нет ни в банке, ни в каталоге (или в каталоге он ушёл) — предмет остаётся с нейтральным именем без цены, как раньше.

ОПРОС: `quiz` — правило `rules/quiz.json` целиком, как в живом `/demo`: без `D.quiz.questions` ссылка покупателя `?quiz=1` опрос не откроет.

Комната — прямоугольное ядро как `trial_room.adapt`, проёмы — по стенам. Отличие от `adapt` одно: геометрия НЕ отказывает
из-за мебели (нет окна, диван не влезает, нет входа, масштаб не проверен) — это причины отказа мебели, а пустая
комната и в них честно показывается («сбой гостиной — 3D остаётся»). Неоднозначные данные — отказ, не угадывание:
`opening_ambiguous`, `contour_distorted`, `no_core`, `opening_cut_by_core`. Радиаторов в контракте нет — `radiators: []`,
не выдумываем. Этажи — `storey` у комнаты, только если подпись панели его подтверждает; `floor`/`floorsTotal` (этаж дома)
не трогаем. Папки и версии — на проде (`lib/trial/repo-bundle.ts`): здесь только сборка JSON.

  ~/venvs/scout/bin/python trial_bundle.py <job_id> <floorplanResult.json> [--scene scene.json] [--parts parts.json] [--out demo-data.json]
      [--release living,bedroom-1]      # комнаты, с которых снята «проверка размера» (кнопка «Обустроить»)
  ~/venvs/scout/bin/python trial_bundle.py --cache-images [--dry]   # плитки фото всех товаров банков пробы (ночной шаг `trial_images`)
Код выхода: 0 — собрано, 2 — честный отказ (причина JSON-строкой в stdout).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import trial_room as TR  # noqa: E402  (кладёт солвер в sys.path)
import trial_demo as TD  # noqa: E402  (исход гостиной — `outcome_of`: «нет места» / «нет товаров», T-20261110-09)

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
# статусы `trial_demo` (`scene.json`); `pending` (подбор не дошёл до конца) сюда не входит — конвейер (`tools/floorplan/conveyor.py`)
# такую сцену не отдаёт, а подменяет отказом `stage_failed`
SCENE_FURNITURE = {'ok': 'ready', 'partial': 'partial', 'no_products': 'failed', 'refused': 'failed', 'failed': 'failed'}
SCENE_READY = ('ok', 'partial')

# ───────────────────────── исход по комнате: код для страницы и тексты (ru, en) ─────────────────────────
# `furniture_state` — машина состояний (дирижёр), `furniture_outcome` — код для страницы (выбор надписи на любом языке),
# `furniture_code` — точная причина стадии (диагностика). Тексты — готовые на обоих языках, страница может взять свои по коду.
ROOM_STATES = ('pending', 'ready', 'refused', 'not_furnished', 'awaiting_check')
# «ЖДЁТ ПРОВЕРКИ РАЗМЕРА» (владелец 09.11, TG 531/533): гостиную/спальню, где распознавание пометило «размер не сошёлся», конвейер сам
# НЕ обставляет — агент поправит размер и нажмёт «Обустроить» (`release` — комнаты, с которых проверка снята). `done` не держит.
SIZE_CHECK_FLAGS = ('dims_mismatch',)      # флаги комнаты из распознавания (`tools/floorplan/pipeline.py:_room_flags`)
# масштаб ВСЕЙ квартиры не подтверждён (`scale.status == not_verified`) → все гостиные и спальни ждут проверки (TG 533: «не обставлять»);
# False — обставлять как обычно
SCALE_UNVERIFIED_AWAITS_CHECK = True
# мягкая пометка на плане по статусу масштаба (`trial.scale_note`, ru/en): `area` — масштаб по общей площади, комнаты обставляются
# как обычно (решение ведущего, T-20261109-26), но размеры примерные — говорим это
SCALE_NOTE = {
    'area': ('Размеры по общей площади — примерные.', 'Sizes are based on the total floor area — approximate.'),
}
# флаг комнаты в результате, который ставит пересборка «Обустроить» (`tools/floorplan/conveyor.py:Rebuild`): агент согласился
# обставить «как есть» — проверка размера снята, решатели не отказывают по масштабу, страница пишет «размеры примерные»
APPROX_CONSENT = 'approx_consent'
# флаг комнаты с размером, который агент задал правкой комнаты в туре (`tools/floorplan/room_edits.py`, T-20261110-36): размер дал
# человек — проверка размера снята (и масштаба квартиры для неё), «примерно» не пишем, фото можно
USER_DIMS = 'user_dims'
# флаг уличного помещения (балкон, лоджия, терраса) из распознавания (`tools/floorplan/pipeline.py:outdoor_room`, T-20261111-20): вид
# `other` (не обставляется), в `apartment_rooms[]` — `outdoor: true`
OUTDOOR = 'outdoor'
OUTCOME_TEXT = {
    'size_unverified': ('Размер может быть неточным — поправьте и нажмите «Обустроить».',
                        'Size may be approximate — adjust and tap “Furnish”.'),
    'no_products': ('Нет подходящих товаров согласно действующим шаблонам.', 'No suitable products under the current templates.'),
    # товары были, места под диван и ТВ решатель не нашёл (`trial_demo._no_space`, T-20261110-09); две двери и больше — «проходная»
    'no_space': ('Не нашлось места под диван и ТВ.', 'No space for a sofa and TV.'),
    'no_space_walkthrough': ('Проходная комната — не нашлось места под диван и ТВ.', 'Walk-through room — no space for a sofa and TV.'),
    'not_readable': ('Не удалось надёжно построить эту комнату по плану, поэтому мебель не расставлена.',
                     'This room could not be read reliably from the plan, so furniture was not placed.'),
    # у комнаты на плане не нашлось ни двери, ни прохода (`no_entry`, T-20261110-11) — честнее, чем «не разобрана»
    'no_entry': ('Не нашли вход в комнату на плане.', 'We couldn’t find a door into this room.'),
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
    **{c: 'not_readable' for c in ('contour_distorted', 'no_core', 'opening_cut_by_core', 'opening_ambiguous')},
    'no_entry': 'no_entry',
    'scale_unverified': 'scale_unverified', 'living_no_window': 'no_window', 'one_living_furnished': 'largest_living_only',
    'room_kind_not_furnished': 'not_furnished',
    **{c: c for c in TD.SPACE_CODES},
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
    if not ru:
        # T-20261110-33: сокращения и раздельные написания листа — синонимы распознавания (`tools/floorplan/listing.py:alias_key`):
        # «ES» → en-suite, «ST.» → store, «BATH ROOM» → bathroom; английская подпись — полным словом
        al = _alias_key(src)
        ru = _tr_room(al, ROOM_EN_RU, 'и') if al else None
        if ru:
            return cap(ru), (src if al.replace(' ', '') == re.sub(r'\W', '', src.lower()) else cap(al))
    return (cap(ru) if ru else fb(base_ru)), src


def _alias_key(name: str) -> str:
    fp = os.path.join(HERE, '..', 'floorplan')
    if fp not in sys.path:
        sys.path.append(fp)                                 # в конец: модули scout с теми же именами главнее
    import listing
    return listing.alias_key(name)

# ───────────────────────── общий разрешённый список полей товара (все комнаты) ─────────────────────────
ITEM_KEYS = {'role', 'x', 'y', 'rot', 'w', 'd', 'h', 'dims_src', 'sku', 'corner', 'corner_left', 'section', 'elev', 'strategy'}
SKU_KEYS = {'name', 'name_en', 'colour_en', 'colour_ru', 'msid', 'w', 'd', 'h', 'sleep_w'}
# товар как в /demo (см. шапку): цена (₽ витрины), фото — плитка витрины `img/<md5>.jpg`, ссылка — та же партнёрская, магазин
PRODUCT_KEYS = {'price', 'img', 'url', 'shop', 'swatch'}       # swatch — цвет товара по фото (`put_swatches`, T-20261112-29)
# поля 3D-сцены — тем же кодом, что у /demo (`sku_scene`, T-20261112-96): подкраска цвета, разворот модели, «подвесная»
SCENE_SKU_KEYS = {'tint', 'yaw', 'hung', 'fam'}            # fam — семья цветов («Цвета этой модели», `sku_scene.family`)
PUBLIC_SKU_KEYS = SKU_KEYS | PRODUCT_KEYS | SCENE_SKU_KEYS
# куски стадий (внутренние файлы DEV, в выход не идут): плюс ключ товара `sid` — по нему сборщик берёт товар из каталога
STAGE_SKU_KEYS = SKU_KEYS | {'sid'}
FEED_KEYS = PUBLIC_SKU_KEYS | {'style', 'styles', 'src', 'corner'}
BANNED_KEYS = {'url', 'url_direct', 'shop', 'img', 'img_hd', 'price', 'brand'}
# в данных страницы — нигде и никогда: ключи товара у поставщика, служебная прямая ссылка, бренд
NEVER_KEYS = {'sid', 'mid', 'eid', 'probe_url', 'url_direct', 'img_hd', 'brand'}
# где у данных страницы товар: предмет варианта, строки лент замен (`sofa_feed` — лента дивана)
GOODS_AT = re.compile(r'\$\.variants\[\d+\]\.items\[\d+\]\.sku|\$\.feeds\.[^\[\]]+\[\d+\]|\$\.sofa_feed\[\d+\]')
IMG_RE = re.compile(r'img/[0-9a-f]{16}\.jpg')
URL_RE = re.compile(r'https://[^\s"\'<>`\\]{4,2000}')
UK_PARTNER = os.path.join(HERE, '..', '..', 'data', 'partners', 'demo-uk.json')   # британский двойник /demo: курс и наценка
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
    return {'rules': {**FD._rules(), 'soft_roles': FD.soft_roles()}, 'msid_of': FD._msid, 'slot_band': FD._slot_band, 'quiz': quiz_rule(),
            'goods': _demo_goods, 'money_en': uk_money(), 'demo_feeds': _demo_feeds, 'dev_flat': dev_flat(), 'scene_live': scene_live}


PARTNERS_DIR = os.path.join(HERE, '..', '..', 'data', 'partners')


def dev_flat(root: str = PARTNERS_DIR) -> dict | None:
    """ОТДЕЛКА ЗАСТРОЙЩИКА В ТУРЕ (T-20261110-37 Г, план `tour-as-demo-01`): своего застройщика у пробы нет — по умолчанию отделка
    витрины, как в /demo: по-русски квартира-хозяйка витрины (`sources.demoData` = `/demo/demo-data.json`, не двойник), по-английски
    её британский двойник (`enTwin`, `data/partners/demo-uk.json`). Страница берёт группы опций карточкой `/api/apartments/<id>`
    (`index.html:loadFlatCard`, в туре — только опции, без шапки квартиры). → {'ru': id, 'en': id} или None."""
    try:
        apts = [a for fn in sorted(os.listdir(root)) if fn.endswith('.json')
                for a in (json.load(open(os.path.join(root, fn), encoding='utf-8')).get('apartments') or [])]
    except (OSError, ValueError):
        return None
    twins = {a.get('enTwin') for a in apts if a.get('enTwin')}
    own = next((a for a in apts if (a.get('sources') or {}).get('demoData') == '/demo/demo-data.json' and a.get('id') not in twins), None)
    if not own:
        return None
    en = own.get('enTwin') if own.get('enTwin') in {a.get('id') for a in apts} else own['id']
    return {'ru': own['id'], 'en': en}


def _demo_feeds() -> dict:
    import demo_feeds as DF
    return DF.load()


def _demo_goods(sid, role):
    """Товар каталога; фото — плитка витрины по ключу, если своей плитки нет (товар пула ленты, подставленный по слоту, T-37)."""
    import demo_feeds as DF
    return catalog_goods(sid, role, tile=DF.tile_of)


# ───────────────────────── товар как в /demo (T-20261110-25) ─────────────────────────

def demo_img(u) -> str | None:
    """Фото товара — плитка витрины `/demo` (`flat215_demo.fetch_images`: `img/<md5 адреса>.jpg`); тур отдаёт `img/*` переадресацией
    на `/demo/img/` (`lib/trial/tour.ts:SHARED_IMG`). `u` — адрес или адреса по порядку (`goods_img_urls`): первая лежащая плитка.
    Плитки нет — фото нет (как у предмета /demo, не скачавшего фото: «нет фото»). Плитки докачивает ночь (`cache_bank_images`)."""
    import flat215_demo as FD
    for x in ([u] if isinstance(u, str) else (u or [])):
        if isinstance(x, str) and x:
            name = hashlib.md5(x.encode()).hexdigest()[:16] + '.jpg'
            if os.path.isfile(os.path.join(FD.OUT, 'img', name)):
                return f'img/{name}'
    return None


def goods_img_urls(b: dict | None, m: dict | None) -> list:
    """Адреса фото товара по порядку (T-20261110-25/2): банка — как у товара `/demo`; затем каталога (`catalog_media`, адрес
    берётся в момент кэширования, банк не переписываем) — у товара без `img` в банке или с мёртвым адресом банка."""
    out: list = []
    for u in ((b or {}).get('img'), (m or {}).get('img')):
        if isinstance(u, str) and u and u not in out:
            out.append(u)
    return out


# ───────────────────────── плитки товаров банков пробы (T-20261110-25/2) ─────────────────────────
# Ночь (`refresh_daily.sh`, шаг `trial_images` сразу за сборкой витрины, до публикации): плитки ВСЕХ товаров банков пробы — тем же
# кодом (`flat215_demo.fetch_images`) в ту же папку (`flat215_demo.OUT/img`), публикует их та же выкладка витрины
# (`publish_demo.sh`: папка сборки целиком). Папку локально никто не чистит, поэтому уже скачанное не перекачивается.
IMG_DIR_CAP_MB = 300            # потолок папки плиток (диск DEV тесный): с ожидаемой докачкой выше — не качаем, WARN
IMG_EST_KB = 60                 # оценка на товар: плитка ~15 КБ + крупная ~36 КБ (замер demo-26 Д)
IMG_FAIL_WARN_SHARE = 0.25      # не скачалось больше этой доли попыток — WARN (обычные мёртвые ссылки фида — тише)


def _dir_mb(path: str) -> float:
    try:
        return sum(e.stat().st_size for e in os.scandir(path) if e.is_file()) / 1e6
    except OSError:
        return 0.0


def bank_img_plan(idx: dict, media) -> tuple[dict, dict]:
    """{sid: [адреса фото по порядку]} по всем товарам банков пробы + счёт источников: `bank` — адрес есть в банке,
    `catalog` — только в каталоге, `none` — нигде (останется «нет фото»)."""
    plan, src = {}, {'bank': 0, 'catalog': 0, 'none': 0}
    for sid, b in idx.items():
        mid, eid = sid.split('_', 1) if '_' in sid else (sid, '')
        urls = goods_img_urls(b, media(mid, eid) if eid else None)
        plan[sid] = urls
        src['bank' if b.get('img') else 'catalog' if urls else 'none'] += 1
    return plan, src


def cache_bank_images(idx: dict | None = None, media=None, fetch=None, imgdir: str | None = None, dry: bool = False,
                      log=print) -> dict:
    """Докачать плитки товаров банков пробы. Первый проход — первый адрес у товаров без плитки; второй — адрес каталога у тех, чей
    адрес банка не скачался. Итог — счётчики (до/после, источники, отказы по причинам, размер папки) строками в журнал."""
    import flat215_demo as FD
    idx = _bank() if idx is None else idx
    if media is None:
        import catalog_media as CM
        try:
            CM._load()
            media = CM.media
        except Exception as e:  # noqa: BLE001 — без каталога качаем адреса банка, громко
            log(f'WARN:trial_images: каталог недоступен ({str(e)[:120]}) — только адреса банка')
            media = lambda mid, eid: None  # noqa: E731
    fetch = fetch or FD.fetch_images
    imgdir = imgdir or os.path.join(FD.OUT, 'img')

    def has(u):
        return os.path.isfile(os.path.join(imgdir, FD.img_name(u)))

    def tiled():
        return sum(1 for us in plan.values() if any(has(u) for u in us))

    plan, src = bank_img_plan(idx, media)
    before = tiled()
    need = sorted({us[0] for us in plan.values() if us and not any(has(u) for u in us)})
    size0 = _dir_mb(imgdir)
    st = {'goods': len(plan), 'tiled_before': before, 'sources': src, 'to_fetch': len(need), 'dir_mb_before': round(size0, 1)}
    log(f'плитки товаров пробы: товаров {len(plan)}, с плиткой {before}; адрес фото — из банка {src["bank"]}, только из каталога '
        f'{src["catalog"]}, нигде {src["none"]}; качать {len(need)}; папка {size0:.1f} МБ')
    if dry:
        return st
    if size0 + len(need) * IMG_EST_KB / 1000 > IMG_DIR_CAP_MB:
        log(f'WARN:trial_images: папка плиток {size0:.0f} МБ + ~{len(need) * IMG_EST_KB / 1000:.0f} МБ докачки > потолка '
            f'{IMG_DIR_CAP_MB} МБ — не качаю')
        return {**st, 'capped': True}
    r1 = fetch(need, imgdir) if need else {'got': {}, 'fail': {}}
    # второй адрес (каталога) — только тем, у кого первый не скачался
    alt = sorted({u for us in plan.values() if us and not any(has(x) for x in us) for u in us[1:]})
    r2 = fetch(alt, imgdir) if alt else {'got': {}, 'fail': {}}
    after = tiled()
    fail: dict = {}
    for r in (r1, r2):
        for k, v in (r.get('fail') or {}).items():
            fail[k] = fail.get(k, 0) + v
    tried = len(need) + len(alt)
    size1 = _dir_mb(imgdir)
    st.update({'catalog_retry': len(alt), 'tiled_after': after, 'fail': fail, 'dir_mb_after': round(size1, 1)})
    log(f'плитки товаров пробы: с плиткой {before} → {after} из {len(plan)}; адрес каталога вторым — {len(alt)}; '
        f'{FD.fail_text(fail)}; без адреса фото — {src["none"]}; папка {size0:.1f} → {size1:.1f} МБ')
    nfail = sum(fail.values())
    if tried and nfail > tried * IMG_FAIL_WARN_SHARE:
        log(f'WARN:trial_images: не скачалось {nfail} из {tried} попыток — {FD.fail_text(fail)}')
    return st


def _bank_sid(it: dict) -> str | None:
    s = it.get('sid')
    if isinstance(s, str) and s:
        return s.replace(':', '_', 1)
    return f"{it['mid']}_{it['eid']}" if it.get('mid') and it.get('eid') else None


def bank_index(paths: list | None = None) -> dict:
    """{sid «mid_eid»: товар банка} — банки, из которых этапы пробы берут мебель: гостиная (`trial_demo.sets_path`, env `TRIAL_SETS`)
    и спальня (env `TRIAL_BEDROOM_SETS` или `sets-bedroom.json`). Товар — любой словарь с названием и ключом поставщика (наборы,
    `alternates`). Нет файла — пропуск."""
    if paths is None:
        paths = [TD.sets_path(), os.environ.get('TRIAL_BEDROOM_SETS') or os.path.join(HERE, 'sets-bedroom.json')]
    idx: dict = {}

    def walk(o):
        if isinstance(o, dict):
            sid = _bank_sid(o) if o.get('name') else None
            if sid:                     # в банке есть и урезанные копии товара (название + цена) — поля сливаем, первое непустое
                cur = idx.setdefault(sid, {})
                cur.update({k: v for k, v in o.items() if v not in (None, '') and cur.get(k) in (None, '')})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for p in paths:
        if p and os.path.isfile(p):
            walk(json.load(open(p, encoding='utf-8')))
    return idx


def catalog_goods(sid: str | None, role: str, bank: dict | None = None, tile=None) -> dict | None:
    """Товар по ключу `sid` («mid_eid») — ровно как у товара `/demo` (`flat215_demo._sku`): название, фото, партнёрская ссылка и
    магазин — из товара БАНКА, цена — текущая из каталога `catalog_media`, нет её — цена банка. Товара нет в банке (старые сцены) —
    всё из каталога. Английское название — `trial_demo._names_en` (правило живой витрины). Не нашли / без названия / без цены — None
    (предмет остаётся нейтральным); каталог говорит «ушёл из продажи» — None и для товара банка (как демо снимает его из банка). Каталог недоступен — исключение."""
    if not isinstance(sid, str) or '_' not in sid:
        return None
    mid, eid = sid.split('_', 1)
    import catalog_media as CM
    m = CM.media(mid, eid) or {}
    b = (bank if bank is not None else _bank()).get(sid)
    if m.get('state') == 'gone':                          # снят с продажи — и товар банка тоже (`flat215_demo.drop_unavailable`, T-96)
        return None
    if b:
        src, price = b, m.get('price') or b.get('price')
    elif m:
        src, price = m, m.get('price')
    else:
        return None
    if not src.get('name') or not isinstance(price, (int, float)) or not price > 0:
        return None
    url = src.get('url') if URL_RE.fullmatch(str(src.get('url') or '')) else None
    ne = TD._names_en({'name': src['name'], 'mid': mid, 'eid': eid}, role)
    return {'name': src['name'], 'name_en': ne.get('name_en') or None, 'colour_en': ne.get('colour_en') or None, 'price': int(price),
            'img': demo_img(goods_img_urls(b, m)) or (tile(sid) if tile else None), 'url': url, 'shop': (src.get('shop') or None)}


_BANK: dict | None = None


def _bank() -> dict:
    global _BANK
    if _BANK is None:
        _BANK = bank_index()
    return _BANK


def uk_money() -> dict | None:
    """Английская цена — ровно как у английского `/demo` (`index.html:fxRateOf`): рубли × курс карточки британского двойника × его
    наценка (`demoMask.priceMarkup`, владелец 30.10 demo-31). Источник один — `data/partners/demo-uk.json`; нет/кривой — None
    (страница на английском тогда цену не пишет)."""
    try:
        p = json.load(open(UK_PARTNER, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    fx = p.get('fx') or {}
    if not (fx.get('from') == 'RUB' and fx.get('to') == p.get('currency') and isinstance(fx.get('rate'), (int, float)) and fx['rate'] > 0):
        return None
    twin = next((a for a in p.get('apartments') or [] if (a.get('sources') or {}).get('demoData') == '/demo/demo-data.json'
                 and a.get('demoMask')), None)
    mk = ((twin or {}).get('demoMask') or {}).get('priceMarkup')
    return {'currency': p['currency'], 'fx': {k: fx.get(k) for k in ('from', 'to', 'rate', 'asOf')},
            'priceMarkup': mk if isinstance(mk, (int, float)) and mk > 0 else 1}


class _Goods:
    """Обёртка резолвера товара на одну сборку: каталог недоступен — товары выключаются на всю сборку (флаг `goods_unavailable`),
    тур собирается как раньше, без цен, а не падает."""

    def __init__(self, fn):
        self.fn, self.down = fn, None

    def __call__(self, sid, role):
        if not self.fn or self.down:
            return None
        try:
            return self.fn(sid, role)
        except Exception as e:  # noqa: BLE001 — сбой каталога не роняет тур: без товаров, с флагом
            self.down = str(e)[:200]
            return None


def attach_goods(sku: dict, sid, role: str, goods) -> dict:
    """Поля товара /demo в `sku` (на месте): название и английское название, цвет, цена, фото, ссылка, магазин. Нет товара — как было."""
    g = goods(sid, _base_role(role)) if goods and sid else None
    if g:
        sku.update({k: v for k, v in g.items() if v not in (None, '')})
    return sku


def put_swatches(variants: list, swatch=None) -> int:
    """ЦВЕТ ТОВАРА НА ПЛАНЕ (T-20261112-29, владелец: «на схеме диван фиолетовый, а в 3D бежевый»): каждому предмету с плиткой витрины —
    `sku.swatch` '#rrggbb' тем же правилом, что образцы цвета /demo (`flat215_demo.swatch_hex` → `_swatch_tone`: цвет ткани по фото).
    Схема комнаты и план рисуют предмет этим цветом (`index.html:planCol`); нет плитки — нейтральный цвет роли. → сколько отмечено."""
    if swatch is None:
        try:
            import flat215_demo as FD
        except Exception:  # noqa: BLE001 — без модуля витрины (тесты без окружения) план рисует нейтральным цветом роли
            return 0
        cache: dict = {}
        swatch = lambda img: FD.swatch_hex(img, FD.OUT, cache)   # noqa: E731
    n = 0
    for v in variants:
        for it in (v.get('items') or []) + (v.get('decor') or []):
            sk = it.get('sku') if isinstance(it, dict) else None
            if not isinstance(sk, dict) or not sk.get('img') or sk.get('swatch'):
                continue
            h = swatch(sk['img'])
            if h:
                sk['swatch'] = h
                n += 1
    return n


def goods_meta(variants: list, money_en) -> dict:
    """`trial.goods` — у предметов есть товары (страница показывает цены, фото и «В магазин», как /demo); `trial.money_en` — курс и
    наценка английской цены. Товаров нет — полей нет (страница — прежний режим без цен)."""
    has = any(isinstance((it.get('sku') or {}).get('price'), (int, float)) for v in variants for it in v.get('items') or [])
    return {'goods': True, **({'money_en': money_en} if money_en else {})} if has else {}


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


def panel_part(title: str | None) -> tuple[str, str] | None:
    """Панель — не этаж, а отдельная часть дома с именем помещения («Garage», «Гараж»): → (по-русски, по-английски), иначе None.
    T-20261111-11 (bs30): панель «Garage» на плане тура подписывалась «Этаж 3» и снимала подтверждение этажей дома."""
    src = re.sub(r'\s+', ' ', str(title or '').strip())
    if not src or storey_of(src) is not None:
        return None
    if src.isupper():
        src = ' '.join(w if len(w) <= 3 else w[:1] + w[1:].lower() for w in src.split(' '))
    if _CYR.search(src):
        en = _tr_room(src, ROOM_RU_EN, 'and')
        return (src[:1].upper() + src[1:], en[:1].upper() + en[1:]) if en and not _CYR.search(en) else None
    ru = _tr_room(src, ROOM_EN_RU, 'и')
    return (ru[:1].upper() + ru[1:], src) if ru else None


def storeys(panels: list) -> tuple[dict, list]:
    """Индекс панели → этаж. Этаж считается подтверждённым, только если подписаны ВСЕ панели этажей и разными этажами; панель —
    часть дома с именем помещения (`panel_part`: гараж) — не этаж, этажа у неё нет и подтверждение она не снимает."""
    idx = [i for i, p in enumerate(panels) if panel_part(p.get('title')) is None]
    vals = [storey_of(panels[i].get('title')) for i in idx]
    if not idx or any(v is None for v in vals) or len(set(vals)) != len(vals):
        return {}, ['storey_unconfirmed'] if len(idx) > 1 else []
    return dict(zip(idx, vals)), []


_NUMBERED = re.compile(r'^(.*?)\s*(\d{1,3})$')


def room_order(panels: list, storey_map: dict) -> list:
    """Комнаты в порядке показа (главная, список): этажи снизу вверх (этаж подтверждён — по нему, иначе по порядку панелей), внутри
    этажа — как на чертеже, но одноимённые с номером («Bedroom 2», «Bedroom 1») — по номеру на своих же местах (TG 593: «Спальня 2»
    шла раньше «Спальни 1»). Остальные не двигаются."""
    out = []
    for i in sorted(range(len(panels)), key=lambda i: (storey_map.get(i, 0), i)):
        src = panels[i]['rooms']
        rooms = list(src)
        groups: dict = {}
        for k, r in enumerate(src):
            m = _NUMBERED.match(str(r.get('name') or '').strip())
            if m and m.group(1).strip():
                groups.setdefault(m.group(1).strip().lower(), []).append((int(m.group(2)), k))
        for g in groups.values():                     # места группы те же, комнаты на них — по номеру
            for pos, (_, k) in zip(sorted(k for _, k in g), sorted(g)):
                rooms[pos] = src[k]
        out += rooms
    return out


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


ANNEX_TOL_CM = 1.5


def _portals(ops: list) -> list:
    return sorted((o['wall'], float(o['offset_cm']), float(o['width_cm'])) for o in ops
                  if o.get('kind') == 'opening' or (o.get('kind') == 'door' and o.get('swing_cm') == 0))


def annexes_of(panel: dict, room: dict, geo: dict, cfg: dict) -> list:
    """Пристройки 3D-комнаты (`trial_room.annexes`, T-20261111-08) для ГОТОВОЙ коробки `geo` (w, d, openings): ядро ищется заново
    по контуру комнаты — то, у которого те же размеры и те же порталы-стыки. Так одно правило и у новой сборки, и у пересборки
    (`trial_reissue`: коробка прежняя, ядра в ней нет), без нового поля в записях стадий. Порталов нет — пристроек нет (быстро);
    ядро не нашлось (гостиная, расширенная мебелью к стенам ниш, `core_extended`) или проёмы неоднозначны — пусто, портал как был."""
    if not _portals(geo.get('openings') or []):
        return []
    m = _core_of(panel, room, geo, cfg)
    return TR.annexes(m[0], m[1], cfg) if m else []


def _core_of(panel: dict, room: dict, geo: dict, cfg: dict):
    """Ядро ГОТОВОЙ коробки `geo` в кадре контура комнаты: прямоугольник тех же размеров с теми же порталами-стыками →
    (кандидат ядра, проёмы в кадре, кадр `ortho_frame`); не нашлось или проёмы неоднозначны — None."""
    want = _portals(geo.get('openings') or [])
    from planner.geometry import largest_free_rectangles
    try:
        ours, amb = TR._openings_of(panel, room, cfg)
        if amb:
            return None
        fr = TR.ortho_frame(room['contour'], cfg)
        ops = [TR._place_opening(fr['poly'], o, fr['T'], cfg) for o in ours]
    except TR.Refusal:
        return None
    seen = set()
    for side in (float(cfg['core_min_side_cm']), 150.0):         # 150 — ядра спален уже порога гостиной (`trial_bedroom`)
        for g in largest_free_rectangles(fr['poly'], min_side_cm=side, limit=48):
            rect = tuple(round(v, 1) for v in g.bounds)
            if rect in seen:
                continue
            seen.add(rect)
            if abs(rect[2] - rect[0] - float(geo['w'])) > ANNEX_TOL_CM or abs(rect[3] - rect[1] - float(geo['d'])) > ANNEX_TOL_CM:
                continue
            cand = TR.core_candidate(fr['poly'], g.bounds, ops, TR.need_group(), cfg)
            so = TR.solver_openings(cand, cfg)
            # коробка, собранная до T-20261112-41, на месте портала широкой внутренней «двери» (`_wide`) держит дверь — сверяем и без него
            for got in (_portals(so), _portals([o for o in so if not o.get('_wide')])):
                if len(got) == len(want) and all(p[0] == q[0] and abs(p[1] - q[1]) <= ANNEX_TOL_CM and abs(p[2] - q[2]) <= ANNEX_TOL_CM
                                                 for p, q in zip(got, want)):
                    return cand, ops, fr
    return None


OUTDOOR_GAP_MAX_CM = 80.0        # наружная стена между ядром и балконом: толщина стены листа с запасом
OUTDOOR_OVERLAP_MIN_CM = 60.0    # общая часть стороны ядра и балкона: меньше — балкон соседней комнаты, виден лишь углом


def outdoor_of(panel: dict, room: dict, geo: dict, cfg: dict, annexes: list = ()) -> list:
    """БАЛКОН В 3D КОМНАТЫ (T-20261111-20/2, владелец TG 1624: «все элементы, как на плане»): уличное помещение панели
    (флаг `outdoor`) за стороной ядра комнаты или её пристройки `annexes` (терраса у хвоста Г-образной гостиной) → пристройка `outdoor: true` той же формы, что `annexes` (x, y — от юго-западного угла
    ядра, оси те же). Рисует `lib/viewer3d/rooms.ts:buildOutdoor`: плита и ограждение, без стен и потолка; выход — дверь в стене самой
    комнаты (её проёмы), поэтому у пристройки проёмов нет. Толщина наружной стены между ними (`OUTDOOR_GAP_MAX_CM`) снимается:
    плита примыкает к стене комнаты. Балкон у стены нескольких комнат — в 3D каждой; меньше `OUTDOOR_OVERLAP_MIN_CM` общей стороны —
    не её балкон. Нет уличных помещений или ядра — пусто."""
    outs = [r for r in panel.get('rooms') or [] if OUTDOOR in (r.get('flags') or []) and r is not room]
    if not outs:
        return []
    m = _core_of(panel, room, geo, cfg)
    if m is None:
        return []
    from shapely.geometry import Polygon
    cx, cy = m[0]['rect'][:2]
    T = m[2]['T']
    # части комнаты в 3D: ядро и её пристройки (хвост Г-образной гостиной у террасы — TGva) — в кадре контура
    parts = [tuple(m[0]['rect'])] + [(cx + a['x'], cy + a['y'], cx + a['x'] + a['w'], cy + a['y'] + a['d'])
                                     for a in annexes if not a.get('outdoor')]
    res = []
    for o in outs:
        b = o.get('bbox') or {}
        ring = o.get('contour') or ([[b['x'], b['y']], [b['x'] + b['w'], b['y']], [b['x'] + b['w'], b['y'] + b['d']],
                                     [b['x'], b['y'] + b['d']]] if b else None)
        if not ring:
            continue
        bx0, by0, bx1, by1 = Polygon([T(p) for p in ring]).buffer(0).bounds
        w, d = bx1 - bx0, by1 - by0
        hit = None
        for x0, y0, x1, y1 in parts:
            sides = {'south': (max(bx0, x0), min(bx1, x1), y0 - by1), 'north': (max(bx0, x0), min(bx1, x1), by0 - y1),
                     'west': (max(by0, y0), min(by1, y1), x0 - bx1), 'east': (max(by0, y0), min(by1, y1), bx0 - x1)}
            for wall, (lo, hi, gap) in sides.items():
                if hi - lo >= OUTDOOR_OVERLAP_MIN_CM and -ANNEX_TOL_CM <= gap <= OUTDOOR_GAP_MAX_CM:
                    # плита примыкает к стороне части вплотную (толщина стены снята); координаты — от угла ядра
                    x = {'west': x0 - w, 'east': x1}.get(wall, bx0) - cx
                    y = {'south': y0 - d, 'north': y1}.get(wall, by0) - cy
                    hit = (x, y, wall)
                    break
            if hit:
                break
        if hit:
            # `wall` — сторона КОМНАТЫ (её части), к которой примыкает плита: с неё ограждения нет, там стена дома с дверью
            res.append({'x': _num(hit[0]), 'y': _num(hit[1]), 'w': _num(w), 'd': _num(d), 'outdoor': True, 'wall': hit[2],
                        'openings': []})
    return res


def shell_of(panel: dict, room: dict, geo: dict, cfg: dict) -> tuple[list, list]:
    """Всё, что 3D дорисовывает к коробке `geo` (w, d, openings), → (проёмы коробки, пристройки). Одно место для сборки и пересборки
    (`trial_reissue`): пристройки-остатки (`annexes_of`), балкон (`outdoor_of`), стыки с пристройками — без перемычки
    (`trial_room.mark_junctions`) и кусок прохода за порталом наружу (`trial_room.portal_stubs`; оба — T-20261112-41)."""
    ax = annexes_of(panel, room, geo, cfg)
    ax += outdoor_of(panel, room, geo, cfg, ax)
    ops = TR.mark_junctions(geo.get('openings') or [], ax)
    ax += TR.portal_stubs(float(geo['w']), float(geo['d']), ops, ax, cfg)
    return ops, ax


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
    return clean_colour((NE.translate(name, role, D).get('colour') or '').strip())


def clean_colour(c: str | None) -> str:
    """Готовый английский цвет (строка сцены `trial_demo`: `colour_en`) — пропускаем только слова словарей цвета, материала, рисунка."""
    c = (c or '').strip()
    if not c:
        return ''
    NE, D = _names_en()
    vocab = {w for t in ('colours', 'materials', 'patterns') for v in (D.get(t) or {}).values() for w in re.findall(r'[a-z]+', str(v).lower())}
    words = re.findall(r'[^\s,/-]+', c.lower())
    return c if words and not NE.bad(c, D) and all(w in vocab or w in ('and', 'with') for w in words) else ''


# ───────── имена предметов тура уникальны (T-20261109-35/3) ─────────
# Страница узнаёт товар по `sku.name` (строка списка, «Заменить», лента, примерка) — как в `/demo`, где названия магазина разные.
# В туре имя нейтральное по роли, и два разных дивана звались одинаково: «Заменить» отмечала не тот, лента пустела. Имя —
# «<Роль> · Ш×Г см»; один товар (роль, модель, размер) — одно имя во всём туре (в разных стилях тоже: лента замен общая);
# разные товары с одинаковой подписью — « · 2», « · 3» в порядке появления.

_ADJ = ('ый', 'ий', 'ой')
_GENDER = {'кровать': 'f', 'ткань': 'f', 'сталь': 'f', 'мебель': 'f', 'ясень': 'm', 'текстиль': 'm'}


def _gender(phrase: str) -> str:
    """Род существительного во фразе («Прикроватная тумба» → тумба → ж., «ТВ-тумба» → ж., «велюр» → м.): первое слово не-прилагательное."""
    words = [w for w in re.split(r'[\s-]+', (phrase or '').lower().replace('ё', 'е')) if w]
    nouns = [w for w in words if not w.endswith(_ADJ + ('ая', 'яя', 'ое', 'ее'))] or words[-1:]
    w = nouns[-1] if nouns else ''
    if w in _GENDER:
        return _GENDER[w]
    return 'f' if w.endswith(('а', 'я')) else ('n' if w.endswith(('о', 'е')) else 'm')


def _agree(adj: str, g: str) -> str:
    """Прилагательное мужского рода → нужный род; в составном («темно-серый») меняется последняя часть."""
    if g == 'm':
        return adj
    head, sep, last = adj.rpartition('-')
    if last.endswith('ий') and len(last) > 2 and last[-3] == 'н':           # синий → синяя, синее
        last = last[:-2] + ('яя' if g == 'f' else 'ее')
    elif last.endswith(_ADJ):                                                 # серый, бургундский, голубой
        last = last[:-2] + ('ая' if g == 'f' else 'ое')
    return head + sep + last


_RU_VOCAB: dict = {}


def _ru_vocab() -> dict:
    """Английская фраза цвета/материала/рисунка → (русская форма, прилагательное ли) по словарю `names_en` (обратно);
    у прилагательного — мужской род (с «ё», если есть), его потом согласуем."""
    if not _RU_VOCAB:
        _, D = _names_en()
        for t in ('colours', 'materials', 'patterns'):
            forms: dict = {}
            for ru, en in (D.get(t) or {}).items():
                if _CYR.search(ru):
                    forms.setdefault(str(en).lower(), []).append(ru)
            for en, rus in forms.items():
                adj = [r for r in rus if all(w.endswith(_ADJ) for w in r.split())]
                pick = next((r for r in adj if 'ё' in r), adj[0]) if adj else rus[0]
                _RU_VOCAB.setdefault(en, (pick, bool(adj)))
    return _RU_VOCAB


def colour_ru(colour: str | None, item_ru: str) -> str:
    """Цвет/материал по-русски из готового `colour_en` (русского названия товара в данных тура нет): фразы словаря, прилагательное
    согласовано с материалом после него («серая рогожка», «мятный велюр»), без материала — с предметом («Прикроватная тумба» →
    «белая»). Хоть одно слово не из словаря — пусто (лучше без строки, чем полу-английская)."""
    toks = re.findall(r'[^\s/]+|/', (colour or '').lower())
    V = _ru_vocab()
    parts, i = [], 0
    while i < len(toks):
        if toks[i] == '/':
            parts.append(('/', '', False))
            i += 1
            continue
        for n in (4, 3, 2, 1):
            seg = toks[i:i + n]
            if '/' in seg:
                continue
            phrase = ' '.join(seg)
            if phrase in V:
                parts.append(('w', *V[phrase]))
                i += n
                break
            if n == 1 and phrase == 'and':
                parts.append(('w', 'и', False))
                i += 1
                break
        else:
            return ''
    if not parts:
        return ''
    out = []
    for k, (kind, ru, adj) in enumerate(parts):
        if kind == '/':
            out.append('/')
            continue
        if adj:
            noun = next((r for kk, r, a in parts[k + 1:] if kk == 'w' and not a and r != 'и'), None)
            ru = ' '.join(_agree(w, _gender(noun or item_ru)) for w in ru.split())
        out.append(ru)
    return re.sub(r'\s*/\s*', '/', ' '.join(out)).strip()


def _dims(sku: dict, it: dict) -> tuple[int, int] | None:
    w, d = sku.get('w', it.get('w')), sku.get('d', it.get('d'))
    return (round(w), round(d)) if isinstance(w, (int, float)) and isinstance(d, (int, float)) and w > 0 and d > 0 else None


def name_items(variants: list) -> None:
    """Имена предметов всех вариантов тура — уникальные и понятные (см. выше), плюс `colour_ru`. Меняет варианты на месте."""
    names: dict = {}                 # товар → (ru, en)
    taken: dict = {}                 # подпись ru → сколько разных товаров уже её носят
    for v in variants:
        for it in v.get('items') or []:
            sku = it.get('sku')
            if not isinstance(sku, dict) or isinstance(sku.get('price'), (int, float)):
                continue                             # товар каталога (`attach_goods`) — его название, как у /demo
            base = _base_role(it.get('role') or '')
            dm = _dims(sku, it)
            key = (base, sku.get('msid'), dm, sku.get('sleep_w'))
            role_ru, role_en = neutral_names(base)
            if key not in names:                     # от нейтрального имени, а не от `sku.name`: повторная сборка не удвоит размер
                ru, en = role_ru, role_en
                sw = sku.get('sleep_w')
                if isinstance(sw, (int, float)) and sw > 0:          # кровать — с шириной спального места (`_part_item`)
                    ru, en = f'{ru} {round(sw)} см', f'{en} {round(sw)} cm'
                if dm:
                    ru, en = f'{ru} · {dm[0]}×{dm[1]} см', f'{en} · {dm[0]}×{dm[1]} cm'
                n = taken[ru] = taken.get(ru, 0) + 1
                names[key] = (ru, en) if n == 1 else (f'{ru} · {n}', f'{en} · {n}')
            ru, en = names[key]
            sku.update(name=ru, name_en=en)
            c = colour_ru(sku.get('colour_en'), role_ru)
            if c:
                sku['colour_ru'] = c
            else:
                sku.pop('colour_ru', None)


def public_item(it: dict, sku_keys=PUBLIC_SKU_KEYS) -> dict:
    """Предмет варианта — только разрешённые поля: общий фильтр для гостиной, спален и любых будущих комнат. Стадии (внутренний файл)
    зовут его с `STAGE_SKU_KEYS` (с `sid`, без полей товара), сборщик — с `PUBLIC_SKU_KEYS` (поля товара, без `sid`)."""
    out = {k: v for k, v in it.items() if k in ITEM_KEYS}
    if isinstance(out.get('sku'), dict):
        out['sku'] = {k: v for k, v in out['sku'].items() if k in sku_keys}
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


def _goods_ok(k: str, v) -> bool:
    """Вид поля товара в данных страницы: цена — число ≥ 0, фото — плитка витрины, ссылка — https без кавычек и пробелов, магазин —
    короткая строка без разметки. Иное — утечка/мусор, отказ."""
    if k == 'price':
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
    if k == 'img':
        return isinstance(v, str) and bool(IMG_RE.fullmatch(v))
    if k == 'url':
        return isinstance(v, str) and bool(URL_RE.fullmatch(v))
    if k == 'swatch':                                 # цвет товара по фото (`put_swatches`) — только '#rrggbb'
        return isinstance(v, str) and bool(re.fullmatch(r'#[0-9a-f]{6}', v))
    if k == 'shop':
        return isinstance(v, str) and 0 < len(v) <= 80 and not re.search(r'[<>"`\\]', v)
    return False


def assert_public(obj, tokens: list, goods: bool = False) -> None:
    """Проверка очисткой ВЫВОДА: ни запрещённых полей, ни ссылок, ни названий товаров/магазинов во всём JSON → иначе `shop_leak`.
    `goods` (данные страницы, T-20261110-25): поля товара /demo (`PRODUCT_KEYS`) разрешены ТОЛЬКО на местах товара (`GOODS_AT`) и
    проверенного вида; их значения и название товара там — не утечка; `NEVER_KEYS` (`sid` и пр.) — нигде. Стадии зовут без `goods`."""
    pats = [re.compile(r'(?<!\w)' + re.escape(t) + r'(?!\w)') for t in tokens]

    def walk(v, path):
        if isinstance(v, dict):
            at = goods and bool(GOODS_AT.fullmatch(path))
            for k, x in v.items():
                if goods and k in NEVER_KEYS:
                    raise BundleRefused('shop_leak', f'запрещённое поле {path}.{k}')
                if at and k in PRODUCT_KEYS:
                    if x is not None and not _goods_ok(k, x):
                        raise BundleRefused('shop_leak', f'поле товара {path}.{k} не того вида')
                    continue
                if at and k == 'name' and isinstance(x, str):
                    continue                         # название товара на месте товара — как у /demo
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
    """Комната показана ядром-прямоугольником заметно меньше контура (Г-образная, скошенная) — `approx`: страница помечает видимо.
    Так же — контур разошёлся с площадью, напечатанной на листе (`area_label_off`, `pipeline.area_shown`, T-20261111-12): подпись
    показана числом, а нарисованная форма — приблизительная."""
    if 'area_label_off' in (room.get('flags') or []):
        return True
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
    `no_space` / `no_space_walkthrough` / `not_readable` / `scale_unverified` / `no_window` / `largest_living_only` / `not_furnished` /
    `failed`), точная причина, тексты ru/en."""
    if state == 'ready':
        outcome = 'furnished'
    elif state == 'pending':
        outcome = 'pending'
    elif state == 'not_furnished':
        outcome = 'not_furnished'
    elif state == 'awaiting_check':
        outcome = 'size_unverified'
    else:
        outcome = CODE_OUTCOME.get(code or '', 'failed')
        outcome = 'failed' if outcome == 'not_furnished' else outcome
    ru, en = OUTCOME_TEXT.get(outcome, (None, None))
    return {'furniture_state': state, 'furniture_outcome': outcome, 'furniture_code': code, 'furniture_text': ru, 'furniture_text_en': en}


def _item(row: dict, place: dict | None, msid_of, goods=None) -> dict:
    """Строка сцены `trial_demo` → предмет варианта по разрешённому списку: имя — нейтральное по роли, модель — `msid`.
    Строка нового формата (`trial_demo.public_row`) несёт `msid` сама: там он уже проверен правилом «годная модель» (нет годной — null,
    в кадре серая форма); по `sid` его тогда НЕ выводим — иначе вернётся модель семьи, снятая проверкой. Цвет — её `colour_en`.
    Товар (название, цена, фото, ссылка, магазин) — из каталога по `sid` строки (`attach_goods`), не из самой строки."""
    p = place or {}
    h = row.get('h') if row.get('h') is not None else p.get('h')
    ru, en = neutral_names(row['role'])
    msid = row['msid'] if 'msid' in row else (msid_of(row.get('sid')) if row.get('sid') else None)
    colour = clean_colour(row['colour_en']) if row.get('colour_en') else colour_en(row.get('name'), _base_role(row['role']))
    sku = attach_goods({'name': ru, 'name_en': en, 'colour_en': colour, 'msid': msid, 'w': row.get('w'), 'd': row.get('d'), 'h': h},
                       row.get('sid'), row['role'], goods)
    out = public_item({'role': row['role'], 'x': row['x'], 'y': row['y'], 'rot': int(row.get('rot') or 0), 'w': row.get('w'), 'd': row.get('d'),
                       'h': h, 'dims_src': 'каталог', 'sku': sku, 'corner': bool(row.get('corner')), 'corner_left': bool(p.get('corner_left')),
                       'section': p.get('section')})
    return _keep_sid(out, row.get('sid'))


def _keep_sid(it: dict, sid: str | None) -> dict:
    """Ключ товара на время сборки — `sku._sid` (подкраске цвета нужен товар, `scene_fields`); в данные страницы не идёт: его снимает
    `scene_fields` до `assert_public`."""
    if sid and isinstance(it.get('sku'), dict):
        it['sku']['_sid'] = str(sid).replace(':', '_', 1)
    return it


def scene_fields(variants: list, live=None) -> dict:
    """ПОЛЯ 3D-СЦЕНЫ У ПРЕДМЕТОВ ТУРА — ТЕМ ЖЕ КОДОМ, ЧТО У /demo (T-20261112-96, `sku_scene`; у демо — `flat215_demo.annotate_*`):
    «подвесная» `hung` (по названию товара) и `strategy` зеркала/картины/ковра — всегда; разворот модели `yaw`, подкраска цветового
    варианта `tint` и семья цветов `fam` — из живых данных (`live(skus)`, у живой сборки — `scene_live` из `default_ctx`).
    Раньше тур их не ставил: вариант цвета — цветом представителя, модель с калибровкой — неразвёрнутой, подвесная тумба в «Фото» —
    на полу. Ключ товара `_sid` снимается всегда (в данные страницы не идёт). → счётчики."""
    import sku_scene as SS
    skus = [it['sku'] for v in variants for it in (v.get('items') or []) + (v.get('decor') or [])
            if isinstance(it, dict) and isinstance(it.get('sku'), dict)]
    items = [it for v in variants for it in v.get('items') or [] if isinstance(it, dict)]
    st = {'hung': SS.mark_hung(skus), 'strategy': SS.strategy(items)}
    if live is not None:
        st.update(live(skus))
    for sk in skus:
        sk.pop('_sid', None)
    return st


def scene_live(skus: list) -> dict:
    """Живая часть `scene_fields`: разворот (`orient.json` прода + ручные поправки), подкраска (замер сторожа или тоны плиток витрины
    `flat215_demo.OUT`, как у `put_swatches`), семья цветов (`room_bindings.mesh_rep`). Нет базы/сети — без них, но громко."""
    import sku_scene as SS
    st = {'yaw': 0, 'tint': 0, 'fam': 0}
    try:
        import flat215_demo as FD
        st['yaw'] = SS.yaw(skus)
        st['tint'] = SS.tint(skus, FD.OUT)
        st['fam'] = SS.family(skus, FD._mesh_rep())
    except Exception as e:  # noqa: BLE001 — без базы/сети тур собирается без подкраски, но громко
        print(f'WARN:trial_scene_fields: {repr(e)[:160]}', flush=True)
    return st


def carried_fams(variants: list, demo: dict | None, rep: dict | None = None) -> int:
    """СЕМЬЯ ЦВЕТОВ У ПЕРЕНЕСЁННЫХ ПРЕДМЕТОВ (T-20261112-53, владелец TG 936: кружки цвета в туре — как в /demo). Сборка ставит `fam`
    в `scene_fields` → `sku_scene.family` по артикулу товара `_sid`; у предмета, который перевыпуск перенёс из тура, собранного до
    T-96, нет ни `fam`, ни артикула — цвета со своей 3D-моделью выпадали из кружков. Артикул — из строки витрины того же товара
    (название + модель), семья — тем же `sku_scene.family` (`rep` — `room_bindings.mesh_rep`; без базы — без семьи, но громко).
    Трогаем только `sku` без `fam` и с найденным артикулом. → сколько отмечено."""
    import sku_scene as SS
    sid_of = {(r['name'], r.get('msid')): r['sid'] for rows in (demo or {}).values() if isinstance(rows, dict)
              for lst in rows.values() for r in lst or [] if isinstance(r, dict) and r.get('sid') and r.get('name')}
    skus = []
    for v in variants:
        for it in (v.get('items') or []) + (v.get('decor') or []):
            sk = it.get('sku') if isinstance(it, dict) else None
            sid = isinstance(sk, dict) and not sk.get('fam') and sid_of.get((sk.get('name'), sk.get('msid')))
            if sid:
                sk['_sid'] = str(sid).replace(':', '_', 1)
                skus.append(sk)
    if not skus:
        return 0
    try:
        if rep is None:
            import flat215_demo as FD
            rep = FD._mesh_rep()
        return SS.family(skus, rep)
    except Exception as e:  # noqa: BLE001 — без базы тур перевыпускается без семьи, но громко
        print(f'WARN:trial_carried_fams: {repr(e)[:160]}', flush=True)
        return 0
    finally:
        for sk in skus:
            sk.pop('_sid', None)


def _scene_variant(sv: dict, room_id: str, geo: dict, msid_of, goods=None) -> dict:
    style = sv.get('style') or PENDING_STYLE
    failed = bool(sv.get('failed'))
    state = 'failed' if failed else ('ready' if sv.get('post_ok') and not sv.get('hard') else 'partial')
    place = {p['role']: p for p in sv.get('placements_core') or []}
    out = {'id': f"set{sv['set_index']}", 'title': style.capitalize(), 'style': style, 'style_id': STYLE_IDS.get(style, ''),
           'room_id': room_id, 'items': [_item(r, place.get(r['role']), msid_of, goods) for r in sv.get('items') or []], 'decor': [],
           'dims_unknown': [], 'missing_item': [{'role': r} for r in sv.get('absent_roles') or []], 'fill': [], 'fill_pct': None,
           'cams': [], 'pending': False, 'furniture_state': state, 'room_size': {'w': geo['w'], 'd': geo['d']}}
    if sv.get('slots'):
        out[SLOTS_KEY] = sv['slots']          # места предметов — только для лент (`feeds_for`), в данные страницы не идут
    if state != 'ready':
        out['furniture_problem'] = {'codes': sorted({p.get('code') for p in sv.get('problems') or []} | set(sv.get('hard') or []))}
    return out


def feed_key(room_id: str, base: str, room_keys: bool = True) -> str:
    """Ключ ленты замен — как ищет страница (`index.html:roomKeysOf`): у гостиных голая роль, у других комнат — «<комната>:<роль>»
    (у каждой спальни своя лента: свои товары и своя полоса размера). Голая роль у спальни — лента не находилась, «Выбрать кровать (0)»."""
    return base if not room_keys or room_id == LIVING or room_id.startswith(LIVING + '-') else f'{room_id}:{base}'


def _feeds(variants: list, room_keys: bool = True) -> dict:
    """Ленты замен — только товары вариантов задания (других для этого плана не считалось), `диван` → строки как в живом `feeds`."""
    out: dict = {}
    seen: dict = {}
    for v in variants:
        for it in v['items']:
            sku, base = it.get('sku') or {}, feed_key(v.get('room_id') or '', _base_role(it['role']), room_keys)
            key = (base, sku.get('msid') or sku.get('name'), sku.get('w'), sku.get('d'), sku.get('sleep_w'))
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


# поля строки ленты витрины, которые страница читает у замены (штук в покупке, сторона угла, подвес, глубина каталога, поворот и тон
# модели) — числа и флаги, не данные магазина
# color_low — стили, где цвет товара «не очень» (в конец ленты, `demo-feeds.ts`), fam — семья цветов: у строк лент /demo они есть,
# тур их срезал (T-20261112-96)
FEED_EXTRA_KEYS = {'corner_left', 'pack', 'hung', 'd_catalog', 'yaw', 'swatch', 'tint', 'color_low', 'fam'}
SLOTS_KEY = '_slots'     # служебное поле варианта: места предметов сцены гостиной; `feeds_for` снимает его (в данные страницы не идёт)


PLACE_GROW = 1.1         # место предмета без места решателя: до 1,1 его размера (верх полосы владельца 22.10) в пределах свободного места
RUG_ROLES = ('ковёр', 'ковер')


def _box(it: dict) -> tuple:
    """Описанный прямоугольник предмета на плане комнаты (x0, y0, x1, y1) — как `index.html:box` (x, y — центр)."""
    a = math.radians(it.get('rot') or 0)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    w, d = it.get('w') or 0, it.get('d') or 0
    sw, sd = w * c + d * s, w * s + d * c
    x, y = it.get('x') or 0, it.get('y') or 0
    return (x - sw / 2, y - sd / 2, x + sw / 2, y + sd / 2)


def free_place(it: dict, items: list, geo: dict | None) -> tuple:
    """(ширина, глубина) МЕСТА предмета в его осях, когда места решателя нет (вариант перенесён перевыпуском, `_slots` не сохранились):
    свободный пролёт до соседей и стен — тем же правилом, что «встаёт ли» на странице (`index.html:freeSpan`), но не больше
    `PLACE_GROW` его размера и не меньше его самого. Раньше местом считался размер самого товара, и в ленту шли только товары не крупнее
    текущего (стул 42×42 — один стул на весь тур, T-40). Ковёр — подложка под мебелью: его место — его размер."""
    w, d = it.get('w') or 0, it.get('d') or 0
    if _base_role(it.get('role') or '') in RUG_ROLES or not geo or not (w and d):
        return (w, d)
    b = _box(it)
    others = [_box(o) for o in items if o is not it and not str(o.get('role') or '').startswith(RUG_ROLES)]

    def span(ax: int) -> float:
        lo, hi = 0.0, float(geo.get('w' if ax == 0 else 'd') or 0)
        e0, e1 = (b[0], b[2]) if ax == 0 else (b[1], b[3])
        for o in others:
            cross = not (o[3] <= b[1] or o[1] >= b[3]) if ax == 0 else not (o[2] <= b[0] or o[0] >= b[2])
            if not cross:
                continue
            o0, o1 = (o[0], o[2]) if ax == 0 else (o[1], o[3])
            if o1 <= e0:
                lo = max(lo, o1)
            elif o0 >= e1:
                hi = min(hi, o0)
        return hi - lo
    sx, sy = span(0), span(1)
    along, across = (sy, sx) if round((it.get('rot') or 0) / 90) % 2 == 1 else (sx, sy)
    return (max(w, min(along, w * PLACE_GROW)), max(d, min(across, d * PLACE_GROW)))


def _sofa_w(v: dict) -> float:
    return max([it.get('w') or 0 for it in v.get('items') or [] if _base_role(it.get('role') or '') == 'диван'] or [0])


WALL_TOUCH_CM = 5.0      # край предмета ближе к стене — «у стены»: при замене на меньший товар этот край остаётся у стены


def _keep_wall_edge(it: dict, b0: tuple, geo: dict | None) -> None:
    """После замены размера предмета (центр прежний): край, что стоял у стены коробки комнаты, — снова у стены (иначе диван/комод
    меньшего товара «отъезжает» от стены); у стены нет — центр прежний."""
    if not geo:
        return
    b1 = _box(it)
    for ax, lim in ((0, float(geo.get('w') or 0)), (1, float(geo.get('d') or 0))):
        lo0, hi0, half = b0[ax], b0[ax + 2], (b1[ax + 2] - b1[ax]) / 2
        key = 'x' if ax == 0 else 'y'
        if lo0 <= WALL_TOUCH_CM:
            it[key] = round(lo0 + half, 1)
        elif lim and hi0 >= lim - WALL_TOUCH_CM:
            it[key] = round(hi0 - half, 1)


def goods_from_feeds(variants: list, demo: dict | None, goods=None, geo: dict | None = None) -> dict:
    """ТОВАР У КАЖДОГО ПРЕДМЕТА (T-20261110-40, владелец TG 917): у туров, собранных до T-25 и перенесённых перевыпуском, предметы — без
    товара (серые квадраты в списке, первая карточка ленты без фото). Предмету без товара — товар витрины /demo:
    (1) та же модель того же размера (`demo_feeds.same_goods`) — фото, магазин, цена, название; модель и место не меняются;
    (2) модель есть, а в витрине её нет (снята из /demo, но лежит в банке пробы) — товар, с которого модель снята: ключ модели = ключ
    товара (`goods`, резолвер сборки `catalog_goods`);
    (3) заглушка без модели (ковёр, обеденный стол без `msid`) или товар снят с продажи — самый крупный товар витрины своего стиля, что
    влезает в место (`free_place`, `demo_feeds.slot_pick`; ковёр — не короче дивана варианта, `index.html:rugFitsSofa`): центр
    прежний, край у стены — у стены (`_keep_wall_edge`), размер — товара, ковёр — длинной стороной вдоль своей длинной; у мебели — его
    модель. Ничего не нашлось — предмет как был (в списке — снимок модели). `geo` — коробки комнат {room_id: {w, d}}.
    Меняет варианты на месте → счётчики {same, bank, slot, model_only, none}."""
    import demo_feeds as DF
    st = {'same': 0, 'bank': 0, 'slot': 0, 'model_only': 0, 'none': 0}
    if not demo and not goods:
        return st
    for v in variants:
        kind = DF.room_kind(v.get('room_id') or '')
        for it in v.get('items') or []:
            sku = it.get('sku')
            if not isinstance(sku, dict) or DF.has_goods(sku):
                continue
            base = _base_role(it.get('role') or '')
            r = DF.same_goods(demo or {}, kind, base, sku)
            if r is not None:
                sku.update({k: r[k] for k in DF.GOODS_FIELDS if r.get(k) not in (None, '')})
                sku.pop('_sid', None)                  # товар витрины без подкраски (фото = цвет модели): `scene_fields` не красит
                st['same'] += 1
                continue
            if sku.get('msid') and base not in DF.NOMESH:
                g = goods(sku['msid'], base) if goods else None
                if g and DF.has_goods(g):
                    sku.update({k: x for k, x in g.items() if x not in (None, '')})
                    sku.pop('_sid', None)              # товар, с которого снята модель, — без подкраски
                    st['bank'] += 1
                    continue
            if not demo:
                st['model_only' if sku.get('msid') else 'none'] += 1
                continue
            w, d, sofa = it.get('w') or 0, it.get('d') or 0, _sofa_w(v)
            place = free_place(it, v.get('items') or [], (geo or {}).get(v.get('room_id') or ''))
            r = DF.slot_pick(demo, kind, base, v.get('style') or '', place,
                             ok=lambda x: DF.has_goods(x) and not x.get('tint')
                             and (base not in RUG_ROLES or DF.side(base, x) >= sofa))
            if r is None:
                st['model_only' if sku.get('msid') else 'none'] += 1
                continue
            rw, rd = r.get('w') or 0, r.get('d') or 0
            if base in RUG_ROLES:                      # длинная сторона ковра — вдоль длинной стороны места
                rw, rd = (max(rw, rd), min(rw, rd)) if w >= d else (min(rw, rd), max(rw, rd))
            b0 = _box(it)
            it.update(w=rw, d=rd, **({'h': r['h']} if r.get('h') else {}))
            _keep_wall_edge(it, b0, (geo or {}).get(v.get('room_id') or ''))
            new = {'w': rw, 'd': rd, **({'h': r['h']} if r.get('h') else {}),
                   **{k: r[k] for k in DF.GOODS_FIELDS if r.get(k) not in (None, '')}}
            if base not in DF.NOMESH and r.get('msid'):
                new['msid'] = r['msid']
            sku.clear()
            sku.update(new)
            st['slot'] += 1
    return st


def feeds_for(variants: list, demo: dict | None = None, room_keys: bool = True, geo: dict | None = None,
              bands: dict | None = None) -> tuple[dict, dict]:
    """ЛЕНТЫ ЗАМЕН ТУРА = ЛЕНТЫ /demo ПОД СЛОТ (T-20261110-37): товары вариантов задания (`_feeds`, первыми) + товары лент витрины
    (`demo_feeds.room_feed`: модель есть, стиль совпадает, влезает в место предмета своего стиля в этой комнате). `demo` — ленты витрины
    (`demo_feeds.load`); нет — только товары вариантов, как раньше. → (ленты, `feeds_short`: {ключ ленты: {стиль: {n, demo}}} при n < 20).
    T-40: место без места решателя — `free_place` по коробке комнаты `geo` ({room_id: {w, d}}); не мельче `BAND_LO` текущего предмета
    стиля (ковёр — не короче дивана); `bands` (если передан) — полосы страницы по ключу ленты ({lo, hi, side} для
    `rules.slot_band_cm`): то же правило, что у ленты, — человек видит столько, сколько насчитал сборщик."""
    import demo_feeds as DF
    own = _feeds(variants, room_keys)
    slots: dict = {}                                   # ключ ленты → (вид комнаты, роль, {стиль: [(ш, г)]}, {стиль: нижняя граница})
    for v in variants:
        rid = v.get('room_id') or ''
        places = v.pop(SLOTS_KEY, None) or {}          # место предмета на расстановке (`trial_demo` → `slots`); нет — свободное место
        for it in v.get('items') or []:
            base = _base_role(it['role'])
            key = feed_key(rid, base, room_keys)
            k = slots.setdefault(key, (DF.room_kind(rid), base, {}, {}))
            sl = places.get(it['role']) or places.get(it.get('style_role') or '') or None
            w, d = (sl[0], sl[1]) if sl else free_place(it, v.get('items') or [], (geo or {}).get(rid))
            # место не меньше своего товара (подстановка могла поставить товар крупнее следа на свободной стороне)
            k[2].setdefault(v.get('style'), []).append((max(w or 0, it.get('w') or 0), max(d or 0, it.get('d') or 0)))
            low = _sofa_w(v) if base in RUG_ROLES else DF.side(base, it) * DF.BAND_LO
            s = v.get('style')
            k[3][s] = min(k[3].get(s, low), low)
    feeds, short = {}, {}
    keep = FEED_KEYS | FEED_EXTRA_KEYS
    for key, (kind, base, sl, lo) in slots.items():
        rows, count = DF.room_feed(demo or {}, kind, base, sl, own.get(key), lo=lo)
        if bands is not None and sl:
            bands[key] = {'lo': round(min(lo.values()) if lo else 0), 'side': 'long' if base in RUG_ROLES else 'w',
                          'hi': round(max(max(DF.side(base, {'w': a, 'd': b}) for a, b in x) for x in sl.values()) + DF.FIT_TOL_CM)}
        out = []
        for r in rows:
            row = {k: x for k, x in r.items() if k in keep}
            if base in DF.NOMESH:
                row.pop('msid', None)                  # плита с фото: модели нет (у витрины `msid` ковра = ключ товара)
            out.append(row)
        feeds[key] = out
        # ПРИЧИНА — ЧИСЛОМ: `demo` — сколько товаров этого стиля с моделью, фото и магазином в ленте /demo вообще; n < demo — отсёк
        # размер места, n ≥ demo — у самой витрины в этом стиле меньше 20
        low = {s: {'n': n, 'demo': sum(1 for r in DF.kind_rows(demo or {}, kind, base)
                                       if s in DF.styles_of(r) and DF.model_ok(base, r) and DF.has_goods(r))}
               for s, n in count.items() if s and n < DF.MIN_FEED}
        if low:
            short[key] = low
    return feeds, short


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


def size_check(result: dict, room: dict) -> str | None:
    """Почему комнату-цель нельзя обставлять сразу: `scale_unverified` (масштаб квартиры, при `SCALE_UNVERIFIED_AWAITS_CHECK`),
    флаг комнаты из `SIZE_CHECK_FLAGS` — или None. Размер, заданный агентом правкой комнаты (`USER_DIMS`), проверять не нужно."""
    if USER_DIMS in (room.get('flags') or []):
        return None
    if SCALE_UNVERIFIED_AWAITS_CHECK and (result.get('scale') or {}).get('status') == 'not_verified':
        return 'scale_unverified'
    return next((f for f in room.get('flags') or [] if f in SIZE_CHECK_FLAGS), None)


PHOTO_SCALES = ('verified', 'listing')


def photo_ok(result: dict, room: dict, kind: str, state: str, consent: bool) -> bool:
    """ДОВЕРИЕ К РАЗМЕРАМ КОМНАТЫ ДЛЯ ФОТО (план agent-trial-08 § «Правило фото», T-20261109-34): фото нейросети — только гостиной или
    спальне, которая обставлена (`ready`), с подтверждённым масштабом квартиры (`verified`/`listing`; `area` без сверки — нет), без флага
    размера и не обставленной «как есть» по согласию агента (мебель есть, фото нет). Одно правило — его читают страница (кнопка) и сервер
    (`/api/trial/<id>/photo`). Размер комнаты задал агент правкой (`USER_DIMS`) — ему и верим: фото можно при любом масштабе квартиры."""
    if kind not in (LIVING, BEDROOM) or state != 'ready':
        return False
    if USER_DIMS in (room.get('flags') or []):
        return True
    return (result.get('scale') or {}).get('status') in PHOTO_SCALES and not consent and size_check(result, room) is None


def _living_rooms(result: dict, cfg: dict) -> tuple[list, list]:
    """Комнаты типа «гостиная»: первая — та же, что выбирает `trial_room.pick_living` (её обставляет сцена), дальше по площади.
    Гостиной в плане нет (`no_living`) — пустой список и флаг `no_living`: тур всё равно собирается из остальных комнат (T-20261110-07)."""
    try:
        panel, main, flags = TR.pick_living(result, cfg)
    except TR.Refusal as e:
        if e.code == 'no_living':
            return [], ['no_living']
        raise BundleRefused(e.code, e.detail) from e
    from shapely.geometry import Polygon
    rest = [(p, r) for p in result['panels'] for r in p['rooms'] if TR.is_living(r, cfg) and r is not main]
    rest.sort(key=lambda pr: -Polygon(pr[1]['contour']).area)
    return [(panel, main)] + rest, flags


def _map_parts(parts: list, panels: list, ids: dict, livings: set, goods=None) -> dict:
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
                                                         'items': [_part_item(it, goods) for it in v.get('items') or []]})
    return out


def _part_item(it: dict, goods=None) -> dict:
    """Предмет из куска стадии → разрешённые поля, имя — нейтральное по роли на обоих языках (кровать — с шириной спального места).
    Поля товара из куска не берём никогда; товар — из каталога по `sku.sid` куска (`attach_goods`; кусок старой сборки без `sid` —
    нейтральный предмет, как раньше)."""
    sid = (it.get('sku') or {}).get('sid') if isinstance(it.get('sku'), dict) else None
    out = public_item(it, SKU_KEYS)
    sku = dict(out.get('sku') or {})
    ru, en = neutral_names(out.get('role') or '')
    sw = sku.get('sleep_w')
    if isinstance(sw, (int, float)) and sw > 0:
        ru, en = f'{ru} {round(sw)} см', f'{en} {round(sw)} cm'
    sku.update(name=ru, name_en=en)
    out['sku'] = attach_goods(sku, sid, out.get('role') or '', goods)
    return _keep_sid(out, sid)


def build(job_id: str, result: dict, scene: dict | None = None, ctx: dict | None = None, parts: list | None = None,
          release=(), stats: dict | None = None) -> dict:
    """floorplanResult (+ сцена гостиной, + куски стадий) → `demo-data.json`. Нечего показать или утечка магазина — `BundleRefused`.
    Гостиная/спальня с `size_check` — `awaiting_check` (мебель не показываем), кроме id из `release` (агент проверил размер) и главной
    гостиной с готовой сценой (её обставили по запросу)."""
    _check_input(job_id, result, scene)
    release = set(release or ())
    parts = list(parts or [])
    ctx = ctx or default_ctx()
    quiz = ctx.get('quiz') or quiz_rule()
    if not (isinstance(quiz, dict) and isinstance(quiz.get('questions'), list) and quiz['questions']):
        raise BundleRefused('quiz_missing', 'нет `questions` в правиле опроса: ссылка покупателя `?quiz=1` не откроет опрос')
    cfg = TR.rules()
    panels = result['panels']
    panel_of = {id(r): i for i, p in enumerate(panels) for r in p['rooms']}
    livings, flags = _living_rooms(result, cfg)
    main = livings[0][1] if livings else None
    if scene is not None and scene.get('room') and (main is None or scene['room'].get('id') != main['id'] or
                                                     scene['room'].get('panel') != panels[panel_of[id(main)]]['id']):
        raise BundleRefused('scene_mismatch', f"сцена про комнату {scene['room'].get('id')}, а гостиная плана — {(main or {}).get('id')}")
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
    # ни одна гостиная не построилась (или её нет) — тур всё равно собирается: стены/план и остальные комнаты с честным исходом
    # (T-20261110-07: иначе задание закрывалось без версии данных и тур не открывался никогда). Отказ — только если показать нечего.
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
                # уличные — свой счёт `outdoor-N` (T-20261111-20): новый балкон не сдвигает номера `other-N` кладовых и гардеробных
                key = OUTDOOR if OUTDOOR in (r.get('flags') or []) else r['kind']
                counters[key] = counters.get(key, 0) + 1
                ids[id(r)] = f"{key}-{counters[key]}"
    goods = _Goods(ctx.get('goods'))                 # товар как в /demo — из каталога по `sid` (контекст теста без него — без товаров)
    pmap = _map_parts(parts, panels, ids, {id(r) for _, r in livings}, goods)
    storey_map, storey_flags = storeys(panels)
    rooms_geo, apartment_rooms, variants = {}, [], []
    outcomes = {ids[id(x['room'])]: _outcome('refused', x['code']) for x in refused}

    def consented(r, rid):
        """Агент нажал «Обустроить» (Р1): комната обставляется «как есть», размеры — примерные (не `verified`!)."""
        return rid in release or APPROX_CONSENT in (r.get('flags') or [])

    def awaits(r, rid):
        return None if consented(r, rid) else size_check(result, r)

    # гостиная, чьё ядро не построилось при НЕПОДТВЕРЖДЁННОМ размере, — не «не разобрана»: ядро считали по угаданному масштабу
    # (T-20261110-29: спальни 3,2–3,5 м² вместо ~10 → `no_core`); исход — тот же, что у построенной: ждёт проверки, «Обустроить»
    for x in refused:
        rid = ids[id(x['room'])]
        if awaits(x['room'], rid):
            outcomes[rid] = _outcome('awaiting_check', awaits(x['room'], rid))

    def put_geo(panel, room, rid, geo, kind):
        full = {'w': geo['w'], 'd': geo['d'], **_geo_titles(room, geo, kind), 'openings': geo['openings'], 'radiators': [],
                'approx': _approx(room, geo)}
        # за порталом-стыком — остаток комнаты с его дверями, а не пустота (T-20261111-08, `annexes_of`)
        # и балкон за наружной стеной — плитой с ограждением (T-20261111-20/2, `outdoor_of`)
        # и за порталом наружу — кусок прохода, стык с пристройкой — без перемычки (T-20261112-41, `shell_of`)
        full['openings'], ax = shell_of(panel, room, full, cfg)
        if ax:
            full['annexes'] = ax
        # ВИД КОМНАТЫ — В КОРОБКУ, КАК У /demo (T-20261110-16/3): правила ракурсов (`index.html:camZ`, ими же `demo-cams.mjs` при
        # сборке) берут зону по `kind` коробки, без него — гостиную: у спальни искали диван, и точка 1 смотрела в угол без мебели
        # (yb3_DQp3 «Спальня 2»: покрыто 0 из 5). Гостиной поле не пишем — у /demo его нет, зона по умолчанию та же
        if kind != LIVING:
            full['kind'] = kind
        if result.get('ceilingCm'):                   # T-20261110-38: высота потолков из объявления — высота стен тура
            full['height_cm'] = _num(float(result['ceilingCm']))
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
            ready = [_scene_variant(sv, rid, geo, ctx['msid_of'], goods) for sv in scene['variants']]
            shown = any(v['items'] and v['furniture_state'] != 'failed' for v in ready)
            if shown:
                variants += sorted(ready, key=lambda v: v['furniture_state'] == 'failed')
                outcomes[rid] = _outcome('ready')
            else:                                            # ни один стиль не встал — пустая комната с текстом, а не пустые «стили»
                variants.append(_empty_variant(rid, geo, 'failed', {'code': 'furniture_failed'}))
                outcomes[rid] = _outcome('refused', 'furniture_failed')
        elif awaits(room, rid):
            variants.append(_empty_variant(rid, geo, 'awaiting_check', {'code': awaits(room, rid)}))
            outcomes[rid] = _outcome('awaiting_check', awaits(room, rid))
        elif room is main and scene is not None:
            first = (scene.get('problems') or [{}])[0].get('code')
            space = TD.outcome_of(scene).get('code')        # по сцене заново: сцена старой сборки хранит прежний код исхода
            why = scene.get('refusal') or ({'code': space} if space in TD.SPACE_CODES else
                                           {'code': 'no_products' if scene['status'] == 'no_products' else (first or scene['status'])})
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
            if awaits(r, rid):                              # кусок стадии спален (если был) не показываем: размер ждёт проверки
                if geo:                                     # ядро не построилось по угаданному масштабу — тоже ждёт (T-29), без коробки
                    variants.append(_empty_variant(rid, geo, 'awaiting_check', {'code': awaits(r, rid)}))
                outcomes[rid] = _outcome('awaiting_check', awaits(r, rid))
                continue
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
    order = [r for _, r in livings] + [r for r in room_order(panels, storey_map) if id(r) not in living_ids]
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
        if kind in (LIVING, BEDROOM) and consented(r, rid) and size_check(result, r):
            entry['approx_consent'] = True                  # страница: «размеры примерные» — проверка снята агентом, не подтверждена
        entry['photo_ok'] = photo_ok(result, r, kind, entry['furniture_state'], consented(r, rid))
        if r.get('edited') or r.get('user_name'):
            entry['edited'] = True                          # страница: «✓ скорректировано» у подписи на плане
        if OUTDOOR in (r.get('flags') or []):
            entry['outdoor'] = True                         # балкон/лоджия/терраса (T-20261111-20): страница рисует уличным, не обставляется
        apartment_rooms.append(entry)
    if not variants:                                 # ни одной комнаты с коробкой — странице нечего открыть (контракт: ≥1 вариант)
        if refused:
            raise BundleRefused(refused[0]['code'], refused[0]['detail'])
        raise BundleRefused('no_living', TR.REFUSALS['no_living'] + '; ни одна другая комната не построилась')
    vids = [v['id'] for v in variants]
    if len(vids) != len(set(vids)):
        raise BundleRefused('parts_mismatch', 'id вариантов повторяются')
    rules = dict(ctx['rules'])
    if ctx.get('slot_band') and LIVING in rooms_geo:
        rules['slot_band_cm'] = ctx['slot_band'](rooms_geo[LIVING])
    demo = ctx['demo_feeds']() if ctx.get('demo_feeds') else None
    got = goods_from_feeds(variants, demo, goods, rooms_geo)   # предмет без товара — товар витрины (T-40); до имён: у товара — его название
    name_items(variants)                             # до лент: лента и строка списка узнают товар по одному имени
    # ленты — как у /demo под слот этой комнаты (T-37); меньше 20 на стиль позиции — `feeds_short` в журнал сборки (`stats`)
    bands: dict = {}
    feeds, short = feeds_for(variants, demo, geo=rooms_geo, bands=bands)
    rules['slot_band_cm'] = {**(rules.get('slot_band_cm') or {}), **bands}   # полоса «по размеру» — от места, как у ленты (T-40)
    # цвет предмета на плане — цвет товара по фото, не условная палитра (T-20261112-29): у предметов вариантов и у товаров лент (замена)
    put_swatches(variants + [{'items': [{'sku': f} for f in lst if isinstance(f, dict)]} for lst in feeds.values()])
    # подкраска, разворот, «подвесная», плоскость — тем же кодом, что /demo (T-20261112-96); строки лент приходят из /demo уже с ними
    scene_st = scene_fields(variants, ctx.get('scene_live'))
    if stats is not None:
        stats.update(feeds={k: len(v) for k, v in feeds.items()}, feeds_short=short, goods_from_feeds=got, scene_fields=scene_st)
    note =SCALE_NOTE.get(result['scale']['status'])
    trial = {'job_id': job_id, 'scale': result['scale']['status'],
             **({'scale_note': {'ru': note[0], 'en': note[1]}} if note else {}), 'furniture': SCENE_FURNITURE[scene['status']] if scene else 'pending',
             'complete': all(r['furniture_state'] != 'pending' for r in apartment_rooms),
             'flags': sorted(set(result.get('flags') or []) | set(flags) | set(storey_flags) | set((scene or {}).get('flags') or [])
                             | ({'goods_unavailable'} if goods.down else set())),
             **goods_meta(variants, ctx['money_en'] if 'money_en' in ctx else uk_money()),
             **({'dev_flat': ctx['dev_flat']} if ctx.get('dev_flat') else {}),
             'refused_rooms': [{'room_id': ids[id(x['room'])], 'code': x['code'], 'detail': x['detail']} for x in refused],
             'panels': [{'id': p['id'], 'title': p['title'],
                         **({'storey': storey_map[i]} if i in storey_map else {}),
                         # T-20261111-11: панель-часть дома (гараж) — своя подпись над планом вместо «Этаж N»
                         **(dict(zip(('titleRu', 'titleEn'), panel_part(p.get('title')))) if panel_part(p.get('title')) else {}),
                         # 2D-план — как прочитан (стены и проёмы панели не двигаются); правленая комната — исходные охват и контур
                         # (`plan`) и размер агента `edited` {w, d} (окошко правки показывает его)
                         'rooms': [{'id': ids[id(r)], 'src_id': r['id'], 'name': r.get('name'), 'kind': r['kind'], 'areaM2': r.get('areaM2'),
                                    'bbox': (r.get('plan') or {}).get('bbox') or r.get('bbox'),
                                    'contour': (r.get('plan') or {}).get('contour') or r.get('contour'), 'flags': r.get('flags') or [],
                                    **({'edited': r['edited']} if r.get('edited') else {})} for r in p['rooms']],
                         'openings': p.get('openings') or [], 'walls': p.get('walls') or []} for i, p in enumerate(panels)]}
    room = rooms_geo.get(LIVING) or next(iter(rooms_geo.values()))
    out = {'room': room, 'rooms_geo': rooms_geo, 'apartment_id': '', 'plan': {}, 'apartment_rooms': apartment_rooms,
           'rooms_enabled': sorted(with_variant), 'variants': variants, 'sets': [], 'sofa_feed': feeds.get('диван', []), 'feeds': feeds,
           'rules': rules, 'incomplete_styles': [], 'quiz': quiz, 'trial': trial}
    assert_public(out, shop_tokens(scene), goods=True)   # поймали — отказ, а не публикация
    return out


def write_atomic(path: str, data: dict) -> None:
    """Подменой: читатель (и сбой на полпути) не видит половину файла."""
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


# РАКУРСЫ — В ДАННЫЕ ТУРА ПРИ СБОРКЕ (T-20261110-32, владелец 10.11 TG 806: тур «загрузился еле-еле»): как у /demo, страница берёт
# готовую пару варианта (`index.html:defaultCams`), а не перебирает точки в главном потоке при открытии (замер 10.11: 16 с у пустой
# спальни, 3,7 с у обставленной гостиной). Срок — меньше срока стадии сборки у конвейера и перевыпуска (`worker.Cfg.bundle_timeout_s` 180)
# ПАРАЛЛЕЛЬНО И К СРОКУ (T-20261111-23): тур aOv8 — 17 вариантов, один процесс 140 с при сроке 120 → ни одной пары. Теперь куски
# (`cams_par`) считают CAMS_JOBS процессов под общей очередью машины (`heavy_slot`, ядра = процессы); срок растёт с числом кругов
# (кусков на процесс), но не выходит за срок стадии (TRIAL_STAGE_TIMEOUT_S от конвейера и перевыпуска минус уже прошедшее и хвост):
# к сроку готовые пары идут в данные, остальные досчитает страница. Замер aOv8 — в отчёте T-23.
_T0 = time.monotonic()
CAMS_JOBS = 4               # процессов node (TRIAL_CAMS_JOBS; внутри чужого слота — не больше его HEAVY_SLOT_CORES)
CAMS_BASE_S = 20.0          # запуск и разбор страницы у каждого процесса
CAMS_ROUND_S = 30.0         # круг = по куску на процесс: вариант 8–16 с (aOv8, спальня без мебели дольше), под нагрузкой — больше
CAMS_MAX_S = 150.0          # без срока стадии (ручной запуск) — не дольше
CAMS_TAIL_S = 15.0          # после ракурсов: проверка публичности, итоговые строки, выход
CAMS_SLOT_GB = 1.0          # свободной памяти: замер aOv8 — пик дерева 0,36 ГБ на 4 процесса
CAMS_SLOT_WAIT_S = 30.0     # очередь машины дольше — считаем одним процессом без слота (как до T-23)


def cams_jobs() -> int:
    try:
        n = int(os.environ.get('TRIAL_CAMS_JOBS') or CAMS_JOBS)
    except ValueError:
        n = CAMS_JOBS
    held = os.environ.get('HEAVY_SLOT_CORES')    # уже внутри слота (ручной запуск под heavy-slot.sh) — его ядра
    if held and held.isdigit():
        n = min(n, int(held))
    return max(1, n)


def cams_budget(units: int, jobs: int, stage_s: float | None = None, elapsed: float = 0.0) -> float:
    """Срок подбора ракурсов, с: база + круги × CAMS_ROUND_S (≤ CAMS_MAX_S), но не дальше срока стадии минус прошедшее и хвост."""
    b = min(CAMS_MAX_S, CAMS_BASE_S + CAMS_ROUND_S * -(-max(units, 1) // max(jobs, 1)))
    if stage_s:
        b = min(b, stage_s - elapsed - CAMS_TAIL_S)
    return max(b, 0.0)


def _stage_s() -> float | None:
    try:
        return float(os.environ['TRIAL_STAGE_TIMEOUT_S'])
    except (KeyError, ValueError):
        return None


def _cams_run(path: str, skip: frozenset = frozenset()) -> str:
    """Куски → слот машины (ядра = процессы) → параллельный подбор к сроку. Очередь не дала слот за CAMS_SLOT_WAIT_S или модуля
    очереди нет — один процесс без слота (как до T-23). `skip` — id вариантов, чьи пары перенесены из прежней версии (`reuse_cams`):
    кусок, целиком из них, не считается."""
    import cams_par as CP
    root = os.path.abspath(os.path.join(HERE, '..', '..'))
    try:
        units = CP.units_of(root, path)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        return f'WARN:trial_cams: куски ракурсов не получены — ракурсы считает страница: {type(e).__name__}: {str(e)[:160]}'
    units = [u for u in units if not set(u) <= skip]
    if not units:
        return f'ракурсы окна в данных: все {len(skip)} перенесены из прежней версии (подбор не нужен)'
    jobs = min(cams_jobs(), len(units) or 1)
    budget = cams_budget(len(units), jobs, _stage_s(), time.monotonic() - _T0)
    if budget < CAMS_BASE_S:
        return f'WARN:trial_cams: на ракурсы не осталось срока стадии ({budget:.0f} с) — ракурсы считает страница'
    deadline = time.monotonic() + budget
    ops = os.path.abspath(os.path.join(HERE, '..', 'ops'))
    if ops not in sys.path:
        sys.path.insert(0, ops)
    try:
        import heavy_slot as HS
        with HS.heavy_slot('trial_cams', min_gb=CAMS_SLOT_GB, timeout=min(CAMS_SLOT_WAIT_S, budget / 3), cores=jobs,
                           cmd=f'trial_cams {os.path.basename(path)} ×{jobs}'):
            return CP.cams(root, path, jobs, deadline - time.monotonic(), units=units)
    except ImportError:
        pass
    except Exception as e:                       # SlotTimeout и сбой очереди — не повод оставлять тур без ракурсов
        if type(e).__name__ != 'SlotTimeout':
            print(f'WARN:trial_cams: очередь машины: {type(e).__name__}: {str(e)[:120]}', flush=True)
    line = CP.cams(root, path, 1, deadline - time.monotonic(), units=units)
    return line + ' (без слота машины, одним процессом)'


# ПЕРЕНОС РАКУРСОВ ИЗ ПРЕЖНЕЙ ВЕРСИИ (T-20261112-92, автоперевыпуск туров после выкладки витрины): подбор пары — 82 из 83 с сборки
# тура (сухой прогон 12.11), 54 тура — ~75 мин на каждую выкладку. Пара зависит только от правил подбора (блок CAMFIT страницы),
# коробки комнаты и мебели варианта — правка движка (высота тумбы, свет, лента «Заменить») её не меняет. Поэтому у варианта
# хранится ключ этих входов (`v.cams_key`); совпал с прежней версией и пара там есть — пара переносится, подбор не идёт.
CAMS_FIELDS = ('cams', 'cam_level', 'cam_cover')


def camfit_sig(root: str | None = None) -> str:
    """Хеш правил подбора ракурсов — блок CAMFIT страницы, тот же срез, что исполняет `tools/flat3d/demo-cams.mjs`. Блока нет — ''."""
    root = root or os.path.abspath(os.path.join(HERE, '..', '..'))
    try:
        with open(os.path.join(root, 'tools', 'scout', 'flat215-demo', 'index.html'), encoding='utf-8') as f:
            html = f.read()
    except OSError:
        return ''
    a, b = html.find('// CAMFIT START'), html.find('// CAMFIT END')
    return hashlib.sha256(html[a:b].encode('utf-8')).hexdigest()[:16] if 0 <= a < b else ''


def _cams_geo(D: dict, v: dict):
    """Коробка комнаты варианта — правило `demo-cams.mjs:geoOf` (= `index.html:roomGeoOf`)."""
    rid = str(v.get('room_id') or 'living')
    rg = D.get('rooms_geo')
    if rg and rid in rg:
        return rg[rid]
    return D.get('room') if rid == 'living' or not rg else None


def cams_key(D: dict, v: dict, fit: str) -> str:
    """Ключ входов подбора пары варианта: правила (CAMFIT), «одна расстановка», коробка комнаты, сам вариант без ракурсов."""
    body = {k: x for k, x in v.items() if k not in CAMS_FIELDS and k != 'cams_key'}
    raw = json.dumps([fit, bool(D.get('one_layout')), _cams_geo(D, v), body], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def reuse_cams(path: str, old: dict | None, fit: str | None = None) -> set:
    """Ключи пар — всем вариантам файла; пары прежней версии с тем же ключом — переносятся. Общая пара комнаты (`one_layout`, без
    `cams_own`) — только если совпали ВСЕ варианты комнаты и их состав тот же. Правил подбора нет (`fit` пуст) — ничего не переносим.
    → id вариантов с перенесённой парой. Файл переписывается подменой."""
    fit = camfit_sig() if fit is None else fit
    with open(path, encoding='utf-8') as f:
        D = json.load(f)
    vs = D.get('variants') or []
    for v in vs:
        v['cams_key'] = cams_key(D, v, fit) if fit else ''
    got: set = set()
    if fit and old:
        prev = {str(v.get('id')): v for v in old.get('variants') or []}
        rooms: dict = {}
        for v in vs:
            rooms.setdefault(str(v.get('room_id') or 'living'), []).append(v)
        for rid, list_ in rooms.items():
            ok = [v for v in list_ if (p := prev.get(str(v.get('id')))) and p.get('cams_key') == v['cams_key']
                  and isinstance(p.get('cams'), list) and len(p['cams']) == 2]
            geo = _cams_geo(D, list_[0]) or {}
            if D.get('one_layout') and len(list_) > 1 and not geo.get('cams_own'):
                same = {str(p.get('id')) for p in prev.values() if str(p.get('room_id') or 'living') == rid} == {str(v.get('id')) for v in list_}
                ok = ok if len(ok) == len(list_) and same else []
            for v in ok:
                p = prev[str(v.get('id'))]
                v.update({k: p[k] for k in CAMS_FIELDS if k in p})
                got.add(str(v.get('id')))
        if got and old.get('cams_shared'):
            D['cams_shared'] = True
    tmp = f'{path}.reuse-{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)
    return got


def add_cams(path: str, tokens: list, runner=None, old: dict | None = None) -> str:
    """Пара ракурсов каждого варианта — в файл версии тем же подбором (`tools/flat3d/demo-cams.mjs` → `v.cams`), что у /demo,
    параллельно и к сроку (`_cams_run`). НЕ ВАЛИТ СБОРКУ: ни одной пары — версия без ракурсов (страница посчитает сама). Ракурсы
    дописаны (все или часть) — версия ещё раз проходит `assert_public`; не прошла — возвращаются прежние байты. → строка лога.
    `old` — прежняя версия (перевыпуск): пары с тем же ключом входов переносятся (`reuse_cams`), считаются только остальные."""
    note = ''
    with open(path, 'rb') as f:
        orig = f.read()
    try:
        reused = reuse_cams(path, old)
    except (OSError, ValueError) as e:            # перенос — ускорение, не условие: не вышел — считаем всё, как раньше
        reused, note = set(), f' · WARN перенос ракурсов: {type(e).__name__}: {str(e)[:120]}'
    if reused:
        note = f' · перенесено из прежней версии {len(reused)}' + note
    with open(path, 'rb') as f:
        mid = f.read()
    # откат — к перенесённым парам, если они есть (они из прежней проверенной версии), иначе к исходным байтам версии
    before = mid if reused else orig

    def restore():
        tmp = f'{path}.{os.getpid()}.tmp'
        with open(tmp, 'wb') as f:
            f.write(before)
        os.replace(tmp, path)
    line = (runner or (lambda p: _cams_run(p, frozenset(reused))))(path)
    if line.startswith('WARN:') and mid == open(path, 'rb').read():
        restore()
        return line + note
    try:
        with open(path, encoding='utf-8') as f:
            assert_public(json.load(f), tokens, goods=True)
    except (OSError, ValueError, BundleRefused) as e:
        restore()
        return f'WARN:trial_cams: ракурсы сняты, версия — без них: {type(e).__name__}: {getattr(e, "detail", str(e))[:160]}'
    return line + note


# СТОРОЖ ЛЁГКИХ КОПИЙ (T-20261111-23): мебель тура подбирается из банков пробы, а копии (`tools/assets/runtime_mesh.py`) ночь делает
# только моделям вариантов /demo (`demo_rt.sh`). Тур aOv8: 4 модели гостиной без копии — браузер тянул исходники по 3,4–3,9 МБ
# (`lib/configurator/mesh-url.ts:meshUrl`). Сборка тура пишет такие модели в очередь ночи, ночь собирает и выкладывает их копии
# вместе с копиями витрины, а тур берёт новые записи таблицы витрины (`lib/trial/tour.ts:withNewCopies`).
RT_TABLE = os.path.expanduser('~/scout-scenes/flat3d-rt/runtime-meshes.json')
RT_QUEUE = os.path.expanduser('~/scout-scenes/rt-queue/trial.txt')


def rt_watch(path: str, table: str | None = None, queue: str | None = None) -> str:
    """Модели вариантов тура без лёгкой копии (обеих: 1024 и `-lite`) → в очередь ночи (без повторов) и строка лога сборки.
    Не валит сборку: сбой чтения — строка WARN."""
    table = table or os.environ.get('RT_MANIFEST') or RT_TABLE
    queue = queue or os.environ.get('RT_QUEUE') or RT_QUEUE
    try:
        assets = os.path.abspath(os.path.join(HERE, '..', 'assets'))
        if assets not in sys.path:
            sys.path.insert(0, assets)
        from runtime_mesh import demo_ids
        var, _ = demo_ids(path)
        with open(table, encoding='utf-8') as f:
            tab = json.load(f).get('meshes') or {}
    except Exception as e:  # noqa: BLE001 — сторож не валит сборку, но молчать нельзя
        return f'WARN:trial_rt: сторож лёгких копий не сработал: {type(e).__name__}: {str(e)[:160]}'
    miss = [m for m in var if not ((tab.get(m) or {}).get('size') and (tab.get(m) or {}).get('size-lite'))]
    if not miss:
        return f'лёгкие копии моделей тура: {len(var)} из {len(var)}'
    try:
        os.makedirs(os.path.dirname(queue), exist_ok=True)
        have = set(open(queue, encoding='utf-8').read().split()) if os.path.exists(queue) else set()
        new = [m for m in miss if m not in have]
        if new:
            with open(queue, 'a', encoding='utf-8') as f:
                f.write(''.join(f'{m}\n' for m in new))
        where = f'в очередь ночи {len(new)} новых ({queue})'
    except OSError as e:
        where = f'очередь не записана: {type(e).__name__}'
    return (f'WARN:trial_rt: без лёгкой копии {len(miss)} из {len(var)} моделей тура (браузер берёт исходник 3–10 МБ): '
            f'{" ".join(miss[:8])} — {where}')


def feeds_line(stats: dict) -> str:
    """Строка журнала сборки: товаров в лентах по позициям и `feeds_short` (позиция → стиль → n, где меньше 20)."""
    return 'feeds ' + json.dumps(stats.get('feeds') or {}, ensure_ascii=False) + ' feeds_short ' + \
        json.dumps(stats.get('feeds_short') or {}, ensure_ascii=False)


def _arg(args: list, name: str) -> str | None:
    if name not in args:
        return None
    i = args.index(name)
    val = args[i + 1]
    del args[i:i + 2]
    return val


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ['--cache-images']:          # ночной шаг `trial_images` (и разовая докачка): плитки товаров банков пробы
        cache_bank_images(dry='--dry' in args)
        return 0
    scene_path, parts_path, out = _arg(args, '--scene'), _arg(args, '--parts'), _arg(args, '--out')
    release = [x for x in (_arg(args, '--release') or '').split(',') if x]
    cams = '--no-cams' not in args                 # версия не для страницы (проверка / промежуточная пересборки) — без ракурсов
    if not cams:
        args.remove('--no-cams')
    if len(args) != 2:
        print(__doc__)
        return 0
    job_id, result_path = args
    result = json.load(open(result_path, encoding='utf-8'))
    scene = json.load(open(scene_path, encoding='utf-8')) if scene_path else None
    parts = json.load(open(parts_path, encoding='utf-8')) if parts_path else []
    stats: dict = {}
    try:
        data = build(job_id, result, scene, parts=parts if isinstance(parts, list) else [parts], release=release, stats=stats)
    except BundleRefused as e:
        print(json.dumps({'refusal': e.code, 'detail': e.detail}, ensure_ascii=False))
        return 2
    if out:
        import build_stamp as BS                    # метка правил сборщика — проверка «демо = туры» (T-20261112-92)
        data['build'] = BS.stamp()
        write_atomic(out, data)
        if cams:
            print(add_cams(out, shop_tokens(scene)), flush=True)   # до итоговой строки: конвейер читает последнюю
            print(rt_watch(out), flush=True)                       # версия для страницы — её модели без копии в очередь ночи
        print(feeds_line(stats), flush=True)
        print(json.dumps({'ok': True, 'rooms': list(data['rooms_geo']), 'variants': len(data['variants'])}, ensure_ascii=False))
    else:
        json.dump(data, sys.stdout, ensure_ascii=False, separators=(',', ':'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
