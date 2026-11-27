#!/usr/bin/env python3
"""Поиск по банку одной командой (T-20261127-175/7, совет Fable 27 § 3 п. 7): «что по этой теме уже пробовали и чем кончилось» — ДО того, как предлагать способ или
звать советника. Причина: 27.11 советник предложил закрытое (нейросеть-художник = StableGen до 20.11, ADR-0455); 19.11 ключ RunPod спросили повторно — банк был, не сверили.

Что ищет: `.memory_bank/**/*.md` (решения, уроки, core, правила, планы с хронологией проб, архив, журнал; `_secrets/` НЕ читается никогда, `_intake/` — только
`session-scratch.md` и `owner-questions.md`, остальное — `--with-intake`) и авто-память Claude этого проекта (`~/.claude/projects/<проект>/memory`, `--no-auto` — без неё).
Как: слова запроса сокращаются до основы (нейросеть/нейросети), место — окно из 6 строк, где встречается не меньше ~2/3 слов запроса (одно слово — само слово);
места ранжируются по числу слов и близости; рядом с каждым — ближайший заголовок (ADR-…, урок, P-…) и пометка «закрытое?», если в окне есть слова
«отброшено / опровергнуто / не помогло / не сработало / снято / закрыли / остановлена…» — то, что НЕ надо предлагать заново. Места с такой пометкой идут В ВЫДАЧЕ ПЕРВЫМИ
(иначе решающая запись «закрыли» тонет за чертой --limit); не всё показано — последней строкой «ещё N мест не показано». Без зависимостей (python 3.9+).

Запуск: `python3 tools/ops/bank_search.py "нейросеть художник" ["второй запрос" …] [--block] [--json] [--limit 12] [--per-file 2] [--root .] [--with-intake] [--no-auto]`
`--block` — готовый раздел «Что уже пробовали (поиск по банку)» для файла вопроса советнику (шаблон — `guides/sovetnik-vopros-shablon.md`; проверка — `question_lint.py`).
Пустой результат — тоже результат: строка «найдено 0» остаётся в блоке (проверено поиском, а не «не искали»). Тест: `python -m pytest tools/ops/tests/test_bank_search.py -q`."""
from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import subprocess
import sys
from pathlib import Path

WINDOW = 6                                                                  # строк в окне «места»
STOP = {"как", "что", "для", "это", "или", "при", "про", "над", "под", "без", "чем", "его", "она", "они", "все", "еще", "уже", "так", "был", "быть",
        "the", "and", "for", "with"}
CLOSED = re.compile(r"отброш|опроверг|не помог|не сработал|не сработ|хуже\b|снят[оаы]?\b|закрыт|закрыл|остановлен|не вливает|отменен|отменён|не лечим|провал|не годится|заменен|заменён|superseded|не берем|не берём|нельзя", re.I)
HEAD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
ID = re.compile(r"(ADR-\d{3,4}|урок\s+\d+|P-\d{3}|T-\d{8}-\d+(?:/\d+)?)", re.I)
SKIP_PARTS = {"_secrets", "node_modules", ".git", "__pycache__"}
INTAKE_KEEP = {"session-scratch.md", "owner-questions.md"}
WEIGHT = {"archive": 0.6, "changelog": 0.6, "completed_plans": 0.8, "_intake": 0.9,                  # канон (решения, уроки, core, правила) — выше блокнота и архива при равенстве
          "decisions": 1.15, "lessons": 1.1, "core": 1.1, "rules": 1.1}


def norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def stems(query: str) -> list[str]:
    out: list[str] = []
    for w in re.findall(r"[0-9a-zа-яё]+", norm(query)):
        if w in STOP or (len(w) < 3 and not any(c.isdigit() for c in w)) or len(w) < 2:
            continue
        s = w if len(w) <= 4 else (w[:4] if len(w) == 5 else w[:5])         # основа: окончания и суффиксы (нейросеть/нейросети, художник/художника) не мешают
        if s not in out:
            out.append(s)
    return out


def main_root(root: Path) -> Path:
    """Корень основной копии (у worktree авто-память лежит по пути основной)."""
    try:
        d = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True, text=True, timeout=10).stdout.strip()
        if d:
            return (root / d).resolve().parent
    except (OSError, subprocess.SubprocessError):
        pass
    return root


def auto_memory_dir(root: Path) -> Path | None:
    for r in (root, main_root(root)):
        p = Path.home() / ".claude" / "projects" / str(r.resolve()).replace("/", "-") / "memory"
        if p.is_dir():
            return p
    return None


def corpus(root: Path, with_intake: bool, auto: bool, auto_dir: Path | None) -> list[tuple[Path, str]]:
    """[(файл, метка источника)] — метка в выводе: путь от корня репо или `авто-память/…`."""
    files: list[tuple[Path, str]] = []
    bank = root / ".memory_bank"
    for p in sorted(bank.rglob("*.md")):
        rel = p.relative_to(root)
        parts = set(rel.parts)
        if parts & SKIP_PARTS:
            continue
        if "_intake" in parts and not with_intake and p.name not in INTAKE_KEEP:
            continue
        files.append((p, str(rel)))
    if auto:
        d = auto_dir or auto_memory_dir(root)
        if d and d.is_dir():
            files += [(p, "авто-память/" + p.name) for p in sorted(d.glob("*.md"))]
    return files


def weight(label: str) -> float:
    for k, w in WEIGHT.items():
        if f"/{k}/" in label or label.startswith(k):
            return w
    return 1.0


def search_file(path: Path, label: str, st: list[str], need: int) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return []
    low = [norm(x) for x in lines]
    hits_by_line = [frozenset(i for i, s in enumerate(st) if s in l) for l in low]
    if not any(hits_by_line):
        return []
    found: list[dict] = []
    n = len(lines)
    for i in range(n):
        if not hits_by_line[i]:
            continue
        j = min(n, i + WINDOW)
        uni = frozenset().union(*hits_by_line[i:j])
        if len(uni) < need:
            continue
        cnt = sum(1 for k in range(i, j) if hits_by_line[k])
        best = max(range(i, j), key=lambda k: (len(hits_by_line[k]), -k))
        found.append({"lo": i, "hi": j, "line": best, "words": len(uni), "lines": cnt, "score": (len(uni) * 10 + cnt) * weight(label)})
    found.sort(key=lambda h: -h["score"])
    keep: list[dict] = []
    for h in found:                                                          # соседние окна одного места — одно место
        if all(h["lo"] >= k["hi"] or h["hi"] <= k["lo"] for k in keep):
            keep.append(h)
    out = []
    for h in keep:
        head = ""
        for k in range(h["line"], -1, -1):
            m = HEAD.match(lines[k])
            if m:
                head = m.group(1).strip()
                break
        text = "\n".join(lines[h["lo"]:h["hi"]])
        ids = list(dict.fromkeys(re.sub(r"\s+", " ", x) for x in ID.findall(head or lines[h["line"]])))
        closed = sorted({m.group(0).lower() for m in CLOSED.finditer(text)})
        snip = re.sub(r"\s+", " ", lines[h["line"]]).strip()
        if len(snip) > 220:
            snip = snip[:217] + "…"
        out.append({"file": label, "line": h["line"] + 1, "heading": head[:100], "ids": ids[:3], "snippet": snip, "closed": closed[:4],
                    "words": h["words"], "of": len(st), "score": round(h["score"], 1)})
    return out


def run_query(query: str, root: Path, with_intake: bool, auto: bool, auto_dir: Path | None, limit: int, per_file: int) -> dict:
    st = stems(query)
    if not st:
        raise ValueError(f"в запросе «{query}» нет слов для поиска (короче 3 букв и стоп-слова не ищутся)")
    need = 1 if len(st) == 1 else max(2, math.ceil(len(st) * 2 / 3))
    files = corpus(root, with_intake, auto, auto_dir)
    allh: list[dict] = []
    for p, label in files:
        allh += search_file(p, label, st, need)
    allh.sort(key=lambda h: (not h["closed"], -h["score"], h["file"], h["line"]))   # места с пометкой «закрытое?» — первыми: решающая запись «ЗАКРЫЛИ» не должна остаться за чертой limit (Fable 27, ответ 24)
    shown: list[dict] = []
    per: dict[str, int] = {}
    for h in allh:
        if per.get(h["file"], 0) >= per_file:
            continue
        per[h["file"]] = per.get(h["file"], 0) + 1
        shown.append(h)
        if len(shown) >= limit:
            break
    return {"query": query, "stems": st, "need": need, "scanned": len(files), "total_places": len(allh), "total_files": len({h["file"] for h in allh}),
            "shown": shown, "date": datetime.date.today().isoformat()}


def marker(r: dict) -> str:
    """Строка-метка поиска: её требует `question_lint.py` — запрос, число мест, дата."""
    return (f"Поиск по банку: «{r['query']}» · найдено {r['total_places']} мест в {r['total_files']} файлах (просмотрено {r['scanned']}) · {r['date']} · "
            f"`python3 tools/ops/bank_search.py \"{r['query']}\"`")


def bullets(r: dict) -> list[str]:
    if not r["shown"]:
        return ["- в банке по этой теме записей нет (проверено поиском; слова: " + ", ".join(r["stems"]) + ")"]
    out = []
    for h in r["shown"]:
        who = (" · " + ", ".join(h["ids"])) if h["ids"] else ""
        flag = (" ⚠ закрытое?: " + ", ".join(h["closed"])) if h["closed"] else ""
        head = f" ({h['heading']})" if h["heading"] else ""
        out.append(f"- `{h['file']}:{h['line']}`{head}{who} — «{h['snippet']}»{flag}")
    hidden = r["total_places"] - len(r["shown"])
    if hidden > 0:                                                           # показано не всё — молча не обрезаем: «искал, не нашёл» было бы ложным
        out.append(f"- …ещё {hidden} мест не показано (--limit {len(r['shown'])} и --per-file ограничивают; больше — `--limit 50 --per-file 5` или уточни слова запроса)")
    return out


def render(results: list[dict], block: bool) -> str:
    out: list[str] = []
    if block:
        out.append("## Что уже пробовали (поиск по банку)")
        out.append("")
    for r in results:
        out.append(marker(r))
        out += bullets(r)
        out.append("")
    if block:
        out.append("Отметки ⚠ — в тексте места есть слова закрытого («отброшено», «не помогло» …): прочитать место целиком, не предлагать заново без нового довода.")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="поиск по банку памяти: что уже пробовали (T-20261127-175/7)")
    ap.add_argument("query", nargs="+", help="запрос (несколько — несколько отдельных поисков)")
    ap.add_argument("--root", default=None, help="корень репо (по умолчанию — где лежит скрипт)")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--per-file", type=int, default=2)
    ap.add_argument("--block", action="store_true", help="раздел «Что уже пробовали (поиск по банку)» для файла вопроса советнику")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-intake", action="store_true", help="искать и по брифам/черновикам _intake/")
    ap.add_argument("--no-auto", action="store_true", help="без авто-памяти Claude")
    ap.add_argument("--auto-memory", default=None, help="папка авто-памяти (по умолчанию — по пути проекта)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[2]
    if not (root / ".memory_bank").is_dir():
        print(f"нет {root}/.memory_bank", file=sys.stderr)
        return 2
    auto_dir = Path(a.auto_memory) if a.auto_memory else None
    try:
        results = [run_query(q, root, a.with_intake, not a.no_auto, auto_dir, a.limit, a.per_file) for q in a.query]
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(results, ensure_ascii=False, indent=1) if a.json else render(results, a.block), end="" if not a.json else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
