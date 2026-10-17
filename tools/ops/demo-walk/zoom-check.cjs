const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// «ФОТО» НА ТЕЛЕФОНЕ И ПРОСМОТР ВО ВЕСЬ ЭКРАН (план demo-09, дополнение 17.10): фото во всю область без размытых полос, кадрирование на
// мебели; галерея — 10 одиночных тапов не сдвигают картинку ни на пиксель, двойной тап — ×2,5 в точку, повторный — назад, свайп вниз — закрыть.
//   PROD=1 node tools/ops/demo-walk/zoom-check.cjs 375x667     — прод как есть;   LOCAL=1 … — локальная страница поверх прода
const LOCAL=process.env.LOCAL, OUT=process.env.OUT||require('os').tmpdir()+'/'; const [W,H]=(process.argv[2]||'375x667').split('x').map(Number);
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i||''));
(async()=>{const b=await pw.chromium.launch(); const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'});
const p=await ctx.newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
if(LOCAL)await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));
await p.goto('https://remont-lab.online/demo/?live=0&lang=ru',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&shots.length>0",null,{timeout:90000}); await p.waitForTimeout(2500);
// вариант с реалистичным снимком своей расстановки — окно в «Фото»
const vi=await p.evaluate(()=>{const c0=cur; for(let i=0;i<allVariants().length;i++){pickVariant(i); if(vwRealShots().length)return i;} pickVariant(c0); return -1;});
if(vi<0){console.log('нет варианта с фото своей расстановки — проверять нечего'); await b.close(); return;}
await p.evaluate(()=>{try{sessionStorage.setItem('remlab-sheet-pos','0')}catch(e){} openLiveWindow();}); await p.waitForTimeout(2500);
const ph=await p.evaluate(()=>{const im=document.querySelector('#shot .shotwrap img.vmain'), bl=document.querySelector('#shot .shotwrap img.vblur'), wr=im.parentNode.getBoundingClientRect(), r=im.getBoundingClientRect(), cs=getComputedStyle(im);
  return {mode:VW.mode, fit:cs.objectFit, pos:im.style.objectPosition, blur:bl?getComputedStyle(bl).display:'нет', img:[Math.round(r.width),Math.round(r.height)], wrap:[Math.round(wr.width),Math.round(wr.height)], url:im.src};});
ok('«Фото» во всю область без размытых полос',ph.mode==='photo'&&ph.fit==='cover'&&ph.blur==='none'&&ph.img[1]>=ph.wrap[1]-1,JSON.stringify(ph));
ok('кадрирование на мебели (сторона обрезки задана)',/%/.test(ph.pos||''),ph.pos);
await p.screenshot({path:OUT+`zoom-${W}-photo.png`});
await p.evaluate(u=>vwZoom(u),ph.url); await p.waitForTimeout(800);
const cdp=await ctx.newCDPSession(p);
const tap=async(x,y,hold=60)=>{await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]}); await p.waitForTimeout(hold); await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});};
const tr=()=>p.evaluate(()=>document.querySelector('#vzoom img').style.transform);
const t0=await tr(); let moved=0;
for(let i=0;i<10;i++){await tap(W/2+((i%3)-1)*40,H/2+((i%2)?30:-30)); await p.waitForTimeout(420); if(await tr()!==t0)moved++;}
ok('10 одиночных тапов — картинка не сдвинулась',moved===0,`сдвигов ${moved} · ${t0}`);
await tap(W*0.3,H*0.4); await p.waitForTimeout(120); await tap(W*0.3,H*0.4); await p.waitForTimeout(500); const t2=await tr();
ok('двойной тап — увеличение ×2,5',/scale\(2\.5\)/.test(t2),t2);
await tap(W/2,H/2); await p.waitForTimeout(120); await tap(W/2,H/2); await p.waitForTimeout(500); const t3=await tr();
ok('повторный двойной тап — назад к масштабу 1',/scale\(1\)/.test(t3),t3);
const sw=async()=>{await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:W/2,y:H*0.4}]});
  for(let i=1;i<=8;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:W/2,y:H*0.4+i*25}]}); await p.waitForTimeout(16);}
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await p.waitForTimeout(500);};
await sw(); ok('свайп вниз при масштабе 1 — закрыть',!(await p.evaluate(()=>document.getElementById('vzoom').classList.contains('on'))),'');
console.log(R.join('\n')); console.log('errs',errs.slice(0,3)); await b.close();})().catch(e=>{console.error(e);process.exit(1);});
