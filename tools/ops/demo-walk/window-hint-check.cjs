const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПОДСКАЗКА ОКНА ПО РЕЖИМУ (demo-22, T-20261022-12/2): разовая подсказка телефона (`remlab-sheet-hint-v1`) в «Фото» называет оба жеста —
// «Потяните фото — вся комната · шторку — товары и замены», в 3D — прежняя; сменили режим, пока видна, — уходит и «уже видел» не ставится.
// Компьютер — подсказки окна нет. Платного нет (заказ фото подменён).
//   DATA=<demo-data.json> FROZEN=1 BASE=https://remont-lab.online/demo/ OUT=<папка/> node tools/ops/demo-walk/window-hint-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const DATA=process.env.DATA?JSON.parse(fs.readFileSync(process.env.DATA,'utf8')):null;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i===undefined?'':typeof i==='string'?i:JSON.stringify(i)));
const PHOTO_RU='Потяните фото — вся комната · шторку — товары и замены', WALK_RU='Потяните или нажмите — товары и замены';
const TIP=`(()=>{const t=document.querySelector('#shot .vtip'); if(!t)return null; const r=t.getBoundingClientRect();
  return {text:t.textContent, mode:t.dataset.mode, r:[r.left,r.top,r.right,r.bottom].map(Math.round), seen:!!localStorage.getItem('remlab-sheet-hint-v1')};})()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errs=[];
  const page=async q=>{const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
    const p=await ctx.newPage(); p.on('pageerror',e=>errs.push(String(e)));
    await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''})); await p.route(/\/api\/warm/,r=>r.fulfill({status:204,body:''}));
    await p.route(/\/api\/render/,r=>r.fulfill({status:200,contentType:'application/json',body:'{"job":"fake"}'}));
    if(DATA)await p.route(u=>new URL(u).pathname.endsWith('/demo/demo-data.json'),r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(DATA)}));
    if(DATA&&process.env.FROZEN)await p.route(/\/test\/share\/shots\.json/,async r=>{const res=await r.fetch(); const j=await res.json();
      const near=(a,c)=>Math.abs(a.x-c.x)<=2&&Math.abs(a.y-c.y)<=2;
      j.forEach(rec=>(rec.cams||[]).forEach(c=>{for(const v of DATA.variants){const d=(v.cams||[]).find(x=>x.name===c.name&&near(x,c)&&x.crop); if(d){c.crop=d.crop; break;}}}));
      await r.fulfill({response:res,body:JSON.stringify(j),headers:{...res.headers(),'content-type':'application/json'}});});
    await p.goto(BASE+'?lang=ru&'+q,{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&SHOTS_LOADED",null,{timeout:90000}).catch(()=>{});
    await p.evaluate(()=>{try{localStorage.removeItem('remlab-sheet-hint-v1');}catch(e){}}); return p;};
  const waitTip=p=>p.waitForFunction(()=>!!document.querySelector('#shot .vtip'),null,{timeout:30000}).then(()=>p.evaluate(TIP)).catch(()=>null);
  // 1. «Фото»: окно открывается сразу на снимке
  let p=await page('live=0');
  await p.evaluate(async()=>{for(let i=0;i<allVariants().length;i++){await vwOpenVariant(i); await new Promise(r=>setTimeout(r,300)); if(vwRealShots().length){vwMode('photo'); return;}}});
  let t=await waitTip(p);
  if(PHONE){ok('1 «Фото»: подсказка про фото и шторку',!!t&&t.mode==='photo'&&t.text===PHOTO_RU,t);
    ok('1 подсказка в ширину экрана',!!t&&t.r[0]>=0&&t.r[2]<=W,t&&t.r);
    await p.screenshot({path:OUT+`hint-${W}-1-photo.png`});
    // смена режима, пока подсказка видна, — уходит; «уже видел» не ставится
    await p.evaluate(()=>vwMode('plan')); await p.waitForTimeout(600);
    const t2=await p.evaluate(TIP), seen=await p.evaluate(()=>!!localStorage.getItem('remlab-sheet-hint-v1'));
    ok('2 сменили режим — подсказка ушла, «уже видел» не стоит',!t2&&!seen,{t2,seen});}
  else ok('1 компьютер «Фото»: подсказки окна нет',!t,t);
  await p.context().close();
  // 3. 3D: прежний текст
  p=await page('live=force');
  await p.evaluate(()=>{openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');});
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>{});
  // программная графика грузит сцену дольше 20 с ожидания подсказки — открываем окно заново на готовой сцене
  await p.evaluate(()=>{document.querySelectorAll('#shot .vtip').forEach(x=>x.remove()); try{localStorage.removeItem('remlab-sheet-hint-v1');}catch(e){}
    openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');});
  t=await waitTip(p);
  if(PHONE){ok('3 3D: прежняя подсказка',!!t&&t.mode==='walk'&&t.text===WALK_RU,t); await p.screenshot({path:OUT+`hint-${W}-3-walk.png`});
    await p.waitForTimeout(3600); ok('3 через 3 с ушла, «уже видел» стоит',await p.evaluate(()=>!document.querySelector('#shot .vtip')&&!!localStorage.getItem('remlab-sheet-hint-v1')));}
  else ok('3 компьютер 3D: подсказки окна нет',!t,t);
  ok('ошибок страницы нет',!errs.length,errs.slice(0,3));
  fs.writeFileSync(OUT+`hint-${W}.log`,R.join('\n')+'\n'); console.log(R.join('\n')); await b.close();
})().catch(e=>{console.log('CRASH',e); fs.writeFileSync(OUT+`hint-${W}.log`,R.join('\n')+'\nCRASH '+e+'\n'); process.exit(1);});
