const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// КАДРЫ ИЗ БРАУЗЕРА ПО ВСЕМ ВАРИАНТАМ ПОДРЯД — БЕСПЛАТНО (demo-10, 17.10: после смены варианта снимок ловил мебель прежнего). Для каждого
// варианта: открыть окно, сразу снять оба вида, сверить модели сцены с расстановкой (`LIVE.scene.models()` против `items`), кадры — на диск.
//   SP=<папка с floorlib/> node tools/ops/demo-walk/capture-variants.cjs        — локальная страница и движок поверх прода
const SP=process.env.SP, OUT=process.env.OUT||require('os').tmpdir()+'/';
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const p=await (await b.newContext({viewport:{width:1280,height:800},locale:'ru-RU'})).newPage(); const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
if(SP){const F=JSON.parse(fs.readFileSync(SP+'/floorlib/scene.json','utf8')).file;
  await p.route(/\/demo\/lib\/scene\.json/,r=>r.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(SP+'/floorlib/scene.json','utf8')}));
  await p.route(/\/demo\/lib\/scene\.[0-9a-f]+\.js/,r=>r.fulfill({status:200,contentType:'text/javascript',body:fs.readFileSync(SP+'/floorlib/'+F,'utf8')}));
  await p.route(/\/demo\/(\?.*)?$/,r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:fs.readFileSync('tools/scout/flat215-demo/index.html','utf8')}));}
await p.route(/\/api\/events/,r=>r.fulfill({status:204,body:''}));
const got=[]; await p.route(/\/api\/render\/frame/,r=>{const buf=r.request().postDataBuffer()||Buffer.alloc(0); const id=require('crypto').createHash('sha256').update(buf).digest('hex'); got.push({id,buf}); r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id})});});
await p.goto('https://remont-lab.online/demo/?live=force&lang=ru',{waitUntil:'load',timeout:120000});
await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000}); await p.waitForTimeout(2000);
const n=await p.evaluate('allVariants().length'); let bad=0;
for(let i=0;i<n;i++){
  const r=await p.evaluate(async i=>{pickVariant(i); openLiveWindow(); if(VW.mode!=='walk')vwMode('walk');
    for(let k=0;k<600&&!LIVE.scene;k++)await new Promise(ok=>setTimeout(ok,100));
    const cap=await vwCaptureViews();
    // сверка: подпись модели каждого предмета сцены ↔ товар (msid) в расстановке
    const m=LIVE.scene.models(), mism=[];
    items.forEach((it,k)=>{const sig=m[k]; const ms=it.sku&&it.sku.msid; if(sig!==undefined&&ms&&!String(sig).includes(String(ms)))mism.push(it.role+': '+String(sig).slice(0,40)+' ≠ '+ms);});
    return {style:allVariants()[i].style, cap:!!cap, mism};},i);
  const fr=got.slice(-2); fr.forEach((f,k)=>fs.writeFileSync(OUT+`cv-${i}-C${k+1}.jpg`,f.buf));
  if(!r.cap||r.mism.length)bad++;
  console.log((r.cap&&!r.mism.length?'OK  ':'FAIL')+` ${r.style}: кадры ${r.cap?'сняты':'НЕТ'}, расхождений модели/товара ${r.mism.length} ${r.mism.slice(0,3).join(' | ')}`);}
console.log('errs',errs.slice(0,2)); await b.close(); process.exit(bad?1:0);})().catch(e=>{console.error(e);process.exit(1);});
