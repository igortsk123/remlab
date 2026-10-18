const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ОКНО ВАРИАНТА, ИЗБРАННОЕ И «ПОДЕЛИТЬСЯ» (план demo-15): тап по предмету → шторка до верха и строка в верхней трети; после замены
// камера наведена на новый предмет; ракурсы подписями (ни стрелок, ни точек); сердечко и «поделиться» в шапке окна; окошко имени
// «<Стиль> #N»; раздел «Избранное» на главной; EN без кириллицы в новых подписях. Платный путь подменён; сохранение в избранное —
// настоящее (`POST /api/collections`).
//   BASE=https://remont-lab.online/test/share/demo-stage/ node tools/ops/demo-walk/fav-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/fav-';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
async function page(b,lang){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:lang==='en'?'en-GB':'ru-RU'});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://remont-lab.online'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:30})}));
  await p.goto(BASE+(lang==='en'?'?lang=en&':'?')+'live=force&v='+Date.now(),{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&allVariants().length>0",null,{timeout:90000});
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos');Object.keys(localStorage).filter(k=>/^remlab-(basket|favorites|collections|fav-thumbs)/.test(k)).forEach(k=>localStorage.removeItem(k));}catch(e){}});
  return p;
}
const openWin=async(p,i)=>{await p.evaluate(i=>{pickVariant(i); VW.collapse=true; vwOpenVariant(i); if(VW.mode!=='walk')vwMode('walk');},i);
  await p.waitForFunction("LIVE.scene&&LIVE.state==='ready'",null,{timeout:180000}); await p.waitForTimeout(1500);};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const p=await page(b,'ru');
    await openWin(p,0);
    await p.screenshot({path:OUT+W+'-1-3d.png'});
    const st0=await p.evaluate(()=>({pos:document.getElementById('vside').dataset.pos, fav:!document.getElementById('vFav').hidden, share:!document.getElementById('vShare').hidden,
      old:document.querySelectorAll('#vPrev,#vNext,#vDots,#shotPrev,#shotNext,.vdots,.vnav,#shPick,#shSave,#shLink,#feedShare,#collSave').length,
      cams:[...document.querySelectorAll('#vCams [data-cam]')].map(x=>x.textContent), camsOn:(()=>{const e=document.getElementById('vCams'); return !!e&&getComputedStyle(e).display!=='none';})()}));
    if(PHONE)ok('3D открыто со свёрнутой шторкой (скрин 1)',st0.pos==='0','pos='+st0.pos);
    ok('сердечко и «поделиться» в шапке окна видны',st0.fav&&st0.share);
    ok('старых стрелок, точек, «В избранное», «Сохранить коллекцию», «Ссылка», «Избранное» нет',st0.old===0,st0.old);
    // сцена во всю область окна: полос над и под холстом нет (≤ 8 px; fable-lead 18.10, цикл 1)
    const band=await p.evaluate(()=>{const w=document.querySelector('#shot .shotwrap').getBoundingClientRect(), c=LIVE.canvas.getBoundingClientRect();
      return {top:Math.round(c.top-w.top), bottom:Math.round(w.bottom-c.bottom)};});
    ok('сцена во всю высоту области, без полос',Math.abs(band.top)<=8&&Math.abs(band.bottom)<=8,JSON.stringify(band));
    ok('ракурсы — подписями, переключатель виден',st0.camsOn&&st0.cams.length===2&&!st0.cams.some(t=>/‹|›/.test(t)),st0.cams.join(' | '));
    // тап по предмету (ценник дивана) → шторка до верха, строка в верхней трети, подсвечена
    const k=await p.evaluate(()=>items.findIndex(i=>String(i.role)==='диван'));
    await p.evaluate(k=>vwHighlight(k),k); await p.waitForTimeout(900);
    const st1=await p.evaluate(k=>{const r=vwRowOf(items[k]), sc=document.getElementById('vscroll'); const rr=r&&r.getBoundingClientRect(), sr=sc.getBoundingClientRect();
      return {pos:document.getElementById('vside').dataset.pos, hl:!!r&&r.classList.contains('hl'), sel:VW.sel, rel:rr?(rr.top-sr.top)/sr.height:null};},k);
    if(PHONE)ok('тап по предмету → шторка до верха',st1.pos==='3','pos='+st1.pos);
    ok('строка предмета подсвечена, пока выделен',st1.hl&&st1.sel===k);
    if(PHONE)ok('строка предмета — в верхней трети списка',st1.rel!=null&&st1.rel>=0&&st1.rel<0.34,st1.rel&&st1.rel.toFixed(2));
    // компьютер: кнопка «Сделать реалистичнее» целиком видна под плашкой и после прокрутки к строке (fable-lead 18.10, цикл 1)
    const ctaOk=()=>p.evaluate(()=>{const c=document.getElementById('vCta').getBoundingClientRect(), s=document.getElementById('vscroll').getBoundingClientRect(),
      pl=document.getElementById('vsum').getBoundingClientRect(); return {ok:c.height>0&&c.top>=s.top-1&&c.top>=pl.bottom-1&&c.bottom<=s.bottom+1, cta:Math.round(c.top), list:Math.round(s.top), plate:Math.round(pl.bottom)};});
    if(!PHONE){const c1=await ctaOk(); ok('компьютер: после выделения строки кнопка целиком под плашкой',c1.ok,JSON.stringify(c1));}
    await p.waitForTimeout(600);   // миниатюры строк грузятся лениво — снимок после загрузки
    await p.screenshot({path:OUT+W+'-2-row.png'});
    await p.waitForTimeout(4500);
    ok('подсветка держится дольше 4 с',await p.evaluate(k=>{const r=vwRowOf(items[k]); return !!r&&r.classList.contains('hl');},k));
    await p.evaluate(k=>vwHighlight(k),k); await p.waitForTimeout(400);
    ok('повторный тап по тому же предмету снимает выделение, шторку не трогает',await p.evaluate(ph=>VW.sel==null&&!document.querySelector('#shotbody .row.hl')&&(!ph||document.getElementById('vside').dataset.pos==='3'),PHONE));
    // замена через ленту → 3D, шторка свёрнута, камера наведена на новый предмет
    // как кнопка ленты (`openPicker` → `tryOn` → `closePicker` → `refreshShotList`)
    const tryN=await p.evaluate(k=>{sel=items[k]; draw(); openPicker(items[k]); const cur0=(skuOf(items[k])||{}).name;
      const c=feedFor(String(items[k].role).replace(/\s+\d+$/,'')).find(x=>x&&x.name&&x.name!==cur0); if(!c)return 0;
      tryOn(c); closePicker(); refreshShotList(); return 1;},k);
    ok('лента замены открылась и замена нажата',tryN===1);
    // ждём само наведение, а не «сцена готова»: это условие верно и до начала обновления сцены — на телефоне с программной
    // графикой обновление дольше 2 с, и проверка читала камеру до поворота (18.10)
    const tf=Date.now(); await p.waitForFunction("LIVE.framed!=null&&LIVE.state==='ready'",null,{timeout:60000}).catch(()=>{});
    const frameMs=Date.now()-tf; await p.waitForTimeout(700);
    const st2=await p.evaluate(()=>({mode:VW.mode, pos:document.getElementById('vside').dataset.pos, framed:LIVE.framed||null, free:!!VW.free,
      camsOn:[...document.querySelectorAll('#vCams [data-cam].on')].length, pose:LIVE.scene&&LIVE.scene.pose&&LIVE.scene.pose()}));
    ok('после замены — 3D',st2.mode==='walk',st2.mode);
    if(PHONE)ok('после замены шторка свёрнута',st2.pos==='0','pos='+st2.pos);
    ok('камера наведена на новый предмет (поворот или переход)',['turn','move','none'].includes(st2.framed)&&st2.free,st2.framed+' '+JSON.stringify(st2.pose)+' за '+frameMs+' мс');
    ok('после наведения ни одна подпись ракурса не активна',st2.camsOn===0);
    if(!PHONE){const c2=await ctaOk(); ok('компьютер: после замены кнопка целиком под плашкой',c2.ok,JSON.stringify(c2));}
    await p.screenshot({path:OUT+W+'-3-framed.png'});
    await p.evaluate(()=>document.querySelector('#vCams [data-cam="1"]').click()); await p.waitForTimeout(900);
    ok('подпись ракурса 2 — переход к точке 2, подпись активна',await p.evaluate(()=>VW.photo===1&&!VW.free&&document.querySelector('#vCams [data-cam="1"]').classList.contains('on')));
    // избранное: окошко имени «<Стиль> #N», сохранение, сердечко, переименование, раздел на главной
    await p.click('#vFav'); await p.waitForTimeout(300);
    const nm=await p.inputValue('#favName');
    ok('окошко имени с автоподстановкой «<Стиль> #N»',/^\S.* #\d+$/.test(nm),nm);
    await p.screenshot({path:OUT+W+'-4-name.png'});
    await p.fill('#favName',nm+' тест'); await p.click('#favOk');
    await p.waitForFunction("!document.getElementById('favPop')",null,{timeout:30000}).catch(()=>{});
    await p.waitForTimeout(1500);
    const st3=await p.evaluate(()=>({heart:document.getElementById('vFav').textContent, list:window.__fav.list()}));
    ok('сохранено — сердечко заполнено',st3.heart==='♥');
    // секрет редактирования в журнал не печатаем (Codex 18.10)
    ok('в избранном одна запись с именем и номером состояния',st3.list.length===1&&/тест$/.test(st3.list[0].displayName)&&/^s[12]-/.test(st3.list[0].stateId||''),
      JSON.stringify(Object.assign({},st3.list[0]||{},{editToken:(st3.list[0]||{}).editToken?'***':null})));
    ok('секрет редактирования получен (сервер demo-15)',!!(st3.list[0]||{}).editToken,(st3.list[0]||{}).editToken?'есть':'нет — сервер старый?');
    await p.click('#vFav'); await p.waitForTimeout(300);
    ok('повторный тап — переименовать / убрать',await p.evaluate(()=>!!document.getElementById('favDel')&&document.getElementById('favOk').textContent.length>0));
    await p.fill('#favName','Гостиная мечты'); await p.click('#favOk'); await p.waitForTimeout(1200);
    ok('переименовано',await p.evaluate(()=>window.__fav.list()[0].displayName==='Гостиная мечты'));
    if(st3.list[0]&&st3.list[0].editToken){const srv=await p.evaluate(id=>fetch('/api/collections/'+id,{cache:'no-store'}).then(r=>r.json()).then(j=>({n:j.collection.displayName,h:'editHash' in j.collection})),st3.list[0].collectionId);
      ok('имя на сервере обновилось, хеша в ответе нет',srv.n==='Гостиная мечты'&&!srv.h,JSON.stringify(srv));}
    // «поделиться»: ссылка на коллекцию этого состояния (нет share — копирование + тост)
    await p.click('#vShare'); await p.waitForTimeout(1500);
    const clip=await p.evaluate(()=>navigator.clipboard.readText().catch(()=>''));
    ok('«поделиться» — ссылка на эту коллекцию',/#c=[A-Za-z0-9_-]{22}$/.test(clip)&&clip.includes(st3.list[0]?st3.list[0].collectionId:'@'),clip);
    // главная: раздел «Избранное»
    await p.evaluate(()=>{document.getElementById('shotx').click();}); await p.waitForTimeout(800);
    const st4=await p.evaluate(()=>({head:!document.getElementById('favHead').hidden, cards:document.querySelectorAll('#favGrid .favcard').length,
      name:(document.querySelector('#favGrid .favcard .nm')||{}).textContent||'',
      img:((document.querySelector('#favGrid .favcard img')||{}).src||'').slice(0,23), cardShare:document.querySelectorAll('#hmRooms [data-share]').length, cardLink:document.querySelectorAll('#coll [data-link],#hmRooms [data-link]').length}));
    ok('раздел «Избранное» на главной с карточкой',st4.head&&st4.cards===1&&st4.name==='Гостиная мечты',JSON.stringify(st4));
    ok('карточка избранного — с картинкой (миниатюра из сцены), не заглушка',/^data:image\/jpeg/.test(st4.img),st4.img||'заглушка');
    ok('на карточках вариантов — иконка «поделиться», текстовой «Ссылки» нет',st4.cardShare>0&&st4.cardLink===0);
    await p.evaluate(()=>{window.__basket.open(); document.getElementById('favHead').scrollIntoView();}); await p.waitForTimeout(500);   // раздел свёрнут строкой (demo-16)
    await p.screenshot({path:OUT+W+'-5-home.png'});
    // убрать из избранного — раздел скрыт
    await p.click('#favGrid [data-fmore]'); await p.waitForTimeout(300); await p.click('#favDel'); await p.waitForTimeout(600);
    ok('убрано — раздел скрыт',await p.evaluate(()=>document.getElementById('favHead').hidden&&!window.__fav.list().length));
    ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
    // EN: новые подписи без кириллицы
    const e=await page(b,'en'); await openWin(e,0);
    const en=await e.evaluate(()=>[...document.querySelectorAll('#vCams [data-cam]')].map(x=>x.textContent).concat([document.getElementById('vFav').getAttribute('aria-label'),document.getElementById('vShare').getAttribute('aria-label')]));
    ok('EN: подписи ракурсов и кнопок без кириллицы',!en.some(t=>/[А-Яа-яЁё]/.test(t||'')),en.join(' | '));
  }finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · снимки ${OUT}${W}-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
