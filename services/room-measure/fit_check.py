"""Ф2 — fit-check движок: детерминированная 2D-геометрия (Shapely), НЕ ML.
Вход: полигон комнаты (см) + footprint занятой мебели + товар Ш×Г. Выход: влезет / велик на N / где / что убрать.
Габариты товара — из фида (точные); зона/мебель — из плана пола."""
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
import numpy as np

def _poly(pts): return Polygon([(float(x),float(y)) for x,y in pts])

def fit_in_zone(zone_w, zone_d, prod_w, prod_d):
    """ЗАМЕНА: товар в зону старого объекта (2 ориентации). → dict(fits, overflow, note)."""
    for a,b in ((prod_w,prod_d),(prod_d,prod_w)):
        if a<=zone_w and b<=zone_d:
            return {"fits":True,"overflow":0,"note":f"влезет (зазор {round(min(zone_w-a,zone_d-b))} см)"}
    over=min(max(prod_w-zone_w,0)+max(prod_d-zone_d,0), max(prod_d-zone_w,0)+max(prod_w-zone_d,0))
    return {"fits":False,"overflow":round(over),"note":f"велик на ~{round(over)} см"}

def free_space(room_pts, occupied_polys, clearance=0):
    room=_poly(room_pts)
    if occupied_polys:
        occ=unary_union([_poly(p).buffer(clearance) for p in occupied_polys])
        return room.difference(occ)
    return room

def place(room_pts, occupied_polys, prod_w, prod_d, walkway=55, step=12):
    """ДОБАВИТЬ: найти позицию товара в свободном месте (с зазором walkway на проход). → dict|None."""
    free=free_space(room_pts, occupied_polys, 0)
    if free.is_empty: return None
    minx,miny,maxx,maxy=free.bounds
    for ang in (0,90):
        w,d=(prod_w,prod_d) if ang==0 else (prod_d,prod_w)
        wb,db=w+walkway, d+walkway                       # рамка с проходом
        y=miny+db/2
        while y<=maxy-db/2:
            x=minx+wb/2
            while x<=maxx-wb/2:
                r=box(x-wb/2,y-db/2,x+wb/2,y+db/2)
                if free.contains(r):
                    return {"x":round(x),"y":round(y),"ang":ang,"w":w,"d":d,
                            "poly":[(x-w/2,y-d/2),(x+w/2,y-d/2),(x+w/2,y+d/2),(x-w/2,y+d/2)]}
                x+=step
            y+=step
    return None

def place_or_remove(room_pts, occupied, prod_w, prod_d, walkway=55):
    """Полный вердикт: влезет / влезет если убрать X / не влезет никак."""
    occ_polys=[o["poly"] for o in occupied]
    p=place(room_pts, occ_polys, prod_w, prod_d, walkway)
    if p: return {"verdict":"влезет","place":p,"remove":None}
    for i,o in enumerate(occupied):                      # что убрать, чтобы влез
        rest=[occ_polys[j] for j in range(len(occupied)) if j!=i]
        p2=place(room_pts, rest, prod_w, prod_d, walkway)
        if p2: return {"verdict":"влезет если убрать","place":p2,"remove":o.get("ru","объект")}
    return {"verdict":"не влезет","place":None,"remove":None}
