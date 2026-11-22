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
В конце — сводка-самопроверка и страница прогона (`paint_run_report.py`, T-180/4): вошло · остановились · покрашено · кадров; страница «фото | наш 3D» по всем покрашенным
в `<прогон>/_report/` (`--report-out`, `--report-name`; `--publish-report` — на /test/paint-<имя>/; `--no-report` — только для тестов).
Код возврата 0; 1 — самопроверка сводки не сошлась (или кадр не построился)."""
import argparse
import json
import math
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
        res.append({'stage': st, 'status': c['status'], 'reason': c['reason'], 'margin': stage_margin(ms),
                    'failed': [fmt_metric(k, ms.get(k, {})) for k in c['hard_failed']], 'soft': [fmt_metric(k, ms.get(k, {})) for k in c['soft_failed']]})
    return res


def stage_margin(ms):
    """Запас этапа до порога: наименьший по меркам с порогом (≥0 — прошла с запасом, <0 — не дотянула). Доля «≥ t при v ≤ 1» (охват, доля граней) — от оставшегося до 1 (запас (v−t)/(1−t)),
    остальные — от порога; целые счётчики и флаги (оба целые: число граней под потолком, «есть/нет») не мерим — потолок и булево запаса не дают. Порог 0 — запас 1 при выполнении. None — мерок нет."""
    out = []
    for m in (ms or {}).values():
        v, t, op = m.get('value'), m.get('threshold'), m.get('op')
        if isinstance(v, bool) or isinstance(t, bool) or not isinstance(v, (int, float)) or not isinstance(t, (int, float)) or op not in ('>=', '<=', '>', '<') or m.get('na'):
            continue
        if isinstance(v, int) and isinstance(t, int) and t:
            continue
        d = (v - t) if op in ('>=', '>') else (t - v)
        if op in ('>=', '>') and 0 < t < 1 and v <= 1:
            out.append(min(1.0, d / (1 - t)))
        else:
            out.append(min(1.0, d / abs(t)) if t else (1.0 if d >= 0 else -1.0))
    return min(out) if out else None


def row_margin(rows):
    """Запас товара: наименьший по этапам 01–08, где он есть (этап 9 — итог, не мерка)."""
    ms = [r['margin'] for r in rows if r.get('margin') is not None]
    return min(ms) if ms else None


def analyse(PC, PS, rules, run):
    stages = list(rules['required_stages']) + [NINE]
    prods = products(run)
    per = {sku: judge(PC, PS, rules, run, sku, stages) for sku in prods}
    return stages, per


def passed_all(rows, strict=False):
    """Прошёл 01–09: все 9 этапов есть и ни одного отказа (strict — ещё и без «мягко»)."""
    bad = ('missing', 'refused') + (('soft',) if strict else ())
    return all(r['status'] not in bad for r in rows)


def pct(n, d):
    return f' ({100 * n / d:.0f} %)' if d else ''


def wilson(k, n, z=1.96):
    """95 % доверительный интервал доли k/n (Уилсон) — на малой выборке честнее «k/n»."""
    if not n:
        return None
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, c - h), min(1.0, c + h)


def read_grades(path):
    """Оценки глазами: TSV `sku<TAB>этап<TAB>вердикт(ок|плохо)<TAB>что`; пустой вердикт — не оценено; несколько строк на товар — товар плохой, если есть хоть одно «плохо»."""
    g = {}
    if not path or not os.path.exists(path):
        return g
    for ln in open(path, encoding='utf-8'):
        if ln.startswith('#') or not ln.strip() or ln.lower().startswith('sku\t'):
            continue
        p = ln.rstrip('\n').split('\t')
        if len(p) < 3:
            continue
        v = p[2].strip().lower()
        if v in ('ок', 'ok', 'хорошо', 'good'):
            g.setdefault(p[0].strip(), []).append(('ok', p[1].strip(), p[3].strip() if len(p) > 3 else ''))
        elif v in ('плохо', 'bad', 'нет'):
            g.setdefault(p[0].strip(), []).append(('bad', p[1].strip(), p[3].strip() if len(p) > 3 else ''))
    return g


def yield_lines(label, per, submitted=None, grades=None):
    """Две цифры сводки. publishable_yield = прошли все 9 СТРОГО (ни одного отказа, ни одного «мягко») / все поданные (папки прогона + список `--submitted`, если дан);
    false_accept_rate = плохие среди принятых по выборке глазами (если оценок нет — «не оценён»). «Мягко» ≠ прошёл; прежняя мягкая доля — отдельной справочной строкой."""
    M = len(set(per) | set(submitted or []))
    n_strict = sum(1 for s in per if passed_all(per[s], True))
    n_soft = sum(1 for s in per if passed_all(per[s]))
    out = [f'ИТОГ {label}: publishable_yield = прошли 01–09 СТРОГО (без отказов и без «мягко»): {n_strict} из {M}' + pct(n_strict, M)]
    if submitted and M > len(per):
        out[0] += f' [поданных {M}, из них в прогоне {len(per)}: остальные до этапов не дошли]'
    out.append(f'  справочно, мягкая мерка (отказов нет, «мягко» не считается отказом — прежняя, к ИТОГУ не относится): {n_soft} из {M}' + pct(n_soft, M))
    acc = {s for s in per if passed_all(per[s], True)}
    gr = {s: v for s, v in (grades or {}).items() if s in acc}
    stray = len([s for s in (grades or {}) if s in per and s not in acc])
    if not gr:
        out.append('  false_accept_rate: не оценён (выборка «посмотреть глазами» не размечена; `--sample N` пишет look.txt + grades.tsv, `--grades grades.tsv` считает)')
        return out
    bad = sum(1 for v in gr.values() if any(x[0] == 'bad' for x in v))
    ci = wilson(bad, len(gr))
    far = bad / len(gr)
    out.append(f'  false_accept_rate = плохие среди принятых: {bad} из {len(gr)} оценённых' + pct(bad, len(gr)) + (f', 95 % интервал {100 * ci[0]:.0f}–{100 * ci[1]:.0f} %' if ci else '')
               + f'; принятых всего {len(acc)}, оценено {len(gr)}' + (f'; {stray} оценок не по принятым — не учтены' if stray else ''))
    out.append(f'  с поправкой: publishable_yield × (1 − false_accept_rate) ≈ {100 * n_strict / M * (1 - far):.0f} % от поданных' if M else '')
    return out


def product_type(run, PS, sku):
    """Тип товара (страта выборки): `product_role` этапа 3 (extra.roles_summary), иначе группа, иначе «?»."""
    chk = read(PS, os.path.join(run, sku, '03-parts'))
    rs = ((chk or {}).get('extra') or {}).get('roles_summary') or {}
    return rs.get('product_role') or rs.get('group') or '?'


def make_sample(per, types, n, seed, margin_min, conf_share):
    """Стратифицированная выборка из ПРИНЯТЫХ (строгих): по типу пропорционально (минимум один на тип, пока хватает n), в каждом типе — не менее `conf_share` уверенно прошедших
    (запас ≥ `margin_min` от порога на самом тесном этапе) и остальные «на грани» (случайно из менее уверенных). Сид фиксирован — повтор даёт ту же выборку. → [(sku, тип, уверенно, запас)]."""
    import random
    rnd = random.Random(seed)
    acc = sorted(s for s in per if passed_all(per[s], True))
    by = {}
    for s in acc:
        by.setdefault(types.get(s, '?'), []).append(s)
    if not acc or n <= 0:
        return []
    n = min(n, len(acc))
    tp = sorted(by, key=lambda t: (-len(by[t]), t))
    quota = {t: 0 for t in tp}
    for t in tp[:n]:
        quota[t] = 1
    left = n - sum(quota.values())
    if left > 0:
        raw = {t: min(len(by[t]), left * len(by[t]) / len(acc)) for t in tp}
        for t in tp:
            add = min(len(by[t]) - quota[t], int(raw[t]))
            quota[t] += add
        left = n - sum(quota.values())
        for t in sorted(tp, key=lambda t: -(raw[t] - int(raw[t]))):
            if left <= 0:
                break
            if quota[t] < len(by[t]):
                quota[t] += 1
                left -= 1
        for t in tp:                                                       # остаток — в самые большие типы
            while left > 0 and quota[t] < len(by[t]):
                quota[t] += 1
                left -= 1
    out = []
    for t in tp:
        ss = by[t][:]
        rnd.shuffle(ss)
        mg = {s: row_margin(per[s]) for s in ss}
        conf = [s for s in ss if mg[s] is not None and mg[s] >= margin_min]
        edge = [s for s in ss if s not in conf]
        k = quota[t]
        want_c = min(len(conf), math.ceil(k * conf_share))
        pick_c = conf[:max(want_c, k - len(edge))]
        pick_e = edge[:k - len(pick_c)]
        for s in pick_c + pick_e:
            out.append((s, t, s in pick_c, mg[s]))
    return out


def write_sample(sample, runof, PS, outdir, label):
    """look.txt (что смотреть: товар, тип, уверенно/на грани, запас, кадры этапов) и grades.tsv (бланк оценки: товар, этап, ок/плохо, что) — в `<outdir>/<label>/`."""
    d = os.path.join(outdir, label)
    os.makedirs(d, exist_ok=True)
    look = [f'# выборка «посмотреть глазами» — {label}: {len(sample)} принятых (строго) товаров; «уверенно» = запас до порога ≥ заданного, «на грани» — меньше',
            '# что смотреть: кадры этапов (frame.png в папках этапов) и итоговую модель; плохое — вписать в grades.tsv']
    tsv = ['sku\tэтап\tвердикт\tчто', '# вердикт: ок | плохо (пусто — не оценено); этап — где видно плохое (09-check — если в целом); один товар можно писать несколькими строками']
    for s, t, conf, mg in sample:
        run = runof[s]
        frames = [os.path.join(run, s, st, PS.FRAME) for st in sorted(os.listdir(os.path.join(run, s))) if re.match(r'^\d\d-', st) and os.path.exists(os.path.join(run, s, st, PS.FRAME))]
        look.append(f'{s}\t{t}\t{"уверенно" if conf else "на грани"}\tзапас {("—" if mg is None else f"{100 * mg:.0f} %")}\t' + ' '.join(frames))
        tsv.append(f'{s}\t\t\t')
    open(os.path.join(d, 'look.txt'), 'w', encoding='utf-8').write('\n'.join(look) + '\n')
    open(os.path.join(d, 'grades.tsv'), 'w', encoding='utf-8').write('\n'.join(tsv) + '\n')
    return d


def funnel_text(label, run, stages, per, submitted=None, grades=None):
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
    out += [''] + [x for x in yield_lines(label, per, submitted, grades) if x]
    blockers = [f'{s}: ' + next((f'{r["stage"]} — {(r["failed"] or [r["reason"]])[0]}' for r in per[s] if r['status'] in ('refused', 'missing')), '') for s in per if not passed_all(per[s])]
    soft_only = [s for s in per if passed_all(per[s]) and not passed_all(per[s], True)]
    if blockers:
        out += ['не прошли (первая остановка):'] + ['  ' + b[:230] for b in blockers]
    if soft_only:
        out += ['прошли только «мягко» (в ИТОГ не входят): ' + ', '.join(soft_only[:8]) + (' …' if len(soft_only) > 8 else '')]
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
    na, nb = (sum(1 for s in common if passed_all(p[s], True)) for p in (per_a, per_b))
    sa, sb = (sum(1 for s in common if passed_all(p[s])) for p in (per_a, per_b))
    out.append(f'прошли 01–09 СТРОГО на общих: {la} {na} из {len(common)}, {lb} {nb} из {len(common)}; справочно мягко: {la} {sa}, {lb} {sb}')
    return out


def before_after(res, union=None):
    """Таблица «было → стало» по прогонам: было — прежняя мягкая доля (мягко ≈ прошёл), стало — строгая (publishable_yield)."""
    out = ['=== было → стало (прежняя мягкая доля → строгая publishable_yield) ===', f'{"прогон":<28}{"поданных":>9}{"было, мягко":>14}{"стало, строго":>16}{"только мягко":>14}']
    tot = [0, 0, 0, 0]
    for label, per, _st in res:
        M, soft = len(per), sum(1 for s in per if passed_all(per[s]))
        strict = sum(1 for s in per if passed_all(per[s], True))
        out.append(f'{label:<28}{M:>9}{f"{soft} ({100 * soft / M:.0f} %)" if M else "—":>14}{f"{strict} ({100 * strict / M:.0f} %)" if M else "—":>16}{soft - strict:>14}')
        tot = [tot[0] + M, tot[1] + soft, tot[2] + strict, tot[3] + soft - strict]
    if len(res) > 1 and tot[0]:
        out.append(f'{"сумма прогонов":<28}{tot[0]:>9}{f"{tot[1]} ({100 * tot[1] / tot[0]:.0f} %)":>14}{f"{tot[2]} ({100 * tot[2] / tot[0]:.0f} %)":>16}{tot[3]:>14}')
    if union:
        M, soft = len(union), sum(1 for s in union if passed_all(union[s]))
        strict = sum(1 for s in union if passed_all(union[s], True))
        out.append(f'{"все вместе (без повторов)":<28}{M:>9}{f"{soft} ({100 * soft / M:.0f} %)" if M else "—":>14}{f"{strict} ({100 * strict / M:.0f} %)" if M else "—":>16}{soft - strict:>14}')
    return out


def main(argv):
    ap = argparse.ArgumentParser(description='воронка 01–09 по папкам прогонов: строгая доля (publishable_yield) и выборка «ложно принятых» (false_accept_rate)')
    ap.add_argument('runs', nargs='*', help='папки прогонов; сравнение — первого со вторым')
    ap.add_argument('--repo')
    ap.add_argument('--json')
    ap.add_argument('--union', action='store_true', help='посчитать все прогоны вместе как один набор товаров (повтор sku — берётся из первого прогона, где он есть)')
    ap.add_argument('--submitted', help='файл со списком поданных товаров (по строке на sku): знаменатель publishable_yield, если поданных больше, чем папок в прогоне')
    ap.add_argument('--sample', type=int, default=0, help='N: выбрать N принятых (строго) товаров стратифицированно по типу — часть уверенно прошедших — и записать look.txt + grades.tsv в --sample-dir')
    ap.add_argument('--sample-dir', default='funnel-sample', help='куда писать look.txt и бланк grades.tsv (по подпапке на прогон)')
    ap.add_argument('--seed', type=int, default=0, help='сид выборки (повтор даёт ту же)')
    ap.add_argument('--confident-margin', type=float, default=0.25, help='«уверенно прошёл»: запас до порога на самом тесном этапе ≥ этой доли порога')
    ap.add_argument('--confident-share', type=float, default=0.5, help='доля уверенно прошедших в выборке каждого типа (не меньше)')
    ap.add_argument('--grades', help='TSV с оценками глазами (бланк grades.tsv после заполнения): считается false_accept_rate')
    ap.add_argument('--no-report', action='store_true', help='ТОЛЬКО ДЛЯ ТЕСТОВ: не строить сводку-самопроверку и страницу прогона (T-180/4: по умолчанию строятся всегда, `paint_run_report.py`)')
    ap.add_argument('--report-out', help='куда класть сводку и страницу (по умолчанию `<прогон>/_report`; для --union — `<первый прогон>/_report-union`)')
    ap.add_argument('--report-name', help='имя страницы для /test/paint-<имя>/ (по умолчанию — метка прогона)')
    ap.add_argument('--publish-report', action='store_true', help='выложить страницу на /test/paint-<имя>/ (по умолчанию только локально)')
    a = ap.parse_args(argv)
    runs = [os.path.expanduser(r).rstrip('/') for r in (a.runs or RUNS)]
    PC, PS, rules, repo = load_pc(a.repo)
    print(f'правила и разбор этапов: {repo}\n')
    submitted = [x.strip() for x in open(a.submitted, encoding='utf-8') if x.strip()] if a.submitted else None
    grades = read_grades(a.grades)
    res, dump, runof, types = [], {}, {}, {}
    for r in runs:
        if not os.path.isdir(r):
            print(f'=== {r}: нет папки ===\n')
            continue
        stages, per = analyse(PC, PS, rules, r)
        label = os.path.basename(r)
        res.append((label, per, stages))
        for sk in per:
            runof.setdefault(sk, r)
            types.setdefault(sk, product_type(r, PS, sk))
        print('\n'.join(funnel_text(label, r, stages, per, submitted if len(runs) == 1 else None, grades)) + '\n')
        dump[label] = {s: [{k: x[k] for k in ('stage', 'status', 'reason')} for x in rows] for s, rows in per.items()}
        if a.sample:
            sm = make_sample(per, types, a.sample, a.seed, a.confident_margin, a.confident_share)
            d = write_sample(sm, runof, PS, a.sample_dir, label)
            print(f'выборка «посмотреть глазами» {label}: {len(sm)} из {sum(1 for s in per if passed_all(per[s], True))} принятых → {d}/look.txt, бланк {d}/grades.tsv; типы: ' + ', '.join(f'{t} ×{sum(1 for x in sm if x[1] == t)}' for t in sorted({x[1] for x in sm})) + '\n')
    merged = {}
    if a.union and len(res) >= 2:
        for _l, per, _st in res:
            for sku, rows in per.items():
                merged.setdefault(sku, rows)
        ul = 'вместе ' + '+'.join(x[0] for x in res)
        print('\n'.join(funnel_text(ul, 'union', res[0][2], merged, submitted, grades)) + '\n')
        if a.sample:
            sm = make_sample(merged, types, a.sample, a.seed, a.confident_margin, a.confident_share)
            d = write_sample(sm, runof, PS, a.sample_dir, 'union')
            print(f'выборка «посмотреть глазами» (все прогоны вместе): {len(sm)} → {d}/look.txt, бланк {d}/grades.tsv\n')
    if len(res) >= 2 and not a.union:
        print('\n'.join(compare_text(res[0][0], res[0][1], res[1][0], res[1][1], res[0][2])) + '\n')
    if res:
        print('\n'.join(before_after(res, merged or None)))
    rc = 0
    if res and not a.no_report:                                 # T-180/4: числа и кадры прогона — автоматом; расхождение сводки = ненулевой код
        import paint_run_report as PRR
        live = [r for r in runs if os.path.isdir(r)]
        groups = [(live, {x[0]: x[1] for x in res}, a.report_out or os.path.join(live[0], '_report-union' if len(live) > 1 else '_report'))] if (a.union and len(res) >= 2) else \
                 [([r], {x[0]: x[1]}, a.report_out if (a.report_out and len(res) == 1) else os.path.join(r, '_report')) for r, x in zip(live, res)]
        for rs, pb, od in groups:
            rc |= PRR.report(rs, pb, od, repo, a.report_name, a.publish_report)
    if a.json:
        out = dict(dump)
        out['_yield'] = {l: {'publishable_yield': (sum(1 for s in p if passed_all(p[s], True)) / len(p)) if p else None, 'soft_reference': (sum(1 for s in p if passed_all(p[s])) / len(p)) if p else None, 'submitted': len(p)} for l, p, _s in res}
        json.dump(out, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
