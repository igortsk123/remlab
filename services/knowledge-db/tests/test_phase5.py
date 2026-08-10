"""Гейты KB5a/KB5b офлайн: реплей вердиктов из реестра (git), recall-гейты,
семьи/canonical/конфликты/зависимости, ID-стабильность (крит.№7 плана)."""
import os
from pathlib import Path

import pytest

from kdb.io import read_jsonl
from kdb.phase0 import run_phase0
from kdb.phase1 import run_phase1
from kdb.phase2 import run_phase2
from kdb.phase3 import run_phase3
from kdb.phase4 import run_phase4
from kdb.phase5a import run_phase5a
from kdb.phase5b import run_phase5b

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"


@pytest.fixture(scope="module")
def staged5(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    os.environ["KDB_NO_LLM"] = "1"
    os.environ["KDB_NO_EMBED"] = "1"
    try:
        run_phase0(SRC, staging, "rtest")
        run_phase1(staging, SRC)
        run_phase2(staging)
        run_phase3(staging)
        run_phase4(staging)
        rep5a = run_phase5a(staging)
        rep5b = run_phase5b(staging)
    finally:
        os.environ.pop("KDB_NO_LLM", None)
        os.environ.pop("KDB_NO_EMBED", None)
    return staging, rep5a, rep5b


def test_offline_replay_no_llm(staged5):
    _, rep5a, _ = staged5
    assert rep5a["llm"]["calls"] == 0
    assert rep5a["llm_judged"]["failed_batches"] == 0


def test_recall_gates(staged5):
    _, rep5a, _ = staged5
    assert rep5a["recall_full"] == 1.0
    assert rep5a["recall_ablation_no_hint"] >= 0.95
    assert rep5a["seed"]["total"] >= 90
    assert rep5a["seed"]["cross_segment"] >= 20
    assert rep5a["seed"]["verified_positives"] >= 40


def test_04a_verdict_invariants(staged5):
    staging, _, _ = staged5
    rows = read_jsonl(staging / "04a_semantic_comparison_candidates.jsonl")
    assert rows
    for r in rows:
        if r.get("scope_relation") == "DISJOINT":
            assert r.get("relationship") not in ("EXACT_DUPLICATE",
                                                 "SEMANTIC_DUPLICATE",
                                                 "TRUE_CONFLICT"), r["pair_id"]
        if r["verdict_status"] == "DETERMINISTIC":
            assert r["basis"].startswith("DET:")


def test_hint_audit_full_coverage(staged5):
    _, rep5a, _ = staged5
    audit = rep5a["hint_audit"]
    assert sum(audit.values()) == rep5a["seed"]["hint"]
    assert audit["CONFIRMED"] >= audit["REJECTED"]


def test_families_cover_all_atoms_once(staged5):
    staging, _, rep5b = staged5
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    fams = read_jsonl(staging / "04_claim_groups.jsonl")
    member_ids = [m for f in fams for m in f["member_ids"]]
    assert len(member_ids) == len(atoms)
    assert len(set(member_ids)) == len(atoms)
    assert rep5b["families"] == len(fams)


def test_canonical_scope_homogeneous_and_cover(staged5):
    staging, _, _ = staged5
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    member_ids = [m for c in canon for m in c["member_ids"]]
    assert len(member_ids) == len(atoms) == len(set(member_ids))
    for c in canon:
        assert c["production_policy_status"] == "UNDECIDED_IN_THIS_PIPELINE"


def test_regression_R068_family_and_dependency(staged5):
    """R068: 1:8 и 1:12 — одна семья (один вопрос), РАЗНЫЕ canonical-варианты
    (условия различают scope), зависимость same-record — VERIFIED_STRUCTURAL."""
    staging, _, _ = staged5
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    m1 = next(a for a in atoms if a["observation"]["record_id"] == "R068"
              and a["observation"]["measurement_id"] == "M001"
              and "::ch02::" in a["observation"]["logical_package_key"])
    m4 = next(a for a in atoms if a["observation"]["record_id"] == "R068"
              and a["observation"]["measurement_id"] == "M004"
              and "::ch02::" in a["observation"]["logical_package_key"])
    fams = read_jsonl(staging / "04_claim_groups.jsonl")
    fam_of = {m: f["claim_family_id"] for f in fams for m in f["member_ids"]}
    assert fam_of[m1["atomic_claim_id"]] == fam_of[m4["atomic_claim_id"]]
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    canon_of = {m: c["canonical_claim_id"] for c in canon
                for m in c["member_ids"]}
    assert canon_of[m1["atomic_claim_id"]] != canon_of[m4["atomic_claim_id"]]


def test_regression_R030_wheelchair_separate_canonical(staged5):
    staging, _, _ = staged5
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    m1 = next(a for a in atoms if a["observation"]["record_id"] == "R030"
              and a["observation"]["measurement_id"] == "M001"
              and "::ch01::" in a["observation"]["logical_package_key"])
    m3 = next(a for a in atoms if a["observation"]["record_id"] == "R030"
              and a["observation"]["measurement_id"] == "M003"
              and "::ch01::" in a["observation"]["logical_package_key"])
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    canon_of = {m: c["canonical_claim_id"] for c in canon
                for m in c["member_ids"]}
    assert canon_of[m1["atomic_claim_id"]] != canon_of[m3["atomic_claim_id"]]


def test_conflicts_scope_aware(staged5):
    staging, _, _ = staged5
    conf = read_jsonl(staging / "05_conflict_groups.jsonl")
    for c in conf:
        assert c["scope_relation"] in ("EQUIVALENT", "OVERLAPPING")
        assert c["member_count"] >= 2
        assert c["resolution_status"] == "UNRESOLVED"  # победителей не выбираем


def test_dependency_closure_classes(staged5):
    staging, _, rep5b = staged5
    deps = read_jsonl(staging / "06b_claim_dependency_graph.jsonl")
    assert rep5b["dependency_edges"] == len(deps)
    for d in deps:
        if d["mandatory_closure"]:
            assert d["verification_status"] == "VERIFIED_STRUCTURAL"
            assert d["closure_class"] == "BIDIRECTIONAL_MANDATORY"


def test_id_stability_cold_llm(staged5, tmp_path):
    """Крит.№7: пересборка 5b с холодным LLM (реестры заморожены) — те же ID."""
    staging, _, _ = staged5
    before = {
        name: (staging / name).read_bytes()
        for name in ("04_claim_groups.jsonl", "06_canonical_knowledge.jsonl",
                     "05_conflict_groups.jsonl",
                     "06b_claim_dependency_graph.jsonl")}
    os.environ["KDB_NO_LLM"] = "1"
    try:
        run_phase5b(staging)
    finally:
        os.environ.pop("KDB_NO_LLM", None)
    for name, prev in before.items():
        assert (staging / name).read_bytes() == prev, name
