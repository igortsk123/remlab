#!/usr/bin/env python3
"""Стенд стиля по осям (план conv-01, ADR-0269): 300 товаров → опрос VLM по осям → ленты стилей владельцу.

ЗАЧЕМ. Владелец выбирает метод глазами (ADR-0251: эталонной разметки человеком не будет): три ленты — лофт,
сканди, неоклассика — по каждому методу: (A) нынешний балл из базы (`product_style_scores`), (B) оси, простое
среднее совместимости, (C) оси, формула M+D, (D) M+D с поправкой пар. В каждой ленте — верх-20 и полоса 5.5–6.5
(граница порога «в стиле»). Расчёт по осям — `style_axes.py`, оси — `rules/style-axes.json`.

  ~/venvs/scout/bin/python style_bench.py --sample          # выборка 300 семейств по пяти группам ролей
  ~/venvs/scout/bin/python style_bench.py --ask [--limit N] # опрос VLM (платно, ≈ $0.0006 за товар), кэш ответов
  ~/venvs/scout/bin/python style_bench.py --page            # страница лент → style-bench/index.html
  python3 style_bench.py --vote-page | --vote-report | --vote-export   # отметки человека: страница, черта, выгрузка для GPT
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
THR = float(json.load(open(os.path.join(HERE, 'rules', 'demo-swap.json'), encoding='utf-8'))['in_style_min'])   # 6.6
STYLES6 = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
VOTE_PER_STYLE = 40
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


def methods(item: dict, ans: dict | None, axes_doc: dict, formula: dict, lam: float = 0.25) -> dict:
    """Баллы по методам (None — нет данных): A — нынешний из базы; V2 — оси, версия 2 (`style_axes.score_v2`);
    H — гибрид A + λ·clip(V2−5, ±1) (Codex 14.10); D — оси, версия 1 (M+D+пары) для сравнения."""
    import style_axes as SA
    out = {'A': item.get('old')}
    if not ans:
        return out | {'V2': None, 'H': None, 'D': None}
    a = {k: (SA.NA if v == 'na' else v) for k, v in (ans.get('axes') or {}).items()}
    v2 = SA.score_v2(a, item['role'], axes_doc, formula)
    old = item.get('old') or {}
    h = {s: round(float(old.get(s, 5)) + lam * max(-1.0, min(1.0, v2['scores'][s] - 5)), 2) for s in axes_doc['styles']} if old else None
    return out | {'V2': v2['scores'], 'V2u': v2['universal'], 'H': h, 'D': SA.score(a, item['role'], axes_doc, formula)['scores']}


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
    names = {'A': 'нынешний балл', 'V2': 'оси, версия 2', 'H': 'смесь: нынешний + оси'}
    blocks = []
    for st in FEED_STYLES:
        for m in ('A', 'V2', 'H'):
            scored = []
            for it in items:
                mm = methods(it, answers.get(it['mkey']), axes_doc, formula)
                sc = mm.get(m)
                if m == 'V2' and mm.get('V2u'):
                    continue                    # «универсальный» — без выраженного стиля, в ленту стиля не идёт
                if sc and st in sc:
                    scored.append((float(sc[st]), it))
            if not scored:
                blocks.append(f'<h3>{st} — {names[m]}</h3><p class="m">нет данных (опрос по осям ещё не проводился)</p>')
                continue
            scored.sort(key=lambda x: -x[0])
            top = scored[:20]
            band = [x for x in scored if THR - 0.5 <= x[0] <= THR + 0.5][:20]

            def card(v: float, it: dict) -> str:
                return (f'<figure><img loading="lazy" src="{html.escape(it["img"])}" alt=""><figcaption>{v:.1f} · '
                        f'{html.escape(it["role"])}<br>{html.escape(it["name"][:60])}</figcaption></figure>')
            blocks.append(f'<h3>{st} — {names[m]}</h3><p class="m">верх-20</p><div class="g">{"".join(card(v, it) for v, it in top)}</div>'
                          f'<p class="m">у границы {THR - 0.5:.1f}–{THR + 0.5:.1f} (порог «в стиле» {THR:g}: решаем, где проходит черта)</p><div class="g">{"".join(card(v, it) for v, it in band)}</div>')
    doc = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>Стенд стиля</title><style>body{font:15px system-ui;margin:16px;background:#faf8f5}h3{margin:28px 0 4px}'
           '.m{color:#777;margin:4px 0}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}'
           'figure{margin:0;background:#fff;border-radius:8px;padding:6px}img{width:100%;aspect-ratio:1;object-fit:contain}'
           'figcaption{font-size:12px}</style>'
           f'<h1>Стенд стиля по осям — {len(items)} товаров, опрошено {len(answers)}</h1>'
           '<p>Выберите метод, чьи ленты больше похожи на стиль. «Нынешний» — как сейчас; «оси, версия 2» — новый по '
           'признакам (товары без выраженного стиля в его ленты не попадают); «смесь» — нынешний, слегка поправленный осями.</p>'
           + ''.join(blocks))
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(doc)
    print(f'страница: {os.path.join(OUT, "index.html")} (опрошено {len(answers)} из {len(items)})')
    return 0


def vote_items(items: list, per_style: int = VOTE_PER_STYLE) -> list[tuple[str, dict, float]]:
    """Карточки для отметок владельца: по стилю — товары у черты (нынешний балл в [THR−1.5; THR+1.5]) вперемешку
    с несколькими уверенными, детерминированно. Балл на карточке НЕ показываем — он подсказывал бы ответ."""
    import random
    out = []
    for st in STYLES6:
        near = [(float(it['old'][st]), it) for it in items if it.get('old') and abs(float(it['old'].get(st, 0)) - THR) <= 1.5]
        top = [(float(it['old'][st]), it) for it in items if it.get('old') and float(it['old'].get(st, 0)) > THR + 1.5]
        rnd = random.Random(st)
        rnd.shuffle(near)
        rnd.shuffle(top)
        pick = near[: per_style - 5] + top[:5]
        rnd.shuffle(pick)
        out += [(st, it, sc) for sc, it in pick]
    return out


VOTE_STYLES = STYLES6 + ['универсальный']   # «универсальный» — подойдёт к любому стилю по мнению человека (владелец 29.10)
REVIEW_API = 'https://remont-lab.online/api/lab/review'


def vote_cards(items: list) -> list[dict]:
    """Карточка = товар (формат владельца 29.10): те же товары, что в выборке v1, без повторов, в её порядке —
    прежние отметки «товар|стиль» ложатся на строки новой карточки сами."""
    seen, out = set(), []
    for _st, it, _sc in vote_items(items):
        k = f"{it['mid']}_{it['eid']}"
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


VOTE_JS = r"""
const API="/api/lab/review";
async function all(kind){let after=0,out=[];for(;;){const j=await (await fetch(API+"?kind="+kind+"&after="+after)).json();const r=j.rows||[];out=out.concat(r);if(r.length<2000)return out;after=r[r.length-1].id;}}
function post(body,keep){return fetch(API,{method:"POST",keepalive:!!keep,headers:{"content-type":"application/json"},body:JSON.stringify(body)});}
const say=(c,t)=>{c.querySelector(".st").textContent=t;};
document.querySelectorAll(".c").forEach(c=>{
  c.querySelectorAll(".t button").forEach(b=>b.onclick=async()=>{
    const v=b.classList.contains("on")?"clear":"yes";
    const r=await post({kind:"style",key:c.dataset.id+"|"+b.dataset.s,verdict:v}).catch(()=>null);
    if(!r||!r.ok){say(c,"не сохранилось — нажмите ещё раз");return;}
    b.classList.toggle("on",v==="yes");b.setAttribute("aria-pressed",v==="yes");say(c,"сохранено");
  });
  const cm=c.querySelector(".cm");let t=0,sent=cm.value;
  const save=async keep=>{clearTimeout(t);const v=cm.value.trim();if(v===sent)return;sent=v;say(c,"сохраняю…");
    const r=await post({kind:"style_note",key:c.dataset.id,verdict:"note",comment:v||undefined},keep).catch(()=>null);
    if(r&&r.ok)say(c,"комментарий сохранён");else{sent=null;say(c,"комментарий не сохранился — допишите или выйдите из поля");}};
  cm.oninput=()=>{clearTimeout(t);t=setTimeout(save,1000);};
  cm.onblur=()=>save();
  c._save=save;
});
addEventListener("pagehide",()=>document.querySelectorAll(".c").forEach(c=>c._save(true)));
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="hidden")document.querySelectorAll(".c").forEach(c=>c._save(true));});
Promise.all([all("style"),all("style_note")]).then(([marks,notes])=>{
  const last={},old={},note={};
  marks.forEach(x=>{last[x.itemKey]=x;if(x.comment){const id=x.itemKey.split("|")[0];(old[id]=old[id]||[]).push(x.comment);}});
  notes.forEach(x=>{note[x.itemKey]=x.comment||"";});
  document.querySelectorAll(".c").forEach(c=>{let any=false;
    c.querySelectorAll(".t button").forEach(b=>{const x=last[c.dataset.id+"|"+b.dataset.s];if(!x||x.verdict!=="yes")return;any=true;
      b.classList.add("on");b.setAttribute("aria-pressed","true");});
    const cm=c.querySelector(".cm");if(document.activeElement!==cm){
      const v=c.dataset.id in note?note[c.dataset.id]:[...new Set(old[c.dataset.id]||[])].join("; ");
      if(v){cm.value=v;any=true;}}
    if(any)say(c,"отмечено раньше");});
});
"""


def vote_page() -> int:
    import html
    items = json.load(open(SAMPLE, encoding='utf-8'))
    cards = []
    for it in vote_cards(items):
        rws = '<div class=t>' + ''.join(f'<button{" class=u" if st == "универсальный" else ""} data-s="{st}" aria-pressed=false>'
                                        f'{st.capitalize()}</button>' for st in VOTE_STYLES) + '</div>'
        cards.append(f'<div class=c data-id="{it["mid"]}_{html.escape(it["eid"])}"><img loading=lazy src="{html.escape(it["img"])}" alt="">'
                     f'<div class=n>{html.escape(it["role"])} · {html.escape(it["name"][:70])}</div>{rws}'
                     '<textarea class=cm maxlength=1000 rows=2 placeholder="комментарий — сохраняется сам"></textarea><div class=st></div></div>')
    doc = ('<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Стиль предметов</title>'
           '<style>body{font:15px system-ui;margin:16px;background:#faf8f5;color:#2b2622}h1{font-size:20px;margin:0 0 6px}p{margin:0 0 12px;color:#555}'
           '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}'
           '.c{background:#fff;border-radius:10px;padding:8px}.c img{width:100%;aspect-ratio:4/3;object-fit:contain}'
           '.n{font-size:12px;color:#555;margin:4px 0 6px}.t{display:flex;flex-wrap:wrap;gap:5px}'
           'button{font:13px system-ui;white-space:nowrap;padding:0 10px;min-height:32px;border-radius:16px;border:1px solid #ccc;background:#fff;color:#2b2622}'
           'button.u{font-weight:600}button.on{background:#2f6b3a;border-color:#2f6b3a;color:#fff}'
           '.cm{width:100%;box-sizing:border-box;margin-top:6px;padding:5px;font:13px system-ui;resize:vertical}.st{font-size:12px;color:#777;min-height:16px}</style>'
           f'<h1>Стиль предметов — {len(cards)} карточек</h1><p>Нажмите стили, к которым предмет подходит, — можно несколько; не нажато — '
           'не подходит. «Универсальный» — подойдёт к любому стилю. Повторное нажатие снимает. Всё, включая комментарий, сохраняется само; '
           'можно бросить и вернуться. Балл модели нарочно скрыт.</p>'
           '<div class=g>' + ''.join(cards) + '</div><script>' + VOTE_JS + '</script>')
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'vote.html')
    open(path, 'w', encoding='utf-8').write(doc)
    print(f'страница отметок: {path} ({len(cards)} карточек × {len(VOTE_STYLES)} кнопок)')
    return 0


def review_rows(kind: str) -> list[dict]:
    """Все отметки вида с прода, постранично по курсору after (сервер отдаёт ≤ 2000 за раз)."""
    import urllib.request
    out, after = [], 0
    while True:
        r = json.loads(urllib.request.urlopen(f'{REVIEW_API}?kind={kind}&after={after}', timeout=30).read())['rows']
        out += r
        if len(r) < 2000:
            return out
        after = r[-1]['id']


def last_marks(rows: list[dict]) -> dict:
    """Последняя отметка по ключу «товар|стиль»; `clear` снимает отметку."""
    last = {}
    for r in rows:
        if r['verdict'] == 'clear':
            last.pop(r['itemKey'], None)
        else:
            last[r['itemKey']] = r
    return last


def card_states(marks: list[dict], notes: list[dict]) -> dict:
    """Состояние карточек v3 (одна кнопка на стиль, план style-vote-v3): нажатые стили = последняя отметка `yes`;
    прежнее `no` (v1/v2) = не нажато, хранится в `legacy_no` для справки. Просмотрена — нажат хоть один стиль или есть
    комментарий: у неё ненажатые = не подходит; у непросмотренной данных нет."""
    out: dict = {}
    def st(sid: str) -> dict:
        return out.setdefault(sid, {'suits': [], 'legacy_no': [], 'comment': None, 'comment_history': [], 'legacy_comments': []})
    for key, r in last_marks(marks).items():
        sid, _, style = key.partition('|')
        (st(sid)['suits'] if r['verdict'] == 'yes' else st(sid)['legacy_no']).append(style)
    for r in marks:
        if r.get('comment'):
            sid, _, style = r['itemKey'].partition('|')
            st(sid)['legacy_comments'].append({'style': style, 'at': r.get('createdAt'), 'text': r['comment']})
    for r in notes:
        c = st(r['itemKey'])
        c['comment_history'].append({'at': r.get('createdAt'), 'text': r['comment'] or ''})
        c['comment'] = r['comment'] or None
    for c in out.values():
        c['viewed'] = bool(c['suits'] or c['comment'] or (not c['comment_history'] and c['legacy_comments']))
    return out


def vote_export() -> int:
    """Просмотренные карточки → style-bench/vote-export.jsonl — вход разбора алгоритма стилей через GPT."""
    states = card_states(review_rows('style'), review_rows('style_note'))
    items = json.load(open(SAMPLE, encoding='utf-8'))
    n = n_suits = 0
    path = os.path.join(OUT, 'vote-export.jsonl')
    with open(path, 'w', encoding='utf-8') as f:
        for it in vote_cards(items):
            c = states.get(f"{it['mid']}_{it['eid']}")
            if not c or not c['viewed']:
                continue
            suits = [x for x in STYLES6 if x in c['suits']]
            f.write(json.dumps({'key': f"{it['mid']}_{it['eid']}", 'role': it['role'], 'name': it['name'], 'img': it['img'],
                                'shop': it.get('shop'), 'model_scores': it.get('old'), 'suits': suits,
                                'not_suits': [x for x in STYLES6 if x not in suits], 'universal': 'универсальный' in c['suits'],
                                'comment': c['comment'], 'comment_history': c['comment_history'],
                                'legacy_comments': c['legacy_comments'], 'legacy_no': c['legacy_no']}, ensure_ascii=False) + '\n')
            n += 1
            n_suits += len(suits) + ('универсальный' in c['suits'])
    print(f'выгрузка: {path} (просмотрено карточек {n}, подошедших стилей у них {n_suits}, включая «универсальный»)')
    return 0


def vote_report() -> int:
    """Отметки владельца → доля «подходит» по корзинам балла (нынешний A и оси V2): где проходит черта.
    Считаются только просмотренные карточки: нажатый стиль = подходит, ненажатый = не подходит."""
    import style_axes as SA
    axes_doc, formula = SA.load()
    states = card_states(review_rows('style'), review_rows('style_note'))
    items = {f"{it['mid']}_{it['eid']}": it for it in json.load(open(SAMPLE, encoding='utf-8'))}
    answers = {json.loads(ln)['mkey']: json.loads(ln) for ln in open(ANSWERS, encoding='utf-8')} if os.path.exists(ANSWERS) else {}
    bins: dict = {}
    viewed = 0
    for sid, c in states.items():
        it = items.get(sid)
        if not it or not c['viewed']:
            continue
        viewed += 1
        ans = answers.get(it['mkey'])
        v2 = SA.score_v2(ans['axes'], it['role'], axes_doc, formula)['scores'] if ans else None
        for st in STYLES6:
            yes = st in c['suits']
            for m, sc in (('A', float((it.get('old') or {}).get(st, 0))), ('V2', v2[st] if v2 else None)):
                if sc is None:
                    continue
                b = bins.setdefault(m, {}).setdefault(int(sc * 2) / 2, [0, 0])
                b[0] += yes
                b[1] += 1
    print(f'просмотрено карточек {viewed}')
    for m, bb in bins.items():
        print(m, ' '.join(f'{k:.1f}:{v[0]}/{v[1]}' for k, v in sorted(bb.items())))
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
    vi = vote_items([{'mid': 1, 'eid': str(i), 'role': 'диван', 'name': 'x', 'img': '', 'mkey': str(i),
                      'old': {st: 4 + i / 10 for st in STYLES6}} for i in range(60)], per_style=10)
    ok('отметки: по 10 карточек на каждый из шести стилей, все у черты или уверенные', len(vi) == 60)
    vc = vote_cards([{'mid': 1, 'eid': str(i), 'role': 'диван', 'name': 'x', 'img': '', 'mkey': str(i),
                      'old': {st: 4 + i / 10 for st in STYLES6}} for i in range(60)])
    ok('карточка = товар: без повторов', len(vc) == len({x['eid'] for x in vc}))
    ok('строки карточки: шесть стилей и «универсальный»', VOTE_STYLES == STYLES6 + ['универсальный'])
    lm = last_marks([{'itemKey': 'a|лофт', 'verdict': 'yes'}, {'itemKey': 'a|лофт', 'verdict': 'clear'},
                     {'itemKey': 'a|сканди', 'verdict': 'no'}, {'itemKey': 'a|сканди', 'verdict': 'yes'}])
    ok('clear снимает отметку, побеждает последняя', set(lm) == {'a|сканди'} and lm['a|сканди']['verdict'] == 'yes')
    cs = card_states([{'itemKey': 'a|лофт', 'verdict': 'yes'}, {'itemKey': 'a|сканди', 'verdict': 'yes'},
                      {'itemKey': 'a|сканди', 'verdict': 'clear'}, {'itemKey': 'b|лофт', 'verdict': 'no'},
                      {'itemKey': 'c|джапанди', 'verdict': 'no'}, {'itemKey': 'd|универсальный', 'verdict': 'yes'}],
                     [{'itemKey': 'c', 'comment': 'светлое дерево'}, {'itemKey': 'e', 'comment': 'x'}, {'itemKey': 'e', 'comment': None}])
    ok('v3: yes→clear снимает стиль, несколько стилей вместе', cs['a']['suits'] == ['лофт'])
    ok('v3: старое «не подходит» = не нажато, карточка без комментария не просмотрена',
       cs['b']['suits'] == [] and cs['b']['legacy_no'] == ['лофт'] and not cs['b']['viewed'])
    ok('v3: просмотрено — по нажатию или комментарию; стёртый комментарий не в счёт',
       cs['a']['viewed'] and cs['c']['viewed'] and cs['d']['viewed'] and not cs['e']['viewed'])
    ok('v3: в разметке страницы нет «не подходит»', 'data-v=no' not in VOTE_JS and '"yes"' in VOTE_JS)
    ok('методы V2, H, D считаются по ответам, A — из базы', m['A'] == {'лофт': 7} and all(m[k] for k in ('V2', 'H', 'D')))
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
    if '--vote-page' in sys.argv:
        sys.exit(vote_page())
    if '--vote-report' in sys.argv:
        sys.exit(vote_report())
    if '--vote-export' in sys.argv:
        sys.exit(vote_export())
    print(__doc__)
