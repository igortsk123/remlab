You are an independent senior reviewer. Answer in Russian, concisely. Do not modify files.

USER OBJECTIVE
Owner wants the "Сделать фото" button on /demo and in tours to produce OUR Blender Cycles render of the user's current arrangement
(the same 2 camera angles as today's photo) instead of the AI photo; once the render is shown, the button becomes "Улучшить фото",
which sends that render plus product photos into the existing AI improve pipeline (instead of the browser 3D frame). Same everywhere,
checked from a phone.

Draft plan: .memory_bank/plans/photo-render-first-01.md. Existing code: tools/scout/draft_service.py (job queue, ETA, paid gate,
registry), tools/scout/draft_jobs.py, tools/scout/improve_mode.py, tools/scout/cycles_probe/render_cycles.py, demo_scene_dump.mjs,
lib/viewer3d/scene-export.ts, tools/scout/flat215-demo/index.html (photo button, /api/render, /api/trial/<id>/photo).
Facts: render service runs on the DEV VM (16 cores shared by 3 VMs; heavy jobs via tools/ops/heavy_slot.py); Cycles CPU today ~4–5 min
per 1536 px frame at 64 samples on 4 threads, OIDN on; no GPU (rented Salad GPU pilot possible later). Furniture must not be altered.

TECHNICAL QUESTION
1. Critique the plan: gaps, wrong order, missing failure modes (concurrency, cache invalidation, queue under load, timeouts, phone UX
   while waiting minutes, abuse/rate limits on a free CPU job, tours vs /demo differences, trace/registry).
2. Where should the scene for Blender come from — page-posted scene export (user's edits) vs server rebuilding from arrangement data?
   Security/trust of a page-posted scene (it drives a CPU job and file fetches).
3. Realistic CPU time targets for phone-vertical and desktop frames with adaptive sampling + denoise; is ≤90 s/frame plausible; when
   GPU becomes necessary.
4. Is AI "improve" over a Cycles render likely better or worse than over the browser frame (fidelity to products, hallucination)?
   How to A/B it cheaply.
5. Pre-render default arrangements nightly — worth it? Cache key design.
Inspect the repository directly. Return: verdict · plan fixes (ordered) · risks · answers 2–5 · uncertainties.
