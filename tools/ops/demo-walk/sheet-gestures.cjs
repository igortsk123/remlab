const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПРОВЕРКА ЖЕСТОВ ШТОРКИ v4 (план demo-02 § «Шторка v4» п.4): трасса, неизменный холст, резинка, флик, тап, передача из списка, пины.
//   PROD=1 node tools/ops/demo-walk/sheet-gestures.cjs 375x667          — прод как есть
//   SP=<папка с floorlib/ сборки движка> node … 390x844                  — локальная страница и движок поверх прода
//   LOCAL=1 node … 375x667                                               — только локальная страница, движок — прода
// v5 (шторка v5): полная остановка — плашка у верха экрана; средняя — по содержимому; раздел «Отделка» → полная, «← Назад» —
// прежняя высота; строки-входы по комнате окна (гостиная — без «Встраиваемое»; `?debug=1&vroom=kitchen` — карточки кухни)
// v5.2: свёрнутая = плашка + чип + кнопка (кнопка целиком в экране, высота ≤ 190 px на высоте 667) — при открытии окна и после
// замены; тап по предмету — список прокручен сразу (через 50 мс), строка в верхней трети к концу подъёма.
//   EN=1 — английский; ширина > 700 (1440x900) — только колонка компьютера: кнопка под плашкой, не уезжает с прокруткой (2.32)
const CTA=require('./cta-rule.cjs');
const SP=process.env.SP, LOCAL=process.env.LOCAL, EN=!!process.env.EN, OUT=process.env.OUT||require('os').tmpdir()+'/'; const prod=!LOCAL&&(process.env.PROD||!SP);
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
await p.goto('https://remont-lab.online/demo/?live=force'+(EN?'&lang=en':''),{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
const R=global.__R=[]; const ok=(name,cond,info)=>{R.push((cond?'OK  ':'FAIL')+' '+name+' '+(info||'')); };
const SFX=(EN?'-en':'')+'-'+W+'x'+H;
// v5.2: положение шторки и кнопки — до переключения режима (окно само в «Фото», если есть снимок) и в 3D
const head=()=>p.evaluate(()=>{const sd=document.getElementById('vside'), c=document.getElementById('vCta'), r=c.getBoundingClientRect(), pl=document.getElementById('vsum').getBoundingClientRect();
  return {pos:sd.dataset.pos, h:Math.round(innerHeight-sd.getBoundingClientRect().top), top:Math.round(r.top), cta:c.hidden?'hidden':[Math.round(r.top),Math.round(r.bottom)].join('-'),
    inScreen:!c.hidden&&r.top>=0&&r.bottom<=innerHeight, ctaTxt:c.textContent, plate:Math.round(pl.bottom), mode:VW.mode, chip:document.getElementById('vchip').textContent};});
await p.evaluate(()=>openLiveWindow()); await p.waitForTimeout(1500);
const hOpen=await head(); console.log('open',JSON.stringify(hOpen)); await p.screenshot({path:OUT+`v52${SFX}-open-${hOpen.mode}.png`});
if(W>700){   // КОМПЬЮТЕР (2.32): кнопка — под плашкой, при прокрутке списка не уезжает
  await p.evaluate(()=>{if(VW.mode==='photo')vwMode('walk');}); await p.waitForTimeout(1500);
  const d0=await head(); await p.evaluate(()=>{document.getElementById('vscroll').scrollTop=400;}); await p.waitForTimeout(400); const d1=await head();
  ok('1440: кнопка под плашкой',CTA.ctaUnderPlate(d0),JSON.stringify(d0));   // правило — `cta-rule.cjs`, общее с fav-check
  ok('1440: прокрутка списка — кнопка на месте',d1.cta===d0.cta,`${d0.cta} → ${d1.cta}`);
  await p.screenshot({path:OUT+`v52${SFX}-desk.png`});
  const idx=await p.evaluate(()=>items.findIndex(it=>vwRowOf(it))); await p.evaluate(i=>{document.getElementById('vscroll').scrollTop=0; vwHighlight(i);},idx); await p.waitForTimeout(900);
  const hl=await p.evaluate(()=>{const r=document.querySelector('#shotbody .row.hl'), sc=document.getElementById('vscroll'); const rr=r&&r.getBoundingClientRect(), sr=sc.getBoundingClientRect();
    return rr?{rowTop:Math.round(rr.top-sr.top), list:sc.clientHeight}:null;});
  ok('1440: тап по предмету — строка в верхней трети списка',!!hl&&hl.rowTop>=0&&hl.rowTop<=hl.list/3,JSON.stringify(hl));
  console.log(R.join('\n')); console.log('errs',errs.slice(0,4)); await b.close(); return;}
ok('v5.2 окно открылось свёрнутым',hOpen.pos==='0',JSON.stringify(hOpen));
await p.evaluate(()=>{if(VW.mode==='photo')vwMode('walk');}); await p.waitForFunction(()=>LIVE.scene,null,{timeout:120000}); await p.waitForTimeout(1200);
const h3d=await head();
ok('v5.2 в 3D свёрнутая: кнопка целиком в экране',h3d.pos==='0'&&h3d.inScreen,JSON.stringify(h3d));
ok('v5.2 высота свёрнутой ≤ 190 px (на 667)',H>667||h3d.h<=190,`${h3d.h} px`);
ok('v5.2 кнопка — «'+(EN?'Make it realistic':'Сделать реалистичнее')+'»',EN?/realistic/.test(h3d.ctaTxt)&&!/[А-Яа-я]/.test(h3d.ctaTxt+h3d.chip):/реалистичнее/.test(h3d.ctaTxt),h3d.ctaTxt+' · '+h3d.chip);
await p.screenshot({path:OUT+`v52${SFX}-open.png`});   // у варианта есть фото — окно в «Фото», жесты меряем в 3D await p.waitForTimeout(8000);
await p.evaluate(()=>{window.__fit=0; const o=liveFit; liveFit=function(){window.__fit++; return o.apply(this,arguments);};});
const geo=()=>p.evaluate(()=>{const sd=document.getElementById('vside').getBoundingClientRect(), cv=LIVE.canvas&&LIVE.canvas.getBoundingClientRect(), pl=document.getElementById('vsum').getBoundingClientRect();
  return {top:Math.round(sd.top), pos:document.getElementById('vside').dataset.pos, cv:cv?[Math.round(cv.top),Math.round(cv.height)].join('/'):'-', plate:Math.round(pl.top), fit:window.__fit,
   edges:JSON.stringify(vwEdges())};});
// ожидание конца анимации — по состоянию, не по часам: на загруженной машине (3D на программной графике) сдвиг идёт дольше 0,9 с
const still=()=>p.waitForFunction(()=>{const sd=document.getElementById('vside'), t=Math.round(sd.getBoundingClientRect().top);
  const ok=window.__lt===t; window.__lt=t; return ok&&!sd.getAnimations().length;},null,{polling:150,timeout:5000}).catch(()=>{});
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
const chip1=await p.$eval('#vchip',e=>e.textContent); ok('тап: свёрнута → полная, чип «Свернуть»',gt.pos==='3'&&/Свернуть|Collapse/.test(chip1),chip1);
await p.click('#vgrip'); await p.waitForTimeout(700); gt=await geo(); const hc=await head();
ok('тап «Свернуть»: полная → свёрнута, кнопка в экране',gt.pos==='0'&&hc.inScreen,await p.$eval('#vchip',e=>e.textContent)+' '+hc.cta);
// 5. из полной, список у начала, касание вниз 20 px → шторка сдвинулась на ~20 px (CDP touch)
await p.evaluate(()=>{vwSheet(3); document.getElementById('vscroll').scrollTop=0;}); await p.waitForTimeout(700); const gA=await geo();
const cdp=await ctx.newCDPSession(p); const sp=await p.evaluate(()=>{const r=document.getElementById('vscroll').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+120};});
const touch=(type,y)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'?[]:[{x:sp.x,y}]});
await touch('touchStart',sp.y); for(let i=1;i<=6;i++){await touch('touchMove',sp.y+i*5); await p.waitForTimeout(30);} const gB=await geo();
ok('передача из списка без прыжка (≈ 30−6 px)',Math.abs((gB.top-gA.top)-24)<=8,`сдвиг ${gB.top-gA.top}`);
await touch('touchEnd'); await p.waitForTimeout(800);
// 6. пины после доводки: зона сцены неизменна
await p.evaluate(()=>vwMode('walk'));   // пины — в 3D (demo-09: в «Фото» их нет) await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(1500);
const pins=async()=>p.evaluate(()=>JSON.stringify(LIVE.scene.pins().filter(x=>x.visible).map(x=>[x.index,Math.round(x.x),Math.round(x.y)])));
const p0=await pins(); await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(1200); const p1=await pins();
ok('пины не смещаются при открытии',p0===p1,'');
await p.screenshot({path:OUT+`v4-${W}-full.png`}); await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(900); await p.screenshot({path:OUT+`v4-${W}-collapsed.png`});
// 7. пузырь ⓘ — у шкалы окна («i» есть и у шкалы главной под окном, demo-19 Б2)
await p.click('#vsum .vpl-i'); await p.waitForTimeout(300); const bub=await p.evaluate(()=>{const e=document.getElementById('vplBub');return e&&!e.hidden?e.innerText.replace(/\n/g,' | '):null;});
ok('ⓘ открывает расшифровку',!!bub,bub||''); await p.screenshot({path:OUT+`v4-${W}-bubble.png`});
// 8. v5: средняя по содержимому, полная — до верха, раздел и возврат высоты, строки по комнате
await p.evaluate(()=>{const bb=document.getElementById('vplBub'); if(bb)bb.hidden=true;});   // закрыть пузырь ⓘ (клик по сцене открыл бы фото)
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);
const mid=await p.evaluate(()=>{const sd=document.getElementById('vside'), r=document.querySelector('#vGroups .vopts-row:last-child'), top=sd.getBoundingClientRect().top;
  return {vis:Math.round(VW.sheetVis), midH:VW.midH, row:r?Math.round(r.getBoundingClientRect().bottom-top):null, rows:[...document.querySelectorAll('#vGroups .vopts-row b')].map(b=>b.textContent)};});
ok('v5 средняя = строки-входы + верх списка (±8)',mid.row!=null&&Math.abs(mid.vis-mid.row-30)<=8,JSON.stringify(mid));
ok('v5.1 плашка — часть шторки (не над фото)',(await geo()).plate>=(await geo()).top,'');
ok('v5 в гостиной строки-входа — только «Отделка и ремонт»',JSON.stringify(mid.rows)===(EN?'["Options & upgrades"]':'["Отделка и ремонт"]'),JSON.stringify(mid.rows));
await p.evaluate(()=>vwSheet(3)); await still(); const gF=await geo();
ok('v5.1 полная — шторка до верха, плашка в её шапке (≤ 30 px)',gF.top<=2&&gF.plate<=30&&gF.plate>=gF.top,`плашка ${gF.plate}, шторка ${gF.top}`);
await p.screenshot({path:OUT+`v5-${W}-full.png`});
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800); const vis0=await p.evaluate('VW.sheetVis');
await p.click('#vGroups [data-opts]'); await p.waitForTimeout(900); const gO=await geo();
const sec=await p.evaluate(()=>({t:document.getElementById('vgTitle').textContent, fl:document.querySelectorAll('#vfloor [data-fl]').length, list:getComputedStyle(document.querySelector('#vlist .vitems')).display}));
ok('v5 «Отделка» → полная, раздел вместо списка',gO.pos==='3'&&sec.fl>0&&sec.list==='none',JSON.stringify(sec));
await p.screenshot({path:OUT+`v5-${W}-finish.png`});
await p.click('#vOptsBack'); await p.waitForTimeout(900); const vis1=await p.evaluate('VW.sheetVis');
ok('v5 «← Назад» — прежняя высота (±2)',Math.abs(vis1-vis0)<=2,`${vis0} → ${vis1}`);
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800); await p.screenshot({path:OUT+`v5-${W}-mid.png`}); await p.screenshot({path:OUT+`v52${SFX}-mid.png`});
const hMid=await head(); ok('v5.2 средняя: кнопка в экране, выше свёрнутой',hMid.inScreen&&hMid.h>h3d.h,`${h3d.h} → ${hMid.h}`);
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(800); await p.screenshot({path:OUT+`v52${SFX}-full.png`});
// 8б. v5.1: 10 тапов по чипу из свёрнутой (CDP-касания) — шторка раскрыта каждый раз, «Сделать реалистичнее» не нажата ни разу.
// Ожидание — по состоянию, не по часам: на загруженной машине анимация идёт дольше 0,3 с
await p.evaluate(()=>{window.__mp=0; makePhoto=function(){window.__mp++;};});
let opened=0; const tl=[]; for(let k=0;k<10;k++){await p.evaluate(()=>vwSheet(0)); await still();
  const c=await p.evaluate(()=>{const r=document.getElementById('vchip').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:c.x,y:c.y}]}); await p.waitForTimeout(50+k*12);
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  const got=await p.waitForFunction(()=>document.getElementById('vside').dataset.pos==='3',null,{timeout:3000}).then(()=>true).catch(()=>false);
  await still(); tl.push(got?'3':'0'); if(got)opened++;}
ok('v5.1 тап по чипу ×10: раскрыта 10/10, ложных «Сделать реалистичнее» 0',opened===10&&(await p.evaluate('window.__mp'))===0,`раскрыта ${opened}, makePhoto ${await p.evaluate('window.__mp')} · ${tl.join('')}`);
// v5.2 п.5: тап по предмету — прокрутка списка сразу, вместе с подъёмом шторки (не вторым движением)
{const idx=await p.evaluate(()=>{vwSelect(null); const k=items.map((it,i)=>[i,vwRowOf(it)]).filter(x=>x[1]).map(x=>x[0]); return k[Math.floor(k.length/2)];});   // средняя строка — прокрутка нужна и возможна
 await p.evaluate(()=>{vwSheet(0); document.getElementById('vscroll').scrollTop=0;}); await still();
 const st0=await p.evaluate(i=>{vwHighlight(i); return document.getElementById('vscroll').scrollTop;},idx);
 await p.waitForTimeout(50); const st50=await p.evaluate(()=>document.getElementById('vscroll').scrollTop); await still();
 const hl=await p.evaluate(()=>{const r=document.querySelector('#shotbody .row.hl'), sc=document.getElementById('vscroll'); const rr=r&&r.getBoundingClientRect(), sr=sc.getBoundingClientRect();
   return {pos:document.getElementById('vside').dataset.pos, top:Math.round(sc.scrollTop), row:rr?Math.round(rr.top-sr.top):null, list:sc.clientHeight};});
 ok('v5.2 тап по предмету: список прокручен через 50 мс',st50>0&&Math.abs(st50-hl.top)<=2,`сразу ${st0}, 50 мс ${st50}, итог ${hl.top}`);
 ok('v5.2 тап по предмету: полная, строка в верхней трети',hl.pos==='3'&&hl.row!=null&&hl.row>=0&&hl.row<=hl.list/3,JSON.stringify(hl));
 await p.evaluate(()=>vwSelect(null));}
// v5.2: замена товара (как кнопка ленты) → свёрнутая с кнопкой целиком
{await p.evaluate(()=>vwSheet(3)); await still();
 const n=await p.evaluate(()=>{const k=items.findIndex(it=>vwRowOf(it)); sel=items[k]; draw(); openPicker(items[k]); const cur0=(skuOf(items[k])||{}).name;
   const c=feedFor(String(items[k].role).replace(/\s+\d+$/,'')).find(x=>x&&x.name&&x.name!==cur0); if(!c)return 0; tryOn(c); closePicker(); refreshShotList(); return 1;});
 await p.waitForTimeout(1200); await still(); const hr=await head();
 ok('v5.2 после замены — свёрнутая, кнопка целиком в экране',n===1&&hr.pos==='0'&&hr.inScreen,JSON.stringify(hr));
 await p.screenshot({path:OUT+`v52${SFX}-replaced.png`});}
const f3=[]; for(let k=0;k<3;k++){await p.evaluate(()=>vwSheet(0)); await still(); await p.evaluate(()=>vwSheet(3)); await still(); f3.push((await geo()).top);}
ok('v5.1 полная с первого раза 3/3',f3.every(t=>t<=2),f3.join(','));
await p.evaluate(()=>vwSheet(0)); await p.waitForTimeout(700); await p.screenshot({path:OUT+`v51-${W}-collapsed.png`});
// v5.2 п.6: «×» закрывает верхний слой — при полной сворачивает список, при свёрнутой закрывает окно
{await p.evaluate(()=>vwSheet(3)); await still(); const l3=await p.evaluate(()=>{const x=document.getElementById('shotx'); return x?x.getAttribute('aria-label'):'нет #shotx · '+location.href;});
 await p.click('#shotx'); await still();
 const x1=await p.evaluate(()=>({on:document.getElementById('shot').classList.contains('on'), pos:document.getElementById('vside').dataset.pos, label:document.getElementById('shotx').getAttribute('aria-label')}));
 ok('v5.2 «×» при полной → окно открыто, свёрнута',x1.on&&x1.pos==='0',`${l3} → ${JSON.stringify(x1)}`);
 await p.click('#shotx'); await p.waitForTimeout(500);
 ok('v5.2 «×» при свёрнутой → окно закрыто',!(await p.evaluate(()=>document.getElementById('shot').classList.contains('on'))),'');}
// 9. v5: окно комнаты с группой кухни (`?debug=1&vroom=kitchen`) — строка «Встраиваемое», четыре карточки, выбор → s2 и ссылка
await p.goto('https://remont-lab.online/demo/?live=0&debug=1&vroom=kitchen',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.evaluate(()=>{openLiveWindow(); vwSheet(2);}); await p.waitForTimeout(2500);   // шторка с прошлого шага свёрнута — раскрыть, как человек
await p.click('#vGroups [data-group="fitted"]'); await p.waitForTimeout(900);
const fit=await p.evaluate(()=>({cards:[...document.querySelectorAll('#vfitted .vfit')].map(b=>b.querySelector('b').textContent+' · '+b.querySelector('.vfit-p').textContent), s:curStateId()}));
ok('v5 «Встраиваемое» → 4 карточки кухни',fit.cards.length===4,fit.cards.join(' | '));
await p.screenshot({path:OUT+`v5-${W}-fitted.png`});
await p.click('#vfitted [data-fl="kitchen:kitchen-practical"]'); await p.waitForTimeout(700);
const fit2=await p.evaluate(()=>({s:curStateId(), dev:JSON.stringify(DEVOPT), href:(document.getElementById('vFlat')||{}).href||''}));
ok('v5 выбор кухни → s2, DEVOPT, ссылка',/^s2-/.test(fit2.s)&&fit2.dev.includes('kitchen-practical')&&fit2.href.includes('kitchen:kitchen-practical'),JSON.stringify(fit2));
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(700);   // выбор кухни свернул шторку (demo-09 п.4a) — раскрыть
await p.click('#vOptsBack'); await p.waitForTimeout(700);
ok('v5 сводка строки обновилась',(await p.$eval('#vGroups [data-group="fitted"] span',e=>e.textContent)).includes('Practical'),await p.$eval('#vGroups [data-group="fitted"] span',e=>e.textContent));
console.log(R.join('\n')); console.log('plate',await p.$eval('#vsum .cs-t',e=>e.innerText.replace(/\n/g,' '))); console.log('errs',errs.slice(0,4)); await b.close();})().catch(e=>{console.log((global.__R||[]).join('\n')); console.error(e);process.exit(1);});
