#!/usr/bin/env python3
"""Стиль как СУММА НАБЛЮДАЕМЫХ ПРИЗНАКОВ, а не как ярлык от модели.

Почему так, а не «модель, скажи стиль»:
  * прямая классификация стиля по одному предмету слаба — 0.41 точности на эталонном датасете
    Bonn Furniture Styles (90 298 фото, 17 стилей), 0.49 с признаками сиамской сети
    (arXiv 1812.03570). Половина ответов неверна;
  * признаковый разбор — принятый подход: материал, масса, формальность, линия, стёжка, цвет
    как отдельные извлекатели (ACM TIST 10.1145/3065951), а описание через признаки точнее и
    объяснимее прямого сопоставления с ярлыком (arXiv 2412.13947);
  * ответ «ножки конические, орнамента нет, дуб светлый» проверяем глазами, а «стиль сканди 0.8» —
    нет. Ошибку в признаке видно, ошибку в ярлыке — нет.

Оценка получается НЕПРЕРЫВНОЙ (в отличие от четырёх ступеней), потому что складывается из десятка
взвешенных свидетельств. Это и было её слабым местом: старый скор различал десять уровней на
двенадцати диванах, а ступенчатый — два.

  ~/venvs/scout/bin/python style_attrs.py --demo        # на товарах с фото
  ~/venvs/scout/bin/python style_attrs.py --explain 116933 3036041517751486277
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enrich_bridge as EB  # noqa: E402

RULES = json.load(open(os.path.join(HERE, 'style_rules.json')))['rules']
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
# сколько признаков модель обычно успевает увидеть; по этому числу считаем уверенность
FULL_EVIDENCE = 10.0   # столько признаков обычно видно, когда вопросы заданы под роль


def _observed(e: dict) -> dict:
    """Наблюдаемые признаки товара из обогащения, приведённые к именам правил.

    Часть вопросов общая (материал, отделка, теплота), часть — своя у каждого типа предмета
    (`specific`: подлокотник у дивана, ручки у комода, каркас у люстры, ворс у ковра).
    """
    ph = dict(e.get('photo') or {})
    ph.update(e.get('specific') or {})
    obs = {
        'materials': e.get('materials') or [],
        'finish': ph.get('finish'),
        'pattern': ph.get('pattern'),
        'warmth': e.get('warmth'),
        'visual_mass': e.get('mass'),
        'legs': ph.get('legs') or e.get('base_type'),
        'lines': ph.get('lines'),
        'ornament': ph.get('ornament'),
        'hardware': ph.get('hardware'),
        'proportions': ph.get('proportions'),
        'formality': ph.get('formality'),
        'arms': ph.get('arms'), 'tufting': ph.get('tufting'), 'seam': ph.get('seam'),
        'back': ph.get('back'), 'seat_height': ph.get('seat_height'),
        'base': ph.get('base'), 'edge': ph.get('edge'), 'top_material': ph.get('top_material'),
        'fronts': ph.get('fronts'), 'handles': ph.get('handles'),
        'handle_finish': ph.get('handle_finish'), 'openness': ph.get('openness'),
        'body': ph.get('body'), 'frame': ph.get('frame'), 'shade': ph.get('shade'),
        'shade_material': ph.get('shade_material'), 'metal_finish': ph.get('metal_finish'),
        'pile': ph.get('pile'), 'rug_pattern': ph.get('rug_pattern'),
        'weave': ph.get('weave'), 'edge_trim': ph.get('edge_trim'),
        'glaze': ph.get('glaze'), 'relief': ph.get('relief'), 'form': ph.get('form'),
        'textile_pattern': ph.get('textile_pattern'), 'heading': ph.get('heading'),
        'skirt': ph.get('skirt'), 'pot_material': ph.get('pot_material'),
        'base_form': ph.get('base_form'),
    }
    return {k: v for k, v in obs.items()
            if v and v not in ('неясно', 'не_определён', 'не_видно', 'не_применимо')}


def evidence(mid, eid) -> tuple[dict, list, int]:
    """Очки по каждому стилю, список сработавших правил и число наблюдённых признаков."""
    e = EB.get(mid, eid)
    if not e:
        return {}, [], 0
    obs = _observed(e)
    pts = {s: 0.0 for s in STYLES}
    fired = []
    seen = 0
    for attr, val in obs.items():
        vals = val if isinstance(val, list) else [val]
        hit = False
        for v in vals:
            for r in RULES:
                if r['attr'] != attr or r['value'] != v:
                    continue
                hit = True
                for st, w in r['w'].items():
                    if st in pts:
                        pts[st] += w
                fired.append((attr, v, r['w'], r.get('why', '')))
        seen += 1 if hit else 0
    return pts, fired, seen


def scores(mid, eid) -> dict | None:
    """Непрерывная оценка 0–10 по каждому стилю.

    Три поправки, каждая со своей причиной:
      1. редкость стиля — «современный» подходит 97% каталога и потому ничего не отличает;
      2. уверенность — если модель разглядела два признака из десяти, оценку тянем к нейтралу;
      3. насыщение — очки уводим в 0–10 плавной кривой, чтобы один сильный признак не решал всё.
    """
    pts, fired, seen = evidence(mid, eid)
    if not pts:
        return None
    conf = min(1.0, seen / FULL_EVIDENCE)
    pr = EB.priors()
    out = {}
    for st in STYLES:
        # плавное насыщение: ±6 очков → почти края шкалы, дальше прирост мал
        base = 5.0 + 5.0 * math.tanh(pts[st] / 4.0)
        rare = 1.0 + (5.0 - pr.get(st, 5.0)) / 5.0        # частый стиль тянем к нейтралу
        val = 5.0 + (base - 5.0) * conf * max(0.4, min(1.6, rare))
        out[st] = round(max(0.0, min(10.0, val)), 1)
    top = max(out.values())
    med = sorted(out.values())[len(out) // 2]
    out['universal'] = (top - med) < 1.2                  # ничего не выделяется — товар нейтрален
    out['confidence'] = round(conf, 2)
    out['src'] = 'attrs'
    return out


def explain(mid, eid) -> None:
    e = EB.get(mid, eid)
    if not e:
        print('нет обогащения у этого товара')
        return
    pts, fired, seen = evidence(mid, eid)
    sc = scores(mid, eid)
    print(f'наблюдено признаков: {seen}, уверенность {sc["confidence"]}\n')
    print('что сработало:')
    for attr, val, w, why in fired:
        plus = ', '.join(f'{s}{v:+.1f}' for s, v in sorted(w.items(), key=lambda kv: -kv[1])[:3])
        print(f'  {attr}={val:20s} → {plus:44s} {why[:50]}')
    print('\nитог:')
    for s in sorted(STYLES, key=lambda x: -sc[x]):
        print(f'  {s:14s} {sc[s]:5.1f}   (очков {pts[s]:+.1f})')


def main() -> None:
    if '--explain' in sys.argv:
        i = sys.argv.index('--explain')
        explain(sys.argv[i + 1], sys.argv[i + 2])
        return
    if '--demo' in sys.argv:
        import subprocess
        PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                '-q', '-t', '-A', '-F', '\x1f']
        q = """select p.shop_mid, p.external_id, p.name from product_enrichment e
               join products p using (shop_mid, external_id)
               where e.schema_version='s3' and p.name ilike 'диван%' limit 12"""
        rows = [l.split('\x1f') for l in
                subprocess.run(PSQL, input=q, capture_output=True, text=True).stdout.strip().split('\n') if l]
        print(f'{"товар":44s} ' + ' '.join(f'{s[:6]:>6}' for s in STYLES))
        vals = set()
        for r in rows:
            if len(r) < 3:
                continue
            sc = scores(r[0], r[1])
            if not sc:
                continue
            vals.update(sc[s] for s in STYLES)
            print(f'{r[2][:42]:44s} ' + ' '.join(f'{sc[s]:6.1f}' for s in STYLES))
        print(f'\nразных значений оценки на этой выборке: {len(vals)}')
        return
    print(__doc__)


if __name__ == '__main__':
    main()
