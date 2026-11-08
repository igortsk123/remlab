const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// РЕЖИМЫ ОКНА (план demo-09): три сценария — «без реалистичного фото», «готово для текущего stateId», «состояние изменилось во время
// задания» — плюс «без 3D» и EN. Платный путь НЕ вызывается: ответы /api/render и /api/job подменяются (готовое фото = картинка товара).
//   PROD=1 node tools/ops/demo-walk/modes-check.cjs 375x667          — прод как есть (платный путь подменён ВО ВСЕХ сценариях)
//   SP=<папка с floorlib/> node … 375x667                            — локальная страница и движок поверх прода
//   PROD=1 BASE=http://127.0.0.1:8799/demo/ node … 375x667            — другая сборка (stage-proxy), страница как есть
const {demoUrl}=require('../demo-url.cjs');
const SP=process.env.SP, OUT=process.env.OUT||require('os').tmpdir()+'/', prod=!!process.env.PROD||!SP;
const BASE=process.env.BASE||'https://remont-lab.online/demo/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number);
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i||''));
// размер JPEG по маркеру SOF0/SOF2 — без зависимостей
function jpegSize(b){for(let i=2;i<b.length-9;){if(b[i]!==0xFF){i++;continue;} const m=b[i+1], L=b.readUInt16BE(i+2);
  if(m===0xC0||m===0xC2)return [b.readUInt16BE(i+7),b.readUInt16BE(i+5)]; i+=2+L;} return null;}
async function page(b,q,lang){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:W<=700,hasTouch:W<=700,locale:lang==='en'?'en-GB':'ru-RU'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  if(!prod){const F=JSON.parse(fs.readFileSync(SP+'/floorlib/scene.json','utf8')).file;
    await p.route(/\/demo\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(SP+'/floorlib/scene.json','utf8')}));
    await p.route(/\/demo\/lib\/scene\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+F,'utf8')}));
    // модуль корзины той же сборки (его версия — в том же scene.json; на проде такого файла ещё нет)
    await p.route(/\/demo\/lib\/basket\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+r.request().url().split('/').pop().split('?')[0],'utf8')}));
    await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));}
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  // подмена съёмки: задание отвечает «готово» по флагу страницы `__fakeReady` (сценарий 3 успевает изменить расстановку)
  await p.route(/\/api\/render/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.route(/\/api\/job\?/,async r=>{const ready=await p.evaluate(()=>!!window.__fakeReady).catch(()=>false);
    const img=await p.evaluate(()=>{const it=(allVariants()[cur]||{}).items||[]; const x=it.find(i=>i.sku&&i.sku.img); return x?new URL(x.sku.img,location.href).href:'';}).catch(()=>'');
    r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(ready?{shots:[{camera:'C1',url:img},{camera:'C2',url:img}],backend:'fake'}:{status:'running',eta:30})});});
  // кадры из браузера (demo-10): загрузка перехвачена — имя = sha256 тела, кадр сохраняется для глаза; тело задания запоминается
  p.frames=[]; p.renderBodies=[];
  await p.route(/\/api\/render\/frame/,r=>{const buf=r.request().postDataBuffer()||Buffer.alloc(0); const id=require('crypto').createHash('sha256').update(buf).digest('hex');
    fs.writeFileSync(OUT+'frame-'+id.slice(0,8)+'.jpg',buf); p.frames.push({id,bytes:buf.length,w:buf.readUInt16BE?jpegSize(buf):null}); r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id,bytes:buf.length})});});
  p.on('request',rq=>{if(rq.method()==='POST'&&/\/api\/render(\?|$)/.test(rq.url())){try{p.renderBodies.push(JSON.parse(rq.postData()||'{}'));}catch(e){}}});
  await p.goto(demoUrl(BASE+q),{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  // РЕЕСТР КАДРОВ — ДО ЧИСТКИ `shots` (T-20261107-66/2): пришедший позже реестр заменяет весь список (реалистичные снова в нём), а окно,
  // открытое в 3D без фото, по его приходу встаёт на «Фото» (правило А1) — сценарий «без фото» ломался посреди шага
  await p.waitForFunction("SHOTS_LOADED&&shots.some(x=>x.srv)",null,{timeout:60000});
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){}});
  return p;
}
const st=p=>p.evaluate(()=>({mode:VW.mode, photoTab:!(document.querySelector('[data-vm="photo"]')||{hidden:true}).hidden,
  cta:(()=>{const c=document.getElementById('vCta'); return c&&!c.hidden?c.innerText.replace(/\n/g,' '):null;})(),
  pins:[...document.querySelectorAll('#vpins .vpin')].filter(n=>!n.hidden).length, pos:(document.getElementById('vside')||{dataset:{}}).dataset.pos,
  stub:(()=>{const e=document.getElementById('vStub'); return !!e&&getComputedStyle(e).display!=='none';})(),
  ready:!!document.querySelector('#shot .vready'), err:(document.getElementById('vCtaErr')||{}).textContent||'', sid:curStateId()}));
// суммы и состав окна (шкала `#vsum` — итоговые цифры через 1,8 с после правки, анимация 0,45 с), главная — пересчитана тут же (`drawHome`)
const sums=p=>p.evaluate(()=>{const s=document.getElementById('vsum'); try{drawHome();}catch(e){}
  const a=document.querySelector('#hmRooms article.hm-room[data-room="'+((allVariants()[cur]||{}).room||'living')+'"]')||document.querySelector('#hmRooms article.hm-room');
  return {sid:curStateId(), mode:VW.mode, stale:!!document.querySelector('#shot .vstale'), plate:s?s.textContent.replace(/\s+/g,' '):'',
    chip:(document.getElementById('vchip')||{}).textContent||'', list:[...document.querySelectorAll('#vside .vitems > *')].map(e=>e.textContent.replace(/\s+/g,' ').trim()).join(' | '),
    comp:items.map(i=>i.role+'='+((i.sku||{}).name||'')), decor:decorList().map(x=>(x.sku||{}).name||''), dev:JSON.stringify(DEVOPT),
    homeInc:(document.getElementById('hmCert')||{dataset:{}}).dataset.included, homeCard:a?(a.querySelector('.rb .sum')||{}).textContent:''};});
// кадр живой сцены с точки 1 (одна поза — сравнимо до и после) и подписи моделей; разница — средняя по пикселям, 0…255
async function frame3d(p){
  const m0=await p.evaluate(()=>VW.mode); await p.evaluate(()=>vwMode('walk'));
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:120000}).catch(()=>{}); await p.waitForTimeout(2500);
  const r=await p.evaluate(async()=>{if(!LIVE.scene||!LIVE.scene.capture)return null; const c=(cams||loadCams())[0]; const x=await LIVE.scene.capture([camPoseOf(c)],320,226);
    const bm=await createImageBitmap(x.frames[0]), cv=document.createElement('canvas'); cv.width=320; cv.height=226; const g=cv.getContext('2d'); g.drawImage(bm,0,0);
    return {px:Array.from(g.getImageData(0,0,320,226).data.filter((_,i)=>i%4!==3)), models:LIVE.scene.models()};}).catch(()=>null);
  await p.evaluate(m=>vwMode(m),m0); await p.waitForTimeout(800);
  return r;
}
const diff3d=(a,b)=>{let s=0; for(let i=0;i<a.length;i++)s+=Math.abs(a[i]-b[i]); return +(s/a.length).toFixed(2);};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
// упала посреди шага — накопленные OK/FAIL всё равно печатаются, падение — отдельной строкой FAIL (T-20261107-66/2)
try{
// 1. без реалистичного фото: 3D, вкладки «Фото» нет, ценники, стрелки — к позе 2 и обратно
let p=await page(b,'?live=force&lang=ru','ru');
await p.evaluate(()=>{shots=shots.filter(x=>x.quality!=='realistic'); openLiveWindow();});
await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:150000}).catch(()=>{}); await p.waitForTimeout(2500);
let s=await st(p); ok('1 без фото — открыто 3D, вкладки «Фото» нет',s.mode==='walk'&&!s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
ok('1 ценники над мебелью в 3D (≥ 3)',s.pins>=3,'видно '+s.pins);
ok('1 «Сделать реалистичнее» видна в 3D',!!s.cta&&/реалистичнее/.test(s.cta),s.cta);
const dz=await p.evaluate(()=>{const d=document.getElementById('vCams').getBoundingClientRect(), t=document.getElementById('vside').getBoundingClientRect(); return {dots:Math.round(d.bottom), sheet:Math.round(t.top)};});
if(W<=700)ok('1 точки ракурсов над верхом шторки',dz.dots<=dz.sheet,JSON.stringify(dz));
await p.screenshot({path:OUT+`m09-${W}-walk.png`});
// 1в. «СКРЫТЬ ЦЕНЫ» (T-20261108-75, владелец TG 606): в 3D вверху «Скрыть цены» (на месте «Сменить стиль») → ценников 0 → «Показать цены» →
// ценники вернулись; в «Фото» — «Сменить стиль» (шаг 2)
const pb=()=>p.evaluate(()=>{const v=id=>{const e=document.getElementById(id); return e&&e.offsetParent?e.innerText.trim():null;};
  return {price:v('vPriceTop'), style:v('vOtherTop'), pins:[...document.querySelectorAll('#vpins .vpin')].filter(n=>!n.hidden).length};});
let pz=await pb(); ok('1в в 3D вверху «Скрыть цены», «Сменить стиль» нет',pz.price==='Скрыть цены'&&!pz.style&&pz.pins>=3,JSON.stringify(pz));
await p.click('#vPriceTop'); await p.waitForTimeout(600); pz=await pb();
ok('1в «Скрыть цены» → ценников 0, кнопка «Показать цены»',pz.pins===0&&pz.price==='Показать цены',JSON.stringify(pz));
await p.click('#vPriceTop'); await p.waitForFunction(()=>[...document.querySelectorAll('#vpins .vpin')].some(n=>!n.hidden),null,{timeout:20000}).catch(()=>{}); pz=await pb();
ok('1в «Показать цены» → ценники вернулись',pz.pins>=3&&pz.price==='Скрыть цены',JSON.stringify(pz));
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
// 2. «Сделать реалистичнее» → сразу вкладка «Фото» и на ней «Улучшаю… N %» во весь кадр (demo-20 Б3, владелец 22.10 TG 791/795) → готово → снимок сам
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);
await p.click('#vCta'); await p.waitForTimeout(1500); s=await st(p);
const pw2=await p.evaluate(()=>{const o=document.querySelector('#shot .vphwait'); return o?o.querySelector('b').textContent:'';});
ok('2 после нажатия — сразу «Фото» с ходом работы',s.mode==='photo'&&s.photoTab&&/^(Улучшаю…|Enhancing…) \d+ %$/.test(pw2),JSON.stringify({mode:s.mode,tab:s.photoTab,wait:pw2}));
// заказ уходит после съёмки кадров — на 1440 под программной графикой это дольше 1,5 с: ждём сам заказ, не время
for(let t=0;t<40&&!p.renderBodies.some(x=>x.quality==='realistic');t++)await p.waitForTimeout(500);
const rb=p.renderBodies.filter(x=>x.quality==='realistic').pop()||{};
ok('2 кадры из браузера: оба вида загружены и в задании только их имена',(rb.views||[]).length===2&&rb.views.every(v=>/^[0-9a-f]{64}$/.test(v.id))&&rb.views.every(v=>p.frames.some(f=>f.id===v.id)),
  JSON.stringify({views:rb.views, frames:p.frames.map(f=>[f.id.slice(0,8),f.bytes,f.w]), cap:await p.evaluate('JSON.stringify(VW.lastCapture)')}));
// ВСЕГДА ШИРОКИЕ виды под лист 2048×3072 на любом устройстве (demo-20 Г1, владелец 22.10: «не обрезай под телефон»; обрезка — только при показе)
const okSize=f=>f.w&&((f.w[0]===2048&&f.w[1]===1489)||(f.w[0]===1536&&f.w[1]===1117));
ok('2 размер кадра — широкий на любом устройстве',p.frames.length>=2&&p.frames.slice(-2).every(okSize),JSON.stringify(p.frames.slice(-2).map(f=>f.w)));
ok('2 ориентация листа в задании — широкая',rb.sheet==='landscape',String(rb.sheet));
// окно уже на «Фото» с самого нажатия — ждём конец задания, а не режим (иначе шаг 4 правил бы под замком «Улучшаю…», demo-20 Г5)
await p.evaluate(()=>{window.__fakeReady=1;}); await p.waitForFunction(()=>!VJ.job&&VW.mode==='photo',null,{timeout:20000}).catch(()=>{}); s=await st(p);
ok('2 готово для этой расстановки → «Фото» открылось само, кнопки нет',s.mode==='photo'&&s.photoTab&&s.cta===null,JSON.stringify({mode:s.mode,tab:s.photoTab,cta:s.cta}));
await p.screenshot({path:OUT+`m09-${W}-photo.png`});
// 4. изменение → 3D и шторка вниз (телефон)
// до правки — суммы окна, чип, список шторки, главная, состав и кадр 3D с точки 1: «Вернуть как было» (4в) должно вернуть всё
const s0=await sums(p), f0=await frame3d(p);
// 4-0. ЛЕГЕНДА ПОД ШКАЛОЙ «ВЫБРАНО» (T-20261108-74, владелец 08.11 TG 598, 612): строки «Другие комнаты» нет нигде (телефон и компьютер) —
// «по общей сумме и так понятно»; «Эта комната N ₽» есть
const lg=await p.evaluate(()=>({li:[...document.querySelectorAll('#vsum .cs-room .li')].map(e=>({t:e.textContent.replace(/\s+/g,' ').trim(),
  vis:getComputedStyle(e).display!=='none'&&e.getBoundingClientRect().height>0})), oth:/Другие комнаты|Other rooms/.test((document.getElementById('vsum')||{}).textContent||'')}));
ok('4-0 под шкалой «Выбрано» — только «Эта комната N ₽», строки «Другие комнаты» нет',
  lg.li.length===1&&lg.li[0].vis&&/^(Эта комната|This room) .*\d/.test(lg.li[0].t)&&!lg.oth,JSON.stringify(lg));
await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(800);
await p.evaluate(()=>{const g=devGroups().find(x=>x.kind==='flooring'); if(g)devSet(g.id,g.variants[1].id);}); await p.waitForTimeout(1500); s=await st(p);
// после правки вкладка «Фото» остаётся: на ней прежнее фото затемнённым, «Вы изменили комнату» и две кнопки (T-20261107-66 Б)
ok('4 смена пола → 3D, вкладка «Фото» есть',s.mode==='walk'&&s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
if(W<=700)ok('4a шторка свернулась сама',s.pos==='0','pos '+s.pos);
await p.evaluate(()=>vwMode('photo')); await p.waitForTimeout(800);
const stl=await p.evaluate(()=>{const o=document.querySelector('#shot .vstale'); return {mode:VW.mode, txt:o?o.innerText.replace(/\n+/g,' / '):'', back:!!(o&&o.querySelector('[data-st="back"]'))};});
ok('4б «Фото» после правки — затемнено, «Вы изменили комнату», «Сделать реалистичнее» и «Вернуть как было»',
  stl.mode==='photo'&&/Вы изменили комнату/.test(stl.txt)&&/Сделать реалистичнее/.test(stl.txt)&&!/Показать изменения/.test(stl.txt)&&stl.back,JSON.stringify(stl));
// 4б. ПЛАШКА ОКНА КОМПАКТНАЯ, ПОЛУПРОЗРАЧНАЯ, ПО ЦЕНТРУ ВИДИМОГО КАДРА (T-20261108-77, владелец TG 618/619): кнопки в ряд 30–40 px, не под
// верхними кнопками и не на подписях ракурсов; на телефоне — по центру между ними и шторкой; текст кнопок — цвет страницы (не синий Safari)
const stg=await p.evaluate(()=>{const R=e=>{if(typeof e==='string')e=document.querySelector(e); if(!e)return null; const cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden'||e.closest('[hidden]'))return null; const r=e.getBoundingClientRect(); return r.width&&r.height?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null;};
  const c=document.querySelector('#shot .vstcard'), cr=R(c), bs=c?[...c.querySelectorAll('.btn')].map(b=>{const r=b.getBoundingClientRect(); return {h:Math.round(r.height),top:Math.round(r.top),c:getComputedStyle(b).color};}):[];
  const top=['#shot .vmodes','#shot .vstyle','#shotx','#shot .vhist'].map(R).filter(Boolean), side=R('#vside'), cams=R('#shot .vcams');
  const tB=Math.max(...top.map(x=>x.b)), bT=Math.min(...[side&&side.t,cams&&cams.t].filter(x=>x!=null)); if(cams)top.push(cams);
  const d=document.createElement('i'); d.style.color='var(--ink)'; document.body.appendChild(d); const ink=getComputedStyle(d).color; d.remove();
  const bg=c?getComputedStyle(c).backgroundColor:'', a=+(bg.match(/rgba?\([^)]*,\s*([\d.]+)\)$/)||[0,1])[1];
  return {h:cr?Math.round(cr.b-cr.t):0, bs, row:bs.length===2&&bs[0].top===bs[1].top, over:!!cr&&top.some(r=>r.l<cr.r&&cr.l<r.r&&r.t<cr.b&&cr.t<r.b),
    mid:cr?Math.round((cr.t+cr.b)/2-(tB+bT)/2):null, ink, alpha:a};});
ok('4б плашка окна компактная (≤ 100 px'+(W>340?', кнопки в ряд':'')+'), полупрозрачная, не на кнопках и подписях ракурсов'+(W<=700?', по центру кадра':'')+', текст кнопок — цвет страницы',
  stg.h>0&&stg.h<=100&&(W<=340||stg.row)&&stg.bs.every(x=>x.h>=30&&x.h<=40)&&!stg.over&&stg.alpha<0.95&&(W>700||Math.abs(stg.mid)<=16)&&stg.bs.length===2&&stg.bs[1].c===stg.ink,
  JSON.stringify(stg));
await p.screenshot({path:OUT+`m77-${W}-stale.png`});
// 4в. «ВЕРНУТЬ КАК БЫЛО» ВОЗВРАЩАЕТ ВСЁ (T-20261108-71 А, владелец TG 563): состав, декор, пол, номер состояния; шкала окна («Выбрано»,
// «Эта комната», доплата), чип и список шторки; главная («Выбрано» и карточка); в 3D — та же картинка с точки 1
const s1e=await sums(p);
await p.click('#shot .vstale [data-st="back"]'); await p.waitForTimeout(1800);
const s1=await sums(p), dif=k=>JSON.stringify(s0[k])===JSON.stringify(s1[k])?'':k;
ok('4в «Вернуть как было» → «Фото» без затемнения; состав, декор, пол и номер — как до правки',s1.mode==='photo'&&!s1.stale&&s1.sid===s0.sid&&!dif('comp')&&!dif('decor')&&!dif('dev'),
  JSON.stringify({mode:s1.mode,stale:s1.stale,sid:[s0.sid,s1e.sid,s1.sid].map(x=>x.slice(3,11)),dev:[s0.dev,s1.dev]}));
const bad=['plate','chip','list','homeInc','homeCard'].map(dif).filter(Boolean);
ok('4в суммы — как до правки: шкала окна, чип, список шторки, «Выбрано» и карточка главной',!bad.length,bad.length?JSON.stringify(bad.map(k=>[k,s0[k],s1[k]])):s1.plate.slice(0,90));
const f1=await frame3d(p), pd=f0&&f1?diff3d(f0.px,f1.px):-1;
ok('4в в 3D — прежняя расстановка: модели и кадр с точки 1 (с полом) как до правки',!!f1&&JSON.stringify(f0.models)===JSON.stringify(f1.models)&&pd>=0&&pd<1,'разница кадра '+pd);
// ↶/↷ после возврата — как отмена: возврат = шаг назад по истории, ↷ снова даёт правку, ↶ от неё — опять возвращённая
const hs=await p.evaluate(()=>{const id0=curStateId(), f=histFwd(), id1=curStateId(), b=histBack(); return {f, b, id0, id1, back:curStateId()===id0};});
ok('4в ↷ после возврата — снова правка, ↶ — снова как было',hs.f&&hs.id1===s1e.sid&&hs.b&&hs.back,JSON.stringify({f:hs.f,b:hs.b,back:hs.back,edit:hs.id1===s1e.sid}));
await p.evaluate(()=>{histFwd();}); await p.waitForTimeout(1200);   // снова правка — дальше шаги как прежде
// 4г. КНОПКИ НА ПОМЕТКЕ КАРТОЧКИ ГЛАВНОЙ (T-20261108-71/2, владелец TG 582): правка → окно закрыто → на карточке «Вы изменили комнату» и
// две кнопки окна (подпись комнаты не закрыта); чипа «✓ Просмотрено» нет, хотя комнату открывали (владелец 08.11 TG 592,
// T-20261108-72); «Вернуть как было» с карточки — тот же возврат, что в окне:
// окно не открывается, пометки нет, сумма карточки и «Выбрано» — как до правки.
// КОМПАКТНО (T-20261108-77, владелец TG 616 «слишком крупно, как открывать комнату»): пометка внизу фото над подписью комнаты ≤ 60 px, кнопки в ряд и на 320 (вверху на первой
// карточке подсказка `.hm-tip`),
// кнопки в ряд 28–36 px; середина фото свободна (там — сама карточка, не кнопка); текст кнопок — цвет страницы, не системный синий Safari
const RM=await p.evaluate(()=>(allVariants()[cur]||{}).room||'living'), CARD=`#hmRooms article.hm-room[data-room="${RM}"]`;
const hcard=()=>p.evaluate(sel=>{try{drawHome();}catch(e){} const a=document.querySelector(sel); if(!a)return null; const m=a.querySelector('.hm-stale');
  if(m)a.scrollIntoView({block:'center'});
  const R=e=>{if(!e)return null; const r=e.getBoundingClientRect(); return {l:r.left,t:r.top,r:r.right,b:r.bottom};};
  const over=(x,y)=>!!x&&!!y&&x.l<y.r&&y.l<x.r&&x.t<y.b&&y.t<x.b;
  const ttl=a.querySelector('.ttl'), tr=ttl?document.createRange():null; if(tr)tr.selectNodeContents(ttl);
  const ink=(()=>{const d=document.createElement('i'); d.style.color='var(--ink)'; document.body.appendChild(d); const c=getComputedStyle(d).color; d.remove(); return c;})();
  const mr=R(m), btn=[...(m?m.querySelectorAll('[data-hst]'):[])].map(b=>{const r=b.getBoundingClientRect(); return {k:b.dataset.hst, t:b.textContent, h:Math.round(r.height), top:Math.round(r.top), c:getComputedStyle(b).color};});
  const ph=R(a.querySelector('.hm-ph')), mid=ph&&document.elementFromPoint((ph.l+ph.r)/2,(ph.t+ph.b)/2);
  return {stale:a.dataset.stale==='1', btn, sum:(a.querySelector('.rb .sum')||{}).textContent, inc:(document.getElementById('hmCert')||{dataset:{}}).dataset.included,
    win:document.getElementById('shot').classList.contains('on'), coverTtl:over(mr,tr?R(tr):null), chip:!!a.querySelector('.hm-seen')||/Просмотрено|Viewed/.test(a.textContent), seenSet:homeSeenSet().size,
    mh:mr?Math.round(mr.b-mr.t):0, mBot:mr&&ph?Math.round(ph.b-mr.b):null, midFree:!!mid&&!!mid.closest(sel)&&!mid.closest('[data-hst]'), row:btn.length===2&&btn[0].top===btn[1].top, ink};},CARD);
await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(1500);
const hc1=await hcard();
ok('4г правка → внизу фото карточки над подписью пометка ≤ 60 px и кнопки «Сделать реалистичнее» и «Вернуть как было» 28–36 px в ряд'+
  ', середина фото свободна, подпись не закрыта, цвет текста кнопок — свой, чипа «Просмотрено» нет',
  !!hc1&&hc1.stale&&hc1.btn.length===2&&hc1.btn[0].k==='real'&&/Сделать реалистичнее/.test(hc1.btn[0].t)&&hc1.btn[1].k==='back'&&hc1.btn.every(x=>x.h>=28&&x.h<=36)&&
  hc1.row&&hc1.mh<=60&&hc1.mBot!=null&&hc1.mBot>=24&&hc1.mBot<=60&&hc1.midFree&&hc1.btn[1].c===hc1.ink&&!hc1.coverTtl&&!hc1.chip,
  JSON.stringify(hc1));
await p.locator(CARD).scrollIntoViewIfNeeded().catch(()=>{}); await p.screenshot({path:OUT+`m71-${W}-card.png`});
await p.click(CARD+' [data-hst="back"]'); await p.waitForTimeout(1500);
const hc2=await hcard(), sid2=await p.evaluate(()=>curStateId());
ok('4г «Вернуть как было» с карточки → окно не открылось, пометки нет, сумма карточки и «Выбрано» как до правки, номер прежний',
  !!hc2&&!hc2.win&&!hc2.stale&&!hc2.btn.length&&hc2.sum===s0.homeCard&&hc2.inc===s0.homeInc&&sid2===s0.sid,
  JSON.stringify({win:hc2&&hc2.win,stale:hc2&&hc2.stale,sum:[s0.homeCard,hc2&&hc2.sum],inc:[s0.homeInc,hc2&&hc2.inc],sid:sid2===s0.sid}));
await p.screenshot({path:OUT+`m71-${W}-card-back.png`});
// окно снова (кнопка «›» карточки) — возврат был шагом истории, как в окне: ↷ даёт правку
await p.click(CARD+' [data-swap]'); await p.waitForFunction(()=>document.getElementById('shot').classList.contains('on'),null,{timeout:20000}).catch(()=>{}); await p.waitForTimeout(1500);
const fw=await p.evaluate(()=>{const f=histFwd(); return {f, sid:curStateId()};}); await p.waitForTimeout(1200);
ok('4г после возврата с карточки ↷ в окне — снова правка',fw.f&&fw.sid===s1e.sid,JSON.stringify({f:fw.f,edit:fw.sid===s1e.sid}));
await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(600);
await p.evaluate(()=>histBack()); await p.waitForTimeout(1200); s=await st(p);
ok('4 ↶ вернул расстановку со снимком → «Фото» снова доступно (в 3D)',s.mode==='walk'&&s.photoTab,JSON.stringify({mode:s.mode,tab:s.photoTab}));
// 4д. «СДЕЛАТЬ РЕАЛИСТИЧНЕЕ» С КАРТОЧКИ — ТО ЖЕ ЗАДАНИЕ, ЧТО ИЗ ОКНА (T-20261108-71/2): окно этой комнаты открывается на «Фото» с ходом
// работы, задание — правленой расстановки, заказ того же вида, что по кнопке окна (шаг 2); платное подменено
await p.evaluate(()=>histFwd()); await p.waitForTimeout(1200);
await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(1500);
// окно уже открывали с карточки (4г, «›») — признак «открывали» записан, а чипа «✓ Просмотрено» нет (владелец 08.11 TG 592, T-20261108-72)
const hc3=await hcard();
ok('4д комнату открывали с карточки — признак для подсказок есть, чипа «Просмотрено» на карточке нет',!!hc3&&hc3.seenSet>0&&!hc3.chip,JSON.stringify(hc3&&{seen:hc3.seenSet,chip:hc3.chip}));
const nb=p.renderBodies.length; await p.evaluate(()=>{window.__fakeReady=0;});
await p.click(CARD+' [data-hst="real"]'); await p.waitForTimeout(1500); s=await st(p);
const jw=await p.evaluate(()=>({on:document.getElementById('shot').classList.contains('on'), job:VJ.job?{vid:VJ.job.vid,sid:VJ.job.stateId}:null, vid:curVid(),
  wait:(()=>{const o=document.querySelector('#shot .vphwait'); return o?o.querySelector('b').textContent:'';})()}));
ok('4д «Сделать реалистичнее» с карточки → окно комнаты на «Фото» с ходом работы, задание — этой правки',
  jw.on&&s.mode==='photo'&&/^(Улучшаю…|Enhancing…) \d+ %$/.test(jw.wait)&&!!jw.job&&jw.job.vid===jw.vid&&jw.job.sid===s1e.sid,JSON.stringify({...jw,mode:s.mode}));
// 4д. ВО ВРЕМЯ УЛУЧШЕНИЯ НА «ФОТО» — ПРЕЖНЕЕ ФОТО (T-20261108-74, владелец 08.11 TG 604): у правки есть прежнее фото → оно затемнено,
// поверх «Улучшаю… N %», плашки «Вы изменили комнату» нет; карточка не под верхними кнопками, на телефоне — по центру кадра между ними и шторкой
const ow=await p.evaluate(()=>{const R=e=>{if(typeof e==='string')e=document.querySelector(e); if(!e)return null; const cs=getComputedStyle(e);
    if(cs.display==='none'||cs.visibility==='hidden'||e.closest('[hidden]'))return null; const r=e.getBoundingClientRect(); return r.width&&r.height?{l:r.left,t:r.top,r:r.right,b:r.bottom}:null;};
  const w=document.querySelector('#shot .vphwait'), c=R(w&&w.querySelector('.vphcard')), img=document.querySelector('#shot .shotwrap img.vmain');
  const top=['#shot .vmodes','#shot .vstyle','#shotx','#shot .vhist'].map(R).filter(Boolean), side=R('#vside'), cams=R('#shot .vcams');
  const tB=Math.max(...top.map(x=>x.b)), bT=Math.min(...[side&&side.t,cams&&cams.t].filter(x=>x!=null));
  return {old:!!w&&w.classList.contains('vprev'), bg:!!w&&!!w.dataset.bg, plate:!!R('#shot .vstale'), stale:vwStalePick().list.length, real:vwRealShots().length,
    img:!!R(img), over:!!c&&top.some(r=>r.l<c.r&&c.l<r.r&&r.t<c.b&&c.t<r.b), mid:c?Math.round((c.t+c.b)/2-(tB+bT)/2):null};});
ok('4д во время улучшения на «Фото» — прежнее фото затемнено, поверх «Улучшаю…», плашки «Вы изменили комнату» нет, карточка не под кнопками'+(W<=700?' и по центру кадра':''),
  ow.old&&!ow.bg&&!ow.plate&&ow.stale>0&&!ow.real&&ow.img&&!ow.over&&(W>700||Math.abs(ow.mid)<=16),JSON.stringify(ow));
await p.screenshot({path:OUT+`m74-${W}-job-old.png`});
for(let t=0;t<40&&!p.renderBodies.slice(nb).some(x=>x.quality==='realistic');t++)await p.waitForTimeout(500);
const rc=p.renderBodies.slice(nb).filter(x=>x.quality==='realistic').pop()||{}, keys=o=>Object.keys(o).sort().join(',');
ok('4д заказ тот же, что по кнопке окна: те же поля, оба вида, тот же лист (платное подменено)',keys(rc)===keys(rb)&&(rc.views||[]).length===2&&rc.sheet===rb.sheet,
  JSON.stringify({card:keys(rc),win:keys(rb),sheet:[rc.sheet,rb.sheet]}));
await p.evaluate(()=>{window.__fakeReady=1;}); await p.waitForFunction(()=>!VJ.job,null,{timeout:20000}).catch(()=>{}); await p.waitForTimeout(600);
const nw=await p.evaluate(()=>({mode:VW.mode, wait:!!document.querySelector('#shot .vphwait'), plate:!!document.querySelector('#shot .vstale'), real:vwRealShots().length,
  img:(()=>{const i=document.querySelector('#shot .shotwrap img.vmain'); return !!i&&getComputedStyle(i).display!=='none'&&i.getBoundingClientRect().height>0;})()}));
ok('4д по готовности — на «Фото» новое фото этой правки, без затемнения и хода',nw.mode==='photo'&&!nw.wait&&!nw.plate&&nw.real>0&&nw.img,JSON.stringify(nw));
await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(600);
// 3. ПРАВКА ВО ВРЕМЯ «УЛУЧШАЮ…» НЕ ПРИМЕНЯЕТСЯ (demo-20 Г5, владелец 22.10 TG 867): ушёл в 3D, пробует сменить пол — подсказка, расстановка
// та же; по готовности окно остаётся в 3D, вкладка «Фото» есть и «Фото готово · Смотреть». Прежний сценарий «поменял во время съёмки →
// „фото готово для прежней“» стал невозможен по замыслу
await p.evaluate(()=>{window.__fakeReady=0; const g=devGroups().find(x=>x.kind==='flooring'); devSet(g.id,g.variants[2].id);}); await p.waitForTimeout(900);
await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(800);   // после изменения шторка свёрнута — кнопку сперва видно, как у человека
await p.evaluate(()=>{window.__cap0=VW.lastCapture;});
await p.click('#vCta'); await p.waitForTimeout(1200);
await p.waitForFunction(()=>VW.lastCapture!==window.__cap0,null,{timeout:20000}).catch(()=>{});
const lk=await p.evaluate(()=>{vwMode('walk'); const s0=curStateId(), g=devGroups().find(x=>x.kind==='flooring'); devSet(g.id,g.variants[3].id);
  const t=document.getElementById('toast'); return {same:curStateId()===s0, hint:t&&!t.hidden?t.textContent:''};});
ok('3 правка во время «Улучшаю…» не применяется, подсказка',lk.same&&/Менять можно, когда улучшение закончится|You can change things once the enhancement is finished/.test(lk.hint),JSON.stringify(lk));
await p.evaluate(()=>{window.__fakeReady=1;});
await p.waitForFunction(()=>!VJ.job,null,{timeout:20000}).catch(()=>{}); await p.waitForTimeout(500); s=await st(p);
const rd=await p.evaluate(()=>{const t=document.getElementById('toast'); return t&&!t.hidden?t.textContent:'';});
ok('3 готово, человек в 3D → вкладка «Фото» есть, «Фото готово · Смотреть»',s.mode==='walk'&&s.photoTab&&/Фото готово.*Смотреть|Photo ready.*View/.test(rd),JSON.stringify({mode:s.mode,tab:s.photoTab,toast:rd}));
const geo=await p.evaluate(()=>{const R=s=>{const e=document.querySelector(s); if(!e)return null; const r=e.getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)];};
  const sc=[...document.querySelectorAll('#shot, #shot *')].filter(e=>e.scrollTop>0).map(e=>(e.id||e.className||e.tagName)+':'+e.scrollTop);
  const m=document.querySelector('#shot .vmodes'), mr=m&&m.getBoundingClientRect(), hit=mr&&document.elementFromPoint(mr.left+mr.width/2,mr.top+mr.height/2);
  return {vmodes:R('#shot .vmodes'), canvas:R('#shot canvas'), box:R('#shot .box'), ready:R('#shot .vready'), scrolled:sc, win:scrollY, top:!!hit&&m.contains(hit)};});
// место — относительно сцены, не экрана: на телефоне окно во весь экран (сцена с 0), на компьютере — карточка 92vh по центру (demo-02,
// ADR-0290), её верх = 4vh (36 px на 900), переключатель — 12 px внутри. Прежнее «верх < 40 px от экрана» (demo-09, писалось под 375)
// на компьютере не выполнялось никогда
const dy=geo.vmodes&&geo.canvas?geo.vmodes[1]-geo.canvas[1]:-1;
ok('3 переключатель режимов на месте (у верха сцены, внутри неё, сверху ничего), сцена не уехала',
  !!geo.vmodes&&dy>=0&&dy<40&&geo.vmodes[0]>=geo.canvas[0]&&geo.vmodes[0]+geo.vmodes[2]<=geo.canvas[0]+geo.canvas[2]&&geo.top
  &&!!geo.box&&geo.canvas[1]===geo.box[1]&&!geo.win&&!geo.scrolled.filter(x=>!/vscroll/.test(x)).length,JSON.stringify({dy,...geo}));
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
// 7. «ФОТО» ВИТРИННОГО ВАРИАНТА (T-20261108-75): вверху «Сменить стиль» (телефон) / строка «Другой стиль для комнаты» в панели (компьютер),
// «Скрыть цены» нет; в 3D — наоборот. Отдельная страница: после «Сделать реалистичнее» (шаги 2–4) расстановка своя, смены стиля у неё нет
p=await page(b,'?live=force&lang=ru','ru'); await p.evaluate(()=>openLiveWindow()); await p.waitForTimeout(2500);
const top7=()=>p.evaluate(()=>{const v=id=>{const e=document.getElementById(id); return e&&e.offsetParent?e.innerText.trim():null;}; return {mode:VW.mode, price:v('vPriceTop'), style:v('vOtherTop'), row:v('vOther')};});
let t7=await top7();
ok('7 «Фото» — «Сменить стиль», «Скрыть цены» нет',t7.mode==='photo'&&!t7.price&&(W<=700?t7.style==='Сменить стиль':/Другой стиль/.test(t7.row||'')),JSON.stringify(t7));
await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(1500); t7=await top7();
ok('7 3D — «Скрыть цены» вместо «Сменить стиль»',t7.mode==='walk'&&t7.price==='Скрыть цены'&&!t7.style,JSON.stringify(t7));
console.log('errs',p.errs.slice(0,3)); await p.context().close();
}catch(e){R.push('FAIL проверка прервалась — '+String(e.message||e).split('\n').slice(0,6).join(' | '));}
finally{console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length}`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0; await b.close().catch(()=>{});}
})().catch(e=>{console.error(e);process.exit(1);});
