"""Сторож и сверка Этажей в раскладке СНИМКА воронки (П1.161 шаг 5, условие Fable 28.11): снимок копирует storozh.py / ru_eval.py / storozh_rules.json ПЛОСКО, без репозитория,
поэтому `from run_card import carded` без запасного хода уронил бы запуск ImportError-ом.

Что проверяем (всё в подпроцессе `python -I`, sys.path = только плоская папка, как в снимке):
  1. оба файла содержат защищённый импорт: try: from run_card import carded / except ImportError (проверка по AST, без запуска тяжёлых зависимостей сторожа);
  2. плоская папка БЕЗ run_card.py: защищённый блок отрабатывает, `@carded(...)` — пустой декоратор (функция и её результат как есть), RUN.json не пишется, в stderr — «карточка прогона недоступна»;
  3. −контроль: тот же вызов с run_card.py (+ run_manifest.py) рядом — карточка пишется, статус ok, stderr без жалобы;
  4. −контроль самого теста: СТАРЫЙ голый импорт в плоской папке без run_card.py падает с ImportError (значит п.2 ловит именно поломку снимка);
  5. частичный снимок (run_card.py есть, run_manifest.py нет) — тоже без падения;
  6. мелочь: в selftest сторожа `lines = [` (не `lines =[`).
Запуск: `python -m pytest tools/ops/tests/test_run_card_snimok.py -q -p no:cacheprovider`. Тяжёлых зависимостей сторожа (cv2, shapely, nc-models) тест не требует."""
import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
REPO = OPS.parents[1]
ETAZHI = REPO / "tools" / "floorplan" / "etazhi"
FILES = ["storozh.py", "ru_eval.py"]
OLD_IMPORT = "from run_card import carded"


def guard_block(name):
    """Исходный текст защищённого импорта (ast.Try с `from run_card import carded` в теле) из файла Этажей; None — если импорт голый."""
    src = (ETAZHI / name).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Try) and any(isinstance(b, ast.ImportFrom) and b.module == "run_card" for b in node.body):
            return ast.get_source_segment(src, node)
    return None


def snapshot_dir(tmp_path, with_card=False, with_manifest=None):
    """Плоская раскладка снимка: копии storozh.py, ru_eval.py, storozh_rules.json в одной папке; глубоко в tmp_path, чтобы `../../ops` не существовало.
    with_card — положить рядом run_card.py (и run_manifest.py, если with_manifest не False)."""
    flat = tmp_path / "a" / "b" / "snap"
    flat.mkdir(parents=True)
    for f in FILES:
        shutil.copyfile(ETAZHI / f, flat / f)
    shutil.copyfile(ETAZHI / "storozh_rules.json", flat / "storozh_rules.json")
    if with_card:
        shutil.copyfile(OPS / "run_card.py", flat / "run_card.py")
        if with_manifest is not False:
            shutil.copyfile(OPS / "run_manifest.py", flat / "run_manifest.py")
    return flat


PROG = """
import sys
sys.path.insert(0, {flat!r})
{block}
@carded({out!r})
def fn(x, y=1):
    return ('результат', x, y)
print(fn(5, y=7))
"""


def run_flat(flat, block, out):
    prog = PROG.format(flat=str(flat), block=block, out=str(out))
    return subprocess.run([sys.executable, "-I", "-c", prog], cwd=str(flat), capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("name", FILES)
def test_both_files_have_guarded_import(name):
    blk = guard_block(name)
    assert blk is not None, f"{name}: импорт run_card голый — снимок воронки (плоские копии) упадёт ImportError"
    assert "ImportError" in blk and "карточка прогона недоступна" in blk and "stderr" in blk
    assert OLD_IMPORT in (ETAZHI / name).read_text(encoding="utf-8")        # test_run_card_etazhi проверяет эту строку


@pytest.mark.parametrize("name", FILES)
def test_flat_snapshot_without_run_card_runs_without_card(tmp_path, name):
    flat = snapshot_dir(tmp_path)
    assert not (flat / "run_card.py").exists()
    out = tmp_path / "vyhod"
    r = run_flat(flat, guard_block(name), out)
    assert r.returncode == 0, r.stderr
    assert "('результат', 5, 7)" in r.stdout                                 # функция и её результат — как есть
    assert "карточка прогона недоступна" in r.stderr and name.split(".")[0] in r.stderr
    assert not (out / "RUN.json").exists()                                  # карточки нет, прогон идёт


@pytest.mark.parametrize("name", FILES)
def test_control_with_run_card_beside_writes_card(tmp_path, name):
    flat = snapshot_dir(tmp_path, with_card=True)
    out = tmp_path / "vyhod"
    r = run_flat(flat, guard_block(name), out)
    assert r.returncode == 0, r.stderr
    assert "('результат', 5, 7)" in r.stdout
    assert "недоступна" not in r.stderr
    card = json.loads((out / "RUN.json").read_text(encoding="utf-8"))
    assert card["status"] == "ok"


@pytest.mark.parametrize("name", FILES)
def test_control_old_bare_import_fails_in_flat_snapshot(tmp_path, name):
    """−контроль теста: как было до правки (голый импорт) в плоской папке без run_card.py — ImportError; значит тест выше действительно ловит поломку снимка."""
    flat = snapshot_dir(tmp_path)
    r = run_flat(flat, OLD_IMPORT, tmp_path / "vyhod")
    assert r.returncode != 0 and "ModuleNotFoundError" in r.stderr and "run_card" in r.stderr


@pytest.mark.parametrize("name", FILES)
def test_partial_snapshot_run_card_without_run_manifest(tmp_path, name):
    flat = snapshot_dir(tmp_path, with_card=True, with_manifest=False)
    assert (flat / "run_card.py").exists() and not (flat / "run_manifest.py").exists()
    out = tmp_path / "vyhod"
    r = run_flat(flat, guard_block(name), out)
    assert r.returncode == 0, r.stderr
    assert "карточка прогона недоступна" in r.stderr and not (out / "RUN.json").exists()


def test_storozh_selftest_lines_formatted():
    src = (ETAZHI / "storozh.py").read_text(encoding="utf-8")
    assert "lines =[" not in src and "lines = ['Сверщик на себе" in src
