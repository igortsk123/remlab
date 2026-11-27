"""Тесты поиска по банку `tools/ops/bank_search.py` и линта вопроса/ответа советнику `tools/ops/question_lint.py` (T-20261127-175/7) — на подставном банке.
Запуск: `python -m pytest tools/ops/tests/test_bank_search.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bank_search as bs  # noqa: E402
import question_lint as ql  # noqa: E402

ADR = """# Решения

## ADR-0455 — 2026-11-20 — Покраска меша
**Решение:** нейросеть-художник (StableGen) отброшена: рисует заново и выдумывает зад. Основной путь — фото на видимое + заливка невидимого.

## ADR-0456 — 2026-11-21 — Другое
Про колёсики дивана, ничего общего.
"""


def make_bank(tmp: Path) -> Path:
    root = tmp / "repo"
    mb = root / ".memory_bank"
    for d in ("decisions", "lessons", "_secrets", "_intake", "archive"):
        (mb / d).mkdir(parents=True, exist_ok=True)
    (mb / "decisions" / "adr.md").write_text(ADR, encoding="utf-8")
    (mb / "lessons" / "l.md").write_text("# Уроки\n\n- **урок 750** — спросили ключ RunPod второй раз, он лежал в банке.\n", encoding="utf-8")
    (mb / "_secrets" / "ACCESS.md").write_text("RUNPOD_API_KEY=секретныйключ нейросеть художник\n", encoding="utf-8")
    (mb / "_intake" / "brief-T-1.md").write_text("бриф про нейросеть художник в брифе\n", encoding="utf-8")
    (mb / "_intake" / "session-scratch.md").write_text("- 2026-11-27 блокнот: нейросеть художник — нет, решение владельца\n", encoding="utf-8")
    (mb / "archive" / "old.md").write_text("старое: нейросеть художник пробовали давно\n", encoding="utf-8")
    return root


def run(root, *q, **kw):
    return bs.run_query(" ".join(q), root, kw.get("intake", False), kw.get("auto", False), kw.get("auto_dir"), kw.get("limit", 12), kw.get("per_file", 2))


def test_stems_morphology():
    assert bs.stems("нейросеть") == bs.stems("нейросети")
    assert bs.stems("художник") == bs.stems("художника")
    assert bs.stems("как что для") == []                               # одни стоп-слова
    assert "99" in bs.stems("T-99 вырезка")                            # числа не теряются


def test_finds_adr_with_heading_and_closed_marker(tmp_path):
    r = run(make_bank(tmp_path), "нейросеть художник")
    top = r["shown"][0]
    assert top["file"].endswith("decisions/adr.md") and "ADR-0455" in top["ids"], top
    assert "отброшен" in " ".join(top["closed"]) or any("отброш" in c for c in top["closed"]), top


def test_secrets_never_read_and_intake_only_scratch(tmp_path):
    root = make_bank(tmp_path)
    files = {h["file"] for h in run(root, "нейросеть художник", limit=50, per_file=5)["shown"]}
    assert not any("_secrets" in f for f in files), files
    assert not any("brief-T-1" in f for f in files), files
    assert any(f.endswith("session-scratch.md") for f in files), files
    assert any("brief-T-1" in h["file"] for h in bs.run_query("нейросеть художник", root, True, False, None, 50, 5)["shown"])   # --with-intake включает брифы
    assert not any("_secrets" in h["file"] for h in bs.run_query("нейросеть художник", root, True, False, None, 50, 5)["shown"])  # а секреты — никогда


def test_archive_weighs_less(tmp_path):
    shown = run(make_bank(tmp_path), "нейросеть художник", limit=50)["shown"]
    adr = next(h for h in shown if h["file"].endswith("adr.md"))
    old = next(h for h in shown if "archive" in h["file"])
    assert adr["score"] > old["score"]


def test_all_words_needed_in_window(tmp_path):
    r = run(make_bank(tmp_path), "нейросеть колёсики дивана")          # слова из разных мест → окна с 2/3 слов нет в одном месте
    assert all(h["words"] >= r["need"] for h in r["shown"])
    r1 = run(make_bank(tmp_path), "колёсики")
    assert r1["total_places"] == 1 and r1["shown"][0]["file"].endswith("adr.md")


def test_zero_result_is_a_result(tmp_path):
    r = run(make_bank(tmp_path), "квантовый телепорт")
    assert r["total_places"] == 0 and r["shown"] == []
    text = bs.render([r], block=True)
    assert "найдено 0 мест" in text and "записей нет" in text
    assert ql.lint_question("# В\n\n" + text) == []                    # «найдено 0» — допустимая метка поиска


def test_auto_memory_included_and_optional(tmp_path):
    root = make_bank(tmp_path)
    am = tmp_path / "am"
    am.mkdir()
    (am / "feedback-x.md").write_text("владелец: нельзя предлагать уже пробованное — урок про сверку банка\n", encoding="utf-8")
    on = run(root, "сверку банка пробованное", auto=True, auto_dir=am)
    assert any(h["file"] == "авто-память/feedback-x.md" for h in on["shown"])
    assert run(root, "сверку банка пробованное", auto=False)["total_places"] == 0


def test_block_roundtrip_passes_question_lint(tmp_path):
    root = make_bank(tmp_path)
    text = bs.render([run(root, "нейросеть художник"), run(root, "ключ RunPod")], block=True)
    assert text.startswith("## Что уже пробовали (поиск по банку)")
    assert text.count("Поиск по банку:") == 2 and "ADR-0455" in text and "урок 750" in text
    assert ql.lint_question("# Вопрос Fable 99\n\n## Факты\n- х\n\n" + text + "\n## Вопросы\n1. да?\n") == []


def test_cli_json_and_errors(tmp_path, capsys):
    root = make_bank(tmp_path)
    assert bs.main(["нейросеть художник", "--root", str(root), "--no-auto", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["shown"] and data[0]["query"] == "нейросеть художник"
    assert bs.main(["как что", "--root", str(root), "--no-auto"]) == 2    # нечего искать
    assert bs.main(["x1", "--root", str(tmp_path / "нет")]) == 2


GOOD_Q = """# Вопрос Fable 5

## Факты
- что-то

## Что уже пробовали (поиск по банку)
Поиск по банку: «нейросеть художник» · найдено 5 мест в 5 файлах (просмотрено 755) · 2026-11-27 · `python3 tools/ops/bank_search.py "нейросеть художник"`
- `файл:1` — «…»

## Вопросы
1. да?
"""


def test_question_lint():
    assert ql.lint_question(GOOD_Q) == []
    assert ql.lint_question("# В\n\n## Факты\n- х\n## Вопросы\n1. да?\n")                       # раздела нет
    assert ql.lint_question(GOOD_Q.replace("Поиск по банку: «нейросеть художник» · найдено 5 мест в 5 файлах (просмотрено 755) · 2026-11-27", "искал, ничего"))   # поле есть, поиска нет
    assert ql.lint_question(GOOD_Q.replace("· 2026-11-27", ""))                                    # без даты — не метка
    na = "# В\n\n## Что уже пробовали (поиск по банку)\nN/A: вопрос про оценку кадра, способа нет\n"
    assert ql.lint_question(na) == []
    assert ql.lint_question("# В\n\n## Что уже пробовали (поиск по банку)\nN/A: нет\n")             # причина короче 10 знаков
    assert ql.lint_question("# В\n\n## Что уже пробовали (поиск по банку)\n\n## Вопросы\n1. да?\n")   # пустой раздел
    assert ql.lint_question("# В\n\n## Что уже пробовали\nПоиск по банку: «х» · найдено 1 · 2026-11-27\n")   # заголовок без «(поиск по банку)»


def test_answer_lint():
    assert ql.lint_answer("Ответ.\n\nСверено с банком: да — ADR-0455, урок 712; закрытого не предлагаю.\n") == []
    assert ql.lint_answer("Ответ.\n\n**Сверено с банком:** да — ADR-0455 и план paint-trial-item-01\n") == []
    assert ql.lint_answer("Сверено с банком: N/A: вопрос про оценку кадра\n") == []
    assert ql.lint_answer("Ответ без поля\n")
    assert ql.lint_answer("Сверено с банком: —\n")
    assert ql.lint_answer("Сверено с банком: да\n")


def test_cli_kind_by_name(tmp_path):
    v, o = tmp_path / "vopros-1.md", tmp_path / "otvet-1.md"
    v.write_text(GOOD_Q, encoding="utf-8")
    o.write_text("Ответ\nСверено с банком: да — ADR-0455; закрытого не предлагаю\n", encoding="utf-8")
    assert ql.main([str(v), str(o)]) == 0
    o.write_text("Ответ\n", encoding="utf-8")
    assert ql.main([str(v), str(o)]) == 1
    assert ql.main([str(v), str(o), "--warn"]) == 0
