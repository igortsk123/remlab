You are an independent senior computer-vision engineer. Do not modify, create or delete files.

USER OBJECTIVE
We cut furniture products out of catalog photos (1295 products, many shot on a pure white studio background) to feed 3D-mesh generation. The owner wants the cleanest possible cutout with the minimum leftover background, as ONE general rule for all products (no per-product special cases, no product IDs in code).

CURRENT CHAIN (code in /home/pakar/igor/remlab/.claude/worktrees/cutredo-1119/tools/scout — look for components.py, fg_estimate.py, defringe / edge_halo / clean_islands / clean_bg_like_specks / close_edge_gaps / fill_body_holes, hybrid_mask, cutout_page30.py, salad preprocess _cut_chain):
BiRefNet (mask only) -> hybrid_mask -> components.clean -> fill_holes -> defringe (edge_halo, clean_islands, refine_edges = port of BiRefNet refine_foreground) -> clean_bg_like_specks -> close_edge_gaps -> fill_body_holes.
Data of a full run: /home/pakar/remlab-logs/t104-1119/1119-a/ (photos/<sha>.*, masks/<sha>.png = raw BiRefNet mask, cut/<sha>.png = final RGBA, products.json, chain.jsonl).

TWO OBSERVED DEFECTS
A) Bed, sha 6929b740fda33fab24a08b1a142838560f7ff2a1b6a8d6c981606261f8c2348f: white headboard panel (pixel value ~230,230,230) on pure white background (255,255,255) is missing ALREADY in the raw BiRefNet mask; the final cut keeps only pillows/frame plus a thin light halo above the pillows. 8.7 % of the photo is outside the mask yet differs from 255 by >10.
B) Floor lamp, sha 3efe9353a56c29229980b2eb27c195aff9be61ca8d1cfc967b4db20d23b19255: raw BiRefNet mask is smooth and slightly fat around thin metal rods; the final cut shows white "beads"/jagged white specks along the thin rods and around the base — background pixels left inside the mask band.

QUESTIONS (answer with evidence: code file:line, measurements you can compute read-only from the run folder with python/numpy if available, and public sources with links)
1. Root cause of each defect: which step of the chain creates/keeps it (mask model vs our post-steps)?
2. Is a "known studio background" rule sound as a general method: detect photos whose border is uniform near-white; flood-fill from the border over near-background pixels; product = not reached; combine with BiRefNet (union for missed bodies like A, subtraction of reached pure-background pixels for B)? Thresholds, how to handle soft drop shadows on the floor, white products whose highlights reach 255 and touch the border region (leaks), JPEG noise, gradient/vignetted backgrounds, products touching the frame edge.
3. Soft edges: difference matting against known background colour vs ViTMatte (or other trimap matting) with a trimap from (2) — which gives cleaner thin rods and anti-aliased edges on CPU, licence (commercial use), speed per 1000 px image.
4. Alternatives worth considering (second mask model such as SAM2 with a box prompt, BiRefNet variants, InSPyReNet, BEN2 — note: our earlier test found BiRefNet-HR 5–9x slower with no gain, BEN2 leaves shadow trails, InSPyReNet tears edges, RMBG licence not acceptable).
5. How to measure on all 1295 products objectively (metrics for leftover background and lost body) and which subsets to look at by eye.

Return: 1) conclusion; 2) evidence; 3) recommended rule with concrete thresholds; 4) risks/edge cases; 5) alternatives; 6) uncertainties; 7) what evidence would change your conclusion. Be critical; look for reasons the obvious solution could be wrong.
