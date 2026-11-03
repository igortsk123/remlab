// design-02 П4б (T-20261103-12): ТОЛЬКО ЧТЕНИЕ — сверка одной страницы после записи с ожиданием из gen-check-p4b.py.
// EXP = {page, pageName, sets:[{id,n,dh:[h(описание), h(описание с &lt;…)],keys,vn:число,vh:h('id=имя|…')}], inst:{mainId:число до},
//        dz:[[id,mainId,h(sub),h(ov),размер]]|null, txt:[[id|'*', h(текст)]]|null}; h — djb2 по UTF-16, base36 (как в gen-check-p4b.py). Возвращает только расхождения: {page, ok, bad:[...], n:{sets,variants,inst}}.
const EXP = __EXP__;
const page = await figma.getNodeByIdAsync(EXP.page);
await figma.setCurrentPageAsync(page);
const bad = [];
if (page.name !== EXP.pageName) bad.push('страница: «' + page.name + '»');
const h = s => { let x = 5381; for (let i = 0; i < s.length; i++) x = ((x * 33) ^ s.charCodeAt(i)) >>> 0; return x.toString(36); };
let nv = 0;
for (const e of EXP.sets) {
  const s = await figma.getNodeByIdAsync(e.id);
  if (!s || s.type !== 'COMPONENT_SET') { bad.push(e.id + ': нет набора'); continue; }
  if (s.name !== e.n) bad.push(e.id + ': имя «' + s.name + '»');
  if (!e.dh.includes(h(s.description))) bad.push(e.id + ': описание «' + s.description.slice(0, 80) + '»');
  const keys = Object.keys(s.componentPropertyDefinitions).map(k => k.split('#')[0]).sort().join(',');
  if (keys !== e.keys) bad.push(e.id + ': свойства ' + keys + ' ≠ ' + e.keys);
  const names = s.children.map(c => c.name);
  if (new Set(names).size !== names.length) bad.push(e.id + ': имена вариантов не уникальны');
  if (s.children.length !== e.vn) bad.push(e.id + ': вариантов ' + s.children.length + ' ≠ ' + e.vn);
  if (h(s.children.map(c => c.id + '=' + c.name).join('|')) !== e.vh) bad.push(e.id + ': варианты ' + names.join(' ; ').slice(0, 200));
  nv += s.children.length;
}
const insts = page.findAllWithCriteria({ types: ['INSTANCE'] });
const mains = await Promise.all(insts.map(i => i.getMainComponentAsync()));
const inst = {};
mains.forEach(m => { const k = m ? m.id : 'null'; inst[k] = (inst[k] || 0) + 1; });
for (const k of new Set([...Object.keys(inst), ...Object.keys(EXP.inst)]))
  if ((inst[k] || 0) !== (EXP.inst[k] || 0)) bad.push('экземпляры ' + k + ': ' + (inst[k] || 0) + ' ≠ ' + (EXP.inst[k] || 0));
if (EXP.dz) {
  const now = [];
  insts.forEach((i, k) => {
    if (i.absoluteTransform[0][2] < 3900) return;
    const sub = i.findAll(() => true).map(d => d.id.split(';').pop() + (d.visible ? '' : '!') + ('characters' in d ? '=' + d.characters : '')).join('|');
    const ov = (i.overrides || []).map(o => o.id.split(';').pop() + ':' + o.overriddenFields.join(',')).join('|');
    now.push([i.id, mains[k] ? mains[k].id : null, h(sub), h(ov), Math.round(i.width) + 'x' + Math.round(i.height)].join(' '));
  });
  const was = EXP.dz.map(r => r.join(' '));
  if (now.join('\n') !== was.join('\n')) bad.push('дизайнер: ' + now.filter(x => !was.includes(x)).join(' ; ') + ' ← было ' + was.filter(x => !now.includes(x)).join(' ; '));
}
if (EXP.txt) {
  const cur = page.findAllWithCriteria({ types: ['TEXT'] }).map(t => [t.id, t.characters]);
  const m = Object.fromEntries(cur);
  for (const [id, t] of EXP.txt) {
    if (id === '*') { if (!cur.some(x => h(x[1]) === t)) bad.push('нет новой строки'); }
    else if (h(m[id] || '') !== t) bad.push('текст ' + id + ': «' + (m[id] || '').slice(0, 60) + '»');
  }
  if (cur.length !== EXP.txt.length) bad.push('текстов ' + cur.length + ' ≠ ' + EXP.txt.length);
}
return JSON.stringify({ page: page.id, ok: bad.length === 0, bad: bad.slice(0, 20), n: { sets: EXP.sets.length, variants: nv, inst: insts.length } });
