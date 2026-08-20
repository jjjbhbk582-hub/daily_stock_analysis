from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_review.config import load_universe
from ashare_review.engine import FixtureDataSource, run_review
from ashare_review.report import render_report
from ashare_review.storage import load_previous_snapshot, should_preserve, write_outputs

TARGET = date(2026, 8, 20)
TZ = ZoneInfo("Asia/Shanghai")


def build_snapshot(tmp_path: Path):
    stocks = load_universe("config/universe.yml")
    source = FixtureDataSource.from_path("config/review_fixture.yml")
    result = run_review(
        stocks,
        source,
        target_date=TARGET,
        generated_at=datetime(2026, 8, 20, 15, 30, tzinfo=TZ),
        max_workers=4,
    )
    assert result.snapshot is not None
    return result.snapshot


def test_fixture_pipeline_outputs_17_rows_and_top5(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    assert snapshot["status"] == "success"
    assert snapshot["valid_count"] == 17
    assert len(snapshot["stocks"]) == 17
    assert len(snapshot["top5"]) == 5
    assert [row["rank"] for row in snapshot["stocks"]] == list(range(1, 18))
    assert all(row["data_date"] == TARGET.isoformat() for row in snapshot["stocks"])
    assert all(row["rating"] in {"S", "A+", "A", "A-", "B+", "B", "C", "D"} for row in snapshot["stocks"])


def test_report_has_required_five_sections_and_levels(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    report = render_report(snapshot)
    for heading in (
        "第一部分：市场环境",
        "第二部分：17只股票完整排名",
        "第三部分：Top5重点分析",
        "第四部分：和上一次排名对比",
        "第五部分：买点变化提醒",
        "最终操作结论",
    ):
        assert heading in report
    assert report.count("最理想回踩买入区间") == 5
    assert report.count("放量突破买入触发价") == 5
    assert "不承诺收益" in report


def test_storage_writes_all_contract_outputs(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    report = render_report(snapshot)
    paths = write_outputs(tmp_path, snapshot, report)
    assert paths.snapshot.is_file()
    assert paths.ranking.is_file()
    assert paths.report.is_file()
    assert paths.latest.is_file()
    previous = load_previous_snapshot(tmp_path, before_date="2026-08-21")
    assert previous is not None
    assert previous["target_date"] == TARGET.isoformat()


def test_better_same_day_run_is_preserved(tmp_path: Path) -> None:
    snapshot = build_snapshot(tmp_path)
    worse = dict(snapshot)
    worse["valid_count"] = 12
    assert should_preserve(snapshot, worse)
    assert not should_preserve(worse, snapshot)
