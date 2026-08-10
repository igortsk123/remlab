#!/usr/bin/env python3
"""Витрина шаблонов зон на согласование владельцу (заявка 10.08): каждый шаблон
инстанцируется с типовыми SKU идеалов band'а и рисуется штатным draw_plan — то, что
на странице, и есть код (planner/template.py), ручных картинок нет.

  ~/venvs/scout/bin/python templates_page.py [--publish]   # → /test/templates/
"""
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'services', 'planner-solver'))
from planner.models import Item, Room  # noqa: E402
from planner.template import (build_block, build_dining, build_media,  # noqa: E402
                              build_reading, build_storage)
from scene_build import draw_plan  # noqa: E402

OUT = os.path.expanduser('~/scout-scenes/templates-page')
os.makedirs(OUT, exist_ok=True)


def _mk(role, w, d, **kw):
    return Item(role=role, w_cm=w, d_cm=d, **kw)


def _render(name, block, gross_m2, pos='wall'):
    """Чертёж БЛОКА крупным планом (владелец 10.08: комната-рамка сбивает — на малых
    площадях блок «занимал 2/3»): рамка = габарит блока + воздух; площадь применения
    пишется текстом в заголовке. Возвращает габарит блока (Ш×Г, м)."""
    from planner.geometry import footprint
    ps0 = block.to_world(0, 0, 0)
    xs, ys = [], []
    for p in ps0:
        b = footprint(p).bounds
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
    bw, bd = max(xs) - min(xs), max(ys) - min(ys)
    pad = 55
    room = Room(width_cm=bw + 2 * pad, depth_cm=bd + 2 * pad, openings=[])
    ps = block.to_world(-min(xs) + pad, -min(ys) + pad, 0)
    png = os.path.join(OUT, f'{name}.png')
    draw_plan(room, ps, [], png, room_dims=False)
    return bw / 100, bd / 100


# типовые SKU (идеалы band'ов; конверты −20/+10% — подбор compose2)
SOFA = _mk('диван', 220, 95)
SOFA_S = _mk('диван', 180, 90)          # идеал S-band (пример владельца: ~160–180)
ARM_S = _mk('кресло', 76, 70)
ARM_S2 = _mk('кресло 2', 76, 70)
TBL_S = _mk('столик', 90, 50)
RUG_S = _mk('ковёр', 200, 140)
SOFA_C = _mk('диван', 260, 160, corner=True, corner_section_cm=95)
ARM = _mk('кресло', 85, 80)
ARM2 = _mk('кресло 2', 85, 80)
ARM3, ARM4 = _mk('кресло 3', 85, 80), _mk('кресло 4', 85, 80)
TBL = _mk('столик', 110, 60)
RUG = _mk('ковёр', 290, 200)
DTBL = _mk('стол обеденный', 140, 80)
CHAIRS = {f'стул {i}' if i > 1 else 'стул': _mk(f'стул {i}' if i > 1 else 'стул', 45, 52)
          for i in range(1, 7)}

cards = []


def card(name, title, block, note, gross_m2=22, pos='wall', status='v1 — активен'):
    if block is None:
        return
    bw, bd = _render(name, block, gross_m2, pos)
    cards.append((name, f'{title} — блок {bw:.1f}×{bd:.1f} м · для комнат от ~{gross_m2} м²',
                  note, status))


card('sofa_armchair', 'Диван + кресло (фланг)',
     build_block('sofa_armchair', {'диван': SOFA_S, 'кресло': ARM_S, 'столик': TBL_S,
                                   'ковёр': RUG_S}),
     'Кресло сбоку на уровне столика, лицом к центру; столик 40–45 см от фронта; '
     'ковёр по оси, длинной стороной вдоль дивана. Band S/M (~15–22 м²).', gross_m2=15)

card('sofa_2armchairs', 'Диван + 2 кресла (фланги)',
     build_block('sofa_2armchairs', {'диван': SOFA, 'кресло': ARM, 'кресло 2': ARM2,
                                     'столик': TBL, 'ковёр': RUG}),
     'Классика книги: кресла с двух флангов, посадка в круге беседы ≤3.96 м. '
     'Band M/L/XXL (~22 м² и выше).', gross_m2=22)

card('sofa_4armchairs', 'Диван + 4 кресла',
     build_block('sofa_4armchairs', {'диван': SOFA, 'кресло': ARM, 'кресло 2': ARM2,
                                     'кресло 3': ARM3, 'кресло 4': ARM4,
                                     'столик': TBL, 'ковёр': RUG}),
     '2 кресла флангами + пара напротив (замыкание круга). Band L/XL (~32–40 м²).', gross_m2=32)

card('corner_2arm', 'Угловой диван + 2 кресла (пара визави)',
     build_block('sofa_2armchairs', {'диван': SOFA_C, 'кресло': ARM, 'кресло 2': ARM2,
                                     'ковёр': RUG}),
     'Кресла парой напротив СВОБОДНОЙ секции (сбоку от оси экрана). Столик у '
     'компактных Г-диванов часто невозможен по клиренсам [32–50] — тогда честно '
     'опускается (каскад демоций), beam доставит если найдёт место.', gross_m2=22)

card('armchair_pair', '2 кресла (без дивана)',
     build_block('armchair_pair', {'кресло': ARM_S, 'кресло 2': ARM_S2, 'столик': TBL_S,
                                   'ковёр': RUG_S}),
     'Кресельный уголок для XS (~до 11 м²): визави через столик.', gross_m2=10)

card('dining_4', 'Столовая: стол + 4 стула (остров)',
     build_dining({'стол обеденный': DTBL, **{k: v for k, v in CHAIRS.items()}}, 4),
     'Стулья задвинуты к кромке (это норма; место отодвигания 46–61 см проверяется '
     'проходами). Пары по длинным сторонам. Стульев по площади: ≤18 м² — 2, '
     '≤30 — 4, больше — 6.', gross_m2=25, pos='center')

card('dining_6', 'Столовая: стол + 6 стульев',
     build_dining({'стол обеденный': _mk('стол обеденный', 180, 90),
                   **{k: v for k, v in CHAIRS.items()}}, 6),
     '4 по длинным сторонам + 2 торцевых. Для просторных гостиных (45+ м²).', gross_m2=45, pos='center')

card('two_sofas_L', 'Два дивана Г-стыком + 2 кресла (v2.1)',
     build_block('two_sofas_2armchairs',
                 {'диван': _mk('диван', 230, 95), 'диван 2': _mk('диван 2', 190, 90),
                  'кресло': ARM, 'кресло 2': ARM2, 'столик': TBL, 'ковёр': RUG}),
     'Торец-к-торцу (стык 10–30 см), спинки наружу; столик у главного дивана; '
     'кресла замыкают «квадрат», якорясь к столику. Главный шаблон 40+ м².',
     gross_m2=45)

card('sofas_facing', 'Два дивана визави (v2.2, состав без ТВ)',
     build_block('sofa_facing_sofa',
                 {'диван': _mk('диван', 220, 95), 'диван 2': _mk('диван 2', 200, 90),
                  'столик': TBL, 'ковёр': RUG}),
     'Чистая беседа/камин: фронт-фронт 183–305 см через столик. С носителем ТВ '
     'в составе не применяется (честное визави несовместимо с прицелом ≤30° — '
     'там работает поштучный компромисс).', gross_m2=32)

card('sofa_4arm_U', 'U-композиция: кресла столбиками по бокам (v2.12)',
     build_block('sofa_4armchairs',
                 {'диван': SOFA, 'кресло': ARM, 'кресло 2': ARM2, 'кресло 3': ARM3,
                  'кресло 4': ARM4, 'столик': TBL, 'ковёр': RUG}, variant='u'),
     'Посадка с трёх сторон, контур открыт к фокусу; вариант выбирается '
     'автоматически, если классическая схема не встала.', gross_m2=40)

card('storage_wall', 'Стеллаж-стена: хранение в линию (v2.4)',
     build_storage({'стеллаж': _mk('стеллаж', 90, 35), 'комод': _mk('комод', 120, 45)}),
     'Ряд вдоль одной стены: фасады в линию, зазор 8 см; ставится ПОСЛЕ медиа '
     '(канон порядка зон), не на ТВ-стене (межзонный штраф).', gross_m2=25)

card('media_flanks', 'Медиа-зона: носитель + фланги декора (v2.7/v2.8)',
     build_media({'тв-тумба': _mk('тв-тумба', 160, 45), 'кашпо': _mk('кашпо', 40, 40),
                  'торшер': _mk('торшер', 35, 35)}),
     'Носитель (тумба или стенка — ADR-0081) отдельным блоком; позиция — по '
     'межзонной связи (соосность с главным посадочным, дистанция по диагонали). '
     'Свободный декор — симметричными флангами 25 см от торцов.', gross_m2=22)

card('reading_corner', 'Уголок чтения (v2.6)',
     build_reading({'кресло 3': _mk('кресло 3', 80, 75), 'торшер': _mk('торшер', 35, 35),
                    'приставной': _mk('приставной', 45, 45)}),
     'Вторая зона на остатке площади: кресло + торшер за плечом + приставной '
     'у подлокотника.', gross_m2=25)

card('dining_round', 'Столовая: круглый стол + 4 стула (v2.3)',
     build_dining({'стол обеденный': _mk('стол обеденный', 100, 100),
                   **{k: v for k, v in CHAIRS.items()}}, 4),
     'Круглый/квадратный стол — по стулу с каждой стороны (через 90°).',
     gross_m2=22, pos='center')

card('dining_wall', 'Столовая у стены (стулья со стороны комнаты)',
     build_dining({'стол обеденный': DTBL, **{k: v for k, v in CHAIRS.items()}}, 4,
                  sides='front'),
     'Пристенная постановка: задняя сторона к стене, стулья с фронта и торцов. '
     'Применяется, когда остров не встал.', gross_m2=22)

# Детальная очередь по 6 зонам владельца (10.08, «жду детально план»). Порядок
# внутри v2 = порядок реализации; каждый шаг проходит приёмку 252 «0 хуже».
QUEUE = {
    '1. Зона общения / отдыха': [
        ('v2.5b Камин + ТВ на смежных стенах — уточнение поведений',
         'Посадка по диагонали к обоим фокусам; данные-правила (tv_wall_offset) уже '
         'в zones.json — осталось научить пробу двойному фокусу.'),
    ],
    '2. ТВ / медиа-зона': [
        ('v3 ТВ на стене + низкая консоль',
         'Нужна роль «консоль» в каталоге (маппинг категорий фидов) — после фидов.'),
    ],
    '4. Библиотека / хранение': [
        ('v2.9 Комод + декор сверху (зеркало/лампа)',
         'Реализовано существующей механикой (декор на столешницах ставит рендер, '
         'комод — движок); отдельный блок не требуется — карточки не будет.'),
    ],
    '6. Барная зона': [
        ('v3 Барный/винный шкаф + 2 кресла + приставной — 45+ м²',
         'Мини-зона у стены вне маршрутов; ждёт роли «барный/винный шкаф» '
         'в каталоге (заведём при следующем маппинге категорий).'),
    ],
}

items_html = []
for name, title, note, status in cards:
    items_html.append(
        f"<section><h2>{html.escape(title)} <small>{html.escape(status)}</small></h2>"
        f"<img src='{name}.png' loading='lazy'>"
        f"<p class='note'>{html.escape(note)}</p></section>")
queue_html = ''.join(
    f"<h3>{html.escape(zone)}</h3><ul>" +
    ''.join(f"<li><b>{html.escape(t)}</b> — {html.escape(n)}</li>" for t, n in items) +
    "</ul>"
    for zone, items in QUEUE.items())

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Шаблоны зон — на согласование</title>
<style>body{{margin:0;background:#fff;color:#1A1F1C;font:17px/1.55 system-ui}}
.wrap{{max-width:980px;margin:0 auto;padding:22px 14px 60px}}
h1{{font-size:23px;margin:0 0 6px}} .sub{{color:#5C655E;font-size:15px;margin-bottom:6px}}
section{{border-top:1px solid #E4E6E2;padding:18px 0}}
h2{{font-size:20px;margin:0 0 10px}} h2 small{{color:#2E7D4F;font-weight:400;font-size:15px}}
img{{max-width:100%;border:1px solid #ECEEEA;border-radius:4px}}
.note{{font-size:16px;color:#3A423C}} ul{{font-size:16px}}
.head{{margin:10px 0 4px;padding:10px 12px;border-left:3px solid #3B76A2;background:#F4F7FA;font-size:15.5px}}
</style></head><body><div class="wrap">
<h1>Шаблоны зон — библиотека на согласование</h1>
<div class="head">АКТИВНЫЕ ПОВЕДЕНИЯ ПОЗИЦИОНИРОВАНИЯ (не блоки, а правила выбора
позиции): <b>v2.10 плавающая посадка</b> — в комнатах 40+ м² блок может встать не у
стены (спинка зонирует комнату; тыл проверяют проходы); <b>v2.11 узкая комната</b> —
при вытянутости ≥1.6 посадка предпочитает ПОПЕРЁК длинной оси; <b>v2.5 камин-фокус</b>
— без носителя ТВ блок ориентируется на камин; <b>межзонный слой</b> — прицел экрана
считается по ЛУЧШЕМУ из диванов группы (компаньон визави легально смотрит от ТВ).</div>
<p class="sub">Каждая схема отрисована КОДОМ шаблона (planner/template.py) с типовыми
габаритами — ручных картинок нет. Внутренняя геометрия запечена по книге: столик
40–45 см от фронта; круг беседы ≤3.96 м; ковёр по оси (крупный — под передние ножки,
малый — под столик); стулья задвинуты к столу. Подбор конкретной мебели — по
слот-конвертам −20%/+10% от идеала площади.</p>
<div class="head">ЗОНЫ РАЗДЕЛЬНЫ (решение владельца): каждый шаблон описывает ТОЛЬКО
свою зону; связи между зонами (диван ↔ экран: дистанция по диагонали, прицел ≤30°;
проходы между зонами ≥91) — отдельный МЕЖЗОННЫЙ слой правил, он уже в движке.
Позицию и поворот блока выбирает солвер с учётом межзонных правил (например,
напротив посадки должно остаться место для ТВ-зоны — но сама ТВ-зона ставится
своим блоком). Блок не встал в геометрию — прежний поштучный перебор (страховка
«0 хуже»). Замечания пишите по названию шаблона.</div>
{''.join(items_html)}
<section><h2>Очередь по всем 6 зонам <small>согласовать состав; реализация после приёмки v1</small></h2>{queue_html}</section>
</div></body></html>"""
open(os.path.join(OUT, 'index.html'), 'w').write(page)
print(f'OK: {len(cards)} шаблонов → {OUT}')
if '--publish' in sys.argv:
    subprocess.run(['bash', '-c',
                    f'cd {os.path.dirname(OUT)} && tar czf /tmp/tpl-page.tgz templates-page/ && '
                    'scp -q /tmp/tpl-page.tgz root@89.167.127.0:/tmp/ && '
                    'ssh root@89.167.127.0 "rm -rf /opt/remlab/test/templates && '
                    'mkdir -p /opt/remlab/test/templates && '
                    'tar xzf /tmp/tpl-page.tgz -C /tmp/ --overwrite && '
                    'mv /tmp/templates-page/* /opt/remlab/test/templates/ && '
                    'rm -rf /tmp/templates-page /tmp/tpl-page.tgz" && rm /tmp/tpl-page.tgz'],
                   check=True)
    print('опубликовано: /test/templates/')
