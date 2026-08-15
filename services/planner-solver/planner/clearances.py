"""Клиренсы по ролям + доступ к каноничным правилам проекта (`rules/occupancy.json`).

Источник истины по числам — `rules/occupancy.json` (тот же файл читает scout-конвейер;
раньше он лежал только в gitignore'нутом tools/scout — перенесён сюда, чтобы канон был ОДИН
и попадал в git/CI). Таблица клиренсов по ролям собрана из `distances_cm` этого свода;
механика «margin входит в след» — идея ProcTHOR (см. guides/layout-mined-rules.md).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "occupancy.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def distances() -> dict:
    return rules().get("distances_cm", {})


def band_scale(key: str, band: str | None, default: list[float]) -> list[float]:
    """Динамическая шкала от площади (решения владельца: кап пола, диван↔столик, диван↔ТВ)."""
    dyn = rules().get("dynamic", {}).get(key, {})
    if band and band in dyn:
        return list(dyn[band])
    return list(default)


# Предметы НИЖЕ этой высоты не блокируют подход: журнальный столик, пуф, ковёр стоят
# в зоне ног легитимно (наше правило sofa_coffee_table 36–50 см; у ProcTHOR такая пара
# вообще ставится единой ассет-группой, внутри которой margin не применяется).
LOW_ITEM_MAX_H_CM = 55.0
NEVER_BLOCKING_ROLES = frozenset({"столик", "ковёр", "пуф", "кашпо", "торшер",
                                  "приставной"})   # C-4: низкая поверхность между креслами — как столик


@dataclass(frozen=True)
class ClearanceSpec:
    """Свободное место вокруг предмета, см. front — ПЕРЕД лицом (подход/ноги/проход)."""

    front_cm: float = 0.0
    side_cm: float = 0.0
    back_cm: float = 0.0
    why: str = ""


def _d(key: str, default: float, idx: int = 0) -> float:
    v = distances().get(key, default)
    return float(v[idx]) if isinstance(v, list) else float(v)


@lru_cache(maxsize=1)
def _table() -> dict[str, ClearanceSpec]:
    return {
        # сидячие: место для ног/подхода спереди, вентзазор сзади (спинка к стене — ок)
        "диван": ClearanceSpec(_d("legroom_front_of_seat", 46), 0, _d("sofa_back_to_wall_vent", 8), "ноги перед диваном"),
        "кресло": ClearanceSpec(_d("legroom_front_of_seat", 46), 0, 0, "ноги перед креслом"),
        "пуф": ClearanceSpec(30, 0, 0, "подход к пуфу"),
        # хранение: открывание фасадов/ящиков спереди
        "шкаф": ClearanceSpec(_d("wardrobe_hinged_front_min", 80), 0, 0, "распашной фасад"),
        "комод": ClearanceSpec(_d("dresser_front", 76), 0, 0, "выдвижной ящик"),
        "стенка": ClearanceSpec(_d("wardrobe_sliding_front", 50), 0, 0, "фасады стенки"),
        "витрина": ClearanceSpec(_d("wardrobe_sliding_front", 50), 0, 0, "фасады витрины"),
        # открытый стеллаж не имеет ни дверец, ни ящиков — ему нужен подход, а не место
        # на распахивание: 30 см (шкаф/комод/витрина сохраняют свои 76–80/50)
        "стеллаж": ClearanceSpec(30, 0, 0, "подход к открытым полкам"),
        "тв-тумба": ClearanceSpec(45, 0, 0, "подход к технике"),
        "камин": ClearanceSpec(_d("fireplace_clear", 100), 0, 0, "безопасная зона у камина"),
        # обеденная группа: отодвинуть стул
        # стол обеденный: стулья отодвигают с трёх сторон; четвёртая может быть у стены —
        # наш свод прямо это допускает (dining_table_to_wall_no_pass 91 см), а клиренс со ВСЕХ
        # сторон требовал остров 2.3×2.0 м и рушил 6 сетов из 126
        "стол обеденный": ClearanceSpec(_d("dining_chair_pullout", 55), _d("dining_chair_pullout", 55), 0, "отодвинуть стул"),
        "стул": ClearanceSpec(_d("dining_chair_pullout", 55), 0, 0, "отодвинуть стул"),
        # мелочь клиренса не требует
        "столик": ClearanceSpec(0, 0, 0, "журнальный столик — центр зоны"),
        "приставной": ClearanceSpec(0, 0, 0, "приставная поверхность — центр зоны (C-4)"),
        "торшер": ClearanceSpec(0, 0, 0, ""),
        "кашпо": ClearanceSpec(0, 0, 0, ""),
        "ковёр": ClearanceSpec(0, 0, 0, ""),
    }


DEFAULT_MIDDLE = ClearanceSpec(35, 35, 35, "ProcTHOR: предмет вне стены — 0.35 м вокруг")


def clearance_for(role: str) -> ClearanceSpec:
    from .geometry import base_role
    # «стул 2..4»/«кресло 2» — те же клиренсы, что у базовой роли (иначе экземпляр получал
    # дефолт 35 вместо, например, chair pullout 55)
    return _table().get(base_role(role)) or _table().get(role) or \
        ClearanceSpec(35, 0, 0, "дефолт: подход спереди")


def passage_min_cm(kind: str = "secondary") -> float:
    if kind == "main":
        return _d("passage_main", 90)
    return _d("passage_secondary_min", 60)
