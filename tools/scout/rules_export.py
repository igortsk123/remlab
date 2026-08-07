#!/usr/bin/env python3
"""Экспорт ВСЕГО действующего свода правил в один .xlsx — для ревизии владельцем.

Листы: оглавление · канон occupancy.json (один файл на оба движка) · zones.json (группы/зоны/
inventory-prior/иерархия) · weights.json (веса скоринга) · composition.json (доли пола по
метражу) · size-bands.json (размерные гейты) · proportions.json · коды валидатора (из
validate.py, с severity и местом).

Запуск: ~/venvs/scout/bin/python rules_export.py [выходной .xlsx]
"""
import datetime
import json
import os
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/rules-svod-{datetime.date.today().isoformat()}.xlsx')

FILES = [
    ('occupancy.json', os.path.join(SOLVER, 'rules', 'occupancy.json'),
     'КАНОН расстановки: шкалы расстояний по метражу, доли, ярусы, именованные правила '
     '(один файл на оба движка; tools/scout/occupancy.json — синхронизированная копия)'),
    ('zones.json', os.path.join(SOLVER, 'rules', 'zones.json'),
     'Зоны-first (ADR-0074): 10 посадочных групп с футпринтами, внутренняя схема группы, '
     'функциональные зоны, inventory-prior по usable-площади, лексикографическая иерархия'),
    ('weights.json', os.path.join(SOLVER, 'rules', 'weights.json'),
     'Веса мягких термов скоринга солвера'),
    ('composition.json', os.path.join(HERE, 'composition.json'),
     'Состав сетов: доли площади пола по ролям в каждом метраже'),
    ('size-bands.json', os.path.join(HERE, 'size-bands.json'),
     'Размерный гейт: допустимая ширина роли в метраже'),
    ('proportions.json', os.path.join(HERE, 'proportions.json'),
     'Пропорции предметов друг к другу (жёсткий фильтр до скоринга)'),
]


def flatten(obj, path=''):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            rows += flatten(v, f'{path}.{k}' if path else str(k))
    elif isinstance(obj, list) and any(isinstance(x, (dict, list)) for x in obj):
        for i, v in enumerate(obj):
            rows += flatten(v, f'{path}[{i}]')
    else:
        val = json.dumps(obj, ensure_ascii=False) if isinstance(obj, list) else obj
        rows.append((path, val))
    return rows


def add_sheet(wb, title, rows, headers):
    ws = wb.create_sheet(title[:31])
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(list(r))
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            widths[c.column] = min(90, max(widths.get(c.column, 10),
                                           len(str(c.value or '')) + 2))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = 'A2'
    return ws


def validator_codes():
    """Каждый вызов _v(...) разбираем ЦЕЛИКОМ (многострочно): severity часто на следующей
    строке, и однострочный парс оставлял «Жёсткость» пустой — внешний аудит 08.08 счёл это
    отсутствием источника истины. Дефолт _v без Severity — HARD (см. сигнатуру _v)."""
    src = open(os.path.join(SOLVER, 'planner', 'validate.py')).read()
    lines = src.splitlines()
    funcs = []
    for i, line in enumerate(lines, 1):
        m = re.match(r'def (check_\w+)', line)
        if m:
            rest = src.split(line, 1)[1]
            d = re.match(r'[^"]*"""(.*?)"""', rest, re.S)
            funcs.append((i, m.group(1), ' '.join(d.group(1).split())[:200] if d else ''))
    def func_of(ln):
        cur = ('', '')
        for fi, fn, doc in funcs:
            if fi <= ln:
                cur = (fn, doc)
        return cur
    seen = {}
    for m in re.finditer(r'_v\(\s*"([A-Z][A-Z_]{3,})"', src):
        ln = src[:m.start()].count('\n') + 1
        depth = 0
        j = m.start()
        while j < len(src):
            if src[j] == '(':
                depth += 1
            elif src[j] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        call = src[m.start():j + 1]
        code = m.group(1)
        sev = ('SOFT' if 'Severity.SOFT' in call else 'HARD')
        fn, doc = func_of(ln)
        if code not in seen:
            seen[code] = [code, sev, fn, f'validate.py:{ln}', doc]
        elif sev == 'SOFT' and seen[code][1] == 'HARD':
            seen[code][1] = 'HARD/SOFT (по условию)'
    return sorted(seen.values())


# --- Режим «для рефери» (--referee): позиция по аудиту + спорные вопросы -------------------
AUDIT_RESPONSE = [
 ('P0.1 Жёсткость кодов пуста', 'ИСПРАВЛЕНО 08.08', 'Дефект экспортёра (severity на соседней строке не парсилась). Теперь: rules/severity.json — реестр классов H0/H1/S1/S2 на каждый код + тест test_severity_registry, механически сверяющий реестр с кодом валидатора. В листе «коды валидатора» — фактическая жёсткость и класс.'),
 ('P0.2 CHAIR_ORPHAN 40 vs 100 см', 'ИСПРАВЛЕНО (док), КОД БЫЛ ВЕРЕН', 'В коде всегда 40 см и ТОЛЬКО для роли «стул» (обеденный); кресло — отдельная роль, правило его не касается. «100 см» — устаревший docstring, исправлен. Subtype-разделение, которого требовал аудит, уже было по построению ролей.'),
 ('P0.3 Столик от площади', 'ПРИНЯТО, W2 РЕАЛИЗОВАНО 08.08', 'Валидатор: hard 32–50 (tight-fallback), комфорт 36–46 soft (SOFA_TABLE_COMFORT), от площади НЕ зависит. Area-шкала dynamic.sofa_table_cm помечена legacy. Скоринг переведён на те же вилки.'),
 ('P0.4 ТВ-дистанция от площади', 'ПРИНЯТО, W2 РЕАЛИЗОВАНО 08.08', 'Primary — диагональ: ТВ в сете нет (рисует генератор), диагональ ОЦЕНИВАЕТСЯ по ширине тумбы (экран≈70% тумбы, /0.872 для 16:9). Вилка 1.2–2.5 диагонали hard, >2.0 soft. Area-шкала — только фолбэк при неизвестной ширине. ВОПРОС РЕФЕРИ №2: корректна ли оценка диагонали по тумбе.'),
 ('P0.5 Несколько floor-cap', 'ЧАСТИЧНО; РАЗВОД СУЩНОСТЕЙ В ОЧЕРЕДИ (W7 IR)', 'Фактически: floor_cap_pct (dynamic, по метражу) — операционный кап солвера/состава; composition.global_floor_cap — legacy-фолбэк. Развод на 4 метрики (physical/usable/visual/zone) — часть будущего constraint-IR.'),
 ('P0.6 corner_sofa_must_be_in_corner', 'УЖЕ БЫЛО КАК РЕКОМЕНДОВАНО', 'CORNER_SOFA_ADRIFT — SOFT (класс S2), floating разрешён: в комнатах 50+ Г-диван ОБЯЗАН отплывать (комментарий в коде validate.py). Флаг в occupancy — предпочтение кандидатов, не hard.'),
 ('P0.7 tv_not_on_window_wall hard ban', 'УЖЕ БЫЛО КАК РЕКОМЕНДОВАНО', 'TV_ON_WINDOW_WALL — SOFT (S1), штраф за блики, не запрет. Раздельные проверки window-obstruction (WINDOW_BLOCKED, hard) и glare (этот SOFT) уже есть.'),
 ('P0.8 base=диван+столик+ТВ конфликтует с zones-first', 'ПРИНЯТО, РЕАЛИЗОВАНО Z4', 'Состав идёт scenario→usable→группа→спутники (compose2+zones.json). placement_tiers.base — ярусы ПРИОРИТЕТА размещения у солвера (что терять последним), не обязательный состав; столик в ≤8 м² band опционален.'),
 ('P0.9 size-bands hard gate', 'ПРИНЯТО, W3 РЕАЛИЗОВАНО 08.08', 'Вилка → приоритет: in-band первыми + бонус, вне — штраф −1.5, НЕ выбывание. Жёстко отсеивают только функция/пропорции/качество карточки; физическую невозможность ловит солвер геометрией.'),
 ('P0.10 SOFA_AIM 30° без сценария', 'ПРИНЯТО ЧАСТИЧНО: H1-класс', 'Класс H1 = «жёстко в ТЕКУЩЕМ продукте (media-гостиная — единственный сценарий)». При добавлении сценариев конфиг перейдёт в условный. Снимать сейчас — нет продукта-потребителя.'),
 ('P1 5.1 chair_requires_dining_table', 'УЖЕ БЫЛО', 'Только роль «стул»; кресло/акцентное — отдельные роли.'),
 ('P1 5.3-5.4 rug-правила', 'УЖЕ БЫЛО', 'Две легальные схемы (front-legs / под столиком с выносами) + вариант «вся мебель на большом ковре» (правка владельца). Схема «только под столиком» — фолбэк, не приоритет.'),
 ('F2S gaps (articulation/reach/workflow/balance)', 'ЧАСТИЧНО / СКОУП', 'Articulation прямоугольной аппроксимацией УЖЕ есть (фасады 50–80, ящик 76, ноги 46 — clearances.py). pair_symmetry добавлен (W5, ярус S2). Reach/posture/workflow/acoustics — сознательно вне скоупа продукта (см. страницу-обоснование).'),
 ('DFS/beam «слабее»', 'ФОРМУЛИРОВКИ ИСПРАВЛЕНЫ', 'Только «на нашем бенчмарке»; страница-обоснование переписана, оба движка сравнимы в лоб: solver_run --engine beam|zoned|dfs.'),
 ('3D-FRONT «реальные»', 'ИСПРАВЛЕНО', 'Везде: «профессионально спроектированные СИНТЕТИЧЕСКИЕ сцены», подмножество фильтровали сами (5 742 гостиных).'),
 ('Provenance без SHA', 'ПРИНЯТО, W4 РЕАЛИЗОВАНО 08.08', 'infinigen@25a7d28 src/infinigen_examples/constraints/home.py (секция livingrooms); Holodeck@362b8ed ai2holodeck/generation/small_objects.py; помечено derived, дата сверки.'),
]
REFEREE_QUESTIONS = [
 ('Q1', 'Обеденная группа: гейт «остаток usable ≥ 6 м²» (после вычета футпринта посадочной группы). Порог взят инженерно (стол 120×75 + стулья + отступы). Верна ли величина и сам подход?'),
 ('Q2', 'ТВ-дистанция: диагональ ОЦЕНИВАЕТСЯ по ширине тумбы (экран ≈ 70% ширины тумбы, диагональ = ширина экрана / 0.872). ТВ как товар в сете отсутствует. Допустима ли такая оценка как primary?'),
 ('Q3', 'DEAD_ZONE_BEHIND_SOFA: полоса за спинкой дивана на ВСЮ ширину комнаты (не только тень дивана) — вердикт владельца после сета с камином в углу за спиной. Не слишком ли широко для больших комнат?'),
 ('Q4', 'NOT_AT_WALL (корпусная мебель спинкой к стене ≤20 см) — класс H1. Room-divider сценарии (стеллаж как перегородка) пока запрещены. Оставить до появления сценария или ослабить сейчас?'),
 ('Q5', 'floor_cap_pct по метражу (40–50% малые → 26–34% в 50+) — операционный кап. Смешивает physical footprint и visual density (замечание P0.5). Достаточно ли до IR-рефактора?'),
 ('Q6', 'Камин: планируем FIREPLACE_FAR_FROM_SEATING (S1) при >450 см до посадки + требование видимости с главной посадки (сектор ≤~75° от оси взгляда). Согласен с порогами 200–450 и углом?'),
 ('Q7', 'Диван спинкой к окну: enforce отступ 15–20 см + «спинка не выше низа стекла» (правило есть в данных, в валидатор не доведено). Какой класс — H1 или S1?'),
]

def referee_sheets(wb):
    ws = add_sheet(wb, 'ответ на аудит', AUDIT_RESPONSE,
                   ['Пункт аудита', 'Статус', 'Позиция проекта / что сделано'])
    ws.column_dimensions['C'].width = 110
    ws2 = add_sheet(wb, 'вопросы рефери', REFEREE_QUESTIONS, ['№', 'Вопрос'])
    ws2.column_dimensions['B'].width = 120
    accpt = [
     ('Приёмочный набор', '252 зафиксированные сцены: 126 базовых прямоугольных + 63 вытянутых 1:1.5 + 63 сложных контура (эркер/пилоны/трапеция), acceptance-scenes.json в git'),
     ('Старый движок (beam), новые составы', '119/252 чистых (47%); медиана мягкого балла 11.1'),
     ('Зонный движок, новые составы', '239/252 чистых (95%); медиана 9.7; сцен хуже старого — 0'),
     ('Зонный по типам сцен', 'база 124/126, вытянутые 56/63, эркер 20/21, пилоны 21/21, трапеция 18/21'),
     ('Решение', 'зонный — боевой дефолт с 08.08; beam остаётся для A/B (--engine beam)'),
     ('Прогон с W-правками', 'идёт на момент экспорта; W2 строже (фикс-эргономика) + впервые полные составы с парами'),
    ]
    ws3 = add_sheet(wb, 'приёмка (контекст)', accpt, ['Что', 'Результат'])
    ws3.column_dimensions['B'].width = 120


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = 'Оглавление'
    ws.append(['Свод правил remlab — полный экспорт', ''])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([f'Дата: {datetime.date.today().isoformat()}', ''])
    ws.append(['Лист', 'Что это'])
    for name, _, note in FILES:
        ws.append([name, note])
    ws.append(['коды валидатора', 'все именованные проверки размещения: код, жёсткость, '
               'функция и строка в validate.py'])
    for col, w in (('A', 28), ('B', 110)):
        ws.column_dimensions[col].width = w
    for name, path, _ in FILES:
        data = json.load(open(path))
        add_sheet(wb, name, flatten(data), ['Правило (путь в файле)', 'Значение'])
    sev_reg = json.load(open(os.path.join(SOLVER, 'rules', 'severity.json')))
    rows = [r + [sev_reg['codes'].get(r[0], '')] for r in validator_codes()]
    add_sheet(wb, 'коды валидатора', rows,
              ['Код', 'Жёсткость (код)', 'Проверка', 'Место', 'Описание проверки',
               'Класс (severity.json: H0 физика / H1 функция сценария / S1 эргономика / S2 эстетика)'])
    if '--referee' in sys.argv:
        referee_sheets(wb)
    wb.save(OUT)
    print(f'{OUT}: {len(wb.sheetnames)} листов')


if __name__ == '__main__':
    main()
