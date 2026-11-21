#!/usr/bin/env python3
"""T-176 · воронка покраски: «доля товаров, прошедших все 9 этапов» (главная мерка владельца, TG 529: лучше мелкие дефекты, но все товары).

Читает `<прогон>/<sku>/<этап>/check.json` (этапы 01…08 и 09-check) и печатает:
  1) воронку по каждому прогону: этап → дошло / прошло / мягко / отказ, и отказы с причиной (мерка, значение, порог);
  2) итог «прошли 01–09: N из M» (отказов нет; строго без пометок — отдельной строкой);
  3) при двух и более прогонах — сравнение первого со вторым по ОБЩИМ товарам (этап за этапом).

Статус этапа — решение самого конвейера (`paint_check.classify_stage`, правила `rules/paint-check.json`: какие мерки жёсткие, какие мягкие), своих порогов нет.
Этап 9 — по `extra.final` его check.json (готов / готов с пометкой / не готов), считать охват и палитру заново не нужно (скрипт лёгкий, ничего не запускает).
Идентификаторов товаров в коде нет: товары — все папки прогона, где лежат папки этапов.

Запуск (только чтение, без heavy-slot):
  python3 paint_funnel.py                              # два прогона по умолчанию: ~/remlab-logs/e2e30-1121 (первый) и ~/remlab-logs/e2eHD-1121
  python3 paint_funnel.py <прогон> [<прогон> …]        # любые другие; сравнение — первого со вторым
  python3 paint_funnel.py --repo <путь к репо> …       # откуда брать paint_check и правила (по умолчанию первое найденное из списка REPOS)
  python3 paint_funnel.py --union <прогон> <прогон> …    # все прогоны вместе как один набор (для двух партий одного пути)
  python3 paint_funnel.py --json out.json …            # то же машинно (для сверки до/после влития правила)
Код возврата 0."""
import argparse
import json
import os
import re
import sys

HOME = os.path.expanduser('~')
RUNS = [HOME + '/remlab-logs/e2e30-1121', HOME + '/remlab-logs/e2eHD-1121']
REPOS = [os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')), HOME + '/remlab-logs/merge-paint-1121', HOME + '/igor/remlab']      # сперва репо, где лежит сам скрипт
NINE = '09-check'
FINAL_STATUS = {'ready': 'ok', 'ready_with_notes': 'soft', 'not_ready': 'refused'}        # `extra.final` этапа 9 → статус воронки
MARK = {'ok': 'прошёл', 'soft': 'мягко', 'refused': 'ОТКАЗ', 'missing': '—'}


def load_pc(repo):
    """Модули `paint_check`/`paint_stage` и правила — из репо (там, где они уже есть)."""
    cands = [repo] if repo else REPOS
    for r in cands:
        sc = os.path.join(r, 'tools', 'scout')
        if os.path.exists(os.path.join(sc, 'paint_check.py')):
            sys.path.insert(0, sc)
            import paint_check as PC  # noqa: E402
            import paint_stage as PS  # noqa: E402
            return PC, PS, PC.load_rules(), r
    sys.exit('нет paint_check.py ни в одном из: ' + ', '.join(cands) + ' (укажи --repo)')


def fmt_metric(name, m):
    v, t, op = m.get('value'), m.get('threshold'), m.get('op')
    return f'{name} {v}' + (f' (нужно {op} {t})' if t is not None else '')


def _why(v):
    """Причина собственного отказа этапа 9 (охват/палитра), если в его extra она записана словарём."""
    if isinstance(v, dict):
        t = v.get('reason') or v.get('why')
        t = '; '.join(t) if isinstance(t, list) else t
        return f' — {t}' if t else ''
    return ''


def products(run):
    """Товары прогона: папки с папками этапов (`NN-…`); служебные `_…` пропускаем."""
    out = []
    for n in sorted(os.listdir(run)):
        p = os.path.join(run, n)
        if n.startswith('_') or not os.path.isdir(p):
            continue
        if any(re.match(r'^\d\d-', x) and os.path.isdir(os.path.join(p, x)) for x in os.listdir(p)):
            out.append(n)
    return out


def read(PS, d):
    try:
        return PS.read_check(d)
    except Exception:  # noqa: BLE001 — битый файл = «нет check.json», как у самого конвейера
        return None


def judge(PC, PS, rules, run, sku, stages):
    """Список решений по этапам: [{stage, status, reason, failed:[текст], …}] — этапы из правил + 9."""
    res = []
    for st in stages:
        d = os.path.join(run, sku, st)
        chk = read(PS, d)
        if st == NINE:
            if chk is None:
                res.append({'stage': st, 'status': 'missing', 'reason': 'нет check.json (этап 9 не запускался)', 'failed': [], 'soft': []})
                continue
            ex = chk.get('extra') or {}
            stt = FINAL_STATUS.get(ex.get('final'), 'refused' if not chk.get('passed') else 'ok')
            notes = (ex.get('notes') or []) if stt == 'soft' else (ex.get('blocking') or [])
            first = next((s for s in ex.get('stages') or [] if s.get('status') == 'refused'), None)
            why = (notes[0] if notes else (first or {}).get('reason')) or chk.get('reason') or ''
            upstream = {s['stage'] for s in res if s['status'] in ('refused', 'missing')}     # этап 9 ругается и на то, что остановило ранний этап, — это не его отказ
            own = [str(x) for x in (ex.get('blocking') or []) if str(x).split(':')[0].strip() not in upstream]
            own_txt = [x + _why(ex.get(x)) for x in own]
            if upstream:                                                      # без итогового GLB охват и палитра не меряются — тоже следствие, не отказ этапа 9
                own_txt = [t for t in own_txt if 'нет итогового GLB' not in t]
                own = own_txt
            if stt == 'refused' and not own:
                why = 'следствие остановки на этапе выше (своих причин нет)'
            res.append({'stage': st, 'status': stt, 'reason': why, 'failed': own_txt if stt == 'refused' else [], 'soft': [str(x) for x in notes] if stt == 'soft' else []})
            continue
        c = PC.classify_stage(st, chk, rules)
        ms = c.get('metrics') or {}
        res.append({'stage': st, 'status': c['status'], 'reason': c['reason'],
                    'failed': [fmt_metric(k, ms.get(k, {})) for k in c['hard_failed']], 'soft': [fmt_metric(k, ms.get(k, {})) for k in c['soft_failed']]})
    return res


def analyse(PC, PS, rules, run):
    stages = list(rules['required_stages']) + [NINE]
    prods = products(run)
    per = {sku: judge(PC, PS, rules, run, sku, stages) for sku in prods}
    return stages, per


def passed_all(rows, strict=False):
    """Прошёл 01–09: все 9 этапов есть и ни одного отказа (strict — ещё и без «мягко»)."""
    bad = ('missing', 'refused') + (('soft',) if strict else ())
    return all(r['status'] not in bad for r in rows)


def funnel_text(label, run, stages, per):
    M = len(per)
    out = [f'=== {label}: {run} — товаров {M} ===', f'{"этап":<14}{"дошло":>7}{"прошло":>8}{"мягко":>7}{"отказ":>7}']
    refusals = {}
    for i, st in enumerate(stages):
        rows = [per[s][i] for s in per]
        reached = [r for r in rows if r['status'] != 'missing']
        n = {k: sum(1 for r in rows if r['status'] == k) for k in ('ok', 'soft', 'refused')}
        out.append(f'{st:<14}{len(reached):>7}{n["ok"]:>8}{n["soft"]:>7}{n["refused"]:>7}')
        for s in per:
            r = per[s][i]
            if r['status'] == 'refused':
                for f in (r['failed'] or [r['reason'] or 'причина не названа']):
                    refusals.setdefault((st, f), []).append(s)
    if refusals:
        out += ['', 'отказы (этап · мерка → товаров):']
        for (st, f), skus in sorted(refusals.items()):
            out.append(f'  {st} · {f} → {len(skus)}: ' + ', '.join(skus[:6]) + (' …' if len(skus) > 6 else ''))
    soft = {}
    for s in per:
        for r in per[s]:
            for f in ([] if r['stage'] == NINE else r.get('soft', [])):         # пометки этапа 9 повторяют пометки этапов выше — не считаем дважды
                soft.setdefault((r['stage'], re.sub(r' [-\d.]+.*$', '', f)), []).append(s)
    if soft:
        out += ['', 'мягко (пометки; этап не останавливают): ' + '; '.join(f'{st} · {k} ×{len(v)}' for (st, k), v in sorted(soft.items()))]
    n_ok = sum(1 for s in per if passed_all(per[s]))
    n_strict = sum(1 for s in per if passed_all(per[s], True))
    out += ['', f'ИТОГ {label}: прошли 01–09: {n_ok} из {M}' + (f' ({100 * n_ok / M:.0f} %)' if M else '') + f'; без единой пометки: {n_strict} из {M}']
    blockers = [f'{s}: ' + next((f'{r["stage"]} — {(r["failed"] or [r["reason"]])[0]}' for r in per[s] if r['status'] in ('refused', 'missing')), '') for s in per if not passed_all(per[s])]
    if blockers:
        out += ['не прошли (первая остановка):'] + ['  ' + b[:230] for b in blockers]
    return out


def compare_text(la, per_a, lb, per_b, stages):
    common = [s for s in per_a if s in per_b]
    out = [f'=== сравнение {la} ↔ {lb} по общим товарам: {len(common)} (в {la} {len(per_a)}, в {lb} {len(per_b)}) ===']
    if not common:
        return out + ['общих товаров нет']
    w = max(len(s) for s in common)
    out.append(f'{"sku":<{w}}  {"этап":<12}{la:<14}{lb:<14}')
    diff = 0
    for s in common:
        a, b = per_a[s], per_b[s]
        for i, st in enumerate(stages):
            if a[i]['status'] != b[i]['status']:
                diff += 1
                out.append(f'{s:<{w}}  {st:<12}{MARK[a[i]["status"]]:<14}{MARK[b[i]["status"]]:<14}' + ((b[i]['failed'] or [b[i]['reason']])[0][:70] if b[i]['status'] == 'refused' else (a[i]['failed'] or [a[i]['reason']])[0][:70] if a[i]['status'] == 'refused' else ''))
    if not diff:
        out.append('этапы по всем общим товарам совпали')
    na = sum(1 for s in common if passed_all(per_a[s]))
    nb = sum(1 for s in common if passed_all(per_b[s]))
    out.append(f'прошли 01–09 на общих: {la} {na} из {len(common)}, {lb} {nb} из {len(common)}')
    return out


def main(argv):
    ap = argparse.ArgumentParser(description='воронка 01–09 по папкам прогонов')
    ap.add_argument('runs', nargs='*', help='папки прогонов; сравнение — первого со вторым')
    ap.add_argument('--repo')
    ap.add_argument('--json')
    ap.add_argument('--union', action='store_true', help='посчитать все прогоны вместе как один набор товаров (повтор sku — берётся из первого прогона, где он есть)')
    a = ap.parse_args(argv)
    runs = [os.path.expanduser(r).rstrip('/') for r in (a.runs or RUNS)]
    PC, PS, rules, repo = load_pc(a.repo)
    print(f'правила и разбор этапов: {repo}\n')
    res, dump = [], {}
    for r in runs:
        if not os.path.isdir(r):
            print(f'=== {r}: нет папки ===\n')
            continue
        stages, per = analyse(PC, PS, rules, r)
        label = os.path.basename(r)
        res.append((label, per, stages))
        print('\n'.join(funnel_text(label, r, stages, per)) + '\n')
        dump[label] = {s: [{k: x[k] for k in ('stage', 'status', 'reason')} for x in rows] for s, rows in per.items()}
    if a.union and len(res) >= 2:
        merged = {}
        for _l, per, _st in res:
            for sku, rows in per.items():
                merged.setdefault(sku, rows)
        print('\n'.join(funnel_text('вместе ' + '+'.join(x[0] for x in res), 'union', res[0][2], merged)) + '\n')
    if len(res) >= 2 and not a.union:
        print('\n'.join(compare_text(res[0][0], res[0][1], res[1][0], res[1][1], res[0][2])))
    if a.json:
        json.dump(dump, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
