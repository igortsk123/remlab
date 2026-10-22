const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КОРЗИНА СЕРТИФИКАТА (план demo-16 шаг 2, «Решения владельца 18.10»): 0 на старте; первый вариант комнаты включается сам; второй — вопрос
// «вместо «Гостиная #1»? Да/Нет»; в избранном — группы по комнатам и переключатель «Включить в сертификат» с пересчётом шкалы; окно —
// та же шкала, что на главной (demo-19 Б2, demo-20 А6: «Выбрано N … сертификат M», светлая часть — эта расстановка); не влезает — в избранное,
// диалог «Доплата N — подтвердить?» с «Подтвердить» / «Изменить расстановку»; без подтверждения не включается (demo-23, ADR-0308)
// (лимит подменяется ответом карточки квартиры, страница не трогается); перенос избранного demo-15. Избранное — отдельный экран
// `#screen-fav` с «← Назад» туда, откуда пришли; поле имени — фокус и каретка в конце сразу после тапа по ♡ (demo-17). Платного пути нет.
//   BASE=https://remont-lab.online/test/share/demo-stage/ OUT=~/scout-scenes/<сессия>/ node tools/ops/demo-walk/basket-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').homedir()+'/scout-scenes/basket-check/').replace(/\/?$/,'/');
fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
async function page(b,o={}){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:PHONE?2:1,isMobile:PHONE,hasTouch:PHONE,locale:o.lang==='en'?'en-GB':'ru-RU'});
  await ctx.grantPermissions(['clipboard-read','clipboard-write'],{origin:'https://remont-lab.online'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:30})}));
  // лимит — пакетом одной суммы (demo-23: страница берёт политику `incentive`, сумма сертификата — её итог)
  if(o.limit)await p.route(/\/api\/apartments\//,async r=>{const res=await r.fetch(); const j=await res.json(); if(j.card&&j.card.certificate)j.card.certificate.amount=o.limit;
    if(j.card&&j.card.incentive)j.card.incentive={...j.card.incentive,mode:'pooled',limits:{furniture:o.limit,fitout:0},total:o.limit};
    await r.fulfill({response:res,body:JSON.stringify(j),headers:{...res.headers(),'content-type':'application/json'}});});
  if(o.embed)await ctx.addInitScript(()=>{window.__EMBED={partner:'demo',flat:'flat215',lang:'ru'}; window.__sendFlat='flat215';});   // как `lib/embed/page.ts`
  if(o.seed)await ctx.addInitScript(s=>{try{if(!sessionStorage.getItem('seeded')){localStorage.clear(); Object.entries(s).forEach(([k,v])=>localStorage.setItem(k,v)); sessionStorage.setItem('seeded','1');}}catch(e){}},o.seed);
  await p.goto(BASE+(o.lang==='en'?'?lang=en&':'?')+'live=force',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!!(window.__basket&&window.__basket.state())",null,{timeout:90000});
  if(!o.seed)await p.evaluate(()=>{Object.keys(localStorage).filter(k=>/^remlab-(basket|favorites|collections|fav-thumbs)/.test(k)).forEach(k=>localStorage.removeItem(k)); location.reload();});
  if(!o.seed)await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!!(window.__basket&&window.__basket.state())",null,{timeout:90000});
  await p.waitForTimeout(800);
  return p;
}
const openWin=async(p,i)=>{await p.evaluate(i=>{pickVariant(i); VW.collapse=true; vwOpenVariant(i); if(VW.mode!=='walk')vwMode('walk');},i);
  await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1200);};
const st=p=>p.evaluate(()=>{const b=window.__basket.state(), t=window.__basket.totals();
  return {n:b.favorites.length, inc:b.includedByRoom, names:b.favorites.map(f=>f.displayName), eligible:t.allowanceEligible, complete:t.allowanceComplete,
    cert:+document.getElementById('hmCert').dataset.included, toast:(document.getElementById('toast')||{}).textContent||'', pop:(document.getElementById('favPop')||{}).innerText||''};});
// фокус в том же тапе (iOS открывает клавиатуру только так): сразу после клика — поле имени активно, каретка в конце, без выделения
const caret=p=>p.evaluate(()=>{const i=document.getElementById('favName'), a=document.activeElement;
  return {focus:!!i&&a===i, start:i?i.selectionStart:-1, end:i?i.selectionEnd:-1, len:i?i.value.length:-1};});
const caretOk=c=>c.focus&&c.start===c.len&&c.end===c.len&&c.len>0;
const favScr=p=>p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), fav:!document.getElementById('screen-fav').hidden,
  home:!document.getElementById('screen-room').hidden, view:(history.state||{}).view, hash:location.hash, len:history.length, y:Math.round(scrollY),
  back:!!document.getElementById('favBack').offsetParent, sec:!!document.getElementById('favSec')}));
let CARET=null;
const saveHeart=async(p)=>{await p.click('#vFav'); CARET=await caret(p); await p.waitForSelector('#favName'); const nm=await p.inputValue('#favName'); await p.click('#favOk');
  await p.waitForFunction("window.__basket.state().favorites.length>0&&!document.querySelector('#favPop #favName')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1200); return nm;};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const p=await page(b);
    const s0=await st(p);
    ok('0 на старте: в избранном пусто, включено 0, строки «Избранное» нет',s0.n===0&&s0.eligible===0&&s0.cert===0&&await p.evaluate(()=>document.getElementById('favHead').hidden),JSON.stringify(s0));
    // 1) первый вариант гостиной — включается сам
    await p.evaluate(i=>{pickVariant(i); VW.collapse=true; vwOpenVariant(i); if(VW.mode!=='walk')vwMode('walk');},0);
    if(PHONE){
      const tip=await p.waitForFunction(()=>{const t=document.querySelector('#shot .vtip'); if(!t)return null;
        const c=document.getElementById('vCams'), tr=t.getBoundingClientRect(), cr=c.getBoundingClientRect();
        return {mode:t.dataset.mode, live:t.dataset.live, busy:t.dataset.busy, ready:LIVE.state==='ready', loading:document.getElementById('vload').classList.contains('on'), tipBottom:Math.round(tr.bottom), camsTop:Math.round(cr.top)};},null,{timeout:40000,polling:100})
        .then(h=>h.jsonValue(),()=>null);
      // в «Фото» сцены ждать нечего — подсказка сразу; в 3D — только после загрузки моделей
      // состояние — на момент показа (записано страницей): позже проверка видит уже следующий кадр
      ok('подсказка шторки — не во время загрузки (нет крутилки; в 3D — сцена готова) и над переключателем ракурсов',!!tip&&tip.busy==='false'&&(tip.mode!=='walk'||tip.live==='ready')&&tip.tipBottom<=tip.camsTop,JSON.stringify(tip));
    }
    await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1200);
    const plate0=await p.evaluate(()=>{const row=document.querySelector('#vsum .cs-t'), pl=document.getElementById('vsum').getBoundingClientRect(), last=row.lastElementChild.getBoundingClientRect();
      return {head:row.querySelector('.cs-l').textContent, pv:(document.querySelector('#vsum .cs-bar i.pv')||{}).style?.width, sum:+document.getElementById('vsum').dataset.sum,
        fits:row.scrollWidth<=row.clientWidth+1&&last.right<=pl.right+1&&row.querySelector('.cs-l').scrollWidth<=row.querySelector('.cs-l').clientWidth+1};});
    ok('плашка окна — в одну строку, не вылезает',plate0.fits,JSON.stringify(plate0));
    ok('окно до добавления: «Выбрано 0», светлая часть полосы — эта расстановка',/^Выбрано 0\s₽$/.test(plate0.head.trim())&&parseFloat(plate0.pv)>0,JSON.stringify(plate0));
    await p.screenshot({path:OUT+W+'-1-plate.png'});
    const n1=await saveHeart(p);
    const s1=await st(p);
    ok('имя по комнате «Гостиная #1»',n1==='Гостиная #1',n1);
    ok('тап по ♡ — поле имени в фокусе сразу, каретка в конце, текст не выделен',caretOk(CARET),JSON.stringify(CARET));
    ok('первый вариант комнаты — включён сам, шкала пересчитана',s1.n===1&&Object.keys(s1.inc).length===1&&s1.eligible>0&&s1.cert===s1.eligible,JSON.stringify({inc:s1.inc,eligible:s1.eligible,cert:s1.cert}));
    ok('сообщение ««Гостиная #1» — в избранном, включено в сертификат, остаток N · Перейти →»',/Гостиная.#1» — в избранном, включено в сертификат, остаток [\d\s ]+₽/.test(s1.toast)&&/Перейти/.test(s1.toast),s1.toast);
    const plate1=await p.evaluate(()=>document.querySelector('#vsum .cs-l').textContent);
    ok('после включения шкала окна — «Выбрано» по корзине',/^Выбрано [1-9]/.test(plate1.trim()),plate1);
    // 1б) «Перейти →» и «назад» (шаг 3): из окна (ракурс 2, шторка приподнята) — в избранное; «назад» — то же окно в том же виде; «вперёд» — снова избранное
    await p.evaluate(()=>{vwCamGo(1); if(VW_PHONE())vwSheet(1);}); await p.waitForTimeout(700);
    const before=await p.evaluate(()=>({vid:(allVariants()[cur]||{}).id, photo:VW.photo, sheet:+document.getElementById('vside').dataset.pos, mode:VW.mode}));
    await p.evaluate(()=>{const a=document.querySelector('#toast .toastact'); if(a&&!document.getElementById('toast').hidden)a.click(); else window.__fav&&histGoFavs('living');});
    await p.waitForTimeout(900);
    const atFav=await favScr(p);
    ok('«Перейти →» — экран «Избранное» с «← Назад», окно закрыто, адрес #fav (новая запись истории); раскрывающейся секции нет',
      !atFav.win&&atFav.fav&&!atFav.home&&atFav.back&&atFav.view==='favorites'&&atFav.hash==='#fav'&&!atFav.sec,JSON.stringify(atFav));
    await p.screenshot({path:OUT+W+'-1a-fav-screen.png'});
    const winNow=()=>p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), fav:!document.getElementById('screen-fav').hidden, vid:(allVariants()[cur]||{}).id, photo:VW.photo, sheet:+document.getElementById('vside').dataset.pos, mode:VW.mode, view:(history.state||{}).view}));
    const same=b=>b.win&&!b.fav&&b.vid===before.vid&&b.photo===before.photo&&b.mode===before.mode&&(!PHONE||b.sheet===before.sheet);
    await p.click('#favBack'); await p.waitForTimeout(2500);
    const back=await winNow();
    ok('«← Назад» экрана — то же окно: вариант, режим, ракурс, шторка',same(back),JSON.stringify({before,back}));
    await p.screenshot({path:OUT+W+'-1b-back.png'});
    await p.goForward(); await p.waitForTimeout(1200);
    const fwd=await favScr(p);
    ok('«вперёд» браузера — снова экран избранного',!fwd.win&&fwd.fav,JSON.stringify(fwd));
    await p.goBack(); await p.waitForTimeout(2500);
    const back2=await winNow();
    ok('«назад» браузера с экрана — то же окно',same(back2),JSON.stringify(back2));
    await p.goForward(); await p.waitForTimeout(1200);
    // перезагрузка на записи «избранное» — избранное, а не окно варианта; ♡ N в той же записи — без новой записи истории (Codex 18.10)
    await p.reload({waitUntil:'load'}); await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!!(window.__basket&&window.__basket.state())",null,{timeout:90000}); await p.waitForTimeout(2000);
    const rl=await favScr(p);
    ok('перезагрузка на #fav — экран избранного, окно не открыто',!rl.win&&rl.fav&&rl.view==='favorites'&&rl.hash==='#fav',JSON.stringify(rl));
    await p.click('#hmFav'); await p.waitForTimeout(400);
    ok('♡ N в записи «избранное» — новой записи истории нет',await p.evaluate(()=>history.length)===rl.len);
    await p.click('#favBack'); await p.waitForTimeout(800);
    const rlb=await favScr(p);
    ok('после перезагрузки «← Назад» — главная',rlb.home&&!rlb.fav&&!rlb.win&&rlb.view==='home',JSON.stringify(rlb));
    // 2) второй вариант той же комнаты — вопрос «вместо …?» → Да
    await openWin(p,1);
    await p.click('#vFav'); await p.waitForSelector('#favName'); const n2=await p.inputValue('#favName'); await p.click('#favOk');
    await p.waitForFunction("/вместо/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
    const ask=await st(p);
    ok('второй вариант гостиной — «Гостиная #2» и вопрос «в сертификат вместо «Гостиная #1»? ±N» (demo-20 А6)',n2==='Гостиная #2'&&/в сертификат вместо «Гостиная #1»\?( [+−][\d\s ]+₽)?/.test(ask.pop),n2+' | '+ask.pop.replace(/\n/g,' '));
    await p.screenshot({path:OUT+W+'-2-ask.png'});
    const fav2=await p.evaluate(()=>window.__basket.state().favorites.find(f=>f.displayName==='Гостиная #2').favoriteId);
    await p.click('#favPop button.primary'); await p.waitForTimeout(800);
    const s2=await st(p);
    ok('«Да» — в расчёте второй вариант, сумма из его состава',s2.inc.living===fav2&&s2.cert===s2.eligible&&s2.eligible!==s1.eligible,JSON.stringify({inc:s2.inc,was:s1.eligible,now:s2.eligible}));
    // 3) третий — «Нет»: только в избранное
    await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(400);
    await openWin(p,2);
    await p.click('#vFav'); await p.waitForSelector('#favName'); await p.click('#favOk');
    await p.waitForFunction("/вместо/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
    await p.click('#favPop button.ghost'); await p.waitForTimeout(600);
    const s3=await st(p);
    ok('«Нет» — в избранном три гостиные, в расчёте по-прежнему вторая',s3.n===3&&s3.inc.living===fav2,JSON.stringify({n:s3.n,inc:s3.inc}));
    // 4) «Перейти →» из тоста — окно закрыто, экран «Избранное» на гостиных
    const from4=await p.evaluate(()=>(allVariants()[cur]||{}).id);
    await p.evaluate(()=>{const a=document.querySelector('#toast .toastact'); if(a&&!document.getElementById('toast').hidden)a.click(); else histGoFavs('living');}); await p.waitForTimeout(900);
    const sec=await p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), open:!document.getElementById('screen-fav').hidden,
      chips:[...document.querySelectorAll('#favChips [data-froom]')].map(x=>x.textContent), cards:document.querySelectorAll('#favGrid .favcard').length,
      checked:[...document.querySelectorAll('#favGrid [data-finc]')].filter(x=>x.checked).map(x=>x.dataset.finc)}));
    ok('«Перейти →» — окно закрыто, экран избранного: «Гостиная · 3», три карточки, отмечена одна',!sec.win&&sec.open&&sec.chips.join()==='Гостиная · 3'&&sec.cards===3&&sec.checked.length===1&&sec.checked[0]===fav2,JSON.stringify(sec));
    const lay=await p.evaluate(()=>{const s=document.getElementById('screen-fav').getBoundingClientRect(), w=document.querySelector('.wrap'), cs=getComputedStyle(w),
      col=w.getBoundingClientRect().width-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight), cards=[...document.querySelectorAll('#favGrid .favcard')].map(c=>c.getBoundingClientRect());
      return {w:Math.round(s.width), col:Math.round(col), hScroll:document.documentElement.scrollWidth>innerWidth, out:cards.filter(r=>r.left<s.left-1||r.right>s.right+1).length,
        perRow:cards.filter(r=>Math.abs(r.top-cards[0].top)<2).length, tabs:!document.getElementById('styleTabs').hidden, top:!!document.getElementById('flatPrice').offsetParent};});
    ok('экран на ширину колонки, карточки внутри, без горизонтальной прокрутки; вкладок стилей и строки ЖК нет'+(PHONE?', на телефоне — одна карточка в ряд':''),
      Math.abs(lay.w-lay.col)<=2&&!lay.out&&!lay.hScroll&&!lay.tabs&&!lay.top&&(!PHONE||lay.perRow===1),JSON.stringify(lay));
    await p.screenshot({path:OUT+W+'-3-favs.png'});
    // 4б) «Открыть» с карточки — окно; «назад» браузера — снова экран избранного; закрыли «×» — экран избранного, «← Назад» — туда, откуда пришли
    await p.click('#favGrid .favcard .acts [data-fopen]'); await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1200);
    await p.goBack(); await p.waitForTimeout(1500);
    const ob=await favScr(p);
    ok('«Открыть» с карточки → окно; «назад» браузера → экран избранного',!ob.win&&ob.fav&&ob.view==='favorites',JSON.stringify(ob));
    await p.click('#favGrid .favcard .acts [data-fopen]'); await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1200);
    await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(900);
    const ox=await favScr(p);
    ok('окно с карточки закрыли «×» — под ним экран избранного',!ox.win&&ox.fav&&ox.view==='favorites',JSON.stringify(ox));
    // 5) переключить «Включить в сертификат» на первый вариант → пересчёт
    const fav1=await p.evaluate(()=>window.__basket.state().favorites.find(f=>f.displayName==='Гостиная #1').favoriteId);
    await p.click(`#favGrid [data-finc="${fav1}"]`); await p.waitForTimeout(700);
    const s5=await st(p);
    ok('переключатель в избранном: включён первый, шкала — снова его сумма',s5.inc.living===fav1&&s5.cert===s1.eligible,JSON.stringify({inc:s5.inc,cert:s5.cert,first:s1.eligible}));
    // 6) убрать включённый — включается старейший оставшийся (второй), если влезает
    await p.evaluate(id=>window.__fav.remove(id),fav1); await p.waitForTimeout(600);
    const s6=await st(p);
    ok('убрали включённый — включён старейший оставшийся',s6.n===2&&s6.inc.living===fav2,JSON.stringify({n:s6.n,inc:s6.inc}));
    await p.evaluate(()=>window.__basket.open('living')); await p.waitForTimeout(400);
    await p.click(`#favGrid [data-fmore="${fav2}"]`); await p.waitForSelector('#favExcl');
    await p.click('#favExcl'); await p.waitForTimeout(700);
    const s6b=await st(p);
    ok('«⋯ → Не включать в сертификат» — комната вне расчёта, шкала 0, вариант в избранном',!Object.keys(s6b.inc).length&&s6b.cert===0&&s6b.n===2,JSON.stringify({inc:s6b.inc,cert:s6b.cert,n:s6b.n}));
    await p.click(`#favGrid [data-finc="${fav2}"]`); await p.waitForTimeout(700);
    const s6c=await st(p);
    ok('включить снова — переключателем, шкала вернулась',s6c.inc.living===fav2&&s6c.cert===s2.eligible,JSON.stringify({inc:s6c.inc,cert:s6c.cert}));
    await p.click('#favBack'); await p.waitForTimeout(2500);
    const ob2=await p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), fav:!document.getElementById('screen-fav').hidden, vid:(allVariants()[cur]||{}).id}));
    ok('«← Назад» после окна с карточки — окно, из которого пришли в избранное',ob2.win&&!ob2.fav&&ob2.vid===from4,JSON.stringify({ob2,from4}));
    ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
    await p.context().close();
    if(PHONE){   // окно сразу в 3D (вариант без реалистичного фото): подсказка ждёт модели
      const t3=await page(b);
      // как расстановка, которую уже меняли (реалистичного фото этого состояния нет): окно открывается сразу в 3D
      await t3.evaluate(()=>{window.vwRealShots=vwRealShots=()=>[];}); const k=0;
      if(k>=0){const m3=await t3.evaluate(i=>{window.vwRealShots=vwRealShots=()=>[]; pickVariant(i); VW.collapse=true; vwOpenVariant(i); return VW.mode;},k);
        console.log('режим окна при открытии:',m3);
        const tp=await t3.waitForFunction(()=>{const t=document.querySelector('#shot .vtip'); if(!t)return null; const cr=document.getElementById('vCams').getBoundingClientRect();
          return {mode:t.dataset.mode, live:t.dataset.live, busy:t.dataset.busy, ready:LIVE.state==='ready', loading:document.getElementById('vload').classList.contains('on'), tipBottom:Math.round(t.getBoundingClientRect().bottom), camsTop:Math.round(cr.top)};},null,{timeout:60000,polling:100}).then(h=>h.jsonValue(),()=>null);
        ok('окно сразу в 3D: подсказка — только после загрузки (нет крутилки) и над переключателем',!!tp&&tp.busy==='false'&&(tp.mode!=='walk'||tp.live==='ready')&&tp.tipBottom<=tp.camsTop,JSON.stringify(tp));}
      else ok('окно сразу в 3D: нет варианта без реалистичного фото — проверить нечем',true,'пропуск');
      await t3.context().close();
    }
    // 7) не влезает: пакет 100 000 → в избранное, диалог «Доплата N — подтвердить?» (N = сумма − лимит); без «Подтвердить» не включено;
    //    «Изменить расстановку» — остаёмся в окне этой расстановки (demo-23, ADR-0308; было — отказ «больше остатка», demo-19 Б4)
    const q=await page(b,{limit:100000});
    await openWin(q,0);
    await q.click('#vFav'); await q.waitForSelector('#favName'); await q.click('#favOk');
    await q.waitForFunction("/Доплата .* — подтвердить\\?/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
    const s7=await st(q), sum7=await q.evaluate(()=>{const f=window.__basket.state().favorites[0]; return f?f.quote.lines.filter(x=>x.settlement==='allowance').reduce((a,x)=>a+(x.amount||0),0):-1;});
    const over=Number((s7.pop.match(/Доплата ([\d\s  ]+)₽/)||[])[1]?.replace(/\D/g,''));
    const btns=await q.evaluate(()=>[...document.querySelectorAll('#favPop button')].map(x=>x.textContent));
    ok('не влезает — в избранном, диалог «Доплата N ₽ — подтвердить?» (N = сумма − лимит), «Подтвердить» / «Изменить расстановку», до ответа не включено',
      s7.n===1&&!Object.keys(s7.inc).length&&over===sum7-100000&&btns.join('|')==='Подтвердить|Изменить расстановку',JSON.stringify({n:s7.n,inc:s7.inc,over,sum7,pop:s7.pop,btns}));
    const plateOver=await q.evaluate(()=>{const sp=document.querySelector('#vsum .cs-l'); return {head:sp.textContent, over:!!document.querySelector('#vsum .cs.over'), cut:sp.scrollWidth>sp.clientWidth+1};});
    ok('шкала при превышении — красная светлая часть, подпись не обрезана',plateOver.over&&!plateOver.cut,JSON.stringify(plateOver));
    await q.screenshot({path:OUT+W+'-4-over.png'});
    await q.locator('#favPop button',{hasText:'Изменить расстановку'}).click(); await q.waitForTimeout(700);
    ok('«Изменить расстановку» — остаёмся в окне этой расстановки, корзина без изменений',await q.evaluate(()=>document.getElementById('shot').classList.contains('on')&&!Object.keys(window.__basket.state().includedByRoom).length));
    ok('без ошибок страницы (лимит)',!q.errs.length,q.errs.slice(0,2).join(' | '));
    const cid=await q.evaluate(()=>window.__basket.state().favorites[0].favoriteId);
    await q.context().close();
    // 8) перенос demo-15: старая запись «Сканди #3» той же коллекции → «Гостиная #1», не включена
    const m=await page(b,{seed:{'remlab-favorites':JSON.stringify([{collectionId:cid,editToken:null,displayName:'Сканди #3',style:'сканди',stateId:'',sourceVariantId:'set1',createdAt:Date.now()-1000,shot:''}])}});
    await m.waitForFunction("window.__basket.state().favorites.length>0",null,{timeout:30000}).catch(()=>{});
    const s8=await st(m);
    ok('перенос избранного demo-15: «Сканди #3» → «Гостиная #1», в сертификат не включён',s8.n===1&&s8.names[0]==='Гостиная #1'&&!Object.keys(s8.inc).length,JSON.stringify({n:s8.n,names:s8.names,inc:s8.inc}));
    ok('без ошибок страницы (перенос)',!m.errs.length,m.errs.slice(0,2).join(' | '));
    await m.context().close();
    // 9) EN: тексты корзины без кириллицы
    const e=await page(b,{lang:'en'}); await openWin(e,0);
    const en1=await e.evaluate(()=>document.querySelector('#vsum').innerText);
    await e.click('#vFav'); await e.waitForSelector('#favName'); const ce=await caret(e); await e.click('#favOk'); await e.waitForTimeout(1500);
    ok('EN: поле имени — фокус и каретка в конце',caretOk(ce),JSON.stringify(ce));
    const en2=await e.evaluate(()=>[(document.getElementById('toast')||{}).textContent||'',(document.getElementById('favPop')||{}).innerText||''].join(' '));
    await e.evaluate(()=>histGoFavs('living')); await e.waitForTimeout(800);
    const en3=await e.evaluate(()=>['favHead','screen-fav','hmCert'].map(id=>document.getElementById(id).innerText).join(' '));
    await e.screenshot({path:OUT+W+'-5-en-fav.png'});
    const cyr=(en1+' '+en2+' '+en3).match(/[А-Яа-яЁё]+/g)||[];
    ok('EN: плашка окна, сообщения и экран «Избранное» без кириллицы',!cyr.length&&/Favourites/.test(en3)&&/Back/.test(en3),cyr.slice(0,5).join(' ')+' | '+en1.slice(0,60)+' | '+en2.slice(0,80));
    await e.context().close();
    // 10) встройка (как `/embed/…`: `window.__EMBED` до скриптов страницы) — экран открывается и закрывается без записей истории и смены адреса
    const m2=await page(b,{embed:true}); await openWin(m2,0); await saveHeart(m2);
    const eb0=await m2.evaluate(()=>({len:history.length, url:location.href}));
    await m2.evaluate(()=>histGoFavs('living')); await m2.waitForTimeout(800);
    const eb1=await favScr(m2);
    await m2.click('#favBack'); await m2.waitForTimeout(800);
    const eb2=await favScr(m2), eb3=await m2.evaluate(()=>location.href);
    ok('встройка: экран избранного открывается и «← Назад» — главная, без записей истории и смены адреса',
      !eb1.win&&eb1.fav&&eb2.home&&!eb2.fav&&eb1.len===eb0.len&&eb2.len===eb0.len&&eb3===eb0.url,JSON.stringify({eb0,eb1:{fav:eb1.fav,len:eb1.len},eb2:{home:eb2.home,len:eb2.len},eb3}));
    ok('без ошибок страницы (встройка)',!m2.errs.length,m2.errs.slice(0,2).join(' | '));
    await m2.context().close();
  }catch(e){R.push('FAIL проверка прервалась — '+String(e.message||e).split('\n').slice(0,14).join(' | '));
    try{for(const c of b.contexts())for(const pg of c.pages())await pg.screenshot({path:OUT+W+'-fail-'+Date.now()+'.png'});}catch(_){}}
  finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · снимки ${OUT}${W}-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
