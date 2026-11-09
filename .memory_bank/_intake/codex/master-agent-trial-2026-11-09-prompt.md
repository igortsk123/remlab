Review the WHOLE meta-plan against the actual code. Repo: remlab (read-only). The owner asked for this one check to replace several smaller ones. Up to 90 lines, findings ranked by severity, each with file:line and a concrete correction. No praise.

Meta-plan: `.memory_bank/plans/MASTER-agent-trial.md`. Goal: an estate agent uploads a photo or PDF of a floor plan and, automatically, gets the same page as our `/demo` built for that plan: walls → 3D → layout → real products → AI images, with two links, in about 3 minutes.

Subplans and work in flight (also inspect these branches with `git show` / `git diff main...<branch>`):
- `.memory_bank/plans/floorplan-raster-bench-01.md` — branch `worktree-floorplan-bench`
- `.memory_bank/plans/agent-trial-01-upload-grey-tour.md` — in main, pages on branch `worktree-trial-pages` (the grey tour there is being dropped)
- `.memory_bank/plans/agent-trial-03-living.md` — branch `worktree-trial-living`
- `.memory_bank/plans/agent-trial-08-demo-as-template.md` and your earlier answer `.memory_bank/_intake/codex/agent-trial-08-2026-11-09-answer.md` — branches `worktree-demo-template`, `worktree-trial-bundle`, in progress
- Hero photo: `tools/scout/trial_hero.py`, plan not written. End-to-end meter: `tools/ops/trial_e2e.py`. Worker: `tools/floorplan/pipeline.py`, unit `remlab-trial-worker`.

Fixed owner decisions, do not argue: `/demo` is the template, no separate viewer; empty rooms with spinner, then furniture appears with an animation; floors go into `/demo`; UK bedrooms later; products shown as British without shop names; D–G reference answers not used for tuning; automatic conveyor, no manual steps.

Check:
1. Does the chain actually connect end to end? For each hand-off (upload → job → worker → walls → scene → furniture → bundle → page → photo), name the exact function or field on each side and any mismatch, missing step, or manual step.
2. Which critical path items are missing from every plan?
3. Failure handling: a stage fails, worker dies, partial results, retries, double publication.
4. Is the 3-minute target achievable given the measured stage times (walls: A 38 s, B 23, D 34, F 75, E 200, G 254, C 465)? What must change, what should the promise become?
5. Conflicts between parallel branches: the same files, contracts or data formats changing under each other, and the merge order you recommend.
6. Risks to live `/demo` and production: nightly publish, shared DEV capacity, money paths.
7. Security and retention of uploaded plans.
8. What to cut or reorder to reach the owner's acceptance soonest: he uploads his own photo and gets a furnished demo without help.

Mark anything you could not verify as unverified.
