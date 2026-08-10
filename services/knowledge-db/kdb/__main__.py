"""CLI: python -m kdb run --phase 0 [--run-id r20260810a]

Фазы идемпотентны; провал гейта = ненулевой exit code (стиль tools/memory-audit.mjs).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_ROOT = REPO_ROOT / "remlab_knowledge_db_v1"
DEFAULT_SOURCES = KB_ROOT / "sources" / "RID_MITTON_NYSTUEN_2016_3E"
DEFAULT_RUN_ID = "r20260810a"


def staging_dir(run_id: str) -> Path:
    return KB_ROOT / "runs" / f"{run_id}.staging"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kdb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--phase", required=True,
                     help="номер фазы: 0, 1, ... или диапазон 0-1")
    run.add_argument("--run-id", default=DEFAULT_RUN_ID)
    run.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    qp = sub.add_parser("query")
    qp.add_argument("--plane", choices=["A", "B", "C"], required=True)
    qp.add_argument("--context", default="{}",
                    help='JSON runtime-контекста, напр. {"room_type":"kitchen"}')
    qp.add_argument("--q", default="", help="текст запроса (PLANE B/C goals)")
    qp.add_argument("--run-id", default=DEFAULT_RUN_ID)
    args = ap.parse_args(argv)

    if args.cmd == "query":
        import json as _json

        from .query import KBQuery
        kq = KBQuery(staging_dir(args.run_id))
        ctx = _json.loads(args.context)
        if args.plane == "A":
            out = kq.plane_a(ctx)
            out = {"counts": out["counts"],
                   "routing_views": {k: v[:10] for k, v in
                                     out["routing_views"].items()}}
        elif args.plane == "B":
            out = kq.plane_b(args.q or "clearance", top_k=10)
        else:
            out = kq.plane_c(ctx, goals_query=args.q or None)
        print(_json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    phases = _parse_phases(args.phase)
    staging = staging_dir(args.run_id)
    for ph in phases:
        if ph == "0":
            from .phase0 import run_phase0
            m = run_phase0(args.sources, staging, args.run_id)
            print(f"phase0: пакетов {len(m['packages'])}, "
                  f"totals={m['corpus_totals']}, "
                  f"аномалий corpus={len(m['corpus_anomalies'])}")
        elif ph == "1":
            from .phase1 import run_phase1
            r = run_phase1(staging, args.sources)
            print(f"phase1: merged записей {r['gate']['records']}, гейт OK")
        elif ph == "2":
            from .phase2 import run_phase2
            s = run_phase2(staging)
            print(f"phase2: атомов {s['atomics_total']} "
                  f"(MB {s['measurement_bound']} + RS {s['record_semantic']}), "
                  f"коллизий слотов {s['slot_collision_groups']} "
                  f"(rate {s['collision_rate']})")
        elif ph == "3":
            import json as _json

            from .phase3 import run_phase3
            s = run_phase3(staging)
            print("phase3:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "4":
            import json as _json

            from .phase4 import run_phase4
            s = run_phase4(staging)
            print("phase4:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "5":
            import json as _json

            from .phase5a import run_phase5a
            s = run_phase5a(staging)
            print("phase5a:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "5b":
            import json as _json

            from .phase5b import run_phase5b
            s = run_phase5b(staging)
            print("phase5b:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "6":
            import json as _json

            from .phase6 import run_phase6
            s = run_phase6(staging)
            print("phase6:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "7":
            import json as _json

            from .phase7 import run_phase7
            s = run_phase7(staging)
            print("phase7:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph == "8":
            import json as _json

            from .phase8 import run_phase8
            s = run_phase8(staging)
            print("phase8:", _json.dumps(s, ensure_ascii=False, indent=1))
        elif ph in ("9", "9c"):
            import json as _json

            from .phase9 import run_phase9
            s = run_phase9(staging, args.sources, args.run_id,
                          commit=(ph == "9c"))
            print("phase9:", _json.dumps(s, ensure_ascii=False, indent=1))
        else:
            print(f"фаза {ph!r} ещё не реализована", file=sys.stderr)
            return 2
    return 0


def _parse_phases(spec: str) -> list[str]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return [str(i) for i in range(int(a), int(b) + 1)]
    return [spec]


if __name__ == "__main__":
    raise SystemExit(main())
