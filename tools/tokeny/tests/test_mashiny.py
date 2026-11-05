"""Учёт токенов со всех машин (`tokeny-mashiny/1`): машина без выгрузки не пропадает из сводки
молча; цена чтений памяти — блок `pamyat` выгрузки и строка «Память» сводки."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ лежит в tools/tokeny/
import tokeny

DEN = "2026-10-20"


def otvet(msg: str, minuty: int, *, kontent: list[dict[str, object]],
          kesh_1h: int = 0, vvod: int = 100, model: str = "claude-opus-5-5") -> dict[str, object]:
    return {"type": "assistant", "timestamp": f"{DEN}T10:{minuty:02d}:00Z", "requestId": f"r-{msg}",
            "uuid": f"u-{msg}-{len(kontent)}",
            "message": {"id": msg, "model": model, "content": kontent,
                        "usage": {"input_tokens": vvod, "output_tokens": 10,
                                  "cache_creation_input_tokens": kesh_1h,
                                  "cache_creation": {"ephemeral_1h_input_tokens": kesh_1h}}}}


def vyzov(ident: str, imya: str, **vvod: str) -> dict[str, object]:
    return {"type": "tool_use", "id": ident, "name": imya, "input": vvod}


def rezultat(ident: str, minuty: int, simvolov: int) -> dict[str, object]:
    return {"type": "user", "timestamp": f"{DEN}T10:{minuty:02d}:30Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": ident,
                                     "content": "я" * simvolov}]}}


def test_sobrat_net_vygruzki_mashiny_i_ne_soshlas(tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    """Сводка 31.10 видела одну машину из трёх и молчала об остальных: теперь — явно по каждой;
    битая выгрузка не роняет сводку остальных машин."""
    bitaya = tmp_path / f"algor-{DEN}.json"
    bitaya.write_text('{"skhema": "tokeny/1", "stro', encoding="utf-8")  # оборвана при записи
    puti = [str(bitaya)]
    for mashina, sverka in (("common", True), ("pakardev", False)):
        chisla = dict.fromkeys(tokeny.CHISLA + tokeny.SPRAVOCHNO, 0) | {"vvod": 1_000_000}
        s = tokeny.Stroka(f"s-{mashina}", "f.jsonl", f"m-{mashina}", "r", "u",
                          datetime(2026, 10, 20, 10, tzinfo=UTC), "claude-opus-5-5", chisla)
        put = tmp_path / f"{mashina}-{DEN}.json"
        put.write_text(json.dumps({"skhema": tokeny.SKHEMA, "proekt": "tamara",
                                   "istochnik": mashina, "period": {"s": DEN, "po": DEN},
                                   "sverka": sverka, "stroki": [tokeny.v_slovar(s)]}),
                       encoding="utf-8")
        puti.append(str(put))
    assert tokeny.main(["--proekt", "tamara", "--sobrat", *puti, "--svodka", "--data", DEN,
                        "--ozhidaem", "common,algor,pakardev", "--zamery", ""]) == 0
    stroki = capsys.readouterr().out.splitlines()
    assert stroki[2:6] == ["По машинам: common $4,00 (1 отв.), pakardev $4,00 (1 отв.).",
                           f"Битые выгрузки, не учтены: algor-{DEN}.json (JSONDecodeError).",
                           "Нет данных: algor (выгрузки за 20 октября нет).",
                           "Сверка с журналами не сошлась: pakardev."]


def test_pamyat_v_vygruzke_i_svodke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    """Чтение `.memory_bank/` — вход по цене записи кэша и перенос в следующие ответы; код и запись
    в память — не чтение памяти; повтор ответа (строкой того же файла, копией истории в другом
    файле) и ответ-заглушка `<synthetic>` не добавляют ни входа, ни переноса."""
    papka = tmp_path / "projects" / "-home-pakar-igor-tamara"
    papka.mkdir(parents=True)
    zapisi = [
        otvet("a1", 0, kontent=[vyzov("t1", "Read", file_path="/r/.memory_bank/core/x.md"),
                                vyzov("t2", "Read", file_path="/r/src/kod.py"),
                                vyzov("t3", "Bash", command="echo x >> .memory_bank/zametki.md")]),
        rezultat("t1", 0, 1950), rezultat("t2", 0, 1950), rezultat("t3", 0, 100),
        rezultat("t1", 0, 1950),  # копия истории при перезапуске — тот же результат
        otvet("a2", 1, kontent=[{"type": "text", "text": "x"}], kesh_1h=5000),
        otvet("a2", 1, kontent=[{"type": "text", "text": "y"}], kesh_1h=5000),  # та же пара id
        otvet("s", 2, kontent=[{"type": "text", "text": "API Error"}], vvod=0, model="<synthetic>"),
        otvet("a3", 2, kontent=[{"type": "text", "text": "z"}]),
    ]
    for imya, chast in (("sess0001", zapisi), ("sess0002", zapisi[:6])):  # 0002 — копия истории
        (papka / f"{imya}.jsonl").write_text("".join(json.dumps(z) + "\n" for z in chast),
                                             encoding="utf-8")
    monkeypatch.setattr("socket.gethostname", lambda: "common")
    vygr = tmp_path / f"common-{DEN}.json"
    assert tokeny.main(["--proekt", "tamara", "--koren", str(tmp_path / "projects"),
                        "--limit", str(tmp_path / "net.jsonl"), "--fazy", str(tmp_path / "net.tsv"),
                        "--s", DEN, "--po", DEN, "--json", str(vygr)]) == 0
    d = json.loads(vygr.read_text(encoding="utf-8"))
    assert d["sverka"] is True
    p = d["pamyat"]
    # 1950 символов памяти = 1000 токенов: вход в a2 по записи 1 ч ($8), перенос в a3 ($0,20)
    assert (p["chteniy"], p["simvoly"], p["simvoly_vse"], p["perenos"]) == (1, 1950, 4000, 1000.0)
    assert (p["usd_vhod"], p["usd_perenos"], p["starty"]) == (0.008, 0.0002, 1)
    capsys.readouterr()
    assert tokeny.main(["--proekt", "tamara", "--sobrat", str(vygr), "--svodka", "--data", DEN,
                        "--ozhidaem", "common", "--zamery", ""]) == 0
    pamyat = [s for s in capsys.readouterr().out.splitlines() if s.startswith("Память:")]
    assert len(pamyat) == 1
    assert pamyat[0].startswith("Память: прочитано ≈ 1 тыс. токенов (48,8 % результатов "
                                "инструментов, 1 чтений); с переносом в контексте ≈ $0,0082 = ")
