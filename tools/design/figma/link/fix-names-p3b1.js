// design-02 П3б (T-20261103-08, помощник p3b1, книга Desktop, страница «Бюджет» 7:23): 9 испорченных имён вариантов
// (начинались с «=»; список — shots/0311-1324-inv/inventory.json → malformed_variant_names.Desktop) переименованы так же,
// как в Mobile (П2б-1, наборы 58:247 / 58:527): «…выбрана часть, закреплено при прокрутке» → «выбрана часть (закреплено)»;
// у «Пузыря пояснения» лишняя часть «Бюджет=…, <состояние>» → «Состояние=<состояние>». Id вариантов и вид не меняются.
const PAGE_ID = '7:23';
const NAMES = {
  '29:50':  'Язык=RU, Бюджет=общий бюджет, Состояние=выбрана часть (закреплено)',
  '29:93':  'Язык=RU, Бюджет=общий бюджет, Состояние=выбрано больше сертификата (закреплено)',
  '29:165': 'Язык=EN, Бюджет=бюджет по частям, Состояние=выбрана часть (закреплено)',
  '29:221': 'Язык=EN, Бюджет=бюджет по частям, Состояние=выбрано больше сертификата (закреплено)',
  '29:444': 'Язык=RU, Место=главная, Состояние=выбрана часть',
  '29:448': 'Язык=RU, Место=главная, Состояние=выбрано больше сертификата',
  '29:491': 'Язык=EN, Место=главная, Состояние=выбрана часть',
  '29:503': 'Язык=EN, Место=главная, Состояние=выбрано больше сертификата',
  '29:515': 'Язык=EN, Место=главная, Состояние=улучшения не входят',
};
const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const out = { renamed: [], sets: {} };
for (const [id, name] of Object.entries(NAMES)) {
  const v = await figma.getNodeByIdAsync(id);
  if (!v || v.type !== 'COMPONENT') throw new Error('нет варианта ' + id);
  if (v.name !== name) { v.name = name; out.renamed.push(id); }
}
for (const id of ['29:241', '29:517']) {
  const s = await figma.getNodeByIdAsync(id);
  out.sets[id] = { bad: s.children.filter(v => v.name.startsWith('=')).map(v => v.id),
    props: Object.entries(s.componentPropertyDefinitions).map(([k, d]) => k + (d.variantOptions ? '[' + d.variantOptions.join('/') + ']' : '')) };
}
return out;
