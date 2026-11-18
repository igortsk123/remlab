You are an independent senior 3D/ML engineer. Do not modify, create or delete files. Use web search for current (Nov 2026) model
releases and benchmarks; cite sources with dates.

USER OBJECTIVE
remlab turns furniture product photos (one main shop photo, sometimes 2–5 angles) into textured GLB meshes for a web 3D room
planner and Blender (Cycles) photo renders. Current generator: Hunyuan3D 2.1 self-hosted on SaladCloud GPU containers
(code `tools/scout/salad/`, memory `.memory_bank/core/mesh-pipeline.md`, `.memory_bank/domain/viz-fidelity-playbook.md`,
`.memory_bank/core/mesh-color.md`). Known pains: colour drift vs photo (we now run a recolor step), grey/flat tops, empty back
views, geometry of thin parts (legs, handles), heavy meshes. Owner wants to test other generators: 20 identical products per
model, compare by renders from all sides under light. Owner shared a leaderboard (Elo): Hi3D 3.0 #1 1366, Meshy 7.1 #2 1298,
Tripo H3.1 #4 1261. Earlier owner noted TRELLIS.2 (detail, PBR, heavy) and Pixal3D (colour good, geometry weaker).

QUESTION
1. Candidate list, split: (A) open weights runnable on our Salad GPU containers (e.g. TRELLIS.2, Hunyuan3D newer versions,
   Step1X-3D, TripoSG/TripoSF, Hi3DGen, Direct3D-S2, Sparc3D, SPAR3D, Pixal3D, others current in Nov 2026); (B) API-only
   commercial (Hi3D, Meshy, Tripo, Rodin, others). For each: latest version, licence for commercial use, single vs multi-image input,
   texture quality (PBR? baked colour fidelity), geometry quality, typical VRAM, time per mesh, output size/polycount, cost per mesh
   (Salad GPU-hours or API price), known weaknesses on furniture.
2. Recommend a shortlist of 4–6 to test (with reasoning), and which leaderboard is trustworthy for our use (single photo of
   furniture, colour fidelity matters).
3. Fair test protocol: product selection (20 across roles: sofa, chair, wardrobe, table, lamp, bed, dresser, vase; easy/hard),
   same input crops as our pipeline (`tools/scout/salad/hybrid_mask.py`), metrics we can compute automatically (colour ΔE vs photo
   per view, silhouette IoU vs photo, polycount, file size, empty-view check like `tools/scout/salad/view_guard.py`), render
   setup (existing Blender renders in our pipeline — find the script), and the owner visual sheet. Budget guard: test batch 2–3
   products first.
4. Integration cost: what changes in `tools/scout/salad/` (Docker image, worker, output contract `model.glb`) per candidate.

Return: conclusion; table of candidates; shortlist; protocol; integration notes; risks; uncertainties. Russian is fine.
