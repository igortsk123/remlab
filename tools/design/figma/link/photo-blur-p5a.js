// design-02 П5 (T-20261107-62) п.9, Desktop: окно «Фото» (Modal / Layout View view=photo, RU 48:368, EN 48:762).
// Причина «сдвига»: фото вписано (FIT 910×660) — сверху и снизу полосы по 84 px, где виден задник «Фото» (то же фото, FILL 1047×952
// со сдвигом −68,−62). На эталоне 13 задник РАЗМЫТ (как на сайте), у сборки — резкий → в шапке виден карниз слева вверху.
// Правка в компоненте: задник — размытие слоя (LAYER_BLUR, радиус __R__). Повтор безопасен (размытие ставится, не добавляется).
const R = __R__;
const out = [];
for (const id of ['48:368', '48:762']) {
  const w = await figma.getNodeByIdAsync(id);
  const bg = w.findOne(n => n.type === 'RECTANGLE' && n.name === 'Фото' && n.width > 1000);
  if (!bg) { out.push(id + ' нет задника'); continue; }
  const b = JSON.stringify(bg.effects.map(e => e.type + (e.radius || '')));
  bg.effects = [{ type: 'LAYER_BLUR', blurType: 'NORMAL', radius: R, visible: true }];
  // второй вызов 07.11: замер полос (probe-p5a.py) — эталон = 0,92 × сборки → поверх картинки чёрный 8 % (заливка, не отдельный слой)
  bg.fills = [...bg.fills.filter(f => f.type === 'IMAGE'), { type: 'SOLID', color: { r: 0, g: 0, b: 0 }, opacity: 0.08 }];
  out.push(id + ' ' + bg.id + ' ' + Math.round(bg.width) + 'x' + Math.round(bg.height) + ' effects ' + b + ' → blur ' + R);
}
return out;
