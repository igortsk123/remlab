const fs=require('fs');const pw=require(process.cwd()+'/node_modules/.pnpm/'+fs.readdirSync('node_modules/.pnpm').find(d=>d.startsWith('playwright-core@'))+'/node_modules/playwright-core');
// МОДЕЛИ 3D ГРУЗЯТСЯ, ПОКА СМОТРЯТ ФОТО (demo-26, T-20261023-09/1). Замер «нажал 3D → сцена готова» и сколько моделей пошло по сети
// на «Фото» и после нажатия; видеоконтекст до «3D» (на телефоне его быть не должно); смена варианта до конца подгрузки — отмена лишнего
// и ни одной ошибки. Подмен запросов НЕТ (подмена в Playwright выключает кэш браузера, а мерим именно кэш): страница — через
// `stage-proxy.mjs` с `NO_EVENTS=1`, платного пути проба не трогает.
//   BASE=http://127.0.0.1:8797/demo/ WAIT=10000 OUT=<папка/> node tools/ops/demo-walk/preload-check.cjs 375x667 [метка]
// SWITCH=1 — сценарий «сменил вариант через 1,5 с на фото»; EXPECT=1 — проверять критерии подгрузки (для старой страницы — только замер)
const BASE=process.env.BASE||'http://127.0.0.1:8797/demo/', OUT=process.env.OUT||require('os').tmpdir()+'/', WAIT=+(process.env.WAIT||10000);
const [W,H]=(process.argv[2]||'375x667').split('x').map(Number), PHONE=W<=700, TAG=process.argv[3]||'run';
const SWITCH=process.env.SWITCH==='1', EXPECT=process.env.EXPECT==='1';
const R=[]; const ok=(n,c,i)=>R.push((c?'OK  ':'FAIL')+' '+n+' '+(i===undefined?'':typeof i==='string'?i:JSON.stringify(i)));
const INIT=()=>{window.__gl=[]; window.__loads=[]; window.__lt=[];
  const g=HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext=function(t,...a){ if(/webgl/.test(String(t)))window.__gl.push(Math.round(performance.now())); return g.call(this,t,...a); };
  try{new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__lt.push([Math.round(e.startTime),Math.round(e.duration)]))).observe({type:'longtask',buffered:true});}catch(e){}
  let last='';
  setInterval(()=>{const l=document.getElementById('vload'), t=l&&l.classList.contains('on')?((document.getElementById('vloadTxt')||{}).textContent||'')+(l.classList.contains('corner')?' [угол]':''):'';
    if(t!==last){last=t; window.__loads.push([Math.round(performance.now()),t]);}},40);};
(async()=>{const b=await pw.chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const ctx=await b.newContext({viewport:{width:W,height:H},deviceScaleFactor:2,isMobile:PHONE,hasTouch:PHONE,locale:'ru-RU'});
  await ctx.addInitScript(INIT);
  const p=await ctx.newPage(); const errs=[];
  p.on('pageerror',e=>errs.push(String(e))); p.on('console',m=>{if(m.type()==='error')errs.push('console: '+m.text());});
  // сеть моделей — по CDP: из кэша ли ответ, сколько байт пришло, что отменено
  const cdp=await ctx.newCDPSession(p); await cdp.send('Network.enable');
  // NETW=slow4g|fast4g — сеть телефона (пресеты Lighthouse / DevTools): на DEV сеть быстрая, и выигрыш подгрузки не виден
  const NP={slow4g:{latency:150,downloadThroughput:1638.4*1024/8,uploadThroughput:675*1024/8},fast4g:{latency:60,downloadThroughput:9000*1024/8,uploadThroughput:1500*1024/8}}[process.env.NETW||''];
  // прочее (оболочка комнаты, транскодер, движок): после «3D» — из кэша или по сети (304 на ревалидацию — тоже сеть, но без тела)
  const OTHER=new Map();
  cdp.on('Network.requestWillBeSent',e=>{if(!/\.glb(\?|$)/.test(e.request.url)&&!/^data:|^blob:/.test(e.request.url))OTHER.set(e.requestId,{url:e.request.url.replace(/^https?:\/\/[^/]+/,'').slice(0,90),t:Date.now()-t0,cache:false,st:0,kb:0});});
  cdp.on('Network.requestServedFromCache',e=>{const r=OTHER.get(e.requestId); if(r)r.cache=true;});
  cdp.on('Network.responseReceived',e=>{const r=OTHER.get(e.requestId); if(r){r.st=e.response.status; if(e.response.fromDiskCache||e.response.fromMemoryCache)r.cache=true;}});
  cdp.on('Network.loadingFinished',e=>{const r=OTHER.get(e.requestId); if(r)r.kb=Math.round(e.encodedDataLength/1024);});
  const NET=new Map(); const t0=Date.now();
  cdp.on('Network.requestWillBeSent',e=>{if(/\.glb(\?|$)/.test(e.request.url))NET.set(e.requestId,{url:e.request.url.replace(/^https?:\/\/[^/]+/,''),t:Date.now()-t0,cache:false,bytes:0,end:null,cancel:false,fail:''});});
  cdp.on('Network.requestServedFromCache',e=>{const r=NET.get(e.requestId); if(r)r.cache=true;});
  cdp.on('Network.responseReceived',e=>{const r=NET.get(e.requestId); if(r&&(e.response.fromDiskCache||e.response.fromMemoryCache))r.cache=true;});
  cdp.on('Network.loadingFinished',e=>{const r=NET.get(e.requestId); if(r){r.bytes=e.encodedDataLength; r.end=Date.now()-t0;}});
  cdp.on('Network.loadingFailed',e=>{const r=NET.get(e.requestId); if(r){r.cancel=!!e.canceled; r.fail=e.errorText; r.end=Date.now()-t0;}});
  const net=(from,to)=>[...NET.values()].filter(r=>r.t>=from&&r.t<(to??1e12));
  const sum=l=>({req:l.length, network:l.filter(r=>!r.cache&&!r.cancel&&!r.fail).length, cache:l.filter(r=>r.cache).length,
    cancel:l.filter(r=>r.cancel).length, fail:l.filter(r=>r.fail&&!r.cancel).length, kb:Math.round(l.reduce((s,r)=>s+(r.cache?0:r.bytes),0)/1024)});
  await p.goto(BASE+'?live=force&lang=ru',{waitUntil:'load',timeout:120000});
  await p.waitForFunction("typeof D!=='undefined'&&!!D&&!!FLAT",null,{timeout:90000});
  // вариант, у которого есть реалистичное фото этой расстановки (окно открывается в «Фото»)
  // (по реестру кадров, без открытия окна: окно варианта без фото открылось бы в «3D» и начало строить сцену до замера).
  // BIND=1 — фото варианта привязать к его текущему состоянию (только в браузере пробы): после смены номера состояния (demo-24, мягкое)
  // опубликованные фото до ночного прогрева не совпадают, и окно открывалось бы сразу в «3D»
  await p.waitForFunction(()=>shots.some(x=>x.quality==='realistic'),null,{timeout:30000}).catch(()=>{});
  if(process.env.BIND==='1')await p.evaluate(()=>allVariants().forEach(v=>{const st=variantStateOf(v);
    shots.filter(x=>x.quality==='realistic'&&x.url&&!x.svc&&!x.orphan&&x.vid===v.id).forEach(x=>{x.stateId=st;});}));
  const photoVariants=await p.evaluate(()=>allVariants().map((v,i)=>({i,st:variantStateOf(v)}))
    .filter(({st})=>shots.some(x=>x.quality==='realistic'&&x.url&&!x.svc&&!x.orphan&&x.stateId===st)).map(({i})=>i).slice(0,2)).catch(e=>String(e));
  ok('есть варианты с фото',Array.isArray(photoVariants)&&photoVariants.length>=1,photoVariants);
  if(!Array.isArray(photoVariants)||!photoVariants.length){console.log(R.join('\n')); await b.close(); process.exit(1);}
  // сеть до открытия (главная) в счёт не идёт
  // сеть телефона — с открытия окна варианта: мерим окно «Фото → 3D», а не загрузку главной
  if(NP)await cdp.send('Network.emulateNetworkConditions',{offline:false,...NP});
  await p.waitForTimeout(500); const tOpen=Date.now()-t0;
  await p.evaluate(i=>vwOpenVariant(i),photoVariants[0]);
  await p.waitForFunction(()=>VW.mode==='photo'&&document.getElementById('shot').classList.contains('on'),null,{timeout:20000});
  if(SWITCH){
    await p.waitForTimeout(1500);
    const j=photoVariants[1]; ok('второй вариант с фото для смены',j!=null,photoVariants);
    const tSw=Date.now()-t0;
    if(j!=null)await p.evaluate(i=>vwOpenVariant(i),j);
    await p.waitForTimeout(WAIT);
    const urls=await p.evaluate(()=>RemlabScene&&RemlabScene.sceneMeshUrls?RemlabScene.sceneMeshUrls({room:D.room,items:clone(items),decor:liveDecor(),base:location.href,lite:isTouchUI()}):[]).catch(()=>[]);
    const before=net(tOpen,tSw), after=net(tSw), done=new Set([...NET.values()].filter(r=>r.end!=null&&!r.cancel&&!r.fail).map(r=>r.url));
    const cancelled=[...NET.values()].filter(r=>r.cancel);
    console.log(JSON.stringify({tag:TAG,W,H,switch:{before:sum(before),after:sum(after),cancelled:cancelled.map(r=>r.url.split('/').pop()),pre:await p.evaluate(()=>typeof PRE!=='undefined'?PRE.n:null)}},null,0));
    if(EXPECT){
      ok('смена варианта: модели нового варианта скачаны все',urls.length>0&&urls.every(u=>done.has(u)),{need:urls.length,missing:urls.filter(u=>!done.has(u)).map(u=>u.split('/').pop())});
      ok('смена варианта: незаконченное отменено или докачано, ошибок сети нет',[...NET.values()].every(r=>!r.fail||r.cancel),[...NET.values()].filter(r=>r.fail&&!r.cancel).map(r=>r.fail));
    }
    ok('ошибок на странице нет',errs.length===0,errs.slice(0,5));
    console.log(R.join('\n')); await b.close(); process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);
  }
  await p.waitForTimeout(WAIT);
  const tClick=Date.now()-t0;
  const onPhoto=sum(net(tOpen,tClick));
  const glPhoto=await p.evaluate(()=>window.__gl.length);
  const ltPhoto=await p.evaluate(o=>window.__lt.filter(([s])=>s>=o),0);
  await p.screenshot({path:OUT+`preload-${TAG}-${W}-photo.png`});
  const pc0=await p.evaluate(()=>performance.now());
  await p.locator('#shot [data-vm="walk"]').click();
  await p.waitForFunction(()=>VW.mode==='walk'&&LIVE.state==='ready',null,{timeout:180000});
  const ms=Math.round(await p.evaluate(()=>performance.now())-pc0);
  const tReady=Date.now()-t0;
  await p.waitForTimeout(300); await p.screenshot({path:OUT+`preload-${TAG}-${W}-3d.png`});
  const loads=await p.evaluate(s=>window.__loads.filter(([t])=>t>=s).map(([t,x])=>[t-Math.round(s),x]),pc0);
  const models=loads.filter(([,x])=>/Загружаем модели \d+ из \d+/.test(x)).map(([t,x])=>t+' мс: '+x);
  const after=sum(net(tClick,tReady)), otherAfter=[...OTHER.values()].filter(r=>r.t>=tClick&&r.t<tReady).map(r=>r.url.split('?')[0].split('/').pop()+(r.cache?' [кэш]':' ['+r.st+' '+r.kb+'КБ]'));
  const res={tag:TAG,W,H,wait:WAIT,clickToReadyMs:ms,onPhoto,after3d:after,glOnPhoto:glPhoto,longtasksOnPhoto:ltPhoto.length,maxLongtask:Math.max(0,...ltPhoto.map(x=>x[1])),
    netw:process.env.NETW||'dev', otherAfter, loaderTexts:loads.map(([t,x])=>t+':'+x), modelsCounter:models, pre:await p.evaluate(()=>typeof PRE!=='undefined'?PRE.n:null)};
  console.log(JSON.stringify(res));
  fs.writeFileSync(OUT+`preload-${TAG}-${W}.json`,JSON.stringify({...res,net:[...NET.values()]},null,1));
  if(EXPECT){
    ok('на «Фото» модели скачаны заранее',onPhoto.network>0,onPhoto);
    ok('после «3D» по сети почти ничего (≤ 1 модели)',after.network<=1,after);
    ok('счётчика «Загружаем модели N из M» с N < M нет',!models.some(x=>{const m=x.match(/(\d+) из (\d+)/); return m&&+m[1]<+m[2];}),models);
    if(PHONE)ok('телефон: видеоконтекста до «3D» нет',glPhoto===0,glPhoto);
  }
  ok('ошибок на странице нет',errs.length===0,errs.slice(0,5));
  console.log(R.join('\n'));
  await b.close(); process.exit(R.some(x=>x.startsWith('FAIL'))?1:0);
})().catch(e=>{console.error(e); process.exit(2);});
