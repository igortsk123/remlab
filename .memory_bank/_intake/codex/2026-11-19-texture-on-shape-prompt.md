You are an independent senior reviewer (3D reconstruction / texturing pipelines). Analyse independently; do not assume any proposed approach is right.

USER OBJECTIVE
remlab makes 3D furniture meshes from ONE product photo (shop catalog, white background, usually 3/4 front view) for a room planner and Cycles photo renders. The current production generator is Hunyuan3D 2.1 (shape + Hunyuan Paint) on Salad GPUs. We are trialling open generators on a fixed set of 30 products (plan `.memory_bank/plans/mesh-models-trial-01.md`). First result on a dresser with a leaf-pattern front: TRELLIS.2-4B gives accurate shape/proportions but the front pattern is wrong (all "scales" same orientation instead of alternating leaves) and wood is darker/browner; Hunyuan 2.1 gets pattern and colour right. TRELLIS.2 also adds a thin flat "floor plate" (42 % of triangles) that we cut by rule (`tools/scout/salad/trellis/mesh_clean.py`).

The owner proposes two hybrids:
 A) TRELLIS.2 shape + Pixal3D texture (Pixal3D = TencentARC, built on TRELLIS.2, pixel-aligned via MoGe camera estimate).
 B) TRELLIS.2 shape + projection of the ORIGINAL product photo onto the UV texture (visible texels from the photo, the rest from the model's own texture).

TECHNICAL QUESTIONS
1. For A and B: realistic quality, failure modes, and the concrete algorithm you would use (camera estimation, visibility, UV baking, seam blending, delighting of shadows/highlights baked in the photo, thin parts like legs, PBR channels other than baseColor).
2. Is there a better third option for "good shape + correct appearance" with open models — e.g. running Hunyuan3D-Paint 2.1 (or another open texturing model such as a multi-view diffusion painter) on the TRELLIS.2 geometry; or using Pixal3D as a whole instead of the hybrid? Compare.
3. How to measure fairly across variants (we have: silhouette IoU, ΔE00 on unlit baseColor, ΔL, frames at 10 views lit + clay). What metric would catch "pattern wrong but colour right"?
4. Our existing code to reuse: `tools/scout/salad/recolor_lp.py` (fits a camera to the photo by silhouette IoU, recolors existing meshes from the photo), `tools/scout/salad/hybrid_mask.py` (cut-out), `tools/scout/mesh_render.py` (UNLIT mode). Inspect them: are they a sound base for B, what is missing?
5. Second, separate question. Variant families in our catalog share ONE mesh; each colour variant gets a per-variant RGB multiplier `sku_scene.tint` (clamped 0.35…5.0) applied to the mesh texture. Recoloring the mesh to the representative's photo breaks light variants (multiplier hits the 5.0 ceiling); recoloring to the lightest variant breaks a dark representative (hits 0.35 floor). Families spanning >~5× in brightness cannot fit one multiplier. Options we see: split the family into several meshes by brightness cluster, a second texture/albedo per cluster, a different tint model (e.g. albedo replacement in a material slot instead of multiply), or hiding outliers. What would you do and why? Relevant code: `tools/scout/salad/recolor_variants_gate.py`, `tools/scout/mesh_color_check.py`, `tools/scout/flat215_demo.py` (family_colour_mismatch).

CONSTRAINTS
Open models only (no paid APIs). GPU work on Salad (4090 typical), cost matters (~$0.1–0.5 per product acceptable for a trial). CPU work on a 16-core VM is free. Output must be a single GLB with baseColor+metallicRoughness, ≤ ~1–2 MB light copy for web. No product IDs in code. Do not modify files.

Return: 1) conclusion per question; 2) evidence (file paths/symbols, papers/repos); 3) risks/edge cases; 4) alternatives; 5) recommendation and order of experiments; 6) uncertainties; 7) what evidence would change your mind. Be critical.
