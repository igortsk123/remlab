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


TIER_W = {'маркер': 3.0, 'поддержка': 1.5, 'фон': 0.6}

FREQ_PATH = os.path.join(HERE, 'attr-freq.json')
_FREQ: dict | None = None


def freq(rebuild: bool = False) -> dict:
    """Как часто признак встречается — ОТДЕЛЬНО ПО КАЖДОЙ ГРУППЕ ПРЕДМЕТОВ.

    Маркер обязан быть редким, но редкость своя у каждого типа вещи: тонкая металлическая опора
    у журнального столика — обычное дело, а у дивана редкость; открытые полки у стеллажа норма,
    а у комода уже характер. Считать частоту по всему каталогу значит мерить диван линейкой
    светильника (замечание владельца, 2026-08-06).
    """
    global _FREQ
    if _FREQ is not None and not rebuild:
        return _FREQ
    if os.path.exists(FREQ_PATH) and not rebuild:
        _FREQ = json.load(open(FREQ_PATH))
        return _FREQ
    from role_prompt import group_of
    cnt: dict[str, int] = {}
    tot: dict[str, int] = {}
    for key in EB.load():
        mid, eid = key.split(':', 1)
        e = EB.get(mid, eid) or {}
        obs = _observed(e)
        if not obs:
            continue
        g = group_of(e.get('role') or '') or 'прочее'
        tot[g] = tot.get(g, 0) + 1
        for a, v in obs.items():
            for vv in (v if isinstance(v, list) else [v]):
                cnt[f'{g}|{a}={vv}'] = cnt.get(f'{g}|{a}={vv}', 0) + 1
    _FREQ = {k: round(n / max(tot.get(k.split('|')[0], 1), 1), 4) for k, n in cnt.items()}
    _FREQ['_totals'] = tot
    json.dump(_FREQ, open(FREQ_PATH, 'w'), ensure_ascii=False)
    return _FREQ


def _tier_capped(attr: str, val: str, tier: str, group: str | None) -> str:
    """Понижение ранга по частоте ВНУТРИ ГРУППЫ: частый для этого типа вещей признак — не маркер."""
    f = freq().get(f'{group or "прочее"}|{attr}={val}')
    if f is None:
        return tier
    if f > 0.45:
        return 'фон'
    if f > 0.22 and tier == 'маркер':
        return 'поддержка'
    return tier


def evidence(mid, eid) -> tuple[dict, list, int, dict]:
    """Очки по стилям, сработавшие правила, число признаков и «чем именно набрано».

    Балл даёт РАНГ признака, а не вкусовой вес: маркер (увидел — почти наверняка этот стиль),
    поддержка (согласуется), фон (слабый намёк). Признак с вето обнуляет стиль целиком: лофта
    с хрустальными подвесами не бывает, сколько бы металла ни было рядом.
    """
    e = EB.get(mid, eid)
    if not e:
        return {}, [], 0, {}
    from role_prompt import group_of, matrix
    role = (e.get('role') or '').strip()
    grp = group_of(role)
    cat = matrix().get(role)     # ранги ИЗ ЯЧЕЙКИ КАТЕГОРИИ, а не из общего правила
    obs = _observed(e)
    pts = {s: 0.0 for s in STYLES}
    kind = {s: {'маркер': 0, 'поддержка': 0, 'фон': 0, 'свой': 0} for s in STYLES}
    banned: set = set()
    fired = []
    seen = 0
    for attr, val in obs.items():
        vals = val if isinstance(val, list) else [val]
        hit = False
        for v in vals:
            cell = (((cat or {}).get('attrs') or {}).get(attr) or {}).get('values', {}).get(v)
            for r in ([{'attr': attr, 'value': v, 'tiers': cell['tiers'], 'veto': cell['veto'],
                        'why': ''}] if cell else RULES):
                if r['attr'] != attr or r['value'] != v:
                    continue
                hit = True
                banned.update(r.get('veto') or [])
                for st, t in (r.get('tiers') or {}).items():
                    if st not in pts:
                        continue
                    # если ячейка категории известна — ранг уже посчитан в ней с учётом
                    # частоты именно этой категории; общий понижатель тогда не нужен
                    tier = t['tier'] if cell else _tier_capped(attr, v, t['tier'], grp)
                    w = TIER_W[tier] * t.get('sign', 1)
                    pts[st] += w
                    if w > 0:
                        kind[st][tier] += 1
                        # Свой признак категории: по нему решается, есть ли у вещи стиль вообще.
                        # Считаем ЛЮБОЙ положительный вклад, а не только ранг «маркер»: после
                        # понижения по частоте свои признаки часто становятся поддержкой, и
                        # требование маркера объявляло нейтральными две трети каталога
                        # (замер 2026-08-06: 66% при цели 15-35%).
                        own = (((cat or {}).get('attrs') or {}).get(attr) or {}).get('own_marker')
                        if own:
                            kind[st]['свой'] += 1
                fired.append((attr, v, r.get('tiers') or {}, r.get('why', '')))
        seen += 1 if hit else 0
    for st in banned:
        if st in pts:
            pts[st] = min(pts[st], -6.0)      # вето: стиль уходит в самый низ шкалы
            kind[st] = {'маркер': 0, 'поддержка': 0, 'фон': 0, 'вето': 1}
    return pts, fired, seen, kind


STATS_PATH = os.path.join(HERE, 'style-stats.json')
_STATS: dict | None = None


def stats(rebuild: bool = False) -> dict:
    """Среднее и разброс СЫРЫХ ОЧКОВ каждого стиля по каталогу.

    Первая версия множила отклонение на «редкость стиля», и редкие языки систематически всплывали
    наверх: у пяти люстр подряд выходил лофт, включая белую классическую и хрустальную (проверка
    глазами, 2026-08-06). Правильнее нормировать каждый стиль по ЕГО СОБСТВЕННОЙ шкале: тогда
    средний товар получает пятёрку по любому стилю, а высокий балл значит «выделяется среди
    остальных именно этим языком».
    """
    global _STATS
    if _STATS is not None and not rebuild:
        return _STATS
    if os.path.exists(STATS_PATH) and not rebuild:
        _STATS = json.load(open(STATS_PATH))
        return _STATS
    acc = {s: [] for s in STYLES}
    for key in EB.load():
        mid, eid = key.split(':', 1)
        pts, _f, seen, _k = evidence(mid, eid)
        if not pts or seen < 3:
            continue
        for s in STYLES:
            acc[s].append(pts[s])
    _STATS = {}
    for s, v in acc.items():
        if len(v) < 50:
            _STATS[s] = {'mean': 0.0, 'sd': 3.0}
            continue
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
        _STATS[s] = {'mean': round(m, 2), 'sd': round(max(sd, 0.5), 2), 'n': len(v)}
    json.dump(_STATS, open(STATS_PATH, 'w'), ensure_ascii=False)
    return _STATS


def scores(mid, eid) -> dict | None:
    """Непрерывная оценка 0–10 по каждому стилю.

    Две поправки, каждая со своей причиной:
      1. нормировка по собственной шкале стиля — иначе редкие языки систематически побеждают;
      2. уверенность — если модель разглядела два признака из десяти, оценку тянем к нейтралу.
    """
    pts, fired, seen, kind = evidence(mid, eid)
    if not pts:
        return None
    item = EB.get(mid, eid) or {}
    from role_prompt import matrix as _matrix
    cat_meta = _matrix().get((item.get('role') or '').strip())
    conf = min(1.0, seen / FULL_EVIDENCE)
    # Нормируем ВНУТРИ ТОВАРА: стили соревнуются друг с другом на одних и тех же признаках.
    # Сравнение со средним по каталогу давало сбой, пока каталог опрошен старым набором вопросов,
    # а карточка — новым: у неё признаков больше, очки выше, и один стиль побеждал в половине
    # случаев просто потому, что накопил больше свидетельств (поймано на замере, 2026-08-06).
    vals = list(pts.values())
    mean = sum(vals) / len(vals)
    sd = max((sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5, 1.2)
    # Стилево нейтральный товар: ни один СОБСТВЕННЫЙ маркер категории не сработал в плюс.
    # Искусственная орхидея одинаково уместна и в сканди, и в неоклассике — честнее сказать
    # «стиля нет», чем назначать победителя (замер 2026-08-06: детский коврик и букет лилейника
    # получали сканди просто потому, что кто-то должен был выиграть).
    neutral = (sum(k.get('свой', 0) for k in kind.values()) == 0
               or bool((cat_meta or {}).get('neutral_by_nature')))
    damp = 0.3 if neutral else 1.0
    # по интерьерной сцене судить о вещи нельзя: на фото комната, а не товар
    if (item.get('image_type') or '') == 'товар_в_интерьере':
        damp *= 0.6
    out = {}
    for st in STYLES:
        z = (pts[st] - mean) / sd
        k = kind.get(st) or {}
        # достаточность: без единого ПОЛОЖИТЕЛЬНОГО маркера и меньше трёх поддерживающих
        # признаков стиль не уходит высоко — иначе он выигрывает на том, чего у вещи НЕТ
        # (нет декора, линии прямые, фасады гладкие), а это верно для любой категории
        if not k.get('маркер') and k.get('поддержка', 0) < 3:
            z = min(z, 0.6)
        if not k.get('маркер'):
            z = min(z, 1.2)
        val = 5.0 + 2.2 * max(-2.2, min(2.2, z)) * conf * damp
        out[st] = round(max(0.0, min(10.0, val)), 1)
    out['neutral'] = neutral
    top = max(out[s] for s in STYLES)
    med = sorted(out[s] for s in STYLES)[len(STYLES) // 2]
    out['universal'] = neutral or (top - med) < 1.2                  # ничего не выделяется — товар нейтрален
    out['confidence'] = round(conf, 2)
    out['src'] = 'attrs'
    return out


def explain(mid, eid) -> None:
    e = EB.get(mid, eid)
    if not e:
        print('нет обогащения у этого товара')
        return
    pts, fired, seen, kind = evidence(mid, eid)
    sc = scores(mid, eid)
    print(f'наблюдено признаков: {seen}, уверенность {sc["confidence"]}\n')
    print('что сработало:')
    for attr, val, tiers, why in fired:
        top = ', '.join(f'{s} {t["tier"]}{"−" if t.get("sign", 1) < 0 else ""}'
                        for s, t in list(tiers.items())[:3])
        print(f'  {attr}={val:22s} → {top:48s} {why[:44]}')
    print('\nитог:')
    for s in sorted(STYLES, key=lambda x: -sc[x]):
        k = kind.get(s) or {}
        mark = ('ВЕТО' if k.get('вето') else
                f'маркеров {k.get("маркер", 0)}, поддержки {k.get("поддержка", 0)}')
        print(f'  {s:14s} {sc[s]:5.1f}   очков {pts[s]:+5.1f}   {mark}')


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
