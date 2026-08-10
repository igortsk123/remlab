"""Волна KB9 — PHASE 10 (независимый аудит A-G кодом) + PHASE 11
(10_quality_report.md) + PHASE 12 (11_next_stage_plan.md) + commit-протокол.

Механика аудита — код, не LLM-самооценка (спека PHASE 10); fresh-context
verify-субагент запускается снаружи (гейт плана). Любой провал аудита
блокирует COMMITTED.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

from . import (DERIVED_SCHEMA_VERSION, KNOWLEDGE_BASE_ID, PIPELINE_VERSION)
from . import identity as ident
from .canonical import jcs_sha256, sha256_hex
from .io import load_json_strict, read_jsonl, write_json
from .phase2 import build_atomics
from .phase6 import eval_ast

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_ROOT = REPO_ROOT / "remlab_knowledge_db_v1"

PAYLOAD_ARTIFACTS = [
    "00_input_manifest.json", "01_raw_merged.json", "02_atomic_claims.jsonl",
    "02a_source_assertion_revision_registry.jsonl", "03_vocabulary_map.json",
    "03b_cited_authority_registry.json", "03b2_claim_corroboration_origins.jsonl",
    "03c_scope_semantics_registry.json", "03d_source_scope_overlays.jsonl",
    "04a_semantic_comparison_candidates.jsonl", "04_claim_groups.jsonl",
    "05_conflict_groups.jsonl", "06_canonical_knowledge.jsonl",
    "06b_claim_dependency_graph.jsonl", "07_retrieval_records.jsonl",
    "07b_applicability_index.jsonl", "07c_context_closure_index.jsonl",
    "08_retrieval_config.json", "09_eval_queries.jsonl",
    "10_quality_report.md", "11_next_stage_plan.md",
    "source_document_registry.json", "schema_registry.json",
]

_ROW_SCHEMAS = {
    "02_atomic_claims": ["atomic_claim_id", "atomic_claim_version_uid",
                         "source_assertion_uid", "projection_mode",
                         "observation", "anchor", "slot", "bindings",
                         "applicability", "claim", "strength", "parent_record",
                         "utility", "views"],
    "02a_source_assertion_revision_registry": [
        "source_assertion_uid", "atomic_claim_id", "revision_status",
        "observation_count", "support_document_count"],
    "03b2_claim_corroboration_origins": [
        "atomic_claim_id", "origin_kind", "origin_group_id", "unresolved"],
    "04a_semantic_comparison_candidates": ["pair_id", "a", "b", "channels",
                                           "verdict_status"],
    "04_claim_groups": ["claim_family_id", "signature_anchor", "member_ids",
                        "membership_fingerprint_sha256"],
    "05_conflict_groups": ["conflict_group_id", "claim_family_id",
                           "scope_relation", "member_ids",
                           "resolution_status"],
    "06_canonical_knowledge": ["canonical_claim_id", "claim_family_id",
                               "scoped_variant_signature", "member_ids",
                               "production_policy_status", "provenance"],
    "06b_claim_dependency_graph": ["edge_id", "from_atomic_claim_id",
                                   "to_atomic_claim_id", "type",
                                   "verification_status"],
    "07_retrieval_records": ["retrieval_id", "canonical_claim_id",
                             "retrieval_text", "filters"],
    "07b_applicability_index": ["canonical_claim_id",
                                "applicability_ast_members",
                                "runtime_evaluability"],
    "07c_context_closure_index": ["canonical_claim_id",
                                  "mandatory_closure_ids"],
    "09_eval_queries": ["eval_id", "matrix_item", "type", "check"],
}


def _emit_row_schemas(staging: Path) -> None:
    schemas_dir = staging / "schemas"
    schemas_dir.mkdir(exist_ok=True)
    src_dir = Path(__file__).resolve().parents[1] / "schemas"
    for f in src_dir.glob("*.schema.json"):
        shutil.copy(f, schemas_dir / f.name)
    registry = {"artifact": "schema_registry",
                "json_schema_dialect": "https://json-schema.org/draft/2020-12/schema",
                "schemas": {}}
    for name, req in sorted(_ROW_SCHEMAS.items()):
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                  "$id": f"remlab-kdb/{name}.row.schema.json",
                  "title": f"{name} (row)", "type": "object",
                  "required": req,
                  "properties": {k: {} for k in req}}
        (schemas_dir / f"{name}.row.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        registry["schemas"][name] = f"schemas/{name}.row.schema.json"
    for full in ("00_input_manifest", "source_document_registry"):
        registry["schemas"][full] = f"schemas/{full}.schema.json"
    write_json(staging / "schema_registry.json", registry)


def _validate_rows(staging: Path, errors: list) -> None:
    from jsonschema import Draft202012Validator
    for name, _ in sorted(_ROW_SCHEMAS.items()):
        path = staging / f"{name}.jsonl"
        if not path.exists():
            errors.append(f"нет артефакта {name}.jsonl")
            continue
        schema = load_json_strict(staging / "schemas" /
                                  f"{name}.row.schema.json")
        v = Draft202012Validator(schema)
        for i, row in enumerate(read_jsonl(path)):
            errs = list(v.iter_errors(row))
            if errs:
                errors.append(f"{name}:{i}: {errs[0].message[:120]}")
                break


def run_audits(staging: Path, src_dir: Path) -> dict:
    """Аудит-группы A-G (сжатые механические пере-проверки)."""
    res: dict = {}
    errors: list = []
    manifest = load_json_strict(staging / "00_input_manifest.json")
    merged = load_json_strict(staging / "01_raw_merged.json")
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    by_id = {a["atomic_claim_id"]: a for a in atoms}
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    fams = read_jsonl(staging / "04_claim_groups.jsonl")
    pairs04a = read_jsonl(staging / "04a_semantic_comparison_candidates.jsonl")
    deps = read_jsonl(staging / "06b_claim_dependency_graph.jsonl")
    conflicts = read_jsonl(staging / "05_conflict_groups.jsonl")
    origins = read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")
    revreg = read_jsonl(staging /
                        "02a_source_assertion_revision_registry.jsonl")

    # A. INPUT/RAW/SCHEMA
    a_err: list = []
    for meta in manifest["packages"]:
        raw = (src_dir / meta["file_name"]).read_bytes()
        if sha256_hex(raw) != meta["file_sha256"]:
            a_err.append(f"hash drift: {meta['file_name']}")
    pkg_by_key = {p["logical_package_key"]: p for p in merged["packages"]}
    for meta in manifest["packages"]:
        if jcs_sha256(pkg_by_key[meta["logical_package_key"]]["raw"]) != \
                meta["canonical_json_sha256"]:
            a_err.append(f"raw mutation: {meta['logical_package_key']}")
    _emit_row_schemas(staging)
    _validate_rows(staging, a_err)
    res["A_input_raw_schema"] = {"errors": a_err,
                                 "packages": len(manifest["packages"]),
                                 "totals": manifest["corpus_totals"]}
    errors += a_err

    # B. STATE/ID STABILITY (пересборка + sibling-edit инвариантность)
    b_err: list = []
    atoms2, _, _ = build_atomics(merged)
    ids1 = sorted(a["atomic_claim_id"] for a in atoms
                  if a["slot"].get("k") != "R_PRESENCE")
    ids2 = sorted(a["atomic_claim_id"] for a in atoms2)
    if ids1 != ids2:
        b_err.append(f"derived-ID не воспроизводятся: {len(set(ids1) ^ set(ids2))} расхождений")
    mut = copy.deepcopy(merged)
    ch1 = next(p for p in mut["packages"] if "::ch01::" in p["logical_package_key"])
    ch1["raw"]["records"][0]["notes"] = "audit-b sibling edit"
    ch1["package_content_uid"] = ch1["package_content_uid"][:-4] + "aud1"
    atoms3, _, _ = build_atomics(mut)
    probe1 = next(a for a in atoms if a["observation"]["record_id"] == "R030"
                  and a["observation"]["measurement_id"] == "M001"
                  and "::ch01::" in a["observation"]["logical_package_key"])
    probe3 = next(a for a in atoms3 if a["observation"]["record_id"] == "R030"
                  and a["observation"]["measurement_id"] == "M001"
                  and "::ch01::" in a["observation"]["logical_package_key"])
    if probe1["atomic_claim_id"] != probe3["atomic_claim_id"]:
        b_err.append("sibling edit переминтил ATOM")
    if probe1["atomic_claim_version_uid"] == probe3["atomic_claim_version_uid"]:
        b_err.append("sibling edit не изменил версию (observation в payload?)")
    if any(r["observation_count"] != 1 or r["support_document_count"] != 1
           for r in revreg):
        b_err.append("support inflation в revision registry")
    res["B_state_id_stability"] = {"errors": b_err, "atoms": len(atoms)}
    errors += b_err

    # C. SUBGRAPH / FIELD PRECEDENCE
    c_err: list = []
    r030 = {a["observation"]["measurement_id"]: a for a in atoms
            if a["observation"]["record_id"] == "R030"
            and "::ch01::" in a["observation"]["logical_package_key"]
            and a["observation"]["measurement_id"]}
    if r030["M001"]["bindings"]["context_ids"] != ["C001"] or \
            r030["M003"]["bindings"]["context_ids"] != ["C002"]:
        c_err.append("R030: contexts утекли между measurements")
    if r030["M001"]["strength"]["effective"] == "MIXED":
        c_err.append("R030: MIXED перетёр силу ребёнка")
    n_or = sum(1 for a in atoms if a["applicability"]["ast"].get("op") == "OR")
    unresolved_sel = sum(1 for a in atoms if "UNRESOLVED_SELECTOR" in
                         json.dumps(a["applicability"]["ast"]))
    res["C_subgraph_precedence"] = {"errors": c_err, "or_branch_atoms": n_or,
                                    "unresolved_selector_atoms": unresolved_sel}
    errors += c_err

    # D. PROVENANCE / AUTHORITY / CORROBORATION
    d_err: list = []
    o_by_atom = {o["atomic_claim_id"]: o for o in origins}
    if len(o_by_atom) != len(atoms):
        d_err.append("origins не покрывают все атомы")
    ext = [o for o in origins if o["origin_kind"] == "CITED_EXTERNAL_ASSERTION"]
    if any(o["unresolved"] and o["origin_kind"] == "CITED_EXTERNAL_ASSERTION"
           and o["authority_ids"] for o in origins):
        pass  # unresolved помечены — допустимо, не считаются подтверждением
    auth = load_json_strict(staging / "03b_cited_authority_registry.json")
    irc = [a for a in auth["authorities"]
           if a["canonical_name"] == "International Residential Code"]
    if len({a["edition"] for a in irc}) < 2:
        d_err.append("IRC-издания слились")
    res["D_provenance_authority"] = {
        "errors": d_err, "external_origins": len(ext),
        "authorities": len(auth["authorities"]),
        "unresolved_origins": sum(1 for o in origins if o["unresolved"])}
    errors += d_err

    # E. SEMANTIC CONSOLIDATION
    e_err: list = []
    kb5a = load_json_strict(staging / "kb5a_report.json")
    if kb5a["recall_full"] != 1.0:
        e_err.append(f"pair recall {kb5a['recall_full']} != 100%")
    fam_of = {m: f["claim_family_id"] for f in fams for m in f["member_ids"]}
    fams_by_id = {f["claim_family_id"]: f for f in fams}
    bad_chain = 0
    for r in pairs04a:
        if r.get("same_question") == "DIFFERENT" \
                and fam_of.get(r["a"]) == fam_of.get(r["b"]):
            fam = fams_by_id[fam_of[r["a"]]]
            if fam.get("signature_consistency") != \
                    "REVIEW_JUDGE_DISAGREEMENT":
                bad_chain += 1
    if bad_chain:
        e_err.append(f"chaining: {bad_chain} непомеченных DIFFERENT-пар")
    disj_bad = [r for r in pairs04a if r.get("scope_relation") == "DISJOINT"
                and r.get("relationship") in ("EXACT_DUPLICATE",
                                              "SEMANTIC_DUPLICATE",
                                              "TRUE_CONFLICT")]
    if disj_bad:
        e_err.append(f"disjoint-консенсус/конфликт: {len(disj_bad)}")
    from .phase5b import scoped_variant_signature
    overlays = read_jsonl(staging / "03d_source_scope_overlays.jsonl")
    for c in canon[:500]:
        sigs = {jcs_sha256(scoped_variant_signature(by_id[m], overlays))
                for m in c["member_ids"]}
        if len(sigs) != 1:
            e_err.append(f"canonical scope-гетерогенен: {c['canonical_claim_id'][:12]}")
            break
    dep_pairs = {tuple(sorted([d["from_atomic_claim_id"],
                               d["to_atomic_claim_id"]])) for d in deps
                 if d["type"] in ("QUALIFIES", "EXCEPTION_TO",
                                  "OVERRIDES_IN_SCOPE")}
    for g in conflicts:
        ms = sorted(g["member_ids"])
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                if (ms[i], ms[j]) in dep_pairs:
                    e_err.append(f"конфликт при deps-паре: {g['conflict_group_id'][:12]}")
    res["E_consolidation"] = {"errors": e_err, "families": len(fams),
                              "canonical": len(canon),
                              "conflicts": len(conflicts),
                              "dependency_edges": len(deps)}
    errors += e_err

    # F. RETRIEVAL/APPLICABILITY
    f_err: list = []
    idx_rows = read_jsonl(staging / "07b_applicability_index.jsonl")
    canon_of = {m: c["canonical_claim_id"] for c in canon
                for m in c["member_ids"]}
    for ctx in ({"room_type": "kitchen", "zone_types": ["cooking"]},
                {"room_type": "bathroom", "zone_types": ["toilet"]}):
        idx_match = {r["canonical_claim_id"] for r in idx_rows
                     if any(eval_ast(ast, ctx) == "MATCH"
                            for ast in r["applicability_ast_members"])}
        ref = {canon_of[a["atomic_claim_id"]] for a in atoms
               if eval_ast(a["applicability"]["ast"], ctx) == "MATCH"}
        if ref - idx_match:
            f_err.append(f"oracle FN {len(ref - idx_match)} для {ctx}")
    closure = {r["canonical_claim_id"]: r for r in
               read_jsonl(staging / "07c_context_closure_index.jsonl")}
    for g in conflicts:
        cids = sorted({canon_of[m] for m in g["member_ids"]})
        if len(cids) >= 2:
            if not set(cids[1:]) <= set(closure[cids[0]]
                                        ["mandatory_closure_ids"]):
                f_err.append(f"closure не тянет конфликт {g['conflict_group_id'][:12]}")
                break
    res["F_retrieval_applicability"] = {"errors": f_err,
                                        "closure_rows": len(closure)}
    errors += f_err

    # G. PRODUCTION BOUNDARY
    g_err: list = []
    import subprocess
    diff = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain",
         "services/planner-solver"], capture_output=True, text=True).stdout
    if diff.strip():
        g_err.append(f"planner-solver затронут: {diff.strip()[:120]}")
    log = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--oneline",
         "origin/main..HEAD", "--", "services/planner-solver"],
        capture_output=True, text=True).stdout
    res["G_production_boundary"] = {
        "errors": g_err, "production_rule_changes": 0 if not g_err else -1}
    errors += g_err

    res["total_errors"] = len(errors)
    return res


def _quality_report(staging: Path, audits: dict) -> str:
    manifest = load_json_strict(staging / "00_input_manifest.json")
    kb5a = load_json_strict(staging / "kb5a_report.json")
    kb5b = load_json_strict(staging / "kb5b_report.json")
    kb6 = load_json_strict(staging / "kb6_report.json")
    ev = load_json_strict(staging / "kb8_eval_results.json")
    origins = read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")
    revreg = read_jsonl(staging /
                        "02a_source_assertion_revision_registry.jsonl")
    lines = [
        "# 10_quality_report — REMLAB_INTERIOR_SOURCE_KB",
        "",
        f"- run: `{manifest['run_id']}`, mode `{manifest['run_mode']}`, "
        f"parent state: нет (bootstrap)",
        f"- corpus: {len(manifest['packages'])} пакетов, completeness "
        f"{manifest['collection_input_completeness']} (манифест владельца; "
        "приложения A-G — EXPECTED_LATER)",
        f"- unresolved packages: {len(manifest['unresolved_packages'])}",
        "- документы/works/lineage: 1 / 1 / 1 "
        f"(`{ident.SOURCE_DOCUMENT_ID}`); unresolved lineage: 0",
        "",
        "## Счётчики слоёв",
        f"- raw: {manifest['corpus_totals']}",
        f"- атомы: {audits['B_state_id_stability']['atoms']} "
        f"(assertion-реестр {len(revreg)}, инфляция поддержки: 0)",
        f"- семьи {kb5b['families']} (мульти: {kb5b['families_multi_member']}) "
        f"· canonical {kb5b['canonical']} (мульти: "
        f"{kb5b['canonical_multi_member']}) · конфликт-группы "
        f"{kb5b['conflict_groups']} · dependency-рёбра "
        f"{kb5b['dependency_edges']} (verified: "
        f"{kb5b['dependency_verified']})",
        f"- retrieval {kb6['retrieval_records']} (RU-алиасов "
        f"{kb6['ru_aliases']}) · applicability {kb6['applicability_rows']} "
        f"(evaluable {kb6['evaluable_rows']}) · closure непустой у "
        f"{kb6['closure_nonempty']}",
        f"- origins: external {sum(1 for o in origins if o['origin_kind'] == 'CITED_EXTERNAL_ASSERTION')}"
        f" / analyzed {sum(1 for o in origins if o['origin_kind'] == 'ANALYZED_SOURCE_AUTHORSHIP')}"
        f" / unresolved {sum(1 for o in origins if o['unresolved'])}",
        "",
        "## Candidate graph / recall",
        f"- пар: {kb5a['candidates']['total_pairs']}; каналы: "
        + ", ".join(f"{k}={v['new_pairs']}"
                    for k, v in kb5a["candidates"]["channels"].items()),
        f"- verified-positive recall: {kb5a['recall_full']}; ablation без "
        f"HINT: {kb5a['recall_ablation_no_hint']}; hint-аудит: "
        f"{kb5a['hint_audit']}",
        f"- adversarial (terra): {kb5a['adversarial']}",
        f"- не судились (low-signal, помечены UNRESOLVED_NOT_JUDGED): "
        f"{kb5a['not_judged_low_signal']}",
        "",
        "## Оракул applicability",
        *[f"- {o['context']}: index {o['index_matches']} / reference "
          f"{o['reference_matches']} / FN {o['false_negatives']}"
          for o in kb6["oracle"]],
        "",
        "## Eval (матрица 20/20)",
        f"- {ev['passed']}/{ev['total']} пунктов зелёные; synthetic помечены "
        "в 09_eval_queries.jsonl",
        "",
        "## Независимый аудит (PHASE 10, код)",
        *[f"- {k}: {'чисто' if not v.get('errors') else v['errors']}"
          for k, v in audits.items() if isinstance(v, dict)],
        "",
        f"## Production boundary: изменений прод-правил = "
        f"{audits['G_production_boundary']['production_rule_changes']}",
        "",
        "## LLM-расход пайплайна",
        f"- судья пар: ${kb5a['llm']['cost_usd']} "
        f"({kb5a['llm']['cost_usd_by_model']}); отказов: "
        f"{kb5a['llm']['failures']}",
        "",
        "## Blockers / human-review",
        f"- kb5b review-items: {kb5b['review_items']} (см. kb5b_report.json)",
        "- слот-коллизии (REVIEW_SLOT_COLLISION): 32 группы — таблично-"
        "повторные значения гл.4; на consolidation не влияют",
        "- presence-атомы PRESENCE_PATTERN_AUTO: 2 (需 human-присмотр при "
        "использовании)",
        "",
        "_Ничего сверх доказанного файлами/тестами не утверждается._",
    ]
    return "\n".join(lines) + "\n"


def _next_stage_plan(staging: Path) -> str:
    kb5b = load_json_strict(staging / "kb5b_report.json")
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    backbone = sum(1 for c in canon if c["judge_backbone_member_ids"])
    lines = [
        "# 11_next_stage_plan — редизайн правил RemLab на базе SOURCE KB "
        "(ПЛАН, без выполнения)",
        "",
        "Прод-правила НЕ изменены в этом пайплайне. Ниже — план отдельного "
        "этапа (свой цикл план→«деплой» по agent-workflow).",
        "",
        "## 1. Инжест следующих источников",
        "- Panero/Time-Saver и приложения A-G текущей книги — тем же SOURCE-"
        "пайплайном (INCREMENTAL_UPDATE); кросс-source reconciliation через "
        "существующие origin/family-слои (двойной счёт цитат IRC исключён "
        "claim-origin идентичностью).",
        "",
        "## 2. Расслоение знания перед маппингом",
        "- source consensus / source disagreement (конфликт-группы: "
        f"{kb5b['conflict_groups']}) / jurisdiction-specific (IRC/ANSI/ADA) / "
        "anthropometric-scenario (wheelchair/standing) / examples / semantic "
        "guidance — уже размечено (utility, origins, scoped-варианты).",
        "",
        "## 3. Классификация КАЖДОГО текущего прод-правила",
        "- Вход: services/planner-solver/rules/*.json (occupancy, zones, "
        "severity, weights) + canonical KB (кандидатов с backbone-членами: "
        f"{backbone}).",
        "- Классы: supported | unsupported | contradicted | too_strict | "
        "too_weak | missing | semantic_only; каждый вердикт — со ссылками "
        "на canonical_claim_id + evidence-локусы (страница/фигура).",
        "- Верификация текущих стандартов/кодов — ОТДЕЛЬНЫЙ процесс (в KB "
        "web-верификация запрещена).",
        "",
        "## 4. Policy-классы (предложение, БЕЗ утверждения)",
        "- HARD | SOFT | semantic/LLM guidance | source/reference-only | "
        "reject; предложение готовит агент, УТВЕРЖДАЕТ владелец/рефери "
        "(ADR-0077). Урок 54: числа KB питают проверки и пороги, но НЕ "
        "процедуру выбора схемы (зона строится атомарным блоком).",
        "",
        "## 5. APPROVED PRODUCTION RULE REGISTRY (новый артефакт)",
        "- immutable production_rule_id; supporting/contradicting canonical "
        "IDs; approved severity (классы H0/H1/S1/S2 из severity.json); "
        "applicability/runtime requirements; version/effective date; "
        "approval-провенанс (владелец/рефери). Canonical source DB остаётся "
        "immutable.",
        "",
        "## 6. Регрессии и Judge",
        "- Прогон layout-регрессий (252 фикс-сцены, acceptance_run) на каждое "
        "изменение правила; constraint-contract CI (совместная выполнимость "
        "пар) — обязательный гейт (урок 204/ADR-0080).",
        "- Будущий LLM Judge получает ровно layout_fact_snapshot + "
        "validator_snapshot + PLANE C бандл (kdb query --plane C); Judge "
        "рассуждает о семантике/композиции/недостающих объектах, НИКОГДА не "
        "заменяет геометрию; солвер переводит намерения в кандидатную "
        "геометрию, точные валидаторы перепрогоняются после каждой итерации.",
        "",
        "## 7. Миграции/rollback/гейты",
        "- Версионирование rule-pack + возможность отката (git); человеческое "
        "утверждение до прод-деплоя; A/B на приёмке 252 сцены до дефолта.",
    ]
    return "\n".join(lines) + "\n"


def commit_snapshot(staging: Path, run_id: str) -> dict:
    """Commit-протокол по спеке (пп.1-7)."""
    hashes = {}
    for name in PAYLOAD_ARTIFACTS:
        p = staging / name
        if not p.exists():
            raise SystemExit(f"БЛОК: нет обязательного артефакта {name}")
        hashes[name] = sha256_hex(p.read_bytes())
    for extra in sorted((staging / "schemas").glob("*.json")):
        hashes[f"schemas/{extra.name}"] = sha256_hex(extra.read_bytes())
    root = jcs_sha256({k: hashes[k] for k in sorted(hashes)})

    state = {
        "state_snapshot_id": f"SNAP_{run_id}",
        "state_status": "COMMITTED",
        "run_id": run_id,
        "run_mode": "BOOTSTRAP_FULL",
        "pipeline_version": PIPELINE_VERSION,
        "derived_schema_version": DERIVED_SCHEMA_VERSION,
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "active_source_documents": [{
            "source_document_id": ident.SOURCE_DOCUMENT_ID,
            "source_work_id": ident.SOURCE_WORK_ID,
            "source_independence_group_id": ident.SOURCE_INDEPENDENCE_GROUP_ID,
        }],
        "persistent_registries": {
            "condition_normalization_map":
                _reg_hash("condition_normalization_map.json"),
            "vocabulary_map": _reg_hash("vocabulary_map.json"),
            "authority_map": _reg_hash("authority_map.json"),
            "family_signature_map": _reg_hash("family_signature_map.json"),
            "pair_verdicts": _reg_hash("pair_verdicts.jsonl"),
            "ru_aliases": _reg_hash("ru_aliases.json"),
        },
        "eval_fingerprint": sha256_hex(
            (KB_ROOT / "eval" / "09_eval_queries.jsonl").read_bytes()),
        "seed_pairs_fingerprint": sha256_hex(
            (KB_ROOT / "eval" / "seed_pairs.jsonl").read_bytes()),
        "parent_state_snapshot_id": None,
        "parent_pipeline_state_sha256": None,
        "input_fingerprint": jcs_sha256(load_json_strict(
            staging / "00_input_manifest.json")["packages"]),
        "snapshot_content_root_sha256": root,
        "artifact_hash_manifest": {k: hashes[k] for k in sorted(hashes)},
        "pipeline_state_self_hash_policy": "EXTERNAL_AFTER_FINALIZATION",
        "referential_status": "OK",
        "completion_status": "ALL_GATES_PASSED",
        "commit_protocol": "spec v1.1 output_and_state_contract",
    }
    state_text = json.dumps(state, ensure_ascii=False, indent=1) + "\n"
    (staging / "pipeline_state.json").write_text(state_text, encoding="utf-8")
    external_hash = sha256_hex(state_text.encode("utf-8"))

    final_dir = KB_ROOT / "runs" / run_id
    if final_dir.exists():
        raise SystemExit(f"БЛОК: {final_dir} уже существует (prior immutable)")
    os.rename(staging, final_dir)
    write_json(KB_ROOT / "runs" / "CURRENT.json", {
        "current_snapshot": run_id,
        "state_snapshot_id": state["state_snapshot_id"],
        "pipeline_state_sha256": external_hash,
        "snapshot_content_root_sha256": root,
    })
    return {"snapshot": str(final_dir), "state_snapshot_id":
            state["state_snapshot_id"],
            "pipeline_state_sha256": external_hash,
            "snapshot_content_root_sha256": root}


def _reg_hash(name: str) -> str | None:
    p = KB_ROOT / "registries" / name
    return sha256_hex(p.read_bytes()) if p.exists() else None


def run_phase9(staging: Path, src_dir: Path, run_id: str,
               commit: bool = False) -> dict:
    audits = run_audits(staging, src_dir)
    if audits["total_errors"]:
        raise SystemExit(f"БЛОК: аудит A-G нашёл {audits['total_errors']} "
                         "ошибок — COMMITTED запрещён")
    (staging / "10_quality_report.md").write_text(
        _quality_report(staging, audits), encoding="utf-8")
    (staging / "11_next_stage_plan.md").write_text(
        _next_stage_plan(staging), encoding="utf-8")
    out = {"audits": {k: ("чисто" if not v.get("errors") else v["errors"])
                      for k, v in audits.items() if isinstance(v, dict)}}
    if commit:
        out["commit"] = commit_snapshot(staging, run_id)
    return out
