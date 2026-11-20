You are an independent senior engineer (computer vision / 3D asset pipelines). Do not modify files. Answer in Russian, plain words, concrete numbers and short reasons. Read-only access to the repo is available (`-C /home/pakar/igor/remlab`); check claims against code where it is cheap, and say what you could NOT check.

# CONTEXT (self-contained)

Product: a furniture/decor catalog, ~50 000 products today, thousands of floor plans. For each product we take ONE shop photo and make a 3D mesh and paint it. Owner is not a programmer, so everything must be automatic; humans only sample. Hard constraints for every answer:
- scale: tens of thousands of products, thousands of floor plans — a rule must work as a data-driven check, not a hand-fix per product; no product IDs in code or rules;
- NO paid per-item steps for checks (CPU only, free; heavy jobs run niced through a heavy-slot); paid GPU (Salad/RunPod) is only for the mesh/painting itself and is used in batches;
- checks run automatically; humans look at a sample only;
- every work file is deleted by the step after success; only results and short logs stay.

Pipeline steps:
(A) CUTOUT — shop-photo background removal before 3D (BiRefNet mask, no text prompt, plus our post-processing chain: fill-holes/closing in `tools/scout/salad/pipeline.py`, a grey-cover detector `tools/scout/mesh_grey_top.py`, etc.).
(B) PAINTING the generated 3D mesh from ONE shop photo: StableGen, 8 cameras (front, side, back, top…), Qwen-Image-Edit; captions per camera angle live in `tools/scout/stablegen/sg_views.py` (worktree `.claude/worktrees/stablegen-1119`). Known facts: giving the shop photo to views whose silhouette matches the photo copies the FRONT onto the BACK; a short caption «the plain side of the same <noun> …» fixes sides. View zones from the driver log: front up to ~47°, side ~85–97°, back ≥130° (ADR-0454: photo only up to ~100°).
Per asset role the canonical strategy is in `tools/scout/rules/asset-strategies.json` (ковёр/картина/зеркало = `procedural_plane`; шторы/плед/покрывало = `cutout` but the line `parametric_soft` is «not implemented yet»; everything else `hunyuan3d`).
Already in the repo (reusable, free): fastembed CLIP ViT-B-32 vision on CPU (`tools/scout/compose2.py:160`, embeddings cache), numpy/scipy/skimage venv, SSIM helper (`tools/scout/salad/recolor_lp.py:_ssim`), a neutral-grey-cover detector with Lab chroma/ΔE thresholds, quarantine mechanism (`tools/scout/rules/mesh-quarantine.json`), input gates (`mesh-photo.json`: cut long side ≥512 px).

# WHAT IS ALREADY DECIDED (do not re-litigate; only sharpen)
Draft: `.memory_bank/plans/mesh-type-passports-draft.md` (read it; it has 23 type passports, 9 director-vs-Codex disagreements resolved, general cutout rules С1–С9, painting rules П1–П11, a new-type trigger). Your previous answer: `.memory_bank/_intake/codex/2026-11-20-type-passports-answer.md`. Decided there: registry `rules/mesh-type-passports.json` (type→aliases, family, subtypes, cutout route+guards, paint views, sample, role_mismatch, version); photo class before BiRefNet (studio_single / studio_multiple / interior / macro_material / flat_rect / transparent_product); rugs/pictures = flat_rect + procedural plane with texture from the rectified source rectangle; curtains/throws = `parametric_soft`, no cutout; glass = full occupancy silhouette + glass material later; photo only to the grain camera (front ≤~50°) for directed items, short caption for side/back; back-view photo forbidden; passport version is part of the cutout/mesh/painting cache key.

# THE 10 QUESTIONS (K1–K10) — each with OUR short conclusion made BEFORE asking you

For each question give: your answer (a number/method), whether you AGREE with our conclusion, the evidence (code line / known source / reasoning), the main risk, and how to calibrate it automatically on our catalog without labels or with a cheap sample.

**К1. Headboard guard for beds (131 beds).** Director said «≥1/3 of total height above the mattress», you said 20–30 %. How to set the threshold and how to automatically separate sub-types without a headboard (тахта, kids bed with a rail, bare base/mattress) from beds that lost the headboard in the cutout?
OUR CONCLUSION: soft flag, not hard reject. Start at 25 % of total mask height above the mattress line (found as the widest horizontal band / top of the wide low plateau in the row-width profile). Sub-type `no_headboard` is decided by the row-width profile: no narrow-then-wide step and aspect (width/height) high → flag, not reject. Calibrate by plotting the histogram of the headboard ratio over all 131 beds and putting the threshold in the valley; items under it go to a contact sheet sample, not to quarantine automatically.

**К2. Photo-class classifier (С1) without paid calls at 50 000 scale.** Which cheap features and/or the CPU CLIP we already have; what error is acceptable at the boundary.
OUR CONCLUSION: two stages. Stage 1 — mask/photo features only: number of components with area >15 % of frame, border-touching share, background uniformity from the four frame corners (ΔE between corners <6 → studio), share of low-texture wall/floor-like bands. Stage 2 — CLIP zero-shot (ViT-B-32, CPU, ~0.1–0.3 s/image) with 4–6 text prompts («product on plain white background», «furnished interior room», «several products», «fabric close-up») only on the ambiguous band of stage 1. Costs are asymmetric: a good studio photo rejected = product stays a flat card (cheap); an interior sent to a paid mesh = wasted paid run + a bad model. So bias to reject: target false-accept of interior ≤2 %, false-reject of studio ≤10–15 %.

**К3. Pillow: how to detect «plain/однотонная» without a human, and may a plain pillow get the shop photo on 2–3 views?**
OUR CONCLUSION: plain = inside the cutout (eroded 6 px) chroma-weighted Lab std small AND ≤2 colour clusters (second cluster <5 % area) AND low Laplacian energy (no print/embroidery/fur texture). Even for plain pillows give the photo only to front and ±45°; never to back (back keeps the caption «plain reverse of the same cushion in the base fabric colour»). The expected gain of showing the photo to more views is small compared to the «face on back» risk.

**К4. Occupancy mask for glass (С3), common path for ваза, витрина, столик, лампа, люстра, торшер without annotation.**
OUR CONCLUSION: no single method fits all. For rotationally symmetric items (ваза, лампа, люстра, круглый столик) use row-wise span fill between the left and right outer contour points after mirroring about the vertical axis (exact except at the throat/open top, which stays open above the rim row). For витрина: detect door rectangles (long straight edges of the frame) and fill those rectangles only. For others: morphological closing with radius proportional to object size + fill holes only if the hole interior is NOT the frame background colour. Common guard for all: full-silhouette fill ≥0.98, mean body colour ΔE >10 from the frame background, throat connected to the background.

**К5. Guard «front façade on the back» (П9): metric and threshold on renders of front vs back.**
OUR CONCLUSION: render front and back views of the painted mesh at the same scale; flip the back horizontally; compare only inside the mask on high-pass/edge maps with normalized cross-correlation (and, as a second opinion, CLIP cosine between the two crops). Initial threshold: local NCC >0.6 on a detail mask (handles, drawers, buttons, text, print) → reject and repaint with the short caption. Symmetric sub-types (round pouf, shelving through, lamp) are exempt through `directed=false` in the passport. Calibrate on the known-bad комод az180 renders (print on the back) vs known-good ones.

**К6. `shape_subtype` automatically (closed/open/suspended/open_frame; directed/symmetric) and catching «role lies» (консоль among комоды, антресоль among стеллажи, банкетка among пуфы).**
OUR CONCLUSION: rules over the cutout silhouette first: mirror-IoU of halves, share of large holes, aspect ratio, bottom gap under the body (suspended = no supports below the body), and the existing registry priors. CLIP zero-shot with role names as text only as a tie-breaker. A «role vs shape» mismatch never auto-corrects the role; it routes the item to a mismatch flag + quarantine for the sample.

**К7. Curtains / throws: `parametric_soft` (parametric panel + fabric from the frame). What gives an acceptable look at thousands of items; how to take fabric from an interior frame without a «main object».**
OUR CONCLUSION: for interior frames do NOT extract fabric from the frame (it would pick furniture). Use catalog attributes (colour/name) + a procedural fabric from the dominant colour and, only when the photo class is studio/macro, a seamless texture patch from the largest homogeneous textile region. Tulle = transparent uniform material. Interior-photo curtains/throws with no usable patch get the plain dominant-colour fabric.

**К8. П7: checking that all four legs of a piece have the same material/colour on renders.**
OUR CONCLUSION: segment legs on the rendered views as thin components under the body-bottom line (bottom 12–20 % of height); compare mean Lab of front-pair vs back-pair legs (ΔE ≤12) and the share of «stain» pixels (ΔL>25 from the leg median) <2 %. Prefer fixing it in the texture (replace leg texels, selected by 3D height below a z-threshold, with the median leg colour) over a longer caption; keep the caption «all four legs the same material and colour» as a complement.

**К9. П8: where to remove isolated dark dots and ragged seams at the table top edge — after texture bake or in the Qwen prompt — and the threshold.**
OUR CONCLUSION: after the bake, in UV space, only on regions marked flat (low local variance): remove blobs whose area <0.05 % of the atlas and ΔL >20 from the local median (median/morphological opening); seam: edge-aware smoothing across the island boundary of the top. The prompt cannot reliably remove point noise. Check: ≤2 isolated blobs per 100 000 px on flat regions; ragged seam length <5 % of the edge.

**К10. Auto-approval of a new type passport.** Is «30/30 invariants pass + family confidently matches an approved one» enough, how to measure family confidence, or does a new shape class always need a human?
OUR CONCLUSION: 30/30 is statistically weak (95 % upper bound of the failure rate ≈10 %), so it is only one of the conditions. Auto-approve only if ALL: family confidence high (distance to the approved-family centroid in CLIP/feature space + margin to the second family, e.g. top-1 cosine ≥0.85 and margin ≥0.05, thresholds calibrated on the 23 existing types by leave-one-type-out), 30/30 invariants, canary ≥10 meshes × 8 views passes the automatic checks, and the type is NOT in a high-risk class (transparent, flat_rect, interior/macro photos, a new shape class). Anything else → owner, one contact sheet per week.

# WHAT WE ASK FROM YOU
1. For each of К1–К10: AGREE / PARTLY / DISAGREE with our conclusion + your concrete number or method + the one main risk + how to calibrate it without human labels.
2. Where our conclusion conflicts with the constraints (cost/scale/automation), say so plainly.
3. Mark clearly what you checked in the code and what you did not.
4. At the end: the 3 questions that REALLY need the owner (not technical), each with a one-line reason; if you think the draft's current 3 owner questions are the right ones, say so.
Be critical and concise. Do not repeat the passports.
