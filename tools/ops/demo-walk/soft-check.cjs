const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// МЯГКОЕ — В СПИСКЕ, В СУММЕ И В ЗАПРОСЕ «УЛУЧШИТЬ», НО НЕ В 3D (план demo-24, владелец 23.10): подушки и шторы варианта — строками
// списка окна с ценой и ссылкой, роль без номера слота, БЕЗ пометки (правки 23.10); сумма и полоса бюджета их учитывают; живая сцена их
// не получает (`liveDecor`), запрос кадра — получает (`payload().decor`); замена подушки — из ленты той же роли, тост «Нажмите
// «<надпись кнопки>», чтобы увидеть изменения» (надпись — та же, что у кнопки); фото прежнего состояния после замены не считается
// актуальным (номер состояния, вариант А); EN — тост с переводом той же надписи. Платного пути нет: запросы кадра подменены.
//   BASE=http://127.0.0.1:8794/demo/ OUT=~/remlab-logs/demo24/<HHMM>/ node tools/ops/demo-walk/soft-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').homedir()+'/remlab-logs/soft-check/').replace(/\/?$/,'/');
fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i!==undefined?' — '+i:''));
async function page(b,lang){
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:PHONE?2:1,isMobile:PHONE,hasTouch:PHONE,locale:lang==='en'?'en-GB':'ru-RU'});
  const p=await ctx.newPage(); p.errs=[]; p.on('pageerror',e=>p.errs.push(String(e)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.route(/\/api\/render(\?|$)/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job:'fake-'+Date.now()})}));
  await p.route(/\/api\/job\?/,r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'running',eta:30})}));
  await p.goto(BASE+(lang==='en'?'?lang=en&':'?')+'live=force',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  await p.waitForTimeout(800);
  return p;
}
const openWin=async(p,i,mode)=>{await p.evaluate(([i,m])=>{pickVariant(i); VW.collapse=true; vwOpenVariant(i); if(VW.mode!==m)vwMode(m);},[i,mode]);
  await p.waitForFunction("document.getElementById('shot').classList.contains('on')",null,{timeout:30000}); await p.waitForTimeout(1500);};
// строки мягкого в списке окна и счёт денег варианта
const state=p=>p.evaluate(()=>{const v=allVariants()[cur]||{}, soft=decorList().filter(x=>isSoft(x.role)), names=soft.map(x=>x.sku.name);
  const rows=soft.map(x=>[...document.querySelectorAll('#vlist .vitems .row')].find(r=>(r.querySelector('b')||{}).textContent===x.sku.name)).filter(Boolean);
  const softSum=soft.reduce((t,x)=>t+((x.sku||{}).price||0),0), base=totalsOf(productsOf(items,tableDecor())).sum;
  return {soft:soft.map(x=>({role:x.role,name:x.sku.name,price:x.sku.price,url:!!x.sku.url,msid:x.sku.msid||null})),
    rows:rows.map(r=>({name:(r.querySelector('b')||{}).textContent, role:(((r.querySelector('.t span')||{}).firstChild||{}).textContent||'').split(' · ')[0],   // роль — до « · магазин»
      link:!!r.querySelector('a[href]'),
      rep:!!r.querySelector('[data-rep]'), price:(r.querySelector('.p')||{}).textContent})),
    price:variantPrice(v), base, softSum, plate:+document.getElementById('vsum').dataset.sum, plateWant:toCard(variantPrice(v)),
    live:liveDecor().map(x=>x.role), sent:payload().decor.map(x=>x.role), stateId:curStateId(),
    noteAny:/видно на улучшенном|shown on the enhanced/.test((document.getElementById('vlist')||{}).textContent||''),
    cta:(document.getElementById('vCta')||{}).textContent||'', mode:VW.mode, real:vwRealShots().length, at:shotAt,
    toast:(document.getElementById('toast')||{}).textContent||'', toastOn:!!document.getElementById('toast')&&!document.getElementById('toast').hidden};});
const softRow=k=>{const x=decorList().filter(x=>isSoft(x.role))[k]; return x&&[...document.querySelectorAll('#vlist .vitems .row')].find(r=>(r.querySelector('b')||{}).textContent===x.sku.name);};
const showRow=async(p,k)=>{await p.evaluate(([k,f])=>{if(VW_PHONE())vwSheet(3); const r=eval(f)(k); if(r)r.scrollIntoView({block:'center'});},[k,softRow.toString()]); await p.waitForTimeout(900);};
const clickRep=(p,k)=>p.evaluate(([k,f])=>eval(f)(k).querySelector('[data-rep]').click(),[k,softRow.toString()]);
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const p=await page(b);
    ok('правило ролей пришло с данными (rules.soft_roles)',await p.evaluate(()=>(D.rules.soft_roles||[]).includes('подушка')&&(D.rules.soft_roles||[]).includes('шторы')));
    await openWin(p,0,'walk');
    const s0=await state(p);
    ok('в варианте есть мягкое (подушки, шторы) — без модели',s0.soft.length>=2&&s0.soft.every(x=>!x.msid&&x.price>0&&x.url),JSON.stringify(s0.soft));
    ok('каждое мягкое — строкой списка окна: цена, «В магазин», «Заменить»; роль без номера слота; пометки нет',
      s0.rows.length===s0.soft.length&&s0.rows.every(r=>r.link&&r.rep&&/\d/.test(r.price||'')&&!/\d/.test(r.role)&&r.role.trim()===r.role.trim().replace(/\s+\d+$/,''))
      &&!s0.noteAny&&s0.rows.some(r=>r.role.trim()==='подушка'),JSON.stringify(s0.rows));
    ok('сумма варианта = мебель и вазы + мягкое',s0.price===s0.base+s0.softSum&&s0.softSum>0,`${s0.price} = ${s0.base} + ${s0.softSum}`);
    ok('плашка окна и полоса бюджета — та же сумма с мягким',s0.plate===s0.plateWant,`${s0.plate} / ${s0.plateWant}`);
    ok('в 3D мягкого нет: живая сцена его не получает',!s0.live.some(r=>/^(подушка|шторы|плед|покрывало)/.test(r)),JSON.stringify(s0.live));
    ok('в запрос кадра (и «Улучшить») мягкое уходит',s0.soft.every(x=>s0.sent.includes(x.role)),JSON.stringify(s0.sent));
    await p.screenshot({path:OUT+W+'-1-3d-bez-myagkogo.png'});
    await showRow(p,0);
    await p.screenshot({path:OUT+W+'-2-spisok-s-myagkim.png'});
    // замена подушки: «Заменить» в строке → лист подбора ленты подушек → другая подушка
    const pil=s0.soft.findIndex(x=>/^подушка/.test(x.role));
    // «ФОТО ЭТОГО СОСТОЯНИЯ» (подложено): до замены оно актуально и показано; после замены подушки — уже нет (вариант А)
    await p.evaluate(()=>{const u=(document.querySelector('#vlist img')||{}).src||'/demo/og.png';
      shots.push({quality:'realistic',url:u,stateId:curStateId(),camera:'C1',vid:curVid(),ts:Date.now()}); vwMode('photo');});
    await p.waitForTimeout(800);
    const sp=await state(p);
    ok('фото текущего состояния показано в «Фото»',sp.real===1&&sp.mode==='photo',JSON.stringify({real:sp.real,mode:sp.mode}));
    await clickRep(p,pil<0?0:pil);
    await p.waitForSelector('#sheet.open',{timeout:10000});
    const feed=await p.evaluate(()=>({title:document.getElementById('sh-title').textContent, cards:document.querySelectorAll('#grid .card').length,
      other:document.querySelectorAll('#grid .card:not(.cur)').length, badge:(document.querySelector('#grid .card .badge')||{}).textContent}));
    ok('лист подбора — лента подушек, есть другая подушка, на карточках без пометки',/подушка/.test(feed.title)&&feed.other>0&&feed.badge===undefined,JSON.stringify(feed));
    await p.click('#grid .card:not(.cur) .acts .mini');
    await p.waitForTimeout(250);
    const s1=await state(p);
    ok('тост замены — «Нажмите «<надпись кнопки>», чтобы увидеть изменения», надпись та же, что у кнопки',
      s1.toastOn&&s1.toast===`Нажмите «${s1.cta||'Сделать реалистичнее'}», чтобы увидеть изменения`&&s1.toast.includes('Сделать реалистичнее'),`${s1.toast} / кнопка «${s1.cta}»`);
    await p.screenshot({path:OUT+W+'-3-tost-zameny.png'});   // пока тост на экране (гаснет за ~1,8 с)
    await p.waitForTimeout(1200);
    const s2=await state(p);
    ok('после замены прежнее фото не актуально: в «Фото» его нет, окно не держит старый кадр',s2.real===0&&!(s2.mode==='photo'&&s2.at>=0&&s2.at===sp.at),
      JSON.stringify({real:s2.real,mode:s2.mode,at:s2.at,was:sp.at}));
    ok('замена записана: другая подушка, сумма пересчитана на разницу, номер состояния новый',
      s1.soft.some((x,k)=>x.name!==s0.soft[k].name)&&s1.price-s0.price===s1.softSum-s0.softSum&&s1.stateId!==s0.stateId,`${s0.price}→${s1.price}`);
    ok('после замены в 3D мягкого по-прежнему нет',!s1.live.some(r=>/^(подушка|шторы|плед|покрывало)/.test(r)));
    ok('ошибок страницы нет',!p.errs.length,p.errs.join(' | ').slice(0,300));
    // EN: пометка и тост — по-английски
    const e=await page(b,'en');
    await openWin(e,0,'walk');
    const e0=await state(e);
    ok('EN: роль переведена, без номера и пометки',e0.rows.length>0&&e0.rows.every(r=>!/\d/.test(r.role)&&!/[А-Яа-яЁё]/.test(r.role))&&!e0.noteAny,JSON.stringify(e0.rows.map(r=>r.role)));
    await clickRep(e,0);
    await e.waitForSelector('#sheet.open',{timeout:10000}); await e.click('#grid .card:not(.cur) .acts .mini'); await e.waitForTimeout(250);
    const e1=await state(e);
    ok('EN: тост замены переведён той же надписью кнопки',e1.toast==='Tap “Make it realistic” to see the changes',e1.toast);
    await showRow(e,0);
    await e.screenshot({path:OUT+W+'-4-en-spisok.png'});
    ok('EN: ошибок страницы нет',!e.errs.length,e.errs.join(' | ').slice(0,300));
  }finally{await b.close();}
  console.log(`soft-check ${W}x${H}\n`+R.join('\n'));
  process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);
})().catch(e=>{console.error(e);process.exit(2);});
