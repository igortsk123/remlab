// design-02 П3а (T-20261103-06): hug в Desktop сузил метки «по размеру»/«Изменено вами» и «Ссылку» на 2–5 px (Inter уже
// шрифта сайта). Не откат: ширина остаётся «по тексту», но не уже прежней — minWidth = ширина до hug. Вид — как был.
const PAGE_ID = '7:2';   // Плашки; для «Ссылки» — '7:98'
const MIN = { '7:2': { '43:155': 98, '43:159': 79, '43:163': 65, '43:167': 80, '43:174': 131, '43:178': 131 },
              '7:98': { '43:54': 77, '43:58': 60 } };
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = [];
for (const [id, w] of Object.entries(MIN[PAGE_ID])) {
  const v = await figma.getNodeByIdAsync(id);
  v.minWidth = w;
  if (PAGE_ID === '7:98') v.primaryAxisAlignItems = 'CENTER'; // у «Ссылки» текст был по центру рамки 77/60 — держим глифы на месте
  out.push(id + ' ' + v.primaryAxisSizingMode + ' w=' + v.width + ' min=' + v.minWidth);
}
return out;
