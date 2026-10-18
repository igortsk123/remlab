// d8: приёмка demo-15 — миниатюры в списке (телефон), перекрытие кнопки плашкой и полосы холста (компьютер)
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const OUT=process.argv[2]||'/tmp/';
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
for(const [name,vp,mobile] of [['phone',{width:375,height:667},true],['desk',{width:1440,height:900},false]]){
  const ctx=await b.newContext({viewport:vp,deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,locale:'ru-RU'}); const p=await ctx.newPage();
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.goto('https://remont-lab.online/demo/?live=0',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(3000);
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} pickVariant(0); openLiveWindow();}); await p.waitForTimeout(6000);
  if(mobile){ await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(1500); }
  const r=await p.evaluate(()=>{const R=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];};
    const thumbs=[...document.querySelectorAll('#vside .vitems img')].slice(0,6).map(i=>({src:(i.getAttribute('src')||'').slice(-28), w:i.naturalWidth, ok:i.complete&&i.naturalWidth>0}));
    const cta=document.getElementById('vCta'), plate=document.getElementById('vsum'), cv=document.querySelector('#shot canvas'), body=document.getElementById('shotbody');
    const overlap=cta&&plate?Math.max(0, Math.min(R(cta)[1]+R(cta)[3], R(plate)[1]+R(plate)[3])-Math.max(R(cta)[1],R(plate)[1])):null;
    return {thumbs, cta:R(cta), plate:R(plate), overlapPx:overlap, canvas:R(cv), area:R(document.querySelector('#shot .vscene, #shot .shotwrap')||body), modes:R(document.querySelector('#shot .vmodes')), views:[...document.querySelectorAll('#shot button')].map(b=>b.textContent.trim()).filter(t=>/стороны|Ракурс/.test(t))};});
  console.log(name, JSON.stringify(r)); await p.screenshot({path:OUT+'/p18-'+name+'.png'}); await ctx.close();
}
await b.close();})();
