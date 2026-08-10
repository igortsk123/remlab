"""PHASE 3B/3B2 — cited authority registry + claim corroboration origins.

Правила спеки:
- одна authority при вариациях строки (IRC в 8+ написаниях), но РАЗНЫЕ издания —
  разные authority_id; unknown edition НЕ сливается с известным;
- composite-строки («ANSI A117.1; UFAS; FHAA 1988; ADA») разбираются на
  компоненты; привязка record-level = candidate context (basis), не verified;
- vague «local codes (unnamed)» — unresolved identity, имя не выдумываем;
- origins: явные внешние атрибуции (Hall/Sommer/IRC/NKBA...) —
  CITED_EXTERNAL_ASSERTION даже при locator=null; AUTHOR_EXAMPLE и
  неатрибутированный текст книги — ANALYZED_SOURCE_AUTHORSHIP;
- web-верификация запрещена; канон нормализации — registries/authority_map.json.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import identity as ident
from .canonical import derived_id
from .io import load_json_strict, write_json
from .llm import MODEL_CHEAP, LLMStats, call_json

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "authority_map.json"

_KINDS = ["CODE", "STANDARD", "BOOK", "GUIDELINE", "ORGANIZATION", "OTHER",
          "UNKNOWN"]

_SYS = (
    "You normalize cited-authority strings from an interior design book. Each "
    "input is (name_string | edition_string) as printed. Split composite "
    "citations (separated by ';' or listing several codes) into components. "
    "For each component give:\n"
    "- canonical: canonical short name (e.g. 'International Residential Code', "
    "'ANSI A117.1', 'NKBA Kitchen Planning Guidelines', 'Edward T. Hall, The "
    "Hidden Dimension'). Do NOT invent names for vague references like 'local "
    "codes (unnamed)' — set canonical='UNRESOLVED_LOCAL_CODES' and "
    "unresolved=true;\n"
    "- kind: CODE|STANDARD|BOOK|GUIDELINE|ORGANIZATION|OTHER|UNKNOWN;\n"
    "- edition: normalized edition/year ('2015', '2003', '1966') or '' if not "
    "stated. Use ONLY what the strings contain — no outside knowledge updates."
)

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "components"],
        "properties": {
            "index": {"type": "integer"},
            "components": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["canonical", "kind", "edition", "unresolved"],
                "properties": {
                    "canonical": {"type": "string"},
                    "kind": {"type": "string", "enum": _KINDS},
                    "edition": {"type": "string"},
                    "unresolved": {"type": "boolean"}}}}}}}},
}


def raw_key(name: str | None, year: str | None) -> str:
    return f"{(name or '').strip()} | {(year or '').strip()}"


def canonical_key(canonical: str) -> str:
    """Детерминированная нормализация canonical-имени: identity не должна
    зависеть от вариаций типа «International Residential Code (IRC)»."""
    s = re.sub(r"\([^)]*\)", " ", str(canonical))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return re.sub(r"\s+", " ", s)


def authority_id(canonical: str, edition: str) -> str:
    return derived_id("AUTH", {"canonical": canonical_key(canonical),
                               "edition": (edition or "").strip()})


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return load_json_strict(REGISTRY_PATH)["raw_variants"]
    return {}


def save_registry(reg: dict) -> None:
    write_json(REGISTRY_PATH, {
        "artifact": "authority_map_registry",
        "note": "канон нормализации цитируемых авторитетов (LLM, без web); "
                "издания раздельны, unknown не сливается с известным",
        "raw_variants": {k: reg[k] for k in sorted(reg)},
    })


def normalize_authorities(pairs: list[tuple[str, str]], stats: LLMStats,
                          batch_size: int = 20) -> tuple[dict, dict]:
    reg = load_registry()
    uniq = sorted({raw_key(n, y) for n, y in pairs if (n or "").strip()})
    missing = [k for k in uniq if k not in reg]
    report = {"unique_raw": len(uniq), "from_registry": len(uniq) - len(missing),
              "llm_needed": len(missing), "llm_done": 0, "failed_batches": 0}
    batches = [missing[i:i + batch_size] for i in range(0, len(missing), batch_size)]
    for bi, b in enumerate(batches):
        user = "Citations:\n" + "\n".join(f"{i}: {k}" for i, k in enumerate(b))
        try:
            obj = call_json(MODEL_CHEAP, _SYS, user, "authority_norm",
                            _SCHEMA, stats)
        except Exception as e:  # noqa: BLE001
            report["failed_batches"] += 1
            print(f"ОТКАЗ authority-батча {bi + 1}/{len(batches)}: {e}")
            if bi == 0:
                raise SystemExit("БЛОК: пилот authority-нормализации провалился")
            continue
        got = 0
        for it in obj.get("items", []):
            i = it.get("index")
            if isinstance(i, int) and 0 <= i < len(b) and it.get("components"):
                reg[b[i]] = {"components": it["components"], "basis": "LLM",
                             "model": MODEL_CHEAP}
                got += 1
        if bi == 0 and got < len(b) * 0.9:
            raise SystemExit(f"БЛОК: пилот authority ответил {got}/{len(b)}")
        report["llm_done"] += got
    save_registry(reg)
    return reg, report


_EXTERNAL_SOURCE_AUTH = {"CITED_CODE", "CITED_STANDARD"}


def classify_origin(atom: dict, reg: dict) -> dict:
    """3B2: происхождение corroboration для атома."""
    p = atom["parent_record"]
    sa = p.get("source_authority")
    name = (p.get("cited_authority_name") or "").strip()
    year = (p.get("cited_authority_year_or_edition") or "").strip()
    locator = (p.get("cited_authority_locator") or "").strip() or None

    is_external = (sa in _EXTERNAL_SOURCE_AUTH
                   or (name and sa == "BOOK_DESIGN_GUIDANCE"))
    if sa == "AUTHOR_EXAMPLE":
        is_external = False

    if not is_external:
        return {
            "origin_kind": "ANALYZED_SOURCE_AUTHORSHIP",
            "origin_group_id": derived_id("ORIG", {
                "kind": "AUTHORSHIP", "work": ident.SOURCE_WORK_ID,
                "assertion": atom["source_assertion_uid"]}),
            "authority_ids": [], "unresolved": False,
            "basis": f"source_authority={sa}, named={bool(name)}",
        }

    comps = (reg.get(raw_key(name, year)) or {}).get("components") or []
    auth_ids = []
    unresolved = not comps
    for c in comps:
        if c.get("unresolved"):
            unresolved = True
        auth_ids.append(authority_id(c["canonical"], c.get("edition", "")))
    if not comps and not name:
        unresolved = True  # CITED_CODE без имени
    slot_sig = atom["slot"]
    origin_id = derived_id("ORIG", {
        "kind": "EXTERNAL",
        "authorities": sorted(auth_ids) or ["UNNAMED"],
        "locator": (locator or "").lower() or None,
        "slot": slot_sig,
    })
    return {"origin_kind": "CITED_EXTERNAL_ASSERTION",
            "origin_group_id": origin_id,
            "authority_ids": sorted(auth_ids),
            "unresolved": unresolved,
            "basis": f"source_authority={sa}, named={bool(name)}, "
                     f"locator={'да' if locator else 'null'}"}


_ROLE_BY_SA = {"CITED_CODE": "GOVERNS_CLAIM",
               "CITED_STANDARD": "PRIMARY_SOURCE_OF_CLAIM",
               "BOOK_DESIGN_GUIDANCE": "SUPPORTS_CLAIM",
               "AUTHOR_EXAMPLE": "SUPPORTS_EXAMPLE"}


def bindings_for(atom: dict, reg: dict) -> list[dict]:
    p = atom["parent_record"]
    name = (p.get("cited_authority_name") or "").strip()
    if not name:
        return []
    year = (p.get("cited_authority_year_or_edition") or "").strip()
    comps = (reg.get(raw_key(name, year)) or {}).get("components") or []
    role = _ROLE_BY_SA.get(p.get("source_authority"), "UNKNOWN")
    out = []
    for c in comps:
        out.append({
            "atomic_claim_id": atom["atomic_claim_id"],
            "atomic_claim_version_uid": atom["atomic_claim_version_uid"],
            "authority_id": authority_id(c["canonical"], c.get("edition", "")),
            "role": role,
            "attribution_basis": ("COMPOSITE_RECORD_LEVEL" if len(comps) > 1
                                  else "RECORD_LEVEL_CANDIDATE"),
            "edition_stated": c.get("edition", "") or None,
            "locator_stated": (p.get("cited_authority_locator") or None),
            "unresolved_identity": bool(c.get("unresolved")),
        })
    return out
