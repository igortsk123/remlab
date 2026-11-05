"""Профиль типа комнаты RoomProfile (room-pipeline-01 Б-2, T-20261105-40): загрузчик, ссылки и линтер.

Профиль — ДАННЫЕ (`rules/profiles/<тип>.json`, схема `rules/room-profile.schema.json`, версия схемы 1): какие роли, откуда товар,
что крупное, жёсткие пределы, стили и веса, слоты и допуск, нормы, 2 вида на зону, стратегия ассета, какой плагин собирает
наборы (`composer`) и какой расставляет (`solver_plugin`). Алгоритмов в профиле нет: плагин выбирается по имени, данные
передаются ему как есть (риск 4 разбора Codex 05.11 — профиль не язык программирования).

Значение поля может быть ссылкой `{"$ref": "<путь от корня репо>#/<JSON-указатель>"}` на уже существующее правило — один факт
в одном месте; `load()` подставляет ссылки. Гостиную профиль только ОПИСЫВАЕТ (compose2.py его не читает); спальня
(`compose_bedroom.py`) читает из профиля.

    python room_profile.py --lint [тип]        # схема, версия, ссылки, плагины, роли = адаптер, виды = CAM_ZONES демо (node)
    python room_profile.py --lint --cam-html <index.html>   # виды сверить с другой копией демо (ветка до вливания)
    python room_profile.py --rehash <тип>      # пересчитать content_sha после правки (и поднять profile_version!)
    python room_profile.py --show <тип>        # профиль с подставленными ссылками
    python room_profile.py --selftest          # без базы и сети
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
PROFILES = os.path.join(HERE, 'rules', 'profiles')
SCHEMA = os.path.join(HERE, 'rules', 'room-profile.schema.json')
CAM_HTML = os.path.join(HERE, 'flat215-demo', 'index.html')
REGISTRY = os.path.join(ROOT, 'services', 'planner-solver', 'planner', 'room_registry.py')
MODELS = os.path.join(ROOT, 'services', 'planner-solver', 'planner', 'models.py')
# реестр сборщиков наборов: имя плагина → файл (плагин — код, профиль только называет его)
COMPOSERS = {'living_legacy': 'tools/scout/compose2.py', 'bedroom': 'tools/scout/compose_bedroom.py'}
UNVERSIONED = ('profile_version', 'content_sha')


# ---------------------------------------------------------------- загрузка и ссылки
def path_of(room_type: str) -> str:
    return os.path.join(PROFILES, f'{room_type}.json')


def types() -> list:
    return sorted(f[:-5] for f in os.listdir(PROFILES) if f.endswith('.json'))


def raw(room_type: str) -> dict:
    """Профиль как в файле (ссылки не подставлены). Нет профиля — ValueError, не «гостиная по умолчанию»."""
    p = path_of(room_type) if isinstance(room_type, str) and re.fullmatch(r'[a-z_]+', room_type or '') else None
    if not p or not os.path.exists(p):
        raise ValueError(f'room_profile: нет профиля типа комнаты {room_type!r}; есть: {", ".join(types())}')
    return json.load(open(p, encoding='utf-8'))


def is_ref(v) -> bool:
    return isinstance(v, dict) and set(v) == {'$ref'} and isinstance(v['$ref'], str)


_FILES: dict = {}


def deref(ref: str):
    """«путь#/указатель» → значение (копия). Путь — от корня репо, указатель — JSON Pointer (RFC 6901)."""
    path, _, ptr = ref.partition('#')
    full = os.path.normpath(os.path.join(ROOT, path))
    if not full.startswith(ROOT + os.sep) or not os.path.isfile(full):
        raise ValueError(f'ссылка {ref!r}: нет файла {path}')
    if full not in _FILES:
        _FILES[full] = json.load(open(full, encoding='utf-8'))
    v = _FILES[full]
    for part in [p.replace('~1', '/').replace('~0', '~') for p in ptr.split('/')[1:]] if ptr else []:
        if isinstance(v, dict) and part in v:
            v = v[part]
        elif isinstance(v, list) and part.isdigit() and int(part) < len(v):
            v = v[int(part)]
        else:
            raise ValueError(f'ссылка {ref!r}: нет «{part}»')
    return copy.deepcopy(v)


def resolve(v):
    if is_ref(v):
        return deref(v['$ref'])
    if isinstance(v, dict):
        return {k: resolve(x) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x) for x in v]
    return v


def refs(v, at: str = '') -> list:
    """[(где, ссылка)] по всему профилю."""
    if is_ref(v):
        return [(at, v['$ref'])]
    if isinstance(v, dict):
        return [x for k, s in v.items() for x in refs(s, f'{at}.{k}' if at else k)]
    if isinstance(v, list):
        return [x for i, s in enumerate(v) for x in refs(s, f'{at}[{i}]')]
    return []


def load(room_type: str) -> dict:
    """Профиль с подставленными ссылками (новая копия на каждый вызов — правка результата файл и кэш не трогает)."""
    return resolve(raw(room_type))


def major(P: dict) -> tuple:
    """Крупное (ставит солвер, полоса Ш×Г×В, меш под слот) — в порядке ролей профиля."""
    return tuple(r for r, v in P['roles'].items() if v.get('major'))


def hard(P: dict, role: str, key: str, default=None):
    return (P['roles'].get(role, {}).get('hard') or {}).get(key, default)


def content_sha(p: dict) -> str:
    body = {k: v for k, v in p.items() if k not in UNVERSIONED}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:12]


# ---------------------------------------------------------------- схема (подмножество draft 2020-12, без зависимостей)
def schema_errors(v, s: dict, at: str = '$') -> list:
    """type, const, enum, pattern, required, properties, patternProperties, additionalProperties, items, minItems.
    Ссылка {"$ref": …} на месте значения принимается как есть (её проверяет сам линтер)."""
    if is_ref(v):
        return []
    T = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'object': dict, 'array': list, 'null': type(None)}
    errs = []
    if 'type' in s:
        ts = s['type'] if isinstance(s['type'], list) else [s['type']]
        if not any(isinstance(v, T[t]) and not (t in ('integer', 'number') and isinstance(v, bool)) for t in ts):
            return [f'{at}: {type(v).__name__}, ждали {"|".join(ts)}']
    if 'const' in s and v != s['const']:
        errs.append(f'{at}: {v!r} ≠ {s["const"]!r}')
    if 'enum' in s and v not in s['enum']:
        errs.append(f'{at}: {v!r} не из {s["enum"]}')
    if 'pattern' in s and isinstance(v, str) and not re.search(s['pattern'], v):
        errs.append(f'{at}: {v!r} не по образцу {s["pattern"]}')
    if isinstance(v, dict):
        errs += [f'{at}: нет поля {k}' for k in s.get('required', []) if k not in v]
        props, pats, add = s.get('properties', {}), s.get('patternProperties', {}), s.get('additionalProperties', True)
        for k, x in v.items():
            if k in props:
                errs += schema_errors(x, props[k], f'{at}.{k}')
            elif any(re.search(p, k) for p in pats):
                errs += schema_errors(x, next(pats[p] for p in pats if re.search(p, k)), f'{at}.{k}')
            elif add is False:
                errs.append(f'{at}: лишнее поле {k}')
            elif isinstance(add, dict):
                errs += schema_errors(x, add, f'{at}.{k}')
    if isinstance(v, list):
        if len(v) < s.get('minItems', 0):
            errs.append(f'{at}: элементов {len(v)} < {s["minItems"]}')
        if 'items' in s:
            for i, x in enumerate(v):
                errs += schema_errors(x, s['items'], f'{at}[{i}]')
    return errs


# ---------------------------------------------------------------- источники истины для сверки (без импорта чужого кода)
def solver_types() -> tuple:
    """(типы, откуда): реестр солвера T-37 (`room_registry.PLAGINY`); до его вливания — `models.RoomType`."""
    for path, what in ((REGISTRY, 'PLAGINY'), (MODELS, 'RoomType')):
        if not os.path.exists(path):
            continue
        for n in ast.walk(ast.parse(open(path, encoding='utf-8').read())):
            tgt = n.target if isinstance(n, ast.AnnAssign) else (n.targets[0] if isinstance(n, ast.Assign) and len(n.targets) == 1 else None)
            if not (isinstance(tgt, ast.Name) and tgt.id == what and n.value is not None):
                continue
            if isinstance(n.value, ast.Dict):
                return [k.value for k in n.value.keys if isinstance(k, ast.Constant)], os.path.relpath(path, ROOT) + ':' + what
            if isinstance(n.value, ast.Subscript):   # Literal["living", …]
                sl = n.value.slice
                els = sl.elts if isinstance(sl, ast.Tuple) else [sl]
                return [e.value for e in els if isinstance(e, ast.Constant)], os.path.relpath(path, ROOT) + ':' + what
    return [], 'нет реестра солвера'


def compose2_roles() -> list:
    src = open(os.path.join(HERE, 'compose2.py'), encoding='utf-8').read()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'ROLES':
            return [e.value for e in n.value.elts]
    raise ValueError('compose2.py: нет ROLES')


# Извлекатель CAM_ZONES из index.html демо: выполняет только объявления const CAM_* в песочнице vm (index.html не меняет).
# Строкой здесь, а не файлом .js: в tools/scout git берёт только код .py/.sh (.gitignore). Вывод: {"CAM_ZONES":…} | {"missing":…}
CAM_JS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function stmt(name) {      // оператор `const …name=…;` целиком (скобки, строки и // комментарии учтены)
  const re = new RegExp('(^|\\n)\\s*const\\s+(?:[A-Za-z_$][\\w$]*\\s*=[^;]*?,\\s*)?' + name + '\\s*=');
  const m = re.exec(src); if (!m) return null;
  const i = src.indexOf('const', m.index); let d = 0, q = null;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (q) { if (c === '\\') { j++; continue; } if (c === q) q = null; continue; }
    if (c === "'" || c === '"' || c === '`') { q = c; continue; }
    if (c === '/' && src[j + 1] === '/') { j = src.indexOf('\n', j); continue; }
    if ('([{'.includes(c)) d++; else if (')]}'.includes(c)) d--; else if (c === ';' && d === 0) return src.slice(i, j + 1);
  }
  return null;
}
const ctx = {}; vm.createContext(ctx);
for (const n of ['CAM_CORE', 'CAM_KEY', 'CAM_KEY_SHOW', 'CAM_MUST', 'CAM_COVER', 'CAM_ZONES']) {
  const s = stmt(n);
  if (!s) { console.log(JSON.stringify({ missing: n })); process.exit(0); }
  vm.runInContext(s.replace(/^const /, 'var '), ctx, { timeout: 1000 });
}
console.log(JSON.stringify({ CAM_ZONES: ctx.CAM_ZONES, CAM_COVER: ctx.CAM_COVER }));
"""


def cam_zones(html: str) -> tuple:
    """(CAM_ZONES | None, почему нет): из демо через node (`CAM_JS`)."""
    if not os.path.exists(html):
        return None, f'нет {html}'
    if not shutil.which('node'):
        return None, 'нет node'
    r = subprocess.run(['node', '-e', CAM_JS, html], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError(f'извлечение CAM_ZONES упало: {r.stderr[:300]}')
    d = json.loads(r.stdout)
    if 'missing' in d:
        return None, f'в {os.path.relpath(html, ROOT)} нет {d["missing"]} (демо с видами по зонам ещё не влито)'
    return d['CAM_ZONES'], ''


# ---------------------------------------------------------------- линтер
def lint(room_type: str, cam_html: str = CAM_HTML) -> tuple:
    """(ошибки, предупреждения) профиля."""
    E, W = [], []
    p = raw(room_type)
    E += schema_errors(p, json.load(open(SCHEMA, encoding='utf-8')))
    if p.get('profile_id') != room_type or p.get('room_type') != room_type:
        E.append(f'profile_id/room_type ≠ имени файла {room_type}')
    if p.get('content_sha') != content_sha(p):
        E.append(f'профиль правлен без новой версии: content_sha {p.get("content_sha")} ≠ {content_sha(p)} — подними profile_version '
                 f'и выполни --rehash {room_type}')
    for at, ref in refs(p):
        try:
            deref(ref)
        except ValueError as e:
            E.append(f'{at}: {e}')
    if E:
        return E, W
    P = resolve(p)
    comp = P['composer']['plugin']
    if not os.path.isfile(os.path.join(ROOT, COMPOSERS[comp])):
        E.append(f'composer {comp}: нет {COMPOSERS[comp]}')
    st, src = solver_types()
    if P['solver_plugin'] not in st:
        E.append(f'solver_plugin {P["solver_plugin"]!r} нет в {src} ({st})')
    if src.endswith('RoomType'):
        W.append(f'реестр солвера T-37 не влит — solver_plugin сверен с {src}')
    # роли профиля = роли адаптера каталога
    import catalog_items as CI
    if room_type not in CI.ROOM_TYPES:
        E.append(f'у адаптера catalog_items нет типа {room_type} ({CI.ROOM_TYPES})')
    else:
        got = {}
        for origin, _, rs in CI._sources(room_type):
            got.setdefault(origin, []).extend(compose2_roles() if rs is None else rs)
        mine = {}
        for r, v in P['roles'].items():
            mine.setdefault(v['source'], []).append(r)
        for o in sorted(set(got) | set(mine)):
            a, b = set(mine.get(o, [])), set(got.get(o, []))
            if a != b:
                E.append(f'роли {o}: в профиле, но не у адаптера {sorted(a - b)}; у адаптера, но не в профиле {sorted(b - a)}'
                         + (' (living: открытый список адаптера сверен с compose2.ROLES)' if room_type == 'living' else ''))
    gstyles = set(deref('tools/scout/styles.json#/styles'))
    bad = [s for s in P['style']['ids'] if s not in gstyles]
    if bad:
        E.append(f'стили {bad} не из глобальных tools/scout/styles.json')
    rw = P['style']['role_weights']
    if not isinstance(rw, dict) or not all(isinstance(x, (int, float)) for x in rw.values()):
        E.append('style.role_weights — не «роль → число»')
    tol = P['tolerance']
    if not (isinstance(tol, list) and len(tol) == 2 and 0 < tol[0] <= 1 <= tol[1]):
        E.append(f'tolerance {tol!r} — ждали [низ ≤ 1 ≤ верх]')
    if comp == 'bedroom':
        R = P['composer']['rules']
        used = {s['role'] for pr in R['purposes'].values() for s in pr.get('slots', [])} | \
               {r for pr in R['purposes'].values() for r in pr.get('decor', {}) if not r.startswith('_')}
        if used - set(P['roles']):
            E.append(f'роли состава наборов не в профиле: {sorted(used - set(P["roles"]))}')
        if set(major(P)) - set(rw):
            E.append(f'у крупного нет веса стиля: {sorted(set(major(P)) - set(rw))}')
    cz, why = cam_zones(cam_html)
    if cz is None:
        W.append(f'виды не сверены с демо: {why}')
    else:
        for z, rec in P['camera']['zones'].items():
            if cz.get(z) != rec:
                E.append(f'camera.zones.{z} ≠ CAM_ZONES.{z} демо ({os.path.relpath(cam_html, ROOT)}) — один источник: поправь профиль')
    return E, W


# ---------------------------------------------------------------- селфтест (без базы, сети и node)
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    for t in ('kitchen', 'hall', 'garage', '', None, '../rules/x'):
        try:
            raw(t)
            ok(f'профиль {t!r} — ошибка', False)
        except ValueError:
            ok(f'профиль {t!r} — ошибка (не гостиная по умолчанию)', True)
    ok('профили living и bedroom есть', {'living', 'bedroom'} <= set(types()))
    for t in ('living', 'bedroom'):
        p = raw(t)
        ok(f'{t}: схема', not schema_errors(p, json.load(open(SCHEMA, encoding='utf-8'))))
        ok(f'{t}: content_sha совпадает', p['content_sha'] == content_sha(p))
        ok(f'{t}: ссылки разрешаются', all(deref(r) is not None for _, r in refs(p)))
    p = raw('bedroom')
    q = copy.deepcopy(p)
    q['roles']['шкаф']['hard']['min_w'] = 70
    ok('правка без новой версии видна', content_sha(q) != p['content_sha'])
    q['profile_version'] = '2026-11-06.1'
    ok('версия в хеш не входит', content_sha(q) == content_sha(dict(q, profile_version='x')))
    S = json.load(open(SCHEMA, encoding='utf-8'))
    ok('схема ловит лишнее, тип, enum, версию схемы',
       len(schema_errors(dict(p, x=1, schema_version=2, composer={'plugin': 'kitchen'}, roles={'a': {'source': 'x'}}), S)) == 4)
    ok('ссылка на месте значения — допустима схемой', not schema_errors({'$ref': 'a#/b'}, {'type': 'array'}))
    for ref in ('tools/scout/nope.json', 'tools/scout/rules/demo-swap.json#/нет', '../../etc/passwd'):
        try:
            deref(ref)
            ok(f'битая ссылка {ref} — ошибка', False)
        except ValueError:
            ok(f'битая ссылка {ref} — ошибка', True)
    P = load('bedroom')
    ok('спальня: крупное и порядок как прежние MAJOR', major(P) == ('кровать', 'шкаф', 'комод', 'тумба прикроватная'))
    ok('спальня: шкаф ≥ 80, допуск 0,8–1,1, порог 6,6',
       hard(P, 'шкаф', 'min_w') == 80 and P['tolerance'] == [0.8, 1.1] and P['style']['in_style_min'] == 6.6)
    P['roles'].clear()
    ok('load — новая копия (правка не портит следующую загрузку)', load('bedroom')['roles'])
    st, src = solver_types()
    ok(f'типы солвера читаются ({src})', {'living', 'bedroom'} <= set(st))
    ok('роли гостиной compose2 читаются без импорта', 'диван' in compose2_roles() and len(compose2_roles()) == 27)
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    pos, i = [], 0
    while i < len(argv):
        if argv[i] == '--cam-html':
            i += 2
            continue
        if not argv[i].startswith('--'):
            pos.append(argv[i])
        i += 1
    arg = pos[0] if pos else None
    if '--rehash' in argv:
        p = raw(arg)
        p['content_sha'] = content_sha(p)
        open(path_of(arg), 'w', encoding='utf-8').write(json.dumps(p, ensure_ascii=False, indent=1) + '\n')
        print(f'{arg}: content_sha {p["content_sha"]}, profile_version {p["profile_version"]} (подними, если правил)')
        return 0
    if '--show' in argv:
        print(json.dumps(load(arg), ensure_ascii=False, indent=1))
        return 0
    html = argv[argv.index('--cam-html') + 1] if '--cam-html' in argv else CAM_HTML
    fails = 0
    for t in [arg] if arg else types():
        E, W = lint(t, html)
        for w in W:
            print(f'WARN {t}: {w}')
        for e in E:
            print(f'ERR  {t}: {e}')
        print(f'{t}: {"OK" if not E else f"{len(E)} ошибок"}')
        fails += len(E)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
