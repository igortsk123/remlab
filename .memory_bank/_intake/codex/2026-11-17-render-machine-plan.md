You are an independent senior infrastructure reviewer. Read-only: do not modify files.

USER OBJECTIVE (owner, 17.11, voice, translated):
The /demo and buyer tours must show a Blender Cycles render of the buyer's arrangement on a button press ("Сделать фото",
2 camera angles), then optionally an AI "improve" step on top. The owner wants a SEPARATE GPU machine for renders on SaladCloud
(not the mesh group), on a high-priority tier so a machine is always found; choose RTX 3090 vs 4090 by measured speed. Turn it on/off
by a Telegram button in the remlab bots on all three servers (common, algor, pakardev); when the machine has warmed up and is
ready, the owner gets an automatic Telegram message. Reuse everything we learned making the mesh pool start fast (image layering,
weights baked/fetched, warm-up). Also look for cheaper alternative render APIs: ~3 RUB per pair of frames feels expensive, and
waiting for a machine to come up is bad. RunPod is rejected by the owner (slow start, machine hunting too).

TECHNICAL QUESTIONS:
1. Architecture for the render machine on Salad: image (Blender + OptiX, size, layering for fast pull), how a job reaches it
   (Salad Job Queue vs HTTP via Container Gateway vs our existing queue proxy `tools/scout/salad/queue_proxy.py`), how scene assets
   reach it (manifest with hashes + signed short-lived URLs, worker cache), how results come back, health/readiness ("warm") signal.
2. On/off control: a small CLI in the repo that starts/stops the Salad render group and reports state; the Telegram button calls it on
   any of the three servers (each runs its own bot plugin; there is a patch script that adds commands — assume we can call a local
   script). Guardrails: money cap per day, auto-stop after N minutes idle, deadman if the controller dies, no interference with mesh
   groups and their stoppers (`money_guard.py`, `idle_guard.sh`, `infra/server/salad-deadman.py`, `rules/salad-groups.json`).
   Where should the source of truth for "render machine on/off" live so three servers do not fight?
3. "Ready" notification: what exactly counts as ready (container running ≠ Blender warmed: first render compiles kernels/BVH);
   should we run a tiny warm-up render on start?
4. Fallback when Salad preempts the node: CPU render on DEV (`tools/scout/cycles_probe/render_cycles.py`, ~4–5 min/frame now);
   how the job router (`tools/scout/draft_service.py`, `draft_jobs.py`, `draft_guard.py`) should pick executor and re-route mid-job.
5. Speed test plan 3090 vs 4090: what to measure (pull, start, warm-up, per-frame at 1536×1117 64 spp + OIDN, both angles in one
   Blender process), budget ≤ $5, stop rules.
6. Cheaper alternatives (research the web if you can; give prices with source URLs and dates): per-second-billed serverless GPU
   with fast cold start (e.g. Modal, Replicate, Beam, Cerebrium, Vast.ai serverless, fal), Blender render farms with API
   (SheepIt, RebusFarm, GarageFarm, etc.), or a cheaper local option (render quality knobs: fewer samples + denoiser, lower res for
   phone, EEVEE instead of Cycles). Compare cost per pair and time-to-first-frame including cold start vs a Salad machine kept on
   (3090 ≈ $0.20/h, 4090 ≈ $0.44/h high priority). Rough expected demand: tens of render pairs per day in the pilot.

KNOWN FACTS / CONSTRAINTS:
- Mesh pool docs: `.memory_bank/core/mesh-pool.md`, `.memory_bank/core/mesh-run.md`, `.memory_bank/domain/mesh-pool-ops.md`,
  `.memory_bank/domain/mesh-run-playbook.md` (warm-up lessons: weights from HF/CDN failed on half the nodes → baked; 26 GB image
  pull took 29 min on a fresh 3090; Salad does not bill pulling). Code: `tools/scout/salad/*` (Dockerfiles, queue_proxy.py,
  queue_run.py, worker.py, idle_guard.sh, recreate_group.py, migrate_groups.py), `infra/server/salad-deadman.py`.
- Render plan: `.memory_bank/plans/photo-render-first-01.md` (section «Видеокарта», owner corrections TG 1585/1596). Previous
  Codex answer: `.memory_bank/_intake/codex/2026-11-17-render-gpu-route-answer.md`.
- `render_cycles.py:109` forces CPU today. Scene export: `lib/viewer3d/scene-export.ts`, `tools/scout/cycles_probe/demo_scene_dump.mjs`.
- Secrets live only in env files on servers; never in images or the repo. The VPN node on the prod host must not be touched.
- DEV CPU is shared (16 cores for all VMs, RAM 29 GB) — no more hardware coming.

Return: 1) recommended architecture and plan steps (who does what, order, acceptance checks); 2) evidence with file paths/lines;
3) risks and edge cases (preemption mid-frame, double start from two bots, cost runaway, stale scene assets, cold image cache);
4) alternatives with a cost table; 5) your recommendation and why; 6) uncertainties; 7) what would change your mind. Be critical.
Answer in Russian, concise.
