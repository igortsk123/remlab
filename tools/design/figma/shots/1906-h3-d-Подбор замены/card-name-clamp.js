// Страница «Подбор замены» (помощник 3, 26.10 19:45): название товара в карточке — не больше 2 строк, как на сайте.
// Зачем: на сайте `.card .nm{line-height:1.32;max-height:44px;overflow:hidden}` (tools/scout/flat215-demo/index.html:463) —
// видно только 2 строки, остальное срезано. Выгрузка берёт полный текст (3–4 строки) и ставит его по центру прежнего блока,
// поэтому в Desktop название наезжает на фото сверху и на цену снизу (check: textHit 32).
// Делаем: возвращаем верх блока туда, где он на сайте (y + (h − 2 строки)/2), и обрезаем текст до 2 строк с «…».
// Работает в обоих файлах; там, где название и так ≤ 2 строк (Mobile), ничего не меняет.
const page = figma.root.children.find((p) => p.name === 'Подбор замены');
await page.loadAsync();
const done = [];
for (const t of page.findAllWithCriteria({ types: ['TEXT'] })) {
  if (t.getSharedPluginData('remlab', 'css') !== 'div.nm') continue;
  const lh = t.lineHeight.unit === 'PIXELS' ? t.lineHeight.value : t.lineHeight.unit === 'PERCENT' ? t.fontSize * t.lineHeight.value / 100 : t.fontSize * 1.32;
  const two = 2 * lh;
  if (t.height <= two + 1) continue;
  await figma.loadFontAsync(t.fontName);
  // верх блока на сайте — под фото карточки с зазором 4 (gap карточки); если фото нет — центр прежнего блока
  // (формула «по центру» верна только когда Фигма переносит в столько же строк, сколько браузер: у «Маре-Мини» 3 против 4)
  const mid = t.y + t.height / 2;
  const photos = t.parent.children.filter((n) => n !== t && n.getSharedPluginData('remlab', 'css') === 'img' && n.y + n.height <= mid);
  const top = photos.length ? Math.max(...photos.map((n) => n.y + n.height)) + 4 : t.y + (t.height - two) / 2;
  t.textAutoResize = 'HEIGHT';
  t.textTruncation = 'ENDING';
  t.maxLines = 2;
  t.y = Math.round(top * 10) / 10;
  done.push([t.id, t.characters.slice(0, 30), Math.round(t.y), Math.round(t.height)]);
}
const g = (k) => figma.root.getSharedPluginData('remlab', k);
const AF = Object.getPrototypeOf(async function () {}).constructor;
const chk = await new AF('P', g('check'))({ page: 'Подбор замены' });
return { fixed: done.length, sample: done.slice(0, 4), counts: chk.counts };
