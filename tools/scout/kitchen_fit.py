#!/usr/bin/env python3
"""ПОСАДКА ПРИМЕРОВ КУХОНЬ на кухню квартиры (план onb-09 Т2–Т3, T-20261105-33): каждый пример RU/UK
(`data/partners/kitchen-examples/{ru,uk}.json`) → `planner/kitchen.py:seat_kitchen` на геометрии кухни
(`tools/scout/flat215-kitchen.json`, та же у английского двойника demo-uk-215) → `data/partners/kitchen-fit/flat215.json`.

Файл читают набор (`lib/viewer3d/kits/kitchen-from-example.ts:kitchenSpecFromExample` с `fit`) и 3D-снимок
(`tools/flat3d/kitchen-snap.mjs --set flat215`). Бесплатно, без сети; детерминирован — сторож свежести
`tests/unit/kitchen-fit.test.ts` (параметры набора совпадают с `kitchenLayout`) и `--check` (файл = пересчёт).

Параметры набора из паспорта (зеркало `kitchen-layout.ts`, сторож — тот же тест): колонн — `KITCHEN_LEVELS[level].columns`,
с `tall-unit` — не меньше одной (по 60 см); верх — уровень с долей верха > 0 или признак `uppers`; холодильник в колонне —
признак `fridge` при колонне.

  python3 tools/scout/kitchen_fit.py            # пересчитать и записать
  python3 tools/scout/kitchen_fit.py --check    # файл совпадает с пересчётом (выход 1 — нет)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "planner-solver"))

from planner.kitchen import KitchenKit, Vent, seat_kitchen  # noqa: E402
from planner.models import Opening, Radiator, Room  # noqa: E402

FLAT = ROOT / "tools" / "scout" / "flat215-kitchen.json"
EXAMPLES = [ROOT / "data" / "partners" / "kitchen-examples" / f"{m}.json" for m in ("ru", "uk")]
OUT = ROOT / "data" / "partners" / "kitchen-fit" / "flat215.json"
APARTMENTS = ["flat215", "demo-uk-215"]          # одна геометрия: demo-uk-215 — enTwin flat215 (`demo.json`)
LEVEL_COLUMNS = {"base": 0, "practical": 0, "comfort": 1, "premium": 2}   # `kitchen-layout.ts:KITCHEN_LEVELS[*].columns`
LEVEL_UPPERS = {"base": False, "practical": True, "comfort": True, "premium": True}   # `.uppers > 0`
COLUMN_W = 60                                     # `kitchen-layout.ts:COLUMN_W`
DROP = ("tried", "score")                         # служебное перебора — в файле только ответ


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def room_from(spec: dict) -> Room:
    return Room(width_cm=spec["w"], depth_cm=spec["d"], room_type="kitchen",
                openings=[Opening(**_clean(o)) for o in spec.get("openings", [])],
                radiators=[Radiator(**_clean(r)) for r in spec.get("radiators", [])])


def kit_from(example: dict) -> KitchenKit:
    k = example["kitSpec"]
    feats = set(k["features"])
    cols = max(1, LEVEL_COLUMNS[k["level"]]) if "tall-unit" in feats else LEVEL_COLUMNS[k["level"]]
    return KitchenKit(length_cm=k["widthCm"], depth_cm=k["depthCm"], shape=example["shape"], tall_cm=cols * COLUMN_W,
                      uppers=LEVEL_UPPERS[k["level"]] or "uppers" in feats, fridge_in_column="fridge" in feats and cols > 0,
                      peninsula=bool(k.get("peninsula")))


def build() -> dict:
    flat = json.loads(FLAT.read_text(encoding="utf-8"))["rooms"][0]
    room = room_from(flat)
    vent = Vent(**_clean(flat["vent"])) if flat.get("vent") else None
    fits = {}
    for path in EXAMPLES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for e in data["examples"]:
            if "flat215" in ((e.get("notFor") or {}).get("flats") or []):
                continue
            r = seat_kitchen(room, kit_from(e), vent)
            fits[e["id"]] = {"market": data["market"], **{k: v for k, v in r.items() if k not in DROP}}
    return {
        "_about": "Посадка примеров кухонь на кухню квартиры 215 (solver `planner/kitchen.py`); генерирует "
                  "`tools/scout/kitchen_fit.py` — руками не править. Система координат — план кухни в см (x вправо, "
                  "y вглубь, стены south/north/west/east), `pose` — центр набора и поворот как у предметов солвера.",
        "room": {"source": "tools/scout/flat215-kitchen.json", "w": flat["w"], "d": flat["d"], "vent_assumed": bool(vent and vent.assumed)},
        "apartments": APARTMENTS,
        "fits": fits,
    }


def dump(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="сверить файл с пересчётом, не записывая")
    a = ap.parse_args()
    text = dump(build())
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("kitchen-fit: свежий" if ok else f"kitchen-fit: УСТАРЕЛ — пересчитай: python3 {Path(__file__).relative_to(ROOT)}")
        return 0 if ok else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    d = json.loads(text)
    for k, v in d["fits"].items():
        print(f"{k}: {'стена ' + v['wall'] + ', с ' + str(v['u0_cm']) + ' см, колонны ' + str(v['columns_at']) if v['ok'] else 'НЕ ВСТАЛ ' + ', '.join(v['reason'][:2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
