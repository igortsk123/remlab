#!/usr/bin/env python3
"""СБОРЩИК ВЕТОК «В ТЕНИ» (T-20261112-78, план .memory_bank/plans/merge-queue-01.md; владелец TG 1083/1093/1117).

Вместо «каждая ветка — свой полный прогон» сборщик сливает 2–4 ветки во ВРЕМЕННОЙ копии от текущего main, гоняет ОДИН полный
набор проверок и при падении сам находит виновную ветку. Не пушит, не вливает, main и основную копию не трогает — только отчёт.

    tools/ops/merge-queue.sh <ветка>[@sha] <ветка>[@sha] …     пачка 2–4 веток (sha — проверить ровно этот хеш, урок 612)
        [--steps typecheck,lint,test,build,prepush,memory]  какие шаги (по умолчанию все, кроме build; порядок — всегда этот)
        [--base main] [--out ПАПКА] [--keep] [--no-slot] [--pkg пакет.json …]
    tools/ops/merge-queue.sh --selftest                     временный репозиторий, подставные шаги, без heavy-slot

Как работает:
  1. временный worktree `~/remlab-logs/mq/<ЧЧММСС>/wt` от main (`git worktree add --detach`; fetch не делает);
  2. ветки по очереди: `git cherry <база> <sha>` → только коммиты, которых в main ещё нет, `cherry-pick` (как вливает директор);
     конфликт → `--abort`, ветка выбывает строкой «конфликт», остальные идут дальше;
  3. `pnpm install --offline --frozen-lockfile` (жёсткие ссылки из хранилища pnpm, без сети; урок 611) — повторно только если
     сменился pnpm-lock.yaml;
  4. ОДИН полный прогон шагов (первый упавший шаг останавливает прогон); весь сборщик — один слот `heavy-slot.sh mq-full
     --min-gb 2 --cores 3 --prio 1` (с build — 3 ГБ; повтор, main и бисекция в очередь заново не встают; `--no-slot` — без очереди);
  5. упало → повтор упавшего шага (прошёл — «мигает», вину не вешаем) → тот же шаг на чистом main (упал — «main красный») →
     деление пополам по префиксам набора (main+B1, main+B1+B2 …) одним упавшим шагом → виновная выбывает → полный прогон без неё;
  6. отчёт `report.md` (строка на ветку `ветка · SHA · ok | конфликт | падает: <шаг>: <тест>`), `summary.json`, логи шагов,
     строка в `~/remlab-logs/mq/journal.tsv`. Всё зелёное — worktree убирается (`git worktree remove`), иначе остаётся для разбора.
Код выхода: 0 — все ветки ok; 1 — есть конфликт/падение/main красный; 2 — ошибка запуска."""
import json
import os
import re
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HEAVY = os.path.join(HERE, 'heavy-slot.sh')
LOG_ROOT = os.path.expanduser(os.environ.get('MQ_LOG_ROOT', '~/remlab-logs/mq'))

# шаги полного прогона. {files} — изменённые пачкой файлы (main..вершина), {soft} — шаг не валит прогон (только предупреждение)
STEPS = [
    ('typecheck', 'pnpm typecheck'),
    ('lint', 'pnpm lint'),
    ('test', 'pnpm test'),
    ('build', 'pnpm build'),
    ('prepush', 'bash tools/ops/prepush-check.sh --budget 600 --files {files}'),
    ('memory', 'node tools/memory-audit.mjs --check . && node tools/memory-project-audit.mjs --check .'),
]
# по умолчанию — как велел директор (T-20261112-57): typecheck + lint + vitest, плюс дешёвые селфтесты CI по изменённым файлам
# и аудиты памяти (CI-гейт). Сборка — по `--steps …,build` (она одна поднимает порог памяти до 3 ГБ).
DEFAULT_STEPS = ['typecheck', 'lint', 'test', 'prepush', 'memory']


def slot_args(step_names: list) -> list:
    """Порог по `heavy-slot.sh --stats` (12.11): typecheck/lint/test — пик 1,1–1,5 ГБ, эфф. порог 2; сборка (тип full) RSS 2,24 → 3.
    vitest ~2,6 ядра → 3. `--prio 1` — проверка пачки ждёт директор, как интерактивную пробу."""
    gb = '3' if 'build' in step_names else '2'
    return ['--min-gb', gb, '--cores', '3', '--prio', '1']
GIT_ID = {'GIT_AUTHOR_NAME': 'merge-queue', 'GIT_AUTHOR_EMAIL': 'mq@remlab.local',
          'GIT_COMMITTER_NAME': 'merge-queue', 'GIT_COMMITTER_EMAIL': 'mq@remlab.local'}


def now() -> str:
    return time.strftime('%H:%M:%S')


def git(args: list, cwd: str, check: bool = True, env: dict | None = None) -> str:
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=True, env=e)
    if check and p.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)}: {p.stderr.strip() or p.stdout.strip()}')
    return p.stdout.strip()


class Run:
    def __init__(self, repo: str, refs: list, steps: list, base: str, out: str, slot: bool, keep: bool, pkgs: list,
                 say=print):
        self.repo, self.refs, self.steps, self.slot, self.keep, self.say = repo, refs, steps, slot, keep, say
        self.base_ref = base
        self.base = git(['rev-parse', '--verify', base + '^{commit}'], repo)
        self.out = out
        self.wt = os.path.join(out, 'wt')
        self.pkgs = pkgs
        self.n_full = 0
        self.n_step = 0
        self.lock_hash = None
        self.seq = 0
        self.t0 = time.time()
        self.need_install = any(c.startswith('pnpm ') or ' pnpm ' in c for _, c in steps)
        gm = os.path.join(repo, '.memory_bank', '_kit', 'gate-mode.txt')
        self.memory_soft = not (os.path.isfile(gm) and open(gm).read().strip() == 'block')

    # ---------- журнал ----------
    def log(self, msg: str) -> None:
        line = f'{now()} {msg}'
        self.say(line)
        with open(os.path.join(self.out, 'mq.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    # ---------- ветки ----------
    def resolve(self) -> list:
        items = []
        for r in self.refs:
            name, _, sha = r.partition('@')
            ref = sha or name
            full = git(['rev-parse', '--verify', ref + '^{commit}'], self.repo)
            tip = git(['rev-parse', '--verify', name + '^{commit}'], self.repo, check=False) if sha else full
            items.append({'name': name, 'sha': full, 'moved': bool(sha and tip and tip != full), 'status': None,
                          'detail': ''})
        return items

    def commits_of(self, sha: str, upstream: str | None = None) -> list:
        """Коммиты ветки, которых нет в upstream (база или уже собранный префикс набора; по содержимому: перенесённое
        cherry-pick'ом — «-», пропускаем). Префикс как upstream нужен веткам, перебазированным на соседнюю: её коммиты
        уже в наборе и второй раз не берутся."""
        out = git(['cherry', upstream or self.base, sha], self.repo)
        return [l[2:] for l in out.splitlines() if l.startswith('+ ')]

    # ---------- worktree ----------
    def wt_add(self) -> None:
        git(['worktree', 'add', '-q', '--detach', self.wt, self.base], self.repo)

    def checkout(self, sha: str) -> None:
        git(['checkout', '-q', '-f', '--detach', sha], self.wt)
        git(['clean', '-fdq'], self.wt)                 # только неотслеживаемое и не игнорируемое: node_modules/.next целы

    def stack(self, items: list) -> list:
        """База + ветки по очереди. Возвращает префиксы: [база, после 1-й ветки, …] для веток со статусом None."""
        self.checkout(self.base)
        prefixes = [self.base]
        for it in items:
            if it['status'] is not None:
                continue
            if not self.commits_of(it['sha']):
                it['status'], it['detail'] = 'ok', 'уже в main'
                continue
            cs = self.commits_of(it['sha'], prefixes[-1])
            if not cs:
                it['status'], it['detail'] = 'ok', 'целиком внутри веток выше по набору'
                continue
            p = subprocess.run(['git', 'cherry-pick', '--allow-empty', '--keep-redundant-commits'] + cs, cwd=self.wt,
                               capture_output=True, text=True, env={**os.environ, **GIT_ID})
            if p.returncode != 0:
                files = git(['diff', '--name-only', '--diff-filter=U'], self.wt, check=False).split()
                git(['cherry-pick', '--abort'], self.wt, check=False)
                git(['reset', '-q', '--hard', prefixes[-1]], self.wt, check=False)
                it['status'] = 'конфликт'
                it['detail'] = ', '.join(files[:5]) or (p.stderr.strip().splitlines() or ['?'])[-1][:160]
                self.log(f'конфликт: {it["name"]} ({it["detail"]})')
                continue
            it['_prefix'] = git(['rev-parse', 'HEAD'], self.wt)
            prefixes.append(it['_prefix'])
            self.log(f'слита: {it["name"]} {it["sha"][:12]} ({len(cs)} коммит.)')
        return prefixes

    def install(self) -> bool:
        if not self.need_install:
            return True
        lf = os.path.join(self.wt, 'pnpm-lock.yaml')
        h = git(['hash-object', lf], self.wt, check=False) if os.path.isfile(lf) else ''
        if h and h == self.lock_hash and os.path.isdir(os.path.join(self.wt, 'node_modules')):
            return True
        t = time.time()
        logf = os.path.join(self.out, 'install.log')
        with open(logf, 'a', encoding='utf-8') as f:
            rc = subprocess.run(['pnpm', 'install', '--offline', '--frozen-lockfile'], cwd=self.wt, stdout=f,
                                stderr=subprocess.STDOUT).returncode
        self.log(f'pnpm install --offline: rc={rc}, {time.time() - t:.0f} с')
        if rc == 0:
            self.lock_hash = h
        return rc == 0

    # ---------- шаги ----------
    def _cmd(self, cmd: str) -> str:
        if '{files}' in cmd:
            files = git(['diff', '--name-only', self.base, 'HEAD'], self.wt, check=False).split()
            cmd = cmd.replace('{files}', ' '.join(shlex.quote(f) for f in files) or '/dev/null')
        return cmd

    def run_steps(self, names: list, tag: str) -> list:
        """Шаги по порядку до первого упавшего (мягкий шаг — только предупреждение). Под одним слотом heavy-slot."""
        self.seq += 1
        d = os.path.join(self.out, f'{self.seq:02d}-{tag}')
        os.makedirs(d, exist_ok=True)
        plan = [(n, self._cmd(c)) for n, c in self.steps if n in names]
        script = ['set -u', f'cd {shlex.quote(self.wt)}']
        for n, c in plan:
            lg = shlex.quote(os.path.join(d, f'{n}.log'))
            rcf = shlex.quote(os.path.join(d, f'{n}.rc'))
            soft = n == 'memory' and self.memory_soft
            script.append(f's=$(date +%s); ( {c} ) > {lg} 2>&1; r=$?; echo "$r $(( $(date +%s) - s ))" > {rcf}')
            if not soft:
                script.append('[ "$r" = 0 ] || exit "$r"')
        sh = os.path.join(d, 'steps.sh')
        with open(sh, 'w', encoding='utf-8') as f:
            f.write('\n'.join(script) + '\nexit 0\n')
        cmd = ['bash', sh]
        if self.slot:
            label = 'mq-full' if len(plan) > 1 else f'mq-{plan[0][0]}' if plan else 'mq'
            cmd = ['bash', HEAVY, label] + slot_args([n for n, _ in plan]) + ['--', 'bash', sh]
        t = time.time()
        with open(os.path.join(d, 'runner.log'), 'w', encoding='utf-8') as f:
            runner_rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode
        res = []
        for n, c in plan:
            rcf = os.path.join(d, f'{n}.rc')
            soft = n == 'memory' and self.memory_soft
            if not os.path.isfile(rcf):
                if self.first_fail(res) is None:
                    # ЛОЖНЫЙ ЗЕЛЁНЫЙ (12.11, директор): шаг не оставил код возврата, а до него ничего не падало — значит, прогон не
                    # дошёл до шага (очередь heavy-slot не пустила/таймаут 124, обрыв, ошибка скрипта). Это провал, а не «ok».
                    res.append({'step': n, 'rc': runner_rc or 99, 's': 0, 'log': os.path.join(d, 'runner.log'),
                                'soft': False, 'missing': True})
                break
            parts = open(rcf).read().split()
            rc = int(parts[0]) if parts and parts[0].lstrip('-').isdigit() else 99
            secs = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            res.append({'step': n, 'rc': rc, 's': secs, 'log': os.path.join(d, f'{n}.log'), 'soft': soft})
        if runner_rc != 0 and self.first_fail(res) is None:
            # все шаги записали 0, а исполнитель упал (heavy-slot, bash) — тоже не зелёный
            res.append({'step': plan[-1][0] if plan else '?', 'rc': runner_rc, 's': 0,
                        'log': os.path.join(d, 'runner.log'), 'soft': False, 'missing': True})
        if tag.startswith('full'):                       # по роли прогона, не по числу шагов (--steps test — тоже «полный»)
            self.n_full += 1
        else:
            self.n_step += 1
        fails = [r for r in res if r['rc'] != 0 and not r['soft']]
        self.log(f'прогон {tag}: ' + ', '.join(f'{r["step"]}={"ok" if r["rc"] == 0 else "rc" + str(r["rc"])}'
                                             f' {r["s"]}с' for r in res) + f' · всего {time.time() - t:.0f} с')
        return res

    @staticmethod
    def first_fail(res: list) -> dict | None:
        for r in res:
            if r['rc'] != 0 and not r['soft']:
                return r
        return None

    def green(self, sha: str, step: str, tag: str) -> bool:
        self.checkout(sha)
        if not self.install():
            return False
        return self.first_fail(self.run_steps([step], tag)) is None

    # ---------- главный цикл ----------
    def go(self) -> dict:
        os.makedirs(self.out, exist_ok=True)
        items = self.resolve()
        self.log(f'база {self.base_ref} {self.base[:12]} · ветки: ' + ', '.join(f'{i["name"]}@{i["sha"][:12]}' for i in items))
        self.wt_add()
        verdict = {'main_red': None, 'flaky': [], 'warnings': []}
        names = [n for n, _ in self.steps]
        try:
            for _ in range(len(items) + 1):
                prefixes = self.stack(items)
                live = [i for i in items if i['status'] is None]
                if not live:
                    break
                if not self.install():
                    for i in live:
                        i['status'], i['detail'] = 'не проверена', 'pnpm install --offline не прошёл (install.log)'
                    break
                res = self.run_steps(names, 'full')
                for r in res:
                    if r['rc'] != 0 and r['soft']:
                        verdict['warnings'].append(f'{r["step"]}: {fail_detail(r["log"])}')
                bad = self.first_fail(res)
                if bad is None:
                    for i in live:
                        i['status'] = 'ok'
                    break
                step = bad['step']
                # (1) мигает? повтор шага на том же наборе
                if self.first_fail(self.run_steps([step], f'retry-{step}')) is None:
                    verdict['flaky'].append(step)
                    rest = names[names.index(step) + 1:]
                    res2 = self.run_steps(rest, 'full-rest') if rest else []
                    bad2 = self.first_fail(res2)
                    if bad2 is None:
                        for i in live:
                            i['status'], i['detail'] = 'ok', f'шаг {step} мигнул (повтор зелёный)'
                        break
                    bad, step = bad2, bad2['step']
                detail = fail_detail(bad['log'])
                if bad.get('missing'):
                    detail = f'шаг не дошёл до кода возврата (исполнитель rc={bad["rc"]}): {detail}'
                # (2) чистый main
                if not self.green(self.base, step, f'main-{step}'):
                    verdict['main_red'] = f'{step}: {fail_detail(self._last_log(step))}'
                    for i in live:
                        i['status'], i['detail'] = 'не проверена', f'main красный на {step}'
                    break
                # (3) деление пополам по префиксам: prefixes[0] зелёный, prefixes[-1] красный
                lo, hi = 0, len(prefixes) - 1
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if self.green(prefixes[mid], step, f'bisect{mid}-{step}'):
                        lo = mid
                    else:
                        hi = mid
                        detail = fail_detail(self._last_log(step))
                culprit = next(i for i in live if i.get('_prefix') == prefixes[hi])
                culprit['status'], culprit['detail'] = 'падает', f'{step}: {detail}'
                self.log(f'виновная: {culprit["name"]} — {step}: {detail}')
                # (4) остальные — следующим кругом цикла: новый набор без виновной, полный прогон
        finally:
            summary = self.finish(items, verdict)
        return summary

    def _last_log(self, step: str) -> str:
        """Лог шага из последнего прогона, где этот шаг был."""
        ds = sorted(d for d in os.listdir(self.out) if re.match(r'\d\d-', d))
        for d in reversed(ds):
            p = os.path.join(self.out, d, f'{step}.log')
            if os.path.isfile(p):
                return p
        return ''

    # ---------- отчёт ----------
    def finish(self, items: list, verdict: dict) -> dict:
        mins = (time.time() - self.t0) / 60
        for i in items:
            if i['status'] is None:
                i['status'], i['detail'] = 'не проверена', 'прогон прерван'
        all_ok = all(i['status'] == 'ok' for i in items) and not verdict['main_red']
        lines = [f'# Сборщик веток (тень) · {time.strftime("%d.%m %H:%M")} · база `{self.base_ref}` {self.base[:12]}', '',
                 f'Итог: {"✅ все ok" if all_ok else "❗ есть проблемы"} · {mins:.1f} мин · полных прогонов {self.n_full}, '
                 f'одиночных шагов {self.n_step} · шаги: {", ".join(n for n, _ in self.steps)}', '']
        if verdict['main_red']:
            lines.append(f'❗ main красный: {verdict["main_red"]} — ветки не виноваты, сначала чинить main')
        if verdict['flaky']:
            lines.append(f'⚠ мигал шаг: {", ".join(verdict["flaky"])} (повтор зелёный — вину не вешаем)')
        for w in verdict['warnings']:
            lines.append(f'⚠ предупреждение (gate warn): {w}')
        lines.append('')
        for i in items:
            st = i['status'] + (f': {i["detail"]}' if i['detail'] and i['status'] != 'ok' else
                                f' ({i["detail"]})' if i['detail'] else '')
            moved = ' · ⚠ ветка ушла вперёд — вердикт про этот SHA' if i['moved'] else ''
            lines.append(f'- `{i["name"]}` · `{i["sha"][:12]}` · {st}{moved}')
        ok_names = [i['name'] for i in items if i['status'] == 'ok' and i['detail'] != 'уже в main']
        if ok_names:
            lines += ['', 'Вливать в этом порядке (проверено вместе, на базе выше): ' + ' → '.join(f'`{n}`' for n in ok_names)]
        lines += ['', f'Логи: `{self.out}` (mq.log — ход, NN-*/шаг.log — вывод шагов)']
        keep = self.keep or not all_ok
        if keep:
            lines.append(f'Временная копия оставлена для разбора: `{self.wt}`')
        for p in self.pkgs:
            lines.append(f'Пакет автора: `{p}`')
        report = os.path.join(self.out, 'report.md')
        with open(report, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        summary = {'base': self.base, 'out': self.out, 'minutes': round(mins, 1), 'full_runs': self.n_full,
                   'step_runs': self.n_step, 'all_ok': all_ok, **verdict,
                   'branches': [{k: v for k, v in i.items() if not k.startswith('_')} for i in items]}
        with open(os.path.join(self.out, 'summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        try:
            with open(os.path.join(os.path.dirname(self.out), 'journal.tsv'), 'a', encoding='utf-8') as f:
                f.write('\t'.join([time.strftime('%Y-%m-%d %H:%M:%S'), self.base[:12], f'{mins:.1f}', str(self.n_full),
                                   str(self.n_step), 'ok' if all_ok else 'fail',
                                   ' '.join(f'{i["name"]}@{i["sha"][:8]}={i["status"]}' for i in items), self.out]) + '\n')
        except OSError:
            pass
        if not keep:
            git(['worktree', 'remove', '--force', self.wt], self.repo, check=False)
        self.log(f'отчёт: {report}')
        return summary


FAIL_RE = [
    re.compile(r'^\s*(FAIL|×|✗)\s+(.+)$'),             # vitest
    re.compile(r'error TS\d+:.*'),                       # tsc
    re.compile(r'^\./.+$|^\s+\d+:\d+\s+Error:.*'),       # next lint
    re.compile(r'Type error:.*|Failed to compile.*'),    # next build
    re.compile(r'^\s*(FAIL|ERROR)\b.*'),                 # prepush / аудиты / прочее
]


def fail_detail(path: str) -> str:
    """Короткая причина из лога шага: первые упавшие тесты/ошибки, иначе последняя непустая строка."""
    if not path or not os.path.isfile(path):
        return '?'
    text = open(path, encoding='utf-8', errors='replace').read().splitlines()
    hits = []
    for rx in FAIL_RE:
        for l in text:
            m = rx.search(l)
            if m and l.strip() not in hits:
                hits.append(l.strip())
            if len(hits) >= 3:
                break
        if hits:
            break
    if not hits:
        hits = [l.strip() for l in text if l.strip()][-1:] or ['(пустой вывод)']
    return ' | '.join(h[:160] for h in hits[:3])


def out_dir(root: str) -> str:
    base = os.path.join(root, time.strftime('%H%M%S'))
    d, k = base, 1
    while os.path.exists(d):
        k += 1
        d = f'{base}-{k}'
    return d


def main(argv: list) -> int:
    if '--selftest' in argv:
        return selftest()
    refs, steps, base, out, slot, keep, pkgs = [], None, 'main', None, True, False, []
    it = iter(argv)
    for a in it:
        if a == '--steps':
            steps = next(it).split(',')
        elif a == '--base':
            base = next(it)
        elif a == '--out':
            out = next(it)
        elif a == '--no-slot':
            slot = False
        elif a == '--keep':
            keep = True
        elif a == '--pkg':
            pkgs.append(next(it))
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        elif a.startswith('-'):
            print(f'неизвестный ключ {a}', file=sys.stderr)
            return 2
        else:
            refs.append(a)
    if not refs:
        print(__doc__, file=sys.stderr)
        return 2
    known = [n for n, _ in STEPS]
    if steps and [s for s in steps if s not in known]:
        print(f'шаги: {",".join(known)}', file=sys.stderr)
        return 2
    sel = [(n, c) for n, c in STEPS if n in (steps or DEFAULT_STEPS)]
    if slot and os.environ.get('MQ_IN_SLOT') != '1':
        # весь сборщик — ОДИН слот heavy-slot: повтор шага, main и бисекция идут без новой очереди (12.11: 14-е место в очереди
        # на каждый шаг превращало 5 одиночных шагов в 5 ожиданий)
        os.environ['MQ_IN_SLOT'] = '1'
        os.execvp('bash', ['bash', HEAVY, 'mq-full'] + slot_args([n for n, _ in sel]) +
                  ['--', sys.executable, os.path.abspath(__file__)] + argv)
    if os.environ.get('MQ_IN_SLOT') == '1':
        slot = False                                     # уже внутри слота
    repo = git(['rev-parse', '--show-toplevel'], os.getcwd())
    os.makedirs(LOG_ROOT, exist_ok=True)
    out = out or out_dir(LOG_ROOT)
    try:
        s = Run(repo, refs, sel, base, out, slot, keep, pkgs).go()
    except RuntimeError as e:
        print(f'ошибка: {e}', file=sys.stderr)
        return 2
    print(open(os.path.join(out, 'report.md'), encoding='utf-8').read())
    return 0 if s['all_ok'] else 1


# ---------------------------------------------------------------- самопроверка
def selftest() -> int:
    sys.path.append(os.path.join(HERE, '..', 'scout'))
    import remlab_tmp
    bad = []

    def ok(cond, msg):
        print(('  ok  ' if cond else '  FAIL ') + msg)
        if not cond:
            bad.append(msg)

    def sh(cwd, *cmd):
        subprocess.run(list(cmd), cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ID})

    def commit(repo, branch, path, text, base='main'):
        if branch != 'main':
            sh(repo, 'git', 'checkout', '-q', '-B', branch, base)
        os.makedirs(os.path.dirname(os.path.join(repo, path)) or repo, exist_ok=True)
        with open(os.path.join(repo, path), 'w') as f:
            f.write(text)
        sh(repo, 'git', 'add', '-A')
        sh(repo, 'git', 'commit', '-qm', f'{branch}: {path}')
        sh(repo, 'git', 'checkout', '-q', 'main')

    # подставные шаги: «тест» падает, если в marks/ есть FAIL; «мигание» — первый вызов падает (счётчик вне репо)
    with remlab_tmp.tmpdir('mq-selftest-') as t:
        repo = os.path.join(t, 'repo')
        os.makedirs(repo)
        sh(repo, 'git', 'init', '-q', '-b', 'main')
        commit(repo, 'main', 'shared.txt', 'a\n')
        commit(repo, 'b1', 'marks/b1', 'ok\n')
        commit(repo, 'b2', 'marks/b2', 'FAIL tests/unit/b2.test.ts > ломается\n')
        commit(repo, 'b3', 'marks/b3', 'ok\n')
        commit(repo, 'c1', 'shared.txt', 'c1\n')
        commit(repo, 'c2', 'shared.txt', 'c2\n')
        test_cmd = 'if grep -rh FAIL marks 2>/dev/null; then exit 1; fi; echo passed'
        steps = [('lint', 'echo lint'), ('test', test_cmd)]

        def run(refs, st=steps, tag='x'):
            out = os.path.join(t, 'logs', tag)
            s = Run(repo, refs, st, 'main', out, False, False, [], say=lambda m: None).go()
            return s, {b['name']: b for b in s['branches']}, out

        s, b, out = run(['b1', 'b2', 'b3'], tag='culprit')
        ok(b['b2']['status'] == 'падает' and 'b2.test.ts' in b['b2']['detail'], f'виновная найдена: b2 → {b["b2"]}')
        ok(b['b1']['status'] == 'ok' and b['b3']['status'] == 'ok', 'b1, b3 — ok (проверены без b2)')
        ok(s['all_ok'] is False, 'шаг упал → итог FAIL (не «все ok»)')
        ok(s['full_runs'] == 2, f'полных прогонов 2 (набор, набор без виновной): {s["full_runs"]}')
        ok(s['step_runs'] <= 4, f'одиночных шагов ≤ 4 (повтор, main, бисекция): {s["step_runs"]}')
        rep = open(os.path.join(out, 'report.md')).read()
        ok('`b2` ·' in rep and 'падает: test:' in rep, 'отчёт: строка «ветка · SHA · падает: шаг: тест»')
        ok(os.path.isdir(os.path.join(out, 'wt')), 'при падении временная копия оставлена')
        ok(git(['rev-parse', 'main'], repo) == git(['rev-parse', 'main~0'], repo) and
           git(['symbolic-ref', '--short', 'HEAD'], repo) == 'main', 'main и основная копия на месте')
        main_before = git(['rev-parse', 'main'], repo)

        s, b, out = run(['b1', 'c1', 'c2', 'b3'], tag='conflict')
        ok(b['c2']['status'] == 'конфликт' and 'shared.txt' in b['c2']['detail'], f'конфликт c2 после c1: {b["c2"]}')
        ok(all(b[n]['status'] == 'ok' for n in ('b1', 'c1', 'b3')), 'остальные прошли')
        ok(s['all_ok'] is False and s['full_runs'] == 1, 'один полный прогон, итог «есть проблемы»')

        commit(repo, 'b4', 'marks/b4', 'ok\n', base='b1')      # ветка перебазирована на соседнюю b1 (как ff-цепочка директора)
        s, b, out = run(['b1', 'b4'], tag='rebased')
        mlog = open(os.path.join(out, 'mq.log'), encoding='utf-8').read()
        ok(s['all_ok'] and b['b4']['status'] == 'ok' and re.search(r'слита: b4 \S+ \(1 коммит', mlog),
           f'ветка поверх соседней: коммиты соседней второй раз не берутся: {b["b4"]}')

        # ложный зелёный (директор 12.11): исполнитель шагов оборвался, кода возврата у шага нет → не «ok»
        s, b, out = run(['b1'], st=[('lint', 'echo lint'), ('test', 'kill -TERM $$')], tag='killed')
        ok(s['all_ok'] is False and b['b1']['status'] != 'ok', f'шаг без кода возврата (обрыв) → FAIL: {b["b1"]}')
        s, b, out = run(['b1'], st=[('lint', 'echo lint'), ('test', 'exit 3')], tag='rc3')
        ok(s['all_ok'] is False and s['main_red'] and 'test' in s['main_red'], f'шаг rc=3 → FAIL: {s["main_red"]}')

        s, b, out = run(['b1', 'b3'], tag='green')
        ok(s['all_ok'] and s['full_runs'] == 1 and s['step_runs'] == 0, 'всё зелёное — один прогон')
        ok(not os.path.exists(os.path.join(out, 'wt')), 'зелёное — временная копия убрана')

        flag = os.path.join(t, 'flaky-once')
        fl = [('test', f'if [ ! -f {flag} ]; then touch {flag}; echo "FAIL мигает"; exit 1; fi; echo passed')]
        s, b, out = run(['b1', 'b3'], st=fl, tag='flaky')
        ok(s['all_ok'] and s['flaky'] == ['test'] and 'мигнул' in b['b1']['detail'], f'мигание не вешается: {s["flaky"]}')

        commit(repo, 'main', 'marks/main', 'FAIL main сломан\n')
        s, b, out = run(['b1', 'b3'], tag='mainred')
        ok(s['main_red'] and all(x['status'] == 'не проверена' for x in b.values()), f'main красный: {s["main_red"]}')

        sh(repo, 'git', 'reset', '-q', '--hard', main_before)
        b1 = git(['rev-parse', 'b1'], repo)
        commit(repo, 'b1', 'marks/b1-late', 'FAIL поздний коммит\n', base='b1')
        s, b, out = run([f'b1@{b1}'], tag='pinned')
        ok(b['b1']['status'] == 'ok' and b['b1']['moved'], 'ветка@sha: проверен ровно хеш, вершина ушла — пометка')

        sh(repo, 'git', 'cherry-pick', git(['rev-parse', 'b3'], repo))
        s, b, out = run(['b3'], tag='already')
        ok(b['b3']['status'] == 'ok' and b['b3']['detail'] == 'уже в main', 'перенесённая cherry-pick ветка — «уже в main»')
        wl = git(['worktree', 'list', '--porcelain'], repo)
        ok(wl.count('worktree ') >= 1, 'git worktree list читается')
    print('merge_queue selftest ' + ('ok' if not bad else f'FAIL ({len(bad)})'))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
