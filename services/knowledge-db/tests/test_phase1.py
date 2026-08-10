"""Гейт KB1: lossless merge — счётчики, UID, иммутабельность raw, детерминизм."""
from pathlib import Path

import pytest

from kdb.canonical import jcs_sha256
from kdb.io import load_json_strict
from kdb.phase0 import run_phase0
from kdb.phase1 import run_phase1

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    run_phase0(SRC, staging, "rtest")
    res = run_phase1(staging, SRC)
    return staging, res


def test_counts_equal_manifest(staged):
    staging, res = staged
    manifest = load_json_strict(staging / "00_input_manifest.json")
    got = res["gate"]["totals"]
    for k, v in got.items():
        assert manifest["corpus_totals"][k] == v, k
    assert got["records"] == 1729 and got["measurements"] == 2559


def test_raw_semantically_unchanged(staged):
    staging, _ = staged
    manifest = load_json_strict(staging / "00_input_manifest.json")
    merged = load_json_strict(staging / "01_raw_merged.json")
    by_key = {p["logical_package_key"]: p for p in manifest["packages"]}
    assert len(merged["packages"]) == 13
    for p in merged["packages"]:
        assert jcs_sha256(p["raw"]) == by_key[p["logical_package_key"]][
            "canonical_json_sha256"]


def test_packages_sorted_by_logical_key(staged):
    staging, _ = staged
    merged = load_json_strict(staging / "01_raw_merged.json")
    keys = [p["logical_package_key"] for p in merged["packages"]]
    assert keys == sorted(keys)


def test_deterministic_rerun(staged, tmp_path):
    staging, _ = staged
    s2 = tmp_path / "s2"
    run_phase0(SRC, s2, "rtest")
    run_phase1(s2, SRC)
    assert (staging / "01_raw_merged.json").read_bytes() == \
        (s2 / "01_raw_merged.json").read_bytes()
