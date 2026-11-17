You are an independent interior-design and 3D-rendering researcher. Answer in Russian. Do not modify files. Use web search for sources.

USER OBJECTIVE
remlab shows a furnished new-build apartment (Russia market, typical 2-room flats, rooms 9–20 m², ceilings 2.6–2.8 m) in a browser
3D viewer (/demo, three.js, phone) and in photoreal Blender Cycles renders. Furniture is real shop products and is never altered.
We control only the room shell: walls, floor, ceiling, accent walls, decor overlays. Styles in the product: скандинавский, современный,
минимализм, лофт, джапанди (неоклассика — catalog only). Rooms: гостиная, спальня (later kitchen, hall, kids).
Today every room has plain matte plaster + light oak floor; for лофт we just added one accent wall of red brick (CC0 ambientCG Bricks085)
behind the bed / sofa (rule «behind-focal»: bed → sofa → TV). Owner: brick render looks flat, «как обычно делают — не только кирпич;
проработай каждый стиль: особенности текстур стен; в спальнях, в гостиных».
Repo context: data/flat3d/finish-cc0.json (accentWalls.styles), data/flat3d/materials.json, tools/assets/material_from_cc0.py,
lib/configurator/accent.ts, contracts/configurator.ts.

TECHNICAL QUESTION
For each style × room (гостиная, спальня), what wall treatments are actually typical in real Russian/European new-build interiors
(designer projects 2023–2026, not clichés), and how should an automatic system choose them?
For each style give:
1. base walls (finish, sheen, colour range, texture scale) and whether an accent wall is typical at all;
2. 2–4 accent options ranked by how typical they are (e.g. for loft: brick — real/clinker tile/painted white brick; concrete / microcement;
   dark painted wall; wood slats …), where they go in a bedroom vs a living room, and which are a cliché to avoid;
3. physical parameters needed for a believable render: real module sizes (brick 250×65 + 10 mm joint, slat width/gap, panel moulding),
   relief depth, roughness, colour variation, and what makes it look fake (oversized pattern, uniform grout, no relief, visible tiling);
4. which CC0 sources have suitable PBR sets (ambientCG, Poly Haven — name concrete asset ids if you can verify them) and the minimum map
   set/resolution for Cycles vs for a phone (three.js);
5. rules to keep it honest and safe for a buyer: accent only one wall, not behind a window, not competing with the furniture colours,
   avoid in rooms < N m², contrast limits with the chosen furniture.
Also: should the accent be fixed per style or chosen per set (by furniture colours/materials), and should the buyer be able to switch it
(as an «upgrade» with a price — real finishing costs in RF)?

Return: a compact table style × room → base / accent options (ranked) / where / params / CC0 ids; then decision rules as data
(JSON-like sketch fitting finish-cc0.json); risks; what you are unsure about; sources (links).
