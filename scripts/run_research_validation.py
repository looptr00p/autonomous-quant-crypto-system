#!/usr/bin/env python3
"""Run one deterministic AQCS research validation from local Parquet."""

from __future__ import annotations

import argparse
from pathlib import Path

from aqcs.research import ResearchValidationConfig, run_research_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AQCS deterministic research validation")
    parser.add_argument("--parquet", required=True, help="Required local OHLCV Parquet path")
    parser.add_argument("--experiments-dir", default="experiments", help="Experiment storage dir")
    parser.add_argument(
        "--artifact-dir",
        default="experiments/artifacts",
        help="Artifact output dir",
    )
    parser.add_argument("--name", default="research_validation_baseline", help="Experiment name")
    parser.add_argument("--initial-capital", type=float, required=True)
    parser.add_argument("--fee-bps", type=float, required=True)
    parser.add_argument("--slippage-bps", type=float, required=True)
    parser.add_argument("--position-size-fraction", type=float, default=1.0)
    parser.add_argument("--momentum-window", type=int, default=20)
    parser.add_argument("--trend-short-window", type=int, default=20)
    parser.add_argument("--trend-long-window", type=int, default=50)
    parser.add_argument("--momentum-long-quantile", type=float, default=0.7)
    parser.add_argument("--momentum-short-quantile", type=float, default=0.3)
    parser.add_argument("--periods-per-year", type=int, default=252)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--config-path", default="")
    args = parser.parse_args()

    result = run_research_validation(
        ResearchValidationConfig(
            parquet_path=Path(args.parquet),
            experiment_storage_dir=Path(args.experiments_dir),
            artifact_dir=Path(args.artifact_dir),
            experiment_name=args.name,
            initial_capital=args.initial_capital,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            position_size_fraction=args.position_size_fraction,
            momentum_window=args.momentum_window,
            trend_short_window=args.trend_short_window,
            trend_long_window=args.trend_long_window,
            momentum_long_quantile=args.momentum_long_quantile,
            momentum_short_quantile=args.momentum_short_quantile,
            periods_per_year=args.periods_per_year,
            start_date=args.start_date,
            end_date=args.end_date,
            config_path=args.config_path,
        )
    )

    print(f"experiment_id={result.experiment.experiment_id}")
    print(f"status={result.experiment.status}")
    print(f"artifacts={len(result.artifacts)}")


if __name__ == "__main__":
    main()
