## Executive conclusion

Do not invest in “TRELLIS.2 geometry + Pixal3D texture” first. Pixal3D does not presently expose an arbitrary-mesh texturing interface; its released inference samples shape and texture together. The technically supported and lowest-risk hybrid is:

1. Clean TRELLIS.2 geometry.
2. Run Hunyuan3D-Paint 2.1 on that geometry, initially with remeshing disabled.
3. Compare it against Pixal3D used end-to-end.
4. Use original-photo projection only as a selective high-confidence overlay for distinctive visible patterns, logos, and front panels.
5. Attempt the Pixal texture hybrid only if Pixal3D proves materially better at appearance while materially worse at shape.

My expected ranking is:

| Variant | Visible-view fidelity | Unseen surfaces | Shape preservation | PBR | Engineering risk |
|---|---:|---:|---:|---:|---:|
| TRELLIS shape + Hunyuan Paint | High hypothesis | Good/generated | Medium–high | Full | Low–medium |
| Pixal3D end-to-end | Potentially high | Generated consistently | Unknown until trial | Full | Low |
| TRELLIS + selective photo projection | Very high where confident | TRELLIS texture | Exact | BaseColor only from photo | Medium–high |
| TRELLIS + Pixal texture stage | Unknown | Potentially good | Potentially exact | Full | Very high |
| TRELLIS texturing-only rerun | Probably modest improvement | Generated | Medium–high | Full | Low |
| MVPainter on TRELLIS | Plausible fallback | Generated | Medium–high | Full | Medium–high |

One dresser is evidence of a useful failure mode, not evidence that TRELLIS shape is generally superior or that Hunyuan repainting will transfer its appearance advantage to foreign geometry.

---

## 1. Hybrid A: TRELLIS.2 shape + Pixal3D texture

### Conclusion

This is not a ready-made hybrid. Pixal3D’s released pipeline is a three-stage cascade—sparse structure, shape, then texture—and the public command produces a complete GLB. The texture stage is conditioned on Pixal’s own pixel-aligned, view-aligned shape representation; it does not accept an arbitrary GLB. The official inference calls the complete pipeline and returns both shape and texture latents. [Pixal3D repo](https://github.com/TencentARC/Pixal3D), [inference implementation](https://github.com/TencentARC/Pixal3D/blob/master/inference.py).

“Built on TRELLIS.2” does not imply that TRELLIS and Pixal texture latents can be interchanged. Pixal explicitly changes conditioning and coordinate assumptions through pixel back-projection and MoGe-estimated camera parameters. Its paper’s contribution is alignment during generation, not a standalone mesh painter. [Pixal3D paper](https://arxiv.org/abs/2605.10922).

Use Pixal3D as a whole before attempting A.

### If A is pursued, the correct algorithm

The preferred implementation is latent-level, not “copy Pixal’s texture image onto the TRELLIS UVs”:

1. Clean and normalize the target TRELLIS mesh.
2. Encode it into the exact O-Voxel/shape representation expected by Pixal’s texture model, at the same resolution and coordinate convention.
3. Estimate focal length using MoGe-2, but refine the full camera against the actual TRELLIS mesh: rotation, translation, roll, focal length and principal point.
4. Back-project Pixal’s image features into the target shape volume.
5. Invoke only the Pixal texture flow model with the externally supplied shape latent.
6. Decode PBR attributes and bake them onto the target mesh.
7. Verify geometry byte-for-byte or by Hausdorff distance, since a decoder may reconstruct rather than merely paint the mesh.

This requires changes inside Pixal’s pipeline. Its public entry point does not supply an external-shape hook.

The fallback is surface transfer:

1. Generate a complete Pixal asset.
2. Align Pixal and TRELLIS meshes with a similarity transform followed by robust ICP.
3. For every TRELLIS surface sample or texel, find a mutual nearest point on the Pixal surface.
4. Accept correspondences only below distance and normal-angle thresholds.
5. Sample Pixal baseColor, metallic and roughness at accepted points.
6. Blend holes back to the TRELLIS material in a geodesic/UV confidence band.

This is materially weaker. Furniture has repeated panels, symmetric legs and near-coplanar surfaces, so nearest-point transfer easily maps a drawer to the wrong drawer, a front edge to a side edge, or one leg to another. Tangent-space normal maps cannot be copied directly between unrelated UV/tangent frames.

### Expected failure modes

- MoGe focal errors on white-background product photography with few perspective cues.
- Pixal and TRELLIS geometry disagreeing exactly where texture correspondence matters.
- Pattern compression, stretching or phase shifts across drawer fronts.
- Incorrect source/target side assignment on symmetric furniture.
- Thin legs receiving sparse or background-contaminated correspondence.
- Glass, mirrors and glossy metal being intrinsically ambiguous.
- Unseen back and underside remaining generative rather than reconstructed.
- PBR transfer failing even when baseColor looks plausible: wrong roughness can dominate Cycles appearance.

Pixal’s official low-VRAM mode reports roughly 10–12 GB peak versus about 18 GB normally, so whole-model inference should be feasible on a 4090 and is a much cheaper experiment than building A. [Pixal3D inference](https://github.com/TencentARC/Pixal3D/blob/master/inference.py).

---

## 2. Hybrid B: project the original product photo

### Conclusion

B is technically sound only as a confidence-masked visible-surface correction. It is the most likely method to preserve the exact alternating-leaf pattern because it copies observed evidence rather than asks another generator to reproduce it.

It should not replace the full baseColor over every visible pixel. A raw projection will bake catalog lighting, contact shadows, highlights, JPEG halos and camera-registration errors into the albedo.

### Concrete algorithm

#### Camera fitting

Use a perspective camera. Initialize from MoGe-2 intrinsics/depth, then optimize against the target mesh using nvdiffrast or PyTorch3D:

- Extrinsic rotation, translation and roll.
- Focal length or horizontal FOV.
- Principal point.
- Optional weak anisotropic scale only as a diagnostic; accepting it hides geometry errors.

The objective should combine:

- Signed-distance contour loss, not only IoU.
- Mask IoU.
- Rendered depth versus MoGe relative depth after robust scale/shift alignment.
- Rendered normals versus MoGe normals.
- Strong image edges versus projected mesh/panel edges.

Silhouette-only optimization is under-constrained: several focal-length/distance combinations produce nearly the same outline, particularly for cabinets.

Reject projection when the optimized contour score is poor or multiple substantially different cameras produce similar scores.

#### Visibility and baking

For each supersampled rendered pixel, store:

- Triangle and primitive ID.
- Perspective-correct barycentric coordinates.
- UV coordinates.
- Depth.
- World/object position.
- Normal and view angle.
- Distance to silhouette and depth discontinuities.

Only project where:

- The surface is front-facing and not grazing.
- The pixel is several pixels inside both masks.
- Depth and normal agree with MoGe.
- The source is not clipped, highlighted, shadowed or background-contaminated.
- The surface projects to enough pixels for the desired texel density.

Splat samples into UV space with an elliptical footprint; do not use one screen pixel → one nearest texel. Track accumulated confidence and coverage separately from colour.

For thin legs and rails, require a projected width of at least roughly 3–5 source pixels after mask erosion. Otherwise retain the model texture.

#### Delighting

Single-image delighting is ill-posed, so use a conservative decomposition:

1. Convert sRGB to linear RGB.
2. Detect clipped highlights, low-saturation bright specular regions and deep shadows.
3. Within each likely material/panel, split log luminance into low-frequency illumination and high-frequency reflectance using an edge-aware filter guided by chroma and mesh normals.
4. Preserve high-frequency pattern and chroma.
5. Replace only trustworthy low-frequency colour with a robust region median or a fitted low-order illumination model.
6. Reject instead of “correcting” strong cast shadows, transparent materials and broad specular lobes.

For the leaf dresser, a good formulation is: copy the high-frequency Lab/chroma structure from the photograph while anchoring low-frequency lightness to a robust estimate. That preserves leaf orientation without writing the softbox gradient into albedo.

#### UV compositing and seams

Solve a weighted UV-domain least-squares or gradient-domain blend:

- Follow photo-derived gradients where confidence is high.
- Match the existing generated texture at the boundary.
- Do not blend across material or semantic boundaries.
- Enforce agreement at pairs of UV seam vertices that are the same 3D position.
- Dilate atlas gutters before mip generation.

Keep the generator texture on unobserved surfaces. A hard visible/unseen border should fail review; feathering alone cannot hide a genuine material mismatch between a projected front and a hallucinated side.

#### PBR channels

- Photo projection should normally affect baseColor only.
- Preserve generated metallic/roughness unless a separate PBR painter predicts them.
- Never overwrite known metallic/glass areas with photographic RGB.
- Do not derive metallic directly from brightness.
- Do not copy tangent-space normal maps from another mesh.
- Alpha should remain geometry/material-derived.
- If variant materials include leather versus fabric or matte versus gloss, the MR texture also needs a separate cluster-specific version.

### Main risks

- Baked shadows/highlights visible when the Cycles light moves.
- Pattern swimming due to slightly wrong focal length.
- Double images around handles and panel edges.
- Mixed foreground/background colours on legs.
- Projection onto geometry that is only approximately the photographed geometry.
- Incorrect colour management from unknown catalog post-processing.
- Abrupt material change between front and unseen side.
- Transparent/glossy products being fundamentally unsuitable.

I would deploy B only through a confidence gate and initially restrict it to large, near-planar, front-visible regions such as cabinet fronts, printed upholstery panels and logos.

---

## 3. Better third options

### First choice: Hunyuan3D-Paint 2.1 on TRELLIS geometry

This is the best immediate experiment. The official interface explicitly takes `mesh.glb + reference image` and returns a PBR-textured mesh. It generates albedo and metallic/roughness views, bakes them and inpaints uncovered UV regions. It recommends at least 21 GB for six 512px views, which is appropriate for a 4090. [Hunyuan Paint README](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/hy3dpaint/README.md), [pipeline](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/hy3dpaint/textureGenPipeline.py).

Your code already supports this architecture:

- [`paint_pipeline()`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:131) initializes Hunyuan Paint.
- [`_paint_stage()`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:927) accepts an existing mesh.
- [`generate(..., shape_glb=...)`](/home/pakar/igor/remlab/tools/scout/salad/pipeline.py:977) already implements paint-only reuse and documents it as about 42% of a full job.

The important complication is geometry preservation. Upstream Hunyuan Paint defaults to `use_remesh=True`, and then always UV-unwraps the result. Your `_paint_stage()` currently calls it without overriding that default. Test `use_remesh=False` first. Compare:

- Vertex positions and bounding box.
- Triangle count.
- Connected components.
- Thin-part survival.
- Silhouette IoU before/after painting.
- Hausdorff distance normalized by object diagonal.

If Hunyuan’s UV wrapper cannot handle the cleaned TRELLIS topology, the remeshed result may lose the shape advantage.

### Pixal3D end-to-end

This is the second strong candidate, not a fallback. Its explicit goal is visible-view pixel fidelity, and its released version generates PBR assets. It should be tested whole before attempting cross-model texture transfer. The shape may equal or outperform TRELLIS on more than this one example.

### TRELLIS.2’s own mesh texturing pipeline

TRELLIS.2 now exposes `Trellis2TexturingPipeline`, taking a mesh and reference image directly. [Official example](https://github.com/microsoft/TRELLIS.2/blob/main/example_texturing.py).

It is cheap to test because the environment is already built, but I do not expect a large improvement over the failed TRELLIS texture stage unless the separate path, seed or guidance settings behave differently. Treat it as a control and seed/guidance sweep, not the leading hypothesis.

### MVPainter / MaterialMVP

MVPainter is a credible independent fallback: its official pipeline accepts an image and GLB, explicitly supports TRELLIS-oriented meshes, and can extract baseColor, metallic and roughness before baking. [MVPainter repo](https://github.com/amap-cvlab/MV-Painter).

MaterialMVP is the underlying open research line used by Hunyuan Paint; its paper-version checkpoint may be useful if Hunyuan’s license is unacceptable. [MaterialMVP repo](https://github.com/ZebinHe/MaterialMVP).

MVPaint and Paint3D are less attractive here:

- MVPaint is mainly prompt-driven and optimized for seamless texture completion rather than exact single-photo product identity. [MVPaint paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Cheng_MVPaint_Synchronized_Multi-View_Diffusion_for_Painting_Anything_3D_CVPR_2025_paper.pdf).
- Paint3D supports image conditioning and explicitly targets lighting-free textures, but its own paper reports multi-face/inconsistency limitations and does not solve full PBR material generation. [Paint3D paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Zeng_Paint3D_Paint_Anything_3D_with_Lighting-Less_Texture_Diffusion_Models_CVPR_2024_paper.pdf).

### Licensing risk

TRELLIS.2 and Pixal3D are MIT at project level, subject to dependency/checkpoint terms. Hunyuan3D-2.1 is open-weight but not OSI open source: its Community License excludes use in the EU, UK and South Korea and imposes other terms. This deserves explicit production review even though remlab already uses it. [Hunyuan license](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE).

---

## 4. Fair measurement and a pattern metric

### The missing metric

Use a masked, camera-aligned high-frequency structure score, not another global colour statistic.

A practical metric is:

1. Fit the same perspective-camera protocol for every asset.
2. Delight or locally normalize the reference photo.
3. Convert both reference and unlit render to Lab.
4. Subtract an edge-aware low-pass at two or three scales.
5. Compute Sobel gradients.
6. In annotated texture-bearing ROIs, compute local normalized cross-correlation of gradient magnitude and orientation, allowing only a 1–2 pixel displacement.
7. Report the area-weighted median and lower-decile patch score.

Call it `pattern_grad_ncc`. The alternating-leaf error will score poorly even if mean colour, ΔE median and frequency spectrum are similar.

Also record masked MS-SSIM or DISTS on the normalized high-pass images. DISTS explicitly combines structural and texture similarity, but I would retain gradient NCC because it is easier to debug and less likely to declare “statistically similar scales” correct when the individual leaves face the wrong way. [DISTS](https://arxiv.org/abs/2004.07728).

Do not rely on CLIP. It will usually consider both leaf arrangements semantically identical.

### Fair protocol

- Keep the fixed 30 products and report paired differences per product.
- Use identical cutout bytes, final orientation and camera-fitting bounds.
- Do not cherry-pick a best seed for only one model. Either one fixed seed or equal best-of-N budget for all.
- Count failures as failures; do not omit them from medians.
- Report results after the final 1–2 MB web conversion as well as before compression.
- Apply the same floor-artifact rule to all generators, but report both raw and cleaned metrics.
- Fit photo pose independently per mesh using the same optimizer, then report fit confidence. A bad fit must not become a texture score.
- Separate:
  - shape;
  - observed-view appearance;
  - novel-view consistency;
  - PBR/relighting;
  - operational cost.

For appearance, report:

- ΔE00 median, p90 and large-region worst case.
- ΔL separately.
- `pattern_grad_ncc`.
- High-pass DISTS/MS-SSIM.
- Human pairwise preference on texture ROIs.

For PBR, render at least two substantially different HDRIs/light directions. A baseColor shadow that remains fixed while illumination moves is a failure even if the source-view render matches well.

Use paired bootstrap confidence intervals and per-category win rates. Thirty samples are enough to reject obvious losers, but not enough to infer small universal differences.

---

## 5. Are the existing files a sound base for B?

### `recolor_lp.py`

It is a good source of reusable components but not a projection implementation.

Useful:

- [`process()`](/home/pakar/igor/remlab/tools/scout/salad/recolor_lp.py:501) already couples pose fitting, rendering and GLB baseColor replacement.
- [`rewrite_glb()`](/home/pakar/igor/remlab/tools/scout/salad/recolor_lp.py:291) avoids re-exporting geometry.
- Metallic areas are protected.
- The detail-preservation checks are useful regression tests.

Not sufficient:

- [`best_pose()`](/home/pakar/igor/remlab/tools/scout/salad/color_steps.py:115) searches only five yaws, six pitches and an orthographic camera.
- [`refine_align()`](/home/pakar/igor/remlab/tools/scout/salad/recolor_lp.py:144) adds only 2D scale/translation.
- The pipeline deliberately preserves the model’s high-frequency texture. Therefore it cannot fix the wrong leaf arrangement; its `HP_RENDER_MIN` guard is designed to reject large pattern changes.
- Colour clustering is not spatial correspondence.
- No focal-length, roll, principal-point or depth/normal fitting.
- No highlight/shadow delighting.
- No projected-coverage or UV seam solve.
- `rewrite_glb()` appends replacement images without reclaiming the old image bytes and writes PNG, which can make the GLB larger—important under the 1–2 MB limit.

### `color_o2.texel_map` and `mesh_render.py`

[`texel_map()`](/home/pakar/igor/remlab/tools/scout/salad/color_o2.py:171) does provide z-buffer visibility and screen-to-UV lookup. That is a useful prototype.

Missing for production baking:

- Perspective-correct camera.
- Triangle/primitive ID and surface normals in the returned map.
- Grazing-angle and silhouette confidence.
- Supersampling and texel footprint.
- Collision handling for several pixels writing one texel.
- Overlapping-UV detection.
- UV seam adjacency.
- glTF sampler wrap modes and `KHR_texture_transform`.
- `baseColorFactor`, material alpha and some multi-material semantics.

[`mesh_render.render()`](/home/pakar/igor/remlab/tools/scout/mesh_render.py:170) is suitable for approximate CPU diagnostics, not accurate inverse rendering. Its UNLIT mode shows the texture lookup but is not a full glTF renderer.

### `hybrid_mask.py`

[`refine()`](/home/pakar/igor/remlab/tools/scout/salad/hybrid_mask.py:74) is a defensible input cutout for ordinary opaque white-background furniture and has useful thin-detail evidence.

For B, preserve:

- Original RGB separately from the composited generator image.
- Soft alpha and a mask confidence map.
- Distance to mask boundary.
- A specific failure class for white products, glass, translucent lampshades and mirrors.

Do not project colours from anti-aliased boundary pixels.

### Floor-plate cleaner

The named `tools/scout/salad/trellis/mesh_clean.py` is not in the current working tree; it exists in git history at commit `b573f93e`. Its rule is plausible as an emergency postprocessor, but it has two risks:

- Disconnected low horizontal product parts—feet, a low stretcher, bottom shelf or glass base—can satisfy the same rule.
- Concatenating scene geometries and exporting through trimesh can collapse or lose primitive/material/PBR organization, despite the file’s comment that textures remain unchanged.

Clean before camera fitting and before repainting, but preserve primitives/materials and validate removed components visually. Record removed area and volume, not only triangle share; thousands of tiny plate triangles can exaggerate its importance.

---

## 6. Variant families

### Conclusion

Keep one logical catalog family and shared geometry, but use multiple material/albedo anchors. Cluster by appearance/material, not only brightness. Apply a small residual tint within each cluster.

I would not force every family through one RGB multiplier. Multiplication cannot:

- Recover clipped highlights.
- Lighten missing dark texture detail.
- Change a pattern.
- Recolour upholstery without recolouring legs and hardware.
- Represent leather and fabric with different roughness.
- Preserve neutral handles while shifting wood or cloth hue.

The nominal range 0.35…5.0 is a theoretical 14.3× span in linear RGB, not 5×. The usable span is much smaller because individual channels clip, `max_spread` rejects divergent channel gains, and the same global multiplier affects every material.

### Recommended representation

For each family:

1. Measure appearance per meaningful material region, not one global photo median.
2. Cluster variants in log-linear RGB/Lab plus material class and pattern identity.
3. Choose the cluster medoid as the anchor texture—not automatically the representative or lightest SKU.
4. Create one baseColor texture per cluster on the same geometry.
5. Share MR/normal only when the physical material is genuinely the same.
6. Apply a conservative per-material residual tint, ideally much narrower than 0.35…5.0.
7. Give genuine material/pattern outliers their own anchor or mesh asset.

Select the minimum number of anchors as a set-cover problem: an anchor covers a variant only if its residual gains stay inside validated limits, clipping remains negligible, hue error passes and protected materials remain unchanged.

A single GLB can contain several material/texture presets, but runtime support and the 1–2 MB limit must be checked. With 512–1024 WebP textures, two or three anchors may still fit. Otherwise publish separate light GLBs that duplicate geometry bytes but retain the same logical family. That is operationally simpler than overloading the tint model.

A flat albedo replacement is appropriate only for a uniform, separately masked material slot. It is not a general replacement for textured wood, patterned fabric or hardware-bearing atlases.

Hiding outliers is an acceptable temporary safety action, not the asset strategy.

### Existing-code implications

The current implementation is good as a gate, not a solution:

- [`tint_from_mesh()`](/home/pakar/igor/remlab/tools/scout/mesh_color_check.py:270) correctly computes gains in linear space and limits spread.
- [`recolor_variants_gate.gate()`](/home/pakar/igor/remlab/tools/scout/salad/recolor_variants_gate.py:63) prevents a representative recolour from newly harming variants.
- [`annotate_tint()`](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:2695) centralizes the runtime field.

But the gate’s `_mesh()` intentionally reduces the mesh to one RGB sample and discards part information. It therefore cannot predict “upholstery improved but legs/handles were damaged,” pattern mismatch, or roughness mismatch. [`surface_colour()`](/home/pakar/igor/remlab/tools/scout/mesh_color_check.py:334) is also an area-weighted global summary and should not drive appearance clustering by itself.

---

## 7. Recommended experiment order

1. **Correct the evaluation first.** Add perspective fitting and `pattern_grad_ncc`; ensure metrics run on the final compressed GLB.

2. **Run the already-planned Pixal3D end-to-end trial.** Do not create a hybrid yet.

3. **On five targeted products**, run:
   - Clean TRELLIS baseline.
   - TRELLIS texturing-only rerun.
   - TRELLIS + Hunyuan Paint with remesh disabled.
   - TRELLIS + Hunyuan Paint with default remesh as a diagnostic.
   - Pixal3D whole.

   Include the leaf dresser, printed/text product, thin-legged chair, multi-material product and glossy/glass item.

4. **Promote TRELLIS + Hunyuan Paint to all 30** if geometry changes are negligible and appearance wins. Your existing paint-only path makes this the cheapest meaningful hybrid.

5. **Prototype B only on planar distinctive ROIs.** First project the leaf-pattern facade, not the whole dresser. Compare raw projection, high-frequency-only projection and delighted projection under two lighting setups.

6. **Test MVPainter** only if Hunyuan repainting fails, changes geometry, or licensing is unsuitable.

7. **Attempt A last**, and only at latent level, if Pixal whole clearly wins appearance but loses shape. Do not start with cross-mesh UV copying.

8. **For families**, implement two-anchor material support on a few known wide-span families before changing multiplier bounds. Wider bounds will hide the underlying representation error.

---

## Uncertainties

- I did not have the actual dresser GLBs, photo, UV atlas or render frames; the visual conclusions are therefore based on your observation and pipeline architecture.
- One dresser cannot establish the relative geometry ranking of TRELLIS and Pixal.
- It is unproven that Hunyuan’s texture advantage on its own geometry transfers to cleaned TRELLIS geometry.
- `use_remesh=False` may expose UV-wrapper or open-surface failures.
- Pixal’s main branch is newer than the paper branch, so paper numbers do not directly validate the released TRELLIS.2-backed checkpoint.
- Final WebP/LOD compression may remove exactly the motif detail that distinguishes the variants.
- Salad cost will be dominated by image cold starts unless weights stay warm; pure inference cost should fit the stated range.

## Evidence that would change my recommendation

I would prefer Pixal3D whole if, across the patterned/thin-part subset, it matches clean TRELLIS silhouette/held-out geometry and wins `pattern_grad_ncc` plus human appearance preference.

I would drop Hunyuan repainting if `use_remesh=False` fails on more than a small minority, or if painting changes normalized silhouette IoU by more than about 0.01 or damages thin components.

I would elevate B to a standard production stage if it improves pattern score and human preference on at least roughly 80% of eligible planar ROIs, while relighting review finds no fixed shadow/highlight residue.

I would elevate A if Pixal exposes or you validate an external-shape texture-stage path that preserves TRELLIS geometry within numerical tolerance. A successful one-off surface-transfer demo would not be enough.

For family variants, I would retain a single-anchor multiplier only where material-region measurements show all variants are explainable by a low-clipping multiplicative transform. Global photo medians alone are not sufficient evidence.