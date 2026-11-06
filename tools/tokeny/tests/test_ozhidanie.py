"""Машина без выгрузки до её таймера — «выгрузка в ЧЧ:ММ», а не «нет данных» (T-20261106-68): владелец в 06:13
по Лондону спросил /tokeny и увидел «нет данных», хотя выгрузки машин приходят по таймерам в 07:10–07:30. Время — из таймера машины
(поле `taymer` её выгрузки, своя машина — systemd), не зашито; таймер прошёл, а файла нет — «выгрузка не пришла»."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tokeny

DEN = date(2026, 11, 5)


def zafiksirovat(monkeypatch: pytest.MonkeyPatch, t: datetime) -> None:
    class Seychas(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # noqa: ARG003 — время теста всегда UTC
            return t

    monkeypatch.setattr(tokeny, "datetime", Seychas)


def vygruzka(papka: Path, mashina: str, den: date, taymer: str | None, otvetov: int = 0) -> Path:
    stroki = []
    for i in range(otvetov):
        chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": 1_000_000}
        stroki.append(tokeny.v_slovar(tokeny.Stroka(f"s-{mashina}", "f.jsonl", f"m-{mashina}-{i}", "r", f"u{i}",
                                                    datetime(den.year, den.month, den.day, 10, tzinfo=UTC),
                                                    "claude-opus-5-5", chisla)))
    telo: dict[str, object] = {"skhema": tokeny.SKHEMA, "proekt": "remlab", "istochnik": mashina,
                               "period": {"s": den.isoformat(), "po": den.isoformat()}, "sverka": True,
                               "stroki": stroki}
    if taymer is not None:
        telo["taymer"] = taymer
    put = papka / f"{mashina}-{den.isoformat()}.json"
    put.write_text(json.dumps(telo), encoding="utf-8")
    return put


def test_ozhidanie_do_taymera_idet_posle_i_leto() -> None:
    """Три случая и запас на саму выгрузку (`TimeoutStartSec` юнита — 30 мин); летом таймер по Лондону = UTC+1."""
    z = tokeny.ozhidanie
    assert z(DEN, "07:20", datetime(2026, 11, 6, 6, 13, tzinfo=UTC)) == "выгрузка в 07:20 (по Лондону)"
    assert z(DEN, "07:20", datetime(2026, 11, 6, 7, 25, tzinfo=UTC)) == "выгрузка идёт с 07:20 (по Лондону)"
    assert z(DEN, "07:20", datetime(2026, 11, 6, 7, 51, tzinfo=UTC)) == "выгрузка не пришла (ждали 07:20)"
    assert z(DEN, "07:20", datetime(2026, 11, 9, 9, 0, tzinfo=UTC)) == "выгрузка не пришла (ждали 6 ноября в 07:20)"
    assert z(DEN, "07:20", datetime(2026, 11, 5, 20, 0, tzinfo=UTC)) == "выгрузка завтра в 07:20 (по Лондону)"
    leto = date(2026, 7, 1)  # 07:10 по Лондону = 06:10 UTC
    assert z(leto, "07:10", datetime(2026, 7, 2, 6, 5, tzinfo=UTC)) == "выгрузка в 07:10 (по Лондону)"
    assert z(leto, "07:10", datetime(2026, 7, 2, 6, 41, tzinfo=UTC)) == "выгрузка не пришла (ждали 07:10)"
    assert z(DEN, None, datetime(2026, 11, 6, 6, 13, tzinfo=UTC)) is None  # время неизвестно — прежнее «нет данных»


def test_svodka_do_taymera_posle_taymera_i_fayl_est(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    """07:15 по Лондону: pakardev выгрузил (файл есть — его $ в строке машин), algor ждём в 07:20 (таймер впереди),
    у common таймер 06:30 прошёл больше чем на 30 мин, а файла нет — сбой. Время таймеров — из их прошлых выгрузок."""
    korni = tmp_path / "igor"
    papka = korni / "remlab" / "data" / "logs" / "tokeny"
    papka.mkdir(parents=True)
    monkeypatch.setattr(tokeny, "KORNI", korni)
    monkeypatch.setattr("socket.gethostname", lambda: "pakardev")
    monkeypatch.setenv("TOKENY_TAYMER", "07:10")  # своя машина — таймер systemd
    zafiksirovat(monkeypatch, datetime(2026, 11, 6, 7, 15, tzinfo=UTC))
    vygruzka(papka, "algor", date(2026, 11, 4), "07:20")
    vygruzka(papka, "common", date(2026, 11, 4), "06:30")
    svoya = vygruzka(papka, "pakardev", DEN, "07:10", otvetov=1)
    assert tokeny.main(["--proekt", "remlab", "--sobrat", str(svoya), "--svodka", "--ozhidaem", "common,algor,pakardev",
                        "--papka-vygruzok", str(papka), "--zamery", "", "--doska", "",
                        "--limit", str(tmp_path / "net.jsonl"), "--koren", str(tmp_path / "net")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Токены Claude — remlab, 5 ноября")
    assert "По машинам: pakardev $4,00 (1 отв.)." in out
    assert ("Нет выгрузки за 5 ноября: algor — выгрузка в 07:20 (по Лондону); "
            "common — выгрузка не пришла (ждали 06:30).") in out
    assert not [s for s in out if "нет данных" in s.lower() and not s.startswith(("На 1 % недели", "Память:"))]
    nedelya = next(s for s in out if s.startswith("Неделя учёток"))
    assert nedelya.startswith("Неделя учёток (время по Лондону): algor — выгрузка в 07:20 (по Лондону); "
                              "common — выгрузка не пришла (ждали 06:30); pakardev — нет замера")
    na_procent = next(s for s in out if s.startswith("На 1 % недели"))
    assert "algor — выгрузка в 07:20 (по Лондону), common — выгрузка не пришла (ждали 06:30), " \
           "pakardev — пока нет данных" in na_procent  # у pakardev выгрузка есть, ступенек в ней нет


def test_vremya_neizvestno_prezhnie_slova(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """Выгрузки машины прежнего вида (без `taymer`) и таймера нет — как раньше: «нет данных»."""
    papka = tmp_path / "v"
    papka.mkdir()
    vygruzka(papka, "algor", date(2026, 11, 4), None)
    svoya = vygruzka(papka, "pakardev", DEN, None, otvetov=1)
    monkeypatch.setattr("socket.gethostname", lambda: "pakardev")
    zafiksirovat(monkeypatch, datetime(2026, 11, 6, 6, 13, tzinfo=UTC))
    assert tokeny.main(["--proekt", "remlab", "--sobrat", str(svoya), "--svodka", "--ozhidaem", "algor,pakardev",
                        "--papka-vygruzok", str(papka), "--zamery", "", "--doska", "",
                        "--limit", str(tmp_path / "net.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "Нет данных: algor (выгрузки за 5 ноября нет)." in out
    assert "algor — нет данных с algor" in out


def test_vygruzka_pishet_taymer_mashiny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Выгрузка кладёт время таймера своей машины — по нему сводка на любой машине знает, когда её ждать."""
    papka = tmp_path / "projects" / "-home-pakar-igor-remlab"
    papka.mkdir(parents=True)
    (papka / "s1.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("TOKENY_TAYMER", "07:20")
    vyhod = tmp_path / "algor.json"
    assert tokeny.main(["--proekt", "remlab", "--koren", str(tmp_path / "projects"), "--papka", str(papka),
                        "--limit", str(tmp_path / "net.jsonl"), "--fazy", str(tmp_path / "net.tsv"),
                        "--s", "2026-11-05", "--po", "2026-11-05", "--json", str(vyhod)]) == 0
    assert json.loads(vyhod.read_text(encoding="utf-8"))["taymer"] == "07:20"


def test_moy_taymer_iz_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Таймер проекта; прежнее имя без проекта — только если оно запускает выгрузку этого проекта."""
    monkeypatch.delenv("TOKENY_TAYMER")
    svoystva = {("tokeny-vygruzka.service", "ExecStart"): "{ path=/home/pakar/igor/tamara/tools/tokeny/vygruzit.sh ; }",
                ("tokeny-vygruzka.timer", "TimersCalendar"):
                    "{ OnCalendar=*-*-* 07:30:00 Europe/London ; next_elapse=Fri 2026-11-06 07:30:00 UTC }",
                ("tokeny-vygruzka-remlab.timer", "TimersCalendar"):
                    "{ OnCalendar=*-*-* 07:10:00 Europe/London ; next_elapse=Fri 2026-11-06 07:10:00 UTC }"}
    monkeypatch.setattr(tokeny, "systemd_svoystvo", lambda y, s: svoystva.get((y, s), ""))
    assert tokeny.moy_taymer("remlab") == "07:10"
    assert tokeny.moy_taymer("tamara") == "07:30"  # стоит под прежним именем
    assert tokeny.moy_taymer("sup2-repo") is None  # чужой таймер прежнего имени не берём
