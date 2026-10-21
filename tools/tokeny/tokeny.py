#!/usr/bin/env python3
"""Учёт токенов Claude Code по задачам и сегментам (план `.memory_bank/plans/uchet-tokenov.md`).

Журналы Claude Code (`~/.claude/projects/<проект>/<сессия>.jsonl`, `<сессия>/subagents/*.jsonl`)
только читаются. Ответ модели — строка `assistant` с `message.usage`. Повторы одной пары
`(message.id, requestId)` (потоковая запись, копия истории при перезапуске сессии) считаются один
раз: числа — последней строки, время — первой; строки без обоих ключей не склеиваются. Непустой
`usage.iterations[]` — основной источник чисел, верхний usage — запасной, вместе не складываются.

Сегменты: планирование · реализация · проверка · исправления · прочее · не размечено. Разметка —
метки в первой строке сообщений между сессиями `[роль] <ID>/<цикл> · <фаза>` и журнал фаз ведущего
`data/logs/tokeny/fazy.tsv` (`tools/tokeny/faza`). Ведущий: пришёл `отчёт`/`вопрос` → проверка
этого ID; ушли `задание`/`правки`/`принято` или пришло событие другой задачи → фаза закрыта; через
2 ч после последнего события — не размечено. Исполнитель: ход относится к последнему полученному
или отправленному им сообщению с ID, приёмка задачу не переключает (цикл 1 — реализация, ≥2 —
исправления); простой больше 2 ч сбрасывает разметку до
следующего сообщения. Переделки делятся по тому, кто запросил: цикл, открытый меткой `правки`, —
исправления (проверка ведущего); меткой `доработка` — доработка (владелец), куда входят и ходы
ведущего от сообщения владельца (Telegram, терминал) до постановки и перепроверка этого цикла.
Субагент наследует сегмент вызвавшего хода по `meta.json → toolUseId` (и вложенные); `verify`
у ведущего — проверка, `opus-implementer` — по метке задания.
`--priblizitelno` — для дней до меток: ID ищется в первой строке свободным поиском, цикл — по
тексту или счёту «задание/правки» исполнителю, планирование ведущего — перед первым заданием по
новому ID, доработка — правки цикла ≥2, когда после отчёта исполнителя писал владелец; такие
строки помечены. Короткий ID («6a-f») дополняется до полного по хвосту, если кандидат один.

Взвешенные токены — ценовой эквивалент API (ввод 1, кэш-запись 5 мин 1,25, 1 ч 2, кэш-чтение 0,1,
вывод 5), не доля лимита подписки. Долю недельного лимита оценивает журнал statusline
`~/.claude/usage-log.jsonl` (только чтение): прирост `seven_day.used_percentage` между соседними
точками делится между ответами всех сессий учётки на этой машине (все проекты) пропорционально
взвешенным токенам; смена `resets_at` — новое окно. Сутки — по Лондону.

    python3 tools/tokeny/tokeny.py --proekt tamara --s 2026-10-19 --po 2026-10-21 --priblizitelno
    python3 tools/tokeny/tokeny.py --proekt remlab --json /tmp/remlab-algor.json
    python3 tools/tokeny/tokeny.py --proekt remlab --sobrat a.json b.json --s 2026-10-21
    python3 tools/tokeny/tokeny.py --proekt tamara --svodka

Вывод в stdout/stderr — результат командной строки (путь отчёта, сводка), а не отладка.
"""

from __future__ import annotations

import argparse
import bisect
import itertools
import json
import re
import socket
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SKHEMA = "tokeny/1"
CHISLA = ("vvod", "kesh_5m", "kesh_1h", "kesh_chtenie", "vyvod")
SPRAVOCHNO = ("thinking", "web_search", "web_fetch", "iteracii")
VESA = {"vvod": 1.0, "kesh_5m": 1.25, "kesh_1h": 2.0, "kesh_chtenie": 0.1, "vyvod": 5.0}
SEGMENTY = ("planirovanie", "realizaciya", "proverka", "ispravleniya", "dorabotka", "prochee",
            "ne_razmecheno")
NAZVANIE = {"planirovanie": "планирование", "realizaciya": "реализация", "proverka": "проверка",
            "ispravleniya": "исправления (проверка ведущего)", "dorabotka": "доработка (владелец)",
            "prochee": "прочее", "ne_razmecheno": "не размечено"}
ROLI = {"vedushchiy": "ведущий", "ispolnitel": "исполнитель", "neizvestno": "неизвестно"}
FAZY = ("план", "проверка", "доработка", "прочее")  # отметки `tools/tokeny/faza`
OKNO = timedelta(hours=2)
DOPUSK_OKNA = 3600  # с: `resets_at` одного окна лимита у разных сессий
POROG_SBROSA = 5.0  # п.п.: падение больше разброса устаревших показаний (±2) — сброс лимита
KOREN_REPO = Path(__file__).resolve().parents[2]
METKA = re.compile(r"^\[[^\]\n]{1,60}\]\s+"
                   r"([A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*)/(\d+)"
                   r"\s+·\s+(задание|отчёт|правки|доработка|принято|вопрос)(?!\w)")
PRIBL_ID = re.compile(r"(?<![\w/.-])(T-\d{8}-\d{2}(?:/[A-Za-z0-9-]+)*"
                      r"|[A-Za-z0-9]+-[A-Za-z0-9-]*(?:/[A-Za-z0-9-]+)+)(?![\w/.-])")
CIKL = re.compile(r"цикл\s*(\d+)", re.IGNORECASE)
PRIEMKA = r"(?:приня(?:т|то|та)|PASS|закрыт[оа]?)(?!\w)"
RYADOM = r"[\s`'\"«»*—–:-]*"  # между ID и словом приёмки — только пробелы, кавычки, тире
PRINYATO_POSLE = re.compile(RYADOM + PRIEMKA, re.IGNORECASE)
PRINYATO_DO = re.compile(r"(?<!\w)" + PRIEMKA + RYADOM + "$", re.IGNORECASE)
BEZ_ID = "без ID"  # приблизительный режим: сообщение владельца или соседа без ID задачи
PODPIS = re.compile(r"^\[([^\]\n]{1,60})\]")
VEDUSCHIY = re.compile(r"lead|ведущ|главн", re.IGNORECASE)
ISPOLNITEL = re.compile(r"worker|рабоч|исполн|implementer", re.IGNORECASE)
PRAVKI = re.compile(r"правк|changes", re.IGNORECASE)
CHANGES = re.compile(r"changes\s+required", re.IGNORECASE)
OTCHET_BEZ_ID = re.compile(r"^(?:\[[^\]\n]{1,60}\]\s*)?claude-[a-z0-9.-]+\s*$")  # формат отчёта
MESYACY = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
           "октября", "ноября", "декабря")
DNI = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")

Metka = tuple[str, str | None, int | None, bool]  # сегмент, задача, цикл, приблизительно
NE_RAZMECHENO: Metka = ("ne_razmecheno", None, None, False)


# ── чтение журналов ──────────────────────────────────────────────────────────────────────────

def slovar(v: object) -> dict[str, object]:
    return v if isinstance(v, dict) else {}


def chislo(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def vremya_iz(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def zapisi(put: Path) -> Iterator[dict[str, object]]:
    """Строки журнала; недописанная строка живого журнала пропускается."""
    with put.open(encoding="utf-8", errors="replace") as f:
        for stroka in f:
            try:
                z = json.loads(stroka)
            except ValueError:
                continue
            if isinstance(z, dict):
                yield z


def schitat_usage(u: dict[str, object]) -> dict[str, int]:
    """Числа ответа: непустой `iterations[]` — основной источник, верхний usage — запасной."""
    it = u.get("iterations")
    chasti = [slovar(e) for e in it] if isinstance(it, list) and it else [u]
    r = dict.fromkeys(CHISLA + SPRAVOCHNO, 0)
    for c in chasti:
        r["vvod"] += chislo(c.get("input_tokens"))
        r["kesh_chtenie"] += chislo(c.get("cache_read_input_tokens"))
        r["vyvod"] += chislo(c.get("output_tokens"))
        vsego = chislo(c.get("cache_creation_input_tokens"))
        k1h = chislo(slovar(c.get("cache_creation")).get("ephemeral_1h_input_tokens"))
        r["kesh_1h"] += min(k1h, vsego)
        r["kesh_5m"] += vsego - min(k1h, vsego)  # остаток — 5 мин: две части дают итог записи
    r["thinking"] = chislo(slovar(u.get("output_tokens_details")).get("thinking_tokens"))
    st = slovar(u.get("server_tool_use"))
    r["web_search"] = chislo(st.get("web_search_requests"))
    r["web_fetch"] = chislo(st.get("web_fetch_requests"))
    r["iteracii"] = len(it) if isinstance(it, list) else 0
    return r


@dataclass(slots=True)
class Stroka:
    """Один ответ модели после склейки повторов."""

    sessiya: str
    fayl: str
    msg_id: str | None
    req_id: str | None
    uuid: str
    vremya: datetime
    model: str
    chisla: dict[str, int]
    rol: str = "neizvestno"
    zadacha: str | None = None
    cikl: int | None = None
    segment: str = "ne_razmecheno"
    priblizitelno: bool = False
    limit: float = 0.0  # оценка: п.п. недельного лимита учётки
    mashina: str = ""  # `istochnik` выгрузки при --sobrat: у машин разные учётки

    def vzveshennye(self) -> float:
        return sum(self.chisla[k] * VESA[k] for k in CHISLA)

    def razmetit(self, rol: str, m: Metka) -> None:
        self.rol = rol
        self.segment, self.zadacha, self.cikl, self.priblizitelno = m


@dataclass(frozen=True, slots=True)
class Sobytie:
    """Метка сообщения (`vhod`/`ishod`) или отметка фазы (`faza`)."""

    vremya: datetime
    vid: str
    faza: str
    id: str | None
    cikl: int | None
    priblizitelno: bool = False


@dataclass(slots=True)
class Fayl:
    put: Path
    sessiya: str
    otvety: list[Stroka] = field(default_factory=list)
    # время, vhod|ishod, первая строка сообщения
    soobscheniya: list[tuple[datetime, str, str]] = field(default_factory=list)
    # id вызова Agent → время, тип субагента, первая строка задания
    vyzovy: dict[str, tuple[datetime, str, str]] = field(default_factory=dict)
    vladelec: list[datetime] = field(default_factory=list)  # владелец: Telegram, терминал
    imena: set[str] = field(default_factory=set)
    podpisi: Counter[str] = field(default_factory=Counter)


def pervaya(tekst: object) -> str:
    return tekst.strip().split("\n", 1)[0] if isinstance(tekst, str) else ""


def prochitat(put: Path, sessiya: str) -> Fayl:
    """Ответы (повторы склеены), сообщения между сессиями, вызовы Agent, имя сессии.

    Итог сжатия контекста и прочий текст событиями не считаются: входящие — только
    `origin.kind=peer` (в т.ч. доставленные в очередь, `attachment.origin`), исходящие — только
    вызов `SendMessage`.
    """
    f = Fayl(put, sessiya)
    po_klyuchu: dict[tuple[str, str], int] = {}
    uvideno: set[str] = set()
    for z in zapisi(put):
        tip = z.get("type")
        if tip in ("agent-name", "custom-title"):
            f.imena.add(str(z.get("agentName") or z.get("customTitle") or ""))
        t = vremya_iz(z.get("timestamp"))
        if t is None:
            continue
        origin = slovar(z.get("origin")) or slovar(slovar(z.get("attachment")).get("origin"))
        if origin.get("kind") == "human" or (origin.get("kind") == "channel"
                                             and "telegram" in str(origin.get("server"))):
            f.vladelec.append(t)
        if origin.get("kind") == "peer":
            telo = pervaya(origin.get("body"))
            k = f"vhod:{origin.get('msg_id') or (t.isoformat() + telo)}"
            if k not in uvideno:
                uvideno.add(k)
                f.soobscheniya.append((t, "vhod", telo))
        if tip != "assistant":
            continue
        m = slovar(z.get("message"))
        soderzhimoe = m.get("content")
        for x in soderzhimoe if isinstance(soderzhimoe, list) else []:
            c = slovar(x)
            vvod = slovar(c.get("input"))
            k = f"ishod:{c.get('id')}"
            if c.get("type") != "tool_use" or k in uvideno:
                continue
            uvideno.add(k)
            if c.get("name") == "SendMessage":
                stroka = pervaya(vvod.get("message"))
                f.soobscheniya.append((t, "ishod", stroka))
                if p := PODPIS.match(stroka):
                    f.podpisi[p.group(1)] += 1
            elif c.get("name") in ("Agent", "Task"):
                f.vyzovy[str(c.get("id"))] = (t, str(vvod.get("subagent_type") or ""),
                                              pervaya(vvod.get("prompt")))
        if isinstance(m.get("usage"), dict):
            dobavit_otvet(f, z, m, t, po_klyuchu)
    return f


def dobavit_otvet(f: Fayl, z: dict[str, object], m: dict[str, object], t: datetime,
                  po_klyuchu: dict[tuple[str, str], int]) -> None:
    msg, req = m.get("id"), z.get("requestId")
    s = Stroka(f.sessiya, f.put.name, msg if isinstance(msg, str) else None,
               req if isinstance(req, str) else None, str(z.get("uuid") or ""), t,
               str(m.get("model") or ""), schitat_usage(slovar(m.get("usage"))))
    if s.msg_id is None or s.req_id is None:
        f.otvety.append(s)
        return
    k = (s.msg_id, s.req_id)
    if k in po_klyuchu:
        staraya = f.otvety[po_klyuchu[k]]
        s.vremya, s.uuid = staraya.vremya, staraya.uuid
        f.otvety[po_klyuchu[k]] = s
    else:
        po_klyuchu[k] = len(f.otvety)
        f.otvety.append(s)


def klyuch(s: Stroka) -> tuple[str, ...]:
    """Один ответ API: пара `(message.id, requestId)`; без неё — сама строка журнала."""
    if s.msg_id is not None and s.req_id is not None:
        return (s.msg_id, s.req_id)
    return ("", s.sessiya, s.fayl, s.uuid)


def bez_povtorov(stroki: list[Stroka]) -> list[Stroka]:
    vidno: set[tuple[str, ...]] = set()
    itog: list[Stroka] = []
    for s in stroki:
        if (k := klyuch(s)) not in vidno:
            vidno.add(k)
            itog.append(s)
    return itog


# ── разметка ─────────────────────────────────────────────────────────────────────────────────

Karta = dict[str, str | None]  # хвост ID → полный ID (None — кандидатов несколько)


def razdelit_cikl(ident: str) -> tuple[str, int | None]:
    if re.search(r"/\d+$", ident):
        ident, nomer = ident.rsplit("/", 1)
        return ident, int(nomer)
    return ident, None


def karta_id(fayly: list[Fayl]) -> Karta:
    """Полные ID (с «/») из первых строк сообщений и вызовов Agent всех сессий проекта."""
    polnye: set[str] = set()
    for f in fayly:
        for stroka in [s for _, _, s in f.soobscheniya] + [s for _, _, s in f.vyzovy.values()]:
            if m := METKA.match(stroka):
                polnye.add(m.group(1))
            polnye.update(razdelit_cikl(x)[0] for x in PRIBL_ID.findall(stroka))
    karta: Karta = {}
    for ident in sorted(x for x in polnye if "/" in x):
        hvost = ident.rsplit("/", 1)[1]
        karta[hvost] = ident if karta.get(hvost, ident) == ident else None
    return karta


def polnyy_id(ident: str, karta: Karta) -> tuple[str, bool]:
    """Короткий ID («6a-f») → полный по хвосту, если кандидат ровно один; и признак замены."""
    if "/" not in ident and (polnyy := karta.get(ident)) is not None:
        return polnyy, True
    return ident, False


def pribl_sobytie(t: datetime, vid: str, stroka: str, rol: str,
                  cikly: dict[str, int], karta: Karta) -> Sobytie:
    """Сообщение без метки: ID свободным поиском (регистр любой, короткий — дополняется); цикл —
    наибольший из «цикл N» и `/N` этой задачи, иначе по счёту «задание/правки» исполнителю.
    Исполнителю: цикл ≥2 или CHANGES REQUIRED — правки, явный цикл 1 — задание. Приёмка — слово
    «принят»/PASS/«закрыт» вплотную к ID («volna-7/s принят»; «A11-s принят» в задании A11-f —
    не приёмка); нет ID — событие `без ID`."""
    p = PRIBL_ID.search(stroka)
    if p is None:
        return Sobytie(t, vid, BEZ_ID, None, None, True)
    ident = polnyy_id(razdelit_cikl(p.group(1))[0], karta)[0]
    nomera = [int(c) for c in CIKL.findall(stroka)]
    for x in PRIBL_ID.findall(stroka):
        drugoy, n = razdelit_cikl(x)
        if n is not None and polnyy_id(drugoy, karta)[0] == ident:
            nomera.append(n)
    cikl = max(nomera) if nomera else None
    novyy = ident not in cikly
    ispolnitelyu = (vid == "ishod") == (rol == "vedushchiy")
    priemka = (PRINYATO_POSLE.match(stroka, p.end()) is not None
               or PRINYATO_DO.search(stroka[:p.start()]) is not None)
    if ispolnitelyu and priemka:
        faza = "принято"
    elif ispolnitelyu:
        pravki = (not novyy and PRAVKI.search(stroka) is not None if cikl is None
                  else cikl >= 2 or (not novyy and CHANGES.search(stroka) is not None))
        faza = "правки" if pravki else "задание"
        if pravki and cikl is not None and cikl < 2:  # «X/1 — CHANGES REQUIRED»
            cikl = max(cikl, cikly.get(ident, 0)) + 1
    else:
        faza = "отчёт"
    if cikl is None:
        cikl = cikly.get(ident, 0) + 1 if novyy or faza == "правки" else cikly[ident]
    return Sobytie(t, vid, faza, ident, cikl, True)


def posle(sob: list[Sobytie], t: datetime) -> datetime:
    """Не раньше последнего события сессии: выведенная фаза не перекрывает чужие события."""
    return max(t, sob[-1].vremya + timedelta(microseconds=1)) if sob else t


def razobrat_metki(f: Fayl, priblizitelno: bool, rol: str,
                   karta: Karta | None = None) -> list[Sobytie]:
    """Точные метки; в приблизительном режиме — ещё ID из первой строки и счёт циклов.

    Короткий ID дополняется до полного по `karta` (такое событие помечено приблизительным).
    Ведущий: `доработка` по точной метке начинается с последнего сообщения владельца перед ней
    (≤ 2 ч). Приблизительно — см. `postavka`; сообщение без ID (владелец, сосед) — `без ID`, то есть
    прочее до следующего события с ID. Текст итога сжатия событием не бывает (см. `prochitat`).
    """
    karta = karta or {}
    sob: list[Sobytie] = []
    cikly: dict[str, int] = {}
    otchety: dict[str, datetime] = {}
    otchet_bez_id: datetime | None = None  # отчёт, первая строка которого — только ID модели
    vladelec = sorted(f.vladelec)
    for t, vid, stroka in sorted([*f.soobscheniya, *((tv, "vladelec", "") for tv in vladelec)]):
        m = METKA.match(stroka) if vid != "vladelec" else None
        e: Sobytie | None = None
        if m:
            ident, dopolnen = polnyy_id(m.group(1), karta)
            e = Sobytie(t, vid, m.group(3), ident, int(m.group(2)), dopolnen)
        elif priblizitelno:
            e = pribl_sobytie(t, vid, stroka, rol, cikly, karta)
        if e is None or e.id is None:
            if e is not None and rol == "vedushchiy":
                sob.append(e)
                if vid == "vhod" and OTCHET_BEZ_ID.match(stroka):
                    otchet_bez_id = t
            continue
        ident = e.id
        if rol == "vedushchiy" and vid == "ishod":
            otchet = otchety.get(ident)
            if otchet is not None and otchet_bez_id is not None:
                otchet = max(otchet, otchet_bez_id)
            e = postavka(sob, e, m is not None, vladelec, otchet, ident not in cikly)
        if vid == "vhod" and e.faza == "отчёт":
            otchety[ident] = t
        cikly[ident] = e.cikl or 1
        sob.append(e)
    return sorted(sob, key=lambda e: e.vremya)


def postavka(sob: list[Sobytie], e: Sobytie, tochno: bool, vladelec: list[datetime],
             otchet: datetime | None, novyy: bool) -> Sobytie:
    """Исходящее ведущего с ID; фазы задним числом дописываются в `sob`.

    Приблизительно: `правки` цикла ≥2, перед которыми после прошлого отчёта исполнителя по этой
    задаче писал владелец, — `доработка` (с первого такого сообщения, ≤ 2 ч); первое задание
    цикла 1 по новому ID — планирование до 2 ч назад, но не раньше прошлого события с ID.
    """
    t, ident = e.vremya, e.id
    if tochno:
        i = bisect.bisect_left(vladelec, t)
        pisal = vladelec[i - 1] if i and vladelec[i - 1] > t - OKNO else None
        if e.faza == "доработка" and pisal and posle(sob, pisal) < t:
            sob.append(Sobytie(posle(sob, pisal), "faza", "доработка", ident, e.cikl,
                               e.priblizitelno))
        return e
    if e.faza == "правки" and (e.cikl or 1) >= 2 and otchet is not None:
        if any(otchet < v < t for v in vladelec):
            zadnim_chislom(sob, max(otchet, t - OKNO), t, "доработка", ident, e.cikl, False)
            return Sobytie(t, e.vid, "доработка", ident, e.cikl, True)
    elif e.faza == "задание" and novyy and (e.cikl or 1) == 1:
        zadnim_chislom(sob, t - OKNO, t, "план", ident, None, True)
    return e


def zadnim_chislom(sob: list[Sobytie], s0: datetime, t: datetime, faza: str, ident: str | None,
                   cikl: int | None, s_nachala: bool) -> None:
    """Фаза задачи задним числом с `s0` (не раньше последнего события с ID) до `t`: каждое
    сообщение владельца без ID её начинает, сообщение соседу без ID оставляет прочим. `s_nachala`
    — фаза и с самого `s0`, если в окне нет сообщений соседу."""
    j = len(sob)
    while j and sob[j - 1].faza == BEZ_ID:
        j -= 1
    s0 = posle(sob[:j], s0)
    v_okne = [k for k in range(j, len(sob)) if sob[k].vremya >= s0]
    for k in v_okne:
        if sob[k].vid == "vladelec":
            sob[k] = Sobytie(sob[k].vremya, "faza", faza, ident, cikl, True)
    if s_nachala and s0 < t and all(sob[k].vid == "faza" for k in v_okne):
        sob.insert(v_okne[0] if v_okne else len(sob), Sobytie(s0, "faza", faza, ident, cikl, True))


Vidy = dict[tuple[str, int], bool]  # цикл доработки по слову владельца → приблизительно ли


def vidy_ciklov(sobytiya: list[Sobytie]) -> Vidy:
    """Циклы `доработка` по событиям всех сессий; точная метка сильнее приблизительной."""
    vidy: Vidy = {}
    for e in sobytiya:
        if e.faza == "доработка" and e.id is not None and e.cikl is not None:
            vidy[(e.id, e.cikl)] = vidy.get((e.id, e.cikl), True) and e.priblizitelno
    return vidy


def dorabotka(e: Sobytie, vidy: Vidy) -> tuple[bool, bool]:
    """Цикл события — доработка владельца? И приблизительна ли разметка. Цикл 1 — никогда."""
    if e.cikl == 1:
        return False, e.priblizitelno
    if e.faza == "доработка":
        return True, e.priblizitelno
    if e.id is not None and e.cikl is not None and (e.id, e.cikl) in vidy:
        return True, e.priblizitelno or vidy[(e.id, e.cikl)]
    return False, e.priblizitelno


def perehod(tek: Metka | None, e: Sobytie, rol: str, vidy: Vidy) -> Metka | None:
    dor, pribl = dorabotka(e, vidy)
    if rol == "vedushchiy":
        if e.faza == BEZ_ID or (e.vid == "faza" and e.faza == "прочее"):
            return ("prochee", None, None, e.faza == BEZ_ID)
        if e.vid == "faza":
            seg = "planirovanie" if e.faza == "план" else "dorabotka" if dor else "proverka"
            return (seg, e.id, e.cikl, pribl)
        if e.vid == "vhod" and e.faza in ("отчёт", "вопрос"):
            return ("dorabotka" if dor else "proverka", e.id, e.cikl, pribl)
        if e.vid == "ishod" and e.faza in ("задание", "правки", "доработка", "принято"):
            return None
        return tek if tek is not None and tek[1] == e.id else None
    if rol == "ispolnitel" and e.vid in ("vhod", "ishod") and e.id is not None:
        if e.faza == "принято":  # приёмка задачу не переключает
            return tek
        cikl = e.cikl or 1
        seg = "dorabotka" if dor else "realizaciya" if cikl == 1 else "ispravleniya"
        return (seg, e.id, cikl, pribl)
    return tek if rol == "ispolnitel" else None


class Razmetchik:
    """Сегмент сессии в момент времени: события строго раньше, окно 2 ч (см. шапку модуля)."""

    def __init__(self, sobytiya: list[Sobytie], aktivnost: list[datetime], rol: str,
                 vidy: Vidy) -> None:
        self.rol = rol
        self.vremena = [e.vremya for e in sobytiya]
        self.sostoyaniya: list[Metka | None] = []
        tek: Metka | None = None
        for e in sobytiya:
            tek = perehod(tek, e, rol, vidy)
            self.sostoyaniya.append(tek)
        vse = sorted(aktivnost + self.vremena)
        self.sbrosy = [b for a, b in itertools.pairwise(vse) if b - a > OKNO]

    def v(self, t: datetime) -> Metka:
        i = bisect.bisect_left(self.vremena, t)
        sost = self.sostoyaniya[i - 1] if i else None
        if sost is None or self.rol not in ("vedushchiy", "ispolnitel"):
            return NE_RAZMECHENO
        posl = self.vremena[i - 1]
        if self.rol == "vedushchiy":
            return sost if t - posl <= OKNO else NE_RAZMECHENO
        j = bisect.bisect_right(self.sbrosy, t)
        return sost if j == 0 or self.sbrosy[j - 1] <= posl else NE_RAZMECHENO


def rol_sessii(f: Fayl, karta: dict[str, str]) -> tuple[str, str]:
    """Роль и признак: карта `--rol` → имя сессии → большинство подписей исходящих."""
    if f.sessiya[:8] in karta:
        return karta[f.sessiya[:8]], "карта --rol"
    for imya in sorted(f.imena):
        if ISPOLNITEL.search(imya):
            return "ispolnitel", "имя сессии"
        if VEDUSCHIY.search(imya):
            return "vedushchiy", "имя сессии"
    golosa: Counter[str] = Counter()
    for p, n in f.podpisi.items():
        if ISPOLNITEL.search(p):
            golosa["ispolnitel"] += n
        elif VEDUSCHIY.search(p):
            golosa["vedushchiy"] += n
    if not golosa:
        return "neizvestno", "нет"
    return golosa.most_common(1)[0][0], "подписи исходящих"


def podtip(rodit: Metka, tip: str, stroka: str, rol: str, priblizitelno: bool,
           vidy: Vidy, karta: Karta) -> Metka:
    """Сегмент субагента: `verify` у ведущего — проверка; `opus-implementer` — по метке."""
    if tip == "verify" and rol == "vedushchiy":
        seg = "dorabotka" if rodit[0] == "dorabotka" else "proverka"
        return (seg, rodit[1], rodit[2], rodit[3])
    if tip == "opus-implementer":
        if m := METKA.match(stroka):
            ident, dopolnen = polnyy_id(m.group(1), karta)
            e = Sobytie(datetime.min, "vhod", m.group(3), ident, int(m.group(2)), dopolnen)
            return perehod(None, e, "ispolnitel", vidy) or NE_RAZMECHENO
        if priblizitelno and (p := PRIBL_ID.search(stroka)):
            return ("realizaciya", polnyy_id(razdelit_cikl(p.group(1))[0], karta)[0], 1, True)
    return rodit


# ── сборка проекта ───────────────────────────────────────────────────────────────────────────

PREFIKS = "-home-pakar-igor-"  # папки журналов проектов владельца


def papki_proekta(koren: Path, proekt: str) -> list[Path]:
    """Папка проекта и его worktree (`-home-pakar-igor-<проект>-…`), без соседних проектов."""
    baza = f"{PREFIKS}{proekt}"
    return sorted(p for p in koren.glob(baza + "*")
                  if p.is_dir() and (p.name == baza or p.name.startswith(baza + "-")))


def subagenty(papka: Path) -> list[Path]:
    return sorted(papka.glob("*.jsonl")) if papka.is_dir() else []


def siroty(papka: Path) -> list[Path]:
    """Папки субагентов, у которых нет файла сессии."""
    return [d for d in sorted(papka.glob("*/subagents"))
            if not (papka / f"{d.parent.name}.jsonl").is_file()]


def fazy_iz(put: Path | None, proekt: str) -> list[Sobytie]:
    if put is None or not put.is_file():
        return []
    sob: list[Sobytie] = []
    for stroka in put.read_text(encoding="utf-8").splitlines():
        chasti = stroka.split("\t")
        t = vremya_iz(chasti[0]) if len(chasti) == 4 else None
        if t is None or chasti[1] != proekt or chasti[3] not in FAZY:
            continue
        ident, cikl = chasti[2], ""
        if re.search(r"/\d+$", ident):
            ident, cikl = ident.rsplit("/", 1)
        sob.append(Sobytie(t, "faza", chasti[3], None if ident in ("", "-") else ident,
                           int(cikl) if cikl else None))
    return sob


@dataclass(slots=True)
class Sbor:
    stroki: list[Stroka] = field(default_factory=list)
    sessii: dict[str, tuple[str, str]] = field(default_factory=dict)  # id8 → роль, признак
    korotkie: dict[str, str] = field(default_factory=dict)  # ID без «/», не дополненный → почему


def sobrat_proekt(papki: list[Path], proekt: str, fazy: Path | None, karta: dict[str, str],
                  priblizitelno: bool) -> Sbor:
    """Сессии и субагенты папок проекта, размеченные по сегментам; порядок — как `vse_otvety`."""
    sbor = Sbor()
    sob_faz = fazy_iz(fazy, proekt)
    fayly = [[prochitat(put, put.stem) for put in sorted(papka.glob("*.jsonl"))]
             for papka in papki]
    ids = karta_id([f for gruppa in fayly for f in gruppa])  # короткий ID → полный
    sessii: list[list[tuple[Fayl, str, list[Sobytie]]]] = []
    for gruppa_f in fayly:  # проход 1: роли и события всех сессий — вид цикла знает ведущий
        sessii.append([])
        for f in gruppa_f:
            rol, priznak = rol_sessii(f, karta)
            sbor.sessii[f.sessiya[:8]] = (rol, priznak)
            sob = razobrat_metki(f, priblizitelno, rol, ids)
            if rol == "vedushchiy":
                sob = sorted(sob + sob_faz, key=lambda e: e.vremya)
            sessii[-1].append((f, rol, sob))
    vse_sob = [e for gruppa in sessii for _, _, sob in gruppa for e in sob]
    sbor.korotkie = {e.id: "несколько полных" if e.id in ids else "нет полного"
                     for e in vse_sob if e.id is not None and "/" not in e.id}
    vidy = vidy_ciklov(vse_sob)
    for papka, gruppa in zip(papki, sessii, strict=True):  # проход 2: разметка ответов
        for f, rol, sob in gruppa:
            r = Razmetchik(sob, [s.vremya for s in f.otvety], rol, vidy)
            for s in f.otvety:
                s.razmetit(rol, r.v(s.vremya))
            sbor.stroki += f.otvety
            sbor.stroki += razmetit_subagentov(papka / f.sessiya / "subagents", f, r, rol,
                                               priblizitelno, vidy, ids)
        for d in siroty(papka):
            for put in subagenty(d):
                sbor.stroki += prochitat(put, d.parent.name).otvety
    sbor.stroki = bez_povtorov(sbor.stroki)
    return sbor


def razmetit_subagentov(papka: Path, glavnyy: Fayl, r: Razmetchik, rol: str,
                        priblizitelno: bool, vidy: Vidy, karta: Karta) -> list[Stroka]:
    """Субагент наследует сегмент вызвавшего хода по `meta.json → toolUseId`, вложенные — по
    цепочке вызовов."""
    fayly = {p.stem: prochitat(p, glavnyy.sessiya) for p in subagenty(papka)}
    kto_vyzval: dict[str, str | None] = dict.fromkeys(glavnyy.vyzovy)
    for ag, f in fayly.items():
        kto_vyzval.update(dict.fromkeys(f.vyzovy, ag))
    gotovo: dict[str, Metka] = {}

    def metka(ag: str, glubina: int) -> Metka:
        if ag in gotovo or glubina > 20:
            return gotovo.get(ag, NE_RAZMECHENO)
        meta: dict[str, object] = {}
        put_meta = papka / f"{ag}.meta.json"
        if put_meta.is_file():
            try:
                meta = slovar(json.loads(put_meta.read_text(encoding="utf-8")))
            except ValueError:
                meta = {}
        vyzov = str(meta.get("toolUseId") or "")
        itog = NE_RAZMECHENO
        if vyzov in kto_vyzval:
            rodit = kto_vyzval[vyzov]
            if rodit is None:
                t, tip, stroka = glavnyy.vyzovy[vyzov]
                itog = podtip(r.v(t), tip, stroka, rol, priblizitelno, vidy, karta)
            else:
                _, tip, stroka = fayly[rodit].vyzovy[vyzov]
                itog = podtip(metka(rodit, glubina + 1), tip, stroka, rol, priblizitelno, vidy,
                              karta)
        gotovo[ag] = itog
        return itog

    stroki: list[Stroka] = []
    for ag, f in fayly.items():
        m = metka(ag, 0)
        for s in f.otvety:
            s.razmetit(rol, m)
        stroki += f.otvety
    return stroki


def vse_otvety(papki: list[Path]) -> list[Stroka]:
    """Все ответы папок без разметки, в том же порядке и с той же склейкой, что `sobrat_proekt`."""
    stroki: list[Stroka] = []
    for papka in papki:
        for put in sorted(papka.glob("*.jsonl")):
            stroki += prochitat(put, put.stem).otvety
            for sub in subagenty(papka / put.stem / "subagents"):
                stroki += prochitat(sub, put.stem).otvety
        for d in siroty(papka):
            for sub in subagenty(d):
                stroki += prochitat(sub, d.parent.name).otvety
    return bez_povtorov(stroki)


def kontrol(papki: list[Path], s: date, po: date) -> dict[str, int]:
    """Сумма по журналам напрямую, без разметки, — для сверки с суммой по сегментам."""
    return summa([x for x in vse_otvety(papki) if s <= london(x.vremya) <= po])


def summa(stroki: list[Stroka]) -> dict[str, int]:
    return {k: sum(s.chisla[k] for s in stroki) for k in CHISLA + SPRAVOCHNO}


# ── доля недельного лимита (оценка) ──────────────────────────────────────────────────────────

Prirost = tuple[datetime, datetime, float]  # начало, конец интервала, прирост п.п.
Rozdano = tuple[datetime, float, float]  # конец интервала, прирост, из него отнесено к ответам


def tochki_limita(put: Path) -> list[tuple[datetime, float, int]]:
    """Точки журнала statusline: время, `seven_day.used_percentage`, `resets_at`."""
    tochki: list[tuple[datetime, float, int]] = []
    for z in zapisi(put):
        t = vremya_iz(z.get("t"))
        sd = slovar(slovar(z.get("rl")).get("seven_day"))
        p, r = sd.get("used_percentage"), sd.get("resets_at")
        if isinstance(p, bool) or not isinstance(p, int | float):
            continue
        if t is not None and isinstance(r, int):
            tochki.append((t, float(p), r))
    return sorted(tochki)


def prirosty_limita(tochki: list[tuple[datetime, float, int]]) -> list[Prirost]:
    """Приросты процента; интервал прироста — от прошлого прироста (или начала окна) до точки.

    Процент целый: 1 п.п. копится всё время с прошлого прироста, а не за секунды от соседней
    точки (иначе прирост достаётся пустому интервалу между двумя сессиями). Новое окно — счёт с
    нуля, а не отрицательный прирост. Окно сменилось, если вырос `resets_at` (допуск — час) или
    процент упал на `POROG_SBROSA` и больше: так выглядит и сброс без смены `resets_at`
    (20.10.2026: 54 → 2). Малое падение — устаревшее показание другой сессии (у одной сессии
    процент не падает): прироста нет, в окне берётся максимум. Точка старого окна после смены —
    тоже устаревшее показание, пропускается.
    """
    itog: list[Prirost] = []
    if not tochki:
        return itog
    pred, maks, okno = tochki[0]  # pred — когда достигнут текущий максимум окна
    staryy_maks = -1.0  # максимум окна до сброса по падению: его отголоски не прирост
    for t, p, r in tochki[1:]:
        if okno - r > DOPUSK_OKNA or (p >= staryy_maks - POROG_SBROSA > maks):
            continue
        if r - okno > DOPUSK_OKNA or p <= maks - POROG_SBROSA:
            staryy_maks = -1.0 if r - okno > DOPUSK_OKNA else maks
            if p > 0:
                itog.append((pred, t, p))
            maks, pred = p, t
        elif p > maks:
            itog.append((pred, t, p - maks))
            maks, pred = p, t
        okno = max(okno, r)
    return itog


def razdelit_limit(vse: list[Stroka], prirosty: list[Prirost]) -> list[Rozdano]:
    """Прирост интервала (начало, конец] — ответам в нём пропорционально взвешенным токенам."""
    po_vremeni = sorted(vse, key=lambda s: s.vremya)
    vremena = [s.vremya for s in po_vremeni]
    itog: list[Rozdano] = []
    for a, b, d in prirosty:
        ss = po_vremeni[bisect.bisect_right(vremena, a):bisect.bisect_right(vremena, b)]
        ves = sum(s.vzveshennye() for s in ss)
        for s in ss if ves > 0 else []:
            s.limit += d * s.vzveshennye() / ves
        itog.append((b, d, d if ves > 0 else 0.0))
    return itog


def pp(n: float) -> str:
    return f"{round(n, 6) + 0.0:.1f}".replace(".", ",")  # без «-0,0» от погрешности сложения


@dataclass(slots=True)
class Limit:
    """Розданные приросты и ответы этой машины вне проекта — для разбора прироста по причинам."""

    rozdano: list[Rozdano]
    drugie: list[Stroka] = field(default_factory=list)  # другие проекты (`-home-pakar-igor-*`)
    vne: list[Stroka] = field(default_factory=list)  # сессии вне проектов (прочие папки журналов)


def razdel_limita(d: list[Stroka], limit: Limit | None, s: date, po: date) -> list[str]:
    nash = sum(x.limit for x in d)
    out = ["## Доля недельного лимита — оценка", "",
           "Журнал statusline `~/.claude/usage-log.jsonl` этой машины: прирост "
           "`seven_day.used_percentage` делится между ответами всех сессий машины (все папки "
           "журналов) за время с прошлого прироста пропорционально взвешенным токенам; сброс "
           "окна — начало нового окна. Процент целый, шаг 1 п.п. Учётка у каждой машины своя: "
           "оценка только по журналу лимита той машины, где он есть.", ""]
    if limit is None:
        po_mashine: dict[str, float] = defaultdict(float)
        for x in d:
            po_mashine[x.mashina or "—"] += x.limit
        out.append("Из выгрузок, по машинам (разные учётки, не складывать): " + " · ".join(
            f"{m} {pp(v)} п.п." for m, v in sorted(po_mashine.items())) + ".")
    else:
        vsego = [x for x in limit.rozdano if s <= london(x[0]) <= po]
        prirost, otneseno = sum(x[1] for x in vsego), sum(x[2] for x in vsego)
        drugie = sum(x.limit for x in za_period(limit.drugie, s, po))
        vne = sum(x.limit for x in za_period(limit.vne, s, po))
        out += [f"Прирост лимита учётки этой машины за период: {pp(prirost)} п.п.", "",
                "| Куда отнесён прирост | п.п. | Доля |", "|---|--:|--:|"]
        for nazv, v in (("этот проект", nash), ("другие проекты (`-home-pakar-igor-*`)", drugie),
                        ("сессии вне проектов (прочие папки журналов)", vne),
                        ("не отнесено: за интервал нет ответов на этой машине",
                         prirost - otneseno),
                        ("прочее: интервал и ответ в разных сутках периода",
                         otneseno - nash - drugie - vne)):
            out.append(f"| {nazv} | {pp(v)} | {procent(v, prirost)} % |")
    out += ["", "| Сегмент | п.п. лимита | Доля проекта |", "|---|--:|--:|"]
    for seg in SEGMENTY:
        v = sum(x.limit for x in d if x.segment == seg)
        out.append(f"| {NAZVANIE[seg]} | {pp(v)} | {procent(v, nash)} % |")
    return [*out, ""]


# ── сутки по Лондону, выгрузка, склейка ──────────────────────────────────────────────────────

def posl_voskresenye(god: int, mesyac: int) -> datetime:
    d = date(god, mesyac, 31)
    d -= timedelta(days=(d.weekday() + 1) % 7)
    return datetime(d.year, d.month, d.day, 1, tzinfo=UTC)


def london(t: datetime) -> date:
    """Дата по Лондону: летнее время — с последнего воскресенья марта по последнее октября,
    переход в 01:00 UTC."""
    t = t.astimezone(UTC)
    leto = posl_voskresenye(t.year, 3) <= t < posl_voskresenye(t.year, 10)
    return (t + timedelta(hours=1 if leto else 0)).date()


def v_slovar(s: Stroka) -> dict[str, object]:
    return {"sessiya": s.sessiya, "fayl": s.fayl, "msg_id": s.msg_id, "req_id": s.req_id,
            "uuid": s.uuid, "vremya": s.vremya.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "model": s.model, "rol": s.rol, "zadacha": s.zadacha, "cikl": s.cikl,
            "segment": s.segment, "priblizitelno": s.priblizitelno,
            "limit_7d": round(s.limit, 9), **{k: s.chisla[k] for k in CHISLA + SPRAVOCHNO}}


def stroka_ili_net(v: object) -> str | None:
    return v if isinstance(v, str) else None


def iz_slovarya(d: dict[str, object]) -> Stroka:
    t = vremya_iz(d.get("vremya"))
    if t is None or d.get("segment") not in SEGMENTY:
        raise ValueError(f"строка выгрузки не по схеме {SKHEMA}: {d.get('uuid')}")
    cikl, limit = d.get("cikl"), d.get("limit_7d")
    return Stroka(str(d.get("sessiya")), str(d.get("fayl")), stroka_ili_net(d.get("msg_id")),
                  stroka_ili_net(d.get("req_id")), str(d.get("uuid")), t, str(d.get("model")),
                  {k: chislo(d.get(k)) for k in CHISLA + SPRAVOCHNO}, str(d.get("rol")),
                  stroka_ili_net(d.get("zadacha")), cikl if isinstance(cikl, int) else None,
                  str(d.get("segment")), d.get("priblizitelno") is True,
                  float(limit) if isinstance(limit, int | float) else 0.0)


def poryadok(s: Stroka) -> tuple[datetime, str, str, str, str, str]:
    return (s.vremya, s.sessiya, s.fayl, s.uuid, s.msg_id or "", s.req_id or "")


def vygruzka(stroki: list[Stroka], proekt: str) -> str:
    """JSON по схеме `tokeny/1`; на тех же журналах — тот же текст."""
    telo = {"skhema": SKHEMA, "proekt": proekt, "istochnik": socket.gethostname(),
            "stroki": [v_slovar(s) for s in sorted(stroki, key=poryadok)]}
    return json.dumps(telo, ensure_ascii=False, indent=1) + "\n"


def skleit(puti: list[Path], proekt: str) -> list[Stroka]:
    """Выгрузки с разных машин без двойного счёта: один ответ API считается один раз."""
    stroki: list[Stroka] = []
    for put in puti:
        d = slovar(json.loads(put.read_text(encoding="utf-8")))
        if d.get("skhema") != SKHEMA or d.get("proekt") != proekt:
            raise ValueError(f"{put}: схема {d.get('skhema')}, проект {d.get('proekt')}; "
                             f"ждали {SKHEMA}, {proekt}")
        spisok = d.get("stroki")
        for x in spisok if isinstance(spisok, list) else []:
            s = iz_slovarya(slovar(x))
            s.mashina = str(d.get("istochnik") or "")
            stroki.append(s)
    return sorted(bez_povtorov(stroki), key=poryadok)


# ── отчёт и сводка ───────────────────────────────────────────────────────────────────────────

def ch(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


def mln(n: float) -> str:
    if n >= 100_000:
        return f"{n / 1e6:.1f} млн".replace(".", ",")
    return f"{n / 1e3:.0f} тыс."


def procent(chast: float, vsego: float) -> str:
    return pp(chast / vsego * 100) if vsego else "0"


def vzv(stroki: list[Stroka]) -> float:
    return sum(x.vzveshennye() for x in stroki)


def za_period(stroki: list[Stroka], s: date, po: date) -> list[Stroka]:
    return [x for x in stroki if s <= london(x.vremya) <= po]


def stroka_chisel(ss: list[Stroka]) -> str:
    sm = summa(ss)
    return f"{len(ss)} | " + " | ".join(ch(sm[k]) for k in CHISLA) + f" | {ch(vzv(ss))}"


def otchet(stroki: list[Stroka], proekt: str, s: date, po: date, kontr: dict[str, int] | None,
           sessii: dict[str, tuple[str, str]], limit: Limit | None = None,
           korotkie: dict[str, str] | None = None) -> tuple[str, bool]:
    """Markdown-отчёт за период и признак «сумма по сегментам = сумма по журналам»."""
    d = za_period(stroki, s, po)
    vsego = vzv(d)
    period = s.isoformat() if s == po else f"{s.isoformat()} — {po.isoformat()}"
    pribl = sum(x.priblizitelno for x in d)
    out = [f"# Токены Claude Code — {proekt}, {period} (сутки по Лондону)", "",
           f"Ответов модели: {len(d)}; взвешенно {ch(vsego)} — ценовой эквивалент API (ввод 1, "
           "кэш-запись 5 мин 1,25, 1 ч 2, кэш-чтение 0,1, вывод 5), не доля лимита подписки.",
           f"Приблизительная разметка (`--priblizitelno`, метка ≈): {pribl} ответов." if pribl
           else "Разметка только по точным меткам и журналу фаз.", ""]

    out += ["## Итоги по сегментам", "",
            "| Сегмент | Вызовы | Ввод | Кэш 5 мин | Кэш 1 ч | Чтение кэша | Вывод | Взвешенно "
            "| Доля |", "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    po_seg = {seg: [x for x in d if x.segment == seg] for seg in SEGMENTY}
    for seg, ss in po_seg.items():
        out.append(f"| {NAZVANIE[seg]} | {stroka_chisel(ss)} | {procent(vzv(ss), vsego)} % |")
    nr = po_seg["ne_razmecheno"]
    out += ["", f"**Не размечено: {procent(vzv(nr), vsego)} % взвешенных, "
            f"{len(nr)} из {len(d)} ответов.**", ""]

    kletki = setka(d)
    out += ["## Сетка сводки: кто и на что", "", "| Кто | На что | Вызовы | Взвешенно | Доля |",
            "|---|---|--:|--:|--:|"]
    for (kto, na_chto), ss in kletki.items():
        out.append(f"| {kto} | {na_chto} | {len(ss)} | {ch(vzv(ss))} | "
                   f"{procent(vzv(ss), vsego)} % |")
    out += ["", stroka_peredelok(kletki, vsego), ""]

    itog = summa(d)
    sovpalo = kontr is None or all(itog[k] == kontr[k] for k in CHISLA)
    out += ["## Сверка с журналами", ""]
    if kontr is None:
        out.append("Отчёт собран из выгрузок `--json`; сверка с журналами — при выгрузке "
                   "на каждой машине.")
    else:
        out += ["| | Ввод | Кэш 5 мин | Кэш 1 ч | Чтение кэша | Вывод |",
                "|---|--:|--:|--:|--:|--:|",
                "| сумма по сегментам | " + " | ".join(ch(itog[k]) for k in CHISLA) + " |",
                "| сумма по журналам | " + " | ".join(ch(kontr[k]) for k in CHISLA) + " |", "",
                "Совпадает до токена." if sovpalo else "**РАСХОЖДЕНИЕ — отчёт неполный.**"]
    out += ["", f"Справочно: thinking {ch(itog['thinking'])} (уже внутри вывода), веб-поиск "
            f"{itog['web_search']}, веб-загрузка {itog['web_fetch']}, ответов с несколькими "
            f"iterations {sum(x.chisla['iteracii'] > 1 for x in d)}. Codex и GPT — не токены "
            "Claude, здесь не считаются.", ""]
    if limit is not None or any(x.limit for x in d):
        out += razdel_limita(d, limit, s, po)
    out += tablica_zadach(d)
    vidny = {x.zadacha for x in d}
    flagi = sorted(f"`{k}` — {v}" for k, v in (korotkie or {}).items() if k in vidny)
    if flagi:
        out += ["ID без «/», не дополненные до полного (оставлены как есть; «нет полного» бывает "
                "и у самостоятельного ID): " + "; ".join(flagi) + ".", ""]
    out += tablica_sessiy(d, sessii)
    return "\n".join(out) + "\n", sovpalo


VED, ISP = "Ведущий", "Исполнители"
KLETKI = ((VED, "планирование"), (VED, "проверка"), (VED, "перепроверка после правок"),
          (VED, "постановка и проверка доработки"), (VED, "прочее"), (ISP, "реализация"),
          (ISP, "исправления"), (ISP, "доработка"), ("Без метки", "не размечено"))
KLETKA = {"planirovanie": KLETKI[0], "prochee": KLETKI[4], "realizaciya": KLETKI[5],
          "ispravleniya": KLETKI[6], "ne_razmecheno": KLETKI[8]}


def kletka(x: Stroka) -> tuple[str, str]:
    """Клетка сетки: проверка делится по циклу, доработка — на ведущего и исполнителей."""
    if x.segment == "proverka":
        return KLETKI[2] if (x.cikl or 0) >= 2 else KLETKI[1]
    if x.segment == "dorabotka":
        return KLETKI[3] if x.rol == "vedushchiy" else KLETKI[7]
    return KLETKA[x.segment]


def setka(d: list[Stroka]) -> dict[tuple[str, str], list[Stroka]]:
    """Одна сетка для отчёта и сводки: каждый ответ ровно в одной клетке, сумма — 100 %."""
    kletki: dict[tuple[str, str], list[Stroka]] = {k: [] for k in KLETKI}
    for x in d:
        kletki[kletka(x)].append(x)
    return kletki


def stroka_peredelok(kletki: dict[tuple[str, str], list[Stroka]], vsego: float) -> str:
    vedushchiy = vzv(kletki[KLETKI[6]]) + vzv(kletki[KLETKI[2]])
    vladelec = vzv(kletki[KLETKI[7]]) + vzv(kletki[KLETKI[3]])
    return (f"Переделки: по проверке ведущего {procent(vedushchiy, vsego)} % (исправления и "
            f"перепроверка после правок) · по слову владельца {procent(vladelec, vsego)} % "
            "(доработка, её постановка и проверка).")


def tablica_zadach(d: list[Stroka]) -> list[str]:
    out = ["## Задача × сегмент × цикл", "",
           "| Задача | Сегмент | Цикл | Вызовы | Ввод | Кэш 5 мин | Кэш 1 ч | Чтение кэша | Вывод "
           "| Взвешенно | ≈ |", "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|"]
    gruppy: dict[tuple[str, str, int], list[Stroka]] = defaultdict(list)
    for x in d:
        gruppy[(x.zadacha or "—", x.segment, x.cikl or 0)].append(x)
    ves: dict[str, float] = defaultdict(float)
    for (z, _, _), ss in gruppy.items():
        ves[z] += vzv(ss)
    for z, seg, c in sorted(gruppy, key=lambda k: (k[0] == "—", -ves[k[0]], k[0], k[2],
                                                     SEGMENTY.index(k[1]))):
        ss = gruppy[(z, seg, c)]
        priznak = "≈" if any(x.priblizitelno for x in ss) else ""
        out.append(f"| {z} | {NAZVANIE[seg]} | {c or ''} | {stroka_chisel(ss)} | {priznak} |")
    return out


def tablica_sessiy(d: list[Stroka], sessii: dict[str, tuple[str, str]]) -> list[str]:
    out = ["", "## Сессии", "", "| Сессия | Роль | Признак роли | Ответов | Взвешенно |",
           "|---|---|---|--:|--:|"]
    po_sessii: dict[str, list[Stroka]] = defaultdict(list)
    for x in d:
        po_sessii[x.sessiya[:8]].append(x)
    for sid, ss in sorted(po_sessii.items(), key=lambda p: (-vzv(p[1]), p[0])):
        rol, priznak = sessii.get(sid, (ss[0].rol, "из выгрузки"))
        out.append(f"| {sid} | {ROLI.get(rol, rol)} | {priznak} | {len(ss)} | {ch(vzv(ss))} |")
    out += ["", "## Модели", "", "| Модель | Ответов | Взвешенно |", "|---|--:|--:|"]
    po_modeli: dict[str, list[Stroka]] = defaultdict(list)
    for x in d:
        po_modeli[x.model or "—"].append(x)
    for model, ss in sorted(po_modeli.items()):
        out.append(f"| {model} | {len(ss)} | {ch(vzv(ss))} |")
    return out


def stroka_limita(d: list[Stroka], proekt: str) -> list[str]:
    """Строка сводки о доле лимита; выгрузки с разных машин — разные учётки, не складываются."""
    po_mashine: dict[str, list[Stroka]] = defaultdict(list)
    for x in d:
        if x.limit:
            po_mashine[x.mashina].append(x)
    if len(po_mashine) > 1:
        return ["Недельный лимит (оценка, у машин разные учётки): " + ", ".join(
            f"{m} ≈ {pp(sum(x.limit for x in ss))} п.п." for m, ss in sorted(po_mashine.items()))]
    if not po_mashine:
        return []
    nash = sum(x.limit for x in d)
    chasti = [f"{NAZVANIE[seg]} {pp(v)}" for seg in SEGMENTY
              if (v := sum(x.limit for x in d if x.segment == seg)) >= 0.05]
    return [f"Недельный лимит (оценка): {proekt} ≈ {pp(nash)} п.п. — {', '.join(chasti)}."]


def svodka(stroki: list[Stroka], proekt: str, den: date) -> str:
    """6–10 строк простым текстом для Telegram: сутки по Лондону."""
    d = za_period(stroki, den, den)
    vsego = vzv(d)
    kletki = setka(d)

    def doli(kto: str) -> str:
        return ", ".join(f"{na_chto} {procent(vzv(ss), vsego)} %"
                         for (k, na_chto), ss in kletki.items() if k == kto)

    pribl = " Разметка приблизительная." if any(x.priblizitelno for x in d) else ""
    bez_metki = vzv(kletki[KLETKI[8]])
    out = [f"Токены Claude — {proekt}, {den.day} {MESYACY[den.month - 1]}, "
           f"{DNI[den.weekday()]} (сутки по Лондону).",
           f"Всего {len(d)} ответов модели, взвешенно {mln(vsego)} — это цена по API, а не доля "
           f"лимита; без метки задачи {procent(bez_metki, vsego)} %.{pribl}",
           f"{VED}: {doli(VED)}.", f"{ISP}: {doli(ISP)}.", stroka_peredelok(kletki, vsego)]
    out += stroka_limita(d, proekt)
    po_zadache: dict[str, float] = defaultdict(float)
    for x in d:
        if x.zadacha:
            po_zadache[x.zadacha] += x.vzveshennye()
    top = sorted(po_zadache.items(), key=lambda p: (-p[1], p[0]))[:3]
    out.append("Самые дорогие задачи:" if top else "Задач с ID за эти сутки нет.")
    out += [f"{i}. {z} — {mln(v)}, {procent(v, vsego)} % суток" for i, (z, v) in enumerate(top, 1)]
    return "\n".join(out) + "\n"


# ── командная строка ─────────────────────────────────────────────────────────────────────────

def argumenty(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Учёт токенов Claude Code по задачам и сегментам.")
    p.add_argument("--proekt", required=True, help="tamara, remlab, …")
    p.add_argument("--papka", action="append", default=[], help="папка журналов (повторяемый)")
    p.add_argument("--koren", default=str(Path.home() / ".claude" / "projects"),
                   help="корень журналов")
    p.add_argument("--fazy", help="журнал фаз (по умолчанию "
                   "/home/pakar/igor/<проект>/data/logs/tokeny/fazy.tsv)")
    p.add_argument("--rol", action="append", default=[],
                   help="<id8>=vedushchiy|ispolnitel (повторяемый)")
    p.add_argument("--priblizitelno", action="store_true", help="разметка дней до меток")
    p.add_argument("--s", type=date.fromisoformat, help="первый день, ГГГГ-ММ-ДД (Лондон)")
    p.add_argument("--po", type=date.fromisoformat, help="последний день, ГГГГ-ММ-ДД (Лондон)")
    p.add_argument("--json", help="выгрузить строки в файл (`-` — в stdout)")
    p.add_argument("--sobrat", nargs="+", help="собрать отчёт из выгрузок --json")
    p.add_argument("--svodka", action="store_true", help="сводка за сутки для Telegram")
    p.add_argument("--data", type=date.fromisoformat,
                   help="сутки для --svodka (по умолчанию вчера)")
    p.add_argument("--vyhod", help="файл отчёта (по умолчанию data/otchety/tokeny/<дата>.md)")
    p.add_argument("--limit", default=str(Path.home() / ".claude" / "usage-log.jsonl"),
                   help="журнал лимита statusline (нет файла — без оценки доли лимита)")
    return p.parse_args(argv)


def soobshit(tekst: str, oshibka: bool = False) -> None:
    (sys.stderr if oshibka else sys.stdout).write(tekst + "\n")


def main(argv: list[str] | None = None) -> int:
    a = argumenty(argv)
    karta: dict[str, str] = {}
    for x in a.rol:
        sid, _, rol = x.partition("=")
        if len(sid) != 8 or rol not in ("vedushchiy", "ispolnitel"):
            soobshit(f"--rol {x}: нужно <id8>=vedushchiy|ispolnitel", oshibka=True)
            return 2
        karta[sid] = rol
    segodnya = london(datetime.now(UTC))
    koren = Path(a.koren).expanduser()
    papki: list[Path] = []
    sessii: dict[str, tuple[str, str]] = {}
    korotkie: dict[str, str] = {}
    if a.sobrat:
        stroki = skleit([Path(x) for x in a.sobrat], a.proekt)
    else:
        papki = [Path(x) for x in a.papka] or papki_proekta(koren, a.proekt)
        if not papki:
            soobshit(f"нет журналов проекта {a.proekt} в {koren}", oshibka=True)
            return 2
        fazy = Path(a.fazy or f"/home/pakar/igor/{a.proekt}/data/logs/tokeny/fazy.tsv")
        sbor = sobrat_proekt(papki, a.proekt, fazy, karta, a.priblizitelno)
        stroki, sessii, korotkie = sbor.stroki, sbor.sessii, sbor.korotkie
    limit: Limit | None = None
    if not a.sobrat and (put_limita := Path(a.limit).expanduser()).is_file():
        prochie = [p for p in sorted(koren.iterdir())
                   if p.is_dir() and p not in papki] if koren.is_dir() else []
        limit = Limit([], vse_otvety([p for p in prochie if p.name.startswith(PREFIKS)]),
                      vse_otvety([p for p in prochie if not p.name.startswith(PREFIKS)]))
        limit.rozdano = razdelit_limit(bez_povtorov(stroki + limit.drugie + limit.vne),
                                       prirosty_limita(tochki_limita(put_limita)))

    if a.json:
        s, po = a.s or date.min, a.po or date.max
        vybor = za_period(stroki, s, po)
        tekst = vygruzka(vybor, a.proekt)
        if a.json == "-":
            sys.stdout.write(tekst)
        else:
            Path(a.json).write_text(tekst, encoding="utf-8")
        sovpalo = not papki or summa(vybor) == kontrol(papki, s, po)
        soobshit(f"выгружено строк: {len(vybor)}; сверка с журналами: "
                 f"{'совпадает' if sovpalo else 'РАСХОЖДЕНИЕ'}", oshibka=True)
        return 0 if sovpalo else 3

    if a.svodka:
        sys.stdout.write(svodka(stroki, a.proekt, a.data or segodnya - timedelta(days=1)))
        return 0

    po = a.po or max(a.s or segodnya, segodnya)
    s = a.s or po
    kontr = kontrol(papki, s, po) if papki else None
    tekst, sovpalo = otchet(stroki, a.proekt, s, po, kontr, sessii, limit, korotkie)
    imya = s.isoformat() if s == po else f"{s.isoformat()}_{po.isoformat()}"
    if a.proekt != KOREN_REPO.name:
        imya = f"{a.proekt}-{imya}"
    vyhod = Path(a.vyhod) if a.vyhod else KOREN_REPO / "data" / "otchety" / "tokeny" / f"{imya}.md"
    vyhod.parent.mkdir(parents=True, exist_ok=True)
    vyhod.write_text(tekst, encoding="utf-8")
    sverka = ("сверка с журналами — при выгрузке --json" if kontr is None else
              f"сумма по сегментам {'совпадает' if sovpalo else 'НЕ СОВПАДАЕТ'} с журналами")
    soobshit(f"отчёт: {vyhod}; {sverka}")
    return 0 if sovpalo else 3


if __name__ == "__main__":
    sys.exit(main())
