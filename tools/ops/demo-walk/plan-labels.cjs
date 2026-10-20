const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПОДПИСИ ПЛАНА В ОКНЕ ВАРИАНТА (T-20261020-01): вкладка «План» каждого варианта — подписи (предметы, дверь, окно) не налезают
// друг на друга и не выходят за рамку плана. Замер — прямоугольники `<text>` на странице (`getBoundingClientRect`).
//   node tools/ops/demo-walk/plan-labels.cjs 375x667            # прод
//   LOCAL=1 node tools/ops/demo-walk/plan-labels.cjs 375x667    # страница из рабочей копии поверх прода (как sheet-gestures)
const LOCAL=process.env.LOCAL, OUT=process.env.OUT||require('os').tmpdir()+'/plan-labels-';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
if(LOCAL)await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=0',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(1500);
const n=await p.evaluate(()=>allVariants().length); let bad=0; const tag=(LOCAL?'local':'prod')+'-'+W+'x'+H;
for(let i=0;i<n;i++){
  await p.evaluate(i=>{pickVariant(i); openLiveWindow();},i); await p.waitForTimeout(1200);
  await p.evaluate(()=>vwMode('plan')); await p.waitForTimeout(800);
  const m=await p.evaluate(()=>{const v=allVariants()[cur]||{}, svg=document.querySelector('#vPlan svg'), vb=svg.viewBox.baseVal, r=svg.getBoundingClientRect();
    // рамка плана на странице: viewBox, вписанный в элемент (`xMidYMid meet`)
    const k=Math.min(r.width/vb.width,r.height/vb.height), fx=r.left+(r.width-vb.width*k)/2, fy=r.top+(r.height-vb.height*k)/2;
    const fr={l:fx,t:fy,r:fx+vb.width*k,b:fy+vb.height*k};
    const L=[...svg.querySelectorAll('text')].filter(t=>t.textContent.trim()&&getComputedStyle(t).display!=='none'&&t.getAttribute('visibility')!=='hidden')
      .map(t=>{const q=t.getBoundingClientRect(); return {s:t.textContent,l:q.left,t:q.top,r:q.right,b:q.bottom};});
    const over=[]; for(let a=0;a<L.length;a++)for(let c=a+1;c<L.length;c++){const A=L[a],B=L[c];
      const ox=Math.min(A.r,B.r)-Math.max(A.l,B.l), oy=Math.min(A.b,B.b)-Math.max(A.t,B.t); if(ox>0.5&&oy>0.5)over.push(`«${A.s}» × «${B.s}» ${ox.toFixed(1)}×${oy.toFixed(1)}`);}
    const out=L.filter(q=>q.l<fr.l-0.5||q.r>fr.r+0.5||q.t<fr.t-0.5||q.b>fr.b+0.5).map(q=>`«${q.s}» ${Math.round(q.l)}–${Math.round(q.r)} при рамке ${Math.round(fr.l)}–${Math.round(fr.r)}`);
    const rd=x=>Math.round(x*10)/10;
    return {v:v.title||v.name||v.style||v.id, labels:L.length, over, out, rects:L.map(q=>`${q.s} [${rd(q.l)},${rd(q.t)},${rd(q.r)},${rd(q.b)}]`)};});
  bad+=m.over.length+m.out.length;
  console.log(`${i} ${m.v}: подписей ${m.labels}, перекрытий ${m.over.length}, за краем ${m.out.length}`);
  m.over.concat(m.out).forEach(s=>console.log('   ',s)); if(process.env.RECTS)m.rects.forEach(s=>console.log('     ',s));
  await p.locator('#vPlan').screenshot({path:OUT+tag+'-v'+i+'.png'});
  await p.evaluate(()=>{const x=document.getElementById('shotx'); if(x)x.click();}); await p.waitForTimeout(500);
}
if(errs.length)console.log('ошибки страницы:',errs.slice(0,3));
console.log(`${tag}: вариантов ${n}, нарушений ${bad}`); await b.close(); process.exit(bad||errs.length?1:0);
})();
