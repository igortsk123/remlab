# Перенос данных и картинок в Фигму (design-01 п.5). Вызывается из gen2.py; руками — через gen2.py img / gen2.py up (README.md).
# Зачем: длинную строку base64 агент переписывает в вызов use_figma руками и может ошибиться в одном знаке — тогда распаковщик
# в Фигме падает «out of memory». Поэтому: части ≤ ~4800 знаков, у каждого куска в 100 знаков своя контрольная сумма;
# неверный кусок вызов возвращает текстом — переписать только его.
import json, os, sys, zlib, base64, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))

PART = 4800  # знаков b64 на часть (вызов use_figma ≤ 50 000 знаков; память песочницы)
SUBC = 100   # кусок сверки


def jhash(s):
    """та же сумма, что hash() в JS: по UTF-16, h = (h*31 + код) mod 1e9+7"""
    h = 0
    for ch in s:
        o = ord(ch)
        for u in ((0xD800 + ((o - 0x10000) >> 10), 0xDC00 + ((o - 0x10000) & 0x3FF)) if o > 0xFFFF else (o,)):
            h = (h * 31 + u) % 1000000007
    return h


def b64(s):
    return base64.b64encode(zlib.compress(s.encode('utf-8'), 9)).decode()


HEAD = "const g = (k) => figma.root.getSharedPluginData('remlab', k);\n" \
       "const hash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000000007; return h; };\n"


def part_js(key, s, note):
    b = b64(s)
    q = [jhash(b[i:i + SUBC]) for i in range(0, len(b), SUBC)]
    return (f"// {note}\n// Вставить ЦЕЛИКОМ как code в use_figma. Сверяет копию по кускам, распаковывает, кладёт в remlab/{key}.\n" + HEAD +
            f"const KEY = {json.dumps(key, ensure_ascii=False)};\nconst b = '{b}';\nconst Q = {json.dumps(q)};\n"
            f"if (b.length !== {len(b)}) return {{ err: 'длина копии не та — где-то потерян или лишний знак', got: b.length, want: {len(b)} }};\n"
            f"const bad = []; for (let i = 0; i < Q.length; i++) {{ const c = b.slice(i * {SUBC}, i * {SUBC} + {SUBC}); if (hash(c) !== Q[i]) bad.push({{ from: i * {SUBC}, text: c }}); }}\n"
            "if (bad.length) return { err: 'копия не совпала — перепишите эти куски точно из файла части', bad: bad.slice(0, 5) };\n"
            "if (!g('inflate')) return { err: 'в этом файле Фигмы нет распаковщика remlab/inflate — README, шаг 0' };\n"
            "const inflateB64 = new Function(g('inflate') + '; return inflateB64;')();\n"
            f"const s = inflateB64(b);\nif (s.length !== {len(s.encode('utf-16-le')) // 2} || hash(s) !== {jhash(s)}) return {{ err: 'распаковка не совпала', len: s.length }};\n"
            "figma.root.setSharedPluginData('remlab', KEY, s);\nreturn { ok: KEY, len: s.length };\n")


def fill_code(page):
    """залить все фото/фоны страницы по карте remlab/imgHash (адрес -> imageHash); вернуть, каких адресов в карте нет и на какой узел их грузить"""
    return (f"const page = figma.root.children.find((p) => p.name === {json.dumps(page, ensure_ascii=False)});\n"
            "await figma.setCurrentPageAsync(page);\n"
            "const M = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');\n"
            "let filled = 0; const need = {};\n"
            "for (const n of page.findAll((n) => !!n.getSharedPluginData('remlab', 'src'))) {\n"
            "  const src = n.getSharedPluginData('remlab', 'src'); const h = M[src];\n"
            "  if (!h) { if (!need[src]) need[src] = n.id; continue; }\n"
            "  n.fills = [{ type: 'IMAGE', imageHash: h, scaleMode: n.getSharedPluginData('remlab', 'fit') === 'contain' ? 'FIT' : 'FILL' }]; filled++;\n"
            "}\n")


def write_parts(P, d):
    """P -> папка с файлами вызовов: NN-*.js (части данных), build-NN.js (сборка секции), fill.js, check.js, ПОРЯДОК.txt"""
    os.makedirs(d, exist_ok=True)
    page, dev = P['page'], P['dev']
    base = f"data/{dev}/{page}"
    names = [s['sec'] for s in P['sections']]
    order, n, allkeys, partdata = [], 0, [], []
    for si, sec in enumerate(P['sections']):
        head = {k: v for k, v in sec.items() if k != 'variants'}
        groups, cur = [], []
        for v in sec['variants']:
            if cur and len(b64(json.dumps({'sec': head, 'variants': cur + [v]}, ensure_ascii=False, separators=(',', ':')))) > PART:
                groups.append(cur); cur = []
            cur.append(v)
        groups.append(cur)
        keys = []
        for gi, grp in enumerate(groups):
            n += 1
            key = f"{base}/{n:02d}"
            s = json.dumps({'sec': head, 'variants': grp}, ensure_ascii=False, separators=(',', ':'))
            if len(b64(s)) > PART * 1.6:
                print(f"ВНИМАНИЕ: один вариант секции «{sec['sec']}» даёт {len(b64(s))} знаков b64 — вызов может не пройти", file=sys.stderr)
            fn = f"{n:02d}-часть.js"
            open(os.path.join(d, fn), 'w', encoding='utf-8').write(
                part_js(key, s, f"часть {n}: «{page}» ({dev}), секция «{sec['sec']}», варианты {gi + 1}/{len(groups)}"))
            keys.append(key); order.append(fn); partdata.append((key, s))
        allkeys.append(keys)
        fn = f"build-{si + 1:02d}.js"
        open(os.path.join(d, fn), 'w', encoding='utf-8').write(
            f"// сборка секции «{sec['sec']}» страницы «{page}» ({dev}) из частей {keys[0]}…{keys[-1]}; затем заливка известных фото.\n" + HEAD +
            f"const keys = {json.dumps(keys, ensure_ascii=False)}; let sec = null;\n"
            "for (const k of keys) { const s = g(k); if (!s) return { err: 'нет части ' + k + ' — сначала вызовите её файл' }; const d = JSON.parse(s); if (!sec) sec = { ...d.sec, variants: [] }; sec.variants.push(...d.variants); }\n"
            f"const names = {json.dumps(names, ensure_ascii=False)};\n"
            f"const P = {{ page: {json.dumps(page, ensure_ascii=False)}, dev: {json.dumps(dev)}, maxW: {P['maxW']}, only: [sec.sec], sections: names.map((x) => (x === sec.sec ? sec : {{ sec: x, variants: [] }})) }};\n"
            "if (!g('builder2')) return { err: 'в этом файле Фигмы нет сборщика remlab/builder2 — README, шаг 0' };\n"
            "const AF = Object.getPrototypeOf(async function () {}).constructor;\n"
            "const out = await new AF('P', g('builder2'))(P);\n"
            "if (out.err) return out;\n" + fill_code(page).replace("const page = ", "const page_ = ").replace("(page)", "(page_)").replace("page.findAll", "page_.findAll") +
            "return { sections: out.sections, warn: out.warn, layout: out.layout, notFit: out.fit.length, filled, needImages: Object.keys(need).length };\n")
        order.append(fn)
    # пачки: несколько частей в одном вызове (≤ ~40 000 знаков кода) — меньше вызовов; проверка та же, что в NN-часть.js
    packs, cur, size = [], [], 0
    for key, s in partdata:
        if cur and size + len(b64(s)) > 36000: packs.append(cur); cur, size = [], 0
        cur.append((key, s)); size += len(b64(s))
    if cur: packs.append(cur)
    for pi, pk in enumerate(packs):
        rows = []
        for key, s in pk:
            b = b64(s)
            rows.append(f"[{json.dumps(key, ensure_ascii=False)}, '{b}', {json.dumps([jhash(b[i:i + SUBC]) for i in range(0, len(b), SUBC)])}, {len(b)}, {len(s.encode('utf-16-le')) // 2}, {jhash(s)}]")
        open(os.path.join(d, f'пачка-{pi + 1}.js'), 'w', encoding='utf-8').write(
            f"// пачка {pi + 1}/{len(packs)}: части {', '.join(k for k, _ in pk)} одним вызовом. Строка: [ключ, b64, суммы кусков по {SUBC}, длина b64, длина текста, сумма текста]\n" + HEAD +
            "const R = [\n" + ',\n'.join(rows) + "\n];\n"
            "if (!g('inflate')) return { err: 'в этом файле Фигмы нет распаковщика remlab/inflate — README, шаг 0' };\n"
            "const inflateB64 = new Function(g('inflate') + '; return inflateB64;')();\n"
            "const res = [];\n"
            f"for (const [key, b, Q, bl, sl, sh] of R) {{\n"
            "  if (b.length !== bl) { res.push({ key, err: 'длина копии не та', got: b.length, want: bl }); continue; }\n"
            f"  const bad = []; for (let i = 0; i < Q.length; i++) {{ const c = b.slice(i * {SUBC}, i * {SUBC} + {SUBC}); if (hash(c) !== Q[i]) bad.push({{ from: i * {SUBC}, text: c }}); }}\n"
            "  if (bad.length) { res.push({ key, err: 'копия не совпала — перепишите эти куски', bad: bad.slice(0, 5) }); continue; }\n"
            "  const s = inflateB64(b);\n"
            "  if (s.length !== sl || hash(s) !== sh) { res.push({ key, err: 'распаковка не совпала' }); continue; }\n"
            "  figma.root.setSharedPluginData('remlab', key, s); res.push({ ok: key, len: s.length });\n"
            "}\nreturn res;\n")
    # вся страница одним вызовом (небольшие страницы; на больших — build-NN.js по одной секции, иначе не хватит памяти)
    open(os.path.join(d, 'build-all.js'), 'w', encoding='utf-8').write(
        f"// сборка ВСЕХ секций «{page}» ({dev}) одним вызовом + заливка фото + проверка; для больших страниц — build-NN.js по очереди\n" + HEAD +
        f"const K = {json.dumps(allkeys, ensure_ascii=False)};\n"
        "const sections = [];\n"
        "for (const keys of K) { let sec = null; for (const k of keys) { const s = g(k); if (!s) return { err: 'нет части ' + k + ' — сначала пачки/части' }; const d = JSON.parse(s); if (!sec) sec = { ...d.sec, variants: [] }; sec.variants.push(...d.variants); } sections.push(sec); }\n"
        f"const P = {{ page: {json.dumps(page, ensure_ascii=False)}, dev: {json.dumps(dev)}, maxW: {P['maxW']}, sections }};\n"
        "if (!g('builder2')) return { err: 'в этом файле Фигмы нет сборщика remlab/builder2 — README, шаг 0' };\n"
        "const AF = Object.getPrototypeOf(async function () {}).constructor;\n"
        "const out = await new AF('P', g('builder2'))(P);\n"
        "if (out.err) return out;\n" + fill_code(page).replace("const page = ", "const page_ = ").replace("(page)", "(page_)").replace("page.findAll", "page_.findAll") +
        f"const chk = await new AF('P', g('check'))({{ page: {json.dumps(page, ensure_ascii=False)} }});\n"
        "return { sections: out.sections, warn: out.warn, notFit: out.fit.length, filled, need: Object.entries(need), check: chk.counts };\n")
    open(os.path.join(d, 'fill-need.js'), 'w', encoding='utf-8').write(
        f"// какие картинки страницы «{page}» ещё не загружены: ответ сохранить в need.json и дать gen2.py img\n" + fill_code(page) +
        "return Object.entries(need);\n")
    open(os.path.join(d, 'check.js'), 'w', encoding='utf-8').write(
        f"// проверка страницы «{page}»: всё должно быть 0\n" + HEAD +
        "const AF = Object.getPrototypeOf(async function () {}).constructor;\n"
        f"return await new AF('P', g('check'))({{ page: {json.dumps(page, ensure_ascii=False)} }});\n")
    order += ['fill-need.js', '(картинки: gen2.py img / upload_assets / gen2.py up → fill.js)', 'check.js']
    open(os.path.join(d, 'ПОРЯДОК.txt'), 'w', encoding='utf-8').write(
        'Вызывать use_figma по порядку, по одному файлу (содержимое файла = code):\n' + '\n'.join(order) + '\n'
        f'\nКороче: сперва пачка-1.js … пачка-{len(packs)}.js (все части), затем build-*.js по порядку (небольшая страница — один build-all.js, он же заливает фото и проверяет), fill-need.js, check.js.\n')
    return {'dir': d, 'files': len(order), 'parts': n}


def main(argv):
    cmd = argv[0]
    if cmd == 'img':
        # gen2.py img <need.json> <новая папка>: скачать, WebP -> PNG (Фигма WebP принимает, но не рисует), план загрузки
        need, out = json.load(open(argv[1])), argv[2]
        if os.path.exists(out): sys.exit(f'папка {out} уже есть — нужна новая (старое не удаляем)')
        try:
            from PIL import Image
        except ImportError:
            sys.exit('нет PIL — запускайте через r (на pakardev он есть): r python3 gen2.py img ...')
        os.makedirs(out)
        plan = []
        for i, (src, node) in enumerate(need):
            ext = src.rsplit('.', 1)[-1].lower().split('?')[0]
            raw = os.path.join(out, f'{i:02d}.{ext}')
            req = urllib.request.Request(src, headers={'User-Agent': 'remlab-figma'})
            open(raw, 'wb').write(urllib.request.urlopen(req, timeout=30).read())
            f, ct = raw, {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif'}.get(ext)
            if not ct:  # webp и прочее -> PNG
                f = os.path.join(out, f'{i:02d}.png'); Image.open(raw).convert('RGBA').save(f); ct = 'image/png'
            plan.append({'src': src, 'node': node, 'file': os.path.abspath(f), 'ct': ct})
        json.dump(plan, open(os.path.join(out, 'plan.json'), 'w'), ensure_ascii=False, indent=1)
        print(json.dumps({'plan': os.path.join(out, 'plan.json'), 'count': len(plan), 'nodeIds': [p['node'] for p in plan]}, ensure_ascii=False))
        return 0
    if cmd == 'up':
        # gen2.py up <plan.json> <ответ upload_assets.json> <Страница>: залить байты, собрать imageHash, написать fill.js
        plan, resp, page = json.load(open(argv[1])), json.load(open(argv[2])), argv[3]
        ups = resp.get('uploads', resp) if isinstance(resp, dict) else resp
        by = {u['targetNodeId']: u['submitUrl'] for u in ups}
        pairs, fail = {}, []
        for p in plan:
            url = by.get(p['node'])
            if not url: fail.append([p['src'], 'нет адреса загрузки для узла ' + p['node']]); continue
            req = urllib.request.Request(url, data=open(p['file'], 'rb').read(), headers={'Content-Type': p['ct']}, method='POST')
            try:
                r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
                h = r.get('imageHash') or (r.get('data') or {}).get('imageHash')
                if not h: raise ValueError(str(r)[:200])
                pairs[p['src']] = h
            except Exception as e:  # noqa: BLE001 — каждую неудачу показываем
                fail.append([p['src'], str(e)[:200]])
        fn = os.path.join(os.path.dirname(os.path.abspath(argv[1])), 'fill.js')
        open(fn, 'w', encoding='utf-8').write(
            f"// записать новые адреса в карту remlab/imgHash и залить фото страницы «{page}»\n"
            "const M0 = JSON.parse(figma.root.getSharedPluginData('remlab', 'imgHash') || '{}');\n"
            f"Object.assign(M0, {json.dumps(pairs, ensure_ascii=False)});\n"
            "figma.root.setSharedPluginData('remlab', 'imgHash', JSON.stringify(M0));\n" + fill_code(page) +
            "return { filled, stillMissing: Object.keys(need) };\n")
        print(json.dumps({'uploaded': len(pairs), 'fail': fail, 'fill': fn}, ensure_ascii=False))
        return 1 if fail else 0
    if cmd == 'install':
        # gen2.py install <новая папка>: вызовы, кладущие распаковщик, сборщик и проверку в файл Фигмы (шаг 0 README)
        out = argv[1]
        if os.path.exists(out): sys.exit(f'папка {out} уже есть — нужна новая')
        os.makedirs(out)
        inf = open(os.path.join(HERE, 'inflate.js'), encoding='utf-8').read()
        n16 = lambda s: len(s.encode('utf-16-le')) // 2  # noqa: E731
        open(os.path.join(out, '0-inflate.js'), 'w', encoding='utf-8').write(
            "// распаковщик текстом (без сжатия): сверка длины и суммы, затем remlab/inflate\n"
            f"const s = {json.dumps(inf, ensure_ascii=False)};\n"
            "let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000000007;\n"
            f"if (s.length !== {n16(inf)} || h !== {jhash(inf)}) return {{ err: 'копия не совпала', len: s.length, h }};\n"
            "figma.root.setSharedPluginData('remlab', 'inflate', s);\nreturn { ok: 'inflate', len: s.length };\n")
        for i, k in ((1, 'builder2'), (2, 'check')):
            s = open(os.path.join(HERE, k + '.js'), encoding='utf-8').read()
            open(os.path.join(out, f'{i}-{k}.js'), 'w', encoding='utf-8').write(part_js(k, s, f'{k}.js ({n16(s)} знаков, сумма {jhash(s)})'))
        print(json.dumps({'dir': out, 'files': sorted(os.listdir(out))}, ensure_ascii=False))
        return 0
    sys.exit('команды: img <need.json> <новая папка> | up <plan.json> <ответ.json> <Страница> | install <новая папка>')
