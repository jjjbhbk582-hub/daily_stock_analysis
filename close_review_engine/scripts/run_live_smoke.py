from __future__ import annotations

import argparse
import json
from datetime import date

from ashare_review.config import load_universe
from ashare_review.engine import build_live_source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--stocks", type=int, default=1)
    parser.add_argument("--universe", default="config/universe.yml")
    parser.add_argument("--require-market", action="store_true")
    parser.add_argument("--require-60m", action="store_true")
    args = parser.parse_args()
    stocks = load_universe(args.universe)[: max(1, min(args.stocks, 17))]
    source = build_live_source()
    market = source.load_market(stocks, args.as_of)
    rows = []
    for stock in stocks:
        bundle = source.load_stock(stock, args.as_of)
        rows.append(
            {
                "code": stock.code,
                "valid_for_target": bundle.valid_for_target,
                "last_data_date": None
                if bundle.last_data_date is None
                else bundle.last_data_date.isoformat(),
                "daily_rows": len(bundle.daily),
                "intraday_rows": len(bundle.intraday_60m),
                "confidence": bundle.data_confidence,
                "core_sources": bundle.core_sources,
                "source_status": bundle.source_status,
            }
        )
    output = {"market": market, "stocks": rows}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))

    errors: list[str] = []
    if args.require_market:
        if len(market.get("indices") or []) < 3:
            errors.append("三大指数备用源未完整返回")
        if market.get("total_amount") in (None, 0):
            errors.append("两市成交额备用源未返回")
        if not market.get("breadth"):
            errors.append("全市场涨跌家数备用源未返回")
        if not market.get("industry_table"):
            errors.append("行业强弱备用源未返回")
    if args.require_60m:
        missing = [row["code"] for row in rows if int(row["intraday_rows"]) < 26]
        if missing:
            errors.append(f"60分钟数据不足：{','.join(missing)}")
    if errors:
        print("LIVE_SMOKE_ERRORS=" + "；".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
