"""Тесты карточки прогона у запускателей Этажей (П1.161 шаг 5, Fable otvet-52): `tools/ops/run_card.py` + декоратор `@carded` на входах `ru_eval.main`, `storozh.run`, `storozh.selftest`.

Что проверяем (без агента, шлюза, сети, cv2; только tmp_path):
  1. прогон-заглушка БЕЗ карточки → проверка `check_card` КРАСНАЯ (и CLI `check` — код 1); недописанная карточка (прогон упал без finish) — тоже красная;
  2. та же заглушка С карточкой → зелёная (код 0), результат и выходные файлы заглушки прежние (кроме RUN.json), аргументы/результат функции проходят насквозь;
  3. −контроль: прогон упал → карточка со статусом fail и причиной, а не ok; исключение летит дальше как было; SystemExit(0) — ok, SystemExit(2) и KeyboardInterrupt — fail;
  4. сбой самой карточки (папка — файл; схема новее известной) прогон не валит: результат тот же, в stderr строка;
  5. запускатели Этажей в репозитории (список ниже) несут декоратор — это ловится по тексту (AST), без импорта cv2; −контроль: копия без декоратора — красная;
  6. новый файл Этажей с `if __name__ == '__main__'` без записи в списке (запускатель или исключение с причиной) — красный: карточку не забудут.
Запуск: `python -m pytest tools/ops/tests/test_run_card_etazhi.py -q -p no:cacheprovider`."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
REPO = OPS.parents[1]
sys.path.insert(0, str(OPS))
import run_card as rc  # noqa: E402
import run_manifest as rm  # noqa: E402

ETAZHI = REPO / "tools" / "floorplan" / "etazhi"
# запускатели Этажей в репозитории: (файл, функция) — у каждой обязан стоять @carded(...)
LAUNCHERS = [
    ("tools/floorplan/etazhi/ru_eval.py", "main"),
    ("tools/floorplan/etazhi/storozh.py", "run"),
    ("tools/floorplan/etazhi/storozh.py", "selftest"),
]
# файлы Этажей с `__main__`, которым карточка не нужна, — с причиной (новый файл с __main__ сюда или в LAUNCHERS — иначе красный)
EXEMPT = {
    "neg_ext.py": "−контроль теста test_ext.py: пишет только в рабочую папку-аргумент (копия ext.py), в печать; прогона с результатами нет",
}


def stub_run(out: Path, boom: BaseException | None = None):
    """Заглушка прогона: пишет таблицу в out, при boom — падает посреди прогона."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "table.tsv").write_text("лист\tисход\nA\tok\n", encoding="utf-8")
    if boom is not None:
        raise boom
    return {"листов": 1}


def files_of(p: Path) -> dict:
    return {str(x.relative_to(p)): x.read_bytes() for x in sorted(p.rglob("*")) if x.is_file() and x.name != "RUN.json"}


# ───────── 1–2. без карточки красный, с карточкой зелёный ─────────
def test_run_without_card_is_red(tmp_path):
    out = tmp_path / "bez"
    stub_run(out)                                         # обычный прогон, декоратора нет
    probs = rc.check_card(str(out))
    assert probs and "нет RUN.json" in probs[0]
    assert rc.main(["check", str(out)]) == 1


def test_unfinished_card_is_red(tmp_path):
    out = tmp_path / "upal"
    rm.start(str(out), task="T-x")                        # прогон начался и не закончил (убит) — finish не звали
    probs = rc.check_card(str(out))
    assert probs and "не закончена" in probs[0]
    assert rc.main(["check", str(out)]) == 1


def test_run_with_card_is_green_and_output_unchanged(tmp_path):
    plain, carded_dir = tmp_path / "a", tmp_path / "b"
    res_plain = stub_run(plain)

    @rc.carded(str(carded_dir))
    def run(out, boom=None):
        return stub_run(out, boom)

    res_card = run(carded_dir)
    assert res_card == res_plain == {"листов": 1}          # результат насквозь
    assert files_of(carded_dir) == files_of(plain)         # выход прежний, добавлен только RUN.json
    assert (carded_dir / "RUN.json").exists() and not (plain / "RUN.json").exists()
    c = json.loads((carded_dir / "RUN.json").read_text(encoding="utf-8"))
    assert c["status"] == "ok" and c["finished_utc"] and c["started_utc"]
    assert rc.check_card(str(carded_dir)) == []
    assert rc.main(["check", str(carded_dir)]) == 0


def test_run_dir_may_be_function_of_args_and_kwargs_pass_through(tmp_path):
    @rc.carded(lambda out, **kw: out)
    def run(out, k=0):
        stub_run(Path(out))
        return k + 1

    assert run(str(tmp_path / "f"), k=41) == 42
    assert rc.check_card(str(tmp_path / "f")) == []


# ───────── 3. −контроль: упал → fail, не ok ─────────
def test_failed_run_card_is_fail_not_ok(tmp_path):
    out = tmp_path / "upal"

    @rc.carded(str(out))
    def run():
        return stub_run(out, boom=ValueError("лист kazan-1 не читается"))

    with pytest.raises(ValueError, match="не читается"):   # исключение летит как раньше
        run()
    c = json.loads((out / "RUN.json").read_text(encoding="utf-8"))
    assert c["status"] == "fail" and c["status"] != "ok"
    assert c["finished_utc"] and "ValueError" in c["note"] and "kazan-1" in c["note"]
    assert rc.check_card(str(out)) == []                   # карточка закончена честно — это не «прогон без карточки»
    assert rm.read_card(str(out))["state"] == "fail"


@pytest.mark.parametrize("exc,status", [(SystemExit(0), "ok"), (SystemExit(None), "ok"), (SystemExit(2), "fail"), (KeyboardInterrupt(), "fail")])
def test_exit_codes_and_interrupt(tmp_path, exc, status):
    out = tmp_path / "x"

    @rc.carded(str(out))
    def run():
        raise exc

    with pytest.raises(type(exc)):
        run()
    assert rm.read_card(str(out))["state"] == status


def test_restart_in_same_dir_counts_and_keeps_start(tmp_path):
    out = tmp_path / "r"

    @rc.carded(str(out))
    def run(boom=None):
        if boom:
            raise boom

    with pytest.raises(RuntimeError):
        run(RuntimeError("1"))
    c1 = json.loads((out / "RUN.json").read_text(encoding="utf-8"))
    run()
    c2 = json.loads((out / "RUN.json").read_text(encoding="utf-8"))
    assert c1["status"] == "fail" and c2["status"] == "ok"
    assert c2["started_utc"] == c1["started_utc"] and c2["restarts"] == 1


# ───────── 4. сбой карточки прогон не валит ─────────
def test_card_failure_does_not_break_run(tmp_path, capsys):
    blocker = tmp_path / "файл"
    blocker.write_text("не папка", encoding="utf-8")

    @rc.carded(str(blocker))                               # «папка прогона» — обычный файл: start не может её создать
    def run():
        return {"листов": 1}

    assert run() == {"листов": 1}
    assert "карточку не начал" in capsys.readouterr().err
    assert blocker.read_text(encoding="utf-8") == "не папка"


def test_newer_schema_card_untouched_and_run_goes_on(tmp_path, capsys):
    out = tmp_path / "новее"
    out.mkdir()
    raw = json.dumps({"schema": 99, "status": "ok"})
    (out / "RUN.json").write_text(raw, encoding="utf-8")

    @rc.carded(str(out))
    def run():
        return 7

    assert run() == 7
    assert (out / "RUN.json").read_text(encoding="utf-8") == raw
    assert "карточку не начал" in capsys.readouterr().err
    assert rc.check_card(str(out))                          # проверка видит: карточка не наша/новее — красная


# ───────── 5–6. запускатели Этажей несут декоратор; новый запускатель не забыт ─────────
def launchers_missing(src_by_file: dict) -> list:
    """Какие из LAUNCHERS без @carded(...) (по AST: без импорта модулей — cv2 в CI-job не нужен)."""
    miss = []
    for rel, fn in LAUNCHERS:
        tree = ast.parse(src_by_file[rel])
        found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn]
        ok = bool(found) and all(
            any((isinstance(d, ast.Call) and getattr(d.func, "id", None) == "carded") for d in f.decorator_list) for f in found)
        if not ok:
            miss.append(f"{rel}:{fn}")
    return miss


def load_sources() -> dict:
    return {rel: (REPO / rel).read_text(encoding="utf-8") for rel, _ in LAUNCHERS}


def test_etazhi_launchers_have_card_decorator():
    assert launchers_missing(load_sources()) == []


def test_etazhi_launcher_without_decorator_is_red():
    src = load_sources()
    for rel, fn in LAUNCHERS:                              # −контроль: убираем декоратор у каждой по очереди — обязана стать красной
        lines = src[rel].splitlines(keepends=True)
        idx = next(i for i, ln in enumerate(lines) if ln.startswith(f"def {fn}(") and lines[i - 1].startswith("@carded("))
        broken = dict(src)
        broken[rel] = "".join(lines[:idx - 1] + lines[idx:])
        assert launchers_missing(broken) == [f"{rel}:{fn}"]


def test_launcher_imports_run_card():
    for rel in sorted({r for r, _ in LAUNCHERS}):
        assert "from run_card import carded" in (REPO / rel).read_text(encoding="utf-8"), rel


def test_every_etazhi_main_is_registered():
    launcher_files = {Path(r).name for r, _ in LAUNCHERS}
    unknown = []
    for p in sorted(ETAZHI.glob("*.py")):
        if p.name.startswith("test_"):
            continue
        if "__name__ == '__main__'" in p.read_text(encoding="utf-8") or '__name__ == "__main__"' in p.read_text(encoding="utf-8"):
            if p.name not in launcher_files and p.name not in EXEMPT:
                unknown.append(p.name)
    assert unknown == [], f"новый запускатель Этажей без карточки: {unknown} — добавь @carded или запиши в EXEMPT с причиной"
    for name, why in EXEMPT.items():
        assert (ETAZHI / name).exists() and why.strip(), name
