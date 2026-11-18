You are an independent senior software-engineering reviewer. Do not modify, create or delete files.

USER OBJECTIVE
Living-room furniture-set bank (tools/scout/sets3.json, rebuilt nightly as candidate tools/scout/sets3.next.json by
bank_prepare → bank_pending → bank_promote → bank_refresh) must become "ready" by itself when the set's furniture has meshes.
Owner rule: if meshes are missing for a set by the composition rules, the pipeline must make them automatically.

OBSERVED (measured 18.11 on DEV, read-only)
- Candidate bank: 126 cells, promoted 0; 124 wait, 2 blocked. For 107 unique family representatives demanded by the candidate:
  - 17 have no asset revision at all → they ARE in the demo mesh queue (mesh_priority.py --profile demo), will be generated.
  - 56 have an accepted/generated asset revision (made 09.11–14.11) and products.mesh_status='ready', but NO row in mesh_demand.
    None of the five demand sources in mesh_queue.run (demand_from_sets, demand_from_reserve_deficit, demand_from_cut_pool,
    demand_from_candidates, demand_reserve) returns them. Across the whole DB: 1442 of 3582 SKUs with a valid revision have no
    mesh_demand row.
  - 27 have orientation_state status review_pending; 5 have orientation resolved for a different glb_sha (re-generated mesh).
- The mesh queue takes only products with mesh_status != 'ready', so the 56 are never queued either.

TECHNICAL QUESTION
1. Root cause: why does the bank never see these 56 meshes as ready, and is it a design gap or intended? Inspect
   tools/scout/mesh_ready.py:_load, tools/scout/mesh_queue.py (run, demand_from_*, ingest, copy_photo_current), mesh_priority.py,
   the bank_* steps (find them, e.g. tools/scout/bank_*.py, refresh_daily.sh), and how products.mesh_status is set.
2. What is the correct general fix (one rule, not per-SKU) so that the bank candidate's furniture gets demand rows / source_sha
   and readiness is computed consistently? Consider alternatives: a new demand source from the bank candidate; changing the
   readiness predicate; reconciling products.mesh_status with mesh_ready; others.
3. Orientation: what step should resolve review_pending and stale-glb_sha orientations automatically, and does it run nightly?
4. Risks: priority/budget effects on the mesh queue (demo profile cap 150), stale-photo safety (source_sha check must stay),
   double work, effect on /demo and tours.

Return: conclusion; evidence with file paths and symbols/lines; risks and edge cases; alternatives; recommendation and why;
uncertainties; what evidence would change your conclusion. Be critical.
