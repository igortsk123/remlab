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
# Оси ПО МАГАЗИНУ И РОЛИ (план catalog-load-hardening П3.1, ИСПРАВЛЕНО 03.09 вечером). У tvoydom
# предмет описан «Ширина / Длина / Высота» без «Глубины». Сверка с названиями «Ш×Г×В» на 1 100 карточках:
# у 85–95 % ролей «ДЛИНА» = ШИРИНА ФАСАДА (1-е число), а «ШИРИНА» = ГЛУБИНА (2-е число): стул 178:34,
# диван 49:5, комод 29:1, статуэтка 72:2, камин 5:0. Первая версия правила (по ОДНОМУ стулу 53х44х87)
# была перевёрнута — урок: конвенцию магазина мерить на выборке, не на примере. Глобальный DIM_KEYS клал
# «Длина» в len_cm, и глубины не было у 100 % мебели tvoydom. Один хелпер dim_keys_for() обслуживает и
# resolve(), и learn(). Название с тройкой «Ш×Г×В» сильнее любых параметров (см. resolve).
LIGHT_ROLES = frozenset({'люстра', 'бра', 'лампа', 'торшер', 'светильник', 'подвес', 'спот'})
FURNITURE_ROLES = frozenset({'диван', 'кресло', 'стул', 'стол', 'стол обеденный', 'столик', 'тумба', 'тв-тумба',
                             'комод', 'стеллаж', 'шкаф', 'стенка', 'пуф', 'банкетка', 'витрина', 'полка',
                             'камин', 'кашпо', 'ваза', 'торшер', 'растение', 'лампа', 'статуэтка'})
# У МАГАЗИНА МОЖЕТ БЫТЬ НЕСКОЛЬКО КОНВЕНЦИЙ — ПО ГРУППАМ РОЛЕЙ (11.10). Значение стало СПИСКОМ
# пар «роли → переопределения»: берётся первая группа, содержащая роль. Раньше запись была одна,
# и свет магазина 99272 падал на глобальную таблицу, где «Длина» уходит в неиспользуемую ось `len`
# — из-за этого у 1 223 люстр и 668 бра глубина оставалась пустой при ЗАПОЛНЕННОМ поле в фиде.
SHOP_DIM_KEYS = {
    99272: [
        (FURNITURE_ROLES, {'w': ['Длина', 'Ширина, см', 'Ширина, мм'],
                           'd': ['Глубина', 'Глубина, см', 'Глубина, мм', 'Ширина'],
                           'len': ['Длина, см', 'Длина, мм']}),
        # СВЕТ: «Ширина» — одна горизонталь, «Длина» — вторая. Замер 11.10 по 2 280 люстрам с
        # обоими полями: у 1 571 (69 %) они различаются менее чем на 10 %, то есть это две
        # горизонтали круглого плафона и выбор оси непринципиален; у 519 длина заметно больше
        # (вытянутые люстры-линии), у 126 наоборот. Ни одного случая, где значение неправдоподобно
        # как горизонталь, нет — поэтому footprint верен в обоих вариантах, а глубина наконец
        # перестаёт быть пустой. Высота у света — вылет/длина подвеса, она и так из «Высота».
        (LIGHT_ROLES, {'d': ['Глубина', 'Глубина, см', 'Глубина, мм',
                             'Длина', 'Длина, см', 'Длина, мм']}),
    ],
    # ОРМАТЕК (подключён 11.10). Конвенция ОБРАТНА магазину 99272: «Ширина» — фасад, «Длина» —
    # глубина. Замер по выборке (правило шапки — не по примеру): комоды 27/27 совпали с первой
    # осью названия, кресла 42/42, зеркала 14/14, диваны 90/92; медианы внутри магазина это
    # подтверждают — комод Длина 53 / Ширина 92, шкаф 61/177, зеркало 6/100 (толщина!).
    # Без этой записи `d` оставалась пустой у 92 диванов, 42 кресел, 27 комодов и 27 пуфов: меш
    # им сделать можно, а честно расставить нельзя.
    # ДЛЯ СВЕТА конвенция НЕ вводится: шесть торшеров — не выборка, и среди них есть и
    # «Длина = глубина», и «Длина = высота» (Largo 59 против Paola 173).
    93965: [
        (FURNITURE_ROLES, {'d': ['Глубина', 'Глубина, см', 'Глубина, мм',
                                 'Длина', 'Длина, см', 'Длина, мм']}),
    ],
}
# Составные поля «две-три цифры в одной строке» → оси, по роли (П3.2). Порядок Д×Ш×В у «Габариты» tvoydom
# сверен на 5 люстрах/бра: первое число — размах (диаметр/длина), второе — высота; для трёх — Д, Ш, В.
COMPOSITE_KEYS = {
    'шторы': [('Размер штор', ('w', 'h'))],
    '*': [('Габариты (Д*Ш*В)', ('len', 'w', 'h')), ('Габариты (Д×Ш×В)', ('len', 'w', 'h')),
          ('Габариты (ДхШхВ)', ('len', 'w', 'h')), ('Размер, см', ('w', 'd', 'h'))],
}
def dim_keys_for(mid: int | None, role: str | None) -> dict[str, list[str]]:
    """Имена параметров по осям для (магазин, роль): глобальные DIM_KEYS + переопределения магазина."""
    groups = SHOP_DIM_KEYS.get(mid or 0) or []
    rule = next((g for g in groups if role in g[0]), None)
    if not rule:
        return DIM_KEYS
    keys = {k: list(v) for k, v in DIM_KEYS.items()}
    for dim, names in rule[1].items():
        keys[dim] = list(names)
    # ключ, отданный другой оси, из прежней оси убираем — иначе значение ляжет в обе
    moved = {n for names in rule[1].values() for n in names}
    for dim in keys:
        if dim not in rule[1]:
            keys[dim] = [n for n in keys[dim] if n not in moved]
    return keys


def composite_dims(role: str | None, params: dict) -> dict[str, tuple[float, str]]:
    """Числа из составных полей («Размер штор» 120Х175, «Габариты (Д*Ш*В)» 80х56 см) → ось → (число, имя поля).
    Двух чисел для трёхосевого поля: первое — первая ось, второе — ВЫСОТА (так пишут карточки света)."""
    out: dict[str, tuple[float, str]] = {}
    for key, axes in COMPOSITE_KEYS.get(role or '', []) + COMPOSITE_KEYS['*']:
        v = params.get(key)
        if not v:
            continue
        m = _title_triple.search(v)
        if not m:
            continue
        nums = [float(g) for g in m.groups() if g]
        if len(nums) == 3 and len(axes) == 3:
            pairs = list(zip(axes, nums))
        elif len(nums) == 2:
            pairs = [(axes[0], nums[0]), (axes[-1], nums[1])]
        else:
            continue
        for ax, n in pairs:
            out.setdefault(ax, (n, key))
    return out


def title_dims(role: str | None, name: str) -> dict[str, float]:
    """Размеры ТОЛЬКО из названия, когда параметров нет: «53х44х87 см» → Ш×Г×В (конвенция RU-карточек);
    два числа — по роли: шторы → Ш×В, свет → диаметр×В, остальным не верим."""
    m = _title_triple.search(name or '')
    if not m:
        return {}
    nums = [float(g) for g in m.groups() if g]
    if len(nums) == 3:
        return {'w': nums[0], 'd': nums[1], 'h': nums[2]}
    if role == 'шторы':
        return {'w': nums[0], 'h': nums[1]}
    if role in LIGHT_ROLES:
        return {'dia': nums[0], 'h': nums[1]}
    return {}


ROLE_MAX_CM = {
    'диван': 470, 'стенка': 430, 'ковёр': 500,
    'ваза': 60, 'статуэтка': 70, 'часы': 100, 'кашпо': 90,
    'лампа': 70, 'бра': 70, 'люстра': 150, 'подушка': 100, 'плед': 260,
}
# Потолок правдоподобной ВЫСОТЫ, см (для остального — 330, выше потолка мебель не бывает)
ROLE_MAX_H_CM = {'ваза': 120, 'статуэтка': 110, 'лампа': 100, 'бра': 80,
                 'люстра': 150, 'часы': 120, 'кашпо': 120, 'подушка': 80, 'плед': 260}
MIN_CM = 5.0    # меньше 5 см любая ось мебели/декора неправдоподобна
# НИЖНИЙ ПОРОГ ВЫСОТЫ ПО РОЛИ (catalog-holes-bank Н2б, 23.10) — зеркало `ROLE_MAX_H_CM` снизу. Накладной потолочный и
# настенный свет бывает плоским: панель 2,5 см, «таблетка» 3,6 см — 259 светильников теряли высоту как «неправдоподобную».
# Только люстра/бра: настольная лампа и торшер ниже 5 см не бывают, там это мусор. 0,1 см (6 штук) — мусор и для света.
ROLE_MIN_H_CM = {'люстра': 1.0, 'бра': 1.0}
# ДЛИННЫЙ ПОДВЕС (Н2в, этап 1): «Высота 230 см» у люстры — длина троса, а не мусор. Высоту `h_cm` по-прежнему не пишем
# (солвер, меш и сцена приняли бы её за рост предмета), но и в «нет высоты» не прячем: evidence `<источник>-suspension`
# с числом `cm` — подбор (`compose_gates.pendant_out`) исключает такой подвес из слота «люстра» с причиной.
PENDANT_MAX_CM = 600.0
# ВЫЛЕТ ПОДВЕСА — ОТДЕЛЬНЫЕ ПОЛЯ (Н2в этап 2, 23.10; без миграции — ключи в `dims_evidence.h`): `drop_min`/`drop_max` (см),
# `drop_adj` (регулируется: да/нет/неизвестно), `drop_from` (откуда максимум). Гейт прохода берёт `drop_min`
# (`compose_gates.pendant_out`): подвес укорачивают, не удлиняют. tvoydom 23.10: у 341 люстры «Высота» — диапазон «36/136»
# (нижняя граница = высота, верхняя — полный спуск, регулируемый), у 597 — «Длина цепи» (максимум = высота + цепь;
# входит ли цепь в «Высоту», фид не говорит — поэтому минимум остаётся высотой, это сторона «больше»), у 371 — флаг.
DROP_RANGE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*(?:см|мм|cm|mm)?\s*[/\-–—]\s*(\d+(?:[.,]\d+)?)')
DROP_CHAIN_KEY, DROP_ADJ_KEY = 'Длина цепи', 'Регулируемая высота'
# ВАЗА-ШАР БЕЗ ВЫСОТЫ (Н4): у шара высота = горизонтальный габарит (диаметр или Ш≈Г). Геометрия, не приор; ошибка
# до ~20 % (срез горла, ножка) — допустимо для гейта «влезает». Провенанс `shape_rule:sphere`.
SPHERE_ROLES = frozenset({'ваза', 'кашпо'})
SPHERE_RX = re.compile(r'(?<![а-яёa-z])шар(?![а-яёa-z])|сферическ', re.I)
SPHERE_WD_TOL = 0.10   # Ш и Г различаются не больше чем на 10 % — круглый в плане

# ТРАНСФОРМЕР: В ФИДЕ СПАЛЬНОЕ МЕСТО — ПАТТЕРН ПРОИЗВОДИТЕЛЯ (catalog-holes-bank Н3; владелец 23.10: «если указан только размер
# спального места и это характерный паттерн производителя — достраивай размеры сам примерно; главное — чтобы влезло»).
# Орматек: у дивана/кресла с механизмом «Ширина × Длина» фида и хвост названия «80x200» — спальное место (98 из 98 трансформеров
# 23.10; собранных Ш×Г в фиде нет, сайт за антиботом). Магазин в таблице = его паттерн замерен, не список товаров.
SLEEP_IN_FEED = {93965: 'Орматек: «Ширина×Длина» и хвост названия «A×B» у трансформера — спальное место'}
# Как лежит спальное место относительно фронта: ВДОЛЬ (еврокнижка, пантограф, клик-кляк…: фронт ≈ длина места) или ВПЕРЁД
# (аккордеон, выкатной, каскад…: фронт ≈ ширина места). Замер на 962 трансформерах divan.ru (место + собранные размеры):
# еврокнижка 165/165 и пантограф 96/96 — вдоль, шагающий 128/128 и выкатной 25/25 — вперёд. Неизвестный механизм — вдоль:
# фронт выходит больше, это безопасная сторона.
FORWARD_MECH = ('аккордеон', 'выкатн', 'каскад', 'отелло', 'седафлекс', 'миксотойл', 'шагающ', 'раскладушк', 'французск')
NOT_TRANSFORMER = re.compile(r'^\s*(|нет|не раскладывается|без механизма)\s*$', re.I)
# (тип, как лежит место) → (прибавка к фронту, глубина собранного [у углового — боковая сторона], высота), см. Квантиль 0,75
# по 956 трансформерам divan.ru 23.10 — пересчёт и сверка с этой таблицей: `transformer_calib.py`. Ошибка — скорее в «больше».
# Доля товаров с недооценкой > 10 % по Ш/Г/В: прямой — 0–4 % / 0 % / 0–7 %; кресло — 13 / 0 / 9 %; угловой «вдоль» — Ш 12 %,
# сторона 22 % (форма «Г» ~160 или шезлонг/«П» 240+ по названию не видна); угловой «вперёд» — Ш 18 % (n=55, разброс большой).
TRANSFORMER_COEF = {('кресло', 'вперёд'): (24, 105, 89), ('прямой', 'вдоль'): (52, 115, 90),
                    ('прямой', 'вперёд'): (24, 105, 87), ('угловой', 'вдоль'): (66, 175, 90),
                    ('угловой', 'вперёд'): (122, 160, 95)}
# Спальное место короче 173 см у 962 трансформеров divan.ru не встретилось (длинное — бывает до 396 у модульных, фронт ≈ место
# + 0…70, правило это уже покрывает); хвост короче — габарит предмета, а не место.
SLEEP_MIN_LEN = 170
_TAIL_AXB = re.compile(r'(\d{2,3})\s*[xх×X]\s*(\d{2,3})\s*\)?\s*$')
_CORNER = re.compile(r'углов|шезлонг|оттоманк|п-образ|модульн', re.I)

_num = re.compile(r'\d+(?:[.,]\d+)?')
_title_triple = re.compile(r'(\d{2,4})\s*[x×хXХ*]\s*(\d{2,4})(?:\s*[x×хXХ*]\s*(\d{2,4}))?')

_PRIORS: dict | None = None


def _priors() -> dict:
    global _PRIORS
    if _PRIORS is None:
        try:
            _PRIORS = json.load(open(PRIORS_PATH))
        except (OSError, json.JSONDecodeError):
            _PRIORS = {}
    return _PRIORS


# ДВЕ ОСИ В ОДНОМ ПОЛЕ — НЕ ОДНА ОСЬ (11.10). «40*25», «80+40» — это два разных габарита или две
# детали, и `_numval` молча брал первое число, выдавая его за ось.
#
# ДИАПАЗОН «40/120» И «100-130» СЮДА НЕ ВХОДИТ, и это измерено, а не мнение: из 178 значений с
# разделителем 157 — диапазоны через «/» (у подвесов это min/max вылета), и только 21 — настоящие
# две оси («*×x» 12, «+» 9). Первая версия правила запрещала и диапазоны: она отняла бы высоту у
# 132 люстр, УЖЕ стоящих в пуле, то есть сама сломала бы прирост, ради которого делалась (поймал
# субагент `verify`). Диапазон читаем как прежде — по нижней границе: для гейта «влезает» это
# безопасная сторона.
# Скобочные пояснения («200 см (с подлокотниками 215)») — одна ось плюс комментарий, читаем.
# Заглавные `X`/`Х` включены: фиды так пишут (см. кейс «120Х175» в селфтесте).
_ambiguous = re.compile(r'\d\s*[xхXХ*×+]\s*\d')


def ambiguous_value(s: str | None) -> bool:
    """Значение описывает ДВЕ оси (или две детали) — читать его как одну ось нельзя.

    Диапазон (`40/120`, `100-130`) НЕ считается многозначным: это одна ось с допуском."""
    return bool(_ambiguous.search(s or ''))


def _numval(s: str) -> float | None:
    if ambiguous_value(s):
        return None
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


def role_min(role: str | None, dim: str) -> float:
    if dim == 'h':
        return ROLE_MIN_H_CM.get(role or '', MIN_CM)
    return MIN_CM


def sphere_height(role: str | None, name: str, dims: dict) -> tuple[float, str] | None:
    """(высота, из чего) для вазы/кашпо-шара без высоты; None — правило не применимо."""
    if role not in SPHERE_ROLES or dims.get('h') is not None or not SPHERE_RX.search(name or ''):
        return None
    dia, w, d = dims.get('dia'), dims.get('w'), dims.get('d')
    if dia:
        h, src = max(x for x in (dia, w, d) if x), 'dia'
    elif w and d and abs(w - d) <= SPHERE_WD_TOL * max(w, d):
        h, src = max(w, d), 'w=d'
    else:
        return None
    return (h, src) if role_min(role, 'h') <= h <= role_max(role, 'h') else None


def transformer_dims(mid: int, role: str | None, name: str, params: dict, dims: dict):
    """Собранные Ш×Г×В трансформера по спальному месту (паттерн магазина `SLEEP_IN_FEED`); None — правило не применимо.
    → ({w,d,h}, {ось: evidence}, тип, ориентация). Измеренная высота фида остаётся (её не трогаем); фронт не меньше «Ширины»
    фида, если магазин прислал её больше места (Орматек Berlin: место 120, «Ширина» 180 — это собранный фронт)."""
    if mid not in SLEEP_IN_FEED or role not in ('диван', 'кресло'):
        return None
    mech = str(params.get('Механизм трансформации') or '')
    # трансформер — как у гейта банка (`bank_ready.TRANSFORMER_SQL`): механизм, «Раскладная конструкция» или «кровать» в названии
    if NOT_TRANSFORMER.match(mech) and str(params.get('Раскладная конструкция') or '').strip().lower() != 'да' \
            and not re.search(r'кроват', name or '', re.I):
        return None
    m = _TAIL_AXB.search(name or '')
    if not m:
        return None
    sw, sl = sorted((float(m.group(1)), float(m.group(2))))
    if sl < SLEEP_MIN_LEN:
        return None                          # «89x83» у кресла — его габарит, не спальное место
    typ = 'кресло' if (role == 'кресло' or re.search(r'кресло', name or '', re.I)) else \
          'угловой' if _CORNER.search(name or '') else 'прямой'
    orient = 'вперёд' if any(k in mech.lower() for k in FORWARD_MECH) else 'вдоль'
    if typ == 'кресло':
        orient = 'вперёд'                    # кресло-кровать раскладывается вперёд всегда (место 70–80 по фронту)
    add, d, h = TRANSFORMER_COEF.get((typ, orient), TRANSFORMER_COEF[(typ, 'вдоль')] if (typ, 'вдоль') in TRANSFORMER_COEF
                                     else TRANSFORMER_COEF[('прямой', 'вдоль')])
    w = (sl if orient == 'вдоль' else sw) + add
    feed_w = _numval(str(params.get('Ширина') or ''))
    if feed_w and feed_w > sw + 5 and feed_w > w:
        w = feed_w
    base = {'unit': 'cm', 'source': 'shape_rule:transformer', 'sleep': [sw, sl], 'mech': mech or None, 'type': typ,
            'orient': orient}
    out_d = {'w': w, 'd': float(d)}
    ev = {'w': dict(base, raw=w), 'd': dict(base, raw=float(d))}
    if dims.get('h') is None:
        out_d['h'] = float(h)
        ev['h'] = dict(base, raw=float(h))
    return out_d, ev, typ, orient


def pendant_drop(role: str | None, params: dict, dims: dict, ev_h: dict | None, h_str: str) -> dict | None:
    """Поля вылета люстры {drop_min, drop_max, drop_adj, drop_from} по уже разобранной высоте; None — нет высоты/не люстра."""
    if role != 'люстра' or not ev_h:
        return None
    src = ev_h.get('source') or ''
    lo = ev_h.get('cm') if src.endswith('-suspension') else dims.get('h')
    if lo is None:
        return None
    k = 10.0 if ev_h.get('unit') == 'mm' else 1.0
    a_s = str(params.get(DROP_ADJ_KEY) or '').strip().lower()
    adj = True if a_s.startswith('да') else False if a_s.startswith('нет') else None
    hi, frm = lo, 'height'
    m = DROP_RANGE.match(h_str or '')
    if m:
        a, b = (float(x.replace(',', '.')) / k for x in m.groups())
        if b > a and abs(a - lo) < 0.05 and b <= PENDANT_MAX_CM:
            hi, frm, adj = round(b, 1), 'range', True        # диапазон — это и есть регулировка
    if frm == 'height':
        c_s = str(params.get(DROP_CHAIN_KEY) or '').lower()
        c = _numval(c_s)
        if c and c > 0:
            mm = 'мм' in c_s or ('см' not in c_s and (k == 10.0 or c > 400))
            c = c / 10 if mm else c
            if lo + c <= PENDANT_MAX_CM:
                hi, frm = round(lo + c, 1), 'chain'
    return {'drop_min': lo, 'drop_max': hi, 'drop_adj': adj, 'drop_from': frm}


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

    comp = composite_dims(role, params)
    h_str = ''
    # РАЗБИРАЕМЫЕ, а не просто присутствующие: товар, у которого размерные поля ТОЛЬКО
    # многозначные, иначе терял бы и фолбэк из названия (находка `verify` 11.10).
    has_params = any(params.get(k) and not ambiguous_value(params.get(k))
                     for ks in dim_keys_for(mid, role).values() for k in ks)
    tdims = title_dims(role, name) if not has_params else {}
    # ТРОЙКА «Ш×Г×В» В НАЗВАНИИ — АВТОРИТЕТ ПО ОСЯМ (03.09): параметры магазинов называют оси
    # непоследовательно (у tvoydom «Длина» — то фасад, то глубина), а порядок чисел в названии RU-карточек
    # стабилен. Значения из названия — см (title_numbers); единица параметров при этом не трогается.
    ttriple = title_dims(role, name) if _title_triple.search(name or '') and len([g for g in _title_triple.search(name or '').groups() if g]) == 3 else {}
    for dim, keys in dim_keys_for(mid, role).items():
        raw, key_used, val_str = None, None, ''
        if dim in ttriple and dim in ('w', 'd', 'h'):
            val = ttriple[dim]
            if role_min(role, dim) <= val <= role_max(role, dim) * 1.15:
                dims[dim] = val
                evidence[dim] = {'raw': val, 'unit': 'cm', 'source': 'title-triple'}
                counts['title-triple'] = counts.get('title-triple', 0) + 1
                continue
        for k in keys:
            v = params.get(k)
            if v:
                raw, key_used, val_str = _numval(v), k, v
                if raw is not None:
                    break
        if dim == 'h':
            h_str = val_str
        if raw is None and dim in comp:
            raw, key_used, val_str = comp[dim][0], comp[dim][1], params.get(comp[dim][1], '')
        if raw is None and dim in tdims:
            # название — единственный источник; числа в нём считаем сантиметрами (см. title_numbers)
            dims[dim] = tdims[dim] if role_min(role, dim) <= tdims[dim] <= role_max(role, dim) * 1.15 else None
            if dims[dim] is not None:
                evidence[dim] = {'raw': tdims[dim], 'unit': 'cm', 'source': 'title-only'}
                counts['title-only'] = counts.get('title-only', 0) + 1
            continue
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
                if pr['unit'] == 'mm' and raw / 10 >= role_min(role, dim):
                    unit, source = 'mm', 'prior'
                elif pr['unit'] == 'cm' and role_min(role, dim) <= raw <= role_max(role, dim):
                    unit, source = 'cm', 'prior'
        # 4. Правдоподобие по роли
        if unit is None:
            mx, mn = role_max(role, dim), role_min(role, dim)
            if mn <= raw <= mx:
                unit, source = 'cm', 'plaus'
            elif raw > mx and mn <= raw / 10 <= mx:
                unit, source = 'mm', 'plaus'

        if unit is None:
            dims[dim] = None
            evidence[dim] = {'raw': raw, 'unit': None, 'source': 'unresolved'}
            counts['unresolved'] = counts.get('unresolved', 0) + 1
            continue
        val = round(raw / 10, 1) if unit == 'mm' else raw
        # Ролевой sanity-clamp итога: даже правильно разрешённая единица не спасает от
        # мусорного сырья (объём/артикул в размерном поле) — ваза «190 см» невозможна
        if not (role_min(role, dim) <= val <= role_max(role, dim) * 1.15):
            dims[dim] = None
            if role == 'люстра' and dim == 'h' and role_max(role, dim) * 1.15 < val <= PENDANT_MAX_CM:
                evidence[dim] = {'raw': raw, 'unit': unit, 'source': f'{source}-suspension', 'cm': val}
                counts['suspension'] = counts.get('suspension', 0) + 1
                continue
            evidence[dim] = {'raw': raw, 'unit': unit, 'source': f'{source}-insane'}
            counts['unresolved'] = counts.get('unresolved', 0) + 1
            continue
        dims[dim] = val
        evidence[dim] = {'raw': raw, 'unit': unit, 'source': source}
        tag = source if unit == 'cm' else f'{source}-mm'
        counts[tag] = counts.get(tag, 0) + 1

    drop = pendant_drop(role, params, dims, evidence.get('h'), h_str)
    if drop:
        evidence['h'].update(drop)          # в сводку источников (`dims_source`) не пишем: высота та же, поля — рядом
    tr = transformer_dims(mid, role, name, params, dims)
    if tr:
        dims.update(tr[0])
        evidence.update(tr[1])
        dims['len'] = None                   # спальное место — не «длина» предмета
        counts['shape-transformer'] = counts.get('shape-transformer', 0) + 1
    sph = sphere_height(role, name, dims)
    if sph:
        dims['h'] = sph[0]
        evidence['h'] = {'raw': sph[0], 'unit': 'cm', 'source': 'shape_rule:sphere', 'from': sph[1]}
        counts['shape-sphere'] = counts.get('shape-sphere', 0) + 1
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
                        for dim, keys in dim_keys_for(mid, role).items():
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


def rules_fingerprint() -> str:
    """Отпечаток таблиц разбора размеров. Правишь их — меняется `geometry_hash` у тысяч товаров, а
    `load3` помечает их обогащение `stale` → платное переобогащение (13.10: +3 761 карточка после правил
    осей 11.10, сняты вручную). Поэтому смена правил = подъём `load3.HASH_VERSION` (baseline без stale) и
    новый `load3.RULES_FINGERPRINT`; селфтест сверяет одно с другим."""
    import hashlib

    def norm(x):
        if isinstance(x, dict):
            return {str(k): norm(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
        if isinstance(x, (set, frozenset)):
            return sorted(norm(v) for v in x)
        if isinstance(x, (list, tuple)):
            return [norm(v) for v in x]
        return x if isinstance(x, (str, int, float, bool)) or x is None else str(x)
    # Пороги правдоподобия тоже меняют `geometry_hash` (Н2б/Н2в/Н4, 23.10: высота у 259 плоских светильников) — в отпечатке
    blob = json.dumps(norm({'dim': DIM_KEYS, 'shop': SHOP_DIM_KEYS, 'comp': COMPOSITE_KEYS,
                            'max': ROLE_MAX_CM, 'max_h': ROLE_MAX_H_CM, 'min': MIN_CM, 'min_h': ROLE_MIN_H_CM,
                            'pendant': PENDANT_MAX_CM, 'sphere': [sorted(SPHERE_ROLES), SPHERE_RX.pattern, SPHERE_WD_TOL],
                            'drop': [DROP_RANGE.pattern, DROP_CHAIN_KEY, DROP_ADJ_KEY], 'transformer': [SLEEP_IN_FEED, SLEEP_MIN_LEN, FORWARD_MECH, NOT_TRANSFORMER.pattern, TRANSFORMER_COEF,
                                            _TAIL_AXB.pattern, _CORNER.pattern]}),
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _fingerprint_guard() -> bool:
    """Отпечаток в load3.py совпадает с текущими правилами? load3 НЕ импортируем — он исполняет прогон."""
    import re as _re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'load3.py'), encoding='utf-8').read()
    m = _re.search(r"^RULES_FINGERPRINT\s*=\s*'([0-9a-f]+)'", src, _re.M)
    now = rules_fingerprint()
    if m and m.group(1) == now:
        print(f'ok   отпечаток правил размеров {now} = load3.RULES_FINGERPRINT')
        return True
    print(f'FAIL правила размеров изменились ({now} ≠ {m.group(1) if m else "нет"}): подними load3.HASH_VERSION '
          f'(иначе тысячи товаров уйдут в платное переобогащение) и запиши RULES_FINGERPRINT = \'{now}\'')
    return False


def selftest() -> None:
    cases = [
        # (mid, name, params, role, ось, ожидание_см, ожид_source)
        (114667, 'П-образный диван Босс Софт', {'Ширина': '440', 'Высота': '88'},
         'диван', 'w', 440.0, 'prior'),   # реальные см НЕ делятся (cm-приор группы диванов)
        (99272, 'Люстра подвесная', {'Высота': '780'}, 'люстра', 'h', 78.0, 'plaus'),
        (99272, 'Тумба узкая', {'Ширина, мм': '350'}, 'тв-тумба', 'w', 35.0, 'param'),
        (116933, 'Диван Тунне 145x82x86', {'Ширина': '145'}, 'диван', 'w', 145.0, 'title-triple'),   # тройка в названии — авторитет
        # название само в мм: точное совпадение 1200==1200 единицу не раскрывает → plaus
        (116933, 'Стеллаж 1200x300x1800', {'Ширина': '1200'}, 'стеллаж', 'w', 120.0, 'plaus'),
        (99272, 'Ваза', {'Высота': '4'}, 'ваза', 'h', None, None),   # < 5 см — не пишем
        # divan.ru: свои имена параметров, единица в значении, Длина габаритная = наш фронт w
        (112923, 'Комод Монблан 185x76', {'Размеры: Длина габаритная': '185см',
         'Размеры: Ширина габаритная': '50см', 'Размеры: Высота габаритная': '76см'},
         'комод', 'w', 185.0, 'param'),
        # П3.1 (исправлено 03.09): tvoydom — «Длина» = фасад (w), «Ширина» = глубина (d); тройка в названии
        # сильнее параметров (этот стул — редкий случай, где параметры перевёрнуты относительно названия)
        (99272, 'Стул TC Breeze 53х44х87 см', {'Ширина': '53', 'Длина': '44', 'Высота': '87'}, 'стул', 'd', 44.0, 'title-triple'),
        (99272, 'Стул TC Breeze 53х44х87 см', {'Ширина': '53', 'Длина': '44', 'Высота': '87'}, 'стул', 'w', 53.0, 'title-triple'),
        (99272, 'Комод Лофт', {'Ширина': '45', 'Длина': '120', 'Высота': '80'}, 'комод', 'w', 120.0, 'prior'),   # мини-приор 99272:комод:w есть
        (99272, 'Комод Лофт', {'Ширина': '45', 'Длина': '120', 'Высота': '80'}, 'комод', 'd', 45.0, 'plaus'),
        (99272, 'Стул TC Breeze', {'Ширина': '53', 'Длина': '44', 'Высота': '87'}, 'стул', 'len', None, None),
        # …а у ковра tvoydom «Длина» остаётся длиной
        (99272, 'Ковёр', {'Ширина': '160', 'Длина': '230'}, 'ковёр', 'len', 230.0, 'prior'),   # для ковра «Длина» остаётся длиной
        # П3.2: составные поля и название как единственный источник
        (99272, 'Роллета Уют', {'Размер штор': '120Х175'}, 'шторы', 'w', 120.0, 'plaus'),
        (99272, 'Люстра', {'Габариты (Д*Ш*В)': '80х56 см'}, 'люстра', 'h', 56.0, 'param'),
        (99272, 'Кресло Progarden 86х76х86 см', {}, 'кресло', 'd', 76.0, 'title-triple'),
        (99272, 'Светильник трековый 65*20', {}, 'светильник', 'dia', 65.0, 'title-only'),
        (99272, 'Стол 120x80', {}, 'стол', 'w', None, None),   # два числа без роли-конвенции — не верим
        # МНОГОЗНАЧНОЕ ЗНАЧЕНИЕ ПАРАМЕТРА — НЕ ОСЬ (11.10). «40*25» в «Диаметре» — две оси или
        # две детали; прежний `_numval` молча брал 40 и выдавал его за диаметр.
        (99272, 'Торшер Зета', {'Диаметр': '40*25', 'Высота': '150 см'}, 'торшер', 'dia', None, None),
        (99272, 'Торшер Зета', {'Диаметр': '40*25', 'Высота': '150 см'}, 'торшер', 'h', 150.0, 'param'),
        # Диапазон — ОДНА ось с допуском: читаем нижнюю границу. Бра — не мебельная роль, поэтому
        # конвенция магазина 99272 на него не распространяется и «Ширина» идёт в w (глобально).
        (99272, 'Бра Омега', {'Ширина': '16/26 см', 'Высота': '30 см'}, 'бра', 'w', 16.0, 'param'),
        # Заглавный разделитель фиды тоже пишут — он обязан отбрасываться наравне со строчным.
        (112923, 'Полка Вита', {'Ширина': '120Х175'}, 'полка', 'w', None, None),
        # Скобочное пояснение — ОДНА ось плюс комментарий: первое число верно, читаем.
        # Магазин без своей конвенции осей: «Ширина» идёт в w по глобальному DIM_KEYS.
        (112923, 'Диван Альфа', {'Ширина': '200 см (с подлокотниками 215)'}, 'диван', 'w', 200.0, 'param'),
        # Ноль уже отсекается правдоподобием (MIN_CM=5) — фиксируем контрактом, а не надеждой.
        (99272, 'Люстра Ноль', {'Диаметр': '0', 'Высота': '40 см'}, 'люстра', 'dia', None, None),
        # СВЕТ МАГАЗИНА 99272: «Длина» — вторая горизонталь, то есть ГЛУБИНА (замер 11.10).
        # Та же «Длина» у мебели этого магазина означает фасад — две конвенции в одном магазине.
        (99272, 'Люстра Рим', {'Ширина': '40 см', 'Длина': '50 см', 'Высота': '60 см'},
         'люстра', 'd', 50.0, 'param'),
        (99272, 'Люстра Рим', {'Ширина': '40 см', 'Длина': '50 см', 'Высота': '60 см'},
         'люстра', 'w', 40.0, 'param'),
        (99272, 'Комод Рим', {'Ширина': '45 см', 'Длина': '90 см', 'Высота': '80 см'},
         'комод', 'w', 90.0, 'param'),
        (99272, 'Комод Рим', {'Ширина': '45 см', 'Длина': '90 см', 'Высота': '80 см'},
         'комод', 'd', 45.0, 'param'),
        # ОРМАТЕК — КОНВЕНЦИЯ ОБРАТНА: «Ширина» фасад, «Длина» глубина (замер 11.10).
        (93965, 'Комод Орма', {'Ширина': '92 см', 'Длина': '53 см', 'Высота': '80 см'},
         'комод', 'w', 92.0, 'param'),
        (93965, 'Комод Орма', {'Ширина': '92 см', 'Длина': '53 см', 'Высота': '80 см'},
         'комод', 'd', 53.0, 'param'),
        # Н2б (23.10): НИЖНИЙ ПОРОГ ВЫСОТЫ СВЕТА — 1 см. Плоский накладной светильник — с высотой, а не «неправдоподобный»
        (99272, 'Светильник настенно-потолочный Плато', {'Высота': '2.5 см'}, 'люстра', 'h', 2.5, 'param'),
        (99272, 'Бра Таблетка', {'Высота': '45 мм'}, 'бра', 'h', 4.5, 'param'),
        (99272, 'Люстра Панель', {'Высота': '3'}, 'люстра', 'h', 3.0, 'prior'),   # cm-приор группы 99272
        (99272, 'Люстра Край', {'Высота': '1 см'}, 'люстра', 'h', 1.0, 'param'),    # ровно 1 см — берём
        (99272, 'Люстра Мусор', {'Высота': '0.9 см'}, 'люстра', 'h', None, None),   # ниже 1 см — нет
        (99272, 'Люстра Мусор', {'Высота': '0.1 см'}, 'люстра', 'h', None, None),   # 6 таких в каталоге — мусор
        (99272, 'Лампа настольная', {'Высота': '3 см'}, 'лампа', 'h', None, None),   # лампа ниже 5 см не бывает
        (99272, 'Торшер', {'Высота': '3 см'}, 'торшер', 'h', None, None),
        (99272, 'Люстра Плато', {'Диаметр': '3 см', 'Высота': '3 см'}, 'люстра', 'dia', None, None),   # порог 1 см — только высота
        # Н2в: подвес длиннее ROLE_MAX_H — высоту не пишем (рост предмета), но и не «нет высоты» (проверка ниже)
        (99272, 'Люстра Каскад', {'Высота': '230 см'}, 'люстра', 'h', None, None),
        # Н4: ваза-шар без высоты — высота = горизонталь; не шар / не круглая в плане / высота есть — правило молчит
        (99272, 'Ваза-шар Неман 260 мм', {'Длина': '26', 'Ширина': '26'}, 'ваза', 'h', 26.0, 'shape_rule:sphere'),
        (99272, 'Ваза Неман шар 140 мм', {'Длина': '14', 'Ширина': '14'}, 'ваза', 'h', 14.0, 'shape_rule:sphere'),
        (99272, 'Кашпо сферическое Луна', {'Диаметр': '30 см'}, 'кашпо', 'h', 30.0, 'shape_rule:sphere'),
        (99272, 'Ваза Шарм', {'Длина': '26', 'Ширина': '26'}, 'ваза', 'h', None, None),
        (99272, 'Ваза-шар овальная', {'Длина': '26', 'Ширина': '15'}, 'ваза', 'h', None, None),
        (99272, 'Ваза-шар Неман 18 см', {'Длина': '18', 'Ширина': '18', 'Высота': '15'}, 'ваза', 'h', 15.0, 'prior'),
        (99272, 'Статуэтка Шар', {'Длина': '26', 'Ширина': '26'}, 'статуэтка', 'h', None, None),
    ]
    bad = 0
    for mid, name, params, role, dim, want, want_src in cases:
        dims, ev, _ = resolve(mid, name, params, role)
        got, src = dims.get(dim), (ev.get(dim) or {}).get('source')
        ok = (got == want) and (want is None or src == want_src)
        bad += 0 if ok else 1
        print(f'{"ok " if ok else "FAIL"} {name[:32]:34} {dim}={got} (src={src}, ждали {want}/{want_src})')
    # Н2в: длинный подвес помечен «вылет» с числом — подбор исключит его из слота с причиной; мусор остаётся мусором
    _, ev, summ = resolve(99272, 'Люстра Каскад', {'Высота': '230 см'}, 'люстра')
    ok = ev['h'].get('source') == 'param-suspension' and ev['h'].get('cm') == 230.0 and 'suspension:1' in (summ or '')
    _, ev2, _ = resolve(99272, 'Люстра Мусор', {'Высота': '900 см'}, 'люстра')
    _, ev3, _ = resolve(99272, 'Бра Длинное', {'Высота': '230 см'}, 'бра')
    ok = ok and ev2['h']['source'].endswith('-insane') and ev3['h']['source'].endswith('-insane')
    bad += 0 if ok else 1
    print(f'{"ok " if ok else "FAIL"} подвес 230 см → suspension с числом; 900 см и бра 230 — мусор')
    # Н2в этап 2: поля вылета люстры — (params) → (drop_min, drop_max, drop_adj, drop_from); None — полей нет
    drop_cases = [
        ({'Высота': '36/136'}, 'люстра', (36.0, 136.0, True, 'range')),          # диапазон = регулировка
        ({'Высота': '59,8-142,3', 'Регулируемая высота': 'да'}, 'люстра', (59.8, 142.3, True, 'range')),
        ({'Высота': '36', 'Длина цепи': '52'}, 'люстра', (36.0, 88.0, None, 'chain')),   # минимум — высота: сторона «больше»
        ({'Высота': '1435', 'Длина цепи': '1000'}, 'люстра', (143.5, 243.5, None, 'chain')),   # мм у высоты → и у цепи
        ({'Высота': '230 см', 'Регулируемая высота': 'Да'}, 'люстра', (230.0, 230.0, True, 'height')),   # подвес
        ({'Высота': '32', 'Регулируемая высота': 'нет'}, 'люстра', (32.0, 32.0, False, 'height')),
        ({'Высота': '136/36'}, 'люстра', (136.0, 136.0, None, 'height')),        # «наоборот» — не диапазон
        ({'Высота': '36/136'}, 'бра', None),                                      # только люстра
        ({'Высота': '900 см'}, 'люстра', None),                                   # мусор — полей нет
    ]
    for params, role, want in drop_cases:
        _, ev, _ = resolve(99272, 'Светильник', params, role)
        h = ev.get('h') or {}
        got = (h.get('drop_min'), h.get('drop_max'), h.get('drop_adj'), h.get('drop_from')) if 'drop_min' in h else None
        ok = got == want
        bad += 0 if ok else 1
        print(f'{"ok " if ok else "FAIL"} вылет {role} {params} → {got} (ждали {want})')
    # Н3: трансформер Орматек — собранные Ш×Г×В по спальному месту из хвоста названия; ошибка — в сторону «больше»
    tr_cases = [   # (магазин, название, params, роль) → ожидаемые w, d, h (None — правило молчит, размеры фида как есть)
        (93965, 'Кресло-кровать Berlin (80x200)', {'Механизм трансформации': 'Аккордеон', 'Ширина': '80'}, 'кресло',
         (104.0, 105.0, 89.0)),
        (93965, 'Диван-кровать Berlin (120x200)', {'Механизм трансформации': 'Аккордеон', 'Ширина': '180'}, 'диван',
         (180.0, 105.0, 87.0)),   # «Ширина» фида больше места — это собранный фронт, берём её
        (93965, 'Угловой диван Фиант (137x200)', {'Механизм трансформации': 'Еврокнижка'}, 'диван', (266.0, 175.0, 90.0)),
        (93965, 'Диван Easy Home (150x200)', {'Механизм трансформации': 'Пантограф', 'Высота': '99'}, 'диван',
         (252.0, 115.0, 99.0)),   # измеренная высота фида остаётся
        (93965, 'Угловой диван Verona (215x334)', {'Механизм трансформации': 'Не раскладывается', 'Ширина': '215',
                                                  'Длина': '334', 'Высота': '80'}, 'диван', None),
        (99272, 'Диван-кровать Berlin (120x200)', {'Механизм трансформации': 'Аккордеон'}, 'диван', None),  # чужой магазин
        (93965, 'Диван-кровать Berlin', {'Механизм трансформации': 'Аккордеон'}, 'диван', None),   # нет места в названии
        (93965, 'Кресло-кровать Tokio Middle (Велюр) 100x157', {'Ширина': '100см'}, 'кресло', None),   # 157 — не длина места
        (93965, 'Кресло Fiji (Велюр) 89x83', {'Раскладная конструкция': 'Да'}, 'кресло', None),   # габарит кресла
        (93965, 'Угловой диван-кровать Tokio Middle (левый, правый) 157x296', {}, 'диван', (362.0, 175.0, 90.0)),  # «кровать»
    ]
    for mid, name, params, role, want in tr_cases:
        dims, ev, _ = resolve(mid, name, params, role)
        got = (dims.get('w'), dims.get('d'), dims.get('h'))
        is_tr = (ev.get('w') or {}).get('source') == 'shape_rule:transformer'
        ok = (got == want and is_tr) if want else not is_tr
        bad += 0 if ok else 1
        print(f'{"ok " if ok else "FAIL"} трансформер {name[:32]:34} w/d/h={got} (ждали {want or "без правила"})')
    if not _fingerprint_guard():
        bad += 1
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    if '--learn' in sys.argv:
        learn()
    elif '--selftest' in sys.argv:
        selftest()
    else:
        print(__doc__)
