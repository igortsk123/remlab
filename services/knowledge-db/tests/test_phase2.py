"""Гейты KB2: проекция, привязки без утечек (R030/R096/R068), стабильные ID."""
import copy
from pathlib import Path

import pytest

from kdb.io import load_json_strict, read_jsonl
from kdb.phase0 import run_phase0
from kdb.phase1 import run_phase1
from kdb.phase2 import build_atomics, run_phase2

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    run_phase0(SRC, staging, "rtest")
    run_phase1(staging, SRC)
    stats = run_phase2(staging)
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    return staging, stats, atoms


def _find(atoms, ch_key_part, rid, mid=None):
    return [a for a in atoms
            if ch_key_part in a["observation"]["logical_package_key"]
            and a["observation"]["record_id"] == rid
            and a["observation"]["measurement_id"] == mid]


def test_totals(staged):
    _, stats, atoms = staged
    assert stats["atomics_total"] == 3347 == len(atoms)
    assert stats["measurement_bound"] == 2559
    assert stats["record_semantic"] == 788


def test_regression_R030_no_context_leak(staged):
    """Спека, mandatory regression 1: C001 standing vs C002 wheelchair."""
    _, _, atoms = staged
    for mid, ctx, strength in (("M001", "C001", "TYPICAL_RANGE"),
                               ("M002", "C001", "TYPICAL_RANGE"),
                               ("M003", "C002", "PREFERRED"),
                               ("M004", "C002", "MAXIMUM")):
        (a,) = _find(atoms, "::ch01::", "R030", mid)
        assert a["bindings"]["context_ids"] == [ctx], mid
        branch_ids = [b["context_id"] for b in a["applicability"]["branches"]]
        assert branch_ids == [ctx], mid
        # parent MIXED не перетирает силу ребёнка
        assert a["strength"]["effective"] == strength, mid
        assert a["strength"]["origin"] == "MEASUREMENT"
        assert a["strength"]["parent_record_strength"] == "MIXED"


def test_regression_R096_door_vs_hallway(staged):
    """Спека, mandatory regression 2: дверь и коридор в своих контекстах."""
    _, _, atoms = staged
    for mid, ctx in (("M001", "C001"), ("M002", "C001"), ("M003", "C002")):
        (a,) = _find(atoms, "::ch02::", "R096", mid)
        assert a["bindings"]["context_ids"] == [ctx], mid


def test_regression_R068_separate_scoped_semantics(staged):
    """Спека, mandatory regression 3: 1:8 MAX и 1:12 REQ_MIN — разные атомы
    со своими условиями; сила ребёнка measurement-локальна."""
    _, _, atoms = staged
    (m1,) = _find(atoms, "::ch02::", "R068", "M001")
    (m4,) = _find(atoms, "::ch02::", "R068", "M004")
    assert m1["source_assertion_uid"] != m4["source_assertion_uid"]
    assert "not serving" in (m1["slot"]["condition"] or "")
    assert "serving a required egress door" in (m4["slot"]["condition"] or "")
    assert m1["strength"]["effective"] == "MAXIMUM"
    assert m4["strength"]["effective"] == "REQUIRED_MINIMUM"


def test_unknown_qualifiers_are_unspecified_not_predicates(staged):
    _, _, atoms = staged
    (a,) = _find(atoms, "::ch01::", "R030", "M001")
    q = a["qualifiers"]
    assert q["population"]["status"] == "UNSPECIFIED_BY_SOURCE"
    # в AST нет предиката по optional-qualifier (C15)
    import json as j
    assert '"population"' not in j.dumps(a["applicability"]["ast"])


def test_collisions_flagged_consistently(staged):
    _, stats, atoms = staged
    flagged = [a for a in atoms
               if "REVIEW_SLOT_COLLISION" in a["flags"]["review"]]
    assert stats["slot_collision_groups"] >= 0
    # у каждого флагованного — группа >= 2 по (anchor, slot-ordinal сняли) —
    # проверяем простое свойство: флаги согласованы с реестром
    reg = read_jsonl(Path(staged[0]) / "02a_source_assertion_revision_registry.jsonl")
    reg_coll = {r["atomic_claim_id"] for r in reg if r["slot_collision"]}
    assert {a["atomic_claim_id"] for a in flagged} == reg_coll


def test_registry_no_support_inflation(staged):
    staging, _, atoms = staged
    reg = read_jsonl(staging / "02a_source_assertion_revision_registry.jsonl")
    assert len(reg) == len(atoms)
    assert all(r["observation_count"] == 1 and r["support_document_count"] == 1
               and r["revision_status"] == "SINGLE" for r in reg)


def test_stable_id_under_unrelated_sibling_edit(staged):
    """Аудит B спеки: правка соседа меняет observation/version, но не ATOM."""
    staging, _, atoms = staged
    merged = load_json_strict(staging / "01_raw_merged.json")
    (before,) = _find(atoms, "::ch01::", "R030", "M001")

    mutated = copy.deepcopy(merged)
    ch1 = next(p for p in mutated["packages"]
               if "::ch01::" in p["logical_package_key"])
    r001 = next(r for r in ch1["raw"]["records"] if r["record_id"] == "R001")
    r001["notes"] = "unrelated edit"
    # имитируем новую версию контента пакета
    ch1["package_content_uid"] = ch1["package_content_uid"][:-4] + "beef"

    atoms2, _, _ = build_atomics(mutated)
    (after,) = [a for a in atoms2
                if a["observation"]["record_id"] == "R030"
                and a["observation"]["measurement_id"] == "M001"
                and "::ch01::" in a["observation"]["logical_package_key"]]
    assert after["atomic_claim_id"] == before["atomic_claim_id"]
    assert after["source_assertion_uid"] == before["source_assertion_uid"]
    assert after["atomic_claim_version_uid"] != before["atomic_claim_version_uid"]


def test_deterministic_rerun(staged, tmp_path):
    staging, _, _ = staged
    s2 = tmp_path / "s2"
    run_phase0(SRC, s2, "rtest")
    run_phase1(s2, SRC)
    run_phase2(s2)
    for name in ("02_atomic_claims.jsonl",
                 "02a_source_assertion_revision_registry.jsonl"):
        assert (staging / name).read_bytes() == (s2 / name).read_bytes()
