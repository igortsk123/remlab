#!/usr/bin/env python3
"""Оценщик ФОРМЫ по картинке (Ш0, T-184/9) — режим OBSERVE: VLM-модель (Gemini через шлюз проекта `llm_gateway`) сравнивает кадры глины формы с фото магазина
и по списку видов брака из паспорта (`plans/mesh-type-rules-01.md` § «Приёмка формы TRELLIS.2») отвечает JSON {вид: да/нет/неясно, где}. Ничего не бракует: флаг `vlm_<вид>` = «да» в `yes_min` из `runs` прогонов (голос, сейчас 2 из 3); `vlm_<вид>_check` = «да» хотя бы в `check_min_yes` (1) прогоне — «на глаз директору» (шире, ложные бывают; в block не идёт).
Правила — `tools/scout/rules/form-checks.json`, раздел `vlm_judge`: версия вопроса (в ключе кэша), модель, число прогонов, группы кадров, виды брака с ролями каталога (подстроки роли; пусто = все роли). В коде нет ID товаров и порогов.
Кэш: файл на (хеш фото + хеш кадров формы — они и есть то, что видит модель, т.е. новая форма/кадры = новый ответ + версия + модель + группа + прогон) — повторный вызов на тех же входах денег не стоит. Названия товара в запрос не идёт, порядок кадров случайный (детерминированный от sku/прогона).
Ключ шлюза — только через `env_keys` внутри `llm_gateway`; значение не читается и не логируется.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import re
import sys

from PIL import Image

PROMPT = '''Ты проверяешь качество 3D-модели мебели/декора, построенной по одной фотографии магазина.
Тебе дано {n} изображений в таком порядке: {order}.
Фото — настоящий предмет. Модели — серые «глиняные» рендеры 3D-модели без цвета и материалов (цвет, узор, текст на ткани и прозрачность стекла на модели НЕ ожидаются — это не дефект).
Сравни ФОРМУ модели с фото и по каждому виду брака ответь: «да» (дефект есть), «нет» (дефекта нет) или «неясно» (по этим кадрам не видно).
Виды брака:
{kinds}
Отвечай строго одним JSON-объектом без пояснений вокруг, ключи — как выше:
{{{shape}}}
В `where` — коротко, где именно (верх, низ, левая створка и т.п.), либо пустая строка. Не называй товар и не оценивай красоту: только перечисленные виды брака.'''

# описание вида брака (что спрашиваем) — здесь; КОМУ спрашиваем (роли) и какие кадры — в rules
KINDS = {
    'invented_detail': ('выдуманная деталь: сначала перечисли в `details` каждую отдельную деталь на ТРЁХМЕРНОЙ МОДЕЛИ, которая выглядит как отдельный элемент (фигурка, кольцо, каркас, выступ, перекладина, коробка внутри прозрачной части), '
                        'и по каждой скажи `on_photo`: «да» — такая деталь видна на фото, «нет» — на фото её нет; `verdict` = «да», если есть хотя бы одна деталь с on_photo «нет»; простые крупные части предмета (корпус, ножки, спинка, дверцы) деталями не считай'),
    'ragged_facade': 'рваный или ступенчатый фасад/верх: на плоскости фасада дыры, зубчатые или ступенчатые края створок, рваный рельеф, которого на фото нет',
    'faceted': 'грани: гладкая округлая поверхность (ваза, абажур) показана плоскими гранями «плиткой» или многогранником, хотя на фото она гладкая',
    'back_copy': ('зад повторяет перёд: на кадрах «вид сзади/сбоку» задняя стенка выглядит копией лицевого фасада (тот же узор, те же створки и ручки) — у настоящего предмета такого типа сзади обычно гладкая или каркасная стенка; '
                  'отвечай по кадрам вида сзади, если их нет — «неясно»'),
    'no_gaps': 'фасад без щелей: ящики или двери на модели слиты в гладкую плиту, щели между ними едва видны или пропали, а на фото ящики/двери/щели между ними есть (если на фото фасад тоже гладкий — «нет»)',
    'count_mismatch': ('число дверей и ящиков не как на фото: СНАЧАЛА в `photo` перечисли по фото, сколько дверей и сколько ящиков в каждом столбце слева направо (например «двери 3; ящики: слева 2, середина 0, справа 2»), '
                       'потом так же в `model` по кадру модели; `verdict` = «да», если число дверей или раскладка/число ящиков различаются (лишние ящики, пропавшие двери, слитые в одну), иначе «нет»; рельеф и ручки не считай'),
    'skewed_body': 'перекос корпуса: углы корпуса не прямые, крышка или боковые стенки скошены/завалены, линии не параллельны, а на фото корпус прямоугольный (кадры модели сняты с перспективой: вертикали слегка сходятся кверху или книзу даже у идеальной коробки — это НЕ перекос; перекос — это завал стенки в одну сторону или явно непрямой угол крышки)',
}
FRAME_LABELS = {'01_az000_clay.png': 'модель, вид спереди', '02_az000_clay_graze.png': 'модель, вид спереди, боковой свет (тени в щелях)', '03_az090_clay.png': 'модель, вид сбоку',
                '05_az180_clay.png': 'модель, вид сзади', '07_az225_clay.png': 'модель, вид сзади-сбоку', '09_top40_clay.png': 'модель, вид сверху'}


def enc(im: Image.Image, side: int = 1024) -> str:
    im = im.convert('RGB')
    k = side / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=88)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()


def photo_on_grey(path: str) -> Image.Image:
    ph = Image.open(path).convert('RGBA')
    bg = Image.new('RGB', ph.size, (190, 190, 190))
    bg.paste(ph, mask=ph.getchannel('A'))
    return bg


def parse(txt: str, kinds: list[str]) -> dict:
    m = re.search(r'\{.*\}', txt, re.S)
    d = json.loads(m.group(0)) if m else {}
    out = {}
    for k in kinds:
        v = d.get(k, {})
        if isinstance(v, str):
            v = {'verdict': v, 'where': ''}
        if k == 'invented_detail' and isinstance(v.get('details'), list) and v['details']:
            nope = [x for x in v['details'] if isinstance(x, dict) and str(x.get('on_photo', '')).strip().lower() in ('нет', 'no')]
            v = dict(v, verdict='да' if nope else 'нет', where=v.get('where') or '; '.join(str(x.get('what', ''))[:30] for x in nope)[:120])
        verd = str(v.get('verdict', '')).strip().lower()
        if k == 'count_mismatch' and (v.get('photo') or v.get('model')):
            v = dict(v, where=f"фото: {str(v.get('photo', ''))[:60]}; модель: {str(v.get('model', ''))[:60]}")
        out[k] = {'verdict': {'да': 'yes', 'нет': 'no', 'неясно': 'unclear', 'yes': 'yes', 'no': 'no', 'unclear': 'unclear'}.get(verd, 'bad:' + verd), 'where': str(v.get('where', ''))[:120]}
    return out


def applicable(role: str, kinds: dict) -> list[str]:
    """Виды, которые спрашиваем для роли каталога (подстрока; пустой список ролей = все)."""
    r = (role or '').lower()
    return [k for k, c in kinds.items() if not c.get('roles') or any(x in r for x in c['roles'])]


def key_of(frames: bytes, photo: bytes, version: str, model: str, group: str, run: int) -> str:
    h = hashlib.sha256()
    for part in (frames, photo, version.encode(), model.encode(), group.encode(), str(run).encode()):
        h.update(hashlib.sha256(part).digest())
    return h.hexdigest()[:40]


def ask(sku: str, group: str, kinds: list[str], frames: list[str], photo: str, run: int, model: str, chat) -> dict:
    items = [('фото магазина', photo_on_grey(photo))] + [(FRAME_LABELS.get(os.path.basename(f), 'модель, кадр'), Image.open(f)) for f in frames]
    random.Random(f'{sku}:{run}:{group}').shuffle(items)
    order = '; '.join(f'изображение {i + 1} — {t}' for i, (t, _im) in enumerate(items))
    shape = ', '.join(('"%s": {"details": [{"what": "", "on_photo": "да|нет"}], "verdict": "да|нет|неясно", "where": ""}' % k) if k == 'invented_detail' else
                      ('"%s": {"photo": "", "model": "", "verdict": "да|нет|неясно", "where": ""}' % k) if k == 'count_mismatch' else ('"%s": {"verdict": "да|нет|неясно", "where": ""}' % k) for k in kinds)
    prompt = PROMPT.format(n=len(items), order=order, kinds='\n'.join(f'- {k}: {KINDS[k]}' for k in kinds), shape=shape)
    content = [{'type': 'text', 'text': prompt}] + [{'type': 'image_url', 'image_url': {'url': enc(im)}} for _t, im in items]
    r = chat(model, [{'role': 'user', 'content': content}], timeout=180, tries=4, direct_fallback=False, temperature=0)
    txt = r['choices'][0]['message']['content'] or ''
    u = r.get('usage', {})
    try:
        ans = parse(txt, kinds)
    except Exception as exc:                                             # noqa: BLE001 — сбой разбора не прячем: вид идёт как bad:parse
        ans = {k: {'verdict': 'bad:parse', 'where': str(exc)[:60]} for k in kinds}
    return {'answer': ans, 'usage': {'in': u.get('prompt_tokens'), 'out': u.get('completion_tokens')}, 'raw': txt[:1500]}


def call_cost(J: dict, gname: str) -> float:
    """Оценка цены ОДНОГО вызова группы кадров, $: токены на вызов (замер по кэшу ответов) × цена модели из rules `vlm_judge.cost`."""
    c = J.get('cost') or {}
    tin, tout = (c.get('tokens_per_call') or {}).get(gname, (2000, 2000))
    return (tin * float(c.get('usd_per_m_in', 0.30)) + tout * float(c.get('usd_per_m_out', 2.50))) / 1e6


def judge(sku: str, glb_path: str | None, photo: str, frames_dir: str, role: str, J: dict, cache_dir: str, chat=None, kinds_only: list[str] | None = None,
          budget: dict | None = None, log=None) -> list[dict]:
    """Проверки `vlm_<вид>` для формы (observe). Нет кадров/фото/ключа — отдельная проверка `vlm_judge` со значением None и причиной, не молчание."""
    from form_checks import check
    if chat is None:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
        import llm_gateway as LG
        chat = LG.chat
    kinds_cfg = J['kinds']
    want = [k for k in applicable(role, kinds_cfg) if kinds_only is None or k in kinds_only]
    if not want:
        return [check('vlm_judge', None, None, False, f'для роли «{role}» видов нет')]
    if not (photo and os.path.isfile(photo)):
        return [check('vlm_judge', None, None, False, 'нет фото')]
    ph = open(photo, 'rb').read()
    os.makedirs(cache_dir, exist_ok=True)
    out: list[dict] = []
    for gname, g in J['groups'].items():
        kinds = [k for k in want if kinds_cfg[k]['group'] == gname]
        if not kinds:
            continue
        frames = [os.path.join(frames_dir, f) for f in g['frames']]
        miss = [os.path.basename(f) for f in frames if not os.path.isfile(f)]
        if miss:
            out.append(check(f'vlm_{gname}', None, None, False, f'нет кадров {miss}'))
            continue
        fb = b''.join(hashlib.sha256(open(f, 'rb').read()).digest() for f in frames)
        fps = [os.path.join(cache_dir, key_of(fb, ph, J['version'], J['model'], gname + ','.join(kinds), run) + '.json') for run in range(int(J['runs']))]
        todo = sum(1 for fp in fps if not os.path.isfile(fp))
        est = todo * call_cost(J, gname)
        if todo and (log or budget is not None):                                  # оценка расхода — строкой в лог ДО платного вызова (правило директора 22.11)
            line = f"vlm {sku} группа {gname}: вызовов не из кэша {todo} × ≈${call_cost(J, gname):.4f} = ≈${est:.4f}" + (f" · осталось ≈${budget['left']:.4f} из ${budget['limit']:.4f}" if budget is not None else '')
            (log or print)(line)
        if budget is not None and est > budget['left'] + 1e-12:                 # потолок: группу не берём (половина голосов не голос), не ошибка — отдельный флаг
            budget['skipped'] = budget.get('skipped', 0) + 1
            out.append(check('vlm_skipped_budget', round(est, 4), round(budget['left'], 4), True, f"группа {gname} не оценена: нужно ≈${est:.4f}, осталось ≈${budget['left']:.4f} из потолка ${budget['limit']:.4f} — показать глазам"))
            continue
        if budget is not None:
            budget['left'] -= est
            budget['spent'] = budget.get('spent', 0.0) + est
        runs = []
        for run in range(int(J['runs'])):
            fp = fps[run]
            if os.path.isfile(fp):
                rec = json.load(open(fp, encoding='utf-8'))
            else:
                rec = ask(sku, gname, kinds, frames, photo, run, J['model'], chat)
                json.dump(rec, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            runs.append(rec['answer'])
        for k in kinds:
            yes = sum(1 for a in runs if a[k]['verdict'] == 'yes')
            need = int(J.get('yes_min', len(runs)))                          # голос: «да» минимум в need прогонах из runs (правило; по умолчанию во всех)
            where = next((a[k]['where'] for a in runs if a[k]['verdict'] == 'yes' and a[k]['where']), '')
            out.append(check(f'vlm_{k}', yes, need, yes >= need, f"«да» в {yes} из {len(runs)} прогонов (нужно {need})" + (f': {where}' if where else '')))
            lo = int(J.get('check_min_yes', 1))                             # второй уровень: «да» хотя бы в lo прогонах — «на глаз» (вердикт не ставит, в block не идёт)
            out.append(check(f'vlm_{k}_check', yes, lo, yes >= lo, (f"«да» в {yes} из {len(runs)} прогонов — показать глазам" + (f': {where}' if where else '')) if yes >= lo else f"«да» в {yes} из {len(runs)} прогонов"))
    return out
