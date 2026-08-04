"""Ф3 — подбор реальных товаров, которые ВЛЕЗУТ в зону (наш моат = measured fit).
Схема каталога = как у фида Гдеслон (name,cat,w,d,h,price,shop,url). Реальный фид подставится сюда же.
Позже: ранжирование по визуальному сходству (DINOv3+SigLIP2 по кропу) — сейчас по «заполняет зону + цена»."""
from fit_check import fit_in_zone

# что чем заменять (категория товара под класс объекта)
CAT_MAP={"матрас":["кровать"],"кровать":["кровать"],"диван":["диван"],"стол":["стол"],
         "офисный стул":["кресло","стул"],"стул":["стул","кресло"],"кресло":["кресло"],"шкаф":["шкаф"]}

def match(zone_w,zone_d,target_ru,catalog,topn=3):
    cats=next((v for k,v in CAT_MAP.items() if k in target_ru.lower()),None)
    res=[]
    for p in catalog:
        if cats and p["cat"] not in cats: continue
        v=fit_in_zone(zone_w,zone_d,p["w"],p["d"])
        if not v["fits"]: continue
        res.append({**p,"note":v["note"],"use":(p["w"]*p["d"])/(zone_w*zone_d+1e-9)})
    res.sort(key=lambda p:(-p["use"],p["price"]))   # лучше заполняет зону, затем дешевле
    return res[:topn],cats
