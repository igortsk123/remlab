## Conclusion

The 56 meshes are invisible to the bank because `mesh_ready` requires a `mesh_demand` row even when a valid current-photo asset revision and `products.mesh_status='ready'` already exist. The bank is waiting for bookkeeping, not for a mesh.

This is a design gap created by combining two individually intentional choices:

- `products.mesh_status='ready'` means a current-photo model is bound to the product.
- Bank/display readiness is stricter and also requires an orientation for that exact GLB.

That distinction is valid. Requiring membership in the mutable demand table as a third condition is not. The candidate’s demand exists only in `bank-pending.json` and the demo-profile ranking; it is never persisted into `mesh_demand`.

The safest general invariant is:

> Resolve every candidate mesh item to its family representative. If it lacks a usable revision for the canonical current photo, it is demand; if such a revision exists, readiness depends on that current photo and an orientation for the exact GLB—not on whether a demand row happens to exist.

## Evidence

### Why the 56 are not ready

[`mesh_ready._load`](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:27) performs inner joins to:

- `asset_revisions`
- `mesh_demand`
- `orientation_state`

The decisive join is [`join mesh_demand d on d.sku = r.sku`](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:39). With no demand row, the revision cannot be returned. The subsequent source check is safe and necessary, but it checks `d.source_sha`, not the canonical photo table.

Exact-GLB orientation matching is correctly enforced at [`left(o.resolution->>'glb_sha',16) = r.glb_sha`](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:47), and family readiness is propagated at [lines 68–73](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:68).

The bank consumes that predicate directly:

- [`bank_ready.load_facts`](/home/pakar/igor/remlab/tools/scout/bank_ready.py:166) loads `mesh_ready_raw()`.
- [`bank_ready.classify`](/home/pakar/igor/remlab/tools/scout/bank_ready.py:81) calls a mesh item ready only when its SKU or representative is in that set.
- [`bank_pending.update`](/home/pakar/igor/remlab/tools/scout/bank_pending.py:119) records everything else as missing.
- [`bank_promote.plan`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:267) refuses a cell unless the matching pending record has `status == 'ready'`.

### Why no demand row appears

[`mesh_queue.run`](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:389) unions exactly these sources:

- live `sets3.json`
- live-set reserve deficits
- cut pool
- `candidates-index`
- directed-role reserve

It does not read `sets3.next.json` or `bank_pending`.

The apparent candidate-demand mechanism is separate:

- [`bank_pending.demand`](/home/pakar/igor/remlab/tools/scout/bank_pending.py:164) calculates missing representatives.
- [`bank_pending.queue_skus`](/home/pakar/igor/remlab/tools/scout/bank_pending.py:330) returns them from saved JSON state.
- [`mesh_priority.demo_rank`](/home/pakar/igor/remlab/tools/scout/mesh_priority.py:144) puts them into tier 2 of the demo-profile queue.

That path never inserts `mesh_demand`.

Furthermore, [`copy_photo_current`](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:350) is only an `UPDATE`. It cannot create a missing demand row. [`ingest`](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:331) hashes only SKUs already present in `mesh_demand`.

### Why `products.mesh_status='ready'` can disagree

[`mesh_bind.bind_ready`](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:167) sets `mesh_status='ready'` from the current non-rejected generation.

[`mesh_bind.enforce_ready_invariant`](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:218) then validates it against `product_photo_current`, accepted/generated non-legacy revisions, and the revision photo-hash prefix. It does not require `mesh_demand` or orientation.

This is mostly correct layering:

- `products.mesh_status`: current model is bound.
- `mesh_ready`: model is display-usable, including exact orientation.

Therefore changing `products.mesh_status` to mirror `mesh_ready` would conflate two states and could make orientation-only problems look like generation work.

## Recommendation

### 1. Make current-photo identity canonical

Change readiness to join `product_photo_current`, not `mesh_demand`, while preserving all existing safety conditions:

- non-legacy accepted/generated revision;
- non-null current-photo SHA;
- current SHA starts with the revision’s stored SHA prefix;
- resolved, usable orientation for the exact `glb_sha`;
- family-representative propagation.

This aligns `mesh_ready` with the canonical photo source already used by `mesh_bind`. It should make the affected 56 ready immediately only if their current-photo hash and exact-GLB orientation really match.

Do not replace this with a bare `products.mesh_status='ready'` check; that would discard orientation, rejection, origin, and exact-revision safety.

### 2. Persist candidate demand, but do not make it an asset-validity gate

For a complete ownership model, add a bank-candidate demand source derived from the attested current candidate or saved `bank_pending` state. It should:

- resolve variants to `mesh_family_rep`;
- use the representative’s HD→SD product photo, dimensions, role, and name;
- preserve the existing demo-profile ordering, reserve of 30, and cap of 150;
- remove abandoned candidate demand naturally on the next reconciliation.

This provides auditability and source SHA for genuine missing assets, but readiness should remain independent of demand-table membership.

### 3. Fix the scheduler before enabling that source broadly

There is an adjacent duplicate-generation defect in [`mesh_scheduler._queue`](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:46):

- it looks only for status `accepted`, not `generated`;
- it compares an exact key constructed with the full `mesh_demand.source_sha`;
- [`ingest_registry.revision_key`](/home/pakar/igor/remlab/tools/scout/salad/ingest_registry.py:61) stores the 16-character photo hash.

Thus the proposed candidate rows could make an already-generated but orientation-pending model look generation-eligible. The scheduler should use the same normalized current-revision predicate as readiness and suppress generation when a current-photo accepted/generated model already exists. Orientation should then be the next action.

## Orientation

There are two different cases.

### Regenerated GLB / stale GLB SHA

[`orient_worker.pending_meshes`](/home/pakar/igor/remlab/tools/scout/orient_worker.py:503) keys orientation by `sku|current_glb_sha16|orient-v1`. A newly generated GLB therefore has no matching key and is automatically selected.

It runs nightly as:

[`orient_worker.py --run --limit 100 --vlm --recheck-roles`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:725)

Caveats:

- It runs after the bank chain, so the bank sees its result on the next night, not the same night.
- It is capped at 100 and failures are non-blocking.
- It scans models on disk; a current generation missing from the scanned paths will not be repaired.

### `review_pending`

General `review_pending` is deliberately not auto-resolved. An existing exact revision key is considered “present,” so `pending_meshes` does not retry it.

The intended path is human review:

- [`mesh_review_sync.push`](/home/pakar/igor/remlab/tools/scout/mesh_review_sync.py:107) publishes review tasks.
- [`mesh_review_sync.pull`](/home/pakar/igor/remlab/tools/scout/mesh_review_sync.py:177) applies decisions as `human_resolved`.
- Both run nightly after `orient_worker` at [`refresh_daily.sh` lines 729–730](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:729).

Some specialized guards can promote narrowly defined cases, notably the bed-headboard guard, but there is no safe general automatic transition from `review_pending`.

## Risks and edge cases

- Changing readiness to `product_photo_current` can expose more than the measured 56—potentially any of the 1,442 valid revisions lacking demand rows. Run a shadow diff first, grouped by exact orientation status and current-photo match.
- The stale-photo prefix check must remain. Removing it would permit an old model after the retailer changes the product photo.
- Candidate variants must use the family representative’s photo SHA. Using the variant’s photo against the representative’s revision would incorrectly mark shared-family meshes stale.
- A candidate-demand source may feed both the demo-profile queue and the general scheduler. Without the scheduler correction, that can create duplicate paid work.
- The demo cap of 150 applies to `mesh_priority --profile demo`, not automatically to the general `mesh_scheduler`. Do not let a new persisted source bypass the profile budget.
- The profile keeps 30 places for bank demand. A large genuinely missing candidate therefore needs multiple waves; it is automatic only when a valid demo-profile wave lease and budget exist.
- Orientation-only blockers should not trigger regeneration.
- Both demand creation and orientation currently occur after the bank has judged the night’s candidate, creating at least a one-night convergence delay.

There is also a separate operational blocker: living-room [`write_enabled` is currently false](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:26). Consequently, even ready cells can only be judged into a manifest; [`refresh_daily.sh`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:519) does not invoke the living-room writer. If “ready” means actual promotion into `sets3.json`, this flag must eventually be explicitly enabled after validation.

## Alternatives

- **Only add a candidate demand source:** minimally fixes missing rows, but preserves the incorrect coupling between validity and demand and exposes the scheduler duplication bug. Acceptable as a tactical patch only with scheduler guards.
- **Global backfill of all 1,442 rows:** not recommended. It turns historical assets into current paid demand and may cause a queue/budget spike.
- **Use `products.mesh_status='ready'` as readiness:** unsafe; it ignores orientation and exact-GLB usability.
- **Force `products.mesh_status` to equal `mesh_ready`:** also unsafe; orientation review would make a valid model look absent and encourage regeneration.
- **Remove the photo check:** unacceptable stale-photo regression.

## Uncertainties and evidence that would change the conclusion

I could not independently query the DEV Docker database from this read-only environment because access to the Docker socket was denied, so the measured counts are taken as supplied.

The conclusion would change for individual SKUs if:

- `product_photo_current.source_sha` does not match the revision photo prefix—then the mesh is genuinely stale;
- no resolved orientation exists for that exact `glb_sha`—then demand repair alone is insufficient;
- the current GLB is absent from `orient_worker`’s scanned paths;
- an external process outside this repository persists bank demand before readiness is evaluated.

Architecturally, I would favor demand-row backfilling as the primary fix only if `mesh_demand` is formally intended as an immutable artifact-provenance ledger. The code instead treats it as mutable current demand (`wanted`/`not_required`), so it is the wrong table to determine whether an existing mesh is valid.