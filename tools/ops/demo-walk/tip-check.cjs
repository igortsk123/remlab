const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПУЗЫРЬ «i» И ВЫДЕЛЕННАЯ СТРОКА (T-20261022-07, снимки владельца с iPhone SE 22.10): пузырь сертификата целиком виден поверх всего —
// на главной (в покое и у прилипшей шкалы), в окне варианта и в карточке избранного; у выделенной строки списка картинка внутри
// рамки с отступом от полосы, а позиция содержимого как у обычной строки. Платный путь подменён (автофото избранного).
//   BASE=https://remont-lab.online/demo/ OUT=<папка/> node tools/ops/demo-walk/tip-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i||''));
// пузырь виден целиком: внутри экрана, и в точках вдоль всех краёв сверху лежит он сам (не строка стилей, не шапка)
const bubSeen=sel=>`(()=>{const b=document.querySelector(${JSON.stringify(sel)}); if(!b||b.hidden)return {open:false};
  const r=b.getBoundingClientRect(), pts=[], bad=[];
  for(const fx of [0.1,0.5,0.9])for(const fy of [0.08,0.5,0.92])pts.push([r.left+r.width*fx,r.top+r.height*fy]);
  pts.forEach(([x,y])=>{const e=document.elementFromPoint(x,y); if(!e||!(e===b||b.contains(e)))bad.push([Math.round(x),Math.round(y),e?(e.id||e.className||e.tagName):'—']);});
  return {open:true, rect:[r.left,r.top,r.right,r.bottom].map(Math.round), inView:r.top>=0&&r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight, bad};})()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.request().method()==='POST'?r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}):r.continue());
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:60})}));
  await p.goto(BASE+'?lang=ru',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!document.getElementById('hmCert').hidden",null,{timeout:90000});
  await p.waitForTimeout(1500);
  // 1. главная, в покое: пузырь шкалы вниз — поверх строки стилей
  await p.click('#hmCert .vpl-i'); await p.waitForTimeout(400);
  let s=await p.evaluate(bubSeen('#hmCert .vpl-bub'));
  ok('1 главная в покое — пузырь «i» целиком виден',s.open&&s.inView&&!s.bad.length,JSON.stringify(s));
  await p.screenshot({path:OUT+`tip-${W}-1-home.png`});
  await p.click('#hmCert .vpl-i'); await p.waitForTimeout(300);
  // 2. главная, шкала прилипла (прокрутка к комнатам)
  await p.evaluate(()=>{const t=document.querySelector('.hm-tabs'); scrollTo(0,(t?t.getBoundingClientRect().top+scrollY:400)+200);}); await p.waitForTimeout(800);
  await p.click('#hmCert .vpl-i'); await p.waitForTimeout(400);
  s=await p.evaluate(bubSeen('#hmCert .vpl-bub'));
  ok('2 главная, шкала прилипла — пузырь целиком виден',s.open&&s.inView&&!s.bad.length,JSON.stringify(s));
  await p.screenshot({path:OUT+`tip-${W}-2-home-stuck.png`});
  await p.click('#hmCert .vpl-i'); await p.waitForTimeout(300);
  ok('2 повторный тап — пузырь закрыт',await p.evaluate(()=>document.querySelector('#hmCert .vpl-bub').hidden));
  // 3. окно варианта: пузырь плашки
  await p.evaluate(()=>{scrollTo(0,0); openLiveWindow();}); await p.waitForTimeout(2500);
  await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:150000}).catch(()=>{}); await p.waitForTimeout(1500);
  if(PHONE){await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(900);}
  const vi=await p.$('#shot .vpl-i'); if(vi){await vi.click(); await p.waitForTimeout(400);}
  s=await p.evaluate(bubSeen('#shot .vpl-bub'));
  ok('3 окно варианта — пузырь «i» целиком виден',s.open&&s.inView&&!s.bad.length,JSON.stringify(s));
  await p.screenshot({path:OUT+`tip-${W}-3-window.png`});
  if(vi){await vi.click(); await p.waitForTimeout(300);}
  // 4. выделенная строка (журнальный столик, иначе первая с картинкой): картинка внутри рамки с отступом, содержимое на месте
  const k=await p.evaluate(()=>{const f=i=>String(i.role||'').replace(/\s+\d+$/,''); let k=items.findIndex(i=>/столик|журнальн/i.test(f(i))); if(k<0)k=items.findIndex(i=>(skuOf(i)||{}).img); return k;});
  const g0=await p.evaluate(k=>{const r=vwRowOf(items[k]); const im=r&&r.querySelector('img,.noimg-sm'); return im?Math.round(im.getBoundingClientRect().left-r.closest('.pinlist').getBoundingClientRect().left):null;},k);
  await p.evaluate(k=>vwHighlight(k),k); await p.waitForTimeout(1500);
  await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{});
  const row=await p.evaluate(()=>{const r=document.querySelector('#shotbody .row.hl'); if(!r)return null; const im=r.querySelector('img,.noimg-sm'), rr=r.getBoundingClientRect(), ir=im.getBoundingClientRect();
    const pr=[...r.querySelectorAll('*')].filter(e=>/₽/.test(e.textContent)&&!e.children.length).map(e=>e.getBoundingClientRect().right), cs=getComputedStyle(r);
    const other=[...document.querySelectorAll('#shotbody .pinlist .row:not(.hl)')].map(x=>x.querySelector('img,.noimg-sm')).filter(Boolean)[0];
    return {row:[rr.left,rr.right].map(Math.round), img:[ir.left,ir.right].map(Math.round), priceR:pr.length?Math.round(Math.max(...pr)):null, bar:cs.boxShadow,
      gapL:Math.round(ir.left-rr.left), otherImgL:other?Math.round(other.getBoundingClientRect().left):null, list:Math.round(r.closest('.pinlist').getBoundingClientRect().left)};});
  ok('4 выделенная строка: картинка внутри рамки, от полосы (3 px) — отступ ≥ 8 px',!!row&&row.gapL>=8&&row.img[1]<=row.row[1],JSON.stringify(row));
  ok('4 выделенная строка: цена не прижата к правому краю рамки (≥ 6 px)',!!row&&row.priceR!=null&&row.row[1]-row.priceR>=6,row&&JSON.stringify({rowR:row.row[1],priceR:row.priceR}));
  ok('4 картинка выделенной строки — на той же вертикали, что у обычных строк',!!row&&row.otherImgL!=null&&Math.abs(row.img[0]-row.otherImgL)<=1&&(g0==null||Math.abs(row.img[0]-row.list-g0)<=1),
    row&&JSON.stringify({hl:row.img[0],other:row.otherImgL,before:g0==null?null:g0+row.list}));
  const hl=await p.$('#shotbody .row.hl'); if(hl){const bb=await hl.boundingBox(); await p.screenshot({path:OUT+`tip-${W}-4-row.png`,clip:{x:0,y:Math.max(0,bb.y-70),width:W,height:Math.min(H-Math.max(0,bb.y-70),bb.height+140)}});}
  await p.screenshot({path:OUT+`tip-${W}-4-sheet.png`});
  // 5. избранное: сохранить, на главной — «i» у «Добавлено в сертификат»
  // шторка во весь экран закрывает кнопки сцены — свернуть, иначе ♡ не нажать
  await p.evaluate(()=>{vwSelect(null); if(VW_PHONE())vwSheet(0);}); await p.waitForTimeout(700);
  await p.click('#vFav'); await p.waitForTimeout(300); await p.click('#favOk');
  await p.waitForFunction("!document.getElementById('favPop')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1200);
  await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(1200);
  await p.evaluate(()=>{window.__basket.open(); const c=document.querySelector('#favGrid .favcard'); if(c)c.scrollIntoView({block:'center'});}); await p.waitForTimeout(1200);
  const fi=await p.$('#favGrid .favcard .incw .vpl-i');
  if(fi){await fi.click(); await p.waitForTimeout(400);}
  s=await p.evaluate(bubSeen('#favGrid .favcard .incw .vpl-bub'));
  ok('5 избранное — пузырь «i» целиком виден',!fi||(s.open&&s.inView&&!s.bad.length),fi?JSON.stringify(s):'«i» в карточке нет');
  await p.screenshot({path:OUT+`tip-${W}-5-fav.png`});
  // 5б. карточка у верха экрана (под строкой стилей): пузырь не уходит под неё
  if(fi){await fi.click(); await p.waitForTimeout(300);
    await p.evaluate(()=>{const c=document.querySelector('#favGrid .favcard .incw'), t=document.querySelector('.hm-tabs').getBoundingClientRect().bottom; scrollBy(0,c.getBoundingClientRect().top-t-30);}); await p.waitForTimeout(800);
    await fi.click(); await p.waitForTimeout(400);
    s=await p.evaluate(bubSeen('#favGrid .favcard .incw .vpl-bub'));
    ok('5б избранное у верха экрана — пузырь целиком виден',s.open&&s.inView&&!s.bad.length,JSON.stringify(s));
    await p.screenshot({path:OUT+`tip-${W}-5b-fav-top.png`});
    await fi.click(); await p.waitForTimeout(300);}
  // убрать пробную запись
  await p.click('#favGrid [data-fmore]').catch(()=>{}); await p.waitForTimeout(300); await p.click('#favDel').catch(()=>{}); await p.waitForTimeout(800);
  ok('пробная запись убрана из избранного',await p.evaluate(()=>!window.__fav.list().length));
  ok('без ошибок страницы',!errs.length,errs.slice(0,3).join(' | '));
  console.log(R.join('\n')); console.log(`tip-check ${W}x${H} итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length}`);
  await b.close();
})().catch(e=>{console.log(R.join('\n')); console.log('FAIL проверка прервалась — '+String(e).slice(0,300)); process.exit(1);});
