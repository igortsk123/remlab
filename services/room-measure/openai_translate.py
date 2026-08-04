"""Дешёвый перевод+чистка ярлыков Grounding DINO через OpenAI (текст, не картинка).
Вход: сырые англ. ярлыки (возможно слипшиеся/с мусором) → выход: короткое рус. существительное.
Кэш в cache/label_ru.json — повторно не платим."""
import os, json, urllib.request
CACHE="./cache/label_ru.json"
MODEL="gpt-4o-mini"   # дешёвая текстовая модель

def _load(): return json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def _save(d): json.dump(d,open(CACHE,"w"),ensure_ascii=False,indent=0)

def translate(raw_labels):
    """raw_labels: list[str] → dict{raw: рус_имя}. Кэшируется."""
    cache=_load(); need=sorted({r for r in raw_labels if r not in cache})
    if need:
        key=os.environ["OPENAI_API_KEY"]
        sys=("Ты ЧЕСТНО переводишь ярлыки детектора объектов на русский — НЕ угадывай класс, переводи что написано. "
             "Правила: (1) составное переводи составно ('wardrobe door'→'дверь шкафа', 'office chair'→'офисный стул'); "
             "(2) убирай только мусор токенизации — фрагменты '##...' и явные дубли-синонимы "
             "('sofa couch mattress'→'диван', '##ifier air purifier router'→'очиститель воздуха'); "
             "(3) им.падеж, нижний регистр, кратко. Ошибки детектора НЕ исправляй — человек поправит. "
             "Верни строго JSON {исходная_фраза: русский_перевод}.")
        body=json.dumps({"model":MODEL,"temperature":0,"response_format":{"type":"json_object"},
            "messages":[{"role":"system","content":sys},
                        {"role":"user","content":json.dumps(need,ensure_ascii=False)}]}).encode()
        req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=body,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"})
        r=json.loads(urllib.request.urlopen(req,timeout=60).read())
        got=json.loads(r["choices"][0]["message"]["content"])
        for k in need: cache[k]=got.get(k,k)
        _save(cache)
    return {r:cache.get(r,r) for r in raw_labels}

if __name__=="__main__":
    test=["sofa couch mattress","##ifier air purifier router","computer monitor television",
          "office chair chair","desk","fan","radiator","picture frame","wardrobe door","pillow clothes"]
    for k,v in translate(test).items(): print(f"  {k:32s} -> {v}")
