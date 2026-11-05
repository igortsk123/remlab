"""Цена памяти проекта по журналам Claude Code (`tokeny-mashiny/1`, схема — замеры задачи).

Чтение памяти — результат `Read`/`Grep`/`Glob` с путём в `.memory_bank/` и `Bash` с командой чтения
по `.memory_bank/` (без записи в него). Токены — символы результата / `SIMVOLOV_NA_TOKEN` (оценка:
в журнале нет токенов отдельного результата). Цена — по прайсу модели ответа, который результат
получил: вход — запись кэша (5 мин или 1 ч — по большей части записи этого ответа); перенос —
каждый следующий ответ того же файла журнала до сжатия (`compact_boundary`) читает результат из
кэша. Чтение и вход относятся к суткам ответа, получившего результат, перенос — к суткам ответа,
который его несёт (сессия через полночь переносит вчерашние чтения в сегодня; сумма за дни та же).
Не считаются: ответы `<synthetic>` (ошибка API, не вызов) и повтор ответа API (та же пара
`message.id`+`requestId`) — и в одном файле, и в копии истории другого файла (`otvety` общий).
Tier 0 (CLAUDE.md, INDEX, правила без `paths:`) в журнал не пишется: справочно — число стартов
файлов журнала и сжатий за сутки.

Только чтение журналов; результат — числа, без текста результатов.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields
from pathlib import Path

# Калибровка 01.11.2026 по журналам common: прирост контекста между соседними ответами, когда между
# ними один результат `Read` (память: 50 случаев, медиана 1,95, квартили 1,81–2,05; код — 2,05).
SIMVOLOV_NA_TOKEN = 1.95
PUT_PAMYATI = re.compile(r"\.memory_bank/")
CHTENIE_BASH = re.compile(r"(?<![\w.-])(?:cat|sed|head|tail|grep|rg|wc|ls|awk|less)(?![\w-])")
ZAPIS_BASH = re.compile(r">>?\s*['\"]?[^\s'\"]*\.memory_bank/|(?<![\w-])tee(?![\w-])|sed\s+-i"
                        r"|(?<![\w-])(?:rm|mv|cp)\s")
PUTI_INSTRUMENTA = {"Read": ("file_path",), "Grep": ("path",), "Glob": ("path", "pattern")}
SINTETICHESKIY = "<synthetic>"  # ответ-заглушка Claude Code без вызова API
Cena = tuple[float, float, float, float, float]  # вход, запись 5 мин, запись 1 ч, чтение кэша, ответ


@dataclass(slots=True)
class Pamyat:
    chteniy: int = 0
    simvoly: int = 0  # результаты чтений памяти
    simvoly_vse: int = 0  # все результаты инструментов
    perenos: float = 0.0  # токенов чтения кэша: память в контексте последующих ответов
    usd_vhod: float = 0.0
    usd_perenos: float = 0.0
    starty: int = 0  # первые ответы файлов журнала и сжатия: Tier 0 входит заново

    def dobavit(self, d: Pamyat) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(d, f.name))

    def v_slovar(self) -> dict[str, object]:
        return {f.name: round(v, 6) if isinstance(v := getattr(self, f.name), float) else v
                for f in fields(self)}

    @classmethod
    def iz_slovarya(cls, d: dict[str, object]) -> Pamyat:
        p = cls()
        for f in fields(cls):
            v = d.get(f.name)
            if isinstance(v, int | float) and not isinstance(v, bool):
                setattr(p, f.name, type(getattr(p, f.name))(v))
        return p

    @property
    def tokeny(self) -> float:
        return self.simvoly / SIMVOLOV_NA_TOKEN

    @property
    def tokeny_vse(self) -> float:
        return self.simvoly_vse / SIMVOLOV_NA_TOKEN

    @property
    def usd(self) -> float:
        return self.usd_vhod + self.usd_perenos


def slovar(v: object) -> dict[str, object]:
    return v if isinstance(v, dict) else {}


def chislo(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def dlina(soderzhimoe: object) -> int:
    """Символы текста результата инструмента (картинки не считаются)."""
    if isinstance(soderzhimoe, str):
        return len(soderzhimoe)
    if isinstance(soderzhimoe, list):
        return sum(len(t) for x in soderzhimoe if isinstance(t := slovar(x).get("text"), str))
    return 0


def chtenie_pamyati(imya: object, vvod: dict[str, object]) -> bool:
    if isinstance(imya, str) and imya in PUTI_INSTRUMENTA:  # у Grep `pattern` — текст, не путь
        return any(PUT_PAMYATI.search(str(vvod.get(k) or "")) for k in PUTI_INSTRUMENTA[imya])
    if imya == "Bash":
        kom = str(vvod.get("command") or "")
        return bool(PUT_PAMYATI.search(kom) and CHTENIE_BASH.search(kom)
                    and not ZAPIS_BASH.search(kom))
    return False


def cena_zapisi(u: dict[str, object], c: Cena) -> float:
    vsego = chislo(u.get("cache_creation_input_tokens"))
    k1h = chislo(slovar(u.get("cache_creation")).get("ephemeral_1h_input_tokens"))
    return c[2] if vsego and 2 * k1h >= vsego else c[1]


def pamyat_fayla(zapisi: Iterable[dict[str, object]], v_okne: Callable[[object], bool],
                 cena: Callable[[str], Cena],
                 otvety: set[tuple[str, str]] | None = None) -> Pamyat:
    """Чтения памяти одного файла журнала за сутки окна (`v_okne` — по `timestamp` записи).

    `otvety` — ответы API, уже посчитанные в других файлах (общий набор на все файлы машины):
    повтор не считается, но его результаты остаются в контексте файла."""
    p = Pamyat()
    pamyat_vyzova: dict[str, bool] = {}
    uvideno: set[str] = set()
    otvety = set() if otvety is None else otvety
    svoi = 0  # своих (не повторённых) ответов файла: первый — старт сессии
    novye: list[tuple[bool, int]] = []  # результаты после прошлого ответа: память ли, символы
    otkryto = 0.0  # токенов памяти в контексте
    for z in zapisi:
        if z.get("type") == "system" and z.get("subtype") == "compact_boundary":
            otkryto, novye = 0.0, []
            p.starty += v_okne(z.get("timestamp"))
            continue
        m = slovar(z.get("message"))
        soderzhimoe = m.get("content")
        for x in soderzhimoe if isinstance(soderzhimoe, list) else []:
            b = slovar(x)
            if b.get("type") == "tool_use":
                pamyat_vyzova[str(b.get("id"))] = chtenie_pamyati(b.get("name"),
                                                                  slovar(b.get("input")))
            elif b.get("type") == "tool_result" and (k := str(b.get("tool_use_id"))) not in uvideno:
                uvideno.add(k)
                novye.append((pamyat_vyzova.get(k, False), dlina(b.get("content"))))
        u = slovar(m.get("usage"))
        if z.get("type") != "assistant" or not u or m.get("model") == SINTETICHESKIY:
            continue
        klyuch = (str(m.get("id")), str(z.get("requestId")))
        povtor = klyuch in otvety  # тот же ответ API другой строкой или копией истории
        if not povtor and v_okne(z.get("timestamp")):
            c = cena(str(m.get("model") or ""))
            prishlo = sum(n for pam, n in novye if pam) / SIMVOLOV_NA_TOKEN
            p.starty += not svoi
            p.chteniy += sum(pam for pam, _ in novye)
            p.simvoly += sum(n for pam, n in novye if pam)
            p.simvoly_vse += sum(n for _, n in novye)
            p.usd_vhod += prishlo * cena_zapisi(u, c) / 1e6
            p.perenos += otkryto
            p.usd_perenos += otkryto * c[3] / 1e6
        otvety.add(klyuch)
        svoi += not povtor
        otkryto += sum(n for pam, n in novye if pam) / SIMVOLOV_NA_TOKEN
        novye = []
    return p


def tier0_simvolov(koren: Path) -> int:
    """Символы Tier 0: CLAUDE.md, INDEX и правила без `paths:` (грузятся в каждую сессию)."""
    puti = [koren / "CLAUDE.md", koren / ".memory_bank" / "INDEX.md"]
    puti += [p for p in sorted((koren / ".claude" / "rules").glob("*.md"))
             if "\npaths:" not in p.read_text(encoding="utf-8").split("\n---", 1)[0]]
    return sum(len(p.read_text(encoding="utf-8")) for p in puti if p.is_file())
