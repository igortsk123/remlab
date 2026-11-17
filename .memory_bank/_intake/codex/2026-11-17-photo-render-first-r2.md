You are an independent senior reviewer and co-planner. Answer in Russian. Do not modify files.

This is round 2. Round 1 (your critique) is in .memory_bank/_intake/codex/2026-11-17-photo-render-first-answer.md; the draft plan is
.memory_bank/plans/photo-render-first-01.md. The owner asked: «передай Codex все мысли — мои и твои — и сделайте общий план, по
которому пойдёшь и всё закончишь». Produce ONE joint, executable plan.

OWNER'S WORDS (verbatim, voice, 17.11):
- TG 1510: «вместо „сделать фото“ запускать процесс не GPT, а рендер. И как только рендер готов, тоже так же выбираем два ракурса,
  как сейчас. Как только рендер готов, показывает рендер, а кнопку менять на „улучшить фото“. … И это же фото отправлять в GPT, уже
  отрендеренное, вместе с товарами. То есть не нашу модель изначально отправлять, а уже отрендеренную, вместе с товарами. Я не думаю,
  что это будет хуже. Тем же пайплайном, как и было. … должно быть везде одинаково и надо проверять как это будет с телефона».
- TG 1514: «раньше, когда мы фотографию делали, кнопка „сделать фото“ пропадала, теперь она должна просто быть „улучшить фото“, и в
  режиме фото подумай, куда её разместить, как это лучше интерфейс обыграть, чтобы всё было окей и логично, не ломая текущую логику».
- TG 1518: «на выходе мне надо, чтобы всё везде работало одинаково, демо и не демо. Любой тур, который заново пройду процесс, чтобы
  работал тоже. Логика одинаковая. Сначала делаем рендер, дальше улучшаем фото».
- TG 1513 (about bedding looking like a crumpled mass): «это же меш… системно смотреть… история, адекватная на разных мешах; нельзя
  подстраивать под конкретную спальню». (Context: material layers plan .memory_bank/plans/render-materials-01.md.)
- Owner rules: design-first (new UI look shown as phone/desktop screenshots before rollout); no special cases per tour/item in code;
  RU/EN pairs for new strings; everything through the conveyor (generated files are rebuilt by programs, never hand-edited).

DIRECTOR'S (my) THOUGHTS:
- I accept your round-1 order: contract → separate Cycles job type with its own limits → routing/quotas (tours) → UI states → cache.
- Wait time is the owner's decision; I will measure first (p50/p95 on real rooms under heavy_slot) and then offer: CPU with an honest
  wait vs a rented-GPU pilot (Salad, money = owner's word).
- Phone: today the page renders a wide 1536×1117 frame and crops for display. Option: render only the visible crop region (Cycles
  border/region or a narrower camera) for phone requests — does that preserve "the same two angles"? Is it worth it?
- Scene source: the service already receives the arrangement (room + items with role/x/y/rot/w/d/h) for the AI path. I lean to the
  hybrid you described: page sends edits + camera poses; server canonicalises from allowed apartment/catalog data and builds the
  Blender scene with the same TS exporter (lib/viewer3d/scene-export.ts) run server-side, no client URLs.
- Tours: free render must not spend AI quota; render allowed by the same photo_ok/dims trust gate as today; auto-photos of a tour
  (ADR-0416) — owner question (keep AI-from-3D or render→improve).
- No silent fallback to AI. If render fails/times out — honest message + "try again"; AI improve only from a finished render.
- Workforce: 2 workers (Sonnet), one edits index.html at a time; DEV VM shared cores; prod app on a separate server; render service on
  DEV (systemd remlab-render). Deploy is automatic after green CI on main.

DELIVERABLE
A joint plan as ordered steps (≤ 9), each with: goal, files/modules, done-criteria (testable), who (worker 1 / worker 2 / director),
dependencies, and what can run in parallel. Mark the 1–3 points that need the OWNER's decision, phrased as simple questions with a
recommended answer. Include the measurement step design (which rooms, sizes, samples, threads, what numbers decide CPU vs GPU), the
A/B of AI-over-render vs AI-over-browser-frame, the UI state machine (Сделать фото → рендерится → рендер → Улучшить фото → улучшается
→ улучшено; edits during waiting), and the tour path (new tour from scratch must work end-to-end). Note where you disagree with my
thoughts, with evidence (file:line).
