You are an independent senior reviewer. Do not modify files. Inspect the repository directly.

USER OBJECTIVE: a buyer on a published tour page presses "Сделать фото" (render of the room). In 6 living rooms of tours the order fails with `bad_item` because the rug item has neither `sid` nor `msid` in the tour data, and in general the render order from a tour cannot resolve product cards at all (`render_snapshot.sku_index/_item` looks up by `sid`, while the public tour bundle never carries `sid` — `trial_bundle.NEVER_KEYS`).

FACTS:
- `tools/scout/trial_demo.py:public_row` (~804) writes `msid=None, mesh='not_needed'` for roles without a mesh (rug etc.).
- `/demo` rugs carry `sid` and `msid` = product key (`flat215_demo._msid`), so /demo orders work.
- `msid` is used on the page to tell "real mesh" (`lib/viewer3d/textile.ts:105`, rug swap feed in demo-feeds, `trial_bundle` ~1574 strips msid from rugs in feeds on purpose).
- App side mirror: `lib/trial/repo-render.ts:collectSkus`.

TECHNICAL QUESTION: which public product key should a tour bundle carry for EVERY item (including no-mesh roles) so the render order can resolve the product card, and how should `render_snapshot` + `repo-render.ts` resolve it?
Option A: new public field `sku.pid` = short hash of sid (non-reversible), allowed in PUBLIC_SKU_KEYS/SKU_KEYS; order resolves `sid or pid`; msid untouched.
Option B: put `msid = product key` on rugs as in /demo.

Return: conclusion; evidence (paths/symbols); risks (collisions, cache keys / scene_hash stability, price/cart integrity, leaking supplier ids, tours already published and their re-issue); alternatives; recommendation; what evidence would change it. Be critical and brief (≤ 60 lines).
