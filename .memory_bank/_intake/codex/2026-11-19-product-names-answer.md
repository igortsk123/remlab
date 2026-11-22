## 1. Conclusions

The worker’s plan addresses the visible symptom but is not a safe catalog-consistency design.

The right source of truth is neither the variant card nor a bank. It should be one canonical, versioned offer record per product identity, resolved once when `/demo` or a tour bundle is built. Banks should retain selection/layout and mesh-binding information, but not act as an authority for names or other commercial fields.

The current inconsistency occurs because the same `sid` is copied at different times into several denormalized snapshots:

- `products` and `room_catalog` are overwritten by later feeds.
- Banks retain older names.
- `/demo/demo-data.json` freezes bank/feed data again.
- Tours mix fresh room catalog cards with that frozen `/demo` data.
- `pid` nevertheless asserts that all those copies are the same product because it hashes only `sid`.

A final normalization pass is useful as an output invariant, but `variants[].items[].sku` must not be its authority. A variant can be neutral, unavailable, stale, absent, or carry an incorrect asset binding.

“Same SID, different model name” is a drift signal, not proof of SID reuse. It must be classified using image, URL/article, dimensions, category/role and mesh binding. If reuse is confirmed, the current `pid_of(sid)` scheme is invalid: the new product needs a new identity generation and therefore a new `pid`.

Raw source disagreements should be unified-and-counted when deterministic. A post-normalization conflict should fail publication because it indicates a code defect. Suspected identity reuse should quarantine the product, not normally reject an unrelated whole tour.

## 2. Evidence

### Source mixing is real

- Living goods explicitly prefer the bank for `name`, URL and shop, while only price is refreshed from `catalog_media`: [trial_bundle.py:473](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:473), especially [trial_bundle.py:483](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:483).
- Bedroom/hall goods instead read current `room_catalog` and use its name, price, URL and shop: [trial_bundle.py:519](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:519).
- The tour swap pool is loaded from the already-built `/demo/demo-data.json`: [demo_feeds.py:29](/home/pakar/igor/remlab/tools/scout/demo_feeds.py:29), [demo_feeds.py:35](/home/pakar/igor/remlab/tools/scout/demo_feeds.py:35).
- Feed rows receive their `pid` from the hidden `sid`: [trial_bundle.py:1657](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:1657).
- `pid` is only a hash of normalized `sid`; there is no product-generation component: [trial_bundle.py:661](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:661).

The concrete Далти evidence is present in the repository:

- Live bedroom bank: `Далти`: [sets-bedroom.json:9380](/home/pakar/igor/remlab/tools/scout/sets-bedroom.json:9380).
- Candidate bank: `Далти-П`, with the same SID, dimensions, image and URL: [sets-bedroom.next.json:9489](/home/pakar/igor/remlab/tools/scout/sets-bedroom.next.json:9489).

That particular case looks like a plain rename, not reuse.

### Why names change

Both live catalogs overwrite the current name when a new accepted feed arrives:

- `products.name = excluded.name`: [load3.py:548](/home/pakar/igor/remlab/tools/scout/load3.py:548).
- `room_catalog.name = excluded.name`: [room_catalog.py:391](/home/pakar/igor/remlab/tools/scout/room_catalog.py:391).

But bank refresh deliberately synchronizes image, URL, shop and dimensions without synchronizing `name`: [catalog_media.py:149](/home/pakar/igor/remlab/tools/scout/catalog_media.py:149). Consequently a legitimate upstream rename changes the catalog while frozen copies retain the earlier name.

There is no general deliberate name rewriter in the bundle. Neutral names are applied only when no catalog product is attached: [trial_bundle.py:1106](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:1106), [trial_bundle.py:1754](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:1754).

This also makes the proposed “variant is authoritative” rule unsafe: `_part_item` can retain a `pid` while its displayed name remains a neutral role label because the product is unavailable. Such a neutral label could then overwrite a real feed name.

### The render guard is narrower than stated

`pid_index` says that differing name or image should make a PID ambiguous, but the implementation compares only `name`: [render_snapshot.py:88](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:88), [render_snapshot.py:100](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:100).

Therefore two cards with the same `pid` and name but different images can still pass the index. Tests cover differing names, not a same-name/different-image identity conflict: [render_snapshot.py:509](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:509).

The product name is indeed absent from render inputs; image and mesh hashes are included instead: [render_snapshot.py:177](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:177). That is correct for a plain rename, but not sufficient when an external SID has been reused.

### Names are used as identity, not only display text

Several client paths join or group products by name:

- Match a shot-list row back to an item: [index.html:8444](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:8444).
- Resolve color family/current color: [index.html:8610](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:8610).
- Find the group of matching chairs during replacement: [index.html:9375](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:9375).
- Match a procedural item to its base item for render requests: [index.html:12180](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:12180).
- Manager-link events include up to ten product names: [index.html:12883](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:12883).
- The manager-side allow-list caches `/demo` names for five minutes: [demo-data.ts:34](/home/pakar/igor/remlab/lib/partners/demo-data.ts:34).

More seriously, replacement code copies `sid` but not `pid`: [index.html:9355](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:9355), [index.html:9390](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:9390). Tour feeds expose `pid`, not `sid`, so a tour swap can lose its product identity and fall back to name/ref matching. The proposed plan does not address this.

### `name_en` and name-derived semantics

`name_en` is derived from the Russian name; a manual translation is accepted only if its stored Russian name still matches: [names_en.py:201](/home/pakar/igor/remlab/tools/scout/names_en.py:201). Updating only one language can therefore create another inconsistency.

The Russian name also influences:

- Package quantity: [flat215_demo.py:150](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:150).
- Mesh/color eligibility and `unfit` filtering: [flat215_demo.py:1132](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1132).
- Suspended-item detection and package count written into feed rows: [flat215_demo.py:1152](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1152).

A final label rewrite occurs too late to recompute those derived decisions.

## 3. Risks in the proposed plan

- It can conceal SID reuse by placing a current name on an old mesh, image, dimensions or URL.
- It copies only names while the same stale cards also carry price, URL, shop, image and possibly dimensions.
- A product that exists only in decor or a swap feed has no variant-card authority.
- A variant with an unavailable product may provide a neutral role label as the supposed canonical name.
- Multiple variants can provide different candidate names; traversal order becomes an undocumented precedence rule.
- `name_en`, `colour_en` and `colour_ru` can cease to describe the selected Russian name.
- Name-derived `pack`, `hung`, family and eligibility decisions remain based on the old name.
- Hard refusal on every raw disagreement makes a minor upstream rename capable of blocking an otherwise valid apartment.
- Immediate mass reissue could silently relabel or relink tours whose product identity has not yet been classified.
- Existing browser collections, saved edits, manager events and rendered/product snapshots can retain old names even after bundle reissue.

## 4. Alternatives

### Variant-card authority

Reject as the primary design. It is acceptable only as a last-resort display fallback for the installed item.

### Resolve live on every page request

This gives freshness but harms reproducibility and availability. A temporary catalog outage would change an existing tour, and price/name/image could come from different catalog moments.

### Refresh all bank names nightly

A useful short-term mitigation, but still leaves multiple authorities and timing races across live bank, `.next`, `/demo`, tours and archived products. It also does not solve SID reuse.

### Canonical product projection at build time

Recommended:

- Maintain one canonical offer record keyed by an internal product identity.
- Living-room eligibility may still come from `products`; bedroom/hall eligibility may come from `room_catalog`, but identity and commercial card resolution should be shared.
- Resolve all SIDs once at a consistent catalog snapshot during `/demo` or tour build.
- Materialize the same complete card into every occurrence.
- Banks store SID, layout/selection metadata and explicit mesh binding, not authoritative commerce labels.
- A product that left the feed uses the last accepted archived card marked unavailable and is excluded from swap feeds. If no trustworthy archived card exists, show a neutral unavailable item without price or shop link.

## 5. Recommendation

1. Before reissuing anything, classify the reported conflicts.

   - Plain rename: stable URL/article, image, dimensions, role and mesh binding.
   - Suspected reuse: changed model tokens plus independent changes in image, URL/article, category/role, dimensions or mesh.
   - The `Ольен Мини → Этен-2 Мини` name alone is insufficient. The repository’s `Этен-2` record still points to a URL containing `olen-mini`, which leans toward a merchant rename rather than proven reuse: [sets2.json:6011](/home/pakar/igor/remlab/tools/scout/sets2.json:6011).

2. Add identity history at ingestion, before current rows are overwritten.

   Store old/new name, canonical URL, article, image hashes or perceptual hash, dimensions, role/category and mesh binding. The existing hash comparison only reports aggregate changes and then overwrites the prior values: [load3.py:537](/home/pakar/igor/remlab/tools/scout/load3.py:537), [load3.py:625](/home/pakar/igor/remlab/tools/scout/load3.py:625).

3. Introduce an internal identity generation.

   For example, `product_uid = source + sid + generation`. Keep the same generation for a verified rename; increment it for confirmed reuse. Future public IDs should hash `product_uid`, not bare SID.

4. Resolve a canonical full card once per build.

   Include `name`, regenerated `name_en`/colors, price and price date/basis, URL, shop and image. Keep scene binding—mesh, scene dimensions and placement—separate. Never repair a suspected identity conflict by copying only the name.

5. Use two different guards.

   - Raw-source disagreement: resolve deterministically and increment metrics.
   - Final bundle invariant: one `product_uid/pid` must have one complete canonical card; failure here should block publication as an implementation defect.
   - Suspected reuse: quarantine only that product. Remove it from swap feeds; hold or degrade the affected room if it is already installed. Do not normally reject unrelated rooms.

6. Replace name-based joins in the client with `pid`/`sid`, and ensure swaps copy `pid`. This is required for the “one product id, one name” rule to remain stable rather than merely look stable.

7. Publish `/demo`, allow cache expiry/invalidation, then dry-run reissue.

   Reissue only tours containing verified plain renames first. Tours containing unresolved identity drift should remain on hold. Tour versions already use revalidation and ETags, but `/demo` name validation has a five-minute process cache, and frozen tour versions only change after a new bundle is published.

The tests should extend beyond `test_trial_bundle.py`: include `render_snapshot`, client swap identity, same-name/different-image conflicts, unavailable products, decor-only products, `name_en` regeneration and reissue behavior.

## 6. Uncertainties

- I verified the code paths and the concrete Далти live/next bank difference. I could not independently reproduce the reported `15 / 26,201` database census because the repository environment denied access to the Docker database socket. That count remains an unverified worker measurement.
- The repository does not retain enough trustworthy per-import history to determine whether every model-name change is a rename or SID reuse.
- The business policy for old tours is not explicit: “always show the current product name” and “preserve exactly what was offered when the tour was built” are different requirements. The recommendation assumes current commercial data plus explicit `unavailable/as_of`, while preserving the original scene binding.
- I verified manager-event and UI consumers of names. I did not find a separate product-search index in the inspected scope; any external analytics, warehouse or manager system should still be audited before rollout.