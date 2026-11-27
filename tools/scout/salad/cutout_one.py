#!/usr/bin/env python3
"""ЕДИНЫЙ МОДУЛЬ ВЫРЕЗКИ (T-20261127-175/9, Fable 29 шаги 1–2): фото + сырая маска + роль → вырезка полного холста + отчёт.

Раньше путей было три (старый `preprocess._cut_chain`, «последний» `cutout_sync.chain_shape`, августовский `viz_paste.cutout`), и вход формы можно было сделать любым.
Тело цепочки `chain_shape` перенесено сюда БЕЗ изменения байтов (проверка — `tests_cutout_one.py`: замороженные фото, эталон старого кода, равенство массивов RGBA);
`cutout_sync.chain_shape` / `chain` / `crop_box` / `mask_local` стали вызовами этого модуля. Ночной шаг оценки пула (`cutout_sync`) идёт по тем же шагам и тем же результатом.

ЧТО ЗДЕСЬ
  mask_cpu(img)                       — ЕДИНСТВЕННАЯ копия сырой маски на ЦП: полная BiRefNet, float32, ревизия закреплена (`cutout_origin.BIREFNET_REVISION`).
                                        (прежние копии: `cutout_sync.mask_local` и `trellis/make_inputs.cpu_cutout` — теперь вызывают её)
  cut_shape(src, net, role, steps=()) — цепочка до обрезки: гибрид → связность → заливка дыр → (счётчик «срезал бы» хвосты у пола) → щели → студийный белый фон → коллаж → кромка →
                                        (главный предмет) → мягкий край. Возвращает (RGBA на полном холсте, info).
  chain_cut(src, net, role, steps=()) — то же + обрезанная копия, вердикт маски, `photo` (то, что раньше делал `cutout_sync.chain`): (shape, cut, info).
  crop_box(shape)                     — рамка обрезки (зеркало `PRE.trim_alpha`).

ШАГИ СТАРОЙ ЦЕПОЧКИ (решение Fable 27.11 по замеру 9.3, `~/remlab-logs/fable-1126/reshenie-t175-93.md`):
  'main_object' — за флагом `steps` (ночная оценка байт-в-байт прежняя; вход формы включает): пара ОДИНАКОВЫХ предметов в кадре → оставить один; только роль «стул»
                  (`MAIN_OBJECT_ROLES`, флаг `main_object` в паспорте типа). Выбор предсказуемый: при равных площадях (меньший ≥ EQUAL_SHARE большего) — ЛЕВЫЙ по bbox.x
                  (иначе один и тот же вход давал разные вырезки от запуска к запуску), иначе — больший (передний). Что взято — `info['picked']` и `origin['pick']`.
  «хвосты у пола» (`components.prune_attached`) — из цепочки УБРАНЫ везде, и у входа формы: на трудных фото хвостов не нашёл ни одного, зато срезал настоящие ножки
                  (кресло Alex — 5 % площади, ножка дивана — 188 px). Не терять наблюдение: `info['attached_prune_would']` — сколько шаг срезал бы, если бы работал (маску НЕ меняет);
                  считает ночная оценка и вход формы — на 200 фото (9.6) и в ночи покажет настоящий хвост, если он есть. Вернуть шаг — только с условием «срез вне зоны ножек».
Старый боевой генератор форм (`preprocess._cut_chain`) до шага 9.6 продолжает резать старой цепочкой — этим модулем не затронут.

Версия цепочки — `cutout_origin.CHAIN_VERSION` (НЕ `preprocess.ASSESSOR_VERSION`: та — ключ кэша оценок пула).
"""
from __future__ import annotations

import io
import os
import time

import numpy as np
from PIL import Image

import collage
import components
import hybrid_mask
import preprocess as PRE
import soft_edge
import studio_bg
import cutout_origin as CO

BIREFNET_REPO = CO.BIREFNET_REPO
BIREFNET_REVISION = CO.BIREFNET_REVISION

# Роли, у которых работает шаг «главный предмет» (одобрено владельцем 30.08 — только стулья). Читает тест паспортов: у типа с флагом `main_object` в `chain_flags` роль обязана быть здесь, и наоборот.
MAIN_OBJECT_ROLES = ('стул',)
EQUAL_SHARE = 0.95      # меньший компонент ≥ этой доли большего — «равные» (пара одинаковых): берётся левый, а не больший

_LOCAL = None


def mask_cpu(img: Image.Image) -> Image.Image:
    """Сырая маска товара: ПОЛНАЯ BiRefNet на процессоре (float32; fp16 на ЦП не считается), ревизия закреплена. Возвращает RGBA: цвета фото, альфа — маска.
    Единственная копия этого кода (вход формы и режим `local` ночного шага). Потоки — переменная THREADS (по умолчанию 12)."""
    global _LOCAL
    src = img.convert('RGB')
    if _LOCAL is None:
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        m = AutoModelForImageSegmentation.from_pretrained(BIREFNET_REPO, trust_remote_code=True, revision=BIREFNET_REVISION)
        m.float().eval()
        torch.set_num_threads(int(os.environ.get('THREADS', '12')))
        _LOCAL = (torch, m, transforms.Compose([
            transforms.Resize((1024, 1024)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]))
    torch, m, tf = _LOCAL
    with torch.no_grad():
        pred = m(tf(src).unsqueeze(0))[-1].sigmoid()[0].squeeze()
    out = src.convert('RGBA')
    out.putalpha(Image.fromarray((pred.numpy() * 255).astype(np.uint8)).resize(src.size))
    return out


def pick_main_object(cut: Image.Image) -> tuple[Image.Image, dict]:
    """Шаг «главный предмет»: пара одинаковых предметов (два крупных компонента, меньший ≥ 40 % большего, их bbox по X почти не пересекаются — как у старого
    `preprocess._pick_main_object`) → оставить ОДИН. Отличие от старого: при РАВНЫХ площадях (меньший ≥ EQUAL_SHARE большего) берётся ЛЕВЫЙ по bbox.x — результат
    не зависит от того, какой из двух стульев случайно на несколько пикселей больше; иначе — больший (передний), как раньше. Не пара → (cut, {})."""
    from scipy import ndimage
    a = np.asarray(cut)[..., 3] > 40
    lab, n = ndimage.label(a)
    if n < 2:
        return cut, {}
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    order = np.argsort(sizes)[::-1]
    if sizes[order[1]] < 0.40 * sizes[order[0]]:
        return cut, {}
    boxes = ndimage.find_objects(lab)
    i1, i2 = int(order[0]), int(order[1])
    b1, b2 = boxes[i1], boxes[i2]
    x1a, x1b, x2a, x2b = b1[1].start, b1[1].stop, b2[1].start, b2[1].stop
    if max(0, min(x1b, x2b) - max(x1a, x2a)) / max(1, min(x1b - x1a, x2b - x2a)) > 0.25:
        return cut, {}
    share = float(sizes[i2] / sizes[i1])
    if share >= EQUAL_SHARE:
        keep, picked = (i1 if (x1a, x1b, i1) <= (x2a, x2b, i2) else i2) + 1, 'left_of_two'
    else:
        keep, picked = i1 + 1, 'larger_of_two'
    arr = np.asarray(cut).copy()
    arr[..., 3] = np.where(lab == keep, arr[..., 3], 0)
    return Image.fromarray(arr, 'RGBA'), {'dual_object_trimmed': True, 'second_share': round(share, 2), 'picked': picked}


def cut_shape(src: Image.Image, net: Image.Image, role: str | None = None, steps=()) -> tuple[Image.Image, dict]:
    """Цепочка до обрезки: полнокадровая RGBA-вырезка + info. Отдельно от `chain_cut`, чтобы замеры считали маску в координатах кадра.
    `steps` — необязательные шаги старой цепочки (см. docstring модуля); пустой набор = прежняя цепочка `cutout_sync.chain_shape` байт-в-байт."""
    steps = frozenset(steps)
    bad = sorted(steps - set(CO.STEPS_ALL))
    if bad:
        raise ValueError(f'неизвестные шаги цепочки {bad}: допустимо {CO.STEPS_ALL}')
    try:
        refined, info = hybrid_mask.refine(src, net, role=role)
    except Exception as e:  # noqa: BLE001 — гибрид не должен ронять шаг; факт отказа виден
        refined, info = net, {'hybrid_error': f'{type(e).__name__}: {str(e)[:100]}'}
    a = np.asarray(refined)[..., 3].astype(np.float32) / 255.0
    cleaned, comp = components.clean(a)
    # «Известный студийный фон» (T-20261119-104/5, Ч.1): строгий признак ровного белого фона по кольцу кадра; Rcore/Rsoft — заливка от рамки.
    # Считаем ВСЕГДА (для замера «загрязнения» по шагам); правим вырезку только при включённом правиле. bg_mode: white_flat | net_only (+ причина).
    src_rgb = np.asarray(src)
    ms = {}
    t0 = time.time()
    bg, st = studio_bg.detect(src_rgb)
    rcore = rsoft = None
    act = studio_bg.enabled() and bg is not None
    info['bg_mode'] = 'white_flat' if bg is not None else 'net_only'
    info['studio'] = dict(st)
    if bg is not None:
        rcore, rsoft = studio_bg.regions(src_rgb, bg, st['t_core'], st['t_soft'])
        info['studio']['pollution'] = {'raw': studio_bg.pollution(np.asarray(net)[..., 3].astype(np.float32) / 255.0, rcore),
                                       'hybrid': studio_bg.pollution(a, rcore), 'clean': studio_bg.pollution(cleaned, rcore)}
    if not studio_bg.enabled():
        info['studio']['applied'] = False
        info['studio']['skipped'] = 'выключено CUTOUT_STUDIO_BG=0'
    ms['detect_regions'] = round(time.time() - t0, 3)
    # Дырки, внутри которых НЕ фон, — это потерянная основа товара (серый ковёр, узор которого
    # сеть удержала, а поле потеряла). Просветы проволоки и реек внутри показывают фон и
    # остаются нетронутыми — различаем по содержимому, а не по размеру (урок 307).
    cleaned, holes = components.fill_holes_unlike_bg(cleaned, np.asarray(src), role=role)
    comp.update(holes)
    # дыры внутри тела корпусной мебели (светлые фасады «как фон», T-20261119-104/3): замкнутые телом возвращаются; стул/стеллаж/стол не трогаются
    cleaned, bh = components.fill_body_holes(cleaned, np.asarray(refined)[..., :3], role=role)
    comp.update(bh)
    # СЧЁТЧИК «срезал бы» (решение Fable 27.11): шаг «хвосты у пола» из цепочки убран (резал ножки), но наблюдение сохранено — считаем, сколько он срезал бы, МАСКУ НЕ МЕНЯЕМ
    # (результат шага выбрасывается). `would_cut_px` — сколько срезал бы; `blocked_px` — нашёл куски, но их больше потолка шага (8 % маски) — не срезал бы; 0 у обоих — не нашёл.
    wc, wi = components.prune_attached(cleaned, role=role)
    fgpx = int((np.asarray(cleaned) > 0.5).sum())
    sh = float(wi.get('attached_share', 0.0))
    info['attached_prune_would'] = {'applied': False, 'pieces': int(wi.get('attached_pruned', 0)), 'would_cut_px': int(round(sh * fgpx)) if wi.get('attached_pruned') else 0,
                                    'blocked_px': int(round(sh * fgpx)) if wi.get('attached_skip') == 'cut_share' else 0, 'skip': wi.get('attached_skip'), 'mask_px': fgpx}
    del wc
    # щели 1–2 px у кромки (светлое на белом рвётся «пунктиром», T-20261119-104/2); внутренние дырки и пустоты от 3 px остаются.
    # С известным фоном — только пикселями «не фон» (T-104/5: белая крупа вокруг трубки торшера склеивалась в «бусины»).
    t0 = time.time()
    cleaned, rgb, gap = components.close_edge_gaps(cleaned, np.asarray(refined)[..., :3], rcore=rcore if act else None)
    comp.update(gap)
    ms['close_gaps'] = round(time.time() - t0, 3)
    if rcore is not None:
        info['studio']['pollution']['closing'] = studio_bg.pollution(cleaned, rcore)
    # Ч.2 (T-104/5): осторожно вернуть крупное потерянное тело (белый щит на белом); до вычитателя — он потом чистит и край добавки
    if act:
        t0 = time.time()
        cleaned, prop = studio_bg.propose(cleaned, np.asarray(net)[..., 3].astype(np.float32) / 255.0, src_rgb, bg, rsoft)
        info['studio'].update(prop)
        ms['propose'] = round(time.time() - t0, 3)
        info['studio']['pollution']['proposal'] = studio_bg.pollution(cleaned, rcore)
    # вычитатель — ПОСЛЕДНИЙ из растущих шагов: чистый фон у кромки, связанный с краем кадра, в полосе ≤ 2 px (T-104/5)
    if act:
        t0 = time.time()
        cleaned, sub = studio_bg.subtract(cleaned, src_rgb, bg, rcore)
        info['studio'].update(sub)
        ms['subtract'] = round(time.time() - t0, 3)
        info['studio']['pollution']['subtract'] = studio_bg.pollution(cleaned, rcore)
        # Ч.3: белые островки цвета фона у тёмного тела, отделённые от рамки тенью (не в Rcore)
        cleaned, cc = studio_bg.contrast_cut(cleaned, src_rgb, bg, rsoft)
        info['studio'].update(cc)
        # клин пола между ножками под плотным телом (T-104/7)
        cleaned, hw = studio_bg.hang_wedge(cleaned, src_rgb, bg, rsoft)
        info['studio'].update(hw)
    info['components'] = comp
    refined = Image.fromarray(np.dstack([rgb, (np.clip(cleaned, 0, 1) * 255).astype(np.uint8)]), 'RGBA')
    is_col, why, feats = collage.is_collage(np.asarray(src).astype(np.float32), cleaned)
    info['collage'] = {'verdict': bool(is_col), 'why': why, 'features': feats}
    shape = PRE.defringe(refined, info)
    # (шаг старой цепочки, только steps∋main_object) пара одинаковых предметов в кадре → один, при равных — левый; срез одобрен владельцем только для стульев (30.08)
    if 'main_object' in steps and ((role or '').split() or [''])[0] in MAIN_OBJECT_ROLES:
        shape, dual = pick_main_object(shape)
        info.update(dual)
    # мягкий край по известному белому фону (аналитика, T-104/5): α = min(α, α_цвет) в полосе кромки, цвет — F; F ≈ B → α сети не трогаем
    if act:
        t0 = time.time()
        sa = np.asarray(shape)
        al, rg, soft = studio_bg.soft_alpha(sa[..., 3].astype(np.float32) / 255.0, sa[..., :3], bg, rsoft)
        shape = Image.fromarray(np.dstack([rg, (np.clip(al, 0, 1) * 255).astype(np.uint8)]), 'RGBA')
        info['studio'].update(soft)
        ms['soft'] = round(time.time() - t0, 3)
        if soft_edge.enabled():                       # опциональный A/B pymatting (по умолчанию выключен)
            shape = soft_edge.apply(shape, src_rgb, bg, info)
    if rcore is not None:
        info['studio']['pollution']['final'] = studio_bg.pollution(np.asarray(shape)[..., 3].astype(np.float32) / 255.0, rcore)
    info['studio']['applied'] = bool(act)
    info['studio']['ms'] = ms
    if steps:       # только у входа формы: ночная оценка (steps пуст) своих отчётов не меняет
        info['chain'] = {'version': CO.CHAIN_VERSION, 'steps': sorted(steps)}
    return shape, info


def crop_box(shape: Image.Image, pad: int = 8) -> tuple[int, int, int, int]:
    """Рамка обрезки, ЗЕРКАЛО `PRE.trim_alpha` (альфа > 8, поле `pad`, в пределах кадра; пустая альфа → весь кадр) — а не `getbbox()`.
    Смещение вырезки в исходном кадре (`photo.object_xy` = левый верх рамки) нужно сторожам паспортов (К1: сравнить исходник с вырезкой без поиска совмещения).
    Совпадение с `trim_alpha` по байтам держит тест (`shape.crop(crop_box(shape)).tobytes() == trim_alpha(shape).tobytes()`)."""
    a = np.asarray(shape)[..., 3]
    ys, xs = np.where(a > 8)
    if not len(ys):
        return 0, 0, shape.width, shape.height
    return (int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)),
            int(min(shape.width, xs.max() + pad + 1)), int(min(shape.height, ys.max() + pad + 1)))


def chain_cut(src: Image.Image, net: Image.Image, role: str | None = None, steps=()) -> tuple[Image.Image, Image.Image, dict]:
    """Цепочка целиком: (RGBA на полном холсте, обрезанная копия, info) — обрезка, вердикт маски (в т.ч. «коллаж»), `photo` (размеры, доля кадра, смещение).

    `role` нужен точечным правкам: рост по связности — только коврам, заливка силуэта — только вазам/кашпо/статуэткам. Остальные 95% товаров идут как раньше."""
    shape, info = cut_shape(src, net, role=role, steps=steps)
    cut = PRE.trim_alpha(shape)
    box = crop_box(shape)
    info.update(PRE.mask_verdict(cut))
    if info['collage']['verdict']:
        info.update(verdict='bad', reason='фото-коллаж: ' + ', '.join(info['collage']['why'][1:] or ['баннер']))
    fw, fh = src.size
    cw, ch = cut.size
    info['photo'] = {'frame_wh': [fw, fh], 'object_wh': [cw, ch],
                     'object_share': round(cw * ch / max(fw * fh, 1), 4),
                     'object_rel_side': round(max(cw, ch) / max(max(fw, fh), 1), 3),
                     'object_min_side': int(min(cw, ch)),
                     'object_xy': [box[0], box[1]]}   # смещение вырезки в кадре — для сторожей паспортов (фаза 1 «тень»)
    return shape, cut, info


def make_input(raw: bytes, role: str | None, steps=CO.STEPS_ALL, net: Image.Image | None = None):
    """ВХОД ФОРМЫ из байтов фото: сырая маска (`mask_cpu`; `net` — готовая, только для тестов) → `chain_cut` → запись происхождения.
    Возвращает (shape RGBA полного холста, обрезанная копия, info, origin). Решать «годен ли» (размер, коллаж, сбой гибрида) — вызывающему: отчёт в `info`."""
    src = Image.open(io.BytesIO(raw)).convert('RGB')
    if net is None:
        net = mask_cpu(src)
    shape, cut, info = chain_cut(src, net, role=role, steps=steps)
    return shape, cut, info, CO.build(raw, steps, shape=shape, pick=info.get('picked', 'none'))
