You are an independent senior engineer / applied-ML researcher. Do not modify files. Answer in Russian.

USER OBJECTIVE: furniture GLB meshes (Hunyuan3D 2.1 shape+paint from a single product photo, Salad GPU) must show the product's real shade. Owner: "many meshes have the wrong shade" (lighter/darker/greyer than the photo). He asked to research a model or method that RECOLOURS AN ALREADY FINISHED MESH to match the product photo while PRESERVING texture detail (wood grain, fabric weave, patterns). Plain flat colour fill or a global multiply kills the texture and is rejected.

KNOWN FACTS (repo + measurements):
- Plan with history: .memory_bank/plans/mesh-color-03.md (and core/mesh-color.md). Paint wrapper: tools/scout/salad/pipeline.py. Colour checks: tools/scout/mesh_color_check.py, rules/mesh-color-guard.json. Experimental lightness correction of the 6 multiview images before bake: tools/scout/salad/mv_color_cal.py (job field _mv_cal).
- Past: shifting the input photo brightness made it worse — the multiview net pulls lightness towards the middle.
- Typical defect: mesh baseColor ΔL 9–30 from the photo's product region; hue mostly right, lightness/chroma wrong. Also some meshes where a surface is the network's background grey (separate plan, ignore here).
- We have: product photo(s) with background, the finished GLB (UV-mapped baseColor + MR), Blender/Cycles on CPU and on a 4090, budget is small (cents per mesh OK).

QUESTIONS:
1. Which methods/models (2024–2026, open-source preferred, with links) can re-texture or re-colour an existing UV-mapped mesh from a reference image while keeping high-frequency detail? E.g. texture-space colour transfer (per-material histogram / Reinhard / optimal transport in Lab with detail preserved as residual), differentiable-render optimisation of a low-frequency colour field against the photo (nvdiffrast / pytorch3d) with the original texture as high-frequency detail, image-guided re-texturing models (TEXTure, Text2Tex, Paint3D, SyncMVD, MV-Adapter, Hunyuan3D-paint re-bake with a colour-corrected multiview, TEXGen, etc.), IP-Adapter style conditioned re-paint. Which keep the existing texture vs regenerate it?
2. For our case (single photo, product region known, finished mesh), what is the most robust and cheapest pipeline? How to get the photo-to-mesh correspondence (render the mesh from the estimated photo camera; segmentation of the product; handle shading/white balance of the photo vs albedo).
3. How to separate albedo from photo lighting so we do not bake highlights/shadows into the target colour (intrinsic decomposition models, simple heuristics)?
4. Acceptance check: what to measure (ΔE on matched regions in rendered view vs photo, detail preservation metric e.g. high-pass energy/SSIM of the luminance residual), and failure modes (multi-material products, photo colour cast, wrong segmentation).
5. Inspect the repo to say where such a step would plug in (after paint, as a post-process on GLB; or inside the paint wrapper before bake) and what existing code can be reused.

Return: conclusion; evidence (paths/symbols, papers/repos with links); risks; alternatives; recommendation and why; uncertainties; what would change your mind. Be critical; say explicitly which options are hype vs proven.
