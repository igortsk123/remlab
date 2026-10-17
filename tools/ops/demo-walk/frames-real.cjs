const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// ЗАМЕР «КАДРЫ ИЗ БРАУЗЕРА» НА ПРОДЕ (план demo-10) — ПЛАТНО: одно настоящее фото нейросети. Вариант + смена пола (новое состояние,
// готового листа на сервере нет), нажатие «Сделать реалистичнее» → кадры из сцены → ответ: timing.ours / model / frames;
// затем ВТОРОЕ нажатие той же расстановки — должно прийти из кэша по серверному ключу (без второй оплаты).
//   node tools/ops/demo-walk/frames-real.cjs <номер варианта>          — запускать только по решению о трате
(async()=>{const vi=+(process.argv[2]||1); const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
// PHONE=1 — телефон в портрете (лист 3072×2048 из двух вертикальных видов, demo-10)
const PH=!!process.env.PHONE; const p=await (await b.newContext(PH?{viewport:{width:375,height:667},deviceScaleFactor:2,isMobile:true,hasTouch:true,locale:'ru-RU'}:{viewport:{width:1280,height:800},locale:'ru-RU'})).newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
await p.goto('https://remont-lab.online/demo/?live=force&lang=ru',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT&&shots.length>0",null,{timeout:90000}); await p.waitForTimeout(3000);
await p.evaluate(i=>{pickVariant(i); const g=devGroups().find(x=>x.kind==='flooring'); if(g)devSet(g.id,g.variants[2].id); openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');},vi);
await p.waitForFunction(()=>LIVE.scene&&LIVE.state==='ready',null,{timeout:200000}); await p.waitForTimeout(2000);
// ДЕНЬГИ — ТОЛЬКО ЕСЛИ КАДРЫ СНИМАЮТСЯ (17.10: кадры не снялись — два нажатия ушли старым путём и оба оплачены): сперва бесплатная
// проба съёмки и загрузки кадров; не вышло — выход без платного вызова
const probe=await p.evaluate(async()=>{const r=await vwCaptureViews(); return r?{size:r.size,ms:r.ms,sheet:r.sheet}:null;});
if(!probe){console.log('STOP: кадры из браузера не снимаются/не загружаются — платный вызов не делаю'); await b.close(); process.exit(1);}
console.log('проба кадров',JSON.stringify(probe));
for(const k of [1,2]){const t0=Date.now(); const n0=await p.evaluate('shots.length');
  await p.evaluate(()=>vwRealistic());
  await p.waitForFunction(()=>!VJ.job,null,{timeout:900000});
  const r=await p.evaluate(n0=>({cap:VW.lastCapture, err:VJ.err, mode:VW.mode, shot:(shots[n0]||{}), sid:curStateId()}),n0);
  console.log(`нажатие ${k}: ${Math.round((Date.now()-t0)/1000)} с · кадры ${JSON.stringify(r.cap)} · timing ${JSON.stringify(r.shot.timing)} · модель ${r.shot.model||'—'} · ${r.shot.url||r.err} · режим ${r.mode}`);
  if(!r.shot.timing||r.shot.timing.frames!=='browser'){console.log('STOP: кадры ушли не из браузера — второе нажатие не делаю'); break;}
  if(k===1)await p.evaluate(()=>vwMode('walk'));}
console.log('errs',errs.slice(0,3)); await b.close();})().catch(e=>{console.error(e);process.exit(1);});
