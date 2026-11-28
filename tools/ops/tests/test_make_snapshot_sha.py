"""Билдер снимков «из репо по SHA» (tools/ops/make_snapshot_sha.py; канон по вердикту Fable 28.11, условия а/б/в).

Что проверяем (свой мир в tmp_path: «база 2234», «база 2105», внешний файл, явный список; код репо — настоящий, `git archive HEAD`; правки путей выключены ключом --bez-pravok):
  1. ДЕТЕРМИНИЗМ (условие в): два запуска с одного SHA в ту же папку → побайтно одинаковые SHA256SUMS (и MANIFEST, FLOORPLAN-SHA, KAK-ZAPUSKAT);
  2. −контроль детерминизма: изменилось содержимое файла списка (и список пересоздан) → SHA256SUMS другие (значит «одинаковые» в п.1 — не пустое сравнение);
  3. ЯВНЫЙ СПИСОК (условие а): черновики в базовых папках (plan_to_result.rab10.py, y2_b3_stend.py, make_snapshot.sha.py, *.bak-*) в снимок НЕ попадают; файл, убранный из списка, тоже не попадает;
  4. файл списка изменился с момента записи → ОТКАЗ (rc=1) и снимок не создан; нет файла → ОТКАЗ; непустая папка назначения → ОТКАЗ;
  5. MANIFEST (условие б): «из репо по SHA <полный sha>» и по строке на каждый файл не из репо — путь · источник · путь источника · sha256 ИСТОЧНИКА (до правки пути);
  6. настоящий список tools/ops/make_snapshot_sha_base.tsv: разбирается, у каждой строки 4 поля, sha256 из 64 hex, пути не повторяются, ни одного черновика и ни одного пути из репо (tools/…).
Запуск: `python -m pytest tools/ops/tests/test_make_snapshot_sha.py -q -p no:cacheprovider`. Нужны только git и стандартная библиотека (реальные базы 2234/2105 не нужны — в CI их нет)."""
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
REPO = OPS.parents[1]
BUILDER = OPS / "make_snapshot_sha.py"
REAL_LIST = OPS / "make_snapshot_sha_base.tsv"
DRAFTS = ["plan_to_result.rab10.py", "plan_to_result.rab10b.py", "y2_b3_stend.py", "y2_b3_stend_v2.py", "make_snapshot.sha.py", "make_snapshot.rab8.py", "tool_a.py.bak-1128"]

sys.path.insert(0, str(OPS))

if shutil.which("git") is None:
    pytest.skip("нет git", allow_module_level=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def head_sha():
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout.strip()


class World:
    """база 2234 (3 файла + KAK-ZAPUSKAT + черновики), база 2105 (run_sb100.py), внешний файл, список"""

    def __init__(self, root):
        self.root = root
        self.b34, self.b05, self.ext = root / "base2234", root / "base2105", root / "ext"
        for d in (self.b34, self.b34 / "sub", self.b05, self.ext):
            d.mkdir(parents=True, exist_ok=True)
        (self.b34 / "tool_a.py").write_text("DATA = '%s/data'\nprint('a')\n" % self.b34, encoding="utf-8")
        (self.b34 / "conf.json").write_text('{"k": 1}\n', encoding="utf-8")
        (self.b34 / "sub" / "inner.py").write_text("X = 1\n", encoding="utf-8")
        (self.b34 / "KAK-ZAPUSKAT.md").write_text("Запуск из %s\n" % self.b34, encoding="utf-8")
        for n in DRAFTS:
            (self.b34 / n).write_text("# черновик %s\n" % n, encoding="utf-8")
        (self.b05 / "run_sb100.py").write_text("S = '%s'\n" % self.b05, encoding="utf-8")
        (self.ext / "nc_ext.py").write_text("E = 2\n", encoding="utf-8")
        self.rows = [
            ("tool_a.py", "2234", "tool_a.py", self.b34 / "tool_a.py"),
            ("conf.json", "2234", "conf.json", self.b34 / "conf.json"),
            ("sub/inner.py", "2234", "sub/inner.py", self.b34 / "sub" / "inner.py"),
            ("KAK-ZAPUSKAT.md", "2234-sluzh", "KAK-ZAPUSKAT.md", self.b34 / "KAK-ZAPUSKAT.md"),
            ("run_sb100.py", "2105", "run_sb100.py", self.b05 / "run_sb100.py"),
            ("nc-models/nc_ext.py", "vneshniy", str(self.ext / "nc_ext.py"), self.ext / "nc_ext.py"),
        ]
        self.tsv = root / "base.tsv"
        self.write_list()

    def write_list(self, skip=()):
        lines = ["# тестовый список"]
        for dst, tag, src, p in self.rows:
            if dst not in skip:
                lines.append("\t".join((dst, tag, src, sha(p.read_bytes()))))
        self.tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build(self, dest):
        return subprocess.run([sys.executable, "-I", str(BUILDER), head_sha(), str(dest), "--repo", str(REPO), "--base-2234", str(self.b34), "--base-2105", str(self.b05),
                               "--list", str(self.tsv), "--bez-pravok"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return World(tmp_path_factory.mktemp("snapsha"))


@pytest.fixture(scope="module")
def two_runs(world):
    """два запуска с одного SHA в одну и ту же папку (первый результат уносится в сторону); → (dest, первый комплект байтов, второй)"""
    dest = world.root / "out" / "snap"
    dest.parent.mkdir()
    keep = ("SHA256SUMS", "MANIFEST.md", "FLOORPLAN-SHA.txt", "KAK-ZAPUSKAT.md")
    r1 = world.build(dest)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    first = {n: (dest / n).read_bytes() for n in keep}
    first_files = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    shutil.move(str(dest), str(world.root / "out" / "run1"))
    r2 = world.build(dest)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    second = {n: (dest / n).read_bytes() for n in keep}
    return dest, first, second, first_files


def test_two_runs_same_sha256sums(two_runs):
    dest, first, second, first_files = two_runs
    assert len(first["SHA256SUMS"].splitlines()) > 1000          # настоящий код репо (tools/scout, tools/floorplan) — не пустой снимок
    assert first["SHA256SUMS"] == second["SHA256SUMS"]
    assert first["MANIFEST.md"] == second["MANIFEST.md"]
    assert first["FLOORPLAN-SHA.txt"] == second["FLOORPLAN-SHA.txt"] and first["KAK-ZAPUSKAT.md"] == second["KAK-ZAPUSKAT.md"]
    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()) == first_files


def test_sha256sums_match_files(two_runs):
    dest = two_runs[0]
    for ln in (dest / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        h, _, name = ln.partition("  ")
        assert sha((dest / name).read_bytes()) == h, name


def test_control_changed_content_changes_sums(world, two_runs):
    """−контроль п.1: другое содержимое файла списка → другие SHA256SUMS"""
    old = two_runs[1]["SHA256SUMS"]
    (world.b34 / "conf.json").write_text('{"k": 2}\n', encoding="utf-8")
    world.write_list()
    d = world.root / "out2" / "snap"
    d.parent.mkdir()
    r = world.build(d)
    assert r.returncode == 0, r.stdout
    assert (d / "SHA256SUMS").read_bytes() != old
    (world.b34 / "conf.json").write_text('{"k": 1}\n', encoding="utf-8")        # вернуть как было
    world.write_list()


def test_drafts_not_in_snapshot(two_runs):
    dest = two_runs[0]
    present = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
    sums = (dest / "SHA256SUMS").read_text(encoding="utf-8")
    snimok = (dest / "SNIMOK.md").read_text(encoding="utf-8")
    for n in DRAFTS:
        assert n not in present and n not in sums and n not in snimok, n
    assert {"tool_a.py", "conf.json", "sub/inner.py", "run_sb100.py", "nc-models/nc_ext.py"} <= present      # файлы списка — взяты
    assert "KAK-ZAPUSKAT.md" in present                                                                   # служебный — пишется заново


def test_file_removed_from_list_not_taken(world):
    world.write_list(skip=("sub/inner.py",))
    d = world.root / "out3" / "snap"
    d.parent.mkdir()
    r = world.build(d)
    assert r.returncode == 0, r.stdout
    assert not (d / "sub" / "inner.py").exists() and (world.b34 / "sub" / "inner.py").exists()        # файл лежит в базе, но в списке его нет
    world.write_list()


def test_changed_source_refused(world):
    p = world.b34 / "tool_a.py"
    old = p.read_text(encoding="utf-8")
    p.write_text(old + "# правка после записи списка\n", encoding="utf-8")
    d = world.root / "out4" / "snap"
    d.parent.mkdir()
    r = world.build(d)
    p.write_text(old, encoding="utf-8")
    assert r.returncode == 1 and "изменился" in r.stdout and "tool_a.py" in r.stdout, r.stdout
    assert not d.exists()


def test_missing_source_refused(world):
    p = world.ext / "nc_ext.py"
    data = p.read_bytes()
    p.rename(world.ext / "nc_ext.py.moved")
    d = world.root / "out5" / "snap"
    d.parent.mkdir()
    r = world.build(d)
    (world.ext / "nc_ext.py.moved").rename(p)
    assert p.read_bytes() == data
    assert r.returncode == 1 and "нет файла списка" in r.stdout, r.stdout
    assert not d.exists()


def test_nonempty_dest_refused(world):
    d = world.root / "out6" / "snap"
    d.mkdir(parents=True)
    (d / "x.txt").write_text("занято", encoding="utf-8")
    r = world.build(d)
    assert r.returncode == 1 and "не пуста" in r.stdout, r.stdout
    assert (d / "x.txt").read_text(encoding="utf-8") == "занято"


def test_manifest_lists_every_non_repo_file(world, two_runs):
    dest = two_runs[0]
    man = (dest / "MANIFEST.md").read_text(encoding="utf-8")
    full = head_sha()
    assert "из репо по SHA %s" % full in man
    assert "## Файлы НЕ из репо (5)" in man
    assert "(sha256 %s)" % sha(world.tsv.read_bytes()) in man                      # какой именно список взят
    for dst, tag, src, p in world.rows:
        if tag == "2234-sluzh":
            continue
        line = "- %s · %s · %s · %s" % (dst, tag, p, sha(p.read_bytes()))
        assert line in man, line
    assert "БЕЗ ПРАВОК ПУТЕЙ" in man                                              # пробный режим помечен
    assert "из репо по SHA %s" % full in (dest / "SNIMOK.md").read_text(encoding="utf-8")
    # путь к снимку в копии заменён, а в MANIFEST — sha256 источника (до замены): они различаются
    assert sha((dest / "tool_a.py").read_bytes()) != sha((world.b34 / "tool_a.py").read_bytes())
    assert str(dest) in (dest / "tool_a.py").read_text(encoding="utf-8") and str(world.b34) not in (dest / "tool_a.py").read_text(encoding="utf-8")


def test_real_list_is_explicit_and_clean():
    import make_snapshot_sha as B

    rows = B.load_list(str(REAL_LIST))
    assert len(rows) >= 100
    paths = [r[0] for r in rows]
    assert len(set(paths)) == len(paths)
    assert sum(1 for r in rows if r[1] == "2234-sluzh") == 1 and sum(1 for r in rows if r[1] == "2105") == 1
    draft = re.compile(r"(^|/)(plan_to_result\.rab|y2_b3_stend|make_snapshot\.(sha|rab\d|frozen)|patch_|scratch_)|\.bak")
    for p in paths:
        assert not draft.search(p), p
        assert not p.startswith(("tools/", "floorplan/")), p                         # то, что идёт из репо, в списке не повторяется
    for r in rows:
        assert re.fullmatch(r"[0-9a-f]{64}", r[3]), r
