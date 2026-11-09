You are an independent reviewer for the remlab repo (read-only). Answer in Russian, concise, ranked, with file:line evidence.

Context: plan `.memory_bank/plans/agent-trial-08-demo-as-template.md` (agent trial: an estate agent uploads a floor plan → the result page is
exactly our `/demo` page `tools/scout/flat215-demo/index.html` rendered from per-job data `demo-data.json`). The owner just added a requirement
(task «П. Два языка»): the trial result page AND the upload/waiting pages (`app/try/**`, `components/trial/**`) must work in Russian and English,
like the live `/demo` (which has a «Русский · English» switch). Not yet implemented in branches: `worktree-demo-template` (page),
`worktree-trial-bundle` (`tools/scout/trial_bundle.py`, data), `worktree-trial-pages` (form/waiting), `worktree-trial-living`, `worktree-trial-bedrooms-all`.

Questions:
1. How does the live `/demo` switch language today (mechanism, where strings live, how room/role names and product names are localised)?
   Cite `index.html` lines and any data fields in `demo-data.json` / `tools/scout/flat215_demo.py`.
2. What must each branch/stage do so the trial page is fully bilingual (new strings: «мебель подбирается», «нет подходящих товаров согласно
   действующим шаблонам», «не обставляется», scale-not-verified badge, «приближённая форма», two links, quiz)? Where must room names from
   floor-plan recognition (English labels from UK plans, Russian from RU plans) be translated — data builder or page?
3. Does the Next.js part (`app/try/**`) have any i18n mechanism already (e.g. landing `/test/landing` EN/RU, other pages)? Recommend the
   smallest consistent approach.
4. Risks/gaps this adds to the plan order (merge order: data → page → living → bedrooms), and whether anything already merged contradicts it.
Keep the answer under ~1200 words.
