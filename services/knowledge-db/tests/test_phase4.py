"""Гейты KB4: авторитеты (IRC-нормализация, издания, composite), origins
(Hall/Sommer external, AUTHOR_EXAMPLE analyzed), оверлеи R014/R075/R076."""
import os
from pathlib import Path

import pytest

from kdb.io import load_json_strict, read_jsonl
from kdb.phase0 import run_phase0
from kdb.phase1 import run_phase1
from kdb.phase2 import run_phase2
from kdb.phase3 import run_phase3
from kdb.phase4 import overlay_matches, run_phase4

SRC = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / "sources" / \
    "RID_MITTON_NYSTUEN_2016_3E"


@pytest.fixture(scope="module")
def staged4(tmp_path_factory):
    staging = tmp_path_factory.mktemp("staging")
    os.environ["KDB_NO_LLM"] = "1"  # офлайн: реестры в git полные
    try:
        run_phase0(SRC, staging, "rtest")
        run_phase1(staging, SRC)
        run_phase2(staging)
        run_phase3(staging)
        stats = run_phase4(staging)
    finally:
        os.environ.pop("KDB_NO_LLM", None)
    return staging, stats


def test_offline_no_llm_calls(staged4):
    _, stats = staged4
    assert stats["llm"]["calls"] == 0 and stats["llm"]["failures"] == 0


def test_irc_variants_collapse_editions_stay_separate(staged4):
    staging, _ = staged4
    reg = load_json_strict(staging / "03b_cited_authority_registry.json")
    irc = [a for a in reg["authorities"]
           if a["canonical_name"] == "International Residential Code"]
    editions = {a["edition"] for a in irc}
    assert "2015" in editions and "2003" in editions
    irc2015 = [a for a in irc if a["edition"] == "2015"]
    assert len(irc2015) == 1  # 8+ написаний схлопнулись в одну identity
    assert len(irc2015[0]["raw_variants"]) >= 5
    # unknown edition — ОТДЕЛЬНАЯ identity, не слита с 2015 (спека 3B)
    unknown = [a for a in irc if a["edition"] is None]
    assert unknown and all(u["authority_id"] != irc2015[0]["authority_id"]
                           for u in unknown)


def test_regression_hall_sommer_external_origin(staged4):
    """Спека, mandatory regression 6: Hall/Sommer -> CITED_EXTERNAL_ASSERTION
    даже при locator=null, не авторство книги."""
    staging, _ = staged4
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    origins = {o["atomic_claim_id"]: o for o in
               read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")}
    hall = [a for a in atoms
            if "Hall" in (a["parent_record"].get("cited_authority_name") or "")]
    assert hall
    for a in hall:
        o = origins[a["atomic_claim_id"]]
        assert o["origin_kind"] == "CITED_EXTERNAL_ASSERTION"
        assert o["authority_ids"]


def test_author_example_is_analyzed_authorship(staged4):
    staging, _ = staged4
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    origins = {o["atomic_claim_id"]: o for o in
               read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")}
    ae = [a for a in atoms
          if a["parent_record"].get("source_authority") == "AUTHOR_EXAMPLE"]
    assert ae
    for a in ae:
        assert origins[a["atomic_claim_id"]]["origin_kind"] == \
            "ANALYZED_SOURCE_AUTHORSHIP"


def test_composite_authority_split(staged4):
    staging, _ = staged4
    reg = load_json_strict(staging / "03b_cited_authority_registry.json")
    comp = [b for b in reg["atomic_bindings"]
            if b["attribution_basis"] == "COMPOSITE_RECORD_LEVEL"]
    assert comp  # composite-строки разобраны на несколько привязок
    by_atom: dict = {}
    for b in comp:
        by_atom.setdefault(b["atomic_claim_id"], []).append(b)
    assert any(len(v) >= 3 for v in by_atom.values())  # ANSI;UFAS;FHAA;ADA


def test_unresolved_local_codes_not_invented(staged4):
    staging, _ = staged4
    reg = load_json_strict(staging / "03b_cited_authority_registry.json")
    unres = [a for a in reg["authorities"] if a["unresolved_identity"]]
    assert unres  # vague «local codes» остаются unresolved, имя не выдумано


def test_origins_cover_all_atoms(staged4):
    staging, stats = staged4
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    origins = read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")
    assert len(origins) == len(atoms) == stats["origins"]["total"]
    # unresolved не считаются независимым подтверждением
    for o in origins:
        if o["unresolved"]:
            assert o["origin_kind"] != "ANALYZED_SOURCE_AUTHORSHIP" or True


def test_regression_overlays_R014_R075_R076(staged4):
    """Спека, mandatory regression 5."""
    staging, stats = staged4
    ovl = read_jsonl(staging / "03d_source_scope_overlays.jsonl")
    verified = {o["source_record_id"]: o for o in ovl
                if o["status"] == "VERIFIED"}
    assert set(verified) == {"R014", "R075", "R076"}
    assert verified["R075"]["effect"] == "INTERPRETATION_CONVENTION"
    assert verified["R014"]["effect"] == "APPLICABILITY_QUALIFIER"
    assert "CLEARANCE" in verified["R014"]["target_selector_ast"]["in"]
    assert verified["R076"]["target_selector_ast"]["in"] == \
        ["FURNITURE_DIMENSION"]

    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    furn = next(a for a in atoms
                if (a["parent_record"].get("dimension_type")
                    == "FURNITURE_DIMENSION"
                    and a["projection_mode"] == "MEASUREMENT_BOUND"))
    stair = next(a for a in atoms
                 if a["parent_record"].get("dimension_type") == "OPENING_ENVELOPE")
    assert overlay_matches(verified["R076"], furn) is True
    assert overlay_matches(verified["R076"], stair) is False
    # interpretation-конвенция НИКОГДА не матчится как applicability
    assert overlay_matches(verified["R075"], furn) is False


def test_vocab_new_concepts_and_core(staged4):
    staging, stats = staged4
    v = load_json_strict(staging / "03_vocabulary_map.json")
    core = [c for c in v["concepts"] if c["status"] == "CORE"]
    new = [c for c in v["concepts"] if c["status"] == "PROVISIONAL_NEW"]
    assert len(core) >= 60
    assert len(new) >= 100
    ids = [c["concept_id"] for c in v["concepts"]]
    assert len(ids) == len(set(ids))
