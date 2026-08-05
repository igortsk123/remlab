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

ROLES = ['диван', 'кресло', 'пуф', 'столик', 'тв-тумба', 'комод', 'стеллаж', 'ковёр', 'торшер',
         'лампа', 'люстра', 'кашпо', 'ваза', 'плед', 'подушка', 'другое']
SUBTYPES = ['подставка_для_ног', 'дополнительное_сиденье', 'пуф_стол', 'пуф_хранение', 'банкетка',
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


def _enum(name, vals):
    return {'type': 'string', 'enum': vals, 'description': name}


SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['role', 'functional_subtype', 'materials', 'primary_color', 'shape', 'base_type',
                 'visual_mass', 'warmth', 'decorativeness', 'styles', 'style_strength', 'flags'],
    'properties': {
        'role': _enum('роль предмета в гостиной', ROLES),
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
    '5. style_strength: "нейтральный" — подойдёт куда угодно; "характерный" — сильно диктует стиль.'
)


def prompt(it: dict) -> str:
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
            f'Описание: {it["desc"][:700] or "нет"}')


def _key() -> str:
    for p in ('/home/pakar/mltest/.env', os.path.join(HERE, '../../.env')):
        if os.path.exists(p):
            for line in open(p):
                if line.startswith('OPENAI_API_KEY='):
                    return line.split('=', 1)[1].strip()
    raise SystemExit('нет OPENAI_API_KEY')


USAGE = {'in': 0, 'out': 0, 'fails': 0}


def ask(it: dict, model: str, key: str) -> dict | None:
    body = {
        'model': model,
        'messages': [{'role': 'system', 'content': SYS},
                     {'role': 'user', 'content': prompt(it)}],
        'response_format': {'type': 'json_schema',
                            'json_schema': {'name': 'furniture', 'strict': True, 'schema': SCHEMA}},
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
        futs = {ex.submit(ask, it, model, key): it for it in items}
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
