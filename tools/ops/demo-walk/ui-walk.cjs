const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ОБХОД ИНТЕРФЕЙСА /demo ДЛЯ РЕВИЗИИ (demo-21 шаг 1): снимок каждого состояния + замер слоёв (липкие/плавающие/оверлейные элементы:
// position, z-index, фон, тень, граница, место на экране) в каждом состоянии — `layers-<W>.json`. Платный путь подменён.
//   BASE=https://remont-lab.online/demo/ OUT=<папка/> node tools/ops/demo-walk/ui-walk.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/';
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const LOG=[], LAYERS={};
const note=(k,v)=>{LOG.push(k+' '+(typeof v==='string'?v:JSON.stringify(v))); console.log(k, typeof v==='string'?v:JSON.stringify(v));};
// слои: всё видимое с position sticky/fixed, absolute с явным z-index, и всё с тенью
const LAYER_JS=`(()=>{const out=[], seen=new Set();
  const nm=e=>(e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/\\s+/).slice(0,3).join('.'):'')||e.tagName.toLowerCase();
  const path=e=>{const a=[]; for(let x=e;x&&x!==document.body&&a.length<3;x=x.parentElement)a.unshift(nm(x)); return a.join(' > ');};
  document.querySelectorAll('body *').forEach(e=>{const cs=getComputedStyle(e); if(cs.display==='none'||cs.visibility==='hidden')return;
    const r=e.getBoundingClientRect(); if(r.width<2||r.height<2||r.bottom<0||r.top>innerHeight||r.right<0||r.left>innerWidth)return;
    const pos=cs.position, z=cs.zIndex, sh=cs.boxShadow!=='none';
    if(!(pos==='sticky'||pos==='fixed'||(pos==='absolute'&&z!=='auto')||sh))return;
    const k=path(e); if(seen.has(k))return; seen.add(k);
    out.push({el:k, pos, z, bg:cs.backgroundColor, shadow:sh?cs.boxShadow:'', border:[cs.borderTopWidth+' '+cs.borderTopStyle+' '+cs.borderTopColor, cs.borderBottomWidth+' '+cs.borderBottomStyle].join(' | '),
      radius:cs.borderRadius, top:pos==='sticky'?cs.top:'', rect:[r.left,r.top,r.width,r.height].map(Math.round)});});
  return out;})()`;
// РАЗМЕРЫ НА ЭКРАНЕ (2K, владелец TG 874): ширины контейнеров и колонок, max-width, сетки, шрифты ключевых строк
const METRICS_JS=`(()=>{const box=[], font={};
  const nm=e=>(e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/\s+/).slice(0,2).join('.'):'')||e.tagName.toLowerCase();
  const walk=(e,d)=>{if(d>5)return; [...e.children].forEach(c=>{const cs=getComputedStyle(c); if(cs.display==='none')return; const r=c.getBoundingClientRect();
    if(r.width>=innerWidth*0.25&&r.height>=20&&(cs.maxWidth!=='none'||/grid|flex/.test(cs.display)||d<=2))
      box.push({el:'  '.repeat(d)+nm(c), x:Math.round(r.left), w:Math.round(r.width), maxW:cs.maxWidth, pad:cs.paddingLeft+' '+cs.paddingRight, disp:cs.display,
        cols:cs.display.includes('grid')?cs.gridTemplateColumns:'', fs:cs.fontSize});
    walk(c,d+1);});};
  walk(document.body,0);
  const f=(k,sel)=>{const e=document.querySelector(sel); if(e){const cs=getComputedStyle(e); font[k]=cs.fontSize+' / '+cs.fontWeight+' · '+Math.round(e.getBoundingClientRect().width)+'px';}};
  f('body','body'); f('шапка: тип квартиры','.hm-hd b, .hm-hd .t, .hm-hd'); f('цена квартиры','.hm-hd .pr, .hm-price'); f('шкала','#hmCert .cs-t'); f('вкладка стиля','.hm-tab');
  f('подпись комнаты на фото','.hm-room .hm-ph .nm, .hm-room b'); f('цена комнаты','.hm-room .pr b, .hm-room .pr'); f('кнопка Открыть','.hm-room .btn.primary, .hm-room .btn');
  f('строка «скоро»','.hm-soon, .hm-rooms .hm-r2'); f('подсказка','.hm-hint'); f('кнопки Ипотека/Консультация','.hm-acts .btn');
  return {vw:innerWidth, vh:innerHeight, box:box.slice(0,60), font};})()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:W>1600?1:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.request().method()==='POST'?r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}):r.continue());
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:60})}));
  const shot=async(name,layers)=>{await p.waitForTimeout(250); await p.screenshot({path:OUT+`${W}-${name}.png`}); if(layers)LAYERS[name]=await p.evaluate(LAYER_JS);};
  const settle=()=>p.waitForFunction(()=>document.getAnimations().filter(a=>a.playState==='running').length===0,null,{timeout:8000}).catch(()=>{});
  const step=async(name,fn)=>{try{await fn();}catch(e){note('FAIL '+name,String(e).split('\n')[0].slice(0,200));}};
  await p.goto(BASE+'?live=force&lang=ru',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!document.getElementById('hmCert').hidden",null,{timeout:90000});
  await p.waitForTimeout(2000);
  // ГЛАВНАЯ
  await step('home',async()=>{
    await shot('home-top',true); fs.writeFileSync(OUT+`metrics-${W}.json`,JSON.stringify(await p.evaluate(METRICS_JS),null,1));
    await p.evaluate(()=>scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(600); await p.evaluate(()=>scrollTo(0,0)); await p.waitForTimeout(400);   // ленивые картинки
    await p.click('#hmCert .vpl-i'); await p.waitForTimeout(400); await shot('home-top-cert-i',true); await p.click('#hmCert .vpl-i');
    const t=await p.evaluate(()=>{const t=document.querySelector('.hm-tabs'); return t?Math.round(t.getBoundingClientRect().top+scrollY):400;});
    for(const [nm,dy] of [['home-scrolled-tabs-stuck',60],['home-scrolled-rooms',360],['home-scrolled-deep',900]]){
      await p.evaluate(y=>scrollTo(0,y),t+dy); await p.waitForTimeout(700); await shot(nm,true);}
    await p.evaluate(y=>scrollTo(0,y),t+60); await p.waitForTimeout(500);
    await p.click('#hmCert .vpl-i'); await p.waitForTimeout(400); await shot('home-stuck-cert-i'); await p.click('#hmCert .vpl-i');
    await p.evaluate(()=>scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(800); await shot('home-bottom',true);
    await p.evaluate(()=>scrollTo(0,0)); await p.waitForTimeout(400);});
  // ПЛАН КВАРТИРЫ (плитка/ссылка на главной)
  await step('flatplan',async()=>{
    // видимая ссылка/плитка плана (на телефоне и компьютере — разные элементы с `data-plan`)
    const ok1=await p.evaluate(()=>{const e=[...document.querySelectorAll('[data-plan]')].find(x=>x.getClientRects().length&&getComputedStyle(x).visibility!=='hidden'); if(!e)return false; e.click(); return true;});
    if(ok1){await p.waitForTimeout(1500); await shot('flat-plan',true);
      await p.keyboard.press('Escape'); await p.waitForTimeout(600);
      const x=await p.$('#planx, .planx, [aria-label="Закрыть"]:visible'); if(x)await x.click().catch(()=>{}); await p.waitForTimeout(600);
      await p.evaluate(()=>scrollTo(0,0));}
    else note('flat-plan','элемент плана не найден');});
  // ОКНО ВАРИАНТА
  await step('window',async()=>{
    await p.evaluate(()=>{try{localStorage.removeItem('remlab-sheet-hint-v1')}catch(e){} openLiveWindow();});
    await p.waitForTimeout(1200); await shot('win-loading');
    await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:150000}).catch(()=>{}); await p.waitForTimeout(1200);
    note('win-open-mode',await p.evaluate(()=>VW.mode)); await shot('win-open',true);
    await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(1500); await shot('win-3d-hint',true); await p.waitForTimeout(3500); await settle(); await shot('win-3d',true);
    note('win-modes',await p.evaluate(()=>({mode:VW.mode, photo:!(document.querySelector('[data-vm="photo"]')||{hidden:true}).hidden, real:vwRealShots().length})));
    if(PHONE){
      // у шторки три остановки (demo-21 п.5): 1 в `vwSheet` — то же, что 2 (средняя), отдельным состоянием не снимаем
      for(const n of [0,2,3]){await p.evaluate(n=>vwSheet(n),n); await p.waitForTimeout(700); await settle(); await shot('sheet-'+['collapsed','low','mid','full'][n],n>=2);}
      await p.evaluate(()=>{const s=document.getElementById('vscroll'); s.scrollTop=260;}); await p.waitForTimeout(600); await shot('sheet-full-scrolled',true);
      await p.evaluate(()=>{const s=document.getElementById('vscroll'); s.scrollTop=s.scrollHeight;}); await p.waitForTimeout(600); await shot('sheet-full-bottom');
      await p.evaluate(()=>{document.getElementById('vscroll').scrollTop=0; vwSheet(2);}); await p.waitForTimeout(700); await settle();}
    // (i) плашки сертификата в окне
    const vi=await p.$('#shot .vpl-i'); if(vi){await vi.click(); await p.waitForTimeout(400); await shot('win-cert-i',true); await vi.click(); await p.waitForTimeout(300);}
    // выделенный предмет (тап по мебели): строка подсвечена
    await p.evaluate(()=>{const f=i=>String(i.role||'').replace(/\s+\d+$/,''); let k=items.findIndex(i=>/столик|журнальн/i.test(f(i))); if(k<0)k=0; vwHighlight(k);});
    await p.waitForTimeout(1500); await settle(); await shot('win-selected-row',true);
    await p.evaluate(()=>vwSelect(null)); await p.waitForTimeout(500);
    // План в окне
    await p.evaluate(()=>vwMode('plan')); await p.waitForTimeout(1500); await shot('win-plan',true);
    // Фото (если есть снимок этой расстановки) и полноэкранный
    const ph=await p.evaluate(()=>vwRealShots().length>0);
    if(ph){await p.evaluate(()=>vwMode('photo')); await p.waitForTimeout(2500); await shot('win-photo',true);
      // кнопка «⤢» перекрыта? — что лежит над её серединой (находка обхода); нажатие — командой
      note('vzbtn-cover',await p.evaluate(()=>{const z=document.getElementById('vzBtn'); if(!z)return 'нет'; const r=z.getBoundingClientRect(), e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
        return {rect:[r.left,r.top,r.width,r.height].map(Math.round), top:e?(e.id||e.className||e.tagName):'—', own:!!e&&(e===z||z.contains(e))};}));
      const zb=await p.$('#vzBtn'); if(zb){await p.evaluate(()=>document.getElementById('vzBtn').click()); await p.waitForTimeout(1500); await shot('photo-fullscreen',true);
        await p.evaluate(()=>{const x=document.querySelector('#vzoom .vzx'); if(x)x.click();}); await p.waitForTimeout(600);}}
    else note('win-photo','вкладки «Фото» нет — для этой расстановки нет готового фото');
    await p.evaluate(()=>vwMode('walk')); await p.waitForTimeout(1500);});
  // ЛИСТ ЗАМЕНЫ: вверху, прокручен; замена → тост
  await step('picker',async()=>{
    if(PHONE){await p.evaluate(()=>vwSheet(3)); await p.waitForTimeout(800); await settle();}
    await p.locator('#vside .vitems [data-rep]').first().click(); await p.waitForTimeout(1500); await settle();
    await shot('picker-top',true);
    await p.evaluate(()=>{const s=document.getElementById('sheet'); const sc=[s,...s.querySelectorAll('*')].find(e=>e.scrollHeight>e.clientHeight+20&&/auto|scroll/.test(getComputedStyle(e).overflowY)); if(sc)sc.scrollTop=500;});
    await p.waitForTimeout(700); await shot('picker-scrolled',true);
    await p.evaluate(()=>{const s=document.getElementById('sheet'); [s,...s.querySelectorAll('*')].forEach(e=>{if(e.scrollTop)e.scrollTop=0;});}); await p.waitForTimeout(400);
    await p.locator('#sheet .mini:has-text("Заменить")').first().click(); await p.waitForTimeout(900);
    await shot('toast-after-replace',true);
    await p.waitForTimeout(2500); await settle(); await shot('after-replace');});
  // ИЗБРАННОЕ
  await step('fav',async()=>{
    await p.click('#vFav'); await p.waitForTimeout(400); await shot('fav-name-popup',true);
    await p.click('#favOk'); await p.waitForFunction("!document.getElementById('favPop')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1000);
    await shot('fav-saved-toast',true);
    await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(1200);
    await p.evaluate(()=>{window.__basket.open(); const h=document.getElementById('favHead'); if(h)h.scrollIntoView({block:'start'});}); await p.waitForTimeout(1200);
    await shot('home-fav-section',true);
    const fi=await p.$('#favGrid .favcard .incw .vpl-i'); if(fi){await fi.click(); await p.waitForTimeout(400); await shot('home-fav-i',true); await fi.click();}
    await p.click('#favGrid [data-fmore]').catch(()=>{}); await p.waitForTimeout(400); await shot('fav-more-popup',true);
    await p.click('#favDel').catch(()=>{}); await p.waitForTimeout(800);
    note('fav-removed',await p.evaluate(()=>!window.__fav.list().length));});
  note('page-errors',errs.slice(0,5));
  fs.writeFileSync(OUT+`layers-${W}.json`,JSON.stringify(LAYERS,null,1));
  fs.writeFileSync(OUT+`walk-${W}.log`,LOG.join('\n')+'\n');
  console.log(`ui-walk ${W}x${H}: снимков ${fs.readdirSync(OUT).filter(f=>f.startsWith(W+'-')).length}`);
  await b.close();
})().catch(e=>{console.log('FAIL обход прервался — '+String(e).slice(0,300)); process.exit(1);});
