You are an independent senior engineer reviewing a texture pipeline design. Do NOT modify files. Answer in Russian, concise, with file:line evidence.

USER OBJECTIVE (owner of the product, voice 23.11, TG 1922, translated):
"The invisible side must be painted from the visible one. Make sure the two halves never differ. Usually an item has ONE colour pattern
that covers ~2/3 of the item; only other MATERIALS have other colours. The back of the item usually follows the main colour pattern.
Think through, per furniture type, how to paint each type."

CONTEXT
- Pipeline v3 for painting 3D furniture meshes (TRELLIS shape) from ONE catalogue photo. Canon: `.memory_bank/plans/paint-photo-fill-01.md`
  section «Как сейчас» (stages 01..08). Stage 03 = parts (`tools/assets/material_parts.py`, `tools/scout/rules/part-roles.json`),
  05 = delight, 06 = visible texels from the photo camera, 07 = fill invisible (`tools/scout/salad/trellis/` — tex_fill / ref_zone / own_panel,
  branch `t187/pipeline-1122` HEAD 86426296 is the latest code; main does not have it yet — inspect with `git show 86426296:<path>`),
  08 = material params (`tools/assets/material_stage.py`, `data/flat3d/material-recipes.json`).
- Report of the latest run: `~/remlab-logs/t187-1122/REPORT-p4-for-algor.md` (read it; absolute path /home/pakar/remlab-logs/...).
- Observed defect (director looked at the frame): wardrobe 112923_10887681585730015317 back after 07 is patchy: light left third, darker
  middle, flat dark patch at the bottom (drawer area), ragged boundary between them. Grey wardrobe = one material. Back of the sofa
  0160604609 is uniform but lighter than the front. Parts of stage 03 split one flat panel into several parts; each part gets its own tone.
  σL of filled back is 0.3–0.4 of photo σL (photo σL contains panel-to-panel tone differences, not only grain).
- Scale constraint: must be automatic for ~50k products and thousands of types/variants; CPU only (heavy-slot), ≤ ~2 min per item; no
  product IDs in code; numbers in `tools/scout/rules/*.json`.

QUESTIONS
1. Design a general rule "one material — one tone": how to group stage-03 parts / panels into MATERIAL groups automatically (signals
   available: photo a,b/L after delight, part roles from catalogue material channels, UltraTex draft, geometry), how to pick the group's
   tone and grain statistics, and how to paint invisible and visible areas of the group so no seam/halves appear (low-frequency
   equalisation? Poisson blend? keep photo high-frequency only?). What must NOT be equalised (real two-tone designs, contrasting fronts,
   cushions, shadows in recesses)?
2. Per type table (wardrobe/chest/TV-stand, sofa/armchair, bed, table, chair, lamp, shelving, decor/vase): main material and which
   parts follow it (back, underside, inner sides), which parts are other materials (legs, handles, fronts, glass, shade), defaults when
   the photo shows only the front.
3. How to detect when the rule is wrong for an item (two-tone item) — automatic check and fallback.
4. Acceptance metric for the owner's "halves never differ": what to measure per material group (ΔE of low-frequency tone visible vs filled,
   σ of panel medians inside a group, boundary step), thresholds to start with.
5. Where in the code this belongs (stage 07 vs a new step between 06 and 07), what to reuse, risks.
Be critical: say where the owner's heuristic fails and what evidence would change your recommendation.
