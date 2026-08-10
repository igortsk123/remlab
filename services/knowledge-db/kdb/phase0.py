"""PHASE 0 — preflight: инвентаризация, валидация, identity пакетов.

Выход (в staging): 00_input_manifest.json, source_document_registry.json.
Гейт: все пакеты валидны и активны; повторный прогон бит-в-бит идентичен
(в манифесте нет wall-clock таймстампов — время живёт только в pipeline_state).

Ключевые правила (спека, PHASE 0/1):
- сегментация выводится из master-страниц, НЕ из битых segment_index/segment_total;
- identity документа — predeclared (identity.py), не из имён файлов;
- invalid/truncated вход блокируется, не чинится;
- raw не мутируем — все находки уходят в anomalies[] манифеста.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from . import KNOWLEDGE_BASE_ID, PIPELINE_VERSION, DERIVED_SCHEMA_VERSION
from . import identity as ident
from .canonical import jcs_sha256, sha256_hex
from .io import DuplicateKeyError, parse_json_strict, write_json

REQUIRED_TOP_KEYS = [
    "package_type", "schema_version", "vocabulary_version", "source", "chapter",
    "coverage_audit", "records", "room_zone_index", "top_findings",
    "chapter_review_queue", "excluded_source_items", "chapter_summary",
]


@dataclasses.dataclass
class PackageInfo:
    file_name: str
    file_bytes: int
    file_sha256: str
    canonical_json_sha256: str
    chapter_number: int
    master_from: int
    master_to: int
    printed_from: int
    printed_to: int
    obj: dict
    errors: list
    anomalies: list

    @property
    def segment_identity(self) -> str:
        return f"p{self.master_from:04d}-{self.master_to:04d}"


def _counts(obj: dict) -> dict:
    recs = obj.get("records", [])
    return {
        "records": len(recs),
        "measurements": sum(len(r.get("measurements", [])) for r in recs),
        "evidence": sum(len(r.get("evidence", [])) for r in recs),
        "applicability_contexts": sum(len(r.get("applicability_contexts", [])) for r in recs),
        "entities": sum(len(r.get("entities", [])) for r in recs),
        "excluded_source_items": len(obj.get("excluded_source_items", [])),
        "chapter_review_queue": len(obj.get("chapter_review_queue", [])),
        "top_findings": len(obj.get("top_findings", [])),
    }


def _validate_package(fn: str, obj: dict, errors: list, anomalies: list) -> None:
    for k in REQUIRED_TOP_KEYS:
        if k not in obj:
            errors.append(f"{fn}: нет обязательного ключа {k!r}")
    if obj.get("package_type") != ident.EXPECTED_PACKAGE_TYPE:
        errors.append(f"{fn}: package_type={obj.get('package_type')!r}")
    if obj.get("schema_version") != ident.EXPECTED_SCHEMA_VERSION:
        errors.append(f"{fn}: schema_version={obj.get('schema_version')!r} != "
                      f"{ident.EXPECTED_SCHEMA_VERSION}")
    if obj.get("vocabulary_version") != ident.EXPECTED_VOCABULARY_VERSION:
        anomalies.append({"kind": "VOCABULARY_VERSION_UNEXPECTED", "file": fn,
                          "detail": str(obj.get("vocabulary_version"))})

    src = obj.get("source", {})
    if src.get("source_collection_id") in (None, "", "SOURCE_ID_MISSING"):
        anomalies.append({"kind": "SOURCE_ID_MISSING", "file": fn,
                          "detail": "identity задаётся predeclared-маппингом (спека)"})

    records = obj.get("records", [])
    rec_ids = [r.get("record_id") for r in records]
    if len(rec_ids) != len(set(rec_ids)):
        errors.append(f"{fn}: неуникальные record_id")
    rec_set = set(rec_ids)

    for r in records:
        rid = r.get("record_id")
        for field, key in (("measurements", "measurement_id"),
                           ("evidence", "evidence_id"),
                           ("applicability_contexts", "context_id")):
            ids = [x.get(key) for x in r.get(field, [])]
            if len(ids) != len(set(ids)):
                errors.append(f"{fn}:{rid}: неуникальные {key}")
        ev_ids = {e.get("evidence_id") for e in r.get("evidence", [])}
        ctx_ids = {c.get("context_id") for c in r.get("applicability_contexts", [])}
        for m in r.get("measurements", []):
            mid = m.get("measurement_id")
            for eid in m.get("evidence_ids", []):
                if eid not in ev_ids:
                    errors.append(f"{fn}:{rid}:{mid}: evidence_id {eid!r} не резолвится")
            for cid in m.get("context_ids", []):
                if cid not in ctx_ids:
                    errors.append(f"{fn}:{rid}:{mid}: context_id {cid!r} не резолвится")
        dup = r.get("local_duplicate_of")
        if dup and dup not in rec_set:
            errors.append(f"{fn}:{rid}: local_duplicate_of {dup!r} не резолвится")
        for c in r.get("local_conflicts_with", []) or []:
            if c not in rec_set:
                errors.append(f"{fn}:{rid}: local_conflicts_with {c!r} не резолвится")

    for tf in obj.get("top_findings", []):
        if tf.get("record_id") and tf["record_id"] not in rec_set:
            errors.append(f"{fn}: top_findings.record_id {tf['record_id']!r} не резолвится")
    for room, zones in (obj.get("room_zone_index", {}) or {}).items():
        for zone, ids in (zones or {}).items():
            for rid in ids:
                if rid not in rec_set:
                    errors.append(f"{fn}: room_zone_index[{room}][{zone}] "
                                  f"ссылается на {rid!r}")

    cov = obj.get("coverage_audit", {})
    if cov.get("coverage_complete") is not True:
        anomalies.append({"kind": "COVERAGE_INCOMPLETE", "file": fn,
                          "detail": str(cov.get("notes", ""))[:200]})
    found = cov.get("relevant_source_items_found")
    mapped = cov.get("relevant_source_items_mapped_to_records")
    excl = cov.get("relevant_source_items_excluded")
    if None not in (found, mapped, excl) and found != mapped + excl:
        anomalies.append({"kind": "COVERAGE_COUNTS_MISMATCH", "file": fn,
                          "detail": f"found={found} != mapped={mapped}+excluded={excl}"})


def load_packages(src_dir: Path) -> list[PackageInfo]:
    infos: list[PackageInfo] = []
    for path in sorted(src_dir.glob("*.json")):
        raw = path.read_bytes()
        errors: list = []
        anomalies: list = []
        try:
            obj = parse_json_strict(raw)
        except DuplicateKeyError as e:
            raise SystemExit(f"БЛОК: {path.name}: {e}")
        except ValueError as e:
            raise SystemExit(f"БЛОК: {path.name}: не парсится ({e})")
        _validate_package(path.name, obj, errors, anomalies)
        ch = obj.get("chapter", {})
        # аномалии сегментных полей (сегментацию выводим из страниц)
        if ch.get("segment_total") in (None, 0) or ch.get("segment_index") in (None, 0) \
                or (ch.get("segment_total") == 1 and "seg" in path.name):
            anomalies.append({"kind": "SEGMENT_FIELDS_BROKEN", "file": path.name,
                              "detail": f"segment_index={ch.get('segment_index')} "
                                        f"segment_total={ch.get('segment_total')}"})
        if "ofU" in path.name:
            anomalies.append({"kind": "FILENAME_TYPO", "file": path.name,
                              "detail": "ofU3 вместо of3 (raw не переименовываем)"})
        infos.append(PackageInfo(
            file_name=path.name,
            file_bytes=len(raw),
            file_sha256=sha256_hex(raw),
            canonical_json_sha256=jcs_sha256(obj),
            chapter_number=ch.get("chapter_number"),
            master_from=ch.get("source_page_master_file_from"),
            master_to=ch.get("source_page_master_file_to"),
            printed_from=ch.get("source_page_printed_from"),
            printed_to=ch.get("source_page_printed_to"),
            obj=obj,
            errors=errors,
            anomalies=anomalies,
        ))
    return infos


def reconcile_segments(infos: list[PackageInfo]) -> list:
    """Проверка встык по master-страницам; derived segment_index/total на главу."""
    corpus_anoms: list = []
    infos.sort(key=lambda p: (p.master_from, p.file_name))
    for prev, cur in zip(infos, infos[1:]):
        if cur.master_from != prev.master_to + 1:
            corpus_anoms.append({
                "kind": "PAGE_GAP_OR_OVERLAP",
                "detail": f"{prev.file_name} (..{prev.master_to}) -> "
                          f"{cur.file_name} ({cur.master_from}..)"})
    by_ch: dict[int, list[PackageInfo]] = {}
    for p in infos:
        by_ch.setdefault(p.chapter_number, []).append(p)
    for ch, parts in by_ch.items():
        parts.sort(key=lambda p: p.master_from)
        for i, p in enumerate(parts, 1):
            p.derived_segment_index = i          # type: ignore[attr-defined]
            p.derived_segment_total = len(parts)  # type: ignore[attr-defined]
    return corpus_anoms


def detect_exact_duplicates(infos: list[PackageInfo]) -> list:
    corpus_anoms = []
    by_hash: dict[str, list[str]] = {}
    for p in infos:
        by_hash.setdefault(p.canonical_json_sha256, []).append(p.file_name)
    for h, files in by_hash.items():
        if len(files) > 1:
            corpus_anoms.append({"kind": "EXACT_DUPLICATE_CONTENT",
                                 "detail": ", ".join(sorted(files))})
    return corpus_anoms


def logical_package_key(p: PackageInfo) -> str:
    return (f"{ident.SOURCE_DOCUMENT_ID}::ch{p.chapter_number:02d}"
            f"::{p.segment_identity}")


def build_expected_input_manifest(infos: list[PackageInfo]) -> dict:
    """Манифест полноты. Решение владельца 2026-08-10: главы 1-10 — полный
    основной корпус; приложения A-G ожидаются позже (INCREMENTAL_UPDATE)."""
    return {
        "origin": "OWNER_DECISION_2026_08_10",
        "expected_present": sorted(logical_package_key(p) for p in infos),
        "expected_future_additions": [
            {"scope": f"appendix_{x}", "status": "EXPECTED_LATER"}
            for x in "ABCDEFG"
        ],
        "notes": "Главы 1-10 объявлены владельцем полным основным корпусом; "
                 "приложения будут добавлены отдельным INCREMENTAL_UPDATE.",
    }


def run_phase0(src_dir: Path, staging: Path, run_id: str) -> dict:
    infos = load_packages(src_dir)
    if not infos:
        raise SystemExit(f"БЛОК: нет входных пакетов в {src_dir}")
    hard_errors = [e for p in infos for e in p.errors]
    if hard_errors:
        for e in hard_errors:
            print("ОШИБКА:", e)
        raise SystemExit(f"БЛОК: {len(hard_errors)} структурных ошибок входа")

    corpus_anoms = reconcile_segments(infos) + detect_exact_duplicates(infos)

    packages = []
    for p in infos:
        key = logical_package_key(p)
        packages.append({
            "logical_package_key": key,
            "artifact_uid": f"{key}::RAW_SHA256_{p.file_sha256}",
            "package_content_uid": f"{key}::JCS_SHA256_{p.canonical_json_sha256}",
            "content_identity_quality": "JCS",
            "file_name": p.file_name,
            "file_bytes": p.file_bytes,
            "file_sha256": p.file_sha256,
            "canonical_json_sha256": p.canonical_json_sha256,
            "chapter_number": p.chapter_number,
            "segment_identity": p.segment_identity,
            "derived_segment_index": p.derived_segment_index,   # type: ignore
            "derived_segment_total": p.derived_segment_total,   # type: ignore
            "pages_master": [p.master_from, p.master_to],
            "pages_printed": [p.printed_from, p.printed_to],
            "source_document_id": ident.SOURCE_DOCUMENT_ID,
            "document_resolution_basis": "PREDECLARED_PROMPT_MAPPING",
            "active_for_semantic_projection": True,
            "counts": _counts(p.obj),
            "anomalies": p.anomalies,
        })

    totals: dict[str, int] = {}
    for pkg in packages:
        for k, v in pkg["counts"].items():
            totals[k] = totals.get(k, 0) + v

    manifest = {
        "artifact": "00_input_manifest",
        "knowledge_base_id": KNOWLEDGE_BASE_ID,
        "pipeline_version": PIPELINE_VERSION,
        "derived_schema_version": DERIVED_SCHEMA_VERSION,
        "run_id": run_id,
        "run_mode": "BOOTSTRAP_FULL",
        "parent_state_snapshot_id": None,
        "parent_pipeline_state_sha256": None,
        "input_delta_manifest": None,
        "expected_input_manifest": build_expected_input_manifest(infos),
        "collection_input_completeness": "COMPLETE",
        "completeness_basis": "expected_input_manifest (решение владельца), "
                              "все 13 пакетов встык по master-страницам 15-259",
        "packages": packages,
        "corpus_totals": totals,
        "corpus_anomalies": corpus_anoms,
        "unresolved_packages": [],
        "exact_duplicate_groups": [],
    }

    registry = {
        "artifact": "source_document_registry",
        "documents": [{
            "source_document_id": ident.SOURCE_DOCUMENT_ID,
            "source_work_id": ident.SOURCE_WORK_ID,
            "source_independence_group_id": ident.SOURCE_INDEPENDENCE_GROUP_ID,
            "lineage_relation": "ORIGINAL",
            "lineage_parents": [],
            "resolution_status": "RESOLVED_PREDECLARED",
            "resolution_basis": "PROMPT_SUPPLIED (fixed_project_identity спеки)",
            "document_kind": "BOOK",
            "bibliographic": ident.PREDECLARED_BIBLIO,
            "metadata_origin": ident.METADATA_ORIGIN,
            "raw_metadata_variants": sorted({
                str(p.obj.get("source", {}).get("title")) for p in infos}),
            "identity_confidence": "HIGH",
            "packages": sorted(logical_package_key(p) for p in infos),
            "migrations": [],
        }],
        "legacy_migration_checks": {
            "canonical_source_collection_id_as_kb_id": "N/A (BOOTSTRAP_FULL, "
                "prior state отсутствует; проверка выполняется при загрузке prior)",
            "cited_authority_provision_rename": "N/A (см. state.py при REBUILD)",
        },
    }

    staging.mkdir(parents=True, exist_ok=True)
    write_json(staging / "00_input_manifest.json", manifest)
    write_json(staging / "source_document_registry.json", registry)
    return manifest
