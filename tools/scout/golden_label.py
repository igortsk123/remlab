#!/usr/bin/env python3
"""Разметка золотой выборки моделью — со строгой схемой ответа и дискретными шкалами.

Два применения: черновой эталон сильной моделью и прогон кандидатов на дешёвую роль. Промпт,
схема и разбор одни и те же — иначе сравнение моделей меряет разницу промптов, а не моделей.

Почему шкалы дискретные, а не числа 0–1: вербализованные числовые оценки у моделей плохо
калиброваны и скачут между прогонами (техническая ревизия, 2026-08-05). «Средняя / высокая»
воспроизводится, «0.65» — нет.

Почему схема strict: она гарантирует форму ответа, но НЕ проверяет диапазоны и перечисления
значений вне enum — числовые границы всё равно валидируем в коде (ADR-0067).

  ~/venvs/scout/bin/python golden_label.py --model gpt-5.6-terra --out golden-ref.json
  ~/venvs/scout/bin/python golden_label.py --model gpt-5-nano --limit 20 --dry
"""
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, 'golden.json')

# Роли ровно те, что различает каталог (view lr_roles) плюс «другое». Если роли нет в списке,
# модель честно отвечает «другое», а система считает это расхождением — так мы теряли 43 шкафа
# и все шторы на ровном месте (замер 2026-08-05).
ROLES = ['диван', 'кресло', 'пуф', 'столик', 'стол обеденный', 'стул', 'тв-тумба', 'комод',
         'стеллаж', 'витрина', 'стенка', 'шкаф', 'полка', 'ковёр', 'торшер', 'лампа', 'люстра',
         'бра', 'камин', 'кашпо', 'ваза', 'статуэтка', 'растение', 'зеркало', 'часы', 'шторы',
         'плед', 'подушка', 'другое']
SUBTYPES = ['шкаф_распашной', 'шкаф_купе', 'пенал', 'подставка_для_ног', 'дополнительное_сиденье', 'пуф_стол', 'пуф_хранение', 'банкетка',
            'журнальный_стол', 'приставной_стол', 'консоль', 'обеденный_стол', 'письменный_стол',
            'комод_хранение', 'тумба_под_тв', 'сервант', 'книжный_стеллаж', 'стеллаж_перегородка',
            'витрина', 'настенная_полка', 'напольный_светильник', 'настольная_лампа',
            'подвесной_светильник', 'мягкая_мебель', 'текстиль', 'декор', 'не_определён']
MATERIALS = ['ткань', 'велюр', 'рогожка', 'шенилл', 'экокожа', 'кожа', 'дерево', 'ЛДСП', 'МДФ',
             'металл', 'стекло', 'камень', 'пластик', 'ротанг', 'керамика', 'не_определён']
COLOURS = ['белый', 'бежевый', 'серый', 'чёрный', 'коричневый', 'синий', 'зелёный', 'жёлтый',
           'красный', 'розовый', 'фиолетовый', 'оранжевый', 'разноцветный', 'не_определён']
SHAPES = ['прямоугольная', 'квадратная', 'круглая', 'овальная', 'угловая', 'другая']
BASES = ['ножки', 'цоколь', 'колёса', 'подвесной', 'без_основания', 'не_определён']
LEVEL = ['нет', 'низкая', 'средняя', 'высокая']
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
FLAGS = ['нет_описания', 'размеры_неполные', 'название_общее', 'текст_противоречив',
         'не_для_гостиной', 'нет']
# Что вообще изображено. Проверка 30 карточек глазами (2026-08-05) показала: среди «фото товара»
# попадаются инфографика с характеристиками, интерьерная сцена и голая панель — по ним стиль
# недостоверен, а модель всё равно отвечает уверенно. Поле было в исходном документе, я его
# ошибочно выбросил из схемы.
IMAGE_TYPES = ['товар_на_фоне', 'товар_в_интерьере', 'инфографика', 'несколько_товаров',
               'непонятно', 'фото_не_смотрел']
# Что ещё берём с фотографии, раз уж мы за неё платим. Список продиктован тем, ГДЕ у нас болит:
#   * ракурс — весь конвейер вклейки считает карточку фронтальной и гадает угол по геометрии
#     сцены; знать угол съёмки значит вклеивать точнее и реже платить за 3D-модель;
#   * фон и логотип — вырезка ломается на брендированных подложках (НОНТОН), а логотип магазина
#     уезжает в кадр вместе с товаром;
#   * посторонние предметы — на фото стеллажа стоят книги и ваза, и генератор дорисовывает их
#     в комнату как часть товара;
#   * пропорции — фото ловит мусорные размеры фида: «столик 100×35» с квадратным видом;
#   * отделка и узор — сочетаемость в комплекте: матовое дерево и глянцевый хром «одинаково
#     современные» по стилю, но рядом не стоят.
VIEW_ANGLES = ['фронтально', 'три_четверти', 'сбоку', 'сверху', 'деталь_крупно', 'неясно']
BACKGROUNDS = ['белый', 'студийный_градиент', 'цветной', 'брендированный', 'интерьер', 'неясно']
FINISHES = ['матовый', 'глянцевый', 'текстурный', 'зеркальный', 'неясно']
PATTERNS = ['однотонный', 'полоска', 'клетка', 'геометрия', 'цветочный', 'текстура_дерева',
            'мрамор', 'другой', 'неясно']
PROPS = ['похоже', 'не_похоже', 'не_проверить']
PHOTO_QUALITY = ['годится_эталоном', 'мелкое_или_мутное', 'не_годится']
# Признаки, из которых СОБИРАЕТСЯ стиль (style_rules.json). Модель отвечает на «что видишь»,
# а стиль выводят правила: прямая классификация стиля по одному предмету даёт 0.41-0.49 точности
# (Bonn Furniture Styles, arXiv 1812.03570), а признаковый разбор — принятый и объяснимый подход
# (ACM TIST 10.1145/3065951, arXiv 2412.13947). Ошибку в «ножки конические» видно глазами,
# ошибку в «стиль сканди» — нет.
LEGS = ['конические', 'прямые', 'точёные', 'резные', 'тонкий_металл', 'цоколь', 'скрытые',
        'колёса', 'не_видно']
LINES = ['прямые', 'мягко_скруглённые', 'изогнутые', 'неясно']
ORNAMENT = ['нет', 'молдинги', 'резьба', 'капитоне', 'плетение', 'гвоздики', 'неясно']
HARDWARE = ['скрытая', 'латунь', 'чёрный_металл', 'хром', 'дерево', 'не_видно']
PROPORTIONS = ['приземистый', 'сбалансированный', 'вертикальный', 'неясно']
FORMALITY = ['бытовая', 'нейтральная', 'парадная']


def _enum(name, vals):
    return {'type': 'string', 'enum': vals, 'description': name}


SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['role', 'functional_subtype', 'materials', 'primary_color', 'shape', 'base_type',
                 'visual_mass', 'warmth', 'decorativeness', 'styles', 'style_strength', 'flags',
                 'image_type', 'photo', 'pack_qty'],
    'properties': {
        'role': _enum('роль предмета в гостиной', ROLES),
        # СКОЛЬКО ПРЕДМЕТОВ В ОДНОЙ ПОКУПКЕ (владелец 01.09). Стулья магазины продают
        # комплектами по 2/4/6, и в фиде этого нет — только в названии, описании или на фото.
        # Спрашиваем ЗДЕСЬ, в общем запросе, а не отдельным вызовом: за карточку мы платим один
        # раз, и лишний вопрос в том же ответе не стоит ничего.
        'pack_qty': {'type': 'integer', 'minimum': 1, 'maximum': 12,
                     'description': 'сколько ОДИНАКОВЫХ предметов входит в одну покупку. '
                                    'Обстановка на фото (стол, посуда, ковёр) не в счёт — её '
                                    'продают отдельно. Один предмет с разных сторон или в разных '
                                    'цветах — это 1. Сомневаешься — 1'},
        'functional_subtype': _enum('функция, а не категория', SUBTYPES),
        'materials': {'type': 'array', 'items': _enum('материал', MATERIALS)},
        'primary_color': _enum('основной цвет', COLOURS),
        'shape': _enum('форма в плане', SHAPES),
        'base_type': _enum('на чём стоит', BASES),
        'visual_mass': _enum('визуальная масса', ['лёгкая', 'средняя', 'тяжёлая']),
        'warmth': _enum('теплота', ['холодная', 'нейтральная', 'тёплая']),
        'decorativeness': _enum('декоративность', LEVEL),
        'styles': {'type': 'object', 'additionalProperties': False, 'required': STYLES,
                   'properties': {s: _enum(f'пригодность для стиля {s}', LEVEL) for s in STYLES}},
        'style_strength': _enum('насколько выражен характер',
                                ['нейтральный', 'умеренный', 'характерный']),
        'flags': {'type': 'array', 'items': _enum('проблемы карточки', FLAGS)},
        'image_type': _enum('что изображено на картинке', IMAGE_TYPES),
        'photo': {
            'type': 'object', 'additionalProperties': False,
            'required': ['view_angle', 'background', 'has_watermark', 'extra_objects',
                         'cropped', 'finish', 'pattern', 'proportions_match', 'quality',
                         'legs', 'lines', 'ornament', 'hardware', 'proportions', 'formality'],
            'properties': {
                'view_angle': _enum('под каким углом снят товар', VIEW_ANGLES),
                'background': _enum('фон карточки', BACKGROUNDS),
                'has_watermark': {'type': 'boolean', 'description': 'логотип или подпись магазина'},
                'extra_objects': {'type': 'boolean',
                                  'description': 'на фото есть посторонние предметы (книги, декор)'},
                'cropped': {'type': 'boolean', 'description': 'товар обрезан краем кадра'},
                'finish': _enum('отделка поверхности', FINISHES),
                'pattern': _enum('узор или фактура', PATTERNS),
                'proportions_match': _enum('вид на фото похож на заявленные размеры', PROPS),
                'quality': _enum('годится ли фото эталоном для генерации', PHOTO_QUALITY),
                'legs': _enum('какие опоры видно', LEGS),
                'lines': _enum('характер линий силуэта', LINES),
                'ornament': _enum('декор на предмете', ORNAMENT),
                'hardware': _enum('ручки и видимая фурнитура', HARDWARE),
                'proportions': _enum('пропорции силуэта', PROPORTIONS),
                'formality': _enum('насколько предмет парадный', FORMALITY),
            },
        },
    },
}

SYS = (
    'Ты размечаешь карточки мебели для подбора комплектов в гостиную. Отвечай ТОЛЬКО по схеме.\n'
    'Правила:\n'
    '1. Роль — что это за предмет в гостиной. Если предмет не для гостиной (садовая мебель, '
    'офисное кресло, детская) — role="другое" и флаг "не_для_гостиной".\n'
    '2. Функциональный подтип важнее категории: банкетка и кресло-мешок — не пуф; пуф высотой '
    'вровень со столиком и с твёрдой столешницей — "пуф_стол"; тумба под телевизор — не комод.\n'
    '3. Пригодность к стилю — НЕЗАВИСИМЫЕ оценки: предмет может одинаково подходить сканди, '
    'джапанди и минимализму. Это не распределение, сумма не важна.\n'
    '4. Не выдумывай: чего в тексте нет — "не_определён". Размеры по фотографии не угадывают.\n'
    '5. style_strength: "нейтральный" — подойдёт куда угодно; "характерный" — сильно диктует стиль.\n'
    '9. В блоке photo опиши, ЧТО ВИДИШЬ, а не что это за стиль. Смотри по списку: опоры '
    '(конические, прямые, точёные, резные, тонкий металл, глухой цоколь, скрытые, колёса); '
    'линии силуэта (прямые, мягко скруглённые, изогнутые); декор (нет, молдинги, резьба, '
    'стёжка-капитоне, плетение, декоративные гвоздики); ручки и фурнитура (скрытая, латунь, '
    'чёрный металл, хром, дерево); пропорции (приземистый, сбалансированный, вытянутый вверх); '
    'парадность (бытовая вещь, нейтральная, парадная). Чего не видно на фото — "не_видно" или '
    '"неясно"; не додумывай по названию.\n'
    '8. Блок photo заполняй ТОЛЬКО по картинке. Без картинки: view_angle="неясно", '
    'background="неясно", quality="не_годится", остальное — "неясно"/false. '
    'view_angle — под каким углом снят сам предмет: строго спереди, вполоборота (видно перед и '
    'бок), строго сбоку, сверху или это крупный фрагмент. proportions_match — похож ли вид на '
    'заявленные Ш×Г×В: если сказано 100×35, а на фото предмет почти квадратный, это "не_похоже". '
    'extra_objects — есть ли на фото вещи, которые НЕ продаются (книги, посуда, декор, растения).\n'
    '7. Если картинки нет — image_type="фото_не_смотрел". Если на картинке не сам товар на '
    'чистом фоне, а интерьерная сцена, схема с характеристиками или несколько разных вещей — '
    'скажи это в image_type и НЕ выводи стиль из обстановки: оценивай только сам товар.\n'
    '6. Светильники различай по креплению: потолочный/подвесной — role="люстра", '
    'подтип "подвесной_светильник"; настенный — role="бра", подтип "подвесной_светильник"; '
    'напольный на стойке — role="торшер", подтип "напольный_светильник"; настольный — '
    'role="лампа", подтип "настольная_лампа". Подтип "не_определён" ставь только когда из текста '
    'действительно не понять, что это за предмет.'
)


def schema_for(it: dict) -> dict:
    """Схема ответа под конкретную роль: общая часть плюс блок вопросов этого типа предмета."""
    from role_prompt import schema_block
    blk = schema_block(it.get('role_feed') or '')
    if not blk:
        return SCHEMA
    sc = json.loads(json.dumps(SCHEMA))
    sc['properties']['specific'] = blk
    sc['required'] = sc['required'] + ['specific']
    return sc


def prompt(it: dict) -> str:
    # Описание отдаём модели, только если оно вообще что-то говорит о товаре. Замер 2026-08-05:
    # годных описаний в пуле 12.3%, остальное — маркетинговый шаблон магазина (969 диванов с одной
    # фразой), инструкция по креплению или обрывок в две строки. Шум занимает место в промпте,
    # стоит денег и создаёт ложное ощущение информативной карточки (замечание владельца).
    from desc_quality import trusted as _desc_ok
    _desc = it.get('desc') if _desc_ok(it.get('desc')) else ''
    dims = ' × '.join(f'{k}{int(v)}' for k, v in
                      (('Ш', it.get('w')), ('Г', it.get('d')), ('В', it.get('h')),
                       ('⌀', it.get('dia'))) if v)
    params = {k: v for k, v in (it.get('params') or {}).items()
              if k in ('Материал', 'Цвет', 'Тип', 'Назначение', 'Форма', 'Стиль', 'Обивка',
                       'Материал каркаса', 'Материал обивки')}
    return (f'Название: {it["name"]}\n'
            f'Категория магазина: {it["cat"]}\n'
            f'Размеры, см: {dims or "не указаны"}\n'
            f'Цена: {it["price"]} ₽\n'
            f'Параметры фида: {json.dumps(params, ensure_ascii=False) if params else "нет"}\n'
            f'Описание: {_desc[:700] or "нет"}'
            + __import__('role_prompt').prompt_block(it.get('role_feed') or ''))


def _key() -> str:
    # свой .env первым: зависимость от чужих проектов ломается при их переезде (А4)
    for p in (os.path.join(HERE, '.env'), '/home/pakar/mltest/.env', os.path.join(HERE, '../../.env')):
        if os.path.exists(p):
            for line in open(p):
                if line.startswith('OPENAI_API_KEY='):
                    return line.split('=', 1)[1].strip()
    raise SystemExit('нет OPENAI_API_KEY')


_IMG_CACHE: dict = {}
IMG_DIR = os.path.join(HERE, 'imgcache')
IMG_STATS = {'ok': 0, 'fail': 0, 'from_disk': 0}


def _image_b64(url: str, retries: int = 3) -> str | None:
    """Картинка байтами, ужатая до 448 px, с кэшем НА ДИСКЕ и ретраями.

    Две грабли, обе стоили денег:
      1. ссылку магазина API не успевал скачать — 2 987 запросов из 19 752 упали по таймауту;
      2. CDN отдаёт 403 при высокой параллельности: в 24 потока скачалось 14 из 40, и прогон на
         25 тысяч ушёл в модель ВСЛЕПУЮ — картинку получили 287 запросов из 2000, остальные
         отвечали «не_видно» (2026-08-06). Молчаливый `except` это скрыл.
    Поэтому: ретраи с паузой, счётчик отказов наружу и кэш на диск — повторный прогон не качает.
    """
    import base64
    import io as _io
    import time as _t
    from PIL import Image as _Im
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    os.makedirs(IMG_DIR, exist_ok=True)
    key = re.sub(r'[^A-Za-z0-9]', '_', url)[-90:]
    path = os.path.join(IMG_DIR, key + '.jpg')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            out = base64.b64encode(f.read()).decode()
        _IMG_CACHE[url] = out
        IMG_STATS['from_disk'] += 1
        return out
    u = 'https:' + url if url.startswith('//') else url
    out = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            raw = urllib.request.urlopen(req, timeout=45).read()
            im = _Im.open(_io.BytesIO(raw)).convert('RGB')
            im.thumbnail((448, 448))
            buf = _io.BytesIO()
            im.save(buf, 'JPEG', quality=78)
            with open(path, 'wb') as f:
                f.write(buf.getvalue())
            out = base64.b64encode(buf.getvalue()).decode()
            IMG_STATS['ok'] += 1
            break
        except Exception:  # noqa: BLE001 — 403 от CDN при параллельности: ждём и пробуем ещё
            if attempt == retries - 1:
                IMG_STATS['fail'] += 1
            else:
                _t.sleep(1.5 * (attempt + 1))
    if out is None:
        _IMG_CACHE[url] = None
    return out


USAGE = {'in': 0, 'out': 0, 'fails': 0}


def ask(it: dict, model: str, key: str, vision: bool = False) -> dict | None:
    # С картинкой: текст карточки + фото товара в низком разрешении. Смысл — проверить, добавляет
    # ли фотография то, чего в тексте нет (стиль, форма, материал). Замер 2026-08-05 показал, что
    # стиль по одному тексту совпадает со стилем по картинке лишь в 16% — на уровне случайности,
    # значит опираться только на текст в стилевых ролях нельзя (вопрос владельца).
    if vision and it.get('img'):
        b64 = _image_b64(it['img'])
        content = ([{'type': 'text', 'text': prompt(it)},
                    {'type': 'image_url',
                     'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'low'}}]
                   if b64 else prompt(it))
    else:
        content = prompt(it)
    body = {
        'model': model,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': content}],
        'response_format': {'type': 'json_schema',
                            'json_schema': {'name': 'furniture', 'strict': True,
                                            'schema': schema_for(it)}},
    }
    if model.startswith('gpt-5'):
        body['reasoning_effort'] = 'low'      # рассуждать тут не о чем, платить за это незачем
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                                 data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
            u = r.get('usage') or {}
            USAGE['in'] += u.get('prompt_tokens', 0)
            USAGE['out'] += u.get('completion_tokens', 0)
            msg = r['choices'][0]['message']
            if msg.get('refusal'):
                USAGE['fails'] += 1
                return None
            return json.loads(msg['content'])
        except Exception as e:  # noqa: BLE001 — 429/5xx: ждём и пробуем ещё раз
            if attempt == 2:
                USAGE['fails'] += 1
                print(f'  {it["name"][:34]}: {str(e)[:60]}', flush=True)
                return None
            time.sleep(2 + 3 * attempt)
    return None


def main() -> None:
    args = sys.argv
    model = args[args.index('--model') + 1] if '--model' in args else 'gpt-5-nano'
    out = args[args.index('--out') + 1] if '--out' in args else f'golden-{model}.json'
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else 0
    items = json.load(open(GOLDEN))
    if limit:
        items = items[:limit]
    if '--dry' in args:
        p = prompt(items[0])
        print(f'модель: {model}; товаров: {len(items)}\n\n--- системная часть ---\n{SYS}'
              f'\n\n--- пример карточки ---\n{p}\n\n'
              f'примерно {len(SYS) + len(p)} символов на товар ≈ '
              f'{(len(SYS) + len(p)) // 3} токенов входа')
        return
    key = _key()
    t0 = time.time()
    res: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(8) as ex:
        vision = '--vision' in sys.argv
        futs = {ex.submit(ask, it, model, key, vision): it for it in items}
        done = 0
        for f in cf.as_completed(futs):
            it = futs[f]
            r = f.result()
            done += 1
            if r:
                res[f'{it["mid"]}:{it["eid"]}'] = r
            if done % 40 == 0:
                print(f'  {done}/{len(items)}', flush=True)
    path = os.path.join(HERE, out)
    json.dump({'model': model, 'usage': USAGE, 'labels': res}, open(path, 'w'), ensure_ascii=False)
    print(f'{model}: размечено {len(res)}/{len(items)}, отказов {USAGE["fails"]}, '
          f'токенов вход {USAGE["in"]} выход {USAGE["out"]}, {time.time() - t0:.0f} с → {out}')


if __name__ == '__main__':
    main()
