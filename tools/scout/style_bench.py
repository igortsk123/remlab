#!/usr/bin/env python3
"""Стенд стиля по осям (план conv-01, ADR-0269): 300 товаров → опрос VLM по осям → ленты стилей владельцу.

ЗАЧЕМ. Владелец выбирает метод глазами (ADR-0251: эталонной разметки человеком не будет): три ленты — лофт,
сканди, неоклассика — по каждому методу: (A) нынешний балл из базы (`product_style_scores`), (B) оси, простое
среднее совместимости, (C) оси, формула M+D, (D) M+D с поправкой пар. В каждой ленте — верх-20 и полоса 5.5–6.5
(граница порога «в стиле»). Расчёт по осям — `style_axes.py`, оси — `rules/style-axes.json`.

  ~/venvs/scout/bin/python style_bench.py --sample          # выборка 300 семейств по пяти группам ролей
  ~/venvs/scout/bin/python style_bench.py --ask [--limit N] # опрос VLM (платно, ≈ $0.0006 за товар), кэш ответов
  ~/venvs/scout/bin/python style_bench.py --page            # страница лент → style-bench/index.html
  python3 style_bench.py --selftest

Опрос: одна карточка = один запрос (все оси сразу + основание), фото 1024 px `detail: high`, модель gpt-6-luna
(как в бою, ADR-0231). Денег на каналах нет — `llm_gateway.NoCredits`: стоп сразу, кэш не трогаем.
"""
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'style-bench')
SAMPLE = os.path.join(OUT, 'sample.json')
ANSWERS = os.path.join(OUT, 'answers.jsonl')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-qtA', '-F', '\x1f']
GROUPS = {
    'мягкая': ['диван', 'кресло', 'пуф'],
    'корпусная': ['шкаф', 'комод', 'стеллаж', 'тв-тумба', 'витрина', 'стенка', 'полка'],
    'столы и стулья': ['стул', 'столик', 'стол обеденный'],
    'свет': ['люстра', 'бра', 'лампа', 'торшер'],
    'декор и текстиль': ['ваза', 'кашпо', 'шторы', 'плед', 'подушка', 'ковёр', 'статуэтка', 'картина', 'зеркало', 'часы'],
}
PER_GROUP = 60
FEED_STYLES = ['лофт', 'сканди', 'неоклассика']
MODEL = os.environ.get('STYLE_MODEL', 'gpt-6-luna')


def rows(q: str) -> list[list[str]]:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[:300])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def pick(cands: dict, per_group: int, seed: int = 13) -> list[dict]:
    """По группе ролей — per_group семейств, роли внутри группы — поровну (сколько есть). Детерминированно."""
    rnd = random.Random(seed)
    out = []
    for g, roles in GROUPS.items():
        pools = {r: sorted(cands.get(r, []), key=lambda x: x['mkey']) for r in roles}
        for p in pools.values():
            rnd.shuffle(p)
        took, i = [], 0
        while len(took) < per_group and any(pools.values()):
            r = roles[i % len(roles)]
            if pools[r]:
                took.append({**pools[r].pop(), 'group': g})
            i += 1
            if i > per_group * len(roles) * 4:
                break
        out += took
    return out


def _model_key():
    """`style_score.model_key` БЕЗ импорта: импорт style_score исполняет полный (платный) прогон — ловушка
    скриптов scout. Достаём определения STOP и model_key из исходника и исполняем только их."""
    src = open(os.path.join(HERE, 'style_score.py'), encoding='utf-8').read()
    stop = re.search(r'^STOP=[^\n]*\n', src, re.M)          # одна строка
    body = re.search(r'^def model_key\(name\):\n(?:    [^\n]*\n)+', src, re.M)   # только строки с отступом
    if not stop or not body:
        raise SystemExit('style_score.model_key не найден — дедуп семейств сломан, СТОП')
    ns: dict = {'re': re}
    exec(stop.group(0) + body.group(0), ns)  # noqa: S102 — свой файл репозитория, только два определения
    return ns['model_key']


def sample() -> int:
    model_key = _model_key()  # дедуп семейств как в бою
    raw = rows("""select l.role, p.shop_mid, p.external_id, p.name, coalesce(p.image_url_hd, p.image_url), p.shop,
                         coalesce(p.params->>'Стиль',''), coalesce(s.scores::text,'')
                    from lr_roles l join products p using (shop_mid, external_id)
                    left join product_style_scores s using (shop_mid, external_id)
                   where l.role is not null and p.in_stock and coalesce(p.photo_alive, true)
                     and coalesce(p.image_url_hd, p.image_url) is not null""")
    fams: dict = {}
    for r in raw:
        k = (r[5], model_key(r[3]))
        if k in fams:
            continue
        fams[k] = {'role': r[0], 'mid': int(r[1]), 'eid': r[2], 'name': r[3], 'img': r[4], 'shop': r[5],
                   'store_style': r[6], 'old': json.loads(r[7]) if r[7] else None, 'mkey': ' | '.join(k)}
    cands: dict = {}
    for f in fams.values():
        cands.setdefault(f['role'], []).append(f)
    s = pick(cands, PER_GROUP)
    os.makedirs(OUT, exist_ok=True)
    json.dump(s, open(SAMPLE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    by = {}
    for x in s:
        by[x['group']] = by.get(x['group'], 0) + 1
    print(f'выборка: {len(s)} семейств из {len(fams)}; по группам: {by}; с баллом в базе: {sum(1 for x in s if x["old"])}')
    return 0


def prompt(item: dict, axes_doc: dict) -> str:
    import style_axes as SA
    lines = []
    for a in axes_doc['axes']:
        if not SA.applies(a, item['role']):
            continue
        lines.append(f'- {a["id"]}: {a["question_ru"]} (1 = {a["scale_1_ru"]}; 10 = {a["scale_10_ru"]})')
    return ('Ты смотришь на фото товара для интерьера и отвечаешь на вопросы о том, ЧТО ВИДНО. Стиль не называй.\n'
            f'Товар: [{item["role"]}] {item["name"][:120]}\n'
            'По каждой оси — целое 1–10; null, если признак не видно на фото; "na", если ось к предмету неприменима.\n'
            + '\n'.join(lines) +
            '\nОтвет STRICT JSON: {"axes": {"<id>": число|null|"na", ...}, "why": "одна фраза: что видно"}')


def ask(limit: int) -> int:
    import style_axes as SA
    from golden_label import _image_b64
    from llm_gateway import NoCredits, chat
    axes_doc, _ = SA.load()
    items = json.load(open(SAMPLE, encoding='utf-8'))
    done = {json.loads(ln)['mkey'] for ln in open(ANSWERS, encoding='utf-8')} if os.path.exists(ANSWERS) else set()
    todo = [x for x in items if x['mkey'] not in done][: limit or None]
    print(f'спросить: {len(todo)} (уже есть {len(done)})', flush=True)
    fails = 0
    with open(ANSWERS, 'a', encoding='utf-8') as fo:
        for i, it in enumerate(todo, 1):
            b64 = _image_b64(it['img'])
            if not b64:
                fails += 1
                continue
            try:
                r = chat(MODEL, [{'role': 'user', 'content': [
                    {'type': 'text', 'text': prompt(it, axes_doc)},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'high'}}]}],
                    response_format={'type': 'json_object'}, reasoning_effort='low')
            except NoCredits as e:
                print(f'СТОП: {e}', flush=True)
                return 2
            except Exception as e:  # noqa: BLE001 — один товар не роняет стенд, но счётчик отказов виден
                fails += 1
                print(f'  отказ {it["mkey"][:40]}: {type(e).__name__}: {str(e)[:80]}', flush=True)
                if fails > 15:
                    print('слишком много отказов — СТОП', flush=True)
                    return 1
                continue
            m = re.search(r'\{.*\}', r['choices'][0]['message']['content'], re.S)
            ans = json.loads(m.group(0)) if m else {}
            fo.write(json.dumps({'mkey': it['mkey'], 'axes': ans.get('axes') or {}, 'why': ans.get('why', ''),
                                 'usage': r.get('usage')}, ensure_ascii=False) + '\n')
            fo.flush()
            if i % 25 == 0:
                print(f'  {i}/{len(todo)}', flush=True)
    print(f'готово; отказов {fails}')
    return 0


def methods(item: dict, ans: dict | None, axes_doc: dict, formula: dict) -> dict:
    """Баллы по методам A–D для одного товара (None — у метода нет данных)."""
    import copy
    import style_axes as SA
    out = {'A': item.get('old')}
    if not ans:
        return out | {'B': None, 'C': None, 'D': None}
    a = {k: (SA.NA if v == 'na' else v) for k, v in (ans.get('axes') or {}).items()}
    full = SA.score(a, item['role'], axes_doc, formula)
    no_pairs = SA.score(a, item['role'], {**axes_doc, 'confusable_pairs': []}, formula)
    simple_f = copy.deepcopy(formula)
    simple_f['mix'] = {'compat': 1.0, 'diagnostic': 0.0}
    simple = SA.score(a, item['role'], {**axes_doc, 'confusable_pairs': []}, simple_f)
    return out | {'B': simple['scores'], 'C': no_pairs['scores'], 'D': full['scores'], 'insufficient': full['insufficient']}


def page() -> int:
    import html
    import style_axes as SA
    axes_doc, formula = SA.load()
    items = json.load(open(SAMPLE, encoding='utf-8'))
    answers = {}
    if os.path.exists(ANSWERS):
        for ln in open(ANSWERS, encoding='utf-8'):
            j = json.loads(ln)
            answers[j['mkey']] = j
    names = {'A': 'нынешний балл', 'B': 'оси: среднее', 'C': 'оси: M+D', 'D': 'оси: M+D + пары'}
    blocks = []
    for st in FEED_STYLES:
        for m in 'ABCD':
            scored = []
            for it in items:
                sc = methods(it, answers.get(it['mkey']), axes_doc, formula).get(m)
                if sc and st in sc:
                    scored.append((float(sc[st]), it))
            if not scored:
                blocks.append(f'<h3>{st} — {names[m]}</h3><p class="m">нет данных (опрос по осям ещё не проводился)</p>')
                continue
            scored.sort(key=lambda x: -x[0])
            top = scored[:20]
            band = [x for x in scored if 5.5 <= x[0] <= 6.5][:20]

            def card(v: float, it: dict) -> str:
                return (f'<figure><img loading="lazy" src="{html.escape(it["img"])}" alt=""><figcaption>{v:.1f} · '
                        f'{html.escape(it["role"])}<br>{html.escape(it["name"][:60])}</figcaption></figure>')
            blocks.append(f'<h3>{st} — {names[m]}</h3><p class="m">верх-20</p><div class="g">{"".join(card(v, it) for v, it in top)}</div>'
                          f'<p class="m">граница 5.5–6.5 (что считать «в стиле»)</p><div class="g">{"".join(card(v, it) for v, it in band)}</div>')
    doc = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Стенд стиля</title><style>body{font:15px system-ui;margin:16px;background:#faf8f5}h3{margin:28px 0 4px}'
           '.m{color:#777;margin:4px 0}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}'
           'figure{margin:0;background:#fff;border-radius:8px;padding:6px}img{width:100%;aspect-ratio:1;object-fit:contain}'
           'figcaption{font-size:12px}</style>'
           f'<h1>Стенд стиля по осям — {len(items)} товаров, опрошено {len(answers)}</h1>'
           '<p>Выберите метод, чьи ленты больше похожи на стиль. A — как сейчас; B, C, D — новые по осям признаков.</p>'
           + ''.join(blocks))
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(doc)
    print(f'страница: {os.path.join(OUT, "index.html")} (опрошено {len(answers)} из {len(items)})')
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    c = {r: [{'mkey': f'{r}{i}', 'role': r} for i in range(50)] for g in GROUPS.values() for r in g}
    s = pick(c, 10)
    ok('по 10 на каждую из пяти групп', len(s) == 50 and all(sum(1 for x in s if x['group'] == g) == 10 for g in GROUPS))
    ok('выборка детерминирована', [x['mkey'] for x in s] == [x['mkey'] for x in pick(c, 10)])
    mk = _model_key()
    ok('ключ семейства без импорта style_score: цвет не различает модели', mk('Диван Сорен велюр серый') == mk('Диван Сорен велюр бежевый'))
    import style_axes as SA
    axes_doc, formula = SA.load()
    it = {'role': 'стеллаж', 'name': 'Стеллаж', 'old': {'лофт': 7}}
    p = prompt(it, axes_doc)
    ok('в вопросе есть оси для роли и нет оси светильника', 'metal_visibility' in p and 'lamp_bulb_exposure' not in p)
    m = methods(it, {'axes': {'metal_visibility': 9, 'colour_lightness': 2, 'raw_imperfection': 8, 'wood_tone_lightness': 2,
                              'wood_visibility': 6, 'ornament_level': 1, 'material_mix': 6, 'surface_gloss': 2}}, axes_doc, formula)
    ok('методы B–D считаются по ответам, A — из базы', m['A'] == {'лофт': 7} and all(m[k] for k in 'BCD'))
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--sample' in sys.argv:
        sys.exit(sample())
    if '--ask' in sys.argv:
        sys.exit(ask(int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0))
    if '--page' in sys.argv:
        sys.exit(page())
    print(__doc__)
