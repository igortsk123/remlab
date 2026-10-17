// d8: приёмка шторки v5 на проде глазами (телефон 375×667 и десктоп 1280): снимки начального вида, полной остановки,
// раздела «Отделка», возврата, карточек кухни (?debug=1&vroom=kitchen), EN. Запуск: node tools/ops/demo-walk/probe14.mjs <OUT>
import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const L=(...a)=>console.log(a.join(" "));
const b=await chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
async function run(name,url,vp,mobile,locale){
  const ctx=await b.newContext({viewport:vp,deviceScaleFactor:mobile?2:1,isMobile:mobile,hasTouch:mobile,locale});
  const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e).slice(0,120)));
  await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
  await p.goto(url,{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  await p.evaluate(()=>{try{sessionStorage.removeItem('remlab-sheet-pos')}catch(e){} openLiveWindow();});
  await p.waitForSelector('#vside',{timeout:60000}); try{await p.waitForFunction(()=>window.LIVE&&(LIVE.scene||LIVE.ok===false),null,{timeout:45000});}catch(e){} L('LIVE:',JSON.stringify(await p.evaluate(()=>({ok:LIVE.ok,why:LIVE.why,state:LIVE.state}))));  await p.waitForTimeout(5000);
  const geo=()=>p.evaluate(()=>{const sd=document.getElementById('vside'), r=sd.getBoundingClientRect(), pl=document.getElementById('vsum').getBoundingClientRect();
    const rows=[...document.querySelectorAll('#vside .vopts-row')].map(e=>e.textContent.trim().replace(/\s+/g,' ').slice(0,60));
    const order=[...document.querySelectorAll('#vscroll > *, #vscroll .vtop > *, #vscroll .vlist > *')].filter(e=>e.offsetParent!==null).map(e=>(e.id||e.className||e.tagName).toString().slice(0,24));
    return {pos:sd.dataset.pos, top:Math.round(r.top), h:Math.round(innerHeight-r.top), plateTop:Math.round(pl.top), rows, order, chip:(document.getElementById('vchip')||{}).textContent};});
  L(`\n== ${name}`); L('старт:',JSON.stringify(await geo())); await p.screenshot({path:`${OUT}/${name}-start.png`});
  if(mobile){ await p.evaluate(()=>vwSheet(3)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(300); L('полная:',JSON.stringify(await geo())); await p.screenshot({path:`${OUT}/${name}-full.png`});
    await p.evaluate(()=>vwSheet(2)); await p.waitForFunction(()=>document.getAnimations().length===0,null,{timeout:8000}).catch(()=>{}); await p.waitForTimeout(300); }
  const row=p.locator('#vside [data-opts]').first();
  if(await row.count()){ await row.click(); await p.waitForTimeout(1000); L('отделка:',JSON.stringify(await geo())); await p.screenshot({path:`${OUT}/${name}-opts.png`});
    const back=p.locator('#vside #vOptsBack, #vside .vopts-back').first(); if(await back.count()){await back.click(); await p.waitForTimeout(900); L('назад:',JSON.stringify(await geo()));} }
  const fit=p.locator('#vside [data-group="fitted"]').first();
  if(await fit.count()){ await fit.click(); await p.waitForTimeout(1000); L('встраиваемое:',JSON.stringify(await geo()));
    L('карточки:',JSON.stringify(await p.evaluate(()=>[...document.querySelectorAll('#vside .vfit-card, #vside [data-fit], #vside .vfl-chip')].map(e=>e.textContent.trim().replace(/\s+/g,' ').slice(0,70)))));
    await p.screenshot({path:`${OUT}/${name}-fitted.png`}); }
  L('кириллица в EN:', locale.startsWith('en')?String(await p.evaluate(()=>/[А-Яа-яЁё]/.test(document.getElementById('shot').innerText))):'—', 'ошибок:',errs.length, errs.slice(0,2).join(' | '));
  await ctx.close();
}
const B='https://remont-lab.online/demo/';
await run('se-ru', B+'?live=force', {width:375,height:667}, true, 'ru-RU');
await run('desk-ru', B+'?live=force', {width:1280,height:900}, false, 'ru-RU');
await b.close();
