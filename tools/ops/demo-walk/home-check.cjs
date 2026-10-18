const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПЕРВЫЙ ЭКРАН ГЛАВНОЙ (план demo-16 шаг 1, макет A): до сгиба — строка квартиры, сертификат, подсказка, вкладки-стили и ≥ 120 px фото
// первой комнаты (метрика `tools/ops/mock/home-v2/check.cjs`); вкладки — стили, внутри — комнаты в порядке плана, неготовые — заглушкой;
// стиль в адресе (`?style=`, `lang`/`s` сохраняются); план квартиры — ссылкой и обратно; EN без кириллицы. Платного пути нет.
//   BASE=https://remont-lab.online/test/share/demo-stage/ OUT=~/scout-scenes/<сессия>/ node tools/ops/demo-walk/home-check.cjs
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').homedir()+'/scout-scenes/home-check/').replace(/\/?$/,'/');
fs.mkdirSync(OUT,{recursive:true});
const VPS=(process.argv[2]?[process.argv[2]]:['375x667','390x844','1440x900']).map(s=>s.split('x').map(Number));
const ORDER=['living','kitchen','bedroom-1','bedroom-2','bathroom-1','hall'];
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
async function page(b,[W,H],q,lang){
  const phone=W<=700;
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:phone?2:1,isMobile:phone,hasTouch:phone,locale:lang==='en'?'en-GB':'ru-RU'});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://remont-lab.online'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.goto(BASE+(q||''),{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&allVariants().length>0&&document.querySelectorAll('#styleTabs [data-style]').length>0",null,{timeout:90000});
  await p.waitForFunction("!!FLAT",null,{timeout:30000}).catch(()=>{});
  await p.waitForFunction("(()=>{const i=document.querySelector('#hmRooms .hm-room img');return !i||i.complete;})()",null,{timeout:20000}).catch(()=>{});
  await p.waitForTimeout(500);
  return p;
}
const fold=p=>p.evaluate(()=>{const R=s=>{const e=document.querySelector(s);return e?e.getBoundingClientRect():null;}, vh=innerHeight;
  const ph=R('#hmRooms .hm-room .hm-ph'), tabs=R('#styleTabs'), hd=R('#hmHd');
  const cut=[...document.querySelectorAll('.hm-fk,.hm-price,#flatMeta,.hm-cert .t span,.hm-acts .btn,.hm-tab,.hm-stub b,.hm-stub span,.hm-room .rb small')]
    .filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.textContent.trim().slice(0,24));
  return {photoTop:ph&&Math.round(ph.top), visiblePhotoHeight:ph&&tabs?Math.round(Math.max(0,Math.min(ph.bottom,vh)-Math.max(ph.top,tabs.bottom))):0,
    tabsVisible:!!tabs&&tabs.top>=0&&tabs.bottom<=vh, tabsBottom:tabs&&Math.round(tabs.bottom), hdH:hd&&Math.round(hd.height),
    hScroll:document.documentElement.scrollWidth>innerWidth, cut};});
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    for(const vp of VPS){const [W,H]=vp, phone=W<=700, tag=W+'x'+H;
      const p=await page(b,vp,'');
      const f=await fold(p);
      if(phone)ok(`${tag}: до сгиба вкладки стилей и ≥ 120 px фото первой комнаты`,f.tabsVisible&&f.visiblePhotoHeight>=120,JSON.stringify({photoTop:f.photoTop,visible:f.visiblePhotoHeight,tabsBottom:f.tabsBottom}));
      else ok(`${tag}: вкладки и фото комнаты на первом экране`,f.tabsVisible&&f.visiblePhotoHeight>=120,JSON.stringify({photoTop:f.photoTop,visible:f.visiblePhotoHeight}));
      ok(`${tag}: без горизонтальной прокрутки, подписи не обрезаны`,!f.hScroll&&!f.cut.length,f.cut.join(' | '));
      await p.screenshot({path:OUT+`home-${tag}-1-top.png`});
      if(phone)await p.screenshot({path:OUT+`home-${tag}-3-full.png`,fullPage:true});
      if(!phone&&vp!==VPS[VPS.length-1]){await p.context().close(); continue;}
      const st=await p.evaluate(()=>({tabs:[...document.querySelectorAll('#styleTabs [data-style]')].map(t=>t.dataset.style), on:(document.querySelector('#styleTabs .hm-tab.on')||{}).dataset,
        rooms:[...document.querySelectorAll('#hmRooms [data-room]')].map(e=>e.dataset.room), ready:[...document.querySelectorAll('#hmRooms .hm-room')].map(e=>e.dataset.room),
        stubs:[...document.querySelectorAll('#hmRooms .hm-stub span')].map(e=>e.textContent), card:!!FLAT&&Array.isArray(FLAT.rooms)&&FLAT.rooms.length,
        cert:(document.getElementById('hmCert')||{}).dataset||{}, styleUrl:new URLSearchParams(location.search).get('style'), nVar:allVariants().filter(v=>!v.mine).length,
        oldTabs:document.querySelectorAll('#tab-plan,#tab-room,[data-soon],#screen-soon,#feedShare,#budgetGo').length,
        collBase:[...document.querySelectorAll('#coll .lay')].length}));
      ok('вкладки — стили, по одной на опубликованный стиль',st.tabs.length===st.nVar&&st.tabs.length>=4,st.tabs.join(','));
      ok('комнаты в порядке плана: гостиная, кухня, спальня 1, спальня 2, санузел, прихожая',JSON.stringify(st.rooms)===JSON.stringify(ORDER),st.rooms.join(',')+(st.card?' (из карточки)':' (запасной путь витрины)'));
      ok('готова только гостиная, остальные — единая заглушка',JSON.stringify(st.ready)===JSON.stringify(['living'])&&st.stubs.length===5&&new Set(st.stubs).size===1,st.stubs[0]);
      ok('сертификат: 0 включено, остаток = весь сертификат',+st.cert.included===0&&+st.cert.amount>0,JSON.stringify(st.cert));
      ok('стиль в адресе',st.styleUrl===st.on.style,st.styleUrl);
      ok('старых вкладок-комнат, «бюджета» и feedShare нет; варианты стилей не дублируются сеткой',st.oldTabs===0&&st.collBase===0,st.oldTabs+'/'+st.collBase);
      // переключение стиля: вкладка → карточка гостиной этого стиля, сумма как в окне, адрес
      const k=Math.min(3,st.tabs.length-1), id=st.tabs[k];
      await p.click(`#styleTabs [data-style="${id}"]`); await p.waitForTimeout(700);
      const s2=await p.evaluate(id=>{const c=document.querySelector('#hmRooms .hm-room'); const v=allVariants()[cur];
        return {on:(document.querySelector('#styleTabs .hm-tab.on')||{}).dataset.style, card:c&&c.dataset.style, variant:c&&c.dataset.variant, cur:v&&v.id,
          url:location.search, sum:c&&c.querySelector('.sum b').textContent};},id);
      ok('вкладка стиля → гостиная этого стиля, открытый вариант и адрес совпадают',s2.on===id&&s2.card===id&&s2.variant===s2.cur&&new URLSearchParams(s2.url).get('style')===id,JSON.stringify(s2));
      await p.screenshot({path:OUT+`home-${tag}-2-style.png`});
      await p.click('#hmRooms .hm-room [data-swap]'); await p.waitForTimeout(800);
      const win=await p.evaluate(()=>({open:document.getElementById('shot').classList.contains('on'), sum:+document.getElementById('vsum').getAttribute('data-sum'), money:money(+document.getElementById('vsum').getAttribute('data-sum'))}));
      ok('«Открыть» → окно варианта, сумма как на карточке',win.open&&win.money===s2.sum,win.money+' / '+s2.sum);
      await p.keyboard.press('Escape'); await p.evaluate(()=>{const x=document.getElementById('shotx'); if(x&&document.getElementById('shot').classList.contains('on'))x.click();}); await p.waitForTimeout(400);
      // ЛИПКАЯ ШАПКА (шаг 3): после прокрутки — две строки (квартира · цена · ♡ и вкладки) ≤ 96 px на телефоне, остальное уехало;
      // вкладка стиля снизу страницы — комнаты нового стиля видны под шапкой
      await p.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight)); await p.waitForTimeout(500);
      const sk=await p.evaluate(()=>{const hd=document.getElementById('hmHd').getBoundingClientRect(), tb=document.getElementById('styleTabs').getBoundingClientRect(),
        gone=['flatPrice','hmCert','hmHint'].every(id=>{const r=document.getElementById(id).getBoundingClientRect(); return r.bottom<=hd.bottom;});
        return {hdTop:Math.round(hd.top), tabsTop:Math.round(tb.top), sticky:Math.round(Math.max(hd.bottom,tb.bottom)), gone};});
      ok(`${tag}: после прокрутки липкие строка квартиры и вкладки${phone?' ≤ 96 px':''}, остальное уехало`,sk.hdTop===0&&sk.tabsTop<=sk.sticky&&sk.gone&&(!phone||sk.sticky<=96),JSON.stringify(sk));
      await p.screenshot({path:OUT+`home-${tag}-4-sticky.png`});
      const id2=st.tabs[0];
      await p.click(`#styleTabs [data-style="${id2}"]`); await p.waitForTimeout(900);
      const s4=await p.evaluate(()=>{const r=document.getElementById('hmRooms').getBoundingClientRect(), tb=document.getElementById('styleTabs').getBoundingClientRect();
        return {roomsTop:Math.round(r.top), tabsBottom:Math.round(tb.bottom), vh:innerHeight, style:new URLSearchParams(location.search).get('style'), room:new URLSearchParams(location.search).get('room')};});
      ok('вкладка стиля из липкой шапки снизу страницы — комнаты нового стиля под шапкой, в адресе стиль и комната',s4.roomsTop>=s4.tabsBottom-1&&s4.roomsTop<s4.vh*0.6&&s4.style===id2&&s4.room==='living',JSON.stringify(s4));
      // план квартиры — ссылкой и обратно
      await p.click('[data-plan]:visible'); await p.waitForTimeout(400);
      const pl=await p.evaluate(()=>({plan:!document.getElementById('screen-plan').hidden, tabs:document.getElementById('styleTabs').hidden, hash:location.hash}));
      await p.click('#planBack'); await p.waitForTimeout(400);
      const bk=await p.evaluate(()=>({room:!document.getElementById('screen-room').hidden, tabs:!document.getElementById('styleTabs').hidden}));
      ok('«План квартиры» — ссылкой: план без вкладок стилей, «← К стилям» — назад',pl.plan&&pl.tabs&&bk.room&&bk.tabs,JSON.stringify([pl,bk]));
      ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
      await p.context().close();
      // ссылка менеджера со стилем: ?style= открывает его, прочие параметры не теряются
      const q=await page(b,vp,'?lang=ru&style='+id);
      const s3=await q.evaluate(()=>({on:(document.querySelector('#styleTabs .hm-tab.on')||{}).dataset.style, url:location.search}));
      ok('?style= открывает этот стиль, lang сохраняется',s3.on===id&&/lang=ru/.test(s3.url),JSON.stringify(s3));
      await q.context().close();
    }
    // EN: первый экран без кириллицы
    const e=await page(b,[390,844],'?lang=en');
    const en=await e.evaluate(()=>['#hmHd','#flatPrice','#hmCert','#hmHint','#styleTabs','#hmRooms'].map(s=>(document.querySelector(s)||{}).innerText||'').join(' '));
    const cyr=en.match(/[А-Яа-яЁё][^ ]*/g)||[];
    ok('EN: первый экран без кириллицы',!cyr.length,cyr.slice(0,6).join(' '));
    await e.screenshot({path:OUT+'home-390x844-en.png'}); await e.context().close();
  }finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · снимки ${OUT}home-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
