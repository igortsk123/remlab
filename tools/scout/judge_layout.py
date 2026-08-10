#!/usr/bin/env python3
"""W4 kb-rules-merge: судья раскладок — полный конвейер (владелец 10.08).

Цикл на сцену: JSON координат (self-describing) + план-PNG + дайджест правил
(числа occupancy на лету) → gpt-5.6-terra VISION → строгий JSON-вердикт
{score, issues, suggested_moves} → ходы применяются как КАНДИДАТЫ: полная
перевалидация, принять только при лексикографическом улучшении (hard↓, затем
soft↓), максимум 2 итерации → пере-рендер «после» → страница до/после + реестр
вердиктов (jsonl, реплей без повторной оплаты).

Судья РАССУЖДАЕТ, но не двигает мебель напрямую — двигает солвер через
валидаторы (граница из спеки source-KB, фаза 12).

  ~/venvs/scout/bin/python judge_layout.py --pilot 10            # хвосты band 50+
  ~/venvs/scout/bin/python judge_layout.py --scenes set112-base set50-base
"""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

from planner.models import Item, Placement, Room  # noqa: E402
from planner.validate import validate  # noqa: E402

MODEL = 'gpt-5.6-terra'
API = 'https://api.openai.com/v1/chat/completions'
VERDICTS = os.path.join(HERE, 'judge-layout-verdicts.jsonl')
OUT_DIR = os.path.expanduser('~/scout-scenes/judge-loop')
OCC = json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver',
                                  'rules', 'occupancy.json')))

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['score', 'issues', 'suggested_moves'],
    'properties': {
        'score': {'type': 'integer', 'minimum': 0, 'maximum': 10},
        'issues': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['severity', 'roles', 'why'],
            'properties': {
                'severity': {'type': 'string', 'enum': ['major', 'minor']},
                'roles': {'type': 'array', 'items': {'type': 'string'}},
                'why': {'type': 'string'}}}},
        'suggested_moves': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['role', 'x', 'z', 'rot', 'why'],
            'properties': {
                'role': {'type': 'string'},
                'x': {'type': 'number'}, 'z': {'type': 'number'},
                'rot': {'type': 'integer', 'enum': [0, 90, 180, 270]},
                'why': {'type': 'string'}}}},
    },
}


def _key() -> str:
    k = os.environ.get('OPENAI_API_KEY')
    if k:
        return k
    for line in open(os.path.join(HERE, '.env')):
        if line.startswith('OPENAI_API_KEY='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('нет OPENAI_API_KEY')


_KB_CACHE: dict[str, str] = {}


def _kb_rules(ctx: dict) -> str:
    """Применимые правила базы (PLANE A) — субпроцессом в kdb-venv, с кэшем.
    Владелец 10.08: только применимые к сцене, не весь корпус."""
    import subprocess
    key = json.dumps(ctx, sort_keys=True, ensure_ascii=False)
    if key not in _KB_CACHE:
        try:
            out = subprocess.run(
                [os.path.expanduser('~/venvs/kdb/bin/python'), '-m',
                 'kdb.scene_rules', key],
                cwd=os.path.join(HERE, '..', '..', 'services', 'knowledge-db'),
                capture_output=True, text=True, timeout=120)
            _KB_CACHE[key] = out.stdout.strip() if out.returncode == 0 else ''
            if out.returncode != 0:
                print(f'  WARNING: kb-правила недоступны: {out.stderr[:120]}')
        except Exception as e:  # noqa: BLE001 — конвейер живёт и без базы
            print(f'  WARNING: kb-правила недоступны ({e})')
            _KB_CACHE[key] = ''
    return _KB_CACHE[key]


def _rules_digest() -> str:
    d = OCC['distances_cm']

    def rng(k):
        v = d.get(k)
        return f"{v[0]}–{v[1]}" if isinstance(v, list) else str(v)
    return (
        "Правила (см, из прод-канона RemLab; спорные решены по книге "
        "Mitton/Nystuen):\n"
        f"- главный проход {rng('passage_main')}, вторичный от "
        f"{rng('passage_secondary_min')}\n"
        f"- диван→столик {rng('sofa_coffee_table_hard')} (идеально "
        f"{rng('sofa_coffee_table_preferred')})\n"
        f"- ТВ: {rng('sofa_tv_cm')} и 1.2–2.5 диагонали, потолок "
        f"{rng('sofa_tv_hard_max')}; перекос взгляда ≤{rng('sofa_tv_aim_deg_max')}°\n"
        f"- лицом-к-лицу сидящие {rng('facing_seats')}; круг общения ≤"
        f"{rng('conversation_circle_max_cm')}\n"
        f"- стул от стола {rng('dining_chair_pullout')}; стол от стены "
        f"{rng('dining_table_to_wall_no_pass')} без прохода / "
        f"{rng('dining_table_to_wall_with_pass')} с проходом\n"
        f"- шкаф распашной: перед ним {rng('wardrobe_hinged_front_min')}\n"
        f"- ковёр: длиннее дивана на {rng('rug_longer_than_sofa')}, по оси "
        "дивана, под передние ножки\n"
        f"- камин: зона {rng('fireplace_clear')} перед ним, в поле зрения посадки\n"
        "- дверь открывается свободно; к каждому предмету есть подход; два "
        "дивана — лицом-к-лицу или Г торец-к-торцу (не в спинку соседа)\n"
        "- окно не блокируется высокой мебелью; телевизор не напротив окна"
    )


SYS = (
    "Ты — опытный дизайнер интерьеров и судья раскладок RemLab. Тебе дают план "
    "гостиной (вид сверху), точные координаты предметов (см) и свод правил. "
    "Оцени раскладку и предложи КОНКРЕТНЫЕ улучшения.\n"
    "Система координат: начало — юго-западный (нижний-левый) угол; x вправо "
    "(восток), z вверх по плану (север); позиция — ЦЕНТР предмета; rot: 0 — "
    "лицом на север (+z), 90 — восток, 180 — юг, 270 — запад.\n"
    "Семантика КЛИРЕНСОВ (важно, по пилоту 10.08): клиренс в правилах — это "
    "СВОБОДНОЕ ПРОСТРАНСТВО ДЛЯ ДВИЖЕНИЯ рядом с предметом, а не статический "
    "отступ между предметами. Пример: «отодвинутый стул 46–61 см» — это место "
    "ПОЗАДИ стула (от кромки стола до препятствия), чтобы стул можно было "
    "отодвинуть; сам стул, задвинутый вплотную к столу, — НОРМА, не нарушение.\n"
    "Правила ответа: suggested_moves — только уверенные улучшения (0–4 хода), "
    "каждый ход — итоговые x,z,rot и краткое «почему» со ссылкой на правило; "
    "не выдумывай предметы; не двигай дверь/окно; если раскладка хороша — "
    "пустой список и score 8–10. Все нарушения физики (коллизии, дверь) всё "
    "равно перепроверит солвер — предлагай смело, но осмысленно."
)


def call_judge(layout: dict, png_path: str, cache: dict,
               owner_comment: str | None = None) -> dict | None:
    payload = {'layout': {k: v for k, v in layout.items() if not k.startswith('_')},
               'room': layout['_room']}
    h = hashlib.sha256((MODEL + (owner_comment or '') +
                        json.dumps(payload, sort_keys=True,
                                   ensure_ascii=False)).encode()).hexdigest()
    if h in cache:
        return cache[h]['verdict']
    b64 = base64.b64encode(open(png_path, 'rb').read()).decode()
    ctx = {'room_type': 'living_room',
           'zone_types': ['conversation', 'tv_media', 'relaxation'],
           'jurisdiction': 'us_north_america'}
    blocks = []
    if owner_comment:
        blocks.append("ЗАМЕЧАНИЕ ВЛАДЕЛЬЦА (высший приоритет — выполнить, не "
                      f"ломая правила): {owner_comment}")
    blocks.append(_rules_digest())
    kb = _kb_rules(ctx)
    if kb:
        blocks.append("Применимые правила из книги (сила в скобках):\n" + kb)
    blocks.append("Координаты (см):\n" + json.dumps(payload, ensure_ascii=False))
    user = [
        {'type': 'text', 'text': "\n\n".join(blocks)},
        {'type': 'image_url', 'image_url': {
            'url': f'data:image/png;base64,{b64}', 'detail': 'high'}},
    ]
    body = {'model': MODEL,
            'messages': [{'role': 'system', 'content': SYS},
                         {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 'layout_verdict',
                                                'strict': True,
                                                'schema': SCHEMA}},
            'reasoning_effort': 'low'}
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {_key()}',
                                          'Content-Type': 'application/json'})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=240))
    except Exception as e:  # noqa: BLE001 — счётчик отказов, не молчание
        print(f'  ОТКАЗ судьи: {e}')
        return None
    verdict = json.loads(r['choices'][0]['message']['content'])
    usage = r.get('usage', {})
    row = {'key': h, 'model': MODEL, 'verdict': verdict, 'usage': usage}
    cache[h] = row
    with open(VERDICTS, 'a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    cost = usage.get('prompt_tokens', 0) / 1e6 * 2 + \
        usage.get('completion_tokens', 0) / 1e6 * 12
    print(f"  судья: score={verdict['score']} issues={len(verdict['issues'])} "
          f"moves={len(verdict['suggested_moves'])} (${cost:.3f})")
    return verdict


def build_scene(layout: dict, set_n: int):
    room = Room(width_cm=layout['_room']['w'], depth_cm=layout['_room']['d'],
                openings=layout['_room'].get('openings', []))
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    heights = {r: (it.get('h') or 60) for r, it in sets[set_n - 1]['items'].items()}
    ps = []
    for role, p in layout.items():
        if role.startswith('_'):
            continue
        ps.append(Placement(role=role, x=p['x'], y=p['z'], rot=p['rot'],
                            item=Item(role=role, w_cm=p['w'], d_cm=p['d'],
                                      h_cm=heights.get(role) or 60,
                                      corner=bool(p.get('corner')),
                                      corner_section_cm=float(p.get('section') or 95),
                                      corner_left=bool(p.get('corner_left')))))
    return room, ps


def lex_score(room, ps):
    lay = validate(room, ps, passage='secondary')
    hard = sum(1 for v in lay.violations if v.severity.name == 'HARD')
    soft = sum(1 for v in lay.violations if v.severity.name == 'SOFT')
    return hard, soft, lay


def apply_moves(room, ps, moves):
    """Ходы судьи = кандидаты: принимаем по одному, только при улучшении."""
    cur = list(ps)
    h0, s0, _ = lex_score(room, cur)
    log = []
    for mv in moves:
        cand = None
        for i, p in enumerate(cur):
            if p.role == mv['role']:
                cand = i
                break
        if cand is None:
            log.append({'move': mv, 'result': 'REJECT_NO_ROLE'})
            continue
        trial = copy.deepcopy(cur)
        p = trial[cand]
        trial[cand] = Placement(role=p.role, x=float(mv['x']), y=float(mv['z']),
                                rot=int(mv['rot']), item=p.item)
        h1, s1, _ = lex_score(room, trial)
        if (h1, s1) < (h0, s0):
            cur, h0, s0 = trial, h1, s1
            log.append({'move': mv, 'result': f'ACCEPT (hard {h1}, soft {s1})'})
        else:
            log.append({'move': mv,
                        'result': f'REJECT (hard {h0}->{h1}, soft {s0}->{s1})'})
    return cur, (h0, s0), log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenes', nargs='*', default=None)
    ap.add_argument('--pilot', type=int, default=0,
                    help='взять N худших сцен (FAIL/soft) из приёмки')
    ap.add_argument('--from-comments', action='store_true',
                    help='обработать сцены из owner-comments.jsonl')
    ap.add_argument('--rounds', type=int, default=2)
    args = ap.parse_args()

    comments: dict[str, str] = {}
    cpath = os.path.join(HERE, 'owner-comments.jsonl')
    if os.path.exists(cpath):
        for l in open(cpath):
            if l.strip():
                row = json.loads(l)
                comments[row['id']] = row['comment']

    seen = {}   # ключ строки отчёта — 'scene'; дубли в jsonl — последняя запись побеждает
    for l in open(os.path.join(HERE, 'acceptance-report-zoned.jsonl')):
        if l.strip():
            row = json.loads(l)
            seen[row['scene']] = row
    report = list(seen.values())
    if args.from_comments:
        todo = [r for r in report if r['scene'] in comments]
    elif args.scenes:
        todo = [r for r in report if r['scene'] in set(args.scenes)]
    else:
        bad = [r for r in report if not (r.get('verdict') == 'OK' or r.get('ok'))]
        rest = sorted((r for r in report if r.get('verdict') == 'OK' or r.get('ok')),
                      key=lambda r: -(r.get('soft_score') or 0))
        todo = (bad + rest)[:args.pilot or 10]

    cache = {}
    if os.path.exists(VERDICTS):
        for l in open(VERDICTS):
            row = json.loads(l)
            cache[row['key']] = row

    os.makedirs(OUT_DIR, exist_ok=True)
    rows_html = []
    summary = []
    for r in todo:
        sid, n = r['scene'], r['set']
        lay_path = os.path.join(HERE, f'v3set{n}-layout-acc-zoned-{sid}.json')
        png_path = os.path.join(HERE, f'v3set{n}-layout-acc-zoned-{sid}.png')
        if not (os.path.exists(lay_path) and os.path.exists(png_path)):
            continue
        print(f'{sid}:')
        layout = json.load(open(lay_path))
        room, ps = build_scene(layout, n)
        before = lex_score(room, ps)[:2]
        cur = ps
        applied_log = []
        verdict = None
        for _ in range(args.rounds):
            verdict = call_judge(layout, png_path, cache,
                                 owner_comment=comments.get(sid))
            if not verdict or not verdict['suggested_moves']:
                break
            cur, after, log = apply_moves(room, cur, verdict['suggested_moves'])
            applied_log += log
            # обновляем layout для следующего раунда (судья видит применённое)
            for p in cur:
                if p.role in layout:
                    layout[p.role].update(x=p.x, z=p.y, rot=p.rot)
            if all(l['result'].startswith('REJECT') for l in log):
                break
        after = lex_score(room, cur)[:2]
        changed = after != before or any(
            l['result'].startswith('ACCEPT') for l in applied_log)
        after_png = os.path.join(OUT_DIR, f'{sid}-after.png')
        import shutil
        shutil.copy(png_path, os.path.join(OUT_DIR, f'{sid}-before.png'))
        if changed:
            from scene_build import draw_plan
            draw_plan(room, cur, [], after_png)
        else:
            shutil.copy(png_path, after_png)
        summary.append({'id': sid, 'before': before, 'after': after,
                        'score': (verdict or {}).get('score'),
                        'issues': (verdict or {}).get('issues', []),
                        'moves_log': applied_log})
        accepted = sum(1 for l in applied_log if l['result'].startswith('ACCEPT'))
        rows_html.append(
            f"<section><h2>{sid} <small>судья: {(verdict or {}).get('score','—')}/10 · "
            f"hard/soft {before}→{after} · принято ходов {accepted}/"
            f"{len(applied_log)}</small></h2>"
            f"<div class='pair'><figure><figcaption>до</figcaption>"
            f"<img src='{sid}-before.png'></figure>"
            f"<figure><figcaption>после</figcaption>"
            f"<img src='{sid}-after.png'></figure></div>"
            + "".join(f"<p class='iss'>• [{i['severity']}] {', '.join(i['roles'])}: "
                      f"{i['why']}</p>" for i in (verdict or {}).get('issues', []))
            + "".join(f"<p class='mv'>→ {l['move']['role']} → "
                      f"({l['move']['x']:.0f},{l['move']['z']:.0f},{l['move']['rot']}) "
                      f"— {l['move']['why']} [{l['result']}]</p>"
                      for l in applied_log)
            + "</section>")
        print(f"  итог: hard/soft {before} → {after}, ходов принято {accepted}")

    json.dump(summary, open(os.path.join(OUT_DIR, 'summary.json'), 'w'),
              ensure_ascii=False, indent=1)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Судья раскладок — до/после</title>
<style>body{{margin:0;background:#fff;color:#1A1F1C;font:15px/1.5 system-ui}}
.wrap{{max-width:1100px;margin:0 auto;padding:20px 14px 60px}}
section{{border-top:1px solid #E4E6E2;padding:14px 0}}
h2 small{{color:#5C655E;font-weight:400;font-size:13px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
figure{{margin:0}} figcaption{{color:#5C655E;font-size:12px}}
img{{max-width:100%;border:1px solid #ECEEEA;border-radius:4px}}
.iss{{color:#A2493B;font-size:13.5px;margin:4px 0}}
.mv{{color:#2F6B8F;font-size:13.5px;margin:4px 0}}</style></head>
<body><div class="wrap"><h1>Судья раскладок (terra-vision) — до/после,
{len(summary)} сцен</h1>{''.join(rows_html)}</div></body></html>"""
    open(os.path.join(OUT_DIR, 'index.html'), 'w').write(page)
    print(f"OK: {len(summary)} сцен → {OUT_DIR}")


if __name__ == '__main__':
    main()
