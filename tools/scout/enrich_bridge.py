#!/usr/bin/env python3
"""Мост между обогащением каталога и сборщиком комплектов.

Сборщик исторически знает о товаре три вещи: роль по регексу категории, стилевой вектор из
`style-scores.json` и подтип по эвристике `item_function`. После К2 у нас есть проверенное
моделью обогащение на 26 147 товаров: роль, функциональный подтип, цвет, материалы, стилевой
вектор и системная оценка качества карточки.

Мост подключает это, не переписывая сборщик:
  * подтип берём из обогащения, если он там есть (модель отличает банкетку от пуфа надёжнее
    регекса по названию);
  * стилевой вектор — фолбэк там, где `style-scores.json` товар не знает (покрытие 15 735 → 23 879);
  * карточки с качеством ниже порога в комплект не пускаем: плохая карточка не должна попадать
    в подбор только потому, что подошла по размеру.

  ~/venvs/scout/bin/python enrich_bridge.py     # замер покрытия
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
MIN_QUALITY = 0.65

# «нет/низкая/средняя/высокая» → шкала 0–10, в которой живёт style-scores.json.
# Дискретные ступени — осознанный выбор К3: числа 0–1 от модели не воспроизводятся между
# прогонами, а ступени воспроизводятся; в общую шкалу переводим один раз здесь.
LEVEL10 = {'нет': 1.5, 'низкая': 4.0, 'средняя': 7.0, 'высокая': 9.0}

# подтипы обогащения → роли сборщика, для которых они допустимы
SUB_OK = {
    'пуф': {'подставка_для_ног', 'дополнительное_сиденье', 'пуф_стол', 'пуф_хранение'},
    'столик': {'журнальный_стол', 'приставной_стол', 'пуф_стол'},
    'комод': {'комод_хранение', 'сервант'},
    'тв-тумба': {'тумба_под_тв'},
    'стеллаж': {'книжный_стеллаж', 'стеллаж_перегородка', 'витрина'},
    'торшер': {'напольный_светильник'},
    'лампа': {'настольная_лампа'},
    'люстра': {'подвесной_светильник'},
}

_CACHE: dict | None = None


def _key(mid, eid) -> str:
    return f'{mid}:{eid}'


def load() -> dict:
    """Обогащение в память: 26 тысяч строк, это десятки мегабайт и одна секунда."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    r = subprocess.run(PSQL, capture_output=True, text=True, input="""
        select shop_mid, external_id, quality,
               payload->'model'->>'role', payload->'model'->>'functional_subtype',
               payload->'model'->>'primary_color', payload->'model'->>'materials',
               payload->'model'->>'styles', payload->'model'->>'style_strength',
               payload->'model'->>'visual_mass', payload->'model'->>'warmth',
               payload->'model'->>'photo', payload->'model'->>'image_type'
          from product_enrichment where payload is not null and status='active'
    """)
    if r.returncode != 0:
        print(r.stderr[:300])
        return {}
    out = {}
    for line in r.stdout.strip().split('\n'):
        if not line:
            continue
        f = line.split('\x1f')
        if len(f) < 11:  # строка с переносом внутри описания
            continue          # строка с переносом внутри описания — пропускаем, их единицы
        out[_key(f[0], f[1])] = dict(
            quality=float(f[2] or 0), role=f[3], subtype=f[4], colour=f[5],
            materials=json.loads(f[6]) if f[6] else [],
            styles=json.loads(f[7]) if f[7] else {},
            strength=f[8], mass=f[9], warmth=f[10],
            photo=json.loads(f[11]) if len(f) > 11 and f[11] else {},
            image_type=f[12] if len(f) > 12 else None)
    _CACHE = out
    return out


def get(mid, eid) -> dict | None:
    return load().get(_key(mid, eid))


def quality_ok(mid, eid) -> bool:
    """Пускать ли карточку в подбор. Товар без обогащения не отвергаем — просто нет данных."""
    e = get(mid, eid)
    return True if e is None else e['quality'] >= MIN_QUALITY


def subtype_ok(role: str, mid, eid) -> bool | None:
    """Годится ли товар роли по функции. None — обогащения нет, решает старая эвристика."""
    e = get(mid, eid)
    if not e or role not in SUB_OK:
        return None
    return e['subtype'] in SUB_OK[role]


# Угол, под которым СНЯТ сам товар на карточке. Раньше конвейер вклейки считал любую карточку
# фронтальной и вычислял разворот только из геометрии сцены — а по факту 53% карточек сняты
# в три четверти (замер по 5 420 товарам, 2026-08-05). Из-за этого предметы, стоящие в сцене
# вполоборота, считались «сильно развёрнутыми» и уезжали на платную 3D-модель зря.
PHOTO_YAW = {'фронтально': 0.0, 'три_четверти': 35.0, 'сбоку': 90.0,
             'сверху': 0.0, 'деталь_крупно': 0.0, 'неясно': 0.0}


def photo_yaw(mid, eid) -> float | None:
    """Собственный разворот товара на фото, градусы. None — фото не смотрели."""
    e = get(mid, eid)
    if not e:
        return None
    return PHOTO_YAW.get((e.get('photo') or {}).get('view_angle'))


def photo_flags(mid, eid) -> dict:
    """Что не так с карточкой: логотип, посторонние предметы, обрезка, годность эталоном."""
    e = get(mid, eid)
    return (e or {}).get('photo') or {}


# Редкость стиля. Замер по каталогу (2026-08-05): «современный» подходит 97.2% товаров,
# «минимализм» 87.1%, а «неоклассика» и «лофт» — по 38%. Оценка «современный: высокая» не отличает
# ничего: её имеет почти каждый товар. Поэтому балл стиля взвешиваем его редкостью — частый стиль
# тянет к нейтралу, редкий решает. Приоры считаются из самого каталога и лежат в style-priors.json,
# чтобы их можно было посмотреть и пересчитать, а не гадать.
PRIORS_PATH = os.path.join(HERE, 'style-priors.json')
_PRIORS: dict | None = None


def priors(rebuild: bool = False) -> dict:
    global _PRIORS
    if _PRIORS is not None and not rebuild:
        return _PRIORS
    if os.path.exists(PRIORS_PATH) and not rebuild:
        _PRIORS = json.load(open(PRIORS_PATH))
        return _PRIORS
    acc: dict[str, list] = {}
    for v in load().values():
        for st, lvl in (v.get('styles') or {}).items():
            a = acc.setdefault(st, [0.0, 0])
            a[0] += LEVEL10.get(lvl, 5.0)
            a[1] += 1
    _PRIORS = {st: round(a[0] / max(a[1], 1), 2) for st, a in acc.items()}
    json.dump(_PRIORS, open(PRIORS_PATH, 'w'), ensure_ascii=False)
    return _PRIORS


def style_scores(mid, eid) -> dict | None:
    """Стилевой вектор в шкале 0–10.

    Если товар опрошен по признакам (есть блок `specific` из вопросов под категорию), считаем
    рейтингом по рангам — он объяснимый и умеет отвечать «стиля нет». Нейтральный товар получает
    ровные пятёрки и флаг `universal`: сборщик не штрафует его за чужой стиль и подбирает по
    цвету, размеру и цене (решение владельца 2026-08-06).
    """
    e = get(mid, eid)
    if e and (e.get('photo') or {}).get('legs') is not None or (e or {}).get('specific'):
        try:
            from style_attrs import scores as _attr_scores, STYLES as _ST
            sc = _attr_scores(mid, eid)
            if sc:
                out = {k: sc[k] for k in _ST}
                out['universal'] = bool(sc.get('universal') or sc.get('neutral'))
                out['neutral'] = bool(sc.get('neutral'))
                out['src'] = 'attrs'
                return out
        except Exception:  # noqa: BLE001 — нет таблицы или правил: работаем по ступеням
            pass
    return _levels_scores(mid, eid)


def _levels_scores(mid, eid) -> dict | None:
    """Запасной путь: ступени «нет/низкая/средняя/высокая» в шкале 0–10.

    Фолбэк для товаров, которых нет в style-scores.json, и заодно поправка на «стоп-стили»:
    оценка, которую имеет почти весь каталог, сдвигается к нейтральной пятёрке, а редкая —
    усиливается. Иначе подбор под лофт и под современный даёт почти один и тот же список.
    """
    e = get(mid, eid)
    if not e or not e['styles']:
        return None
    pr = priors()
    out = {}
    for k, v in e['styles'].items():
        raw = LEVEL10.get(v, 5.0)
        mean = pr.get(k, 5.0)
        out[k] = max(0.0, min(10.0, round(5.0 + (raw - mean) * 1.6, 1)))
    out['universal'] = e.get('strength') == 'нейтральный'
    out['src'] = 'enrich'
    return out


def main() -> None:
    e = load()
    ss_path = os.path.join(HERE, 'style-scores.json')
    ss = json.load(open(ss_path)) if os.path.exists(ss_path) else {}

    def emb_key(mid, eid):
        return f"{mid}-{re.sub(r'[^A-Za-z0-9]', '_', str(eid))[:40]}"

    have_ss = sum(1 for k in e if emb_key(*k.split(':', 1)) in ss)
    low = sum(1 for v in e.values() if v['quality'] < MIN_QUALITY)
    subs: dict[str, int] = {}
    for v in e.values():
        subs[v['subtype']] = subs.get(v['subtype'], 0) + 1
    print(f'обогащено: {len(e)}')
    print(f'  из них уже были в style-scores.json: {have_ss} ({have_ss / len(e) * 100:.0f}%)')
    print(f'  добавляем стилевой вектор: {len(e) - have_ss}')
    print(f'  не пройдут порог качества {MIN_QUALITY}: {low} ({low / len(e) * 100:.1f}%)')
    print('\nфункциональные подтипы (топ-12):')
    for s, n in sorted(subs.items(), key=lambda kv: -kv[1])[:12]:
        print(f'  {s:26s} {n:>6}')


if __name__ == '__main__':
    main()
