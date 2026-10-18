// Проверка макета home-v2 (demo-16): до сгиба видны вкладки стилей и ≥ 120 px фото; после прокрутки липкая часть ≤ 96 px.
// Запуск из корня репо: node tools/ops/mock/home-v2/check.cjs [base-url|dir] [out-dir]
const fs=require('fs'),path=require('path');
const ROOT=process.cwd();
const pnpm=path.join(process.env.REMLAB_ROOT||ROOT,'node_modules/.pnpm');  // из worktree: REMLAB_ROOT=<основная копия>
const pw=require(path.join(pnpm,fs.readdirSync(pnpm).find(d=>d.startsWith('playwright-core@')),'node_modules/playwright-core'));
const BASE=process.argv[2]||'file://'+path.join(ROOT,'tools/ops/mock/home-v2')+'/';
const OUT=process.argv[3]||'/tmp';
const VPS=[[375,667,true],[390,844,true],[1440,900,false]];
(async()=>{const b=await pw.chromium.launch(); const rows=[]; let fail=0;
for(const v of ['a','b','c']) for(const [w,h,mobile] of VPS) for(const s of mobile?[0,1]:[0]){
  const ctx=await b.newContext({viewport:{width:w,height:h},deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,locale:'ru-RU'});
  const p=await ctx.newPage(); await p.goto(BASE+v+'.html'+(s?'?s=1':''),{waitUntil:'load'}); await p.waitForTimeout(400);
  const r=await p.evaluate(()=>{const R=s=>document.querySelector(s).getBoundingClientRect(), vh=innerHeight;
    const img=R('#r-living img'), tabs=R('.tabs'), hd=R('.hd1');
    const cut=[...document.querySelectorAll('.fk,.price,.hd2,.cert .t span,.pc .c,.m span,.btn,.tab,.stub b,.stub span,.rb small')].filter(e=>e.scrollWidth>e.clientWidth+1&&e.getBoundingClientRect().right<=innerWidth).map(e=>e.textContent.trim().slice(0,24));
    return {scrollY:Math.round(scrollY), photoTop:Math.round(img.top), visiblePhotoHeight:Math.round(Math.max(0,Math.min(img.bottom,vh)-Math.max(img.top,tabs.bottom))),
      tabsBottom:Math.round(tabs.bottom), tabsVisible:tabs.top>=0&&tabs.bottom<=vh, stickyPx:Math.round(Math.max(hd.bottom,tabs.bottom)),
      hScroll:document.documentElement.scrollWidth>innerWidth, cut};});
  const ok=s?r.stickyPx<=96&&r.scrollY>0:(r.tabsVisible&&r.visiblePhotoHeight>=120);
  if(mobile&&!ok)fail++;
  rows.push({v,vp:w+'x'+h,state:s?'scrolled':'top',...r,ok:mobile?ok:'—'});
  await p.screenshot({path:path.join(OUT,`home-v2-${v}-${w}x${h}${s?'-s':''}.png`)}); await ctx.close();
}
await b.close(); console.table(rows.map(r=>({...r,cut:r.cut.join(' | ')}))); process.exit(fail?1:0);})();
