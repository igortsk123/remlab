"""Текст объявления (T-20261109-04): разбор строк риелтора и сопоставление с подписями плана по имени."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import listing as ls  # noqa: E402


@pytest.mark.parametrize('line, name, dims, unit', [
    ('Lounge L:3.77m W:4.20m', 'Lounge', (3.77, 4.20), 'm'),
    ('Lounge 3.77m x 4.20m', 'Lounge', (3.77, 4.20), 'm'),
    ('Lounge 3.77 x 4.20', 'Lounge', (3.77, 4.20), 'm'),
    ('Kitchen/Diner: 5.10m × 3.05m', 'Kitchen/Diner', (5.10, 3.05), 'm'),
    ("Bedroom Two 12'3\" x 6'9\"", 'Bedroom Two', (3.734, 2.057), 'ft'),
    ("Bedroom 1 4.10m (13'5\") x 3.20m (10'6\") max", 'Bedroom 1', (4.10, 3.20), 'm'),
    ('Sitting Room - 5,16 m x 4,68 m', 'Sitting Room', (5.16, 4.68), 'm'),
])
def test_parse_line_formats(line, name, dims, unit):
    r = ls.parse_line(line)
    assert r is not None
    assert r['name'] == name
    assert r['dims_m'] == pytest.approx(dims, abs=0.002)
    assert r['unit'] == unit


def test_parse_line_notes_and_feet_check():
    r = ls.parse_line("Living Room 6.02m x 3.96m (19'9\" x 13'0\") into bay")
    assert 'into bay' in r['notes']
    assert 'conflict' not in r
    r = ls.parse_line("Study 3.20m x 2.10m (13'9\" x 6'11\")")        # 13'9" = 4,19 м — чтение не сошлось
    assert r['conflict'] == 'метры ≠ футы'
    r = ls.parse_line('Master Bedroom 4.50m x 3.60m (max)')
    assert r['notes'] == ['max']


def test_parse_line_without_two_sizes_is_none():
    assert ls.parse_line('Ground Floor') is None
    assert ls.parse_line('Gross internal area 125 sq m') is None
    assert ls.parse_line('Garden 30m') is None


def test_parse_listing_name_on_line_above():
    rows = ls.parse_listing('GROUND FLOOR\nLounge\n3.77m x 4.20m\n\nKitchen 3.10m x 2.40m\n')
    assert [(r['name'], r['dims_m']) for r in rows] == [('Lounge', (3.77, 4.20)), ('Kitchen', (3.10, 2.40))]


def test_norm_name_numbers_case_separators():
    assert ls.norm_name('Bedroom One') == ls.norm_name('BEDROOM 1') == ls.norm_name('bedroom 01')
    assert ls.norm_name('Kitchen/Diner') == ls.norm_name('Kitchen & Diner') == ls.norm_name('kitchen and diner')
    assert ls.norm_name('Bedroom Two') != ls.norm_name('Bedroom 1')


def test_match_takes_text_size_and_flags_orphans():
    plan = [{'name': 'Lounge', 'dims': None}, {'name': 'Bedroom 1', 'dims': None}, {'name': 'Bathroom', 'dims': None},
            {'name': 'Kitchen', 'dims': (3.1, 2.4)}]
    rows = ls.parse_listing('Lounge L:3.77m W:4.20m\nBedroom One 3.50m x 3.00m max\nKitchen 2.40m x 3.10m\n'
                            'Utility 2.00m x 1.50m\n')
    got, orphans = ls.match(plan, rows)
    by = {g['name']: g for g in got}
    assert by['Lounge']['dims'] == (3.77, 4.20) and by['Lounge']['dims_src'] == 'text'
    assert by['Bedroom 1']['dims'] == (3.5, 3.0) and 'текст: max' in by['Bedroom 1']['text_flags']
    assert by['Kitchen']['dims_src'] == 'both'                         # порядок сторон не важен
    assert by['Bathroom']['dims'] is None and 'нет в тексте' in by['Bathroom']['text_flags']
    assert [o['name'] for o in orphans] == ['Utility']


def test_match_duplicate_names_not_guessed():
    plan = [{'name': 'Bedroom', 'dims': None}, {'name': 'Bedroom', 'dims': None}]
    rows = ls.parse_listing('Bedroom 3.00m x 3.00m\nBedroom 4.00m x 3.50m\n')
    got, orphans = ls.match(plan, rows)
    assert all(g['dims'] is None for g in got)
    assert all('повтор имени — текст не взят' in g['text_flags'] for g in got)
    assert len(orphans) == 2


def test_match_text_disagrees_with_plan_keeps_plan_and_flags():
    got, _ = ls.match([{'name': 'Study', 'dims': (3.2, 2.93)}], ls.parse_listing('Study 3.60m x 2.93m'))
    assert got[0]['dims'] == (3.2, 2.93)
    assert any('≠ план' in f for f in got[0]['text_flags'])


# ── миллиметры, сантиметры и синонимы имён (T-20261110-29: лист агента с `3,290.0mm`, 0 из 5 строк сопоставлено) ──

@pytest.mark.parametrize('line, name, dims', [
    ('Bedroom 1 - 3,290.0mm x 3,754.0mm - 10\' 10" x 12\' 4"', 'Bedroom 1', (3.29, 3.754)),     # агентский лист 10.11
    ('En-Suite - 3,265.0mm x 1,215.0mm - 10\' 9" x 4\'', 'En-Suite', (3.265, 1.215)),
    ('Kitchen 3290mm x 2450mm', 'Kitchen', (3.29, 2.45)),
    ('Lounge 4,880 x 3,660mm', 'Lounge', (4.88, 3.66)),                                         # одна единица на пару
    ('Bedroom 2 329cm x 305cm', 'Bedroom 2', (3.29, 3.05)),
    ('Dining Room 4.5 x 3.2 m', 'Dining Room', (4.5, 3.2)),
    ('Bedroom 3 - 2119 mm x 3018 mm', 'Bedroom 3', (2.119, 3.018)),
    ('Garage 5,500mm x 2,700mm', 'Garage', (5.5, 2.7)),
    # Rightmove / Zoopla / OnTheMarket: метры и футы в одной строке, метрика главнее, в любом порядке
    ('Living Room 4.88m x 3.66m (16\'0" x 12\'0")', 'Living Room', (4.88, 3.66)),
    ('Bedroom 1 13\'2" x 11\'5" (4.01m x 3.48m)', 'Bedroom 1', (4.01, 3.48)),
    ('Reception Room: 4.57m x 3.66m (15\' x 12\')', 'Reception Room', (4.57, 3.66)),
    ('Bedroom 1 - Double - 3.20m x 4.10m', 'Bedroom 1', (3.2, 4.1)),                            # хвост « - Double» — не имя
    ('Kitchen - Diner 3.20m x 4.10m', 'Kitchen - Diner', (3.2, 4.1)),                          # «Diner» — помещение, имя целиком
])
def test_parse_line_metric_mm_cm_and_feet(line, name, dims):
    r = ls.parse_line(line)
    assert r is not None and r['name'] == name and r['unit'] == 'm'
    assert r['dims_m'] == pytest.approx(dims, abs=0.002)
    assert 'conflict' not in r


def test_parse_line_mm_feet_check_and_notes():
    r = ls.parse_line('Bedroom 1 - 3,290.0mm x 3,754.0mm - 10\' 10" x 12\' 4"')
    assert r['dims_ft_m'] == pytest.approx((3.302, 3.759), abs=0.002)                          # футы — сверка, сошлись
    r = ls.parse_line('Lounge 4,880mm x 3,660mm (19\'9" x 12\'0") into bay')
    assert r['conflict'] == 'метры ≠ футы' and r['notes'] == ['into bay']                       # 19'9" = 6,02 м
    r = ls.parse_line('Master Bedroom 4.12m (13\'6") max x 3.61m (11\'10")')
    assert r['name'] == 'Master Bedroom' and r['notes'] == ['max'] and r['dims_m'] == (4.12, 3.61)
    assert ls.parse_line('Total area 72.5 m²') is None and ls.parse_line('Ground Floor 1,200 sq ft') is None


def test_alias_key_spellings():
    assert ls.alias_key('ES') == ls.alias_key('En-Suite') == ls.alias_key('ENSUITE') == ls.alias_key('en suite')
    assert ls.alias_key('BATH ROOM') == ls.alias_key('Bathroom')
    assert ls.alias_key('W.C.') == ls.alias_key('WC') == ls.alias_key('Cloakroom')
    assert ls.alias_key('Bed 2') == ls.alias_key('Bedroom 2') and ls.alias_key('ST.') == ls.alias_key('Store')
    assert ls.alias_key('Lounge') != ls.alias_key('Living Room')                                # разные слова — не синонимы


AGENT_1011 = ('First Floor\nBedroom 1 - 3,290.0mm x 3,754.0mm - 10\' 10" x 12\' 4"\nEn-Suite - 3,265.0mm x 1,215.0mm - 10\' 9" x 4\'\n'
              'Bedroom 2 - 3,290.0mm x 3,055.0mm - 10\' 10" x 10\'\nBedroom 3 - 2,119.0mm x 3,018.0mm - 6\' 11" x 9\' 11"\n'
              'Bathroom - 2,075.0mm x 1,878.0mm - 6\' 10" x 6\' 2"')


def test_match_agent_sheet_mm_aliases_and_master():
    """Лист агента 10.11 (`aRQVC9nJ1g1WqBTXeA6VqA`): подписи плана VLM ↔ строки объявления — все 5 с размером из текста."""
    plan = [{'name': n, 'dims': None} for n in ('MASTER BEDROOM', 'BEDROOM 3', 'ES', 'BEDROOM 2', 'ST.', 'BATH ROOM')]
    got, orphans = ls.match(plan, ls.parse_listing(AGENT_1011))
    by = {g['name']: g for g in got}
    assert orphans == []
    assert by['MASTER BEDROOM']['dims'] == (3.29, 3.754) and by['MASTER BEDROOM']['text_match'] == 'master'
    assert by['ES']['dims'] == (3.265, 1.215) and by['ES']['text_match'] == 'alias'
    assert by['BATH ROOM']['dims'] == (2.075, 1.878) and by['BATH ROOM']['text_match'] == 'alias'
    assert by['BEDROOM 2']['text_match'] == by['BEDROOM 3']['text_match'] == 'name'
    assert sum(g['dims_src'] == 'text' for g in got) == 5 and by['ST.']['dims'] is None


def test_match_master_only_when_unambiguous():
    rows = ls.parse_listing('Bedroom 1 3.30m x 3.75m\nBedroom 2 3.00m x 3.00m')
    # своя «Bedroom 1» на плане есть — главную не подменяем
    got, orphans = ls.match([{'name': 'Master Bedroom', 'dims': None}, {'name': 'Bedroom 1', 'dims': None},
                             {'name': 'Bedroom 2', 'dims': None}], rows)
    by = {g['name']: g for g in got}
    assert by['Master Bedroom']['dims'] is None and by['Bedroom 1']['dims'] == (3.3, 3.75)
    # две «главные» на плане — не угадываем
    got, _ = ls.match([{'name': 'Master Bedroom', 'dims': None}, {'name': 'Principal Bedroom', 'dims': None}], rows)
    assert all(g['dims'] is None for g in got)
    # обратная сторона: на плане «Bedroom 1», в тексте единственная «Master Bedroom» и своей «Bedroom 1» нет
    got, _ = ls.match([{'name': 'BEDROOM 1', 'dims': None}], ls.parse_listing('Master Bedroom 4.12m x 3.61m'))
    assert got[0]['dims'] == (4.12, 3.61) and got[0]['text_match'] == 'master'


def test_match_alias_one_to_one():
    """Синоним — только один-к-одному: «ES» и «En-Suite» на плане при одной строке «Ensuite» — не угадываем."""
    got, orphans = ls.match([{'name': 'ES', 'dims': None}, {'name': 'En-Suite', 'dims': None}],
                            ls.parse_listing('Ensuite 2.00m x 1.50m'))
    assert all(g['dims'] is None for g in got) and orphans[0]['why'] == 'неясно, какая комната на плане'
    # точный ключ главнее синонима: «WC» ↔ «WC», «Cloakroom» ↔ «Cloakroom»
    got, orphans = ls.match([{'name': 'WC', 'dims': None}, {'name': 'Cloakroom', 'dims': None}],
                            ls.parse_listing('WC 1.20m x 0.90m\nCloakroom 1.50m x 1.00m'))
    assert {g['name']: g['dims'] for g in got} == {'WC': (1.2, 0.9), 'Cloakroom': (1.5, 1.0)} and orphans == []


# ── русский текст агента (T-20261109-33, «размеры своими словами») ──

@pytest.mark.parametrize('line, name, dims', [
    ('гостиная 4,2 на 3,8', 'гостиная', (4.2, 3.8)),
    ('Гостиная: 4.2 x 3.8', 'Гостиная', (4.2, 3.8)),
    ('спальня 3×3', 'спальня', (3.0, 3.0)),
    ('Спальня 1 — 3х3,5', 'Спальня 1', (3.0, 3.5)),                  # «х» — кириллица
    ('кухня 3 на 4 м', 'кухня', (3.0, 4.0)),
    ('Комната 2 4,5 м на 3 м', 'Комната 2', (4.5, 3.0)),
    ('детская 3 метра на 2,8 метра', 'детская', (3.0, 2.8)),
])
def test_parse_line_russian(line, name, dims):
    r = ls.parse_line(line)
    assert r is not None and r['name'] == name and r['unit'] == 'm'
    assert r['dims_m'] == pytest.approx(dims, abs=0.002)


def test_parse_line_room_area_and_english_integers_unchanged():
    r = ls.parse_line('кухня 10 м²')
    assert r['name'] == 'кухня' and r['dims_m'] is None and r['area_m2'] == 10.0
    assert ls.parse_line('Bedroom 2 9,8 кв. м')['area_m2'] == 9.8
    assert ls.parse_line('Общая площадь 54,3 м²') is None                # общая — не комната (это total_area)
    assert ls.parse_line('Gross internal area 125 sq m') is None
    assert ls.parse_line('Bedroom 3 x 3') is None                         # целые без единиц — только у русского текста
    assert ls.parse_line('кухня 10 м2')['dims_m'] is None                 # «м2» — не метры


def test_parse_listing_russian_free_text():
    rows = ls.parse_listing('Гостиная 4,2 на 3,8\nспальня первая 3х3\nКомната 2:\n3,1 на 2,9\nкухня 10 м²\n')
    assert [(r['name'], r['dims_m'], r.get('area_m2')) for r in rows] == [
        ('Гостиная', (4.2, 3.8), None), ('спальня первая', (3.0, 3.0), None), ('Комната 2', (3.1, 2.9), None),
        ('кухня', None, 10.0)]
    both = ls.parse_listing('Кухня 3 на 4\nКухня 12 м²')                 # площадь той же комнаты — поле, не вторая строка
    assert len(both) == 1 and both[0]['area_m2'] == 12.0


def test_norm_name_and_room_kind_russian():
    assert ls.norm_name('Спальня 1') == ls.norm_name('спальня первая') == ls.norm_name('СПАЛЬНЯ 01')
    assert ls.room_kind('Гостиная') == ('living', None) and ls.room_kind('Lounge') == ('living', None)
    assert ls.room_kind('Bedroom Two') == ('bedroom', '2') == ls.room_kind('вторая спальня')
    assert ls.room_kind('Кухня-гостиная') == ('kitchen', None) and ls.room_kind('Kitchen/Diner')[0] == 'kitchen'
    assert ls.room_kind('Жилая комната 1') == ('room', '1') and ls.room_kind('Санузел')[0] == 'bathroom'


def test_match_russian_text_to_english_plan_by_kind():
    plan = [{'name': 'Lounge', 'dims': None}, {'name': 'Bedroom 1', 'dims': None}, {'name': 'Bedroom 2', 'dims': None},
            {'name': 'Kitchen/Diner', 'dims': (5.1, 3.05)}, {'name': 'Bathroom', 'dims': None}]
    rows = ls.parse_listing('гостиная 4,2 на 3,8\nспальня 1 3,5 на 3\nвторая спальня 3х2,7\nкухня 3,05 на 5,1\nванная 5 м²')
    got, orphans = ls.match(plan, rows)
    by = {g['name']: g for g in got}
    assert by['Lounge']['dims'] == (4.2, 3.8) and by['Lounge']['dims_src'] == 'text' and by['Lounge']['text_match'] == 'kind'
    assert by['Bedroom 1']['dims'] == (3.5, 3.0) and by['Bedroom 2']['dims'] == (3.0, 2.7)
    assert by['Kitchen/Diner']['dims_src'] == 'both'
    assert by['Bathroom']['dims'] is None and by['Bathroom']['text_area_m2'] == 5.0     # площадь — поле, стороны не выдуманы
    assert orphans == []


def test_match_russian_ambiguous_kind_not_guessed():
    plan = [{'name': 'Bedroom 1', 'dims': None}, {'name': 'Bedroom 2', 'dims': None}, {'name': 'Living Room', 'dims': None},
            {'name': 'Lounge', 'dims': None}]
    got, orphans = ls.match(plan, ls.parse_listing('спальня 3 на 3\nгостиная 4 на 5'))
    assert all(g['dims'] is None for g in got)                           # две спальни и две «гостиные» на плане — не угадываем
    assert {o['why'] for o in orphans} == {'неясно, какая комната на плане'}
    got, _ = ls.match([{'name': 'Bedroom', 'dims': None}], ls.parse_listing('спальня 3 на 3\nспальня 4 на 3'))
    assert got[0]['dims'] is None                                         # две спальни в тексте на одну — тоже нет


def test_match_english_to_english_stays_exact():
    got, orphans = ls.match([{'name': 'Lounge', 'dims': None}], ls.parse_listing('Living Room 4.20m x 3.80m'))
    assert got[0]['dims'] is None and orphans[0]['why'] == 'в тексте есть, на плане не найдено'


def test_match_russian_plan_russian_text():
    plan = [{'name': 'Жилая комната 1', 'dims': None}, {'name': 'Жилая комната 2', 'dims': None}, {'name': 'Кухня', 'dims': None}]
    got, orphans = ls.match(plan, ls.parse_listing('комната 1 4 на 4,5\nкомната 2 3 на 3,2\nкухня 10 м²'))
    by = {g['name']: g for g in got}
    assert by['Жилая комната 1']['dims'] == (4.0, 4.5) and by['Жилая комната 2']['dims'] == (3.0, 3.2)
    assert by['Кухня']['text_area_m2'] == 10.0 and by['Кухня']['text_match'] == 'name' and orphans == []


# ── общая площадь (T-20261109-26) ──

@pytest.mark.parametrize('text, m2, conv, approx', [
    ('Total area 72.5 m²', 72.5, 'gia', False),
    ('Approx. Gross Internal Area 780 sq ft', 72.46, 'gia', True),
    ('Approximate total area\n1,347 sq ft / 125.2 sq m', 125.2, 'gia', True),
    ('GIA: 90.3 sqm (973 sq ft)', 90.3, 'gia', False),
    ('Общая площадь 54,3 м²', 54.3, 'rooms', False),
    ('Квартира, площадь общая — 61 кв. м', 61.0, 'rooms', False),
    ('Lovely flat.\n780 sq ft of space', 72.46, 'gia', False),
])
def test_total_area_formats(text, m2, conv, approx):
    a = ls.total_area(text)
    assert a is not None and a['m2'] == pytest.approx(m2, abs=0.05)
    assert a['conv'] == conv and a['approx'] is approx and a['src'] == 'text'


def test_total_area_keyed_wins_and_ambiguous_is_none():
    txt = 'Lounge 3.77m x 4.20m\nBedroom 1 12.4 m²\nTotal area 72.5 m² (excl. balcony and garage)\n'
    a = ls.total_area(txt)
    assert a['m2'] == 72.5 and set(a['excl']) == {'balcon', 'garage'}
    assert ls.total_area('Bedroom 1 12.4 m²\nBedroom 2 9.8 m²') is None          # две разные площади без ключа — не угадываем
    assert ls.total_area('Total area 72.5 m²\nTotal area 95 m²') is None           # две разные «общие»
    assert ls.total_area('Lounge 3.77m x 4.20m\nKitchen 12\'3" x 6\'9"') is None  # размеры комнат — не площадь
    assert ls.total_area('') is None and ls.total_area('Total area 3 m²') is None
    assert 'area_m2_ne_sqft' in ls.total_area('Total area 72.5 m² / 900 sq ft')['flags']


def test_sheet_area_total_label_or_sum_of_parts():
    rows = [{'label': 'Farmhouse', 'm2': 213.1}, {'label': 'Garage', 'm2': 71.6}, {'label': 'Total', 'm2': 804.1}]
    assert ls.sheet_area(rows)['m2'] == 804.1 and ls.sheet_area(rows)['flags'] == []
    parts = ls.sheet_area([{'label': 'Ground Floor', 'm2': 63.9}, {'label': 'First Floor', 'm2': 61.3}])
    assert parts['m2'] == 125.2 and parts['flags'] == ['area_sum_of_parts']
    ex = ls.sheet_area([{'label': 'Approximate total area (excl. balconies)', 'm2': 90.3}])
    assert ex['excl'] == ['balcon'] and ex['approx'] and ex['src'] == 'sheet'
    assert ls.sheet_area([]) is None and ls.sheet_area([{'label': 'x', 'm2': 'n/a'}]) is None


def test_pick_area_text_and_sheet():
    t, s = ls.total_area('Total area 90 m²'), ls.sheet_area([{'label': 'Total', 'm2': 91.0}])
    a, fl = ls.pick_area(t, s)
    assert a['src'] == 'both' and a['m2'] == 90 and fl == []
    a, fl = ls.pick_area(t, ls.sheet_area([{'label': 'Total', 'm2': 120.0}]))
    assert a is None and fl == ['area_conflict']                                    # разошлись > 5 % — опоры нет, флаг
    assert ls.pick_area(None, s)[0]['src'] == 'sheet' and ls.pick_area(None, None) == (None, [])
