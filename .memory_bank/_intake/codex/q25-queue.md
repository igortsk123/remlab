You are an independent senior software-engineering reviewer.

Independently analyse the following problem. Do not assume another agent's implementation or hypothesis is correct.

USER OBJECTIVE (владелец remlab, 28.08.2026):
Зафиксировать методику отбора товаров на 3D-меши и встроить её в конвейер АВТОМАТИЧЕСКИ:
1) очередь «что отдавать на меши» формируется сама (генерация мешей — ВСЕГДА на SaladCloud, отдельный план mesh-bulk-salad-hunyuan уже в работе другой сессией: свой образ Hunyuan3D 2.1, R2-хранилище, PBR-приёмка, пилот 481 товаров из сетов);
2) правило: сеты собираются ТОЛЬКО из товаров, у которых есть годный меш;
3) полученные меши проходят анализ ориентации: 3d-orienter+flipper (ICML 2025, локально CPU ~5с/меш, уже поднят и прогнан на 35 мешах) + наш геометрический классификатор сидячих mesh_front;
4) что не уверено — VLM (qwen3-vl с признаковым промптом, уже отобран бенчем 10/10);
5) спорное — проверка человеком на ЕДИНОЙ странице с быстрыми кнопками «выбери фронтальное положение».

TECHNICAL QUESTION:
Спроектировать недостающие звенья конвейера и найти дыры в предлагаемой архитектуре. Конкретно:
а) mesh_queue: как правильно вычислять «кому нужен меш» (роли слотов сетов × ворота пригодности: in_stock, живое фото, enrichment quality>=0.65 — это даёт ~4900 направленных + столики/пуфы/декор из сетов) и как дифить против уже сделанного (манифесты в R2, версионирование: фото-хеш, генератор, параметры)? Где должна жить очередь и state machine статусов SKU (needs_mesh → pending → ready/failed → orient_auto/vlm/review → oriented)?
б) правило «сеты только из товаров с мешами»: как вводить БЕЗ обвала сетов (мешей сейчас ~35 из ~4900)? Этапность shadow→hard? Где точка встройки (sets_incremental._slot_ok уже проверяет replace-registry)?
в) очередь ориентации: orienter+flipper на DEV-VM cron (CPU, 5с/меш) или на Salad вместе с генерацией? Контракт хранения вердикта: raw_to_canonical quaternion + версии (orienter ckpt, FRONT_VERSION, VLM) + status + equivalence — куда его писать, чтобы обе сессии не конфликтовали (соседняя владеет manifest.json ассета)?
г) страница человеческой проверки: спорные SKU, 4 рендера (0/90/180/270), кнопка-клик. Прод — Next.js на сервере (remont-lab.online), статика /test/ через Caddy, дев-VM отдельно. Как правильно сделать write-path вердиктов (API route в Next.js + таблица Postgres? токен? как дев-конвейер забирает вердикты?) — минимально, но не времянкой.
д) определение «спорного»: конфликт методов (orienter vs mesh_front, 90°+), VLM не уверен, VLM противоречит обоим. Верна ли лексикографика: сидячие — mesh_front авторитет, orienter второй свидетель; корпусные — orienter + фото-сверка; VLM только предлагает; человек — финальный авторитет?

KNOWN FACTS / CONSTRAINTS:
- Прогон 35 мешей: orienter p>=0.9 на сидячих (10/11 совпали с mesh_front, 1 конфликт 90°), корпусные p=0.2-0.6 (честный abstain); канонический фронт orienter = наш yaw 180 (замерен).
- Codex q24 уже принят: GLB не перезаписывать, raw_to_canonical quaternion версионированный, авто-180° от VLM запрещён, большой prediction set у симметричных — норма.
- Правила владельца: fal и Trellis НЕ используем; только Hunyuan 2.1 на Salad. Секреты в .env/_secrets. Salad-план (другая сессия) владеет: tools/scout/salad/*, mesh_pilot.py, mesh_gate*.py, mesh_make.py, mesh_render.py — мои правки этих файлов должны быть минимальны или согласованы.
- Мой скоуп файлов: sets_incremental.py (правило слота), refresh_daily.sh (шаг очереди уже есть за MESH_QUEUE=1), новые mesh_queue.py / orient_pipeline.py, mesh_front.py (готов), страница ревью + write-path.
- DEV-VM: 6 ядер, 9.8 GiB RAM, e2e только в CI, deploy.sh с VM не запускать; прод-деплой штатный ./deploy.sh с сервера-стороны разрешён.
- Human review: владелец готов кликать десятки, не сотни. Симметричные роли (пуф без спинки и т.п.) — NONDIRECTIONAL, фронт не нужен.

Inspect the repository directly (tools/scout/, services/planner-solver/, .memory_bank/plans/mesh-bulk-salad-hunyuan.md, .memory_bank/plans/viz-mesh-orientation.md), including sets_incremental.py, refresh_daily.sh, mesh_front.py, mesh_gate.py, enrich_bridge.py.

Do not modify, create, or delete files.

Return:
1. your conclusion; 2. evidence (file paths/lines); 3. risks and edge cases; 4. alternatives worth considering; 5. what you recommend and why; 6. uncertainties; 7. what evidence would change your conclusion.
Be critical. Look specifically for reasons the obvious solution could be wrong. If information is insufficient, say exactly what is missing rather than guessing.
