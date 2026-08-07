#!/usr/bin/env python3
"""Сравнение моделей на золотой выборке — числами, а не впечатлением.

Считаем согласие каждой модели с эталонной разметкой по каждому полю, отдельно на простых и
трудных карточках, с доверительным интервалом (бутстрап) и ценой за товар. «Модель А на 2%
лучше» без интервала ничего не значит: на 256 товарах 2% — это шесть карточек.

Эталон — черновой: он размечен сильной моделью, а не человеком, поэтому ВСЕ цифры отсюда —
model-agreement, НЕ измеренная точность (вердикт рефери, T2 truth-first). Человеческий эталон
и честные метрики — gold_human.py (gold-human-v1). Отдельно печатаем
позиции, где кандидаты расходятся с эталоном ЕДИНОГЛАСНО: это места, где, скорее всего, ошибается
сам эталон, и их надо показать владельцу.

  ~/venvs/scout/bin/python golden_eval.py --ref golden-ref.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES = {  # $/1M токенов, ADR-0067; сверять перед прогоном
    'gpt-5.6-terra': (2.00, 12.00), 'gpt-5.6-luna': (0.20, 1.20),
    'gpt-5-nano': (0.05, 0.40), 'gpt-5.4-nano': (0.20, 1.25), 'gpt-5.4-mini': (0.75, 4.50),
}
FIELDS = ['role', 'functional_subtype', 'primary_color', 'shape', 'base_type',
          'visual_mass', 'warmth', 'style_strength']


def agree(a, b, field: str) -> bool:
    if field == 'materials':
        return bool(set(a.get(field) or []) & set(b.get(field) or []))
    return a.get(field) == b.get(field)


def styles_close(a, b) -> bool:
    """Стилевой вектор считаем совпавшим, если ни один стиль не разошёлся больше чем на ступень."""
    order = {'нет': 0, 'низкая': 1, 'средняя': 2, 'высокая': 3}
    sa, sb = a.get('styles') or {}, b.get('styles') or {}
    if not sa or not sb:
        return False
    return all(abs(order.get(sa.get(k), 0) - order.get(sb.get(k), 0)) <= 1 for k in sa)


def ci(hits: list[bool], rounds: int = 400) -> tuple[float, float, float]:
    """Доля попаданий и её интервал бутстрапом. Детерминированно: шаг вместо случайности."""
    n = len(hits)
    if not n:
        return 0.0, 0.0, 0.0
    p = sum(hits) / n
    samples = []
    for r in range(rounds):
        step = 1 + (r * 7919) % max(n - 1, 1)      # псевдослучайный, но воспроизводимый обход
        s = [hits[(i * step + r) % n] for i in range(n)]
        samples.append(sum(s) / n)
    samples.sort()
    return p, samples[int(0.025 * rounds)], samples[int(0.975 * rounds)]


def main() -> None:
    args = sys.argv
    ref_name = args[args.index('--ref') + 1] if '--ref' in args else 'golden-ref.json'
    ref = json.load(open(os.path.join(HERE, ref_name)))
    golden = {f'{i["mid"]}:{i["eid"]}': i for i in json.load(open(os.path.join(HERE, 'golden.json')))}
    cands = [f for f in sorted(os.listdir(HERE))
             if f.startswith('golden-') and f.endswith('.json')
             and f not in (ref_name, 'golden-probe.json')]
    if not cands:
        print('нет файлов кандидатов')
        return

    print(f'эталон: {ref["model"]} ({len(ref["labels"])} товаров)\n')
    print(f'{"модель":16s} {"роль":>16s} {"подтип":>16s} {"цвет":>10s} {"материал":>10s} '
          f'{"стиль":>10s} {"$/1000 тов.":>12s}')
    rows = []
    for fn in cands:
        c = json.load(open(os.path.join(HERE, fn)))
        model = c['model']
        common = [k for k in ref['labels'] if k in c['labels']]
        hits = {f: [agree(ref['labels'][k], c['labels'][k], f) for k in common] for f in FIELDS}
        hits['materials'] = [agree(ref['labels'][k], c['labels'][k], 'materials') for k in common]
        hits['styles'] = [styles_close(ref['labels'][k], c['labels'][k]) for k in common]
        pin, pout = PRICES.get(model, (0, 0))
        u = c['usage']
        per1000 = (u['in'] / len(common) * pin + u['out'] / len(common) * pout) / 1e6 * 1000
        r_p, r_lo, r_hi = ci(hits['role'])
        s_p, s_lo, s_hi = ci(hits['functional_subtype'])
        print(f'{model:16s} {r_p*100:6.1f}% ({r_lo*100:.0f}–{r_hi*100:.0f}) '
              f'{s_p*100:6.1f}% ({s_lo*100:.0f}–{s_hi*100:.0f}) '
              f'{sum(hits["primary_color"])/len(common)*100:9.0f}% '
              f'{sum(hits["materials"])/len(common)*100:9.0f}% '
              f'{sum(hits["styles"])/len(common)*100:9.0f}% {per1000:11.2f}$')
        rows.append({'model': model, 'hits': hits, 'labels': c['labels'], 'common': common,
                     'per1000': per1000, 'usage': u})

    # трудные карточки отдельно: там и ломаются дешёвые модели
    print(f'\n{"модель":16s} {"роль (простые)":>16s} {"роль (трудные)":>16s} '
          f'{"подтип (трудные)":>18s}')
    for r in rows:
        easy = [h for k, h in zip(r['common'], r['hits']['role']) if not golden[k]['hard']]
        hard = [h for k, h in zip(r['common'], r['hits']['role']) if golden[k]['hard']]
        hard_s = [h for k, h in zip(r['common'], r['hits']['functional_subtype'])
                  if golden[k]['hard']]
        print(f'{r["model"]:16s} {sum(easy)/max(len(easy),1)*100:15.1f}% '
              f'{sum(hard)/max(len(hard),1)*100:15.1f}% {sum(hard_s)/max(len(hard_s),1)*100:17.1f}%')

    # где эталон, скорее всего, сам ошибается: все кандидаты сказали одно и то же, но иначе
    print('\nпозиции, где ВСЕ кандидаты разошлись с эталоном одинаково (проверить вручную):')
    suspects = []
    for k in ref['labels']:
        vals = {r['labels'][k]['role'] for r in rows if k in r['labels']}
        if len(vals) == 1 and vals != {ref['labels'][k]['role']}:
            suspects.append((k, ref['labels'][k]['role'], vals.pop()))
    for k, was, now in suspects[:15]:
        print(f'  {golden[k]["name"][:50]:52s} эталон: {was:10s} кандидаты: {now}')
    print(f'  всего таких: {len(suspects)}')
    json.dump({'suspects': [{'key': k, 'ref': a, 'cands': b} for k, a, b in suspects]},
              open(os.path.join(HERE, 'golden-suspects.json'), 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
