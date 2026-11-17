You are an independent senior interior-design + catalog engineer. Do not modify files. Answer in Russian, ≤ 900 words, facts with file paths, separate facts from assumptions; check norms on the web with sources.

USER OBJECTIVE (owner, 17.11): decide what a full furniture+decor SET should contain for each room type (living room, bedroom, kids
room, others we support) so that the room looks finished and realistic in 3D and in renders — rug, plants, small decor (books, vases,
trays, candles), lamps, textiles, art — and find the optimum at the intersection with what our catalog actually has.

FACTS: audit of 16 /demo sets (6 living, 10 bedrooms, 189 items): `.memory_bank/_intake/codex/2026-11-17-render-3d-audit.md`; no plants and no
small decor in any set; bedrooms have no rugs in some sets. Set composition rules / roles: find them (start from
`.memory_bank/core/lr-composition.md`, `core/lr-checklist.md`, `core/bedroom.md`, `core/styles.md`, `domain/living-room-checklist.md`,
`tools/scout/rules/**`, `tools/scout/dependent_decor.py`). Catalog: products table via code in `tools/scout/` (roles/categories, mesh
availability). Furniture meshes must not be invented; decor may be simplified.

QUESTIONS
1. Per room type: core / recommended / optional items with counts and size rules (what designers and stagers consider "finished").
2. Which of these our catalog has (roles/categories present, how many SKUs, with meshes or not) — exact queries/files you used; gaps.
3. Optimum: minimal additions to set rules that give the biggest realism gain, given catalog availability; what to represent procedurally
   (generic plant/books) vs real SKU (must be buyable, with price/ref link).
4. Risks: clutter, price of the set, placement collisions, phone performance, mesh generation cost.
5. Concrete first step with acceptance criteria.
