#!/usr/bin/env python3
"""Сверка политики расхода токенов (сжатие контекста) по проектам и машинам: одинаково ли везде.

Читает только нужные ключи (`modelSettings.<модель>.autoCompactWindow`, `idleCompaction`, переменные `env` со словом
COMPACT) из `~/.claude/settings.json` каждой машины (своя — напрямую, другие — по ssh, разбор на той стороне: в канал
идут только эти ключи, прочее содержимое настроек — нет) и из `.claude/settings.json` + `.claude/settings.local.json`
каждого проекта (папки проектов общие — sshfs с pakardev, читаются здесь). Печатает две таблицы: источники и итог
«проект/машина» по старшинству Claude Code (settings.local.json > settings.json проекта > ~/.claude/settings.json).
Итог «одинаково везде» или список расхождений; код 0 — одинаково, 1 — расходится, 2 — какую-то машину не прочитать.

    python3 tools/tokeny/sverka_nastroek.py
    TOKENY_MASHINY_SSH="pakardev=pakar@192.168.0.44 algor=algor@192.168.0.33 common=common@192.168.0.45" \\
    TOKENY_SVERKA_PROEKTY="remlab tamara sup2-repo" python3 tools/tokeny/sverka_nastroek.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

KORNI = Path(os.environ.get("TOKENY_PROEKTY") or "/home/pakar/igor")
MASHINY = os.environ.get("TOKENY_MASHINY_SSH") or (
    "pakardev=pakar@192.168.0.44 algor=algor@192.168.0.33 common=common@192.168.0.45")
PROEKTY = (os.environ.get("TOKENY_SVERKA_PROEKTY") or "remlab tamara sup2-repo").split()
MODELI = ("claude-opus-5-5", "claude-fable-5-1")
KOLONKI = (*(f"окно {m.removeprefix('claude-')}" for m in MODELI), "idleCompaction", "env")

# Выполняется и на удалённой машине (python3 - по ssh): печатает только нужные ключи, без остального файла.
IZVLECH = r'''
import json, sys
from pathlib import Path
put = Path(sys.argv[1]).expanduser()
try:
    d = json.loads(put.read_text(encoding="utf-8"))
except FileNotFoundError:
    print(json.dumps({"net": True})); sys.exit(0)
except ValueError as e:
    print(json.dumps({"oshibka": f"не JSON: {e}"})); sys.exit(0)
ms = d.get("modelSettings") if isinstance(d.get("modelSettings"), dict) else {}
env = d.get("env") if isinstance(d.get("env"), dict) else {}
print(json.dumps({"okno": {m: (ms.get(m) or {}).get("autoCompactWindow") for m in sys.argv[2:]},
                  "idle": d.get("idleCompaction"),
                  "env": {k: v for k, v in env.items() if "COMPACT" in k}}))
'''


def prochitat_lokalno(put: str) -> dict[str, object]:
    r = subprocess.run([sys.executable, "-c", IZVLECH, put, *MODELI], capture_output=True, text=True,
                       timeout=30, check=False)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else {"oshibka": r.stderr.strip()[:200]}


def prochitat_po_ssh(adres: str, put: str) -> dict[str, object]:
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", adres, "python3", "-", put, *MODELI],
                           input=IZVLECH, capture_output=True, text=True, timeout=40, check=False)
    except subprocess.TimeoutExpired:
        return {"oshibka": "ssh: время вышло"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"oshibka": f"ssh {adres}: {r.stderr.strip()[:160] or r.returncode}"}
    return json.loads(r.stdout)


def znacheniya(d: dict[str, object]) -> tuple[str, ...]:
    """Ячейки строки: «—» — ключа нет (действует источник ниже по старшинству)."""
    if d.get("net"):
        return ("нет файла",) + ("",) * (len(KOLONKI) - 1)
    if "oshibka" in d:
        return (f"ОШИБКА: {d['oshibka']}",) + ("",) * (len(KOLONKI) - 1)
    okno = d.get("okno") if isinstance(d.get("okno"), dict) else {}
    env = d.get("env") if isinstance(d.get("env"), dict) else {}
    return (*(str(okno.get(m)) if okno.get(m) is not None else "—" for m in MODELI),
            str(d["idle"]).lower() if d.get("idle") is not None else "—",
            ", ".join(f"{k}={v}" for k, v in sorted(env.items())) or "—")


def itog(sloi: list[tuple[str, ...]]) -> tuple[str, ...]:
    """Старшинство: первый слой, где ключ задан (`sloi` — от старшего к младшему); env — по переменным."""
    out = []
    for i in range(len(KOLONKI) - 1):
        out.append(next((s[i] for s in sloi if s[i] not in ("—", "", "нет файла") and not s[0].startswith("ОШИБКА")),
                        "по умолчанию"))
    env: dict[str, str] = {}
    for s in reversed(sloi):
        if s[-1] not in ("—", "") and not s[0].startswith(("ОШИБКА", "нет файла")):
            env |= dict(x.split("=", 1) for x in s[-1].split(", "))
    out.append(", ".join(f"{k}={v}" for k, v in sorted(env.items())) or "по умолчанию")
    return tuple(out)


def tablica(zagolovok: str, stroki: list[tuple[str, ...]]) -> list[str]:
    shapka = (zagolovok, *KOLONKI)
    shir = [max(len(r[i]) for r in [shapka, *stroki]) for i in range(len(shapka))]
    fmt = lambda r: "| " + " | ".join(c.ljust(w) for c, w in zip(r, shir, strict=True)) + " |"  # noqa: E731
    return [fmt(shapka), "|" + "|".join("-" * (w + 2) for w in shir) + "|", *map(fmt, stroki)]


def main() -> int:
    svoya = socket.gethostname()
    mashiny = dict(x.split("=", 1) for x in MASHINY.split())
    po_mashine: dict[str, tuple[str, ...]] = {}
    for m, adres in mashiny.items():
        d = prochitat_lokalno("~/.claude/settings.json") if m == svoya else prochitat_po_ssh(adres, "~/.claude/settings.json")
        po_mashine[m] = znacheniya(d)
    po_proektu: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for p in PROEKTY:
        k = KORNI / p / ".claude"
        po_proektu[p] = (znacheniya(prochitat_lokalno(str(k / "settings.local.json"))),
                         znacheniya(prochitat_lokalno(str(k / "settings.json"))))
    istochniki = [(f"~/.claude/settings.json @ {m}", *v) for m, v in po_mashine.items()]
    for p, (lok, proj) in po_proektu.items():
        istochniki += [(f"{p}/.claude/settings.json", *proj), (f"{p}/.claude/settings.local.json", *lok)]
    itogi = [(f"{p} / {m}", *itog([lok, proj, po_mashine[m]]))
             for p, (lok, proj) in po_proektu.items() for m in mashiny]
    print(f"Сверка настроек сжатия — с машины {svoya}; «—» — ключ не задан в этом файле.\n")
    print("\n".join(tablica("источник", istochniki)))
    print("\nДействует (settings.local.json > settings.json проекта > ~/.claude/settings.json):\n")
    print("\n".join(tablica("проект / машина", itogi)))
    nedostupny = [m for m, v in po_mashine.items() if v[0].startswith("ОШИБКА")]
    raznye = {i: {r[i + 1] for r in itogi} for i in range(len(KOLONKI))}
    rashozhdeniya = [f"{KOLONKI[i]}: {', '.join(sorted(v))}" for i, v in raznye.items() if len(v) > 1]
    print()
    if nedostupny:
        print(f"Не прочитаны машины: {', '.join(nedostupny)}.")
    print("Итог: одинаково везде." if not rashozhdeniya else "Итог: РАСХОДИТСЯ — " + "; ".join(rashozhdeniya) + ".")
    return 2 if nedostupny else 1 if rashozhdeniya else 0


if __name__ == "__main__":
    sys.exit(main())
