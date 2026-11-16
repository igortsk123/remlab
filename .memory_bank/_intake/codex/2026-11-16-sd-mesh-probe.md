You are an independent senior engineer reviewing an experiment design. Do not modify files. Answer in Russian.

USER OBJECTIVE
The product shows a buyer a photoreal "photo" of a furnished room. Today: our 3D scene with REAL furniture meshes
(generated from catalog product photos) is rendered in the browser; that render + a sheet of catalog product photos +
JSON with measured product colours go to `openai/gpt-image-2.5-sunburst` (edit endpoint, Vercel gateway) — ≈ 2.9 RUB per
frame, ~30 s. The owner asks whether a much cheaper SD-class pipeline (SDXL / FLUX with ControlNet depth/canny/tile, or
low-strength img2img; via fal.ai or our own Salad GPU pool) applied ON TOP OF the mesh render could replace it.

HISTORY (verify in repo)
- Aug 2026: SDXL + ControlNet (`fal-ai/sdxl-controlnet-union`) was tried when the scene had only boxes / pasted product photos,
  not meshes: hallucinated furniture on empty walls, boxes read as other objects; img2img 0.35 not real, 0.62 recomposes
  (`.memory_bank/lessons/viz-render.md` lessons 62, 65, 87, 88; ADR-0063 in `.memory_bank/decisions/adr-0051-0100.md`).
- Meshes + gpt-image "improve only" won later (ADR-0128). Blind pairs 07.11: current model won 18/19 vs Seedream, FLUX.3 Klein,
  gpt-image-2.6 (`.memory_bank/plans/photo-model-rebench-01.md`).
- The photo pass currently also corrects wrong mesh colours using the product photos (`.memory_bank/domain/viz-fidelity-playbook.md`).

DRAFT EXPERIMENT: `.memory_bank/plans/viz-sd-mesh-probe-01.md` — read it.

QUESTIONS
1. Is the experiment worth running, and is its design able to give a decisive answer? What would you change?
2. Best concrete pipeline to test first (model, conditioning: depth from the 3D scene vs estimated depth, canny, tile;
   strength; resolution; IP-Adapter/reference for product colour?) and which hosted endpoints exist for it (fal.ai etc.).
3. How to measure product fidelity objectively (per-item colour vs catalog photo, shape, extra openings), and what pass
   threshold vs the current model is sensible.
4. Risks and failure modes (colour of meshes is often wrong — the current pass fixes it; two-view consistency; text/logos;
   safety filter black frames; 1024 px limits), and cheap mitigations.
5. Realistic cost per frame and latency for the candidates, and whether self-hosting on Salad (RTX 4060 Ti 16 GB,
   $0.08–0.14/h, billed while the node runs) could ever beat hosted per-image prices at our volume (tens to hundreds of frames/day).
Give evidence with file paths; separate facts from assumptions; say what would change your conclusion.
