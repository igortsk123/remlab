#!/usr/bin/env python3
"""Волна 1: дозаполнение размеров tvoydom.ru. Прямые URL (без реф), 4-6с джиттер, HTML-only.
Идемпотентен: берёт из scrape_queue только status='new', можно перезапускать."""
import urllib.request, gzip, re, time, random, subprocess, sys, codecs

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
PSQL=["docker","exec","-i","remlab-devdb","psql","-U","remlab","-d","remlab","-q","-v","ON_ERROR_STOP=1"]
def sql(q):
    r=subprocess.run(PSQL,input=q,capture_output=True,text=True)
    if r.returncode!=0: print("SQL ERR",r.stderr[:300],flush=True)
    return r.stdout
def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html","Accept-Encoding":"gzip","Accept-Language":"ru-RU,ru;q=0.9"})
    with urllib.request.urlopen(req,timeout=40) as r:
        data=r.read()
        if r.headers.get('Content-Encoding')=='gzip' or data[:2]==b'\x1f\x8b':
            data=gzip.decompress(data)
        return r.geturl(), data.decode('utf-8',errors='ignore')
KEY=r'(Ширина|Глубина|Высота|Длина|Диаметр)'
PAIR=re.compile(r'"'+KEY+r'[^"]{0,25}"\s*:\s*"([\d][\d.,]{0,7})\s*(мм|см|м)?"')
COL={'Ширина':'w_cm','Глубина':'d_cm','Высота':'h_cm','Длина':'len_cm','Диаметр':'dia_cm'}
def tocm(v,u):
    x=float(v.replace(',','.'))
    if u=='мм': x/=10
    elif u=='м': x*=100
    elif x>400: x/=10
    return round(x,1) if 1<=x<=1500 else None
def parse(t):
    dec=codecs.decode(t.encode('ascii','ignore').decode('ascii'),'unicode_escape')
    out={}
    for k,v,u in PAIR.findall(dec):
        c=tocm(v,u)
        if c and COL[k] not in out: out[COL[k]]=c
    return out
rows=sql("copy (select shop_mid, external_id, direct_url from scrape_queue where status='new' order by case role when 'торшер' then 0 when 'лампа' then 1 when 'зеркало' then 2 when 'ковёр' then 3 else 5 end, external_id) to stdout with (format text)").strip().split('\n')
print(f"queue: {len(rows)}",flush=True)
fails=0; done=0
for line in rows:
    if not line: continue
    mid,eid,url=line.split('\t')
    try:
        final,html=fetch(url)
        if 'showcaptcha' in final or len(html)<5000:
            raise RuntimeError('captcha/short')
        dims=parse(html)
        if dims:
            sets=', '.join(f"{c} = coalesce({c}, {v})" for c,v in dims.items())
            sql(f"update products set {sets}, dims_source = coalesce(dims_source,'scrape') where shop_mid={mid} and external_id='{eid}';"
                f"update scrape_queue set status='done', note='{','.join(dims)}' where shop_mid={mid} and external_id='{eid}';")
        else:
            sql(f"update scrape_queue set status='nodims' where shop_mid={mid} and external_id='{eid}';")
        fails=0; done+=1
        if done%25==0: print(f"done {done}",flush=True)
    except Exception as e:
        fails+=1
        sql(f"update scrape_queue set status='fail', tries=tries+1, note='{str(e)[:80]}' where shop_mid={mid} and external_id='{eid}';")
        print("FAIL",url[:90],e,flush=True)
        if fails>=5:
            print("5 фейлов подряд — стоп (антибот?)",flush=True); sys.exit(1)
        time.sleep(30)
    time.sleep(random.uniform(4,6))
print("wave1 complete",flush=True)
