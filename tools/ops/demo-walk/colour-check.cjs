const {demoUrl}=require('../demo-url.cjs');
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ЦВЕТА ТОВАРА (demo-28, владелец 23.10): кружки цвета в строке окна — только у товаров, у модели которых в ленте ≥ 2 цветов; тап по
// кружку — СРАЗУ смена цвета без окна (T-20261112-53, владелец TG 936): название, цена, ссылка, модель цвета или подкраска, номер
// состояния новый, кружки на местах; «+N» и название строки — карточка с предпросмотром и «Сохранить»; пара одинаковых предметов — вместе; лента —
// чип цвета текущего открывает ту же карточку («×» закрывает только её, лист замен остаётся — не больше двух слоёв), плитка модели —
// её цвета и «Заменить» выбранным. Платного нет, на сервер ничего не пишется.
//   BASE=http://127.0.0.1:8790/demo/ OUT=<папка/> [V=2] [TAG=after] node tools/ops/demo-walk/colour-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').tmpdir()+'/').replace(/\/?$/,'/');
const V=+(process.env.V||2), TAG=process.env.TAG||'run'; fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i===undefined?'':' '+(typeof i==='string'?i:JSON.stringify(i))));
const ST=`({card:!!document.querySelector('#itemCard.on'), sheet:document.getElementById('sheet').classList.contains('open'), win:document.getElementById('shot').classList.contains('on'),
  state:curStateId(), toast:(()=>{const t=document.getElementById('toast'); return t&&!t.hidden?t.textContent:'';})(),
  btns:[...document.querySelectorAll('#itemCard .ic-acts .btn,#itemCard .ic-na')].map(e=>e.innerText), cl:(document.querySelector('#itemCard .ic-cl')||{}).innerText||'',
  nm:(document.querySelector('#itemCard .ic-nm')||{}).innerText||'', img:((document.querySelector('#itemCard .ic-s')||{}).getAttribute||(()=>''))?.call(document.querySelector('#itemCard .ic-s'),'src')||'',
  pr:(document.querySelector('#itemCard .ic-pr')||{}).innerText||'', shop:(document.querySelector('#itemCard .ic-acts a')||{}).href||''})`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errs=[];
  for(const lang of ['ru','en']){
    const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:lang==='en'?'en-GB':'ru-RU'});
    const p=await ctx.newPage(); p.on('pageerror',e=>errs.push(lang+': '+String(e)));
    await p.addInitScript(()=>{try{localStorage.setItem('remlab-sheet-hint-v1','1')}catch(e){}});
    await p.goto(demoUrl(BASE+'?lang='+lang+'&live=0'),{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(1500);
    await p.evaluate(v=>vwOpenVariant(v),V);
    await p.waitForFunction(()=>document.querySelectorAll('#shotbody .pinlist .row').length>2,null,{timeout:60000}); await p.waitForTimeout(1200);
    await p.evaluate(()=>{const x=[...document.querySelectorAll('#shot button')].find(e=>/Мебель и|Furniture/.test(e.innerText)); if(x)x.click();}); await p.waitForTimeout(1200);
    const shot=async n=>{for(let i=0;i<4;i++){try{await p.screenshot({path:`${OUT}${TAG}-${W}-${lang}-${n}.png`,timeout:20000,animations:'disabled'});return;}catch(e){await p.waitForTimeout(1500);}}};
    // телефон: после смены цвета шторка сворачивается (видна сцена с заменой) — перед нажатием в списке открыть её снова
    const sheetUp=async()=>{if(!PHONE)return; const was=await p.evaluate(()=>{const sd=document.getElementById('vside'); if(!sd||+sd.dataset.pos>0)return 0;
      const x=[...document.querySelectorAll('#shot button')].find(e=>/Мебель и|Furniture/.test(e.innerText)); if(x)x.click(); return 1;}); if(was)await p.waitForTimeout(1200);};
    const tap=async sel=>{await sheetUp(); const l=p.locator(sel).first();
      if(sel.startsWith('#shotbody'))await l.evaluate(e=>e.scrollIntoView({block:'center'})); else await l.scrollIntoViewIfNeeded(); await p.waitForTimeout(300);
      if(PHONE)await l.tap(); else await l.click();};
    const st=()=>p.evaluate(ST);
    // 1. кружки — ровно у тех строк, у чьей модели ≥ 2 цветов в ленте
    const rows=await p.evaluate(()=>[...document.querySelectorAll('#shotbody .pinlist .row')].map(r=>{const a=shotRows[+r.dataset.k];
      const it=items.find(i=>(skuOf(i)||{}).name===a.name), dx=decorList().find(x=>(x.sku||{}).name===a.name), s=(it&&skuOf(it))||(dx&&dx.sku)||null;
      return {k:+r.dataset.k, name:a.name, sw:r.querySelectorAll('.sws [data-sw].sw').length, more:!!r.querySelector('.sws .swn'), fam:colourFam(s,a.role).length,
        swatch:!!(r.querySelector('.sws .sw')||{style:{}}).style.background&&/rgb|#/.test((r.querySelector('.sws .sw')||{style:{}}).style.background)};}));
    const bad=rows.filter(r=>r.sw!==Math.min(5,r.fam)||(r.fam>5)!==r.more);
    ok(`${lang}: кружки — у строк с цветами (до 5 и «+N»), у остальных нет`,!bad.length&&rows.some(r=>r.sw),rows.map(r=>`${r.name.slice(0,22)}: ${r.sw}/${r.fam}`).join(' | '));
    ok(`${lang}: кружки — тоном из сборки (swatch)`,rows.filter(r=>r.sw).every(r=>r.swatch),rows.filter(r=>r.sw).map(r=>r.swatch));
    const row=rows.find(r=>r.sw&&/Диван|Кресло|Стул/.test(r.name))||rows.find(r=>r.sw);
    if(!row){ok(`${lang}: есть строка с цветами`,false); await ctx.close(); continue;}
    const R0=`#shotbody .pinlist .row[data-k="${row.k}"]`;
    await p.evaluate(s=>document.querySelector(s).scrollIntoView({block:'center'}),R0); await p.waitForTimeout(400);
    await shot('row');
    // цвета строки — в порядке ленты (`colourFamRow`, T-20261112-53): номер кружка `data-sw` — номер в этом списке
    const fam=await p.evaluate(k=>{const a=shotRows[k], it=items.find(i=>(skuOf(i)||{}).name===a.name), dx=decorList().find(x=>(x.sku||{}).name===a.name);
      const s=(it&&skuOf(it))||(dx&&dx.sku); return colourFamRow(s,a.role).map(f=>({name:f.name,img:f.img,price:f.price,url:f.url,sid:f.sid,msid:f.msid||f.sid,tint:f.tint||null,u:itemUrl(f)||''}));},row.k);
    const s0=await st(), j1=fam.findIndex(f=>f.name!==row.name);
    const labels=()=>p.evaluate(()=>[...document.querySelectorAll('#shotbody .pinlist .row .sws .sw')].map(e=>e.getAttribute('aria-label')));
    const lab0=await labels();
    // 2. КРУЖОК ДРУГОГО ЦВЕТА — СРАЗУ СМЕНА (T-20261112-53, владелец TG 936): окна нет, товар места — этот цвет (название, цена, ссылка,
    //    модель цвета или подкраска), состояние новое, кружки на своих местах, выбранный — нажатый; подсказки «Сделать фото» нет
    await tap(R0+` .sws [data-sw="${j1}"]`); await p.waitForTimeout(1000);
    let s2=await st();
    const after=await p.evaluate(n=>{const its=items.filter(i=>(skuOf(i)||{}).name===n), a=shotRows.find(x=>x.name===n)||{};
      return {n:its.length, msid:its.map(i=>skuOf(i).msid||skuOf(i).sid), tint:its.map(i=>skuOf(i).tint||null), rows:shotRows.map(a=>a.name), price:a.price, url:itemUrl(a)};},fam[j1].name);
    ok(`${lang}: кружок — без окна, цвет в строке новый, состояние новое`,!s2.card&&after.rows.includes(fam[j1].name)&&!after.rows.includes(row.name)&&s2.state!==s0.state,
      {rows:after.rows.slice(0,3), st:[s0.state,s2.state]});
    ok(`${lang}: модель и подкраска — того цвета (своя модель или подкраска из сборки)`,after.n>=1&&after.msid.every(m=>m===fam[j1].msid)&&after.tint.every(t=>JSON.stringify(t)===JSON.stringify(fam[j1].tint)),
      {msid:after.msid, want:fam[j1].msid, tint:after.tint});
    ok(`${lang}: цена и ссылка строки — того цвета`,after.price===fam[j1].price&&(after.url||'')===fam[j1].u,{price:after.price,want:fam[j1].price});
    ok(`${lang}: подсказки «Сделать фото» нет (смена видна сразу)`,!/Сделать фото|Take photo/.test(s2.toast),s2.toast);
    const lab1=await labels(), on=await p.evaluate(s=>{const b=document.querySelector(s+' .sws .sw.on'); return b?b.dataset.sw:null;},`#shotbody .pinlist .row[data-k="${await p.evaluate(n=>shotRows.findIndex(a=>a.name===n),fam[j1].name)}"]`);
    ok(`${lang}: кружки не перескочили, выбранный — нажатый`,JSON.stringify(lab0)===JSON.stringify(lab1)&&on===String(j1),{on,j1});
    const kin=await p.evaluate(([a,b])=>({old:items.filter(i=>(skuOf(i)||{}).name===a).length, nu:items.filter(i=>(skuOf(i)||{}).name===b).length}),[row.name,fam[j1].name]);
    ok(`${lang}: все одинаковые предметы места сменили цвет вместе (старого не осталось)`,kin.old===0&&kin.nu>=1,kin);
    await shot('saved');
    // 3. кружок нажатого цвета — ничего не меняет; кружок прежнего — вернул как было
    const R1=`#shotbody .pinlist .row[data-k="${await p.evaluate(n=>shotRows.findIndex(a=>a.name===n),fam[j1].name)}"]`;
    await tap(R1+` .sws [data-sw="${j1}"]`); await p.waitForTimeout(600); let s3=await st();
    ok(`${lang}: кружок того же цвета — ничего не изменилось`,!s3.card&&s3.state===s2.state);
    const j0=fam.findIndex(f=>f.name===row.name);
    await tap(R1+` .sws [data-sw="${j0}"]`); await p.waitForTimeout(900); s3=await st();
    ok(`${lang}: кружок прежнего цвета — вернул прежний товар`,!s3.card&&(await p.evaluate(()=>shotRows.map(a=>a.name))).includes(row.name));
    // 4. «+N» (цветов больше пяти) — карточка со всеми цветами, как прежде
    if(await p.locator(R0+' .sws .swn').count()){await tap(R0+' .sws .swn'); await p.waitForTimeout(600); const s4=await st();
      ok(`${lang}: «+N» — карточка со всеми цветами`,s4.card,s4); await p.locator('#itemCard .ic-x').click(); await p.waitForTimeout(400);}
    // 5. название строки — карточка товара с цветами (предпросмотр и «Сохранить» там — как прежде)
    await p.evaluate(s=>document.querySelector(s+' .t b').click(),R0); await p.waitForTimeout(600);
    await p.locator(`#itemCard [data-icsw="1"]`).click(); await p.waitForTimeout(400); const s5=await st();
    ok(`${lang}: в карточке товара кружок — предпросмотр и «Сохранить»`,s5.card&&s5.btns[0]===(lang==='en'?'Save':'Сохранить'),s5.btns);
    await p.locator('#itemCard .ic-x').click(); await p.waitForTimeout(400);
    // 6. лента: чип цвета текущего — карточка поверх листа; «×» закрывает только её; «Сохранить» — цвет и лист закрыт
    await p.evaluate(k=>{const b=document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] [data-rep]`); if(b)b.click();},row.k); await p.waitForTimeout(900);
    const chip=await p.evaluate(()=>{const c=[...document.querySelectorAll('#grid .colchip:not(.on)')]; return c.length;});
    if(chip){
      const nm0=await p.evaluate(k=>shotRows[k].name,row.k);
      await tap('#grid .colchip:not(.on)'); await p.waitForTimeout(700); let s3=await st();
      ok(`${lang}: чип цвета в ленте — карточка поверх листа, «Сохранить», не применено`,s3.card&&s3.sheet&&s3.btns[0]===(lang==='en'?'Save':'Сохранить')&&(await p.evaluate(k=>shotRows[k].name,row.k))===nm0,s3.btns);
      await shot('feed-chip-card');
      await p.locator('#itemCard .ic-x').click(); await p.waitForTimeout(500); s3=await st();
      ok(`${lang}: «×» карточки — лист замен остаётся (закрыт только верхний слой)`,!s3.card&&s3.sheet);
      await tap('#grid .colchip:not(.on)'); await p.waitForTimeout(600); const want=await p.evaluate(()=>document.querySelector('#itemCard .ic-nm').innerText);
      await p.goBack(); await p.waitForTimeout(800); s3=await st();
      ok(`${lang}: «назад» — закрыта карточка, лист и окно на месте`,!s3.card&&s3.sheet&&s3.win,s3);
      await tap('#grid .colchip:not(.on)'); await p.waitForTimeout(600);
      await p.locator('#itemCard .ic-sv').click(); await p.waitForTimeout(1000); s3=await st();
      ok(`${lang}: «Сохранить» из ленты — цвет сменился, лист закрыт, тост`,!s3.card&&!s3.sheet&&(await p.evaluate(()=>shotRows.map(a=>a.name))).includes(want)&&/Сделать фото|Take photo/.test(s3.toast),{want,toast:s3.toast});
    }else R.push(`ИНФО ${lang}: у текущей модели в отфильтрованной ленте один цвет — чипов нет`);
    // 7. плитка другой модели: её цвета в карточке, «Заменить» ставит показанный цвет — ищем ленту с такой плиткой по строкам
    let tile=-1;
    for(const r of rows){ await p.evaluate(k=>{const b=document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] [data-rep]`); if(b)b.click();},r.k); await p.waitForTimeout(800);
      tile=await p.evaluate(()=>[...document.querySelectorAll('#grid .card:not(.cur)')].findIndex(c=>/ещё \d+|\+\d+ more/.test(c.innerText)));
      if(tile>=0)break; await p.evaluate(()=>closePicker()); await p.waitForTimeout(300);}
    if(tile>=0){
      await tap(`#grid .card:not(.cur) >> nth=${tile} >> img`); await p.waitForTimeout(700);
      const n=await p.evaluate(()=>document.querySelectorAll('#itemCard [data-icsw]').length);
      ok(`${lang}: плитка модели с цветами — карточка с её цветами и «Заменить»`,n>=2&&(await st()).btns[0]===(lang==='en'?'Replace':'Заменить'),{n});
      await p.locator('#itemCard [data-icsw="1"]').click(); await p.waitForTimeout(400);
      const want=await p.evaluate(()=>document.querySelector('#itemCard .ic-nm').innerText);
      await p.locator('#itemCard .ic-pk').click(); await p.waitForTimeout(1000); const s4=await st();
      ok(`${lang}: «Заменить» в карточке плитки — поставлен показанный цвет, лист закрыт`,!s4.card&&!s4.sheet&&(await p.evaluate(()=>shotRows.map(a=>a.name))).includes(want),{want});
    }else R.push(`ИНФО ${lang}: в ленте нет плитки с «ещё N цветов»`);
    // 8. пара одинаковых предметов (стулья ×2) с цветами — цвет меняется у всех
    const pair=await p.evaluate(()=>[...document.querySelectorAll('#shotbody .pinlist .row')].map(r=>shotRows[+r.dataset.k]).find(a=>a&&(a.qty||1)>1&&
      document.querySelector(`#shotbody .pinlist .row[data-k="${shotRows.indexOf(a)}"] .sws`)));
    if(pair){const k=await p.evaluate(n=>shotRows.findIndex(a=>a.name===n),pair.name), n0=await p.evaluate(n=>items.filter(i=>(skuOf(i)||{}).name===n&&i.sku&&i.sku.name).length,pair.name);
      const want=await p.evaluate(k=>{const b=document.querySelector(`#shotbody .pinlist .row[data-k="${k}"] .sws .sw:not(.on)`), a=shotRows[k];
        const it=items.find(i=>(skuOf(i)||{}).name===a.name); const w=colourFamRow(skuOf(it),a.role)[+b.dataset.sw].name; b.click(); return w;},k);
      await p.waitForTimeout(900);
      const c=await p.evaluate(([a,b])=>({old:items.filter(i=>i.sku&&i.sku.name===a).length, nu:items.filter(i=>i.sku&&i.sku.name===b).length}),[pair.name,want]);
      ok(`${lang}: пара (${pair.qty} шт.) — цвет сменился у всех`,c.old===0&&c.nu===n0&&n0>=2,{...c,n0});}
    else R.push(`ИНФО ${lang}: пары с цветами в варианте нет`);
    // 9. «Заменить» в карточке строки — карточка закрыта, лист замен на её месте (не третьим слоем)
    await p.evaluate(s=>document.querySelector(s+' .t b').click(),R0); await p.waitForTimeout(500);
    if(await p.locator('#itemCard .ic-sw').count()){await p.locator('#itemCard .ic-sw').click(); await p.waitForTimeout(800);
      const s5=await st(); ok(`${lang}: «Заменить» карточки строки — карточка закрыта, открыт лист замен (слоёв поверх окна: 1)`,!s5.card&&s5.sheet,s5);
      await p.evaluate(()=>closePicker());}
    await ctx.close();}
  ok('ошибок на странице нет',!errs.length,errs);
  console.log(R.join('\n')); fs.writeFileSync(`${OUT}${TAG}-${W}.log`,R.join('\n')+'\n'); await b.close();
  process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);})().catch(e=>{console.error(e);console.log(R.join('\n'));process.exit(2);});
