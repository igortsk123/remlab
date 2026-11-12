"""Проходы по норме обычного жилья (ADR-0394, T-20261112-68): одна функция «проход + режим + профиль → см».

Числа — `rules/occupancy.json` `distances_cm.clearances` (одно место). У прохода три числа: target — цель, compact — допуск
малой комнаты (покупателю строкой), hard — жёсткий минимум. Профиль general — по умолчанию; m4_2 / m4_3 / mgn — жильё,
которое продают как доступное: допусков нет, числа не меньше floor профиля.

Режим задаёт движок (`using`): движок групп спальни (`planner/bedroom.py:_solve_groups`) — проход 1 «target», проход 2
«compact»; поштучный движок — «legacy» (прежние ключи, байт в байт). Вне движка (`validate`, листы, проверки извне) —
«compact»: раскладка законна, если не меньше допуска; недобор до цели — это допуск (`allowances`), не нарушение.
"""
from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager

from .clearances import distances

MODES = ("target", "compact", "legacy")
DEFAULT_MODE = "compact"
_MODE: contextvars.ContextVar = contextvars.ContextVar("passage_mode", default=None)
_PROFILE: contextvars.ContextVar = contextvars.ContextVar("passage_profile", default=None)


def block() -> dict:
    return distances().get("clearances") or {}


def profiles() -> dict:
    return block().get("_profiles") or {}


def profile() -> str:
    """Профиль текущего расчёта: заданный в `using` → `_profile_default` → general."""
    return _PROFILE.get() or block().get("_profile_default") or "general"


def mode() -> str:
    return _MODE.get() or DEFAULT_MODE


def allowances_on(prof: str | None = None) -> bool:
    """Есть ли у профиля допуски `compact` (у доступного жилья — нет: второй проход движка не нужен)."""
    return bool((profiles().get(prof or profile()) or {}).get("allowances", True))


@contextmanager
def using(m: str, prof: str | None = None):
    """Режим (и профиль) проходов на время блока: `with using("compact"): ...`."""
    if m not in MODES:
        raise ValueError(f"режим проходов {m!r}? можно {', '.join(MODES)}")
    if prof is not None and prof not in profiles():
        raise ValueError(f"профиль проходов {prof!r}? есть {', '.join(sorted(profiles()))}")
    t1 = _MODE.set(m)
    t2 = _PROFILE.set(prof) if prof is not None else None
    try:
        yield
    finally:
        _MODE.reset(t1)
        if t2 is not None:
            _PROFILE.reset(t2)


def triple(name: str, prof: str | None = None) -> dict:
    """{target, compact, hard} прохода для профиля. Свой блок профиля у прохода — как записан; иначе у профиля без
    допусков все три = max(target general, floor профиля)."""
    spec = block().get(name)
    if not isinstance(spec, dict) or "general" not in spec:
        raise KeyError(f"прохода {name!r} нет в occupancy.json distances_cm.clearances")
    prof = prof or profile()
    if prof in spec:
        return dict(spec[prof])
    gen = spec["general"]
    pc = profiles().get(prof)
    if pc is None:
        raise KeyError(f"профиля {prof!r} нет в distances_cm.clearances._profiles")
    if pc.get("allowances", True):
        return dict(gen)
    v = max(float(gen["target"]), float(pc.get("floor", 0)))
    return {"target": v, "compact": v, "hard": v}


def clearance(name: str, level: str | None = None, prof: str | None = None) -> float | None:
    """Число прохода, см. level: target | compact | hard | legacy | None (= текущий режим). legacy — прежний ключ
    (`legacy` у прохода); у прохода без прежнего ключа в legacy — None (проверка выключена, как было)."""
    level = level or mode()
    if level == "legacy":
        key = (block().get(name) or {}).get("legacy")
        if not key:
            return None
        v = distances().get(key)
        return float(v[0]) if isinstance(v, list) else (float(v) if v is not None else None)
    return float(triple(name, prof)[level])


def where(name: str) -> str:
    return (block().get(name) or {}).get("where") or name


_SLIDING = re.compile(r"купе|раздвижн|sliding|открыт|стеллаж|open\b", re.I)


def wardrobe_kind(item) -> str:
    """Тип шкафа из данных товара: caps.doors (hinged | sliding | open) → название (купе, раздвижной, открытый) → hinged
    (неизвестно — распашной, бриф T-68)."""
    caps = getattr(item, "caps", None) or {}
    k = caps.get("doors")
    if k in ("hinged", "sliding", "open"):
        return k
    name = getattr(item, "name", None) or ""
    return "sliding" if _SLIDING.search(name) else "hinged"


def drawer_reach_unknown() -> float:
    return float((block().get("dresser_front") or {}).get("drawer_reach_unknown", 70))


def front_need(item, kind: str) -> tuple[str, float | None]:
    """(проход, см перед фасадом) для текущего режима: шкаф — по типу, не меньше дуги створки (caps.door_leaf_cm);
    комод — не меньше вылета ящика (caps.drawer_reach_cm; неизвестен — 70)."""
    caps = getattr(item, "caps", None) or {}
    if kind == "шкаф":
        name = "storage_sliding_front" if (mode() != "legacy" and wardrobe_kind(item) != "hinged") else "wardrobe_hinged_front"
        v = clearance(name)
        leaf = caps.get("door_leaf_cm")
        if mode() != "legacy" and name == "wardrobe_hinged_front" and isinstance(leaf, (int, float)):
            v = max(v, float(leaf))
        return name, v
    if kind == "комод":
        v = clearance("dresser_front")
        if mode() != "legacy":
            reach = caps.get("drawer_reach_cm")
            v = max(v, float(reach) if isinstance(reach, (int, float)) else drawer_reach_unknown())
        return "dresser_front", v
    raise ValueError(kind)
