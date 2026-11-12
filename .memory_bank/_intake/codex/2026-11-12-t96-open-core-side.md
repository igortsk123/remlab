You are an independent senior software-engineering reviewer. Do not modify, create, or delete files.

USER OBJECTIVE
Buyers upload a flat plan; the tour pipeline furnishes each bedroom (`tools/scout/trial_bedroom.py`) with the shared bedroom
solver (`services/planner-solver/planner/bedroom.py`). One rule set must serve both the /demo bank and uploaded plans.

OBSERVED FACTS (repository: worktree `.claude/worktrees/bed-memo-1112`, branch `worktree-bed-memo-1112`; logs are facts, not conclusions)
- `trial_bedroom.build_room` (≈ line 624) gives the solver only the core RECTANGLE of the room (`cand['rect']`) with openings from
  `trial_room.solver_openings`. Residues (niches/recesses) touching the core become a pseudo-door `{"kind":"door","swing_cm":0}`
  at the junction ("junction").
- Plan iT0XpK2WcZbtEUzf1ybqHw, bedroom-1: core rect [15,75,405,545] (390×470). Along the north side of the core the real room
  contour is at y=35 (a 40 cm band near the window that is neither core nor a residue). The solver treats y=75 as a wall.
- When the solver puts the bed on the west wall, wardrobe and dresser are pushed with their backs against the core's north
  side (y=75). The post-check `trial_bedroom.back_off_wall` (≈ line 647, uses `room_edge` = boundary of core ∪ residues, and
  BACK_GAP_CM=12, BACK_MIN_SHARE=0.8) measures 40 cm to the real contour → `back_off_wall` problem → `fit_extras` keeps the
  bare kit → wardrobe/dresser reported `no_space`. Which wall the bed takes depends on bed size, so different styles lose
  storage. Data: `~/remlab-logs/t47-1112/1832-batch2/backs.out`.
- Related, just changed in this branch: junction pseudo-doors (swing 0) now reserve a 20 cm strip (`JUNCTION_STRIP_CM` in
  `planner/bedroom.py:_Statics`) instead of the 76 cm door-front strip, so nothing stands flush against a niche opening.

TECHNICAL QUESTION
What is the right general fix so the solver does not place back-to-wall items (bed, wardrobe, dresser) against a core side
that is not a real wall (distance to the true room contour > BACK_GAP_CM)? Candidates that were proposed (evaluate
independently, add others):
 (a) `build_room` passes those "open" core spans to the solver as something "do not put a back here" — a new opening kind,
     a flag on Room, or reusing the swing-0 junction pseudo-door. Note that a door-kind opening also participates in route
     checks (`planner/bedroom_checks.py`: entrance → bed route) and in `validate.check_openings`.
 (b) `_solve_kit` (≈ line 697) retries with a mirrored room when the only problems are `back_off_wall`.
 (c) building the core so it includes the band (core geometry), or making the solver aware of the true contour.
For each: correctness, which call sites/contracts change (solver Room/Opening model, validate, bedroom_checks routes,
/demo bank builder `tools/scout/compose_bedroom.py`), regression risk for the 14 T-68 bedroom sheets
(`tools/scout/bedroom_t6_schemes.py`), runtime cost (per-room time budget ~30 s, solver ~0.5–1.4 s per call).

Return: 1) conclusion; 2) evidence with file paths/symbols; 3) risks/edge cases; 4) alternatives; 5) recommendation and why;
6) uncertainties; 7) what evidence would change your conclusion. Be critical; look for reasons the obvious fix is wrong.
Answer in Russian, concisely (≤ 60 lines).
