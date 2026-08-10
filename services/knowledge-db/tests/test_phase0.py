"""Гейт KB0 на реальном корпусе: валидность, счётчики, детерминизм, схемы."""
from pathlib import Path

import pytest

from kdb.io import load_json_strict
from kdb.phase0 import run_phase0
from kdb.schemacheck import validate_file

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"

# Профиль корпуса 2026-08-10 (remlab_knowledge_db_v1/scratch_profile/)
EXPECTED_TOTALS = {
    "records": 1729,
    "measurements": 2559,
    "evidence": 3146,
    "applicability_contexts": 1954,
    "entities": 4455,
    "excluded_source_items": 137,
    "chapter_review_queue": 287,
}


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    m = run_phase0(SRC, staging, "rtest")
    return m, staging


def test_13_packages_active(manifest):
    m, _ = manifest
    assert len(m["packages"]) == 13
    assert all(p["active_for_semantic_projection"] for p in m["packages"])


def test_corpus_totals_match_profile(manifest):
    m, _ = manifest
    for k, v in EXPECTED_TOTALS.items():
        assert m["corpus_totals"][k] == v, k


def test_pages_contiguous_no_gaps(manifest):
    m, _ = manifest
    gaps = [a for a in m["corpus_anomalies"] if a["kind"] == "PAGE_GAP_OR_OVERLAP"]
    assert gaps == []


def test_known_anomalies_recorded(manifest):
    m, _ = manifest
    kinds = {}
    for p in m["packages"]:
        for a in p["anomalies"]:
            kinds.setdefault(a["kind"], []).append(p["file_name"])
    assert len(kinds["SOURCE_ID_MISSING"]) == 13
    assert any("ofU3" in f for f in kinds["FILENAME_TYPO"])
    assert any("ch3" in f for f in kinds["COVERAGE_INCOMPLETE"])
    assert len(kinds["SEGMENT_FIELDS_BROKEN"]) >= 4  # ch4 x3 + ch6


def test_logical_keys_unique_and_derived_segments(manifest):
    m, _ = manifest
    keys = [p["logical_package_key"] for p in m["packages"]]
    assert len(keys) == len(set(keys))
    ch4 = sorted((p["derived_segment_index"], p["derived_segment_total"])
                 for p in m["packages"] if p["chapter_number"] == 4)
    assert ch4 == [(1, 3), (2, 3), (3, 3)]


def test_deterministic_rerun(manifest, tmp_path):
    _, staging1 = manifest
    staging2 = tmp_path / "s2"
    run_phase0(SRC, staging2, "rtest")
    for name in ("00_input_manifest.json", "source_document_registry.json"):
        assert (staging1 / name).read_bytes() == (staging2 / name).read_bytes()


def test_artifacts_schema_valid(manifest):
    _, staging = manifest
    assert validate_file(staging / "00_input_manifest.json", "00_input_manifest") == []
    assert validate_file(staging / "source_document_registry.json",
                         "source_document_registry") == []


def test_completeness_complete_by_owner_manifest(manifest):
    m, _ = manifest
    assert m["collection_input_completeness"] == "COMPLETE"
    exp = m["expected_input_manifest"]
    assert len(exp["expected_present"]) == 13
    assert len(exp["expected_future_additions"]) == 7


def test_raw_untouched():
    obj = load_json_strict(SRC / "remlab_SOURCE_ID_MISSING_ch1.json")
    assert obj["chapter"]["chapter_number"] == 1
