You are an independent senior reviewer for a furniture-layout engine (remlab, B2C renovation/furnishing service; RU market first, UK next).

USER OBJECTIVE (owner, 12.11): in small bedrooms for a couple the engine currently drops BOTH bedside tables to keep the comfortable passage. Owner: "maybe only one side fits — ask how small rooms are best furnished".

TECHNICAL QUESTION:
How should a small double bedroom be furnished when two bedside tables + comfortable passages do not fit? Give a ranked degradation ladder (what to give up first) for a couple's bedroom, grounded in sources (RU and UK/EU interior-design guides, furniture makers, ergonomics references such as Neufert / ADM M4 / СП 54 if relevant). Consider: one bedside table on the free side; narrow (30–35 cm) or wall-hung bedside tables; shelf/ledge or sconce instead of a table; headboard with built-in shelf; bed against a wall (one-side access) for a couple — acceptable or not; smaller bed (140 vs 160); dropping the chest of drawers or wardrobe width before the bedside tables; minimum side passage for a couple's bed.

KNOWN FACTS / CONSTRAINTS:
- Example: room 450×293 cm, door 90, wardrobe, bed 160 (footprint ~171×212), comfortable passage target 75 from the door, bed side target 60 / tolerance 50 (ADR-0394, «обычное жильё»). With both bedside tables the path from the door narrows to 51 cm; engine level C keeps target passages without bedside tables.
- Engine and passport live in services/planner-solver/planner/bedroom.py, bedroom_allowances.py, passage_norms.py, rules services/planner-solver/rules/occupancy.json (distances_cm.clearances), bedroom.json, room templates services/planner-solver/rules/room-templates/ and .memory_bank/domain/room-templates.md. Inspect them to see what levels/degradation exist now (e.g. is there a level with ONE bedside table for a pair, codes NIGHTSTAND_NO_FIT, COUPLE_NO_SECOND_SIDE).
- Do not modify files.

Return: 1) recommended degradation ladder with numbers; 2) sources (URLs) for each number/claim; 3) how it maps onto the existing passport levels (what is missing — file:symbol); 4) risks (e.g. one table looks asymmetric, buyer expectations); 5) uncertainties. Answer in Russian, concise.
