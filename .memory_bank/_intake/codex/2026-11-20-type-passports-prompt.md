You are an independent senior engineer and visual reviewer. Do not modify files.

OWNER OBJECTIVE (voice, 20.11): rules PER PRODUCT TYPE (комод, шкаф, тумба, люстра…) for two conveyor steps, so fixes are systemic, not per product, at the scale of tens of thousands of products. Particular rules per type first, then general rules derived from them. The conveyor must handle a NEW type automatically (a trigger creates the type's rules/prompt; otherwise new types will be cut badly).

STEPS
(A) CUTOUT — removing the shop-photo background before 3D generation (BiRefNet mask, no text prompt, + our post-processing chain). Worker code: `.claude/worktrees/cutout-redo-104`.
(B) PAINTING the 3D mesh from ONE shop photo (StableGen, 8 cameras, Qwen-Image-Edit; captions per camera angle in `.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_views.py`). Known: giving the shop photo to views whose silhouette matches the photo copies the front onto the back; short caption «plain side of the same …» fixes sides.

INPUT — LOOK AT THE IMAGES YOURSELF. The attached images are contact sheets, one per type: 30 random products of that type (fewer if the type has fewer), each tile = «shop photo | our CURRENT cutout on grey», numbered 01–30 with the product name. The file name is `<count in catalog>-<type>.png`. Types (count): кровать 131, комод 130, стул 93, ковёр 90, подушка 89, кресло 89, тв-тумба 85, диван 71, шкаф 67, тумба прикроватная 65, пуф 60, стеллаж 54, картина 51, столик 39, стол обеденный 36, кашпо 33, ваза 31, торшер 29, шторы 27, плед 11, витрина 9, лампа 3, люстра 2.

TASK
1. For EACH type, a passport (short, Russian, plain words):
   - what photos of this type look like (angle, background, materials, special shapes);
   - cutout failures you SEE on the sheet (cite tile numbers), their likely cause, and the rule that fixes them for the whole type;
   - an AUTOMATIC check that catches this type's failure without a human;
   - painting: which views may get the shop photo, what hidden sides/back become, the caption text for hidden sides; whether 3D painting is needed at all (check the code/memory for how rugs, pictures, curtains, throws are placed: `core/furniture.md`, `core/mesh-pipeline.md`, search the repo);
   - sample to verify the rule (how many, which tiles).
2. Then GENERAL rules that several types share, and where a per-type rule would be a bad idea (hides a general bug).
3. NEW-TYPE trigger: how the conveyor detects a type without a passport, what it does automatically (sample, draft passport, fallback rules), and who/what approves.
4. Flag wrong catalog roles you notice (item of another type inside a sheet).
Be concrete and critical; cite tile numbers. Table of types first, then details.
