"""Тесты линта брифов `tools/ops/brief_lint.py` — на подставных брифах (T-20261123-23/1, п.2).
Запуск: `python -m pytest tools/ops/tests/test_brief_lint.py -q -p no:cacheprovider`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brief_lint as bl  # noqa: E402

GOOD = """[директор] T-20261123-99/1 · задание · что-то

## Конвейер (P-032)
- правило изменено: общее правило X;
- где ещё действует: все товары;
- шаг пересоберёт: ничего;
- особый случай под товар: нет.
## Что чистит шаг
Временные файлы — в своей папке.
## Salad или наши ядра
Наши.
## Границы
Без sudo. `/memory-check` не запускать — свод директор.
"""


def cats(text):
    return [c for c, _ in bl.lint_brief(text)]


def test_good_brief_is_clean():
    assert bl.lint_brief(GOOD) == []


def test_label_required():
    assert cats(GOOD.replace("[директор] ", "")) == ["BRIEF-LABEL"]
    assert cats(GOOD.replace("T-20261123-99/1", "задание")) == ["BRIEF-LABEL"]
    assert cats(GOOD.replace("[директор]", "[рабочий 4]")) == []


def test_each_required_line_is_checked():
    assert cats(GOOD.replace("Salad или наши ядра", "Платформа")) == ["BRIEF-SALAD"]
    assert cats(GOOD.replace("Что чистит шаг", "Уборка")) == ["BRIEF-CLEAN"]
    assert cats(GOOD.replace("## Границы", "## Рамки")) == ["BRIEF-BOUNDS"]
    assert cats(GOOD.replace("`/memory-check` не запускать — свод директор", "ничего")) == ["BRIEF-MEMCHECK"]


def test_pipeline_lists_missing_lines():
    t = GOOD.replace("- особый случай под товар: нет.\n", "").replace("- шаг пересоберёт: ничего;\n", "")
    f = bl.lint_brief(t)
    assert [c for c, _ in f] == ["BRIEF-PIPELINE"]
    assert "особый случай" in f[0][1] and "шаг пересоберёт" in f[0][1]


def test_pipeline_required_in_report_is_accepted():
    four = "- правило изменено: общее правило X;\n- где ещё действует: все товары;\n- шаг пересоберёт: ничего;\n- особый случай под товар: нет.\n"
    assert four in GOOD
    assert bl.lint_brief(GOOD.replace(four, "Плюс 4 строки конвейера в отчёте.\n")) == []


def test_na_with_reason_is_accepted():
    t = GOOD.replace("- особый случай под товар: нет.", "- особый случай: N/A: разбор без кода.")
    assert bl.lint_brief(t) == []


def test_case_insensitive_and_crlf():
    assert bl.lint_brief(GOOD.replace("\n", "\r\n").replace("Границы", "ГРАНИЦЫ")) == []


def test_collect_only_new_briefs(tmp_path):
    d = tmp_path / ".memory_bank" / "_intake"
    d.mkdir(parents=True)
    for n in ("brief-T-20261121-171.md", "brief-T-20261123-01.md", "brief-T-20261124-02.md", "notes.md", "brief-T-x.md"):
        (d / n).write_text(GOOD, encoding="utf-8")
    got = [p.name for p in bl.collect(tmp_path, "20261123")]
    assert got == ["brief-T-20261123-01.md", "brief-T-20261124-02.md"]


def test_cli_warn_vs_block(tmp_path, capsys):
    d = tmp_path / ".memory_bank" / "_intake"
    d.mkdir(parents=True)
    (d / "brief-T-20261123-01.md").write_text("[директор] T-20261123-01/1\nпусто\n", encoding="utf-8")
    assert bl.main(["--root", str(tmp_path)]) == 0
    assert bl.main(["--root", str(tmp_path), "--block", "BRIEF-SALAD"]) == 1
    assert bl.main([str(tmp_path / "нет.md")]) == 2
    assert "BRIEF-CLEAN" in capsys.readouterr().out
