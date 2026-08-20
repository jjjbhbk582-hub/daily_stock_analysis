from __future__ import annotations

import argparse
import json
from datetime import date

from ashare_review.config import load_universe
from ashare_review.data import HttpClient
from ashare_review.engine import build_live_source
from ashare_review.fallbacks import (
    fetch_sina_industries,
    fetch_sina_intraday,
    fetch_sina_market_spot,
    fetch_tencent_intraday,
    fetch_tencent_market_indices,
)


def _fallback_only(stocks, target_date: date) -> dict:
    client = HttpClient(timeout=10.0)
    source_status: list[dict] = []
    market: dict = {
        "data_date": target_date.isoformat(),
        "indices": [],
        "total_amount": None,
        "breadth": {},
        "industry_table": [],
        "source_status": source_status,
    }

    try:
        tencent = fetch_tencent_market_indices(client, target_date=target_date)
        market["indices"] = tencent.get("indices") or []
        market["total_amount"] = tencent.get("total_amount")
        source_status.append(
            {
                "source": "腾讯指数与两市成交额",
                "ok": len(market["indices"]) == 3 and market["total_amount"] not in (None, 0),
                "indices": len(market["indices"]),
            }
        )
    except Exception as exc:  # noqa: BLE001
        source_status.append(
            {"source": "腾讯指数与两市成交额", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    try:
        spot = fetch_sina_market_spot(client)
        valid = spot["pct_change"].dropna() if not spot.empty else None
        if valid is not None:
            if market["total_amount"] in (None, 0):
                market["total_amount"] = float(spot["amount"].fillna(0).sum())
            market["breadth"] = {
                "up": int((valid > 0).sum()),
                "down": int((valid < 0).sum()),
                "flat": int((valid == 0).sum()),
                "median_pct": float(valid.median()) if not valid.empty else None,
            }
        source_status.append(
            {"source": "新浪全市场行情", "ok": not spot.empty, "rows": len(spot)}
        )
    except Exception as exc:  # noqa: BLE001
        source_status.append(
            {"source": "新浪全市场行情", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    try:
        industries = fetch_sina_industries(client)
        market["industry_table"] = industries
        source_status.append(
            {"source": "新浪行业行情", "ok": bool(industries), "rows": len(industries)}
        )
    except Exception as exc:  # noqa: BLE001
        source_status.append(
            {"source": "新浪行业行情", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        )

    rows = []
    for stock in stocks:
        attempts: list[dict] = []
        chosen = None
        for source_name, loader in (
            (
                "腾讯60分钟",
                lambda symbol=stock.symbol: fetch_tencent_intraday(client, symbol, limit=320),
            ),
            (
                "新浪60分钟",
                lambda symbol=stock.symbol: fetch_sina_intraday(client, symbol, limit=1_970),
            ),
        ):
            try:
                intraday = loader()
                intraday = intraday[
                    intraday["date"].dt.date <= target_date
                ].reset_index(drop=True)
                usable = len(intraday) >= 26
                attempts.append(
                    {
                        "source": source_name,
                        "ok": usable,
                        "rows": len(intraday),
                        "last_intraday": None
                        if intraday.empty
                        else str(intraday["date"].max()),
                    }
                )
                if usable:
                    chosen = attempts[-1]
                    break
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    {
                        "source": source_name,
                        "ok": False,
                        "rows": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        selected = chosen or attempts[-1]
        rows.append(
            {
                "code": stock.code,
                "intraday_rows": int(selected.get("rows") or 0),
                "last_intraday": selected.get("last_intraday"),
                "source": selected.get("source"),
                "ok": bool(chosen),
                "attempts": attempts,
            }
        )
    return {"market": market, "stocks": rows}


def _integrated(stocks, target_date: date) -> dict:
    source = build_live_source()
    market = source.load_market(stocks, target_date)
    rows = []
    for stock in stocks:
        bundle = source.load_stock(stock, target_date)
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
    return {"market": market, "stocks": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--stocks", type=int, default=1)
    parser.add_argument("--universe", default="config/universe.yml")
    parser.add_argument("--require-market", action="store_true")
    parser.add_argument("--require-60m", action="store_true")
    parser.add_argument("--fallback-only", action="store_true")
    args = parser.parse_args()
    stocks = load_universe(args.universe)[: max(1, min(args.stocks, 17))]
    output = _fallback_only(stocks, args.as_of) if args.fallback_only else _integrated(stocks, args.as_of)
    market = output["market"]
    rows = output["stocks"]
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
