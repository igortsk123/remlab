const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КОРЗИНА СЕРТИФИКАТА (план demo-16 шаг 2, «Решения владельца 18.10»): 0 на старте; первый вариант комнаты включается сам; второй — вопрос
// «вместо «Гостиная #1»? Да/Нет»; в избранном — группы по комнатам и переключатель «Включить в сертификат» с пересчётом шкалы; окно —
// «Остаток с этой гостиной» на той же полосе; не влезает — в избранное без включения, «превышена сумма на N» и «Изменить расстановку»
// (лимит подменяется ответом карточки квартиры, страница не трогается); перенос избранного demo-15. Платного пути нет.
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
  if(o.limit)await p.route(/\/api\/apartments\//,async r=>{const res=await r.fetch(); const j=await res.json(); if(j.card&&j.card.certificate)j.card.certificate.amount=o.limit;
    await r.fulfill({response:res,body:JSON.stringify(j),headers:{...res.headers(),'content-type':'application/json'}});});
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
const saveHeart=async(p)=>{await p.click('#vFav'); await p.waitForSelector('#favName'); const nm=await p.inputValue('#favName'); await p.click('#favOk');
  await p.waitForFunction("window.__basket.state().favorites.length>0&&!document.querySelector('#favPop #favName')",null,{timeout:30000}).catch(()=>{}); await p.waitForTimeout(1200); return nm;};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const p=await page(b);
    const s0=await st(p);
    ok('0 на старте: в избранном пусто, включено 0, строки «Избранное» нет',s0.n===0&&s0.eligible===0&&s0.cert===0&&await p.evaluate(()=>document.getElementById('favHead').hidden),JSON.stringify(s0));
    // 1) первый вариант гостиной — включается сам
    await openWin(p,0);
    const plate0=await p.evaluate(()=>{const row=document.querySelector('#vsum .vpl-row'), pl=document.getElementById('vsum').getBoundingClientRect(), last=row.lastElementChild.getBoundingClientRect();
      return {head:row.querySelector('span').textContent, pv:(document.querySelector('#vsum .vpl-bar i.pv')||{}).style?.width, sum:+document.getElementById('vsum').dataset.sum,
        fits:row.scrollWidth<=row.clientWidth+1&&last.right<=pl.right+1&&row.querySelector('span').scrollWidth<=row.querySelector('span').clientWidth+1};});
    ok('плашка окна — в одну строку, не вылезает',plate0.fits,JSON.stringify(plate0));
    ok('окно до добавления: «С гостиной», светлая часть полосы — эта расстановка',/^С гостиной$/.test(plate0.head.trim())&&parseFloat(plate0.pv)>0,JSON.stringify(plate0));
    await p.screenshot({path:OUT+W+'-1-plate.png'});
    const n1=await saveHeart(p);
    const s1=await st(p);
    ok('имя по комнате «Гостиная #1»',n1==='Гостиная #1',n1);
    ok('первый вариант комнаты — включён сам, шкала пересчитана',s1.n===1&&Object.keys(s1.inc).length===1&&s1.eligible>0&&s1.cert===s1.eligible,JSON.stringify({inc:s1.inc,eligible:s1.eligible,cert:s1.cert}));
    ok('тост «Добавлено в избранное · Перейти →»',/Добавлено в избранное/.test(s1.toast)&&/Перейти/.test(s1.toast),s1.toast);
    const plate1=await p.evaluate(()=>document.querySelector('#vsum .vpl-row span').textContent);
    ok('после включения плашка — «Остаток» по корзине',/^Остаток$/.test(plate1.trim()),plate1);
    // 2) второй вариант той же комнаты — вопрос «вместо …?» → Да
    await p.evaluate(()=>document.getElementById('shotx').click()); await p.waitForTimeout(400);
    await openWin(p,1);
    await p.click('#vFav'); await p.waitForSelector('#favName'); const n2=await p.inputValue('#favName'); await p.click('#favOk');
    await p.waitForFunction("/вместо/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
    const ask=await st(p);
    ok('второй вариант гостиной — «Гостиная #2» и вопрос «вместо «Гостиная #1»?»',n2==='Гостиная #2'&&/вместо «Гостиная #1»/.test(ask.pop),n2+' | '+ask.pop.replace(/\n/g,' '));
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
    // 4) «Перейти →» из тоста — окно закрыто, «Избранное» раскрыто на гостиных
    await p.evaluate(()=>{const a=document.querySelector('#toast .toastact'); if(a)a.click(); else window.__basket.open('living');}); await p.waitForTimeout(900);
    const sec=await p.evaluate(()=>({win:document.getElementById('shot').classList.contains('on'), open:!document.getElementById('favSec').hidden,
      chips:[...document.querySelectorAll('#favChips [data-froom]')].map(x=>x.textContent), cards:document.querySelectorAll('#favGrid .favcard').length,
      checked:[...document.querySelectorAll('#favGrid [data-finc]')].filter(x=>x.checked).map(x=>x.dataset.finc)}));
    ok('«Перейти →» — окно закрыто, раздел раскрыт: «Гостиная · 3», три карточки, отмечена одна',!sec.win&&sec.open&&sec.chips.join()==='Гостиная · 3'&&sec.cards===3&&sec.checked.length===1&&sec.checked[0]===fav2,JSON.stringify(sec));
    await p.evaluate(()=>document.getElementById('favHead').scrollIntoView()); await p.waitForTimeout(300);
    await p.screenshot({path:OUT+W+'-3-favs.png'});
    // 5) переключить «Включить в сертификат» на первый вариант → пересчёт
    const fav1=await p.evaluate(()=>window.__basket.state().favorites.find(f=>f.displayName==='Гостиная #1').favoriteId);
    await p.click(`#favGrid [data-finc="${fav1}"]`); await p.waitForTimeout(700);
    const s5=await st(p);
    ok('переключатель в избранном: включён первый, шкала — снова его сумма',s5.inc.living===fav1&&s5.cert===s1.eligible,JSON.stringify({inc:s5.inc,cert:s5.cert,first:s1.eligible}));
    // 6) убрать включённый — включается старейший оставшийся (второй), если влезает
    await p.evaluate(id=>window.__fav.remove(id),fav1); await p.waitForTimeout(600);
    const s6=await st(p);
    ok('убрали включённый — включён старейший оставшийся',s6.n===2&&s6.inc.living===fav2,JSON.stringify({n:s6.n,inc:s6.inc}));
    ok('без ошибок страницы',!p.errs.length,p.errs.slice(0,2).join(' | '));
    await p.context().close();
    // 7) не влезает: сертификат 100 000 → в избранное без включения, «превышена сумма на N», «Изменить расстановку»
    const q=await page(b,{limit:100000});
    await openWin(q,0);
    await q.click('#vFav'); await q.waitForSelector('#favName'); await q.click('#favOk');
    await q.waitForFunction("/превышена сумма/.test((document.getElementById('favPop')||{}).innerText||'')",null,{timeout:30000}).catch(()=>{});
    const s7=await st(q), sum7=await q.evaluate(()=>+document.getElementById('vsum').dataset.sum);
    const over=Number((s7.pop.match(/на ([\d\s ]+)₽/)||[])[1]?.replace(/\D/g,''));
    ok('не влезает — в избранном без включения, «превышена сумма на N ₽» (N = сумма − лимит), кнопка «Изменить расстановку»',
      s7.n===1&&!Object.keys(s7.inc).length&&over===sum7-100000&&/Изменить расстановку/.test(s7.pop),JSON.stringify({n:s7.n,inc:s7.inc,over,sum7}));
    await q.screenshot({path:OUT+W+'-4-over.png'});
    await q.click('#favPop button.primary'); await q.waitForTimeout(700);
    ok('«Изменить расстановку» — остаёмся в окне этой расстановки',await q.evaluate(()=>document.getElementById('shot').classList.contains('on')));
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
    await e.click('#vFav'); await e.waitForSelector('#favName'); await e.click('#favOk'); await e.waitForTimeout(1500);
    const en2=await e.evaluate(()=>[(document.getElementById('toast')||{}).textContent||'',(document.getElementById('favPop')||{}).innerText||''].join(' '));
    const cyr=(en1+' '+en2).match(/[А-Яа-яЁё]+/g)||[];
    ok('EN: плашка окна и сообщения корзины без кириллицы',!cyr.length,cyr.slice(0,5).join(' ')+' | '+en1.slice(0,60)+' | '+en2.slice(0,80));
    await e.context().close();
  }finally{await b.close();}
  console.log(R.join('\n')); console.log(`итог: ${R.filter(x=>x.startsWith('OK')).length}/${R.length} · снимки ${OUT}${W}-*.png`);
  process.exitCode=R.some(x=>x.startsWith('FAIL'))?1:0;
})();
