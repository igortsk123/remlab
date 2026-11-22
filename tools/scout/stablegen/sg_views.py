"""Подсказки по видам для StableGen (T-20261119-90/7, ⑪; по ответу Codex 20.11 `_intake/codex/2026-11-20-view-prompts-answer.md`): чистые функции без bpy — проверяются в unittest.

Принципы (общие для каталога, без привязки к товару):
  • утвердительные тексты («одна сплошная боковая панель в цвете корпуса»), а не отрицания: при cfg 1.0 негативного канала нет, а слово «no front pattern» само подсказывает нежелательный мотив;
  • класс поверхности — по ТОЧНОМУ `cat_role` через таблицу (нормализация: регистр, пробелы/дефисы/подчёркивания; без нечёткого поиска). Неизвестная роль → осторожный текст
    «продолжи материал соответствующей детали» + флаг `unknown_role` (никогда не правило «глухая панель»);
  • 5 зон по азимуту от «переда» (границы на половинах шага: 22,5° / 67,5° / 112,5° / 157,5°): front · quarter · side · rear_quarter · rear; левая/правая — по знаку;
  • «перёд» — направление камеры-зерна (камеры, ближайшей к фото по силуэту), а не допущение «−Y» (Codex: −Y — соглашение рендера стенда, не контракт формы);
  • фото товара — только первому виду (qwen_external_style_initial_only): тексты следующих видов продолжают материал уже покрашенных соседних участков, не ссылаются на «style reference»;
  • верх: кольцо камер приподнято (≈26°), верх виден на обычных боковых видах — формулировка про верх входит в тексты классов; «top view» — лишь при угле места > 60°."""
import json
import math
import os
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


def _words(role):
    return frozenset(norm_role(role).split())


ROLE_CLASS_BY_WORDS = {_words(r): c for r, c in ROLE_CLASS.items()}        # порядок слов роли не важен: «тумба прикроватная» = «прикроватная тумба» (Codex, свод паспортов 20.11)


def role_class(cat_role):
    """(класс, известна ли роль). Неизвестная роль → ('generic', False) — осторожный текст и флаг."""
    c = ROLE_CLASS.get(norm_role(cat_role)) or ROLE_CLASS_BY_WORDS.get(_words(cat_role))
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


def short_side_text(cat_role, cam_dir, front, back_suffix=''):
    """T-90/8 (T5): КОРОТКАЯ подпись направления только у видов сбоку/сзади — по углу камеры от переда, не по товару. |угол| < 60° → '' (подпись не меняется);
    60…120° → «the plain left|right side of the same <предмет>»; > 120° → «the plain back of the same <предмет>». Предмет — по роли из каталога (ROLE_NOUN), иначе «piece of furniture».
    Возвращает (текст, мета)."""
    ang = azimuth_deg(cam_dir, front)
    a = abs(ang)
    noun = role_noun(cat_role) or 'piece of furniture'
    meta = {'azimuth': round(ang, 1), 'zone': 'front' if a < 60 else ('side' if a <= 120 else 'back')}
    if a < 60.0:
        return '', meta
    if a <= 120.0:
        return f"the plain {'left' if ang > 0 else 'right'} side of the same {noun}", meta
    back_phrase = BACK_BY_CLASS.get(role_class(cat_role)[0])        # T-154/1: зад корпусной мебели — позитивно «одна сплошная задняя панель», без слов «двери/ручки» даже в отрицании
    if back_phrase:
        return f'the back of the same {noun}, {back_phrase}{back_suffix}', meta
    return f'the plain back of the same {noun}{back_suffix}', meta


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
    'торшер': 'floor lamp', 'лампа': 'table lamp', 'люстра': 'chandelier', 'ваза': 'vase', 'кашпо': 'planter', 'растение': 'plant', 'статуэтка': 'figurine',
    'ковер': 'rug', 'ковёр': 'rug', 'плед': 'throw blanket', 'шторы': 'curtains', 'бра': 'wall sconce', 'полка': 'wall shelf', 'зеркало': 'mirror', 'картина': 'painting', 'часы': 'clock', 'камин': 'fireplace',
}
ROLE_NOUN = {norm_role(k): v for k, v in ROLE_NOUN.items()}
ROLE_NOUN_BY_WORDS = {_words(k): v for k, v in ROLE_NOUN.items()}


def role_noun(cat_role):
    """Английское существительное роли; порядок слов не важен; нет в словаре → None (вызывающий ставит «piece of furniture»)."""
    return ROLE_NOUN.get(norm_role(cat_role)) or ROLE_NOUN_BY_WORDS.get(_words(cat_role))
_CAPTIONS_PATH = os.environ.get('SG_CAPTIONS_RULES') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rules', 'stablegen-captions.json')
_CAPTIONS_FALLBACK = {                       # запасные значения, если файла данных нет (как был встроенный словарь); рабочие тексты — в rules/stablegen-captions.json
    'material_phrase': {'velour': 'fine short-pile velour upholstery with uniform low-contrast nap, matte', 'velvet': 'ribbed corduroy upholstery with fine parallel cords, matte',
                        'rogozhka': 'coarse woven slubby linen-like upholstery, matte', 'chenille': 'soft chenille upholstery with a fine dense pile, matte',
                        'boucle': 'looped bouclé upholstery with a curly nubby texture, matte', 'leather': 'smooth leather upholstery with a fine grain and a soft sheen',
                        'wood_solid': 'solid wood with a visible natural grain', 'wood_veneer': 'wood veneer with a fine straight grain',
                        'ldsp': 'matte laminated chipboard finish with a fine uniform surface', 'mdf_film': 'smooth matte painted finish', 'metal': 'brushed metal', 'glass': 'clear glass'},
    'back_by_class': {'casework': 'one uninterrupted flat construction back panel in the carcass finish, simple fastening seams'},
    'parts': {'by_role': {}, 'colour_phrases': []},
}


def load_captions(path=None):
    """Подписи — данные (T-154/1): фразы материала и зада по классу. Нет файла — запасные значения."""
    try:
        with open(path or _CAPTIONS_PATH, encoding='utf-8') as fh:
            d = json.load(fh)
    except OSError:
        return _CAPTIONS_FALLBACK
    out = {k: d.get(k) or _CAPTIONS_FALLBACK[k] for k in _CAPTIONS_FALLBACK}
    out['material_phrase_bare'] = {k: x for k, x in (d.get('material_phrase_bare') or {}).items() if not k.startswith('_')}
    out['pattern_words'] = list(d.get('pattern_words') or [])
    out['colour_template'] = {k: x for k, x in (d.get('colour_template') or {}).items() if not k.startswith('_')}
    pt = d.get('parts') or {}
    out['parts'] = {'by_role': {norm_role(k): x for k, x in (pt.get('by_role') or {}).items() if not k.startswith('_')},       # T-161: цвет по частям — данные, не код
                    'colour_phrases': [(re.compile(rx), en) for rx, en in (pt.get('colour_phrases') or [])]}
    return out


CAPTIONS = load_captions()
MATERIAL_PHRASE = CAPTIONS['material_phrase']
BACK_BY_CLASS = CAPTIONS['back_by_class']
BARE_PHRASE = CAPTIONS['material_phrase_bare']
COLOUR_TEMPLATE = CAPTIONS['colour_template']
PARTS = CAPTIONS['parts']
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


# русские слова цвета: основа (без окончания) → английское слово; данные по типам, без ID товаров
COLOUR_STEMS = {
    'графит': 'graphite', 'графитов': 'graphite', 'антрацит': 'anthracite', 'антрацитов': 'anthracite', 'сер': 'grey', 'бел': 'white',
    'молочн': 'milky white', 'кремов': 'cream', 'бежев': 'beige', 'песочн': 'sand', 'чёрн': 'black', 'черн': 'black', 'син': 'blue', 'голуб': 'light blue',
    'зелен': 'green', 'зелён': 'green', 'оливков': 'olive', 'мят': 'mint', 'мятн': 'mint', 'изумрудн': 'emerald', 'коричнев': 'brown', 'красн': 'red',
    'бордов': 'burgundy', 'розов': 'pink', 'жёлт': 'yellow', 'желт': 'yellow', 'горчичн': 'mustard', 'оранжев': 'orange', 'терракотов': 'terracotta',
    'фиолетов': 'purple', 'лавандов': 'lavender', 'дуб': 'oak', 'дубов': 'oak', 'орех': 'walnut', 'ореховый': 'walnut', 'ясен': 'ash', 'ясеневый': 'ash',
    'венге': 'wenge', 'бук': 'beech', 'буков': 'beech', 'сосн': 'pine', 'сосновый': 'pine',
}
_COLOUR_ENDINGS = ('', 'ый', 'ий', 'ой', 'ая', 'яя', 'ое', 'ее', 'ые', 'ие', 'ого', 'ему', 'ым', 'ом', 'ых', 'их', 'ь', 'а', 'й')
COLOUR_WORDS = {st + e: en for st, en in COLOUR_STEMS.items() for e in _COLOUR_ENDINGS}      # слово целиком, не по началу («букле» ≠ «бук», «серия» ≠ «сер»)


def colour_from_texts(texts):
    """Первое слово цвета по списку текстов в порядке приоритета (название, затем параметры): слово целиком — в таблице. Нет — None."""
    for t in texts:
        for tok in re.split(r'[^\w]+', (t or '').casefold()):
            if tok in COLOUR_WORDS:
                return COLOUR_WORDS[tok]
    return None


def colours_in_order(texts):
    """Слова цвета по порядку появления в тексте (T-161, П6): слова таблицы COLOUR_WORDS и фразы данных `parts.colour_phrases` («светлое дерево»).
    Берётся первый текст, где два и больше РАЗНЫХ цвета; иначе первый, где есть хоть один; нет — []."""
    first = []
    for t in texts:
        s = unicodedata.normalize('NFKC', t or '').casefold()
        hits = []                                                               # (начало, конец, слово)
        for rx, en in PARTS['colour_phrases']:
            hits += [(m.start(), m.end(), en) for m in rx.finditer(s)]
        for m in re.finditer(r'\w+', s):
            if m.group() in COLOUR_WORDS and not any(a <= m.start() < b for a, b, _ in hits):
                hits.append((m.start(), m.end(), COLOUR_WORDS[m.group()]))
        out = []
        for _, _, en in sorted(hits):
            if en not in out:
                out.append(en)
        if len(out) >= 2:
            return out
        if out and not first:
            first = out
    return first


def parts_phrase(cat_role, colours, top_colours=None):
    """Подпись-композиция «with a white top and natural wood frame and legs» (T-161, П6) по шаблону роли из данных; None — шаблона нет или цвет один (прежняя подпись).
    `top_colours` — цвета из поля «цвет столешницы», если оно есть в каталоге: найденный среди `colours` — верх, другой — каркас и ножки."""
    tpl = PARTS['by_role'].get(norm_role(cat_role))
    cols = list(colours or [])
    if not tpl or len(cols) < 2:
        return None
    top = next((c for c in (top_colours or []) if c in cols), cols[0])
    rest = next((c for c in cols if c != top), None)
    return tpl.format(c1=top, c2=rest) if rest else None


def strip_colour(prompt):
    """T-90/11: подпись без слова цвета — для видов С фото (их ведёт фото, цвет из каталога им лишний и «серит» узор): «a graphite chest of drawers, matte …» → «a chest of drawers, matte …».
    Слово цвета берём из таблицы COLOUR_WORDS (значения), только в первой фразе до запятой; артикль a/an пересчитывается. Нет слова цвета — подпись как есть."""
    head, sep, tail = prompt.partition(',')
    m = re.match(r'^(an?)\s+(.*)$', head.strip(), flags=re.I)
    if not m:
        return prompt
    rest = m.group(2)
    for col in sorted(set(COLOUR_WORDS.values()), key=len, reverse=True):
        if rest.casefold().startswith(col + ' '):
            rest = rest[len(col) + 1:]
            art = 'an' if rest[:1].casefold() in 'aeiou' else 'a'
            return f'{art} {rest}{sep}{tail}'
    return prompt


def _art(word):
    return 'an' if word[:1].casefold() in 'aeiou' else 'a'


def add_colour(prompt, word, cat_role=None, parts=None):
    """Слово цвета в подпись без цвета: «a chair, matte …» → «a <цвет> chair, matte …» (данные colour_template: классу — слово только к основной поверхности:
    «a dining table with a white main surface», детали ведёт образец). Слова цвета уже есть / нет слова / нет артикля — подпись как есть.
    `parts` (T-161, П6) — готовая подпись-композиция («with a white top and natural wood frame and legs»): вместо слова цвета, «a dining table with a white top and …»."""
    if parts:
        head, sep, tail = prompt.partition(',')
        return f'{head.strip()} {parts}{sep}{tail}' if re.match(r'^an?\s', head.strip(), flags=re.I) and parts not in prompt else prompt
    if not word or strip_colour(prompt) != prompt:
        return prompt
    head, sep, tail = prompt.partition(',')
    m = re.match(r'^(an?)\s+(.*)$', head.strip(), flags=re.I)
    if not m:
        return prompt
    tpl = COLOUR_TEMPLATE.get(role_class(cat_role)[0]) if cat_role else None
    if tpl:
        return tpl.format(head=head.strip(), art=_art(word), colour=word) + sep + tail
    return f'{_art(word)} {word} {m.group(2)}{sep}{tail}'


def build_prompt(cat_role, material, colour=None, bare=False, parts=None):
    """Основной промпт из атрибутов каталога: «a <цвет> <предмет по роли>, <фраза материала>». Никогда не подменяется «заготовкой по ID»:
    неизвестная роль → «piece of furniture», неизвестный материал/цвет → честно без них. Возвращает (промпт, флаги)."""
    flags = []
    noun = role_noun(cat_role)
    if not noun:
        noun = 'piece of furniture'
        flags.append('unknown_role_noun')
    mc = material_class(material) if material else None
    if not mc:
        flags.append('unknown_material')
    if not colour:
        flags.append('unknown_colour')
    head = f'{colour} {noun}' if colour else noun
    if parts:                                                                    # T-161: цвет по частям — «a dining table with a white top and … frame and legs» (общая подпись, не разметка граней)
        head = f'{noun} {parts}'
    text = f"{'an' if head[0] in 'aeiou' else 'a'} {head}"
    if mc:
        text += f', {(BARE_PHRASE.get(mc) or MATERIAL_PHRASE[mc]) if bare else MATERIAL_PHRASE[mc]}'
    return text, flags


# ---- выбор камеры-зерна и порядок обхода (чистая логика; рендер силуэтов — в sg_drive)
SEED_TIE = 0.04      # разница IoU силуэтов, ниже которой они считаются неразличимыми


def natural_key(name):
    return tuple(int(p) if p.isdigit() else p.casefold() for p in re.split(r'(\d+)', name))


FRONT_HEMI_MIN_DOT = 0.01   # камера — в передней полусфере, если cos угла к направлению «лица» (−Y) > этого (строго меньше 90°)


def choose_seed(scores, dirs, prior_dir=(0.0, -1.0)):
    """Чистая логика выбора зерна: scores {камера: IoU}, dirs {камера: (x, y) от центра предмета}.
    T-90/10 (общее правило): силуэт спереди и сзади совпадает, IoU их не различает — поэтому зерно ищем ТОЛЬКО среди камер передней полусферы
    (лицо формы генератор ставит на prior_dir = −Y), IoU выбирает лишь угол внутри неё. Возвращает (камера, уверенно): уверенно=False, когда лучшая
    по IoU камера вообще была вне передней полусферы (правило переопределило IoU) — тогда перёд задан только допущением «−Y = лицо»."""
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best = ranked[0]
    if not dirs:
        return best[0], True

    def dot(n):
        x, y = dirs[n]
        h = math.hypot(x, y) or 1.0
        return (x * prior_dir[0] + y * prior_dir[1]) / h
    front = [(n, s_) for n, s_ in ranked if n in dirs and dot(n) > FRONT_HEMI_MIN_DOT]
    if not front:
        return best[0], True
    chosen = front[0][0]
    return chosen, chosen == best[0]


def alternating_order(dirs, front, seed):
    """T-90/9 (T5c): порядок «от переда попеременно в обе стороны, зад последним»: зерно, затем ±45°, ±90°, ±135°, 180° по УГЛАМ от переда (не списком имён).
    dirs — {камера: (dx, dy) от центра предмета}; сначала камеры с + (против часовой), потом − на каждой ступени."""
    def key(n):
        ang = azimuth_deg((dirs[n][0], dirs[n][1], 0.0), front)
        return (round(abs(ang) / 45.0), 0 if ang > 0 else 1, natural_key(n))
    rest = sorted((n for n in dirs if n != seed), key=key)
    return [seed] + rest


BACK_LIMIT_DEG = 150.0


def back_cameras(dirs, front, limit=BACK_LIMIT_DEG):
    """T-90/10: камеры «строго сзади» — |угол от зерна| > limit (по углу, не по имени)."""
    return [n for n in dirs if abs(azimuth_deg((dirs[n][0], dirs[n][1], 0.0), front)) > limit]


def side_sample_camera(dirs, front, order):
    """T-90/10 (T5e): уже сгенерированный вид бока для зада — |угол| в 60–120°, ближайший к 90° (при равенстве — раньше в порядке обхода)."""
    best, key = None, None
    for i, n in enumerate(order):
        if n not in dirs:
            continue
        a = abs(azimuth_deg((dirs[n][0], dirs[n][1], 0.0), front))
        if 60.0 <= a <= 120.0:
            k = (round(abs(a - 90.0), 1), i)
            if key is None or k < key:
                best, key = n, k
    return best


def side_sample_for(ang, angles, order, usable):
    """T-154/1 (Codex): образец материала заднему виду — готовый вид бока ТОГО ЖЕ знака угла (+135° → +90°, −135° → −90°); строго сзади (|угол| > 165°) — любой из двух ближайший к 90°.
    angles {камера: знаковый азимут}, order — порядок обхода, usable — множество камер, чьи виды ПРИНЯТЫ (отклонённые образцом не служат). Нет подходящего — None."""
    best, key = None, None
    for i, n in enumerate(order):
        if n not in usable or n not in angles:
            continue
        a = angles[n]
        if not (60.0 <= abs(a) <= 120.0):
            continue
        mismatch = 0 if (abs(ang) > 165.0 or a * ang > 0) else 1
        k = (mismatch, round(abs(abs(a) - 90.0), 1), i)
        if key is None or k < key:
            best, key = n, k
    return best


def camera_order(names, seed):
    """Обход по кругу от зерна: seed, следующая по номеру, … (Codex: один обход соседями, не «перёд → зад → бок»)."""
    ns = sorted(names, key=natural_key)
    i = ns.index(seed)
    return ns[i:] + ns[:i]


