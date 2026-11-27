"""Советник Fable в сводке токенов (T-20261127-170/1): цена `claude-fable-5-2`, роль «советник» по имени сессии и подписи,
строка «Советник Fable: …» за сутки и неделю. Журналы — заглушки во временной папке; машины и журналы этой машины не читаются."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import tokeny

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
DEN = T0.date()
MLN = 1_000_000


def stroka(model: str, *, rol: str, vvod: int = 0, vyvod: int = 0, chtenie: int = 0, dni_nazad: int = 0,
           msg: str = "m", segment: str = "ne_razmecheno") -> tokeny.Stroka:
    chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {
        "vvod": vvod, "kesh_chtenie": chtenie, "vyvod": vyvod}
    s = tokeny.Stroka("sess0001", "f.jsonl", msg, "r", f"u-{msg}", T0 - timedelta(days=dni_nazad), model, chisla)
    s.razmetit(rol, (segment, None, None, False))
    return s


# ── цена ──────────────────────────────────────────────────────────────────────────────────────

def test_cena_fable_5_2_iz_praysa() -> None:
    """Прайс 27.11: вход $8, кэш 5 мин $10, кэш 1 ч $16, чтение кэша $0,20, ответ $40 за 1 млн; не по запасной цене Opus 5.5."""
    assert tokeny.cena_iz_praysa("claude-fable-5-2") == (8.0, 10.0, 16.0, 0.20, 40.0)
    assert stroka("claude-fable-5-2", rol="sovetnik", vvod=MLN).stoimost() == pytest.approx(8.0)
    assert stroka("claude-fable-5-2", rol="sovetnik", chtenie=MLN).stoimost() == pytest.approx(0.20)
    assert stroka("claude-fable-5-2", rol="sovetnik", vyvod=MLN).stoimost() == pytest.approx(40.0)
    assert tokeny.bez_ceny([stroka("claude-fable-5-2", rol="sovetnik", vyvod=10)]) == []


def test_cena_fable_5_1_i_5_ne_izmenilas() -> None:
    assert tokeny.cena_iz_praysa("claude-fable-5-1") == (10.0, 12.5, 20.0, 0.25, 50.0)
    assert tokeny.cena_iz_praysa("claude-fable-5") == (10.0, 12.5, 20.0, 0.25, 50.0)
    assert tokeny.cena_iz_praysa("claude-fable-5-2[1m]") == (8.0, 10.0, 16.0, 0.20, 40.0)
    assert tokeny.cena_iz_praysa("claude-fable-5-3") is None  # новая версия — не молча по 5.2 или 5


# ── роль ──────────────────────────────────────────────────────────────────────────────────────

def fayl(imena: tuple[str, ...] = (), podpisi: dict[str, int] | None = None, sessiya: str = "abcdef12-0000") -> tokeny.Fayl:
    f = tokeny.Fayl(Path("x.jsonl"), sessiya)
    f.imena.update(imena)
    f.podpisi.update(Counter(podpisi or {}))
    return f


def test_rol_po_imeni_sessii() -> None:
    assert tokeny.rol_sessii(fayl(("remlab-sovetnik-fable",)), {}) == ("sovetnik", "имя сессии")
    assert tokeny.rol_sessii(fayl(("REMLAB-SOVETNIK",)), {})[0] == "sovetnik"
    assert tokeny.rol_sessii(fayl(("советник-Fable",)), {})[0] == "sovetnik"
    assert tokeny.rol_sessii(fayl(("fable-5",)), {})[0] == "sovetnik"


def test_rol_rabochih_i_vedushchih_ne_izmenilas() -> None:
    assert tokeny.rol_sessii(fayl(("remlab-lead",)), {}) == ("vedushchiy", "имя сессии")
    assert tokeny.rol_sessii(fayl(("rabochiy-remlab-2 worker",)), {}) == ("ispolnitel", "имя сессии")
    assert tokeny.rol_sessii(fayl(("fable-lead",)), {})[0] == "vedushchiy"  # ведущий на Fable — не советник
    assert tokeny.rol_sessii(fayl(("рабочий Fable",)), {})[0] == "ispolnitel"
    assert tokeny.rol_sessii(fayl(), {}) == ("neizvestno", "нет")


def test_rol_po_podpisi_ishodyashchih() -> None:
    assert tokeny.rol_sessii(fayl(podpisi={"Fable": 3, "ведущий": 1}), {}) == ("sovetnik", "подписи исходящих")
    assert tokeny.rol_sessii(fayl(podpisi={"советник Fable": 2}), {})[0] == "sovetnik"
    assert tokeny.rol_sessii(fayl(podpisi={"Fable": 1, "ведущий remlab": 5}), {})[0] == "vedushchiy"
    assert tokeny.rol_sessii(fayl(podpisi={"рабочий 6": 4}), {})[0] == "ispolnitel"


def test_karta_rol_starshe_imeni() -> None:
    f = fayl(("remlab-sovetnik-fable",), sessiya="abcdef12-0000")
    assert tokeny.rol_sessii(f, {"abcdef12": "vedushchiy"}) == ("vedushchiy", "карта --rol")
    assert tokeny.rol_sessii(fayl(("remlab-lead",), sessiya="abcdef12-0000"), {"abcdef12": "sovetnik"})[0] == "sovetnik"


def zapis(**kw: object) -> str:
    return json.dumps(kw, ensure_ascii=False) + "\n"


def otvet(msg: str, minuty: int, model: str = "claude-fable-5-2") -> str:
    return zapis(type="assistant", timestamp=(T0 + timedelta(minutes=minuty)).isoformat().replace("+00:00", "Z"),
                 uuid=f"u-{msg}", requestId=f"r-{msg}",
                 message={"id": msg, "model": model, "content": [],
                          "usage": {"input_tokens": 1000, "output_tokens": 100}})


def test_zhurnal_sessii_sovetnika_i_ee_subagenta(tmp_path: Path) -> None:
    """Из журнала: сессия с именем советника — роль советник у её ответов и ответов её субагентов; соседняя — ведущий."""
    papka = tmp_path / "proekt"
    (papka / "aaaa1111-0000" / "subagents").mkdir(parents=True)
    (papka / "aaaa1111-0000.jsonl").write_text(
        zapis(type="agent-name", agentName="remlab-sovetnik-fable") + otvet("a1", 0) + otvet("a2", 1), encoding="utf-8")
    (papka / "aaaa1111-0000" / "subagents" / "agent-x.jsonl").write_text(otvet("s1", 2), encoding="utf-8")
    (papka / "bbbb2222-0000.jsonl").write_text(
        zapis(type="agent-name", agentName="remlab-lead") + otvet("b1", 3, "claude-opus-5-5"), encoding="utf-8")
    sbor = tokeny.sobrat_proekt([papka], "remlab", None, {}, False)
    assert sbor.sessii["aaaa1111"] == ("sovetnik", "имя сессии")
    assert sbor.sessii["bbbb2222"] == ("vedushchiy", "имя сессии")
    po_roli = Counter(s.rol for s in sbor.stroki)
    assert po_roli == {"sovetnik": 3, "vedushchiy": 1}
    assert all(s.model == "claude-fable-5-2" for s in sbor.stroki if s.rol == "sovetnik")


# ── сводка ────────────────────────────────────────────────────────────────────────────────────

def stroki_s_sovetnikom() -> list[tokeny.Stroka]:
    return [stroka("claude-opus-5-5", rol="vedushchiy", vvod=MLN, msg="v1", segment="planirovanie"),   # $4
            stroka("claude-fable-5-2", rol="sovetnik", vyvod=100_000, msg="s1"),                      # $4 сегодня
            stroka("claude-fable-5-2", rol="sovetnik", vvod=MLN // 2, msg="s2"),                      # $4 сегодня
            stroka("claude-fable-5-2", rol="sovetnik", vyvod=MLN // 10, dni_nazad=3, msg="s3"),       # $4 три дня назад
            stroka("claude-fable-5-2", rol="sovetnik", vyvod=MLN // 10, dni_nazad=7, msg="s4")]       # 8 дней — вне недели


def test_stroka_sovetnika_sutki_i_nedelya() -> None:
    tekst = tokeny.svodka(stroki_s_sovetnikom(), "remlab", DEN)
    stroki = tekst.splitlines()
    assert "Советник Fable: $8,00 за сутки (2 ответов), $12,00 за неделю (3 ответов)." in stroki
    i = stroki.index("Советник Fable: $8,00 за сутки (2 ответов), $12,00 за неделю (3 ответов).")
    assert stroki[i - 1].startswith("Исполнители:") and stroki[i + 1].startswith("Переделки:")  # рядом с ведущим и исполнителями
    assert "Внимание: нет цены" not in tekst
    assert "без метки задачи 0,0 %" in tekst, "ответы советника — не «без метки»"


def test_nedelya_iz_otdelnogo_spiska() -> None:
    """Сводка из выгрузок одних суток: неделя — отдельный список строк (`main` берёт его из выгрузок папки)."""
    sutki = [x for x in stroki_s_sovetnikom() if x.vremya.date() == DEN]
    tekst = tokeny.svodka(sutki, "remlab", DEN, nedelya=stroki_s_sovetnikom())
    assert "Советник Fable: $8,00 за сутки (2 ответов), $12,00 за неделю (3 ответов)." in tekst
    assert "$4,00 за неделю" not in tokeny.svodka(sutki, "remlab", DEN, nedelya=sutki)


def test_nedelya_iz_vygruzok_papki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Сводка из выгрузок (`svodka.sh`): неделю советника `main` собирает из файлов `<машина>-<сутки>.json` папки за 7 суток;
    файл за 8 суток назад и чужая выгрузка (другой проект) в неё не входят."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(tokeny, "KORNI", tmp_path / "proekty")
    papka = tokeny.koren_proekta("remlab") / "data" / "logs" / "tokeny"  # папка выгрузок проекта по умолчанию
    papka.mkdir(parents=True)
    vse = stroki_s_sovetnikom()
    for dni_nazad in (0, 3, 7):
        den = DEN - timedelta(days=dni_nazad)
        rows = [x for x in vse if x.vremya.date() == den]
        (papka / f"pakardev-{den}.json").write_text(
            tokeny.vygruzka(rows, "remlab", tokeny.Vygruzka("pakardev", den, den, True)), encoding="utf-8")
    (papka / f"algor-{DEN}.json").write_text(
        tokeny.vygruzka([], "drugoy", tokeny.Vygruzka("algor", DEN, DEN, True)), encoding="utf-8")
    kod = tokeny.main(["--proekt", "remlab", "--svodka", "--data", str(DEN),
                       "--sobrat", str(papka / f"pakardev-{DEN}.json"), "--zamery", ""])
    assert kod == 0
    assert "Советник Fable: $8,00 за сутки (2 ответов), $12,00 за неделю (3 ответов)." in capsys.readouterr().out


def test_net_sovetnika_net_stroki() -> None:
    """Проект без советника — строки нет (не «$0»); общая сумма и остальные строки те же."""
    bez = [x for x in stroki_s_sovetnikom() if x.rol != "sovetnik"]
    tekst = tokeny.svodka(bez, "tamara", DEN)
    assert "Советник" not in tekst and "$0 за сутки" not in tekst
    assert "≈ $4,00 по прайсу" in tekst


def test_sovetnik_ne_za_sutki_a_za_nedelyu() -> None:
    """Сегодня советник молчал, а за неделю был — строка есть, за сутки $0."""
    tolko_nedelya = [x for x in stroki_s_sovetnikom() if x.vremya.date() != DEN or x.rol != "sovetnik"]
    assert "Советник Fable: $0 за сутки (0 ответов), $4,00 за неделю (1 ответов)." in tokeny.svodka(tolko_nedelya, "remlab", DEN)


def test_setka_summa_sto_procentov() -> None:
    d = [x for x in stroki_s_sovetnikom() if x.vremya.date() == DEN]
    kletki = tokeny.setka(d)
    assert sum(len(v) for v in kletki.values()) == len(d)
    assert len(kletki[tokeny.KLETKI[9]]) == 2 and len(kletki[tokeny.KLETKI[8]]) == 0
    assert tokeny.stoimost(sum(kletki.values(), [])) == pytest.approx(tokeny.stoimost(d))


def test_vygruzka_hranit_rol_sovetnika() -> None:
    """Выгрузка `--json` и обратно: роль и $ советника доезжают до сводки с других машин."""
    d = [x for x in stroki_s_sovetnikom() if x.rol == "sovetnik"]
    nazad = [tokeny.iz_slovarya(json.loads(json.dumps(tokeny.v_slovar(x)))) for x in d]
    assert {x.rol for x in nazad} == {"sovetnik"}
    assert tokeny.stoimost(nazad) == pytest.approx(tokeny.stoimost(d))


def test_rol_v_karte_komandnoy_stroki(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """`--rol <id8>=sovetnik` принимается разбором аргументов, чужое значение — отказ с перечнем допустимых (отчёт не пишется)."""
    assert tokeny.main(["--proekt", "x", "--papka", str(tmp_path), "--rol", "abcdef12=chuzhoy"]) == 2
    assert "vedushchiy|ispolnitel|sovetnik" in capsys.readouterr().err
    assert tokeny.argumenty(["--proekt", "x", "--rol", "abcdef12=sovetnik"]).rol == ["abcdef12=sovetnik"]
