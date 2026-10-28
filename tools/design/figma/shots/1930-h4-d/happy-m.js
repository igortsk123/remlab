// «Счастливый путь» (помощник 4): шаги основного сценария снимками со страницы «Экраны RU» той же книги.
// Картинки — клон заливки исходного фрейма (тот же imageHash), «Экраны RU» только читаются.
const CFG = {"dev": "телефон", "w": 375, "h": 812, "per": 6, "r": 20, "fs": 17, "sub": "Главный сценарий покупателя на телефоне: от ссылки до доплаты по сертификату. Шаги идут слева направо, ряд за рядом.", "steps": [["01 Главная: первый экран", "Открывает ссылку: квартира и сертификат"], ["07 Главная: другая вкладка стиля", "Выбирает стиль на вкладках"], ["05 Главная: прокрутка к комнатам", "Листает вниз к «Плану квартиры»"], ["08 План квартиры", "На плане выбирает гостиную"], ["09 Окно варианта: подсказка", "Комната открылась, с подсказкой"], ["10 Окно варианта: 3D", "Переключает на 3D и осматривается"], ["12 Шторка: наполовину", "Тянет шторку вверх — список вещей"], ["15 Окно: выбран предмет", "Нажимает на вещь — она в списке"], ["21 Карточка товара", "Карточка: фото, размер, цвет, цена"], ["22 Лист замены", "Жмёт «Заменить» — похожие вещи"], ["24 Сообщение: «Заменено»", "Выбирает замену — «Заменено»"], ["25 Окно после замены", "Комната с новой вещью, сумма новая"], ["18 Окно: Фото", "Смотрит реалистичное фото"], ["27 Избранное: окошко имени", "Жмёт ♡ и называет вариант"], ["28 Главная: есть избранное", "На главной — строка «Избранное»"], ["29 Экран «Избранное»", "Открывает «Избранное» — свои варианты"], ["32 Полоса бюджета: сертификат покрывает часть", "Полоса: сколько покрыл сертификат"], ["41 Диалог: доплата, подтвердить?", "Дороже сертификата — подтверждает доплату"]]};
const PAGE = 'Счастливый путь';
const src = figma.root.children.find((p) => p.name === 'Экраны RU');
await figma.setCurrentPageAsync(src);
const byName = {}; for (const n of src.children) byName[n.name] = n;
const miss = CFG.steps.filter((s) => !byName[s[0]]).map((s) => s[0]);
if (miss.length) return { err: 'нет фреймов', miss };
// переменные цвета
const vars = await figma.variables.getLocalVariablesAsync('COLOR');
const V = (name) => vars.find((v) => v.name === name);
const paint = (name, fb) => { const v = V(name); const p = { type: 'SOLID', color: fb }; return v ? figma.variables.setBoundVariableForPaint(p, 'color', v) : p; };
const C_BG = paint('Фон/Страница', { r: 0.984, g: 0.973, b: 0.953 });
const C_TXT = paint('Текст/Основной', { r: 0.161, g: 0.145, b: 0.141 });
const C_SEC = paint('Текст/Второстепенный', { r: 0.47, g: 0.443, b: 0.424 });
const C_BR = paint('Бренд/Основной', { r: 0.69, g: 0.416, b: 0.29 });
const C_LINE = paint('Граница/Обычная', { r: 0.906, g: 0.898, b: 0.894 });
for (const st of ['Bold', 'Medium', 'Regular']) await figma.loadFontAsync({ family: 'Inter', style: st });
// страница: новая, сразу после первой («Как пользоваться» / Page 1); старую свою — пересобрать
let page = figma.root.children.find((p) => p.name === PAGE);
if (!page) { page = figma.createPage(); page.name = PAGE; }
figma.root.insertChild(1, page);
await figma.setCurrentPageAsync(page);
for (const n of [...page.children]) n.remove();
const W = CFG.w, H = CFG.h, PER = CFG.per, GX = 140, GY = 150, PAD = 120;
const NUM_H = 52, TXT_Y = 60, SCR_Y = 104, CELL_H = SCR_Y + H;
const rows = Math.ceil(CFG.steps.length / PER);
const gridW = PER * W + (PER - 1) * GX;
const root = figma.createFrame();
root.name = 'Счастливый путь — ' + CFG.dev;
root.fills = [C_BG];
const title = figma.createText(); title.fontName = { family: 'Inter', style: 'Bold' }; title.fontSize = 32; title.characters = 'Счастливый путь'; title.fills = [C_TXT];
const sub = figma.createText(); sub.fontName = { family: 'Inter', style: 'Regular' }; sub.fontSize = 18; sub.characters = CFG.sub; sub.fills = [C_SEC];
root.appendChild(title); root.appendChild(sub); title.x = PAD; title.y = 80; sub.x = PAD; sub.y = 80 + 48;
const TOP = 80 + 48 + 28 + 64;
const cellXY = (i) => ({ x: PAD + (i % PER) * (W + GX), y: TOP + Math.floor(i / PER) * (CELL_H + GY) });
const cells = [];
for (let i = 0; i < CFG.steps.length; i++) {
  const [fname, say] = CFG.steps[i]; const s = byName[fname];
  const { x, y } = cellXY(i);
  const cell = figma.createFrame(); cell.name = 'Шаг ' + (i + 1); cell.fills = []; cell.clipsContent = false;
  root.appendChild(cell); cell.x = x; cell.y = y; cell.resize(W, CELL_H);
  const num = figma.createText(); num.name = 'Номер'; num.fontName = { family: 'Inter', style: 'Bold' }; num.fontSize = 44; num.characters = String(i + 1); num.fills = [C_BR];
  const t = figma.createText(); t.name = 'Что делает человек'; t.fontName = { family: 'Inter', style: 'Medium' }; t.fontSize = CFG.fs; t.characters = say; t.fills = [C_TXT]; t.textAutoResize = 'WIDTH_AND_HEIGHT';
  const scr = figma.createFrame(); scr.name = 'Экран'; scr.resize(W, H); scr.cornerRadius = CFG.r; scr.clipsContent = true;
  scr.fills = JSON.parse(JSON.stringify(s.fills));
  scr.strokes = [C_LINE]; scr.strokeWeight = 1; scr.strokeAlign = 'OUTSIDE';
  scr.setSharedPluginData('remlab', 'screen', s.name + ' | ' + s.id + ' | Экраны RU');
  cell.appendChild(num); cell.appendChild(t); cell.appendChild(scr);
  num.x = 0; num.y = 0; t.x = 0; t.y = TXT_Y; scr.x = 0; scr.y = SCR_Y;
  cells.push({ cell, t, scr, s, x, y });
}
// стрелки: в ряду — вправо по середине экрана; на переносе — вправо, вниз в просвет, влево, вниз, вправо к первому шагу ряда
const arrows = [];
const mk = async (pts, name) => {
  const v = figma.createVector(); v.name = name; root.appendChild(v);
  const minX = Math.min(...pts.map((p) => p[0])), minY = Math.min(...pts.map((p) => p[1]));
  await v.setVectorNetworkAsync({
    vertices: pts.map((p, k) => ({ x: p[0] - minX, y: p[1] - minY, strokeCap: k === pts.length - 1 ? 'ARROW_EQUILATERAL' : 'ROUND', cornerRadius: k > 0 && k < pts.length - 1 ? 20 : 0 })),
    segments: pts.slice(1).map((_, k) => ({ start: k, end: k + 1 })), regions: [],
  });
  v.x = minX; v.y = minY; v.strokes = [C_BR]; v.strokeWeight = 3; v.strokeJoin = 'ROUND';
  arrows.push({ v, pts });
};
const midY = (i) => cellXY(i).y + SCR_Y + H / 2;
for (let i = 0; i + 1 < cells.length; i++) {
  const a = cellXY(i), b = cellXY(i + 1);
  if (Math.floor(i / PER) === Math.floor((i + 1) / PER)) {
    await mk([[a.x + W + 24, midY(i)], [b.x - 24, midY(i)]], 'Стрелка ' + (i + 1) + ' → ' + (i + 2));
  } else {
    const gapY = a.y + CELL_H + GY / 2, rx = a.x + W + 60, lx = b.x - 60;
    await mk([[a.x + W + 24, midY(i)], [rx, midY(i)], [rx, gapY], [lx, gapY], [lx, midY(i + 1)], [b.x - 24, midY(i + 1)]], 'Стрелка ' + (i + 1) + ' → ' + (i + 2) + ' (новый ряд)');
  }
}
root.resize(PAD * 2 + gridW, TOP + rows * CELL_H + (rows - 1) * GY + 120);
root.x = 0; root.y = 0;
// проверка: тексты в одну строку и в ширину шага; шаги не налезают друг на друга; стрелки не задевают шаги; картинки на месте
const R = (n) => n.absoluteBoundingBox;
const inter = (a, b) => Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 0.5 && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 0.5;
const segHit = (p, q, r) => { const x0 = Math.min(p[0], q[0]) - 1.5, x1 = Math.max(p[0], q[0]) + 1.5, y0 = Math.min(p[1], q[1]) - 1.5, y1 = Math.max(p[1], q[1]) + 1.5; return inter({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, r); };
const rootR = R(root);
const problems = [];
for (const c of cells) {
  if (c.t.height > CFG.fs * 1.6) problems.push(['текст в 2 строки', c.cell.name, c.t.characters]);
  if (c.t.width > W) problems.push(['текст шире экрана', c.cell.name, Math.round(c.t.width)]);
  const f = c.scr.fills[0], g = c.s.fills.find((x) => x.type === 'IMAGE');
  if (!f || f.type !== 'IMAGE' || !g || f.imageHash !== g.imageHash) problems.push(['картинка', c.cell.name]);
}
for (let i = 0; i < cells.length; i++) for (let j = i + 1; j < cells.length; j++) if (inter(R(cells[i].cell), R(cells[j].cell))) problems.push(['наложение шагов', i + 1, j + 1]);
for (const a of arrows) for (const c of cells) for (let k = 0; k + 1 < a.pts.length; k++) {
  const p = [a.pts[k][0] + rootR.x, a.pts[k][1] + rootR.y], q = [a.pts[k + 1][0] + rootR.x, a.pts[k + 1][1] + rootR.y];
  if (segHit(p, q, R(c.cell))) problems.push(['стрелка задевает шаг', a.v.name, c.cell.name]);
}
for (const n of [title, sub]) for (const c of cells) if (inter(R(n), R(c.cell))) problems.push(['заголовок на шаге', c.cell.name]);
for (const a of arrows) for (const n of [title, sub]) for (let k = 0; k + 1 < a.pts.length; k++) {
  const p = [a.pts[k][0] + rootR.x, a.pts[k][1] + rootR.y], q = [a.pts[k + 1][0] + rootR.x, a.pts[k + 1][1] + rootR.y];
  if (segHit(p, q, R(n))) problems.push(['стрелка на заголовке', a.v.name]);
}
const outside = [...cells.map((c) => c.cell), ...arrows.map((a) => a.v), title, sub].filter((n) => { const r = R(n); return r.x < rootR.x || r.y < rootR.y || r.x + r.width > rootR.x + rootR.width || r.y + r.height > rootR.y + rootR.height; }).map((n) => n.name);
return { page: page.id, pageIndex: figma.root.children.indexOf(page), root: root.id, size: [root.width, root.height], steps: cells.length, arrows: arrows.length, problems, outside, maxText: Math.max(...cells.map((c) => Math.round(c.t.width))) };
