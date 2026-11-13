## 1. Conclusion

Commit `ca7d70e5` is not the correct general fix. It makes a dresser an inventory-level alternative to seating and rewards dresser-bearing sets indirectly, but it does not establish the required solver invariant.

The correct invariant is:

> Adding an optional dresser–lamp atom to a bank must never worsen hard feasibility, circulation, or realization of required seating, coffee-table, media, and scenario-required dining. If it cannot be added to an already valid core plan, the whole dresser–lamp atom is omitted and reported in `skipped_optional`.

Formally, for required-outcome vector `M`:

```text
M(solve(bank + optional_dresser_lamp)) <= M(solve(bank))
```

The dresser should therefore be lower priority than every required slot/zone, but it need not be the first thing dropped among all optional objects. A sensible order is:

```text
hard feasibility
→ required seating atom + coffee table
→ required media
→ required dining, when the scenario requires it
→ circulation/template integrity
→ preferred zones (currently dining, then storage)
→ optional dresser + lamp / other enrichment
→ decor and aesthetics
```

Unplaceable extra items must be neutral in set selection: neither reward nor penalty. A dresser-bearing set should win only if the dresser and lamp are actually realized without worsening the higher-priority plan.

## 2. Evidence

### The commit changes the wrong abstraction

At `ca7d70e5`:

- `tools/scout/composition.json:28-31` adds the dresser to the 14–16 m² inventory band.
- `services/planner-solver/rules/occupancy.json:1198-1211` groups dresser, pouf, and armchair as mutually exclusive, with dresser first.
- `tools/scout/compose2.py:675-696` implements `instead_only_by_band` and moves the entire exclusive group to the earliest position in the composition order.

That treats storage and seating as substitutes. They are not equivalent functions; whether either fits is a geometry decision. It also moves the dresser ahead of mandatory media in the composer. The ordinary order already puts storage before the TV stand at `ca7d70e5:tools/scout/compose2.py:666-667`; the new reordering can move the dresser earlier still.

The later TV fallback at `ca7d70e5:tools/scout/compose2.py:975-984` repairs missing inventory after floor/perimeter caps, but does not undo set-selection or geometry changes caused by the dresser.

### The declared rules already say light is optional and media is required

[services/planner-solver/rules/zones.json:1005](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1005) orders media before dining, storage, light, and decor. Its status table declares:

- media required,
- dining and storage preferred,
- light optional.

See [zones.json:1043](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1043).

But `plan_key` adds a special dresser/floor-lamp term before preferred-zone coverage:

- [zones.py:1616](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1616) defines light carriers.
- [zones.py:1638](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1638) documents the ranking.
- [zones.py:1683](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1683) places `light_missing` before `-covered_pref`.

The existing test deliberately requires this override: [test_beam_hypotheses.py:98](/home/pakar/igor/remlab/services/planner-solver/tests/test_beam_hypotheses.py:98) says light beats preferred dining, and [test_beam_hypotheses.py:166](/home/pakar/igor/remlab/services/planner-solver/tests/test_beam_hypotheses.py:166) asserts it.

That contradicts the declared zone order. T-98 solved “dresser often omitted” by promoting optional light, rather than by expressing optional storage coverage generically.

Mandatory media still precedes `light_missing` in `plan_key`, so the special term alone should not select a media-missing plan over a reachable media-valid plan. The observed all-`MEDIA_MISSING` regression is therefore more consistent with changed set selection/common geometry or finite search reachability than with a direct comparison-key reversal.

### The actual set-selection bias is outside `compose2.py`

`compose2.py` scores individual products; it does not choose the tour’s winning set.

The tour selector is [trial_demo.py:1126](/home/pakar/igor/remlab/tools/scout/trial_demo.py:1126). Its key is:

```python
(lower_band_distance, no_mesh_count, -placeable_count, gaps, index)
```

at [trial_demo.py:1135](/home/pakar/igor/remlab/tools/scout/trial_demo.py:1135). Thus one extra dresser directly makes a set more attractive.

`/demo` has the same raw-count preference at [flat215_demo.py:55](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:55) and [flat215_demo.py:873](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:873). However, `/demo` retries the next candidate after solver failure at [flat215_demo.py:1286](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1286). Tours select one set per style before solving and do not have equivalent cross-set fallback.

The tour also builds shared geometry from the largest SKU for every sufficiently common role at [trial_demo.py:216](/home/pakar/igor/remlab/tools/scout/trial_demo.py:216). Consequently, selecting different dresser-bearing sets can also change the sofa/media SKUs and inject the largest dresser into shared geometry. This explains why an apparently optional inventory addition can change all geometry/style outcomes.

### The placement chain is already mostly correct

The zoned solver executes media before storage at `ca7d70e5:services/planner-solver/planner/zones.py:1002-1021`, and applies a final media contract at [zones.py:219](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:219).

The model already has the correct failure representation: [models.py:226](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:226) distinguishes required `unplaced` from normal `skipped_optional`.

So the general solution is to preserve core-first search and rank optional coverage later—not add a dresser-specific rescue.

### The passport currently calls the dresser/light mandatory

The dresser and lamp are correctly modeled as carrier and dependent at [living.json:373](/home/pakar/igor/remlab/services/planner-solver/rules/room-templates/living.json:373), with `reject_composition` if the lamp cannot resolve.

But compact templates declare the entire light group required at [living.json:1083](/home/pakar/igor/remlab/services/planner-solver/rules/room-templates/living.json:1083), and their small-room levels explicitly alternate dresser/light and floor-lamp compositions at [living.json:1321](/home/pakar/igor/remlab/services/planner-solver/rules/room-templates/living.json:1321).

That conflicts with `zones.json`, where light is optional.

`room_templates.py` already provides most required mechanics:

- conditional/optional slots: [room_templates.py:651](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:651);
- dependent removal when an optional carrier disappears: [room_templates.py:671](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:671);
- level selection without missing optional slots: [room_templates.py:693](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:693).

No dresser-specific code belongs there.

### `trial_bundle.py` is not the selector

[trial_bundle.py:1773](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:1773) merely converts the completed scene to tour variants and turns “no shown variants” into a furniture failure. It amplifies the all-style failure into an empty room but does not choose sets or plans.

## 3. Risks and edge cases

- Lamp atomicity is incomplete today. `decor_roles=['лампа']` proves only that a lamp SKU exists, not that its actual model fits the chosen dresser. `dependent_decor` can still reject the lamp after the dresser has been accepted. If “dresser with a lamp” is strict, a dresser must be omitted when lamp preflight fails.
- Area bands are insufficient. A 16 m² room with many openings can fit less than a 13 m² rectangle; fit must remain geometry-driven.
- Common tour geometry takes maximum SKU dimensions across styles. Optional roles should not make the mandatory common geometry infeasible.
- Adding an item can change finite beam enumeration even when ranking is correct. A robust monotonic guarantee requires core-first search or isolating optional enrichment from core hypothesis generation.
- Kitchen-living and dining-room scenarios require dining. Ordinary living currently treats dining as preferred. The dresser must never override required dining.
- TV-over-fireplace and wall-unit media variants must still count as media before optional storage.
- Dresser without a resolvable lamp must not be counted as successful `light` coverage.
- “Table” is ambiguous: the coffee table is part of the seating atom; dining is scenario-dependent.

## 4. Alternatives

- Restrict dressers to 17–20 m² and above. Safe but area-based, not “where it fits.”
- On `MEDIA_MISSING`, retry without the dresser. Acceptable only if implemented as a generic optional-degradation pass for every optional slot—not as a tour/dresser patch.
- Penalize sets with more items. Also wrong: unplaceable extras should be neutral, while successfully placed extras may be beneficial.
- Keep T-98’s special light tier but move it after preferred coverage. Better than current behavior, but still hardcodes one optional capability instead of using the passport/status model.

## 5. Recommendation and minimal change set

1. On the `ca7d70e5` branch, keep only the 14–16 dresser SKU envelope in `composition.json`. Remove `instead_only_by_band` and remove dresser from the seating-exclusive group. Storage and seating should not be inventory substitutes.

2. Make composition core-first in `compose2.py`: base seating/table/media roles must be selected before optional storage can consume floor or wall budgets. A dresser may enter the bank only as an optional candidate paired with an eligible lamp.

3. In `living.json`, model `dresser + lamp` as one optional composite:

   - dresser is the carrier;
   - lamp remains a dependent with `reject_composition`;
   - the compact core levels remain valid without this group;
   - local light/storage must not be a required group unless product policy explicitly says so.

   `room_templates.py` needs no dresser special case. If stronger atomic inventory validation is needed, add generic support for required sellable dependents inside an optional atom.

4. Replace `light_missing`’s special position in both `plan_key` versions with generic realized capability coverage:

   - `storage` and resolved `light` included in `have`;
   - required coverage first;
   - preferred coverage next according to `zones.json`;
   - optional coverage after that;
   - dresser counts as light only when its lamp actually resolves.

5. Fix set selection in both tours and `/demo`:

   - remove raw `-placeable` from pre-solver ranking;
   - rank first by band, required-core completeness, required-role mesh readiness, gaps, then stable identity;
   - after solving, compare required outcome vectors;
   - only then compare realized preferred/optional capabilities;
   - inventory extras that remain unplaced are neutral.

   Tours should retry the next set of the same style on mandatory solver failure, matching `/demo`’s existing behavior.

6. Keep `passed_not_placed`/`skipped_optional` for an unplaced dresser. It is a normal outcome, not a room failure.

Tests should include:

- A deterministic 13 m² core, e.g. 325×400 cm, with sofa, coffee table, media carrier, rug, dresser, and lamp. Assert sofa/table/media remain placed, no `MEDIA_MISSING`, and dresser is either placed with its lamp or listed as skipped.
- The same 13 m² room with and without the optional atom; assert the required-outcome vector is identical or better after adding it.
- Openings on two walls and a narrow/elongated 13 m² case.
- A kitchen-living case where required dining beats dresser/light.
- A set-ranking test where two sets have identical core items and only one has an unplaceable dresser; the extra item must not affect pre-solver choice or final required score.
- A case where the dresser does fit; after equal required outcomes, the dresser-bearing plan wins optional coverage.
- Lamp-fit failure: dresser must not remain alone.
- Tour and `/demo` parity using the same room and bank.
- Existing 17–20 m² mixed-tour coverage to ensure the successful 4/5 placement does not regress.

The current targeted suites pass—55 tests—but they encode the disputed T-98 rule that optional light beats preferred dining, so passing them does not validate the desired policy.

## 6. Uncertainties

- The three failing tour inputs and generated `sets3` artifacts were not present, so I cannot prove which changed selected SKU or common geometry caused each `MEDIA_MISSING`.
- `ca7d70e5` is on `worktree-dresser-demo-1112` and is not an ancestor of current `main`; current files therefore do not contain its dresser changes.
- Owner priority between an ordinary living-room dining zone and dresser storage needs an explicit product decision. I recommend preserving the current declared order—dining before storage/light—unless deliberately changed in `zones.json`.
- If “lamp on it” permits showing the dresser when the lamp model is unavailable, the atomicity recommendation can be relaxed. The wording of the objective suggests it should not be.