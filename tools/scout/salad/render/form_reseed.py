#!/usr/bin/env python3
"""Правило повтора формы TRELLIS.2 (T-20261126-99/8, П1.164): по вердикту автопроверок формы (`form_checks.run_sku`) решает — взять форму, повторить генерацию с новым «зерном» или отказать.
Основа — замер T-99/1 (новый seed лечит классы Т/Л/У/С, но не класс Н) и ответ Codex (паспорт 5б, `plans/mesh-type-rules-01.md`): Н — только карантин, не правило; повтор — «лучший из ВСЕХ образцов, а не первый прошедший».

ФЛАГ `FORM_RESEED` (окружение; по умолчанию 0):
  0       · выключено: форма-гейт пишет всё как раньше, этот модуль ничего не добавляет (план побайтно тот же);
  shadow  · только пишет решение («что было бы сделано») в запись формы `rec['reseed']`; ничего не генерирует и ничего не меняет в статусе;
  1       · включено: то же решение — действие (повтор/отказ) для вызывающего конвейера. Платные повторы без слова владельца не запускаются (этот модуль генерацию не умеет).

РЕШЕНИЕ по одной форме (`plan_one`):
  не удалось проверить (glb_sane / мало измеренных проверок / флаг есть, а класса нет) → отказ «не удалось проверить», без повторов;
  счёт ≤ `pass_score_max`                                                              → keep (форма годна);
  класс Н                                                                               → отказ «число опор/дверей не как на фото», метка `quarantine_n` (карантин, правилом не считается);
  класс Т/Л/У/С                                                                         → reseed: до `n_new_max` новых образцов.
По набору образцов (`decide`: исходная + новые): из ВСЕХ, у кого проверка получилась, берётся лучший по счёту (меньше — лучше; при равенстве раньше стоящий, то есть исходная), а не первый прошедший; ни один не прошёл → отказ.
Класс брака — по флагам проверок (`class_checks`, порядок `class_priority`: Н первым — он уводит в карантин); флагом считается и `would_flag` («сработало бы»: у мерок толщины/габаритов флаг выключен), если `use_would_flag`.
Все пороги, таблицы классов и причины — `tools/scout/rules/form-reseed.json`; в коде ни порогов, ни ID товаров.
Запуск тени по сохранённым проверкам: python form_reseed.py --raw raw_checks.json --eye metki.json --key KLYUCH.json --manifest manifest.json --out DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'form-reseed.json'))
MODES = ('0', 'shadow', '1')


def mode(env: dict | None = None) -> str:
    """Режим из FORM_RESEED; любое незнакомое значение — выключено (безопасный выбор)."""
    v = str((os.environ if env is None else env).get('FORM_RESEED', '0')).strip().lower()
    return v if v in MODES else '0'


def load_rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


def _derived(c: dict, R: dict) -> bool:
    d = (R.get('derived_flags') or {}).get(c['name'])
    if not d or c.get('value') is None:
        return False
    v, t = float(c['value']), float(d['thr'])
    return {'<': v < t, '>': v > t, '<=': v <= t, '>=': v >= t}[d['op']]


def flagged(rec: dict, R: dict) -> list[str]:
    """Имена проверок, считающихся сработавшими: флаг, `would_flag` (если разрешено) или производный флаг из rules."""
    out = []
    for c in rec.get('checks', []):
        if c.get('flag') or (R.get('use_would_flag') and c.get('would_flag')) or _derived(c, R):
            out.append(c['name'])
    return out


def score(names: list[str], R: dict) -> float:
    w = R.get('weights') or {}
    return float(sum(w.get(n, w.get('default', 1.0)) for n in names))


def klass(names: list[str], R: dict) -> str | None:
    """Класс брака по сработавшим проверкам; приоритет — `class_priority`. Нет сработавших или ни одна не в таблице — None."""
    for k in R['class_priority']:
        if any(n in (R['class_checks'].get(k) or []) for n in names):
            return k
    return None


def measured(rec: dict) -> int:
    return sum(1 for c in rec.get('checks', []) if c.get('value') is not None)


def verdict(rec: dict, R: dict) -> dict:
    """Оценка одного образца: имена сработавших, счёт, класс, проверяемость. `ok` — счёт не больше порога."""
    names = flagged(rec, R)
    unver = None
    if any(n in (R.get('unverifiable_flags') or []) for n in names):
        unver = 'glb_sane: форма не читается или пуста'
    elif measured(rec) < int(R['min_measured']):
        unver = f"измерено проверок {measured(rec)} < {R['min_measured']}"
    cls = klass(names, R)
    sc = score(names, R)
    if unver is None and names and cls is None:
        unver = 'сработали проверки без класса брака: ' + ','.join(names)
    return {'flags': names, 'score': sc, 'class': cls, 'unverifiable': unver, 'ok': unver is None and sc <= float(R['pass_score_max'])}


def plan_one(rec: dict, R: dict) -> dict:
    """Решение по одной (исходной) форме: keep | reseed | refuse. Генерации не делает."""
    v = verdict(rec, R)
    base = {'flags': v['flags'], 'score': v['score'], 'class': v['class']}
    if v['unverifiable']:
        return dict(base, action='refuse', reason=R['reasons']['unverifiable'], detail=v['unverifiable'], quarantine=None)
    if v['ok']:
        return dict(base, action='keep', reason='годна', quarantine=None)
    if v['class'] in R['quarantine_classes']:
        return dict(base, action='refuse', reason=R['reasons']['quarantine_n'], quarantine='quarantine_n')
    if v['class'] in R['reseed_classes']:
        return dict(base, action='reseed', reason=f"класс {v['class']}: до {R['n_new_max']} новых образцов", n_new=int(R['n_new_max']), quarantine=None)
    return dict(base, action='refuse', reason=R['reasons']['unverifiable'], detail='класс не определён', quarantine=None)


def decide(recs: list[dict], R: dict) -> dict:
    """Решение по набору образцов `recs` = [исходная, новый 1, новый 2, …] (порядок важен: при равном счёте побеждает раньше стоящая). Берутся только первые 1+`n_new_max`.
    Возврат: action keep | pick | refuse, `chosen` — индекс выбранного образца (0 — исходная), план по исходной и оценки всех образцов."""
    recs = recs[:1 + int(R['n_new_max'])]
    first = plan_one(recs[0], R)
    vs = [verdict(r, R) for r in recs]
    out = {'first': first, 'verdicts': vs, 'chosen': None}
    if first['action'] == 'keep':
        return dict(out, action='keep', chosen=0, reason=first['reason'])
    if first['action'] == 'refuse':
        return dict(out, action='refuse', reason=first['reason'], quarantine=first.get('quarantine'))
    cand = [(v['score'], i) for i, v in enumerate(vs) if not v['unverifiable']]
    if len(recs) == 1 or not cand:
        return dict(out, action='reseed' if len(recs) == 1 else 'refuse', reason=first['reason'] if len(recs) == 1 else R['reasons']['unverifiable'])
    sc, i = min(cand)
    if sc <= float(R['pass_score_max']):
        return dict(out, action='pick', chosen=i, reason=f'лучший из {len(recs)} образцов: №{i}, счёт {sc:g}')
    return dict(out, action='refuse', reason=R['reasons']['none_passed'], best=i)


def annotate(rec: dict, env: dict | None = None, R: dict | None = None) -> dict:
    """Точка входа для форма-гейта: при FORM_RESEED=0 запись возвращается как есть (тот же объект, ключей не добавляется); иначе добавляется `rec['reseed']` с планом по этой форме."""
    m = mode(env)
    if m == '0':
        return rec
    rec['reseed'] = dict(plan_one(rec, R or load_rules()), mode=m, executed=False)
    return rec


# ---------- тень по сохранённым образцам T-99/1 ----------
SEEDS_SAME_INPUT = ('hdA', 'hdB')                    # два новых seed на том же входе, что у исходной (у всех, кроме К2: исходная HD)
SEEDS_NATIVE = ('curA', 'curB')                      # у К2 исходная — родная форма, тот же вход = обычный


def shadow(raw: dict, eye: dict, key: dict, R: dict) -> dict:
    """Таблицы «решение конвейера ↔ глаз директора». `raw` — {«товар:вид»: {rec,…}} (проверки по образцам), `eye` — {товар: {буква: ok|bad}}, `key` — буквы → вид образца (KLYUCH)."""
    forms, items = [], []
    for it, v in key.items():
        lab = {x['kind']: eye[it][L] for L, x in v['letters'].items() if it in eye and L in eye[it]}
        orig_kind = 'old_native' if any(x['kind'] == 'old_native' for x in v['letters'].values()) else 'orig_hd'
        seeds = SEEDS_NATIVE if orig_kind == 'old_native' else SEEDS_SAME_INPUT
        for kind, e in lab.items():
            r = raw.get(f'{it}:{kind}')
            if not r:
                continue
            vd = verdict(r['rec'], R)
            forms.append({'item': it, 'kind': kind, 'eye': e, 'auto_ok': vd['ok'], 'class': vd['class'], 'flags': vd['flags'], 'unverifiable': vd['unverifiable'], 'seed': kind in seeds,
                          'agree': (vd['ok'] and e == 'ok') or ((not vd['ok']) and e == 'bad')})
        names = [orig_kind] + [s for s in seeds if f'{it}:{s}' in raw]
        recs = [raw[f'{it}:{k}']['rec'] for k in names if f'{it}:{k}' in raw]
        if not recs:
            continue
        d = decide(recs, R)
        ch = names[d['chosen']] if d.get('chosen') is not None else None
        any_good = any(lab.get(k) == 'ok' for k in names)
        if d['action'] in ('keep', 'pick'):
            outcome = 'взяли годную' if lab.get(ch) == 'ok' else 'ВЗЯЛИ ПЛОХУЮ'
        else:
            outcome = 'ОТКАЗАЛИ ХОРОШЕЙ (годная была)' if any_good else 'отказали верно (годной не было)'
        items.append({'item': it, 'name': v['name'], 'cls_old_frame': v['cls'], 'action': d['action'], 'reason': d['reason'], 'chosen': ch, 'quarantine': d.get('quarantine'), 'outcome': outcome,
                      'first_class': d['first']['class'], 'first_flags': d['first']['flags'], 'names': names, 'eye': {k: lab.get(k) for k in names}})
    return {'forms': forms, 'items': items}


def report(sh: dict) -> str:
    f, it = sh['forms'], sh['items']
    new = [x for x in f if x['kind'] not in ('orig_hd', 'old_native', 'old_s42')]
    n_ag = sum(x['agree'] for x in f)
    n_ag_new = sum(x['agree'] for x in new)
    bad_taken = sum(1 for x in f if x['auto_ok'] and x['eye'] == 'bad')
    good_refused = sum(1 for x in f if (not x['auto_ok']) and x['eye'] == 'ok')
    unver = sum(1 for x in f if x['unverifiable'])
    lines = ['## По формам: автопроверка (счёт ≤ порога = годна) ↔ глаз директора', f'размеченных форм {len(f)}; из них новых образцов {len(new)}',
             f'совпало с глазом: {n_ag} из {len(f)}; на новых образцах {n_ag_new} из {len(new)}',
             f'авто «годна», глаз «брак» (взяли бы плохую): {bad_taken}; авто «брак», глаз «годна» (отказали бы хорошей): {good_refused}; не удалось проверить: {unver}', '',
             '| товар | вид | глаз | авто | класс | сработало |', '|---|---|---|---|---|---|']
    for x in f:
        lines.append(f"| {x['item']} | {x['kind']} | {x['eye']} | {'годна' if x['auto_ok'] else ('не проверить' if x['unverifiable'] else 'брак')} | {x['class'] or '—'} | {', '.join(x['flags']) or '—'} |")
    lines += ['', '## По товарам: решение конвейера (исходная + 2 новых seed) ↔ глаз', '| товар | решение | выбрано | причина | исход | глаз по образцам |', '|---|---|---|---|---|---|']
    for x in it:
        lines.append(f"| {x['item']} {x['name']} | {x['action']}{' · ' + x['quarantine'] if x['quarantine'] else ''} | {x['chosen'] or '—'} | {x['reason']} | {x['outcome']} | " + ', '.join(f'{k}={v}' for k, v in x['eye'].items()) + ' |')
    cnt = {}
    for x in it:
        cnt[x['outcome']] = cnt.get(x['outcome'], 0) + 1
    lines += ['', 'исходы по товарам: ' + '; '.join(f'{k} — {v}' for k, v in sorted(cnt.items()))]
    return '\n'.join(lines) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True, help='raw_checks.json: проверки по образцам (collect)')
    ap.add_argument('--eye', required=True, help='metki.json директора {товар: {буква: ok|bad}}')
    ap.add_argument('--key', required=True, help='KLYUCH.json: буква → вид образца')
    ap.add_argument('--rules', default=RULES)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    R = load_rules(a.rules)
    sh = shadow(json.load(open(a.raw, encoding='utf-8')), json.load(open(a.eye, encoding='utf-8')), json.load(open(a.key, encoding='utf-8')), R)
    os.makedirs(a.out, exist_ok=True)
    json.dump(sh, open(os.path.join(a.out, 'shadow.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    txt = report(sh)
    open(os.path.join(a.out, 'shadow.md'), 'w', encoding='utf-8').write(txt)
    print(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main())
