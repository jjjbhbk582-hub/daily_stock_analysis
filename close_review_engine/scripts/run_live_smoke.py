from __future__ import annotations

import argparse
import json
from datetime import date

from ashare_review.config import load_universe
from ashare_review.data import LiveDataSource


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--stocks", type=int, default=1)
    parser.add_argument("--universe", default="config/universe.yml")
    args = parser.parse_args()
    universe = load_universe(args.universe)
    stocks = universe[: max(1, min(args.stocks, len(universe)))]
    source = LiveDataSource()
    market = source.load_market(stocks, args.as_of)
    rows = []
    for stock in stocks:
        bundle = source.load_stock(stock, args.as_of)
        rows.append(
            {
                "code": stock.code,
                "valid_for_target": bundle.valid_for_target,
                "last_data_date": None if bundle.last_data_date is None else bundle.last_data_date.isoformat(),
                "daily_rows": len(bundle.daily),
                "intraday_rows": len(bundle.intraday_60m),
                "confidence": bundle.data_confidence,
                "core_sources": bundle.core_sources,
                "source_status": bundle.source_status,
            }
        )
    print(json.dumps({"market": market, "stocks": rows}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
