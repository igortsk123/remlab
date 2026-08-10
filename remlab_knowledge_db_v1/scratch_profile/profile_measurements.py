#!/usr/bin/env python3
"""Profile measurements[] across the 13 chapter packages (schema v3.2)."""
import json, glob, os
from collections import Counter, defaultdict

SRC = "/home/pakar/igor/remlab/remlab_knowledge_db_v1/sources/RID_MITTON_NYSTUEN_2016_3E"
files = sorted(glob.glob(os.path.join(SRC, "*.json")))

dist = {k: Counter() for k in ("quantity_kind", "value_type", "comparison_operator",
                               "unit_original", "canonical_unit")}
total = 0
n_value = n_range = n_both = n_neither = 0
n_relexpr = 0
relexpr_examples = []   # (file, record_id, expr)
subj_keys = Counter(); ref_keys = Counter()
subj_vals = defaultdict(Counter); ref_vals = defaultdict(Counter)
ref_issues = defaultdict(lambda: Counter())  # file -> counter of issue types
per_file_meas = Counter()

# --- normalization check ---
IN = {"in", "inch", "inches", '"'}
FT = {"ft", "feet", "foot"}
SQFT = {"sq ft", "sqft", "sq. ft", "ft2", "square feet", "sq feet", "sq ft."}
FACTORS = {  # unit_original-class -> {canonical_unit: factor}
    "in":  {"mm": 25.4, "cm": 2.54, "m": 0.0254},
    "ft":  {"mm": 304.8, "cm": 30.48, "m": 0.3048},
    "sqft": {"m2": 0.09290304, "sq m": 0.09290304, "sqm": 0.09290304},
}
def unit_class(u):
    if not isinstance(u, str): return None
    ul = u.strip().lower()
    if ul in IN: return "in"
    if ul in FT: return "ft"
    if ul in SQFT: return "sqft"
    return None

chk_total = chk_exact = chk_round = 0
mismatches = []  # (file, record_id, measurement_id, orig, unit, norm, cu, expected)

def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

for fp in files:
    fname = os.path.basename(fp)
    with open(fp) as f:
        d = json.load(f)
    for rec in d.get("records", []):
        rid = rec.get("record_id")
        ev_ids = {e.get("evidence_id") for e in rec.get("evidence", []) or []}
        ctx_ids = {c.get("context_id") for c in rec.get("applicability_contexts", []) or []}
        for m in rec.get("measurements", []) or []:
            total += 1
            per_file_meas[fname] += 1
            for k in ("quantity_kind", "value_type", "comparison_operator",
                      "unit_original", "canonical_unit"):
                v = m.get(k)
                dist[k][str(v)] += 1
            vo, ro = m.get("value_original"), m.get("range_original")
            has_v = vo is not None
            has_r = ro is not None
            if has_v and has_r: n_both += 1
            elif has_v: n_value += 1
            elif has_r: n_range += 1
            else: n_neither += 1
            rex = m.get("relationship_expression")
            if rex is not None:
                n_relexpr += 1
                if rex not in [e[2] for e in relexpr_examples]:
                    relexpr_examples.append((fname, rid, rex))
            # subject / reference
            for key_field, kc, vc in (("subject", subj_keys, subj_vals),
                                      ("reference", ref_keys, ref_vals)):
                obj = m.get(key_field)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        kc[k] += 1
                        vc[k][str(v)] += 1
            # referential integrity
            for eid in m.get("evidence_ids") or []:
                if eid not in ev_ids:
                    ref_issues[fname][f"evidence_id missing ({rid})"] += 1
            for cid in m.get("context_ids") or []:
                if cid not in ctx_ids:
                    ref_issues[fname][f"context_id missing ({rid})"] += 1
            # normalization check
            uc = unit_class(m.get("unit_original"))
            cu = (m.get("canonical_unit") or "").strip().lower() if m.get("canonical_unit") else ""
            if uc and cu in FACTORS[uc]:
                f_ = FACTORS[uc][cu]
                pairs = []
                nv, nr = m.get("normalized_value"), m.get("normalized_range")
                if num(vo) and num(nv):
                    pairs.append((vo, nv))
                if isinstance(ro, list) and isinstance(nr, list) and len(ro) == len(nr):
                    pairs += [(a, b) for a, b in zip(ro, nr) if num(a) and num(b)]
                if pairs:
                    chk_total += 1
                    worst = 0.0
                    details = []
                    for a, b in pairs:
                        exp = a * f_
                        rel = abs(b - exp) / exp if exp else abs(b - exp)
                        worst = max(worst, rel)
                        details.append((a, b, exp))
                    if worst <= 0.005:
                        chk_exact += 1
                    elif worst <= 0.03:
                        chk_round += 1  # consistent with printed rounding
                    else:
                        mismatches.append((fname, rid, m.get("measurement_id"),
                                           m.get("unit_original"), cu, details, worst))

def top(counter, n=None):
    items = counter.most_common(n)
    return "\n".join(f"| {k} | {v} |" for k, v in items)

out = []
out.append(f"TOTAL measurements: {total} across {len(files)} files")
out.append("PER FILE: " + json.dumps(dict(per_file_meas), indent=0))
for k in dist:
    out.append(f"\n### {k} ({len(dist[k])} distinct)\n| value | n |\n|---|---|\n{top(dist[k])}")
out.append(f"\nvalue/range: value_only={n_value} range_only={n_range} both={n_both} neither={n_neither}")
out.append(f"relationship_expression non-null: {n_relexpr}")
out.append("\n15 distinct relationship_expression examples:")
for fname, rid, rex in relexpr_examples[:15]:
    out.append(f"- [{fname} {rid}] {str(rex)[:140]}")
out.append(f"\nNORMALIZATION CHECK (in/ft/sqft -> metric): checked={chk_total} "
           f"exact(<=0.5%)={chk_exact} rounding(<=3%)={chk_round} mismatch(>3%)={len(mismatches)}")
for fname, rid, mid, u, cu, details, worst in mismatches[:8]:
    out.append(f"- [{fname} {rid}/{mid}] {u}->{cu} worst_rel_err={worst:.1%}: " +
               "; ".join(f"orig={a} norm={b} expected={e:.4g}" for a, b, e in details))
out.append(f"\nREF INTEGRITY: files with violations: {len(ref_issues)}")
for fname, c in ref_issues.items():
    out.append(f"- {fname}: total={sum(c.values())} " + json.dumps(dict(c), ensure_ascii=False))
if not ref_issues:
    out.append("- all evidence_ids/context_ids resolve within their record in all files")
out.append("\nSUBJECT keys: " + json.dumps(dict(subj_keys)))
out.append("REFERENCE keys: " + json.dumps(dict(ref_keys)))
for name, vals in (("subject", subj_vals), ("reference", ref_vals)):
    for k in vals:
        out.append(f"\n{name}.{k} top10:\n" + top(vals[k], 10))

report = "\n".join(out)
print(report)
open("/home/pakar/igor/remlab/remlab_knowledge_db_v1/scratch_profile/profile_raw.txt", "w").write(report)
