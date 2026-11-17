You are an independent senior archviz / real-time rendering engineer. Do not modify files. Answer in Russian, ≤ 900 words, concrete settings and file paths; separate facts from assumptions; check claims on the web where useful (with sources).

USER OBJECTIVE (owner, 17.11): our free Blender Cycles render of a furnished apartment room must look as close as possible to the
AI photo (gpt-image) of the same room — CHEAPLY: walls, light, camera, post-processing — "anything that artificially makes it
more realistic". AI photo stays a paid option later.

IMAGES ATTACHED
1. `gpt-bed2-base.jpg` — AI photo of the bedroom (two views: top C1, bottom C2) produced from our 3D frame + product photos. Target look.
2. `v-cycles-best53-bed2-japandi-C1.jpg` — our Blender 5.3 Cycles render of the same room, view C1 (1536 px, 64 spp, CPU).

HARD CONSTRAINTS
- Furniture is NEVER changed: meshes, textures, materials as they are (ADR-0419). Decor (curtains, plaid, rug, lamps light, plants),
  room shell (walls, floor, ceiling, window, baseboard), lighting, camera and post-processing may change.
- Cost: render on GPU later (target 15–30 s/frame, ≈0.1 ₽); now CPU probe. Must be automatic for thousands of rooms (no manual art).
- No AI img2img that redraws furniture in the free tier.

CONTEXT IN REPO
- Probe: branch `worktree-cycles-1117` (`tools/scout/cycles_probe/render_cycles.py`, `demo_scene_dump.mjs`), worktree
  `.claude/worktrees/render-3d` (in progress: shared scene export + CC0 finish maps). Plan `.memory_bank/plans/render-3d-01.md`,
  audit `.memory_bank/_intake/codex/2026-11-17-render-3d-audit.md`.

QUESTIONS
1. Compare the two images: list the concrete visual differences that make ours read as "CG" (light, exposure/tonemapping, wall colour
   and texture, camera height/focal length/verticals, shadows/AO, textile, window/view, clutter, colour grading), ranked by impact.
2. For each: the cheapest automatic fix in Blender Cycles (exact settings: view transform AgX/Filmic + look, exposure, sun+sky/HDRI,
   light portals, emission for lamps, bevel shader node for hard edges on the SHELL, denoiser, compositor glare/vignette/grain/
   chromatic aberration/lens distortion, DOF, camera 1.2–1.5 m with vertical shift), render-time cost, and whether it also applies to
   the browser three.js /demo.
3. Top-5 changes giving most realism per unit of effort, in order, with acceptance check (what to compare between AI photo and render).
4. What CANNOT be closed cheaply without touching furniture (be honest), and what minimal decor additions matter most.
5. Risks: over-processing look, consistency across thousands of rooms, licences of HDRI/textures.
