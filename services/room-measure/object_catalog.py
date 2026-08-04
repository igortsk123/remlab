"""Универсальный справочник размеров объектов жилых помещений (см).
Размеры — seed из Neufert/dimensions.com/ГОСТ + общие стандарты; ПОГРЕШНОСТИ проставлены вручную (owner 2026-07-06).
На каждое измерение: avg (среднее), tol (обычный разброс %, → жёлтая коррекция), min/max (ЖЁСТКИЕ границы, вне = красная ошибка).
W=ширина, D=глубина, H=высота. Ключ = канонический англ. класс (см. taxonomy.py). В проде уточняется фидом Гдеслон."""
def _d(avg,tol,mn,mx): return {"avg":avg,"tol":tol,"min":mn,"max":mx}

CATALOG = {
 # ---- архитектура / общее (любая комната) ----
 "door":     {"room":["any"],"measure":["h","w"],"h":_d(200,6,180,230),"w":_d(80,25,55,120),"src":"gost"},
 "window":   {"room":["any"],"measure":["h","w"],"h":_d(140,35,50,200),"w":_d(110,50,40,250),"src":"neufert"},
 "sill":     {"room":["any"],"measure":["h"],"h":_d(85,18,60,105),"src":"neufert"},        # подоконник от пола
 "ceiling":  {"room":["any"],"measure":["h"],"h":_d(265,10,235,330),"src":"gost"},
 "radiator": {"room":["any"],"measure":["h","w","d"],"h":_d(60,45,30,95),"w":_d(80,55,40,200),"d":_d(12,60,8,20),"src":"gost"},
 "curtain":  {"room":["any"],"measure":["h","w"],"h":_d(210,30,140,320),"w":_d(150,60,60,320),"src":"neufert"},
 "mirror":   {"room":["any"],"measure":["h","w"],"h":_d(100,60,30,200),"w":_d(55,60,25,120),"src":"dimensions"},
 "picture":  {"room":["any"],"measure":["h","w"],"h":_d(50,70,15,150),"w":_d(50,70,15,150),"src":"dimensions"},
 "chandelier":{"room":["any"],"measure":["h"],"h":_d(45,70,10,120),"src":"dimensions"},
 "ac":       {"room":["any"],"measure":["w","h"],"w":_d(90,20,70,120),"h":_d(30,25,20,45),"src":"dimensions"},
 "rug":      {"room":["any"],"measure":["w"],"w":_d(200,60,60,400),"src":"neufert"},

 # ---- гостиная ----
 "sofa":     {"room":["living"],"measure":["w","d","h"],"w":_d(210,35,140,330),"d":_d(90,20,75,110),"h":_d(85,18,70,105),"src":"neufert"},
 "armchair": {"room":["living"],"measure":["w","h"],"w":_d(75,25,55,100),"h":_d(95,20,70,110),"src":"neufert"},
 "ottoman":  {"room":["living"],"measure":["w","h"],"w":_d(60,45,35,130),"h":_d(42,30,22,60),"src":"dimensions"},  # пуф
 "coffee_table":{"room":["living"],"measure":["w","h"],"w":_d(100,40,50,150),"h":_d(45,25,30,55),"src":"neufert"},
 "tv_stand": {"room":["living"],"measure":["w","h"],"w":_d(140,45,60,240),"h":_d(45,30,30,70),"src":"dimensions"},
 "tv":       {"room":["living"],"measure":["w","h"],"w":_d(120,45,55,210),"h":_d(70,45,35,120),"src":"dimensions"},
 "bookcase": {"room":["living","office"],"measure":["h","w"],"h":_d(185,35,60,240),"w":_d(80,55,40,300),"src":"neufert"},
 "shelf":    {"room":["any"],"measure":["h","w"],"h":_d(150,60,30,240),"w":_d(80,60,30,300),"src":"neufert"},
 "dresser":  {"room":["living","bedroom"],"measure":["w","h"],"w":_d(100,35,60,200),"h":_d(85,25,70,140),"src":"neufert"},  # комод
 "floor_lamp":{"room":["living","bedroom"],"measure":["h"],"h":_d(155,22,120,190),"src":"dimensions"},
 "plant":    {"room":["any"],"measure":["w","d","h"],"w":_d(40,50,20,80),"d":_d(40,50,20,80),"h":_d(80,85,15,220),"src":"dimensions"},
 "lamp":     {"room":["any"],"measure":["w","d","h"],"w":_d(35,40,20,55),"d":_d(35,40,20,55),"h":_d(45,70,20,190),"src":"dimensions"},

 # ---- спальня ----
 "bed":      {"room":["bedroom"],"measure":["w","d","h"],"w":_d(160,35,80,210),"d":_d(205,8,185,220),"h":_d(55,25,40,70),"src":"gost"},
 "mattress": {"room":["bedroom"],"measure":["w","d","h"],"w":_d(140,40,80,200),"d":_d(200,8,185,215),"h":_d(22,40,14,35),"src":"gost"},
 "nightstand":{"room":["bedroom"],"measure":["w","h"],"w":_d(45,35,35,70),"h":_d(50,30,35,70),"src":"neufert"},
 "wardrobe": {"room":["bedroom","hallway"],"measure":["w","h","d"],"w":_d(120,60,45,300),"h":_d(210,14,180,250),"d":_d(60,20,45,72),"src":"gost"},
 "vanity":   {"room":["bedroom"],"measure":["w","h"],"w":_d(100,35,60,160),"h":_d(75,10,68,82),"src":"neufert"},

 # ---- кухня ----
 "base_cabinet":{"room":["kitchen"],"measure":["h","d"],"h":_d(85,6,82,92),"d":_d(60,15,50,68),"src":"gost"},
 "wall_cabinet":{"room":["kitchen"],"measure":["h","d"],"h":_d(72,30,50,100),"d":_d(35,25,28,45),"src":"gost"},
 "countertop":{"room":["kitchen"],"measure":["h"],"h":_d(90,6,82,95),"src":"gost"},
 "fridge":   {"room":["kitchen"],"measure":["w","h","d"],"w":_d(60,20,50,92),"h":_d(180,22,140,210),"d":_d(65,15,55,80),"src":"dimensions"},
 "stove":    {"room":["kitchen"],"measure":["w","h"],"w":_d(60,20,45,92),"h":_d(85,10,80,95),"src":"gost"},
 "oven":     {"room":["kitchen"],"measure":["w","h"],"w":_d(60,10,55,70),"h":_d(60,15,45,75),"src":"dimensions"},
 "hood":     {"room":["kitchen"],"measure":["w"],"w":_d(60,25,45,92),"src":"dimensions"},
 "dishwasher":{"room":["kitchen"],"measure":["w","h"],"w":_d(60,12,45,70),"h":_d(82,8,80,95),"src":"dimensions"},
 "microwave":{"room":["kitchen"],"measure":["w","h"],"w":_d(50,20,40,60),"h":_d(30,25,25,40),"src":"dimensions"},
 "sink":     {"room":["kitchen"],"measure":["w"],"w":_d(60,40,35,120),"src":"dimensions"},
 "dining_table":{"room":["kitchen","living"],"measure":["w","d","h"],"w":_d(140,40,70,300),"d":_d(90,30,60,140),"h":_d(75,8,70,80),"src":"neufert"},
 "table":    {"room":["any"],"measure":["w","h"],"w":_d(120,45,50,300),"h":_d(75,10,68,82),"src":"neufert"},
 "chair":    {"room":["any"],"measure":["w","d","h"],"w":_d(45,20,38,58),"d":_d(52,20,42,62),"h":_d(95,15,80,118),"src":"neufert"},
 "office_chair":{"room":["office"],"measure":["w","d","h"],"w":_d(62,22,50,78),"d":_d(62,20,52,72),"h":_d(105,25,80,130),"src":"dimensions"},
 "bar_stool":{"room":["kitchen"],"measure":["h"],"h":_d(75,25,58,88),"src":"dimensions"},

 # ---- ванная / санузел ----
 "bathtub":  {"room":["bathroom"],"measure":["w","d","h"],"w":_d(170,20,140,190),"d":_d(75,15,70,90),"h":_d(60,20,50,75),"src":"gost"},
 "shower":   {"room":["bathroom"],"measure":["w","h"],"w":_d(90,20,80,120),"h":_d(200,10,185,225),"src":"dimensions"},
 "toilet":   {"room":["bathroom"],"measure":["w","h","d"],"w":_d(37,20,32,45),"h":_d(78,15,70,95),"d":_d(65,20,55,75),"src":"gost"},
 "washbasin":{"room":["bathroom"],"measure":["w","h"],"w":_d(55,30,40,80),"h":_d(85,10,78,92),"src":"gost"},
 "washing_machine":{"room":["bathroom","kitchen"],"measure":["w","h","d"],"w":_d(60,12,55,70),"h":_d(85,8,80,95),"d":_d(55,25,40,70),"src":"dimensions"},
 "towel_rail":{"room":["bathroom"],"measure":["h","w"],"h":_d(80,40,40,120),"w":_d(50,40,30,90),"src":"dimensions"},

 # ---- прихожая ----
 "shoe_rack":{"room":["hallway"],"measure":["w","h"],"w":_d(70,40,40,120),"h":_d(55,50,25,200),"src":"dimensions"},
 "console":  {"room":["hallway","living"],"measure":["w","h"],"w":_d(90,35,60,160),"h":_d(80,15,70,95),"src":"dimensions"},
 "coat_rack":{"room":["hallway"],"measure":["h"],"h":_d(180,25,150,200),"src":"dimensions"},

 # ---- детская ----
 "crib":     {"room":["kids"],"measure":["w","d","h"],"w":_d(65,15,60,80),"d":_d(125,15,110,145),"h":_d(95,15,80,115),"src":"gost"},
 "bunk_bed": {"room":["kids"],"measure":["h","w"],"h":_d(165,20,140,190),"w":_d(100,30,80,160),"src":"dimensions"},

 # ---- кабинет / офис ----
 "desk":     {"room":["office","kids"],"measure":["w","h","d"],"w":_d(120,40,60,200),"h":_d(75,8,70,80),"d":_d(60,25,45,80),"src":"neufert"},

 # ---- техника ----
 "monitor":  {"room":["office","living"],"measure":["w","h"],"w":_d(55,45,40,90),"h":_d(42,35,28,60),"src":"dimensions"},
 "laptop":   {"room":["any"],"measure":["w","h"],"w":_d(33,25,28,40),"h":_d(22,40,14,30),"src":"dimensions"},
 "keyboard": {"room":["any"],"measure":["w","h"],"w":_d(44,20,30,48),"h":_d(3,60,2,6),"src":"dimensions"},
 "tv":       {"room":["any"],"measure":["w","h"],"w":_d(120,45,55,210),"h":_d(70,45,35,120),"src":"dimensions"},
 "fan":      {"room":["any"],"measure":["w","d","h"],"w":_d(40,35,25,55),"d":_d(38,35,25,50),"h":_d(100,50,35,140),"src":"dimensions"},
 "heater":   {"room":["any"],"measure":["w","d","h"],"w":_d(30,40,20,60),"d":_d(28,40,18,45),"h":_d(55,45,35,80),"src":"dimensions"},
 "humidifier":{"room":["any"],"measure":["w","d","h"],"w":_d(24,40,16,40),"d":_d(24,40,16,40),"h":_d(30,50,18,55),"src":"dimensions"},
 "purifier": {"room":["any"],"measure":["w","d","h"],"w":_d(30,40,20,45),"d":_d(30,40,20,45),"h":_d(55,45,25,75),"src":"dimensions"},
 "speaker":  {"room":["any"],"measure":["h"],"h":_d(30,70,12,120),"src":"dimensions"},
 "router":   {"room":["any"],"measure":["h"],"h":_d(5,80,3,15),"src":"dimensions"},
 "vacuum":   {"room":["any"],"measure":["h"],"h":_d(30,50,18,120),"src":"dimensions"},
 "ironing_board":{"room":["any"],"measure":["h","w"],"h":_d(90,15,80,100),"w":_d(120,25,100,150),"src":"dimensions"},

 # ---- мелочь на поверхностях (детектим, не показываем; для само-проверки высот) ----
 "cup":      {"room":["any"],"measure":["h"],"h":_d(10,40,6,15),"src":"dimensions"},
 "bottle":   {"room":["any"],"measure":["h"],"h":_d(25,50,15,40),"src":"dimensions"},
 "box":      {"room":["any"],"measure":["h"],"h":_d(35,70,10,70),"src":"dimensions"},
 "books":    {"room":["any"],"measure":["h"],"h":_d(24,40,12,35),"src":"dimensions"},
 "bag":      {"room":["any"],"measure":["h"],"h":_d(40,60,15,70),"src":"dimensions"},
 "pillow":   {"room":["any"],"measure":["h"],"h":_d(16,50,8,30),"src":"dimensions"},
}
