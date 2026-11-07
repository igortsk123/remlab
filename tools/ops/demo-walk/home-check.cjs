const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПЕРВЫЙ ЭКРАН ГЛАВНОЙ (план demo-16 шаг 1; с home-mix-01 шаг 5 — макет дизайнера 158:452): до сгиба — строка квартиры, переключатель
// «Интерьер / План квартиры», сертификат, строка «<стиль> · рекомендуем · Выбрать другой» и ≥ 120 px фото первой комнаты (метрика
// `tools/ops/mock/home-v2/check.cjs`); внутри — комнаты в порядке плана, неготовые — заглушкой; окно «Выбрать другой»: фото гостиных,
// 1–2, после двух остальные серые, два — гостиная из первого, спальни из второго (`mix=`); стиль в адресе (`?style=`, `lang`/`s`
// сохраняются); план квартиры — переключателем и обратно; EN без кириллицы. Избранное (demo-17) — отдельный экран `#fav` с «← Назад»:
// пустой по ссылке; ♡ N, «Перейти →» и строка на главной ведут на него; «← Назад» — главная на той же прокрутке; на главной
// раскрывающейся секции нет; поле имени — фокус и каретка в конце сразу после тапа по ♡. Платного пути нет.
//   BASE=https://remont-lab.online/test/share/demo-stage/ OUT=~/scout-scenes/<сессия>/ node tools/ops/demo-walk/home-check.cjs
const {demoUrl}=require('../demo-url.cjs');
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').homedir()+'/scout-scenes/home-check/').replace(/\/?$/,'/');
fs.mkdirSync(OUT,{recursive:true});
const VPS=(process.argv[2]?[process.argv[2]]:['375x667','390x844','1440x900']).map(s=>s.split('x').map(Number));
const ORDER=['living','kitchen','bedroom-1','bedroom-2','bathroom-1','bathroom-2','hall'];   // второй санузел — T-20261022-04
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
const READY="typeof D!=='undefined'&&!!D&&allVariants().length>0&&typeof homeModel==='function'&&homeModel().styles.length>0&&!!document.getElementById('hmMix')";
async function page(b,[W,H],q,lang){
  const phone=W<=700;
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:phone?2:1,isMobile:phone,hasTouch:phone,locale:lang==='en'?'en-GB':'ru-RU'});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://remont-lab.online'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.goto(demoUrl(BASE+(q||'')),{waitUntil:'load',timeout:120000});
  await p.waitForFunction(READY,null,{timeout:90000});
  await p.waitForFunction("!!FLAT",null,{timeout:30000}).catch(()=>{});
  await p.waitForFunction("(()=>{const i=document.querySelector('#hmRooms .hm-room img');return !i||i.complete;})()",null,{timeout:20000}).catch(()=>{});
  await p.waitForTimeout(500);
  return p;
}
const fold=p=>p.evaluate(()=>{const R=s=>{const e=document.querySelector(s);return e?e.getBoundingClientRect():null;}, vh=innerHeight;
  const ph=R('#hmRooms .hm-room .hm-ph'), tabs=R('#hmMix'), hd=R('#hmHd'), vw=R('#hmView');
  const cut=[...document.querySelectorAll('.hm-fk,.hm-price,#flatMeta,.cs-l,.cs-r,.hm-more,.hm-acts .btn,.hm-vw,.hm-mix-n,.hm-mix-pick,.hm-stub b,.hm-stub span,.hm-room .rb small')]
    .filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.textContent.trim().slice(0,24));
  return {photoTop:ph&&Math.round(ph.top), visiblePhotoHeight:ph&&tabs?Math.round(Math.max(0,Math.min(ph.bottom,vh)-Math.max(ph.top,tabs.bottom))):0,
    tabsVisible:!!tabs&&tabs.height>0&&tabs.top>=0&&tabs.bottom<=vh, tabsBottom:tabs&&Math.round(tabs.bottom), hdH:hd&&Math.round(hd.height),
    viewVisible:!!vw&&vw.height>0&&vw.bottom<=vh, hScroll:document.documentElement.scrollWidth>innerWidth, cut};});
// окно «Выбрать другой»: открыть строкой, нажать плитку `at[0]` — окно закрывается, выбор сразу (один выбор, владелец TG 451). Возвращает [id]
async function pickWin(p,at,{shot=''}={}){
  await p.click('#hmMixPick'); await p.waitForSelector('#mixBox.on',{timeout:5000});
  await p.waitForFunction("!!document.querySelector('#mixBox .qz-ph:not([disabled])')",null,{timeout:20000});
  if(shot)await p.screenshot({path:shot});
  const t=p.locator('#mixBox .qz-ph').nth(at[0]), id=await t.getAttribute('data-mx-ph');
  await t.click(); await p.waitForSelector('#mixBox.on',{state:'detached',timeout:5000}).catch(()=>{}); await p.waitForTimeout(700);
  return [id];
}
const sel=p=>p.evaluate(()=>{const e=homeSel(homeModel()), L=homeLayout(homeModel());
  return {sel:e.selected, name:document.getElementById('hmMixName').textContent, want:Object.fromEntries(L.map(x=>[x.r.id,x.want])),
    url:location.search, card:(document.querySelector('#hmRooms .hm-room[data-room=living]')||{}).dataset||{}};});
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    for(const vp of VPS){const [W,H]=vp, phone=W<=700, tag=W+'x'+H;
      const p=await page(b,vp,'');
      const f=await fold(p);
      if(phone)ok(`${tag}: до сгиба переключатель, строка стиля и ≥ 120 px фото первой комнаты`,f.viewVisible&&f.tabsVisible&&f.visiblePhotoHeight>=120,JSON.stringify({photoTop:f.photoTop,visible:f.visiblePhotoHeight,tabsBottom:f.tabsBottom}));
      else ok(`${tag}: переключатель, строка варианта и фото комнаты на первом экране`,f.viewVisible&&f.tabsVisible&&f.visiblePhotoHeight>=120,JSON.stringify({photoTop:f.photoTop,visible:f.visiblePhotoHeight}));
      ok(`${tag}: без горизонтальной прокрутки, подписи не обрезаны`,!f.hScroll&&!f.cut.length,f.cut.join(' | '));
      await p.screenshot({path:OUT+`home-${tag}-1-top.png`});
      if(phone)await p.screenshot({path:OUT+`home-${tag}-3-full.png`,fullPage:true});
      if(!phone&&vp!==VPS[VPS.length-1]){await p.context().close(); continue;}
      const st=await p.evaluate(()=>({tabs:homeModel().styles.map(s=>s.id), titles:Object.fromEntries(homeModel().styles.map(s=>[s.id,s.title])), on:homeSel(homeModel()).selected[0], name:document.getElementById('hmMixName').textContent,
        view:[...document.querySelectorAll('#hmView [data-view]')].map(b=>b.dataset.view+':'+b.getAttribute('aria-selected')),
        rooms:[...document.querySelectorAll('#hmRooms [data-room]')].map(e=>e.dataset.room), ready:[...document.querySelectorAll('#hmRooms .hm-room')].map(e=>e.dataset.room),
        stubs:[...document.querySelectorAll('#hmRooms .hm-stub:not(.hm-plan-tile) span')].map(e=>e.textContent), card:!!FLAT&&Array.isArray(FLAT.rooms)&&FLAT.rooms.length,
        cert:(document.getElementById('hmCert')||{}).dataset||{}, styleUrl:new URLSearchParams(location.search).get('style'),
        oldTabs:document.querySelectorAll('#styleTabs,.hm-tab,#planLink,#planBack,#tab-plan,#tab-room,[data-soon],#screen-soon,#feedShare,#budgetGo').length,
        collBase:[...document.querySelectorAll('#coll .lay')].length}));
      const nm=x=>String(x).replace(/ · (рекомендуем|recommended)$/,'');   // имя стиля, у рекомендуемого — метка (владелец TG 447–448)
      ok('стили главной (≥ 4) — строкой «<стиль> · рекомендуем», переключатель на «Интерьер»',st.tabs.length>=4&&nm(st.name)===st.titles[st.on]&&/ · рекомендуем$/.test(st.name)&&st.view.join()==='room:true,plan:false',st.name+' · '+st.view.join());
      ok('комнаты в порядке плана: гостиная, кухня, спальня 1, спальня 2, санузел 1, санузел 2, прихожая',JSON.stringify(st.rooms)===JSON.stringify(ORDER),st.rooms.join(',')+(st.card?' (из карточки)':' (запасной путь витрины)'));
      ok('гостиная готова; неготовые — единая заглушка',st.ready[0]==='living'&&st.ready.length+st.stubs.length===ORDER.length&&new Set(st.stubs).size<=1,st.ready.join(',')+' | '+st.stubs[0]);
      ok('сертификат: 0 включено, остаток = весь сертификат',+st.cert.included===0&&+st.cert.amount>0,JSON.stringify(st.cert));
      ok('стиль в адресе',st.styleUrl===st.on,st.styleUrl);
      ok('вкладок стилей, ссылки плана, старых вкладок-комнат, «бюджета» и feedShare нет; варианты не дублируются сеткой',st.oldTabs===0&&st.collBase===0,st.oldTabs+'/'+st.collBase);
      // ОКНО «ВЫБРАТЬ ДРУГОЙ»: фото гостиной каждого варианта, названия стилей, у рекомендуемого метка, отмечен нынешний; после двух — остальные серые
      await p.click('#hmMixPick'); await p.waitForSelector('#mixBox.on',{timeout:5000});
      await p.waitForFunction("!!document.querySelector('#mixBox .qz-ph:not([disabled])')",null,{timeout:20000});
      const w0=await p.evaluate(()=>({tiles:[...document.querySelectorAll('#mixBox .qz-ph')].map(b=>({id:b.dataset.mxPh, cap:b.querySelector('b').textContent, img:!!b.querySelector('img'), on:b.getAttribute('aria-pressed')==='true'})),
        quiz:!!document.querySelector('#mixBox [data-mx="quiz"]'), apply:!!document.querySelector('#mixBox [data-mx="apply"]'), locked:document.body.style.position==='fixed'}));
      ok('окно «Выбрать другой» (один выбор, без «Показать»): у каждой плитки фото, подписи — названия стилей, «рекомендуем» у одного, отмечен нынешний, страница под окном стоит',w0.tiles.length>=2&&w0.tiles.every(t=>t.img&&t.cap.replace(/ (рекомендуем|recommended)$/,'')===st.titles[t.id])&&w0.tiles.filter(t=>/ рекомендуем$/.test(t.cap)).length===1&&
        w0.tiles.filter(t=>t.on).map(t=>t.id).join()===st.on&&w0.locked&&!w0.apply,JSON.stringify(w0.tiles.map(t=>t.cap+(t.on?'*':''))));
      ok('окно: «Пройти опрос заново»',w0.quiz);
      await p.screenshot({path:OUT+`home-${tag}-2a-window.png`});
      await p.keyboard.press('Escape'); await p.waitForTimeout(300);
      ok('Esc закрывает окно, выбор прежний',!(await p.$('#mixBox.on'))&&(await sel(p)).sel.join()===st.on);
      // переключение: окно → третий вариант → «Показать»: гостиная этого стиля, открытый вариант, адрес, строка — имя стиля
      const k=Math.min(2,w0.tiles.length-1), [id]=await pickWin(p,[k]);
      const s2=await p.evaluate(()=>{const c=document.querySelector('#hmRooms .hm-room'); const v=allVariants()[cur];
        return {name:document.getElementById('hmMixName').textContent, card:c&&c.dataset.style, variant:c&&c.dataset.variant, cur:v&&v.id,
          url:location.search, sum:c&&c.querySelector('.sum b').textContent};});
      ok('«Выбрать другой» → гостиная этого варианта, открытый вариант и адрес совпадают, строка — имя стиля без метки',s2.card===id&&s2.variant===s2.cur&&new URLSearchParams(s2.url).get('style')===id&&
        s2.name===st.titles[id],JSON.stringify(s2));
      await p.screenshot({path:OUT+`home-${tag}-2-style.png`});
      await p.click('#hmRooms .hm-room [data-swap]'); await p.waitForTimeout(800);
      const win=await p.evaluate(()=>({open:document.getElementById('shot').classList.contains('on'), sum:+document.getElementById('vsum').getAttribute('data-sum'), money:money(+document.getElementById('vsum').getAttribute('data-sum'))}));
      ok('«Открыть» → окно варианта, сумма как на карточке',win.open&&win.money===s2.sum,win.money+' / '+s2.sum);
      await p.keyboard.press('Escape'); await p.evaluate(()=>{const x=document.getElementById('shotx'); if(x&&document.getElementById('shot').classList.contains('on'))x.click();}); await p.waitForTimeout(400);
      // СМЕШИВАНИЕ — ВЫБОРОМ СТИЛЯ В КОМНАТЕ (владелец TG 451): окно гостиной → «Другой стиль для комнаты ›» → один стиль: окно комнаты
      // на новом варианте, меняется только гостиная (`requested`), строка главной — прежний основной стиль, в адресе `mix=`
      const s5a=await sel(p);
      await p.click('#hmRooms .hm-room[data-room=living] [data-swap]'); await p.waitForSelector('#shot.on.v2 #vside',{timeout:15000}); await p.waitForTimeout(600);
      // телефон — плашка «Сменить стиль» поверх фото, строки в шторке нет (владелец TG 472–477); компьютер — строка вверху правой панели
      const row=await p.evaluate(()=>{const t=document.getElementById('vOtherTop'), r=document.getElementById('vrow'), m=document.querySelector('#shot .vmodes').getBoundingClientRect(),
        b=t.getBoundingClientRect(), x=document.getElementById('shotx'); const xb=x&&x.getBoundingClientRect();
        return {top:!!t.offsetParent&&t.textContent, row:r.offsetParent?r.innerText.replace(/\s+/g,' ').trim():'',
          sameRow:Math.abs((b.top+b.bottom)/2-(m.top+m.bottom)/2)<=4, clear:b.left>=m.right+8&&(!xb||b.right<=xb.left-4)&&b.right<=innerWidth};});
      if(phone)ok('окно комнаты (телефон): «Сменить стиль» поверх фото в ряд с «Фото | 3D» и ×, не наезжает; строки стиля в шторке нет',
        row.top==='Сменить стиль'&&!row.row&&row.sameRow&&row.clear,JSON.stringify(row));
      else ok('окно комнаты (компьютер): строка «<стиль> · Другой стиль для комнаты ›», плашки над фото нет',
        !row.top&&row.row===st.titles[s5a.want.living||st.on]+' · Другой стиль для комнаты ›',JSON.stringify(row));
      await p.evaluate(()=>{const t=document.getElementById('vOtherTop'); (t&&t.offsetParent?t:document.getElementById('vOther')).click();}); await p.waitForSelector('#mixBox.on',{timeout:5000});
      await p.waitForFunction("!!document.querySelector('#mixBox .qz-ph:not([disabled])')",null,{timeout:20000});
      const rw=await p.evaluate(()=>({h:document.getElementById('mixH').textContent, tiles:[...document.querySelectorAll('#mixBox .qz-ph')].map(b=>({id:b.dataset.mxPh, on:b.getAttribute('aria-pressed')==='true'})),
        apply:!!document.querySelector('#mixBox [data-mx="apply"]'), nums:[...document.querySelectorAll('#mixBox .qz-tick')].some(t=>/\d/.test(t.textContent))}));
      ok('«Другой стиль для комнаты»: отмечен стиль комнаты, без «Показать» и номеров',rw.tiles.length>=2&&rw.tiles.filter(t=>t.on).length===1&&!rw.apply&&!rw.nums,JSON.stringify(rw));
      await p.screenshot({path:OUT+`home-${tag}-2b-room-window.png`});
      const to=rw.tiles.find(t=>!t.on).id;
      await p.click(`#mixBox .qz-ph[data-mx-ph="${to}"]`); await p.waitForTimeout(900);
      const s5=await sel(p), w5=await p.evaluate(()=>({open:document.getElementById('shot').classList.contains('on'), box:!!document.querySelector('#mixBox.on'), st:styleIdOf(allVariants()[cur]||{})}));
      ok('один выбор: окно стилей закрылось, комната на новом стиле, остальные комнаты как были, строка главной «<основной> + <стиль комнаты>» без «рекомендуем», адрес mix=',
        !w5.box&&w5.open&&w5.st===to&&s5.want.living===to&&Object.keys(s5a.want).every(k=>k==='living'||s5.want[k]===s5a.want[k])&&s5.name===nm(s5a.name)+' + '+st.titles[to]&&/[?&]mix=1\./.test(s5.url),JSON.stringify({w5,s5}));
      await p.screenshot({path:OUT+`home-${tag}-2c-room-style.png`});
      await p.evaluate(()=>{const x=document.getElementById('shotx'); if(x&&document.getElementById('shot').classList.contains('on'))x.click();}); await p.waitForTimeout(400);
      // ЛИПКАЯ ШАПКА (шаг 3; demo-19 Б3 — шкала сертификата тоже липкая, сразу под строкой квартиры): после прокрутки — строка квартиры,
      // шкала и строка варианта (≤ 140 px на телефоне), остальное уехало; «Выбрать другой» снизу страницы — комнаты нового выбора под шапкой
      await p.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight)); await p.waitForTimeout(500);
      const sk=await p.evaluate(()=>{const hd=document.getElementById('hmHd').getBoundingClientRect(), tb=document.getElementById('hmMix').getBoundingClientRect(),
        ce=document.getElementById('hmCert').getBoundingClientRect(),
        gone=['flatPrice','hmView','hmHint'].every(id=>{const r=document.getElementById(id).getBoundingClientRect(); return r.bottom<=hd.bottom;});
        // страница короче высоты шапки и экрана (компьютер, одна готовая комната) — прокрутить мимо шапки нельзя, липкость не включается
        const short=document.documentElement.scrollHeight-innerHeight<document.getElementById('hmHint').getBoundingClientRect().bottom+scrollY;
        return {hdTop:Math.round(hd.top), certTop:Math.round(ce.top), certBot:Math.round(ce.bottom), hdBot:Math.round(hd.bottom), tabsTop:Math.round(tb.top), sticky:Math.round(Math.max(hd.bottom,tb.bottom)), gone, short};});
      ok(`${tag}: после прокрутки липкие строка квартиры, шкала сертификата и строка варианта${phone?' ≤ 140 px':''}, остальное уехало`,
        sk.hdTop===0&&Math.abs(sk.certTop-sk.hdBot)<=1&&sk.tabsTop>=sk.certBot-1&&(sk.gone||(!phone&&sk.short))&&(!phone||sk.sticky<=140),JSON.stringify(sk));
      await p.screenshot({path:OUT+`home-${tag}-4-sticky.png`});
      // прокрутка к комнатам плавная, её длина зависит от высоты страницы — ждём конца: scrollY не меняется 300 мс (не дольше 3 с)
      const [id2]=await pickWin(p,[0]);
      await p.evaluate(()=>new Promise(res=>{let y=scrollY, t0=Date.now(), same=Date.now();
        const tick=()=>{const n=Date.now(); if(scrollY!==y){y=scrollY; same=n;} if(n-same>=300||n-t0>=3000)return res(); requestAnimationFrame(tick);}; requestAnimationFrame(tick);}));
      const s4=await p.evaluate(()=>{const r=document.getElementById('hmRooms').getBoundingClientRect(), tb=document.getElementById('hmMix').getBoundingClientRect();
        return {roomsTop:Math.round(r.top), tabsBottom:Math.round(tb.bottom), vh:innerHeight, style:new URLSearchParams(location.search).get('style'), mix:new URLSearchParams(location.search).get('mix'), room:new URLSearchParams(location.search).get('room')};});
      ok('«Выбрать другой» из липкой строки снизу страницы — комнаты нового выбора под шапкой, в адресе стиль и комната',s4.roomsTop>=s4.tabsBottom-1&&s4.roomsTop<s4.vh*0.6&&s4.style===id2&&!s4.mix&&s4.room==='living',JSON.stringify(s4));
      // план квартиры — переключателем и обратно
      await p.evaluate(()=>scrollTo(0,0)); await p.waitForTimeout(300);
      await p.click('#hmView [data-view="plan"]'); await p.waitForTimeout(400);
      const pl=await p.evaluate(()=>({plan:!document.getElementById('screen-plan').hidden, mixHidden:document.getElementById('hmMix').hidden, hash:location.hash,
        sel:document.querySelector('#hmView [data-view="plan"]').getAttribute('aria-selected')}));
      await p.screenshot({path:OUT+`home-${tag}-8-plan.png`});
      await p.click('#hmView [data-view="room"]'); await p.waitForTimeout(400);
      const bk=await p.evaluate(()=>({room:!document.getElementById('screen-room').hidden, mix:!document.getElementById('hmMix').hidden,
        sel:document.querySelector('#hmView [data-view="room"]').getAttribute('aria-selected')}));
      ok('«План квартиры» — переключателем: план без строки варианта, «Интерьер» — назад',pl.plan&&pl.mixHidden&&pl.sel==='true'&&pl.hash==='#plan'&&bk.room&&bk.mix&&bk.sel==='true',JSON.stringify([pl,bk]));
      ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
      await p.context().close();
      // ссылка менеджера со стилем: ?style= открывает его, прочие параметры не теряются
      const q=await page(b,vp,'?lang=ru&style='+id);
      const s3=await q.evaluate(()=>({on:homeSel(homeModel()).selected.join(), name:document.getElementById('hmMixName').textContent, url:location.search}));
      ok('старая ссылка ?style= открывает этот стиль во всей квартире, lang сохраняется',s3.on===id&&/lang=ru/.test(s3.url)&&nm(s3.name)===st.titles[id],JSON.stringify(s3));
      await q.screenshot({path:OUT+`home-${tag}-9-old-style.png`});
      await q.context().close();
    }
    // ИЗБРАННОЕ — ЭКРАН (demo-17): пустой по ссылке `#fav`; с главной — ♡ N / строка / «Перейти →», «← Назад» — та же прокрутка
    for(const vp of VPS){const [W,H]=vp, tag=W+'x'+H;
      const p=await page(b,vp,'?live=force#fav');
      const scr=()=>p.evaluate(()=>{const s=document.getElementById('screen-fav'), w=document.querySelector('.wrap'), cs=getComputedStyle(w);
        return {fav:!s.hidden, home:!document.getElementById('screen-room').hidden, win:document.getElementById('shot').classList.contains('on'),
          back:!!document.getElementById('favBack').offsetParent, empty:!!document.getElementById('favEmpty').offsetParent, title:document.getElementById('favTitle').textContent,
          cards:document.querySelectorAll('#favGrid .favcard').length, sec:!!document.getElementById('favSec'), tabs:!document.getElementById('hmMix').hidden||!document.getElementById('hmView').hidden,
          w:Math.round(s.getBoundingClientRect().width), col:Math.round(w.getBoundingClientRect().width-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight)),
          hScroll:document.documentElement.scrollWidth>innerWidth, y:Math.round(scrollY), hash:location.hash, len:history.length};});
      const e0=await scr();
      ok(`${tag}: ссылка #fav без избранного — экран «Пока пусто» с «← Назад», строки варианта и переключателя нет`,e0.fav&&e0.empty&&e0.back&&!e0.tabs&&!e0.sec,JSON.stringify(e0));
      await p.screenshot({path:OUT+`home-${tag}-5-fav-empty.png`});
      await p.click('#favBack'); await p.waitForTimeout(500);
      const e1=await scr();
      ok(`${tag}: «← Назад» с пустого экрана — главная`,e1.home&&!e1.fav,JSON.stringify({home:e1.home,hash:e1.hash}));
      // ♡ в окне → поле имени: фокус и каретка в конце сразу после тапа
      await p.click('#hmRooms .hm-room [data-swap]'); await p.waitForSelector('#vFav',{state:'visible',timeout:30000}); await p.waitForTimeout(800);
      await p.click('#vFav');
      const c=await p.evaluate(()=>{const i=document.getElementById('favName'); return {focus:!!i&&document.activeElement===i, start:i?i.selectionStart:-1, end:i?i.selectionEnd:-1, len:i?i.value.length:-1, v:i?i.value:''};});
      ok(`${tag}: тап по ♡ — поле имени в фокусе сразу, каретка в конце`,c.focus&&c.start===c.len&&c.end===c.len&&c.len>0,JSON.stringify(c));
      await p.screenshot({path:OUT+`home-${tag}-6-name.png`});
      await p.click('#favOk'); await p.waitForFunction("window.__basket.state().favorites.length>0&&!document.querySelector('#favPop #favName')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1200);
      await p.evaluate(()=>{const x=document.getElementById('shotx'); if(document.getElementById('shot').classList.contains('on'))x.click();}); await p.waitForTimeout(600);
      const row=await p.evaluate(()=>({row:!document.getElementById('favHead').hidden, n:document.getElementById('favRowN').textContent, sec:!!document.getElementById('favSec'), badge:document.getElementById('hmFavN').textContent}));
      ok(`${tag}: на главной строка «♥ Избранное · 1» (ссылка), раскрывающейся секции нет`,row.row&&row.n==='· 1'&&!row.sec&&row.badge==='1',JSON.stringify(row));
      // ♡ N с прокрученной главной → экран; «← Назад» — та же прокрутка; «вперёд» — экран
      await p.evaluate(()=>scrollTo(0,Math.min(420,document.documentElement.scrollHeight-innerHeight))); await p.waitForTimeout(400);
      const y0=await p.evaluate(()=>Math.round(scrollY));
      await p.click('#hmFav'); await p.waitForTimeout(700);
      const f1=await scr();
      ok(`${tag}: ♡ N → экран «Избранное · 1» с карточкой, на ширину колонки, адрес #fav`,f1.fav&&!f1.home&&f1.back&&f1.title.endsWith('· 1')&&f1.cards===1&&Math.abs(f1.w-f1.col)<=2&&!f1.hScroll&&f1.hash==='#fav',JSON.stringify(f1));
      await p.screenshot({path:OUT+`home-${tag}-7-fav.png`});
      await p.click('#favBack'); await p.waitForTimeout(900);
      const f2=await scr();
      ok(`${tag}: «← Назад» — главная на той же прокрутке`,f2.home&&!f2.fav&&Math.abs(f2.y-y0)<=2,JSON.stringify({y0,y:f2.y,home:f2.home}));
      await p.goForward(); await p.waitForTimeout(900);
      const f3=await scr();
      ok(`${tag}: «вперёд» браузера — снова экран избранного`,f3.fav&&!f3.home,JSON.stringify({fav:f3.fav}));
      await p.goBack(); await p.waitForTimeout(900);
      // строка на главной — тоже на экран
      await p.click('#favRowBtn'); await p.waitForTimeout(700);
      const f4=await scr();
      ok(`${tag}: строка «Избранное» на главной → экран, без лишней записи истории`,f4.fav&&f4.len===f3.len,JSON.stringify({fav:f4.fav,len:f4.len,was:f3.len}));
      ok(`${tag}: без ошибок страницы (избранное)`,!p.errs.length,p.errs.slice(0,2).join(' | '));
      await p.context().close();
    }
    // EN: первый экран и окно «Выбрать другой» без кириллицы
    const e=await page(b,[390,844],'?lang=en','en');
    const en=await e.evaluate(()=>['#hmHd','#flatPrice','#hmView','#hmCert','#hmMix','#hmHint','#hmRooms'].map(s=>(document.querySelector(s)||{}).innerText||'').join(' '));
    const cyr=en.match(/[А-Яа-яЁё][^ ]*/g)||[];
    ok('EN: первый экран без кириллицы',!cyr.length,cyr.slice(0,6).join(' '));
    await e.screenshot({path:OUT+'home-390x844-en.png'});
    await e.click('#hmMixPick'); await e.waitForSelector('#mixBox.on',{timeout:5000}); await e.waitForTimeout(600);
    const enw=await e.evaluate(()=>document.querySelector('#mixBox .qz-card').innerText);
    const cyw=enw.match(/[А-Яа-яЁё][^ ]*/g)||[];
    ok('EN: окно «Выбрать другой» без кириллицы',!cyw.length&&/recommended/.test(enw),cyw.slice(0,6).join(' ')||enw.slice(0,60));
    await e.screenshot({path:OUT+'home-390x844-en-window.png'});
    ok('EN: без ошибок страницы',!e.errs.length,e.errs.slice(0,2).join(' | '));
    await e.context().close();
  }finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · снимки ${OUT}home-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
