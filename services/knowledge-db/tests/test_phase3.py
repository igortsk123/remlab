"""Гейты KB3: numeric/symbolic views, условия из реестра (без сети),
presence-регрессия (egress), стабильность ID при обогащении."""
import os
from decimal import Decimal
from pathlib import Path

import pytest

from kdb.io import read_jsonl
from kdb.phase0 import run_phase0
from kdb.phase1 import run_phase1
from kdb.phase2 import run_phase2
from kdb.phase3 import run_phase3
from kdb.symbolic import build_symbolic_view
from kdb.units import build_numeric_view, parse_scalar

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"


# ---------- unit-тесты 2B/2C ----------

def test_parse_scalar_formats():
    assert parse_scalar(48, "in")[1] == Decimal("48")
    st, v, ex = parse_scalar("8'-3\"", "ft_in")
    assert st == "OK" and v == Decimal("99") and ex["reparsed_unit"] == "in"
    st, v, ex = parse_scalar("1:12", None)
    assert st == "RATIO" and ex["ratio"] == ["1", "12"]
    st, v, _ = parse_scalar("7-plus", "count")
    assert st == "OPEN_GTE" and v == Decimal("7")
    assert parse_scalar("hand-lettered", "in")[0] == "AMBIGUOUS"


def test_numeric_view_consistent_and_conflicting():
    ok = build_numeric_view({"value_original": 36, "unit_original": "in",
                             "normalized_value": 91.4, "canonical_unit": "cm",
                             "range_original": [None, None],
                             "normalized_range": [None, None]})
    assert ok["comparison"] == "CONSISTENT" and ok["value"] == "91.44"
    # опечатка книги: 18 in напечатано как 914 mm (регресс ch3 R079)
    bad = build_numeric_view({"value_original": 18, "unit_original": "in",
                              "normalized_value": 91.4, "canonical_unit": "cm",
                              "range_original": [None, None],
                              "normalized_range": [None, None],
                              "conversion_note": "as printed"})
    assert bad["comparison"] == "CONFLICTING"
    assert bad["conflict_subtype"] == "INTERNAL_UNIT_EQUIVALENCY_CONFLICT"


def test_symbolic_examples():
    v = build_symbolic_view("rise / run <= 1/12", None)
    assert v["parse_status"] == "PARSED" and v["kind"] == "INEQUALITY"
    v = build_symbolic_view("glazing_area >= 0.08 * floor_area", None)
    assert v["parse_status"] == "PARSED" and v["kind"] == "PROPORTION"
    v = build_symbolic_view("cost(remove existing element) > cost(retain)", None)
    assert v["parse_status"] == "PARTIALLY_PARSED"
    assert v["kind"] == "QUALITATIVE_RELATION"
    v = build_symbolic_view("efficacy = lumens / watts", "EXAMPLE")
    assert v["example_only"] and v["kind"] == "EXAMPLE"


# ---------- интеграция: фазы 0-3 офлайн (реестр в git, LLM выключен) ----------

@pytest.fixture(scope="module")
def staged3(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    run_phase0(SRC, staging, "rtest")
    run_phase1(staging, SRC)
    run_phase2(staging)
    pre_ids = {a["atomic_claim_id"]
               for a in read_jsonl(staging / "02_atomic_claims.jsonl")}
    os.environ["KDB_NO_LLM"] = "1"
    try:
        stats = run_phase3(staging)
    finally:
        os.environ.pop("KDB_NO_LLM", None)
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    return staging, stats, atoms, pre_ids


def test_offline_replay_from_registry(staged3):
    _, stats, _, _ = staged3
    assert stats["llm"]["calls"] == 0  # всё из реестра/кэша
    assert stats["predicate_coverage"] >= 0.6


def test_numeric_distribution_matches_profile(staged3):
    _, stats, _, _ = staged3
    n = stats["numeric_comparison"]
    assert n["CONSISTENT"] >= 2200
    assert n["CONFLICTING"] == 20
    assert n["UNKNOWN"] == 0


def test_regression_egress_presence_atom(staged3):
    """Спека, mandatory regression 4: existence/cardinality отдельно от размеров."""
    _, _, atoms, _ = staged3
    r159 = [a for a in atoms
            if a["observation"]["record_id"] == "R159"
            and "::ch02::" in a["observation"]["logical_package_key"]]
    widths = [a for a in r159 if a["projection_mode"] == "MEASUREMENT_BOUND"]
    pres = [a for a in r159 if a["slot"].get("k") == "R_PRESENCE"]
    assert len(widths) == 4 and len(pres) == 1
    p = pres[0]
    assert p["views"]["quantification_view"]["kind"] == "EXISTS_MIN"
    assert p["views"]["quantification_view"]["min"] == 1
    assert p["atomic_claim_id"] not in {w["atomic_claim_id"] for w in widths}
    # D22: отсутствие таргета — кандидат в нарушение, не в неприменимость
    assert p["views"]["constraint_target_view"][
        "target_absence_is_violation_candidate"] is True


def test_presence_no_dimensional_false_positives(staged3):
    _, stats, atoms, _ = staged3
    pres = [a for a in atoms if a["slot"].get("k") == "R_PRESENCE"]
    assert stats["presence_atoms"] == len(pres) == 2
    assert all(a["claim"]["min_count"] <= 10 for a in pres)
    assert all("PRESENCE_PATTERN_AUTO" in a["flags"]["review"] for a in pres)


def test_ids_stable_through_enrichment(staged3):
    _, _, atoms, pre_ids = staged3
    post_ids = {a["atomic_claim_id"] for a in atoms
                if a["slot"].get("k") != "R_PRESENCE"}
    assert post_ids == pre_ids


def test_examples_never_backbone(staged3):
    _, _, atoms, _ = staged3
    for a in atoms:
        if a["strength"]["effective"] == "EXAMPLE" or \
                a["claim"].get("value_type") == "EXAMPLE":
            assert a["utility"]["judge_backbone_eligible"] is False
    # и наоборот: backbone только у SOURCE_CONSTRAINT_GUIDANCE
    for a in atoms:
        if a["utility"]["judge_backbone_eligible"]:
            assert "SOURCE_CONSTRAINT_GUIDANCE" in a["utility"]["classes"]


def test_condition_predicates_replace_unknown(staged3):
    """Ветка с wheelchair-условием получает предикат, а не UNKNOWN (R030 C002)."""
    import json as j
    _, _, atoms, _ = staged3
    (a,) = [x for x in atoms
            if x["observation"]["record_id"] == "R030"
            and x["observation"]["measurement_id"] == "M003"
            and "::ch01::" in x["observation"]["logical_package_key"]]
    s = j.dumps(a["applicability"]["ast"], ensure_ascii=False)
    assert "mobility_context" in s
    assert "OPAQUE_CONDITION_PENDING_NORMALIZATION" not in s


def test_double_enrichment_blocked(staged3):
    staging, _, _, _ = staged3
    with pytest.raises(SystemExit):
        run_phase3(staging)
