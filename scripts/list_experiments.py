#!/usr/bin/env python3
"""List local experiment records.

Usage:
    python scripts/list_experiments.py
    python scripts/list_experiments.py --storage data/experiments
    python scripts/list_experiments.py --status completed
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="List AQCS experiment records")
    parser.add_argument(
        "--storage",
        default="experiments",
        help="Experiment storage directory (default: experiments/)",
    )
    parser.add_argument(
        "--status",
        default=None,
        help="Filter by status: created | running | completed | failed | cancelled",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output as JSON lines",
    )
    args = parser.parse_args()

    storage_dir = Path(args.storage)
    if not storage_dir.is_dir():
        print(f"Storage directory not found: {storage_dir}")
        return

    files = sorted(storage_dir.rglob("experiment_*.json"))
    if not files:
        print(f"No experiments found in {storage_dir}")
        return

    records = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if args.status and data.get("status") != args.status:
                continue
            records.append(data)
        except Exception as exc:
            print(f"  [error reading {path.name}: {exc}]")

    if not records:
        print(f"No experiments matching status='{args.status}'")
        return

    if args.as_json:
        for r in records:
            print(json.dumps(r, default=str))
        return

    print(f"{'ID':<38}  {'Name':<30}  {'Status':<12}  {'Started':<24}")
    print("-" * 108)
    for r in records:
        eid = str(r.get("experiment_id", ""))[:36]
        name = r.get("experiment_name", "")[:30]
        status = r.get("status", "")[:12]
        started = str(r.get("timestamp_started_utc", ""))[:23]
        print(f"{eid:<38}  {name:<30}  {status:<12}  {started:<24}")

    print(f"\nTotal: {len(records)}")


if __name__ == "__main__":
    main()
