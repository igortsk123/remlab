## 1. Conclusion

Do not ship the current `sg_views.py` as the catalog-wide solution.

The most plausible cause of the observed leakage is the combination of:

1. Every later view receives the original front product photo as image 3.
2. The stock prompt calls that photo “the overall style of the object,” inviting Qwen to transfer front-face layout—not merely materials—to every visible face.
3. At CFG 1.0 there is no effective negative-conditioning channel.
4. The draft’s positive prompt still names the unwanted concept: “no front pattern.”
5. Camera 0 is not front-facing, while the pipeline generates cameras in name order.
6. The ring is elevated, so top surfaces are visible in ordinary side views, but the draft only recognizes a top view above 60°.

My recommended order of changes is:

- For directional products, use the product photo only on the first, reference-matching view; use projected context for views 1–7.
- Generate the product-photo-matching view first, then sweep through adjacent cameras.
- Replace negative wording with affirmative, role-class-specific surface descriptions.
- Classify views as front / front-quarter / side / rear-quarter / rear, and separately add clauses for every materially visible top or underside.
- Resolve the reference-facing direction from orientation metadata or render-to-photo matching. Do not assume −Y unless the upstream contract is verified.
- Treat wall backs as excluded coverage, and route rugs/throws/curtains away from this eight-view workflow where possible.

The defective run did not use the teammate’s draft: its archived view prompts are empty. The draft is a proposed fix, not the cause of that run.

---

## 2. Technical findings and evidence

### 1. How camera prompts are merged

They are prepended to the shared object prompt, not appended and not substituted.

StableGen:

- Retrieves the prompt frozen for the current view in [`workflows.py:54`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/workflows.py:54).
- Builds `user_prompt` from the scene texture prompt, then executes `user_prompt = f"{view_desc}, {user_prompt}"` in [`workflows.py:1293`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/workflows.py:1293).
- Only afterward inserts that string into the Qwen initial/sequential template.

Consequently, for a camera prompt `"Left side view..."`, the effective initial text resembles:

```text
Change and transfer the format of
'Left side view..., a wooden chest of drawers'
in image 1 to the style from image 2
```

The same injection executes before the `is_initial_image` branches, so it reaches view 0 and views 1–7 equally. What changes is the surrounding template and image slots, not the camera-prompt merge.

Conditions under which it is ignored:

- `scene.use_camera_prompts` is false.
- There is no collection entry whose name exactly matches the camera.
- A custom Qwen template omits `{main_prompt}`.

The driver correctly creates exact-name entries and enables the toggle in [`sg_drive.py:68`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_drive.py:68). StableGen freezes those prompts into its view plan in [`generator.py:1071`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/generator.py:1071).

However, this run’s [`view_plan.json:4`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/view_plan.json:4) contains `prompt: ""`, and its [`cfg.json:5`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/cfg.json:5) has no `view_prompts` option. Therefore no camera-specific text affected the defective run.

### 2. CFG 1.0, negative prompts, and positive negation

For this run, the negative prompt is doubly ineffective:

- The legacy Qwen workflow template initializes the negative encoder with an empty string in [`workflow_templates.py:1407`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/util/workflow_templates.py:1407).
- The archived view-0 graph has `cfg: 1.0` and an empty negative prompt in [`view_000…json:2`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/prompts/view_000_Camera_0_qwen_edit.json:2) and [`view_000…json:122`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/prompts/view_000_Camera_0_qwen_edit.json:122).

In conventional CFG,

```text
unconditional + cfg × (conditional − unconditional)
```

reduces to the positive prediction at CFG 1. ComfyUI’s maintainer explicitly confirms that CFG 1 ignores the negative prompt in [ComfyUI discussion #2081](https://github.com/Comfy-Org/ComfyUI/discussions/2081). The Lightning repository recommends four steps and CFG 1 for Edit-2509 in [LightX2V-Qwen-Image-Lightning](https://github.com/ModelTC/LightX2V-Qwen-Image-Lightning).

Do not confuse this with the official Diffusers example: the [Qwen-Image-Edit-2509 model card](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) uses `true_cfg_scale=4.0`, blank negative text, and `guidance_scale=1.0`. That is not the same interface as this standard ComfyUI KSampler graph.

Positive wording such as `"no front pattern"` remains part of the active positive conditioning. Qwen may understand the negation semantically, but it is unreliable and names/primes the exact motif you do not want. Weak negation handling is a broader, measured image-editing problem; see [NeIn: Telling What You Don’t Want](https://openaccess.thecvf.com/content/CVPR2025W/SyntaGen/papers/Bui_NeIn_Telling_What_You_Dont_Want_CVPRW_2025_paper.pdf).

Prefer:

```text
Left side view. One continuous matte dark-grey side panel matching the carcass.
The wooden top finish continues across the visible top.
```

Avoid:

```text
Plain side panel, no front pattern.
```

This affirmative recommendation is strong engineering practice, but there is no published Qwen-2509 furniture benchmark proving that every negated positive prompt is counterproductive.

### 3. Should the front photo be sent to side/rear/top views?

For directionally differentiated products, my default answer is no: use it on the first reference-matching view, then let projected context propagate materials.

The archived graphs prove the current wiring:

- View 0: depth is image 1 and the product photo is image 2 in [`view_000…json:143`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/prompts/view_000_Camera_0_qwen_edit.json:143).
- View 1: depth is image 1, projected context is image 2, and the original photo is image 3 in [`view_001…json:147`](/home/pakar/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509q5-rp-231438/blender/sg-output/Scene/2026-11-19T23-14-46/prompts/view_001_Camera_1_qwen_edit.json:147).
- The later prompt describes image 3 as “the overall style,” even though it contains a front-specific leaf layout.

Qwen feeds references through both semantic and appearance paths, according to the [ComfyUI Qwen documentation](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit). Strong reference leakage is therefore unsurprising. Qwen officially supports one to three images, but the [2509 model card](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) does not say that image-role ambiguity is automatically resolved. Qwen’s own [prompt enhancer source](https://github.com/QwenLM/Qwen-Image/blob/main/src/examples/tools/prompt_utils.py#L974-L1065) says multi-image prompts should identify what comes from each image.

Without patching StableGen, you have:

- One global external image path, not a per-camera path: [`properties.py:1198`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/core/properties.py:1198).
- “External for Initial Only”: [`properties.py:1207`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/core/properties.py:1207).
- Context modes `NONE`, `REPLACE_STYLE`, and `ADDITIONAL`: [`properties.py:1189`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/core/properties.py:1189).
- Custom initial and sequential prompt templates: [`properties.py:1217`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/core/properties.py:1217).
- Per-camera text, but not per-camera image references.

With QWEN PRECISE and `qwen_external_style_initial_only=True`, later `REPLACE_STYLE` views use the current projected context as image 2; the routing is in [`workflows.py:1337`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/workflows.py:1337) and [`workflows.py:1382`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/workflows.py:1382).

Exceptions by class:

- Continuous/sculptural objects—vases, planters, many shades—can reasonably receive the photo on all azimuths because materials and patterns often continue around the same physical component.
- A crop is useful only if it is a reliable material swatch or actually shows the relevant side. Cropping a front panel does not reveal the unseen back.
- Different side/back photos require a patch, separate generation passes, or supplier multiview data.

If the front photo must remain on every view, replace “overall style” with:

```text
Image 3 shows the product from the front.
Use its colors and materials on corresponding physical components.
```

### 4. General role-class rule

Use two independent labels:

1. A surface-semantic class: casework, upholstered, open-frame, continuous/sculptural, wall-fronted, flat textile.
2. A coverage profile: floor, wall, ceiling, or flat.

That stays general while avoiding the false assumption that every side or back is a plain panel.

| Class | Roles | Surface rule |
|---|---|---|
| Casework | шкаф, комод, тв-тумба, витрина, стенка, прикроватная тумба | Front layout belongs to front components. Side uses carcass construction; rear uses a simple construction-appropriate backing; top uses the corresponding top finish. |
| Upholstered/bed | диван, кресло, пуф, подушка, кровать | Continue upholstery over arms, body, cushion sides and finished back, with plausible seams; preserve exposed frame and leg materials. |
| Open-frame | стул, стеллаж, столик, стол обеденный | Continue each component’s material around that component; preserve gaps and open spaces. |
| Continuous/sculptural | люстра, лампа, торшер, ваза, кашпо, растение, статуэтка | Continue material and pattern around the same continuous component, while preserving boundaries between components. |
| Wall-fronted | бра, полка, зеркало, картина, часы, камин | Texture face, visible thickness, top/bottom and fixture parts. Exclude the wall-facing back from normal coverage. |
| Flat textile | ковёр, плед, шторы | Prefer a 2D textile/albedo pipeline. If meshed, apply the face pattern once and derive a matching reverse/edge treatment. |

Automatic selection should be an exact normalized lookup from `products.cat_role`, with explicit English aliases such as `sofa`, `chest_of_drawers`, `wardrobe`, and `floor_lamp`. Normalize Unicode, case, spaces and hyphens, but do not use fuzzy substring guessing. Unknown roles should get a conservative “corresponding-component continuity” prompt plus a QA flag—not the casework/plain-panel rule.

### 5. Is front = −Y safe?

No, not from the inspected pipeline.

The only −Y evidence is a convention local to the stand renderer: [`render_stand.py:218`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/render_stand.py:218). It says azimuth 0 views the object from −Y; it does not orient the imported product.

The preparation script imports, joins, decimates, unwraps and exports, but never rotates or canonicalizes the mesh: [`sg_prep_shape.py:23`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_prep_shape.py:23). TRELLIS.2’s exporter performs a GLB coordinate-system conversion, but its source does not establish a semantic furniture-front axis: [TRELLIS.2 texturing source](https://github.com/microsoft/TRELLIS.2/blob/main/trellis2/pipelines/trellis2_texturing.py).

There is already useful orientation machinery elsewhere in this repository:

- [`mesh_orient.py:127`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/mesh_orient.py:127) compares candidate renders with the product photo using silhouette IoU and spatial color similarity, returning confidence and ambiguity.
- [`orient_worker.py:303`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/orient_worker.py:303) stores canonical transforms and treats uncertain cases as reviewable rather than silently rotating them.

For StableGen, adapt that idea to all eight actual camera poses:

- Render untextured silhouette/normal/depth previews.
- Compare the cutout silhouette and internal edges to the product photo.
- Pick the best camera as the seed/reference-matching view.
- Record the top-two margin; abstain on symmetry or low confidence.
- Prefer existing canonical-orientation metadata when its coordinate mapping to Blender has been verified.

Do not infer the front from Qwen’s already-textured outputs; leakage would make that circular.

Also distinguish:

- Reference-facing seed view: the camera that best matches the photo, often three-quarter.
- Semantic front axis: the actual product front used for classifying side and rear.

They are not always the same.

### 6. Camera order

Yes: generate the photo-matching front or front-quarter view first, then visit adjacent cameras around the ring.

View 0 has no prior context; later views render context from prior projections in [`generator.py:1987`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/generator.py:1987), and every completed image is projected immediately in [`generator.py:2159`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/generator.py:2159). A good first anchor therefore propagates into subsequent views.

But “dominates” needs qualification: earlier views do not automatically receive greater final bake weight. `early_priority` defaults to false in [`properties.py:1430`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/core/properties.py:1430), and projection applies that bias only when enabled in [`projection.py:2711`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/projection.py:2711).

Current ordering is natural camera-name order:

- StableGen natural-sorts cameras in [`view_plan.py:38`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/view_plan.py:38).
- The driver does not set a custom order.
- The run’s plan is Camera_0 through Camera_7.

Relative to assumed −Y, archived Camera_0 is approximately 68° away from front, while Camera_7 is approximately 21° away. Thus the run begins with a side/front-quarter view, not the best front view.

After selecting Camera_7, for example, use one adjacent sweep such as:

```text
Camera_7, Camera_0, Camera_1, …, Camera_6
```

rather than jumping front → rear → side.

### 7. Risks in `sg_views.py`

The main defects are:

- It is explicitly a casework rule but would be applied to the whole catalog: [`sg_views.py:1`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_views.py:1).
- `"plain back panel"` is wrong for upholstered furniture, chairs, lamps, plants and many beds.
- `"plain top surface"` is wrong for wooden tops, glass tops, upholstered cushions, patterned shades and tables.
- It uses positive negation: [`sg_views.py:9`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_views.py:9).
- It assumes −Y without consuming orientation metadata.
- With an eight-camera 45° ring, cameras can land exactly at 45° and 135°. The code assigns exactly 45° to front and exactly 135° to side in [`sg_views.py:29`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_views.py:29); tiny floating-point changes can flip labels.
- A 45° view visibly contains both front and side, so a single `front` label is semantically incomplete.
- The top and bottom branches require elevation beyond ±60° in [`sg_views.py:18`](/home/pakar/igor/remlab/.claude/worktrees/stablegen-1119/tools/scout/stablegen/sg_views.py:18).
- The actual ring preserves a constant camera height in [`placement.py:951`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/cameras/placement.py:951). The archived cameras aim downward by roughly 26.5°, so tops are visible but never labeled top.
- The ring contains no bottom view. That is acceptable for most floor casework, but not for chandelier undersides, pendant shades, some tables/chairs, or other objects seen from below.
- Camera_0 originates from the current Blender viewport when no reference camera exists: [`placement.py:456`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/cameras/placement.py:456). The ring’s phase is therefore not a semantic-front contract.

Use five azimuth states with half-step boundaries:

```text
front:          < 22.5°
front-quarter:  22.5°–67.5°
side:           67.5°–112.5°
rear-quarter:   112.5°–157.5°
rear:           > 157.5°
```

More importantly, add top/underside clauses based on actual projected surface visibility, not solely camera elevation.

---

## 3. Recommended prompt texts

### Common templates

Initial/reference-matching view:

```text
Image 1 is the current-view depth guide. Image 2 is the product reference for this view.
Render the same product on the guide. {main_prompt}
```

Later views, preferred initial-only-photo configuration:

```text
Image 1 is the current-view depth guide. Image 2 is the current projected texture.
Fill the solid-magenta object regions by continuing the matching materials from adjacent painted regions.
Preserve the existing non-magenta object pixels. {main_prompt}
```

Later views if the product photo remains as image 3:

```text
Image 1 is the current-view depth guide. Image 2 is the current projected texture.
Fill the solid-magenta object regions. Image 3 shows the product from the front.
Use its colors and materials on corresponding physical components. {main_prompt}
```

Set `qwen_prompt_template="CUSTOM"`; the legacy path selects custom fields based on that enum in [`workflows.py:901`](/home/pakar/ext-src/stablegen-1911/repo/stablegen/texturing/workflows.py:901).

### Per-class camera prompts

Casework:

```text
Front view. Match the doors, drawers, hardware and front-face finish to the product reference.
```

```text
Front-left three-quarter view. Match the front components; continue the carcass finish over the visible left side and the top finish over the visible top.
```

```text
Left side view. Render one continuous side panel in the carcass finish; continue the matching top finish across the visible top.
```

```text
Rear-left three-quarter view. Render a simple construction-appropriate back panel and the corresponding side panel; continue the matching top finish.
```

```text
Rear view. Render one simple construction-appropriate back panel in the carcass color family.
```

Upholstered/bed:

```text
Side view. Continue the corresponding upholstery over the arms, cushions and body with realistic construction seams; keep exposed frame and legs in their matching materials.
```

```text
Rear view. Cover the finished back in the corresponding upholstery with simple construction seams; keep exposed frame and legs in matching materials.
```

```text
High view. Continue the corresponding upholstery and materials over cushions, arms and upper frame surfaces, preserving part boundaries.
```

Open-frame furniture:

```text
Side view. Continue each visible structural component in the material of the corresponding component; keep all gaps and openings open.
```

```text
Rear view. Continue the back, seat, shelf, frame and leg materials on the corresponding existing components; keep open spaces open.
```

```text
High view. Continue the upper-surface finish across each tabletop, seat or shelf that exists; keep openings open.
```

Continuous/sculptural:

```text
Continue each material and surface pattern around the same continuous component, preserving boundaries between components.
```

For elevated or low views:

```text
Match the visible upper surfaces and undersides of each component to its corresponding material.
```

Wall-fronted:

```text
Front view. Match the visible face, frame and fixture materials to the product reference.
```

```text
Oblique view. Continue the face, frame and fixture materials around their visible thickness; render shelf top and underside surfaces where present.
```

Rear, only if unavoidable:

```text
Rear mounting view. Render a simple uniform backing or mounting plate.
```

Flat textiles, if forced through 3D:

```text
Reproduce the textile color and pattern on the visible face with woven texture and finished edges.
```

```text
Use a matching textile reverse in the same base colors with finished hems.
```

---

## 4. Risks and edge cases

- One front photo contains no ground truth for the rear. Category rules can produce plausible backs, not accurate backs.
- A casework side may itself contain glass, trim or decoration. “Corresponding side construction” is safer than universally saying “plain.”
- `витрина`, mirrors, fireplaces and lamps expose material problems beyond albedo: glass, reflection, emission and transparency cannot be solved reliably by RGB projection prompts alone.
- Product-photo lighting and reflections may be baked as color.
- Q5 quantization plus four-step Lightning may reduce instruction adherence relative to the base BF16 model. I found no controlled public benchmark for this exact combination.
- Symmetric objects may have no meaningful front. Mark them nondirectional instead of inventing one.
- A product photo may be three-quarter despite being catalogued as “front.” Use it as the seed pose, not blindly as the semantic front axis.
- Curtains still need 3D drape geometry, but their textile appearance should normally come from a single 2D texture/material rather than eight independently hallucinated views.
- Rugs and many throws can be a plane or cloth mesh with a rectified product texture. The eight-view workflow adds inconsistency without adding useful evidence.
- Chandelier and pendant undersides require a low-angle view. An elevated ring alone is the wrong coverage profile.
- Wall-facing backs should be removed from the bake-coverage objective, not generated and then trusted.

---

## 5. Alternatives

1. **Recommended no-patch configuration:** external style initial-only, QWEN PRECISE `REPLACE_STYLE`, custom templates, role-class camera prompts, reference-matching first camera.

2. **Keep the photo on all views:** appropriate primarily for continuous/sculptural objects; otherwise explicitly label it as a front-view material/identity reference.

3. **Universal material swatch:** extract a reliable carcass/upholstery swatch and use that instead of the full product image on later views. This reduces layout leakage but loses component identity.

4. **Per-view references:** use supplier spin photography or generated/approved side and rear references. StableGen currently needs a patch or separate passes for per-camera image paths.

5. **Surface masks:** classify front/side/rear/top mesh regions and condition or mask each material independently. This is more robust than language-only suppression.

6. **Base-model validation:** test the 40-step/base configuration on a small matrix. It may follow detailed prompts better, but do not assume Diffusers `true_cfg_scale` and ComfyUI KSampler CFG are identical.

---

## 6. Uncertainties

- The archived wiring and outputs strongly support front-reference leakage, but there is no controlled run where only image 3 or only the wording changed.
- There is no official Qwen-2509 result comparing `"no leaf pattern"` with `"continuous dark-grey side panel"` on furniture.
- I found no documented TRELLIS.2 semantic-front guarantee.
- The current run’s camera elevation and azimuth were inferred from its archived matrices; the object’s semantic axes were not recorded in the run.
- Role strings cannot reveal whether a particular sofa has an unfinished back, whether a cabinet has glass sides, or whether a rug is reversible.
- Existing `mesh_orient.py` is a strong starting point, but it evaluates four cardinal yaws and uses color evidence; an untextured mesh and a three-quarter photo require extending the candidate poses or relying more heavily on silhouette/edge evidence.

---

## 7. Evidence that would change the recommendation

I would revise the conclusions if any of the following appeared:

- A documented, tested upstream contract proving that every prepared TRELLIS.2 furniture mesh has semantic front mapped to Blender −Y.
- A representative A/B test showing that all-view product-photo conditioning, with explicit image-role prompts, materially improves rear/side consistency without increasing front-layout leakage.
- Supplier side/rear imagery. Real multiview evidence should replace category priors immediately.
- A reliable semantic surface classifier or material-part segmentation, making coarse angular prompt classes unnecessary.
- Tests showing the base model or another guidance method uses negative conditioning effectively while retaining the required latency and quality.
- A catalog evaluation across casework, upholstery, open frames, radial objects, wall items and flat textiles showing that another camera order produces lower seam and leakage rates.

The minimum useful experiment is a factorial test over approximately 30 products: photo all views vs initial-only, default vs explicit image roles, negated vs affirmative prompts, and natural vs reference-first camera order. Score side/rear motif leakage, material consistency, UV seams and human acceptability separately.