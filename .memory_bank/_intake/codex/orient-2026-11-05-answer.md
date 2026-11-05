## Conclusion

Fix (b) is mathematically and operationally correct: when the raw furniture is upright and its front is visible at MR yaw 0°, the raw-to-canonical matrix must be a 180° Y rotation, while the legacy scalar must be 0°. I found no downstream double flip.

However:

- The fix will not update any existing decision automatically.
- Recomputing all 375 in place is unsafe until the top-view hash-selection and cache problems are addressed.
- The broader “raw 0° whenever VLM is absent” policy is not sound across all furniture roles.
- Commit `e6a1e01e` has material rollout defects in the PBR/reseed changes and fails to version its changed orientation semantics.

I would accept the narrow orientation fix after adding a controlled migration, but would not deploy the broad raw-0 policy or the commit as-is.

## 1. Correctness and downstream behavior

The conventions are internally consistent:

- Canonical front is explicitly “MR-yaw 180” at [orient_worker.py:31](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:31).
- `front_yaw_from_R()` derives the raw camera yaw at which the canonical front is visible at [orient_worker.py:50](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:50).
- The new fallback is `Ry(180)` with the matching WXYZ quaternion at [orient_worker.py:62](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:62).
- The fallback now updates all representations—`R`, quaternion, legacy yaw and tilt—at [orient_worker.py:180](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:180).

That produces:

- Full-matrix path: raw front at yaw 0 is mapped to canonical front at yaw 180.
- Legacy path: `legacy_front_yaw = 0`, correctly saying the front is visible in the raw yaw-0 view.

The previous implementation had an additional consistency bug: it replaced the local quaternion and working `R`, but did not update stored `resolution.R`. All 375 stored rows I inspected have identity quaternion, legacy yaw 180, but a non-identity rejected network matrix. A representative sidecar shows the contradiction at [orientation JSON:6](/home/pakar/scout-scenes/orientation/v1/112923_4922194797449750070__ea50337176fbae12__orient-v1.json:6), [line 12](/home/pakar/scout-scenes/orientation/v1/112923_4922194797449750070__ea50337176fbae12__orient-v1.json:12), and [line 33](/home/pakar/scout-scenes/orientation/v1/112923_4922194797449750070__ea50337176fbae12__orient-v1.json:33). The commit correctly repairs this for newly computed decisions.

### Downstream consumers

I found no code that combines both the matrix and scalar and thereby double-flips:

- `mesh_publish` copies the raw GLB; it does not bake orientation into it: [mesh_publish.py:179](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/mesh_publish.py:179).
- Server scene rendering applies scalar yaw exactly once as `Ry(-front_yaw)`: [scene_mesh.py:87](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/scene_mesh.py:87).
- Browser placement does the same once: [meshes.ts:146](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/lib/viewer3d/meshes.ts:146).
- Demo/catalog builders merely pass the published scalar through: [flat215_demo.py:1590](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/flat215_demo.py:1590), [build-catalogue.mjs:137](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/flat3d/build-catalogue.mjs:137).
- Matrix consumers apply `R` once for dimensions/review: [mesh_dims.py:88](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/mesh_dims.py:88), [mesh_review_sync.py:59](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/mesh_review_sync.py:59).
- Human review composes one correction into `R` and updates the scalar consistently: [mesh_review_sync.py:145](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/mesh_review_sync.py:145).
- `cabinet_front` analyzes the raw GLB and returns an absolute raw yaw; top-view uses it as an override, not an extra rotation: [topview_render.py:349](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/topview_render.py:349).

`render_top(..., R=...)` applies `R` and then uses canonical yaw 180, which is intentional rather than compensation: [topview_render.py:180](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/topview_render.py:180). The production loop currently uses only the scalar path.

There are two misleading comments/docstrings, but the executable code is correct: [scene_mesh.py:8](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/scene_mesh.py:8) says `-front_yaw`, while line 10 describes `+front_yaw`; and the top-view lookup docstring claims the full `R` is applied although the main loop deliberately uses only the scalar.

### Existing decisions

They will not change on their own.

`pending_meshes()` excludes every existing revision key at [orient_worker.py:258](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:258), and the key includes the unchanged `orient-v1` contract at lines 269–272. The commit did not bump `CONTRACT` or the front-method version.

The 375 sidecars all predate the commit. They represent 318 unique SKUs; 45 SKUs have multiple affected revisions. Therefore any update requires explicit recomputation or deletion/versioning of those exact revision keys.

## 2. Recomputing the 375

It is appropriate to recompute them, but not as a blind in-place rerun.

The cohort is genuinely suspect:

- Exact role distribution matches the report.
- All 46 `seat_conflict` records have the confident seat front at yaw 0.
- All 375 have inconsistent stored matrix/quaternion/scalar representations.
- Matrix consumers such as dimension measurement may currently use the rejected tilted `R`, even though scalar consumers use yaw 180.

Recommended reversible process:

1. Export the exact 375 DB rows, including `revision_key`, status, full resolution and timestamp. Also copy their sidecars, `topview.json`, relevant PNGs, and published `orient.json`.
2. Match each row to the exact GLB SHA. Do not recompute “by SKU”: 375 rows are only 318 SKUs.
3. Exclude any row currently marked `human_resolved`, `human:*`, or `unusable`, regardless of what its older sidecar says.
4. Shadow-recompute under a non-production contract/directory. Reuse the stored original orienter output so only the fallback semantics change.
5. Re-run seat evidence and VLM evidence. Old VLM evidence was collected from the wrong side and cannot simply be reinterpreted.
6. Review changes by role, then promote exact revision keys in batches.
7. Force targeted top-view regeneration and merge publication only after validation.
8. Rollback by restoring the saved DB rows and sidecars/published orientation entries. Raw GLBs are untouched, so rollback is straightforward.

Two blockers should be fixed before promotion:

- Top-view selects the latest orientation by SKU, not the current GLB hash: [topview_render.py:27](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/topview_render.py:27). Updating an old revision can therefore make its yaw the “latest” and apply it to another GLB.
- Its cache only compares PNG and GLB mtimes, ignoring orientation changes: [topview_render.py:313](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/topview_render.py:313). A promoted DB decision will leave stale top-view metadata unless `TOPVIEW_FORCE=1` is used.

## 3. Broad “raw 0° without VLM” policy

Do not enable this globally.

The data supports raw 0° as a strong prior for seated furniture, but not as a universal invariant:

| Role/evidence | Inferred raw-0 front |
|---|---:|
| Sofa, confident seat evidence | 729/766 = 95.2% |
| Armchair, confident seat evidence | 491/498 = 98.6% |
| Chair, confident seat evidence | 331/351 = 94.3% |
| Chest, confident VLM-derived evidence | 162/205 = 79.0% |
| TV stand, confident VLM-derived evidence | 127/182 = 69.8% |

Thus:

- Sofas/armchairs: raw 0° is a good fallback prior, but still leaves roughly 1–5% wrong. Prefer the seat detector whenever confident.
- Chests/TV stands: plainly unsafe as a blanket policy. Use `cabinet_front`, VLM, or review.
- Beds: the artifact records 24/24 headboard-rule results at raw 0°, e.g. [beds.json:1](/home/pakar/remlab-logs/t36-2-front-1105-1944-v4/beds.json:1), but the executable rule that produced the artifact is absent. This is promising, not sufficient validation.
- Nightstands: the visual sheets contain counterexamples—items 34 and 36 show their drawer/open front at network yaw 90, while raw 0 is a plain side/back.
- Wardrobes: the selected sheets are favorable, but there is no independent, persisted ground truth.

The reported “22/86 changed, all correct” dry run does not test the broad proposal. Its code runs the existing cascade and changes only `up_rejected` cases; `cand_yaw0` is merely recorded at [dry_orient.py:21](/home/pakar/remlab-logs/t36-2-front-1105-1944-v4/dry_orient.py:21). It also joins “latest orientation by SKU” to the first sorted GLB rather than by hash at lines 29–34. A true raw-0 policy would change 36/86 bedroom meshes, not 22: 4 beds, 9 nightstands and 23 wardrobes.

Before enabling per role, I would require:

- Exact-SHA current GLBs only.
- Blind functional-front labels from the product photo plus four raw mesh views.
- Stratification by role, supplier and source-photo angle.
- Paired comparison of raw 0 versus network yaw, with disagreements oversampled and prevalence-weighted.
- At least 149 zero-error examples per role to claim a <2% error rate at approximately 95% one-sided confidence; otherwise keep the result as a prior or review-pending state.
- Separate thresholds for 180° errors and 90° side errors.

## 4. Other issues in `e6a1e01e`

Material issues:

- Orientation semantics changed without bumping `CONTRACT` or `versions.front`, so neither persisted decisions nor caches are invalidated.
- Manifest fallback runs only for literal `'?'`: [orient_worker.py:161](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/orient_worker.py:161). A `NULL` or empty `mesh_demand.role` bypasses the manifest and is treated as nondirectional. It should conceptually test “missing or `?`”.
- PBR verdicts are cached solely by `verdict.json >= model.glb`: [apply_repairs.py:227](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/apply_repairs.py:227). None of the 3,396 existing verdicts is newer than this commit; 1,577 remain `geometry_valid`. The missing-normal relaxation therefore does not reclassify existing meshes.
- The existing reseed file is loaded and retained at [apply_repairs.py:161](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/apply_repairs.py:161). The new helper only prevents new additions; it does not remove old geometry-valid entries before rewriting at line 268. The live queue still has 2,599 entries.
- `geometry_valid` now goes neither to reseed nor manual repair, and I found no separate finishing queue. That may be intentional, but non-normal-map PBR failures—missing metallic/roughness, baked light, transmission/emissive failures—can become stranded.
- The no-model branch still adds every seed-0 GPU-gate status to reseed without calling `wants_reseed()` at [apply_repairs.py:207](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/salad/apply_repairs.py:207), so “only generated goes to reseed” is not literally enforced.

The new missing-normal behavior itself is reasonable and retains all other PBR checks at [mesh_gate_pbr.py:138](/home/pakar/igor/remlab/.claude/worktrees/t36-mesh-holes/tools/scout/mesh_gate_pbr.py:138).

## Uncertainties

- I could not query the live database because Docker access is denied in this review environment; persisted sidecars and repository code were available.
- I reproduced the 375 total and role/source counts, but not the report’s exact chest `49/67` or TV-stand `29/52` subsets. All affected sidecars give chest `58 back / 19 front / 1 none` and TV stand `38 back / 37 front`; the report’s filtering provenance is absent.
- The 24/24 bed heuristic results are present, but its generating code is not.
- The bedroom sheets are selected examples, not a randomized or blinded evaluation.