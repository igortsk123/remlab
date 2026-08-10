"""PHASE 3E — high-recall candidate graph (каналы UNION, капы, детерминизм).

Каналы (ни один не hard-исключает пару; unknown расширяет кандидатов):
- FP: одинаковый context_fingerprint (кросс-файлово);
- SUBJ_DIM: блок (subject-концепт, dimension_type, quantity_kind);
- SUBJ_REF: блок (subject-концепт, reference-концепт);
- BM25: лексические top-K соседи (свой мини-BM25, без зависимостей);
- VEC: векторные top-K соседи (fastembed, optional — деградирует с warning);
- HINT: local_duplicate_of/local_conflicts_with как seeds;
- AUTH: (authority_id, quantity_kind);
- SIBLING: атомы одной записи (кандидаты QUALIFIES/зависимостей).

Кап на блок: крупные блоки дробятся по (value_type, room) — иначе декартов
взрыв; итоговый бюджет пар контролируется явно (гейт ≤150k из плана).
Pair ID детерминирован из сортированных atomic ID + purpose.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .vocab import norm_label

MAX_BLOCK = 60          # блок больше -> дробим ключ
TOP_K_LEX = 8
TOP_K_VEC = 8
PAIR_BUDGET = 150_000


def subject_concept(atom: dict, vocab_map: dict) -> str | None:
    ent = atom["claim"].get("subject") or {}
    if not ent and atom["claim"].get("entities"):
        ent = atom["claim"]["entities"][0]
    t = ent.get("entity_type")
    if t:
        return f"CORE_{t}"
    p = ent.get("proposed_entity_type")
    if p:
        v = vocab_map.get(norm_label(p))
        if v and v.get("core"):
            return f"CORE_{v['core']}"
        if v:
            return f"NEW_{v['canonical_label']}"
        return f"RAW_{norm_label(p)}"
    lbl = ent.get("source_label")
    return f"LBL_{norm_label(lbl)}" if lbl else None


def reference_concept(atom: dict, vocab_map: dict) -> str | None:
    ent = atom["claim"].get("reference") or {}
    t = ent.get("entity_type")
    if t and t != "unknown":
        return f"CORE_{t}"
    p = ent.get("proposed_entity_type")
    if p:
        v = vocab_map.get(norm_label(p))
        return (f"CORE_{v['core']}" if v and v.get("core")
                else f"NEW_{v['canonical_label']}" if v else f"RAW_{norm_label(p)}")
    return None


def atom_text(atom: dict) -> str:
    c = atom["claim"]
    p = atom["parent_record"]
    parts = [
        (c.get("subject") or {}).get("source_label") or "",
        (c.get("reference") or {}).get("source_label") or "",
        c.get("metric") or "", c.get("condition") or "",
        p.get("concept") or "", p.get("rule_plain_language") or "",
        c.get("presence_phrase") or "",
    ]
    return " ".join(x for x in parts if x)[:600]


_TOKEN = re.compile(r"[a-zа-яё0-9]+")


def tokenize(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


class BM25:
    """Мини-BM25 (k1=1.5, b=0.75) на инвертированном индексе, детерминированный."""

    def __init__(self, docs: list[list[str]]):
        self.docs = docs
        self.N = len(docs)
        self.avg = sum(len(d) for d in docs) / max(self.N, 1)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for j, d in enumerate(docs):
            for t, tf in Counter(d).items():
                self.postings[t].append((j, tf))
        self.df = {t: len(p) for t, p in self.postings.items()}

    def top_k(self, qi: int, k: int) -> list[int]:
        scores: dict[int, float] = defaultdict(float)
        for t in set(self.docs[qi]):
            df = self.df.get(t, 0)
            if df < 2 or df > self.N * 0.3:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for j, tf in self.postings[t]:
                denom = tf + 1.5 * (0.25 + 0.75 * len(self.docs[j]) / self.avg)
                scores[j] += idf * tf * 2.5 / denom
        scores.pop(qi, None)
        return [j for j, _ in sorted(scores.items(),
                                     key=lambda kv: (-kv[1], kv[0]))[:k]]


def _add_pairs_from_block(block: list[int], channel: str,
                          pairs: dict[tuple[int, int], set]) -> None:
    for i in range(len(block)):
        for j in range(i + 1, len(block)):
            a, b = block[i], block[j]
            key = (a, b) if a < b else (b, a)
            pairs.setdefault(key, set()).add(channel)


def _blocked(items: list[tuple[int, tuple]], subkey_fn=None) -> list[list[int]]:
    """Группировка по ключу; блоки > MAX_BLOCK дробятся subkey_fn (или режутся
    с warning — фиксируется в отчёте вызывающим)."""
    by_key: dict[tuple, list[int]] = defaultdict(list)
    for idx, key in items:
        if key is not None:
            by_key[key].append(idx)
    out = []
    for key, block in by_key.items():
        if len(block) <= MAX_BLOCK or subkey_fn is None:
            out.append(block)
        else:
            sub: dict = defaultdict(list)
            for idx in block:
                sub[subkey_fn(idx)].append(idx)
            out.extend(sub.values())
    return out


def build_candidates(atoms: list[dict], vocab_map: dict,
                     vectors=None) -> tuple[dict, dict]:
    """-> (pairs {(i,j): {channels}}, report)."""
    n = len(atoms)
    subj = [subject_concept(a, vocab_map) for a in atoms]
    ref = [reference_concept(a, vocab_map) for a in atoms]
    dim = [a["parent_record"].get("dimension_type") for a in atoms]
    qk = [a["claim"].get("quantity_kind") for a in atoms]
    vt = [a["claim"].get("value_type") for a in atoms]
    room = [tuple(sorted({b.get("room_type") or ""
                          for b in a["applicability"]["branches"]}))
            for a in atoms]
    rec_key = [(a["observation"]["logical_package_key"],
                a["observation"]["record_id"]) for a in atoms]

    pairs: dict[tuple[int, int], set] = {}
    report: dict = {"channels": {}}

    def run_channel(name: str, blocks: list[list[int]]) -> None:
        before = len(pairs)
        for b in blocks:
            _add_pairs_from_block(b, name, pairs)
        report["channels"][name] = {"blocks": len(blocks),
                                    "new_pairs": len(pairs) - before}

    # FP: fingerprint кросс-файлово
    run_channel("FP", _blocked(
        [(i, atoms[i]["parent_record"].get("context_fingerprint")) for i in range(n)],
        subkey_fn=lambda i: (vt[i],)))
    # SUBJ_DIM
    run_channel("SUBJ_DIM", _blocked(
        [(i, (subj[i], dim[i], qk[i]) if subj[i] else None) for i in range(n)],
        subkey_fn=lambda i: (vt[i], room[i])))
    # SUBJ_REF
    run_channel("SUBJ_REF", _blocked(
        [(i, (subj[i], ref[i]) if subj[i] and ref[i] else None)
         for i in range(n)],
        subkey_fn=lambda i: (qk[i], vt[i])))
    # AUTH: авторитет + вид величины
    auth_key = []
    for i, a in enumerate(atoms):
        nm = (a["parent_record"].get("cited_authority_name") or "").strip()
        auth_key.append((i, (norm_label(nm)[:40], qk[i]) if nm else None))
    run_channel("AUTH", _blocked(auth_key, subkey_fn=lambda i: (subj[i],)))
    # SIBLING: атомы одной записи (для зависимостей)
    run_channel("SIBLING", _blocked(
        [(i, rec_key[i]) for i in range(n)]))
    # HINT: local hints как seeds (записи -> все их атом-пары)
    hint_blocks = []
    by_rec: dict[tuple, list[int]] = defaultdict(list)
    for i in range(n):
        by_rec[rec_key[i]].append(i)
    for i in range(n):
        p = atoms[i]["parent_record"]
        lpk = atoms[i]["observation"]["logical_package_key"]
        targets = list(p.get("local_conflicts_with") or [])
        if p.get("local_duplicate_of"):
            targets.append(p["local_duplicate_of"])
        for t in targets:
            other = by_rec.get((lpk, t), [])
            if other:
                hint_blocks.append([i] + other)
    run_channel("HINT", hint_blocks)
    # NUMNEIGH: соседи по канон-значению внутри (subject, qk) БЕЗ дробления
    # по value_type/room — закрывает кросс-value_type пары (recall-гейт)
    from decimal import Decimal
    num_groups: dict[tuple, list[tuple[Decimal, int]]] = defaultdict(list)
    for i, a in enumerate(atoms):
        nv = a.get("numeric_view") or {}
        v = nv.get("value") or (nv.get("range") or [None])[0]
        if subj[i] and v is not None and str(nv.get("status", "")).startswith("OK"):
            num_groups[(subj[i], qk[i])].append((Decimal(v), i))
    nn_blocks = []
    for key, items in sorted(num_groups.items()):
        items.sort(key=lambda t: (t[0], t[1]))
        # (а) РАВНОЕ канон-значение: полный блок (топ-кандидаты в дубли)
        eq: dict[Decimal, list[int]] = defaultdict(list)
        for v, i in items:
            eq[v].append(i)
        for v, block in eq.items():
            if len(block) > 1:
                nn_blocks.append(block)
        # (б) окно ±10% для неравных, кап 8 соседей на атом
        for pos, (v, i) in enumerate(items):
            added = 0
            for off in range(1, len(items) - pos):
                v2, j = items[pos + off]
                if v2 == v:
                    continue  # покрыто равно-блоком
                close = v == 0 or abs(v2 - v) / abs(v) <= Decimal("0.1")
                if not close and added >= 3:
                    break
                nn_blocks.append([i, j])
                added += 1
                if added >= 8:
                    break
    run_channel("NUMNEIGH", nn_blocks)
    # BM25
    texts = [tokenize(atom_text(a)) for a in atoms]
    bm = BM25(texts)
    lex_blocks = [[i] + bm.top_k(i, TOP_K_LEX) for i in range(n)]
    lex_pairs_blocks = [[b[0], j] for b in lex_blocks for j in b[1:]]
    run_channel("BM25", lex_pairs_blocks)
    # VEC (optional)
    if vectors is not None:
        import numpy as np
        vec_blocks = []
        vn = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
        sims = vn @ vn.T
        for i in range(n):
            idx = np.argsort(-sims[i])
            picked = [int(j) for j in idx if j != i][:TOP_K_VEC]
            vec_blocks.extend([[i, j] for j in picked])
        run_channel("VEC", vec_blocks)
    else:
        report["channels"]["VEC"] = {"blocks": 0, "new_pairs": 0,
                                     "disabled": True}

    report["total_pairs"] = len(pairs)
    report["budget"] = PAIR_BUDGET
    if len(pairs) > PAIR_BUDGET:
        raise SystemExit(f"БЛОК: пар {len(pairs)} > бюджета {PAIR_BUDGET} — "
                         "пересмотри капы каналов (гейт KB5a)")
    return pairs, report
