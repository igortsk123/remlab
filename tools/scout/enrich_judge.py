#!/usr/bin/env python3
"""А7: контур мониторинга обогащения — судья-сэмпл + дрифт-бейзлайн + копилка для голдена.

Стандарт индустрии (Shopify ICLR 2025, сверка 2026-08-06): рабочую модель ежедневно проверяет
сильная на СЭМПЛЕ свежего трафика; согласие сравнивается с историческим бейзлайном, просадка —
алерт; расхождения копятся как кандидаты в golden set (голден из прод-ошибок, а не из головы).

  ~/venvs/scout/bin/python enrich_judge.py            # сэмпл из обогащённых сегодня
  ~/venvs/scout/bin/python enrich_judge.py --any      # сэмпл из всего пула (первый бейзлайн)
Пишет: enrich-drift.jsonl (строка в день), golden-candidates.jsonl (расхождения).
Дешёвый предохранитель: сэмпл ≤ JUDGE_N (дефолт 30), при <10 свежих — выходим молча.
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from enrich import MODEL_STRONG, sql  # noqa: E402
from golden_label import _key  # noqa: E402
from rules0 import pool  # noqa: E402

JUDGE_N = int(os.environ.get('JUDGE_N', '30'))
DRIFT_LOG = os.path.join(HERE, 'enrich-drift.jsonl')
CAND_LOG = os.path.join(HERE, 'golden-candidates.jsonl')
DROP_ALERT_PP = 10.0          # просадка согласия к бейзлайну, после которой зовём человека


def _styles_close(a: dict, b: dict) -> bool:
    """Стили сходятся, если по каждому стилю расхождение ≤1 ступени (критерий голдена)."""
    steps = {'нет': 0, 'низкая': 1, 'средняя': 2, 'высокая': 3}
    for k in set(a) | set(b):
        if abs(steps.get(str(a.get(k, 'нет')), 0) - steps.get(str(b.get(k, 'нет')), 0)) > 1:
            return False
    return True


def main() -> None:
    fresh_only = '--any' not in sys.argv
    cond = "and e.enriched_at::date = current_date" if fresh_only else ''
    rows = sql(f"""select e.shop_mid, e.external_id, e.payload->'model'
                 from product_enrichment e where e.payload is not null {cond}""")
    got = [r.split('\x1f') for r in rows.strip().split('\n') if r]
    if fresh_only and len(got) < 10:
        print(f'свежих обогащений {len(got)} (<10) — судья сегодня не нужен')
        return
    random.seed(20260806)     # детерминированный сэмпл в рамках дня — повтор не платит дважды?
    random.shuffle(got)       # нет: повтор судит тех же — это осознанно (идемпотентность дня)
    sample = got[:JUDGE_N]
    keys = {(m, e) for m, e, _ in sample}
    items = {(str(it['mid']), it['eid']): it for it in pool()
             if (str(it['mid']), it['eid']) in keys}
    key = _key()
    from enrich import ask
    from openai_budget import allow as _budget_allow   # дневной лимит $ (владелец 17.08); ask() пишет учёт сам
    if not _budget_allow(MODEL_STRONG, len(sample) * 2, False, 'enrich_judge drift'):
        return
    n = {'judged': 0, 'role': 0, 'subtype': 0, 'style': 0, 'fail': 0}
    for mid, eid, payload_s in sample:
        it = items.get((mid, eid))
        if not it:
            continue
        ours = json.loads(payload_s)
        strong = None
        try:
            strong = ask(it, key, MODEL_STRONG, vision=True)
        except Exception as e:  # noqa: BLE001 — счётчик, не молчание
            print(f'  {mid}:{eid} судья упал: {str(e)[:80]}')
        if not strong:
            n['fail'] += 1
            continue
        n['judged'] += 1
        agree_role = (strong.get('role') == ours.get('role'))
        agree_sub = (strong.get('functional_subtype') == ours.get('functional_subtype'))
        agree_style = _styles_close(strong.get('styles') or {}, ours.get('styles') or {})
        n['role'] += agree_role
        n['subtype'] += agree_sub
        n['style'] += agree_style
        if not (agree_role and agree_style):
            with open(CAND_LOG, 'a') as f:   # прод-ошибка → кандидат в голден
                f.write(json.dumps({'date': time.strftime('%F'), 'mid': mid, 'eid': eid,
                                    'name': it.get('name'), 'ours': ours.get('role'),
                                    'strong': strong.get('role'),
                                    'ours_styles': ours.get('styles'),
                                    'strong_styles': strong.get('styles')},
                                   ensure_ascii=False) + '\n')
    if not n['judged']:
        print('судить нечего (все вызовы упали?)')
        return
    rec = {'date': time.strftime('%F'), 'n': n['judged'], 'fail': n['fail'],
           'role_agree': round(100 * n['role'] / n['judged'], 1),
           'subtype_agree': round(100 * n['subtype'] / n['judged'], 1),
           'style_agree': round(100 * n['style'] / n['judged'], 1)}
    hist = []
    if os.path.exists(DRIFT_LOG):
        hist = [json.loads(l) for l in open(DRIFT_LOG) if l.strip()]
    with open(DRIFT_LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print('судья:', json.dumps(rec, ensure_ascii=False))
    if hist:
        base = sum(h['role_agree'] for h in hist) / len(hist)
        if rec['role_agree'] < base - DROP_ALERT_PP:
            os.system(f'bash {os.path.join(HERE, "alert.sh")} '
                      f'"remlab: дрифт обогащения — согласие по роли {rec["role_agree"]}% '
                      f'против бейзлайна {base:.0f}%"')


if __name__ == '__main__':
    main()
