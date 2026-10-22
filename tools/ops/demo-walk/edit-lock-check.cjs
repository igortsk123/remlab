const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ЗАМОК ПРАВОК НА ВРЕМЯ «УЛУЧШАЮ…» И «ФОТО ГОТОВО» (demo-20 Г5, T-20261022-07/2): пока рисуется фото этой расстановки, замена, ↶,
// отделка и «Изменить план» не применяются — подсказка; по готовности (ушёл в 3D) — сообщение «Фото готово · Смотреть» → вкладка «Фото»;
// карточка главной у правленого варианта — кадр 3D его расстановки (`liveShot`), а не фото опубликованной. Платный путь подменён:
// задание «идёт», пока проба не скажет «готово», и отдаёт уже опубликованный кадр. Заодно: ссылок на /flat нет (demo-20 Г6).
//   BASE=https://remont-lab.online/demo/ OUT=<папка/> node tools/ops/demo-walk/edit-lock-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i===undefined?'':typeof i==='string'?i:JSON.stringify(i)));
const LOCK=/Менять можно, когда улучшение закончится/;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  let done=null;   // ответ задания по готовности: {status:'done', shots:[…]}
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render\/frame/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'f'+Date.now()+Math.random().toString(36).slice(2,8)})}));
  await p.route(/\/api\/render(\?|$)/,r=>r.request().method()==='POST'?r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}):r.continue());
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(done||{status:'running',eta:60})}));
  await p.goto(BASE+'?lang=ru&live=force',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  await p.waitForTimeout(1500);
  const toastTxt=()=>p.evaluate(()=>{const t=document.getElementById('toast'); return t&&!t.hidden?t.textContent:'';});
  // 0. окно варианта, 3D; без правок кадр карточки не снимается
  await p.evaluate(()=>{openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');});
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:300000}).catch(()=>{}); await p.waitForTimeout(2500);
  ok('0 живая сцена готова',await p.evaluate(()=>LIVE.state==='ready'),await p.evaluate(()=>({state:LIVE.state,ok:LIVE.ok,why:LIVE.why||''})));
  ok('0 без правок кадр карточки не снят',await p.evaluate(()=>LIVE_SHOTS.size===0));
  // ссылок «Вся квартира в 3D» / «Посмотреть в 3D» нет (demo-20 Г6): ни в окне 3D, ни на странице под ним
  const fl0=await p.evaluate(()=>[...document.querySelectorAll('a[href*="/flat"]')].map(a=>a.id||a.className||a.textContent.trim()).slice(0,5));
  ok('0 окно 3D — ссылок на /flat нет',!fl0.length,fl0);
  const s0=await p.evaluate(()=>curStateId());
  // 1. «Сделать реалистичнее» → «Фото» с ходом работы
  await p.click('#vCta'); await p.waitForFunction(()=>!!VJ.job,null,{timeout:20000});
  await p.waitForFunction(()=>VW.mode==='photo',null,{timeout:30000}).catch(()=>{});
  ok('1 задание идёт, окно на «Фото» с «Улучшаю…»',await p.evaluate(()=>!!VJ.job&&VW.mode==='photo'&&!!document.querySelector('#shot .vphwait')));
  await p.waitForTimeout(800); await p.screenshot({path:OUT+`lock-${W}-1-enhancing.png`});
  // 2. ушёл в 3D — правки не применяются, подсказка
  await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(1500);
  const rep=p.locator('#vside .row button',{hasText:'Заменить'}).first();
  if(PHONE)await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(600);
  await (PHONE?rep.tap({timeout:10000}):rep.click({timeout:10000})).catch(e=>ok('2 «Заменить» нажимается',false,String(e).slice(0,120)));
  await p.waitForTimeout(300);
  ok('2 «Заменить» — лист не открылся',await p.evaluate(()=>!document.getElementById('sheet').classList.contains('open')));
  const t2=await toastTxt(); ok('2 подсказка «Менять можно, когда улучшение закончится»',LOCK.test(t2),t2);
  await p.screenshot({path:OUT+`lock-${W}-2-hint.png`});
  const r3=await p.evaluate(()=>{const before=JSON.stringify(DEVOPT); const g=devGroups().find(x=>x.kind==='flooring'); const o=g&&(g.variants||[]).find(x=>x.id!==(DEVOPT[g.id]||g.defaultVariantId));
    if(g&&o)devSet(g.id,o.id); return {tried:!!(g&&o), same:JSON.stringify(DEVOPT)===before};});
  ok('3 отделка не меняется',r3.same,r3);
  ok('3 ↶ не срабатывает',await p.evaluate(()=>histGo(-1)===false));
  ok('3 лист замены из кода не открывается',await p.evaluate(()=>{openPicker(items[0]); return !document.getElementById('sheet').classList.contains('open');}));
  await p.evaluate(()=>vwMode('plan')); await p.waitForTimeout(800);
  await p.click('#vCta'); await p.waitForTimeout(500);
  ok('3 «Изменить план» — редактор не открылся',await p.evaluate(()=>!document.getElementById('cons').classList.contains('on')));
  ok('3 расстановка та же',await p.evaluate(s=>curStateId()===s,s0));
  // 4. готово, человек в 3D — «Фото готово · Смотреть» → «Фото»
  await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(800);
  const url=await p.evaluate(()=>{const s=pubShot(allVariants()[cur])||shots.find(x=>x.url&&x.quality==='realistic'); return s?s.url:'';});
  done={status:'done',shots:[{url,camera:'C1'},{url,camera:'C2'}],model:'probe'};
  await p.waitForFunction(()=>!VJ.job,null,{timeout:30000}).catch(()=>{});
  await p.waitForTimeout(400);
  const t4=await toastTxt(); ok('4 «Фото готово» с «Смотреть»',/Фото готово/.test(t4)&&/Смотреть/.test(t4),t4);
  ok('4 окно осталось в 3D',await p.evaluate(()=>VW.mode==='walk'));
  const t0=Date.now(); await p.screenshot({path:OUT+`lock-${W}-4-ready.png`}); const shotMs=Date.now()-t0;
  // кнопка сверху (не перекрыта) — и настоящий щелчок по ней; ожидание «устойчивости» не нужно: под программной графикой на 1440
  // живая сцена почти останавливает перерисовку, и Playwright не дожидается двух кадров
  const top=await p.evaluate(()=>{const b=document.querySelector('#toast .toastact'); if(!b)return 'нет кнопки'; const r=b.getBoundingClientRect();
    const e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2); return e===b?'':'сверху '+(e?(e.id||e.className||e.tagName):'—');});
  ok('4 «Смотреть» не перекрыта',!top,top);
  const ce=await p.click('#toast .toastact',{timeout:3000,force:true}).then(()=>'',e=>String(e).slice(0,400)); await p.waitForTimeout(800);
  ok('4 «Смотреть» → «Фото»',await p.evaluate(()=>VW.mode==='photo'),
    {click:ce, shotMs, ...await p.evaluate(()=>({mode:VW.mode, real:vwRealShots().length, st:curStateId(), toast:!document.getElementById('toast').hidden}))});
  // 5. замок снят: отделка меняется; в 3D снимается кадр карточки; на главной — он, а не опубликованное фото
  await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(800);
  const r5=await p.evaluate(()=>{const g=devGroups().find(x=>x.kind==='flooring'); const o=g&&(g.variants||[]).find(x=>x.id!==(DEVOPT[g.id]||g.defaultVariantId));
    const before=curStateId(); if(g&&o)devSet(g.id,o.id); return {changed:curStateId()!==before};});
  ok('5 после готовности правка применяется',r5.changed,r5);
  await p.waitForFunction(()=>LIVE_SHOTS.size>0,null,{timeout:40000}).catch(()=>{});
  ok('5 снят кадр 3D правленой расстановки',await p.evaluate(()=>!!liveShot(allVariants()[cur])));
  await p.evaluate(()=>{const c=document.getElementById('shotx'); if(c)c.click();}); await p.waitForTimeout(1200);
  const card=await p.evaluate(()=>{const i=document.querySelector('#hmRooms .hm-room img'); return i?i.getAttribute('src'):'';});
  ok('5 карточка главной — кадр 3D (blob:)',/^blob:/.test(card),card.slice(0,60));
  const fl5=await p.evaluate(()=>[...document.querySelectorAll('a[href*="/flat"]')].map(a=>a.id||a.className||a.textContent.trim()).slice(0,5));
  ok('5 главная — ссылок на /flat нет',!fl5.length,fl5);
  await p.evaluate(()=>{const c=document.querySelector('#hmRooms .hm-room'); if(c)c.scrollIntoView({block:'center'});}); await p.waitForTimeout(600);
  await p.screenshot({path:OUT+`lock-${W}-5-home-card.png`});
  ok('ошибок страницы нет',!errs.length,errs.slice(0,3));
  console.log(R.join('\n')); console.log(`edit-lock-check ${W}x${H}: ${R.filter(x=>x.startsWith('FAIL')).length} FAIL из ${R.length}`);
  await b.close();
})().catch(e=>{console.log(R.join('\n')); console.log('CRASH',e); process.exit(1);});
