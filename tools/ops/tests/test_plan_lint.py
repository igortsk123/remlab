"""Тесты линта плана `tools/ops/plan_lint.py` — на подставном тексте плана, без настоящих файлов проекта (T-20261123-23/1, п.1).
Запуск: `python -m pytest tools/ops/tests/test_plan_lint.py -q -p no:cacheprovider`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan_lint as pl  # noqa: E402

HEAD = "<!--\nКАК ВЕСТИ\nДиректор: algor с 23.11 06:37 (владелец TG 1811)\n-->\n# План задач remlab · ≈ 54 %\n"
GOOD = "**П1.144 · algor · р.1 · 100 % — z-буфер в растре камеры, чтобы фасад не терял своё (влито dfc37516)** <!-- T-20261123-01 · algor:рабочий 1 -->\n"


def cats(text):
    return [x.cat for x in pl.lint_plan(text)]


def test_good_plan_is_clean():
    assert pl.lint_plan(HEAD + GOOD) == []


def test_good_item_with_tid_on_next_line():
    t = HEAD + "**П1.1 · algor · р.2 · 40 % — делаю, чтобы работало**\n<!-- T-20261123-02 · algor:рабочий 2 -->\n"
    assert pl.lint_plan(t) == []


def test_bad_pct():
    t = HEAD + "**П1.5 · algor · р.2 · 97 % — делаю** <!-- T-20261123-02 -->\n"
    assert cats(t) == ["PLAN-PCT"]


def test_all_allowed_pct_pass():
    for p in sorted(pl.ALLOWED_PCT):
        t = HEAD + f"**П1.5 · algor · р.2 · {p} % — делаю** <!-- T-20261123-02 -->\n"
        assert cats(t) == [], p


def test_checkmark_only_at_100():
    t = HEAD + "**П1.5 · algor · р.2 · 90 % — ✅ готово** <!-- T-20261123-02 -->\n"
    assert cats(t) == ["PLAN-CHECK"]
    t = HEAD + "**П1.5 · algor · р.2 · 100 % — ✅ готово** <!-- T-20261123-02 -->\n"
    assert cats(t) == []


def test_clock_needs_wait_word():
    t = HEAD + "**П1.5 · algor · р.2 · 70 % — 🕓 чего-то** <!-- T-20261123-02 -->\n"
    assert cats(t) == ["PLAN-WAIT"]
    t = HEAD + "**П1.5 · algor · р.2 · 70 % — 🕓 ждёт: ответа владельца** <!-- T-20261123-02 -->\n"
    assert cats(t) == []


def test_missing_tid():
    t = HEAD + "**П1.5 · algor · р.2 · 70 % — делаю**\n"
    assert cats(t) == ["PLAN-TID"]


def test_legacy_format_flagged():
    t = HEAD + "П1.121 · р.1 · 70 % — этап 3: делим модель на части <!-- T-185/1 -->\n"
    assert cats(t) == ["PLAN-FORMAT"]
    t = HEAD + "П1.76 · 70 % — стены по стилям <!-- T-1/1 -->\n"
    assert cats(t) == ["PLAN-FORMAT"]


def test_director_line_exactly_one():
    assert cats(GOOD) == ["PLAN-DIRECTOR"]  # нет строки
    assert cats(HEAD + "Директор: pakardev\n" + GOOD) == ["PLAN-DIRECTOR"]  # две


def test_duplicate_tid_different_executors():
    a = "**П1.1 · algor · р.1 · 40 % — делаю один** <!-- T-20261123-09 -->\n"
    b = "**П1.2 · algor · р.2 · 40 % — делаю другой** <!-- T-20261123-09/2 -->\n"
    t = HEAD + a + b
    assert cats(t) == ["PLAN-DUP"]
    same = "**П1.2 · algor · р.1 · 40 % — тот же исполнитель** <!-- T-20261123-09/2 -->\n"
    assert cats(HEAD + a + same) == []


def test_items_inside_hidden_comment_are_ignored():
    t = HEAD + GOOD + "<!-- ДЛЯ %\n**П1.104 · 90 %**\nП1.9 · 33 % — ✅ 🕓\n-->\n"
    assert pl.lint_plan(t) == []


def test_multiline_comment_then_item():
    t = HEAD + "<!--\nT-20261123-77 — не пункт\n-->\n**П1.3 · algor · р.3 · 30 % — делаю** <!-- T-20261123-03 -->\n"
    assert pl.lint_plan(t) == []


def test_cli_block_and_warn(tmp_path, capsys):
    p = tmp_path / "plan.md"
    p.write_text(HEAD + "**П1.5 · algor · р.2 · 97 % — делаю** <!-- T-20261123-02 -->\n", encoding="utf-8")
    assert pl.main([str(p)]) == 0  # по умолчанию — предупреждение
    assert pl.main([str(p), "--block", "PLAN-PCT"]) == 1
    assert pl.main([str(p), "--block", "PLAN-TID"]) == 0
    assert pl.main([str(tmp_path / "нет.md")]) == 2
    assert "PLAN-PCT" in capsys.readouterr().out


def test_empty_plan_has_director_finding_only():
    assert cats("") == ["PLAN-DIRECTOR"]
