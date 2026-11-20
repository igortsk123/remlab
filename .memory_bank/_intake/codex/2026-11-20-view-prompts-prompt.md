You are an independent senior engineer reviewing a texturing pipeline. Do not modify, create or delete files.

USER OBJECTIVE
We texture 3D furniture meshes (shape from TRELLIS.2) with the Blender add-on StableGen + ComfyUI + Qwen-Image-Edit-2509 (GGUF Q5) + Lightning 4-step LoRA (cfg=1.0, 4 steps, euler/simple). 8 cameras in an orbit ring; views are generated sequentially; each later view inpaints the not-yet-textured ("magenta") areas, then everything is projected and baked to UV.
Inputs per view: depth map of the view, context render of already-painted texture (views 1..7), and ONE product photo (front view of the product, cut out on transparent background) as the "style image".
The goal: one GENERAL rule for ALL our product roles — no per-product special cases. Full list of roles in our catalog (products.cat_role in the dev DB, Russian, with counts):
люстра (chandelier) 5231, диван (sofa) 3445, шкаф (wardrobe) 1984, бра (wall lamp) 1380, стул (chair) 1325, кресло (armchair) 992, пуф (pouf/ottoman) 837, комод (chest of drawers) 785, ваза (vase) 708, кашпо (planter) 636, стеллаж (open shelving unit) 550, лампа (table lamp) 522, тв-тумба (TV stand) 516, плед (throw blanket) 477, шторы (curtains) 475, растение (plant) 401, столик (coffee/side table) 395, ковёр (rug) 388, подушка (cushion) 366, стол обеденный (dining table) 322, статуэтка (figurine) 285, торшер (floor lamp) 267, полка (wall shelf) 184, зеркало (mirror) 162, камин (fireplace) 109, картина (wall art) 93, витрина (display cabinet, glass doors) 71, часы (clock) 53, стенка (wall unit) 43; plus bedroom: кровать (bed), прикроватная тумба (nightstand).
Wall-mounted items (бра, полка, зеркало, картина, часы) have a back that is never seen; flat items (ковёр, плед, шторы) may not need 3D at all — say so if relevant. Group all roles into a small number of view-prompt classes and give the rule for each class.

OBSERVED DEFECT (chest of drawers whose front has a leaf pattern, carcass is plain dark grey)
The run folder: /home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/
(generated/generated_image{0..7}-0-0001.png = what the model generated per view; prompts/view_00N_Camera_N_qwen_edit.json = exact ComfyUI graphs sent; inpaint/, controlnet/depth/).
Views 2, 3, 6, 7 painted the FRONT leaf pattern onto whatever face looked at the camera (side, back); views 0, 4, 5 kept the side plain; view 1 even put leaves on the top. Final model: left side good, right side and back copy the front.
All views get the same text: view 0 "Change and transfer the format of 'a wooden chest of drawers' in image 1 to the style from image 2"; views 1..7 "Change and transfer the format of image 1 to 'a wooden chest of drawers'. Replace all solid magenta areas in image 2. ... Image 3 represents the overall style of the object."

CODE
- StableGen add-on source: /home/pakar/ext-src/stablegen-1911/repo/stablegen (how prompts are built, camera_prompts / use_camera_prompts, how the style image and context images are wired, negative prompt handling).
- Our driver: /home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_drive.py (apply_view_prompts) and sg_views.py (a teammate's draft: classifies each camera as front/side/rear/top relative to an assumed front direction −Y and appends text like "left side view, plain side panel, no front pattern").

TECHNICAL QUESTIONS — answer each with evidence from the code (file:line) and, for model behaviour, from public sources (Qwen-Image-Edit-2509 model card / ComfyUI docs / community reports) with links:
1. How exactly does StableGen merge a camera prompt into the per-view prompt for the qwen_image_edit architecture (appended, replaced, ignored)? Does it reach view 0 and the inpaint views 1..7 equally?
2. With cfg=1.0 (Lightning) is the negative prompt effectively ignored? Is negation wording ("no front pattern") in the positive prompt effective or counterproductive for Qwen-Image-Edit-2509? What wording works better (describe what IS there, e.g. "plain matte dark grey side panel, same carcass material")?
3. Should side/rear/top views still receive the front product photo as an image input, or a different reference (e.g. a crop, or only the context render), or the photo with an explicit instruction "image N shows the FRONT only"? What does the add-on allow without patching it?
4. A general per-category rule: what should the side/back/top text say for box furniture vs upholstered sofas/armchairs (back is upholstered fabric, not a plain panel) vs tables/chairs (legs, open frames) vs lamps/vases (rotationally symmetric — pattern legitimately continues around)? Propose a compact rule table, and how to pick the category automatically from data we have (product role string such as "sofa", "chest", "wardrobe", "floor_lamp").
5. Front direction: is assuming front = −Y safe for TRELLIS.2 outputs as prepared by our pipeline? How to verify or detect the front robustly per product (e.g. from which view best matches the photo)?
6. Camera order: should the front view be generated first so its context dominates? Check how the ring is ordered now.
7. Risks and failure modes of the teammate's draft (sg_views.py) — e.g. 45°/135° thresholds with an 8-camera ring at 45° steps landing exactly on borders, the elevation of the ring cameras, the bottom view.

Return: 1) conclusion; 2) evidence with file paths/lines and links; 3) concrete recommended prompt texts per view type (English, short); 4) risks/edge cases; 5) alternatives; 6) uncertainties; 7) what evidence would change your conclusion. Be critical.
