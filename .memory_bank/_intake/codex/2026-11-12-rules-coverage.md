You are an independent senior reviewer for remlab (B2C furnishing service). Answer in Russian, concise, with file:symbol evidence.

USER OBJECTIVE (owner, 12.11): "if tomorrow I upload a new floor plan on the landing (/try), the layout must be created by ALL worked-out rules" — the same rules that apply on the demo apartment (/demo, flat215) and «Этажи».

TECHNICAL QUESTION:
Inventory the rules/guards that shape the result on /demo and check, for each, whether it is applied on the path of a NEW upload (app/try → POST /api/trial → tools/floorplan/worker.py → tools/floorplan/conveyor.py → tools/scout/trial_demo.py (living room) / tools/scout/trial_bedroom.py (bedrooms) → tools/scout/trial_bundle.py → tour route app/try/[id]/tour/... with lib/trial/tour-bundle.ts).
Rule families to check at least:
- passage/clearance norms (services/planner-solver/rules/occupancy.json distances_cm.clearances, passage_norms.py, bedroom_allowances.py, ADR-0394 ordinary housing);
- room templates and degradation levels (services/planner-solver/rules/room-templates/*.json, bedroom.py:_solve_groups, compose_bedroom.py);
- hall rules (hall_checks.py, room-templates/hall.json) — are halls furnished at all on the upload path?;
- kitchen/bathroom — furnished or not;
- colour guard mcg-v2 (mesh_color_check.py, room_bindings.py:measured_colour, flat215_demo.py:annotate_tint, feeds hiding wrong-colour variants);
- TV stand hang height (lib/viewer3d/scene-extras.ts, draft_render.py:HUNG_CABINET_ROLES), chandelier, rugs, wall pictures;
- bank of sets / style selection, own-mesh gate (mesh_ready.py), product feeds for «Заменить»;
- headboard orientation guard, window/radiator rules, door swing;
- page version: tours pin a demo release (ensureJobRelease / pinRelease) — what a new upload gets vs. old tours.

KNOWN FACTS: the demo is built by tools/scout/flat215_demo.py → publish_demo.sh; tours reuse the demo page (tour-as-demo, ADR-0372). Old tours are re-issued with tools/floorplan/reissue.py.

Inspect the repository directly. Do not modify files.
Return:
1) table: rule → where it lives (file:symbol) → applied on /demo? → applied on new upload? (evidence) → gap;
2) gaps ranked by buyer impact;
3) the cheapest way to guarantee "one rule set for all plans" (shared module vs. copied logic; a test that fails when demo and upload paths diverge);
4) uncertainties.
Be critical: look for logic copied into flat215_demo.py but not into trial_* (or vice versa), constants duplicated in TS and Python, and rules gated by flags that are on only for the demo.
