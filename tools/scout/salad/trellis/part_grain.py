#!/usr/bin/env python3
"""Зерно дерева на части — шаг после тона Ш4а (T-20261124-69/4; план paint-material-01). ВЫКЛЮЧЕНО (`rules/part-grain.json` → enabled=false): ни одного байта текстуры не трогает.

ЗАЧЕМ. Тон Ш4а — ровная заливка части. У деревянных частей на фото виден рисунок волокон: ровная заливка выглядит пластиком. Здесь на ровный тон кладётся узор ТОЛЬКО по светлоте L
(a/b не трогаем: цветная крапка при бледном тоне — причина «серо-сирени», T-69/3); цвет и средняя светлота части остаются теми, что задал тон.

ЧТО ДЕЛАЕТ (общее правило, без ID и имён товаров; пороги — `rules/part-grain.json`):
  1. `plan_grain` — решение по каждой части: дерево (по карточке/имени части или флагом вызывающего) · тон ровный (σL ≤ even_tone_sigma_max) · ≥ min_texels · бин библиотеки по тону
     · АМПЛИТУДА с двумя предохранителями: (1) потолок amp_max; (2) зерно по фото только при высокочастотной σL фото ≥ photo_sigma_min, иначе амплитуда = медиана амплитуд соседних частей
     этого же товара с видимым рисунком, а их нет → зерна нет. Отказ записывается причиной (счётчик в отчёте, молчаливых пропусков нет).
  2. `apply_grain` — узор в текстуру: ось зерна по плоскости (`parts_role_planes.merge_planes`; круглая плита — ось ширины товара), плитка по `tile_cm` бина, два слоя шагов, сдвиг/зеркало
     по хэшу плоскости, только L; меняются ТОЛЬКО тексели маски части.
  Вход для Ш4а: маска части (bool по текселям `tx.ti`) + тон Lab части; всё остальное — в `parts[i]`.
  Заливка непокрытых текселей — НЕ здесь (код 07/08, T-70 `texel_pad`).

  python3 tests_part_grain.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'part-grain.json')

import tex_coverage as TC  # noqa: E402
import top_prior as TP  # noqa: E402


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as fh:
        r = json.load(fh)
    if not (0 < r['amp_min'] < r['amp_max'] <= 1.0):
        raise ValueError('part-grain.json: amp_min/amp_max вне пределов (0 < min < max ≤ 1)')
    if not (0 < r['photo_sigma_min'] < 10) or not (0 < r['even_tone_sigma_max'] < 20) or r['min_texels'] < 1 or r['round_ratio'] < 1.0:
        raise ValueError('part-grain.json: пороги вне допустимых пределов')
    if not (0.0 <= float(r.get('amp_floor_L') or 0.0) < 20.0):
        raise ValueError('part-grain.json: amp_floor_L вне пределов (0 = выкл … 20 L)')
    wa = r.get('wood_always')
    if wa and wa.get('enabled'):                                  # T-97/1 ф.5: проверка только при включении (выкл — ключ не читается)
        need = ('colourless_chroma_max', 'reserve_sigma_L', 'reserve_sigma_strong_L', 'reserve_amp_max', 'photo_classes', 'fallback_fields', 'not_wood_words', 'solid_extra_words',
                'strong_species', 'weak_species', 'strong_top_div', 'calm_sigma_max', 'calm_directionality_min', 'calm_low_freq_max')
        miss = [k for k in need if k not in wa]
        if miss:
            raise ValueError('part-grain.json: wood_always без ключей %s' % miss)
        if not (0 < float(wa['reserve_sigma_L']) <= float(wa['reserve_sigma_strong_L']) < 20) or not (0 < float(wa['reserve_amp_max']) <= 10) or int(wa['strong_top_div']) < 1:
            raise ValueError('part-grain.json: wood_always — размах запаса/потолок/доля вне пределов')
    tp = r.get('thin_plate')
    if tp and tp.get('enabled'):                                  # T-97/1 ф.7: проверка только при включении (выкл — ключ не читается)
        import thin_plate as TPL
        TPL.check_rules(tp)
    if len(r['tile_layers']) < 1 or len(r['no_tile_layers']) < 1:
        raise ValueError('part-grain.json: нужен хотя бы один слой шага')
    return r


# ------------------------------------------------------------------ материал части ----------------------------------------------------------------
def part_is_wood(name: str, card: dict | None, rules: dict, role: str | None = None) -> bool:
    """Дерево ли часть по карточке и имени части (для Ш4а, если у него нет своего решения). Ножки/стойки — по «Материал ножек»; обивка/ручки/лампа/клавиши — не дерево; корпус/фасад/столешница — по их словам."""
    n = (name or '').lower()
    card = card or {}
    if role:                                   # роль р.1 (top/legs/facade/side/back/body — выход Ш4а): ножки — по «Материал ножек», остальное — корпус/фасад/столешница
        keys = rules['leg_card_keys'] if role == 'legs' else rules['wood_card_keys']
        t = ' '.join(str(v).lower() for k, v in card.items() if any(s_ in k.lower() for s_ in keys))
        return any(w in t for w in rules['wood_words'])
    txt = lambda keys: ' '.join(str(v).lower() for k, v in card.items() if any(s in k.lower() for s in keys))  # noqa: E731
    if any(w in n for w in rules['non_wood_part_words']):
        return False
    t = txt(rules['leg_card_keys']) if any(w in n for w in rules['leg_part_words']) else txt(rules['wood_card_keys'])
    return any(w in t for w in rules['wood_words'])


# ------------------------------------------------------------------ фото: высокочастотная σL ------------------------------------------------------
def photo_hf_sigma(L_frame, mask, rules: dict):
    """σL «зерна» на фото части: из L вычтено сглаживание по маске части (окно photo_hf_window_px) — плавный свет/тень рисунком не считается. → float | None (мало пикселей).
    L_frame — (h,w) светлота кадра фото в системе кадра 04, mask — (h,w) bool пикселей этой части."""
    import cv2
    w = int(rules['photo_hf_window_px'])
    Lf = np.asarray(L_frame, np.float32)
    mm = np.asarray(mask, bool)
    mf = mm.astype(np.float32)
    num = cv2.blur(Lf * mf, (w, w))
    den = cv2.blur(mf, (w, w))
    ok = mm & (den > 0.6)
    if int(ok.sum()) < int(rules['photo_hf_min_px']):
        return None
    res = Lf[ok] - num[ok] / den[ok]
    return float(1.4826 * np.median(np.abs(res - np.median(res))))


# ------------------------------------------------------------------ бин и узор ---------------------------------------------------------------------
_LIB_CACHE: dict = {}


def _library(tp_rules: dict) -> dict:
    p = os.path.join(ROOT, tp_rules['library'])
    if p not in _LIB_CACHE:
        with open(p, encoding='utf-8') as fh:
            _LIB_CACHE[p] = json.load(fh)
    return _LIB_CACHE[p]


def load_pattern(tone_lab, rules: dict, classes: list | None = None):
    """Бин библиотеки по тону → (описание бина, узор L (m,m) float, нулевое среднее, бесшовный, ось по бину; σL узора). Нет бина/flat → (описание, None, 0.0)."""
    tp = TP.load_rules()
    lib = _library(tp)
    b = TP.library_bin(tone_lab, 'library', lib, dict(tp, library_max_de00=rules['library_max_de00']), None, classes)
    if b.get('bin') in (None, 'flat'):
        return b, None, 0.0
    pat, std = pattern_of_bin(b['bin'], b.get('grain_axis'))
    return b, pat, std


def pattern_of_bin(name: str, grain_axis: str | None) -> tuple:
    """Узор L одного бина библиотеки по имени (нулевое среднее, бесшовный, ось по бину) → (узор (512,512), σL узора). Одно место для `load_pattern` и для запасного бина `plan_wood_always`."""
    from PIL import Image
    tp = TP.load_rules()
    path = os.path.join(ROOT, tp['library_pat'], name + '.jpg')
    im = np.asarray(Image.open(path).convert('RGB').resize((512, 512)), np.uint8)
    L = TC.rgb2lab(im.reshape(-1, 3)).reshape(512, 512, 3)[:, :, :1].astype(np.float64)
    pat = L - L.reshape(-1, 1).mean(0)
    pat = np.concatenate([pat, np.zeros_like(pat), np.zeros_like(pat)], axis=2)       # узор только по L
    pat = TP.seamless_pattern(pat, tp['pattern'].get('seam_overlap', 0.0))
    pat = pat[:, :, 0]
    if grain_axis == 'v':
        pat = pat.T
    pat = pat - pat.mean()
    return np.ascontiguousarray(pat), float(pat.std())


# ------------------------------------------------------------------ решение по частям ---------------------------------------------------------------
def plan_grain(parts: list, rules: dict | None = None) -> dict:
    """Решение по каждой части. parts[i] = {'id', 'name', 'is_wood' (bool; нет — по part_is_wood с 'card'), 'tone_lab', 'tone_sigma' (σL тона внутри части), 'n_texels',
    'photo_sigma' (float | None), 'card' (dict | None), 'classes' (классы бина | None)}. → {id: {'apply': bool, 'reason': str, 'bin', 'amp', 'amp_source', 'pat', 'pat_std'}}.
    Амплитуда: фото-доказательство (σ ≥ photo_sigma_min) → σ/σ_узора в [amp_min, amp_max]; иначе — медиана амплитуд частей с доказательством; их нет → 'no_photo_evidence'."""
    rules = rules or load_rules()
    if (rules.get('wood_always') or {}).get('enabled'):          # T-97/1 фаза 5 (TG 3039): деревянная деталь — волокно всегда; выкл (по умолчанию) — ни одной строки ниже функции не выполняется
        return plan_wood_always(parts, rules)
    out: dict = {}
    evid: dict = {}
    mres = None
    if (rules.get('pattern_measure') or {}).get('enabled'):          # T-20261125-93/3: мера «есть рисунок» / «узор» (выкл по умолчанию; выкл — ни одной строки ниже не выполняется)
        import part_grain_measure as PM
        mres = PM.resolve_patterns(parts, rules)
    for p in parts:
        pid = p['id']
        rec = {'apply': False, 'reason': None, 'bin': None, 'amp': None, 'amp_source': None, 'pat': None, 'pat_std': 0.0}
        out[pid] = rec
        wood = p.get('is_wood')
        if wood is None:
            wood = part_is_wood(p.get('name', ''), p.get('card'), rules)
        if not wood:
            rec['reason'] = 'not_wood'
            continue
        if str(p.get('name', '')) in (rules.get('no_grain_groups') or []):      # группа без зерна по решению вызывающего (на фото рисунка нет — плита/пластик; Fable 25.11: «ровная по паспорту → ровный тон»)
            rec['reason'] = 'no_grain_group'
            continue
        if int(p.get('n_texels', 0)) < rules['min_texels']:
            rec['reason'] = 'too_small'
            continue
        if p.get('tone_lab') is None or p.get('tone_sigma') is None:
            rec['reason'] = 'no_tone'
            continue
        if float(p['tone_sigma']) > rules['even_tone_sigma_max']:
            rec['reason'] = 'tone_not_even'          # градиент Ш4а — зерно поверх градиента отдельной задачей
            continue
        if mres is not None:
            m_ = mres[pid]
            rec['measure'] = {k: m_[k] for k in ('decision', 'path', 'why', 'verdict', 'from', 'field') if k in m_}
            if m_['decision'] != 'fiber':
                rec['reason'] = 'measure_flat'      # «узор» / «нет» / наследование / карточка-плита: библиотечное волокно не кладём, тон остаётся ровным
                continue
        b, pat, pstd = load_pattern(p['tone_lab'], rules, p.get('classes'))
        rec['bin'] = {k: b.get(k) for k in ('bin', 'dE00', 'tile_cm', 'grain_axis')}
        if pat is None:
            rec['reason'] = 'no_bin'
            continue
        rec['pat'], rec['pat_std'] = pat, pstd
        ps = p.get('photo_sigma')
        if ps is not None and float(ps) >= rules['photo_sigma_min']:
            amp = float(np.clip(float(ps) / max(pstd, 1e-6), rules['amp_min'], rules['amp_max']))
            rec.update(amp=amp, amp_source='photo')
            evid[pid] = amp
    med = float(np.median(list(evid.values()))) if evid else None
    for p in parts:
        rec = out[p['id']]
        if rec['pat'] is None or rec['reason'] is not None:
            continue
        if rec['amp_source'] is None:
            if med is None or not rules.get('amp_from_neighbors', True):      # Fable 25.11 19:13: «зерно везде или нигде» — амплитуда у соседа не доказательство для этой части; нет СВОЕГО фото-доказательства → ровный тон (флаг amp_from_neighbors=false)
                rec['reason'] = 'no_photo_evidence'
                rec['pat'] = None
                continue
            rec.update(amp=float(np.clip(med, rules['amp_min'], rules['amp_max'])), amp_source='neighbors')
        rec.update(apply=True, reason='ok')
        fl = float(rules.get('amp_floor_L') or 0.0)             # T-97/1 фаза 4 (вариант А, шаг 8): пол размаха зерна в единицах L; 0 = выкл (амплитуда как была)
        if fl > 0 and rec['amp'] is not None:
            sig = rec['amp'] * max(rec['pat_std'], 1e-6)         # σL, которую даст узор бина при этой амплитуде
            rec['floor'] = {'L': fl, 'sigma_before': round(float(sig), 3), 'raised': bool(sig < fl)}
            if sig < fl:
                rec['amp'] = float(min(fl / max(rec['pat_std'], 1e-6), 1.0))
                rec['amp_source'] = str(rec['amp_source']) + '+floor'
    return out


# ------------------------------------------------------------------ дерево — волокно всегда (T-97/1 фаза 5, слово владельца TG 3039; проба р.5 t94/fiber_grain.py) ----------------------------
def _wood_rules(rules: dict) -> tuple:
    """(правила ветки wood_always, правила меры материала из pattern_measure). Слова материала/породы/обивки — ОДИН источник: `pattern_measure` (T-93); в файле правил его нет (замороженные rules-g) — берём из rules/part-grain.json."""
    wa = rules['wood_always']
    pm = rules.get('pattern_measure') or load_rules()['pattern_measure']
    return wa, pm


def _straight_rows(wa: dict) -> tuple:
    """Бины straight семейства «дерево» с разметкой библиотеки (`grain_marks`: σ узора, доля низких частот, направленность — пишет part_grain_marks.py) → (библиотека, [(σ, имя, низких, направленность)] по возрастанию σ)."""
    lib = _library(TP.load_rules())
    rows = []
    for name, v in lib['items'].items():
        if v.get('family', 'wood') != 'wood' or v.get('pattern_class', 'straight') not in wa['photo_classes']:
            continue
        m = v.get('grain_marks')
        if not m:
            raise ValueError('library.json: у бина %s нет grain_marks — запустить tools/scout/salad/trellis/part_grain_marks.py и закоммитить файл' % name)
        rows.append((float(m['sigma_L']), name, float(m['low_freq']), float(m['directionality'])))
    rows.sort()
    return lib, rows


def _nearest_bin(lib: dict, names: list, tone_lab):
    return min(names, key=lambda n: TP._de(tone_lab, lib['items'][n]['lab']))


def _pick_reserve(species_text: str, tone_lab, lib: dict, rows: list, wa: dict) -> tuple:
    """Запасной бин, когда фото молчит и материала-соседа нет: порода дуб/ясень → «выраженный» (верхняя треть straight по σ узора, ближайший по тону), бук/берёза/сосна… → «спокойный»
    (σ ≤ calm_sigma_max, направленность ≥ calm_directionality_min, низких частот ≤ calm_low_freq_max — без пятен и сучков; ближайший по тону), порода не названа → самый спокойный (наименьшая доля низких частот).
    → (имя бина, σL-цель, пометка)."""
    k = max(1, len(rows) // int(wa['strong_top_div']))
    toks = ' '.join(re.findall(r'[а-яёa-z]+', species_text.lower()))
    if any(w in toks for w in wa['strong_species']):
        return _nearest_bin(lib, [r[1] for r in rows[-k:]], tone_lab), float(wa['reserve_sigma_strong_L']), 'порода выраженная (дуб/ясень)'
    calm = [r for r in rows if r[0] <= wa['calm_sigma_max'] and r[3] >= wa['calm_directionality_min'] and r[2] <= wa['calm_low_freq_max']]
    note_none = ''
    if not calm:                                                    # разметка не оставила спокойных — самый слабый по σ, с пометкой (честно, не падаем)
        calm, note_none = rows[:1], ' (спокойных бинов нет — самый слабый)'
    if any(w in toks for w in wa['weak_species']):
        return _nearest_bin(lib, [r[1] for r in calm], tone_lab), float(wa['reserve_sigma_L']), 'порода слабая (бук/берёза/сосна): спокойный мелкий прямой, ближайший по тону' + note_none
    return min(calm, key=lambda r: (r[2], r[0]))[1], float(wa['reserve_sigma_L']), 'порода не названа — самый спокойный мелкий прямой (без пятен)' + note_none


def _wood_class(rf: dict, extra: str, pm: dict, wa: dict) -> tuple:
    """Класс материала части по тексту поля карточки роли: дерево / не_дерево / плита / не_назван."""
    import part_grain_measure as PGM
    text = (rf['text'] + ' ' + extra).strip()
    solid = any(w in text for w in pm['solid_words']) or PGM.has_decor(text, pm) or any(w in text for w in wa['solid_extra_words'])
    if solid:
        return 'дерево', 'материал: ' + text[:60]
    if PGM.has_decor(rf['color_text'], pm):
        return 'дерево', 'порода в поле цвета: ' + rf['color_text'][:40]
    if any(w in text for w in wa['not_wood_words']) or PGM.has_upholstery(text, pm):
        return 'не_дерево', 'материал: ' + text[:60]
    if any(w in text for w in pm['board_words']):
        return 'плита', 'материал: ' + text[:60]
    return 'не_назван', 'материала нет в карточке'


def plan_wood_always(parts: list, rules: dict) -> dict:
    """Решение по частям при rules.wood_always.enabled (вместо `plan_grain` по умолчанию): ДЕРЕВО определяет карточка по роли детали (поле роли; нет — запасные поля fallback_fields), волокно на дереве — ВСЕГДА,
    ровный тон — только не-дерево / бесцветная деталь без волокна на фото / плита / материал не назван. Фото решает «какое и сколько»: σL фото ≥ photo_sigma_min → бин класса straight по тону (лимит library_max_de00; дальше — ближайший без лимита),
    амплитуда σ_фото/σ_бина в [amp_min, amp_max], пол amp_floor_L. Фото молчит → размах ТОГО ЖЕ материала на товаре (группа с тем же текстом материала и фото-доказательством: её σ_фото переносится, бин — по тону группы),
    иначе запас по породе (`_pick_reserve`): размах reserve_sigma_L (дуб/ясень — reserve_sigma_strong_L), не ниже пола, амплитуда не выше reserve_amp_max. Ось зерна — как в `apply_grain` (ось детали, rules.axis_per_part).
    След: у группы `wood` {role, field, material_text, class, why, photo_sigma, tone_L_C, decision, source, sigma_applied, ...}. Решения (потолок запаса, «спокойные» бины, straight) — кандидаты проб р.5, см. _about в rules."""
    import part_grain_measure as PGM
    wa, pm = _wood_rules(rules)
    prm = dict(rules, pattern_measure=pm)
    lib, rows = _straight_rows(wa)
    names = [r[1] for r in rows]
    fl = float(rules.get('amp_floor_L') or 0.0)
    out, info, mkey, ev = {}, {}, {}, {}
    for p in parts:                                                   # 1) класс материала по роли
        pid = p['id']
        role, _src = PGM.part_role(p, prm)
        rf = PGM.role_field(p.get('card'), role, prm)
        extra, ff = '', []
        if rf['status'] != 'ok':                                      # поля роли нет: общий «Основной материал»/«Материал каркаса» как запасные поля (без «цвет»)
            h = [(k, v) for k, v in (p.get('card') or {}).items() if any(s in k.lower() for s in wa['fallback_fields'])]
            extra, ff = ' '.join(str(v).lower() for k, v in h if 'цвет' not in k.lower()), [k for k, _ in h]
        cls, why = _wood_class(rf, extra, pm, wa)
        mkey[pid] = ' '.join(sorted(re.findall(r'[а-яёa-z]+', (rf['text'] + ' ' + extra).lower())))
        ps = p.get('photo_sigma')
        info[pid] = {'role': role, 'field': rf['status'] + ('+запасное поле ' + ','.join(ff) if ff else ''), 'fields': rf['fields'] or ff, 'material_text': (rf['text'] + ' ' + extra).strip(),
                     'color_text': rf['color_text'], 'class': cls, 'why': why, 'photo_sigma': None if ps is None else round(float(ps), 2)}
    for p in parts:                                                   # 2) решение по группе (с фото-доказательством)
        pid = p['id']
        w = info[pid]
        rec = {'apply': False, 'reason': None, 'bin': None, 'amp': None, 'amp_source': None, 'pat': None, 'pat_std': 0.0, 'wood': w}
        out[pid] = rec
        tone = p.get('tone_lab')
        if tone is None or p.get('tone_sigma') is None:
            rec['reason'], w['decision'] = 'no_tone', 'ровно: нет тона'
            continue
        chroma = float(np.hypot(tone[1], tone[2]))
        w['tone_L_C'] = [round(float(tone[0]), 1), round(chroma, 1)]
        if w['class'] == 'не_назван':
            rec['reason'], w['decision'], w['source'] = 'material_not_named', 'ровно: материал не назван', 'не назван'
            continue
        if w['class'] != 'дерево':
            rec['reason'], w['decision'] = 'not_wood', 'ровно: ' + w['class']
            continue
        if str(p.get('name', '')) in (rules.get('no_grain_groups') or []):
            rec['reason'], w['decision'] = 'no_grain_group', 'ровно: группа без зерна по решению вызывающего'
            continue
        if int(p.get('n_texels', 0)) < rules['min_texels']:
            rec['reason'], w['decision'] = 'too_small', 'ровно: мало текселей'
            continue
        if float(p['tone_sigma']) > rules['even_tone_sigma_max']:
            rec['reason'], w['decision'] = 'tone_not_even', 'ровно: градиент тона'
            continue
        ps = p.get('photo_sigma')
        sees = ps is not None and float(ps) >= rules['photo_sigma_min']
        if not sees and chroma < float(wa['colourless_chroma_max']):   # «массив» бесцветный и фото волокна не показывает — деталь крашеная, ровно
            rec['reason'], w['decision'], w['source'] = 'colourless_no_photo', 'ровно: бесцветный тон, фото волокна не показывает', 'бесцветный'
            continue
        if not sees:
            w['_need'] = True
            continue
        b, pat, pstd = load_pattern(tone, rules, wa['photo_classes'])
        note = ''
        if pat is None:                                               # бин дальше лимита ΔE00 — ближайший straight без лимита, с пометкой
            near = b.get('nearest')
            nm = near if near in names else _nearest_bin(lib, names, tone)
            pat, pstd = pattern_of_bin(nm, lib['items'][nm].get('grain_axis'))
            v = lib['items'][nm]
            b = {'bin': nm, 'dE00': round(float(TP._de(tone, v['lab'])), 1), 'tile_cm': v.get('tile_cm'), 'grain_axis': v.get('grain_axis')}
            note = 'бин дальше лимита — ближайший без лимита'
        amp = float(np.clip(float(ps) / max(pstd, 1e-6), rules['amp_min'], rules['amp_max']))
        ev[pid] = float(ps)
        raised = False
        if fl > 0 and amp * pstd < fl:
            amp, raised = float(min(fl / max(pstd, 1e-6), 1.0)), True
        rec.update(bin={k: b.get(k) for k in ('bin', 'dE00', 'tile_cm', 'grain_axis')}, pat=pat, pat_std=pstd, amp=amp, amp_source='photo' + ('+floor' if raised else ''), apply=True, reason='ok')
        w.update(decision='волокно', source='фото' + (' (' + note + ')' if note else ''), sigma_applied=round(amp * pstd, 2), floor_raised=raised)
    for p in parts:                                                   # 3) фото молчит: тот же материал на товаре → запас по породе
        pid = p['id']
        w = info[pid]
        if not w.pop('_need', False):
            continue
        rec, tone = out[pid], p['tone_lab']
        sib = [q for q in ev if q != pid and mkey[q] and mkey[q] == mkey[pid]]
        if sib:
            sig_t = float(np.median([ev[q] for q in sib]))
            nm, src, note = _nearest_bin(lib, names, tone), 'material', 'материал (того же на товаре: группы %s)' % sib
        else:
            nm, sig_t, note = _pick_reserve(w['material_text'] + ' ' + w['color_text'], tone, lib, rows, wa)
            src, note = 'reserve', 'запас (' + note + ')'
        v = lib['items'][nm]
        pat, pstd = pattern_of_bin(nm, v.get('grain_axis'))
        sig_t = max(sig_t, fl)
        amp = float(min(sig_t / max(pstd, 1e-6), float(wa['reserve_amp_max'])))
        rec.update(bin={'bin': nm, 'dE00': round(float(TP._de(tone, v['lab'])), 1), 'tile_cm': v.get('tile_cm'), 'grain_axis': v.get('grain_axis')}, pat=pat, pat_std=pstd, amp=amp, amp_source=src, apply=True, reason='ok')
        w.update(decision='волокно', source=note, sigma_applied=round(amp * pstd, 2), sigma_target=round(sig_t, 2))
    return out


# ------------------------------------------------------------------ оси и узор по текселям ----------------------------------------------------------------
def hsh(x: int) -> int:
    return (int(x) * 2654435761 + 40503) % 4294967296


def sample_pat(pat, u_cm, s_cm, tile_cm, key: int, layers: list):
    """Узор по плоскости: слои разного шага, у каждого свой сдвиг и зеркало по `key` (хэш плоскости), сумма / sqrt(n) — решётки плитки нет. u — вдоль волокна, s — поперёк."""
    m = pat.shape[0]
    acc = 0.0
    for k, f in enumerate(layers):
        h = hsh(int(key) * 7 + k * 131)
        su, ss = (h % 1000) / 1000.0, ((h >> 10) % 1000) / 1000.0
        fu, fs = (-1.0 if (h >> 20) & 1 else 1.0), (-1.0 if (h >> 21) & 1 else 1.0)
        u = (fu * u_cm / (tile_cm[0] * f) + su) % 1.0
        s_ = (fs * s_cm / (tile_cm[1] * f) + ss) % 1.0
        acc = acc + pat[np.floor(s_ * m).astype(int) % m, np.floor(u * m).astype(int) % m]
    return acc / np.sqrt(len(layers))


def _unit(v, fallback):
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, np.float64)


def _plane_eig(q_cm, n_plane):
    """Собственные числа/векторы разброса текселей в плоскости с нормалью n_plane (по возрастанию; наименьшее ≈ 0 — нормаль). → (n, w, ev)."""
    n = _unit(n_plane, (0, 1, 0))
    q = np.asarray(q_cm, np.float64)
    q = q - q.mean(0)
    qp = q - (q @ n)[:, None] * n
    w, ev = np.linalg.eigh(np.cov(qp.T) if len(qp) > 3 else np.eye(3))
    return n, w, ev


def plane_axes(q_cm, n_plane, width_axis, rules: dict):
    """Оси зерна в плоскости с нормалью n_plane по текселям q_cm (N,3): c1 — вдоль волокна, c2 = n × c1. Вытянутая плоскость — длинная ось текселей; круглая/квадратная (отношение осей < round_ratio) —
    ось ширины товара (width_axis), спроецированная в плоскость. → (c1, c2, round_like)."""
    n, w, ev = _plane_eig(q_cm, n_plane)
    big, mid = float(w[2]), float(max(w[1], 1e-12))
    round_like = big / mid < rules['round_ratio']
    if round_like:
        wa = np.zeros(3) if width_axis is None else np.asarray(width_axis, np.float64)
        c1 = wa - (wa @ n) * n
        if np.linalg.norm(c1) < 1e-6:
            for ax in ((1, 0, 0), (0, 0, 1), (0, 1, 0)):
                c1 = np.asarray(ax, np.float64) - (np.asarray(ax, np.float64) @ n) * n
                if np.linalg.norm(c1) > 1e-6:
                    break
    else:
        c1 = ev[:, 2]
        c1 = c1 - (c1 @ n) * n
    c1 = _unit(c1, (1, 0, 0))
    c2 = _unit(np.cross(n, c1), (0, 0, 1))
    return c1, c2, round_like


def ang_diff180(a: float, b: float) -> float:
    """Разница направлений (без знака) в градусах, 0…90: ось — прямая, не стрелка."""
    d = abs(float(a) - float(b)) % 180.0
    return min(d, 180.0 - d)


def photo_grain_dir(L, sel, ac: dict, rules: dict) -> dict:
    """Направление волокон на фото по тензору структуры светлоты L в пикселях sel (кадр 04, y вниз). Края силуэта (erode_px) и мало пикселей — не берём.
    → {'n_px','coh','deg','hf'}: hf — σL рисунка (`photo_hf_sigma`; меньше photo_sigma_min — рисунка не видно, coh/deg = None); deg ∈ [0,180) — направление ВДОЛЬ волокон в кадре (atan2(dy,dx)), coh 0…1 — насколько одно направление (0 — шум/без рисунка)."""
    from scipy import ndimage as ndi
    L = np.asarray(L, np.float64)
    sel = ndi.binary_erosion(np.asarray(sel, bool), iterations=int(ac['erode_px']))
    n = int(sel.sum())
    if n < int(ac['min_px']):
        return {'n_px': n, 'coh': None, 'deg': None}
    hf = photo_hf_sigma(L, sel, rules)                                                         # то же «рисунок виден», что у самого зерна (photo_sigma_min): одно определение
    if hf is None or hf < float(rules['photo_sigma_min']):
        return {'n_px': n, 'coh': None, 'deg': None, 'hf': None if hf is None else round(hf, 2)}   # рисунка на фото не видно — подсказки нет
    Ls = ndi.gaussian_filter(L, float(ac['sigma_px'])) - ndi.gaussian_filter(L, float(ac['dog_sigma_px']))      # направление — по масштабу рисунка: плавный свет и тень не волокна
    gy, gx = np.gradient(Ls)
    jxx, jyy, jxy = float((gx[sel] ** 2).mean()), float((gy[sel] ** 2).mean()), float((gx[sel] * gy[sel]).mean())
    tr = jxx + jyy
    if tr < 1e-9:
        return {'n_px': n, 'coh': 0.0, 'deg': None}
    coh = float(np.hypot(jxx - jyy, 2 * jxy) / tr)
    phi = 0.5 * np.degrees(np.arctan2(2 * jxy, jxx - jyy))                 # направление градиента (поперёк волокон)
    return {'n_px': n, 'coh': round(coh, 3), 'deg': round(float((phi + 90.0) % 180.0), 1), 'hf': round(hf, 2)}


def plane_axis_img_deg(Pc, xy_c, w, c1) -> float | None:
    """Куда в кадре смотрит ось c1 плоскости: наклон регрессии координат кадра (x, y) на положение точек вдоль c1 (центры граней плоскости Pc, веса w — их площади). → угол, ° ∈ [0,180)."""
    Pc, xy_c, w = np.asarray(Pc, np.float64), np.asarray(xy_c, np.float64), np.asarray(w, np.float64)
    if len(Pc) < 3 or float(w.sum()) <= 0:
        return None
    u = Pc @ np.asarray(c1, np.float64)
    wu = w / w.sum()
    um = float((wu * u).sum())
    var = float((wu * (u - um) ** 2).sum())
    if var < 1e-14:
        return None
    dx = float((wu * (u - um) * (xy_c[:, 0] - (wu * xy_c[:, 0]).sum())).sum() / var)
    dy = float((wu * (u - um) * (xy_c[:, 1] - (wu * xy_c[:, 1]).sum())).sum() / var)
    if abs(dx) + abs(dy) < 1e-12:
        return None
    return float(np.degrees(np.arctan2(dy, dx)) % 180.0)


def axis_verdict(round_like: bool, photo: dict, axis_deg, ac: dict) -> dict:
    """Решение проверки «ось зерна верха» (паспорт р. «круглая/квадратная плита»): подсказка фото есть (n_px ≥ min_px и coh ≥ coh_min) → ось должна совпасть с волокнами фото (≤ max_deg);
    подсказки нет → круглая/квадратная плита (ось не из формы) получает навязанный рисунок = флаг; вытянутая плита — ось по длинной стороне, не флаг. → {'verdict','would_flag','d_deg'}."""
    if int(photo.get('n_px') or 0) < int(ac['min_px']):
        return {'verdict': 'not_visible', 'would_flag': False, 'd_deg': None}                  # плоскость на фото не видна (оборот, низ): подсказки нет и быть не может, зерно на неё — не по фото
    hint = photo.get('coh') is not None and photo.get('deg') is not None and float(photo['coh']) >= float(ac['coh_min'])
    if hint and axis_deg is not None:
        d = ang_diff180(photo['deg'], axis_deg)
        bad = d > float(ac['max_deg'])
        return {'verdict': 'axis_off_photo' if bad else 'axis_ok_photo', 'would_flag': bool(bad), 'd_deg': round(d, 1)}
    if round_like:
        return {'verdict': 'imposed_no_hint', 'would_flag': True, 'd_deg': None}
    return {'verdict': 'long_side_no_hint', 'would_flag': False, 'd_deg': None}


def axis_check_plane(q, nn_plane, c1, round_like: bool, ctx: dict, faces, ac: dict, rules: dict) -> dict:
    """Одна плоскость части: форма (отношение осей), подсказка фото, куда смотрит ось в кадре, решение. ctx — из `part_grain_stage` (L кадра, id граней растра, годные пиксели, xy вершин, P, F)."""
    _n, w3, _ev = _plane_eig(q, nn_plane)
    ratio = float(w3[2]) / float(max(w3[1], 1e-12))
    fs = np.unique(np.asarray(faces))
    F = np.asarray(ctx['F'], np.int64)[fs]
    Pc = np.asarray(ctx['P'], np.float64)[F].mean(1)
    xy = np.asarray(ctx['xy'], np.float64)[F].mean(1)
    a, b, c = (np.asarray(ctx['P'], np.float64)[F[:, i]] for i in range(3))
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pix = np.asarray(ctx['valid'], bool) & np.isin(np.asarray(ctx['ids']), fs)
    photo = photo_grain_dir(ctx['L'], pix, ac, rules)
    axis_deg = plane_axis_img_deg(Pc, xy, area, c1)
    v = axis_verdict(round_like, photo, axis_deg, ac)
    return {'ratio': round(ratio, 3), 'round_like': bool(round_like), 'photo_deg': photo['deg'], 'photo_coh': photo['coh'], 'photo_px': photo['n_px'],
            'photo_hf': photo.get('hf'), 'axis_deg': None if axis_deg is None else round(axis_deg, 1), **v}


def apply_grain(tex, tx, parts: list, masks: dict, face_plane, plane_normal, cm_per_unit: float | None, width_axis=None, rules: dict | None = None, enabled: bool | None = None, plan: dict | None = None, axis_ctx: dict | None = None, face_part=None):
    """Зерно на текстуру. tex — (H,W,3) uint8 после тона Ш4а; tx — растр развёртки (`tex_fill.Tex`: ti, Q, N, f); parts — как в `plan_grain` (+ 'id'); masks[id] — bool по текселям tx
    (какие тексели части красить: маска части ∩ «тон Ш4а лёг»); face_plane — (m,) id плоскости на грань (−1 — не плоскость), plane_normal — (k,3); cm_per_unit — см на единицу кадра;
    width_axis — ось ширины товара (кадр 04). → (новая текстура, отчёт). Выключено (rules.enabled / enabled=False) → (tex БЕЗ изменений, отчёт enabled=False)."""
    rules = rules or load_rules()
    on = rules['enabled'] if enabled is None else bool(enabled)
    rep = {'enabled': on, 'parts': {}, 'applied': 0, 'skipped': {}, 'texels_changed': 0}
    if not on:
        return tex, rep
    import tex_fill as TF
    plan = plan if plan is not None else plan_grain(parts, rules)
    out = np.array(tex, copy=True)
    flat = out.reshape(-1, 3)
    scale = float(cm_per_unit or 100.0)
    fpt = np.asarray(face_plane)[tx.f]
    for p in parts:
        pid = p['id']
        d = plan[pid]
        r = {'apply': d['apply'], 'reason': d['reason'], 'bin': d['bin'], 'amp': None if d['amp'] is None else round(d['amp'], 3), 'amp_source': d['amp_source']}
        if d.get('measure') is not None:
            r['measure'] = d['measure']
        if d.get('floor') is not None:                           # пол включён (T-97/1 ф.4): что дала амплитуда до пола и поднят ли размах
            r['floor'] = d['floor']
        if d.get('wood') is not None:                            # «дерево — волокно всегда» (T-97/1 ф.5): класс материала, поле карточки, источник размаха
            r['wood'] = d['wood']
        rep['parts'][pid] = r
        if not d['apply']:
            rep['skipped'][d['reason']] = rep['skipped'].get(d['reason'], 0) + 1
            continue
        sel = np.asarray(masks[pid], bool)
        if not sel.any():
            r.update(apply=False, reason='empty_mask')
            rep['skipped']['empty_mask'] = rep['skipped'].get('empty_mask', 0) + 1
            continue
        tc = (d['bin'] or {}).get('tile_cm') or [0, 0]
        if tc[0] and tc[1]:
            tile, layers = (float(tc[0]), float(tc[1])), rules['tile_layers']
        else:
            tile, layers = tuple(rules['fallback_tile_cm']), rules['no_tile_layers']
        tone = np.asarray(p['tone_lab'], np.float64)
        qall = tx.Q[sel] * scale
        # части без значимой плоскости — главные оси текселей части (трёхосный запасной путь)
        w3, ev3 = np.linalg.eigh(np.cov((qall - qall.mean(0)).T))
        a1, a2, a3 = ev3[:, 2], ev3[:, 1], ev3[:, 0]
        n_pl_groups = 0
        # одно правило: ось зерна = ось ДЕТАЛИ (главная ось текселей самой части) во ВСЕХ путях — для ролей из rules.axis_per_part_roles (ножки/рама); по умолчанию выключено
        per_part = bool(rules.get('axis_per_part')) and face_part is not None and (p.get('role') in (rules.get('axis_per_part_roles') or ['legs', 'frame']))
        pp_min = int(rules.get('axis_per_part_min_texels', 200))
        pp_round = float(rules.get('axis_per_part_round_ratio', 1.1))                     # «круглая деталь» — отношение главных осей (дисперсий) ≤ этого
        groups = [int(g) for g in np.unique(fpt[sel])]
        acx = rules.get('axis_check') or {}
        swap_by_plane, swap_part = {}, False
        if acx.get('enabled') and acx.get('apply') and axis_ctx is not None and any(w in str(p.get('name', '')).lower() for w in acx['part_words']):
            # T-99/11 шаг 4 (Fable 14 п.3): направление волокна — по ФОТО: плоскость с подсказкой фото берёт ту из осей (c1 вдоль / c2 поперёк), что ближе к волокнам фото;
            # плоскость без подсказки (оборот, низ, не видна) — решение части целиком (взвешенное по числу текселей голосов); нет голосов — как раньше (по форме)
            votes = {True: 0, False: 0}
            for g in groups:
                tg = sel & (fpt == g)
                if g < 0 or int(tg.sum()) < rules['min_plane_texels']:
                    continue
                qg = tx.Q[tg] * scale
                c1g, c2g, rlg = plane_axes(qg, plane_normal[g], width_axis, rules)
                v1 = axis_check_plane(qg, plane_normal[g], c1g, rlg, axis_ctx, tx.f[tg], acx, rules)
                if v1['verdict'] not in ('axis_off_photo', 'axis_ok_photo'):
                    continue
                if v1['verdict'] == 'axis_ok_photo':
                    swap_by_plane[g] = False
                else:
                    v2 = axis_check_plane(qg, plane_normal[g], c2g, rlg, axis_ctx, tx.f[tg], acx, rules)
                    swap_by_plane[g] = bool(v2['verdict'] == 'axis_ok_photo')
                votes[swap_by_plane[g]] += int(tg.sum())
            swap_part = votes[True] > votes[False]
            r['axis_apply'] = {'планы_по_фото': {str(g): ('поперёк→вдоль' if v else 'как было') for g, v in swap_by_plane.items()}, 'голоса_текселей': {'повернуть': votes[True], 'оставить': votes[False]}, 'часть_повёрнута': bool(swap_part)}
        for g in groups:
            tgt = sel & (fpt == g)
            if not tgt.any():
                continue
            q = tx.Q[tgt] * scale
            nn = tx.N[tgt]
            if g >= 0 and int(tgt.sum()) >= rules['min_plane_texels']:
                c1, c2, _rl = plane_axes(q, plane_normal[g], width_axis, rules)
                if acx.get('apply') and acx.get('enabled') and axis_ctx is not None and swap_by_plane.get(g, swap_part):          # шаг 4: ось — по фото (или решению части)
                    c1, c2 = c2, _unit(np.cross(_unit(plane_normal[g], (0, 1, 0)), c2), (0, 0, 1))
                ac = rules.get('axis_check') or {}
                if ac.get('enabled') and axis_ctx is not None and any(w in str(p.get('name', '')).lower() for w in ac['part_words']):      # T-20261124-57/5: только отчёт — зерно и текстуру не меняет
                    r.setdefault('axis', []).append(dict(plane=g, n_texels=int(tgt.sum()), **axis_check_plane(q, plane_normal[g], c1, _rl, axis_ctx, tx.f[tgt], ac, rules)))
                u_cm, s_cm = q @ c1, q @ c2
                if per_part:
                    # плоскость склеила несколько деталей (ножка+перекладина…): ось — по текселям КАЖДОЙ детали в плоскости, а не плоскости целиком (T-63 р.5d)
                    fpl = np.asarray(face_part)[tx.f[tgt]]
                    for pp in np.unique(fpl):
                        mm = fpl == pp
                        if int(mm.sum()) >= pp_min and int(mm.sum()) < len(fpl):
                            e1, e2, _r2 = plane_axes(q[mm], plane_normal[g], width_axis, dict(rules, round_ratio=pp_round))
                            u_cm[mm], s_cm[mm] = q[mm] @ e1, q[mm] @ e2
                key = g + 1
                n_pl_groups += 1
            elif (per_part or rules.get('fallback_axis_per_part')) and face_part is not None and g < 0:
                # ось зерна — ось ДЕТАЛИ (главная ось ЕЁ текселей), а не всей группы: у ножек в разные стороны и у перекладин ось группы идёт вкось/поперёк (диагональная «ёлочка», T-63 р.5)
                fpart = np.asarray(face_part)[tx.f[tgt]]
                dl = np.zeros(len(q))
                for pp in np.unique(fpart):
                    mm = fpart == pp
                    qq = q[mm]
                    if int(mm.sum()) >= 3:
                        _w, _ev = np.linalg.eigh(np.cov((qq - qq.mean(0)).T))
                        b1, b2, b3 = _ev[:, 2], _ev[:, 1], _ev[:, 0]
                        if width_axis is not None and float(_w[2]) / max(float(_w[1]), 1e-12) <= pp_round:
                            # круглая деталь (диск, кольцо): длинной оси нет, главная ось — случайная → ось ширины товара в плоскости диска (как у круглой плиты в plane_axes)
                            wa = np.asarray(width_axis, np.float64)
                            e1 = wa - (wa @ b3) * b3
                            if np.linalg.norm(e1) > 1e-6:
                                b1 = e1 / np.linalg.norm(e1)
                                b2 = np.cross(b3, b1)
                    else:
                        b1, b2, b3 = a1, a2, a3
                    dl[mm] = sample_pat(d['pat'], qq @ b1, np.where(np.abs(nn[mm] @ b2) < np.abs(nn[mm] @ b3), qq @ b2, qq @ b3), tile, 777 + int(pp), layers)
            else:
                u_cm = q @ a1
                s_cm = np.where(np.abs(nn @ a2) < np.abs(nn @ a3), q @ a2, q @ a3)
                key = 777 + int(pid)
            lab = np.tile(tone, (int(tgt.sum()), 1))
            if not ((per_part or rules.get('fallback_axis_per_part')) and face_part is not None and g < 0):
                dl = sample_pat(d['pat'], u_cm, s_cm, tile, key, layers)
            lab[:, 0] = np.clip(lab[:, 0] + d['amp'] * dl, 0.0, 100.0)
            flat[tx.ti[tgt]] = TF.lab2rgb(lab)
            rep['texels_changed'] += int(tgt.sum())
        r.update(planes_used=n_pl_groups, groups=len(groups))
        rep['applied'] += 1
    return out, rep


# ------------------------------------------------------------------ плоскости для вызывающего -------------------------------------------------------------
def planes_for(V, F):
    """Плоскости меша через `tools/assets/parts_role_planes.merge_planes` (правила `part-role-planes.json`). → (face_plane (m,), normal (k,3)). Вызывать один раз на геометрию."""
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'assets'))
    import parts_role_planes as PRP
    pl = PRP.merge_planes(V, F, **{k: v for k, v in PRP.load_rules().items() if k in ('ang_deg', 'tol_rel', 'min_share')})
    return np.asarray(pl.face_plane), np.asarray(pl.normal)


# ------------------------------------------------------------------ вход от Ш4а (part_material, р.3) -------------------------------------------------------
def parts_from_masks(npz, tx, tex, card: dict | None = None, photo_sigma: dict | None = None, rules: dict | None = None):
    """Выход Ш4а `06-visible/part_material_masks.npz` → (parts для plan_grain, masks по текселям tx). Ключи npz: group_map (T×T int16, группа по текселю, −1 = не красили), names (имя группы),
    tone_srgb (плоский тон группы, (G,3), 0..255 или 0..1), painted_group (bool: группу красил Ш4а), roles (английский ключ роли р.1 на группу: top/legs/facade/side/back/body; names — русские имена групп), texture_size. Берутся только painted_group. Дерево — по карточке и имени (`part_is_wood`; номер материала Ш4а —
    «один материал = один тон», классов он не несёт). Ровность тона (`tone_sigma`) — σL текстуры под маской группы (Ш4а кладёт плоский тон → ≈0; градиент → отказ tone_not_even).
    photo_sigma — {id группы: σL фото (`photo_hf_sigma`)}; нет — None (предохранитель 2 берёт соседей)."""
    rules = rules or load_rules()
    z = npz if isinstance(npz, dict) else dict(np.load(npz, allow_pickle=False))
    gm = np.asarray(z['group_map']).reshape(-1)
    if gm.size != np.asarray(tex).shape[0] * np.asarray(tex).shape[1]:
        raise ValueError(f'group_map {np.asarray(z["group_map"]).shape} не совпадает с текстурой {np.asarray(tex).shape[:2]}')
    gt = gm[tx.ti]
    if 'texture_size' in z and int(np.asarray(z['texture_size']).reshape(-1)[0]) != int(np.asarray(tex).shape[0]):
        raise ValueError('texture_size в npz не совпадает с текстурой')
    names = [str(x) for x in np.asarray(z['names']).reshape(-1)]
    roles = [str(x) for x in np.asarray(z['roles']).reshape(-1)] if 'roles' in z else [None] * len(names)
    tone = np.asarray(z['tone_srgb'], np.float64).reshape(-1, 3)
    if tone.size and tone.max() <= 1.5:
        tone = tone * 255.0
    painted = np.asarray(z['painted_group'], bool).reshape(-1)
    flat = np.asarray(tex).reshape(-1, 3)[tx.ti]
    parts, masks = [], {}
    for g in range(len(names)):
        if g >= len(painted) or not painted[g]:
            continue
        m = gt == g
        n = int(m.sum())
        lab = TC.rgb2lab(np.clip(np.round(tone[g]), 0, 255).astype(np.uint8).reshape(1, 3))[0]
        sig = float(TC.rgb2lab(flat[m])[:, 0].std()) if n >= 20 else None
        parts.append({'id': g, 'name': names[g], 'is_wood': part_is_wood(names[g], card, rules, roles[g] if g < len(roles) else None), 'tone_lab': [float(x) for x in lab], 'tone_sigma': sig,
                      'n_texels': n, 'photo_sigma': (photo_sigma or {}).get(g), 'card': card, 'role': roles[g] if g < len(roles) else None,
                      'classes': (rules.get('bin_classes_by_role') or {}).get(roles[g] if g < len(roles) else None) or None})   # классы бина по роли (ножки/рама — straight: завитки/«глазки» на узкой детали дают ёлочку)
        masks[g] = m
    return parts, masks


def cm_per_unit(ext_max_units: float, card: dict | None, rules: dict):
    """Сантиметров на единицу меша: наибольший «габаритный» размер карточки (высота/длина/ширина, см) / наибольшая сторона габарита меша в тех же единицах. Нет карточки/размеров → None (вызывающий берёт fallback_length_cm)."""
    if not card or not ext_max_units > 0:
        return None
    nums = []
    for k, v in card.items():
        kl = str(k).lower()
        if 'габаритн' in kl and any(w in kl for w in ('высот', 'длин', 'ширин')):
            s = ''.join(ch for ch in str(v).replace(',', '.') if ch.isdigit() or ch == '.')
            try:
                x = float(s)
            except ValueError:
                continue
            if x > 0:
                nums.append(x)
    return (max(nums) / float(ext_max_units)) if nums else None
