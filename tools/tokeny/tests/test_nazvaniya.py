"""Сводка для владельца (05.11.2026): задачи — названием с доски, а не T-ID; «На 1 % недели» — млн взвешенных токенов
по учётке каждой машины. Только поведение, которое владелец видит в тексте."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import nazvaniya
import tokeny

DEN = date(2026, 11, 4)
SHAPKA = ["| T-ID | план (§) | кто | журнал | состояние | дальше |", "|---|---|---|---|---|---|"]


def stroka(zadacha: str | None, mashina: str = "", usd: float = 4.0, limit: float = 0.0) -> tokeny.Stroka:
    """`usd` долларов Opus 5.5 вводом (1 млн входа = $4 = 1 млн взвешенных токенов)."""
    chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": round(usd / 4 * 1e6)}
    klyuch = f"{zadacha}-{mashina}-{usd}"
    s = tokeny.Stroka("sess0001", "f.jsonl", f"m-{klyuch}", "r", f"u-{klyuch}",
                      datetime(2026, 11, 4, 12, tzinfo=UTC), "claude-opus-5-5", chisla)
    s.razmetit("ispolnitel", ("realizaciya", zadacha, 1, False))
    s.mashina, s.limit = mashina, limit
    return s


def test_nazvanie_korotko_bez_sluzhebnogo() -> None:
    k = nazvaniya.korotko
    assert k("conv-14 глубина угловых диванов divan.ru (Т1–Т5)") == "Глубина угловых диванов divan.ru"
    assert k("onb-01 Фигма Т1+Т2 (компоненты опроса, экраны RU телефон)") == "Фигма: компоненты опроса, экраны RU телефон"
    assert k("слово владельца TG 680–682 — бриф `_intake/zadaniya/tokeny-mashiny-1.md`: токены со всех машин") \
        == "Токены со всех машин"
    assert k("утренняя сводка refresh_daily уходит пустой с 21.10") == "Утренняя сводка refresh_daily уходит пустой…"


def test_idy_diapazony_i_imena_zadach() -> None:
    assert nazvaniya.idy("T-20261104-02…04, -07") == {"T-20261104-02", "T-20261104-03", "T-20261104-04",
                                                       "T-20261104-07"}
    assert nazvaniya.idy(" tokeny-mashiny/1 ") == {"tokeny-mashiny"}
    assert nazvaniya.idy("T-20261102-01/1") == {"T-20261102-01"}  # sup2: с циклом
    assert nazvaniya.idy("T-20261104-02…05, -07…08") == {f"T-20261104-0{n}" for n in (2, 3, 4, 5, 7, 8)}


def test_nazvaniya_s_doski_i_iz_istorii_git(tmp_path: Path) -> None:
    """Завершённую строку свод памяти удаляет — название берётся из истории доски; прочие таблицы файла — мимо."""
    doska = tmp_path / "README.md"
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    staraya = "| T-20261104-06 | conv-15 глубина с чертежа (Т1 бесплатно) | р1 | common | отчёт | — |"
    doska.write_text("\n".join(["| slug | Название | status | created | updated |", "| x-1 | Не доска | a | b | c |",
                                *SHAPKA, staraya]) + "\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "1"], check=True)
    doska.write_text("\n".join([*SHAPKA, "| T-20261105-25/1 | сводка токенов: названия задач | р7 | p | — | — |"]),
                     encoding="utf-8")
    n = nazvaniya.nazvaniya(doska, DEN)
    assert n == {"T-20261104-06": "Глубина с чертежа", "T-20261105-25": "Сводка токенов: названия задач"}
    assert nazvaniya.nazvaniya(tmp_path / "net.md", DEN) is None


def test_svodka_zadachi_nazvaniem_bez_id_i_bez_doski_bez_bloka() -> None:
    d = [stroka("T-20261104-06", usd=3), stroka("T-20261104-99", usd=2), stroka("T-20261104-98", usd=1)]
    s = tokeny.svodka(d, "remlab", DEN, nazv={"T-20261104-06": "Глубина с чертежа"})
    assert "1. Глубина с чертежа — $3,00, 50,0 % суток" in s
    assert "2. прочее (без метки) — $3,00, 50,0 % суток" in s
    assert "T-2026" not in s
    assert "Самые дорогие" not in tokeny.svodka(d, "remlab", DEN)  # проекта без доски — блока нет


def test_na_procent_nedeli_po_uchetkam() -> None:
    """algor: $40 = 10 млн взвешенных на 2 п.п. → 5,0 млн; common: 2 млн на 1 п.п.; pakardev: 0,5 п.п. —
    «пока 0,5 п.п. (рано считать)» (видно, что данные смотрели)."""
    d = [stroka("a", "algor", 40, 2.0), stroka("b", "common", 8, 1.0), stroka("c", "pakardev", 8, 0.5)]
    assert tokeny.stroka_na_procent(d, ["algor", "common", "pakardev"], 7) == [
        "На 1 % недели (за 7 дн., все проекты; токены взвешенные): algor 5,0 млн, common 2,0 млн, pakardev — пока "
        "0,5 п.п. (рано считать); выгоднее algor: в 2,5 раза больше, чем common."]
    assert tokeny.stroka_na_procent(d[:1] + d[2:], ["algor", "pakardev"])[0].endswith("сравнить пока не с чем.")
    assert tokeny.stroka_na_procent([stroka("a", "algor", 4)], ["algor"]) == []  # оценки лимита нет — строки нет


def test_baza_na_procent_vse_proekty_za_nedelyu(tmp_path: Path) -> None:
    """1 % — свойство учётки: строки всех проектов общей папки за 7 суток; восьмые сутки и чужой файл — мимо."""
    for proekt, den in (("remlab", DEN), ("tamara", DEN - timedelta(days=6)), ("tamara", DEN - timedelta(days=7))):
        papka = tmp_path / proekt / "data" / "logs" / "tokeny"
        papka.mkdir(parents=True, exist_ok=True)
        x = stroka(f"z-{den}", usd=4, limit=1.0)
        x.vremya = datetime(den.year, den.month, den.day, 12, tzinfo=UTC)
        (papka / f"algor-{den}.json").write_text(tokeny.vygruzka([x], proekt), encoding="utf-8")
    (tmp_path / "remlab" / "data" / "logs" / "tokeny" / f"common-{DEN}.json").write_text("{", encoding="utf-8")
    baza = tokeny.baza_na_procent(tmp_path, DEN)
    assert sorted(x.zadacha or "" for x in baza) == [f"z-{DEN - timedelta(days=6)}", f"z-{DEN}"]


def test_zhivoy_schet_segodnya_bez_dvoynogo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """05.11 pakardev: выгрузки за вчера ещё нет (она ночью), работа сегодня есть — «На 1 % недели» считает свои
    вчера и сегодня живым счётом журналов, а не «мало данных». Прирост 3 п.п. делится по цене между тремя ответами
    машины, в т.ч. проекта без учёта токенов (tamara). Ночная выгрузка за вчера заменяет живой счёт — не задваивает."""
    monkeypatch.setattr("socket.gethostname", lambda: "pakardev")
    korni, koren = tmp_path / "igor", tmp_path / "projects"
    tokeny_papka = korni / "remlab" / "data" / "logs" / "tokeny"
    tokeny_papka.mkdir(parents=True)
    (korni / "tamara").mkdir()
    monkeypatch.setattr(tokeny, "KORNI", korni)
    monkeypatch.setattr(tokeny, "PREFIKS", tokeny.imya_papki(str(korni)) + "-")
    seychas = datetime.now(UTC) - timedelta(seconds=1)
    segodnya = tokeny.london(seychas)
    vchera = segodnya - timedelta(days=1)
    t_vchera = datetime(vchera.year, vchera.month, vchera.day, 12, tzinfo=UTC)

    def otvet(t: datetime, n: str) -> str:
        return json.dumps({"type": "assistant", "timestamp": t.isoformat().replace("+00:00", "Z"), "uuid": f"u{n}",
                           "requestId": f"r{n}", "message": {"id": f"m{n}", "model": "claude-opus-5-5",
                                                             "usage": {"input_tokens": 1_000_000}}}) + "\n"

    for proekt, stroki in (("remlab", otvet(t_vchera, "1") + otvet(seychas, "2")), ("tamara", otvet(seychas, "3"))):
        (koren / f"{tokeny.PREFIKS}{proekt}").mkdir(parents=True)
        (koren / f"{tokeny.PREFIKS}{proekt}" / "s1.jsonl").write_text(stroki, encoding="utf-8")
    okno = int((seychas + timedelta(days=3)).timestamp())
    limit = tmp_path / "usage-log.jsonl"
    limit.write_text("".join(json.dumps({"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": "s",
                                         "rl": {"seven_day": {"used_percentage": p, "resets_at": okno}}}) + "\n"
                             for t, p in ((t_vchera - timedelta(hours=1), 10), (seychas + timedelta(seconds=1), 13))),
                     encoding="utf-8")
    argv = ["--proekt", "remlab", "--sobrat", "--svodka", "--ozhidaem", "pakardev", "--zamery", "", "--doska", "",
            "--koren", str(koren), "--limit", str(limit)]

    def na_procent() -> str:
        assert tokeny.main(argv) == 0
        return next(s for s in capsys.readouterr().out.splitlines() if s.startswith("На 1 %"))

    ozhidaem = (f"На 1 % недели (за 7 дн. по {segodnya:%d.%m}, все проекты; токены взвешенные): pakardev 1,0 млн; "
                "сравнить пока не с чем.")
    assert na_procent() == ozhidaem  # 2 млн взвешенных remlab на 2 п.п.; tamara — в доле, но не в учёте
    zhivye = tokeny.zhivye_po_proektam(korni, koren, limit, vchera)
    noch = [x for x in zhivye["remlab"] if tokeny.london(x.vremya) == vchera]
    (tokeny_papka / f"pakardev-{vchera}.json").write_text(tokeny.vygruzka(noch, "remlab"), encoding="utf-8")
    assert na_procent() == ozhidaem  # ночная выгрузка за вчера есть — живой «вчера» не добавлен второй раз
    baza = tokeny.baza_na_procent(korni, segodnya, zhivye=tokeny.zhivye_po_proektam(korni, koren, limit, vchera))
    assert sorted(x.msg_id or "" for x in baza) == ["m1", "m2"]
    assert tokeny.stroka_na_procent([x for x in baza if x.msg_id == "m2"], ["pakardev", "algor"], 7) == [
        "На 1 % недели (за 7 дн., все проекты; токены взвешенные): algor — пока 0,0 п.п. (рано считать), "
        "pakardev 1,0 млн; сравнить пока не с чем."]
