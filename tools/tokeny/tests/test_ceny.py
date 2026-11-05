"""Учёт токенов в $ по прайсу модели (`tokeny-ceny/1`) и доля недельного лимита: только регрессии
дефектов расчёта цены и лимита (аудит тестов 25.10 — утренняя сводка владельца); сброс окна
лимита — спорное, оставлено."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import tokeny

T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)  # 20.10 по Лондону
MLN = 1_000_000


def stroka(model: str, *, vvod: int = 0, chtenie: int = 0, vyvod: int = 0,
           segment: str = "realizaciya", rol: str = "ispolnitel", zadacha: str = "ab-cd",
           minuty: float = 0, msg: str = "m") -> tokeny.Stroka:
    chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {
        "vvod": vvod, "kesh_chtenie": chtenie, "vyvod": vyvod}
    s = tokeny.Stroka("sess0001", "f.jsonl", msg, "r", f"u-{msg}", T0 + timedelta(minutes=minuty),
                      model, chisla)
    s.razmetit(rol, (segment, zadacha, 1, False))
    return s


def test_chtenie_kesha_opus_5_5_vdvoe_deshevle_starogo_vesa() -> None:
    """Дефект: чтение кэша Opus 5.5 — $0,20 при входе $4 (×0,05), а не ×0,1."""
    chtenie = stroka("claude-opus-5-5", chtenie=MLN).stoimost()
    vvod = stroka("claude-opus-5-5", vvod=MLN).stoimost()
    assert chtenie == pytest.approx(0.20)
    assert vvod == pytest.approx(4.0)
    assert chtenie / vvod == pytest.approx(0.05)


def dve_modeli() -> list[tokeny.Stroka]:
    """A: Opus 5.5, 1 млн чтения кэша = $0,20; B: Fable 5.1, 10 тыс. вывода = $0,50.

    Старые веса дали бы A 100 000 и B 50 000 (2 : 1), по $ — наоборот (2 : 5)."""
    return [stroka("claude-opus-5-5", chtenie=MLN, zadacha="a-a", msg="A"),
            stroka("claude-fable-5-1", vyvod=10_000, segment="proverka", rol="vedushchiy",
                   zadacha="b-b", minuty=1, msg="B")]


def test_doli_i_limit_ot_dollarov() -> None:
    """Дефект: доли и лимит делились по взвешенным токенам, их нельзя складывать между моделями."""
    d = dve_modeli()
    assert tokeny.stoimost(d) == pytest.approx(0.70)
    s = tokeny.svodka(d, "tamara", T0.date(), nazv={"b-b": "Проверка сводки"}).strip().split("\n")
    assert s[2].startswith("Ведущий: планирование 0,0 %, проверка 71,4 %,")
    assert s[3].startswith("Исполнители: реализация 28,6 %,")
    assert s[-2:] == ["1. Проверка сводки — $0,5000, 71,4 % суток", "2. прочее (без метки) — $0,2000, 28,6 % суток"]
    tokeny.razdelit_limit(d, [(T0 - timedelta(minutes=1), T0 + timedelta(minutes=5), 7.0)])
    assert [round(x.limit, 9) for x in d] == [2.0, 5.0]


def test_limit_pustoy_interval_ne_teryaet_prirost(tmp_path: Path) -> None:
    """Сессия B отстала: её точка за секунду до прироста не обрезает интервал (было 26 п.п.)."""
    r = 1_793_000_000
    log = tmp_path / "usage-log.jsonl"
    log.write_text("".join(json.dumps({
        "t": (T0 + timedelta(minutes=m)).isoformat().replace("+00:00", "Z"), "session": "s",
        "model": "Opus", "rl": {"five_hour": {"used_percentage": 50, "resets_at": 1},
                                "seven_day": {"used_percentage": p, "resets_at": r}}}) + "\n"
        for m, p in ((0, 10), (29.98, 10), (30, 11))), encoding="utf-8")
    prirosty = tokeny.prirosty_limita(tokeny.tochki_limita(log))
    assert prirosty == [(T0, T0 + timedelta(minutes=30), 1.0)]
    otvety = [stroka("x", vvod=10, minuty=i, msg=f"m{i}") for i in (5, 15)]
    assert [o for _, _, o in tokeny.razdelit_limit(otvety, prirosty)] == [1.0]
    assert [x.limit for x in otvety] == [0.5, 0.5]


# ── сброс окна лимита (из unit/test_tokeny.py; спорное — оставлено, решение ведущего 6) ─────────

def vr(minuty: float) -> str:
    return (T0 + timedelta(minutes=minuty)).isoformat().replace("+00:00", "Z")


def zapisat(put: Path, zapisi: list[dict[str, object]], *, hvost: str = "") -> None:
    put.write_text("".join(json.dumps(z) + "\n" for z in zapisi) + hvost, encoding="utf-8")


def tochka(m: float, procent: int | None, resets: int) -> dict[str, object]:
    return {"t": vr(m), "session": "s", "model": "Opus",
            "rl": {"five_hour": {"used_percentage": 50, "resets_at": 1},
                   "seven_day": {"used_percentage": procent, "resets_at": resets}}}


def test_limit_sbros_okna_i_ustarevshie_pokazaniya(tmp_path: Path) -> None:
    r1, r2 = 1_793_000_000, 1_793_604_800  # окна неделя к неделе
    log = tmp_path / "usage-log.jsonl"
    zapisat(log, [tochka(0, 5, r1), tochka(10, 7, r1),
                  tochka(20, 6, r1 + 30),  # устаревшее показание; resets_at плавает в пределах часа
                  tochka(30, 1, r2),  # сброс окна: +1 от нуля, а не −5
                  tochka(40, 9, r1),  # показание старого окна после сброса — пропуск
                  tochka(45, None, r2),  # нет процента — пропуск
                  tochka(50, 3, r2), tochka(60, 4, r2)], hvost='{"t": ')
    prirosty = tokeny.prirosty_limita(tokeny.tochki_limita(log))

    def m(minuty: int) -> datetime:
        return T0 + timedelta(minutes=minuty)

    # интервал прироста — от прошлого прироста: точка 20 (устаревшая, 6) его не обрезает
    assert prirosty == [(m(0), m(10), 2.0), (m(10), m(30), 1.0), (m(30), m(50), 2.0),
                        (m(50), m(60), 1.0)]

    def s(minuty: int, vvod: int, sessiya: str) -> tokeny.Stroka:
        chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": vvod}
        return tokeny.Stroka(sessiya, "f", f"m{minuty}", "r", "u", m(minuty), "x", chisla)

    nashi = [s(5, 100, "tamara"), s(25, 50, "tamara"), s(45, 10, "tamara"), s(10, 1, "tamara")]
    chuzhie = [s(8, 299, "remlab"), s(35, 30, "remlab")]  # другой проект той же учётки
    rozdano = tokeny.razdelit_limit(nashi + chuzhie, prirosty)
    # (0,10]: 2 п.п. на 100+299+1; (20,30]: 1 на 50; (30,50]: 2 на 10+30; (50,60]: ответов нет
    assert [round(x.limit, 9) for x in nashi] == [0.5, 1.0, 0.5, 0.005]
    assert [round(x.limit, 9) for x in chuzhie] == [1.495, 1.5]
    assert [(d, o) for _, d, o in rozdano] == [(2.0, 2.0), (1.0, 1.0), (2.0, 2.0), (1.0, 0.0)]
    den = date(2026, 10, 20)
    tekst = tokeny.razdel_limita(nashi, tokeny.Limit(rozdano, chuzhie, []), den, den)
    assert "Прирост лимита учётки этой машины за период: 6,0 п.п." in tekst
    for stroka in ("| этот проект | 2,0 | 33,4 % |",
                   "| другие проекты (`-home-pakar-igor-*`) | 3,0 | 49,9 % |",
                   "| сессии вне проектов (прочие папки журналов) | 0,0 | 0,0 % |",
                   "| не отнесено: за интервал нет ответов на этой машине | 1,0 | 16,7 % |",
                   "| прочее: интервал и ответ в разных сутках периода | 0,0 | 0,0 % |"):
        assert stroka in tekst


@pytest.mark.parametrize(("procenty", "ozhidaem"), [
    # сброс без смены resets_at (смена тарифа, 20.10): +2 от нуля; 53 — отголосок старого окна от
    # отставшей сессии — пропуск; 5 → 4 — малое падение, устаревшее показание
    ((50, 54, 2, 53, 5, 4), [(0, 1, 4.0), (1, 2, 2.0), (2, 4, 3.0)]),
    # дефект 25.10: простаивающая сессия всегда 60 при живой 65+ — не сброс, прирост по максимуму
    ((60, 65, 60, 65, 60, 66, 60), [(0, 1, 5.0), (1, 5, 1.0)]),
])
def test_limit_sbros_bez_smeny_resets_at(tmp_path: Path, procenty: tuple[int, ...],
                                         ozhidaem: list[tuple[int, int, float]]) -> None:
    r = 1_793_000_000
    log = tmp_path / "usage-log.jsonl"
    zapisat(log, [tochka(10 * i, p, r) for i, p in enumerate(procenty)])
    prirosty = tokeny.prirosty_limita(tokeny.tochki_limita(log))
    t = [T0 + timedelta(minutes=10 * i) for i in range(len(procenty))]
    assert prirosty == [(t[a], t[b], d) for a, b, d in ozhidaem]
