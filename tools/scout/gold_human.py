#!/usr/bin/env python3
"""gold-human-v1 — человеческий эталон обогащения (T2 мастер-плана truth-first).

Зачем: текущий golden set размечен сильной МОДЕЛЬЮ (gpt-5.6-terra), поэтому 92.6/89.8/97%
— это model-agreement, а не измеренная точность (вердикт рефери, принят). Человеческий
эталон делает цифры настоящими и позволяет откалибровать порог quality 0.65.

Схема разметки (ответ рефери на наш Q2):
  - разметчики A и B — вся выборка; арбитр C — конфликты;
  - НЕЗАВИСИМЫЙ C-прогон на ~25% (детерминированное подмножество по хешу ключа) — для
    честного agreement: арбитр, видевший спор, независимым рейтером не является;
  - объективные поля (роль/подтип/цвет/материалы) — хватает A+B+арбитраж;
    субъективные (стили, low/med/high) — считаем α по каждому стилю отдельно;
  - низкий α по полю = чинить guideline/объединять лейблы, а не выжимать разметку.

Команды:
  --sample [N]           стратифицированная выборка (デф. 400) → gold-human/sample.json
  --page                 слепая страница разметки → gold-human/annotate.html (localStorage,
                         экспорт в JSON; ?rater=C показывает только C-подмножество)
  --agree a.json b.json [c.json]   Krippendorff α (nominal/ordinal) + конфликты → adjudicate.json
  --calibrate gold.json  P(role_correct | quality-бакет) против ответов модели из БД
"""
import hashlib
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'gold-human')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

ROLES = ['диван', 'кресло', 'пуф', 'столик', 'стол обеденный', 'стул', 'тв-тумба', 'комод',
         'стеллаж', 'витрина', 'стенка', 'шкаф', 'полка', 'ковёр', 'торшер', 'лампа', 'люстра',
         'бра', 'камин', 'кашпо', 'ваза', 'статуэтка', 'растение', 'зеркало', 'часы', 'шторы',
         'плед', 'подушка', 'картина', 'другое']
COLORS = ['белый', 'чёрный', 'серый', 'бежевый', 'коричневый', 'синий', 'зелёный', 'жёлтый',
          'красный', 'оранжевый', 'розовый', 'фиолетовый', 'не_определён']
MATERIALS = ['велюр', 'рогожка', 'шенилл', 'букле', 'экокожа', 'кожа', 'ткань', 'бархат',
             'дерево', 'ЛДСП', 'МДФ', 'металл', 'стекло', 'камень', 'пластик', 'ротанг',
             'керамика', 'не_видно']
STYLES = ['сканди', 'современный', 'минимализм', 'лофт', 'неоклассика', 'джапанди']
LEVELS = ['нет', 'низкая', 'средняя', 'высокая']   # порядковая шкала для α-ordinal
C_SHARE = 0.25   # доля независимого C-подмножества


def sql(q: str) -> str:
    r = subprocess.run(PSQL, input=q, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[:400]); sys.exit(1)
    return r.stdout


def key(mid, eid) -> str:
    return f'{mid}:{eid}'


def in_c_subset(k: str) -> bool:
    """Детерминированное C-подмножество ~25% — по хешу ключа, без Math.random."""
    return int(hashlib.sha1(k.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < C_SHARE


# ------------------------------------------------------------------ выборка

def sample(n: int = 400) -> None:
    """Стратификация: роль (пропорционально, min 5) × наличие фото/размеров/описания;
    +10% квота карточек quality<0.65 (спорные) и редких подтипов."""
    rows = []
    for line in sql("""
        select p.shop_mid, p.external_id, p.name, p.shop, p.cat_role,
               coalesce(p.image_url,''), coalesce(p.price_rub,0),
               (p.w_cm is not null and p.d_cm is not null)::int,
               (p.description is not null)::int, coalesce(e.quality,0)
          from products p join product_enrichment e using (shop_mid, external_id)
         where p.cat_role is not null and p.in_stock and p.image_url is not null
    """).strip().split('\n'):
        f = line.split('\x1f')
        if len(f) >= 10:
            rows.append({'mid': int(f[0]), 'eid': f[1], 'name': f[2], 'shop': f[3],
                         'role_feed': f[4], 'img': f[5], 'price': int(f[6]),
                         'has_dims': f[7] == '1', 'has_desc': f[8] == '1',
                         'quality': float(f[9])})
    random.seed(42)   # воспроизводимая выборка
    by_role: dict[str, list] = {}
    for r in rows:
        by_role.setdefault(r['role_feed'], []).append(r)
    total_pool = len(rows)
    picked, seen = [], set()

    def take(r):
        k = key(r['mid'], r['eid'])
        if k not in seen:
            seen.add(k); picked.append(r)

    # 1) квота спорных: 10% из низкого качества
    low = [r for r in rows if r['quality'] < 0.65]
    random.shuffle(low)
    for r in low[:max(1, n // 10)]:
        take(r)
    # 2) пропорционально по ролям, min 5 на роль, внутри роли — разнообразие по
    #    (магазин, есть_размеры, есть_описание)
    for role, pool in sorted(by_role.items()):
        quota = max(5, round(n * len(pool) / total_pool))
        random.shuffle(pool)
        pool.sort(key=lambda r: (r['shop'], r['has_dims'], r['has_desc']))
        stepped = pool[::max(1, len(pool) // quota)][:quota]
        for r in stepped:
            take(r)
    random.shuffle(picked)
    picked = picked[:max(n, len([p for p in picked if in_c_subset(key(p['mid'], p['eid']))]))]
    os.makedirs(OUT, exist_ok=True)
    for r in picked:
        r['c_subset'] = in_c_subset(key(r['mid'], r['eid']))
    json.dump(picked, open(os.path.join(OUT, 'sample.json'), 'w'), ensure_ascii=False, indent=1)
    n_c = sum(1 for r in picked if r['c_subset'])
    print(f'выборка: {len(picked)} товаров ({len(by_role)} ролей), C-подмножество {n_c}')


# ------------------------------------------------------------------ страница разметки

def _model_answers(items: list) -> dict:
    """Предразметка автоматом (схема владельца 08.08): модельные ответы из product_enrichment
    предзаполняют форму, человек ПРАВИТ, расхождения human↔model = карта ошибок автомата.
    ВАЖНО (anchor-bias): C-подмножество (?rater=C) остаётся СЛЕПЫМ — без предзаполнения;
    сравнение C-слепых с prefilled-разметкой A/B измеряет, насколько автомат «якорит» людей."""
    keys = ','.join(f"({it['mid']},'{it['eid']}')" for it in items)
    out = {}
    for line in sql(f"""select shop_mid, external_id, payload->'model'
                          from product_enrichment
                         where (shop_mid, external_id) in ({keys})
                           and payload is not null""").strip().split('\n'):
        f = line.split('\x1f')
        if len(f) >= 3 and f[2]:
            try:
                m = json.loads(f[2])
            except json.JSONDecodeError:
                continue
            out[f'{f[0]}:{f[1]}'] = {
                'role': m.get('role'), 'color': m.get('primary_color'),
                'materials': [x for x in (m.get('materials') or []) if x],
                'styles': m.get('styles') or {}}
    return out


def page() -> None:
    items = json.load(open(os.path.join(OUT, 'sample.json')))
    prefill = _model_answers(items) if '--prefill' in sys.argv else {}
    opt = lambda vals: ''.join(f'<option>{v}</option>' for v in vals)  # noqa: E731
    html = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>gold-human-v1 — разметка</title>
<style>
 body{{font-family:system-ui;margin:0;background:#f4f4f2;color:#222}}
 .bar{{position:sticky;top:0;background:#2f6b5e;color:#fff;padding:10px 16px;display:flex;gap:16px;align-items:center}}
 .bar input{{padding:4px 8px}} .bar button{{padding:6px 12px;cursor:pointer}}
 .card{{background:#fff;max-width:900px;margin:14px auto;padding:14px 18px;border-radius:8px;display:none}}
 .card.active{{display:block}}
 img{{max-height:340px;max-width:46%;object-fit:contain;float:left;margin-right:18px;background:#eee}}
 h3{{margin:.2em 0}} .hint{{color:#777;font-size:.85em}}
 fieldset{{border:1px solid #ddd;margin:.5em 0;border-radius:6px}}
 label.m{{display:inline-block;margin:2px 8px 2px 0;white-space:nowrap}}
 select{{padding:3px}} .styles td{{padding:2px 8px}}
 .nav{{display:flex;gap:10px;margin-top:10px}} .nav button{{padding:8px 14px}}
 .done{{outline:3px solid #2f6b5e}}
</style>
<div class="bar">
 <b>gold-human-v1</b>
 <label>Разметчик: <input id="rater" size="8" placeholder="A / B / C"></label>
 <span id="pos"></span>
 <button onclick="exp()">Экспорт JSON</button>
 <span class="hint">Слепая разметка: ответы модели не показываются. «uncertain» — честный ответ.</span>
</div>
<div id="cards"></div>
<script>
const ITEMS = {json.dumps(items, ensure_ascii=False)};
const PREFILL = {json.dumps(prefill, ensure_ascii=False)};   // предразметка автоматом; для C — не применяется (слепое подмножество)
const ROLES = {json.dumps(ROLES, ensure_ascii=False)};
const COLORS = {json.dumps(COLORS, ensure_ascii=False)};
const MATERIALS = {json.dumps(MATERIALS, ensure_ascii=False)};
const STYLES = {json.dumps(STYLES, ensure_ascii=False)};
const LEVELS = {json.dumps(LEVELS + ['uncertain'], ensure_ascii=False)};
const params = new URLSearchParams(location.search);
const onlyC = params.get('rater') === 'C';
const list = onlyC ? ITEMS.filter(i => i.c_subset) : ITEMS;
if (onlyC) document.getElementById('rater').value = 'C';
let idx = +(localStorage.getItem('gh-idx') || 0);
const K = it => it.mid + ':' + it.eid;
const store = k => JSON.parse(localStorage.getItem('gh-' + k) || 'null');
function render() {{
  const c = document.getElementById('cards'); c.innerHTML = '';
  const it = list[idx]; if (!it) return;
  document.getElementById('pos').textContent = (idx + 1) + ' / ' + list.length;
  // предзаполнение: сохранённое человеком сильнее автомата; C-режим всегда слепой
  const auto = (!onlyC && PREFILL[K(it)]) || {{}};
  const prev = store(K(it)) || auto;
  const isAuto = !store(K(it)) && !!PREFILL[K(it)] && !onlyC;
  const sel = (name, vals, cur) => `<select data-f="${{name}}">` +
    ['— выберите —', ...vals, 'uncertain'].map(v => `<option ${{v === cur ? 'selected' : ''}}>${{v}}</option>`).join('') + '</select>';
  const mats = MATERIALS.map(m => `<label class="m"><input type="checkbox" data-mat="${{m}}" ${{(prev.materials || []).includes(m) ? 'checked' : ''}}>${{m}}</label>`).join('');
  const styleRows = STYLES.map(s => `<tr><td>${{s}}</td><td>${{sel('style:' + s, LEVELS.slice(0, 4), (prev.styles || {{}})[s])}}</td></tr>`).join('');
  c.innerHTML = `<div class="card active ${{prev.role ? 'done' : ''}}">
    <img src="${{it.img.startsWith('//') ? 'https:' + it.img : it.img}}" loading="lazy">
    <h3>${{it.name}}</h3><div class="hint">${{it.shop}} · ${{it.price}} ₽ · категория фида: ${{it.role_feed}}
    ${{isAuto ? ' · <b style="color:#b07c2e">⚠ предзаполнено автоматом — проверь каждое поле</b>' : ''}}</div>
    <fieldset><legend>Роль</legend>${{sel('role', ROLES, prev.role)}}</fieldset>
    <fieldset><legend>Основной цвет</legend>${{sel('color', COLORS, prev.color)}}</fieldset>
    <fieldset><legend>Материалы (видимые)</legend>${{mats}}</fieldset>
    <fieldset><legend>Стиль (независимо по каждому)</legend><table class="styles">${{styleRows}}</table></fieldset>
    <div class="nav"><button onclick="nav(-1)">← Назад</button><button onclick="saveIt(1)">Сохранить →</button></div>
    <div style="clear:both"></div></div>`;
}}
function collect() {{
  const it = list[idx]; const out = {{}};
  document.querySelectorAll('[data-f]').forEach(s => {{
    const v = s.value; if (v && v !== '— выберите —') {{
      const f = s.dataset.f;
      if (f.startsWith('style:')) {{ out.styles = out.styles || {{}}; out.styles[f.slice(6)] = v; }}
      else out[f === 'color' ? 'color' : f] = v;
    }}
  }});
  out.materials = [...document.querySelectorAll('[data-mat]:checked')].map(x => x.dataset.mat);
  return out;
}}
function saveIt(d) {{
  const it = list[idx]; localStorage.setItem('gh-' + K(it), JSON.stringify(collect())); nav(d);
}}
function nav(d) {{ idx = Math.min(Math.max(idx + d, 0), list.length - 1); localStorage.setItem('gh-idx', idx); render(); }}
function exp() {{
  const rater = document.getElementById('rater').value || '?';
  const out = {{ rater, subset: onlyC ? 'C25' : 'full', items: {{}} }};
  list.forEach(it => {{ const v = store(K(it)); if (v) out.items[K(it)] = v; }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {{type: 'application/json'}}));
  a.download = 'gold-human-' + rater + '.json'; a.click();
}}
render();
</script></html>"""
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'annotate.html'), 'w').write(html)
    print(f'страница: {OUT}/annotate.html ({len(items)} товаров; ?rater=C — C-подмножество)')


# ------------------------------------------------------------------ agreement (Krippendorff α)

def _alpha(pairs: list[tuple], ordinal: list | None = None) -> float | None:
    """Krippendorff α для 2+ рейтеров, попарные значения (v1, v2) по каждому item.
    ordinal — упорядоченный список уровней (квадратичные веса), иначе nominal."""
    vals = [v for p in pairs for v in p if v is not None]
    if len(vals) < 4:
        return None
    def d(a, b):
        if ordinal:
            try:
                return (ordinal.index(a) - ordinal.index(b)) ** 2
            except ValueError:
                return 0 if a == b else 1
        return 0 if a == b else 1
    Do = sum(d(a, b) for a, b in pairs if a is not None and b is not None)
    no = sum(1 for a, b in pairs if a is not None and b is not None)
    if not no:
        return None
    Do /= no
    De = sum(d(a, b) for a in vals for b in vals) / (len(vals) * (len(vals) - 1))
    return None if De == 0 else round(1 - Do / De, 3)


def agree(files: list[str]) -> None:
    raters = [json.load(open(f)) for f in files]
    keys = set.intersection(*[set(r['items']) for r in raters]) if raters else set()
    print(f'общих размеченных: {len(keys)} (рейтеры: {", ".join(r["rater"] for r in raters)})')
    def col(field, sub=None):
        pairs = []
        for k in keys:
            vs = []
            for r in raters:
                v = r['items'][k].get(field) if sub is None else (r['items'][k].get(field) or {}).get(sub)
                vs.append(None if v in (None, 'uncertain') else v)
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    pairs.append((vs[i], vs[j]))
        return pairs
    print('α роль:      ', _alpha(col('role')))
    print('α цвет:      ', _alpha(col('color')))
    for s in STYLES:
        print(f'α стиль {s:12}', _alpha(col('styles', s), ordinal=LEVELS))
    conflicts = [k for k in keys
                 if len({r['items'][k].get('role') for r in raters} - {None, 'uncertain'}) > 1]
    json.dump(sorted(conflicts), open(os.path.join(OUT, 'adjudicate.json'), 'w'), indent=1)
    print(f'конфликтов по роли: {len(conflicts)} → gold-human/adjudicate.json (арбитру C)')


# ------------------------------------------------------------------ калибровка порога

def calibrate(gold_file: str) -> None:
    gold = json.load(open(gold_file))['items']
    keys = ','.join(f"({k.split(':')[0]},'{k.split(':', 1)[1]}')" for k in gold)
    buckets: dict[str, list] = {}
    for line in sql(f"""select shop_mid, external_id, payload->'model'->>'role',
                              coalesce(quality, 0)
                         from product_enrichment
                        where (shop_mid, external_id) in ({keys})""").strip().split('\n'):
        f = line.split('\x1f')
        if len(f) < 4:
            continue
        k = f'{f[0]}:{f[1]}'
        human = gold.get(k, {}).get('role')
        if not human or human == 'uncertain' or not f[2]:
            continue
        b = f'{float(f[3]) // 0.1 * 0.1:.1f}'
        buckets.setdefault(b, []).append(f[2] == human)
    print('P(role_correct | quality-бакет) — против ЧЕЛОВЕЧЕСКОГО эталона:')
    for b in sorted(buckets):
        v = buckets[b]
        print(f'  {b}–{float(b)+0.1:.1f}: {sum(v)}/{len(v)} = {sum(v)/len(v)*100:.0f}%')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == '--help':
        print(__doc__)
    elif a[0] == '--sample':
        sample(int(a[1]) if len(a) > 1 else 400)
    elif a[0] == '--page':
        page()
    elif a[0] == '--agree':
        agree(a[1:])
    elif a[0] == '--calibrate':
        calibrate(a[1])
