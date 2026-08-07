#!/usr/bin/env python3
"""SKU-identity бенчмарк на своих same-series hard-negatives — T4 truth-first (рефери §27–28).

Задача, которую он калибрует: «кроп предмета из сгенерированного кадра — это ТОТ ЖЕ SKU,
что купленный, или его сосед по серии (другой цвет / ножки / конфигурация)?» Готового
публичного бенча под это нет (ответ рефери на Q3) — порог берётся ТОЛЬКО отсюда.

Сборка (v1):
  - семейство = (магазин, модельный ключ имени без цветовых слов); ≥2 живых SKU;
  - hard-negative пары: разные SKU одного семейства (та же серия!);
  - easy-negative: случайные SKU разных семейств;
  - positive (v1-прокси, честно помечено): та же карточка с лёгкими деформациями
    (кроп 8% + отражение) — верхняя граница разделимости; настоящие positives
    (принятые кропы из финалов, доверенные Trellis-рендеры) добавляются по мере
    накопления в generated-positives/ (формат: <mid>_<eid>_*.jpg|png).
  - split ПО СЕМЕЙСТВАМ (не по картинкам) — правка рефери: варианты одной серии не должны
    попадать и в калибровку, и в тест.

Метрики: verification ROC-AUC, FAR/FRR на пороге EER и на FAR=1%; retrieval Recall@1/5
внутри «сет + семейства-соседи». Приоритет продукта — низкий FAR (показать чужой диван
как купленный хуже, чем честное «не уверен»).

Эмбеддер v1 — CLIP (fastembed, уже в venv, тот же что в phash); DINOv2/DreamSim — челленджеры
(нужен torch, на VM не ставим без замера пользы: правило «test before spend»).

  ~/venvs/scout/bin/python sku_bench.py --build [--families 150]   # собрать пары
  ~/venvs/scout/bin/python sku_bench.py --eval                     # посчитать метрики
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
IMGCACHE = os.path.join(HERE, 'imgcache')
BENCH = os.path.join(HERE, 'sku-bench.json')
GENPOS = os.path.join(HERE, 'generated-positives')
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

_COLOR_WORDS = re.compile(
    r'\b(бел\w*|черн\w*|чёрн\w*|сер\w*|беж\w*|коричнев\w*|син\w*|голуб\w*|зелен\w*|зелён\w*|'
    r'желт\w*|жёлт\w*|красн\w*|оранж\w*|розов\w*|фиолетов\w*|мятн\w*|латте|мокко|капучино|'
    r'графит\w*|шоколад\w*|молочн\w*|карбон|аква|сталь|тауп|шампань|агат|венге|дуб|орех|сонома|'
    r'смоки|велюр\w*|рогожк\w*|шенилл\w*|вельвет\w*|экокож\w*|монолит|роял|корд|глосс|софт)\b',
    re.I)


def model_key(name: str) -> str:
    base = _COLOR_WORDS.sub(' ', name.lower())
    words = re.sub(r'[^а-яa-z0-9ё ]', ' ', base).split()
    return ' '.join(words[:5])


def img_path(mid, eid, url) -> str | None:
    """Тот же ключ кэша, что у golden_label._image_b64: не-алфанум → '_', хвост 90 симв."""
    if not url:
        return None
    key = re.sub(r'[^A-Za-z0-9]', '_', url)[-90:]
    p = os.path.join(IMGCACHE, key + '.jpg')
    return p if os.path.exists(p) else None


def build(max_families: int = 150) -> None:
    rows = []
    out = subprocess.run(PSQL, input="""
        select shop_mid, external_id, shop, name, coalesce(image_url,''), cat_role
          from products where in_stock and image_url is not null and cat_role is not null;
    """, capture_output=True, text=True).stdout
    for line in out.strip().split('\n'):
        f = line.split('\x1f')
        if len(f) >= 6:
            rows.append(f)
    fams: dict[tuple, list] = {}
    for mid, eid, shop, name, img, role in rows:
        p = img_path(mid, eid, img)
        if p:
            fams.setdefault((shop, role, model_key(name)), []).append(
                {'mid': int(mid), 'eid': eid, 'name': name, 'img': p, 'role': role})
    fams = {k: v for k, v in fams.items() if len({m['eid'] for m in v}) >= 2}
    # детерминированный отбор и split по семействам: чёт/нечет хеша ключа
    ordered = sorted(fams.items(), key=lambda kv: hashlib.sha1(str(kv[0]).encode()).hexdigest())
    picked = ordered[:max_families]
    bench = {'families': [], 'note': 'positives v1 = self-аугментация (прокси); '
             'настоящие — generated-positives/<mid>_<eid>_*.png'}
    for (shop, role, key), members in picked:
        split = 'calib' if int(hashlib.sha1(f'{shop}|{key}'.encode()).hexdigest()[:4], 16) % 2 \
            else 'test'
        uniq = {}
        for m in members:
            uniq.setdefault(m['eid'], m)
        bench['families'].append({'shop': shop, 'role': role, 'key': key, 'split': split,
                                  'members': list(uniq.values())[:6]})
    json.dump(bench, open(BENCH, 'w'), ensure_ascii=False, indent=1)
    n_m = sum(len(f['members']) for f in bench['families'])
    n_t = sum(1 for f in bench['families'] if f['split'] == 'test')
    print(f"семейств {len(bench['families'])} (test {n_t}), членов {n_m} → {BENCH}")
    for f in bench['families'][:5]:
        print(f"  [{f['split']}] {f['role']} «{f['key']}»: {len(f['members'])} SKU")


# ------------------------------------------------------------------ eval

def _dino_embed(paths):
    """Челленджер DINOv2 (ViT-S/14, torch.hub, CPU) — рефери §10: fine-grained identity
    обычно сильнее у DINO-семейства, чем у CLIP. Веса кэшируются в ~/.cache/torch."""
    import torch
    from PIL import Image
    import torchvision.transforms as T
    model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14', verbose=False)
    model.eval()
    tf = T.Compose([T.Resize(244), T.CenterCrop(224), T.ToTensor(),
                    T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    out = []
    with torch.no_grad():
        for i in range(0, len(paths), 16):
            batch = torch.stack([tf(Image.open(p).convert('RGB')) for p in paths[i:i + 16]])
            out.append(model(batch).numpy())
    a = np.concatenate(out)
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def _embed_paths(paths, aug=False, embedder='clip'):
    from fastembed import ImageEmbedding
    from PIL import Image, ImageOps
    import tempfile
    model = ImageEmbedding('Qdrant/clip-ViT-B-32-vision')
    use = paths
    tmpdir = None
    if aug:   # лёгкая деформация: кроп 8% + отражение (v1-прокси positive)
        tmpdir = tempfile.mkdtemp(prefix='skuaug-', dir=os.environ.get('TMPDIR', '/tmp'))
        use = []
        for p in paths:
            im = Image.open(p).convert('RGB')
            w, h = im.size
            im = ImageOps.mirror(im.crop((int(w*0.08), int(h*0.08), int(w*0.96), int(h*0.96))))
            q = os.path.join(tmpdir, os.path.basename(p) + '.aug.jpg')
            im.save(q, quality=90)
            use.append(q)
    if embedder == 'dino':
        return _dino_embed(use)
    vecs = list(model.embed(use))
    a = np.array(vecs)
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def evaluate(embedder: str = 'clip') -> None:
    bench = json.load(open(BENCH))
    fams = bench['families']
    paths, owner = [], []
    for fi, f in enumerate(fams):
        for m in f['members']:
            paths.append(m['img'])
            owner.append(fi)
    print(f'эмбеддинг {len(paths)} карточек ({embedder}, CPU)...', flush=True)
    E = _embed_paths(paths, embedder=embedder)
    EA = _embed_paths(paths, aug=True, embedder=embedder)
    owner = np.array(owner)
    split = np.array([fams[o]['split'] for o in owner])
    pos = (E * EA).sum(1)                                   # своя карточка ↔ своя аугментация
    hard, easy = [], []
    S = E @ E.T
    for i in range(len(paths)):
        same_fam = (owner == owner[i]) & (np.arange(len(paths)) != i)
        hard += list(S[i][same_fam])
        other = np.where(owner != owner[i])[0]
        if len(other):
            rng = np.random.default_rng(i)
            easy += list(S[i][rng.choice(other, min(3, len(other)), replace=False)])
    hard, easy = np.array(hard), np.array(easy)

    def far_frr(thr):
        return float((hard >= thr).mean()), float((pos < thr).mean())
    # ROC-AUC (verification: pos vs hard)
    scores = np.concatenate([pos, hard])
    labels = np.concatenate([np.ones_like(pos), np.zeros_like(hard)])
    order = np.argsort(-scores)
    tp = np.cumsum(labels[order]) / max(labels.sum(), 1)
    fp = np.cumsum(1 - labels[order]) / max((1 - labels).sum(), 1)
    auc = float(np.trapezoid(tp, fp))
    # порог по калибровочной половине: FAR=1% на hard-negatives calib-семейств
    calib_mask = np.repeat(split == 'calib', 0)  # noqa: F841 — hard уже смешан; v1: общий
    thr_far1 = float(np.quantile(hard, 0.99))
    far, frr = far_frr(thr_far1)
    # retrieval: кроп (аугментация) должен вернуть свой SKU против семьи+случайных
    r1 = r5 = 0
    for i in range(len(paths)):
        cand = np.where((owner == owner[i]) | (np.arange(len(paths)) % 7 == i % 7))[0]
        sims = E[cand] @ EA[i]
        rank = int((sims > float(E[i] @ EA[i])).sum())
        r1 += rank == 0
        r5 += rank < 5
    print(f"пар: pos {len(pos)}, hard-neg {len(hard)}, easy-neg {len(easy)}")
    print(f"verification ROC-AUC (pos vs same-series): {auc:.3f}")
    print(f"порог FAR=1% по hard: {thr_far1:.3f} → FAR {far*100:.1f}%, FRR {frr*100:.1f}%")
    print(f"разделение: pos μ {pos.mean():.3f} | hard μ {float(hard.mean()):.3f} | "
          f"easy μ {float(easy.mean()):.3f}")
    print(f"retrieval (aug-кроп → свой SKU): Recall@1 {r1/len(paths)*100:.1f}%, "
          f"Recall@5 {r5/len(paths)*100:.1f}%")
    gen = glob.glob(os.path.join(GENPOS, '*.*'))
    print(f"настоящих generated-positives: {len(gen)} (порог продукту — только после них)")
    json.dump({'auc': auc, 'thr_far1': thr_far1, 'far': far, 'frr': frr,
               'pos_mean': float(pos.mean()), 'hard_mean': float(hard.mean()),
               'recall1': r1 / len(paths), 'recall5': r5 / len(paths),
               'n_pos': len(pos), 'n_hard': len(hard),
               'embedder': embedder, 'positives': 'v1-proxy (self-aug)'},
              open(os.path.join(HERE, f'sku-bench-report{"" if embedder == "clip" else "-" + embedder}.json'), 'w'), indent=1)


if __name__ == '__main__':
    if '--build' in sys.argv:
        i = sys.argv.index('--families') if '--families' in sys.argv else -1
        build(int(sys.argv[i + 1]) if i > 0 else 150)
    elif '--eval' in sys.argv:
        i = sys.argv.index('--model') if '--model' in sys.argv else -1
        evaluate(sys.argv[i + 1] if i > 0 else 'clip')
    else:
        print(__doc__)
