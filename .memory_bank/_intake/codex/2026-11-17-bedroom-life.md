You are an independent senior interior-design + catalog engineer. Do not modify files. Answer in Russian, ≤ 700 words, facts with file paths, separate facts from assumptions; norms with web sources.

OBJECTIVE (owner 17.11): bedrooms must look lived-in: bedside table lamps and wall sconces (бра), all via the conveyor (bank rules →
/demo → tours). Critique the draft plan `.memory_bank/plans/bedroom-life-01.md` (read it and the files it cites:
`tools/scout/rules/bedroom-composition.json`, `tools/scout/compose_bedroom.py`, `tools/scout/trial_bedroom.py`, `tools/scout/category-roles.json`,
`tools/scout/category_map.py`, audit `.memory_bank/_intake/codex/2026-11-17-render-3d-audit.md`).

QUESTIONS
1. Why do some /demo bedrooms lack bedside lamps although the rule has decor.лампа? Find the mechanism in code.
2. Sconce (бра) role: how the catalog classifies it, how many usable SKUs (style, in stock, price, photo, mesh) — exact query; why 12.11 counted 1.
3. Rule design: when lamp vs sconce vs both; mounting height and offset from headboard (norms with sources); symmetry; conflicts
   with wall art above bed and with curtains/window; placement in the solver (wall item) — which existing mechanism to reuse.
4. Risks (clutter, price, mesh cost, tours re-issue) and the minimal first step with acceptance criteria.
