"""Таксономия классов: сырой англ. ярлык Grounding DINO → канонический класс → тип (опора/пол/стена/предмет).
Это ЛОГИКА-код (я владею), а НЕ переводы. Русские подписи берутся отдельно из авто-словаря OpenAI.
Словарь детекции и таблицу размеров в проде даёт фид Гдеслон; здесь — стартовый набор."""

# порядок важен: первое найденное ключевое слово в сыром ярлыке побеждает (специфичное раньше общего)
CANON_RULES = [
    ("office chair","office_chair"),("desk chair","office_chair"),("armchair","chair"),("chair","chair"),
    ("desk","desk"),("dining table","table"),("table","table"),
    ("sofa","sofa"),("couch","sofa"),
    ("mattress","mattress"),("bed","bed"),
    ("wardrobe","wardrobe"),("shelf","shelf"),
    ("computer monitor","monitor"),("monitor","monitor"),("television","tv"),("tv","tv"),
    ("laptop","laptop"),("keyboard","keyboard"),
    ("humidifier","humidifier"),("air purifier","purifier"),("purifier","purifier"),
    ("fan","fan"),("heater","heater"),("radiator","radiator"),
    ("floor lamp","lamp"),("lamp","lamp"),
    ("potted plant","plant"),("plant","plant"),
    ("box","box"),("books","books"),("book","books"),("bottle","bottle"),("cup","cup"),
    ("speaker","speaker"),("router","router"),
    ("mirror","mirror"),("picture","picture"),("frame","picture"),
    ("curtain","curtain"),("window","window"),("door","door"),
    ("rug","rug"),("carpet","rug"),("pillow","pillow"),("cushion","pillow"),
    ("bag","bag"),("clothes","clothes"),
]
SUPPORT={"desk","table","sofa","bed","mattress","wardrobe","shelf"}
FLOOR  ={"fan","heater","radiator","chair","office_chair","lamp","plant","humidifier","purifier"}   # стоят на полу, крупные
WALL   ={"mirror","picture","window","door","curtain","tv"}
# остальное (monitor,laptop,keyboard,cup,bottle,box,books,speaker,router,humidifier,purifier,bag,pillow,rug,clothes)
# = "item": мелочь на поверхностях (детектим, но не рисуем)

# стартовый словарь для open-vocab детекции (в проде — из категорий фида Гдеслон)
DETECT_VOCAB=("office chair. chair. desk. table. sofa. couch. bed. mattress. wardrobe. shelf. "
    "computer monitor. television. laptop. keyboard. humidifier. air purifier. fan. heater. radiator. "
    "floor lamp. lamp. potted plant. box. books. bottle. cup. speaker. router. mirror. picture frame. "
    "curtain. window. door. rug. pillow. bag. clothes.")

def canon(raw_label):
    """сырой ярлык (возможно слипшийся) → канонический класс или None."""
    low=raw_label.lower().replace("#","")
    for kw,cn in CANON_RULES:
        if kw in low: return cn
    return None

def kind(cn):
    if cn in SUPPORT: return "support"
    if cn in WALL: return "wall"
    if cn in FLOOR: return "floor"
    return "item"
