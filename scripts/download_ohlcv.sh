#!/usr/bin/env bash
# download_ohlcv.sh — convenience wrapper around the OHLCV downloader
#
# Usage:
#   ./scripts/download_ohlcv.sh                          # defaults: BTC/USDT, 1d, 2023-01-01
#   ./scripts/download_ohlcv.sh ETH/USDT 4h 2024-01-01
#   AQCS_SYMBOLS="BTC/USDT ETH/USDT SOL/USDT" ./scripts/download_ohlcv.sh

set -euo pipefail

SYMBOLS="${AQCS_SYMBOLS:-BTC/USDT}"
TIMEFRAME="${2:-1d}"
START="${3:-2023-01-01}"
END="${4:-}"

END_FLAG=""
if [ -n "$END" ]; then
  END_FLAG="--end $END"
fi

for sym in $SYMBOLS; do
  echo "Downloading $sym $TIMEFRAME from $START..."
  python -m aqcs.data.ohlcv \
    --symbol "$sym" \
    --timeframe "$TIMEFRAME" \
    --start "$START" \
    $END_FLAG
done

echo "Done."
