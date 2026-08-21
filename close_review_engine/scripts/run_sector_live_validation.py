from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from ashare_review.calendar import last_completed_trading_day
from ashare_review.engine import build_live_source
from ashare_review.sector_runtime import build_sector_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="独立验证板块全景、成份广度、历史代理和2+2候选"
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--output", default="/tmp/sector-live-validation.json")
    parser.add_argument("--workers", type=int, default=6)
    return parser


def _minimal_market() -> dict[str, Any]:
    # Sector scoring only needs market median return. Using a neutral baseline
    # here deliberately avoids coupling this validation to the fixed 17-stock
    # market-environment fetch. Production still uses the real market summary.
    return {
        "indices": [],
        "total_amount": None,
        "breadth": {"up": 0, "down": 0, "flat": 0, "median_pct": 0.0},
        "industry_table": [],
        "source_status": [
            {
                "source": "板块独立验收中性市场基准",
                "ok": True,
                "note": "仅用于验收板块数据完整性，不替代正式市场环境数据",
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_date = args.as_of or last_completed_trading_day()
    source = build_live_source()
    sectors = build_sector_review(
        source,
        _minimal_market(),
        target_date=target_date,
        previous_snapshot=None,
        max_workers=max(1, min(args.workers, 8)),
    )
    payload = {
        "target_date": target_date.isoformat(),
        "validation_mode": "sector_only",
        "market_baseline": "neutral_validation_only",
        "sectors": sectors,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SECTOR_OUTPUT={output}")
    print(f"TARGET_DATE={target_date.isoformat()}")
    print(f"INDUSTRY_COUNT={len(sectors.get('industry_ranking', []))}")
    print(f"CONCEPT_COUNT={len(sectors.get('concept_ranking', []))}")
    print(f"DYNAMIC_COUNT={len(sectors.get('dynamic_candidates', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
