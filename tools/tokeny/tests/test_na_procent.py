"""«На 1 % недели» без чужой работы учётки (T-30, владелец 05.11.2026: «пики вычистить — это не мы»): ступеньки процента
по окну `resets_at`, разложение `п.п. = a·$ + b·часы` (b — фон: Windows, claude.ai), пики, порог окна, строка
«Вне наших машин»; ступеньки в ночной выгрузке — сводка на любой машине видит все учётки."""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import tokeny

T0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
OKNO = int((T0 + timedelta(days=7)).timestamp())  # окно учётки: T0 … T0 + 7 сут
DANNYE = Path(__file__).with_name("dannye")


def otvet(t: datetime, usd: float, n: int) -> tokeny.Stroka:
    chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": round(usd / 4 * 1e6)}
    return tokeny.Stroka("s", "f.jsonl", f"m{n}", f"r{n}", f"u{n}", t, "claude-opus-5-5", chisla)


def nedelya(mln: float, fon: float, pik: tuple[int, float] | None = None, seed: int = 5) -> list[tokeny.Otrezok]:
    """Неделя учётки: ответы машины каждые 10 мин днём ($0–5), чужая работа — `fon` п.п. в час круглые сутки и
    `pik` (час, п.п.) разом; statusline — целый процент каждые 10 мин. Наш расход — `mln` млн взвешенных на 1 %."""
    rnd = random.Random(seed)
    a = 1 / (4 * mln)  # п.п. на $
    tochki, otvety, nakopleno = [], [], 0.0
    for k in range(6 * 24 * 6):
        t = T0 + timedelta(minutes=10 * k)
        usd = rnd.uniform(0, 5) if 8 <= t.hour < 22 else 0.0
        if usd:
            otvety.append(otvet(t - timedelta(minutes=5), usd, k))
        nakopleno += a * usd + fon / 6 + (pik[1] if pik and k == pik[0] * 6 else 0.0)
        tochki.append((t, float(int(nakopleno)), OKNO))
    return tokeny.otrezki_mashiny(tochki, otvety)


@pytest.mark.parametrize(("mln", "fon"), [(5.2, 0.3), (3.3, 0.0), (3.7, 0.1)])
def test_sintetika_izvestnye_a_b(mln: float, fon: float) -> None:
    """Известные наш расход и фон восстанавливаются ±10 % (процент целый — ступеньки по 1 п.п.)."""
    r = tokeny.razlozhit(nedelya(mln, fon))
    assert r is not None
    assert r.mln_na_procent / 1e6 == pytest.approx(mln, rel=0.1)
    assert r.b == pytest.approx(fon, abs=max(0.1 * fon, 0.01))
    assert r.vne == pytest.approx(fon * r.chasy, abs=max(0.1 * fon * r.chasy, 1.0))


def test_pik_vykinut_i_idet_vo_vne() -> None:
    """Чужие 8 п.п. разом ночью (наших $ нет) — пик: выкинут, наш расход не задет, 8 п.п. — «вне наших машин»."""
    r = tokeny.razlozhit(nedelya(5.2, 0.0, pik=(50, 8.0)))
    assert r is not None and r.pikov >= 1
    assert r.mln_na_procent / 1e6 == pytest.approx(5.2, rel=0.1)
    assert r.vne == pytest.approx(8.0, abs=1.0)


def test_fon_algor_common_nol() -> None:
    """Сохранённые ступеньки algor и common 05.11 (разбор ведущего): фона нет — «вне ≈0»; algor — текущее окно 13 п.п.
    меньше порога, считается прошлое."""
    dannye = json.loads((DANNYE / "otrezki-algor-common.json").read_text(encoding="utf-8"))["otrezki"]
    otr = {m: [o for x in v if (o := tokeny.Otrezok.iz_slovarya(x))] for m, v in dannye.items()}
    for m, mln, proshloe in (("algor", 3.25, True), ("common", 3.72, False)):
        r, po_proshlomu, _ = tokeny.ocenka_mashiny(otr[m])
        assert r is not None and po_proshlomu is proshloe
        assert r.mln_na_procent / 1e6 == pytest.approx(mln, rel=0.05)
        assert r.vne < 1
    assert tokeny.stroki_na_procent(otr, ["algor", "common", "pakardev"]) == [
        "На 1 % недели (по неделе каждой учётки, все проекты; токены взвешенные): algor 3,2 млн (прошлая неделя), "
        "common 3,7 млн, pakardev — пока нет данных; выгоднее common: в 1,15 раза больше, чем algor.",
        "Вне наших машин (та же учётка на Windows, в claude.ai и др.): algor ≈0, common ≈0."]


def test_pustoe_i_maloe_okno() -> None:
    """Пустое окно — «пока нет данных»; меньше 20 п.п. или 10 ступенек и прошлого окна нет — «мало данных (X п.п.)»."""
    assert tokeny.razlozhit([]) is None
    malo = nedelya(5.2, 0.0)[:6]
    assert tokeny.stroki_na_procent({"pakardev": [], "algor": malo}) == [
        f"На 1 % недели (по неделе каждой учётки, все проекты; токены взвешенные): algor — мало данных "
        f"({tokeny.pp(sum(o.dp for o in malo))} п.п.), pakardev — пока нет данных; сравнить пока не с чем."]
    assert tokeny.stroki_na_procent({}) == []


def test_novoe_okno_ot_nachala_okna() -> None:
    """Дефект (Codex 05.11): первый прирост нового окна шёл от прироста прошлого окна (05.11 pakardev — «с 27.10»)."""
    r1 = int((T0 + timedelta(days=3)).timestamp())
    tochki = [(T0, 50.0, r1), (T0 + timedelta(hours=1), 55.0, r1),
              (T0 + timedelta(days=3, hours=2), 4.0, r1 + 7 * 86400)]
    assert tokeny.prirosty_limita(tochki) == [(T0, T0 + timedelta(hours=1), 5.0),
                                              (T0 + timedelta(days=3), T0 + timedelta(days=3, hours=2), 4.0)]


def test_vygruzka_so_stupenkami_i_staraya(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ночная выгрузка кладёт ступеньки учётки машины (все проекты — одинаковые, склеиваются); выгрузка старого
    формата читается — машина без ступенек; сводка берёт последнюю выгрузку не позже дня; своя машина — живой счёт."""
    monkeypatch.setattr("socket.gethostname", lambda: "pakardev")
    korni, koren = tmp_path / "igor", tmp_path / "projects"
    monkeypatch.setattr(tokeny, "PREFIKS", tokeny.imya_papki(str(korni)) + "-")
    den = T0.date() + timedelta(days=2)
    t = datetime(den.year, den.month, den.day, 12, tzinfo=UTC)
    for proekt, n in (("remlab", 1), ("tamara", 2)):
        (koren / f"{tokeny.PREFIKS}{proekt}").mkdir(parents=True)
        (koren / f"{tokeny.PREFIKS}{proekt}" / "s1.jsonl").write_text(json.dumps({
            "type": "assistant", "timestamp": (t + timedelta(minutes=n)).isoformat().replace("+00:00", "Z"),
            "uuid": f"u{n}", "requestId": f"r{n}", "message": {"id": f"m{n}", "model": "claude-opus-5-5",
                                                              "usage": {"input_tokens": 1_000_000}}}) + "\n",
            encoding="utf-8")
    limit = tmp_path / "usage-log.jsonl"
    limit.write_text("".join(json.dumps({"t": x.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": "s",
                                         "rl": {"seven_day": {"used_percentage": p, "resets_at": OKNO}}}) + "\n"
                             for x, p in ((t - timedelta(hours=1), 10), (t + timedelta(minutes=5), 12))),
                     encoding="utf-8")
    for proekt in ("remlab", "tamara"):
        papka = korni / proekt / "data" / "logs" / "tokeny"
        papka.mkdir(parents=True)
        assert tokeny.main(["--proekt", proekt, "--koren", str(koren), "--limit", str(limit), "--s", str(den),
                            "--po", str(den), "--json", str(papka / f"pakardev-{den}.json")]) == 0
        (papka / f"algor-{den}.json").write_text(tokeny.vygruzka([], proekt, tokeny.Vygruzka("algor", den, den)),
                                                 encoding="utf-8")  # старый формат: без ступенек
    _, v = tokeny.prochitat_vygruzku(korni / "remlab" / "data" / "logs" / "tokeny" / f"pakardev-{den}.json", "remlab")
    assert [(o.t0, o.t1, o.dp, o.usd) for o in v.otrezki or []] == [(t - timedelta(hours=1), t + timedelta(minutes=5),
                                                                     2.0, 8.0)]  # $ обоих проектов машины
    assert tokeny.prochitat_vygruzku(korni / "tamara" / "data" / "logs" / "tokeny" / f"algor-{den}.json",
                                     "tamara")[1].otrezki is None
    po = tokeny.otrezki_po_mashinam(korni, den)
    assert {m: len(v) for m, v in po.items()} == {"algor": 0, "pakardev": 1}  # повтор из двух проектов склеен
    assert tokeny.otrezki_po_mashinam(korni, den - timedelta(days=1)) == {}  # выгрузки позже дня — мимо
    svoya = tokeny.otrezki_zhivye(koren, limit, t + timedelta(hours=1))
    assert svoya is not None and [(o.dp, o.usd) for o in svoya] == [(2.0, 8.0)]
    assert tokeny.otrezki_po_mashinam(korni, den, [])["pakardev"] == []  # живой счёт заменяет выгрузку своей машины
    assert tokeny.otrezki_zhivye(koren, tmp_path / "net.jsonl", t) is None

