const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ГЕЙТ ЦЕННИКОВ В 3D (demo-09, Codex 17.10): p95 кадра при повороте взгляда с ценниками не хуже, чем без них, более чем на 15 %.
// Пары замеров чередуются (без, с, без, с…), чтобы нагрузка машины делилась поровну. SP=<папка с floorlib/> — локальный движок.
const SP=process.env.SP, [W,H]=(process.argv[2]||'375x667').split('x').map(Number), N=+(process.env.N||4);
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:W<=700,hasTouch:W<=700,locale:'ru-RU'}); const p=await ctx.newPage();
if(SP){const F=JSON.parse(fs.readFileSync(SP+'/floorlib/scene.json','utf8')).file;
  await p.route(/\/demo\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(SP+'/floorlib/scene.json','utf8')}));
  await p.route(/\/demo\/lib\/scene\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+F,'utf8')}));
  await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));}
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=force',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
await p.evaluate(()=>{shots=shots.filter(x=>x.quality!=='realistic'); openLiveWindow();});
await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:150000}); await p.waitForTimeout(2000);
const run=pins=>p.evaluate(async pins=>{
  const box=document.getElementById('vpins'); box.style.display=pins?'':'none';
  if(!pins){cancelAnimationFrame(PINS.raf); PINS.raf=0; window.__noPins=1;} else {window.__noPins=0; vwPins();}
  const o=window.vwPinsTick; if(!window.__wrapped){window.__wrapped=1; window.vwPinsTick=function(t){if(window.__noPins){PINS.raf=0;return;} return o(t);};}
  const ts=[]; let last=performance.now(), k=0;
  await new Promise(ok=>{const f=t=>{ts.push(t-last); last=t; LIVE.scene.look(3,0); if(++k<120)requestAnimationFrame(f); else ok();}; requestAnimationFrame(f);});
  ts.shift(); ts.sort((a,b)=>a-b); return {p95:ts[Math.floor(ts.length*0.95)], med:ts[Math.floor(ts.length/2)], shown:[...box.querySelectorAll('.vpin')].filter(n=>!n.hidden).length};},pins);
const A=[],B=[]; for(let i=0;i<N;i++){A.push(await run(false)); B.push(await run(true));}
const med=a=>a.map(x=>x.p95).sort((x,y)=>x-y)[Math.floor(a.length/2)];
const a=med(A), bb=med(B), ratio=bb/a;
console.log('без ценников p95',A.map(x=>Math.round(x.p95)).join(','),'· с ценниками',B.map(x=>Math.round(x.p95)+'('+x.shown+')').join(','));
console.log((ratio<=1.15?'OK  ':'FAIL')+` p95 с ценниками / без = ${ratio.toFixed(2)} (≤ 1,15)`);
await b.close();})().catch(e=>{console.error(e);process.exit(1);});
