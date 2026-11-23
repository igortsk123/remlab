#!/usr/bin/env python3
"""Пульс обходов директора: обход должен идти по расписанию P-070 (днём каждые 5 мин, ночью каждые 30, утренняя сводка 07:04) —
эту проверку делает код таймера, а не память сессии (T-20261123-23/1, п.5; владелец TG 2094/2114: «правила должны работать»).

Источник — журнал обходов директора: одна строка на обход, которую директор дописывает САМ в конце каждого обхода (и утренней сводки):
    <UTC ISO> obhod            — обычный обход (после него можно дописать любые слова: «plan=54 %»)
    <UTC ISO> utro             — утренняя сводка владельцу отправлена
Файл по умолчанию — ~/.local/state/remlab/obhod-direktora.log на машине директора (имя машины в код не зашито: таймер запускается там,
где директор по шапке плана). Время суток — Лондон: днём 07:00–21:00, ночью остальное.
Печатает ❗-строки и возвращает 1, если:
  • журнала нет или он пуст;  • последний обход старше `--day-max` (15) мин днём / `--night-max` (45) мин ночью;
  • после `--morning-by` (07:15) и до `--morning-until` (11:00) в журнале нет `utro` за сегодняшнюю дату по Лондону.
Тихо (код 0), если всё в порядке. `--state ФАЙЛ --dedupe-min N` — не повторять ту же ❗ чаще, чем раз в N минут (для таймера раз в 5 мин).
Запуск: `python3 tools/ops/obhod_puls.py [--log ФАЙЛ] [--now ISO] [-v]`; тест: `python -m pytest tools/ops/tests/test_obhod_puls.py -q`.
Без зависимостей (python 3.9+: zoneinfo)."""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # noqa: BLE001 — нет tzdata: зимой Лондон = UTC (запас на лето ≤ 1 ч, предупреждение ниже)
    LONDON = timezone.utc

DEFAULT_LOG = "~/.local/state/remlab/obhod-direktora.log"
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)Z?\s+(obhod|utro)\b")


def parse_iso(s: str) -> datetime:
    s = s.strip().rstrip("Z")
    fmt = "%Y-%m-%dT%H:%M:%S" if s.count(":") == 2 else "%Y-%m-%dT%H:%M"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def read_log(text: str):
    out = []
    for raw in text.split("\n"):
        m = LINE.match(raw.strip())
        if m:
            out.append((parse_iso(m.group(1)), m.group(2)))
    return out


def hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def check(entries, now: datetime, day_max=15, night_max=45, morning_by="07:15", morning_until="11:00", day_from="07:00", day_to="21:00") -> list[str]:
    """Список ❗-строк (пустой — всё в порядке). now — aware-время."""
    loc = now.astimezone(LONDON)
    mins = loc.hour * 60 + loc.minute
    day = hhmm(day_from) <= mins < hhmm(day_to)
    out = []
    if not entries:
        return ["❗ журнал обходов пуст: директор не дописывает строку после обхода"]
    last = max(t for t, _ in entries)  # утренняя сводка тоже признак жизни директора
    age = (now - last).total_seconds() / 60
    limit = day_max if day else night_max
    if age > limit:
        out.append(f"❗ обход директора не отмечен {int(age)} мин ({'днём' if day else 'ночью'} норма ≤ {limit} мин, последняя строка {last.astimezone(LONDON):%d.%m %H:%M} по Лондону)")
    if hhmm(morning_by) <= mins < hhmm(morning_until):
        today = loc.date()
        if not any(k == "utro" and t.astimezone(LONDON).date() == today for t, k in entries):
            out.append(f"❗ к {morning_by} по Лондону нет утренней сводки владельцу за {today:%d.%m}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", default=os.environ.get("OBHOD_LOG", DEFAULT_LOG))
    ap.add_argument("--now", default="", help="UTC ISO для проверки (по умолчанию — сейчас)")
    ap.add_argument("--day-max", type=int, default=15)
    ap.add_argument("--night-max", type=int, default=45)
    ap.add_argument("--morning-by", default="07:15")
    ap.add_argument("--morning-until", default="11:00")
    ap.add_argument("--state", default="", help="файл состояния для --dedupe-min")
    ap.add_argument("--dedupe-min", type=int, default=0)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    now = parse_iso(a.now) if a.now else datetime.now(timezone.utc)
    p = Path(os.path.expanduser(a.log))
    if not p.is_file():
        probs = [f"❗ журнала обходов нет ({p}): директор не дописывает строку после обхода"]
    else:
        probs = check(read_log(p.read_text(encoding="utf-8", errors="replace")), now, a.day_max, a.night_max, a.morning_by, a.morning_until)
    if not probs:
        if a.verbose:
            print("[obhod-puls] ✓ обходы идут")
        return 0
    if a.state and a.dedupe_min:
        st = Path(os.path.expanduser(a.state))
        if st.is_file() and (now.timestamp() - st.stat().st_mtime) < a.dedupe_min * 60 and st.read_text(encoding="utf-8") == "\n".join(probs):
            return 1  # то же ❗ уже сказали недавно — молчим, но код 1
        st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text("\n".join(probs), encoding="utf-8")
    print("\n".join(probs))
    return 1


if __name__ == "__main__":
    sys.exit(main())
