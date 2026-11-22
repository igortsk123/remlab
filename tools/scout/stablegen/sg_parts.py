#!/usr/bin/env python3
"""Слоты материалов по частям для покраски StableGen (T-20261120-161, П6/П7, Codex v2 20.11): «ножки» и «тело» — два слота материала на ГРАНЯХ формы.

ЗАЧЕМ. Драйвер красит один меш одним материалом, и StableGen ведёт всю поверхность одной подписью. Нужна разметка граней по частям (Codex v2: «блок — не один кусок,
а нет разметки граней»): ID-карты материалов StableGen сохраняют уже заданные разделы, но сами смысловые части не угадывают.
КАК. Разметка — ГЕОМЕТРИЯ формы, готовый код `tools/assets/material_parts.py` (ножки — отдельные малые пятна у пола). Считается ЗДЕСЬ, вне Blender (там нет trimesh),
в файл `parts-faces.json` рядом с прогоном; драйвер читает файл и кладёт `material_index` на грани. Правило — ТОЛЬКО по статусу геометрии, ID товаров в коде нет:
  • `split` + уверенность ≥ порога правил + доля площади ножек в пределах `parts.slots` → слоты (0 тело, 1 ножки);
  • иначе (`whole`, `unsure`, слитые формы: стол-табурет, лампа; доля вне предела) → слотов НЕТ, красится «как сейчас» (не выдумываем разметку).
Замеры 20.11 (стол 16 unsure, лампа 37 whole, кресло 23 split, ножки 0,9 % площади): разметка по граням честна только у мебели с отдельными ножками; столам и лампам нужна другая
(по сечению/меткам каталога — отдельная задача), здесь они остаются без слотов.
Запуск проверки: python3 sg_parts.py <glb> [<glb> …]    (печать: статус, доля ножек, причина; ничего не пишет)."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..'))
ASSETS = os.path.normpath(os.path.join(SCOUT, '..', 'assets'))
CAPTIONS_PATH = os.path.join(SCOUT, 'rules', 'stablegen-captions.json')
BODY, LEGS = 0, 1                                            # номера слотов материала на гранях


def load_slot_rules(path: str = CAPTIONS_PATH) -> dict:
    """Правила слотов из данных (`parts.slots` в stablegen-captions.json): доля площади ножек от min до max, имена материалов слотов."""
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    s = (d.get('parts') or {}).get('slots') or {}
    return {'legs_share_min': float(s.get('legs_share_min', 0.002)), 'legs_share_max': float(s.get('legs_share_max', 0.30)),
            'names': list(s.get('names') or ['body', 'legs'])}


def decide(rec: dict, legs_share: float, rules: dict, apply_conf: float) -> tuple[bool, str]:
    """Кладём ли слоты: (да/нет, причина). Чистая функция — по записи геометрии, без mesh."""
    if rec.get('status') != 'split':
        return False, f"слотов нет: геометрия {rec.get('status')} — красим как сейчас ({rec.get('reason', '')})"
    if (rec.get('confidence') or 0.0) < apply_conf:
        return False, f"слотов нет: уверенность {rec.get('confidence')} < {apply_conf}"
    if not (rules['legs_share_min'] <= legs_share <= rules['legs_share_max']):
        return False, f"слотов нет: доля площади ножек {100 * legs_share:.1f}% вне {100 * rules['legs_share_min']:.1f}–{100 * rules['legs_share_max']:.0f}%"
    return True, f"слоты: ножки {100 * legs_share:.1f}% площади ({rec.get('reason', '')})"


def face_slots(glb: str, rules: dict | None = None) -> dict:
    """Разметка граней формы `glb`: {'ok', 'faces', 'legs' (индексы граней ножек), 'legs_share', 'status', 'reason'}. Нет trimesh/numpy или форма не читается → ok False + причина (красим как сейчас)."""
    rules = rules or load_slot_rules()
    try:
        sys.path.insert(0, ASSETS)
        import material_parts as MP
        mesh = MP.load_mesh(glb)
        mp_rules = MP.load_rules()
        rec = MP.judge(MP.analyze(mesh, mp_rules), mp_rules, None)
        legs = MP.legs_face_mask(mesh, rec)
        total = float(mesh.area_faces.sum()) or 1.0
        share = float(mesh.area_faces[legs].sum()) / total
    except Exception as e:  # noqa: BLE001 — нет библиотек/сломанный файл: разметки нет, прогон не падает
        return {'ok': False, 'faces': 0, 'legs': [], 'legs_share': 0.0, 'status': 'error', 'reason': f'разметка недоступна: {str(e)[:120]}'}
    ok, why = decide(rec, share, rules, mp_rules['confidence']['apply'])
    return {'ok': ok, 'faces': int(len(mesh.faces)), 'legs': [int(i) for i in legs.nonzero()[0]] if ok else [], 'legs_share': round(share, 4),
            'status': rec.get('status'), 'reason': why}


def write_faces(info: dict, path: str, names: list[str] | None = None) -> str:
    """Файл разметки для драйвера: только число граней, индексы ножек и имена слотов (малый, без mesh)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'faces': info['faces'], 'legs': info['legs'], 'names': names or load_slot_rules()['names'], 'reason': info['reason']}, f, ensure_ascii=False)
    return path


def slot_indices(doc: dict, n_faces: int) -> list[int] | None:
    """Номера слотов по граням из файла разметки или None — число граней не сошлось (Blender пересобрал форму) → слотов нет, красим как сейчас.
    Чистая функция: ей пользуется драйвер внутри Blender."""
    if not doc or int(doc.get('faces', -1)) != int(n_faces) or not doc.get('legs'):
        return None
    idx = [BODY] * int(n_faces)
    for i in doc['legs']:
        if not 0 <= int(i) < n_faces:
            return None
        idx[int(i)] = LEGS
    return idx


def main(argv: list[str]) -> int:
    rules = load_slot_rules()
    for glb in argv:
        r = face_slots(glb, rules)
        print(f"{os.path.basename(glb)}: слоты={'да' if r['ok'] else 'нет'} граней={r['faces']} ножек={len(r['legs'])} доля={r['legs_share']} статус={r['status']} — {r['reason']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
