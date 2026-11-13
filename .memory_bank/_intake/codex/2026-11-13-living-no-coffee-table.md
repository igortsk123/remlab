You are an independent senior reviewer for the remlab repository (B2C furnishing: living-room "sets" = curated product bundles placed in 3D; RU market catalogue Gdeslon/divan.ru). Read-only: do not modify files.

USER OBJECTIVE
The owner asked: three living-room sets in the live bank have NO coffee table at all; what should we do? Owner's new rule (13.11): everything in the set list must be visible in 3D, and sets should look complete to a buyer.

FACTS (from worker reports, verify in repo where possible)
- Sets without a coffee table in the set itself: japandi `set-d6e76793`, loft `set-e23e105d`, neoclassic `set-6cf8beac` (live bank `tools/scout/sets3.json`, not in git in worktrees; builder code in `tools/scout/`).
- Earlier catalogue scan for a neoclassic coffee table (70–132 cm, in stock): 66 candidates; only one with style score ≥ 6.6 — Gatwick 99272:11608135805058655222 (score 8.1), mesh ready, but binding is `blocked: passport_dim_missing:d` (round table, passport has no depth). Next: Crocus Portman 92×92 (6.1), also `passport_dim_missing:d`. Then divan.ru Лори Орех 5.9, Лейтон 5.7, Саймон 5.2.
- Relevant docs: `.memory_bank/core/lr-checklist.md`, `core/lr-composition.md`, `core/stock-and-dims.md`, `core/styles.md`, `core/catalog.md`.

TECHNICAL QUESTION
1. Is a coffee table a mandatory core role for a living-room set here (check checklist/composition docs and code: lead/core roles, gates)? Should a set without it be published at all?
2. What is the right general fix (not a per-set patch)? Options include: (a) treat round tables' diameter as both width and depth in the passport/dims rule so `passport_dim_missing:d` stops blocking round tables; (b) lower the style-score threshold for core roles with a fallback order; (c) borrow from a neighbouring style; (d) drop/replace the set; (e) something else.
3. Risks of each (wrong dims → collisions, style dilution), and how to verify.

Return: conclusion; evidence with file paths/symbols; risks; alternatives; recommendation and why; uncertainties; what would change your mind. Be critical. Answer in Russian, concise.
