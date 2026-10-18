// fable-lead: приёмка demo-16 шаг 3 — липкая шапка, вкладка стиля снизу, возврат «назад» в окно, перезагрузка на избранном, EN
const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const OUT=process.argv[2]||'/tmp/'; const BASE='https://remont-lab.online/demo/';
const R=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const VPS={p375:[{width:375,height:667},true],p390:[{width:390,height:844},true],desk:[{width:1440,height:900},false]};
for(const name of (process.argv[3]||'p375,p390,desk').split(',')){const [vp,mobile]=VPS[name];
  const ctx=await b.newContext({viewport:vp,deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,locale:'ru-RU'}); const p=await ctx.newPage();
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  const out={}; p.on('crash',()=>console.error('CRASH at',out._step)); const step=s=>{out._step=s; global.STEP=s; global.OUT=out;};
  await p.goto(BASE+'?live=0',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(3000);
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos');}catch(e){}});
  await p.screenshot({path:OUT+'/p19-'+name+'-1top.png'});
  step('top');
  // 1. липкая шапка после прокрутки
  await p.evaluate(()=>scrollTo(0,1500)); await p.waitForTimeout(600);
  out.sticky=await p.evaluate(()=>{const R=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];};
    const hd=document.querySelector('.hm-hd'), tabs=document.querySelector('.hm-tabs');
    const stuck=[...document.querySelectorAll('body *')].filter(e=>{const s=getComputedStyle(e); if(!(s.position==='sticky'||s.position==='fixed'))return false; const r=e.getBoundingClientRect(); return r.top<=1&&r.height>0&&r.width>100;}).map(e=>[e.className||e.id, R(e)]);
    return {hd:R(hd), tabs:R(tabs), hdText:(hd?hd.innerText:'').replace(/\s+/g,' ').slice(0,80), tabsBottom:tabs?Math.round(tabs.getBoundingClientRect().bottom):null, stuck, y:scrollY};});
  await p.screenshot({path:OUT+'/p19-'+name+'-2sticky.png'});
  step('sticky');
  // 2. вкладка стиля снизу страницы → комнаты стиля под шапкой, адрес
  await p.evaluate(()=>scrollTo(0,document.body.scrollHeight)); await p.waitForTimeout(500);
  const tab=p.locator('#styleTabs [data-style]:not(.on)').last(); const tabId=await tab.getAttribute('data-style'); await tab.click(); await p.waitForTimeout(1200);
  out.tab=await p.evaluate((id)=>{const R=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.width),Math.round(b.height)];};
    const tabs=document.querySelector('.hm-tabs'), first=document.querySelector('.hm-room[data-style="'+id+'"]');
    return {id, url:location.search+location.hash, on:document.querySelector('#styleTabs .on')?.dataset.style, tabsBottom:tabs?Math.round(tabs.getBoundingClientRect().bottom):null, firstRoom:R(first), y:scrollY};},tabId);
  await p.screenshot({path:OUT+'/p19-'+name+'-3tab.png'});
  step('tab');
  // 3. окно варианта → ракурс 2 → шторка → ♡ → «Перейти →» → назад → вперёд → перезагрузка
  await p.evaluate(()=>{scrollTo(0,0); pickVariant(0); openLiveWindow();}); await p.waitForTimeout(6000);
  await p.evaluate(()=>{vwCamGo(1);}); await p.waitForTimeout(2500);
  if(mobile){await p.evaluate(()=>vwSheet(2)); await p.waitForTimeout(1200);}
  step('win'); out.before=await p.evaluate(()=>viewSnap());
  await p.click('#vFav'); await p.waitForSelector('#favName',{timeout:10000}); await p.click('#favOk');
  await p.waitForFunction("window.__basket.state().favorites.length>0&&!document.querySelector('#favPop #favName')",null,{timeout:30000}).catch(()=>{});
  const go=p.locator('#toast .toastact'); out.goVisible=await go.waitFor({state:'visible',timeout:12000}).then(()=>true).catch(()=>false);
  out.toast=await p.evaluate(()=>(document.getElementById('toast')||{}).textContent||'');
  if(out.goVisible){await go.click(); await p.waitForTimeout(1500);}
  out.afterGo=await p.evaluate(()=>({shotOn:document.getElementById('shot').classList.contains('on'), favSec:!document.getElementById('favSec').hidden, st:history.state, url:location.search+location.hash}));
  await p.screenshot({path:OUT+'/p19-'+name+'-4favs.png'});
  step('go'); await p.goBack(); await p.waitForTimeout(3500);
  out.afterBack=await p.evaluate(()=>Object.assign(viewSnap(),{shotOn:document.getElementById('shot').classList.contains('on'), favSec:!document.getElementById('favSec').hidden, cam:[...document.querySelectorAll('#shot button')].filter(b=>b.getAttribute('aria-pressed')==='true').map(b=>b.textContent.trim()).slice(0,3)}));
  await p.screenshot({path:OUT+'/p19-'+name+'-5back.png'});
  step('back'); await p.goForward(); await p.waitForTimeout(1500);
  out.afterFwd=await p.evaluate(()=>({shotOn:document.getElementById('shot').classList.contains('on'), favSec:!document.getElementById('favSec').hidden}));
  await p.reload({waitUntil:'load'}); await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(3000);
  out.afterReload=await p.evaluate(()=>({shotOn:document.getElementById('shot').classList.contains('on'), favSec:!document.getElementById('favSec').hidden, st:history.state}));
  await p.screenshot({path:OUT+'/p19-'+name+'-6reload.png'});
  step('reload');
  // 4. EN
  await p.goto(BASE+'?live=0&lang=en',{waitUntil:'load',timeout:120000}); await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(3000);
  out.en=await p.evaluate(()=>{const txt=[...document.querySelectorAll('.hm-hd, .hm-tabs, .hm-fav-row, .hm-fav-sec, #hmRooms, header, [role=dialog]')].map(e=>e.innerText||'').join('\n');
    const cyr=txt.match(/[^\n]*[А-Яа-яЁё]+[^\n]*/g)||[]; return {cyr:cyr.slice(0,8), favLabel:document.getElementById('hmFav')?.getAttribute('aria-label'), tabs:[...document.querySelectorAll('#styleTabs .hm-tab')].map(b=>b.textContent.trim())};});
  await p.evaluate(()=>{pickVariant(0); openLiveWindow();}); await p.waitForTimeout(5000);
  out.enWin=await p.evaluate(()=>{const txt=document.getElementById('shot').innerText||''; return (txt.match(/[^\n]*[А-Яа-яЁё]+[^\n]*/g)||[]).slice(0,8);});
  await p.screenshot({path:OUT+'/p19-'+name+'-7en.png'});
  console.log(name, JSON.stringify(out)); await ctx.close();
}
await b.close();})().catch(e=>{console.error('ERR at',global.STEP,e.message.slice(0,200)); console.log('PARTIAL',JSON.stringify(global.OUT));process.exit(1);});
