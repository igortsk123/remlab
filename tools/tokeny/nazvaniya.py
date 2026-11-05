"""Названия задач для сводки: T-ID → несколько простых слов из доски задач проекта (владелец 05.11.2026: «в отчёт не надо
писать T-20261104-06 — я не знаю, что это за планы»).

Доска — `.memory_bank/plans/README.md` § «Доска задач»: строка `| T-ID | план (§) | кто | … |`. Завершённые строки при своде
памяти удаляются, поэтому кроме нынешней доски читается история файла в git за `DNEY_ISTORII` дней (новые версии строк — первыми).
Нет доски — `None` (сводка блок задач не выводит); нет строки для ID — названия нет (сводка пишет «прочее (без метки)»).
"""
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

SLOV = 6
KOLONOK = 6  # у доски ≥ 6 колонок; реестр планов и таблица статусов в том же файле — 5 и 2
DNEY_ISTORII = 30
# «T-20261104-02…05, -07…08»: дата у первого ID, дальше — только номера той же даты.
ID_V_KLETKE = re.compile(r"(?:T-(\d{8}))?-(\d{2})(?:(?:…|\.\.)(\d{2}))?(?!\d)")
SLUG_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*")  # tamara: «tokeny-mashiny/1» (цикл — «/N»)
# Имя плана или задачи латиницей — владельцу ничего не говорит: «onb-01», «price-agreement-p6-3-package», «shkola-malyshi/1–2».
SLUG = re.compile(r"(?<![\w.])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?:/[\w–-]+)?(?![\w.-])")
SLUZHEBNOE = re.compile(r"(?<!\w)(?:по слову владельца|слово владельца|владелец|находка|без плана|бриф|"
                        r"TG\s*\d+(?:\s*[–,-]\s*\d+)*|часть\s+[А-ЯA-Z]|[ТП]\d+\w*(?:[–+…-][ТП]?\d+\w*)*|-\d{2})(?!\w)\s*:?",
                        re.IGNORECASE)
HVOST = re.compile(r"^(?:[а-яё]{1,2}|для|без|при|над|под|про|\W+)$")  # не кончать название предлогом или знаком


def idy(kletka: str) -> set[str]:
    """ID задач первой колонки строки доски: T-ID (диапазоны раскрываются) или имя задачи без «/цикла»."""
    out: set[str] = set()
    den = None
    for m in ID_V_KLETKE.finditer(kletka):
        den = m[1] or den
        if den is None:
            continue
        s = int(m[2])
        for n in range(s, max(s, int(m[3] or s)) + 1):
            out.add(f"T-{den}-{n:02d}")
    if not out and (m := SLUG_ID.search(kletka)):
        out.add(re.sub(r"/\d+$", "", m[0]))
    return out


def kod(m: re.Match[str]) -> str:
    """`lib/configurator/fromDemo.ts:planRooms` → «fromDemo»: от кода остаётся слово, а не дыра."""
    return re.sub(r"\.\w+$", "", m[1].split(":")[0].rstrip("/").split("/")[-1])


def chistka(s: str) -> str:
    s = SLUZHEBNOE.sub(" ", SLUG.sub(" ", s))
    s = re.sub(r"\s*→\s*(?=[,.:;—–]|$)", " ", s)
    s = re.sub(r"\s+([,.:;])", r"\1", s)
    s = re.sub(r"([,:;—–])(?:\s*[,:;—–])+", r"\1", s)
    return re.sub(r"\s+", " ", s).strip(" ,.:;—–-+→")


def korotko(plan: str) -> str:
    """«onb-11 часть А: `fromDemo.ts` по комнатам (гостиная без изменений)» → «FromDemo по комнатам: гостиная без изменений»."""
    t = re.sub(r"`([^`]*)`", kod, plan)
    osnova = chistka(re.sub(r"\([^()]*\)", " ", t))
    skobki = chistka(" ".join(re.findall(r"\(([^()]*)\)", t)))
    if len(osnova.split()) < 3 and skobki:
        osnova = f"{osnova}: {skobki}" if osnova else skobki
    slova = osnova.split()
    obrezano = len(slova) > SLOV
    slova = slova[:SLOV]
    while len(slova) > 1 and HVOST.match(slova[-1].strip(",.:;").lower() or slova[-1]):
        slova.pop()
        obrezano = True
    tekst = " ".join(slova).strip(" ,.:;—–-+→")
    if not tekst:
        return ""
    return tekst[0].upper() + tekst[1:] + ("…" if obrezano else "")


def iz_strok(stroki: list[str], out: dict[str, str]) -> None:
    """Строки доски → `out`; известный ID не перезаписывается (первым идёт более свежее).

    Прочие таблицы файла (реестр планов, статусы) — с меньшим числом колонок, пропускаются, как и шапка и разделитель."""
    for s in stroki:
        kletki = s.strip().strip("|").split("|")
        pervaya = kletki[0].strip()
        if len(kletki) < KOLONOK or pervaya.lower() in ("t-id", "id") or set(pervaya) <= set("-: "):
            continue
        nazv = korotko(kletki[1])
        for i in idy(kletki[0]) if nazv else ():
            out.setdefault(i, nazv)


def nazvaniya(doska: Path, den: date) -> dict[str, str] | None:
    if not doska.is_file():
        return None
    out: dict[str, str] = {}
    iz_strok(doska.read_text(encoding="utf-8").splitlines(), out)
    try:
        r = subprocess.run(["git", "-C", str(doska.parent), "log", "-p", "--format=",
                            f"--since={den - timedelta(days=DNEY_ISTORII)}", "--", doska.name],
                           capture_output=True, text=True, timeout=15, check=False)
        iz_strok([s[1:] for s in r.stdout.splitlines() if s.startswith("+|")], out)
    except (OSError, subprocess.TimeoutExpired):
        pass  # нет git или долго — названия только с нынешней доски
    return out
