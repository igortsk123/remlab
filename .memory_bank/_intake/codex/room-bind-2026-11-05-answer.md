## Recommendation

Use a generated, atomic file manifest as the temporary binding layer. Existing DB tables remain authoritative for generation, revision, and orientation facts, but no existing table should be repurposed as the room-neutral current binding.

Suggested artifact:

```text
~/scout-scenes/catalog-assets/v1/
  bindings-<content_sha>.json   # immutable snapshot
  current.json                 # atomically replaced copy/pointer
```

Commit only its schema and builder code. Keep previous snapshots for rollback.

The structure should mirror the eventual canonical schema:

```json
{
  "schema_version": 1,
  "assets": {
    "sha256:<full-glb-sha>": {
      "generation_key": "...",
      "revision_key": "...",
      "source_sha": "...",
      "pipeline_version": "v2",
      "local_path": ".../model.glb",
      "orientation": {
        "revision_key": "...|orient-v2",
        "resolution_sha": "...",
        "yaw_deg": 180
      },
      "gate": "pass"
    }
  },
  "families": {
    "mesh-family:<version>:<hash>": {
      "representative_offer_id": "112923:123",
      "asset_id": "sha256:...",
      "basis": "products.mesh_family_rep"
    }
  },
  "offers": {
    "112923:456": {
      "asset_id": "sha256:...",
      "representative_offer_id": "112923:123",
      "via_family": true,
      "status": "ready",
      "reasons": [],
      "passport": {},
      "capabilities": {
        "solver": true,
        "local_3d": true,
        "published_3d": false,
        "appearance": false
      }
    }
  }
}
```

Room and role membership must not be part of the binding key. They may appear as diagnostic `seen_in` metadata, but remain owned by the catalog adapter/profile.

### Identity

Use these distinct identities:

| Concept | Key |
|---|---|
| Physical offer | Composite `(shop_mid, external_id)`, serialized as `mid:eid` |
| Immutable mesh asset | Full `sha256(model.glb)` |
| Logical generation revision | Existing `revision_key` |
| Selected physical attempt | Existing `generation_key` |
| Published compatibility ID | Representative offer ID with `:` converted to `_` |
| Room/role membership | Separate adapter/profile relation, never part of asset identity |

`offer_id` is already defined as the asset SKU in `CatalogItem` [catalog_items.py:34](/home/pakar/igor/remlab/tools/scout/catalog_items.py:34). The adapter already merges duplicate roles by `offer_id` [catalog_items.py:251](/home/pakar/igor/remlab/tools/scout/catalog_items.py:251). Conversely, `room_catalog` includes room in its primary key [013-room-catalog.sql:5](/home/pakar/igor/remlab/tools/scout/013-room-catalog.sql:5), so it is unsuitable as the physical asset owner.

Do not key on revision or GLB SHA alone: revision and content identify an asset version, not the offer-to-asset relationship. Do not parse `offer_id` by splitting on every colon; retain `mid` and `eid` separately in the artifact.

## Why not an existing table?

The existing tables are useful inputs but none is the binding:

- `mesh_generations` is correctly one row per physical attempt and has an immutable `generation_key` [008-mesh-owner-audit.sql:11](/home/pakar/igor/remlab/tools/scout/008-mesh-owner-audit.sql:11).
- `asset_revisions.current_generation_key` selects an attempt within a logical revision [008-mesh-owner-audit.sql:34](/home/pakar/igor/remlab/tools/scout/008-mesh-owner-audit.sql:34).
- `orientation_state` is keyed by orientation revision, not an offer binding [mesh_queue.py:99](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:99).
- `mesh_demand` is mutable queue state with one role per SKU [mesh_queue.py:67](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:67), and the living rebuild marks absent demand `not_required` [mesh_queue.py:402](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:402). Room binding must not live there.
- `products` has the necessary pointer columns, but `mesh_bind` writes only `products` [mesh_bind.py:194](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:194). Copying that model into `room_catalog` requires the forbidden migration and would duplicate a shared offer.

The artifact should be a deterministic materialized binding over these facts, not a new independent history store.

## Family variants and readiness

Represent family reuse by reference, not by copying the representative’s URI and status into every variant:

```text
variant offer
  → family_id
  → representative_offer_id
  → immutable asset_id
```

This preserves provenance and makes rejection or regeneration of the representative invalidate every dependent member automatically.

Use `products.mesh_family_rep` for the currently identified 563 variants. Do not use `CatalogItem.family` as a mesh family: it is explicitly a style-scoring family [catalog_items.py:55](/home/pakar/igor/remlab/tools/scout/catalog_items.py:55) and is computed from shop plus normalized name without the mesh family’s role/dimension safeguards [catalog_items.py:205](/home/pakar/igor/remlab/tools/scout/catalog_items.py:205).

For room-only offers, either:

1. Initially bind only direct assets and explicitly reviewed family aliases; or
2. Run the conservative `mesh_family.family_key` logic into the file artifact.

The mesh family key includes role and rounded dimensions [mesh_family.py:78](/home/pakar/igor/remlab/tools/scout/mesh_family.py:78), and same-photo merging is deliberately conservative [mesh_family.py:94](/home/pakar/igor/remlab/tools/scout/mesh_family.py:94). Preserve the existing sticky representative behavior [mesh_family.py:241](/home/pakar/igor/remlab/tools/scout/mesh_family.py:241).

### Readiness predicate

An offer should be locally `ready` only when all of the following pass:

1. The selected generation is the `current_generation_key` for the revision matching the current photo SHA—not merely the newest filesystem entry.
2. `model.glb` exists and its full SHA matches the artifact’s `asset_id` and the DB SHA prefix.
3. Revision status is `accepted` or `generated`, origin is non-legacy, owner verdict is clear, and machine verdict is not a known failure.
4. Orientation is resolved for the exact GLB SHA, is not `unusable`, and uses the currently required orientation contract.
5. The current catalog dimensions pass the asset passport check.
6. The offer remains catalog-eligible for placement, including `footprint_ok` where required.
7. For a family member, the current family assignment and member passport still match the assignment used by the snapshot.
8. Appearance reuse is permitted or a validated tint exists if the consumer needs visual fidelity.

The existing strict orientation linkage is correct: `mesh_ready` joins orientation to the exact `glb_sha`, accepts only resolved statuses, and excludes `unusable` [mesh_ready.py:38](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:38). The current problem is that it also requires `mesh_demand`, so room jobs outside that queue cannot become ready through this predicate.

The asset passport is already captured in every generation manifest as image hash plus `dims_cm` [manifest.py:63](/home/pakar/igor/remlab/tools/scout/salad/manifest.py:63). `room_mesh_jobs` already refuses jobs without verified footprint and positive W×D×H [room_mesh_jobs.py:34](/home/pakar/igor/remlab/tools/scout/room_mesh_jobs.py:34).

Keep two dimension concepts separate:

- Asset passport: W×D×H and generation role used to produce the mesh.
- Placement passport: current catalog dimensions, sleep dimensions, `footprint_ok`, and solver eligibility.

For direct binding, current asset dimensions should match the generation passport under a dedicated versioned policy. Do not reuse the room slot tolerance of −20/+10%; that answers a different question. For family reuse with differing sizes, require an explicit `same_shape_rescalable` decision and store the member’s passport hash.

### Geometry versus appearance

A family variant can be solver/geometry-ready without being demo-ready. The current demo explicitly rejects representative meshes with a mismatched colour [flat215_demo.py:600](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:600).

Expose separate capability flags:

- `solver`: current dimensions/placement facts are valid.
- `local_3d`: mesh, orientation, and geometry gates pass.
- `appearance`: exact appearance or validated tint.
- `published_3d`: local 3D ready and the exact mesh revision is published.

For the final `status="ready"` consumed by the demo, require all applicable capabilities. Otherwise 563 variants would become technically bound but visibly wrong.

## `catalog_items.py`

Replace `mesh_state()/with_mesh()` for non-living items with one bulk load of the binding artifact.

At present:

- `room_catalog` items receive an entirely empty asset object [catalog_items.py:207](/home/pakar/igor/remlab/tools/scout/catalog_items.py:207).
- `with_mesh()` adds only `ready/generated` and `defect`; it does not identify the actual asset, family representative, orientation, or URL [catalog_items.py:231](/home/pakar/igor/remlab/tools/scout/catalog_items.py:231).

Keep the existing keys for compatibility, but extend `asset` with:

```text
mesh_status
mesh_url
revision
defect
ready
asset_id
mesh_id
representative_offer_id
via_family
generation_key
revision_key
source_sha
glb_sha
orientation
passport_status
gate_status
published
reasons[]
binding_snapshot
```

Recommended behavior:

- `with_assets=False`: retain the cheap current behavior.
- `with_assets=True`: load the snapshot once and overlay by `offer_id`.
- Missing, malformed, or version-incompatible binding: fail closed for room meshes with `mesh_status="unbound"` and a reason.
- Living/product rows retain their current DB fields until living parity permits migration.
- An offer present in several rooms gets the same asset binding; only `room_type` and `roles` differ.

`asset_coverage.py` will then naturally stop calling these files orphans because its status function already recognizes `mesh_url + mesh_status=ready` as bound [asset_coverage.py:41](/home/pakar/igor/remlab/tools/scout/asset_coverage.py:41).

## Publishing

Do not create a second full publisher; that would duplicate disk-space, rsync, and index safety. Add an opt-in room provider around the existing publisher while preserving the living selection byte-for-byte.

Flow:

1. Run existing `bank_files()`, `ready_skus()`, and `demo_band.publish_skus()` unchanged.
2. If a room binding/bank configuration is present, load bank offer IDs and resolve only `published-eligible` bindings to their representative `mesh_id`.
3. Run the existing living `gallery_build.py`.
4. Stage room models into the gallery from the exact `local_path` in the binding, verifying the full SHA.
5. Union the room mesh IDs only for rsync/index accounting.
6. Publish, rebuild the index, then build room demo data.

The exact-path staging is important. `gallery_build.py` currently chooses the newest manifest by filesystem mtime [gallery_build.py:198](/home/pakar/igor/remlab/tools/scout/salad/gallery_build.py:198), whereas the binding must publish the selected `generation_key`. Passing room SKUs through `GALLERY_ONLY` alone could publish a different generation than the one declared ready.

The living publisher currently derives readiness only from `products` and translates to the family representative [mesh_publish.py:69](/home/pakar/igor/remlab/tools/scout/mesh_publish.py:69). Its default bank/candidate behavior should remain unchanged [mesh_publish.py:56](/home/pakar/igor/remlab/tools/scout/mesh_publish.py:56).

For room demo data:

- `sid` remains the offer.
- `msid`/`meshId` comes from `asset.mesh_id`, which may be the family representative.
- `yaw` comes from the binding’s exact orientation resolution, not from a product-only family lookup.
- Do not attach `msid` merely because the SKU appears in `mesh-index.json`.

The current demo treats index membership as mesh availability [flat215_demo.py:230](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:230), and `_msid` only knows families stored in `products` [flat215_demo.py:280](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:280). The generic room path must use the binding instead. Next.js already consumes `msid` directly as `meshId` [fromDemo.ts:294](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:294).

The nightly ordering should be:

```text
ingest registry
→ orientation
→ build atomic binding snapshot
→ legacy + room mesh publication
→ verify production index
→ build room demo/banks
```

The existing publisher already documents that publication must precede demo rebuilding [mesh_publish.py:14](/home/pakar/igor/remlab/tools/scout/mesh_publish.py:14).

## Principal failure modes

1. **Regeneration selects a different GLB.**  
   New generation without orientation must make the offer `orientation_pending`; do not silently retain or publish the old asset. Previous snapshot remains available only for explicit rollback.

2. **Gallery publishes a different generation.**  
   Avoid SKU-only selection for rooms; stage the exact bound path and verify SHA.

3. **Orientation rule changes are not invalidated.**  
   The checked-out tree still has `orient-v1` [orient_worker.py:34](/home/pakar/igor/remlab/tools/scout/orient_worker.py:34), and `pending_meshes()` skips any existing identical revision key [orient_worker.py:233](/home/pakar/igor/remlab/tools/scout/orient_worker.py:233). Adding кровать/тумба прикроватная/шкаф to `DIRECTED` must bump the orientation contract or explicitly invalidate prior `symmetric_by_role` results. Otherwise those meshes will never be reconsidered.

4. **Orientation changes without GLB changes.**  
   Include a hash of the orientation resolution/status/contract in the binding snapshot. Human yaw changes must rebuild demo data even when `glb_sha` is unchanged.

5. **Photo changes under the same URL.**  
   A room photo hash artifact is needed because `CatalogItem.photo.revision` is currently `None` [catalog_items.py:212](/home/pakar/igor/remlab/tools/scout/catalog_items.py:212). URL equality is insufficient.

6. **Dimensions change after generation.**  
   Passport mismatch makes the binding stale until explicitly revalidated or regenerated.

7. **Representative rejection invalidates variants.**  
   Resolve references dynamically from one family record; do not copy ready status into 563 independent records.

8. **Colour-family reuse produces wrong visuals.**  
   Keep geometry and appearance readiness separate.

9. **Offer disappears or moves roles/rooms.**  
   Omit it from the active offer map or emit a tombstone. Bank references become explicit `offer_not_in_catalog` failures. Preserve historical snapshots, but never resurrect them automatically.

10. **Hand-published GLB differs from the binding.**  
    Production index membership proves only that a path exists. The room publisher must overwrite/verify the expected bound bytes before advertising `published_3d`.

11. **Snapshot split-brain.**  
    Write to a temporary file, fsync, validate, then atomically rename. Include source snapshot hashes and a monotonically changing content digest.

## Required tests

### Pure/unit tests

- Same `(mid,eid)` in two rooms and three roles produces one offer binding.
- Direct binding selects the matching current photo revision and its `current_generation_key`, not newest mtime.
- Missing file, truncated file, or SHA mismatch is never ready.
- New generation with old-generation orientation is not ready.
- `auto_resolved` and `human_resolved` pass; pending, unusable, and wrong contract fail.
- Changing `DIRECTED`/orientation contract invalidates old `symmetric_by_role`.
- Owner rejection, quarantine, `flat_shape`, and failed generation invalidate the binding.
- Direct passport match, dimension change, and lost `footprint_ok`.
- Family variant inherits the representative asset by reference.
- Rejected/regenerated representative invalidates every member.
- Missing representative, family cycle, and two representatives fail closed.
- Geometry-ready but colour-mismatched variant is not appearance-ready.
- Removed offer is not returned by `catalog_items`, even if an old snapshot or production file exists.
- Binding snapshots are deterministic and atomic; interrupted generation leaves the prior snapshot intact.

### Adapter tests

- Existing living `CatalogItem` output remains exactly equal when no room binding is configured.
- Bedroom item receives `asset_id`, `mesh_id`, exact orientation, representative, and reasons.
- Missing/corrupt/unsupported artifact yields `unbound`, not an exception halfway through a catalog result.
- One bulk artifact read per `items()` call; no per-offer SQL or filesystem lookup.
- Updated catalog-item schema accepts the extended asset object.

### Publisher tests

- With room configuration absent, living selected SKUs and commands are exactly unchanged.
- A room bank adds only locally ready bindings.
- Variant bank entry publishes the representative mesh ID once.
- The staged file comes from the bound generation path, even when a newer unbound generation exists.
- SHA mismatch aborts room staging without suppressing living publication.
- Existing hand-published wrong bytes are replaced or rejected.
- Missing room bank fails explicitly; it does not silently publish all room meshes.
- Production index contains the published representative before room demo data gains `msid`.
- Regeneration updates cache/version metadata so clients do not retain the old GLB.

### Integration/regression tests

- Temporary DB fixture: `room_catalog` offer absent from `products` → generation → exact orientation → binding → catalog adapter → publication selection.
- One offer shared by bedroom and hall binds once and produces two room memberships.
- Bedroom bank → binding → gallery → index → demo data → Next `meshUrl`.
- Re-run `asset_coverage`: the 781 bedroom orphans move to bound/blocked categories with reason accounting; “outside rooms” remains stable.
- Full living parity/golden test before and after the opt-in publisher hook.
- Deleted offer, stale photo, changed dimensions, new GLB, and human orientation change each produce the expected invalidation.

## Uncertainties

- The DEV DB socket was unavailable in this read-only sandbox, so I could not independently verify the supplied counts or inspect live revision/family rows.
- The pending branch that adds the bedroom roles to `DIRECTED` is not visible here. I could not verify whether it also bumps the orientation contract; that is mandatory.
- A versioned tolerance policy for direct and family passport compatibility does not yet exist. It should be decided explicitly rather than borrowing solver slot tolerances.
- The policy for colour variants—exact texture, automatic tint, or temporary geometry-only use—needs an owner/product decision before 563 variants can honestly be called demo-ready.
- Room photo hashing is not yet part of the adapter path, so strict source freshness requires a small file-backed photo-revision cache.
- The production index currently proves path presence, not the bound GLB revision. Revision metadata or verified staging is needed for strong publication readiness.

No files were modified.