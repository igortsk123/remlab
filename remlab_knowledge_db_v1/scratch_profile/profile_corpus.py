#!/usr/bin/env python3
"""Vocabulary profile of CHAPTER_KNOWLEDGE_PACKAGE v3.2 corpus (13 files)."""
import json, glob, collections, sys

SRC = "/home/pakar/igor/remlab/remlab_knowledge_db_v1/sources/RID_MITTON_NYSTUEN_2016_3E"
files = sorted(glob.glob(SRC + "/*.json"))

C = collections.Counter
dist = {k: C() for k in [
    "knowledge_type", "status", "source_claim_strength", "remlab_candidate_use",
    "relation_type", "dimension_type"]}
vocab_status = C()
room_type = C()
zone_types = C()
entity_family = C()
entity_type = C()
noncore_count = 0
proposed_et = C()
assignment_basis = C()
ctx_condition_nonempty = 0
ctx_total = 0
ctx_needs_verif = C()
condition_examples = []
condition_seen = set()
demo_fields = ["population", "sex", "age_group", "percentile", "posture",
               "mobility_context", "clothing_or_equipment"]
demo = {k: C() for k in demo_fields}
rec_condition_nonempty = 0

surprises = []
type_anomalies = C()  # (field, observed_type)
per_file = []
n_records = 0
n_entities = 0
schema_versions = C()
vocab_versions = C()

def tname(v):
    return type(v).__name__

for fp in files:
    with open(fp) as f:
        pkg = json.load(f)
    schema_versions[str(pkg.get("schema_version"))] += 1
    vocab_versions[str(pkg.get("vocabulary_version"))] += 1
    recs = pkg.get("records", [])
    per_file.append((fp.split("/")[-1], len(recs)))
    n_records += len(recs)
    for r in recs:
        for k in dist:
            v = r.get(k, "<MISSING>")
            if v is None:
                v = "<null>"
            elif not isinstance(v, str):
                type_anomalies[(k, tname(v))] += 1
                v = f"<{tname(v)}>{v}"
            dist[k][v] += 1
        # record-level condition
        rc = r.get("condition")
        if rc is None:
            type_anomalies[("record.condition", "null")] += 1
        elif not isinstance(rc, str):
            type_anomalies[("record.condition", tname(rc))] += 1
        elif rc.strip():
            rec_condition_nonempty += 1
        # demo fields
        for k in demo_fields:
            v = r.get(k, "<MISSING>")
            if v is None:
                v = "<null>"
            elif not isinstance(v, str):
                type_anomalies[(k, tname(v))] += 1
                v = f"<{tname(v)}>{v}"
            demo[k][v] += 1
        # contexts
        ctxs = r.get("applicability_contexts")
        if not isinstance(ctxs, list):
            type_anomalies[("applicability_contexts", tname(ctxs))] += 1
            ctxs = []
        for c in ctxs:
            ctx_total += 1
            rt = c.get("room_type")
            room_type[rt if isinstance(rt, str) else f"<{tname(rt)}>"] += 1
            zts = c.get("zone_types")
            if isinstance(zts, list):
                for z in zts:
                    zone_types[z if isinstance(z, str) else f"<{tname(z)}>"] += 1
            else:
                type_anomalies[("zone_types", tname(zts))] += 1
            ab = c.get("assignment_basis")
            assignment_basis[ab if isinstance(ab, str) else f"<{tname(ab)}>"] += 1
            cond = c.get("condition")
            if cond is None:
                type_anomalies[("context.condition", "null")] += 1
            elif not isinstance(cond, str):
                type_anomalies[("context.condition", tname(cond))] += 1
            elif cond.strip():
                ctx_condition_nonempty += 1
                key = cond.strip()
                if key not in condition_seen and len(condition_examples) < 10:
                    condition_seen.add(key)
                    condition_examples.append(key)
            nv = c.get("needs_verification")
            ctx_needs_verif[str(nv)] += 1
        # entities
        ents = r.get("entities")
        if not isinstance(ents, list):
            type_anomalies[("entities", tname(ents))] += 1
            ents = []
        for e in ents:
            n_entities += 1
            ef = e.get("entity_family")
            entity_family[ef if isinstance(ef, str) else f"<{tname(ef)}>"] += 1
            et = e.get("entity_type")
            if et is None:
                entity_type["<null>"] += 1
            elif isinstance(et, str):
                entity_type[et] += 1
            else:
                type_anomalies[("entity_type", tname(et))] += 1
            vs = e.get("vocabulary_status")
            vocab_status[vs if isinstance(vs, str) else f"<{tname(vs)}>"] += 1
            if vs != "CORE":
                noncore_count += 1
            pet = e.get("proposed_entity_type")
            if pet is not None:
                if isinstance(pet, str) and pet.strip():
                    proposed_et[pet] += 1
                elif not isinstance(pet, str):
                    type_anomalies[("proposed_entity_type", tname(pet))] += 1

out = {
    "files": per_file,
    "n_records": n_records,
    "n_entities": n_entities,
    "n_contexts": ctx_total,
    "schema_versions": dict(schema_versions),
    "vocab_versions": dict(vocab_versions),
    "dist": {k: v.most_common() for k, v in dist.items()},
    "vocab_status": vocab_status.most_common(),
    "room_type": room_type.most_common(),
    "zone_types": zone_types.most_common(),
    "entity_family": entity_family.most_common(),
    "entity_type_top40": entity_type.most_common(40),
    "entity_type_unique": len(entity_type),
    "noncore_count": noncore_count,
    "proposed_entity_type": proposed_et.most_common(),
    "assignment_basis": assignment_basis.most_common(),
    "ctx_condition_nonempty": ctx_condition_nonempty,
    "rec_condition_nonempty": rec_condition_nonempty,
    "ctx_needs_verification": ctx_needs_verif.most_common(),
    "condition_examples": condition_examples,
    "demo": {k: v.most_common() for k, v in demo.items()},
    "type_anomalies": [[list(k), v] for k, v in type_anomalies.most_common()],
}
json.dump(out, open("/home/pakar/igor/remlab/remlab_knowledge_db_v1/scratch_profile/profile_out.json", "w"),
          ensure_ascii=False, indent=1)
print("OK", n_records, "records,", n_entities, "entities,", ctx_total, "contexts")
