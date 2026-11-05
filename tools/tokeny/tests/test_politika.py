"""Модуль кита `tokeny` (политика токенов, 05.11.2026): % недели учётки по журналу statusline, токены по машинам,
«нет данных с <машина>», проект — параметр (соседние проекты не смешиваются), `svodka.sh --proekt` с любой машины."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import tokeny

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
OKNO = int((T0 + timedelta(days=3)).timestamp())  # сброс недели через 3 дня
DEN = "2026-11-04"


def zapis(minuty: int, sessiya: str, procent: float | None, resets: int = OKNO, api_ms: int = 0) -> str:
    rl = {"seven_day": {"used_percentage": procent, "resets_at": resets}} if procent is not None else None
    return json.dumps({"t": (T0 + timedelta(minutes=minuty)).strftime("%Y-%m-%dT%H:%M:%SZ"), "session": sessiya,
                       "rl": rl, "cost": {"total_api_duration_ms": api_ms}}) + "\n"


def test_nedelya_maksimum_okna_a_ne_otstavshaya_sessiya(tmp_path: Path) -> None:
    """05.11 на common: простаивающие сессии показывают 41 и 57 %, живая — 85: процент учётки — 85, замер — когда 85
    впервые пришло, ответ модели — последний рост времени API; точка прошлого окна не мешает."""
    put = tmp_path / "usage-log.jsonl"
    put.write_text("".join([
        zapis(0, "staraya", 99, resets=OKNO - 7 * 86400),  # прошлое окно
        zapis(1, "prostoy", 41, api_ms=500), zapis(2, "zhivaya", 84, api_ms=1000),
        zapis(3, "prostoy", 41, api_ms=500), zapis(4, "zhivaya", 85, api_ms=2000),
        zapis(5, "zhivaya", 85, api_ms=2000), zapis(6, "prostoy", 57, api_ms=500),
        zapis(7, "bez", None), "{oborvano",
    ]), encoding="utf-8")
    n = tokeny.nedelya_seychas(put, T0 + timedelta(hours=1))
    assert n == {"procent": 85.0, "sbros": "2026-11-08T10:00:00Z", "zamer": "2026-11-05T10:04:00Z",
                 "otvet": "2026-11-05T10:04:00Z", "posledniy": "2026-11-05T10:06:00Z", "sbroshen": False}


def test_nedelya_okno_konchilos_i_net_fayla(tmp_path: Path) -> None:
    """pakardev: журнал оборвался 27.10, окно с тех пор сброшено — процент неизвестен, а не «100 %»."""
    put = tmp_path / "usage-log.jsonl"
    put.write_text(zapis(0, "s", 100, resets=int(T0.timestamp()) - 3600), encoding="utf-8")
    assert tokeny.nedelya_seychas(put, T0)["sbroshen"] is True  # type: ignore[index]
    assert tokeny.nedelya_seychas(tmp_path / "net.jsonl", T0) is None


def test_nedelya_otvet_proshlogo_okna_ne_v_schet(tmp_path: Path) -> None:
    """05.11 pakardev: ответ модели был 18.10 (прошлое окно), новая сессия без ответов дала 15 % нового окна —
    «ответ модели» не показываем, а не «18.10»."""
    put = tmp_path / "usage-log.jsonl"
    staroe = OKNO - 7 * 86400
    put.write_text(zapis(-20000, "staraya", 50, resets=staroe, api_ms=1) + zapis(-19999, "staraya", 51, resets=staroe,
                   api_ms=2) + zapis(0, "novaya", 15), encoding="utf-8")
    n = tokeny.nedelya_seychas(put, T0)
    assert n is not None and n["procent"] == 15.0 and n["otvet"] is None


def vygruzka(tmp_path: Path, mashina: str, nedelya: dict[str, object] | None, vvod: int = 1_000_000) -> str:
    chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": vvod, "kesh_chtenie": 2 * vvod}
    s = tokeny.Stroka(f"s-{mashina}", "f.jsonl", f"m-{mashina}", "r", "u", datetime(2026, 11, 4, 10, tzinfo=UTC),
                      "claude-opus-5-5", chisla)
    telo: dict[str, object] = {"skhema": tokeny.SKHEMA, "proekt": "remlab", "istochnik": mashina,
                               "period": {"s": DEN, "po": DEN}, "sverka": True, "stroki": [tokeny.v_slovar(s)]}
    if nedelya is not None:
        telo["nedelya"] = nedelya
    put = tmp_path / f"{mashina}-{DEN}.json"
    put.write_text(json.dumps(telo), encoding="utf-8")
    return str(put)


def test_svodka_tokeny_i_nedelya_po_mashinam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    """Сводка по трём машинам: токены и % недели каждой учётки; машины без выгрузки — «нет данных с <машина>»;
    учётка без свежего замера — сказано, почему."""
    monkeypatch.setattr("socket.gethostname", lambda: "nichya")  # не своя машина: живой журнал не подмешивается
    puti = [vygruzka(tmp_path, "algor", {"procent": 11.0, "sbros": "2026-11-09T08:00:00Z", "zamer": "2026-11-05T07:20:00Z",
                                         "otvet": "2026-11-05T07:25:00Z", "posledniy": "2026-11-05T07:29:00Z",
                                         "sbroshen": False}),
            vygruzka(tmp_path, "pakardev", {"procent": 100.0, "sbros": "2026-10-29T10:00:00Z",
                                            "zamer": "2026-10-27T06:00:00Z", "otvet": None,
                                            "posledniy": "2026-10-27T06:21:00Z", "sbroshen": True}, vvod=0)]
    assert tokeny.main(["--proekt", "remlab", "--sobrat", *puti, "--svodka", "--data", DEN,
                        "--ozhidaem", "common,algor,pakardev", "--zamery", "",
                        "--limit", str(tmp_path / "net.jsonl")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Токены Claude — remlab, 4 ноября, среда")
    assert "Нет данных: common (выгрузки за 4 ноября нет)." in out
    assert "Токены по машинам: algor 3,0 млн (чтение кэша 2,0 млн, ответ 0,0 млн), pakardev 0,0 млн (чтение кэша " \
           "0,0 млн, ответ 0,0 млн)." in out
    nedelya = next(s for s in out if s.startswith("Неделя учёток"))
    assert nedelya == ("Неделя учёток (время по Лондону): algor 11 % (на 05.11 07:20, ответ модели 05.11 07:25; "
                       "сброс 09.11 08:00); common — нет данных с common; pakardev — нет свежего замера (последний "
                       "27.10 06:21, окно сброшено 29.10 10:00; нужна CLI-сессия со statusline).")


def test_svoya_mashina_beret_zhivoy_zhurnal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    """Сводка на машине — её % недели из живого журнала, если он свежее ночной выгрузки."""
    monkeypatch.setattr("socket.gethostname", lambda: "algor")
    staryy = {"procent": 5.0, "sbros": "2099-01-01T00:00:00Z", "zamer": "2026-11-05T07:00:00Z", "otvet": None,
              "posledniy": "2026-11-05T07:00:00Z", "sbroshen": False}
    put = vygruzka(tmp_path, "algor", staryy)
    zhurnal = tmp_path / "usage-log.jsonl"
    zhurnal.write_text(zapis(0, "a", 7, resets=4_000_000_000, api_ms=1) + zapis(1, "a", 8, resets=4_000_000_000,
                                                                                    api_ms=2), encoding="utf-8")
    assert tokeny.main(["--proekt", "remlab", "--sobrat", put, "--svodka", "--data", DEN, "--ozhidaem", "algor",
                        "--zamery", "", "--limit", str(zhurnal)]) == 0
    assert any(s.startswith("Неделя учёток (время по Лондону): algor 8 % (на 05.11 10:01")
               for s in capsys.readouterr().out.splitlines())


def test_proekt_ne_zabiraet_zhurnaly_soseda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Проект — параметр: «sup2» не считает журналы соседа «sup2-repo», а свои worktree и рабочие копии — считает."""
    korni = tmp_path / "igor"
    for p in ("sup2", "sup2-repo"):
        (korni / p).mkdir(parents=True)
    monkeypatch.setattr(tokeny, "KORNI", korni)
    monkeypatch.setattr(tokeny, "PREFIKS", tokeny.imya_papki(str(korni)) + "-")
    koren = tmp_path / "projects"
    b = tokeny.PREFIKS
    for imya in ("sup2", "sup2--claude-worktrees-t1", "sup2-data-rabochaya-kopiya-x", "sup2-repo",
                 "sup2-repo--claude-worktrees-t2"):
        (koren / f"{b}{imya}").mkdir(parents=True)
    imena = lambda p: [x.name.removeprefix(b) for x in tokeny.papki_proekta(koren, p)]  # noqa: E731
    assert imena("sup2") == ["sup2", "sup2--claude-worktrees-t1", "sup2-data-rabochaya-kopiya-x"]
    assert imena("sup2-repo") == ["sup2-repo", "sup2-repo--claude-worktrees-t2"]


def test_svodka_sh_proekt_s_lyuboy_mashiny(tmp_path: Path) -> None:
    """`svodka.sh --proekt X` — выгрузки и файл сводки в папке проекта X; папки данных сами не попадают в git."""
    korni = tmp_path / "igor"
    papka = korni / "remlab" / "data" / "logs" / "tokeny"
    papka.mkdir(parents=True)
    (papka / f"algor-{DEN}.json").write_text(Path(vygruzka(tmp_path, "algor", None)).read_text(), encoding="utf-8")
    skript = Path(tokeny.__file__).with_name("svodka.sh")
    env = os.environ | {"TOKENY_PROEKTY": str(korni), "TOKENY_MASHINY": "algor,common", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(skript), "--proekt", "remlab", DEN], capture_output=True, text=True, env=env,
                       check=False)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("Токены Claude — remlab, 4 ноября")
    assert "Нет данных: common (выгрузки за 4 ноября нет)." in r.stdout
    fayl = korni / "remlab" / "data" / "otchety" / "tokeny" / f"svodka-{DEN}.txt"
    assert fayl.read_text(encoding="utf-8") == r.stdout
    assert (fayl.parent / ".gitignore").read_text() == "*\n"
    assert "(выгрузок: 1, код 0)" in r.stderr
    bad = subprocess.run(["bash", str(skript), "--proekt", "../x"], capture_output=True, text=True, env=env, check=False)
    assert bad.returncode == 2
