#!/usr/bin/env python3
"""Замер «с памятью / без» (модуль кита v1.9 `_optional/memory-eval`; пилот sup2 27.09).

Сценарий «как в работе»: одна сессия Claude Code = 10 вопросов подряд. Две копии кода из HEAD: с памятью
(.memory_bank + CLAUDE.md + .claude + копия авто-памяти) и без неё. Изоляция: без пользовательских настроек,
режим dontAsk, только Read/Grep/Glob, запреты чтения вне своей копии, уникальная метка сессии (холодный кэш на старте,
тёплый внутри сессии). Слепой судья в 2 прохода (прямой и обратный порядок), истина — код полной копии.

  python3 tools/memory-eval/eval.py --dry                 # собрать копии и настройки, без трат
  python3 tools/memory-eval/eval.py --probe               # + проба изоляции (~0,05 $)
  python3 tools/memory-eval/eval.py --run [--pairs 2] --questions tools/memory-eval/questions-ГГГГ-ММ-ДД.json
  --rabochee (с любым режимом): копии из рабочего дерева, а не из HEAD — когда работа не закоммичена.

Итог: таблица «$ / критичные / некритичные» и строка в .memory_bank/changelog/memory-eval.log (в git).
Цена прогона (--pairs 2): ~7 $ сессии + ~8 $ судья, ~15 мин. Вопросы для честного повтора — НОВЫЕ (см. README).
"""
import argparse, json, os, random, re, shutil, subprocess, sys, tempfile, time, uuid
from concurrent.futures import ThreadPoolExecutor

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
PROJECT = os.path.basename(REPO) or "project"
# Своя папка на каждый запуск (mkdtemp: не предсказуема, не пересекается с другим проектом того же имени) — удаляем
# только её и папки Claude Code, выведенные из неё; копии и выходы остаются для разбора, путь печатается.
# dir=/tmp явно: TMPDIR харнесса бывает под /tmp/claude-*, а его чтение запрещено (запреты ниже) — копии стали бы невидимы.
WORK, PROJ = "", {}  # задаются в main() после разбора аргументов (ошибка в аргументах не оставляет пустых папок)
HOME = os.path.expanduser("~")
SAN = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)  # как Claude Code называет папку проекта
AUTOMEM_SRC = f"{HOME}/.claude/projects/{SAN(REPO)}/memory"
PRICE = {"in": 4.0, "w5": 5.0, "w1h": 8.0, "rd": 0.20, "out": 20.0}  # Opus 5.5, $ за 1М (platform.claude.com, 27.09.2026)
MODEL, EFFORT = "opus[1m]", "high"
SUFFIX = " Отвечай по-русски, кратко (до 15 строк), с путями к файлам. Ничего не меняй."
LOG = f"{REPO}/.memory_bank/changelog/memory-eval.log"
LOG_HEAD = "date\tcommit\tpairs\tcost_mem\tcost_nomem\tcrit_mem\tcrit_nomem\tminor_mem\tminor_nomem\tquestions\tnote\n"


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def udalit(put):
    if os.path.isdir(put) and not os.path.islink(put):
        shutil.rmtree(put, ignore_errors=True)
    elif os.path.lexists(put):
        os.remove(put)


def zaprety_vne(koren, nuzhnye):
    """Запреты чтения на всё под `koren`, кроме путей `nuzhnye` и их предков (в предков — вглубь).
    Ловит то, что поимённые запреты пропускают: ссылки на проект в доме (`~/tamara`), соседние
    папки, файлы Claude Code, которых нет в списке."""
    out = []
    try:
        imena = sorted(os.listdir(koren))
    except OSError:
        return out
    for n in imena:
        put = os.path.join(koren, n)
        if any(x == put for x in nuzhnye):
            continue
        if any(x.startswith(put + "/") for x in nuzhnye) and os.path.isdir(put) and not os.path.islink(put):
            out += zaprety_vne(put, nuzhnye)
            continue
        out += [f"Read(/{put})", f"Read(/{put}/**)"]
    return out


def working_tree_files():
    """Файлы рабочего дерева: отслеживаемые и неигнорируемые новые (`git ls-files -co --exclude-standard`);
    удалённые с диска, но ещё отслеживаемые, пропускаются."""
    out = sh(["git", "-C", REPO, "ls-files", "-co", "--exclude-standard", "-z"])
    if out.returncode != 0:
        sys.exit(f"git ls-files: {out.stderr.strip()}")
    seen, files = set(), []
    for f in out.stdout.split("\0"):
        if f and f not in seen and os.path.lexists(os.path.join(REPO, f)):
            seen.add(f)
            files.append(f)
    return files


def build(rabochee=False):
    """Две копии кода из HEAD (или, с rabochee, из рабочего дерева); стенд и журналы замеров в копии не попадают
    (иначе утечка эталонов)."""
    commit = sh(["git", "-C", REPO, "rev-parse", "--short", "HEAD"]).stdout.strip()
    if rabochee:
        # Одна выгрузка рабочего дерева (репозиторий бывает сетевым) — вторая копия локально.
        os.makedirs(f"{WORK}/mem")
        src = subprocess.Popen(["tar", "-c", "-C", REPO, "--no-recursion", "--null", "-T", "-"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        dst = subprocess.Popen(["tar", "-x", "-C", f"{WORK}/mem"], stdin=src.stdout)
        src.stdout.close()
        src.stdin.write("\0".join(working_tree_files()).encode())
        src.stdin.close()
        if src.wait() != 0 or dst.wait() != 0:
            sys.exit("копирование рабочего дерева не удалось (tar)")
        shutil.copytree(f"{WORK}/mem", f"{WORK}/nomem", symlinks=True)
    else:
        for v in ("mem", "nomem"):
            os.makedirs(f"{WORK}/{v}")
            arch = subprocess.Popen(["git", "-C", REPO, "archive", "HEAD"], stdout=subprocess.PIPE)
            subprocess.run(["tar", "-x", "-C", f"{WORK}/{v}"], stdin=arch.stdout, check=True)
            arch.wait()
    for v in ("mem", "nomem"):
        for p in ["tools", ".memory_bank/changelog/verify-log.tsv"]:
            udalit(f"{WORK}/{v}/{p}")
        # Всё со словом memory-eval (журнал замеров, задания на замер с темами вопросов, сам стенд кита) — вон.
        for kor, dirs, fs in os.walk(f"{WORK}/{v}", topdown=True):
            for n in [d for d in dirs if "memory-eval" in d] + [f for f in fs if "memory-eval" in f]:
                udalit(os.path.join(kor, n))
            dirs[:] = [d for d in dirs if "memory-eval" not in d]
    # Без памяти: банк, правила, а также корневой _intake/ (блокнот сессии, ТЗ — тоже память проекта).
    for p in [".memory_bank", "CLAUDE.md", ".claude", "_optional", "AGENTS.md", "_intake"]:
        udalit(f"{WORK}/nomem/{p}")
    for v in ("mem", "nomem"):
        shutil.rmtree(PROJ[v], ignore_errors=True)
    os.makedirs(f"{PROJ['mem']}/memory")
    if os.path.isdir(AUTOMEM_SRC):
        for f in os.listdir(AUTOMEM_SRC):
            if f.endswith(".md"):
                shutil.copy(f"{AUTOMEM_SRC}/{f}", f"{PROJ['mem']}/memory/{f}")
    # Запреты чтения: весь дом пользователя, кроме нужного, /tmp вне стенда, другая копия.
    H = f"/{HOME}"
    parent = os.path.dirname(REPO)  # соседние проекты и сам репозиторий — не читать
    common = [f"Read(/{parent}/**)", f"Read({H}/.ssh/**)", f"Read({H}/.codex/**)", f"Read({H}/.config/**)", f"Read({H}/.cache/**)",
              f"Read({H}/.local/**)", "Read(//tmp/claude-*/**)", "Read(//tmp/mb-precompact-*/**)",
              f"Read({H}/.claude/projects/-home-*/**)", f"Read({H}/.claude/projects/-tmp-claude-*/**)",
              f"Read(//{WORK.lstrip('/')}/out/**)"]
    for ext in ("md", "log", "py", "json", "txt", "sh", "ts"):
        common.append(f"Read(//tmp/*.{ext})")
    for d in ["backups", "cache", "file-history", "history.jsonl", "ide", "jobs", "memory", "paste-cache", "plans", "plugins",
              "session-env", "sessions", "shell-snapshots", "skills", "state", "tasks", "uploads", "daemon.log", "stats-cache.json"]:
        common += [f"Read({H}/.claude/{d})", f"Read({H}/.claude/{d}/**)"]
    # Всё прочее в /home и /tmp на момент сборки — кроме стенда и папок Claude Code обеих копий.
    nuzhnye = [WORK, PROJ["mem"], PROJ["nomem"]]
    for koren in ("/home", HOME, "/tmp"):
        common += [z for z in zaprety_vne(koren, nuzhnye) if z not in common]
    os.makedirs(f"{WORK}/out", exist_ok=True)
    open(f"{WORK}/out/canary.txt", "w").write("x")  # проба: существующий файл вне копии должен дать ОТКАЗ
    for v, other in (("mem", "nomem"), ("nomem", "mem")):
        deny = common + [f"Read(//{WORK.lstrip('/')}/{other}/**)", f"Read({H}/.claude/projects/{SAN(f'{WORK}/{other}')}/**)"]
        json.dump({"permissions": {"deny": deny}}, open(f"{WORK}/deny-{v}.json", "w"))
    return f"{commit}+рабочее" if rabochee else commit


def claude(v, prompt, out, session=None, resume=False, nonce="", max_turns=60):
    env = {k: val for k, val in os.environ.items() if not k.startswith("CLAUDE")}
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL, "--effort", EFFORT,
           "--setting-sources", "project,local", "--settings", f"{WORK}/deny-{v}.json", "--permission-mode", "dontAsk",
           "--tools", "Read,Grep,Glob", "--append-system-prompt", f"Служебная метка (не упоминать): {nonce}",
           "--max-turns", str(max_turns), "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    if session:
        cmd += ["--resume", session] if resume else ["--session-id", session]
    with open(out, "w") as fo:
        subprocess.run(cmd, cwd=f"{WORK}/{v}", env=env, stdout=fo, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=1500)
    try:
        return json.load(open(out))
    except Exception:
        return None


def probe():
    """Изоляция: своя копия читается, чужое — нет."""
    ok, oshibka = True, ""
    for v, other in (("mem", "nomem"), ("nomem", "mem")):
        own = next((f for f in sorted(os.listdir(f"{WORK}/{v}")) if os.path.isfile(f"{WORK}/{v}/{f}")), "README.md")
        tests = [(f"./{own}", True), (f"{WORK}/{other}/{own}", False), (f"{REPO}/.git/HEAD", False),
                 (f"{WORK}/out/canary.txt", False)]
        prompt = "Проверка доступа. Для каждого пути сделай Read и напиши номер и ДОСТУПНО или ОТКАЗ:\n" + "\n".join(f"{i + 1}) {p}" for i, (p, _) in enumerate(tests))
        d = claude(v, prompt, f"{WORK}/out/probe-{v}.json", nonce=str(uuid.uuid4()), max_turns=10) or {}
        res = d.get("result", "")
        if not d or d.get("is_error"):
            # Сбой вызова (лимит учётки, сеть, вход) — изоляция не проверена, а не нарушена.
            oshibka = f"{v}: {d.get('api_error') or d.get('subtype') or 'нет ответа claude'} — {res or '-'}"
            print(f"  ⚠ проба {oshibka}")
            break
        for i, (p, want) in enumerate(tests):
            got = re.search(rf"{i + 1}\)\s*(ДОСТУПНО|ОТКАЗ)", res)
            if not got or (got.group(1) == "ДОСТУПНО") != want:
                ok = False
                print(f"  ⚠ {v}: {p} — ожидалось {'доступ' if want else 'отказ'}, получено {got.group(1) if got else '?'}")
    if oshibka:
        print("изоляция: НЕ ПРОВЕРЕНА — вызов claude не удался (выше), прогон не запускать")
        return None
    print("изоляция:", "OK" if ok else "НАРУШЕНА — прогон не запускать")
    return ok


def cost_of_session(v, sid):
    p = f"{PROJ[v]}/{sid}.jsonl"
    calls = {}
    for line in open(p, encoding="utf-8", errors="replace"):
        o = json.loads(line)
        m = o.get("message") or {}
        if o.get("type") == "assistant" and isinstance(m, dict) and m.get("id"):
            u = m.get("usage") or {}
            if m["id"] not in calls or (u.get("output_tokens") or 0) > (calls[m["id"]].get("output_tokens") or 0):
                calls[m["id"]] = u
    tot = 0.0
    for u in calls.values():
        cc = u.get("cache_creation") or {}
        w1 = cc.get("ephemeral_1h_input_tokens", u.get("cache_creation_input_tokens") or 0)
        w5 = cc.get("ephemeral_5m_input_tokens", 0)
        tot += ((u.get("input_tokens") or 0) * PRICE["in"] + w5 * PRICE["w5"] + w1 * PRICE["w1h"]
                + (u.get("cache_read_input_tokens") or 0) * PRICE["rd"] + (u.get("output_tokens") or 0) * PRICE["out"]) / 1e6
    return tot, p


def run_session(v, pair, qs, order):
    sid, nonce = str(uuid.uuid4()), str(uuid.uuid4())
    answers, fails = {}, 0
    for i, qid in enumerate(order, 1):
        q = next(x for x in qs if x["id"] == qid)
        for attempt in range(3):
            d = claude(v, q["q"] + SUFFIX, f"{WORK}/out/{v}.{pair}.{i:02d}.json", session=sid, resume=(i > 1 or attempt > 0), nonce=nonce)
            if d and not d.get("is_error") and d.get("subtype") == "success" and d.get("result", "").strip():
                answers[qid] = d["result"]
                break
            fails += 1
            time.sleep(20)
    cost, path = cost_of_session(v, sid)
    return {"v": v, "pair": pair, "sid": sid, "answers": answers, "cost": cost, "fails": fails, "transcript": path}


def leaks(sessions):
    """Чтения вне своей копии + строки памяти, которых нет в копии без памяти, в ответах без памяти."""
    found = []
    for s in sessions:
        own = f"{WORK}/{s['v']}"
        for line in open(s["transcript"], encoding="utf-8", errors="replace"):
            o = json.loads(line)
            m = o.get("message") or {}
            if o.get("type") == "assistant" and isinstance(m, dict):
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        path = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("path") or ""
                        if not path:
                            continue
                        full = os.path.normpath(path if os.path.isabs(path) else os.path.join(own, path))  # ../ — тоже выход
                        mem_dir = f"{PROJ[s['v']]}/memory"
                        if not (full == own or full.startswith(own + "/") or full == mem_dir or full.startswith(mem_dir + "/")):
                            found.append(f"{s['v']}{s['pair']}: чтение {path}")
    canary = canaries()
    for s in sessions:
        if s["v"] == "nomem":
            found += [f"маяк «{c}» в ответе без памяти ({q})" for q, t in s["answers"].items() for c in canary if c in t]
    return found


def canaries(limit=40):
    """Строки, которые есть в памяти копии mem, но которых нет в коде копии nomem: их появление в ответе без
    памяти — утечка. Берём `в обратных кавычках` токены длиной от 8 символов без пробелов."""
    toks = []
    mem_files = [f"{WORK}/mem/CLAUDE.md"]
    for d in (f"{WORK}/mem/.memory_bank/core", f"{WORK}/mem/.claude/rules"):
        if os.path.isdir(d):
            mem_files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".md")]
    for f in mem_files:
        if not os.path.exists(f):
            continue
        for m in re.finditer(r"`([^`\s]{8,60})`", open(f, encoding="utf-8", errors="replace").read()):
            if m.group(1) not in toks:
                toks.append(m.group(1))
    out = []
    for tok in toks:
        if sh(["grep", "-rqF", "--", tok, f"{WORK}/nomem"]).returncode != 0:
            out.append(tok)
        if len(out) >= limit:
            break
    return out


REDACT = [(r"`?\.?memory_bank/[^\s`),;]+`?", "[документ проекта]"), (r"`?\.claude/(rules|agents|skills)/[^\s`),;]+`?", "[документ проекта]"),
          (r"`?(core|domain|decisions|reference|completed_plans|changelog)/[\w\-./]+\.md`?", "[документ проекта]"),
          (r"`?CLAUDE\.md`?|`?MEMORY\.md`?", "[документ проекта]"), (r"(личн\w*|авто)[-\s]?памят\w*", "заметки"),
          (r"[^.\n]*в этой (копии|папке)[^.\n]*[.\n]", ""), (r"[^.\n]*(в репозитории|в проекте|в папке)[^.\n]*(нет|отсутств)[^.\n]*[.\n]", "")]

JUDGE = """Ты — строгий проверяющий. Оцени ответы ассистентов на вопрос о проекте в текущей папке. Проверяй утверждения по КОДУ
(Read/Grep/Glob); код — истина, документы проекта могут отставать. Не верь ответам на слово.

ВОПРОС: {q}

ЭТАЛОН (подсказка, сверена с кодом на момент составления; при расхождении прав код):
{truth}
{crit}
Ответы (порядок и метки случайны, авторство скрыто):
{answers}

Для КАЖДОГО ответа: errors — фактические ошибки [{{"claim": "...", "severity": "minor|major|dangerous"}}] (minor — неточность без
последствий; major — неверный факт, ведущий к неправильному действию; dangerous — опасный совет или пропуск запрета, ведущий к
вреду); missed_critical — какие пункты из списка КРИТИЧНЫХ не названы (нет списка — пусто).
Верни ТОЛЬКО JSON: {{"answers": [{{"label": "A", "errors": [], "missed_critical": []}}, ...]}}"""


def judge(q, sessions, pas):
    items = []
    for s in sessions:
        t = s["answers"].get(q["id"], "(нет ответа)")
        for rx, rep in REDACT:
            t = re.sub(rx, rep, t, flags=re.I)
        items.append({"v": s["v"], "pair": s["pair"], "text": t})
    random.Random(q["id"]).shuffle(items)
    if pas == 2:
        items = items[::-1]
    labels = "ABCDEFGH"
    key = {labels[i]: (it["v"], it["pair"]) for i, it in enumerate(items)}
    prompt = JUDGE.format(q=q["q"], truth="\n".join(f"{i + 1}. {x}" for i, x in enumerate(q["truth"])),
                          crit=("КРИТИЧНЫЕ ПУНКТЫ: " + "; ".join(q["critical"]) + "\n") if q.get("critical") else "",
                          answers="\n\n".join(f"=== Ответ {labels[i]} ===\n{it['text']}" for i, it in enumerate(items)))
    for attempt in range(3):
        # копия без памяти: судья сверяет по коду и не видит память, которую оценивает (иначе смещение в её пользу)
        d = claude("nomem", prompt, f"{WORK}/out/judge.{q['id']}.p{pas}.json", nonce=str(uuid.uuid4()), max_turns=90) or {}
        try:
            parsed = json.loads(re.search(r"\{[\s\S]*\}", d.get("result", "")).group(0))
            assert len(parsed["answers"]) == len(items)
            return key, parsed, d.get("total_cost_usd") or 0
        except Exception:
            time.sleep(15)
    return key, None, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--pairs", type=int, default=2)
    ap.add_argument("--questions", required=True, help="JSON с вопросами (формат — questions.example.json)")
    ap.add_argument("--note", default="")
    ap.add_argument("--rabochee", action="store_true",
                    help="копии из рабочего дерева (отслеживаемые + неигнорируемые новые), а не из HEAD; в журнал — <коммит>+рабочее")
    a = ap.parse_args()
    if not (a.dry or a.probe or a.run):
        ap.error("нужен режим: --dry (без трат), --probe (~0,05 $) или --run (полный прогон, ~15 $)")
    qs = json.load(open(a.questions, encoding="utf-8"))
    global WORK, PROJ
    WORK = tempfile.mkdtemp(prefix=f"memory-eval-{PROJECT}-", dir="/tmp" if os.path.isdir("/tmp") else None)
    PROJ = {v: f"{HOME}/.claude/projects/{SAN(f'{WORK}/{v}')}" for v in ("mem", "nomem")}
    commit = build(a.rabochee)
    print(f"копии кода из {commit}: {WORK}/mem, {WORK}/nomem; вопросов {len(qs)} ({os.path.basename(a.questions)})")
    if a.dry:
        print(f"сухой прогон: копии и запреты готовы; полный прогон --run --pairs {a.pairs} ≈ {7 * a.pairs / 2:.0f} $ + судья ≈ 8 $")
        return
    izol = probe()
    if not izol:
        sys.exit(1 if izol is False else 3)
    if a.probe:
        return
    order = [q["id"] for q in qs]
    random.Random(7).shuffle(order)
    jobs = [(v, p) for p in range(1, a.pairs + 1) for v in ("mem", "nomem")]
    with ThreadPoolExecutor(4) as ex:
        sessions = list(ex.map(lambda j: run_session(j[0], j[1], qs, order), jobs))
    lk = leaks(sessions)
    with ThreadPoolExecutor(4) as ex:
        verdicts = list(ex.map(lambda qp: (qp[0], qp[1], *judge(qp[0], sessions, qp[1])), [(q, p) for q in qs for p in (1, 2)]))
    agg = {v: {"crit": 0.0, "minor": 0.0} for v in ("mem", "nomem")}
    jcost = 0.0
    for q, pas, key, parsed, c in verdicts:
        jcost += c
        if not parsed:
            print("⚠ судья не ответил:", q["id"], pas)
            continue
        for x in parsed["answers"]:
            v, _ = key[x["label"]]
            sev = [e.get("severity") for e in x.get("errors", [])]
            agg[v]["crit"] += (sev.count("major") + sev.count("dangerous") + (len(x.get("missed_critical", [])) if q.get("critical") else 0)) / 2 / a.pairs
            agg[v]["minor"] += sev.count("minor") / 2 / a.pairs
    cost = {v: sum(s["cost"] for s in sessions if s["v"] == v) / a.pairs for v in ("mem", "nomem")}
    fails = sum(s["fails"] for s in sessions)
    print(f"\n{'':22}{'с памятью':>12}{'без памяти':>12}")
    print(f"{'$ за сессию (10 вопр.)':22}{cost['mem']:12.2f}{cost['nomem']:12.2f}")
    print(f"{'критичных ошибок':22}{agg['mem']['crit']:12.1f}{agg['nomem']['crit']:12.1f}")
    print(f"{'некритичных ошибок':22}{agg['mem']['minor']:12.1f}{agg['nomem']['minor']:12.1f}")
    print(f"судья {jcost:.2f} $; сбоев/повторов {fails}; утечки: {lk or 'нет'}")
    if not os.path.exists(LOG):
        open(LOG, "w").write(LOG_HEAD)
    note = (a.note + ("; УТЕЧКИ" if lk else "")).strip("; ")
    open(LOG, "a").write("\t".join(map(str, [time.strftime("%Y-%m-%d"), commit, a.pairs, f"{cost['mem']:.2f}", f"{cost['nomem']:.2f}",
                                                f"{agg['mem']['crit']:.1f}", f"{agg['nomem']['crit']:.1f}", f"{agg['mem']['minor']:.1f}",
                                                f"{agg['nomem']['minor']:.1f}", os.path.basename(a.questions), note])) + "\n")
    print("строка записана в .memory_bank/changelog/memory-eval.log — сводка: node tools/memory-health.mjs")


main()
