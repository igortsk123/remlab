You are an independent senior engineer / technical artist. Do not modify files. Answer in Russian, ≤ 900 words, facts with file paths, separate facts from assumptions.

USER OBJECTIVE
Product: buyer sees a furnished apartment (catalog furniture as real 3D meshes, browser three.js scene on /demo and tours).
Owner's new idea: give EVERY listing (partner developer with thousands of listings) FREE photoreal still renders made on our
server (Blender Cycles), shown on the phone as images; the paid AI "photo" (gpt-image edit, ≈3.3–6.5 RUB per 2 views) only when
the user presses a button. Plus a series of 3D improvements so that ALL decor of the set (vases, plants, small items, pictures,
lamps, curtains, textiles) appears in 3D automatically — both for people in the interactive 3D and for the render.

FACTS (verify in repo)
- Probe 17.11 (branch worktree-cycles-1117, scripts tools/scout/cycles_probe/*): scene exported by the same code that builds the
  server 3D frame (`tools/scout/draft_render.py`, `tools/scout/scene_mesh.py`), full model.glb meshes (2048² textures), Blender 4.5
  Cycles on 8 CPU cores: 340–450 s per 2048×1489 frame at 100–128 samples + OIDN. Result: frame matches the 3D frame, soft window
  light, but an EMPTY white room — no curtains/pictures/lamps/rug texture. Of 30 decor items of the set, 3 visible in the 3D frame,
  17 without meshes (lesson 689 in `.memory_bank/lessons/viz-render.md`).
- /demo already places some decor and abstract curtains/plaid in 3D (commit af1d88d5: `lib/configurator/textile.ts:isTextileDecor`,
  `tools/scout/flat215-demo/index.html` isCloth3d/in3dDecor/liveDecor).
- Mesh generation pipeline and Salad GPU pool: `.memory_bank/core/mesh-pipeline.md`, `core/mesh-pool.md`, `domain/mesh-pool-ops.md`.
- Decor rules / placement: `core/demo-planner.md`, `core/lr-composition.md`, `core/bedroom.md`, `core/pipeline-order.md`.

QUESTIONS
1. Is "free Blender render for every listing + paid AI photo on demand" sound? What would make the free render look like a
   real photo rather than "CG"? Rank realism levers by impact/cost (HDRI + window portal, AgX/exposure, bevel, fabric sheen,
   floor/wall materials, DoF, light from fixtures, clutter/decor density, Blender 5.x features, denoiser choice).
2. Decor in 3D automatically: what is missing in our pipeline (catalog → set → placement → mesh → scene) so that every decor item
   of a set appears in 3D? Which items should be cheap procedural/flat stand-ins (pictures = textured plane, curtains, rugs) vs
   generated meshes; where should placement rules live; how to keep one source for browser 3D and Blender.
3. Compute: CPU on our dev VM vs Salad GPU (RTX 4060 Ti class, $0.08–0.14/h) vs others for thousands of listings × rooms × 2
   views; realistic seconds per frame at 1024–1536 px with denoise; batch architecture; cache invalidation when a set changes.
4. Risks (licenses of HDRI/textures, Blender in containers, memory, phone delivery size, consistency with the interactive 3D).
5. Your recommended first 3 steps with acceptance criteria.
