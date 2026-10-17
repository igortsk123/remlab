// d8: замена товара в окне на телефоне — сворачивается ли шторка (demo-09 п.4a); события remlab:hist и состояние пикера #sheet
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const OUT=process.argv[2]||'/tmp/';
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:375,height:667},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'}); const p=await ctx.newPage();
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=force',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} window.__hist=[]; document.addEventListener('remlab:hist',e=>window.__hist.push(JSON.stringify(e.detail||{}))); openLiveWindow();});
await p.waitForFunction(()=>typeof LIVE!=='undefined'&&LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>{}); await p.waitForTimeout(4000);
const st=(tag)=>p.evaluate(t=>({t, mode:VW.mode, pos:document.getElementById('vside').dataset.pos, top:Math.round(document.getElementById('vside').getBoundingClientRect().top), picker:(()=>{const s=document.getElementById('sheet'); return !!s&&getComputedStyle(s).display!=='none'&&s.getBoundingClientRect().height>0;})(), hist:window.__hist, phone:VW_PHONE()}),tag);
console.log(JSON.stringify(await st('старт')));
await p.evaluate(()=>vwSheet(3)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{});
const rep=p.locator('#vside .vitems :text-is("Заменить")').first(); console.log('кнопок Заменить в списке:', await p.locator('#vside .vitems :text-is("Заменить")').count());
await rep.click(); await p.waitForTimeout(2500); console.log(JSON.stringify(await st('после «Заменить»'))); await p.screenshot({path:OUT+'/p16-picker.png'});
const cand=p.locator('#sheet .mini:has-text("Заменить")'); console.log('кандидатов:', await cand.count());
if(await cand.count()){ await cand.first().click(); await p.waitForTimeout(1500); console.log(JSON.stringify(await st('+1.5с после выбора')));
  await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(2500); console.log(JSON.stringify(await st('после выбора'))); await p.screenshot({path:OUT+'/p16-after-swap.png'}); }
await b.close();})();
