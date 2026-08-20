from __future__ import annotations

import argparse
import json
from datetime import date, time

from ashare_review.config import load_universe
from ashare_review.engine import build_live_source
from ashare_review.enhanced_data import fetch_sina_intraday_60m


def _intraday_complete(frame, target_date: date) -> bool:
    if frame.empty or len(frame) < 40:
        return False
    target_rows = frame[frame["date"].dt.date == target_date]
    if target_rows.empty:
        return False
    return target_rows["date"].max().time() >= time(15, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--stocks", type=int, default=1)
    parser.add_argument("--universe", default="config/universe.yml")
    parser.add_argument("--require-market", action="store_true")
    parser.add_argument("--require-daily", action="store_true")
    parser.add_argument("--require-60m", action="store_true")
    parser.add_argument("--require-sina-60m", action="store_true")
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
                "intraday_complete": _intraday_complete(
                    bundle.intraday_60m,
                    args.as_of,
                ),
                "last_intraday": None
                if bundle.intraday_60m.empty
                else str(bundle.intraday_60m["date"].max()),
                "confidence": bundle.data_confidence,
                "core_sources": bundle.core_sources,
                "source_status": bundle.source_status,
            }
        )

    sina_probe: dict | None = None
    if args.require_sina_60m:
        probe_stock = stocks[0]
        try:
            frame = fetch_sina_intraday_60m(
                source.client,
                probe_stock.symbol,
                target_date=args.as_of,
            )
            sina_probe = {
                "code": probe_stock.code,
                "rows": len(frame),
                "complete": _intraday_complete(frame, args.as_of),
                "last_intraday": None if frame.empty else str(frame["date"].max()),
                "source": "新浪60分钟",
            }
        except Exception as exc:  # noqa: BLE001
            sina_probe = {
                "code": probe_stock.code,
                "rows": 0,
                "complete": False,
                "source": "新浪60分钟",
                "error": f"{type(exc).__name__}: {exc}",
            }

    output = {"market": market, "stocks": rows, "sina_60m_probe": sina_probe}
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))

    errors: list[str] = []
    if args.require_market:
        breadth = market.get("breadth") or {}
        breadth_count = sum(int(breadth.get(key) or 0) for key in ("up", "down", "flat"))
        if len(market.get("indices") or []) < 3:
            errors.append("三大指数未完整返回")
        if market.get("total_amount") in (None, 0):
            errors.append("两市成交额未返回")
        if breadth_count < 3_000:
            errors.append(f"全市场涨跌家数样本不足：{breadth_count}")
        if not market.get("industry_table"):
            errors.append("行业强弱列表未返回")
    if args.require_daily:
        invalid = [row["code"] for row in rows if not row["valid_for_target"]]
        if invalid:
            errors.append(f"当日完整日线校验失败：{','.join(invalid)}")
    if args.require_60m:
        incomplete = [row["code"] for row in rows if not row["intraday_complete"]]
        if incomplete:
            errors.append(f"60分钟完成K线不足：{','.join(incomplete)}")
    if args.require_sina_60m and not (sina_probe or {}).get("complete"):
        errors.append("新浪60分钟强制探针未返回目标日15:00完成K线")
    if errors:
        print("LIVE_SMOKE_ERRORS=" + "；".join(errors))
        return 1
    print("LIVE_SMOKE_STATUS=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
