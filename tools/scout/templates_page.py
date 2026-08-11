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
import time

VER = str(int(time.time()))   # cache-busting: браузер владельца кэшировал старые PNG

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'services', 'planner-solver'))
from planner.models import Item, Room  # noqa: E402
from planner.template import (build_block, build_dining,  # noqa: E402
                              build_fireplace, build_media, build_quiet,
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


_OCC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', '..', 'services', 'planner-solver',
                                   'rules', 'occupancy.json')))
_CAP = _OCC['dynamic']['floor_cap_pct']
_BAND_HI = [('14-16', 16), ('17-20', 20), ('21-25', 25), ('26-30', 30),
            ('31-40', 40), ('41-50', 50), ('50+', 999)]


def min_area_for(block) -> tuple[float, float]:
    """СИСТЕМНОЕ правило (владелец 11.08): минимальная площадь комнаты для шаблона
    выводится из ДВУХ ограничений, а не назначается на глаз:

    1) ДОЛЯ ПОЛА — сумма футпринтов (мебель + ковёр как отделка) должна укладываться
       в наш кап `floor_cap_pct` band'а (occupancy.json);
    2) ФИЗИЧЕСКАЯ ВМЕСТИМОСТЬ — блок + проход 80 см по свободным сторонам; для
       ПРИСТЕННЫХ зон (глубина < 1 м: медиа, хранение, камин) дополнительно нужна
       глубина комнаты под подход/просмотр — 180 см (нижняя граница ТВ-дистанции).

    Возвращает (минимальная площадь м², занятая площадь м²)."""
    from planner.geometry import footprint
    ps = block.to_world(0, 0, 0)
    used = sum(footprint(p).area for p in ps) / 1e4
    xs = [c for p in ps for c in (footprint(p).bounds[0], footprint(p).bounds[2])]
    ys = [c for p in ps for c in (footprint(p).bounds[1], footprint(p).bounds[3])]
    bw, bd = (max(xs) - min(xs)) / 100, (max(ys) - min(ys)) / 100
    depth_need = max(bd, 1.8) if bd < 1.0 else bd      # пристенная зона → подход 1.8 м
    fit_m2 = (bw + 0.8) * (depth_need + 0.8)
    for m2 in [round(x * 0.5, 1) for x in range(16, 200)]:      # 8 … 100 м²
        band = next(b for b, hi in _BAND_HI if m2 <= hi)
        cap_hi = _CAP[band][1] / 100.0
        if used / m2 <= cap_hi and m2 >= fit_m2:
            return m2, used
    return 100.0, used


def card(name, title, block, note, gross_m2=None, pos='wall', status='v1 — активен'):
    if block is None:
        return
    auto_m2, used = min_area_for(block)
    gross_m2 = max(auto_m2, gross_m2 or 0)      # ручной порог может быть только выше
    bw, bd = _render(name, block, gross_m2, pos)
    share = used / gross_m2 * 100
    cards.append((name, f'{title} — блок {bw:.1f}×{bd:.1f} м · для комнат от '
                        f'~{gross_m2:.0f} м² (занимает {used:.1f} м², {share:.0f}% пола)',
                  note, status, gross_m2))


card('sofa_solo', 'ПРОСТОЙ: диван + столик + ковёр (v1.1)',
     build_block('compact_sectional', {'диван': SOFA_S, 'столик': TBL_S,
                                       'ковёр': RUG_S}),
     'Самый частый состав малых гостиных (52% сцен в данных ProcTHOR). Столик '
     '40–45 см от фронта, ковёр по оси под передние ножки. Работает и с угловым '
     'диваном.', gross_m2=12)

card('dining_2', 'ПРОСТОЙ: стол + 2 стула',
     build_dining({'стол обеденный': _mk('стол обеденный', 90, 80),
                   **{k: v for k, v in CHAIRS.items()}}, 2),
     'Микро-столовая для комнат до ~18 м²: два стула по длинным сторонам, '
     'задвинуты к кромке. Место для отодвигания (46–61 см) проверяют проходы.',
     gross_m2=15, pos='center')

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

card('corner_2arm', 'Угловой диван + 2 кресла (пара визави) + столик',
     build_block('sofa_2armchairs', {'диван': SOFA_C, 'кресло': ARM, 'кресло 2': ARM2,
                                     'столик': TBL_S, 'ковёр': RUG}),
     'Кресла парой напротив СВОБОДНОЙ секции (сбоку от оси экрана); столик у '
     'свободной секции с отжимом от плеча (зазор 32–50 выдержан). Если конкретный '
     'SKU-столик геометрически невозможен (напр. длинная консоль 124 см у компактного '
     'Г) — честно опускается, движок доставит его отдельно, если найдёт место.',
     gross_m2=22)

card('armchair_pair', '2 кресла (без дивана)',
     build_block('armchair_pair', {'кресло': ARM_S, 'кресло 2': ARM_S2, 'столик': TBL_S,
                                   'ковёр': _mk('ковёр', 160, 120)}),
     'Кресельный уголок самых малых гостиных: визави через столик. Порог поднят '
     'до 12 м² по правилу заполненности (замечание владельца 11.08): мебель+ковёр '
     'здесь 3.4 м² — 29% пола при 12 м², что укладывается в наш кап 40–50% и в '
     'дизайн-правило «30% (до 40% в малых)». При 10 м² с крупным ковром выходило '
     '43% — на верхней границе. Габарит блока (5.5 м²) — НЕ занятая площадь: '
     'в него входит воздух беседы и ковёр.', gross_m2=12)

card('dining_4', 'Столовая: стол + 4 стула (остров)',
     build_dining({'стол обеденный': DTBL, **{k: v for k, v in CHAIRS.items()}}, 4),
     'Стулья задвинуты к кромке (это норма; место отодвигания 46–61 см проверяется '
     'проходами). Пары по длинным сторонам. Стульев по площади: ≤18 м² — 2, '
     '≤30 — 4, больше — 6.', gross_m2=25, pos='center')

card('dining_6', 'Столовая: стол + 6 стульев',
     build_dining({'стол обеденный': _mk('стол обеденный', 180, 90),
                   **{k: v for k, v in CHAIRS.items()}}, 6),
     '4 по длинным сторонам + 2 торцевых. Для просторных гостиных (45+ м²).', gross_m2=45, pos='center')

card('two_sofas_L', 'Два дивана П-стыком + 2 кресла (v2.1)',
     build_block('two_sofas_2armchairs',
                 {'диван': _mk('диван', 230, 95), 'диван 2': _mk('диван 2', 230, 95),
                  'кресло': ARM, 'кресло 2': ARM2, 'столик': TBL, 'ковёр': RUG}),
     'Буква П (правка владельца): второй диван перпендикулярно слева, его торец '
     'от ФРОНТА главного; кресла на длинной стороне столика напротив главного; '
     'открытая сторона П — к экрану. Главный шаблон 40+ м².', gross_m2=45)

card('sofas_facing', 'Два дивана визави (v2.2, состав без ТВ)',
     build_block('sofa_facing_sofa',
                 {'диван': _mk('диван', 220, 95), 'диван 2': _mk('диван 2', 220, 95),
                  'столик': TBL, 'ковёр': RUG}),
     'Чистая беседа/камин: фронт-фронт 183–305 см через столик. С носителем ТВ '
     'в составе не применяется (честное визави несовместимо с прицелом ≤30° — '
     'там работает поштучный компромисс).', gross_m2=32)

card('sofa_4arm_U', 'U-композиция: кресла столбиками по бокам (v2.12)',
     build_block('sofa_4armchairs',
                 {'диван': SOFA, 'кресло': ARM, 'кресло 2': ARM2, 'кресло 3': ARM3,
                  'кресло 4': ARM4, 'столик': TBL, 'ковёр': RUG}, variant='u'),
     'Посадка с трёх сторон, контур открыт к фокусу; вариант выбирается '
     'автоматически, если классическая схема не встала. Столик для U — крупный '
     '(122–137×76–102, ~2/3 дивана, квадрат/круг предпочтительней) или ПАРА '
     'столиков (веб-свод; конверт подбора — этап композитора).', gross_m2=40)

card('media_solo', 'ПРОСТОЙ: ТВ-тумба соло (классика малых гостиных)',
     build_media({'тв-тумба': _mk('тв-тумба', 120, 40)}, with_flanks=False),
     'Медиа-зона малой гостиной — просто носитель у стены напротив посадки. '
     'Декор — НА тумбе (его ставит рендер), напольных акцентов в тесной комнате '
     'не добавляем: по данным майнинга их там 0.7 на комнату.')

card('sofa_pouf', 'ПРОСТОЙ: диван + пуф вместо кресла (v2 C1)',
     build_block('sofa_armchair', {'диван': SOFA_S, 'пуф': _mk('пуф', 67, 50),
                                   'столик': TBL_S, 'ковёр': RUG_S}),
     'Тесные гостиные: пуф у столика вместо кресла (правило «пуф вместо кресла» '
     'для малых площадей уже в правилах зон).')

card('bridge_chair', 'Кресло-мостик: диван к ТВ, кресло под 45° к камину (v2 B1)',
     build_block('sofa_2armchairs', {'диван': SOFA, 'кресло': ARM, 'кресло 2': ARM2,
                                     'столик': TBL, 'ковёр': RUG}, variant='bridge'),
     'Двойной фокус по веб-своду: диван смотрит на экран, одно кресло развёрнуто '
     'по диагонали — связывает медиа-зону с каминной. Выбирается автоматически, '
     'когда в составе есть и носитель ТВ, и камин.')

card('fireplace_chairs', 'Каминная зона: пара кресел по бокам камина (v2 A2)',
     build_fireplace({'камин': _mk('камин', 120, 35), 'кресло 3': _mk('кресло 3', 80, 75),
                      'кресло 4': _mk('кресло 4', 80, 75)}),
     'Канон симметрии: одинаковые кресла лицом друг к другу, камин между ними; '
     'зона безопасности от очага 61–91 см (веб-свод).')

card('quiet_zone', 'Тихая зона: 2 кресла + приставной (v2 B2, 45+ м²)',
     build_quiet({'кресло 3': _mk('кресло 3', 80, 75), 'кресло 4': _mk('кресло 4', 80, 75),
                  'приставной': _mk('приставной', 45, 45)}),
     'Вторая подзона просторных гостиных: «зона просмотра» у ТВ + «тихая зона» '
     'у камина/окна. Ставится после главной зоны, если кресла остались свободны.',
     gross_m2=45)

card('storage_wall', 'Стеллаж-стена: хранение в линию + растение (v2.4)',
     build_storage({'стеллаж': _mk('стеллаж', 90, 35), 'комод': _mk('комод', 120, 45),
                    'кашпо': _mk('кашпо', 40, 40)}),
     'Ряд вдоль одной стены: фасады в линию, зазор 8 см; живой акцент (кашпо) у '
     'торца ряда — по интернет-своду; декор НА полках ставит рендер. Не на '
     'ТВ-стене (межзонный штраф).')

card('fireplace_shelves', 'Каминная зона: камин + симметричные стеллажи (v2.5)',
     build_fireplace({'камин': _mk('камин', 120, 35),
                      'стеллаж': _mk('стеллаж', 80, 35),
                      'стеллаж 2': _mk('стеллаж 2', 80, 35)}),
     'Канон built-ins (веб-свод 11.08): симметричная пара по бокам камина, фасады '
     'в одну линию, зазор 20 см от торцов. Приоритет флангов: стеллаж×2 → '
     'стеллаж+комод → зелень. Камин смотрит в посадочную зону (межзонная связь). '
     'ИСТОЧНИК — только свод дизайнеров: в датасете ProcTHOR каминов НЕТ (0 на '
     '9013 гостиных), сверить схему данными невозможно.')

card('fireplace_plants', 'Каминная зона: камин + зелень (когда стеллажей нет)',
     build_fireplace({'камин': _mk('камин', 120, 35), 'кашпо': _mk('кашпо', 40, 40),
                      'кашпо 2': _mk('кашпо 2', 40, 40)}),
     'Фолбэк-вариант того же блока: симметричные растения вместо стеллажей. '
     'Выбирается автоматически по составу сета.')

card('media_wall_unit', 'ТВ-зона, вариант А: СТЕНКА + акценты',
     build_media({'стенка': _mk('стенка', 280, 51), 'кашпо': _mk('кашпо', 40, 40),
                  'кашпо 2': _mk('кашпо 2', 40, 40)}, max_flanks=2),
     'Стенка — сама носитель ТВ (ADR-0081, экран в центральной секции). Пара '
     'растений 25 см от торцов — ТОЛЬКО в просторных комнатах (32+ м²); в обычных '
     'ставится один акцент. Основная «красота» медиа-зоны — предметы НА полках '
     'и тумбе (в реальных сценах носитель несёт ~2.8 предмета) — их ставит рендер.')

card('media_flanks', 'ТВ-зона, вариант Б: ТВ-ТУМБА + акцент (v2.7/v2.8)',
     build_media({'тв-тумба': _mk('тв-тумба', 160, 45), 'кашпо': _mk('кашпо', 40, 40)},
                 max_flanks=1),
     'Носитель отдельным блоком; позиция — по межзонной связи (соосность с главным '
     'посадочным). ОДИН напольный акцент сбоку — по данным майнинга: напольного '
     'декора в гостиной 0.7–1.0 предмета, вплотную к тумбе он стоит редко. Торшер '
     'по своду живёт у ПОСАДКИ; мелкий декор — НА тумбе (рендер).')

card('reading_corner', 'Уголок чтения (v2.6)',
     build_reading({'кресло 3': _mk('кресло 3', 80, 75), 'торшер': _mk('торшер', 35, 35),
                    'приставной': _mk('приставной', 45, 45)}),
     'Вторая зона на остатке площади: кресло + торшер за плечом + приставной '
     'у подлокотника.')

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
    'Закрыто 11.08 — очередь пуста': [
        ('v2.5b Камин + ТВ на смежных стенах — РЕАЛИЗОВАНО',
         'Проба двойного фокуса: посадка выбирается так, чтобы впереди было место '
         'под носитель ТВ, а на смежной стене (±60°) — под камин. Отдельной '
         'карточки нет: это поведение позиционирования, а не блок.'),
        ('v3 ТВ на стене + низкая консоль — УЖЕ РАБОТАЕТ, роль не нужна',
         'Проверка каталога: консольные тумбы (150×35, h 22) уже размечены как '
         '«тв-тумба» — 8 SKU; ещё 4 идут столиками-консолями. То есть медиа-блок '
         'ставит их и сейчас; заводить отдельную роль не из чего и незачем.'),
        ('v2.9 Комод + декор сверху — покрыто существующей механикой',
         'Комод ставит движок, декор на столешницу — рендер (hosts). Блок не нужен.'),
        ('v3 Барная зона — НЕВОЗМОЖНА: в каталоге 0 товаров',
         'Проверка 28 680 товаров: барных/винных ШКАФОВ нет вовсе (есть 62 барных '
         'стула и 4 барные стойки — кухонная категория, исключена из гостиной). '
         'Вернёмся, если такие товары появятся в фидах.'),
    ],
}

BANDS = [12, 15, 22, 32, 45]     # «комната от N м²» — таб показывает всё применимое
items_html = []
for name, title, note, status, gm2 in cards:
    items_html.append(
        f"<section data-min='{gm2}'><h2>{html.escape(title)} "
        f"<small>{html.escape(status)}</small></h2>"
        f"<img src='{name}.png?v={VER}' loading='lazy'>"
        f"<p class='note'>{html.escape(note)}</p></section>")
tabs_html = "<div class='tabs'>" + ''.join(
    f"<button data-band='{b}'>комната {b} м²</button>" for b in BANDS
) + "<button data-band='all' class='on'>все шаблоны</button></div>"
tabs_js = '''<script>
(function(){
  var btns=[].slice.call(document.querySelectorAll('.tabs button'));
  var secs=[].slice.call(document.querySelectorAll('section[data-min]'));
  function apply(band){
    btns.forEach(function(b){b.classList.toggle('on', b.dataset.band===band);});
    var n=0;
    secs.forEach(function(s){
      var ok = band==='all' || parseFloat(s.dataset.min) <= parseFloat(band);
      s.style.display = ok ? '' : 'none';
      if(ok) n++;
    });
    var c=document.getElementById('cnt');
    if(c) c.textContent = band==='all'
      ? ('всего шаблонов: '+n)
      : ('применимо к комнате '+band+' м²: '+n+' шаблон(ов)');
  }
  btns.forEach(function(b){b.onclick=function(){apply(b.dataset.band);};});
  apply('all');
})();
</script>'''
queue_html = ''.join(
    f"<h3>{html.escape(zone)}</h3><ul>" +
    ''.join(f"<li><b>{html.escape(t)}</b> — {html.escape(n)}</li>" for t, n in items) +
    "</ul>"
    for zone, items in QUEUE.items())

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta http-equiv="cache-control" content="no-cache, must-revalidate">
<title>Шаблоны зон — на согласование</title>
<style>body{{margin:0;background:#fff;color:#1A1F1C;font:17px/1.55 system-ui}}
.wrap{{max-width:980px;margin:0 auto;padding:22px 14px 60px}}
h1{{font-size:23px;margin:0 0 6px}} .sub{{color:#5C655E;font-size:15px;margin-bottom:6px}}
section{{border-top:1px solid #E4E6E2;padding:18px 0}}
h2{{font-size:20px;margin:0 0 10px}} h2 small{{color:#2E7D4F;font-weight:400;font-size:15px}}
img{{max-width:100%;border:1px solid #ECEEEA;border-radius:4px}}
.note{{font-size:16px;color:#3A423C}} ul{{font-size:16px}}
.head{{margin:10px 0 4px;padding:10px 12px;border-left:3px solid #3B76A2;background:#F4F7FA;font-size:15.5px}}
.tabs{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 6px;position:sticky;top:0;
background:#fff;padding:10px 0;border-bottom:1px solid #ECEEEA;z-index:5}}
.tabs button{{font:inherit;font-size:15px;padding:7px 13px;border:1px solid #D7DBD6;
border-radius:20px;background:#fff;color:#3A423C;cursor:pointer}}
.tabs button.on{{background:#2E7D4F;border-color:#2E7D4F;color:#fff}}
#cnt{{color:#5C655E;font-size:14.5px;margin:2px 0 0}}
</style></head><body><div class="wrap">
<h1>Шаблоны зон — библиотека на согласование</h1>
<div class="head">АКТИВНЫЕ ПОВЕДЕНИЯ ПОЗИЦИОНИРОВАНИЯ (не блоки, а правила выбора
позиции): <b>v2.10 плавающая посадка</b> — в комнатах 40+ м² блок может встать не у
стены (спинка зонирует комнату; тыл проверяют проходы); <b>v2.11 узкая комната</b> —
при вытянутости ≥1.6 посадка предпочитает ПОПЕРЁК длинной оси; <b>v2.5 камин-фокус</b>
— без носителя ТВ блок ориентируется на камин; <b>камин + ТВ на смежных стенах</b> — посадка по диагонали к обоим фокусам (проба двойного фокуса); <b>узкая комната, тесно флангам</b> — кресла столбиком с одного бока (вариант выбирается автоматически); <b>межзонный слой</b> — прицел экрана
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
{tabs_html}
<p id="cnt"></p>
{''.join(items_html)}
<section data-min="0"><h2>Очередь по 6 зонам <small>ЗАКРЫТА 11.08 — библиотека полная</small></h2>{queue_html}</section>
</div>{tabs_js}</body></html>"""
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
