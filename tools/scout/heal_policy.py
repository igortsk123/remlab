#!/usr/bin/env python3
"""Правила автозамены товара в комплекте: журнал, карантин, лимит, защита от дребезга.

ПОЧЕМУ ЭТО НЕ ПРОСТО «НАЙТИ ЗАМЕНУ». Лечение работает каждую ночь на живом каталоге, где
наличие мигает: товар пропал, завтра вернулся. Без памяти о прошлых заменах система начинает
качать сет туда-обратно — владелец видит «изменённый сет» каждое утро и перестаёт им верить.
Поэтому решение о замене опирается на историю, а не только на текущий снимок.

ПРАВИЛА (после критики Codex 28.08):
  * менять — ТОЛЬКО по жёсткой причине (нет наличия, мёртвое фото, негодное фото, провал
    контракта, брак меша). Здоровый товар не трогаем, даже если появился «более удобный» запас;
  * замена обязана иметь ГОТОВЫЙ МЕШ — иначе «заменитель с готовым мешом» превращается в дыру
    в визуализации; лучше честно показать пробел, чем подменить втихую;
  * выбывший — в карантин: обратно он вернётся не раньше чем через QUARANTINE_DAYS, и только
    если всё это время был здоров. Автовозврата «как было» нет;
  * не больше MAX_PER_SET_PER_DAY автозамен на комплект за сутки: иначе одна ночь может
    переписать сет целиком, и человек уже не поймёт, что именно изменилось;
  * каждая замена — строкой в журнале, с причиной и версией контракта. Журнал и есть то, что
    видит человек: «вот сет, вот что в нём поменялось и почему».
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

QUARANTINE_DAYS = int(os.environ.get('HEAL_QUARANTINE_DAYS', '14'))
MAX_PER_SET_PER_DAY = int(os.environ.get('HEAL_MAX_PER_SET', '1'))
CONTRACT_VERSION = 'c1'

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

SCHEMA = """
create table if not exists set_changes (
  id bigserial primary key,
  set_id text not null,             -- стабильный id (set_identity), НЕ номер в массиве
  slot text not null,
  old_sku text,
  new_sku text,
  reason text not null,             -- out_of_stock|dead_photo|bad_photo|contract_fail|bad_mesh
  source_sha text,
  contract_version text,
  at timestamptz default now()
);
create index if not exists set_changes_set_at on set_changes (set_id, at desc);
create index if not exists set_changes_old_at on set_changes (old_sku, at desc);
"""

_QUARANTINE: set[str] | None = None
_TODAY: dict[str, int] | None = None


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def init() -> None:
    db(SCHEMA)


def _load() -> None:
    global _QUARANTINE, _TODAY
    if _QUARANTINE is not None:
        return
    try:
        init()
        _QUARANTINE = {r[0] for r in db(
            "select distinct old_sku from set_changes "
            f"where old_sku is not null and at > now() - interval '{QUARANTINE_DAYS} days'")
            if r and r[0]}
        _TODAY = {r[0]: int(r[1]) for r in db(
            "select set_id, count(*) from set_changes "
            "where at > now() - interval '1 day' group by set_id") if r and r[0]}
    except Exception:  # noqa: BLE001 — без БД лечение работает как раньше, но без защиты
        _QUARANTINE, _TODAY = set(), {}


def quarantined(sku: str) -> bool:
    """Товар недавно вынесли из сета — обратно рано, даже если он снова «здоров»."""
    _load()
    return sku in (_QUARANTINE or set())


def budget_left(set_id: str | None) -> bool:
    """Не исчерпан ли суточный лимит замен для комплекта."""
    if not set_id:
        return True
    _load()
    return (_TODAY or {}).get(set_id, 0) < MAX_PER_SET_PER_DAY


def record(set_id: str | None, slot: str, old_sku: str | None, new_sku: str | None,
           reason: str, source_sha: str | None = None) -> None:
    if not set_id:
        return                       # без стабильного id запись бесполезна: не к чему привязать
    try:
        init()
        def q(v):
            return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"
        db("insert into set_changes (set_id, slot, old_sku, new_sku, reason, source_sha, "
           f"contract_version) values ({q(set_id)}, {q(slot)}, {q(old_sku)}, {q(new_sku)}, "
           f"{q(reason)}, {q(source_sha)}, {q(CONTRACT_VERSION)})")
        if _TODAY is not None:
            _TODAY[set_id] = _TODAY.get(set_id, 0) + 1
        if _QUARANTINE is not None and old_sku:
            _QUARANTINE.add(old_sku)
    except Exception as e:  # noqa: BLE001 — журнал не должен ронять лечение, но молчать не должен
        print(f'  журнал замен недоступен: {type(e).__name__}: {str(e)[:80]}')


def affected_sets(since_hours: int = 24) -> list[str]:
    """Комплекты, изменившиеся за период — вход для точечной пересборки."""
    try:
        init()
        return [r[0] for r in db(
            "select distinct set_id from set_changes "
            f"where at > now() - interval '{since_hours} hours'") if r and r[0]]
    except Exception:  # noqa: BLE001
        return []


def report(limit: int = 30) -> None:
    init()
    rows = db("select at::date, set_id, slot, coalesce(old_sku,'—'), coalesce(new_sku,'—'), reason "
              f"from set_changes order by at desc limit {limit}")
    if not rows or rows == [['']]:
        print('замен пока не было')
        return
    print(f"{'дата':12}{'комплект':16}{'слот':16}{'причина':16}замена")
    for r in rows:
        if len(r) < 6:
            continue
        print(f'{r[0]:12}{r[1][:15]:16}{r[2][:15]:16}{r[5][:15]:16}{r[3][:22]} → {r[4][:22]}')


if __name__ == '__main__':
    report()
