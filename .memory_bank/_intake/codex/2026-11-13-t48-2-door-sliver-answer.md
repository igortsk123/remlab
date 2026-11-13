## Conclusion

This is not primarily an `INNER_ARC` or 3D bug. `_analyze` invents multiple segmentation closures, then conflates every surviving inner closure with a door. A nearby real door glyph is subsequently reusable as evidence for false candidates.

## Evidence

- Candidate strips originate in `bridge_parts`; `xy_cut` only partitions separate plans and does not create these doors: [fpcore.py:644](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/fpcore.py:644), [bench.py:1810](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1810).
- At 63.77 ppm, the 1.7 m “small gap” pass includes all three candidates. It bridges wall ends, measures frame/arc evidence, and writes accepted pixels into `keep`: [bench.py:965](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:965), [bench.py:1060](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1060).
- Upper 75.3 cm kitchen door (`glaze=.09`) follows the arc-claim branch at lines 1091–94.
- Lower 80.0 cm duplicate has `glaze=.80`; it follows the frame branch, enters `keep_other`, and never becomes an arc claim: [bench.py:1086](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1086). Therefore `own_arcs` cannot drop it regardless of share threshold.
- The 157.2 cm candidate has `glaze=0`, so it is accepted as an arc claim. `door_evidence` searches both sides, shifted hinges, and radii 0.5–1.05× candidate width; a wide false span can borrow the kitchen or WC glyph: [fpcore.py:1545](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/fpcore.py:1545).
- `own_arcs` drops only when at least 50% of the exact sampled evidence-pixel set was already owned: [bench.py:897](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:897). Those sets are 5×5 neighborhoods around the winning fit, so two fits to nearby graphics can overlap below 50%: [fpcore.py:1590](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/fpcore.py:1590).
- The saved artifacts do not serialize claim sets, so the exact 157 cm overlap fraction is unknowable. It was not a `deep_door` or `TWO_ARCS` product; the latter runs only for exterior gaps: [bench.py:1382](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1382).
- After segmentation, every non-notch inner gap is unconditionally typed `door`: [bench.py:1299](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1299), [bench.py:1334](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1334).
- `INNER_ARC` then remeasures and annotates those already-created doors; it does not validate ownership or create them: [bench.py:1392](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:1392).
- Export is lossless pass-through into model/result: [bench.py:2443](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/bench.py:2443), [pipeline.py:791](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/pipeline.py:791). `arc=true`, 157 cm therefore becomes a real double door in 3D: [trial_room.py:493](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/scout/trial_room.py:493).

## Recommendation

Fix this inside `bench._analyze`, before `final`/room segmentation—not in `panel_result` or 3D:

1. Represent closure purpose separately from opening semantics: `wall closure`, `door closure`, `window/frame`.
2. Assign each detected door glyph globally to at most one candidate using hinge/radius/orientation fit, not only evidence-pixel overlap.
3. For parallel candidates with strong span overlap and normal separation within wall thickness plus the enclosed narrow strip:
   - retain the glyph owner;
   - discard the non-owner when raw pixels do not support a wall;
   - retain it as solid wall, without an opening record, when raw wall support exists—as above the WC.

This removes the lower 80 cm closure while preserving the WC wall, instead of merely hiding records.

## Alternatives and risks

- A model-level “merge nearby doors” is insufficient: duplicate header bands and incorrect room segmentation already exist. The exported model also lacks opening axis.
- Globally absorbing thin slivers is dangerous: vestibules, en-suites and cupboards can genuinely be narrow.
- Lowering `OWN_SHARE` may catch the 157 cm claim, but cannot affect the `.80` `keep_other` duplicate and risks adjacent genuine doors.
- Existing aRQ output contains several inner-door centers within roughly 0.6 m around corners; proximity without parallel-axis, wall-support and independent-glyph checks will merge real doors.
- Back-to-back vestibule doors must survive when two independent glyphs exist. A paired-leaf door should remain one record with `leaves=2`.

## What would change my view

Serialize candidate origin, axes/depth, winning glyph parameters, evidence-pixel overlap matrix, and raw wall support. If the 157 cm candidate owns a distinct, geometrically correct local glyph, the proposed one-glyph rule is insufficient. Add golden positional/type assertions for all five sheets plus synthetic vestibule, en-suite, cupboard and back-to-back-door cases; the current harness mainly compares per-room counts within 30 cm and can miss compensating errors: [regress.py:39](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/regress.py:39), [regress.py:216](/home/pakar/igor/remlab/.claude/worktrees/door-pairs-1113/tools/floorplan/regress.py:216).