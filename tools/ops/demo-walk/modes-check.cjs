const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// РЕЖИМЫ ОКНА (план demo-09): три сценария — «без реалистичного фото», «готово для текущего stateId», «состояние изменилось во время
// задания» — плюс «без 3D» и EN. Платный путь НЕ вызывается: ответы /api/render и /api/job подменяются (готовое фото = картинка товара).
//   PROD=1 node tools/ops/demo-walk/modes-check.cjs 375x667          — прод как есть (платный путь подменён ВО ВСЕХ сценариях)
//   SP=<папка с floorlib/> node … 375x667                            — локальная страница и движок поверх прода
const SP=process.env.SP, OUT=process.env.OUT||require('os').tmpdir()+'/', prod=!!process.env.PROD||!SP;
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number);
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i||''));
async function page(b,q,lang){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:W<=700,hasTouch:W<=700,locale:lang==='en'?'en-GB':'ru-RU'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  if(!prod){const F=JSON.parse(fs.readFileSync(SP+'/floorlib/scene.json','utf8')).file;
    await p.route(/\/demo\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(SP+'/floorlib/scene.json','utf8')}));
    await p.route(/\/demo\/lib\/scene\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+F,'utf8')}));
    await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));}
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  // подмена съёмки: задание отвечает «готово» по флагу страницы `__fakeReady` (сценарий 3 успевает изменить расстановку)
  await p.route(/\/api\/render/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.route(/\/api\/job\?/,async r=>{const ready=await p.evaluate(()=>!!window.__fakeReady).catch(()=>false);
    const img=await p.evaluate(()=>{const it=(allVariants()[cur]||{}).items||[]; const x=it.find(i=>i.sku&&i.sku.img); return x?new URL(x.sku.img,location.href).href:'';}).catch(()=>'');
    r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(ready?{shots:[{camera:'C1',url:img},{camera:'C2',url:img}],backend:'fake'}:{status:'running',eta:30})});});
  await p.goto('https://remont-lab.online/demo/'+q,{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){}});
  return p;
}
const st=p=>p.evaluate(()=>({mode:VW.mode, photoTab:!(document.querySelector('[data-vm="photo"]')||{hidden:true}).hidden,
  cta:(()=>{const c=document.getElementById('vCta'); return c&&!c.hidden?c.innerText.replace(/\n/g,' '):null;})(),
  pins:[...document.querySelectorAll('#vpins .vpin')].filter(n=>!n.hidden).length, pos:(document.getElementById('vside')||{dataset:{}}).dataset.pos,
  stub:(()=>{const e=document.getElementById('vStub'); return !!e&&getComputedStyle(e).display!=='none';})(),
  ready:!!document.querySelector('#shot .vready'), err:(document.getElementById('vCtaErr')||{}).textContent||'', sid:curStateId()}));
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
// 1. без реалистичного фото: 3D, вкладки «Фото» нет, ценники, стрелки — к позе 2 и обратно
let p=await page(b,'?live=force&lang=ru','ru');
await p.evaluate(()=>{shots=shots.filter(x=>x.quality!=='realistic'); openLiveWindow();});
await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:150000}).catch(()=>{}); await p.waitForTimeout(2500);
let s=await st(p); ok('1 без фото — открыто 3D, вкладки «Фото» нет',s.mode==='walk'&&!s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
ok('1 ценники над мебелью в 3D (≥ 3)',s.pins>=3,'видно '+s.pins);
ok('1 «Сделать реалистичнее» видна в 3D',!!s.cta&&/реалистичнее/.test(s.cta),s.cta);
const dz=await p.evaluate(()=>{const d=document.getElementById('vDots').getBoundingClientRect(), t=document.getElementById('vside').getBoundingClientRect(); return {dots:Math.round(d.bottom), sheet:Math.round(t.top)};});
if(W<=700)ok('1 точки ракурсов над верхом шторки',dz.dots<=dz.sheet,JSON.stringify(dz));
await p.screenshot({path:OUT+`m09-${W}-walk.png`});
const p0=await p.evaluate(()=>LIVE.scene.pose()); await p.evaluate(()=>vwPhoto(VW.photo+1)); await p.waitForTimeout(1500);
const p1=await p.evaluate(()=>LIVE.scene.pose()); await p.evaluate(()=>vwPhoto(VW.photo-1)); await p.waitForTimeout(1500); const p2=await p.evaluate(()=>LIVE.scene.pose());
ok('1 стрелка → поза 2, обратно → поза 1',(p1.x!==p0.x||p1.y!==p0.y)&&Math.abs(p2.x-p0.x)<=2&&Math.abs(p2.y-p0.y)<=2,JSON.stringify([p0,p1,p2]));
await p.evaluate(()=>LIVE.scene.look(-200,0)); await p.waitForTimeout(400); const p3=await p.evaluate(()=>LIVE.scene.pose());
ok('1 тянуть — поворот взгляда из той же точки',p3.x===p2.x&&p3.y===p2.y&&p3.yaw!==p2.yaw,JSON.stringify(p3));
// 1б. замена через ленту из полной шторки → шторка физически свёрнута, ничего не прокручено (владелец 17.10, probe16 d8)
if(W<=700){await p.evaluate(()=>vwSheet(3)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{});
  await p.locator('#vside .vitems [data-rep]').first().click(); await p.locator('#sheet .mini:has-text("Заменить")').first().click();
  await p.waitForTimeout(1500); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(800);
  const sw=await p.evaluate(()=>{const sd=document.getElementById('vside'); return {pos:sd.dataset.pos, top:Math.round(sd.getBoundingClientRect().top), want:Math.round(innerHeight-vwEdges().min),
    scrolled:[...document.querySelectorAll('#shot, #shot *')].filter(e=>e.scrollTop>0&&!/vscroll|sheetscroll/.test(e.id)).map(e=>(e.id||e.className)+':'+e.scrollTop)};});
  ok('1б замена через ленту → шторка свёрнута на деле',sw.pos==='0'&&sw.top>=sw.want-2&&!sw.scrolled.length,JSON.stringify(sw));
  await p.evaluate(()=>closePicker()); await p.waitForTimeout(500);}
// 2. «Сделать реалистичнее» → ход на кнопке, 3D остаётся → готово → «Фото» само
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);
await p.click('#vCta'); await p.waitForTimeout(1500); s=await st(p);
ok('2 после нажатия — ход на кнопке, режим 3D',s.mode==='walk'&&/Рисуем фото/.test(s.cta||''),s.cta);
await p.evaluate(()=>{window.__fakeReady=1;}); await p.waitForFunction(()=>VW.mode==='photo',null,{timeout:20000}).catch(()=>{}); s=await st(p);
ok('2 готово для этой расстановки → «Фото» открылось само, кнопки нет',s.mode==='photo'&&s.photoTab&&s.cta===null,JSON.stringify({mode:s.mode,tab:s.photoTab,cta:s.cta}));
await p.screenshot({path:OUT+`m09-${W}-photo.png`});
// 4. изменение → 3D и шторка вниз (телефон)
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(800);
await p.evaluate(()=>{const g=devGroups().find(x=>x.kind==='flooring'); if(g)devSet(g.id,g.variants[1].id);}); await p.waitForTimeout(1500); s=await st(p);
ok('4 смена пола → 3D, вкладки «Фото» нет',s.mode==='walk'&&!s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
if(W<=700)ok('4a шторка свернулась сама',s.pos==='0','pos '+s.pos);
await p.evaluate(()=>histBack()); await p.waitForTimeout(1200); s=await st(p);
ok('4 ↶ вернул расстановку со снимком → «Фото» снова доступно (в 3D)',s.mode==='walk'&&s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
// 3. состояние изменилось во время задания → без переключения, подсказка
await p.evaluate(()=>{window.__fakeReady=0; const g=devGroups().find(x=>x.kind==='flooring'); devSet(g.id,g.variants[2].id);}); await p.waitForTimeout(900);
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);   // после изменения шторка свёрнута — кнопку сперва видно, как у человека
await p.click('#vCta'); await p.waitForTimeout(1200);
await p.evaluate(()=>{const g=devGroups().find(x=>x.kind==='flooring'); devSet(g.id,g.variants[3].id); window.__fakeReady=1;});
await p.waitForFunction(()=>!VJ.job,null,{timeout:20000}).catch(()=>{}); await p.waitForTimeout(500); s=await st(p);
ok('3 расстановка менялась во время съёмки → 3D, подсказка «фото готово для прежней»',s.mode==='walk'&&!s.photoTab&&s.ready,JSON.stringify({mode:s.mode,tab:s.photoTab,ready:s.ready}));
const geo=await p.evaluate(()=>{const R=s=>{const e=document.querySelector(s); if(!e)return null; const r=e.getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)];};
  const sc=[...document.querySelectorAll('#shot, #shot *')].filter(e=>e.scrollTop>0).map(e=>(e.id||e.className||e.tagName)+':'+e.scrollTop);
  return {vmodes:R('#shot .vmodes'), canvas:R('#shot canvas'), ready:R('#shot .vready'), scrolled:sc, win:scrollY};});
ok('3 переключатель режимов на месте, сцена не уехала',!!geo.vmodes&&geo.vmodes[1]>=0&&geo.vmodes[1]<40&&!geo.scrolled.filter(x=>!/vscroll/.test(x)).length,JSON.stringify(geo));
await p.screenshot({path:OUT+`m09-${W}-ready.png`});
console.log('errs',p.errs.slice(0,3)); await p.context().close();
// 5. без 3D: заглушка, кнопка работает. ПЛАТНОЕ НЕ ВЫЗЫВАЕТСЯ НИКОГДА: отказ «нет денег» подменён (17.10 сценарий нажимал настоящую
// кнопку в расчёте на пустой баланс — после пополнения это были бы настоящие съёмки)
p=await page(b,'?live=0&lang=ru','ru');
await p.unroute(/\/api\/render/); await p.unroute(/\/api\/job\?/);
await p.route(/\/api\/render/,r=>r.fulfill({status:402,contentType:'application/json',body:JSON.stringify({code:'no_credits',error:'нет денег (подмена проверки)'})}));
await p.route(/\/api\/job\?/,r=>r.fulfill({status:410,contentType:'application/json',body:JSON.stringify({code:'not_found',error:'подмена проверки'})}));
await p.evaluate(()=>{shots=shots.filter(x=>x.quality!=='realistic'); openLiveWindow();}); await p.waitForTimeout(2500); s=await st(p);
ok('5 без 3D — заглушка, кнопка видна',s.mode==='walk'&&s.stub&&!!s.cta,JSON.stringify({stub:s.stub,cta:s.cta}));
await p.click('#vCta'); await p.waitForFunction(()=>!VJ.job,null,{timeout:20000}).catch(()=>{}); s=await st(p);
ok('5 «Сделать реалистичнее» без денег — честный ответ под кнопкой',!!s.err,s.err.slice(0,90));
await p.screenshot({path:OUT+`m09-${W}-stub.png`}); console.log('errs',p.errs.slice(0,3)); await p.context().close();
// 6. EN: подписи режима без кириллицы
p=await page(b,'?live=0&lang=en','en'); await p.evaluate(()=>{shots=shots.filter(x=>x.quality!=='realistic'); openLiveWindow();}); await p.waitForTimeout(2500);
const en=await p.evaluate(()=>[document.getElementById('vStub').innerText, document.getElementById('vCta').innerText].join(' | '));
ok('6 EN без кириллицы',!/[А-Яа-яЁё]/.test(en),en); await p.context().close();
console.log(R.join('\n')); await b.close();})().catch(e=>{console.error(e);process.exit(1);});
