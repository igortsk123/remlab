// design-02 П5 (T-20261107-62) п.7: «заплатки» на кадре «после замены» — в вырезке из эталона запечены полупрозрачные плашки
// (Фото · 3D · План, Отменить/Повторить, Ракурс камеры); поверх них окно кладёт свои такие же → двойное затемнение и «призрак» текста.
// Заплатка = прямоугольник с той же картинкой (CROP), взятой со смещением из соседнего места (стена/пол), — плашки окна ложатся на чистый фон.
// CFG = { ref:[RW,RH], crop:[cx,cy], variants:[{ variant, patches:[{ x, y, w, h, r, sx, sy }] }] } — x,y,sx,sy в координатах кадра;
// эталон RW×RH, кадр вырезан из него с (cx,cy). Mobile: ref 375×812, crop 0,0; Desktop: ref 1440×900, crop 60,36.
// Второй прогон 07.11: заплатки по размеру самих плашек (+1 px) со скруглением r — на первом (с запасом 3–5 px) был виден светлый ободок;
// источник для стены — сдвиг вбок, для пола — чуть выше.
const CFG = __CFG__;
const [RW, RH] = CFG.ref, [CX, CY] = CFG.crop;
const out = {};
for (const V of CFG.variants) {
  const c = await figma.getNodeByIdAsync(V.variant);
  const img = c.findOne(n => n.name === 'Кадр');
  const hash = img.fills[0].imageHash;
  for (const o of c.children.filter(n => n.name.startsWith('Заплатка'))) o.remove(); // повтор: свои заплатки пересоздаются
  for (const [i, p] of V.patches.entries()) {
    const r = figma.createRectangle(); r.name = 'Заплатка ' + (i + 1); r.resize(p.w, p.h); r.cornerRadius = p.r || 0;
    r.fills = [{ type: 'IMAGE', imageHash: hash, scaleMode: 'CROP', imageTransform: [[p.w / RW, 0, (CX + p.sx) / RW], [0, p.h / RH, (CY + p.sy) / RH]] }];
    c.appendChild(r); r.x = p.x; r.y = p.y;
  }
  out[V.variant] = c.children.map(n => n.name + ' ' + Math.round(n.x) + ',' + Math.round(n.y) + ' ' + Math.round(n.width) + 'x' + Math.round(n.height)).join(' | ');
}
return out;
