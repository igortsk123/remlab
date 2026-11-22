You are an independent senior reviewer (data pipelines, catalog consistency). Analyse independently; do not assume the proposed plan is right. Do not modify files.

USER OBJECTIVE
remlab builds furniture "tours" (3D apartment pages) from a catalog. The owner wants each product to carry ONE name everywhere, and wants this inconsistency to stay fixed: one product id, one name. He also asks why our product names change at all.

OBSERVED FACTS (from a worker's investigation; verify in code)
- One shop product (sid `112923_2281508011157666424`, bed) appears on a tour page under two names. The variant card says "Далти-П"; the swap feed says "Далти". Its public key `pid` is computed from sid only (`tools/scout/trial_bundle.py:661 pid_of`).
  - The variant item of a bedroom or hallway comes from the live table `room_catalog` via `_part_item` → `attach_goods` → `room_goods` (`trial_bundle.py:1766`, `:519`, `:529`).
  - The swap feeds come from the frozen /demo build `demo-data.json` (`tools/scout/demo_feeds.py:29`, `:159`; `trial_bundle.py:1625 feeds_for`, `:1548 goods_from_feeds`). Those feeds carry bank names (`sets-bedroom.json`).
  - `catalog_goods` prefers the BANK name over the catalog (`trial_bundle.py:487`).
- Names come from 4 places: `room_catalog`, `products`, banks (live and `.next`), and `demo-data.json`. Nothing deliberately rewrites product names. The one exception is a neutral role name ("Кровать 160 см · 224×176 см") for items without a product (`name_items` `:1106`, `_part_item` `:1766`).
- Scale: 15 of 26 201 sids with names have differing names.
  - 13 are living-room bank or demo against `products`. Some look like real renames ("Белый" → "Белый/Черный"). One looks like a different model under the same sid ("Ольен Мини" → "Этен-2 Мини").
  - 2 are bedroom bank against `room_catalog`.
- The render service validates orders against tour data (`tools/scout/render_snapshot.py pid_index`, `_item`). It now prefers the card of the room's own item (commit 81a17a27). The product name is not part of the frame hash (`_sku_inputs`).

WORKER'S PROPOSED PLAN (critique it)
1. A final pass in `trial_bundle` that collects {pid → name, name_en} from `variants[].items[].sku` and rewrites every card with that pid in `feeds`, `sofa_feed` and `decor`.
2. A guard: if a pid still has 2 names, the build is refused with `names_conflict`. Plus a nightly report-only scan of banks and catalogs for sids with differing names.
3. Tests in `tools/scout/tests/test_trial_bundle.py`.
4. Re-issue affected tours via `tools/floorplan/reissue.py`.

QUESTIONS
1. Which single source of truth for a product's name, and where should it be enforced? Options:
   - the variant card at bundle time;
   - always resolve the name live from the catalog by sid, with banks storing only sid;
   - refresh bank names on the nightly rebuild;
   - something else.
   Consider /demo, the living room (bank > products today), bedrooms and hallway (`room_catalog`), and products that left the feed.
2. Is "same sid, different model name" (e.g. "Ольен Мини" → "Этен-2 Мини") a sign the shop reused a sid for a different product? If so, a name fix would hide a wrong mesh, photo or price. How should that be detected and handled differently from a plain rename?
3. Is refusing the whole tour build on a name conflict right, or too harsh? Would unify-and-count be better?
4. What does the plan miss: `name_en`, the price and URL of the same stale copies, caches, other consumers of names (search, analytics, manager pages)?

Return:
1. conclusions;
2. evidence (file:line);
3. risks;
4. alternatives;
5. recommendation;
6. uncertainties.
Be critical.
