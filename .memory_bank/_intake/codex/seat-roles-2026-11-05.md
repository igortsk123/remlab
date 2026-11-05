You are an independent senior reviewer. Read-only. Do not modify files.

OBJECTIVE: fix wrong catalog roles in the living-room catalog of remlab (poufs/benches/ottomans, modular-sofa sections, beds and stools that are labelled "диван"/"кресло"), with one general rule, then apply to DB safely, without breaking the live demo bank.

FACTS (from a worker's report; verify in code):
- Role = products.cat_role, written by tools/scout/load3.py:assign from tools/scout/category_map.classify (shop branch → role; name checked only for MIXED branches). Mixed branches (tvoydom «Мягкая мебель», mnogomebeli «Кресла»/«Диваны», divan.ru «Бескаркасная мебель») put poufs, ottomans, beds and modular sections into диван/кресло.
- Proposed rule: commit 548c4615 on branch worktree-roles-53 (`git show 548c4615`): category_map.seat_role, applied only to диван/кресло; first type-word in the name decides; пуф/банкетка/оттоманка → «пуф»; кровать → no role; standalone «Модуль …» section without диван/кресло/софа word → no role.
- Shadow over whole catalog (tools/scout/seat_role_shadow.py): 330 of 4639 rows change (диван→пуф 100, кресло→пуф 13, диван→no role 217 incl. 208 module sections, 9 beds); 0 false positives found by eye. Not caught: 20 «Топпер для дивана», 3 «Табурет Glasar».
- Recomputed living bank on DB copies (compose2 --style --bands all): 115 of 126 sets change composition, mostly because compose2.tier_band takes price percentiles over the whole role pool.
- Live bank sets3.json is written only by bank_refresh behind gates (bank_prepare/bank_promote, ≤25% replacement) — see tools/scout/refresh_daily.sh around bank_prepare/bank_promote/bank_refresh, and heal.
- tools/scout/mesh_queue.py ~389-405: re-upsert of demand never updates `role` → 243 rows with role ≠ cat_role.
- Apply plan: merge code first (nightly load3 would otherwise revert), then SQL via tools/ops/db-migrate-safe.sh (full dump, one transaction, check, rollback). Worker found db-migrate-safe.sh:sql_scan misses `update products p set` (alias) → would dump schema only.

QUESTIONS:
1. Is the rule correct and general? Edge cases it gets wrong (e.g., «Диван-кровать», «Пуф-трансформер в кровать», «Кресло-мешок», «Оттоманка» as a sofa type, «Банкетка-диван», «Модуль угловой дивана …»)? Is "module section → no role" right vs. a new role?
2. What will happen to the LIVE bank and live demo on the next nights after merge + SQL (heal, bank_prepare/promote, demo_band, flat215_demo)? Could sets containing now-roleless items be broken/emptied? Is the 115/126 churn real for the live bank or only for a fresh full rebuild?
3. mesh_queue role refresh on re-upsert: safe? Side effects on mesh pipeline (queues keyed by role, budgets)?
4. Toppers → no role, stools → «стул»: right?
5. db-migrate-safe.sh sql_scan alias bug: confirm and suggest a minimal fix.
Return: conclusion, evidence (file:line), risks, alternatives, recommendation, uncertainties. Russian, concise.
