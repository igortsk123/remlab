You are an independent senior reviewer of 3D interior visualization for a consumer product. Answer in Russian, concisely. Do not modify files.

USER OBJECTIVE
remlab (Russia market) shows a buyer of a new-build apartment their rooms furnished with REAL shop products (price list, links):
(a) live browser 3D on a phone (three.js, /demo) — attached images 1 and 3 (375×667 phone screenshots of the live site today);
(b) a photoreal render of the same scene in Blender Cycles on CPU (no GPU yet) — attached image 2 (loft bedroom, 1536 px, 64 samples,
~4–5 min/frame on 4 cores). Furniture meshes are auto-generated from a single shop photo (Hunyuan3D-class image-to-3D), one material per
mesh; we never alter furniture shape/colour (honesty). Room shell (walls, floor, windows, curtains, plants, lamps, radiators) is ours.
Owner asks: «is this the best achievable for the price/quality, or not?»

Cost context: mesh generation is a one-off per product on rented GPU (Salad); live 3D is free per view; Cycles render is CPU-only now;
there is also an AI-photo button (image model over a 3D frame, ~3.7–6.5 ₽ per photo). Plans in repo: .memory_bank/plans/render-materials-01.md
(fabric/wood material layers by class + leg masks), .memory_bank/plans/wall-finishes-01.md (walls per style), render-3d-01 (GPU pilot).

TECHNICAL QUESTION
1. Look at the three images critically as a buyer and as an interior visualizer. What are the 5–8 most visible quality problems in each
   medium (3D phone; Cycles render), ranked by impact on buyer trust?
2. Is the current quality close to the best achievable at this cost level (image-to-3D meshes, CPU render, phone WebGL), or are there
   cheap levers with large gain still unused? For each lever: expected gain, cost (money/time), risk to honesty (furniture must stay as sold).
   Consider: lighting/exposure/tone mapping, AO/contact shadows, bed textiles, mesh texture resolution, material layers, camera/lens,
   denoise, GPU rendering, AI-photo pass over the render (img2img with low strength), Gaussian splats, etc.
3. What do comparable products achieve (IKEA Kreativ, Planner 5D, Roomstyler, Coohom/Kujiale, Homestyler) and at what cost?
4. Recommendation: top-3 next steps in order, and what we should NOT spend on.
Inspect the repository where useful (lib/viewer3d/, tools/scout/cycles_probe/render_cycles.py, plans named above).

Return: verdict (one paragraph) · problems per medium (ranked) · levers table (gain/cost/risk) · comparison · top-3 · uncertainties.
