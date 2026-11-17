You are an independent senior engineer. Do not modify files. Answer in Russian, ≤ 600 words, facts with file paths.

Critique the plan `.memory_bank/plans/photo-tariff-mass-01.md` (cheap photo tariff "mass" for tour auto-photos, order class `auto`).
Probe code is on branch `worktree-sd-probe-1116` (worktree `.claude/worktrees/sd-probe-1116/tools/scout/sd_probe/`: `cheap.py`,
`consistency.py`). Production path: `tools/scout/draft_render.py` (realistic branch ~3781–3900), `tools/scout/improve_mode.py`
(`build_from_views`, `frames_key`), `tools/scout/draft_trial.py` (class auto), `tools/scout/rules/tour-auto-photos.json`,
`lib/trial/auto-photos-*.ts`.

Questions:
1. Holes in the plan: where the tariff must be threaded so that cache/single-flight/cost logs/photo-speed stay correct; whether the
   browser payload of a tour auto-photo actually carries room geometry (w, d, openings) and cameras (x, y, rot, fov) that
   `consistency.py` needs — if not, the cheapest correct source.
2. Is "tariff chosen by order class in draft_trial.py" the right contract, vs. a field in the queue row / rules json read by the app?
3. Risks: regressions of the standard path, the 3-image vs 2-image prompt numbering (IMAGE 2/3), paid_gate, band check.
4. Minimal test set that proves standard is byte-identical and mass is correct.
