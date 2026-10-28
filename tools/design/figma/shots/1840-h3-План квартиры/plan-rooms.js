// Страница «План квартиры» (помощник 3, 26.10): после build-all — разложить импортированный SVG плана на понятные слои.
// Зачем: SVG приходит «как картинка» — контур квартиры одним многоугольником и комнаты группами, где подписи лежат
// поверх прямоугольника. Дизайнеру удобнее «Комната — Кухня» (рамка с заливкой и стенами) с подписями ВНУТРИ,
// наружные стены — отрезками, окна/двери — по именам. Заодно проверка check.js не видит «текст на соседе».
// Вид не меняется: координаты, цвета и толщины — те же, что дал импорт SVG. Начертание: 500 → Medium, 600 → Semi Bold (как на сайте).
const page = figma.root.children.find((p) => p.name === 'План квартиры');
await figma.setCurrentPageAsync(page);
for (const st of ['Regular', 'Medium', 'Semi Bold', 'Bold']) await figma.loadFontAsync({ family: 'Inter', style: st });
const near = (a, b) => Math.abs(a - b) < 0.5;
const rgb = (p) => p && p.color ? [p.color.r, p.color.g, p.color.b].map((v) => Math.round(v * 255)).join(',') : '';
const done = [];
const plans = page.findAll((n) => n.type === 'FRAME' && n.name === 'Значок' && n.children.some((c) => c.type === 'GROUP'));
for (const svg of plans) {
  svg.name = 'План (рисунок)';
  // 1) контур квартиры: многоугольник -> отрезки «Наружная стена» (заливка белая и так закрыта комнатами)
  const poly = svg.children.find((c) => c.type === 'VECTOR' && c.fills.length && rgb(c.fills[0]) === '255,255,255' && c.width > svg.width * 0.5);
  if (poly) {
    const vs = poly.vectorNetwork.vertices, segs = poly.vectorNetwork.segments;
    const walls = figma.createFrame(); walls.name = 'Наружные стены'; walls.fills = []; walls.clipsContent = false;
    svg.insertChild(svg.children.indexOf(poly), walls); walls.x = 0; walls.y = 0; walls.resize(svg.width, svg.height);
    for (const s of segs) {
      const a = vs[s.start], b = vs[s.end];
      const mx = Math.min(a.x, b.x), my = Math.min(a.y, b.y);
      const v = figma.createVector();
      v.vectorPaths = [{ windingRule: 'NONE', data: `M ${a.x - mx} ${a.y - my} L ${b.x - mx} ${b.y - my}` }];
      v.strokes = poly.strokes; v.strokeWeight = poly.strokeWeight; v.strokeAlign = 'CENTER'; v.strokeCap = 'SQUARE'; v.fills = [];
      walls.appendChild(v); v.x = poly.x + mx; v.y = poly.y + my; v.name = 'Наружная стена';
    }
    poly.remove();
  }
  // 2) комнаты: группа -> рамка «Комната — <имя>» (заливка и стены прямоугольника), подписи внутри; внутренняя обводка -> «Выделение»
  for (const g of svg.children.filter((c) => c.type === 'GROUP')) {
    const idx = svg.children.indexOf(g);
    const shapes = g.children.filter((c) => c.type !== 'TEXT').sort((p, q) => q.width * q.height - p.width * p.height);
    const texts = g.children.filter((c) => c.type === 'TEXT');
    if (!shapes.length) continue;
    const frames = [];
    let parent = svg, px = 0, py = 0;
    shapes.forEach((sh, i) => {
      const f = figma.createFrame();
      f.name = i === 0 ? 'Комната — ' + (texts[0] ? texts[0].characters : '') : 'Выделение';
      f.fills = sh.fills; f.strokes = sh.strokes; f.strokeWeight = sh.strokeWeight; f.strokeAlign = 'CENTER'; f.clipsContent = false;
      f.resize(Math.max(0.01, sh.width), Math.max(0.01, sh.height));
      if (i === 0) svg.insertChild(idx, f); else frames[frames.length - 1].appendChild(f);
      f.x = sh.x - px; f.y = sh.y - py; px = sh.x; py = sh.y;
      frames.push(f);
    });
    const inner = frames[frames.length - 1];
    const ix = shapes[shapes.length - 1].x, iy = shapes[shapes.length - 1].y;
    texts.forEach((t, i) => {
      const tx = t.x, ty = t.y;
      inner.appendChild(t); t.x = tx - ix; t.y = ty - iy;
      const w = t.fontName.style;
      if (/→/.test(t.characters)) t.fontName = { family: 'Inter', style: 'Semi Bold' };
      else if (i === 0 && w === 'Regular') t.fontName = { family: 'Inter', style: 'Medium' };
      t.name = i === 0 ? 'Название' : (/м²|m²/.test(t.characters) ? 'Площадь' : (/→/.test(t.characters) ? 'Действие' : 'Статус'));
    });
    for (const sh of shapes) sh.remove();
    if (!g.removed) g.remove();
    done.push(frames[0].name);
  }
  // 3) окна и двери — по цвету линии
  const lines = svg.children.filter((c) => c.type === 'VECTOR');
  const blue = lines.filter((c) => rgb(c.strokes[0]) === '90,155,212');
  for (const c of lines) {
    const col = rgb(c.strokes[0]);
    const win = blue.some((b) => near(b.x, c.x) && near(b.y, c.y) && near(b.width, c.width) && near(b.height, c.height));
    c.name = col === '90,155,212' ? 'Окно' : col === '255,255,255' ? (win ? 'Окно — проём в стене' : 'Дверь — проём в стене') : col === '200,120,60' ? (c.width > 0.5 && c.height > 0.5 ? 'Дверь — дуга открывания' : 'Дверь — полотно') : c.name;
  }
}
return { plans: plans.length, rooms: done };
