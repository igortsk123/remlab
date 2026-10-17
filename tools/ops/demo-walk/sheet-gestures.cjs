const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПРОВЕРКА ЖЕСТОВ ШТОРКИ v4 (план demo-02 § «Шторка v4» п.4): трасса, неизменный холст, резинка, флик, тап, передача из списка, пины.
//   PROD=1 node tools/ops/demo-walk/sheet-gestures.cjs 375x667          — прод как есть
//   SP=<папка с floorlib/ сборки движка> node … 390x844                  — локальная страница и движок поверх прода
//   LOCAL=1 node … 375x667                                               — только локальная страница, движок — прода
// v5 (шторка v5): полная остановка — плашка у верха экрана; средняя — по содержимому; раздел «Отделка» → полная, «← Назад» —
// прежняя высота; строки-входы по комнате окна (гостиная — без «Встраиваемое»; `?debug=1&vroom=kitchen` — карточки кухни)
const SP=process.env.SP, LOCAL=process.env.LOCAL, OUT=process.env.OUT||require('os').tmpdir()+'/'; const prod=!LOCAL&&(process.env.PROD||!SP);
const F=(prod||LOCAL)?null:JSON.parse(fs.readFileSync(SP+'/floorlib/scene.json','utf8')).file;
const [W,H]=(process.argv[2]||'390x844').split('x').map(Number);
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'});
const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
if(!prod&&!LOCAL){
await p.route(/\/demo\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(SP+'/floorlib/scene.json','utf8')}));
await p.route(/\/demo\/lib\/scene\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+F,'utf8')}));
}
if(!prod)await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=force',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} openLiveWindow();}); await p.waitForFunction(()=>LIVE.scene,null,{timeout:120000}); await p.waitForTimeout(8000);
await p.evaluate(()=>{window.__fit=0; const o=liveFit; liveFit=function(){window.__fit++; return o.apply(this,arguments);};});
const geo=()=>p.evaluate(()=>{const sd=document.getElementById('vside').getBoundingClientRect(), cv=LIVE.canvas&&LIVE.canvas.getBoundingClientRect(), pl=document.getElementById('vsum').getBoundingClientRect();
  return {top:Math.round(sd.top), pos:document.getElementById('vside').dataset.pos, cv:cv?[Math.round(cv.top),Math.round(cv.height)].join('/'):'-', plate:Math.round(pl.top), fit:window.__fit,
   edges:JSON.stringify(vwEdges())};});
const R=[]; const ok=(name,cond,info)=>{R.push((cond?'OK  ':'FAIL')+' '+name+' '+(info||'')); };
let g=await geo(); console.log('start',JSON.stringify(g));
const grip=await p.evaluate(()=>{const r=document.getElementById('vgrip').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};});
// 1. медленный drag вверх 200 px: трасса монотонна, холст не меняется, liveFit не зовётся
await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(600); g=await geo();
const cv0=g.cv, fit0=g.fit; let g0=await p.evaluate(()=>document.getElementById('vgrip').getBoundingClientRect().top);
const gp={x:grip.x,y:g0+20}; await p.mouse.move(gp.x,gp.y); await p.mouse.down(); const trace=[]; let cvSame=true;
for(let i=1;i<=20;i++){await p.mouse.move(gp.x,gp.y-i*10); const q=await geo(); trace.push(q.top); if(q.cv!==cv0)cvSame=false;}
const mono=trace.every((t,i)=>i===0||t<=trace[i-1]); const gMid=await geo();
ok('трасса монотонна при медленном drag',mono,trace.slice(0,6).join(','));
ok('холст не меняется при drag',cvSame,cv0); ok('liveFit не вызывался при drag',gMid.fit===fit0,`${fit0}->${gMid.fit}`);
await p.waitForTimeout(400); await p.mouse.up(); await p.waitForTimeout(800); const gRel=await geo();
ok('медленно отпустил — осталась (±4 px)',Math.abs(gRel.top-gMid.top)<=4,`${gMid.top}->${gRel.top}`);
// 2. резинка: из полной тянем вверх ещё на 200 px
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(1800); const gFull=await geo();
const gy=await p.evaluate(()=>document.getElementById('vgrip').getBoundingClientRect().top+20);
await p.mouse.move(gp.x,gy); await p.mouse.down(); for(let i=1;i<=10;i++)await p.mouse.move(gp.x,gy-i*20); const gRub=await geo();
ok('резинка ≤ 30 % перетяга',(gFull.top-gRub.top)<=0.3*200+6,`сдвиг ${gFull.top-gRub.top} при 200`);
await p.mouse.up(); await p.waitForTimeout(1800); const gBack=await geo(); ok('после резинки вернулась к краю',Math.abs(gBack.top-gFull.top)<=2,`${gBack.top} vs ${gFull.top}`);
// 3. флик вниз 60 px за ~80 мс → свёрнута; флик вверх → полная
const fl=async (dir)=>{await p.evaluate(async dir=>{const g=document.getElementById('vgrip'), r=g.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+20;
  const ev=(t,yy)=>g.dispatchEvent(new PointerEvent(t,{pointerId:7,clientX:x,clientY:yy,bubbles:true,pointerType:'touch'}));
  ev('pointerdown',y); for(let i=1;i<=4;i++){await new Promise(r=>setTimeout(r,20)); ev('pointermove',y+dir*15*i);} ev('pointerup',y+dir*60);},dir);
  await p.waitForTimeout(800); return geo();};
const flOld=async (dir)=>{const y=await p.evaluate(()=>document.getElementById('vgrip').getBoundingClientRect().top+20);
  await p.mouse.move(gp.x,y); await p.mouse.down(); const t0=Date.now(); for(let i=1;i<=4;i++){await p.mouse.move(gp.x,y+dir*15*i);} console.log('flick ms',Date.now()-t0); await p.mouse.up(); await p.waitForTimeout(800); return geo();};
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(700); let gf=await fl(1); ok('флик вниз → свёрнута',gf.pos==='0',`pos ${gf.pos} v=${await p.evaluate('VW.lastFlick')}`);
gf=await fl(-1); ok('флик вверх → полная',gf.pos==='3',`pos ${gf.pos} v=${await p.evaluate('VW.lastFlick')}`);
// 4. тап по ручке: открыть ↔ свернуть
await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(600); await p.click('#vgrip'); await p.waitForTimeout(700); let gt=await geo();
const chip1=await p.$eval('#vchip',e=>e.textContent); ok('тап: свёрнута → полная',gt.pos==='3',chip1);
await p.click('#vgrip'); await p.waitForTimeout(700); gt=await geo(); ok('тап: полная → свёрнута',gt.pos==='0',await p.$eval('#vchip',e=>e.textContent));
// 5. из полной, список у начала, касание вниз 20 px → шторка сдвинулась на ~20 px (CDP touch)
await p.evaluate(()=>{vwSheet(3); document.getElementById('vscroll').scrollTop=0;}); await p.waitForTimeout(700); const gA=await geo();
const cdp=await ctx.newCDPSession(p); const sp=await p.evaluate(()=>{const r=document.getElementById('vscroll').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+120};});
const touch=(type,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'?[]:[{x:sp.x,y}]});
await touch('touchStart',sp.y); for(let i=1;i<=6;i++){await touch('touchMove',sp.y+i*5); await p.waitForTimeout(30);} const gB=await geo();
ok('передача из списка без прыжка (≈ 30−6 px)',Math.abs((gB.top-gA.top)-24)<=8,`сдвиг ${gB.top-gA.top}`);
await touch('touchEnd'); await p.waitForTimeout(800);
// 6. пины после доводки: зона сцены неизменна
await p.click('[data-vm="photo"]').catch(()=>{}); await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(1500);
const pins=async()=>p.evaluate(()=>JSON.stringify(LIVE.scene.pins().filter(x=>x.visible).map(x=>[x.index,Math.round(x.x),Math.round(x.y)])));
const p0=await pins(); await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(1200); const p1=await pins();
ok('пины не смещаются при открытии',p0===p1,'');
await p.screenshot({path:OUT+`v4-${W}-full.png`}); await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(900); await p.screenshot({path:OUT+`v4-${W}-collapsed.png`});
// 7. пузырь ⓘ
await p.click('.vpl-i'); await p.waitForTimeout(300); const bub=await p.evaluate(()=>{const e=document.getElementById('vplBub');return e&&!e.hidden?e.innerText.replace(/\n/g,' | '):null;});
ok('ⓘ открывает расшифровку',!!bub,bub||''); await p.screenshot({path:OUT+`v4-${W}-bubble.png`});
// 8. v5: средняя по содержимому, полная — до верха, раздел и возврат высоты, строки по комнате
await p.click('body',{position:{x:5,y:5}}).catch(()=>{});
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);
const mid=await p.evaluate(()=>{const sd=document.getElementById('vside'), r=document.querySelector('#vGroups .vopts-row:last-child'), top=sd.getBoundingClientRect().top;
  return {vis:Math.round(VW.sheetVis), midH:VW.midH, row:r?Math.round(r.getBoundingClientRect().bottom-top):null, rows:[...document.querySelectorAll('#vGroups .vopts-row b')].map(b=>b.textContent)};});
ok('v5 средняя = строки-входы + верх списка (±8)',mid.row!=null&&Math.abs(mid.vis-mid.row-30)<=8,JSON.stringify(mid));
ok('v5 в гостиной строки-входа — только «Отделка и ремонт»',JSON.stringify(mid.rows)==='["Отделка и ремонт"]',JSON.stringify(mid.rows));
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(900); const gF=await geo();
ok('v5 полная — плашка у верха экрана (≤ 10 px)',gF.plate<=10&&gF.plate>=0,`плашка ${gF.plate}, шторка ${gF.top}`);
await p.screenshot({path:OUT+`v5-${W}-full.png`});
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800); const vis0=await p.evaluate('VW.sheetVis');
await p.click('#vGroups [data-opts]'); await p.waitForTimeout(900); const gO=await geo();
const sec=await p.evaluate(()=>({t:document.getElementById('vgTitle').textContent, fl:document.querySelectorAll('#vfloor [data-fl]').length, list:getComputedStyle(document.querySelector('#vlist .vitems')).display}));
ok('v5 «Отделка» → полная, раздел вместо списка',gO.pos==='3'&&sec.fl>0&&sec.list==='none',JSON.stringify(sec));
await p.screenshot({path:OUT+`v5-${W}-finish.png`});
await p.click('#vOptsBack'); await p.waitForTimeout(900); const vis1=await p.evaluate('VW.sheetVis');
ok('v5 «← Назад» — прежняя высота (±2)',Math.abs(vis1-vis0)<=2,`${vis0} → ${vis1}`);
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800); await p.screenshot({path:OUT+`v5-${W}-mid.png`});
// 9. v5: окно комнаты с группой кухни (`?debug=1&vroom=kitchen`) — строка «Встраиваемое», четыре карточки, выбор → s2 и ссылка
await p.goto('https://remont-lab.online/demo/?live=0&debug=1&vroom=kitchen',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.evaluate(()=>openLiveWindow()); await p.waitForTimeout(2500);
await p.click('#vGroups [data-group="fitted"]'); await p.waitForTimeout(900);
const fit=await p.evaluate(()=>({cards:[...document.querySelectorAll('#vfitted .vfit')].map(b=>b.querySelector('b').textContent+' · '+b.querySelector('.vfit-p').textContent), s:curStateId()}));
ok('v5 «Встраиваемое» → 4 карточки кухни',fit.cards.length===4,fit.cards.join(' | '));
await p.screenshot({path:OUT+`v5-${W}-fitted.png`});
await p.click('#vfitted [data-fl="kitchen:kitchen-practical"]'); await p.waitForTimeout(700);
const fit2=await p.evaluate(()=>({s:curStateId(), dev:JSON.stringify(DEVOPT), href:(document.getElementById('vFlat')||{}).href||''}));
ok('v5 выбор кухни → s2, DEVOPT, ссылка',/^s2-/.test(fit2.s)&&fit2.dev.includes('kitchen-practical')&&fit2.href.includes('kitchen:kitchen-practical'),JSON.stringify(fit2));
await p.click('#vOptsBack'); await p.waitForTimeout(700);
ok('v5 сводка строки обновилась',(await p.$eval('#vGroups [data-group="fitted"] span',e=>e.textContent)).includes('Practical'),await p.$eval('#vGroups [data-group="fitted"] span',e=>e.textContent));
console.log(R.join('\n')); console.log('plate',await p.$eval('#vsum .vpl-row',e=>e.innerText.replace(/\n/g,' '))); console.log('errs',errs.slice(0,4)); await b.close();})().catch(e=>{console.error(e);process.exit(1);});
