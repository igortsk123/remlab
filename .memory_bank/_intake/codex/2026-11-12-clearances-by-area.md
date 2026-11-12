You are an independent senior reviewer with domain knowledge of residential interior ergonomics. Do not modify, create or delete files. Answer in Russian.

## USER OBJECTIVE
remlab places furniture into real apartment rooms (RU market first, then UK) from catalog items, using room templates (bedroom, living room,
later hall, kids room, kitchen-living). The owner (12.11.2026) wants ONE standard for building templates, written as the only correct variant,
and says: "for small bedrooms some passages may be sacrificed; find RU and UK standards and the allowances for small and large areas — there
is a norm, and there are exceptions due to area; somewhere a passage is consciously narrower, and that is normal for a certain area".

## TECHNICAL QUESTION
Build a table of clearances in residential rooms: "norm / conscious minimum (allowed with a reason) / never less", by room area or width band,
with sources for each number. Cover at least:
- bedroom: free strip along the long side of the bed (couple — both sides; single/guest — one side), at the foot of the bed, in front of a hinged
  wardrobe, a sliding wardrobe, a chest of drawers (drawer pull-out), radiator under the window vs bed foot / furniture;
- walking route from the room door to the window (opening it, curtains, ventilation) and to each side of the bed; door swing zone;
- living room: main route through the room, route between zones, sofa ↔ coffee table, in front of TV stand, to the window, around a dining table
  (chair pull-out + passage behind);
- area/width bands: e.g. < 9 m², 9–12, 12–16, > 16 m² (or better bands if the sources suggest them, e.g. by clear width of the room).
Sources to check (verify, do not invent): RU — СП 54.13330.2022 (residential buildings), СП 59.13330 (accessibility) where relevant, old
normative recommendations for furniture layout of apartments (e.g. ВСН / пособия к СНиП 2.08.01), Нойферт; UK — Approved Document M4(1)/M4(2)/M4(3)
(bed clearances 750/1000 mm etc.), Lifetime Homes criteria, Nationally Described Space Standard (bedroom areas/widths), London Housing Design
Guide / Mayor's Housing Design Standards (furniture schedules and clearances), NHBC; international practice (Neufert, Time-Saver Standards,
NKBA for dining/kitchen). For each number say whether it is mandatory (regulation), a design guide, or practice, and for which case (wheelchair vs general).

## KNOWN FACTS (repository)
- Current product norms: `services/planner-solver/rules/occupancy.json` `distances_cm` — `bed_side_passage` 75 (note cites Lifetime Homes / M4(2)
  750 mm, Neufert 70–90), bed foot 60, `wardrobe_hinged_front_min` 90, `dresser_front`, `passage_main` 91, `_route_classes` (primary 90–107,
  secondary 76–91, object access 60–75, `tight_fallback` 46–61 with growing penalty), `passage_absolute_min_tight`, `hall_passage_min` 85 (note:
  СП 54 clause NOT confirmed), `door_swing`. Inspect them and say which are well-founded and which are not.
- Observed (bedroom engine sheets, 14 rooms): a 75 cm route from the door to the window / second bed side fails in 13 of 14 rooms; typical narrow
  spots: 68–69 cm between bed foot and a radiator under the window (demo bedroom 597×293); 34–73 cm bed ↔ wardrobe/dresser (450×293); UK guest
  rooms 210×370 — 28 cm wardrobe ↔ bed, 295×370 — 50 cm bed ↔ dresser.
- Owner rule: decisions must scale to all rooms, no one-off fixes; degradation only as whole compositions.

Return:
1. the table (rows = clearance, columns = norm / conscious minimum / never less, by area/width band), each cell with a source and its status;
2. which reductions for small rooms are defensible (e.g. one bed side for a single, foot 50–60 at a radiator) and which are never acceptable (door
   swing blocked, window unreachable, drawers can't open);
3. how to express it in our rules: per-band thresholds vs one norm + named exceptions; what to show the buyer when an allowance is used;
4. critique of our current numbers in occupancy.json;
5. uncertainties: what you could not confirm and which sources would settle it.
Be critical; distinguish wheelchair-accessibility norms from general-needs ones.
