// d8: «Фото» на телефоне после demo-09 дополнения — без полос? и просмотр во весь экран
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const OUT=process.argv[2]||'/tmp/';
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:375,height:667},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'}); const p=await ctx.newPage();
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=0',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(4000);
await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} pickVariant(0); openLiveWindow();}); await p.waitForTimeout(4000);
console.log(JSON.stringify(await p.evaluate(()=>{const im=document.querySelector('#shot .shotwrap img, #shot img.vphoto, #shot .vphotoimg'); const r=im&&im.getBoundingClientRect(); const cs=im&&getComputedStyle(im); return {mode:VW.mode, img:r&&[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)], fit:cs&&cs.objectFit, pos:cs&&cs.objectPosition, blur:!!document.querySelector('#shot [style*="blur"], #shot .vbg, #shot .vblur')};})));
await p.screenshot({path:OUT+'/p17-photo.png'});
console.log('кнопка/шторка:', JSON.stringify(await p.evaluate(()=>{const b=document.getElementById('vzBtn'), r=b&&b.getBoundingClientRect(), sd=document.getElementById('vside').getBoundingClientRect(), im=[...document.querySelectorAll('#shot img')].map(i=>i.getBoundingClientRect()).filter(r=>r.width>300)[0]; return {btn:r&&[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)], sheetTop:Math.round(sd.top), img:im&&[Math.round(im.left),Math.round(im.top),Math.round(im.width),Math.round(im.height)]};})));
await p.evaluate(()=>vwSheet(0)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(400); await p.screenshot({path:OUT+'/p17-photo-collapsed.png'});
const z=p.locator('#shot :text("во весь экран")').first(); if(await z.count()){await z.click(); await p.waitForTimeout(1200); await p.screenshot({path:OUT+'/p17-zoom.png'});
  const before=await p.evaluate(()=>document.querySelector('#vzoom img').getBoundingClientRect().left);
  for(let i=0;i<5;i++){await p.touchscreen.tap(187,333); await p.waitForTimeout(250);}
  const after=await p.evaluate(()=>document.querySelector('#vzoom img').getBoundingClientRect().left);
  console.log('сдвиг после 5 тапов, px:', Math.round(after-before));
  await p.touchscreen.tap(187,333); await p.waitForTimeout(80); await p.touchscreen.tap(187,333); await p.waitForTimeout(600);
  console.log('после двойного тапа transform:', await p.evaluate(()=>document.querySelector('#vzoom img').style.transform.slice(0,80))); await p.screenshot({path:OUT+'/p17-zoom2.png'});}
await b.close();})();
