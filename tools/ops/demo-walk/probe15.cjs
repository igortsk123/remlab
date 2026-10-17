// d8: после смены пола (demo-09 п.4/4a) — где переключатель режимов, холст и шторка; не уехал ли #shot (снимок m09-375-ready.png без «3D · План»)
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const OUT=process.argv[2]||'/tmp/';
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:375,height:667},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'}); const p=await ctx.newPage();
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=force',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} openLiveWindow();});
await p.waitForTimeout(4000);
console.log('после открытия', JSON.stringify(await p.evaluate(()=>({mode:VW.mode, photoTab:!(document.querySelector('[data-vm="photo"]')||{hidden:true}).hidden, live:LIVE.state, realistic:shots.filter(x=>x.quality==='realistic').length, withState:shots.filter(x=>x.quality==='realistic'&&x.stateId).length, cur:curStateId(), match:shots.filter(x=>x.quality==='realistic'&&x.stateId===curStateId()).length}))));
if(await p.evaluate(()=>VW.mode==='photo')){await p.evaluate(()=>vwMode('walk')); console.log('переключил в 3D');}
await p.waitForFunction(()=>typeof LIVE!=="undefined"&&LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>console.log('сцена не готова за 300 с:', JSON.stringify(null))); await p.waitForTimeout(5000);
console.log('LIVE', JSON.stringify(await p.evaluate(()=>({state:LIVE.state, ok:LIVE.ok, why:LIVE.why, scene:!!LIVE.scene}))));
const st=()=>p.evaluate(()=>{const R=s=>{const e=document.querySelector(s); if(!e)return null; const r=e.getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)];};
  const sh=document.getElementById('shot'); return {mode:VW.mode,pos:document.getElementById('vside').dataset.pos,vmodes:R('#shot .vmodes'),canvas:R('#shot canvas'),vside:R('#vside'),dots:R('#shot .vdots'),ready:R('#shot .vready'),shotScroll:sh.scrollTop,bodyScroll:document.scrollingElement.scrollTop,shotTop:R('#shot'),vsh:getComputedStyle(sh).getPropertyValue('--vsh')};});
console.log('старт', JSON.stringify(await st()));
await p.evaluate(()=>vwSheet(3)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{});
console.log('полная', JSON.stringify(await st()));
await p.evaluate(()=>{const g=devGroups().find(x=>x.kind==='flooring'); devSet(g.id,g.variants[1].id);}); await p.waitForTimeout(600); console.log('+0.6с после смены пола', JSON.stringify(await st()));
await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(1500);
console.log('после смены пола', JSON.stringify(await st())); await p.screenshot({path:OUT+'/p15-after-floor.png'});
await p.evaluate(()=>vwSheet(2)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(500);
console.log('средняя после', JSON.stringify(await st())); await p.screenshot({path:OUT+'/p15-mid-after.png'});
await b.close();})();
