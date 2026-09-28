#!/usr/bin/env python3
# merge-settings — единственная реализация merge пресета прав в существующий settings JSON (для apply.sh).
# Parity: tools/merge-settings.ps1 обязан давать тот же результат; контракт — tests/merge-cases/*.json.
# Меняешь логику здесь — поменяй в ps1-паре и добавь кейс в merge-cases.
#
# Контракт:
#   - permissions.defaultMode берётся из пресета;
#   - permissions.allow/ask — СМЕНА РЕЖИМА, а не накопление:
#       result = [записи existing, которых нет в kit-managed] ++ [записи пресета]  (без дублей).
#     kit-managed — объединение allow/ask/deny всех пресетов кита, найденных рядом с
#     применяемым (файлы default|important|autopilot|plan-first.json в его каталоге).
#     Смысл: записи, принадлежащие ДРУГОМУ режиму, при переключении уходят (иначе autopilot
#     после important навсегда остаётся с его ask-списком — а ask сильнее allow, и режим
#     фактически не меняется). Пользовательские записи ни в один пресет не входят → выживают.
#     Соседних пресетов нет (напр. в тестах) → kit-managed пуст → прежнее поведение-объединение.
#   - permissions.deny — ТОЛЬКО объединение, вычитания НЕТ. Пресеты кита `deny` не задают
#     вообще, значит любая запись в deny — авторская. Вычитание сняло бы жёсткий блок: напр.
#     `Bash(rm -rf /)` лежит в `ask` пресетов, т.е. является kit-managed, и был бы вычтен из
#     авторского deny — хардблок молча превратился бы в вопрос. Недопустимо (поймано на sib).
#   - hooks (v1.9 — слияние по событиям): свои hooks пользователя сохраняются как есть; из пресета добавляются
#     только НЕДОСТАЮЩИЕ. Ключ хука: скрипт кита `tools/<имя>.(mjs|py|sh)` в команде (тогда хук кита с другими
#     флагами — напр. `--block` — уже считается установленным и не задваивается), иначе — команда целиком.
#     Добавленный хук идёт отдельной записью {matcher, hooks:[…]} в конец списка события.
#   - остальные ключи existing не трогаются;
#   - если результат не отличается от existing — печатается __NOCHANGE__.
#
# Usage: merge-settings.py <preset.json> <existing.json>   (результат — в stdout)
import json
import os
import re
import sys

PRESET_NAMES = ("default", "important", "autopilot", "plan-first")
PERM_KEYS = ("allow", "ask", "deny")


def uniq(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def kit_managed(preset_path):
    """Объединение allow/ask/deny всех пресетов кита рядом с применяемым."""
    managed = set()
    d = os.path.dirname(os.path.abspath(preset_path))
    for name in PRESET_NAMES:
        p = os.path.join(d, name + ".json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                perm = (json.load(f) or {}).get("permissions", {})
        except (OSError, ValueError):
            continue
        for k in PERM_KEYS:
            managed.update(perm.get(k) or [])
    return managed


def merge(existing, preset, managed=frozenset()):
    merged = json.loads(json.dumps(existing))
    perm = merged.setdefault("permissions", {})
    pp = preset.get("permissions", {})
    if "defaultMode" in pp:
        perm["defaultMode"] = pp["defaultMode"]
    for k in PERM_KEYS:
        cur = list(perm.get(k) or [])
        # deny — авторский жёсткий блок, вычитать нельзя (см. контракт в шапке).
        kept = cur if k == "deny" else [x for x in cur if x not in managed]
        perm[k] = uniq(kept + list(pp.get(k) or []))
    if "hooks" in preset:
        merge_hooks(merged, preset["hooks"])
    return merged


KIT_SCRIPT = re.compile(r"tools[\\/]([\w.-]+\.(?:mjs|py|sh))")  # и `tools\x.mjs` (Windows)


def hook_key(cmd):
    m = KIT_SCRIPT.search(cmd or "")
    return "kit:" + m.group(1) if m else "cmd:" + (cmd or "")


def merge_hooks(merged, preset_hooks):
    """Слияние hooks по событиям: добавить из пресета только недостающие (см. контракт в шапке)."""
    if not preset_hooks:
        return
    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):  # нет или `"hooks": null` — как в .ps1: создаём
        hooks = merged["hooks"] = {}
    for event, entries in preset_hooks.items():
        have = hooks.get(event)
        if not isinstance(have, list):  # `"<событие>": null`
            have = hooks[event] = []
        keys = {hook_key(h.get("command")) for e in have if isinstance(e, dict) for h in (e.get("hooks") or []) if isinstance(h, dict)}
        for e in entries or []:
            for h in e.get("hooks") or []:
                k = hook_key(h.get("command"))
                if k in keys:
                    continue
                have.append({"matcher": e.get("matcher", ""), "hooks": [h]})
                keys.add(k)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: merge-settings.py <preset.json> <existing.json>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        preset = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        existing = json.load(f)
    merged = merge(existing, preset, kit_managed(sys.argv[1]))
    if json.dumps(existing, sort_keys=True) == json.dumps(merged, sort_keys=True):
        print("__NOCHANGE__")
    else:
        print(json.dumps(merged, indent=2, ensure_ascii=False))
