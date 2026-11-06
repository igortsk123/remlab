## Verdict

The plan is directionally sound, but it is not safe to execute as written. Its main problems are:

- The quota has three incompatible meanings.
- K5 enables rooms before K6 makes the frontend room-aware.
- Only bedroom-1 is enabled; bedroom-2 is omitted.
- Rooms support five styles while the living room has six.
- Publication happens before first-visit photos are warmed.
- Existing room mesh machinery is understated and partly bypassed.
- The estimated 64 meshes / ~51 RUB is unsupported by the stated acceptance criteria.
- There is no atomic “complete apartment or last-good apartment” publication gate.

## 1. Gap-table accuracy

| Plan row | Finding |
|---|---|
| Catalog | Mostly correct: nightly currently runs only `room_catalog`, and it runs late—after photo/style/cutout and mesh processing. That late placement is the more important missing gap because the new catalog cannot affect the same night’s downstream work. See [refresh_daily.sh:440](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:440). |
| Alive | Correct that room catalogs have no durable `photo_alive` field: [013-room-catalog.sql:5](/home/pakar/igor/remlab/tools/scout/013-room-catalog.sql:5). `img_alive` updates products and candidate indexes, not room catalog rows: [img_alive.py:165](/home/pakar/igor/remlab/tools/scout/img_alive.py:165), [img_alive.py:203](/home/pakar/igor/remlab/tools/scout/img_alive.py:203). Missing: the plan needs exact checked URL, timestamp/run ID and unknown/dead semantics, not merely “one field.” |
| Styles | Manual-only is substantially correct, but the proposed adapter is underspecified. `style_score` supports the room sources [style_score.py:32](/home/pakar/igor/remlab/tools/scout/style_score.py:32), but bedroom needs a file output while hall consumption expects DB scores [catalog_items.py:217](/home/pakar/igor/remlab/tools/scout/catalog_items.py:217). Also, scores are globally keyed by product, while bedroom applies room-specific material rules [style_score.py:86](/home/pakar/igor/remlab/tools/scout/style_score.py:86), [style_score.py:320](/home/pakar/igor/remlab/tools/scout/style_score.py:320). The plan must decide whether style is global or room-specific. |
| Selection | Factually wrong. Selection is not “only manual compose.” `room_mesh_demand.py` already selects by room/style/role/slot, applies the −20%/+10% envelope, deduplicates demand, and emits queue snapshots: [room_mesh_demand.py:1](/home/pakar/igor/remlab/tools/scout/room_mesh_demand.py:1), [room_mesh_demand.py:411](/home/pakar/igor/remlab/tools/scout/room_mesh_demand.py:411). K2 should extend this path, not re-create it through products-only `mesh_bind`/`mesh_family`. |
| Cutouts | Integration gap is correct, but scripts already support room targets. They are disabled nightly by `CUTOUT_DAILY_MAX=0`: [refresh_daily.sh:301](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:301). More seriously, the same SKU is assigned one lexicographically chosen room/role [photo_hash.py:235](/home/pakar/igor/remlab/tools/scout/photo_hash.py:235), although verdicts are role-sensitive [cutout_sync.py:163](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:163), while the cache key omits role [mesh_queue.py:116](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:116). This can reuse an inappropriate verdict across rooms. |
| “30 variants” | The current limits are not just 24/12/12. They are bed 24, nightstand/dresser/wardrobe 12, vanity 8: [flat215_demo.py:1077](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1077). Bedroom feeds also merge bank, styled alternatives and unstyled photo-catalog items [demo_bedroom.py:390](/home/pakar/igor/remlab/tools/scout/demo_bedroom.py:390). |
| Placement | Broadly correct that nightly compose is not wired and geometry flags are off. However, `compose_bedroom --nightly` currently skips every room [compose_bedroom.py:655](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:655). Missing blocker: the bedroom composer writes the candidate before validation and returns success even on hard failures [compose_bedroom.py:676](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:676). Candidate output must be atomic and failure must be nonzero. |
| Orientation | Correct but incomplete. Directed roles are hard-coded and omit several hall-specific roles [mesh_queue.py:52](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:52), [orient_worker.py:45](/home/pakar/igor/remlab/tools/scout/orient_worker.py:45). T-78 is a prerequisite for usable hall bindings, not optional cleanup. |
| Queue/autostart | Incomplete. `mesh_bind`, `mesh_family`, and `mesh_priority` are products-oriented [mesh_bind.py:128](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:128), [mesh_family.py:243](/home/pakar/igor/remlab/tools/scout/mesh_family.py:243). `wave_guard` only obtains queues through `mesh_priority`, not room queue files [wave_guard.py:201](/home/pakar/igor/remlab/tools/scout/wave_guard.py:201). Meanwhile `room_mesh_demand` already produces room snapshots. K2 therefore needs queue arbitration and accounting integration, not merely `MESH_PROFILE=demo`. |
| Bank | Correct that bedroom support is skeletal and hall is absent: [room_bank_spec.py:153](/home/pakar/igor/remlab/tools/scout/room_bank_spec.py:153). Missing: the current bank candidate rules still disable bedroom flags [bank-candidate.json:52](/home/pakar/igor/remlab/rules/bank-candidate.json:52), and T-70 previously failed because alternatives were below three. |
| Publication | Understated. `batch_show` runs products `mesh_bind`, but never rebuilds room bindings after orientation/publication [batch_show.py:622](/home/pakar/igor/remlab/tools/scout/batch_show.py:622). `room_publish` skips non-ready offers rather than requiring complete room coverage [room_publish.py:83](/home/pakar/igor/remlab/tools/scout/room_publish.py:83), and `mesh_publish` returns success for several no-op/failure states [mesh_publish.py:173](/home/pakar/igor/remlab/tools/scout/mesh_publish.py:173). |
| Vitrine | Correct that hall has no adapter. Missing structural blocker: feeds and slot bands are globally keyed by base role [flat215-demo/index.html:4804](/home/pakar/igor/remlab/public/flat215-demo/index.html:4804), while bedroom merge uses `setdefault(role, rows)` [flat215_demo.py:1280](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1280). Living, bedroom and hall roles can collide. Feeds need room instance/type + role + slot/purpose keys. |
| AI photos | Correct that hall-specific prompt rules are absent: [improve-rooms.json:1](/home/pakar/igor/remlab/rules/improve-rooms.json:1). Missing: the regeneration server silently proceeds without an identity/reference sheet if construction fails [improve_mode.py:566](/home/pakar/igor/remlab/server/improve_mode.py:566). That directly violates “product photos attached.” |
| First visit | Missing row. Warm support already exists, but it runs after main publication [refresh_daily.sh:445](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:445), [refresh_daily.sh:461](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:461). Therefore a newly published room can be visible without frames. |

Two further missing blockers:

- Living has six styles, including neoclassic [flat215_demo.py:515](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:515), but bedroom and hall composition files define only five [bedroom-composition.json:7](/home/pakar/igor/remlab/data/scout/bedroom-composition.json:7), [hall-composition.json:3](/home/pakar/igor/remlab/data/scout/hall-composition.json:3).
- K5 enables only bedroom-1. The apartment contains bedroom-1, bedroom-2 and hall [demo.json:65](/home/pakar/igor/remlab/data/partners/demo.json:65), [demo.json:74](/home/pakar/igor/remlab/data/partners/demo.json:74), [demo.json:101](/home/pakar/igor/remlab/data/partners/demo.json:101).

## 2. Correct task order

K5 must not precede K6. The recommended critical path is:

1. **Freeze contracts and quota semantics.** Define required room instances, bedroom-2 purpose, six styles, required slots, minimum supply, product-count versus unique-mesh-count, and failure/degraded behavior.
2. **Implement room-aware data keys.** Feeds, slot bands, frame identities and selection state must include room instance/type, role and slot/purpose. This is the core of K6 and must precede room enablement.
3. **Move K1 to the head of nightly.** Create fresh bedroom and hall catalog snapshots before style, photo, cutout, bank and mesh-demand stages.
4. **Build strict candidate manifests.** Atomically compose/check both bedrooms and hall, retain last-good output, and refuse hard-invalid candidates.
5. **Run a dry inventory/budget pass.** Count eligible products, unique families, already-ready meshes and new paid jobs.
6. **Generate and process room mesh demand.** Extend `room_mesh_demand`; unify direct queue snapshots with `wave_guard`, budget ledger and deduplication.
7. **Orient, rebuild bindings, publish assets, rebuild bindings again.** Published-state readiness cannot be known before these steps.
8. **Build the complete apartment in an unpublished staging location.** Validate all room/style/slot/feed/mesh/frame invariants.
9. **Warm all first-visit frames before switching main `/demo`.**
10. **Atomically promote the complete apartment or retain last-good.** No visible `/test` is required.

Work that can run in parallel:

- T-73 mirror implementation and T-78 orientation-role work.
- Bedroom and hall catalog adapters after the common catalog contract is fixed.
- Hall prompt/reference-sheet work and warm validation tooling.
- Supply expansion K9 alongside K1–K4, although it blocks final acceptance.
- Candidate-bank development and frontend room-key work, once the shared schema is decided.

K4 has two phases: candidate construction can occur before meshes; live bank promotion cannot.

## 3. Hidden blockers and risks

### Money and quota math

The plan contradicts itself:

- K1 says 30 per room × role × style [room-conveyor-02.md:48](/home/pakar/igor/remlab/.memory_bank/plans/room-conveyor-02.md:48).
- The quota section says 30 per room × style distributed among roles [room-conveyor-02.md:65](/home/pakar/igor/remlab/.memory_bank/plans/room-conveyor-02.md:65).
- Acceptance says up to 30 for every slot [room-conveyor-02.md:74](/home/pakar/igor/remlab/.memory_bank/plans/room-conveyor-02.md:74).

Those are radically different workloads.

The current ledger reports 500 RUB total, 78.9 spent and **421.1 RUB remaining**, not approximately 424. At 1.4 RUB/model, that is at most about 300 new models.

For five styles, 30 products per styled slot implies at least:

- Bedroom major roles: 4 × 5 × 30 = 600 product positions.
- Hall mesh roles: 6 × 5 × 30 = 900 product positions.

That becomes 1,800 positions for six styles. Deduplication and shared representatives can reduce paid meshes substantially, but the plan’s “64 meshes / ~51 RUB” cannot be derived from its acceptance criteria. The dry run must separately report products, unique families, ready assets and new paid jobs.

Accounting is also split: room budget reads the manual room ledger [room_mesh_demand.py:27](/home/pakar/igor/remlab/tools/scout/room_mesh_demand.py:27), while automatic waves use a separate dollar-denominated lease [wave_guard.py:218](/home/pakar/igor/remlab/tools/scout/wave_guard.py:218). Automatic room waves would otherwise escape the 500 RUB ledger.

### Runtime and RAM

The nightly already contains:

- A 25-minute photo sweep [refresh_daily.sh:254](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:254).
- A catalog API step documented around 26 minutes [refresh_daily.sh:207](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:207).
- An approximately 11-minute bank candidate pass [refresh_daily.sh:408](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:408).
- Orientation/top-view history involving roughly 8–10 GB failures [batch_show.py:350](/home/pakar/igor/remlab/tools/scout/batch_show.py:350).

Style scoring loads CLIP and uses eight LLM workers [style_score.py:239](/home/pakar/igor/remlab/tools/scout/style_score.py:239), while cutout jobs may retry eight times and wait up to 300 seconds [cutout_sync.py:57](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:57). Enabling full-catalog room cutouts could dominate the nightly. Paid cutouts should target the selected supply manifest and have per-stage time, money and retry-debt caps.

The local filesystem was 90% used during review. `wave_guard` rejects disks at 85% usage [wave_guard.py:92](/home/pakar/igor/remlab/tools/scout/wave_guard.py:92), so automatic mesh startup is currently blocked even before queue logic.

### Living-room regression and data roles

Shared global structures make regression plausible:

- Product style scores are global although scoring rules vary by room.
- Cutout verdicts are cached without role.
- Frontend feeds are keyed only by role.
- Room binding publication is a shared snapshot rather than isolated per-room writes.

The plan’s “living parity” needs concrete golden checks after catalog/style, binding and frontend-build stages—not only a general acceptance sentence.

### Partial publication

The demo builder warns and drops incomplete styles rather than failing [flat215_demo.py:1266](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1266). The runtime mesh check covers current variants and only the first six feed candidates [demo_rt.sh:20](/home/pakar/igor/remlab/tools/ops/demo_rt.sh:20). Neither proves the owner’s 30-per-slot or all-room/all-style requirement.

Processing failures may be allowed not to block living-room refresh, but publication must use either:

- a complete new room snapshot, or
- the complete last-good room snapshot.

Publishing a mixture of current living data and half-updated room data is unsafe.

## 4. Missing work required for the owner goal

- Add the sixth style, neoclassic, to bedroom and hall or explicitly revise the acceptance requirement.
- Furnish and enable bedroom-2, not only bedroom-1.
- Choose bedroom-2’s actual purpose; several modes remain pending in the composition data.
- Define per-slot product supply separately from paid Hunyuan mesh supply. Rugs, lamps, curtains, throws and mirrors need explicit asset strategies even if they do not consume Hunyuan quota.
- Treat K9 supply expansion as a blocking task, not optional cleanup. Several hall roles reportedly have only four or five fitting items.
- Make composer output atomic: write/check a candidate, then rename; retain last-good on failure.
- Add an apartment-level manifest gate for the exact room × style × slot matrix.
- Rebuild room bindings after orientation and again after publication.
- Validate all intended swap candidates, not only the first six.
- Pre-warm frames before main promotion. `demo-warm` currently creates draft frames and defaults to a cap of `5 × rooms` [demo-warm.mjs:32](/home/pakar/igor/remlab/tools/ops/demo-warm.mjs:32); six styles across four rooms would need 24 frames, exceeding the default cap of 20.
- Decide whether “first visit photos” permits draft frames. The realistic nightly budget is only about five images at the configured 50 RUB cap [demo-realistic.json:3](/home/pakar/igor/remlab/rules/demo-realistic.json:3), so realistic prepopulation of all room/styles cannot happen in a single normal night.
- Make product references mandatory for regeneration. If any placed product photo or identity sheet is missing, do not spend money on a reference-free generation.
- Test regeneration after a swap and verify that the attached reference sheet contains the new SKU/photo hash, not the old one.
- Add hall-specific generation rules preserving entrance/storage/mirror structure and forbidding bedroom/living-room furniture.
- Use stable slot/item IDs in reference construction; role-only dictionaries can overwrite repeated roles.
- Introduce unpublished internal staging followed by an atomic or manifest-driven main switch. This complies with “main `/demo` only”; it does not require a user-visible test demo.

## 5. Recommended plan changes, ranked

### P0 — Required before any paid mesh run or room enablement

1. Rewrite the quota and acceptance section with one definition: per-slot eligible products, minimum publish threshold, unique mesh-family target, and maximum new paid meshes.
2. Add bedroom-2 and the sixth style to scope.
3. Move the room-aware feed/state contract from K6 to the first implementation task.
4. Replace K2’s products-oriented `mesh_bind → mesh_family` approach with an extension of `room_mesh_demand`.
5. Add a dry-run inventory and RUB report as a hard approval gate.
6. Unify room queue accounting with `wave_guard`; include currency, room attribution and deduplicated job IDs.
7. Make K9 a blocking dependency wherever supply is below the declared minimum.
8. Add complete-snapshot/last-good publication semantics.

### P1 — Required before main `/demo` promotion

9. Move both catalogs to the head of nightly and attach run IDs/freshness.
10. Fix room/role-sensitive style, cutout and frontend keys.
11. Make compose/check/promote atomic and hard failures nonzero.
12. Add six-style apartment completeness validation.
13. Extend orientation roles and complete mirror handling.
14. Rebuild bindings around orientation/publication and require exact offer coverage.
15. Warm all expected frames before main publication and automatically retain/restore last-good on failure.
16. Make the regeneration identity sheet mandatory and verify swapped-SKU references.

### P2 — Operational hardening

17. Put style, cutout, compose and mesh postprocessing under the existing heavy-work scheduling mechanism.
18. Add per-stage time/RAM/API-money caps and backlog metrics.
19. Add living-room golden parity checks after each shared-data mutation.
20. Add two clean unpublished shadow nights before enabling the rooms.
21. Keep K8 color work deferred unless it becomes necessary to remove visible placeholders or family mismatches.

## What I could not verify

I could inspect the repository, local ledger/lease/pause files and local disk state, but could not safely run the full nightly, paid APIs, production DB/network operations, Salad generation, or visually test production `/demo` under the read-only environment. I also could not substantiate the claimed 64-mesh demand from a committed T-82 artifact; it appears to be a plan estimate rather than evidence produced by the current acceptance criteria. No files were modified.