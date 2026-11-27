"""Ручная строка карантина `mesh_quarantine.py --manual` (T-20261127-175/brovis, слово владельца TG 3673).
Без Postgres и сети: таблицы — в памяти sqlite (те же SQL-тексты: insert … on conflict, `room_bindings.hard_sql()`), `now()` подставлена.
У каждой проверки — отрицательный контроль (сломал → красное).
    python3 tools/scout/tests/test_mesh_quarantine_manual.py"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'salad')]
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_mesh_quarantine_manual')

import mesh_quarantine as MQ  # noqa: E402
import room_bindings as RB  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


SHA_A, SHA_B = 'a1' * 32, 'b2' * 32          # полные 64 знака; в таблице карантина — первые 16
SKU_A, SKU_B, SKU_C = 'shop:100', 'shop:200', 'shop:300'


def fresh(swallow_writes=False):
    """База в памяти: ревизии (A, B; у C моделей нет) и пустой карантин → (db(sql), соединение)."""
    con = sqlite3.connect(':memory:')
    con.create_function('now', 0, lambda: '2026-11-27 17:00:00')
    con.executescript("""
        create table asset_revisions (sku text, glb_sha text, status text, updated text);
        create table mesh_quarantine (sku text not null, glb_sha text not null, prev_status text not null, axis text, threshold numeric not null,
            decision text, comment text, decided_at text, reasons text, metric_version integer not null default 1, primary key (sku, glb_sha));
        insert into asset_revisions values ('shop:100', '%s', 'generated', '2026-11-27 10:00:00');
        insert into asset_revisions values ('shop:100', 'ffff0000ffff0000', 'accepted', '2026-11-01 10:00:00');
        insert into asset_revisions values ('shop:200', '%s', 'accepted', '2026-11-27 11:00:00');
        insert into asset_revisions values ('shop:300', null, 'generated', '2026-11-27 12:00:00');
    """ % (SHA_A, SHA_B))

    def db(sql):
        s = sql.strip()
        if s.lower().startswith('select'):
            return [['' if v is None else str(v) for v in r] for r in con.execute(s).fetchall()]
        if swallow_writes:
            return []
        con.executescript(s)
        return []
    return db, con


def hard(con):
    return {r[0] for r in con.execute(f"select sku from mesh_quarantine where {RB.hard_sql()}")}


def rows(con):
    return con.execute('select sku, glb_sha, prev_status, decision, comment, reasons from mesh_quarantine order by sku').fetchall()


REASON = 'владелец: лапа основания доской, рычаг пропал'

# 1. строка пишется: glb_sha16 текущей ревизии (самой свежей), причина, решение
db, con = fresh()
rc = MQ.manual(SKU_A, 'reject', REASON, dbf=db)
r = rows(con)
check('ручная строка пишется: rc 0, одна строка, glb_sha — 16 знаков САМОЙ СВЕЖЕЙ ревизии, решение reject, причина в comment, reasons=manual',
      rc == 0 and len(r) == 1 and r[0][:2] == (SKU_A, SHA_A[:16]) and r[0][3] == 'reject' and r[0][4] == REASON and r[0][5] == 'manual', r)
check('prev_status — статус текущей ревизии (generated)', r and r[0][2] == 'generated', r)
check('hard_sql её вычитает: товар A в жёстком карантине, B — нет', hard(con) == {SKU_A}, hard(con))
check('таблицу ревизий строка не трогает', con.execute("select count(*) from asset_revisions where status = 'quarantine' or status = 'owner_reject'").fetchone()[0] == 0)

# 2. повтор не дублирует
rc2 = MQ.manual(SKU_A, 'reject', REASON, dbf=db)
check('повтор не дублирует: rc 0, по-прежнему одна строка', rc2 == 0 and len(rows(con)) == 1, rows(con))
rc3 = MQ.manual(SKU_B, 'reject', REASON, dbf=db)
check('второй товар — вторая строка (всего 2), оба в жёстком карантине', rc3 == 0 and len(rows(con)) == 2 and hard(con) == {SKU_A, SKU_B}, rows(con))

# 3. нет причины / плохие аргументы → отказ ≠ 0, ничего не пишет
for name, args in (('без причины', (SKU_A, 'reject', '')), ('причина из пробелов', (SKU_A, 'reject', '   ')),
                   ('решение accept вручную', (SKU_A, 'accept', REASON)), ('решение не из списка', (SKU_A, 'xyz', REASON)),
                   ('sku без «:»', ('abc', 'reject', REASON)), ('пустой sku', ('', 'reject', REASON))):
    d2, c2 = fresh()
    rc = MQ.manual(*args, dbf=d2)
    check(f'{name} → отказ rc ≠ 0 и строки нет', rc != 0 and rows(c2) == [], (rc, rows(c2)))

# 4. нет модели / нет БД → ≠ 0 и причина (не 0)
d2, c2 = fresh()
check('у товара нет ревизии с моделью → rc 3, строки нет', MQ.manual(SKU_C, 'reject', REASON, dbf=d2) == 3 and rows(c2) == [])
check('товара нет в ревизиях вовсе → rc 3', MQ.manual('shop:999', 'reject', REASON, dbf=d2) == 3)


def boom(sql):
    raise RuntimeError('psql: connection refused')


check('базы нет (psql упал) → rc 4, а не 0', MQ.manual(SKU_A, 'reject', REASON, dbf=boom) == 4)

# 5. --dry: читает, печатает, не пишет
d2, c2 = fresh()
check('--dry: rc 0 и строки в таблице нет', MQ.manual(SKU_A, 'reject', REASON, dry=True, dbf=d2) == 0 and rows(c2) == [])

# 6. отрицательный контроль: «запись убрана» → товар вернулся в выборку; «запись молча не легла» → rc ≠ 0
con.execute("delete from mesh_quarantine where sku = ?", (SKU_A,))
check('ОТРИЦ.: строку A убрали → A вернулся (hard_sql его больше не вычитает), B по-прежнему вычтен', hard(con) == {SKU_B}, hard(con))
d3, c3 = fresh(swallow_writes=True)
rc = MQ.manual(SKU_A, 'reject', REASON, dbf=d3)
check('ОТРИЦ.: запись молча не легла (БД проглотила insert) → rc ≠ 0, а не «записано»', rc != 0 and rows(c3) == [] and hard(c3) == set(), rc)

# 7. чужое решение не перетираем; мягкая строка (без решения) становится решением
d4, c4 = fresh()
c4.execute("insert into mesh_quarantine (sku, glb_sha, prev_status, threshold, decision, reasons) values (?, ?, 'accepted', 0, 'accept', 'grey_top')", (SKU_A, SHA_A[:16]))
rc = MQ.manual(SKU_A, 'reject', REASON, dbf=d4)
check('решение владельца «принять» на тот же GLB не перетирается: rc ≠ 0, остаётся accept, A не в жёстком', rc != 0 and rows(c4)[0][3] == 'accept' and hard(c4) == set(), rows(c4))
d5, c5 = fresh()
c5.execute("insert into mesh_quarantine (sku, glb_sha, prev_status, threshold, decision, reasons) values (?, ?, 'generated', 0, null, 'grey_top')", (SKU_A, SHA_A[:16]))
check('до ручной строки серая крышка (decision null, grey_top) — МЯГКАЯ, A не вычтен', hard(c5) == set())
rc = MQ.manual(SKU_A, 'reject', REASON, dbf=d5)
check('мягкая строка → ручная reject: одна строка, ЖЁСТКАЯ (вычтен), причина manual', rc == 0 and len(rows(c5)) == 1 and rows(c5)[0][3] == 'reject' and rows(c5)[0][5] == 'manual' and hard(c5) == {SKU_A}, rows(c5))
d6, c6 = fresh()
c6.execute("insert into mesh_quarantine (sku, glb_sha, prev_status, threshold, decision, reasons) values (?, ?, 'accepted', 0, 'auto_release_v2', 'proportion')", (SKU_A, SHA_A[:16]))
check('автоснятие замера (auto_release_*) решением не считается — ручная строка его заменяет', MQ.manual(SKU_A, 'reject', REASON, dbf=d6) == 0 and rows(c6)[0][3] == 'reject' and hard(c6) == {SKU_A})

# 8. в коде нет номеров товаров; страница разбора знает причину manual
src = open(os.path.join(HERE, '..', 'mesh_quarantine.py'), encoding='utf-8').read()
check('в mesh_quarantine.py нет номеров товаров Брувиса (sku — только аргументом)', '16786625495984216921' not in src and '5133342355912879939' not in src)
check('у причины manual есть текст для страницы разбора', 'manual' in MQ.REASON_TEXT)
check('CLI: --manual без причины → код ≠ 0 (запуск скрипта)', os.system(f'{sys.executable} {os.path.join(HERE, "..", "mesh_quarantine.py")} --manual shop:1 --decision reject > /dev/null 2>&1') != 0)

print(f'\nИТОГ: ошибок {fails}')
sys.exit(1 if fails else 0)
