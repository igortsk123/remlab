const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// НЕДОЧЁТЫ ИЗ ВЫГРУЗКИ В ФИГМУ (план demo-fix-figma-defects): EN без русских слов в сообщении замены, значке «изменено» и сообщении
// избранного (без повтора «Living room “Living room #1”»); квадратики легенды бюджета 10 px, кружки цвета в строке 22 px и в карточке
// 34 px; название в окне замены — не больше двух строк и с «…». Платное не нажимается: кадр и задание подменены; сохранение в избранное
// подменено (`POST/PATCH /api/collections`) — в базу прода проба не пишет.
//   BASE=http://127.0.0.1:8790/demo/ OUT=/путь/снимков/ node tools/ops/demo-walk/figma-defects-check.cjs 1440x900
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/figma-';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+(typeof i==='string'?i:JSON.stringify(i)):''));
const CYR=/[А-Яа-яЁё]/;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{for(const lang of ['ru','en']){
    const EN=lang==='en', tag=`${W}-${lang}`;
    const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:EN?'en-GB':'ru-RU'});
    const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
    await p.addInitScript(()=>{try{localStorage.setItem('remlab-sheet-hint-v1','1');
      Object.keys(localStorage).filter(k=>/^remlab-(basket|favorites|collections|fav-thumbs)/.test(k)).forEach(k=>localStorage.removeItem(k));}catch(e){}});
    await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
    await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
    await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:30})}));
    await p.route(/\/api\/collections/,r=>{const m=r.request().method();
      if(m==='POST')return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,id:'Fake'+String(Date.now()).padStart(18,'0'),editToken:'probe'})});
      if(m==='PATCH'||m==='DELETE')return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true})});
      return r.continue();});
    const shot=async(n,o)=>{for(let i=0;i<4;i++){try{await p.screenshot({path:`${OUT}${tag}-${n}.png`,timeout:20000,animations:'disabled',...(o||{})});return;}catch(e){await p.waitForTimeout(1200);}}};
    const box=s=>p.evaluate(s=>{const e=document.querySelector(s); if(!e)return null; const r=e.getBoundingClientRect(), c=getComputedStyle(e);
      return {w:+r.width.toFixed(1),h:+r.height.toFixed(1),radius:c.borderRadius,display:c.display,cursor:c.cursor};},s);
    await p.goto(BASE+'?lang='+lang+'&live=0&v='+Date.now(),{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&allVariants().length>0",null,{timeout:90000}); await p.waitForTimeout(2000);
    // 1. главная: легенда бюджета (раздельный пакет) — квадратики 10 px со скруглением 3 px
    await p.evaluate(()=>{const c=document.getElementById('hmCert'); if(c&&!c.hidden)c.scrollIntoView({block:'center'});}); await p.waitForTimeout(500);
    await shot('1-home');
    const lg=await box('.cs-lg .li > span:first-child');
    if(lg){ok(`${lang}: легенда бюджета — квадратик 10×10`,lg.w===10&&lg.h===10&&lg.radius==='3px',lg);
      const cb=await p.evaluate(()=>{const e=document.querySelector('#hmCert .cs'); if(!e)return null; const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height};});
      if(cb)await shot('1-cert-zoom',{clip:{x:Math.max(0,cb.x-6),y:Math.max(0,cb.y-6),width:Math.min(W,cb.width+12),height:cb.height+12}});}
    else R.push(`--   ${lang}: легенды бюджета на главной нет (пакет не раздельный)`);
    // 2. окно варианта, список: кружки цвета 22 px
    await p.evaluate(()=>vwOpenVariant(0));
    await p.waitForFunction(()=>document.querySelectorAll('#shotbody .pinlist .row').length>2,null,{timeout:60000}); await p.waitForTimeout(1200);
    await p.evaluate(()=>{const x=[...document.querySelectorAll('#shot button')].find(e=>/Мебель и|Furniture/.test(e.innerText)); if(x)x.click();}); await p.waitForTimeout(1200);
    const rk=await p.evaluate(()=>{const r=[...document.querySelectorAll('#shotbody .pinlist .row')].find(r=>r.querySelector('.sws [data-sw]')); if(!r)return null; r.scrollIntoView({block:'center'}); return r.dataset.k;});
    await p.waitForTimeout(600); await shot('2-list');
    if(rk!=null){const s=await box(`#shotbody .pinlist .row[data-k="${rk}"] .sws button[data-sw]`);
      ok(`${lang}: кружок цвета в строке — 22×22, круглый`,!!s&&s.w===22&&s.h===22&&s.radius==='50%',s);
      // 3. карточка товара: кружки 34 px
      await p.evaluate(k=>document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] .t b`).click(),rk); await p.waitForTimeout(1500);
      const c=await box('#itemCard .ic-swr button[data-sw], #itemCard .ic-swr .sw');
      ok(`${lang}: кружок цвета в карточке — 34×34`,!!c&&c.w===34&&c.h===34,c);
      await shot('3-card');
      await p.evaluate(()=>{const x=document.querySelector('#itemCard .ic-x'); if(x)x.click();}); await p.waitForTimeout(700);}
    else R.push(`--   ${lang}: строк с кружками цвета нет`);
    // 4. окно замены: названия — не больше двух строк и с «…»
    const k=await p.evaluate(()=>items.findIndex(i=>String(i.role)==='диван'));
    await p.evaluate(k=>{sel=items[k]; draw(); openPicker(items[k]);},k); await p.waitForTimeout(2500);
    const nm=await p.evaluate(()=>[...document.querySelectorAll('#grid .card .nm')].map(e=>{const c=getComputedStyle(e), lh=parseFloat(c.lineHeight);
      return {cut:e.scrollHeight>e.clientHeight+1, clamp:c.webkitLineClamp||c.getPropertyValue('-webkit-line-clamp'), lines:+(e.clientHeight/lh).toFixed(2)};}));
    const cut=nm.filter(x=>x.cut);
    ok(`${lang}: окно замены — у обрезанных названий многоточие (line-clamp 2), видимых строк ≤ 2`,
      cut.every(x=>String(x.clamp)==='2')&&nm.every(x=>x.lines<=2.05),{cards:nm.length,cut:cut.length,clamp:[...new Set(nm.map(x=>x.clamp))],maxLines:Math.max(...nm.map(x=>x.lines))});
    await shot('4-swap');
    const gb=await p.evaluate(()=>{const e=document.getElementById('grid'); const r=e.getBoundingClientRect(); return {x:r.x,y:Math.max(0,r.y),width:r.width,height:Math.min(r.height,420)};});
    await shot('4-swap-zoom',{clip:{x:gb.x,y:gb.y,width:Math.min(gb.width,W-gb.x),height:Math.min(gb.height,H-gb.y)}});
    // 5. замена → сообщение «Заменено: …» / «Replaced: sofa»
    await p.evaluate(k=>{const cur0=(skuOf(items[k])||{}).name; const c=feedFor('диван').find(x=>x&&x.name&&x.name!==cur0);
      tryOn(c); closePicker(); refreshShotList();},k);
    await p.waitForTimeout(250);
    const t1=await p.evaluate(()=>{const t=document.getElementById('toast'); return t&&!t.hidden?t.textContent:'';});
    await shot('5-toast');
    ok(`${lang}: сообщение замены`,EN?/^Replaced: sofa/.test(t1)&&!CYR.test(t1):/^Заменено: диван/.test(t1),t1);
    // 6. избранное: «Living room #1 — in favourites and included…» без повтора типа комнаты
    await p.waitForTimeout(2500);
    await p.evaluate(()=>{const v=document.getElementById('vFav'); if(v)v.click();}); await p.waitForTimeout(400);
    const fname=await p.inputValue('#favName').catch(()=>'');
    await p.click('#favOk').catch(()=>{});
    await p.waitForFunction(()=>{const t=document.getElementById('toast'); return t&&!t.hidden&&/избранн|favourites|сертификат|allowance/i.test(t.textContent);},null,{timeout:15000}).catch(()=>{});
    const t2=await p.evaluate(()=>{const t=document.getElementById('toast'); return t&&!t.hidden?t.textContent:'';});
    // окошко имени закрывается после всей цепочки сохранения — снимок без него, пока сообщение ещё видно (~3 с)
    await p.waitForFunction(()=>!document.getElementById('favPop'),null,{timeout:2500}).catch(()=>{});
    await shot('6-fav');
    const head=t2.split(/ — /)[0].replace(/ /g,' ');
    ok(`${lang}: сообщение избранного без повтора типа комнаты`,!!t2&&!/^(\S+(?: \S+)?) [«“]\1 #/.test(head)&&(!EN||!CYR.test(t2)),{name:fname,toast:t2});
    // 7. значок «Изменено вами» / «Changed by you» в планировке
    // окно варианта закрываем (как кнопка «Планировка»: `#shot` и `#cons` на одном уровне — иначе окно закрывает план)
    await p.evaluate(()=>{document.querySelectorAll('#favPop,.dlg').forEach(e=>e.remove()); const x=document.getElementById('shotx'); if(x)x.click();}); await p.waitForTimeout(800);
    await p.evaluate(()=>openCons('edit')); await p.waitForTimeout(1500);
    const st=await p.evaluate(()=>{const e=document.getElementById('layoutState'); return {text:e.textContent, shown:getComputedStyle(e).display!=='none'};});
    ok(`${lang}: значок изменённой расстановки`,st.shown&&(EN?st.text==='Changed by you':st.text==='Изменено вами'),st);
    await shot('7-cons');
    const sb=await p.evaluate(()=>{const e=document.getElementById('layoutState'); const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height};});
    if(sb.width)await shot('7-badge-zoom',{clip:{x:Math.max(0,sb.x-120),y:Math.max(0,sb.y-30),width:Math.min(W-Math.max(0,sb.x-120),sb.width+240),height:sb.height+60}});
    ok(`${lang}: без ошибок страницы`,!errs.length,errs.slice(0,2).join(' | '));
    await ctx.close();
  }}finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.filter(x=>!x.startsWith('--')).length} · снимки ${OUT}${W}-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
