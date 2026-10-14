import { chromium } from "@playwright/test";
const OUT=process.argv[2]; const BASE="https://remont-lab.online";
const b=await chromium.launch(); const ctx=await b.newContext({viewport:{width:1280,height:900},locale:'ru-RU'});
const pg=await ctx.newPage(); const errs=[]; const fails=[];
pg.on('console',m=>{ if(m.type()==='error') errs.push(m.text().slice(0,200)); });
pg.on('response',r=>{ if(r.status()>=400) fails.push(r.status()+' '+r.url().slice(0,120)); });
const t0=Date.now(); await pg.goto(BASE+'/demo/',{waitUntil:'networkidle',timeout:60000}); console.log('load ms',Date.now()-t0);
await pg.screenshot({path:OUT+'/01-load.png',fullPage:true});
const dump=async(label)=>{ const items=await pg.evaluate(()=>{
  const vis=e=>{const r=e.getBoundingClientRect();const st=getComputedStyle(e);return r.width>0&&r.height>0&&st.visibility!=='hidden'&&st.display!=='none';};
  return [...document.querySelectorAll('button,a,[role=button],[onclick],input,select,.tab,.card,.variant')].filter(vis).map(e=>({tag:e.tagName,id:e.id,cls:(e.className||'').toString().slice(0,40),text:(e.innerText||e.value||e.getAttribute('aria-label')||'').trim().replace(/\s+/g,' ').slice(0,50),href:e.getAttribute('href')||''})).filter(x=>x.text||x.href);
}); console.log('=== '+label+' ('+items.length+')'); for(const i of items) console.log(`${i.tag}#${i.id}.${i.cls} | ${i.text} ${i.href?'→'+i.href:''}`); };
await dump('page');
console.log('=== console errors', errs.length, errs.slice(0,8)); console.log('=== http fails', fails.length, fails.slice(0,8));
console.log('=== title', await pg.title(), '| h1', await pg.locator('h1').first().innerText().catch(()=>''));
await b.close();
