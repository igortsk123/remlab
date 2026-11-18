const {demoUrl}=require('../demo-url.cjs');
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// T-20261118-20/5: «Сделать фото» на /demo ЦЕЛИКОМ и с НАСТОЯЩИМИ кадрами, БЕЗ платного: заказы идут на сервис кадров за стендом (`stage-proxy.mjs` с `LOCAL_API`).
//   PART=A — стенд смотрит на ЖИВОЙ 8600 (`LOCAL_API=http://127.0.0.1:8600`): неизменённая комната — кадры из заготовки сразу (кэш), «Фото» с настоящими кадрами,
//            кнопка «Улучшить фото» — снимок ДО нажатия (нейросеть не зовём: `/api/render` блокируется и считается).
//   PART=B — стенд смотрит на локальный сервис-заглушку (`draft_local.py`, повтор готовых кадров с настоящими паузами): после смены товара — «Вы изменили комнату» →
//            «Сделать фото» → «Делаю фото · N %» → «Фото» → «Улучшить фото» (кадры — повтор чужой комнаты, проверяется ход, не картинка).
//   BASE=http://127.0.0.1:<порт>/demo/ OUT=<папка/> PART=A|B node tools/ops/demo-walk/photo-flow-real.cjs 375x667
const BASE=process.env.BASE||'http://127.0.0.1:8792/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/', PART=process.env.PART||'A';
const ALT=+(process.env.ALT||1);   // какой по счёту другой диван взять (у сервиса-заглушки готовые кадры по ключу — повторный заказ той же замены вернётся мгновенно)
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
fs.mkdirSync(OUT,{recursive:true});
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i===undefined?'':typeof i==='string'?i:JSON.stringify(i)));
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:PHONE?2:1,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  ctx.setDefaultTimeout(180000);
  const p=await ctx.newPage(); const errs=[], net=[], paid=[];
  p.on('pageerror',e=>errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  // платное — только счёт: «Улучшить фото» (нейросеть) не вызываем
  await p.route(/\/api\/render(\?|$)/,r=>{if(r.request().method()==='POST'){paid.push(r.request().url()); return r.abort();} return r.continue();});
  // PART=A на ЖИВОМ сервисе: заказ уходит только если «проверка» (check, без постановки) говорит «кадры уже есть»; иначе — отказ у стенда, живой сервис ничего не считает
  if(PART==='A')await p.route(/\/api\/render\/cycles(\?|$)/,async r=>{if(r.request().method()!=='POST')return r.continue();
    let j={}; try{const body=JSON.parse(r.request().postData()||'{}'); const c=await r.fetch({postData:JSON.stringify(Object.assign({},body,{check:true}))}); j=await c.json();}catch(e){}
    if(j&&j.cached===true)return r.continue();
    net.push({t:'blocked',cached:j&&j.cached,key:((j&&j.key)||'').slice(0,12)}); return r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({ok:false,code:'stand_not_cached'})});});
  p.on('response',async r=>{const u=r.url(); if(/\/api\/render\/cycles(\?|$)/.test(u)&&r.request().method()==='POST'){let j={};try{j=await r.json();}catch(e){} net.push({t:'order',s:r.status(),status:j.status,cached:j.cached,key:(j.key||'').slice(0,12),code:j.code||null});}
    else if(/\/api\/render\/cycles\/frame\//.test(u))net.push({t:'frame',s:r.status(),u:u.slice(-40)});});
  const shot=async n=>{await p.screenshot({path:OUT+`${PART}-${W}-${n}.png`,timeout:180000});};
  await p.goto(demoUrl(BASE+'?lang=ru&live=force'),{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  await p.waitForTimeout(1500);
  await p.evaluate(()=>{openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');});
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>{}); await p.waitForTimeout(2500);
  ok('0 живая сцена готова',await p.evaluate(()=>LIVE.state==='ready'));
  // у варианта с готовым фото этой расстановки кнопки «Сделать фото» нет (так задумано, T-20/2) — берём первый вариант гостиной, где она есть (без фото ⇒ заказ найдёт кадры заготовки)
  const pickV=await p.evaluate(async()=>{const vs=allVariants(); const rec=[];
    for(let i=0;i<vs.length&&i<24;i++){
      vwOpenVariant(i); await new Promise(r=>setTimeout(r,3500)); if(VW.mode!=='walk')vwMode('walk'); await new Promise(r=>setTimeout(r,1200));
      const k=vwCtaKind(); rec.push([vs[i].id,k]); if(k==='make')return {i,id:vs[i].id,rec};}
    return {i:-1,rec};});
  ok('0 у каких вариантов в 3D есть кнопка «Сделать фото» (у неизменённых с готовым фото — нет)',true,pickV.rec.filter(r=>r[1]).length+' из '+pickV.rec.length);
  if(pickV.i<0)await p.evaluate(()=>{vwOpenVariant(0);});
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>{}); await p.waitForTimeout(2500);
  await shot('1-3d-before-press');
  const cta=()=>p.evaluate(()=>{const c=document.getElementById('vCta'); return c?{t:(c.textContent||'').trim(),a:c.getAttribute('aria-label')||'',vis:!!(c.offsetParent&&c.getBoundingClientRect().height>0)}:null;});
  // у неизменённой комнаты /demo уже есть готовое фото — кнопки «Сделать фото» нет (так задумано); съёмку запускаем ТОЙ ЖЕ функцией, что кнопка (`vwRealistic`), —
  // чтобы показать путь «заказ → кадры заготовки сразу»
  const c1=await cta(); ok('1 у неизменённой комнаты с готовым фото кнопки «Сделать фото» нет (по задумке)',!(c1&&c1.vis),c1);
  if(c1&&c1.vis){await p.click('#vCta'); await p.waitForTimeout(1500); if(!(await p.evaluate(()=>!!VJ.job||VW.mode==='photo')))await p.click('#vCta');}
  else await p.evaluate(()=>{vwRealistic({});});
  await p.waitForFunction(()=>VW.mode==='photo',null,{timeout:120000});
  await p.waitForTimeout(400); await shot('2-after-press');
  // готово: настоящие кадры на экране (картинки загрузились)
  await p.waitForFunction(()=>!VJ.job&&[...document.querySelectorAll('#shot .shotwrap img')].some(i=>i.complete&&i.naturalWidth>300),null,{timeout:240000}).catch(()=>{});
  await p.waitForTimeout(1200);
  const ph=await p.evaluate(()=>({mode:VW.mode,job:!!VJ.job,imgs:[...document.querySelectorAll('#shot .shotwrap img')].map(i=>({w:i.naturalWidth,h:i.naturalHeight,src:(i.currentSrc||i.src).slice(-45)})).slice(0,3),err:VJ.err||null}));
  ok('3 «Фото» с настоящим кадром (картинка > 300 px, не битая)',ph.mode==='photo'&&!ph.job&&ph.imgs.some(i=>i.w>300),ph);
  await shot('3-photo-real-frame-1');
  ok('3 заказ принят, кадры отданы',net.some(n=>n.t==='order'&&n.s===200)&&net.some(n=>n.t==='frame'&&n.s===200),net.slice(0,5));
  if(PART==='A')ok('3 неизменённая комната — из заготовки сразу (cached)',net.some(n=>n.t==='order'&&n.cached===true),net.filter(n=>n.t==='order'));
  const c2=await p.evaluate(()=>{const t=[...document.querySelectorAll('#vCams [data-cam]')]; if(t[1]){t[1].click(); return true;} return false;});
  if(c2){await p.waitForTimeout(1500); await shot('4-photo-real-frame-2');}
  const c4=await cta(); ok('4 внизу «Улучшить фото» (до нажатия)',c4&&c4.vis&&/Улучшить/.test(c4.t+c4.a),c4);
  await shot('5-improve-button-before-press');
  if(PART==='B'){
    // смена товара → «Вы изменили комнату» → «Сделать фото» → ход в % → готово
    await p.evaluate(()=>{vwMode('walk');}); await p.waitForTimeout(1200);
    const sw=await p.evaluate(ALT=>{const k=items.findIndex(i=>i.role==='диван'&&i.sku); if(k<0)return null;
      const cur=(items[k].sku||{}).sid, alts=[...new Map(allVariants().flatMap(v=>v.items||[]).filter(o=>o.role==='диван'&&o.sku&&o.sku.sid&&o.sku.sid!==cur).map(o=>[o.sku.sid,o])).values()], alt=alts[(ALT-1)%Math.max(1,alts.length)];
      if(!alt)return null; items[k].sku=JSON.parse(JSON.stringify(alt.sku)); draw(); histPush(); return {from:cur,to:alt.sku.sid};},ALT);
    ok('6 товар заменён (диван)',!!sw,sw); await p.waitForTimeout(2000);
    await p.evaluate(()=>{vwMode('photo');}); await p.waitForTimeout(1500);
    const st=await p.evaluate(()=>{const e=document.querySelector('#shot .vstale'); return e?e.innerText.replace(/\n/g,' | '):null;});
    ok('6 «Вы изменили комнату» + кнопка «Сделать фото»',!!st&&/Вы изменили комнату/.test(st)&&/Сделать фото/.test(st),st);
    await shot('6-changed-overlay');
    await p.click('#shot .vstale [data-st="show"]'); await p.waitForTimeout(2500);
    const pr=await p.evaluate(()=>{const w=document.querySelector('.vphwait'); return {job:!!VJ.job,text:w?w.innerText.replace(/\n/g,' | '):null};});
    ok('7 ход «Делаю фото · N %»',pr.job&&/Делаю фото · \d+ %/.test(pr.text||''),pr);
    await shot('7-progress');
    await p.waitForFunction(()=>!VJ.job,null,{timeout:240000}).catch(()=>{}); await p.waitForTimeout(1500);
    const c8=await cta(); ok('8 готово → «Улучшить фото»',c8&&c8.vis&&/Улучшить/.test(c8.t+c8.a),c8);
    await shot('8-done-improve-button');
  }
  ok('нейросеть не вызывалась (платных заказов 0)',paid.length===0,paid);
  ok('ошибок страницы нет',!errs.length,errs.slice(0,3));
  console.log(R.join('\n')); console.log('итог:',R.filter(x=>x.startsWith('OK')).length+'/'+R.length);
  await b.close();})().catch(e=>{console.log(R.join('\n')); console.log('проверка прервалась —',String(e).slice(0,300)); process.exit(1);});
