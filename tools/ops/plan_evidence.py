#!/usr/bin/env python3
"""Процент пункта плана — ТОЛЬКО из доказательств (T-20261123-48/4; владелец TG 2319 «проценты в плане — да, честнее»; аудит Codex a-dupes-1123 § 2 и § 3 п.3).

ЗАЧЕМ. Ручной «· 90 %» в `.memory_bank/plan-zadach.md` смешивал «код написан», «влито», «прошло товары» и «проверено на живом» (П1.112 «90 %» — паспорта в тени; П1.70 «90 %» — на живом 6 из 10).
Здесь процент ВЫЧИСЛЯЕТСЯ из того, что можно проверить: git, папки прогона, реестр правил. Нет доказательств → «не измерено» (в средний процент не идёт, отдельный счётчик).

КАК. У строки пункта (`П1.n · …`) — скрытый комментарий в той же строке (или в строке сразу под ней; может идти после T-ID: `<!-- T-… · ev: … -->`):
    <!-- ev: task=T-…; branch=ветка; report=путь|sha; sha=sha[,sha]; run=папка; rules=R-…[,R-…]; live=ссылка дата -->
ФАЗА (наибольшая, чьё доказательство есть; «влито» ≠ «принято»):
    0 очередь (ev есть, доказательств нет) · 10 выдано (task) · 40 в работе (branch существует в git или wt=путь существует) · 70 отчёт (report — файл есть или коммит найден)
    80 влито (все sha — предки origin/main) · 90 CI зелёный на этом sha или потомке (прод ≥ sha по /api/health; либо от кода прода до sha менялись только доки — правило deploy-need.sh;
       API GitHub не опрашивается) · 95 прогон есть (run существует; для rules — структурная сверка rule_registry_audit.check_run: rule_id, digest паспорта, applied|abstain по типам;
       есть sha → нужен и 90) · 100 живая проверка (live = ссылка + дата; есть sha/run → нужны и их фазы).
«Конвейер покраски» (строка `**Конвейер покраски — NN %**`): ev `paint=<summary.json круга loop5>` → главная цифра «прошло 5 признаков N из M» (summary['eval'].passed_all из measured),
    процент шагов — вторым (ручная оценка директора, как в строке).
Ручной «· NN %» перезаписывается вычисленным (--write); расхождение > 10 п. печатается всегда. `--dry` (по умолчанию) файл не трогает.
`--infer` — ТОЛЬКО предпросмотр для пунктов без ev: sha/T-ID/ветка/worktree ищутся в тексте строки (не доказательство; с --write нельзя).

  python tools/ops/plan_evidence.py [--plan ФАЙЛ] [--dry | --write] [--check] [--infer] [--json ФАЙЛ] [--prod-sha SHA] [--base origin/main]
--check: rc=1, если у пункта ручной % ≥ 90 без ev или у пункта с ev расхождение > 10 п. (в CI на настоящем плане — шаг «plan-evidence (warn)» в job gate: печатает предупреждение, не валит; тест — на заглушке плана).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rule_registry_audit as RA  # noqa: E402

PLAN = os.path.join(ROOT, '.memory_bank', 'plan-zadach.md')
SITE = os.environ.get('SITE', 'https://remont-lab.online')
SKIP_RE = re.compile(r'^(\.memory_bank/|docs/|\.claude/|\.vscode/|[^/]+\.md$)')   # как в deploy-need.sh: пути, не попадающие в выкладку
LABELS = {0: 'очередь', 10: 'выдано', 40: 'в работе', 70: 'отчёт', 80: 'влито', 90: 'CI зелёный', 95: 'прогон есть', 100: 'живая проверка'}
KEYS = ('task', 'branch', 'wt', 'report', 'sha', 'run', 'rules', 'live', 'paint')
ITEM_RE = re.compile(r'^\**(П\d+\.\d+)\b')
PAINT_RE = re.compile(r'^\*\*Конвейер покраски\b')
PCT_RE = re.compile(r'·\s*(\d+)\s*%')
PAINT_PCT_RE = re.compile(r'(?:—\s*|шаги\s+)(\d+)\s*%')
EV_RE = re.compile(r'<!--(?:(?!-->).)*?\bev:\s*(.*?)\s*-->')   # ev: может стоять после T-ID в том же комментарии
DATE_RE = re.compile(r'\b(\d{1,2}\.\d{1,2}(\.\d{2,4})?|\d{4}-\d{2}-\d{2})\b')
URL_RE = re.compile(r'https?://\S+')
TASK_RE = re.compile(r'\bT-\d{8}-\d+(?:/\d+)?|\bT-\d{2,4}(?:/\d+)?')
HEX_RE = re.compile(r'\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,40}\b')
DIFF_LIMIT = 10


class Ctx:
    """Git, файлы, прод. Всё, что снаружи, — здесь (тесты подставляют prod_sha и временный репозиторий)."""

    def __init__(self, root: str = ROOT, base: str = 'origin/main', prod_sha: str | None = None, registry: str = RA.REGISTRY, passports: str = RA.PASSPORTS, fetch_prod: bool = True):
        self.root, self.base, self.registry, self.passports = root, base, registry, passports
        self._prod, self._prod_set, self.fetch_prod = prod_sha, prod_sha is not None, fetch_prod
        self._pass = None
        self._reg = None

    def git(self, *a: str) -> tuple:
        p = subprocess.run(['git', '-C', self.root, *a], capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.strip()

    def commit(self, ref: str) -> str | None:
        rc, out = self.git('rev-parse', '--verify', '--quiet', ref + '^{commit}')
        return out if rc == 0 and out else None

    def is_ancestor(self, a: str, b: str) -> bool:
        return self.git('merge-base', '--is-ancestor', a, b)[0] == 0

    def merged(self, full: str) -> bool:
        return self.is_ancestor(full, self.base)

    def ref_exists(self, name: str) -> bool:
        return any(self.commit(r) for r in (name, 'origin/' + name))

    def path(self, p: str) -> str:
        p = os.path.expanduser(p.strip())
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def path_exists(self, p: str) -> bool:
        q = self.path(p)
        return os.path.isfile(q) or (os.path.isdir(q) and bool(os.listdir(q)))

    def prod(self) -> str | None:
        if not self._prod_set:
            self._prod_set = True
            if self.fetch_prod:
                try:
                    with urllib.request.urlopen(SITE + '/api/health', timeout=5) as r:
                        m = re.search(r'"version"\s*:\s*"([0-9a-f]{40})"', r.read().decode('utf-8', 'replace'))
                        self._prod = m.group(1) if m else None
                except Exception:  # noqa: BLE001 — нет сети/сайта: «не подтверждено», не падение
                    self._prod = None
        return self._prod

    def ci_green(self, full: str) -> tuple:
        """CI зелёный на sha или потомке — без API: на проде версия ≥ sha (выкладка идёт только после зелёного CI) либо от кода прода до sha менялись только доки (правило deploy-need.sh)."""
        p = self.prod()
        if not p:
            return False, 'версия прода не прочитана (/api/health)'
        pf = self.commit(p)
        if not pf:
            return False, 'коммит прода %s не найден локально (git fetch)' % p[:8]
        if self.is_ancestor(full, pf):
            return True, ''
        if self.is_ancestor(pf, full):
            rc, out = self.git('diff', '--name-only', pf, full)
            if rc == 0 and all(SKIP_RE.match(f) for f in out.splitlines() if f):
                return True, ''
            return False, 'прод позади: стоит %s, код %s ещё не выкачан' % (pf[:8], full[:8])
        return False, 'прод %s и %s в разных ветках истории' % (pf[:8], full[:8])

    def registry_rules(self) -> dict:
        if self._reg is None:
            try:
                self._reg = {r['rule_id']: r for r in json.load(open(self.registry, encoding='utf-8')).get('rules', [])}
            except (OSError, ValueError):
                self._reg = {}
            self._pass = RA.load_passports(self.passports)
        return self._reg

    def passports_map(self) -> dict:
        self.registry_rules()
        return self._pass or {}


def parse_ev(text: str) -> tuple:
    """'k=v; k=v' → ({k: v}, [неизвестные ключи])."""
    ev, bad = {}, []
    for part in text.split(';'):
        if '=' not in part:
            if part.strip():
                bad.append(part.strip()[:20])
            continue
        k, v = part.split('=', 1)
        k = k.strip().lower()
        (ev.__setitem__(k, v.strip()) if k in KEYS else bad.append(k))
    return ev, bad


def parse_plan(text: str) -> list:
    """→ [{kind:'item'|'paint', id, line (индекс), manual (int|None), ev (str|None)}]. Многострочные комментарии пропускаются (скрытый блок «для %» не пункты)."""
    lines = text.splitlines()
    out, in_c = [], False
    for i, raw in enumerate(lines):
        if in_c:
            in_c = '-->' not in raw
            continue
        vis = re.sub(r'<!--.*?-->', '', raw)
        if '<!--' in vis:
            vis = vis.split('<!--', 1)[0]
            in_c = True
        s = vis.strip()
        m = ITEM_RE.match(s)
        if not (m or PAINT_RE.match(s)):
            continue
        evm = EV_RE.search(raw) or (EV_RE.match(lines[i + 1].strip()) if i + 1 < len(lines) else None)
        if m:
            pm = PCT_RE.search(vis)
            out.append({'kind': 'item', 'id': m.group(1), 'line': i, 'manual': int(pm.group(1)) if pm else None, 'ev': evm.group(1) if evm else None, 'text': raw})
        else:
            pm = PAINT_PCT_RE.search(vis)
            out.append({'kind': 'paint', 'id': 'Конвейер покраски', 'line': i, 'manual': int(pm.group(1)) if pm else None, 'ev': evm.group(1) if evm else None, 'text': raw})
    return out


def infer_ev(text: str, ctx: Ctx) -> dict | None:
    """Предпросмотр: что можно вытащить из текста строки (НЕ доказательство). → ev-словарь или None."""
    ev = {}
    t = TASK_RE.search(text)
    if t:
        ev['task'] = t.group(0)
    shas = [h for h in HEX_RE.findall(text) if ctx.commit(h)]
    if shas:
        ev['sha'] = ','.join(shas)
    b = re.search(r'ветк[аи]\s+([\w./\-]+)', text)
    if b and ctx.ref_exists(b.group(1)):
        ev['branch'] = b.group(1)
    w = re.search(r'(\.claude/worktrees/[\w.\-]+|~/remlab-logs/[\w.\-]+)', text)
    if w and ctx.path_exists(w.group(1)):
        ev['wt'] = w.group(1)
    return ev or None


def _shas(ev: dict) -> list:
    return [x for x in re.split(r'[,\s]+', ev.get('sha', '')) if x]


def evaluate(ev: dict, ctx: Ctx) -> dict:
    """→ {phase, label, blockers[]}: фаза — наибольшая из LEVELS с доказательством; blockers — что заявлено, но не подтвердилось."""
    ok, bl = {0: True}, []
    ok[10] = bool(ev.get('task'))
    if ev.get('branch'):
        if ctx.ref_exists(ev['branch']):
            ok[40] = True
        else:
            bl.append('ветка «%s» не найдена в git' % ev['branch'])
    if ev.get('wt'):
        if ctx.path_exists(ev['wt']):
            ok[40] = True
        else:
            bl.append('папка wt «%s» не найдена' % ev['wt'])
    if ev.get('report'):
        r = ev['report']
        if ctx.path_exists(r) or ctx.commit(r):
            ok[70] = True
        else:
            bl.append('отчёт «%s» не найден (ни файл, ни коммит)' % r[:60])
    fulls = []
    for s in _shas(ev):
        f = ctx.commit(s)
        if f:
            fulls.append(f)
        else:
            bl.append('sha %s не найден в git' % s[:12])
    p80 = bool(_shas(ev)) and len(fulls) == len(_shas(ev)) and all(ctx.merged(f) for f in fulls)
    if fulls and len(fulls) == len(_shas(ev)) and not p80:
        bl.append('влито не всё: %s не в %s' % (', '.join(f[:8] for f in fulls if not ctx.merged(f)), ctx.base))
    ok[80] = p80
    p90 = False
    if p80:
        bad = [(f, w) for f in fulls for g, w in [ctx.ci_green(f)] if not g]
        p90 = not bad
        if bad:
            bl.append('CI не подтверждён: ' + bad[0][1])
    ok[90] = p90
    run_ok = None
    if ev.get('run'):
        run_ok = ctx.path_exists(ev['run'])
        if not run_ok:
            bl.append('папка прогона «%s» не найдена или пуста' % ev['run'])
        elif ev.get('rules'):
            probs = []
            reg, pas = ctx.registry_rules(), ctx.passports_map()
            for rid in [x for x in re.split(r'[,\s]+', ev['rules']) if x]:
                rule = reg.get(rid)
                if not rule:
                    probs.append('%s: нет в реестре' % rid)
                    continue
                RA.check_run(rule, ctx.path(ev['run']), pas, ctx.root, lambda r_, c_, why, err=False, _p=probs: _p.append('%s: %s' % (r_, why)))
            if probs:
                run_ok = False
                bl.append('сверка прогона по правилам: ' + '; '.join(probs[:3]))
    elif ev.get('rules'):
        bl.append('rules без run — сверять нечего')
    ok[95] = run_ok is True and (not _shas(ev) or p90)
    live = ev.get('live', '')
    live_ok = bool(URL_RE.search(live) and DATE_RE.search(live))
    if live and not live_ok:
        bl.append('live: нужны ссылка и дата (https://… дд.мм)')
    ok[100] = live_ok and (not _shas(ev) or p90) and (run_ok is None or run_ok is True)
    if live_ok and not ok[100]:
        bl.append('живая проверка есть, но не закрыты sha/CI/прогон — «влито ≠ принято»')
    phase = max(k for k, v in ok.items() if v)
    return {'phase': phase, 'label': LABELS[phase], 'blockers': bl}


def paint_main(path: str, ctx: Ctx) -> dict | None:
    """summary.json круга loop5 → {passed, measured, items, pct}; нет файла/ключей → None («не измерено»)."""
    try:
        d = json.load(open(ctx.path(path), encoding='utf-8'))
    except (OSError, ValueError):
        return None
    e = d.get('eval') if isinstance(d.get('eval'), dict) else d
    if 'passed_all' not in e:
        return None
    items = e.get('items')
    meas = e.get('measured', (items - len(e.get('uncertain') or [])) if isinstance(items, int) else None)
    if not meas:
        return None
    return {'passed': e['passed_all'], 'measured': meas, 'items': items, 'pct': round(100.0 * e['passed_all'] / meas)}


def analyse(text: str, ctx: Ctx, infer: bool = False) -> dict:
    rows = []
    for it in parse_plan(text):
        row = {'id': it['id'], 'kind': it['kind'], 'line': it['line'], 'manual': it['manual'], 'measured': False, 'inferred': False}
        evtxt = it['ev']
        ev, bad = parse_ev(evtxt) if evtxt is not None else (None, [])
        if ev is None and infer and it['kind'] == 'item':
            ev = infer_ev(it['text'], ctx)
            row['inferred'] = ev is not None
        if it['kind'] == 'paint':
            pm = paint_main(ev['paint'], ctx) if ev and ev.get('paint') else None
            row.update(measured=pm is not None, paint=pm, steps=it['manual'], blockers=[] if (pm or not ev) else ['summary.json не найден/не разобран'])
            rows.append(row)
            continue
        if ev is None:
            rows.append(row)
            continue
        r = evaluate(ev, ctx)
        row.update(measured=True, computed=r['phase'], label=r['label'], blockers=r['blockers'] + ['неизвестный ключ «%s»' % b for b in bad])
        if it['manual'] is not None:
            row['diff'] = r['phase'] - it['manual']
        rows.append(row)
    items = [r for r in rows if r['kind'] == 'item']
    meas = [r for r in items if r['measured']]
    return {'rows': rows, 'measured': len(meas), 'unmeasured': len(items) - len(meas), 'avg': round(sum(r['computed'] for r in meas) / len(meas), 1) if meas else None,
            'diverged': [r for r in meas if r.get('diff') is not None and abs(r['diff']) > DIFF_LIMIT],
            'no_ev_high': [r for r in items if not r['measured'] and (r['manual'] or 0) >= 90]}


def render(res: dict, infer: bool = False) -> str:
    L = ['plan_evidence: пунктов %d · измерено %d · не измерено %d (в средний %% не идут)%s' % (res['measured'] + res['unmeasured'], res['measured'], res['unmeasured'],
                                                                                       ' · ПРЕДПРОСМОТР --infer: ev выведены из текста строк, это не доказательство' if infer else '')]
    L.append('')
    for r in res['rows']:
        if r['kind'] == 'paint':
            p = r.get('paint')
            L.append('Конвейер покраски: %s · шаги %s (ручная оценка)' % ('прошло 5 признаков %d из %d (%d %%)' % (p['passed'], p['measured'], p['pct']) if p else 'прошло 5 признаков — не измерено',
                                                                         ('%d %%' % r['steps']) if r.get('steps') is not None else '—'))
            continue
        if not r['measured']:
            continue
        flag = ''
        if r.get('diff') is not None and abs(r['diff']) > DIFF_LIMIT:
            flag = '  ✗ расхождение %+d п.' % r['diff']
        L.append('  %-8s ручной %5s → вычислено %3d %% (%s)%s%s' % (r['id'], ('%d %%' % r['manual']) if r['manual'] is not None else '—', r['computed'], r['label'], flag, ' [предпросмотр]' if r['inferred'] else ''))
        for b in r['blockers']:
            L.append('           · ' + b)
    L.append('')
    L.append('Средний вычисленный %%: %s (по %d измеренным)' % (res['avg'] if res['avg'] is not None else 'нет данных', res['measured']))
    if res['diverged']:
        L.append('Расхождения > %d п.: %s' % (DIFF_LIMIT, ', '.join('%s (%+d)' % (r['id'], r['diff']) for r in res['diverged'])))
    if res['no_ev_high']:
        L.append('Ручной ≥ 90 %% без ev: %s' % ', '.join('%s (%d %%)' % (r['id'], r['manual']) for r in res['no_ev_high']))
    un = [r['id'] for r in res['rows'] if r['kind'] == 'item' and not r['measured']]
    if un:
        L.append('Не измерено: ' + ' '.join(un))
    return '\n'.join(L)


def write_plan(text: str, res: dict) -> tuple:
    """Подставляет вычисленное вместо ручного «· NN %» (у пунктов) и «— NN %» (у строки покраски → «— прошло 5 признаков N из M · шаги S %»). → (новый текст, число правок)."""
    lines = text.splitlines(keepends=True)
    n = 0
    for r in res['rows']:
        if not r['measured'] or r.get('inferred'):
            continue
        raw = lines[r['line']]
        head, sep, tail = raw.partition('<!--')
        if r['kind'] == 'item':
            if r['manual'] is None or r['manual'] == r['computed']:
                continue
            new = PCT_RE.sub('· %d %%' % r['computed'], head, count=1)
        else:
            p = r['paint']
            steps = r['steps'] if r['steps'] is not None else 0
            canon = '— прошло 5 признаков %d из %d · шаги %d %%' % (p['passed'], p['measured'], steps)
            new = re.sub(r'—\s*прошло 5 признаков[^*]*?шаги\s+\d+\s*%|—\s*\d+\s*%', canon, head, count=1)
        if new != head:
            lines[r['line']] = new + sep + tail
            n += 1
    return ''.join(lines), n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--plan', default=PLAN)
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--dry', action='store_true', help='только показать (по умолчанию)')
    g.add_argument('--write', action='store_true', help='вписать вычисленное вместо ручного %%')
    ap.add_argument('--check', action='store_true', help='rc=1: ручной ≥ 90 без ev или расхождение > 10 п. у пункта с ev')
    ap.add_argument('--infer', action='store_true', help='предпросмотр без ev: вывести из текста строк (не доказательство)')
    ap.add_argument('--json', default='', metavar='ФАЙЛ')
    ap.add_argument('--prod-sha', default=None, help='версия прода (иначе читается /api/health)')
    ap.add_argument('--base', default='origin/main')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--registry', default=RA.REGISTRY)
    ap.add_argument('--passports', default=RA.PASSPORTS)
    a = ap.parse_args(argv)
    if a.infer and a.write:
        ap.error('--infer — только предпросмотр, с --write нельзя')
    ctx = Ctx(a.root, a.base, a.prod_sha, a.registry, a.passports)
    text = open(a.plan, encoding='utf-8').read()
    res = analyse(text, ctx, a.infer)
    print(render(res, a.infer))
    if a.json:
        json.dump({k: v for k, v in res.items()}, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    if a.write:
        new, n = write_plan(text, res)
        if n:
            open(a.plan, 'w', encoding='utf-8').write(new)
        print('\n--write: правок %d' % n)
    return 1 if (a.check and (res['diverged'] or res['no_ev_high'])) else 0


if __name__ == '__main__':
    sys.exit(main())
