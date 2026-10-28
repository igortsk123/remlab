// Страница «Образцы» (помощник 3, 26.10): после relabel.js строка «что это» у образца пола стала в одну строку — под ней
// осталась пустая полоса. Поднимаем содержимое секции на ту же дистанцию «подпись → первые подписи вариантов», что у секции
// «Кружок цвета», и уменьшаем высоту секции на столько же.
const page = figma.root.children.find((p) => p.name === 'Образцы');
await page.loadAsync();
const gapOf = (sec) => { const cap = sec.children.filter((n) => n.type === 'TEXT').sort((a, b) => a.y - b.y)[0]; const rest = sec.children.filter((n) => n !== cap); return { cap, rest, gap: Math.min(...rest.map((n) => n.y)) - (cap.y + cap.height) }; };
const ref = gapOf(page.children.find((n) => n.type === 'SECTION' && n.name === 'Кружок цвета'));
const floor = page.children.find((n) => n.type === 'SECTION' && n.name === 'Образец пола');
const f = gapOf(floor);
const d = Math.round(f.gap - ref.gap);
if (d > 0) { for (const n of f.rest) n.y -= d; floor.resizeWithoutConstraints(floor.width, floor.height - d); }
return { refGap: ref.gap, floorGap: f.gap, moved: d };
