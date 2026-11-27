"""МЕТКА ФОРМЫ — генератор и ступень (T-20261127-175/10-zapisi, ответ директора 27.11: «один источник — ключи формы из ladder/.model, не руками в json»).

Ворота №10 (`circle_origin.py`, пункт «генератор и ступень») читают у готовой формы `<форма>.form.json` с ключами `generator` и `stage`.
Писателя этих ключей не было: запись происхождения вырезки их не несёт. Этот модуль — единственный штатный писатель:
  • generator — из `<форма>.model` рядом с GLB (метку пишет `salad/trellis/trellis_trial.py`: `<id>.model`, например `trellis2`);
  • stage — имя ступени лесенки (`--ladder`, JSON-список `{name, …}` как у `trellis_trial.parse_ladder`): GLB называется `<товар>-<ступень>.glb`.
Нет `.model` / он пуст / нет лесенки / имя GLB не оканчивается именем ступени — НЕ ВЫПОЛНЕНО: строка с причиной, код ≠ 0, файл не пишется
(тихого «нашёл что-нибудь» нет). Существующая метка с другим содержимым не перезаписывается (код ≠ 0): ничего не удаляю и не подменяю.
Разрешён ли генератор — решают ворота (`allowed_generators`), здесь пишется то, что сказал `.model`. Новых выключателей и правил нет — реестр не нужен.

Запуск: python3 tools/scout/form_meta.py <форма.glb> [<форма.glb> …] --ladder <ladder.json> [--dry]   (--dry — только показать, ничего не писать)
Коды: 0 — все метки записаны/уже есть такие же; 1 — хотя бы по одной форме не выполнено (причина строкой); 2 — неверный вызов (нет форм/лесенки)."""
import argparse
import datetime
import hashlib
import json
import os
import sys

SCHEMA = 'form-meta/1'


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def stems_of(glb: str) -> str:
    return os.path.splitext(os.path.abspath(os.path.expanduser(glb)))[0]


def load_ladder(path: str) -> list[str]:
    """Имена ступеней лесенки; ошибка файла → ValueError с причиной."""
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise ValueError(f'нет файла лесенки {p}')
    try:
        items = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError(f'лесенка {p} не читается: {e}')
    if not isinstance(items, list) or not items:
        raise ValueError(f'лесенка {p}: нужен непустой JSON-список ступеней')
    names = [str(it.get('name') or '') for it in items if isinstance(it, dict)]
    if len(names) != len(items) or not all(names):
        raise ValueError(f'лесенка {p}: у каждой ступени нужно имя (`name`)')
    return names


def build(glb: str, ladder: str) -> tuple[dict | None, str]:
    """→ (метка, '') или (None, причина «не выполнено»)."""
    g = os.path.abspath(os.path.expanduser(glb))
    if not os.path.isfile(g):
        return None, f'нет файла формы {g}'
    stem = stems_of(g)
    mp = stem + '.model'
    if not os.path.isfile(mp):
        return None, f'нет `{os.path.basename(mp)}` рядом с формой — генератор неизвестен (метку пишет trellis_trial при генерации)'
    model = open(mp, encoding='utf-8', errors='replace').read().strip()
    if not model or len(model) > 64 or any(c.isspace() for c in model):
        return None, f'`{os.path.basename(mp)}` пуст или не похож на имя модели («{model[:40]}») — генератор неизвестен'
    try:
        names = load_ladder(ladder)
    except ValueError as e:
        return None, str(e)
    base = os.path.basename(stem)
    hit = sorted((n for n in names if base.endswith('-' + n)), key=len, reverse=True)
    if not hit:
        return None, f'имя формы «{base}» не оканчивается именем ни одной ступени лесенки {names} — ступень неизвестна'
    return {'schema': SCHEMA, 'generator': model, 'stage': hit[0],
            'source': {'model_file': os.path.basename(mp), 'ladder': os.path.abspath(os.path.expanduser(ladder)), 'ladder_sha256': _sha(os.path.expanduser(ladder)),
                       'glb_sha256': _sha(g)},
            'created': datetime.date.today().isoformat()}, ''


def same(a: dict, b: dict) -> bool:
    """Та же метка (дата выдачи не в счёт)."""
    return {k: v for k, v in a.items() if k != 'created'} == {k: v for k, v in b.items() if k != 'created'}


def write(glb: str, ladder: str, dry: bool = False) -> tuple[int, str]:
    """→ (код, строка). 0 — записано / уже есть такая же / dry; 1 — не выполнено или чужая метка на месте."""
    rec, why = build(glb, ladder)
    if rec is None:
        return 1, f'НЕ ВЫПОЛНЕНО {glb}: {why}'
    out = stems_of(glb) + '.form.json'
    if os.path.exists(out):
        try:
            old = json.load(open(out, encoding='utf-8'))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict) and same(old, rec):
            return 0, f'есть {out} (та же метка): generator={rec["generator"]}, stage={rec["stage"]}'
        return 1, f'НЕ ВЫПОЛНЕНО {glb}: {out} уже есть и отличается от того, что дают `.model` и лесенка — не перезаписываю (разобрать вручную владельцу задачи)'
    if dry:
        return 0, f'dry: записал бы {out}: generator={rec["generator"]}, stage={rec["stage"]}'
    tmp = out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    return 0, f'записано {out}: generator={rec["generator"]}, stage={rec["stage"]}'


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('glb', nargs='*')
    ap.add_argument('--ladder', default=None, help='JSON лесенки формы (список ступеней с именами)')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args(argv)
    if not a.glb:
        print('form_meta: НЕ ВЫПОЛНЕНО — не названо ни одной формы (<форма.glb>)')
        return 2
    if not a.ladder:
        print('form_meta: НЕ ВЫПОЛНЕНО — не назван --ladder (ступень берётся только из лесенки)')
        return 2
    bad = 0
    for g in a.glb:
        rc, line = write(g, a.ladder, a.dry)
        print(line)
        bad += rc != 0
    if bad:
        print(f'form_meta: НЕ ВЫПОЛНЕНО у {bad} из {len(a.glb)} форм — код возврата 1')
        return 1
    print(f'form_meta: готово {len(a.glb)} из {len(a.glb)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
