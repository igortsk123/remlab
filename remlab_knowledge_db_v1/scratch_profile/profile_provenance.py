#!/usr/bin/env python3
"""Профиль провенанса и подсказок в 13 JSON-пакетах CHAPTER_KNOWLEDGE_PACKAGE v3.2."""
import json, glob, os, re
from collections import Counter, defaultdict

SRC = '/home/pakar/igor/remlab/remlab_knowledge_db_v1/sources/RID_MITTON_NYSTUEN_2016_3E'
files = sorted(glob.glob(os.path.join(SRC, '*.json')))

authority_dist = Counter()
cited = Counter()           # (name, year) -> count records
auth_no_name = 0            # authority типа CITED_* но cited_authority_name пуст
auth_no_name_by_auth = Counter()
total_records = 0

dup_nonempty = 0
conf_nonempty = 0
dup_resolved = 0
dup_unresolved = []
conf_resolved_pairs = 0
conf_unresolved = []
conflict_examples = []      # (file, rid, target, concept)
crossfile_refs = []

ev_type = Counter()
ev_strength = Counter()
ev_conf = Counter()
ev_total = 0
ev_with_table = 0
ev_with_figure = 0
ev_derived_nonempty = 0

top_findings = []           # (file, rid, why)

fp_formats = Counter()
fp_dupes_per_file = {}
fp_examples = []
fp_missing = 0

per_file = {}

for fp in files:
    fname = os.path.basename(fp).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    with open(fp) as f:
        d = json.load(f)
    recs = d['records']
    ids = {r['record_id'] for r in recs}
    per_file[fname] = len(recs)
    total_records += len(recs)

    fps = Counter()
    for r in recs:
        # 1) authority
        auth = r.get('source_authority') or 'MISSING'
        authority_dist[auth] += 1
        name = (r.get('cited_authority_name') or '').strip()
        year = (r.get('cited_authority_year_or_edition') or '').strip()
        if name:
            cited[(name, year or '—')] += 1
        elif auth.startswith('CITED'):
            auth_no_name += 1
            auth_no_name_by_auth[auth] += 1

        # 2) dup / conflicts
        dup = r.get('local_duplicate_of')
        if dup:
            dup_nonempty += 1
            targets = dup if isinstance(dup, list) else [dup]
            for t in targets:
                if t in ids:
                    dup_resolved += 1
                else:
                    dup_unresolved.append((fname, r['record_id'], t))
                    if re.match(r'^R\d+$', str(t)) is None:
                        crossfile_refs.append((fname, r['record_id'], t, 'dup'))
        confs = r.get('local_conflicts_with') or []
        if confs:
            conf_nonempty += 1
            for t in confs:
                if t in ids:
                    conf_resolved_pairs += 1
                else:
                    conf_unresolved.append((fname, r['record_id'], t))
            conflict_examples.append((fname, r['record_id'], confs, r.get('concept', '')[:110]))

        # 3) evidence
        for e in r.get('evidence') or []:
            ev_total += 1
            ev_type[e.get('evidence_type') or 'MISSING'] += 1
            ev_strength[e.get('support_strength') or 'MISSING'] += 1
            ev_conf[e.get('extraction_confidence') or 'MISSING'] += 1
            if e.get('source_table'):
                ev_with_table += 1
            if e.get('source_figure'):
                ev_with_figure += 1
            if e.get('derived_from_evidence_ids'):
                ev_derived_nonempty += 1

        # 5) fingerprint
        cf = r.get('context_fingerprint')
        if not cf:
            fp_missing += 1
        else:
            fps[cf] += 1
            # формат: SEGMENT__SEGMENT__... верхний регистр
            n_seg = cf.count('__') + 1
            is_upper = bool(re.match(r'^[A-Z0-9_]+$', cf))
            fp_formats[(n_seg, is_upper)] += 1
    dupes = {k: v for k, v in fps.items() if v > 1}
    fp_dupes_per_file[fname] = (len(fps), sum(v for v in fps.values()), dupes)
    if recs:
        fp_examples.append((fname, recs[0].get('context_fingerprint'), recs[len(recs)//2].get('context_fingerprint')))

    # 4) top_findings
    for tfind in d.get('top_findings') or []:
        top_findings.append((fname, tfind.get('record_id'), tfind.get('why_useful', '')))

out = {}
out['files'] = per_file
out['total_records'] = total_records
out['authority_dist'] = dict(authority_dist.most_common())
out['cited_pairs'] = [(n, y, c) for (n, y), c in cited.most_common()]
out['auth_no_name'] = auth_no_name
out['auth_no_name_by_auth'] = dict(auth_no_name_by_auth)
out['dup'] = dict(nonempty=dup_nonempty, resolved=dup_resolved, unresolved=dup_unresolved[:20])
out['conf'] = dict(nonempty=conf_nonempty, resolved_refs=conf_resolved_pairs, unresolved=conf_unresolved[:20])
out['crossfile_refs'] = crossfile_refs[:20]
out['conflict_examples'] = conflict_examples[:10]
out['evidence'] = dict(total=ev_total, types=dict(ev_type.most_common()),
                       strength=dict(ev_strength.most_common()), confidence=dict(ev_conf.most_common()),
                       with_table=ev_with_table, with_figure=ev_with_figure,
                       derived_nonempty=ev_derived_nonempty)
out['top_findings_count'] = len(top_findings)
out['top_findings'] = top_findings
out['fp'] = dict(formats={str(k): v for k, v in fp_formats.most_common()},
                 missing=fp_missing,
                 per_file={k: dict(unique=v[0], total=v[1], dup_count=len(v[2]),
                                   dup_sample=list(v[2].items())[:3]) for k, v in fp_dupes_per_file.items()},
                 examples=fp_examples[:5])

with open('/home/pakar/igor/remlab/remlab_knowledge_db_v1/scratch_profile/profile_out.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print('OK, records:', total_records, 'evidence:', ev_total, 'top_findings:', len(top_findings))
print('cited unique pairs:', len(out['cited_pairs']))
