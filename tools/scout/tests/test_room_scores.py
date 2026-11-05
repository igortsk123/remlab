"""Оценки стиля комнат не смешиваются (T-20261105-34/2): `catalog_rules.twin_scores_sql` — товары одной комнаты
`room_catalog`, без дублей; `style_score.py --source room_catalog` берёт выборку только оттуда.
Таблицы-заглушки — sqlite в памяти (тот же SQL, что идёт в postgres), без базы и сети.
    ~/venvs/scout/bin/python tools/scout/tests/test_room_scores.py"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
from catalog_rules import twin_scores_sql  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


db = sqlite3.connect(':memory:')
db.executescript("""
create table product_style_scores (shop_mid int, external_id text, scores text, universal bool, src text,
                                   primary key (shop_mid, external_id));
create table room_catalog (shop_mid int, external_id text, room text, primary key (shop_mid, external_id, room));
insert into product_style_scores values (1, 'bed', '{"сканди": 0.9}', 0, 'llm'),       -- кровать: только спальня
                                        (1, 'hall', '{"лофт": 0.8}', 0, 'llm'),        -- обувница: только прихожая
                                        (2, 'both', '{"классика": 0.7}', 1, 'llm'),    -- шкаф-купе: обе комнаты
                                        (3, 'living', '{"минимализм": 0.6}', 0, 'llm'); -- диван: ни одной
insert into room_catalog values (1, 'bed', 'bedroom'), (1, 'hall', 'hall'), (2, 'both', 'bedroom'), (2, 'both', 'hall');
""")


def keys(room):
    return [(r[0], r[1]) for r in db.execute(twin_scores_sql(room))]


bed, hall = keys('bedroom'), keys('hall')
check('спальня видит только свои товары', sorted(bed) == [(1, 'bed'), (2, 'both')])
check('прихожая видит только свои товары', sorted(hall) == [(1, 'hall'), (2, 'both')])
check('товар обеих комнат — одна строка, не две', bed.count((2, 'both')) == 1 and hall.count((2, 'both')) == 1)
check('строка прихожей не в словаре спальни', (1, 'hall') not in bed and (1, 'bed') not in hall)
check('товар без комнаты (гостиная) — ни в одной', (3, 'living') not in bed + hall)
old = [(r[0], r[1]) for r in db.execute("select s.shop_mid, s.external_id from product_style_scores s"
                                        " join room_catalog c using (shop_mid, external_id)")]
check('контроль: прежняя выборка без комнаты смешивала (прихожая в спальне, дубль)',
      (1, 'hall') in old and old.count((2, 'both')) == 2)
try:
    twin_scores_sql("bedroom' or 1=1 --")
    check('комната — только имя, не кусок SQL', False)
except ValueError:
    check('комната — только имя, не кусок SQL', True)
src = open(os.path.join(HERE, '..', 'style_score.py'), encoding='utf-8').read()
check('style_score.py берёт оценки близнецов через twin_scores_sql(своя комната)',
      'twin_scores_sql(_RC.ROOM)' in src and 'join room_catalog c using' not in src)
sys.exit(1 if fails else 0)
