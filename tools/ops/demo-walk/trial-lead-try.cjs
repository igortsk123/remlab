// Сквозной прогон /try как агент (ведущий, TG 611; образец — `.t-lead-try.cjs` ведущего; T-20261110-24 — ключ наших машин):
//   TRIAL_OWN_KEY=… node tools/ops/demo-walk/trial-lead-try.cjs <картинка> <outdir> [ru|en] [текст размеров]
// /try → загрузка → страница ожидания (снимки по ходу) → «Открыть тур» → тур (главная + окно каждой комнаты), времена шагов.
// ПЛАТНО: каждая загрузка — настоящее задание на проде (VLM на DEV). Адрес — TRIAL_BASE (по умолчанию прод).
// Наши машины без лимита загрузки (`lib/trial/own-key.ts`): ключ — только из окружения, заголовком `x-trial-own-key` и только
// в `POST <TRIAL_BASE>/api/trial` (не в каждый запрос страницы — шрифты и сторонние адреса его не видят); в журнал не пишется.
const fs=require('fs');const path=require('path');const root=path.resolve(__dirname,'../../..')+'/';
const pnpm=root+'node_modules/.pnpm/';
const pw=require(pnpm+fs.readdirSync(pnpm).find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
const [IMG,OUT,LANG='ru',LISTING='']=process.argv.slice(2);
if(!IMG||!OUT){console.error('нужно: <картинка> <outdir> [ru|en] [текст размеров]');process.exit(2);}
fs.mkdirSync(OUT,{recursive:true});
const BASE=(process.env.TRIAL_BASE||'https://remont-lab.online').replace(/\/+$/,''), OWN=process.env.TRIAL_OWN_KEY||'';
const t0=Date.now(), T=()=>((Date.now()-t0)/1000).toFixed(1)+' с', log=(...a)=>console.log(T(),...a);
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const ctx=await b.newContext({viewport:{width:1280,height:800},locale:LANG==='en'?'en-GB':'ru-RU'});
if(OWN){ // заголовок — только загрузке плана на нашем адресе
  await ctx.route(u=>u.origin===new URL(BASE).origin&&u.pathname==='/api/trial',(route,req)=>req.method()==='POST'
    ?route.continue({headers:{...req.headers(),'x-trial-own-key':OWN}}):route.continue());
}
log(OWN?'ключ наших машин: есть':'ключ наших машин: нет (лимиты — как у всех)');
const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.goto(BASE+'/try?lang='+LANG,{waitUntil:'load',timeout:60000});
await p.locator('input[type="file"]').setInputFiles(IMG);
if(LISTING){await p.locator('details summary').first().click(); await p.locator('textarea[name="listing"]').fill(LISTING);}
await p.screenshot({path:OUT+'/01-form.png'});
await p.locator('form button[type="submit"]').click(); log('отправил');
await p.waitForURL(/\/try\/[A-Za-z0-9_-]{22}/,{timeout:120000}); log('страница ожидания',p.url().replace(/k=[^&]+/,'k=…'));
fs.writeFileSync(OUT+'/url.txt',p.url());
let shot=2, last='';
for(let i=0;i<120;i++){ // до 20 мин
  const txt=(await p.locator('body').innerText()).replace(/\s+/g,' ').slice(0,300);
  if(txt!==last){log('ожидание:',txt.slice(0,160)); await p.screenshot({path:`${OUT}/${String(shot++).padStart(2,'0')}-wait.png`}); last=txt;}
  if(await p.getByTestId('trial-open-tour').count())break;
  if(/\/tour\//.test(p.url()) && !/Подбираем мебель|Furnishing|Choosing furniture/.test(txt) && /товар|item/i.test(txt))break;
  await p.waitForTimeout(10000);
}
let href; const a=p.getByTestId('trial-open-tour');
if(await a.count()) href=new URL(await a.getAttribute('href'),p.url()).href; else if(/\/tour\//.test(p.url())) href=p.url();
if(!href){log('тур не готов за 20 мин'); await b.close(); return;}
log('тур готов'); fs.writeFileSync(OUT+'/tour.txt',href);
await p.goto(href.includes('live=')?href:href+(href.includes('?')?'&':'?')+'live=force',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D",null,{timeout:90000}).catch(()=>{}); await p.waitForTimeout(6000); log('тур открыт');
await p.screenshot({path:OUT+'/20-tour-home.png'});
const n=await p.evaluate(()=>typeof allVariants==='function'?allVariants().length:0);
for(let i=0;i<n;i++){
  await p.evaluate(i=>{pickVariant(i); openLiveWindow();},i); await p.waitForTimeout(5000);
  const info=await p.evaluate(()=>{const v=allVariants()[cur]||{};return (v.room&&v.room.name||v.name||'')+' · предметов '+((v.items||[]).length);});
  log('окно',i,info); await p.screenshot({path:`${OUT}/3${i}-room.png`});
  await p.keyboard.press('Escape'); await p.waitForTimeout(800);
}
log('ошибки страницы',errs.slice(0,5)); await b.close();})();
