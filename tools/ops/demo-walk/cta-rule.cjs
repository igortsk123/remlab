// КНОПКА «СДЕЛАТЬ РЕАЛИСТИЧНЕЕ» НА КОМПЬЮТЕРЕ (2.32): стоит под плашкой «Остаток» над списком и целиком в экране — одно правило
// для `sheet-gestures.cjs` и `fav-check.cjs` (T-20261020-01: в fav-check была своя копия «кнопка внутри списка», устаревшая с 2.32).
// `ctaGeom` — для `page.evaluate`, `ctaUnderPlate` — само условие.
exports.ctaGeom=()=>{const c=document.getElementById('vCta'), r=c.getBoundingClientRect(), pl=document.getElementById('vsum').getBoundingClientRect();
  return {top:Math.round(r.top), bottom:Math.round(r.bottom), plate:Math.round(pl.bottom), inScreen:!c.hidden&&r.height>0&&r.top>=0&&r.bottom<=innerHeight};};
exports.ctaUnderPlate=g=>g.inScreen&&g.top>=g.plate-1;
