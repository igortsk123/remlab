#!/usr/bin/env python3
"""Срез расхода токенов по журналам Claude Code: сессии, часы, субагенты. Только чтение."""
import glob, json, os, sys, collections, datetime as dt

# Журналы remlab: основная копия + worktree фоновых сессий исполнителя (claude --bg → .claude/worktrees/<имя>).
# Источник скрипта — сессия tamara 18.10 (совет по расходу токенов); перенесён в remlab по слову владельца 18.10.
# Запуск: python3 tools/ops/tokstat.py [смещение часового пояса, по умолчанию +3]
P = os.path.expanduser("~/.claude/projects/-home-pakar-igor-remlab")
DIRS = [P] + sorted(glob.glob(P + "--claude-worktrees-*"))
# относительные веса цены (ввод=1): вывод ×5, запись кэша ×1.25, чтение кэша ×0.1
W = dict(inp=1.0, out=5.0, cw=1.25, cr=0.1)
TZ = dt.timezone(dt.timedelta(hours=int(sys.argv[1]) if len(sys.argv) > 1 else 3))

def rows(path):
    seen = set()
    with open(path, errors="ignore") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            if not u or d.get("type") != "assistant":
                continue
            key = (m.get("id"), d.get("requestId"))
            if key in seen:
                continue
            seen.add(key)
            ts = d.get("timestamp")
            if not ts:
                continue
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
            yield t, m.get("model", "?"), dict(
                inp=u.get("input_tokens", 0) or 0, out=u.get("output_tokens", 0) or 0,
                cw=u.get("cache_creation_input_tokens", 0) or 0, cr=u.get("cache_read_input_tokens", 0) or 0)

def w(a): return sum(a[k] * W[k] for k in W)
def z(): return collections.Counter()

sess = {}
for D in DIRS:
    for f in glob.glob(f"{D}/*.jsonl"):
        sid = os.path.basename(f)[:8]
        # worktree-сессии (исполнитель на задачу) помечаем «wt», чтобы ведущий и исполнители были видны раздельно
        sess[(sid, "main" if D == P else "wt")] = list(rows(f))
        for sf in glob.glob(f"{D}/{os.path.basename(f)[:-6]}/subagents/*.jsonl"):
            sess.setdefault((sid, "sub"), []).extend(rows(sf))

M = 1e6
print("=== По сессиям (M токенов; «вес» = в эквиваленте ввода) ===")
print(f"{'сессия':9}{'кто':5}{'вызов':>7}{'ввод':>7}{'вывод':>7}{'кэшЗап':>8}{'кэшЧт':>8}{'конт/выз':>9}{'вес':>8}  период  модели")
tot = z(); hours = collections.defaultdict(z); hcalls = collections.Counter()
for (sid, who), R in sorted(sess.items(), key=lambda x: min((r[0] for r in x[1]), default=dt.datetime.max.replace(tzinfo=TZ))):
    if not R: continue
    a = z(); models = collections.Counter()
    for t, mod, u in R:
        a.update(u); models[mod] += 1
        hours[(sid, t.strftime("%m-%d %H"))].update(u); hcalls[(sid, t.strftime("%m-%d %H"))] += 1
    tot.update(a)
    ctx = (a["inp"] + a["cw"] + a["cr"]) / len(R)
    ts = sorted(r[0] for r in R)
    print(f"{sid:9}{who:5}{len(R):7}{a['inp']/M:7.2f}{a['out']/M:7.2f}{a['cw']/M:8.1f}{a['cr']/M:8.1f}{ctx/1000:8.0f}k{w(a)/M:8.1f}  "
          f"{ts[0]:%m-%d %H:%M}…{ts[-1]:%m-%d %H:%M}  " + ", ".join(f"{k.replace('claude-','')}:{v}" for k, v in models.most_common(3)))
print(f"\nИТОГО вес {w(tot)/M:.1f}M; доли веса: " + " · ".join(f"{k} {tot[k]*W[k]/w(tot)*100:.0f}%" for k in W))

print("\n=== Активные часы: топ-25 по весу (сессия+субагенты) ===")
print(f"{'сессия':9}{'час':10}{'вызов':>6}{'вывод k':>8}{'кэшЗап M':>9}{'кэшЧт M':>8}{'конт/выз':>9}{'вес M':>7}")
for (sid, h), a in sorted(hours.items(), key=lambda x: -w(x[1]))[:25]:
    n = hcalls[(sid, h)]
    print(f"{sid:9}{h:10}{n:6}{a['out']/1000:8.0f}{a['cw']/M:9.2f}{a['cr']/M:8.1f}{(a['inp']+a['cw']+a['cr'])/n/1000:8.0f}k{w(a)/M:7.1f}")

act = [w(a) for a in hours.values()]
act.sort()
print(f"\nАктивных часов-сессий: {len(act)}; медиана веса/час {act[len(act)//2]/M:.1f}M, 90-й перц. {act[int(len(act)*.9)]/M:.1f}M")

print("\n=== По дням (все сессии) ===")
days = collections.defaultdict(z)
for (sid, h), a in hours.items(): days[h[:5]].update(a)
for d, a in sorted(days.items()):
    print(f"{d}  вес {w(a)/M:6.1f}M  кэшЧт {a['cr']/M:6.1f}M  кэшЗап {a['cw']/M:5.1f}M  вывод {a['out']/M:5.2f}M")
