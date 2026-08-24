from __future__ import annotations

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ashare_review.calendar import is_trading_day, market_is_closed
from ashare_review.config import load_universe
from ashare_review.engine import FixtureDataSource, build_live_source, run_review
from ashare_review.report import render_report
from ashare_review.storage import load_previous_snapshot, write_outputs

SHANGHAI = ZoneInfo("Asia/Shanghai")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="沪深A股固定股票池收盘复盘、评分与Top5买点变化引擎")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="执行一次收盘复盘")
    run.add_argument("--as-of", type=date.fromisoformat, help="目标日期YYYY-MM-DD；默认北京时间当天")
    run.add_argument("--universe", default="config/universe.yml")
    run.add_argument("--output-root", default=".")
    run.add_argument("--fixture", help="使用离线fixture进行确定性验收")
    run.add_argument("--force", action="store_true", help="跳过当前时钟限制；不会跳过交易日校验")
    run.add_argument("--no-write", action="store_true")
    run.add_argument("--workers", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(tz=SHANGHAI)
    target_date = args.as_of or now.date()
    if not is_trading_day(target_date):
        print("今日A股休市，不进行重新排名")
        return 0
    if target_date == now.date() and not args.force and not market_is_closed(now):
        print(f"A股尚未收盘；当前北京时间{now:%Y-%m-%d %H:%M:%S}，未使用未完成日线。")
        return 2
    stocks = load_universe(args.universe)
    source = FixtureDataSource.from_path(args.fixture) if args.fixture else build_live_source()
    previous = load_previous_snapshot(args.output_root, before_date=target_date.isoformat())
    result = run_review(
        stocks,
        source,
        target_date=target_date,
        generated_at=now,
        previous_snapshot=previous,
        max_workers=max(1, min(args.workers, 8)),
    )
    if result.snapshot is None:
        print(result.message)
        return 1
    report = render_report(result.snapshot)
    if args.no_write:
        print(report)
        return 0 if result.status in {"success", "partial"} else 1
    paths = write_outputs(args.output_root, result.snapshot, report)
    if paths.preserved_existing:
        report = paths.report.read_text(encoding="utf-8") if paths.report.is_file() else report
        print("PRESERVED_EXISTING_BETTER_RUN=true")
    print(f"REPORT_PATH={paths.report}")
    print(f"SNAPSHOT_PATH={paths.snapshot}")
    print(f"RANKING_PATH={paths.ranking}")
    print(f"STATUS={result.status}")
    print(f"VALID_COUNT={result.snapshot.get('valid_count')}")
    print(f"UNIVERSE_COUNT={result.snapshot.get('universe_count')}")
    print(report)
    return 0 if result.status in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
