#!/usr/bin/env python3
"""Фиды Гдеслона (распакованные feeds/f*/ *.xml) → products.tsv (COPY text format).
Затем: docker exec -i remlab-devdb psql -U remlab -d remlab -c "\\copy products (...) from stdin with (format text)" < products.tsv"""
import xml.etree.ElementTree as ET
import re, glob, json
NAMES={'110353':'h-f-l.ru','114082':'divanboss.ru','112098':'gipfel.ru','114667':'mnogomebeli.com','99272':'tvoydom.ru','116933':'nonton.ru','109882':'sanok.ru'}
NUM=re.compile(r'(\d+(?:[.,]\d+)?)')
def tocm(val):
    m=NUM.search(val or '')
    if not m: return None
    x=float(m.group(1).replace(',','.'))
    v=(val or '').lower()
    if 'мм' in v: x/=10
    elif re.search(r'(?<![а-яс])м\b|метр', v): x*=100
    elif 'см' not in v and x>400: x/=10
    return round(x,1) if 1<=x<=1500 else None
AX={'ширина':'w','глубина':'d','высота':'h','длина':'len','диаметр':'dia'}
dim3=re.compile(r'(\d{2,4})\s*[xх×*]\s*(\d{2,4})\s*[xх×*]\s*(\d{2,4})')
def esc(s):
    return s.replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r','')
def extract(params,name):
    out={};src=None
    for k,v in params.items():
        kl=k.lower().strip()
        for key,ax in AX.items():
            if kl==key or kl.startswith(key+' ') or kl.startswith(key+','):
                c=tocm(v)
                if c and ax not in out: out[ax]=c; src='param'
    if not out:
        m=dim3.search(name or '')
        if m:
            a,b,c=(float(x) for x in m.groups())
            if all(1<=x<=1500 for x in (a,b,c)): out={'w':a,'d':b,'h':c}; src='name'
    return out,src
out=open('products.tsv','w'); n=0
for path in sorted(glob.glob('feeds/f*/*.xml')):
    cats={}; parent={}
    for ev,el in ET.iterparse(path,events=('end',)):
        if el.tag=='category':
            cats[el.get('id')]=(el.text or '').strip(); parent[el.get('id')]=el.get('parentId')
        elif el.tag=='offer':
            mid=el.get('merchant_id'); eid=el.get('id') or el.get('article') or ''
            if not eid: el.clear(); continue
            params={(p.get('name') or '').strip():(p.text or '').strip() for p in el.findall('param')}
            nm=(el.findtext('name') or '').strip()
            dims,src=extract(params,nm)
            cid=el.findtext('categoryId')
            pn=[]; c=cid
            while c and c in cats and len(pn)<6: pn.append(cats[c]); c=parent.get(c)
            def ival(x):
                try: return str(int(float(x)))
                except: return None
            fields=[mid,eid,NAMES.get(mid,mid),cid,' / '.join(reversed(pn)) or None,
                nm[:500] or 'без названия',(el.findtext('vendor') or '').strip()[:200] or None,
                (el.findtext('url') or '').strip(),(el.findtext('picture') or '').strip() or None,
                ival(el.findtext('price')),ival(el.findtext('oldprice')),
                (el.findtext('charge') or '').strip() or None,
                't' if el.get('available','true')!='false' else 'f',
                *(str(dims[a]) if a in dims else None for a in ('w','d','h','len','dia')),
                src, json.dumps(params,ensure_ascii=False) if params else None]
            out.write('\t'.join('\\N' if f is None else esc(f) for f in fields)+'\n'); n+=1
            el.clear()
out.close(); print('rows',n)
