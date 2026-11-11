const {demoUrl}=require('../demo-url.cjs');
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КОРЗИНА — КАК СЕЙЧАС (T-20261107-69, после окна по макету 373:7035 / home-figma-02, 837faf28): «Выбрано» — сумма вариантов ВСЕХ комнат
// главной (`homeChosen`), а не корзина избранного. Что проверяем:
//  1. главная на старте: «Выбрано X» = сумма цен на карточках комнат = `#hmCert[data-included]`; справа — сертификат карточки квартиры;
//  2. окно гостиной: «Выбрано» = X главной; «Эта комната» = цена карточки = чип «⌃ Мебель и отделка · N (сумма)», N — как на карточке;
//     шкала в одну строку; на телефоне подсказка шторки — не во время загрузки и над переключателем ракурсов;
//  3. замена ТВ-тумбы на первую в ленте: «Выбрано», «Эта комната» и чип меняются РОВНО на разницу цен (× число сменённых предметов);
//  4. окно закрыто — на главной «Выбрано» и карточка гостиной сдвинулись на ту же разницу;
//  5. доплата (сертификат подменён ответом карточки квартиры: X + 1 ₽): на старте её нет; замена на самую дорогую — «доплата N»,
//     N = выбрано − сертификат, в шкале окна, в «i» и на главной; обратная замена — доплата ушла, сумма снова X;
//  6. EN (цены — в фунтах по курсу, сертификат подменён на 100): шкала главной и окна, чип и «i» с доплатой — без кириллицы;
//  7. на телефоне окно сразу в 3D (комната без фото) — подсказка только после загрузки.
// «Убрать из выбора» на странице нет (только модуль `lib/basket/basket.ts:excludeLine`, юнит-тесты `tests/unit/basket.test.ts`).
// ИЗБРАННОЕ (♡, «Гостиная #1», экран `#screen-fav`, вопрос «вместо», диалог доплаты при включении) — код на странице есть, вход скрыт
// (`favUi`: ♡ всегда `hidden`) — шаги под флагом `BASKET_FAV=1` (по умолчанию выключены), ♡ нажимается из кода.
// Платного пути нет: `/api/render` и `/api/job` подменены (счётчик — в итоге).
//   PROD=1 OUT=~/remlab-scratch/<папка>/ node tools/ops/demo-walk/basket-check.cjs 375x667      (BASE=<адрес демо> — другая сборка)
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').homedir()+'/scout-scenes/basket-check/').replace(/\/?$/,'/');
const FAV=process.env.BASKET_FAV==='1';
fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
let FAKE=0;
const READY="typeof D!=='undefined'&&!!D&&!!FLAT&&!!(window.__basket&&window.__basket.state())&&typeof homeModel==='function'&&homeModel().styles.length>0";
async function page(b,o={}){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:PHONE?2:1,isMobile:PHONE,hasTouch:PHONE,locale:o.lang==='en'?'en-GB':'ru-RU'});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://remont-lab.online'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>{FAKE++; r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})});});
  await p.route(/\/api\/job\?/,r=>{FAKE++; r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:30})});});
  // сертификат — пакетом одной суммы (demo-23: страница берёт политику `incentive`, сумма сертификата — её итог)
  if(o.limit)await p.route(/\/api\/apartments\//,async r=>{const res=await r.fetch(); const j=await res.json(); if(j.card&&j.card.certificate)j.card.certificate.amount=o.limit;
    if(j.card&&j.card.incentive)j.card.incentive={...j.card.incentive,mode:'pooled',limits:{furniture:o.limit,fitout:0},total:o.limit};
    await r.fulfill({response:res,body:JSON.stringify(j),headers:{...res.headers(),'content-type':'application/json'}});});
  if(o.embed)await ctx.addInitScript(()=>{window.__EMBED={partner:'demo',flat:'flat215',lang:'ru'}; window.__sendFlat='flat215';});   // как `lib/embed/page.ts`
  if(o.seed)await ctx.addInitScript(s=>{try{if(!sessionStorage.getItem('seeded')){localStorage.clear(); Object.entries(s).forEach(([k,v])=>localStorage.setItem(k,v)); sessionStorage.setItem('seeded','1');}}catch(e){}},o.seed);
  // `quiz=0` — без опроса-знакомства: главная сразу, как у проверок окна
  await p.goto(demoUrl(BASE+(o.lang==='en'?'?lang=en&':'?')+'live=force&quiz=0'),{waitUntil:'load',timeout:120000});
  await p.waitForFunction(READY,null,{timeout:90000});
  // реестр кадров пришёл: иначе окно, открытое в 3D до него, по его приходу встаёт на «Фото» посреди шага (T-20261107-66/2)
  await p.waitForFunction("SHOTS_LOADED&&shots.some(x=>x.srv)",null,{timeout:60000});
  await p.waitForTimeout(800);
  return p;
}
const dig=s=>{const m=String(s||'').replace(/[^\d]/g,''); return m?+m:null;};
// главная: шкала липкого низа и карточки комнат (цена и число товаров — из карточки, как видит покупатель)
const home=p=>p.evaluate(()=>{const c=document.getElementById('hmCert'), q=s=>c.querySelector(s);
  return {inc:+c.dataset.included, over:+c.dataset.over, amount:+c.dataset.amount, hidden:c.hidden, incTxt:(q('.cs-l b')||{}).textContent, total:(q('.cs-t > .cs-r b')||{}).textContent,
    overCls:!!q('.cs.over'), dop:(q('.cs-ov .dop')||{}).textContent||'', text:c.textContent, cert:(FLAT.certificate||{}).amount||0,
    cards:[...document.querySelectorAll('#hmRooms article.hm-room[data-room]')].map(a=>({room:a.dataset.room, sum:(a.querySelector('.rb .sum b')||{}).textContent, n:(a.querySelector('.rb .sum small')||{}).textContent}))};});
// окно: шкала `#vsum` (эта комната / другие), чип шторки; `data-to` — итог без анимации цифр
const plate=p=>p.evaluate(()=>{const s=document.getElementById('vsum'), q=x=>s.querySelector(x), row=q('.cs-t'), pl=s.getBoundingClientRect();
  const last=row?row.lastElementChild.getBoundingClientRect():null, chip=(document.getElementById('vchip')||{}).textContent||'';
  return {inc:+((q('[data-k="inc"]')||{dataset:{}}).dataset.to), incTxt:(q('.cs-l b')||{}).textContent, room:(q('.cs-room .nv')||{}).textContent, total:(q('.cs-t > .cs-r b')||{}).textContent,
    sum:+s.dataset.sum, count:+s.dataset.count, chip, over:!!q('.cs.over'), dop:(q('.cs-ov .dop')||{}).textContent||'', bub:(q('.vpl-bub')||{}).textContent||'', text:s.textContent,
    fits:!!row&&row.scrollWidth<=row.clientWidth+1&&last.right<=pl.right+1&&row.querySelector('.cs-l').scrollWidth<=row.querySelector('.cs-l').clientWidth+1,
    vid:(allVariants()[cur]||{}).id};});
const chipN=t=>{const m=String(t).match(/·\s*(\d+)\s*\(/); return m?+m[1]:null;}, chipSum=t=>dig((String(t).match(/\(([^)]*)\)/)||[])[1]);
// открыть окно гостиной с карточки главной; на телефоне — состояние подсказки шторки в момент показа
async function openLiving(p,{tip}={}){
  await p.evaluate(()=>{const g=document.querySelector('#hmRooms article.hm-room[data-room="living"] [data-swap]')||document.querySelector('#hmRooms [data-swap]'); g.click();});
  let t=null;
  if(tip)t=await p.waitForFunction(()=>{const t=document.querySelector('#shot .vtip'); if(!t)return null;
    const c=document.getElementById('vCams'), tr=t.getBoundingClientRect(), cr=c.getBoundingClientRect();
    return {mode:t.dataset.mode, live:t.dataset.live, busy:t.dataset.busy, tipBottom:Math.round(tr.bottom), camsTop:Math.round(cr.top)};},null,{timeout:40000,polling:100}).then(h=>h.jsonValue(),()=>null);
  await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000});
  await p.evaluate("vwMode('walk')");
  await p.waitForFunction("LIVE.state==='ready'&&!!LIVE.scene",null,{timeout:120000}); await p.waitForTimeout(1000);
  return t;
}
const closeWin=async p=>{await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(1500);};
// замена предмета роли из ленты: `first` — первая не текущая (лента — «дешевле сначала»), `max` — самая дорогая, `{name}` — по имени
async function replace(p,role,pick){
  const k=await p.evaluate(role=>items.findIndex(i=>i.role.startsWith(role)),role); if(k<0)return null;
  const old=await p.evaluate(k=>({price:items[k].sku.price, name:items[k].sku.name}),k);
  await p.evaluate(k=>openPicker(items[k]),k); await p.waitForTimeout(600);
  const j=await p.evaluate(pk=>{const cs=[...document.querySelectorAll('#grid .card:not(.cur)')], pr=c=>+String(c.querySelector('.pr').textContent).replace(/[^\d]/g,'');
    if(!cs.length)return -1; if(pk==='first')return 0; if(pk==='max')return cs.reduce((a,c,i)=>pr(c)>pr(cs[a])?i:a,0);
    return cs.findIndex(c=>c.querySelector('.nm').textContent.trim()===pk.name.trim());},pick);
  if(j<0){await p.evaluate(()=>typeof closePicker==='function'&&closePicker()); return {old,fail:'в ленте нет карточки «'+(pick.name||pick)+'»'};}
  await p.locator('#grid .card:not(.cur)').nth(j).locator('.acts button').first().click(); await p.waitForTimeout(1800);   // цифры шкалы — 0,45 с
  const now=await p.evaluate(k=>({price:items[k].sku.price, name:items[k].sku.name, n:(TRY_LAST&&TRY_LAST.n)||1}),k);
  return {old, now, delta:(now.price-old.price)*now.n};
}
const fm=n=>Math.round(n).toLocaleString('ru-RU');
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    // 1) главная на старте
    const p=await page(b);
    const h0=await home(p), cardsSum=h0.cards.reduce((a,c)=>a+(dig(c.sum)||0),0);
    ok('главная: «Выбрано» = сумма цен на карточках комнат (сумма витрины), не 0',h0.inc>0&&h0.inc===cardsSum&&dig(h0.incTxt)===h0.inc,JSON.stringify({inc:h0.inc,txt:h0.incTxt,cards:h0.cards}));
    ok('главная: справа — сумма сертификата квартиры; доплаты нет, пока выбрано не больше',!h0.hidden&&dig(h0.total)===h0.cert&&h0.amount===h0.cert&&(h0.inc>h0.cert||(!h0.overCls&&h0.over===0&&!h0.dop)),
      JSON.stringify({total:h0.total,cert:h0.cert,over:h0.over,dop:h0.dop}));
    await p.screenshot({path:OUT+W+'-1-home.png'});
    const X=h0.inc, liv=h0.cards.find(c=>c.room==='living')||h0.cards[0];
    // 2) окно гостиной
    const tip=await openLiving(p,{tip:PHONE});
    if(PHONE)ok('подсказка шторки — не во время загрузки (в 3D — сцена готова) и над переключателем ракурсов',!!tip&&tip.busy==='false'&&(tip.mode!=='walk'||tip.live==='ready')&&tip.tipBottom<=tip.camsTop,JSON.stringify(tip));
    const w0=await plate(p);
    ok('окно: «Выбрано» = «Выбрано» главной (все комнаты)',w0.inc===X&&dig(w0.incTxt)===X,JSON.stringify({inc:w0.inc,txt:w0.incTxt,X}));
    ok('окно: «Эта комната» = цена карточки гостиной = сумма в чипе; «· N» чипа = число товаров карточки',
      dig(w0.room)===dig(liv.sum)&&w0.sum===dig(liv.sum)&&chipSum(w0.chip)===w0.sum&&chipN(w0.chip)===dig(liv.n)&&w0.count===dig(liv.n),JSON.stringify({room:w0.room,card:liv,sum:w0.sum,chip:w0.chip}));
    ok('окно: справа та же сумма сертификата, шкала в одну строку',dig(w0.total)===h0.cert&&w0.fits,JSON.stringify({total:w0.total,fits:w0.fits}));
    await p.screenshot({path:OUT+W+'-2-window.png'});
    // 3) замена — сумма ровно на разницу цен
    const r1=await replace(p,'тв-тумба','first');
    const w1=await plate(p);
    ok('замена ТВ-тумбы: «Выбрано», «Эта комната» и чип изменились ровно на разницу цен; число товаров то же',
      !!r1&&!r1.fail&&r1.delta!==0&&w1.inc===X+r1.delta&&dig(w1.incTxt)===w1.inc&&w1.sum===w0.sum+r1.delta&&dig(w1.room)===w1.sum&&chipSum(w1.chip)===w1.sum&&w1.count===w0.count,
      JSON.stringify({r:r1,inc:[w0.inc,w1.inc],room:[w0.sum,w1.sum],chip:w1.chip}));
    await p.screenshot({path:OUT+W+'-3-replaced.png'});
    // 4) окно закрыто — главная пересчитана
    await closeWin(p);
    const h1=await home(p), liv1=h1.cards.find(c=>c.room===liv.room)||{};
    ok('после окна главная: «Выбрано» и карточка гостиной сдвинулись на ту же разницу',!!r1&&!r1.fail&&h1.inc===X+r1.delta&&dig(h1.incTxt)===h1.inc&&dig(liv1.sum)===dig(liv.sum)+r1.delta,
      JSON.stringify({inc:[X,h1.inc],card:[liv.sum,liv1.sum],delta:r1&&r1.delta}));
    ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
    await p.screenshot({path:OUT+W+'-4-home-after.png'});
    await p.context().close();
    // 5) доплата: сертификат = X + 1 ₽
    const L=X+1, q=await page(b,{limit:L});
    const hq0=await home(q);
    ok(`доплата: сертификат ${fm(L)} (подменён), выбрано ${fm(hq0.inc)} — доплаты нет`,hq0.inc===X&&hq0.cert===L&&dig(hq0.total)===L&&!hq0.overCls&&hq0.over===0&&!hq0.dop,JSON.stringify({inc:hq0.inc,total:hq0.total,over:hq0.over,dop:hq0.dop}));
    await openLiving(q);
    const r2=await replace(q,'тв-тумба','max'), wq=await plate(q), N=r2&&!r2.fail?X+r2.delta-L:null;
    ok('замена на самую дорогую — в окне «доплата N», N = выбрано − сертификат; в «i» — «Доплата N»',
      !!r2&&!r2.fail&&r2.delta>0&&wq.inc===X+r2.delta&&wq.over&&dig(wq.dop)===N&&new RegExp('Доплата\\s*'+fm(N).replace(/\s/g,'\\s*')).test(wq.bub.replace(/[\u00a0\u202f]/g,' ')),
      JSON.stringify({r:r2,inc:wq.inc,N,dop:wq.dop,bub:wq.bub.slice(0,160)}));
    await q.screenshot({path:OUT+W+'-5-over-window.png'});
    await closeWin(q);
    const hq1=await home(q);
    ok('главная с доплатой: data-over = N, «доплата N» под шкалой',hq1.inc===X+(r2&&r2.delta||0)&&hq1.over===N&&hq1.overCls&&dig(hq1.dop)===N,JSON.stringify({inc:hq1.inc,over:hq1.over,dop:hq1.dop,N}));
    await q.screenshot({path:OUT+W+'-6-over-home.png'});
    await openLiving(q);
    const r3=await replace(q,'тв-тумба',{name:r2&&r2.old?r2.old.name:''}), wq2=await plate(q);
    ok('обратная замена — сумма снова X, доплаты нет',!!r3&&!r3.fail&&wq2.inc===X&&!wq2.over&&!wq2.dop,JSON.stringify({r:r3,inc:wq2.inc,X,over:wq2.over,dop:wq2.dop}));
    ok('без ошибок страницы (доплата)',!q.errs.length,q.errs.slice(0,2).join(' | '));
    await q.context().close();
    // 6) EN — шкала главной и окна, чип, «i» с доплатой. Английская страница русской квартиры — в фунтах по курсу (`toCard`, чип «£2,406»):
    //    сертификат X + 1 там был бы в фунтах и доплаты не дал — берём 100 в валюте карточки, доплата видна сразу
    const e=await page(b,{lang:'en',limit:100});
    const he=await home(e);
    await openLiving(e);
    const re=await replace(e,'тв-тумба','max'), we=await plate(e);
    await closeWin(e);
    const he2=await home(e);
    const txt=[he.text,we.text,we.chip,we.bub,he2.text].join(' '), cyr=txt.match(/[А-Яа-яЁё]+/g)||[];
    ok('EN: шкала главной и окна, чип и «i» — без кириллицы; «Chosen», «allowance», «top-up», «Furniture & finishes»',
      !cyr.length&&/Chosen/.test(txt)&&/allowance/i.test(txt)&&/top-up/i.test(txt)&&/Furniture & finishes/.test(we.chip)&&!!re&&!re.fail,cyr.slice(0,6).join(' ')+' | '+we.chip+' | '+we.dop);
    await e.screenshot({path:OUT+W+'-7-en-home.png'});
    ok('без ошибок страницы (EN)',!e.errs.length,e.errs.slice(0,2).join(' | '));
    await e.context().close();
    // 7) телефон: окно сразу в 3D (комната без единого фото) — подсказка ждёт модели
    if(PHONE){
      const t3=await page(b);
      const m3=await t3.evaluate(()=>{window.vwRealShots=vwRealShots=()=>[]; window.vwPhotoShots=vwPhotoShots=()=>[]; pickVariant(0); VW.collapse=true; vwOpenVariant(0); return VW.mode;});
      const tp=await t3.waitForFunction(()=>{const t=document.querySelector('#shot .vtip'); if(!t)return null; const cr=document.getElementById('vCams').getBoundingClientRect();
        return {mode:t.dataset.mode, live:t.dataset.live, busy:t.dataset.busy, tipBottom:Math.round(t.getBoundingClientRect().bottom), camsTop:Math.round(cr.top)};},null,{timeout:60000,polling:100}).then(h=>h.jsonValue(),()=>null);
      ok('окно сразу в 3D: подсказка — только после загрузки и над переключателем',m3==='walk'&&!!tp&&tp.busy==='false'&&(tp.mode!=='walk'||tp.live==='ready')&&tp.tipBottom<=tp.camsTop,JSON.stringify({m3,tp}));
      await t3.context().close();
    }
    if(FAV)await favSteps(b);
  }catch(e){R.push('FAIL проверка прервалась — '+String(e.message||e).split('\n').slice(0,14).join(' | '));
    try{for(const c of b.contexts())for(const pg of c.pages())await pg.screenshot({path:OUT+W+'-fail-'+Date.now()+'.png'});}catch(_){}}
  finally{
    await b.close().catch(()=>{});
    console.log(R.join('\n'));
    console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · ${R.some(x=>x.startsWith('FAIL'))?'ЕСТЬ FAIL':'ВСЁ OK'} · подмен платного ${FAKE}${FAV?' · с избранным':''} · снимки ${OUT}${W}-*.png`);
    process.exitCode=R.some(x=>x.startsWith('FAIL'))||!R.length?1:0;
  }
})();

// ───── ИЗБРАННОЕ (флаг `BASKET_FAV=1`): прежний сценарий корзины избранного demo-16…demo-23. Вход на странице скрыт — ♡ и ♡ N
// нажимаются из кода; шкала главной теперь не корзина (`homeChosen`), поэтому суммы — по `__basket.totals()`, а не по `#hmCert`.
async function favPage(b,o){const p=await page(b,o);
  if(!o||!o.seed){await p.evaluate(()=>{Object.keys(localStorage).filter(k=>/^remlab-(basket|favorites|collections|fav-thumbs)/.test(k)).forEach(k=>localStorage.removeItem(k)); location.reload();});
    await p.waitForFunction(READY,null,{timeout:90000}); await p.waitForFunction("SHOTS_LOADED&&shots.some(x=>x.srv)",null,{timeout:60000}); await p.waitForTimeout(800);}
  return p;}
const heart=p=>p.evaluate(()=>document.getElementById('vFav').click());
const fst=p=>p.evaluate(()=>{const b=window.__basket.state(), t=window.__basket.totals();
  return {n:b.favorites.length, inc:b.includedByRoom, names:b.favorites.map(f=>f.displayName), eligible:t.allowanceEligible, complete:t.allowanceComplete,
    toast:(document.getElementById('toast')||{}).textContent||'', pop:(document.getElementById('favPop')||{}).innerText||''};});
const caret=p=>p.evaluate(()=>{const i=document.getElementById('favName'), a=document.activeElement;
  return {focus:!!i&&a===i, start:i?i.selectionStart:-1, end:i?i.selectionEnd:-1, len:i?i.value.length:-1};});
const caretOk=c=>c.focus&&c.start===c.len&&c.end===c.len&&c.len>0;
const favScr=p=>p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), fav:!document.getElementById('screen-fav').hidden,
  home:!document.getElementById('screen-room').hidden, view:(history.state||{}).view, hash:location.hash, len:history.length,
  back:!!document.getElementById('favBack').offsetParent, sec:!!document.getElementById('favSec')}));
const openWin=async(p,i)=>{await p.evaluate(i=>{pickVariant(i); VW.collapse=true; vwOpenVariant(i); if(VW.mode!=='walk')vwMode('walk');},i);
  await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1200);};
const saveHeart=async p=>{await heart(p); const c=await caret(p); await p.waitForSelector('#favName'); const nm=await p.inputValue('#favName'); await p.click('#favOk');
  await p.waitForFunction("window.__basket.state().favorites.length>0&&!document.querySelector('#favPop #favName')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1200); return {nm,c};};
async function favSteps(b){
  const p=await favPage(b);
  const s0=await fst(p);
  ok('[избранное] на старте пусто, в расчёте 0',s0.n===0&&s0.eligible===0,JSON.stringify(s0));
  await openWin(p,0);
  const {nm:n1,c:c1}=await saveHeart(p), s1=await fst(p);
  ok('[избранное] имя по комнате «Гостиная #1»; поле имени в фокусе, каретка в конце',n1==='Гостиная #1'&&caretOk(c1),n1+' '+JSON.stringify(c1));
  ok('[избранное] первый вариант комнаты — включён сам',s1.n===1&&Object.keys(s1.inc).length===1&&s1.eligible>0,JSON.stringify({inc:s1.inc,eligible:s1.eligible}));
  ok('[избранное] сообщение ««Гостиная #1»: в избранном, включено в сертификат, остаток N · Перейти →»',/Гостиная.#1»: в избранном, включено в сертификат, остаток [\d\s  ]+₽/.test(s1.toast)&&/Перейти/.test(s1.toast),s1.toast);
  await p.evaluate(()=>{const a=document.querySelector('#toast .toastact'); if(a&&!document.getElementById('toast').hidden)a.click(); else histGoFavs('living');}); await p.waitForTimeout(900);
  const atFav=await favScr(p);
  ok('[избранное] «Перейти →» — экран «Избранное» с «← Назад», окно закрыто, адрес #fav',!atFav.win&&atFav.fav&&atFav.back&&atFav.view==='favorites'&&atFav.hash==='#fav'&&!atFav.sec,JSON.stringify(atFav));
  await p.screenshot({path:OUT+W+'-fav-1-screen.png'});
  await p.click('#favBack'); await p.waitForTimeout(2500);
  const back=await favScr(p);
  ok('[избранное] «← Назад» — снова окно',back.win&&!back.fav,JSON.stringify(back));
  await openWin(p,1);
  await heart(p); await p.waitForSelector('#favName'); const n2=await p.inputValue('#favName'); await p.click('#favOk');
  await p.waitForFunction("/вместо/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
  const ask=await fst(p);
  ok('[избранное] второй вариант — «Гостиная #2» и вопрос «в сертификат вместо «Гостиная #1»?»',n2==='Гостиная #2'&&/в сертификат вместо «Гостиная #1»\?/.test(ask.pop),n2+' | '+ask.pop.replace(/\n/g,' '));
  const fav2=await p.evaluate(()=>window.__basket.state().favorites.find(f=>f.displayName==='Гостиная #2').favoriteId);
  await p.click('#favPop button.primary'); await p.waitForTimeout(800);
  const s2=await fst(p);
  ok('[избранное] «Да» — в расчёте второй вариант',s2.inc.living===fav2&&s2.eligible!==s1.eligible,JSON.stringify({inc:s2.inc,was:s1.eligible,now:s2.eligible}));
  ok('[избранное] без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
  await p.context().close();
  // не влезает при включении: пакет 100 000 → диалог «Доплата N. Подтвердить?» (N = сумма − лимит), до ответа не включено
  const q=await favPage(b,{limit:100000});
  await openWin(q,0);
  await heart(q); await q.waitForSelector('#favName'); await q.click('#favOk');
  await q.waitForFunction("/Доплата .*\\. Подтвердить\\?/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
  const s7=await fst(q), sum7=await q.evaluate(()=>{const f=window.__basket.state().favorites[0]; return f?f.quote.lines.filter(x=>x.settlement==='allowance').reduce((a,x)=>a+(x.amount||0),0):-1;});
  const over=Number((s7.pop.match(/Доплата ([\d\s  ]+)₽/)||[])[1]?.replace(/\D/g,''));
  ok('[избранное] не влезает — диалог «Доплата N ₽. Подтвердить?», N = сумма − лимит, до ответа не включено',s7.n===1&&!Object.keys(s7.inc).length&&over===sum7-100000,JSON.stringify({n:s7.n,inc:s7.inc,over,sum7}));
  await q.screenshot({path:OUT+W+'-fav-2-over.png'});
  await q.context().close();
}
