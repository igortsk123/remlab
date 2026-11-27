"""МЕТКА ФОРМЫ — генератор и ступень ИЗ ЖУРНАЛА ГЕНЕРАЦИИ (T-20261127-175/10-zapisi; директор 27.11: «один источник — ключи формы, не руками в json»; Fable (б): из журнала, не константой).

Ворота №10 (`circle_origin.py`, пункт «генератор и ступень») читают у готовой формы `<форма>.form.json` с ключами `generator` и `stage`; писателя не было.
Этот модуль — единственный штатный писатель. Журнал генерации — `summary-trial-<модель>-<суффикс>.json` (его пишет `salad/trellis/trellis_trial.py` в папку `--out`
вместе с GLB): `model` (чем построено), `jobs[]` с `job_id` = `<товар>-<ступень>` (= имя GLB без `.glb`), `status`, `ladder_step`, seed, образ.
  • generator = `model` журнала; stage = `ladder_step` задания с `job_id` = имя формы и `status == done`;
  • журнал ищется в папке GLB (`summary-trial-*.json`) или задаётся `--journal` (можно несколько);
  • `<форма>.model` рядом, если есть, — сверка: другое имя модели → отказ (не «выбираю удобное»).
Нет журнала / в нём нет выполненного (`done`) задания этой формы / нет `ladder_step` / журналы спорят (разные model/ступень) / `.model` расходится — НЕ ВЫПОЛНЕНО:
строка с причиной, код ≠ 0, файл не пишется. Существующая метка с другим содержимым не перезаписывается (код ≠ 0): ничего не удаляю и не подменяю.
Разрешён ли генератор — решают ворота (`allowed_generators`); здесь пишется то, что сказал журнал. Новых выключателей и правил нет — реестр не нужен.

Запуск: python3 tools/scout/form_meta.py <форма.glb> [<форма.glb> …] [--journal <summary-trial-….json> …] [--dry]   (--dry — только показать, ничего не писать)
Коды: 0 — все метки записаны/уже есть такие же; 1 — хотя бы по одной форме не выполнено (причина строкой); 2 — неверный вызов (не названо ни одной формы)."""
import argparse
import datetime
import glob
import hashlib
import json
import os
import sys

SCHEMA = 'form-meta/2'


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def stem_of(glb: str) -> str:
    return os.path.splitext(os.path.abspath(os.path.expanduser(glb)))[0]


def journals_for(glb: str, journals: list | None) -> list[str]:
    if journals:
        return [os.path.abspath(os.path.expanduser(j)) for j in journals]
    return sorted(glob.glob(os.path.join(os.path.dirname(stem_of(glb)), 'summary-trial-*.json')))


def build(glb: str, journals: list | None = None) -> tuple[dict | None, str]:
    """→ (метка, '') или (None, причина «не выполнено»)."""
    g = os.path.abspath(os.path.expanduser(glb))
    if not os.path.isfile(g):
        return None, f'нет файла формы {g}'
    stem = stem_of(g)
    base = os.path.basename(stem)
    files = journals_for(g, journals)
    if not files:
        return None, f'нет журнала генерации: в {os.path.dirname(g)} нет `summary-trial-*.json` (и `--journal` не задан) — чем и на какой ступени построена форма, неизвестно'
    found, notes = [], []
    for jf in files:
        if not os.path.isfile(jf):
            notes.append(f'{jf}: нет файла')
            continue
        try:
            d = json.load(open(jf, encoding='utf-8'))
        except (OSError, ValueError) as e:
            notes.append(f'{os.path.basename(jf)}: не читается ({e})')
            continue
        jobs = d.get('jobs') if isinstance(d, dict) else None
        if not isinstance(jobs, list):
            notes.append(f'{os.path.basename(jf)}: нет списка jobs')
            continue
        for j in jobs:
            if isinstance(j, dict) and str(j.get('job_id') or '').replace(':', '_') == base:
                found.append((jf, d, j))
    done = [x for x in found if str(x[2].get('status')) == 'done']
    if not done:
        why = ('в журналах задание есть, но не выполнено: ' + '; '.join(f'{os.path.basename(f)}: status {j.get("status")}' for f, _d, j in found)) if found else 'в журналах нет задания этой формы'
        return None, f'{why} (искал `{base}` в {", ".join(os.path.basename(f) for f in files)}{"; " + "; ".join(notes) if notes else ""}) — формы по журналу нет'
    pairs = {(str(d.get('model') or ''), str(j.get('ladder_step') or '')) for _f, d, j in done}
    if len(pairs) != 1:
        return None, f'журналы спорят о форме `{base}`: {sorted(pairs)} — какой верить, решает владелец задачи'
    model, stage = pairs.pop()
    if not model:
        return None, f'в журнале {os.path.basename(done[-1][0])} нет `model` — генератор неизвестен'
    if not stage:
        return None, f'в задании `{base}` журнала {os.path.basename(done[-1][0])} нет `ladder_step` — ступень неизвестна'
    mp = stem + '.model'
    if os.path.isfile(mp):
        tag = open(mp, encoding='utf-8', errors='replace').read().strip()
        if tag and tag != model:
            return None, f'`{os.path.basename(mp)}` говорит «{tag}», журнал — «{model}»: расходятся, не выбираю'
    jf, d, j = done[-1]
    return {'schema': SCHEMA, 'generator': model, 'stage': stage,
            'source': {'journal': jf, 'journal_sha256': _sha(jf), 'job_id': j.get('job_id'), 'group': d.get('group'), 'image': d.get('image'), 'seed': j.get('seed'),
                       'res': j.get('res'), 'model_file': os.path.basename(mp) if os.path.isfile(mp) else None, 'glb_sha256': _sha(g)},
            'created': datetime.date.today().isoformat()}, ''


def same(a: dict, b: dict) -> bool:
    """Та же метка (дата выдачи не в счёт)."""
    return {k: v for k, v in a.items() if k != 'created'} == {k: v for k, v in b.items() if k != 'created'}


def write(glb: str, journals: list | None = None, dry: bool = False) -> tuple[int, str]:
    """→ (код, строка). 0 — записано / уже есть такая же / dry; 1 — не выполнено или чужая метка на месте."""
    rec, why = build(glb, journals)
    if rec is None:
        return 1, f'НЕ ВЫПОЛНЕНО {glb}: {why}'
    out = stem_of(glb) + '.form.json'
    if os.path.exists(out):
        try:
            old = json.load(open(out, encoding='utf-8'))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict) and same(old, rec):
            return 0, f'есть {out} (та же метка): generator={rec["generator"]}, stage={rec["stage"]}'
        return 1, f'НЕ ВЫПОЛНЕНО {glb}: {out} уже есть и отличается от того, что говорит журнал — не перезаписываю (разобрать вручную владельцу задачи)'
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
    ap.add_argument('--journal', action='append', default=None, help='журнал генерации summary-trial-*.json (по умолчанию — все такие в папке GLB)')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args(argv)
    if not a.glb:
        print('form_meta: НЕ ВЫПОЛНЕНО — не названо ни одной формы (<форма.glb>)')
        return 2
    bad = 0
    for g in a.glb:
        rc, line = write(g, a.journal, a.dry)
        print(line)
        bad += rc != 0
    if bad:
        print(f'form_meta: НЕ ВЫПОЛНЕНО у {bad} из {len(a.glb)} форм — код возврата 1')
        return 1
    print(f'form_meta: готово {len(a.glb)} из {len(a.glb)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
