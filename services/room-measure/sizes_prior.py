"""Само-проверка размеров по универсальному каталогу (object_catalog.py).
validate_dim: мягкая граница (avg±tol) = ok; между мягкой и жёсткой = коррекция (жёлт); вне min/max = ошибка (красн).
resolve_class: класс детектора → ключ каталога; если нет — ближайший синоним через GPT (кэш)."""
import os, json
from object_catalog import CATALOG

def validate_dim(cls, dim, value):
    """→ (status, conf, corrected). status: ok | corrected | flag_low | flag_high | unknown | no_value."""
    e=CATALOG.get(cls)
    if value is None: return "no_value",0.2,None
    if not e or dim not in e: return "unknown",0.4,value
    d=e[dim]; avg,tol,mn,mx=d["avg"],d["tol"],d["min"],d["max"]
    slo,shi=avg*(1-tol/100),avg*(1+tol/100)
    if slo<=value<=shi: return "ok",0.9,value
    if value<mn:  return "flag_low",0.28,value      # ниже жёсткой границы = «тупая ошибка»
    if value>mx:  return "flag_high",0.28,value      # выше жёсткой границы = «тупая ошибка»
    return "corrected",0.5,round(slo if value<slo else shi)   # между → к ближней мягкой границе (жёлт)

def in_catalog(cls): return cls in CATALOG

# --- резолвер синонимов (класс не в каталоге → ближайший ключ через GPT, кэш) ---
_SYN=f"{os.path.dirname(__file__)}/cache/synonyms.json"
def _load(): return json.load(open(_SYN)) if os.path.exists(_SYN) else {}
def _save(d): json.dump(d,open(_SYN,"w"),ensure_ascii=False,indent=0)
def resolve_class(cls):
    """канон-класс детектора → ключ каталога. Прямое совпадение или ближайший синоним (GPT, кэш). None если никак."""
    if cls in CATALOG: return cls
    cache=_load()
    if cls in cache: return cache[cls] or None
    import urllib.request
    keys=list(CATALOG.keys())
    sys=("Дан класс объекта из детектора. Верни СТРОГО один ближайший по смыслу ключ из списка (или 'none'). "
         f"Список: {', '.join(keys)}. Ответ строго JSON: {{\"key\":\"...\"}}")
    body=json.dumps({"model":"gpt-4o-mini","temperature":0,"response_format":{"type":"json_object"},
        "messages":[{"role":"system","content":sys},{"role":"user","content":cls}]}).encode()
    try:
        req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=body,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {os.environ['OPENAI_API_KEY']}"})
        k=json.loads(json.loads(urllib.request.urlopen(req,timeout=45).read())["choices"][0]["message"]["content"]).get("key","none")
    except Exception: k="none"
    k=k if k in CATALOG else None
    cache[cls]=k or ""; _save(cache)
    return k
