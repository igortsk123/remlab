You are an independent senior software-engineering reviewer. Independently analyse the problem below.
Do not assume any other agent's hypothesis is correct. Do not modify, create or delete files.

USER OBJECTIVE
Real-estate floor-plan sheets (RU developers, UK agents) often show several drawings on one sheet ("Этаж 1" /
"Этаж 2", "Ground Floor" / "First Floor", "Outbuildings", "Garage"), and a printed area under each drawing
(e.g. "Ground Floor 65.2 sq m"), sometimes also a printed total. The product owner wants a safeguard: compare the
area of EACH floor/drawing that our pipeline reconstructed against the area printed for that floor, so that a
missed or merged room on one floor is caught instead of silently producing wrong metres.

TECHNICAL QUESTION
Design this per-floor (per-panel) area check in the existing /try floor-plan pipeline:
1. Where in the pipeline should it run, and on what data (which per-panel area, in which measure — GIA vs sum of
   rooms — so that it is comparable with what is printed)?
2. How to associate each printed area with the right panel (VLM returns `areas: [{label, m2}]` without points;
   titles come with points; panels come from titles or from VLM contours or mask pieces)?
3. Tolerance / threshold, and what the result of a mismatch should be: only a flag in the result, a message to
   the agent (size-confirmation UI), rooms of that floor moved to `awaiting_check`, or something else. Consider
   each scale status (`verified`, `listing`, `area`, `not_verified`).
4. Should a per-floor area ever be used as a per-floor SCALE source, or only as a check? Why?
5. Edge cases and failure modes (single-drawing sheets, total only, sum-of-parts, "excl. garage", balconies /
   outdoor share, sq ft, duplicated titles, panels that are pieces of one drawing, VLM misreads).
6. How to test it (existing benches / gold sets / unit tests) and how to make sure it does not regress existing
   sheets.

KNOWN FACTS (from reading the code; verify yourself)
- Pipeline entry: `tools/floorplan/pipeline.py` (scale selection `scale_of`, `_scale_labels`, `area_scale`,
  `area_rerun_ppm`, `outdoor_share`, `_area_m2_of`, room flags `_room_flags`); geometry: `tools/floorplan/bench.py:run_plan`
  (panels by titles / VLM contours, per-panel scale fit, `gia_m2` per panel; a bench-only per-panel area comparison
  near `log['areas']`), `tools/floorplan/fpcore.py:fit_scale`.
- VLM prompts and schema: `tools/floorplan/vlm.py` (`labels3`/`labels4` return `rooms`, `areas`, `titles`).
- Printed totals: `tools/floorplan/listing.py:sheet_area` (total label wins, otherwise sum of parts with flag
  `area_sum_of_parts`), `pick_area` (sheet vs listing text, conflict > 5 % → not used).
- Rooms waiting for size confirmation: `tools/floorplan/conveyor.py` (`awaiting_check`), `lib/trial/size-ask.ts`.
- Project rules: no special cases in code for specific tours/items/rooms (IDs outside `rules/**` and tests are
  forbidden); every rule must work for all sheets (RU and UK, /demo, all tours, future uploads); new UI strings
  come in RU/EN pairs; generated files are rebuilt by the pipeline, never edited by hand.

Inspect the repository directly (implementation, tests under `tools/floorplan/`, benches, git log of these files).

Return:
1. your conclusion (recommended design);
2. evidence with file paths and symbols/lines;
3. risks and edge cases;
4. alternatives worth considering;
5. what you recommend and why (including threshold values with justification);
6. uncertainties / assumptions;
7. what evidence would change your conclusion.
Be critical. Look specifically for reasons the obvious solution could be wrong, including cases where the check
would produce false alarms on correct sheets. Answer in Russian.
