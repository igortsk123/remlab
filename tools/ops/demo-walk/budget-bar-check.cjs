const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ПОЛОСА ДВУХ БЮДЖЕТОВ (demo-23 шаг 3, ADR-0308, макет А владельца 22.10). Корзина задаётся заранее в хранилище браузера (выдуманные
// варианты с готовыми строками цен — без коллекций на сервере), пакет — ответом карточки квартиры. Состояния: РФ общий бюджет — пусто,
// частично, перерасход; UK раздельный — пусто, частично обе части, перерасход мебели при остатке улучшений, лимит улучшений 0; пузырь «i»;
// окно варианта — «выйдет за лимит на N»; избранное — «Доплата N — подтвердить?», без подтверждения корзина та же. Плюс высота липкой
// шапки телефона после прокрутки (сценарий 2.34). Платного нет, на сервер ничего не пишется.
//   BASE=http://127.0.0.1:8790/demo/ OUT=<папка/> node tools/ops/demo-walk/budget-bar-check.cjs 375x667
const BASE=process.env.BASE||'https://remont-lab.online/demo/', OUT=(process.env.OUT||require('os').tmpdir()+'/').replace(/\/?$/,'/');
fs.mkdirSync(OUT,{recursive:true});
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700;
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+(i===undefined?'':' '+(typeof i==='string'?i:JSON.stringify(i))));
const FX={RU:null, UK:'0.0089@2026-10-16'};
// выдуманное избранное: id — 22 знака, как у коллекции; строки — по бюджетам
const fid=n=>('budgetcheck'+n).padEnd(22,'x').slice(0,22);
function fav(n,room,kind,lines,cur,fx){return {favoriteId:fid(n), editToken:null, roomId:room, roomKind:kind, styleId:'scandi', stateId:'', sourceVariantId:'',
  displayName:(room==='living'?'Гостиная':room==='kitchen'?'Кухня':'Спальня')+' #'+n, autoName:true, createdAt:1760000000000+n,
  quote:{status:'fresh', currency:cur, at:Date.now(), lines:lines.map(([b,a],k)=>({chargeKey:'shop:t'+n+'-'+k, roomId:room, label:'позиция '+k, settlement:'allowance',
    amount:a, priceStatus:'known', source:'shop', budgetBucket:b})), ...(fx?{fx}:{})}};}
function basket(apt,cur,fx,favs,inc){return {v:2, apartmentId:apt, favorites:favs.map(f=>fav(...f,cur,fx)), includedByRoom:Object.fromEntries(inc.map(n=>[favs.find(f=>f[0]===n)[1],fid(n)]))};}
const RU=(favs,inc)=>({lang:'ru', apt:'flat215', b:basket('flat215','RUB',FX.RU,favs,inc)});
const UK=(favs,inc,limits)=>({lang:'en', apt:'demo-uk-215', b:basket('demo-uk-215','GBP',FX.UK,favs,inc), limits});
const S={
  'ru-empty':RU([],[]),
  'ru-part':RU([[1,'living','living',[['furniture',250000]]]],[1]),
  'ru-over':RU([[1,'living','living',[['furniture',450000]]],[2,'kitchen','kitchen',[['fitout',230000]]]],[1,2]),
  'uk-empty':UK([],[]),
  'uk-part':UK([[1,'living','living',[['furniture',1200]]],[2,'kitchen','kitchen',[['fitout',3000]]]],[1,2]),
  'uk-over-f':UK([[1,'living','living',[['furniture',5300]]],[2,'kitchen','kitchen',[['fitout',3000]]]],[1,2]),
  'uk-zero':UK([[1,'living','living',[['furniture',1200]]],[2,'kitchen','kitchen',[['fitout',600]]]],[1,2],{furniture:4500,fitout:0}),
};
const BAR=`(()=>{const c=document.getElementById('hmCert'); if(!c||c.hidden)return null; const q=s=>[...c.querySelectorAll(s)];
  const fit=e=>e.scrollWidth<=e.clientWidth+1;
  return {mode:c.dataset.mode, over:+c.dataset.over, head:(c.querySelector('.cs-t')||{}).innerText, legend:(c.querySelector('.cs-lg')||{}).innerText||'',
    group:q('.cs-bar[role=group]').length, meters:q('[role=meter]').map(m=>({name:m.getAttribute('aria-label'), now:+m.getAttribute('aria-valuenow'), max:+m.getAttribute('aria-valuemax'), text:m.getAttribute('aria-valuetext')})),
    hatch:q('.sg i.x').some(i=>parseFloat(i.style.width)>0), fits:q('.cs-t,.cs-lg .li,.cs-l').every(fit), h:Math.round(c.getBoundingClientRect().height)};})()`;
const BUB=`(()=>{const b=document.querySelector('#hmCert .vpl-bub'); if(!b||b.hidden)return null; const r=b.getBoundingClientRect(); return {text:b.innerText, r:[r.left,r.top,r.right,r.bottom].map(Math.round)};})()`;
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errs=[];
  async function open(name){const s=S[name];
    const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:PHONE?2:1,isMobile:PHONE,hasTouch:PHONE,locale:s.lang==='en'?'en-GB':'ru-RU'});
    const p=await ctx.newPage(); p.on('pageerror',e=>errs.push(name+': '+String(e)));
    await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
    // выдуманных коллекций на сервере нет — чтение отвечает сбоем (не «нет такой»): строки цен корзины остаются как заданы
    await p.route(/\/api\/collections(\?|\/)/,r=>r.request().method()==='GET'?r.fulfill({status:503,body:''}):r.continue());
    if(s.limits)await p.route(/\/api\/apartments\//,async r=>{const res=await r.fetch(); const j=await res.json();
      if(j.card&&j.card.incentive){j.card.incentive.limits=s.limits; j.card.incentive.total=s.limits.furniture+s.limits.fitout; j.card.certificate.amount=j.card.incentive.total;}
      await r.fulfill({response:res, body:JSON.stringify(j), headers:{...res.headers(),'content-type':'application/json'}});});
    await p.addInitScript(([k,v])=>{try{if(!sessionStorage.getItem('bbc')){localStorage.setItem(k,v); localStorage.setItem('remlab-sheet-hint-v1','1'); sessionStorage.setItem('bbc','1');}}catch(e){}},
      ['remlab-basket:v2:'+s.apt, JSON.stringify(s.b)]);
    await p.goto(BASE+'?lang='+s.lang+'&live=0',{waitUntil:'load',timeout:120000});
    await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&!!window.__basket&&!!window.__basket.totals()&&!document.getElementById('hmCert').hidden",null,{timeout:90000});
    await p.waitForTimeout(800); return p;}
  const shot=(p,n)=>p.screenshot({path:`${OUT}bar-${W}-${n}.png`});
  // 1. главная: состояния полосы
  for(const name of Object.keys(S)){
    const p=await open(name), s=await p.evaluate(BAR), en=S[name].lang==='en';
    const split=name.startsWith('uk')&&name!=='uk-zero';
    ok(`${name}: режим ${en?'split':'pooled'}`,s&&s.mode===(en?'split':'pooled'),s&&s.mode);
    ok(`${name}: группа и ${split?'два':'один'} meter`,s&&s.group===1&&s.meters.length===(split?2:1),s&&s.meters);
    if(split)ok(`${name}: части названы`,s.meters.map(m=>m.name).join('|')==='Furniture and appliances|Upgrades',s.meters.map(m=>m.name));
    ok(`${name}: текст не обрезан`,s&&s.fits,s&&s.head);
    if(name==='ru-over'){ok('ru-over: штриховка и «доплата 80 000 ₽» под полосой',s.hatch&&/доплата 80[\s  ]000 ₽/.test(s.legend),s.legend);}
    if(name==='uk-part')ok('uk-part: легенда — обе части цифрами',/Furniture( and appliances)?\s*1,200\s*\/\s*4,500/.test(s.legend)&&/Upgrades\s*3,000\s*\/\s*8,000/.test(s.legend)&&!s.hatch,s.legend);
    if(name==='uk-over-f')ok('uk-over-f: доплата £800 у мебели, улучшения без доплаты',s.hatch&&/top-up £800/.test(s.legend)&&/Upgrades\s*3,000\s*\/\s*8,000\s*$/m.test(s.legend),s.legend);
    if(name==='uk-zero')ok('uk-zero: обычная полоса, улучшения — доплата £600',s.meters.length===1&&s.meters[0].max===4500&&/top-up £600/.test(s.legend),s.legend);
    if(name==='ru-empty'||name==='uk-empty')ok(`${name}: выбрано 0, без штриховки`,!s.hatch&&s.meters.every(m=>m.now===0),s.meters);
    await shot(p,name);
    if(['ru-part','uk-part','uk-over-f','uk-zero'].includes(name)){
      await p.click('#hmCert .vpl-i'); await p.waitForTimeout(400); const u=await p.evaluate(BUB);
      const want=name.startsWith('ru')?/мебель, технику и улучшения/:name==='uk-zero'?/Upgrades — not included in the package/:/Furniture and appliances: £[\d,]+ of £4,500[\s\S]*Upgrades: £[\d,]+ of £8,000[\s\S]*No transfer between the budgets/;
      ok(`${name}: пузырь «i» — оба бюджета`,!!u&&want.test(u.text)&&u.r[0]>=0&&u.r[2]<=W,u&&u.text.replace(/\n/g,' | '));
      await shot(p,name+'-i');}
    if(PHONE&&(name==='ru-part'||name==='uk-part')){   // 2.34: высота липкой шапки после прокрутки
      await p.evaluate("scrollTo(0, document.documentElement.scrollHeight)"); await p.waitForTimeout(500);
      const st=await p.evaluate("({sticky:Math.round(Math.max(document.getElementById('hmHd').getBoundingClientRect().bottom, document.getElementById('styleTabs').getBoundingClientRect().bottom)), cert:Math.round(document.getElementById('hmCert').getBoundingClientRect().height)})");
      R.push(`ИНФО липкая шапка ${name} ${W}×${H}: ${st.sticky} px (полоса ${st.cert} px)`); await shot(p,name+'-sticky');}
    await p.context().close();}
  // 2. окно варианта: эта расстановка выведет за лимит — «выйдет за лимит на N», штриховка предпросмотра
  for(const [name,re] of [['ru-win',/выйдет за лимит на [\d\s  ]+₽/],['uk-win',/goes over the limit by £[\d,]+/]]){
    S[name]=name==='ru-win'?RU([[2,'kitchen','kitchen',[['fitout',560000]]]],[2]):UK([[3,'bedroom-1','bedroom',[['furniture',4300]]],[2,'kitchen','kitchen',[['fitout',3000]]]],[3,2]);
    const p=await open(name);
    await p.evaluate(()=>vwOpenVariant(0)); await p.waitForFunction(()=>!!document.querySelector('#vsum .cs'),null,{timeout:60000}); await p.waitForTimeout(1500);
    const v=await p.evaluate(()=>{const c=document.querySelector('#vsum .cs'), cr=c.getBoundingClientRect();
      return {lg:(c.querySelector('.cs-lg')||{}).innerText||'', xp:[...c.querySelectorAll('.sg i.xp')].some(i=>parseFloat(i.style.width)>0), meters:c.querySelectorAll('[role=meter]').length,
        inside:[...c.querySelectorAll('.cs-lg .li>*,.cs-t>*')].every(e=>{const r=e.getBoundingClientRect(); return !r.width||r.left>=cr.left-0.5&&r.right<=cr.right+0.5;})};});
    ok(`${name}: окно — «выйдет за лимит», штриховка предпросмотра`,re.test(v.lg)&&v.xp,v);
    ok(`${name}: подписи окна внутри плашки`,v.inside);
    await shot(p,name);
    await p.click('#vsum .vpl-i'); await p.waitForTimeout(400);
    ok(`${name}: пузырь окна открыт`,await p.evaluate(()=>{const x=document.getElementById('vplBub'); return !!x&&!x.hidden;}));
    await shot(p,name+'-i'); await p.context().close();}
  // 3. избранное: включить вариант сверх пакета — «Доплата N — подтвердить?»; мимо — корзина та же; «Подтвердить» — включён, доплата на полосе
  for(const [name,re,cf] of [['ru-dlg',/Доплата [\d\s  ]+₽ — подтвердить\?/,'Подтвердить'],['uk-dlg',/Top-up £[\d,]+ — confirm\?/,'Confirm']]){
    S[name]=name==='ru-dlg'?RU([[1,'living','living',[['furniture',200000]]],[4,'living','living',[['furniture',520000]]],[2,'kitchen','kitchen',[['fitout',150000]]]],[1,2])
      :UK([[1,'living','living',[['furniture',1200]]],[4,'living','living',[['furniture',5000]]],[2,'kitchen','kitchen',[['fitout',3000]]]],[1,2]);
    const p=await open(name);
    await p.evaluate(()=>window.__basket.open('living')); await p.waitForSelector('#favGrid [data-finc]',{timeout:30000});
    const inc0=await p.evaluate(()=>JSON.stringify(window.__basket.state().includedByRoom));
    await p.click(`#favGrid [data-finc="${fid(4)}"]`); await p.waitForSelector('#favPop',{timeout:10000});
    const t=await p.evaluate(()=>document.getElementById('favPop').innerText);
    ok(`${name}: диалог доплаты`,re.test(t),t.replace(/\n/g,' | '));
    await shot(p,name);
    await p.mouse.click(3,3); await p.waitForTimeout(400);    // мимо — закрыть без решения
    ok(`${name}: без подтверждения корзина та же`,await p.evaluate(()=>JSON.stringify(window.__basket.state().includedByRoom))===inc0);
    await p.click(`#favGrid [data-finc="${fid(4)}"]`); await p.waitForSelector('#favPop',{timeout:10000});
    await p.locator('#favPop button.primary').click(); await p.waitForTimeout(700);
    const after=await p.evaluate(()=>({inc:window.__basket.state().includedByRoom.living, lg:(document.querySelector('#hmCert .cs-lg')||{}).innerText||''}));
    ok(`${name}: «${cf}» — включён, на полосе доплата`,after.inc===fid(4)&&/(доплата|top-up)/.test(after.lg),after);
    await shot(p,name+'-done'); await p.context().close();}
  ok('ошибок страницы нет',!errs.length,errs.slice(0,3));
  fs.writeFileSync(`${OUT}bar-${W}.log`,R.join('\n')+'\n'); console.log(R.join('\n')); await b.close();
})().catch(e=>{console.log('CRASH',e); fs.writeFileSync(`${OUT}bar-${W}.log`,R.join('\n')+'\nCRASH '+e+'\n'); process.exit(1);});
