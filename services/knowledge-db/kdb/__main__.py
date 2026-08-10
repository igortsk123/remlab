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
    args = ap.parse_args(argv)

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
