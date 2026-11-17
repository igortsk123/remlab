Independent reviewer, Russian, concise, do not modify files.

OBJECTIVE (owner TG 1523, verbatim): «рендер сразу на видеокарту, это в конвейере должно быть. Желательно по запросам API — RunPod,
fal — сравнить; если у нас есть активные Salad-машины (где меши генерятся) — генерим рендер на них вперёд; если нет — идём с запросом
в API, чтобы человек не ждал. Постоянно гонять Salad пока нет смысла; в будущем одну-несколько машин будем держать для мешей».
Context: plan .memory_bank/plans/photo-render-first-01.md (Blender Cycles render of user's arrangement, 2 angles, then optional AI
improve); Salad mesh pool: .memory_bank/core/mesh-pool.md, .memory_bank/domain/mesh-pool-ops.md, tools in tools/scout/ (mesh pool code);
render script tools/scout/cycles_probe/render_cycles.py (CPU today, ~4–5 min/frame 1536 px 64 spp on 4 threads).

PRICES (fetched today from official pages):
- RunPod Serverless: RTX 4090 $1.34/h, RTX 5090 $1.89/h, L4/A5000/3090 $0.75/h, L40S $1.89/h; billed from worker start to handler ready
  (model/scene load) + idle timeout (default 5 s); image pull not billed while scaled down; FlashBoot advertised; per-second rounding.
- Modal: L4 $0.000222/s (~$0.80/h), A10 $0.000306/s, L40S $0.000542/s; load time billed; default 60 s scaledown idle billed; $30/mo free
  credits on Starter; custom images OK; GPU preemptible.
- fal Serverless: only datacenter GPUs listed (H100 $4.50/h, RTX PRO 6000 $4.00/h…); setup + idle billed; deploy needs account approval.
- SaladCloud: RTX 4090 $0.16–0.44/h by priority; allocation/download/start free; but node allocation + image pull takes minutes.

QUESTIONS
1. Routing design: «live Salad node with Blender → priority render; else serverless API» — is it sound? How to know a Salad node is live
   and has capacity (mesh jobs in progress), preemption mid-render, and keeping one image with both Hunyuan and Blender vs two images.
2. Which serverless provider for the fallback and which GPU class (Cycles OptiX on 4090 vs L4)? Expected per-frame GPU time for an
   interior 1536×1117 at 64–128 spp with OIDN; expected cold start for a ~2–3 GB Blender image; resulting ₽ per pair of frames and
   p50/p95 wait. Mark estimates vs facts.
3. Scene transfer: meshes/textures are on our DEV/prod (GLB per product, finish maps). Cache strategy on serverless (network volume /
   baked image / per-request download), size, and security (signed URLs, no secrets in image).
4. What must the measurement pilot (≤ $5) contain to decide? Ordered steps for the plan.
Inspect the repository for the mesh pool controller and how Salad nodes are started/stopped. Return: verdict · routing design ·
provider/GPU recommendation with numbers · scene transfer · pilot steps · risks · uncertainties.
