// design-02 П3а (T-20261103-06): копия link-room-card.js под книгу Desktop — связывание «Карточки комнаты»: рамки «как кнопка» → экземпляры базовых компонентов.
// Правка НА МЕСТЕ: набор и его варианты не пересоздаются (id сохраняются, экземпляры дизайнера не теряют связь).
// Повторный запуск безопасен: рамки ищутся по метке sharedPluginData remlab/css, уже заменённые — экземпляры (пропуск).
// Одна страница на вызов. Для другой страницы/набора — поменять PAGE_ID, SET_ID, PAIRS.
//
// PAIRS: css — метка рамки (из сборщика); base — набор базового; variant — как выбрать вариант базового по имени
//   варианта составного (здесь — по «Язык»; Состояние базового = «Обычное»/«не отмечено»); name — имя слоя-экземпляра;
//   expose — показать свойства вложенного экземпляра в панели составного (TEXT «Текст», вид кнопки);
//   bool — BOOLEAN-свойство набора-составного, к которому привязать видимость экземпляра (null — нет).
const PAGE_ID = '9:28';             // Desktop → «Комната»
const SET_ID = '25:86';             // «Комната/Карточка комнаты»
const PAIRS = [
  { css: 'button.btn.cta',  base: '43:10',  variant: { RU: '43:4',   EN: '43:8'   }, name: 'Кнопка «Открыть»', expose: true,  bool: null },
  { css: 'button.iconbtn',  base: '43:49',  variant: { RU: '43:40',  EN: '43:47'  }, name: 'Поделиться',       expose: false, bool: { prop: 'Поделиться', def: true } },
  { css: 'button.hm-heart', base: '25:105', variant: { RU: '25:91',  EN: '25:99'  }, name: 'Сердечко',         expose: false, bool: { prop: 'Сердечко',   def: true } },
];

const page = await figma.getNodeByIdAsync(PAGE_ID);
await figma.setCurrentPageAsync(page);
const set = await figma.getNodeByIdAsync(SET_ID);
if (!set || set.type !== 'COMPONENT_SET') throw new Error('нет набора ' + SET_ID);
const propKey = (name) => Object.keys(set.componentPropertyDefinitions).find(k => k.replace(/#[^#]*$/, '') === name);
const out = { replaced: [], created: [], removed: [], props: {}, skipped: [], mismatch: [] };

// BOOLEAN-свойства набора (до привязки)
for (const p of PAIRS) if (p.bool) {
  let k = propKey(p.bool.prop);
  if (!k) k = set.addComponentProperty(p.bool.prop, 'BOOLEAN', p.bool.def);
  out.props[p.bool.prop] = k;
}

for (const v of set.children) {
  const lang = /Язык=EN/.test(v.name) ? 'EN' : 'RU';
  for (const p of PAIRS) {
    const olds = v.findAll(n => n.type === 'FRAME' && n.getSharedPluginData('remlab', 'css') === p.css);
    if (!olds.length) { out.skipped.push(v.name + ': нет рамок ' + p.css); continue; }
    const base = await figma.getNodeByIdAsync(p.variant[lang]);
    for (const old of olds) {
      const parent = old.parent, idx = parent.children.indexOf(old);
      const auto = parent.layoutMode && parent.layoutMode !== 'NONE';
      const st = { x: old.x, y: old.y, w: old.width, h: old.height, visible: old.visible, pos: auto ? old.layoutPositioning : null,
        lsh: auto ? old.layoutSizingHorizontal : null, lsv: auto ? old.layoutSizingVertical : null,
        grow: auto ? old.layoutGrow : null, align: auto ? old.layoutAlign : null, cons: old.constraints };
      if (Math.abs(base.width - st.w) > 0.5 || Math.abs(base.height - st.h) > 0.5) out.mismatch.push({ old: old.id, base: base.id, old_wh: [st.w, st.h], base_wh: [base.width, base.height] });
      const inst = base.createInstance();
      parent.insertChild(idx, inst);
      inst.name = p.name;
      if (auto && st.pos === 'ABSOLUTE') inst.layoutPositioning = 'ABSOLUTE';
      if (Math.abs(inst.width - st.w) > 0.01 || Math.abs(inst.height - st.h) > 0.01) inst.resize(st.w, st.h);
      if (auto && st.pos !== 'ABSOLUTE') {
        inst.layoutAlign = st.align; inst.layoutGrow = st.grow;
        inst.layoutSizingHorizontal = st.lsh; inst.layoutSizingVertical = st.lsv;
      } else { inst.x = st.x; inst.y = st.y; }
      inst.constraints = st.cons;
      inst.visible = st.visible;
      for (const k of old.getSharedPluginDataKeys('remlab')) inst.setSharedPluginData('remlab', k, old.getSharedPluginData('remlab', k));
      if (p.bool) inst.componentPropertyReferences = Object.assign({}, inst.componentPropertyReferences || {}, { visible: out.props[p.bool.prop] });
      if (p.expose) inst.isExposedInstance = true;
      const oldId = old.id;
      old.remove();
      out.removed.push(oldId); out.created.push(inst.id);
      out.replaced.push({ variant: v.id, old: oldId, inst: inst.id, base: base.id, idx, xy: [inst.x, inst.y], wh: [inst.width, inst.height], was_xy: [st.x, st.y] });
    }
  }
}
out.setProps = Object.keys(set.componentPropertyDefinitions);
return out;
