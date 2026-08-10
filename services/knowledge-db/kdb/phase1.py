"""PHASE 1 — lossless mechanical merge -> 01_raw_merged.json.

Инварианты (спека A1-A3, PHASE 1):
- каждый raw-пакет входит в merged БЕЗ изменений (семантическое равенство
  проверяется JCS-хэшем против манифеста Phase 0);
- derived-метаданные живут СНАРУЖИ raw-объекта;
- гейт: счётчики до/после равны, UID уникальны, raw-мутаций ноль.

Observation UID-схема (используется фазами 2+):
  <package_content_uid>::<record_id>
  <package_content_uid>::<record_id>::<measurement_id|evidence_id|context_id>
Artifact UID никогда не входит в стабильные семантические ID.
"""
from __future__ import annotations

import json
from pathlib import Path

from .canonical import jcs_sha256
from .io import load_json_strict, parse_json_strict


def _counts_of(raw_packages: list[dict]) -> dict:
    tot = {"records": 0, "measurements": 0, "evidence": 0,
           "applicability_contexts": 0, "entities": 0,
           "excluded_source_items": 0, "chapter_review_queue": 0,
           "top_findings": 0}
    for pkg in raw_packages:
        obj = pkg["raw"]
        recs = obj.get("records", [])
        tot["records"] += len(recs)
        for r in recs:
            tot["measurements"] += len(r.get("measurements", []))
            tot["evidence"] += len(r.get("evidence", []))
            tot["applicability_contexts"] += len(r.get("applicability_contexts", []))
            tot["entities"] += len(r.get("entities", []))
        tot["excluded_source_items"] += len(obj.get("excluded_source_items", []))
        tot["chapter_review_queue"] += len(obj.get("chapter_review_queue", []))
        tot["top_findings"] += len(obj.get("top_findings", []))
    return tot


def run_phase1(staging: Path, src_dir: Path) -> dict:
    manifest = load_json_strict(staging / "00_input_manifest.json")
    packages_meta = sorted(manifest["packages"],
                           key=lambda p: p["logical_package_key"])

    raw_packages = []
    for meta in packages_meta:
        path = src_dir / meta["file_name"]
        obj = parse_json_strict(path.read_bytes())
        # гейт иммутабельности: содержимое семантически идентично Phase 0
        h = jcs_sha256(obj)
        if h != meta["canonical_json_sha256"]:
            raise SystemExit(f"БЛОК: {meta['file_name']} изменился после Phase 0 "
                             f"({h[:12]} != {meta['canonical_json_sha256'][:12]})")
        raw_packages.append({
            "logical_package_key": meta["logical_package_key"],
            "artifact_uid": meta["artifact_uid"],
            "package_content_uid": meta["package_content_uid"],
            "file_name": meta["file_name"],
            "active_for_semantic_projection": meta["active_for_semantic_projection"],
            "raw": obj,
        })

    # гейт: уникальность UID пакетов и observation-UID записей
    for field in ("logical_package_key", "artifact_uid", "package_content_uid"):
        vals = [p[field] for p in raw_packages]
        if len(vals) != len(set(vals)):
            raise SystemExit(f"БЛОК: неуникальные {field}")
    rec_uids = set()
    n_child_uids = 0
    for p in raw_packages:
        pcu = p["package_content_uid"]
        for r in p["raw"].get("records", []):
            uid = f"{pcu}::{r['record_id']}"
            if uid in rec_uids:
                raise SystemExit(f"БЛОК: дубликат observation UID {uid}")
            rec_uids.add(uid)
            for fld, key in (("measurements", "measurement_id"),
                             ("evidence", "evidence_id"),
                             ("applicability_contexts", "context_id")):
                n_child_uids += len({x[key] for x in r.get(fld, [])})

    # гейт: счётчики до (манифест) == после (пересчёт из merged)
    after = _counts_of(raw_packages)
    before = manifest["corpus_totals"]
    diffs = {k: (before.get(k), after.get(k)) for k in after
             if before.get(k) != after.get(k)}
    if diffs:
        raise SystemExit(f"БЛОК: счётчики разошлись: {diffs}")

    merged = {
        "artifact": "01_raw_merged",
        "knowledge_base_id": manifest["knowledge_base_id"],
        "run_id": manifest["run_id"],
        "run_mode": manifest["run_mode"],
        "merge_semantics": "BOOTSTRAP_FULL: все active-пакеты, сортировка по "
                           "logical_package_key; raw неизменен (JCS-проверка)",
        "corpus_totals": after,
        "packages": raw_packages,
    }
    out = staging / "01_raw_merged.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # компактная запись: артефакт крупный (~11 МБ raw)
    text = json.dumps(merged, ensure_ascii=False, separators=(",", ":")) + "\n"
    out.write_text(text, encoding="utf-8")
    parse_json_strict(out.read_bytes())

    return {"gate": {"records": len(rec_uids), "child_uid_sets": n_child_uids,
                     "totals": after}}
