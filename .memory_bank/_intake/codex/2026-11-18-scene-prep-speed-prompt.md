You are an independent senior software-engineering reviewer. Do not modify, create or delete files.

USER OBJECTIVE
Product owner wants the "photo" (Cycles render) of a furnished room to come back faster when a buyer changes one item (e.g. swaps the sofa) on /demo. Today a changed arrangement costs 25–40 s end-to-end; target ≈ 15 s. The GPU part (Blender on a rented RTX 4090, warm) is ≈ 10 s and is out of scope. The cold "scene preparation" on our DEV server (CPU, 16 cores, 29 GB RAM, shared with other jobs) is the target.

TECHNICAL QUESTION
How should cold scene preparation in `tools/scout/render_exec.py` (`_prepare`, `_prepare_fresh`, `_dump_cached`) be made substantially faster, safely? Rank the options by gain/risk and propose a concrete design.

KNOWN FACTS (measured 18.11, DEV under load ≈ 15 on 16 cores, so ×1.5 slower than usual; normal service time 9–12 s)
- `_prepare_fresh` runs two subprocesses in parallel per job: `tools/scout/cycles_probe/export_scene.py` (python) and `tools/scout/cycles_probe/demo_scene_dump.mjs` (node + headless Chromium, loads a built bundle of `demo_scene_entry.ts`).
- export_scene.py, cProfile, 15.9 s total: module imports ≈ 2.8 s (trimesh/scipy ≈ 1.7); `planner/scene.py:compile_scene` 3.1 s (raster_flat 2.2, _edge_cm 0.9, _point_in_convex 0.9); `mesh_render.load_parts` 2.7 s of which trimesh visual/material `.copy()` of textures ≈ 1.9 s; `opening_ir.paint_beyond` 2.1 s (single call); `draft_render._push_from_supports` 2.1 s; `save_tex` 1.1 s; `np.savez_compressed` 0.9 s; md5 0.8 s; PIL decode 1.6 s total.
- demo_scene_dump.mjs: 17 s total; its own log says "сцена собрана за 11.0 с" (scene build inside the page), the rest is Chromium start/page load (~4 s) and output (~2 s).
- Prepared-scene cache key `_prep_key` (hash of all *.py in three dirs + versions) and dump cache `_dump_cached` (hash of data.json + bundle + mode) already give 0 s on exact repeats; a changed arrangement misses both.
- Constraints: no IDs of rooms/items/tours in code; same result must be produced as today (frames must not change — byte-identical scene files or provably equivalent); DEV runs a live service (`remlab-render`, port 8600) that must not be destabilised; memory headroom is limited (other heavy jobs run under a slot limiter `tools/ops/heavy-slot.sh`); simple, testable changes preferred.

Ideas to evaluate (not a preference order — challenge them, add others):
- persistent pre-imported python worker (fork-server) for export_scene;
- persistent Chromium/page with the bundle loaded, reused across jobs; what in the page takes 11 s (GLB fetch/parse? shell build? solver?) and can parts be cached per apartment;
- avoid trimesh texture copies; cache `paint_beyond` per window/apartment; faster npz (no compression) and md5;
- incremental: reuse the previous variant's prepared scene and re-export only changed items;
- running prep for a buyer's change speculatively (e.g. on hover/selection) — product-side.

Inspect the repository directly (render_exec.py, export_scene.py, demo_scene_dump.mjs, demo_scene_entry.ts, draft_render.py scene3d_frame, opening_ir.py, planner/scene.py, mesh_render.py, render_jobs.py) and tests.

Return: 1) conclusion; 2) evidence with file paths/symbols; 3) risks and edge cases (stale state in persistent processes, memory, concurrency with two jobs, cache-key correctness, determinism); 4) alternatives; 5) recommendation with an ordered plan and expected seconds saved per step; 6) uncertainties; 7) what evidence would change your mind. Be critical; look for reasons the obvious solution could be wrong.
