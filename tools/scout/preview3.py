#!/usr/bin/env python3
"""Перегенерация sets3-preview.html из финального sets3.json (после judge_apply).
Запуск: python3 preview3.py"""
import os, json

HERE=os.path.dirname(os.path.abspath(__file__))
sets=json.load(open(os.path.join(HERE,'sets3.json')))
rep={r['set']:r for r in json.load(open(os.path.join(HERE,'judge-report3.json')))} if os.path.exists(os.path.join(HERE,'judge-report3.json')) else {}
def esc(s): return s.replace('&','&amp;').replace('<','&lt;')
H=['<!doctype html><meta charset="utf-8"><title>Сеты v3 — по стилям</title><style>',
'body{font-family:system-ui;margin:20px;background:#faf7f2;color:#222}',
'.set{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin:18px 0}',
'.items{display:flex;flex-wrap:wrap;gap:10px}',
'.it{width:150px;border:1px solid #eee;border-radius:8px;padding:6px;font-size:11px;background:#fff}',
'.it img{width:100%;height:96px;object-fit:contain;background:#fff}',
'h2{margin:4px 0} .meta{color:#666;font-size:13px} a{color:#b06a4a}',
'.role{font-weight:600;color:#888;text-transform:uppercase;font-size:10px}',
'.why{color:#7a9;font-size:10px}</style>']
for i,s in enumerate(sets,1):
    c=s['capsule']; r=rep.get(i,{})
    jg=f' · судья {r.get("grade","—")}/10, стиль {r.get("style_grade","—")}/10' if r else ''
    H.append(f'<div class=set><h2>Сет {i} (v3): {s["band"]} м² — {s["tier"].capitalize()} — {s.get("style","")}</h2>')
    H.append(f'<div class=meta>стиль-фит {s.get("style_fit","—")}/10{jg} · дерево {c["wood"] or "—"} · металл {c["metal"] or "—"} · гамма {c["temp"]} · акценты {"+".join(s["pair"])} · пол {s["fill_pct"]}% · ≈ {s["total"]:,} ₽</div><div class=items>'.replace(',',' '))
    for role,it in s['items'].items():
        img=it['img'] if not it['img'].startswith('//') else 'https:'+it['img']
        dims=f"{it.get('w') or ''}×{it.get('d') or it.get('dia') or ''}"
        q=f" ×{it['qty']}" if it.get('qty',1)>1 else ''
        H.append(f'<div class=it><div class=role>{role}{q}</div><img loading=lazy src="{esc(img)}">'
                 f'<div>{esc(it["name"][:70])}</div><div>{dims} см · <b>{it["price"]:,} ₽</b></div>'.replace(',',' ')
                 +f'<div><a href="{esc(it["url"])}" target=_blank>открыть</a> · {it["shop"]}</div>'
                 +f'<div class=why>{esc((it.get("why") or "")[:120])}</div></div>')
    H.append('</div></div>')
open(os.path.join(HERE,'sets3-preview.html'),'w').write('\n'.join(H))
print(f"OK: sets3-preview.html ({len(sets)} сетов)")
