#!/usr/bin/env python3
"""Сравнение моделей для стиль-скоринга: terra против luna против gpt-5-mini.

ЗАЧЕМ (владелец 29.08). Основной сигнал стиля даёт LLM, и выбор модели — это цена × качество:
  gpt-5.6-luna   $0.20/$1.20 за 1M — дешевле mini на входе;
  gpt-5-mini     $0.25/$2.00 — текущая в style_score;
  gpt-5.6-terra  $2.00/$12.00 — дорогая, кандидат в эталон.
Берём ОДИН комплект (до 20 товаров), гоняем ТОТ ЖЕ промпт, что в бою (`style_score.llm_batch`),
по 6 стилям, и сравниваем: согласие моделей между собой, расход по факту из usage, и главное —
листы товаров для проверки глазами: цифры без картинок тут не решают.

  ~/venvs/scout/bin/python style_model_bench.py [номер_сета]
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from golden_label import _key  # noqa: E402  (фолбэк, основной канал — llm_gateway)

MODELS = ['gpt-5.6-luna', 'gpt-5-mini', 'gpt-5.6-terra']
PRICE = {'gpt-5.6-luna': (0.20, 1.20), 'gpt-5-mini': (0.25, 2.00), 'gpt-5.6-terra': (2.00, 12.00)}
SH = {'сканди': 'sk', 'современный': 'sv', 'минимализм': 'mn',
      'лофт': 'lf', 'неоклассика': 'nk', 'джапанди': 'jp'}
RSH = {v: k for k, v in SH.items()}


def build_prompt(items):
    lines = []
    for i, p in enumerate(items):
        extra = '; '.join(x for x in (p.get('mat', ''), p.get('col', '')) if x)[:110]
        lines.append(f"{i}. [{p['role']}] {p['name'][:90]}" + (f" ({extra})" if extra else ''))
    return ("Ты интерьерный дизайнер. Оцени КАЖДЫЙ товар: насколько он уместен в каждом стиле, 0-10 "
            "(0 — противоречит стилю, 5 — нейтрален, 10 — икона стиля). Стили: sk=сканди(светлое дерево, "
            "простые формы), sv=современный(чистые линии, нейтраль+акцент), mn=мягкий минимализм(гладкое, "
            "монохром), lf=лофт(чёрный металл, бетон, тёмное дерево), nk=неоклассика(классические силуэты, "
            "латунь, бархат, симметрия), jp=джапанди(низкие силуэты, тёплый монохром, натуральные материалы, "
            "ротанг). u=true если товар стилистически нейтральный. Суди по названию и материалу. "
            'Ответ STRICT JSON: {"items":[{"i":0,"sk":5,"sv":5,"mn":5,"lf":5,"nk":5,"jp":5,"u":false},...]} '
            f"— ровно {len(items)} элементов.\nТовары:\n" + '\n'.join(lines))


def call(model, prompt, key):
    from llm_gateway import chat
    t0 = time.time()
    out = chat(model, [{'role': 'user', 'content': prompt}], reasoning_effort='low')
    usage = out.get('usage', {})
    pin, pout = PRICE[model]
    cost = usage.get('prompt_tokens', 0) / 1e6 * pin + usage.get('completion_tokens', 0) / 1e6 * pout
    m = re.search(r'\{.*\}', out['choices'][0]['message']['content'], re.S)
    items = json.loads(m.group(0))['items']
    return items, cost, time.time() - t0, usage


def main():
    set_no = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[set_no - 1]
    items = []
    for slot, it in sorted((s.get('items') or {}).items()):
        if it and it.get('mid') and len(items) < 20:
            parts = slot.split(' ')
            role = slot if not parts[-1].isdigit() else ' '.join(parts[:-1])
            items.append({'role': role, 'name': it.get('name', ''), 'img': it.get('img'),
                          'mat': '', 'col': ''})
    print(f'комплект №{set_no} ({s.get("set_id")}): товаров {len(items)}')
    prompt = build_prompt(items)
    key = _key()
    results = {}
    for m in MODELS:
        try:
            parsed, cost, secs, usage = call(m, prompt, key)
            scores = {}
            for it in parsed:
                if isinstance(it, dict) and 'i' in it:
                    scores[int(it['i'])] = ({RSH[k]: float(it.get(k, 5)) for k in SH.values()}
                                            | {'universal': bool(it.get('u'))})
            results[m] = {'scores': scores, 'cost': cost, 'secs': secs,
                          'tokens': usage.get('total_tokens')}
            print(f'  {m:16} ${cost:.4f}  {secs:.0f} с  {usage.get("total_tokens")} ток  '
                  f'ответов {len(scores)}/{len(items)}')
        except Exception as e:  # noqa: BLE001
            print(f'  {m:16} ✗ {type(e).__name__}: {str(e)[:90]}')
    out = {'set': set_no, 'set_id': s.get('set_id'), 'items': items,
           'results': {m: {'scores': {str(k): v for k, v in r['scores'].items()},
                           'cost': r['cost'], 'secs': r['secs']} for m, r in results.items()}}
    json.dump(out, open(os.path.join(HERE, 'style-model-bench.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('→ style-model-bench.json')


if __name__ == '__main__':
    main()
