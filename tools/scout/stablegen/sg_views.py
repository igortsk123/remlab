"""Подсказки по видам для StableGen (T-20261119-90/7, ⑪; по ответу Codex 20.11 `_intake/codex/2026-11-20-view-prompts-answer.md`): чистые функции без bpy — проверяются в unittest.

Принципы (общие для каталога, без привязки к товару):
  • утвердительные тексты («одна сплошная боковая панель в цвете корпуса»), а не отрицания: при cfg 1.0 негативного канала нет, а слово «no front pattern» само подсказывает нежелательный мотив;
  • класс поверхности — по ТОЧНОМУ `cat_role` через таблицу (нормализация: регистр, пробелы/дефисы/подчёркивания; без нечёткого поиска). Неизвестная роль → осторожный текст
    «продолжи материал соответствующей детали» + флаг `unknown_role` (никогда не правило «глухая панель»);
  • 5 зон по азимуту от «переда» (границы на половинах шага: 22,5° / 67,5° / 112,5° / 157,5°): front · quarter · side · rear_quarter · rear; левая/правая — по знаку;
  • «перёд» — направление камеры-зерна (камеры, ближайшей к фото по силуэту), а не допущение «−Y» (Codex: −Y — соглашение рендера стенда, не контракт формы);
  • фото товара — только первому виду (qwen_external_style_initial_only): тексты следующих видов продолжают материал уже покрашенных соседних участков, не ссылаются на «style reference»;
  • верх: кольцо камер приподнято (≈26°), верх виден на обычных боковых видах — формулировка про верх входит в тексты классов; «top view» — лишь при угле места > 60°."""
import math
import re
import unicodedata

# ---- роли → класс поверхности (точное совпадение после нормализации)
CLASS_ROLES = {
    'casework': ['шкаф', 'комод', 'тв-тумба', 'витрина', 'стенка', 'прикроватная тумба', 'тумба',
                 'wardrobe', 'chest_of_drawers', 'chest of drawers', 'dresser', 'cabinet', 'tv_stand', 'nightstand', 'sideboard'],
    'upholstered': ['диван', 'кресло', 'пуф', 'подушка', 'кровать',
                    'sofa', 'armchair', 'ottoman', 'pouf', 'cushion', 'bed'],
    'open_frame': ['стул', 'стеллаж', 'столик', 'стол обеденный',
                   'chair', 'shelving_unit', 'side_table', 'dining_table', 'coffee_table'],
    'continuous': ['люстра', 'лампа', 'торшер', 'ваза', 'кашпо', 'растение', 'статуэтка',
                   'chandelier', 'lamp', 'floor_lamp', 'vase', 'planter', 'plant', 'figurine'],
    'wall': ['бра', 'полка', 'зеркало', 'картина', 'часы', 'камин',
             'sconce', 'wall_shelf', 'mirror', 'painting', 'clock', 'fireplace'],
    'textile': ['ковёр', 'ковер', 'плед', 'шторы',
                'rug', 'carpet', 'throw', 'curtains'],
}


def norm_role(role):
    s = unicodedata.normalize('NFKC', str(role or '')).casefold().replace('ё', 'е')
    return re.sub(r'[\s_\-]+', ' ', s).strip()


ROLE_CLASS = {norm_role(r): c for c, rs in CLASS_ROLES.items() for r in rs}


def role_class(cat_role):
    """(класс, известна ли роль). Неизвестная роль → ('generic', False) — осторожный текст и флаг."""
    c = ROLE_CLASS.get(norm_role(cat_role))
    return (c, True) if c else ('generic', False)


# ---- зоны по азимуту
ZONES = ('front', 'quarter', 'side', 'rear_quarter', 'rear')


def azimuth_deg(cam_dir, front):
    """Знаковый азимут камеры от «переда» в градусах (−180…180): 0 — камера на переде, + — против часовой сверху (влево от предмета при взгляде на передок)."""
    x, y = cam_dir[0], cam_dir[1]
    h = math.hypot(x, y) or 1.0
    fh = math.hypot(front[0], front[1]) or 1.0
    cross = (front[0] * y - front[1] * x) / (h * fh)
    dot = (front[0] * x + front[1] * y) / (h * fh)
    return math.degrees(math.atan2(cross, dot))


def zone_of(ang):
    a = round(abs(ang), 6)
    if a < 22.5:
        return 'front'
    if a < 67.5:
        return 'quarter'
    if a < 112.5:
        return 'side'
    if a < 157.5:
        return 'rear_quarter'
    return 'rear'


def elevation_deg(cam_dir):
    x, y, z = cam_dir
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return math.degrees(math.asin(max(-1.0, min(1.0, z / n))))


# ---- тексты (по классам и зонам); {side} — «left»/«right»; без точки в конце: аддон добавляет «, <общий промпт>» после текста вида
_V = {
    'casework': {
        'front': 'Front view. {front_core}',
        'quarter': '{Side}-front three-quarter view. {front_core}; continue the carcass finish over the visible {side} side and the top finish over the visible top',
        'side': '{Side} side view. Render one continuous side panel in the carcass finish; continue the matching top finish across the visible top',
        'rear_quarter': 'Rear-{side} three-quarter view. Render a simple construction-appropriate back panel and the corresponding side panel; continue the matching top finish',
        'rear': 'Rear view. Render one simple construction-appropriate back panel in the carcass color family; continue the matching top finish across the visible top',
    },
    'upholstered': {
        'front': 'Front view. {front_core}',
        'quarter': '{Side}-front three-quarter view. {front_core}; continue the same upholstery over the visible {side} arm and side, keep exposed frame and legs in their matching materials',
        'side': '{Side} side view. Continue the corresponding upholstery over the arms, cushions and body with realistic construction seams; keep exposed frame and legs in their matching materials',
        'rear_quarter': 'Rear-{side} three-quarter view. Cover the finished back and the visible {side} arm in the corresponding upholstery with simple construction seams; keep exposed frame and legs in matching materials',
        'rear': 'Rear view. Cover the finished back in the corresponding upholstery with simple construction seams; keep exposed frame and legs in matching materials',
    },
    'open_frame': {
        'front': 'Front view. {front_core}',
        'quarter': '{Side}-front three-quarter view. {front_core}; keep all gaps and openings open',
        'side': '{Side} side view. Continue each visible structural component in the material of the corresponding component; keep all gaps and openings open',
        'rear_quarter': 'Rear-{side} three-quarter view. Continue the back, seat, shelf, frame and leg materials on the corresponding existing components; keep open spaces open',
        'rear': 'Rear view. Continue the back, seat, shelf, frame and leg materials on the corresponding existing components; keep open spaces open',
    },
    'continuous': {z: 'Continue each material and surface pattern around the same continuous component, preserving boundaries between components' for z in ZONES},
    'wall': {
        'front': 'Front view. {front_core}',
        'quarter': 'Oblique view. Continue the face, frame and fixture materials around their visible thickness; render shelf top and underside surfaces where present',
        'side': 'Oblique view. Continue the face, frame and fixture materials around their visible thickness; render shelf top and underside surfaces where present',
        'rear_quarter': 'Oblique view. Continue the face, frame and fixture materials around their visible thickness; render shelf top and underside surfaces where present',
        'rear': 'Rear mounting view. Render a simple uniform backing or mounting plate',
    },
    'textile': {
        'front': 'Reproduce the textile color and pattern on the visible face with woven texture and finished edges',
        'quarter': 'Reproduce the textile color and pattern on the visible face with woven texture and finished edges',
        'side': 'Reproduce the textile color and pattern on the visible face with woven texture and finished edges',
        'rear_quarter': 'Use a matching textile reverse in the same base colors with finished hems',
        'rear': 'Use a matching textile reverse in the same base colors with finished hems',
    },
    'generic': {z: 'Continue the material of each visible component from the corresponding adjacent painted component' for z in ZONES},
}

# «ядро» переда: для вида-зерна (фото есть) — «совпади с фото»; для остальных — «продолжай уже покрашенный перед»
_FRONT_CORE = {
    'casework': ('Match the doors, drawers, hardware and front-face finish to the style reference',
                 'Continue the doors, drawers, hardware and front-face finish consistently with the painted front components'),
    'upholstered': ('Match the upholstery, cushions, seams and exposed legs to the style reference',
                    'Continue the upholstery, cushions and seams consistently with the painted front'),
    'open_frame': ('Match the visible components and their materials to the style reference',
                   'Continue the visible components in the materials of the corresponding painted components'),
    'wall': ('Match the visible face, frame and fixture materials to the style reference',
             'Continue the face, frame and fixture materials consistently with the painted face'),
}


def view_text(cat_role, cam_dir, front, is_seed=False):
    """Текст вида для `scene.camera_prompts`. cam_dir — вектор от центра предмета к камере, front — горизонтальное направление «переда», is_seed — камера-зерно (получает фото товара).
    Возвращает (текст, {'class','known','zone','azimuth','elevation'})."""
    cls, known = role_class(cat_role)
    elev = elevation_deg(cam_dir)
    ang = azimuth_deg(cam_dir, front)
    zone = zone_of(ang)
    side = 'left' if ang > 0 else 'right'
    meta = {'class': cls, 'known': known, 'zone': zone, 'azimuth': round(ang, 1), 'elevation': round(elev, 1)}
    if elev > 60.0:
        return 'High view. Continue the corresponding materials over each upper surface; preserve part boundaries and openings', meta
    if elev < -60.0:
        return 'Underside view. Continue each component material on its underside; keep openings open', meta
    tpl = _V[cls][zone]
    core = _FRONT_CORE.get(cls, ('', ''))[0 if is_seed else 1]
    return tpl.format(front_core=core, side=side, Side=side.capitalize()), meta


# ---- шаблоны Qwen: СВОИ формулировки с ролями картинок НЕ работают (пробный прогон ⑪ 20.11 08:36: Qwen при «Render the same product on the guide» игнорировал фото и закрасил глубину
# плоским ярким цветом). Работает только штатная идиома аддона «Change and transfer the format of … image 1 … style from image 2 … Replace all solid magenta areas in image 2» — оставляем штатные
# шаблоны (QWEN_EDIT_LEGACY), меняем только то, что передаётся в {main_prompt} (тексты видов), и «фото только первому виду».
CUSTOM_PROMPT_PROPS = {
    'qwen_external_style_initial_only': True,
}


# ---- основной промпт из каталога: существительное по роли + фраза материала по классу (словарь материалов — data/flat3d/material-classes.json, id классов)
ROLE_NOUN = {
    'комод': 'chest of drawers', 'шкаф': 'wardrobe', 'тв-тумба': 'TV stand', 'витрина': 'display cabinet', 'стенка': 'wall unit', 'прикроватная тумба': 'bedside cabinet', 'тумба': 'cabinet',
    'диван': 'sofa', 'кресло': 'armchair', 'пуф': 'pouf', 'подушка': 'cushion', 'кровать': 'bed',
    'стул': 'chair', 'стеллаж': 'shelving unit', 'столик': 'side table', 'стол обеденный': 'dining table',
    'комод ': 'chest of drawers',
}
ROLE_NOUN = {norm_role(k): v for k, v in ROLE_NOUN.items()}
MATERIAL_PHRASE = {
    'velour': 'crushed velvet upholstery, soft marbled mottled pile, matte',
    'velvet': 'ribbed corduroy upholstery with fine parallel cords, matte',
    'rogozhka': 'coarse woven slubby linen-like upholstery, matte',
    'chenille': 'soft chenille upholstery with a fine dense pile, matte',
    'boucle': 'looped bouclé upholstery with a curly nubby texture, matte',
    'leather': 'smooth leather upholstery with a fine grain and a soft sheen',
    'wood_solid': 'solid wood with a visible natural grain',
    'wood_veneer': 'wood veneer with a fine straight grain',
    'ldsp': 'matte laminated chipboard finish with a fine uniform surface',
    'mdf_film': 'smooth matte painted finish',
    'metal': 'brushed metal',
    'glass': 'clear glass',
}
# русские названия и частые слова → id класса (точное совпадение после нормализации; нечёткого поиска нет)
MATERIAL_WORDS = {norm_role(w): c for c, ws in {
    'velour': ['велюр', 'велюра'], 'velvet': ['вельвет'], 'rogozhka': ['рогожка'], 'chenille': ['шенилл'], 'boucle': ['букле'],
    'leather': ['кожа', 'экокожа', 'эко кожа', 'искусственная кожа', 'натуральная кожа'],
    'wood_solid': ['дерево', 'массив', 'массив дерева'], 'wood_veneer': ['шпон', 'фанера', 'шпон и фанера'],
    'ldsp': ['лдсп', 'дсп', 'меламин'], 'mdf_film': ['мдф'], 'metal': ['металл'], 'glass': ['стекло'],
}.items() for w in ws}


def material_class(text):
    """id класса материала по id класса или русскому слову; None — неизвестно."""
    t = norm_role(text)
    if t in MATERIAL_PHRASE:
        return t
    return MATERIAL_WORDS.get(t)


def material_from_texts(texts):
    """Первый известный материал по списку текстов в порядке приоритета (параметр обивки/фасада, затем название): токены (слова) точным совпадением со словарём; «ткань» без вида не считается."""
    for t in texts:
        for tok in re.split(r'[^\w]+', norm_role(t)):
            mc = MATERIAL_WORDS.get(tok)
            if mc:
                return mc
    return None


def build_prompt(cat_role, material, fallback):
    """Основной промпт из атрибутов каталога. Возвращает (промпт, флаги). Неизвестная роль или материал → промпт `fallback` (как раньше) и флаг."""
    noun = ROLE_NOUN.get(norm_role(cat_role))
    mc = material_class(material) if material else None
    flags = []
    if not noun:
        flags.append('unknown_role_noun')
    if not mc:
        flags.append('unknown_material')
    if flags:
        return fallback, flags
    return f'a {noun}, {MATERIAL_PHRASE[mc]}', flags


# ---- выбор камеры-зерна и порядок обхода (чистая логика; рендер силуэтов — в sg_drive)
SEED_TIE = 0.04      # разница IoU силуэтов, ниже которой они считаются неразличимыми


def natural_key(name):
    return tuple(int(p) if p.isdigit() else p.casefold() for p in re.split(r'(\d+)', name))


def choose_seed(scores, dirs, prior_dir=(0.0, -1.0)):
    """Чистая логика выбора зерна: scores {камера: IoU}, dirs {камера: (x, y) от центра предмета}. Возвращает (камера, уверенно).
    Лучшая по IoU; если среди равных (в пределах SEED_TIE) есть камера из противоположной полусферы — перёд/зад неразличимы, берём ближайшую к prior_dir (−Y), уверенно=False."""
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best = ranked[0]
    if not dirs:
        return best[0], True
    cands = [n for n, s_ in ranked if best[1] - s_ < SEED_TIE]
    def unit(n):
        x, y = dirs[n]
        h = math.hypot(x, y) or 1.0
        return x / h, y / h
    bx, by = unit(best[0])
    if not [n for n in cands if unit(n)[0] * bx + unit(n)[1] * by < 0.0]:
        return best[0], True
    return min(cands, key=lambda n: -(unit(n)[0] * prior_dir[0] + unit(n)[1] * prior_dir[1])), False


def camera_order(names, seed):
    """Обход по кругу от зерна: seed, следующая по номеру, … (Codex: один обход соседями, не «перёд → зад → бок»)."""
    ns = sorted(names, key=natural_key)
    i = ns.index(seed)
    return ns[i:] + ns[:i]


