"""Волна KB5a (PHASE 3E + вердикты) -> 04a_semantic_comparison_candidates.jsonl.

Шаги: эмбеддинги (fastembed, optional) -> UNION-каналы кандидатов ->
детерминированная предклассификация -> LLM-судья (luna, пилот + прогноз
стоимости, потолок $60) -> adversarial-проход (terra) по конфликтам/дублям ->
аудит local hints -> seed-набор (frozen) -> recall-гейты (полный + абляция
без HINT-канала).
"""
from __future__ import annotations

import concurrent.futures as cf
import os
from decimal import Decimal
from pathlib import Path

from .io import read_jsonl, write_json, write_jsonl
from .llm import MODEL_STRONG, LLMStats
from .pairing import build_candidates, subject_concept
from .vocab import load_registry as load_vocab
from .verdicts import (judge_pairs, load_verdict_registry, pair_id,
                       preclassify, scope_relation_det, scope_signature,
                       verdict_key)

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "eval" / "seed_pairs.jsonl"
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _vectors(atoms: list[dict], staging: Path | None = None):
    """Эмбеддинги для VEC-канала; кэш npz по хэшу текстов; отказ -> None."""
    if os.environ.get("KDB_NO_EMBED"):
        return None
    try:
        import numpy as np

        from .canonical import jcs_sha256
        from .pairing import atom_text
        texts = [atom_text(a) for a in atoms]
        cache = None
        if staging is not None:
            key = jcs_sha256({"model": EMB_MODEL, "texts": texts})[:32]
            cache = staging / f"embeddings_{key}.npz"
            if cache.exists():
                return np.load(cache)["v"]
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=EMB_MODEL,
                              cache_dir=str(Path.home() / ".cache" / "fastembed"))
        vecs = np.array(list(model.embed(texts)), dtype="float32")
        if cache is not None:
            np.savez_compressed(cache, v=vecs)
        return vecs
    except Exception as e:  # noqa: BLE001 — деградация с явным warning
        print(f"WARNING: VEC-канал недоступен ({e}) — работаем без него")
        return None


def _judge_filter(a1, a2, channels, vocab_map) -> bool:
    if "HINT" in channels:
        return True
    qk1 = a1["claim"].get("quantity_kind")
    qk2 = a2["claim"].get("quantity_kind")
    same_subj = subject_concept(a1, vocab_map) == subject_concept(a2, vocab_map)
    if same_subj and qk1 == qk2:
        return True
    if "FP" in channels:
        return True
    if {"BM25", "VEC"} <= channels:
        return True
    if "SIBLING" in channels and qk1 == qk2:
        return True
    if "AUTH" in channels and qk1 == qk2:
        return True
    return False


def _parallel_judge(pairs_list, stats, budget_usd, model=None, workers=8):
    """Пилот последовательно (прогноз на ВЕСЬ объём + потолок), хвост — пулом.
    Реестр сохраняет только этот (единственный) writer — гонки снапшотов нет."""
    from .verdicts import (judge_pairs as _jp, load_verdict_registry,
                           save_verdict_registry)
    mk = {"model": model} if model else {}
    if len(pairs_list) <= 200 or os.environ.get("KDB_NO_LLM"):
        return _jp(pairs_list, stats, budget_usd=budget_usd, **mk)

    head, tail = pairs_list[:96], pairs_list[96:]
    cost_before = stats.cost_usd
    verdicts, rep = _jp(head, stats, budget_usd=budget_usd, save=False, **mk)
    head_cost = stats.cost_usd - cost_before
    if rep["llm_needed"]:
        per_pair = head_cost / max(rep["llm_needed"], 1)
        forecast = per_pair * len(pairs_list)
        rep["forecast_usd"] = round(forecast, 2)
        print(f"ПРОГНОЗ полного прогона ({len(pairs_list)} пар, "
              f"по пилоту {rep['llm_needed']} пар за ${head_cost:.3f}): "
              f"~${forecast:.2f}")
        if forecast > budget_usd:
            save_verdict_registry({**load_verdict_registry(), **verdicts})
            raise SystemExit(f"БЛОК: прогноз ${forecast:.2f} > бюджета "
                             f"${budget_usd} — эскалация владельцу")

    chunk = max(64, len(tail) // (workers * 4) or 64)
    chunks = [tail[i:i + chunk] for i in range(0, len(tail), chunk)]
    fails = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_jp, c, stats, budget_usd=1e9, save=False, **mk)
                for c in chunks]
        for f in cf.as_completed(futs):
            try:
                v, r = f.result()
                verdicts.update(v)
                rep["llm_done"] += r["llm_done"]
                rep["failed_batches"] += r["failed_batches"]
            except SystemExit:
                fails += 1
            except Exception as e:  # noqa: BLE001 — счётчик, не молчание
                fails += 1
                print(f"ОТКАЗ чанка судьи: {e}")
    if fails:
        rep["failed_chunks"] = fails
    reg = load_verdict_registry()
    reg.update(verdicts)
    save_verdict_registry(reg)
    return verdicts, rep


def _seed_pairs(atoms, by_rec, verdicts_reg, stats) -> list[dict]:
    """Seed: аудированные local hints + кросс-сегментные пары (verified terra)."""
    seeds = []
    seen = set()
    # 1) hints (record-level) -> представительная атом-пара
    for a in atoms:
        p = a["parent_record"]
        lpk = a["observation"]["logical_package_key"]
        rid = a["observation"]["record_id"]
        hints = [("HINT_DUP", p.get("local_duplicate_of"))] + \
                [("HINT_CONFLICT", t) for t in (p.get("local_conflicts_with") or [])]
        for kind, tgt in hints:
            if not tgt:
                continue
            key = (lpk, tuple(sorted([rid, tgt])), kind)
            if key in seen:
                continue
            seen.add(key)
            other = by_rec.get((lpk, tgt))
            if not other:
                continue
            seeds.append({"kind": kind,
                          "a_atom": a["atomic_claim_id"],
                          "b_atom": other[0]["atomic_claim_id"],
                          "a_record": f"{lpk}::{rid}",
                          "b_record": f"{lpk}::{tgt}",
                          "verified_by": "SOURCE_LOCAL_HINT"})
    # 2) кросс-сегментные: одинаковый subject-концепт+qk, близкие значения,
    #    РАЗНЫЕ сегменты одной главы
    vocab_map = load_vocab()
    cand = []
    by_seg: dict = {}
    for a in atoms:
        lpk = a["observation"]["logical_package_key"]
        ch = lpk.split("::")[1]
        nv = a.get("numeric_view") or {}
        if not str(nv.get("status", "")).startswith("OK") or not nv.get("value"):
            continue
        sc = subject_concept(a, vocab_map)
        if not sc:
            continue
        by_seg.setdefault((ch, sc, a["claim"].get("quantity_kind")),
                          []).append(a)
    for (ch, sc, qk), grp in sorted(by_seg.items()):
        segs = {g["observation"]["logical_package_key"] for g in grp}
        if len(segs) < 2:
            continue
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                g1, g2 = grp[i], grp[j]
                if g1["observation"]["logical_package_key"] == \
                        g2["observation"]["logical_package_key"]:
                    continue
                v1 = Decimal(g1["numeric_view"]["value"])
                v2 = Decimal(g2["numeric_view"]["value"])
                if v1 == 0 or abs(v1 - v2) / abs(v1) > Decimal("0.1"):
                    continue
                cand.append((g1, g2))
    cand = cand[:120]
    if cand:
        verdicts, _ = judge_pairs(cand, stats, budget_usd=10,
                                  model=MODEL_STRONG)
        for g1, g2 in cand:
            k = verdict_key(g1["atomic_claim_version_uid"],
                            g2["atomic_claim_version_uid"])
            v = verdicts.get(k)
            if v and v["same_question"] == "SAME":
                seeds.append({"kind": "CROSS_SEGMENT",
                              "a_atom": g1["atomic_claim_id"],
                              "b_atom": g2["atomic_claim_id"],
                              "a_record": g1["observation"]["logical_package_key"]
                              + "::" + g1["observation"]["record_id"],
                              "b_record": g2["observation"]["logical_package_key"]
                              + "::" + g2["observation"]["record_id"],
                              "verified_by": f"LLM:{MODEL_STRONG}"})
    return seeds


def run_phase5a(staging: Path) -> dict:
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    vocab_map = load_vocab()
    idx = {a["atomic_claim_id"]: i for i, a in enumerate(atoms)}
    by_rec: dict = {}
    for a in atoms:
        by_rec.setdefault((a["observation"]["logical_package_key"],
                           a["observation"]["record_id"]), []).append(a)

    vectors = _vectors(atoms, staging)
    pairs, gen_report = build_candidates(atoms, vocab_map, vectors)

    stats = LLMStats()
    det, llm_todo, skipped = {}, [], 0
    for (i, j), channels in sorted(pairs.items()):
        a1, a2 = atoms[i], atoms[j]
        v = preclassify(a1, a2)
        if v is not None:
            det[(i, j)] = v
        elif _judge_filter(a1, a2, channels, vocab_map):
            llm_todo.append((a1, a2))
        else:
            skipped += 1

    verdicts, judge_report = _parallel_judge(llm_todo, stats, budget_usd=60)

    # adversarial-проход terra: TRUE_CONFLICT и кросс-record дубли
    adv_pairs = []
    for a1, a2 in llm_todo:
        k = verdict_key(a1["atomic_claim_version_uid"],
                        a2["atomic_claim_version_uid"])
        v = verdicts.get(k)
        if not v or v.get("adversarial_checked"):
            continue
        cross = (a1["observation"]["record_id"] != a2["observation"]["record_id"]
                 or a1["observation"]["logical_package_key"]
                 != a2["observation"]["logical_package_key"])
        if v["relationship"] == "TRUE_CONFLICT" or \
                (cross and v["relationship"] in ("EXACT_DUPLICATE",
                                                 "SEMANTIC_DUPLICATE")
                 and v["scope_relation"] == "EQUIVALENT"):
            adv_pairs.append((a1, a2))
    adv_report = {"pairs": len(adv_pairs), "confirmed": 0, "downgraded": 0}
    if adv_pairs and not os.environ.get("KDB_NO_LLM"):
        # terra пере-судит; расхождение -> даунгрейд в REVIEW-статус
        from .verdicts import save_verdict_registry
        strong, _ = _parallel_judge(adv_pairs, stats, budget_usd=60,
                                    model=MODEL_STRONG)
        reg = load_verdict_registry()
        for a1, a2 in adv_pairs:
            k = verdict_key(a1["atomic_claim_version_uid"],
                            a2["atomic_claim_version_uid"])
            base, chal = verdicts.get(k), strong.get(k)
            if not base:
                continue
            if chal and chal["relationship"] == base["relationship"]:
                base["adversarial_checked"] = "CONFIRMED"
                adv_report["confirmed"] += 1
            else:
                base["adversarial_checked"] = "DOWNGRADED"
                base["relationship"] = ("POTENTIAL_CONFLICT"
                                        if base["relationship"] == "TRUE_CONFLICT"
                                        else "UNRESOLVED")
                base["review"] = "ADVERSARIAL_DISAGREEMENT"
                adv_report["downgraded"] += 1
            reg[k] = base
        save_verdict_registry(reg)

    # seed + recall-гейты
    seeds = _seed_pairs(atoms, by_rec, verdicts, stats)
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SEED_PATH.exists():  # frozen: не перезаписываем существующий
        write_jsonl(SEED_PATH, sorted(seeds, key=lambda s: (s["kind"],
                                                            s["a_atom"],
                                                            s["b_atom"])))
    seeds = read_jsonl(SEED_PATH)

    def _covered(pairs_dict, seed) -> bool:
        i, j = idx.get(seed["a_atom"]), idx.get(seed["b_atom"])
        if i is None or j is None:
            return False
        key = (i, j) if i < j else (j, i)
        if key in pairs_dict:
            return True
        # достаточно ЛЮБОЙ атом-пары между записями
        a_rec = tuple(seed["a_record"].rsplit("::", 1))
        b_rec = tuple(seed["b_record"].rsplit("::", 1))
        for x in by_rec.get((a_rec[0], a_rec[1]), []):
            for y in by_rec.get((b_rec[0], b_rec[1]), []):
                xi, yj = idx[x["atomic_claim_id"]], idx[y["atomic_claim_id"]]
                k2 = (xi, yj) if xi < yj else (yj, xi)
                if k2 in pairs_dict:
                    return True
        return False

    # аудит hints (нужен ДО recall: гейт меряется на verified POSITIVES)
    hint_audit = {"CONFIRMED": 0, "PARTIAL": 0, "REJECTED": 0, "UNRESOLVED": 0}
    reg_all = load_verdict_registry()
    seed_status: dict[int, str] = {}
    for si, s in enumerate(seeds):
        if not s["kind"].startswith("HINT"):
            seed_status[si] = "CROSS_SEGMENT_VERIFIED"
            continue
        a1 = atoms[idx[s["a_atom"]]]
        a2 = atoms[idx[s["b_atom"]]]
        k = verdict_key(a1["atomic_claim_version_uid"],
                        a2["atomic_claim_version_uid"])
        v = reg_all.get(k)
        if not v:
            cls = "UNRESOLVED"
        elif v["relationship"] in ("EXACT_DUPLICATE", "SEMANTIC_DUPLICATE",
                                   "TRUE_CONFLICT", "POTENTIAL_CONFLICT",
                                   "SCOPED_VARIANT",
                                   "SAME_PRIMARY_QUANTITY_WITH_EQUIVALENCY_DISCREPANCY"):
            cls = "CONFIRMED"
        elif v["relationship"] in ("COMPATIBLE_VARIANT", "COMPLEMENTARY",
                                   "RELATED_NOT_SAME"):
            cls = "PARTIAL"
        else:
            cls = "UNRESOLVED"
        hint_audit[cls] += 1
        seed_status[si] = cls

    # recall-гейты. Полный (с HINT-каналом) — по ВСЕМ seed-парам; абляция —
    # только по verified POSITIVES (спека: «verified positive regression
    # pairs»): CONFIRMED-хинты + cross-segment SAME. Отвергнутые аудитом
    # подсказки (RELATED_NOT_SAME/DIFFERENT) позитивами не являются —
    # их переоткрытие каналами не измеряет полноту.
    recall_full = sum(1 for s in seeds if _covered(pairs, s)) / max(len(seeds), 1)
    positives = [s for si, s in enumerate(seeds)
                 if seed_status[si] in ("CONFIRMED", "CROSS_SEGMENT_VERIFIED")]
    pairs_no_hint, _ = build_candidates(atoms, vocab_map, vectors)
    for key in [k for k, ch in pairs_no_hint.items() if ch == {"HINT"}]:
        del pairs_no_hint[key]
    recall_ablation = sum(1 for s in positives
                          if _covered(pairs_no_hint, s)) / max(len(positives), 1)

    if recall_full < 1.0:
        raise SystemExit(f"БЛОК: candidate_pair_recall {recall_full:.3f} < 100% "
                         "на seed-наборе")
    if recall_ablation < 0.95:
        raise SystemExit(f"БЛОК: ablation-recall {recall_ablation:.3f} < 95% "
                         f"на {len(positives)} verified-positive парах")

    # артефакт 04a
    rows = []
    for (i, j), channels in sorted(pairs.items()):
        a1, a2 = atoms[i], atoms[j]
        row = {"pair_id": pair_id(a1["atomic_claim_id"], a2["atomic_claim_id"]),
               "a": a1["atomic_claim_id"], "b": a2["atomic_claim_id"],
               "channels": sorted(channels)}
        if (i, j) in det:
            row.update({"verdict_status": "DETERMINISTIC", **det[(i, j)]})
        else:
            k = verdict_key(a1["atomic_claim_version_uid"],
                            a2["atomic_claim_version_uid"])
            v = reg_all.get(k)
            if v:
                row.update({"verdict_status": "LLM",
                            "same_question": v["same_question"],
                            "scope_relation": v["scope_relation"],
                            "relationship": v["relationship"],
                            "dependency": v["dependency"],
                            "dep_direction": v["dep_direction"],
                            "adversarial": v.get("adversarial_checked"),
                            "review": v.get("review")})
            else:
                row.update({"verdict_status": "UNRESOLVED_NOT_JUDGED",
                            "scope_relation": scope_relation_det(
                                scope_signature(a1), scope_signature(a2))})
        rows.append(row)
    rows.sort(key=lambda r: r["pair_id"])
    write_jsonl(staging / "04a_semantic_comparison_candidates.jsonl", rows)

    report = {
        "candidates": gen_report,
        "deterministic": len(det),
        "llm_judged": judge_report,
        "not_judged_low_signal": skipped,
        "adversarial": adv_report,
        "seed": {"total": len(seeds),
                 "hint": sum(1 for s in seeds if s["kind"].startswith("HINT")),
                 "cross_segment": sum(1 for s in seeds
                                      if s["kind"] == "CROSS_SEGMENT"),
                 "verified_positives": len(positives)},
        "recall_full": round(recall_full, 4),
        "recall_ablation_no_hint": round(recall_ablation, 4),
        "hint_audit": hint_audit,
        "llm": stats.as_dict(),
    }
    write_json(staging / "kb5a_report.json", report)
    return report
