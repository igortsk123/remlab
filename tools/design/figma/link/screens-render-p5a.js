// design-02 П5 (T-20261107-62) п.7: сборки «после замены» — в окне 3D включить кадр «после замены» (showAfterReplace),
// прежние кадр и ценники окна скрыть (переопределение видимости в экземпляре; сами слои в компоненте остаются).
// Два прохода (__PASS__ = 1 | 2): после setProperties чтение имени вложенного узла в том же вызове падает
// («node 414:… does not exist»), поэтому скрытие — отдельным вызовом, по id вида I<окно>;<слой компонента>, без чтения после записи.
// CFG = [{ page, w:[<id экземпляра окна в сборке>…], old:[<id прежнего кадра>, <id рамки ценников> в компоненте окна] }]
//   Mobile: RU 280:2 окна 318:8427/8667/8905/9143, old 95:212, 95:225; EN 293:2 окна 323:9034/9291/9546/9801/10079, old 95:586, 95:599.
const CFG = __CFG__, PASS = __PASS__;
const out = {};
for (const C of CFG) {
  await figma.setCurrentPageAsync(await figma.getNodeByIdAsync(C.page));
  for (const wid of C.w) {
    const w = await figma.getNodeByIdAsync(wid);
    if (PASS === 1) {
      const k = Object.keys(w.componentProperties).find(x => x.startsWith('showAfterReplace#'));
      out[wid] = 'before=' + (k && w.componentProperties[k].value); if (k) w.setProperties({ [k]: true });
    } else {
      const r = [];
      for (const m of C.old) { const n = await figma.getNodeByIdAsync('I' + wid + ';' + m); if (!n) { r.push('нет ' + m); continue; } n.visible = false; r.push(m + ' скрыт'); }
      out[wid] = r.join(',');
    }
  }
}
return out;
