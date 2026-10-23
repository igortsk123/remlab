const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КАРТОЧКА ТОВАРА (demo-26 Д, снимок владельца 23.10): тап по названию или миниатюре строки окна варианта — карточка: полное название,
// роль, магазин, цена, размеры, «Заменить» и «В магазин», плитка сразу и крупная копия поверх (`img/<id>-l.jpg` при `_img_large`).
// Закрывают «×», тап мимо, «назад» браузера (окно под карточкой остаётся), свайп вниз (телефон), Esc (компьютер). «Заменить» карточки —
// лист замен; в ленте замен фото — карточка, её «Заменить» — замена; остальная карточка ленты меняет товар, как раньше; тап по строке
// мимо названия и фото карточку не открывает. Платного нет, на сервер ничего не пишется.
//   BASE=http://127.0.0.1:8790/demo/ OUT=<папка/> [V=2] [TAG=after] node tools/ops/demo-walk/item-card-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').tmpdir()+'/').replace(/\/?$/,'/');
const V=+(process.env.V||2), TAG=process.env.TAG||'run'; fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i===undefined?'':' '+(typeof i==='string'?i:JSON.stringify(i))));
const CARD=`(()=>{const c=document.getElementById('itemCard'); if(!c||!c.classList.contains('on'))return null; const q=s=>c.querySelector(s), b=q('.ic-box').getBoundingClientRect();
  const nm=q('.ic-nm'), s=q('.ic-s'), l=q('.ic-l');
  return {name:nm.innerText, nameCut:nm.scrollHeight>nm.clientHeight+1||nm.scrollWidth>nm.clientWidth+1, meta:[...c.querySelectorAll('.ic-meta')].map(e=>e.innerText),
    price:q('.ic-pr').innerText, btns:[...c.querySelectorAll('.ic-acts .btn')].map(e=>e.innerText), shop:(q('.ic-acts a')||{}).href||'',
    small:!!s&&s.complete&&s.naturalWidth>0, smallW:s?s.naturalWidth:0, big:!!l&&l.classList.contains('ld'), bigW:l?l.naturalWidth:0, bigSrc:l?l.getAttribute('src'):'',
    box:[b.left,b.top,b.right,b.bottom].map(Math.round), inView:b.left>=0&&b.right<=innerWidth+0.5&&b.top>=0&&b.bottom<=innerHeight+0.5,
    win:document.getElementById('shot').classList.contains('on'), hist:!!(history.state&&history.state.icard)};})()`;
const WIN=`({win:document.getElementById('shot').classList.contains('on'), card:!!document.querySelector('#itemCard.on'), cur:typeof cur!=='undefined'?cur:null,
  hist:!!(history.state&&history.state.icard), sheet:document.getElementById('sheet').classList.contains('open')})`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errs=[];
  for(const lang of ['ru','en']){
    const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:lang==='en'?'en-GB':'ru-RU'});
    const p=await ctx.newPage(); p.on('pageerror',e=>errs.push(lang+': '+String(e)));
    await p.addInitScript(()=>{try{localStorage.setItem('remlab-sheet-hint-v1','1')}catch(e){}});
    await p.goto(BASE+'?lang='+lang+'&live=0',{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(1500);
    await p.evaluate(v=>vwOpenVariant(v),V);
    await p.waitForFunction(()=>document.querySelectorAll('#shotbody .pinlist .row').length>2,null,{timeout:60000}); await p.waitForTimeout(1200);
    await p.evaluate(()=>{const x=[...document.querySelectorAll('#shot button')].find(e=>/Мебель и|Furniture/.test(e.innerText)); if(x)x.click();}); await p.waitForTimeout(1200);
    const shot=async n=>{for(let i=0;i<4;i++){try{await p.screenshot({path:`${OUT}${TAG}-${W}-${lang}-${n}.png`,timeout:20000,animations:'disabled'});return;}catch(e){await p.waitForTimeout(1500);}}};
    const row=k=>`#shotbody .pinlist .row[data-k="${k}"]`, cur0=(await p.evaluate(WIN)).cur;
    const full=await p.evaluate(()=>shotRows[0].name), wait=()=>p.waitForTimeout(500);
    const tap=async sel=>{await p.locator(sel).first().scrollIntoViewIfNeeded(); if(PHONE)await p.locator(sel).first().tap(); else await p.locator(sel).first().click();};
    // 1. название — карточка; полное название без обрезки; роль, магазин, размеры, цена, две кнопки; плитка сразу, крупная — следом
    await tap(row(0)+' .t b'); await p.waitForTimeout(150);
    const c0=await p.evaluate(CARD);
    ok(`${lang}: тап по названию — карточка, плитка уже показана`,!!c0&&c0.small,c0&&{small:c0.small,smallW:c0.smallW});
    await p.waitForFunction(()=>{const l=document.querySelector('#itemCard .ic-l'); return !l||l.classList.contains('ld');},null,{timeout:15000}).catch(()=>{});
    await p.waitForTimeout(350);   // подъём листа — 0,2 с
    const c1=await p.evaluate(CARD);
    ok(`${lang}: полное название без обрезки`,!!c1&&c1.name===full&&!c1.nameCut,c1&&c1.name);
    ok(`${lang}: роль · магазин, размеры, цена; «Заменить» и «В магазин»`,!!c1&&c1.meta.length===2&&/×/.test(c1.meta[1])&&/\d/.test(c1.price)&&c1.btns.length===2&&/^https?:/.test(c1.shop),c1&&{meta:c1.meta,price:c1.price,btns:c1.btns});
    ok(`${lang}: крупное фото проявилось поверх плитки (шире 400 px)`,!!c1&&c1.big&&c1.bigW>400,c1&&{big:c1.big,bigW:c1.bigW,src:c1.bigSrc});
    ok(`${lang}: карточка целиком на экране, окно под ней, своя запись истории`,!!c1&&c1.inView&&c1.win&&c1.hist,c1&&{box:c1.box,win:c1.win,hist:c1.hist});
    await shot('card');
    // 2. «×» — закрыта, окно и вариант те же, записи карточки нет
    await p.locator('#itemCard .ic-x').click(); await wait();
    let w=await p.evaluate(WIN); ok(`${lang}: «×» — закрыта, окно и вариант те же`,!w.card&&w.win&&w.cur===cur0&&!w.hist,w);
    // 3. миниатюра — карточка; тап мимо — закрыта
    await tap(row(1)+' img'); await wait();
    ok(`${lang}: тап по миниатюре — карточка`,!!(await p.evaluate(CARD)));
    if(PHONE)await p.touchscreen.tap(W/2,12); else await p.mouse.click(12,12);
    await wait(); w=await p.evaluate(WIN); ok(`${lang}: тап мимо — закрыта, окно на месте`,!w.card&&w.win&&!w.hist,w);
    // 4. «назад» браузера — закрывает карточку, а не окно
    await tap(row(0)+' .t b'); await wait();
    await p.goBack(); await p.waitForTimeout(900);
    w=await p.evaluate(WIN); ok(`${lang}: «назад» браузера — карточка закрыта, окно и вариант на месте`,!w.card&&w.win&&w.cur===cur0,w);
    // 5. свайп вниз (телефон) / Esc (компьютер)
    await tap(row(0)+' .t b'); await wait();
    if(PHONE){const cdp=await ctx.newCDPSession(p), x=W/2, y0=Math.round(H*0.62);
      await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y:y0}]});
      for(let i=1;i<=8;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y0+i*20}]}); await p.waitForTimeout(16);}
      await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await p.waitForTimeout(700);
      w=await p.evaluate(WIN); ok(`${lang}: свайп вниз — закрыта, окно на месте`,!w.card&&w.win&&!w.hist,w);}
    else{await p.keyboard.press('Escape'); await wait(); w=await p.evaluate(WIN); ok(`${lang}: Esc — закрыта карточка, окно не закрылось`,!w.card&&w.win&&!w.hist,w);}
    // 6. тап по строке мимо названия и фото — карточки нет
    await tap(row(0)+' .t span'); await wait();
    ok(`${lang}: тап по строке мимо названия и фото — карточки нет`,!(await p.evaluate(WIN)).card);
    // 7. декор (последняя строка): карточка открывается и без крупной копии (адрес магазина) — плитка
    const last=await p.evaluate(()=>document.querySelectorAll('#shotbody .pinlist .row').length-1);
    await tap(row(last)+' .t b'); await p.waitForTimeout(900);
    const cd=await p.evaluate(CARD); ok(`${lang}: последняя строка (декор) — карточка, фото есть`,!!cd&&cd.small,cd&&{name:cd.name,small:cd.small,big:cd.big});
    await shot('card-decor'); await p.locator('#itemCard .ic-x').click(); await wait();
    // 8. «Заменить» карточки — лист замен; в ленте фото — карточка, её «Заменить» — замена
    await tap(row(0)+' .t b'); await wait();
    await p.locator('#itemCard .ic-sw').click(); await p.waitForTimeout(900);
    w=await p.evaluate(WIN); ok(`${lang}: «Заменить» карточки — карточка закрыта, лист замен открыт`,!w.card&&w.sheet&&!w.hist,w);
    await p.waitForSelector('#grid .card:not(.cur) img',{timeout:15000});
    await tap('#grid .card:not(.cur) img'); await p.waitForTimeout(900);
    const cf=await p.evaluate(CARD); ok(`${lang}: лента замен — фото открывает карточку с «Заменить»`,!!cf&&cf.btns.length===2,cf&&{name:cf.name,btns:cf.btns});
    await shot('card-feed');
    await p.locator('#itemCard .ic-sw').click(); await p.waitForTimeout(1200);
    w=await p.evaluate(WIN); const nm0=await p.evaluate(()=>shotRows[0].name);
    ok(`${lang}: «Заменить» в карточке ленты — диван заменён, лист закрыт`,!w.card&&!w.sheet&&!!cf&&nm0===cf.name,{sheet:w.sheet,row0:nm0,card:cf&&cf.name});
    // 9. остальная карточка ленты — замена, как раньше
    await p.evaluate(()=>document.querySelector('#shotbody [data-rep="0"]').click()); await p.waitForSelector('#grid .card:not(.cur) .pr',{timeout:15000}); await p.waitForTimeout(500);
    const pick=await p.evaluate(()=>document.querySelector('#grid .card:not(.cur) .nm').innerText);
    await tap('#grid .card:not(.cur) .pr'); await p.waitForTimeout(1200);
    w=await p.evaluate(WIN); ok(`${lang}: тап по цене карточки ленты — замена, как раньше (без карточки)`,!w.card&&!w.sheet&&(await p.evaluate(()=>shotRows[0].name))===pick,w);
    await ctx.close();}
  ok('ошибок на странице нет',!errs.length,errs);
  console.log(R.join('\n')); fs.writeFileSync(`${OUT}${TAG}-${W}.log`,R.join('\n')+'\n'); await b.close();
  process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);})().catch(e=>{console.error(e);process.exit(2);});
